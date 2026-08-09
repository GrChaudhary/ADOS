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

from contracts import Capability, CallStatus, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from orchestrate.governance import CAPABILITY_RISK_CLASS, assign_policy_tier

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
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask ADOS to perform one governed capability.

    Returns `executed` with a result, `pending_approval` with a request_id when
    a human must decide, or `denied` with a reason. The runtime states what it
    wants; ADOS decides what is permitted.
    """
    arguments = arguments or {}

    async with async_session_factory() as db:
        try:
            session_row, mission = await _resolve_session(db)
        except _Denied as e:
            return {"status": "denied", "reason": e.reason}

        # Idempotency before anything with a side effect: a retried call must
        # return the ORIGINAL outcome, never execute twice. Scoped to this
        # session so keys cannot collide across missions.
        if idempotency_key:
            prior = (
                await db.execute(
                    select(CapabilityRequestRow).where(
                        CapabilityRequestRow.session_id == session_row.session_id,
                        CapabilityRequestRow.idempotency_key == idempotency_key,
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
                idempotency_key=idempotency_key,
            )
            db.add(denial)
            await db.commit()
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
            idempotency_key=idempotency_key,
            status="pending_approval",
        )
        db.add(row)
        session_row.capability_request_count = (session_row.capability_request_count or 0) + 1

        if tier != PolicyTier.AUTONOMOUS:
            # Park it. Deliberately NOT holding this HTTP call open against a
            # human's attention span — the row is durable, the agent polls.
            session_row.state = "waiting_approval"
            await db.commit()
            return {
                "status": "pending_approval",
                "request_id": str(row.request_id),
                "policy_tier": int(tier),
                "reason": f"tier {int(tier)} requires human approval",
            }

        await db.commit()
        request_id = row.request_id

    # Outside the DB session so a slow connector doesn't hold a transaction
    # open. The row is resolved unconditionally below — including when the
    # executor raises — so no request can be stranded at pending_approval.
    try:
        result = await _execute_capability(
            capability, arguments, mission_id=mission.mission_id, tier=tier,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort guard, see above
        result = {"ok": False, "capability": capability, "error": f"{type(exc).__name__}: {exc}"}

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, request_id)
        row.status = "executed" if result.get("ok") else "failed"
        row.result = result
        row.reason = None if result.get("ok") else result.get("error")
        row.decided_by = "policy:autonomous"
        await db.commit()

    return {
        "status": "executed" if result.get("ok") else "failed",
        "request_id": str(request_id),
        "policy_tier": int(PolicyTier.AUTONOMOUS),
        "result": result,
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
) -> Dict[str, Any]:
    """Run the capability through the real ADOS path.

    Kept as a single choke point so there is exactly one place where a
    capability becomes a real side effect, and so the audit record is written
    by the executor rather than reconstructed from what the agent claimed.

    Everything, including building the CapabilityCall, is inside the try:
    constructing it can raise (it is a validated Pydantic contract), and an
    escape here would leave the request row stranded at pending_approval
    forever — a tier-0 call that neither executed nor failed. That exact bug
    was observed the first time this ran against a real MCP client.

    `request_id` is the CapabilityRequestRow's primary key, passed in rather
    than minted here. One governed request, one id, everywhere it appears.
    Letting `CapabilityCall` fall back to its own `uuid4` default produced two
    ids for a single action, and connectors write the *call's* id into the
    systems they touch: a real ServiceNow incident (INC0010027) carried
    `Capability request: c0258072-…` while the audit row's key was
    `cf4522b4-…`. An operator following that pointer back into ADOS found
    nothing. Provenance that does not resolve is worse than none, because it
    looks like a working audit trail.
    """
    # default_hub(), not a bare IntegrationHub(): the bare constructor has NO
    # connectors registered, so every capability comes back
    # "no connector registered for capability X" — which the first real run of
    # this gateway did, calmly, while reporting success.
    from integrations.hub import default_hub  # local import: avoids a cycle at app import time
    from contracts import CapabilityCall, GovernanceInfo

    try:
        call = CapabilityCall(
            capability=Capability(capability),
            # The audit row's own key — NOT a fresh uuid4. See the docstring.
            request_id=str(request_id),
            input={k: v for k, v in arguments.items() if not k.startswith("_")},
            requested_by=f"prime-runtime:mission:{mission_id}",
            incident_id=str(mission_id),
            # The tier ADOS decided, carried into the call the connectors see —
            # so the governance record travels with the action rather than
            # being asserted separately.
            governance=GovernanceInfo(policy_tier=tier),
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
        # contracts.CallStatus: succeeded | failed | rolled_back. Only the
        # first is success — rolled_back explicitly is not.
        succeeded = str(payload.get("status", "")).lower() == CallStatus.SUCCEEDED.value
        return {
            "ok": succeeded,
            "capability": capability,
            "outcome": payload,
            **({} if succeeded else {"error": payload.get("error") or f"connector reported status={payload.get('status')!r}"}),
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the agent as a real error
        logger.exception("Capability execution failed", extra={"capability": capability})
        return {"ok": False, "capability": capability, "error": f"{type(exc).__name__}: {exc}"}


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
