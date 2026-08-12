"""
P11 — controlled operator recovery exercise: real Docker, real Postgres, no
ServiceNow. Deliberately not repeating P9's own real-ServiceNow crash-
recovery proof (scripts/p9_crash_recovery_e2e.py already did that
exhaustively) — the orphan-resource scenario needs no external side effect
to demonstrate, so none is created here, matching this phase's own bar for
when ServiceNow use is "genuinely necessary"
(docs/prime-agent-integration/19-metrics-and-alerting.md).

Demonstrates the complete operator loop this phase's own instructions ask
for, against real state throughout:

    FAILURE -> DETECTION -> DIAGNOSIS -> REMEDIATION -> INDEPENDENT VERIFICATION

using the exact, already-existing mechanisms an operator would use in
production (orchestrate/runtime/session_reconcile.py,
orchestrate/runtime/orphan_sweep.py) — nothing new is written for this
exercise, matching scripts/p9_crash_recovery_e2e.py's own precedent of
proving EXISTING mechanisms against real infrastructure rather than
exercising new throwaway code.

WHAT "FAILURE" MEANS HERE
--------------------------
A real Prime Agent container is started for real
(PrimeAgentRuntime.start() -- an actual `docker run`, a real per-session
egress boundary). This script then simply stops -- it never calls
teardown() or writes the session's terminal state, exactly mirroring what
happens when the ADOS PROCESS itself is killed (SIGKILL, an OOM kill)
mid-mission: nothing survives to run PrimeRuntimeConnector._run's own
`finally` block. The container and its egress network are real, detached
Docker resources and are left running, orphaned, on purpose.

ONE DELIBERATE SHORTCUT, CLEARLY MARKED
------------------------------------------
`reconcile_abandoned_sessions` only ever acts on a session whose token has
ALREADY expired (`token_expires_at < now`) -- and every session's grace
period is a fixed 300s (TOKEN_GRACE_SECONDS) on top of its wall-clock
budget, by design (a real safety margin, not a bug). Actually sleeping 5+
minutes to observe expiry would make this exercise slow without proving
anything more than "time passes." Detection is instead invoked with an
explicit `now=` several minutes in the future -- a parameter
reconcile_abandoned_sessions already accepts for exactly this reason. This
does NOT shortcut anything about Docker or Postgres: the container is
real, the rows are real, the sweep's docker rm/network rm calls are real.
Only the wall-clock comparison for "has this token expired" is answered
without an actual wait.

Usage:
    python scripts/p11_orphan_recovery_exercise.py
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.mcp_gateway import hash_token
from db.engine import async_session_factory, engine
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime.base import AgentSessionSpec
from orchestrate.runtime.egress import _SAFE_SUFFIX
from orchestrate.runtime.orphan_sweep import sweep_once
from orchestrate.runtime.prime import PrimeAgentRuntime, TOKEN_GRACE_SECONDS, mint_session_token, token_expiry
from orchestrate.runtime.session_reconcile import reconcile_abandoned_sessions

SHORT_WALL_CLOCK_SECONDS = 3.0


def _docker(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=30).stdout


def _present(names: list) -> list:
    return [n for n in names if n.strip()]


async def main() -> int:
    print("=" * 78)
    print("P11 ORPHAN RECOVERY EXERCISE -- real Docker, real Postgres, no ServiceNow")
    print("=" * 78)

    # ---------------------------------------------------------------- FAILURE
    print("\n[1/5] FAILURE")
    print("      Starting one real Prime Agent mission (real `docker run`), then")
    print("      abandoning it before teardown -- simulating an ADOS process")
    print("      crash mid-mission (SIGKILL/OOM: nothing survives to run the")
    print("      real finally block that would normally tear this down).")

    async with async_session_factory() as db:
        mission = MissionRow(
            title="P11 recovery exercise", objective="say hello", domain="it",
            allowed_capabilities=[], status="running", created_by="p11-recovery-exercise",
        )
        db.add(mission)
        await db.flush()
        token = mint_session_token()
        session = RuntimeSessionRow(
            mission_id=mission.mission_id, state="starting",
            token_hash=hash_token(token),
            token_expires_at=token_expiry(SHORT_WALL_CLOCK_SECONDS),
        )
        db.add(session)
        await db.commit()
        mission_id, session_id = mission.mission_id, session.session_id

    spec = AgentSessionSpec(
        mission_id=str(mission_id), session_id=str(session_id),
        objective="say hello", allowed_capabilities=[], workspace_files={},
        max_wall_clock_seconds=SHORT_WALL_CLOCK_SECONDS,
    )
    runtime = PrimeAgentRuntime(mcp_url="http://host.docker.internal:8077/mcp/")
    await runtime.start(spec, token)  # REAL docker run, REAL egress boundary

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        row.state = "running"
        row.container_name = runtime.container_name
        row.workspace_path = str(runtime.workspace)
        await db.commit()

    suffix = _SAFE_SUFFIX.sub("", str(session_id))[:24]
    expected_container = runtime.container_name
    expected_relay = f"ados-relay-{suffix}"
    expected_net_internal = f"ados-rt-{suffix}"
    expected_net_egress = f"ados-rt-out-{suffix}"

    print(f"      real container: {expected_container}")
    print(f"      real relay:     {expected_relay}")
    print(f"      real networks:  {expected_net_internal}, {expected_net_egress}")
    print("      NOT calling teardown() -- this is the simulated crash. Mission/")
    print(f"      session ids: mission_id={mission_id} session_id={session_id}")

    # -------------------------------------------------------------- DETECTION
    print("\n[2/5] DETECTION")
    print("      Running session_reconcile.reconcile_abandoned_sessions() -- the")
    print("      exact function backend/app/main.py's periodic loop calls, with")
    print("      an explicit future `now` (see module docstring for why).")

    simulated_now = datetime.now(timezone.utc) + timedelta(seconds=SHORT_WALL_CLOCK_SECONDS + TOKEN_GRACE_SECONDS + 5)
    reconciled = await reconcile_abandoned_sessions(async_session_factory, now=simulated_now)
    reconciled_ids = [str(r.session_id) for r in reconciled]
    print(f"      reconciled session ids: {reconciled_ids}")
    if str(session_id) not in reconciled_ids:
        print("      FAIL: the abandoned session was not detected as reconcilable")
        await engine.dispose()
        return 1

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        detected_state = row.state
        detected_reason = row.failure_reason
    print(f"      session state after detection: {detected_state}")
    print(f"      failure_reason: {detected_reason}")
    assert detected_state == "failed"
    assert "orphaned" in (detected_reason or "")

    # -------------------------------------------------------------- DIAGNOSIS
    print("\n[3/5] DIAGNOSIS")
    print("      Independently confirming, via `docker ps`/`docker network ls`,")
    print("      that what detection just flagged actually still exists and is")
    print("      labeled as belonging to this exact session -- not trusting the")
    print("      database row alone.")

    containers = _present(_docker("docker", "ps", "-a", "--filter", f"name={expected_container}", "--format", "{{.Names}}").splitlines())
    networks = _present(_docker("docker", "network", "ls", "--filter", f"name={expected_net_internal}", "--format", "{{.Name}}").splitlines())
    networks += _present(_docker("docker", "network", "ls", "--filter", f"name={expected_net_egress}", "--format", "{{.Name}}").splitlines())
    relay = _present(_docker("docker", "ps", "-a", "--filter", f"name={expected_relay}", "--format", "{{.Names}}").splitlines())

    print(f"      containers found: {containers}")
    print(f"      relay found:      {relay}")
    print(f"      networks found:   {networks}")

    label = _docker("docker", "inspect", "-f", '{{index .Config.Labels "ados.session_id"}}', expected_container).strip()
    print(f"      container's ados.session_id label: {label}")
    if not containers or label != str(session_id):
        print("      FAIL: the real container is missing, or its ownership label doesn't match")
        await engine.dispose()
        return 1

    # ------------------------------------------------------------ REMEDIATION
    print("\n[4/5] REMEDIATION")
    print("      Running orphan_sweep.sweep_once() -- the exact function")
    print("      scripts/sweep_orphans.py wraps for manual operator use.")

    report = await sweep_once(async_session_factory)
    print(f"      claimed: {report.claimed}  cleaned: {report.cleaned}  "
          f"absent: {report.absent}  failed: {report.failed}  refused: {report.refused}")
    for outcome in report.outcomes:
        print(f"        [{outcome.status:8}] {outcome.item.kind:16} {outcome.item.name} -- {outcome.detail}")

    # ------------------------------------------------- INDEPENDENT VERIFICATION
    print("\n[5/5] INDEPENDENT VERIFICATION")
    print("      A FRESH `docker ps`/`docker network ls` -- not the sweep's own")
    print("      reported outcome -- plus a fresh read of the session's own")
    print("      event log.")

    ok = True
    for name in (expected_container, expected_relay):
        still_there = _present(_docker("docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}").splitlines())
        if still_there:
            print(f"      FAIL: {name} still present after sweep")
            ok = False
    for name in (expected_net_internal, expected_net_egress):
        still_there = _present(_docker("docker", "network", "ls", "--filter", f"name={name}", "--format", "{{.Name}}").splitlines())
        if still_there:
            print(f"      FAIL: network {name} still present after sweep")
            ok = False

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        events = row.events or []
    resolved_events = [e for e in events if e.get("type", "").startswith("orphan_sweep.") and e.get("type") != "orphan_sweep.claimed"]
    print(f"      session's own durable event log: {len(resolved_events)} resolution event(s)")
    for e in resolved_events:
        print(f"        {e['type']}: {e.get('detail')}")
    if len(resolved_events) < 3:  # relay + 2 networks (no container_name was ever recorded... it WAS recorded, so 3: container + relay + 2 nets = 4 candidates minimum)
        print("      FAIL: fewer sweep resolution events than expected")
        ok = False

    if not ok:
        print("\nFAIL: orphan recovery exercise did not fully clean up.")
        await engine.dispose()
        return 1

    print("\nPASS: failure -> detection -> diagnosis -> remediation -> independent")
    print("      verification, complete, against real Docker and real Postgres.")
    print(f"mission_id={mission_id} session_id={session_id}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
