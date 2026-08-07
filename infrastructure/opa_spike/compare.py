"""
Correctness + latency comparison: the existing in-process
integrations/policy_engine.py rules vs. the same logic re-implemented in
Rego and queried over HTTP from a local `opa run --server` sidecar
(policy.rego). Requires the OPA server running:

    opa run --server --addr localhost:8181 infrastructure/opa_spike/policy.rego

Run from the ADOS/ repo root:  ./.venv/bin/python infrastructure/opa_spike/compare.py
"""

import asyncio
import time

from contracts import Capability, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.policy_engine import PolicyViolation, require_governance

from opa_client import OPAPolicySidecar, capability_call_to_opa_input

sidecar = OPAPolicySidecar()


def in_process_verdict(call: CapabilityCall, capability_status: str | None) -> tuple[bool, str]:
    try:
        require_governance(call)
        if capability_status == "hot_disabled":
            raise PolicyViolation(f"capability {call.capability.value} is hot-disabled")
        return True, ""
    except PolicyViolation as exc:
        return False, exc.reason


async def opa_verdict(call: CapabilityCall, capability_status: str | None) -> tuple[bool, str]:
    try:
        await sidecar.check(capability_call_to_opa_input(call, capability_status))
        return True, ""
    except PolicyViolation as exc:
        return False, exc.reason


def make_call(governance: GovernanceInfo | None) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR,
        incident_id="INC-OPA-SPIKE-1",
        requested_by="infrastructure/opa_spike/compare.py",
        input={},
        governance=governance,
    )


SCENARIOS = [
    ("governed, active capability", make_call(GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS)), "active"),
    ("hot-disabled capability", make_call(GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS)), "hot_disabled"),
]

# CapabilityCall.governance is a required field on the contract itself
# (Pydantic rejects a None at construction) — require_governance's "missing
# governance" branch is exercised by IntegrationHub.invoke() building a
# CapabilityCall without one at all, not representable via make_call() here.
# The Rego side is still checked directly against that same input shape.
# Key OMITTED, not set to null — see opa_client.py's docstring for why.
MISSING_GOVERNANCE_OPA_INPUT = {"capability": "NotifyOperator", "capability_status": "active"}


async def main() -> None:
    print("=== Correctness ===")
    for label, call, status in SCENARIOS:
        py_allow, py_reason = in_process_verdict(call, status)
        opa_allow, opa_reason = await opa_verdict(call, status)
        match = "MATCH" if py_allow == opa_allow else "MISMATCH"
        print(f"[{match}] {label}: python={py_allow} ({py_reason!r})  opa={opa_allow} ({opa_reason!r})")

    opa_allow, opa_reason = True, ""
    try:
        await sidecar.check(MISSING_GOVERNANCE_OPA_INPUT)
    except PolicyViolation as exc:
        opa_allow, opa_reason = False, exc.reason
    print(f"[{'MATCH' if not opa_allow else 'MISMATCH'}] missing governance: python=False (contract-enforced)  opa={opa_allow} ({opa_reason!r})")

    print("\n=== Latency (avg over 200 calls, allow path) ===")
    call, status = SCENARIOS[0][1], SCENARIOS[0][2]

    n = 200
    start = time.perf_counter()
    for _ in range(n):
        in_process_verdict(call, status)
    py_ms = (time.perf_counter() - start) / n * 1000

    start = time.perf_counter()
    for _ in range(n):
        await opa_verdict(call, status)
    opa_ms = (time.perf_counter() - start) / n * 1000

    print(f"in-process Python rule: {py_ms:.4f} ms/call")
    print(f"OPA sidecar over HTTP:  {opa_ms:.4f} ms/call (pooled connection, keep-alive)")
    print(f"overhead: {opa_ms / py_ms:.0f}x")

    await sidecar.aclose()


if __name__ == "__main__":
    asyncio.run(main())
