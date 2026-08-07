"""
Capability Manifest Registry — Postgres-backed path (session_factory set).
Requires `docker compose up -d postgres` + `alembic upgrade head` applied
to ados_test (conftest.py points DATABASE_URL there for the whole suite).

Covers what's genuinely new and DB-specific: durability across a fresh
registry instance (simulating a process restart), and the row-locking fix
for a race that could never happen in the pure in-memory path (no `await`
there, so Python's cooperative scheduling made it accidentally atomic —
see integrations/capability_manifest.py's module docstring).
"""

import asyncio

import pytest
from sqlalchemy import text

from contracts import PolicyTier
from db.engine import async_session_factory
from integrations.capability_manifest import (
    CapabilityManifestRegistry,
    CapabilityStatus,
    RiskProfileEntry,
)
from integrations.policy_engine import PolicyViolation


@pytest.fixture(autouse=True)
async def _clean_tables():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE capability_promotion_events, capability_manifests CASCADE"))
        await session.commit()
    yield


def _risk_profile():
    return [RiskProfileEntry(action="read_ticket", tier=PolicyTier.AUTONOMOUS, reasoning="read-only, no side effects")]


@pytest.mark.asyncio
async def test_full_pipeline_persists_and_verifies_against_real_postgres():
    registry = CapabilityManifestRegistry(session_factory=async_session_factory)
    await registry.propose(
        "zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y",
        risk_profile=_risk_profile(), proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence("zendesk.read_ticket", "ran ok", actor="onboarding-agent")
    manifest = await registry.activate("zendesk.read_ticket", actor="admin-1", reason="looks good")

    assert manifest.status is CapabilityStatus.ACTIVE
    assert len(await registry.history_for("zendesk.read_ticket")) == 3
    assert await registry.verify_integrity("zendesk.read_ticket") is True


@pytest.mark.asyncio
async def test_survives_a_fresh_registry_instance_same_database():
    """The actual property this migration exists to deliver: durability
    across a process restart. A brand-new CapabilityManifestRegistry has
    an empty in-memory cache, but the DB-backed history is unaffected."""
    writer = CapabilityManifestRegistry(session_factory=async_session_factory)
    await writer.propose(
        "zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y",
        risk_profile=_risk_profile(), proposed_by="onboarding-agent",
    )
    await writer.record_sandbox_evidence("zendesk.read_ticket", "ran ok", actor="onboarding-agent")
    await writer.activate("zendesk.read_ticket", actor="admin-1", reason="approved")

    reader = CapabilityManifestRegistry(session_factory=async_session_factory)
    # manifest_for() is the sync in-memory cache — empty until something
    # populates it. history_for() always reads Postgres directly.
    assert reader.manifest_for("zendesk.read_ticket") is None
    history = await reader.history_for("zendesk.read_ticket")
    assert [e.event_type for e in history] == ["proposed", "sandbox_tested", "activated"]
    assert await reader.verify_integrity("zendesk.read_ticket") is True


@pytest.mark.asyncio
async def test_concurrent_hot_disable_calls_do_not_corrupt_the_hash_chain():
    """Two concurrent transitions on the SAME capability must serialize,
    not interleave. Without the SELECT ... FOR UPDATE row lock, both
    coroutines could read status=ACTIVE, both pass the check, and both
    compute the next hash-chain link off the same previous_event_hash —
    exactly the race this test exists to rule out."""
    registry = CapabilityManifestRegistry(session_factory=async_session_factory)
    await registry.propose(
        "zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y",
        risk_profile=_risk_profile(), proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence("zendesk.read_ticket", "ran ok", actor="onboarding-agent")
    await registry.activate("zendesk.read_ticket", actor="admin-1", reason="approved")

    results = await asyncio.gather(
        registry.hot_disable("zendesk.read_ticket", actor="admin-1", reason="race A"),
        registry.hot_disable("zendesk.read_ticket", actor="admin-2", reason="race B"),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    # Exactly one wins (ACTIVE -> HOT_DISABLED is only a valid transition
    # once); the other correctly finds it's no longer ACTIVE and rejects.
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], PolicyViolation)

    history = await registry.history_for("zendesk.read_ticket")
    assert [e.event_type for e in history] == ["proposed", "sandbox_tested", "activated", "hot_disabled"]
    # The hash chain must still be internally consistent — no duplicate or
    # out-of-order sequence numbers from the race.
    assert await registry.verify_integrity("zendesk.read_ticket") is True


@pytest.mark.asyncio
async def test_concurrent_double_proposal_is_rejected_not_corrupted():
    registry = CapabilityManifestRegistry(session_factory=async_session_factory)
    results = await asyncio.gather(
        registry.propose(
            "zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y",
            risk_profile=_risk_profile(), proposed_by="onboarding-agent",
        ),
        registry.propose(
            "zendesk.read_ticket", domain="support", version="1.0.1", source="github.com/x/y",
            risk_profile=_risk_profile(), proposed_by="onboarding-agent",
        ),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], PolicyViolation)
    assert "already registered" in str(failures[0])
