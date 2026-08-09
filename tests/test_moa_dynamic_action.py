"""
Onboarded (dynamic) capabilities showing up in MOA's action space —
orchestrate/moa/dynamic_registry.py + graph.py's _get_domain_actions merge
point. Pins down the behaviors that make an onboarded capability actually
useful to the LLM, not just invocable via a direct hub.invoke() call
(tests/test_dynamic_capability_connector.py covers that half): it shows up
in the prompt, the LLM can select it by key, its real capability_id
threads into the resulting CapabilityCall, it's scoped to its own domain
(not visible to every domain pod), and it disappears again the instant it's
hot-disabled — no restart required, since manifest_for() is synchronous/
in-memory and dynamic_registry reads it fresh on every call.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from contracts import Capability, PolicyTier
from integrations import IntegrationHub
from integrations.capability_manifest import CapabilityManifestRegistry, RiskProfileEntry
from integrations.connectors.console import ConsoleConnector
from integrations.connectors.dynamic import DynamicDispatchConfig
from knowledge.local_llm_client import local_llm_client
from orchestrate.moa import dynamic_registry, graph as moa_graph
from orchestrate.moa.dynamic_registry import DynamicAction

# One InMemorySaver shared by this module's tests. build_graph() creates a
# fresh one per call by design (so that forgetting to pass a checkpointer in
# production fails loudly rather than silently "working" in one process), which
# means a test that resumes a task must hand the same saver back in.
_saver = InMemorySaver()



@pytest.fixture(autouse=True)
def _clean_dynamic_registry():
    """dynamic_registry._ENTRIES is process-global — must not leak into
    other test modules sharing this pytest session."""
    dynamic_registry.clear()
    yield
    dynamic_registry.clear()


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


async def _register_active_dynamic_action(
    manifests: CapabilityManifestRegistry, *, key: str, capability_id: str, domain: str,
    estimated_cost_usd: float = 0.0, description: str = "Send a Slack DM to the employee's manager",
    input_schema: dict = None,
) -> None:
    await manifests.propose(
        capability_id,
        domain=domain,
        version="1.0.0",
        source="https://github.com/example/slack-notifier",
        risk_profile=[RiskProfileEntry(action=key, tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="newly onboarded, max scrutiny")],
        proposed_by="onboarding-agent",
    )
    await manifests.record_sandbox_evidence(capability_id, "ran 1/1 sample tool call, succeeded", actor="onboarding-agent")
    await manifests.activate(capability_id, actor="admin-1", reason="reviewed and approved")
    dynamic_registry.register(
        DynamicAction(
            key=key,
            description=description,
            capability=Capability.DYNAMIC_CAPABILITY,
            estimated_cost_usd=estimated_cost_usd,
            capability_id=capability_id,
            input_schema=input_schema or {},
        )
    )


def test_dynamic_action_only_visible_in_its_own_domain():
    manifests = CapabilityManifestRegistry()

    import asyncio
    asyncio.run(_register_active_dynamic_action(manifests, key="notify_slack", capability_id="slack.dm", domain="finance"))

    hr_actions = moa_graph._get_domain_actions("hr", manifests)
    finance_actions = moa_graph._get_domain_actions("finance", manifests)
    all_actions = moa_graph._get_domain_actions("all", manifests)

    assert "notify_slack" not in hr_actions
    assert "notify_slack" in finance_actions
    assert finance_actions["notify_slack"].capability_id == "slack.dm"
    assert "notify_slack" in all_actions


def test_dynamic_action_disappears_immediately_after_hot_disable_no_restart():
    manifests = CapabilityManifestRegistry()
    import asyncio
    asyncio.run(_register_active_dynamic_action(manifests, key="notify_slack", capability_id="slack.dm", domain="hr"))

    assert "notify_slack" in moa_graph._actions_description("hr", manifests)

    asyncio.run(manifests.hot_disable("slack.dm", actor="admin-1", reason="spamming channel"))

    assert "notify_slack" not in moa_graph._actions_description("hr", manifests)


@pytest.mark.asyncio
async def test_llm_can_select_a_dynamic_action_and_capability_id_flows_into_the_call(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    await _register_active_dynamic_action(hub.manifests, key="notify_slack", capability_id="slack.dm", domain="hr")

    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call)
        return {"sent": True}

    hub.dynamic_capability_connector.register("slack.dm", DynamicDispatchConfig(track="fake"))
    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_slack"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Manager notified via Slack."},
            ]
        ),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub, checkpointer=_saver)

    # DYNAMIC_CAPABILITY has no CAPABILITY_RISK_CLASS entry -> fails safe to
    # "high" -> always EXECUTIVE_APPROVAL, so this must pause, never
    # auto-execute, regardless of estimated_cost_usd.
    assert result is None
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["action_key"] == "notify_slack"
    assert proposed["policy_tier"] == PolicyTier.EXECUTIVE_APPROVAL.value
    assert calls_seen == []  # nothing invoked before approval

    result, graph, config = await moa_graph.resume_moa_task(config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", hub=hub, checkpointer=_saver)

    assert result["tools_called"] == ["notify_slack"]
    assert len(calls_seen) == 1
    assert calls_seen[0].capability is Capability.DYNAMIC_CAPABILITY
    assert calls_seen[0].input["capability_id"] == "slack.dm"
    assert calls_seen[0].governance.policy_tier == PolicyTier.EXECUTIVE_APPROVAL
    assert calls_seen[0].governance.approved_by == "exec-1"


# ---------------------------------------------------------------------
# Real per-action risk-tier calibration (vision §5.2/§8.6) —
# CapabilityManifestRegistry.calibrate_tier()'s effect must actually reach
# MOA's real per-call governance decision (orchestrate/moa/graph.py's
# _effective_policy_tier), not just live in the manifest as inert data.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calibrated_tier_overrides_the_executive_approval_floor(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    await _register_active_dynamic_action(hub.manifests, key="notify_slack", capability_id="slack.dm", domain="hr")
    for _ in range(10):
        await hub.manifests.record_usage("slack.dm")
    await hub.manifests.calibrate_tier(
        "slack.dm", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="10 clean invocations"
    )

    hub.dynamic_capability_connector.register("slack.dm", DynamicDispatchConfig(track="fake"))
    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call)
        return {"sent": True}

    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client, "_generate_text",
        _fake_generate([
            {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_slack"},
            {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Manager notified via Slack."},
        ]),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub, checkpointer=_saver)

    # Still pauses -- APPROVAL_REQUIRED, not AUTONOMOUS -- but at the
    # calibrated tier, not the uncalibrated EXECUTIVE_APPROVAL floor.
    assert result is None
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["policy_tier"] == PolicyTier.APPROVAL_REQUIRED.value

    result, graph, config = await moa_graph.resume_moa_task(config["configurable"]["thread_id"], decision="approved", approved_by="mgr-1", hub=hub, checkpointer=_saver)
    assert calls_seen[0].governance.policy_tier == PolicyTier.APPROVAL_REQUIRED


@pytest.mark.asyncio
async def test_calibrated_to_autonomous_auto_executes_without_pausing(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    await _register_active_dynamic_action(hub.manifests, key="notify_slack", capability_id="slack.dm", domain="hr")
    for _ in range(10):
        await hub.manifests.record_usage("slack.dm")
    await hub.manifests.calibrate_tier(
        "slack.dm", target_tier=PolicyTier.AUTONOMOUS, actor="admin-1", reason="long clean track record"
    )

    hub.dynamic_capability_connector.register("slack.dm", DynamicDispatchConfig(track="fake"))
    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call)
        return {"sent": True}

    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client, "_generate_text",
        _fake_generate([
            {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_slack"},
            {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Manager notified via Slack."},
        ]),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub, checkpointer=_saver)

    # No pause at all -- calibrated all the way to AUTONOMOUS.
    assert result is not None
    assert result["tools_called"] == ["notify_slack"]
    assert calls_seen[0].governance.policy_tier == PolicyTier.AUTONOMOUS
    assert calls_seen[0].governance.approved_by is None


# ---------------------------------------------------------------------
# Argument passing — the LLM can supply real per-call argument values for
# an onboarded action, not just pick which action key to invoke. Before
# this, _action_input() only ever emitted {employee_name, action,
# capability_id}, none of which is a real tool parameter, so
# runtime_registry._filter_to_tool_arguments always resolved to {} for any
# genuinely parameterized tool (e.g. add_numbers(a, b)) — it silently
# laundered every call to an empty-args invocation.
# ---------------------------------------------------------------------

_ADD_NUMBERS_SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "required": ["a", "b"],
}


def test_dynamic_action_with_required_params_shows_a_hint_in_the_prompt():
    manifests = CapabilityManifestRegistry()
    import asyncio
    asyncio.run(
        _register_active_dynamic_action(
            manifests, key="add_numbers", capability_id="calc.add_numbers", domain="hr",
            description="Add two integers", input_schema=_ADD_NUMBERS_SCHEMA,
        )
    )
    description = moa_graph._actions_description("hr", manifests)
    assert "add_numbers: Add two integers (params: a integer required, b integer required)" in description


@pytest.mark.asyncio
async def test_llm_supplies_real_argument_values_and_they_flow_into_the_call(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    await _register_active_dynamic_action(
        hub.manifests, key="add_numbers", capability_id="calc.add_numbers", domain="hr",
        description="Add two integers", input_schema=_ADD_NUMBERS_SCHEMA,
    )

    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call)
        return {"result": call.input["a"] + call.input["b"]}

    hub.dynamic_capability_connector.register("calc.add_numbers", DynamicDispatchConfig(track="fake"))
    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": 'ACTION: add_numbers\nARGS: {"a": 4, "b": 5}'},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Added the numbers."},
            ]
        ),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Add 4 and 5", hub=hub, checkpointer=_saver)
    assert result is None  # still pauses -- DYNAMIC_CAPABILITY always floors at EXECUTIVE_APPROVAL

    result, graph, config = await moa_graph.resume_moa_task(config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", hub=hub, checkpointer=_saver)

    assert result["tools_called"] == ["add_numbers"]
    assert len(calls_seen) == 1
    # Previously this always resolved to {} -- the exact bug this feature fixes.
    assert calls_seen[0].input["a"] == 4
    assert calls_seen[0].input["b"] == 5
    assert calls_seen[0].input["capability_id"] == "calc.add_numbers"  # bookkeeping keys still ride along


@pytest.mark.asyncio
async def test_missing_required_args_is_a_hard_failure(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    await _register_active_dynamic_action(
        hub.manifests, key="add_numbers", capability_id="calc.add_numbers", domain="hr",
        description="Add two integers", input_schema=_ADD_NUMBERS_SCHEMA,
    )
    hub.dynamic_capability_connector.register("calc.add_numbers", DynamicDispatchConfig(track="fake"))

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client, "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: add_numbers"}]),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Add some numbers", hub=hub, checkpointer=_saver)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_malformed_args_is_a_hard_failure_even_when_nothing_was_required(monkeypatch):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    await _register_active_dynamic_action(
        hub.manifests, key="notify_slack", capability_id="slack.dm", domain="hr",
        input_schema={"type": "object", "properties": {"message": {"type": "string"}}},  # optional, no "required"
    )
    hub.dynamic_capability_connector.register("slack.dm", DynamicDispatchConfig(track="fake"))

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client, "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_slack\nARGS: not valid json"}]),
    )

    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Notify the manager", hub=hub, checkpointer=_saver)
    # Malformed ARGS is a hard fail even though nothing was strictly
    # required -- never silently ignore malformed LLM output.
    assert result["status"] == "error"


# ---------------------------------------------------------------------
# Human-edited arguments — a reviewer can correct the LLM's own proposed
# arguments before a paused action executes, not just approve/reject it
# as-is (docs/PHASE7_ANTIGRAVITY_ONBOARDING_UI_HANDOFF.md's own "no UI/API
# surface for this yet" note — the API surface now exists).
# ---------------------------------------------------------------------

async def _setup_add_numbers(monkeypatch, *, first_llm_text: str = 'ACTION: add_numbers\nARGS: {"a": 4, "b": 5}'):
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    await _register_active_dynamic_action(
        hub.manifests, key="add_numbers", capability_id="calc.add_numbers", domain="hr",
        description="Add two integers", input_schema=_ADD_NUMBERS_SCHEMA,
    )
    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call)
        return {"result": call.input["a"] + call.input["b"]}

    hub.dynamic_capability_connector.register("calc.add_numbers", DynamicDispatchConfig(track="fake"))
    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client, "_generate_text",
        _fake_generate([
            {"status": "live_llm_generated", "model_used": "fake", "text": first_llm_text},
            # Queued for whichever resume actually reaches a second
            # reason_node turn (an approval that executes) -- a resume
            # that raises before ever calling graph.ainvoke(), or one that
            # just rejects, never consumes this.
            {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Added the numbers."},
        ]),
    )
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Add some numbers", hub=hub, checkpointer=_saver)
    assert result is None
    return hub, graph, config, calls_seen


@pytest.mark.asyncio
async def test_proposed_action_exposes_input_schema_for_the_frontend_to_render_an_edit_form(monkeypatch):
    _, graph, config, _ = await _setup_add_numbers(monkeypatch)
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["arguments"] == {"a": 4, "b": 5}
    assert proposed["input_schema"] == _ADD_NUMBERS_SCHEMA


@pytest.mark.asyncio
async def test_human_edited_arguments_override_the_llm_proposed_ones(monkeypatch):
    hub, graph, config, calls_seen = await _setup_add_numbers(monkeypatch)

    # A human notices the LLM got it wrong and corrects it before approving.
    result, graph, config = await moa_graph.resume_moa_task(
        config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", edited_arguments={"a": 100, "b": 1}, hub=hub, checkpointer=_saver,
    )

    assert result["tools_called"] == ["add_numbers"]
    assert len(calls_seen) == 1
    assert calls_seen[0].input["a"] == 100
    assert calls_seen[0].input["b"] == 1  # the human's values, not the LLM's original 4/5


@pytest.mark.asyncio
async def test_edited_arguments_missing_a_required_param_is_rejected_before_resuming(monkeypatch):
    hub, graph, config, calls_seen = await _setup_add_numbers(monkeypatch)

    with pytest.raises(ValueError, match="missing required parameter"):
        await moa_graph.resume_moa_task(config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", edited_arguments={"a": 100}, hub=hub, checkpointer=_saver)

    assert calls_seen == []  # rejected before act_node ever ran -- nothing executed with a partial edit

    # Still genuinely resumable afterward with a valid correction -- proves
    # the rejected attempt never advanced or corrupted the paused graph.
    result, graph, config = await moa_graph.resume_moa_task(
        config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", edited_arguments={"a": 100, "b": 1}, hub=hub, checkpointer=_saver,
    )
    assert result["tools_called"] == ["add_numbers"]
    assert calls_seen[0].input["a"] == 100 and calls_seen[0].input["b"] == 1


@pytest.mark.asyncio
async def test_edited_arguments_must_be_a_json_object(monkeypatch):
    hub, graph, config, calls_seen = await _setup_add_numbers(monkeypatch)

    with pytest.raises(ValueError, match="must be a JSON object"):
        await moa_graph.resume_moa_task(config["configurable"]["thread_id"], decision="approved", approved_by="exec-1", edited_arguments=[1, 2, 3], hub=hub, checkpointer=_saver)

    assert calls_seen == []


@pytest.mark.asyncio
async def test_rejecting_with_edited_arguments_present_still_just_rejects(monkeypatch):
    """edited_arguments is only relevant to an approval that actually
    executes -- rejecting must ignore it rather than validating it, since
    a rejected action never builds a CapabilityCall at all."""
    hub, graph, config, calls_seen = await _setup_add_numbers(monkeypatch)

    result, graph, config = await moa_graph.resume_moa_task(
        config["configurable"]["thread_id"], decision="rejected", approved_by="exec-1",
        edited_arguments={"a": 100},  # missing "b", would fail if validated
        hub=hub, checkpointer=_saver,
    )

    assert result["approval_decision"] == "rejected"
    assert calls_seen == []


@pytest.mark.asyncio
async def test_dynamic_action_not_yet_active_is_invisible_to_the_llm(monkeypatch):
    """propose() without sandbox/activate — the prompt must not offer an
    action the connector would refuse to execute anyway (see
    tests/test_dynamic_capability_connector.py's not-yet-active gate)."""
    hub = IntegrationHub()
    await hub.manifests.propose(
        "slack.dm",
        domain="hr",
        version="1.0.0",
        source="https://github.com/example/slack-notifier",
        risk_profile=[RiskProfileEntry(action="notify_slack", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="newly onboarded")],
        proposed_by="onboarding-agent",
    )
    dynamic_registry.register(
        DynamicAction(
            key="notify_slack",
            description="Send a Slack DM",
            capability=Capability.DYNAMIC_CAPABILITY,
            estimated_cost_usd=0.0,
            capability_id="slack.dm",
        )
    )

    assert "notify_slack" not in moa_graph._get_domain_actions("hr", hub.manifests)
