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
import os
from typing import Any, Dict, Optional

from rlm import McpIntegration

__all__ = ["ados", "Ados", "CapabilityDenied", "CapabilityTimeout"]


class CapabilityDenied(RuntimeError):
    """ADOS refused the request — not in this mission's grant, or policy
    blocked it. Not retryable by rephrasing; the mission would have to grant
    the capability."""


class CapabilityTimeout(RuntimeError):
    """A human approval did not arrive inside the wait budget. The request is
    still pending in ADOS; it was not cancelled and may still be approved."""


class Ados(McpIntegration):
    server = "ados"
    url = os.environ.get("ADOS_MCP_URL", "http://host.docker.internal:8000/mcp")
    bearer_token_env = "ADOS_MCP_TOKEN"

    async def capabilities(self) -> list:
        """What this session is actually allowed to do, per ADOS.

        Ask before assuming: the grant is per-mission and resolved server-side,
        so it is not guessable from the objective text."""
        return await self.call_tool("list_capabilities", {})

    async def run_capability(
        self,
        capability: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
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
        budget expires with the request still pending.
        """
        payload: Dict[str, Any] = {"capability": capability, "arguments": arguments or {}}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        res = await self.call_tool("request_capability", payload)

        if res.get("status") == "denied":
            raise CapabilityDenied(f"{capability}: {res.get('reason', 'no reason given')}")
        if res.get("status") == "executed" or not wait:
            return res

        request_id = res["request_id"]
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_seconds)
            state = await self.call_tool("get_capability_request", {"request_id": request_id})
            status = state.get("status")
            if status == "denied":
                raise CapabilityDenied(f"{capability}: {state.get('reason', 'rejected by approver')}")
            if status != "pending_approval":
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
