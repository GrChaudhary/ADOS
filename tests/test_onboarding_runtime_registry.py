"""
orchestrate/onboarding/runtime_registry.py — the glue that makes an
activated onboarding session actually live: registered into
DynamicCapabilityConnector's dispatch table and, for domain-scoped
capabilities, into orchestrate/moa/dynamic_registry.py so MOA can choose
it. Uses real Postgres for onboarding_sessions (matching
tests/test_onboarding_session_model.py's precondition) and an in-memory
CapabilityManifestRegistry for the governance-status side hydrate_all()
reads.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from contracts import Capability, PolicyTier
from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow
from integrations.capability_manifest import CapabilityManifestRegistry, RiskProfileEntry
from integrations.connectors.dynamic import DynamicCapabilityConnector
from orchestrate.moa import dynamic_registry
from orchestrate.onboarding import runtime_registry


@pytest.fixture(autouse=True)
async def _clean_table():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE onboarding_sessions CASCADE"))
        await session.commit()
    dynamic_registry.clear()
    yield
    dynamic_registry.clear()


async def _insert_activated_session(*, capability_id: str, domain: str, key: str = "read_ticket") -> None:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        session.add(
            OnboardingSessionRow(
                id=str(uuid.uuid4()),
                track="mcp_native",
                status="activated",
                source_url="https://github.com/example/zendesk-mcp",
                domain=domain,
                capability_id=capability_id,
                selected_tool_name=key,
                synthesized_manifest={
                    "key": key,
                    "description": "Fetch a support ticket",
                    "estimated_cost_usd": 0.0,
                    "runtime": {
                        "launch_command": ["python", "server.py"],
                        "tool_name": key,
                        "local_path": "/tmp/ados-onboarding/zendesk-mcp",
                        "input_schema": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
                    },
                },
                audit_log=[],
                created_by="admin-1",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_register_runtime_returns_false_when_no_session_exists():
    connector = DynamicCapabilityConnector(CapabilityManifestRegistry())
    result = await runtime_registry.register_runtime(async_session_factory, "no.such.capability", connector)
    assert result is False


@pytest.mark.asyncio
async def test_register_runtime_populates_connector_and_dynamic_registry():
    await _insert_activated_session(capability_id="zendesk.read_ticket", domain="support")
    connector = DynamicCapabilityConnector(CapabilityManifestRegistry())

    result = await runtime_registry.register_runtime(async_session_factory, "zendesk.read_ticket", connector)

    assert result is True
    assert "zendesk.read_ticket" in connector._dispatch
    config = connector._dispatch["zendesk.read_ticket"]
    assert config.track == "mcp_native"
    assert config.runtime["local_path"] == "/tmp/ados-onboarding/zendesk-mcp"

    manifests = CapabilityManifestRegistry()
    await manifests.propose(
        "zendesk.read_ticket", domain="support", version="1.0.0", source="https://github.com/example/zendesk-mcp",
        risk_profile=[RiskProfileEntry(action="read_ticket", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="new")],
        proposed_by="onboarding-agent",
    )
    await manifests.record_sandbox_evidence("zendesk.read_ticket", "ran ok", actor="onboarding-agent")
    await manifests.activate("zendesk.read_ticket", actor="admin-1", reason="approved")

    dynamic_actions = dynamic_registry.dynamic_actions_for_all_domains(manifests)
    assert "read_ticket" in dynamic_actions
    assert dynamic_actions["read_ticket"].capability_id == "zendesk.read_ticket"
    assert dynamic_actions["read_ticket"].capability is Capability.DYNAMIC_CAPABILITY
    # register_runtime() must thread the tool's real input_schema through to
    # DynamicAction, not just the connector's dispatch config -- otherwise
    # MOA's reason_node has no way to describe/require real parameters.
    assert dynamic_actions["read_ticket"].input_schema["required"] == ["ticket_id"]


@pytest.mark.asyncio
async def test_hydrate_all_counts_only_active_manifests_with_a_real_session():
    manifests = CapabilityManifestRegistry()

    async def _propose_and_activate(capability_id: str, domain: str):
        await manifests.propose(
            capability_id, domain=domain, version="1.0.0", source="x",
            risk_profile=[RiskProfileEntry(action="a", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="new")],
            proposed_by="onboarding-agent",
        )
        await manifests.record_sandbox_evidence(capability_id, "ran ok", actor="onboarding-agent")
        await manifests.activate(capability_id, actor="admin-1", reason="approved")

    # (1) ACTIVE manifest with a matching onboarding_sessions row — hydrates.
    await _propose_and_activate("zendesk.read_ticket", "support")
    await _insert_activated_session(capability_id="zendesk.read_ticket", domain="support")

    # (2) ACTIVE manifest with NO onboarding_sessions row (e.g. proposed
    # directly, outside this pipeline) — safe no-op, doesn't count.
    await _propose_and_activate("built_in.notify", "ops")

    # (3) PROPOSED (not yet ACTIVE) — hydrate_all must skip it entirely.
    await manifests.propose(
        "slack.dm", domain="hr", version="1.0.0", source="x",
        risk_profile=[RiskProfileEntry(action="a", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="new")],
        proposed_by="onboarding-agent",
    )

    connector = DynamicCapabilityConnector(manifests)
    count = await runtime_registry.hydrate_all(async_session_factory, manifests, connector)

    assert count == 1
    assert "zendesk.read_ticket" in connector._dispatch
    assert "built_in.notify" not in connector._dispatch
    assert "slack.dm" not in connector._dispatch


def test_register_default_executors_wires_all_three_tracks():
    connector = DynamicCapabilityConnector(CapabilityManifestRegistry())
    runtime_registry.register_default_executors(connector)
    assert "mcp_native" in connector._executors
    assert "raw_code" in connector._executors
    assert "openapi" in connector._executors


def test_filter_to_tool_arguments_drops_moa_bookkeeping_keys_not_in_the_schema():
    """The real bug this exists to prevent: CapabilityCall.input carries
    employee_name/action (orchestrate/moa/graph.py's fixed HR_ACTIONS-style
    payload shape) and capability_id (this bridge's own routing key)
    alongside real tool arguments — none of those are parameters the tool
    itself declared, and FastMCP rejects a call with unexpected kwargs."""
    call_input = {"employee_name": "Priya Nair", "action": "add_numbers", "capability_id": "echo-sample.add_numbers", "a": 4, "b": 5}
    schema = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}
    assert runtime_registry._filter_to_tool_arguments(call_input, schema) == {"a": 4, "b": 5}


def test_filter_to_tool_arguments_empty_schema_yields_no_arguments():
    call_input = {"employee_name": "Priya Nair", "action": "send_welcome_back_message", "capability_id": "x.notify"}
    assert runtime_registry._filter_to_tool_arguments(call_input, {}) == {}
