"""
Capability Manifest Registry — orchestration-platform-vision.md §8.4/§8.7.
Covers the two hard rules that must hold structurally, not just by
convention: no activating without sandbox evidence, and no self-approval.

Pure in-memory path only (no session_factory) — fast, no Postgres needed.
See tests/test_capability_manifest_postgres.py for the DB-backed path and
the concurrent-transition row-locking behavior that only exists there.
"""

import pytest

from contracts import PolicyTier
from integrations.capability_manifest import (
    CapabilityManifestRegistry,
    CapabilityStatus,
    RiskProfileEntry,
    verify_event_chain,
)
from integrations.policy_engine import PolicyViolation


def _risk_profile():
    return [RiskProfileEntry(action="read_ticket", tier=PolicyTier.AUTONOMOUS, reasoning="read-only, no side effects")]


@pytest.mark.asyncio
async def test_propose_requires_nonempty_risk_profile_with_reasoning():
    registry = CapabilityManifestRegistry()
    with pytest.raises(PolicyViolation):
        await registry.propose("zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y", risk_profile=[], proposed_by="onboarding-agent")

    with pytest.raises(PolicyViolation):
        await registry.propose(
            "zendesk.read_ticket",
            domain="support",
            version="1.0.0",
            source="github.com/x/y",
            risk_profile=[RiskProfileEntry(action="read_ticket", tier=PolicyTier.AUTONOMOUS, reasoning="  ")],
            proposed_by="onboarding-agent",
        )


@pytest.mark.asyncio
async def test_full_pipeline_happy_path():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence("zendesk.read_ticket", "ran against sandboxed mock ticket, got expected 200", actor="onboarding-agent")
    manifest = await registry.activate("zendesk.read_ticket", actor="admin-1", reason="looks good")

    assert manifest.status is CapabilityStatus.ACTIVE
    assert len(await registry.history_for("zendesk.read_ticket")) == 3
    assert await registry.verify_integrity("zendesk.read_ticket") is True


@pytest.mark.asyncio
async def test_cannot_activate_without_sandbox_testing():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    with pytest.raises(PolicyViolation, match="no fast-forward"):
        await registry.activate("zendesk.read_ticket", actor="admin-1", reason="skip ahead")


@pytest.mark.asyncio
async def test_cannot_self_approve():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence("zendesk.read_ticket", "sandbox run ok", actor="onboarding-agent")
    with pytest.raises(PolicyViolation, match="cannot activate its own capability"):
        await registry.activate("zendesk.read_ticket", actor="onboarding-agent", reason="self-approve")


@pytest.mark.asyncio
async def test_sandbox_evidence_must_be_nonempty():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    with pytest.raises(PolicyViolation):
        await registry.record_sandbox_evidence("zendesk.read_ticket", "", actor="onboarding-agent")


@pytest.mark.asyncio
async def test_hot_disable_only_from_active_and_resume_round_trips():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    with pytest.raises(PolicyViolation):
        await registry.hot_disable("zendesk.read_ticket", actor="admin-1", reason="not live yet")

    await registry.record_sandbox_evidence("zendesk.read_ticket", "sandbox run ok", actor="onboarding-agent")
    await registry.activate("zendesk.read_ticket", actor="admin-1", reason="approved")

    disabled = await registry.hot_disable("zendesk.read_ticket", actor="admin-1", reason="misbehaving in prod")
    assert disabled.status is CapabilityStatus.HOT_DISABLED

    resumed = await registry.resume("zendesk.read_ticket", actor="admin-1", reason="root cause fixed")
    assert resumed.status is CapabilityStatus.ACTIVE


@pytest.mark.asyncio
async def test_usage_tracking():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    await registry.record_usage("zendesk.read_ticket")
    await registry.record_usage("zendesk.read_ticket")
    manifest = registry.manifest_for("zendesk.read_ticket")
    assert manifest.usage_count == 2
    assert manifest.last_used_at is not None


@pytest.mark.asyncio
async def test_verify_integrity_detects_tampering():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    events = await registry.history_for("zendesk.read_ticket")
    tampered = [events[0].__class__(**{**events[0].__dict__, "reason": "tampered"})]
    with pytest.raises(PolicyViolation, match="event hash is invalid"):
        verify_event_chain(tampered)


@pytest.mark.asyncio
async def test_double_proposal_rejected():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=_risk_profile(),
        proposed_by="onboarding-agent",
    )
    with pytest.raises(PolicyViolation, match="already registered"):
        await registry.propose(
            "zendesk.read_ticket",
            domain="support",
            version="1.0.1",
            source="github.com/x/y",
            risk_profile=_risk_profile(),
            proposed_by="onboarding-agent",
        )


# ---------------------------------------------------------------------
# Real per-action risk-tier calibration (vision §5.2/§8.6) — an onboarded
# capability starts fixed at EXECUTIVE_APPROVAL (orchestrate/onboarding/
# risk_proposal.py's deliberate v1 floor); calibrate_tier() is the
# previously-missing mechanism to loosen that once a real, clean usage
# track record justifies it. record_failure() is the other half: without
# it, usage_count alone can't tell "10 clean calls" from "10 calls, 6
# errors."
# ---------------------------------------------------------------------

async def _active_capability(registry: CapabilityManifestRegistry, capability_id: str = "zendesk.read_ticket"):
    await registry.propose(
        capability_id, domain="support", version="1.0.0", source="github.com/x/y",
        risk_profile=_risk_profile(), proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence(capability_id, "sandbox run ok", actor="onboarding-agent")
    return await registry.activate(capability_id, actor="admin-1", reason="approved")


@pytest.mark.asyncio
async def test_record_failure_tracked_separately_from_usage_count():
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)

    await registry.record_usage("zendesk.read_ticket")
    await registry.record_usage("zendesk.read_ticket")
    await registry.record_failure("zendesk.read_ticket")

    manifest = registry.manifest_for("zendesk.read_ticket")
    assert manifest.usage_count == 2
    assert manifest.failure_count == 1
    assert manifest.last_used_at is not None


@pytest.mark.asyncio
async def test_calibrate_tier_requires_active_status():
    registry = CapabilityManifestRegistry()
    await registry.propose(
        "zendesk.read_ticket", domain="support", version="1.0.0", source="github.com/x/y",
        risk_profile=_risk_profile(), proposed_by="onboarding-agent",
    )
    with pytest.raises(PolicyViolation, match="must be ACTIVE"):
        await registry.calibrate_tier(
            "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="looks fine"
        )


@pytest.mark.asyncio
async def test_calibrate_tier_requires_minimum_usage_count():
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)
    for _ in range(5):  # below MIN_CALIBRATION_USAGE_COUNT (10)
        await registry.record_usage("zendesk.read_ticket")

    with pytest.raises(PolicyViolation, match="needs at least"):
        await registry.calibrate_tier(
            "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="looks fine"
        )


@pytest.mark.asyncio
async def test_calibrate_tier_requires_zero_failures():
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)
    for _ in range(10):
        await registry.record_usage("zendesk.read_ticket")
    await registry.record_failure("zendesk.read_ticket")

    with pytest.raises(PolicyViolation, match="clean track record"):
        await registry.calibrate_tier(
            "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="looks fine"
        )


@pytest.mark.asyncio
async def test_calibrate_tier_rejects_a_non_strict_downgrade():
    """target_tier must be strictly safer than the current effective tier
    (EXECUTIVE_APPROVAL, the fail-safe default, when never calibrated) —
    tightening or a no-op has a dedicated tool (hot_disable) already."""
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)
    for _ in range(10):
        await registry.record_usage("zendesk.read_ticket")

    with pytest.raises(PolicyViolation, match="not safer"):
        await registry.calibrate_tier(
            "zendesk.read_ticket", target_tier=PolicyTier.EXECUTIVE_APPROVAL, actor="admin-1", reason="no-op"
        )


@pytest.mark.asyncio
async def test_calibrate_tier_succeeds_with_a_clean_sufficient_record():
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)
    for _ in range(10):
        await registry.record_usage("zendesk.read_ticket")

    updated = await registry.calibrate_tier(
        "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1",
        reason="10 clean invocations, promoting per policy",
    )

    assert updated.tier_override is PolicyTier.APPROVAL_REQUIRED
    assert registry.manifest_for("zendesk.read_ticket").tier_override is PolicyTier.APPROVAL_REQUIRED

    # Recorded in the same tamper-evident event log as every other
    # lifecycle transition, verifiable end to end.
    events = await registry.history_for("zendesk.read_ticket")
    assert events[-1].event_type == "tier_calibrated"
    assert "APPROVAL_REQUIRED" in events[-1].reason
    assert await registry.verify_integrity("zendesk.read_ticket") is True


@pytest.mark.asyncio
async def test_calibrate_tier_can_be_applied_a_second_time_from_the_new_floor():
    """Once calibrated to APPROVAL_REQUIRED, a second, later calibration
    to AUTONOMOUS must compare against the NEW floor (APPROVAL_REQUIRED),
    not silently re-compare against the original EXECUTIVE_APPROVAL
    default — proves current_tier is read from tier_override, not
    hardcoded."""
    registry = CapabilityManifestRegistry()
    await _active_capability(registry)
    for _ in range(10):
        await registry.record_usage("zendesk.read_ticket")
    await registry.calibrate_tier(
        "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="first calibration"
    )

    # Would incorrectly succeed if current_tier were still hardcoded to
    # EXECUTIVE_APPROVAL instead of read from tier_override.
    with pytest.raises(PolicyViolation, match="not safer"):
        await registry.calibrate_tier(
            "zendesk.read_ticket", target_tier=PolicyTier.APPROVAL_REQUIRED, actor="admin-1", reason="no-op retry"
        )

    updated = await registry.calibrate_tier(
        "zendesk.read_ticket", target_tier=PolicyTier.AUTONOMOUS, actor="admin-1", reason="second calibration"
    )
    assert updated.tier_override is PolicyTier.AUTONOMOUS
