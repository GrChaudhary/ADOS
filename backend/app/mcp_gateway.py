"""
ADOS MCP Capability Gateway — the upward half of the Prime Agent runtime
boundary, and the only door from the execution plane back into ADOS.

MCP is the transport here, not the authorization layer. The authority chain is:

    runtime request
      -> authenticate the session token   (identity only)
      -> resolve mission/session          (server side)
      -> resolve the capability grant     (server side, from the mission row)
      -> membership check
      -> idempotency
      -> policy + risk (orchestrate/governance)
      -> execute via IntegrationHub, or park for human approval
      -> audit
      -> result

Two properties this file exists to guarantee:

1. **The runtime cannot widen its own permissions.** There is no request field
   carrying a capability list, a role, or a tier. The grant is read from the
   mission row every time. A compromised or confused agent can ask for
   anything and still get exactly what the mission allowed.

2. **A capability is only ever recorded as executed by the code that executed
   it.** The agent's self-report is never written to the audit trail. This is
   the same discipline the ServiceNow work established after a blank ticket was
   reported as SUCCEEDED.

HTTP (not stdio) is forced by Prime Agent: its kernel drops non-HTTP mcpServers
entries (packages/coding-agent/docs/mcp-integrations.md).
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from contracts import Capability, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from orchestrate.governance import CAPABILITY_RISK_CLASS, assign_policy_tier
from orchestrate.runtime.capability_execution import (
    STATUS_EXECUTED,
    STATUS_EXECUTING,
    STATUS_FAILED,
    STATUS_OUTCOME_UNKNOWN,
    canonical_idempotency_key,
    outcome_status_for,
)

logger = logging.getLogger("ados.mcp_gateway")

mcp = FastMCP("ADOS Capability Gateway")

# Session states in which a runtime may still act. A completed or torn-down
# session's token is dead even if it has not expired by wall clock.
_LIVE_STATES = {"starting", "running", "waiting_approval"}


def hash_token(token: str) -> str:
    """SHA-256, the same function used when the session row is written.

    Plain SHA-256 rather than a password KDF is deliberate and defensible here:
    the token is 32 bytes of `secrets.token_urlsafe` entropy, not a
    user-chosen secret, so there is no dictionary to attack and the slow-hash
    property buys nothing while costing latency on every capability call."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _Denied(Exception):
    """Refusal that should reach the agent as a structured answer rather than
    a transport error — the agent can then report the limitation instead of
    retrying blindly."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _presented_token() -> str:
    headers = get_http_headers()
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise _Denied("missing bearer token")
    return auth.split(" ", 1)[1].strip()


async def _resolve_session(session_db) -> tuple[RuntimeSessionRow, MissionRow]:
    """Token -> session -> mission. Every authorization decision starts here,
    and nothing from the request body participates."""
    token_hash = hash_token(_presented_token())

    row = (
        await session_db.execute(
            select(RuntimeSessionRow).where(RuntimeSessionRow.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if row is None:
        raise _Denied("unrecognized session token")
    if row.state not in _LIVE_STATES:
        raise _Denied(f"session is {row.state} and can no longer act")
    if row.token_expires_at is not None and datetime.now(timezone.utc) > row.token_expires_at:
        raise _Denied("session token expired")

    mission = await session_db.get(MissionRow, row.mission_id)
    if mission is None:
        raise _Denied("mission no longer exists")
    return row, mission


def _describe(capability: str) -> str:
    risk = CAPABILITY_RISK_CLASS.get(Capability(capability), "unclassified")
    return f"{capability} (risk class: {risk})"


@mcp.tool
async def list_capabilities() -> Dict[str, Any]:
    """The capabilities this mission has granted this runtime session.

    Exposed so the agent discovers its grant instead of guessing, and so a
    denial later is informative rather than mysterious."""
    async with async_session_factory() as db:
        try:
            _, mission = await _resolve_session(db)
        except _Denied as e:
            return {"status": "denied", "reason": e.reason, "capabilities": []}

        return {
            "status": "ok",
            "mission_id": str(mission.mission_id),
            "capabilities": [
                {"capability": c, "description": _describe(c)}
                for c in (mission.allowed_capabilities or [])
            ],
        }


@mcp.tool
async def request_capability(
    capability: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ask ADOS to perform one governed capability.

    Returns `executed` with a result, `pending_approval` with a request_id
    when a human must decide, `outcome_unknown` when ADOS cannot yet say
    whether the action happened (see P9), or `denied` with a reason. The
    runtime states what it wants; ADOS decides what is permitted.

    THERE IS NO `idempotency_key` PARAMETER ANY MORE. P8 found the old one —
    caller-supplied, optional — practically unreachable: nothing in the real
    prompt template (`orchestrate/runtime/prime.py::_compose_prompt`) ever
    taught the model it existed, so no live mission ever set one. P9 replaces
    it with a canonical key this function computes itself, from the session
    and the real capability/arguments being sent — see
    `orchestrate.runtime.capability_execution.canonical_idempotency_key`.
    There is nothing left for a caller to substitute.
    """
    arguments = arguments or {}
    # Set inside the block below, before anything that can raise
    # IntegrityError — the outer handler needs both to resolve a lost race.
    key: Optional[str] = None
    session_id_for_replay: Optional[uuid.UUID] = None

    try:
        async with async_session_factory() as db:
            try:
                session_row, mission = await _resolve_session(db)
            except _Denied as e:
                return {"status": "denied", "reason": e.reason}

            # Idempotency before anything with a side effect, ALWAYS — not
            # opt-in. A retried call (the agent's own retry, or a legitimate
            # duplicate poll) must return the ORIGINAL outcome, never execute
            # twice. Scoped to this session so keys cannot collide across
            # missions, and to the real content of the request so two
            # genuinely different actions never collide with each other.
            key = canonical_idempotency_key(session_row.session_id, capability, arguments)
            session_id_for_replay = session_row.session_id
            prior = (
                await db.execute(
                    select(CapabilityRequestRow).where(
                        CapabilityRequestRow.session_id == session_row.session_id,
                        CapabilityRequestRow.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if prior is not None:
                return {
                    "status": prior.status,
                    "request_id": str(prior.request_id),
                    "result": prior.result,
                    "reason": prior.reason,
                    "replayed": True,
                }

            # The grant, read server-side. Nothing in the request influences this.
            granted = set(mission.allowed_capabilities or [])
            if capability not in granted:
                denial = CapabilityRequestRow(
                    session_id=session_row.session_id,
                    mission_id=mission.mission_id,
                    capability=capability,
                    arguments=arguments,
                    status="denied",
                    reason=f"'{capability}' is not in this mission's capability grant",
                    idempotency_key=key,
                )
                db.add(denial)
                await db.commit()  # IntegrityError, if any, is handled by the outer try
                logger.warning(
                    "Capability request denied — outside mission grant",
                    extra={"capability": capability, "mission_id": str(mission.mission_id)},
                )
                return {"status": "denied", "request_id": str(denial.request_id), "reason": denial.reason}

            try:
                cap = Capability(capability)
            except ValueError:
                return {"status": "denied", "reason": f"'{capability}' is not a known ADOS capability"}

            # Same policy engine the MOA uses — one governance implementation, not
            # a parallel one for agents.
            tier = assign_policy_tier(
                cap,
                confidence=float(arguments.get("_confidence", 0.95)),
                estimated_cost_usd=float(arguments.get("_estimated_cost_usd", 0.0)),
            )
            risk = CAPABILITY_RISK_CLASS.get(cap, "unclassified")

            row = CapabilityRequestRow(
                session_id=session_row.session_id,
                mission_id=mission.mission_id,
                capability=capability,
                arguments=arguments,
                policy_tier=int(tier),
                risk_class=risk,
                idempotency_key=key,
                status="pending_approval",
            )
            db.add(row)
            session_row.capability_request_count = (session_row.capability_request_count or 0) + 1

            if tier != PolicyTier.AUTONOMOUS:
                # Park it. Deliberately NOT holding this HTTP call open against
                # a human's attention span — the row is durable, the agent polls.
                session_row.state = "waiting_approval"
                await db.commit()
                # P10: an operator watching the approval queue by eye already
                # sees this; an operator watching logs (or alerting on a
                # queue that never drains) did not, until now. Capability
                # and tier only — never the arguments, which are agent-
                # authored and may carry free text not meant for a log line.
                logger.info(
                    "Capability request parked for human approval",
                    extra={
                        "request_id": str(row.request_id), "capability": capability,
                        "policy_tier": int(tier), "mission_id": str(mission.mission_id),
                    },
                )
                return {
                    "status": "pending_approval",
                    "request_id": str(row.request_id),
                    "policy_tier": int(tier),
                    "reason": f"tier {int(tier)} requires human approval",
                }

            # P9: durably mark EXECUTING and commit — releasing nothing that
            # needs releasing here (no lock is held across the slow call
            # below; this commit's only job is to make "a decision to
            # execute this exact request was made" survive this process
            # dying immediately afterward). See
            # orchestrate/runtime/capability_execution.py.
            row.status = STATUS_EXECUTING
            await db.commit()
            request_id = row.request_id
    except IntegrityError:
        # Lost a genuine race against a concurrent, canonically-identical
        # call — `uq_capability_requests_session_idempotency` (alembic
        # revision d1e2f3a4b5c6) turned what would otherwise be a classic
        # check-then-act TOCTOU into a database-enforced fact. Caught OUTSIDE
        # the `async with` block deliberately: recovering with more async ORM
        # calls on the SAME session immediately after its own mid-flush
        # failure was observed to raise `MissingGreenlet` (a SQLAlchemy/
        # asyncpg quirk in that exact sequence) — letting the session's own
        # context manager finish tearing down first, then opening a
        # completely fresh one in `_replay_or_raise`, sidesteps it.
        return await _replay_or_raise(session_id_for_replay, key)

    # Outside the DB session so a slow connector doesn't hold a transaction
    # open. The row is resolved unconditionally below — including when the
    # executor raises — so no request can be stranded at `executing`.
    try:
        result = await _execute_capability(
            capability, arguments, mission_id=mission.mission_id, tier=tier,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort guard, see above
        result = {"outcome_status": STATUS_FAILED, "capability": capability, "error": f"{type(exc).__name__}: {exc}"}

    outcome_status = result.get("outcome_status", STATUS_FAILED)
    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, request_id)
        row.status = outcome_status
        row.result = result
        row.reason = None if outcome_status == STATUS_EXECUTED else result.get("error")
        row.decided_by = "policy:autonomous"
        await db.commit()

    if outcome_status == STATUS_OUTCOME_UNKNOWN:
        # P10: this is the anomaly `orchestrate/runtime/capability_reconcile.py`
        # exists to resolve — a connector reported it could not tell whether
        # the action happened. Durable state already carries it (row.status);
        # this is what makes it visible without querying the database, e.g.
        # for an alert on this exact log line. Never the arguments or the
        # connector's raw error text, which may embed request content.
        logger.warning(
            "Capability execution outcome unknown — requires reconciliation",
            extra={"request_id": str(request_id), "capability": capability},
        )

    return {
        "status": outcome_status,
        "request_id": str(request_id),
        "policy_tier": int(PolicyTier.AUTONOMOUS),
        "result": result,
    }


async def _replay_or_raise(session_id: uuid.UUID, key: str) -> Dict[str, Any]:
    """Lost a race to create the row for this exact (session, canonical key)
    pair — `uq_capability_requests_session_idempotency` (alembic revision
    `d1e2f3a4b5c6`) makes that a database-enforced fact, not a hope. The
    winner's row is read back and replayed exactly as an ordinary,
    non-concurrent idempotency hit would be: this caller sees the SAME
    outcome the winner sees, never a second row and never a second external
    effect. If, impossibly, no row is found (the winner's own transaction
    somehow never committed), the original IntegrityError's absence of a
    resolvable row is itself the honest answer — surfaced as `denied` rather
    than silently retried, since retrying here would recreate the very race
    this function exists to resolve.

    Always opens a FRESH session: the caller (`request_capability`) catches
    the triggering `IntegrityError` OUTSIDE the session that raised it, for
    exactly this reason — see that catch's own comment.
    """
    async with async_session_factory() as db:
        prior = (
            await db.execute(
                select(CapabilityRequestRow).where(
                    CapabilityRequestRow.session_id == session_id,
                    CapabilityRequestRow.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
    if prior is None:
        return {"status": "denied", "reason": "a concurrent identical request could not be resolved"}
    return {
        "status": prior.status,
        "request_id": str(prior.request_id),
        "result": prior.result,
        "reason": prior.reason,
        "replayed": True,
    }


@mcp.tool
async def get_capability_request(request_id: str) -> Dict[str, Any]:
    """Current state of a previously submitted request.

    How the agent waits for a human without anyone holding a socket open."""
    async with async_session_factory() as db:
        try:
            session_row, _ = await _resolve_session(db)
        except _Denied as e:
            return {"status": "denied", "reason": e.reason}

        try:
            row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        except ValueError:
            return {"status": "denied", "reason": "malformed request_id"}

        # Scoped read: a session can only inspect its own requests.
        if row is None or row.session_id != session_row.session_id:
            return {"status": "denied", "reason": "no such request for this session"}

        return {
            "status": row.status,
            "request_id": str(row.request_id),
            "capability": row.capability,
            "policy_tier": row.policy_tier,
            "result": row.result,
            "reason": row.reason,
        }


async def _execute_capability(
    capability: str,
    arguments: Dict[str, Any],
    *,
    mission_id: uuid.UUID,
    tier: PolicyTier,
    request_id: uuid.UUID,
    approved_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the capability through the real ADOS path.

    Kept as a single choke point so there is exactly one place where a
    capability becomes a real side effect, and so the audit record is written
    by the executor rather than reconstructed from what the agent claimed.

    Everything, including building the CapabilityCall, is inside the try:
    constructing it can raise (it is a validated Pydantic contract), and an
    escape here would leave the request row stranded at `executing` forever
    — a tier-0 call that neither executed nor failed. That exact bug (against
    the row's PRIOR name for this state, `pending_approval`) was observed the
    first time this ran against a real MCP client.

    `request_id` is the CapabilityRequestRow's primary key, passed in rather
    than minted here. One governed request, one id, everywhere it appears.
    Letting `CapabilityCall` fall back to its own `uuid4` default produced two
    ids for a single action, and connectors write the *call's* id into the
    systems they touch: a real ServiceNow incident (INC0010027) carried
    `Capability request: c0258072-…` while the audit row's key was
    `cf4522b4-…`. An operator following that pointer back into ADOS found
    nothing. Provenance that does not resolve is worse than none, because it
    looks like a working audit trail.

    RETURNS A TRI-STATE OUTCOME, NOT A BOOLEAN (P9)
    -------------------------------------------------
    `result["outcome_status"]` is one of `executed` / `failed` /
    `outcome_unknown` — never a collapsed `ok: bool`. A connector reporting
    `CallStatus.UNKNOWN` (contracts/capabilities.py: "the request was already
    in flight when contact was lost... FAILED is also a lie, and the more
    dangerous one") used to be indistinguishable from an ordinary failure
    here, which would have let a caller safely-looking retry something that
    may already have happened. See `orchestrate.runtime.capability_execution.
    outcome_status_for`.
    """
    # default_hub(), not a bare IntegrationHub(): the bare constructor has NO
    # connectors registered, so every capability comes back
    # "no connector registered for capability X" — which the first real run of
    # this gateway did, calmly, while reporting success.
    from integrations.hub import default_hub  # local import: avoids a cycle at app import time
    from contracts import CapabilityCall, GovernanceInfo
    from orchestrate.runtime.build_identity import verify_no_drift_since_process_start

    try:
        # P10: the P7-D drift guard used to run only at mission start
        # (PrimeRuntimeConnector._run, before any container exists) — never
        # again for the rest of that mission's life. A commit landing while
        # a mission was already in flight was never caught for that
        # mission's remaining capability calls, including ones that reach a
        # real external system. This is the single choke point every
        # capability call passes through (autonomous AND human-approval),
        # so one call here closes that window for both. Raises
        # StaleGatewayError (a RuntimeError), caught by the `except
        # Exception` below exactly like every other failure constructing or
        # executing this call — no new error shape, and importantly this
        # runs BEFORE default_hub().invoke() below, so a stale gateway is
        # refused before any connector, and therefore any external side
        # effect, is ever reached.
        verify_no_drift_since_process_start()
        call = CapabilityCall(
            capability=Capability(capability),
            # The audit row's own key — NOT a fresh uuid4. See the docstring.
            request_id=str(request_id),
            input={k: v for k, v in arguments.items() if not k.startswith("_")},
            requested_by=f"prime-runtime:mission:{mission_id}",
            incident_id=str(mission_id),
            # The tier ADOS decided, carried into the call the connectors see —
            # so the governance record travels with the action rather than
            # being asserted separately. `approved_by` is the verified username
            # of the human who released a Tier 1/2 request, never a value the
            # runtime supplied; None on the autonomous path, which is what the
            # contract means by "null for Tier 0".
            governance=GovernanceInfo(policy_tier=tier, approved_by=approved_by),
        )
        # hub.invoke(), the same entry point orchestrate/moa/graph.py uses —
        # one execution path for agents and for the MOA, not a parallel one.
        outcome = await default_hub().invoke(call)
        payload = _jsonable(outcome)

        # "No exception" is NOT "it worked". CapabilityResponse carries its own
        # status, and a hub with no connector registered for the capability
        # returns status="failed" perfectly calmly. Reporting that as executed
        # is how an agent ends up believing it acted when nothing happened —
        # the same failure mode as the blank ServiceNow ticket recorded as
        # SUCCEEDED. The response's own status is the authority.
        # contracts.CallStatus: succeeded | failed | rolled_back | unknown.
        # outcome_status_for maps this 4-valued wire status onto the 3-valued
        # capability_requests outcome — succeeded->executed, unknown->
        # outcome_unknown, everything else (failed, rolled_back, an
        # unrecognised value)->failed. See its own docstring.
        outcome_status = outcome_status_for(str(payload.get("status", "")).lower())
        return {
            "outcome_status": outcome_status,
            "capability": capability,
            "outcome": payload,
            **(
                {} if outcome_status == STATUS_EXECUTED
                else {"error": payload.get("error") or f"connector reported status={payload.get('status')!r}"}
            ),
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the agent as a real error
        # An exception here happens BEFORE any connector was ever entered —
        # constructing the CapabilityCall, or the hub failing to select a
        # connector at all — never after a real external call was attempted
        # (every connector this codebase ships catches its own transport
        # exceptions and returns a CapabilityResponse; see servicenow.py's
        # own FAILED/UNKNOWN split). FAILED is therefore still the correct,
        # non-ambiguous answer for this branch specifically.
        logger.exception("Capability execution failed", extra={"capability": capability})
        return {"outcome_status": STATUS_FAILED, "capability": capability, "error": f"{type(exc).__name__}: {exc}"}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def mcp_http_app():
    """ASGI app to mount at /mcp on the FastAPI backend."""
    return mcp.http_app(path="/")
