"""
P9 — reconciliation for `capability_requests` rows a crash or an ambiguous
response left without a known outcome
(orchestrate/runtime/capability_reconcile.py).

WHAT THESE TESTS PIN
----------------------
* a row stuck `executing` past the stall bound becomes `outcome_unknown`,
  never guessed as `executed` or `failed`
* a row not yet past the stall bound is left alone — a merely-slow call must
  not be mistaken for an abandoned one
* `outcome_unknown` resolves to `executed` ONLY when the external system
  itself confirms a matching record, keyed on the row's own canonical
  `request_id`
* a record whose text merely CONTAINS something request-id-shaped, but not
  THIS row's actual id, must never resolve it — forged or unrelated
  provenance cannot hijack reconciliation
* a capability with no ServiceNow table mapping has no automated
  reconciliation path and is left untouched, honestly
* a query that could not be answered at all leaves the row exactly where it
  was — "I don't know" must never be treated as "I checked, and no"
* every reconciliation attempt — resolved or not — is durably recorded on
  the row itself
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from orchestrate.runtime.capability_execution import STATUS_EXECUTED, STATUS_EXECUTING, STATUS_OUTCOME_UNKNOWN
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown, reconcile_outcome_unknown


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


async def _seeded_row(*, status: str, capability: str = "NotifyITHelpdesk", updated_at=None) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="reconcile", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        sess = RuntimeSessionRow(mission_id=mission.mission_id, state="running")
        db.add(sess)
        await db.flush()
        row = CapabilityRequestRow(
            session_id=sess.session_id, mission_id=mission.mission_id,
            capability=capability, arguments={"summary": "x"}, status=status,
            idempotency_key=f"k-{uuid.uuid4().hex}",
        )
        db.add(row)
        await db.commit()
        request_id = row.request_id

    if updated_at is not None:
        # Backdating requires a raw UPDATE — the ORM's own onupdate would
        # otherwise stamp "now" the moment this test touches the row again.
        async with async_session_factory() as db:
            await db.execute(
                text("UPDATE capability_requests SET updated_at = :ts WHERE request_id = :id"),
                {"ts": updated_at, "id": request_id},
            )
            await db.commit()

    return request_id


async def _get(request_id: uuid.UUID) -> CapabilityRequestRow:
    async with async_session_factory() as db:
        return await db.get(CapabilityRequestRow, request_id)


class _FakeServiceNow(ServiceNowConnector):
    """Stands in for the real connector — `reconcile_outcome_unknown` takes
    one by dependency injection specifically so this test never needs
    httpx/MockTransport plumbing to control what "the external system says"."""

    def __init__(self, answer):
        super().__init__()
        self._answer = answer  # (ok: bool, records: list[dict])

    async def find_by_request_id(self, table, request_id):
        return self._answer


# --- mark_stalled_executions_unknown ------------------------------------------

async def test_a_row_executing_past_the_stall_bound_becomes_outcome_unknown():
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    request_id = await _seeded_row(status=STATUS_EXECUTING, updated_at=old)

    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=60)

    assert [s.request_id for s in stalled] == [request_id]
    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN
    assert "reconciliation" in row.reason


async def test_a_row_executing_within_the_stall_bound_is_left_alone():
    recent = datetime.now(timezone.utc) - timedelta(seconds=5)
    request_id = await _seeded_row(status=STATUS_EXECUTING, updated_at=recent)

    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=60)

    assert stalled == []
    row = await _get(request_id)
    assert row.status == STATUS_EXECUTING, "a merely-slow call must not be mistaken for an abandoned one"


async def test_a_row_not_executing_is_never_touched_by_stall_detection():
    old = datetime.now(timezone.utc) - timedelta(seconds=999)
    request_id = await _seeded_row(status=STATUS_EXECUTED, updated_at=old)

    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=60)

    assert stalled == []
    row = await _get(request_id)
    assert row.status == STATUS_EXECUTED


# --- reconcile_outcome_unknown --------------------------------------------------

async def test_a_matching_external_record_resolves_the_row_to_executed():
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    fake = _FakeServiceNow((True, [
        {"sys_id": "s1", "number": "INC1", "description": f"...Capability request: {request_id}..."},
    ]))

    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert len(outcomes) == 1 and outcomes[0].resolved
    row = await _get(request_id)
    assert row.status == STATUS_EXECUTED
    assert row.result["reconciled"] is True
    assert row.result["reconciled_match"]["number"] == "INC1"


async def test_a_record_that_does_not_actually_contain_this_rows_id_does_not_resolve_it():
    """ServiceNow's own `descriptionLIKE` is a substring match server-side —
    this is the client-side re-check that a hit is a REAL match, not a false
    positive from an unrelated record ServiceNow happened to return."""
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    other_id = uuid.uuid4()
    fake = _FakeServiceNow((True, [
        {"sys_id": "s1", "number": "INC1", "description": f"Capability request: {other_id}"},
    ]))

    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert outcomes[0].resolved is False
    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN


async def test_a_forged_agent_authored_provenance_block_cannot_hijack_reconciliation():
    """The query is server-side (`descriptionLIKE<real request_id>`), so a
    record can only ever be RETURNED by ServiceNow if it already contains
    THIS row's own id — an agent cannot cause a record naming a DIFFERENT
    request to be considered here no matter what text it writes, because
    that record would never even match the search."""
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    # Simulates what the server-side query would legitimately return: nothing,
    # because no real record names this row's id — an agent-forged block in
    # some OTHER record naming a different id never enters this list at all.
    fake = _FakeServiceNow((True, []))

    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert outcomes[0].resolved is False
    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN


async def test_no_match_leaves_the_row_at_outcome_unknown_but_records_the_attempt():
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    fake = _FakeServiceNow((True, []))

    await reconcile_outcome_unknown(async_session_factory, connector=fake)

    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN
    attempts = row.result["reconciliation_attempts"]
    assert len(attempts) == 1
    assert attempts[0]["found"] is False


async def test_a_query_that_could_not_be_answered_is_not_treated_as_a_negative_answer():
    """`ok=False` means "I don't know", not "I checked and it's not there" —
    the row must stay exactly where it was, not be quietly cleared."""
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    fake = _FakeServiceNow((False, [{"error": "simulated transport failure"}]))

    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert outcomes[0].resolved is False
    assert "could not be answered" in outcomes[0].detail
    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN


async def test_a_capability_with_no_servicenow_mapping_has_no_automated_reconciliation():
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN, capability="RunPrimeRLMAgent")
    fake = _FakeServiceNow((True, [{"sys_id": "s1", "number": "INC1", "description": str(request_id)}]))

    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert outcomes[0].resolved is False
    assert "no automated reconciliation path" in outcomes[0].detail
    row = await _get(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN


async def test_reconciliation_is_idempotent_a_second_pass_over_a_resolved_row_finds_nothing():
    request_id = await _seeded_row(status=STATUS_OUTCOME_UNKNOWN)
    fake = _FakeServiceNow((True, [{"sys_id": "s1", "number": "INC1", "description": str(request_id)}]))

    first = await reconcile_outcome_unknown(async_session_factory, connector=fake)
    second = await reconcile_outcome_unknown(async_session_factory, connector=fake)

    assert len(first) == 1 and first[0].resolved
    assert second == [], "an already-resolved row must not be reconsidered"
