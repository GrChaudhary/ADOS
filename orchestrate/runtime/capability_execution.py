"""
P9 — the durable execution state machine shared by both writers of
`capability_requests` (the autonomous path in `backend/app/mcp_gateway.py`
and the human-approval path in `backend/app/routers/runtime_approvals.py`),
and the canonical, server-computed idempotency key that makes the existing
`idempotency_key` column actually load-bearing.

THE FAILURE THIS CLOSES
------------------------
Both writers used to go straight from `pending_approval` to a terminal status
(`executed`/`failed`), with the real external call (a ServiceNow POST, for
example) happening in between and nothing durable recorded until AFTER it
returned. If the ADOS process died in that window, the row was left exactly
where it started (still `pending_approval`, or rolled back to it) even though
the external system might already hold a brand-new record — indistinguishable
from a request that had simply never been decided, and therefore approvable
or auto-executable a second time. See
docs/prime-agent-integration/18-production-readiness-review.md §9.

THE STATE MACHINE
------------------
    pending_approval --(decision, BEFORE the external call)--> executing
    executing --(external call resolves)--> executed | failed
    executing --(external call resolves ambiguously, OR the process
                 that would have resolved it never comes back)--> outcome_unknown
    outcome_unknown --(reconciliation finds proof)--> executed
    outcome_unknown --(reconciliation finds no proof)--> outcome_unknown (unchanged)

`executing` is written and COMMITTED in its own transaction, strictly before
the external call is made. That write is the fix: it is a durable fact ("a
decision to act on this exact request was made") that survives the process
dying immediately afterward, and it is what makes `pending_approval` and
"already decided" mutually exclusive regardless of what happens next.

`outcome_unknown` is terminal with respect to AUTOMATIC execution. Nothing in
this codebase ever transitions it back to something an agent's retry or an
approver's click can act on without an intervening, independent reconciliation
that finds positive proof. See capability_reconcile.py.

Neither state needed a schema migration: both are new values of the existing
free-text `status` column (never an enum/CHECK-constrained type), following
the same reuse-what-already-exists discipline P7-C's `events` column and
P7-D's `session_reconcile.py` already established for this codebase.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Optional

# -- states -------------------------------------------------------------------

STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_EXECUTING = "executing"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"
STATUS_DENIED = "denied"
STATUS_OUTCOME_UNKNOWN = "outcome_unknown"

#: Genuinely finished, in the sense that nothing acts on the row again
#: automatically. `outcome_unknown` is deliberately NOT in this set — it is
#: terminal for automatic execution, not for the row's story (reconciliation
#: can still move it to `executed`).
TERMINAL_CAPABILITY_STATES = frozenset({STATUS_EXECUTED, STATUS_FAILED, STATUS_DENIED})

#: How long a row may sit at `executing` before it is presumed to belong to a
#: process that is never coming back. Generous relative to every external
#: call this system makes today (ServiceNow's Table API has responded in low
#: single-digit seconds in every live run recorded in this programme) so that
#: a merely-slow call is never mistaken for an abandoned one.
EXECUTION_STALL_SECONDS_DEFAULT = 60.0


def outcome_status_for(call_status: str) -> str:
    """Maps a connector's `CallStatus` value (already lower-cased, as
    `_execute_capability` reads it off the wire) onto the three outcomes a
    capability_requests row can durably record.

    SUCCEEDED -> executed. Anything else that is NOT explicitly `unknown` is
    `failed` — a connector that raised, returned a 4xx/5xx it could read, or
    reported `rolled_back` has told ADOS enough to know the action did not
    (or no longer) stand, which is a real answer, not an absence of one.
    Only `unknown` — reserved by contracts/capabilities.py for exactly "the
    request may already have reached the far side" — earns the state that
    refuses automatic retry.
    """
    if call_status == "succeeded":
        return STATUS_EXECUTED
    if call_status == "unknown":
        return STATUS_OUTCOME_UNKNOWN
    return STATUS_FAILED


def canonical_idempotency_key(
    session_id: "uuid.UUID | str", capability: str, arguments: Optional[Dict[str, Any]]
) -> str:
    """The one identity a retry of "the same logical request" is judged
    against — computed here, on the server, from facts the server already
    trusts (the session making the call, which capability, and the real
    arguments that will actually be sent), never from a string the caller
    labels a request with.

    WHY THIS REPLACES THE OLD CALLER-SUPPLIED `idempotency_key`
    -------------------------------------------------------------
    The old mechanism was opt-in: `request_capability` accepted an optional
    `idempotency_key` argument, and nothing reachable from a real mission ever
    passed one — the prompt template that teaches the model the `ados` skill's
    API (`orchestrate/runtime/prime.py::_compose_prompt`) never mentions the
    parameter. A safety mechanism no real caller ever exercises is not a
    safety mechanism; it is a code path this review found and P9 exists to
    close. Computing the key here means it protects every call automatically,
    with nothing for a model, a prompt author, or a future caller to remember
    — and nothing for any of them to substitute, since there is no field
    carrying an explicit key for a caller to set at all any more.

    `_confidence`/`_estimated_cost_usd` and any other underscore-prefixed key
    are excluded, matching `_execute_capability`'s own stripping of them
    before they reach a connector — those are governance HINTS about the
    call, not part of the real external action, and two calls that request
    the identical action while merely disagreeing about their own claimed
    cost must still be recognised as the same request.

    STATED TRADEOFF, NOT HIDDEN
    -----------------------------
    Two calls with byte-identical capability and arguments are treated as the
    same logical request for the lifetime of the session. A mission that
    genuinely needs to send the exact same notification twice cannot,
    automatically, inside one session — this system has no way to distinguish
    that from a retry, and the safe default (favouring one action over a
    possible duplicate) is deliberate, not an oversight.
    """
    payload = {k: v for k, v in (arguments or {}).items() if not str(k).startswith("_")}
    material = json.dumps(
        {"session_id": str(session_id), "capability": str(capability), "arguments": payload},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
