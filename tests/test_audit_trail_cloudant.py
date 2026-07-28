"""
AuditTrail <-> Cloudant write-through/hydration — orchestrate/audit_trail.py.

All Cloudant access is monkeypatched on the module-level `cloudant_db`
singleton; no live network calls, matching the discipline established in
tests/test_itsm_connector.py (whose own docstring documents a past incident
where an unmocked test made real ~12s network calls).
"""

import pytest

from contracts import IncidentRecord, PolicyTier
from knowledge.cloudant_client import cloudant_db
from orchestrate.audit_trail import AuditTrail


def _record(incident_id: str = "INC-TEST-1") -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-27T00:00:00Z",
        final_state="Resolved",
        confidence=0.95,
        policy_tier=PolicyTier.AUTONOMOUS,
    )


@pytest.mark.asyncio
async def test_append_writes_through_to_cloudant_when_configured(monkeypatch):
    monkeypatch.setattr(cloudant_db, "is_configured", lambda: True)
    captured = {}
    monkeypatch.setattr(cloudant_db, "save_incident", lambda doc: captured.update(doc) or doc["incidentId"])

    trail = AuditTrail()
    record = _record()
    result = await trail.append(record)

    assert result is record
    assert trail.get("INC-TEST-1") is record
    assert captured["incidentId"] == "INC-TEST-1"
    assert captured["finalState"] == "Resolved"


@pytest.mark.asyncio
async def test_append_degrades_gracefully_when_cloudant_write_raises(monkeypatch):
    monkeypatch.setattr(cloudant_db, "is_configured", lambda: True)

    def _boom(doc):
        raise RuntimeError("Cloudant unreachable")

    monkeypatch.setattr(cloudant_db, "save_incident", _boom)

    trail = AuditTrail()
    record = _record()
    result = await trail.append(record)

    # In-memory append must still succeed even though the Cloudant write failed.
    assert result is record
    assert trail.get("INC-TEST-1") is record
    assert trail.all() == [record]


@pytest.mark.asyncio
async def test_append_skips_cloudant_when_not_configured(monkeypatch):
    monkeypatch.setattr(cloudant_db, "is_configured", lambda: False)

    def _fail_if_called(doc):
        raise AssertionError("save_incident should not be called when Cloudant is unconfigured")

    monkeypatch.setattr(cloudant_db, "save_incident", _fail_if_called)

    trail = AuditTrail()
    await trail.append(_record())
    assert len(trail.all()) == 1


@pytest.mark.asyncio
async def test_hydrate_from_cloudant_loads_existing_records(monkeypatch):
    docs = [
        {
            "_id": "INC-HYDRATE-1",
            "_rev": "1-abc",
            "incidentId": "INC-HYDRATE-1",
            "plantId": "FAC-P04-L2",
            "lineId": "Line 2",
            "detectedAt": "2026-07-27T00:00:00Z",
            "finalState": "Resolved",
            "confidence": 0.9,
            "policyTier": 0,
        }
    ]
    monkeypatch.setattr(cloudant_db, "list_incidents", lambda limit=500: docs)

    trail = AuditTrail()
    loaded = await trail.hydrate_from_cloudant()

    assert loaded == 1
    assert trail.get("INC-HYDRATE-1") is not None
    assert trail.get("INC-HYDRATE-1").plant_id == "FAC-P04-L2"


@pytest.mark.asyncio
async def test_hydrate_skips_malformed_docs_without_crashing(monkeypatch):
    docs = [
        {"_id": "INC-BAD", "incidentId": "INC-BAD"},  # missing required fields
        {
            "_id": "INC-GOOD",
            "incidentId": "INC-GOOD",
            "plantId": "FAC-P04-L2",
            "lineId": "Line 2",
            "detectedAt": "2026-07-27T00:00:00Z",
            "finalState": "Resolved",
            "confidence": 0.9,
            "policyTier": 0,
        },
    ]
    monkeypatch.setattr(cloudant_db, "list_incidents", lambda limit=500: docs)

    trail = AuditTrail()
    loaded = await trail.hydrate_from_cloudant()

    assert loaded == 1
    assert trail.get("INC-GOOD") is not None
    assert trail.get("INC-BAD") is None


def test_default_construction_has_no_cloudant_side_effects(monkeypatch):
    def _fail_if_called():
        raise AssertionError("is_configured() should not be called by bare AuditTrail() construction")

    monkeypatch.setattr(cloudant_db, "is_configured", _fail_if_called)

    trail = AuditTrail()
    assert trail.all() == []
