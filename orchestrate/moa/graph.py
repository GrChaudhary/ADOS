"""
MOA's ReAct-style reason/act loop for the HR domain pod — see
orchestrate/moa/__init__.py. Structurally mirrors
orchestrate/langgraph_agents/itsm_agent.py's reason ⇄ act LangGraph shape
(strict text-protocol tool selection, since knowledge/local_llm_client.py
is prompt-completion only with no native tool-calling API), but unlike
itsm_agent.py, this DOES reuse orchestrate/governance.py's
assign_policy_tier() per action — itsm_agent.py skipped it because its one
write action is a deterministic, always-ask-a-human chat action; MOA's HR
actions genuinely span three different tiers and proving that per-action
tiering works end-to-end is the whole point of this milestone.

Replay-safety note (verified against the installed langgraph==1.2.10):
LangGraph re-executes a node's Python code from the top on every resume
after an interrupt() inside that node. CascadeCircuitBreaker.
record_auto_approved()/record_human_decision() are real, non-idempotent
mutations, so each must only be reachable from a code path that runs
exactly once:
  - record_auto_approved() is called only inside the branch that never
    calls interrupt() at all — that whole branch runs exactly once, full
    stop, no replay possible.
  - record_human_decision() is called only in code AFTER a resumed
    interrupt() returns, which LangGraph guarantees runs exactly once per
    resume (the same guarantee itsm_agent.py's hub.invoke()-after-
    interrupt() already relies on).
Whether a would-be-autonomous action must instead be escalated is decided
by a pure read of cascade_breaker.state before branching — never a
speculative call-then-catch of CascadeBreakerOpen.

Tier-computation placement note: a paused node's local variables never
reach the LangGraph checkpoint, only the previous *completed* node's
return value does. So the tier shown in the pending-approval payload (and
RBAC-gated on by backend/app/routers/moa.py) is computed once in
reason_node and carried in state as proposed_action["policy_tier"] —
computing it inside act_node would be invisible to anything reading
graph.get_state() while paused. This preview is deliberately NOT
cascade-breaker-aware: cascade escalation can only ever move an AUTONOMOUS
action to APPROVAL_REQUIRED, never touch an EXECUTIVE_APPROVAL verdict, so
the one RBAC check that actually matters (the Tier-2 role gate) is never
fooled by that cosmetic gap.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations import IntegrationHub, default_hub
from integrations.capability_manifest import CapabilityManifestRegistry
from knowledge.local_llm_client import local_llm_client
from orchestrate.cascade_breaker import CascadeCircuitBreaker, CascadeState
from orchestrate.governance import assign_policy_tier

from .hr_domain import HR_ACTIONS
from .it_domain import IT_ACTIONS
from .finance_domain import FINANCE_ACTIONS
from .manufacturing_domain import MANUFACTURING_ACTIONS
from .dynamic_registry import dynamic_actions_for_all_domains, dynamic_actions_for_domain

MAX_ITERATIONS = 6

_ACTION_PATTERN = re.compile(r"^\s*ACTION:\s*(\S+)", re.IGNORECASE)
_ANSWER_PATTERN = re.compile(r"^\s*ANSWER:\s*(.+)", re.IGNORECASE | re.DOTALL)
# Permissive label-detector, not a strict "must be {...}" pattern: it only
# asks "is there an ARGS: line at all," so a malformed non-JSON payload
# after the label (e.g. "ARGS: [1,2,3]" or "ARGS: garbage") is still
# DETECTED and can be treated as malformed (hard fail) rather than
# silently read as "absent" — see reason_node's own two-phase detect-then-
# validate handling below.
_ARGS_PATTERN = re.compile(r"^\s*ARGS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

ALL_ACTIONS = {**HR_ACTIONS, **IT_ACTIONS, **FINANCE_ACTIONS, **MANUFACTURING_ACTIONS}


def _get_domain_actions(
    domain: Optional[str], manifests: Optional[CapabilityManifestRegistry] = None
) -> Dict[str, Any]:
    """manifests is optional (defaults to no dynamic actions merged in) so
    every existing call site that doesn't care about onboarded capabilities
    keeps working unchanged — only reason_node/act_node, which have a hub
    to read manifests off of, pass it."""
    dom = (domain or "hr").lower()
    if dom == "it":
        return {**IT_ACTIONS, **dynamic_actions_for_domain(dom, manifests)}
    elif dom == "finance":
        return {**FINANCE_ACTIONS, **dynamic_actions_for_domain(dom, manifests)}
    elif dom in ("mfg", "manufacturing"):
        return {**MANUFACTURING_ACTIONS, **dynamic_actions_for_domain(dom, manifests)}
    elif dom in ("cross-domain", "all", "multi"):
        return {**ALL_ACTIONS, **dynamic_actions_for_all_domains(manifests)}
    return {**HR_ACTIONS, **dynamic_actions_for_domain(dom, manifests)}


class MOAGraphState(TypedDict, total=False):
    task_id: str
    domain: str
    employee_name: str
    instruction: str
    transcript: List[str]
    tools_called: List[str]
    trajectory_log: List[Dict[str, Any]]
    next_action: Optional[str]  # "act:<action_key>" | "answer" | "give_up"
    proposed_action: Optional[Dict[str, Any]]
    approval_decision: Optional[str]
    approved_by: Optional[str]
    final_answer: Optional[str]
    model_used: Optional[str]
    status: str
    iteration: int


def _schema_hint(schema: Dict[str, Any]) -> str:
    """Compact per-action parameter hint appended to its prompt listing —
    e.g. ' (params: a integer required, b integer required)'. Empty string
    for an action with no schema/no properties (every built-in HR/IT/
    Finance/Manufacturing action today, and any onboarded action with no
    real parameters), so their listing is byte-for-byte unchanged from
    before this existed."""
    properties = (schema or {}).get("properties") or {}
    if not properties:
        return ""
    required = set((schema or {}).get("required") or [])
    parts = [f"{name} {(spec or {}).get('type', 'any')} {'required' if name in required else 'optional'}" for name, spec in properties.items()]
    return f" (params: {', '.join(parts)})"


def _actions_description(domain: Optional[str], manifests: Optional[CapabilityManifestRegistry] = None) -> str:
    actions = _get_domain_actions(domain, manifests)
    return "\n".join(
        f"- {key}: {action.description}{_schema_hint(getattr(action, 'input_schema', {}))}"
        for key, action in actions.items()
    )


def _build_prompt(state: MOAGraphState, manifests: Optional[CapabilityManifestRegistry] = None) -> str:
    domain = state.get("domain", "hr")
    transcript_text = "\n".join(state.get("transcript") or []) or "(nothing done yet)"
    target_name = state.get("employee_name") or "Target Entity"
    return (
        f"You are the ADOS Main Orchestrating Agent (MOA) for the {domain.upper()} domain pod.\n"
        f"Target/Subject: {target_name}\n"
        f"Instruction: {state['instruction']}\n\n"
        f"Available actions:\n{_actions_description(domain, manifests)}\n\n"
        f"So far:\n{transcript_text}\n\n"
        "Decide your NEXT single action based on the outcome above — do not plan "
        "the whole sequence up front. Respond in EXACTLY ONE of these formats, "
        "nothing else:\n"
        "ACTION: <action_key>\n"
        "ACTION: <action_key>\nARGS: <json object of the action's parameters>\n"
        "ANSWER: <final summary once the task is complete>\n"
        "Only use an action_key exactly as listed above. Never repeat an action "
        "already completed above. Only include ARGS when the action's listing "
        "above shows it takes parameters — ARGS must be a single-line JSON "
        "object using exactly those parameter names as keys."
    )


def _make_reason_node(hub: IntegrationHub):
    """A closure over hub, mirroring _make_act_node below — needed so the
    prompt and action-key lookup can see onboarded capabilities via
    hub.manifests (dynamic_registry.py), not just the four static domain
    dicts. Bare module-level `reason_node` never had a way to reach hub
    before this."""

    async def reason_node(state: MOAGraphState) -> MOAGraphState:
        if not local_llm_client.is_configured():
            return {**state, "status": "not_configured", "next_action": "give_up", "final_answer": None}

        prompt = _build_prompt(state, hub.manifests)
        result = await asyncio.to_thread(local_llm_client._generate_text, prompt, 400, 0.2)
        if result["status"] != "live_llm_generated":
            return {
                **state,
                "status": "error",
                "next_action": "give_up",
                "final_answer": None,
                "model_used": result.get("model_used"),
            }

        text = result["text"]
        answer_match = _ANSWER_PATTERN.match(text)
        action_match = _ACTION_PATTERN.match(text)
        trajectory_log = list(state.get("trajectory_log") or [])
        step_num = len(trajectory_log) + 1
        now_iso = datetime.now(timezone.utc).isoformat()

        if answer_match:
            trajectory_log.append({
                "step": step_num,
                "type": "answer",
                "thought": f"Final Answer: {answer_match.group(1).strip()}",
                "action": None,
                "capability": None,
                "policy_tier": 0,
                "status": "completed",
                "timestamp": now_iso,
            })
            return {
                **state,
                "trajectory_log": trajectory_log,
                "next_action": "answer",
                "final_answer": answer_match.group(1).strip(),
                "model_used": result["model_used"],
                "status": "ok",
            }

        if not action_match:
            # Unparseable — never silently guess which action was meant.
            return {
                **state,
                "status": "error",
                "next_action": "give_up",
                "final_answer": None,
                "model_used": result["model_used"],
            }

        action_key = action_match.group(1).strip().lower()
        actions = _get_domain_actions(state.get("domain"), hub.manifests)
        action = actions.get(action_key)
        if action is None:
            # Hallucinated/unrecognized action — same hard-failure rule.
            return {
                **state,
                "status": "error",
                "next_action": "give_up",
                "final_answer": None,
                "model_used": result["model_used"],
            }

        # Two-phase ARGS handling, detection separate from validation: a
        # regex that required literal `{...}` to even match would silently
        # read "ARGS: [1,2,3]" or "ARGS: garbage" as ABSENT rather than
        # MALFORMED — exactly the silent-empty-args failure mode this
        # exists to close. Malformed ARGS is always a hard fail if present
        # at all, matching the existing ACTION/ANSWER "never guess"
        # convention; its ABSENCE is only fine when nothing was required.
        action_schema = getattr(action, "input_schema", {}) or {}
        args_match = _ARGS_PATTERN.search(text)
        arguments: Dict[str, Any] = {}
        if args_match is not None:
            try:
                parsed = json.loads(args_match.group(1).strip())
            except json.JSONDecodeError:
                parsed = None
            if not isinstance(parsed, dict):
                return {
                    **state, "status": "error", "next_action": "give_up",
                    "final_answer": None, "model_used": result["model_used"],
                }
            arguments = parsed
        if _missing_required_params(action_schema, arguments):
            return {
                **state, "status": "error", "next_action": "give_up",
                "final_answer": None, "model_used": result["model_used"],
            }

        tier = _effective_policy_tier(action, hub.manifests, confidence=1.0)
        target_name = state.get("employee_name") or "Target Entity"

        trajectory_log.append({
            "step": step_num,
            "type": "action",
            "thought": text,
            "action": action.key,
            "capability": action.capability.value,
            "policy_tier": tier.value,
            "status": "proposed",
            "timestamp": now_iso,
        })

        return {
            **state,
            "trajectory_log": trajectory_log,
            "next_action": f"act:{action_key}",
            "proposed_action": {
                "action_key": action.key,
                "capability": action.capability.value,
                "summary": f"{action.description} — {target_name}",
                "estimated_cost_usd": action.estimated_cost_usd,
                "policy_tier": tier.value,
                "arguments": arguments,
                # Surfaced so a human reviewing this pause can see/edit the
                # LLM-chosen arguments before approving (resume_moa_task's
                # edited_arguments) rather than only ever running exactly
                # what the model proposed — the same schema reason_node
                # itself validated `arguments` against, above.
                "input_schema": action_schema,
            },
            "model_used": result["model_used"],
        }

    return reason_node


def _effective_policy_tier(action: Any, manifests: Optional[CapabilityManifestRegistry], confidence: float) -> PolicyTier:
    """The real per-call governance verdict. Checks a capability-id-keyed
    admin calibration (CapabilityManifestRegistry.calibrate_tier()) before
    falling back to assign_policy_tier()'s Capability-enum-keyed static
    table. Only ever relevant for a DYNAMIC_CAPABILITY action —
    action.capability_id only exists on DynamicAction (see
    dynamic_registry.py); static HR/IT/Finance/Manufacturing actions each
    have their own real Capability enum member already, so their tier is
    already correctly per-capability via CAPABILITY_RISK_CLASS and
    calibration doesn't apply to them.

    Called identically from reason_node (the preview a human sees before
    approving) and act_node (the tier actually enforced) — this module's
    own "Tier-computation placement note" above already flags why those
    two must never diverge; routing both through one function is what
    keeps that true as this file changes."""
    capability_id = getattr(action, "capability_id", None)
    if capability_id and manifests is not None:
        manifest = manifests.manifest_for(capability_id)
        if manifest is not None and manifest.tier_override is not None:
            return manifest.tier_override
    return assign_policy_tier(action.capability, confidence=confidence, estimated_cost_usd=action.estimated_cost_usd)


def _missing_required_params(schema: Dict[str, Any], arguments: Dict[str, Any]) -> set:
    """Shared by reason_node's own ARGS: validation and resume_moa_task's
    human-edited-arguments validation below — one definition of "valid
    arguments for this action" rather than two that could drift apart."""
    required = set((schema or {}).get("required") or [])
    return required - arguments.keys()


def _action_input(state: MOAGraphState, action: Any, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Threads the real onboarded capability_id through for dynamic actions
    (action.capability is Capability.DYNAMIC_CAPABILITY) so
    DynamicCapabilityConnector.execute() can dispatch it — see
    integrations/connectors/dynamic.py. Static domain actions
    (HRAction/ITAction/etc.) never have this attribute, hence the
    capability-first check rather than getattr-with-default.

    arguments (parsed by reason_node from an LLM-supplied ARGS: line, see
    the module's _ARGS_PATTERN) are merged in FLAT, not nested under an
    "arguments" key — runtime_registry._filter_to_tool_arguments matches
    real parameter names against input_schema["properties"] at the top
    level of CapabilityCall.input directly, so a flat merge is the only
    shape that already works with zero changes to that function."""
    payload = {"employee_name": state["employee_name"], "action": action.key}
    if action.capability is Capability.DYNAMIC_CAPABILITY:
        payload["capability_id"] = action.capability_id
    if arguments:
        payload.update(arguments)
    return payload


def _make_act_node(hub: IntegrationHub, cascade_breaker: CascadeCircuitBreaker):
    async def act_node(state: MOAGraphState) -> MOAGraphState:
        proposed = state["proposed_action"]
        actions = _get_domain_actions(state.get("domain"), hub.manifests)
        action = actions[proposed["action_key"]]
        transcript = list(state.get("transcript") or [])
        tools_called = list(state.get("tools_called") or [])
        iteration = state.get("iteration", 0) + 1
        summary = proposed["summary"]
        target_name = state.get("employee_name") or "Target Entity"

        raw_tier = _effective_policy_tier(action, hub.manifests, confidence=1.0)
        cascade_open = cascade_breaker.state is CascadeState.OPEN  # pure read — safe to repeat on replay

        if raw_tier == PolicyTier.AUTONOMOUS and not cascade_open:
            # No interrupt() anywhere in this branch — runs exactly once per
            # real action, so this real mutation can never double-fire.
            cascade_breaker.record_auto_approved(action.capability.value, summary)
            call = CapabilityCall(
                capability=action.capability,
                incident_id=state["task_id"],
                requested_by="moa-hr-agent",
                input=_action_input(state, action, proposed.get("arguments")),
                governance=GovernanceInfo(policy_tier=raw_tier, approved_by=None),
            )
            response = await hub.invoke(call)
            tools_called.append(action.key)
            transcript.append(
                f"ACTION {action.key} AUTO-EXECUTED via {response.connector}: {response.output}"
                if response.status == CallStatus.SUCCEEDED
                else f"ACTION {action.key} FAILED via {response.connector}: {response.error}"
            )
            return {**state, "transcript": transcript, "tools_called": tools_called, "iteration": iteration}

        # Requires a human — either genuinely (tier != AUTONOMOUS) or because
        # the cascade breaker is already OPEN and this would-be-autonomous
        # action must be escalated instead. interrupt() must be the first
        # side-effecting statement from here down — see module docstring.
        escalated_tier = raw_tier if raw_tier != PolicyTier.AUTONOMOUS else PolicyTier.APPROVAL_REQUIRED
        decision = interrupt(
            {
                "proposed_action": {**proposed, "policy_tier": escalated_tier.value},
                "message": f"HR action '{action.key}' requires {escalated_tier.name} — approve to execute.",
            }
        )

        # Everything below here runs exactly once per resume.
        cascade_breaker.record_human_decision()
        if decision.get("decision") != "approved":
            transcript.append(f"ACTION {action.key} REJECTED: {summary}")
            return {
                **state,
                "transcript": transcript,
                "approval_decision": decision.get("decision"),
                "approved_by": decision.get("approved_by"),
                "iteration": iteration,
            }

        # edited_arguments (already validated against proposed["input_schema"]
        # in resume_moa_task BEFORE this resume was ever sent in — see that
        # function's docstring for why validation must happen there and not
        # here) fully replaces the LLM's own proposed arguments when a human
        # supplied one; None (the common case: approved as-is) falls back to
        # what the LLM originally proposed.
        edited_arguments = decision.get("edited_arguments")
        arguments = edited_arguments if edited_arguments is not None else proposed.get("arguments")

        call = CapabilityCall(
            capability=action.capability,
            incident_id=state["task_id"],
            requested_by="moa-hr-agent",
            input=_action_input(state, action, arguments),
            governance=GovernanceInfo(policy_tier=escalated_tier, approved_by=decision.get("approved_by")),
        )
        response = await hub.invoke(call)
        tools_called.append(action.key)
        transcript.append(
            f"ACTION {action.key} SUCCEEDED via {response.connector}: {response.output}"
            if response.status == CallStatus.SUCCEEDED
            else f"ACTION {action.key} FAILED via {response.connector}: {response.error}"
        )
        return {
            **state,
            "transcript": transcript,
            "tools_called": tools_called,
            "approval_decision": decision.get("decision"),
            "approved_by": decision.get("approved_by"),
            "iteration": iteration,
        }

    return act_node


def route_after_reason(state: MOAGraphState) -> str:
    next_action = state.get("next_action", "")
    if state.get("iteration", 0) >= MAX_ITERATIONS and next_action.startswith("act:"):
        return "max_iterations"
    if next_action == "answer":
        return "end"
    if next_action.startswith("act:"):
        return "act"
    return "end"  # give_up — not_configured or error, already terminal


def build_graph(
    hub: Optional[IntegrationHub] = None,
    cascade_breaker: Optional[CascadeCircuitBreaker] = None,
    checkpointer=None,
):
    """checkpointer defaults to a fresh InMemorySaver, which is right for
    tests and for any single-process use: the graph itself is pure structure,
    so what makes a paused task durable is entirely which saver it compiles
    against. The app passes db/checkpointer.py's AsyncPostgresSaver instead
    (backend/app/routers/moa.py), which is what lets a task be resumed by a
    process that never ran it.

    Note that a *fresh* InMemorySaver means a rebuilt graph starts with no
    history — so anything that rebuilds and expects to resume must hand the
    same saver back in. That is not a concern for the Postgres saver, where
    the state lives in the database rather than in the object."""
    hub = hub if hub is not None else default_hub()
    cascade_breaker = cascade_breaker if cascade_breaker is not None else CascadeCircuitBreaker()
    checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    builder = StateGraph(MOAGraphState)
    builder.add_node("reason", _make_reason_node(hub))
    builder.add_node("act", _make_act_node(hub, cascade_breaker))

    builder.add_edge(START, "reason")
    builder.add_conditional_edges(
        "reason",
        route_after_reason,
        {"act": "act", "end": END, "max_iterations": END},
    )
    builder.add_edge("act", "reason")

    return builder.compile(checkpointer=checkpointer)


async def run_moa_task(
    employee_name: str,
    instruction: str,
    domain: str = "hr",
    hub: Optional[IntegrationHub] = None,
    task_id: Optional[str] = None,
    cascade_breaker: Optional[CascadeCircuitBreaker] = None,
    checkpointer=None,
):
    """Returns (result, graph, config). result is None when the graph
    paused on a proposed-action interrupt — call resume_moa_task() with the
    task_id and the human's decision to continue.

    The returned graph is a convenience for the caller that just ran the
    task; it is deliberately NOT required to resume, because the process that
    resumes may not be the one that started it."""
    task_id = task_id or str(uuid.uuid4())
    cascade_breaker = cascade_breaker if cascade_breaker is not None else CascadeCircuitBreaker()
    graph = build_graph(hub, cascade_breaker, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": task_id}}
    initial: MOAGraphState = {
        "task_id": task_id,
        "domain": domain,
        "employee_name": employee_name,
        "instruction": instruction,
        "transcript": [],
        "tools_called": [],
        "iteration": 0,
    }
    result = await graph.ainvoke(initial, config=config)
    if "__interrupt__" in result:
        return None, graph, config
    if result.get("iteration", 0) >= MAX_ITERATIONS and result.get("status") != "ok":
        result = {**result, "status": "max_iterations_exceeded", "final_answer": None}
    return result, graph, config


async def resume_moa_task(
    task_id: str,
    decision: str,
    approved_by: Optional[str] = None,
    edited_arguments: Optional[Dict[str, Any]] = None,
    hub: Optional[IntegrationHub] = None,
    cascade_breaker: Optional[CascadeCircuitBreaker] = None,
    checkpointer=None,
):
    """Resumes a paused task by id, rebuilding the graph rather than being
    handed the original object. That is the whole point: compiling a graph is
    cheap and deterministic, so the only thing a resuming process actually
    needs is the task_id plus a checkpointer pointing at the same storage.
    Previously this took the live `graph` object, which meant only the exact
    process that started a task could finish it.

    cascade_breaker must be the task's RESTORED breaker
    (backend/app/moa_breaker_store.py), not a fresh one — passing a new
    instance would reset the auto-approval streak that vision §5.3 exists to
    count, without any visible symptom.

    decision: "approved" | "rejected". edited_arguments, when given,
    lets a human override the LLM's own proposed_action["arguments"]
    before the action actually executes (e.g. correcting a wrong value the
    model picked) — validated HERE, against proposed_action["input_schema"],
    before the resume is ever sent into the graph, deliberately not inside
    act_node itself. Raises ValueError on an invalid edit — the caller
    (backend/app/routers/moa.py) turns that into a clean 4xx and leaves the
    task exactly as paused as it was, so a bad edit costs nothing but a
    retry. This ordering matters for a reason beyond tidiness: LangGraph
    re-executes a resumed node's code from the top (see this module's own
    docstring), and act_node's post-interrupt() code is only guaranteed to
    run exactly once per resume — raising partway through it on bad input
    would be new, unproven territory for that guarantee. Validating before
    graph.ainvoke() is ever called means an invalid edit never reaches
    act_node at all, so that guarantee is never tested by this path.

    Only validated when decision == "approved" — a rejected action never
    builds a CapabilityCall at all (see act_node), so there's nothing for
    an incomplete/malformed edited_arguments to be wrong about; validating
    it anyway would block a plain rejection for a reason that has nothing
    to do with rejecting."""
    graph = build_graph(hub, cascade_breaker, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": task_id}}

    if edited_arguments is not None and decision == "approved":
        if not isinstance(edited_arguments, dict):
            raise ValueError("edited_arguments must be a JSON object")
        # aget_state, not get_state: an async checkpointer rejects synchronous
        # calls from the running loop outright (InvalidStateError), so the sync
        # form would work in tests against InMemorySaver and fail in production
        # at the moment a human clicked approve.
        proposed = (await graph.aget_state(config)).values.get("proposed_action") or {}
        missing = _missing_required_params(proposed.get("input_schema") or {}, edited_arguments)
        if missing:
            raise ValueError(f"edited_arguments is missing required parameter(s): {sorted(missing)}")

    resume_payload: Dict[str, Any] = {"decision": decision, "approved_by": approved_by}
    if edited_arguments is not None:
        resume_payload["edited_arguments"] = edited_arguments

    result = await graph.ainvoke(Command(resume=resume_payload), config=config)
    if "__interrupt__" in result:
        return None, graph, config
    if result.get("iteration", 0) >= MAX_ITERATIONS and result.get("status") != "ok":
        result = {**result, "status": "max_iterations_exceeded", "final_answer": None}
    return result, graph, config
