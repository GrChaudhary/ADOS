"""
TTS incident-briefing wiring — orchestrate/orchestrator.py's _finalize().
All Watson TTS access is monkeypatched on the module-level `tts_client`
singleton; no live network calls, matching the discipline in
tests/test_itsm_connector.py.
"""

import asyncio

import pytest

from backend.app.eventbus import InMemoryEventBus
from contracts import Capability, CausalChainEntry, IncidentRecord, PolicyTier
from integrations import default_hub
from knowledge.tts_client import tts_client
from orchestrate import DecisionOrchestrator, PriorityInputs


def _record(**overrides) -> IncidentRecord:
    kwargs = dict(
        incident_id="INC-TTS-1",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-27T00:00:00Z",
        final_state="Resolved",
        confidence=0.92,
        policy_tier=PolicyTier.AUTONOMOUS,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-1", description="Tolerance drift on CNC-102", weight=0.9, evidence_path=[]
            )
        ],
    )
    kwargs.update(overrides)
    return IncidentRecord(**kwargs)


def test_build_briefing_text_uses_only_record_fields():
    record = _record()
    text = DecisionOrchestrator._build_briefing_text(record)

    assert "Line 2" in text
    assert "FAC-P04-L2" in text
    assert "Resolved" in text
    assert "Tolerance drift on CNC-102" in text
    assert "ScheduleMaintenance" in text
    assert "92 percent" in text


def test_build_briefing_text_omits_absent_optional_fields():
    record = _record(causal_chain=[], capability_invoked=None)
    text = DecisionOrchestrator._build_briefing_text(record)

    assert "Root cause" not in text
    assert "Action taken" not in text


@pytest.mark.asyncio
async def test_finalize_skips_tts_when_flag_unset(monkeypatch):
    monkeypatch.delenv("TTS_INCIDENT_BRIEFING_ENABLED", raising=False)
    called = {"synthesize": False}
    monkeypatch.setattr(tts_client, "is_configured", lambda: True)
    monkeypatch.setattr(tts_client, "synthesize", lambda *a, **k: called.update(synthesize=True) or {})

    bus = InMemoryEventBus()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=default_hub())

    from agents.sdk import IncidentContext
    from contracts import IncidentState
    from orchestrate.state_machine import IncidentStateMachine

    ctx = IncidentContext(plant_id="FAC-P1", line_id="Line3")
    sm = IncidentStateMachine()
    for state in [
        IncidentState.DIAGNOSING, IncidentState.CANDIDATE_GENERATION, IncidentState.RESERVING,
        IncidentState.AWAITING_APPROVAL, IncidentState.EXECUTING, IncidentState.RESOLVED,
    ]:
        sm.transition(state)

    record = await orchestrator._finalize(ctx, sm, confidence=0.9, causal_chain=[], policy_tier=PolicyTier.AUTONOMOUS)

    assert called["synthesize"] is False
    assert orchestrator.get_audio_briefing(record.incident_id) is None


@pytest.mark.asyncio
async def test_finalize_synthesizes_and_caches_briefing_when_enabled(monkeypatch):
    monkeypatch.setenv("TTS_INCIDENT_BRIEFING_ENABLED", "true")
    monkeypatch.setattr(tts_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        tts_client,
        "synthesize",
        lambda text, voice=None, accept="audio/mp3": {
            "status": "live",
            "audio_bytes": b"FAKE-MP3-BYTES",
            "content_type": accept,
        },
    )

    bus = InMemoryEventBus()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=default_hub())

    from agents.sdk import IncidentContext
    from contracts import IncidentState
    from orchestrate.state_machine import IncidentStateMachine

    ctx = IncidentContext(plant_id="FAC-P1", line_id="Line3")
    sm = IncidentStateMachine()
    for state in [
        IncidentState.DIAGNOSING, IncidentState.CANDIDATE_GENERATION, IncidentState.RESERVING,
        IncidentState.AWAITING_APPROVAL, IncidentState.EXECUTING, IncidentState.RESOLVED,
    ]:
        sm.transition(state)

    record = await orchestrator._finalize(ctx, sm, confidence=0.9, causal_chain=[], policy_tier=PolicyTier.AUTONOMOUS)

    assert orchestrator.get_audio_briefing(record.incident_id) == b"FAKE-MP3-BYTES"


@pytest.mark.asyncio
async def test_finalize_does_not_cache_briefing_on_tts_failure(monkeypatch):
    monkeypatch.setenv("TTS_INCIDENT_BRIEFING_ENABLED", "true")
    monkeypatch.setattr(tts_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        tts_client, "synthesize", lambda *a, **k: {"status": "error", "error": "TTS API returned 500"}
    )

    bus = InMemoryEventBus()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=default_hub())

    from agents.sdk import IncidentContext
    from contracts import IncidentState
    from orchestrate.state_machine import IncidentStateMachine

    ctx = IncidentContext(plant_id="FAC-P1", line_id="Line3")
    sm = IncidentStateMachine()
    for state in [
        IncidentState.DIAGNOSING, IncidentState.CANDIDATE_GENERATION, IncidentState.RESERVING,
        IncidentState.AWAITING_APPROVAL, IncidentState.EXECUTING, IncidentState.RESOLVED,
    ]:
        sm.transition(state)

    record = await orchestrator._finalize(ctx, sm, confidence=0.9, causal_chain=[], policy_tier=PolicyTier.AUTONOMOUS)

    assert orchestrator.get_audio_briefing(record.incident_id) is None
