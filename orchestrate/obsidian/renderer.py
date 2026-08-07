"""
Markdown and Native Obsidian Canvas (.canvas) rendering engine for ADOS Obsidian Projection Layer.
Generates Dataview-compatible Markdown notes with YAML frontmatter, [[WikiLinks]], and Mermaid diagrams.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from contracts.obsidian import ObsidianCanvasData, ObsidianCanvasEdge, ObsidianCanvasNode


def domain_pod_name(domain: str) -> str:
    """Canonical pod note title for a domain key.

    Has to match the reconciler's DOMAIN_POD_SPECS keys exactly ("HR Domain
    Pod", not "Hr Domain Pod") or every [[WikiLink]] built from it resolves
    to nothing and the graph view shows orphans.
    """
    key = (domain or "").strip()
    if key.lower() in ("hr", "it"):
        return f"{key.upper()} Domain Pod"
    return f"{key.capitalize()} Domain Pod"


def render_yaml_frontmatter(metadata: Dict[str, Any]) -> str:
    """Formats a dict into YAML frontmatter lines."""
    lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(json.dumps(x) for x in v)}]")
        elif isinstance(v, (dict, bool, int, float)):
            lines.append(f"{k}: {json.dumps(v)}")
        elif v is None:
            lines.append(f"{k}: null")
        else:
            lines.append(f"{k}: {json.dumps(str(v))}")
    lines.append("---")
    return "\n".join(lines)


def render_moa_root_note(domain_pods: List[str], cascades: List[Dict[str, Any]]) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "moa_root",
        "id": "moa-orchestrator",
        "title": "Main Orchestrating Agent (MOA)",
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/core", "ados/moa", "orchestration/root"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    pod_links = "\n".join(f"- [[{pod}]]" for pod in domain_pods)
    cascade_links = "\n".join(f"- [[{c['name']}]] — {c['description']}" for c in cascades)

    return f"""{frontmatter}

# Main Orchestrating Agent (MOA)

The **Main Orchestrating Agent (MOA)** is the multi-domain reasoning core of the ADOS platform (`orchestrate/moa/graph.py`).
It executes dynamic ReAct planning loops (`reason ⇄ act`), assigning action-level governance policy tiers.

## Active Domain Pods
{pod_links}

## Cross-Domain Multi-Pod Cascades
{cascade_links}

## Architecture Properties
- **Engine**: LangGraph StateGraph (`MOAGraphState`)
- **Safety Gate**: [[CascadeCircuitBreaker]] per-task execution
- **Governance Engine**: Action-level policy tiering (Tier 0 / Tier 1 / Tier 2)
- **Event Bus Substrate**: Apache Kafka (`EventEnvelope` v2)
"""


def render_domain_pod_note(
    pod_name: str,
    description: str,
    actions: Dict[str, Any],
    default_risk_tier: str = "Tier 1 Manager Approval",
) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "domain_pod",
        "id": pod_name.lower().replace(" ", "_"),
        "title": pod_name,
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/domain_pod", f"domain/{pod_name.split()[0].lower()}"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    capability_links = []
    for action_key, action_obj in actions.items():
        cap_name = getattr(action_obj, "capability", None)
        cap_str = cap_name.value if hasattr(cap_name, "value") else str(action_key)
        desc = getattr(action_obj, "description", "(No description)")
        capability_links.append(f"- [[{cap_str}]] — `{action_key}`: {desc}")

    cap_list_text = "\n".join(capability_links) if capability_links else "- (No capabilities registered yet)"

    return f"""{frontmatter}

# {pod_name}

**Description**: {description}  
**Parent System**: [[Main Orchestrating Agent (MOA)]]  
**Default Risk Tier**: {default_risk_tier}  

## Member Capabilities
{cap_list_text}

## Governance Profile
- **Tier 0 (Autonomous)**: Low risk, < $25,000 cost exposure
- **Tier 1 (Manager Approval)**: Medium risk, $25,000 – $250,000 cost exposure
- **Tier 2 (Executive Approval)**: High risk or > $250,000 cost exposure
"""


def render_capability_note(
    capability_id: str,
    domain: str,
    action_key: str,
    description: str,
    risk_class: str = "MEDIUM",
    estimated_cost_usd: float = 0.0,
    status: str = "ACTIVE",
    source: str = "built-in",
    sandbox_evidence: Optional[str] = None,
) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "capability",
        "id": capability_id,
        "title": f"Capability: {capability_id}",
        "domain": domain,
        "status": status,
        "risk_class": risk_class,
        "estimated_cost_usd": estimated_cost_usd,
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/capability", f"domain/{domain}", f"risk/{risk_class.lower()}"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    pod_link = domain_pod_name(domain)

    return f"""{frontmatter}

# Capability: {capability_id}

- **Action Key**: `{action_key}`
- **Domain Pod**: [[{pod_link}]]
- **Status**: `{status}`
- **Risk Class**: `{risk_class.upper()}`
- **Estimated Cost Exposure**: `${estimated_cost_usd:,.2f}` USD
- **Source**: `{source}`
- **Parent System**: [[Main Orchestrating Agent (MOA)]]

## Description
{description}

## Sandbox Evidence & Lineage
{sandbox_evidence or "Validated in sandbox environment prior to execution."}

## Governance & Safety
Executions are evaluated against `orchestrate/governance.py`'s `assign_policy_tier()`.
"""


def render_task_note(
    task_id: str,
    domain: str,
    employee_name: str,
    instruction: str,
    status: str,
    trajectory_log: Optional[List[Dict[str, Any]]] = None,
    proposed_action: Optional[Dict[str, Any]] = None,
    answer: Optional[str] = None,
    model_used: Optional[str] = None,
) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    tier = proposed_action.get("policy_tier", 1) if proposed_action else 0
    meta = {
        "type": "live_task",
        "id": task_id,
        "title": f"Task: {task_id[:8]}",
        "domain": domain,
        "status": status,
        "policy_tier": tier,
        "target_entity": employee_name,
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/task", f"domain/{domain}", f"status/{status}"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    pod_link = domain_pod_name(domain)

    trajectory_items = []
    mermaid_steps = []
    if trajectory_log:
        for idx, step in enumerate(trajectory_log, start=1):
            thought = step.get("thought", "")
            action = step.get("action") or step.get("capability") or "Reasoning"
            step_status = step.get("status", "ok")
            step_tier = step.get("policy_tier", 0)

            tier_link = f"[[Tier {step_tier} Approval]]" if step_tier > 0 else "[[Tier 0 Autonomous]]"
            trajectory_items.append(
                f"### Step {idx} — {action}\n"
                f"> {thought}\n"
                f"- **Capability**: [[{action}]]\n"
                f"- **Governance**: {tier_link}\n"
                f"- **Status**: `{step_status}`"
            )
            mermaid_steps.append(f'    Task --> S{idx}["Step {idx}: {action}"]')

    trajectory_text = "\n\n".join(trajectory_items) if trajectory_items else "*No ReAct steps logged yet.*"
    mermaid_block = "\n".join(mermaid_steps) if mermaid_steps else '    Task --> Run["Executing Task"]'

    proposed_block = ""
    if proposed_action and status == "pending_approval":
        proposed_block = f"""
## ⚠️ Held Action Pending Governance Sign-Off
- **Action**: [[{proposed_action.get('capability', proposed_action.get('action_key'))}]]
- **Summary**: {proposed_action.get('summary')}
- **Cost Exposure**: `${proposed_action.get('estimated_cost_usd', 0):,.2f}` USD
- **Governance Tier**: [[Tier {tier} Approval]]
"""

    answer_block = ""
    if answer:
        answer_block = f"""
## Final MOA Answer
{answer}
"""

    return f"""{frontmatter}

# Task: {instruction[:60]}...

- **Task ID**: `{task_id}`
- **Domain Pod**: [[{pod_link}]]
- **Target Entity**: [[{employee_name}]]
- **Status**: `{status.upper()}`
- **LLM Model**: `{model_used or "Local NEMOTRON"}`

{proposed_block}

## ReAct Execution Trajectory
{trajectory_text}

{answer_block}

## ReAct Execution Topology
```mermaid
graph TD
    Task["Task: {instruction[:30]}..."]
{mermaid_block}
```
"""


def render_decision_note(
    decision_id: str,
    task_id: str,
    action_key: str,
    capability_id: str,
    tier: int,
    cost_usd: float,
    decision: str,
    actor: str,
    reasoning: str,
    prev_hash: Optional[str] = None,
    curr_hash: Optional[str] = None,
) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "decision_ledger",
        "id": decision_id,
        "title": f"Decision: {decision_id}",
        "task_id": task_id,
        "capability": capability_id,
        "policy_tier": tier,
        "actor": actor,
        "decision": decision,
        "cost_usd": cost_usd,
        "prev_hash": prev_hash or "0" * 64,
        "curr_hash": curr_hash or "0" * 64,
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/audit", "ados/decision", f"decision/{decision.lower()}"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    tier_note = f"[[Tier {tier} Approval]]"

    return f"""{frontmatter}

# Decision Audit Record: {decision_id}

- **Decision ID**: `{decision_id}`
- **Task Reference**: [[Task-{task_id[:8]}]] (Full ID: `{task_id}`)
- **Capability Invoked**: [[{capability_id}]]
- **Action Key**: `{action_key}`
- **Governance Tier**: {tier_note}
- **Decision Outcome**: `{decision.upper()}`
- **Acting Reviewer / Actor**: [[{actor}]]
- **Cost Exposure**: `${cost_usd:,.2f}` USD

## Reasoning & Justification
{reasoning}

## Tamper-Evident Ledger Hashes
- **Previous Record Hash**: `{prev_hash or ("0" * 64)}`
- **Current Audit Hash**: `{curr_hash or ("0" * 64)}`
"""


def render_cascade_canvas(cascade_title: str, steps: List[str]) -> str:
    """Renders a native Obsidian .canvas JSON string."""
    nodes = []
    edges = []

    # Title node
    nodes.append(
        ObsidianCanvasNode(
            id="node-title",
            type="text",
            text=f"# {cascade_title}\n\nMulti-pod cross-domain cascading workflow.",
            x=0,
            y=0,
            width=300,
            height=120,
            color="6",  # purple
        )
    )

    y_offset = 180
    prev_node_id = "node-title"

    for idx, step_text in enumerate(steps, start=1):
        node_id = f"node-step-{idx}"
        nodes.append(
            ObsidianCanvasNode(
                id=node_id,
                type="text",
                text=f"### Step {idx}\n{step_text}",
                x=0,
                y=y_offset,
                width=280,
                height=100,
                color="4" if "Tier 0" in step_text else "2" if "Tier 1" in step_text else "1",
            )
        )
        edges.append(
            ObsidianCanvasEdge(
                id=f"edge-{idx}",
                fromNode=prev_node_id,
                fromSide="bottom",
                toNode=node_id,
                toSide="top",
            )
        )
        prev_node_id = node_id
        y_offset += 160

    canvas_data = ObsidianCanvasData(nodes=nodes, edges=edges)
    return json.dumps(canvas_data.model_dump(), indent=2)


def render_cascade_note(cascade: Dict[str, Any]) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "cascade",
        "id": cascade["name"].lower().replace(" ", "_"),
        "title": cascade["name"],
        "created_at": now_iso,
        "updated_at": now_iso,
        "tags": ["ados/cascade", "orchestration/cascade"],
    }
    frontmatter = render_yaml_frontmatter(meta)

    pod_links = [f"- [[{pod}]]" for pod in cascade["pods"]]
    step_links = [f"{idx+1}. {step}" for idx, step in enumerate(cascade["steps"])]

    return f"""{frontmatter}

# Cross-Domain Cascade: {cascade['name']}

**Description**: {cascade['description']}
**Orchestrator**: [[Main Orchestrating Agent (MOA)]]

## Participating Domain Pods
{"\n".join(pod_links)}

## Execution Sequence
{"\n".join(step_links)}
"""
