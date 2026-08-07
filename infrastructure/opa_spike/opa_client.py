"""
Minimal async client for the OPA sidecar spike — queries a locally running
`opa run --server` process the same way a real policy-interception sidecar
deployment would (network call to a local PDP), using httpx to match the
project's existing HTTP client convention (integrations/connectors/*.py).
Not wired into the live ConnectorPolicyEngine; see
infrastructure/OPA_POLICY_SPIKE.md.
"""

from typing import Any, Dict

import httpx

from integrations.policy_engine import PolicyViolation


class OPAPolicySidecar:
    """Reuses one httpx.AsyncClient (real connection pooling/keep-alive)
    rather than opening a new connection per check — the fair way to
    measure a sidecar's steady-state overhead, not its TCP handshake cost."""

    def __init__(self, url: str = "http://localhost:8181", policy_path: str = "ados/policy_engine"):
        self._url = f"{url}/v1/data/{policy_path}"
        self._client = httpx.AsyncClient(timeout=5.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def check(self, call_input: Dict[str, Any]) -> None:
        """Same contract as a policy_engine.PolicyRule: raises
        PolicyViolation to deny, returns None to allow."""
        response = await self._client.post(self._url, json={"input": call_input})
        response.raise_for_status()
        result = response.json().get("result", {})

        if not result.get("allow", False):
            reasons = "; ".join(result.get("deny", [])) or "denied by OPA policy"
            raise PolicyViolation(reasons)


def capability_call_to_opa_input(call, capability_status: str | None) -> Dict[str, Any]:
    """Projects a real contracts.CapabilityCall into the JSON shape
    policy.rego expects — the same fields require_governance and
    hot_disable_policy_rule read off the call, not the whole object.

    Deliberately OMITS the "governance" key entirely rather than sending
    JSON null when call.governance is None — found via this spike that
    Rego's `not input.governance` only treats an *absent* key as falsy;
    an explicit `null` is a present, defined value and does NOT trip the
    rule (`not null` fails, so `deny` never fires). Passing null here was
    the first version of this function and silently let ungoverned calls
    through OPA while the in-process Python rule correctly denied them —
    see infrastructure/OPA_POLICY_SPIKE.md's "correctness pitfall" section.
    """
    result: Dict[str, Any] = {"capability": call.capability.value, "capability_status": capability_status}
    if call.governance is not None:
        result["governance"] = {
            "policyTier": int(call.governance.policy_tier),
            "approvedBy": call.governance.approved_by,
        }
    return result
