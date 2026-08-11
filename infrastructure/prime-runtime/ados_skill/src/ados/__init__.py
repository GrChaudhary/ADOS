"""
ADOS capability skill — the ONLY route from a Prime Agent runtime back into
ADOS.

Prime Agent has a single-tool design: the model's tool is a persistent IPython
kernel, and integrations are Python packages it imports rather than new agent
tools (packages/coding-agent/docs/mcp-integrations.md). So this is a
Python-backed skill subclassing `McpIntegration`, and every ADOS capability the
runtime can reach comes through it.

Authorization deliberately does NOT live here. This module can ask for
anything; ADOS decides what is allowed. `ADOS_MCP_TOKEN` is opaque and
identity-only — it names the runtime session and nothing else. The gateway
hashes it, resolves the mission's capability grant server-side, applies policy
and risk, and audits the outcome. Nothing in this file can widen a grant,
because no field here is trusted for authorization.
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional

from rlm import McpIntegration

__all__ = ["ados", "Ados", "CapabilityDenied", "CapabilityTimeout", "CapabilityOutcomeUnknown"]


def _decoded(result: Any) -> Any:
    """Normalize what `McpIntegration.call_tool` hands back.

    `rlm.mcp_base._parse_result` prefers the MCP response's `structuredContent`
    and returns it as a dict — but when the server sends only text blocks (which
    is what FastMCP emits for these tools) it falls back to joining them, and
    the caller gets a JSON **string**.

    Without this, `run_capability` called `.get("status")` on a str and raised

        AttributeError: 'str' object has no attribute 'get'

    from inside this module, on every single call. The capability itself had
    already executed — the audit trail showed three successful
    FetchIncidentEvidence rows — so ADOS did the work and the agent never
    received the answer. The model diagnosed it correctly and could not fix it,
    because the exception is raised in here before anything is returned.

    Handles both shapes rather than depending on which one the server happens to
    produce, since that is a property of the MCP server's schema declarations
    and can change without notice.
    """
    if isinstance(result, (bytes, bytearray)):
        result = result.decode("utf-8", "replace")
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            # Genuinely not JSON: hand it back untouched rather than guess.
            return result
    return result


class CapabilityDenied(RuntimeError):
    """ADOS refused the request — not in this mission's grant, or policy
    blocked it. Not retryable by rephrasing; the mission would have to grant
    the capability."""


class CapabilityTimeout(RuntimeError):
    """A human approval did not arrive inside the wait budget. The request is
    still pending in ADOS; it was not cancelled and may still be approved."""


class CapabilityOutcomeUnknown(RuntimeError):
    """ADOS cannot say whether this action happened. Raised, not returned as
    a normal-looking result — a caller checking `result["ok"]` or reading
    `result["output"]` on a dict that silently meant "maybe" is exactly the
    false-success class this integration exists to prevent (P9). The action
    may or may not have occurred out there; ADOS will not execute it again
    automatically, and a human must reconcile it before it can move further.
    Do not retry by calling `run_capability` again with the same arguments —
    the request is already recorded and will not re-execute on its own, but a
    DIFFERENT real action must never be disguised as "trying again"."""


class Ados(McpIntegration):
    server = "ados"
    url = os.environ.get("ADOS_MCP_URL", "http://host.docker.internal:8000/mcp")
    bearer_token_env = "ADOS_MCP_TOKEN"

    async def capabilities(self) -> list:
        """What this session is actually allowed to do, per ADOS.

        Ask before assuming: the grant is per-mission and resolved server-side,
        so it is not guessable from the objective text."""
        return _decoded(await self.call_tool("list_capabilities", {}))

    async def run_capability(
        self,
        capability: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        wait: bool = True,
        timeout_seconds: float = 900.0,
        poll_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """Request one governed ADOS capability and return its result.

        Handles the asynchronous approval path for you. A Tier 1/2 capability
        returns `pending_approval` immediately rather than holding this call
        open against a human's attention span, so this polls
        `get_capability_request` until ADOS decides.

        Raises CapabilityDenied if ADOS refuses, CapabilityTimeout if the wait
        budget expires with the request still pending, and
        CapabilityOutcomeUnknown if ADOS cannot yet say whether the action
        happened (see that exception's own docstring — do not treat this as
        an ordinary failure to retry).

        THERE IS NO `idempotency_key` PARAMETER. P8 found the old one
        practically unreachable — nothing here ever set it, because nothing
        taught a mission it existed. P9 replaced it with a key ADOS computes
        itself, server-side, from the session and the real capability and
        arguments this call sends — the same two things this function already
        has no choice but to send for the request to mean anything. There is
        nothing left for this function, or the model driving it, to supply or
        substitute; a retry with byte-identical arguments is recognised and
        replayed automatically, without ADOS ever executing it twice.
        """
        payload: Dict[str, Any] = {"capability": capability, "arguments": arguments or {}}

        res = _decoded(await self.call_tool("request_capability", payload))

        if res.get("status") == "denied":
            raise CapabilityDenied(f"{capability}: {res.get('reason', 'no reason given')}")
        if res.get("status") == "outcome_unknown":
            raise CapabilityOutcomeUnknown(
                f"{capability}: {res.get('reason') or 'ADOS cannot confirm whether this action happened'} "
                f"(request {res.get('request_id')})"
            )
        # `executing` is a real but NON-FINAL status — it means a decision to
        # act was just durably recorded, not that the action has resolved yet
        # (P9). Falling through to `return res` for it here would hand the
        # caller a result that looks final but is not; treat it exactly like
        # `pending_approval` and wait for a real outcome instead.
        if res.get("status") in ("executed", "failed") or not wait:
            return res

        request_id = res["request_id"]
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_seconds)
            state = _decoded(
                await self.call_tool("get_capability_request", {"request_id": request_id})
            )
            status = state.get("status")
            if status == "denied":
                raise CapabilityDenied(f"{capability}: {state.get('reason', 'rejected by approver')}")
            if status == "outcome_unknown":
                raise CapabilityOutcomeUnknown(
                    f"{capability}: {state.get('reason') or 'ADOS cannot confirm whether this action happened'} "
                    f"(request {request_id})"
                )
            if status not in ("pending_approval", "executing"):
                return state
        raise CapabilityTimeout(
            f"{capability}: still awaiting approval after {timeout_seconds}s (request {request_id})"
        )


ados = Ados()

# Forward bare module access (`import ados; await ados.run_capability(...)`) to
# the instance, but never the names the kernel bootstrap probes — forwarding
# `run` would make it treat the module as a callable skill and break tool
# dispatch. This is the pattern the built-in integrations use.
_RESERVED = {"run", "__wrapped__", "__call__"}


def __getattr__(name):
    if name.startswith("_") or name in _RESERVED:
        raise AttributeError(name)
    return getattr(ados, name)
