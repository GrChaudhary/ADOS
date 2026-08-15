"""
EXPLICIT END-TO-END DEMONSTRATION — this MUTATES a real ServiceNow instance.

    set -a && source .env && set +a
    ./.venv/bin/python scripts/prime_agent_servicenow_e2e.py

NOT a pytest test, and deliberately not importable as one. `pytest` must never
create a real incident as a side effect of running a suite, so this lives in
scripts/ and has to be invoked by a human who meant it. The safe, mocked
coverage of the same connector is backend/tests/test_notify_it_helpdesk_servicenow.py.

WHAT THIS RUN PROVES THAT NOTHING ELSE DOES
-------------------------------------------
The acceptance run proved the governed path with a simulated final step. The
external pytest test proved a real side effect while calling the hub directly.
Neither proved the whole chain in one unbroken execution. This does:

    Prime Agent container
      -> ADOS Python skill (in the kernel)
      -> MCP HTTP gateway
      -> ADOS governance (session auth, server-side grant, policy, risk)
      -> FetchIncidentEvidence            (evidence ADOS holds, agent does not)
      -> the model reasons FROM the retrieved evidence
      -> NotifyITHelpdesk
      -> ServiceNowConnector
      -> a real ServiceNow incident
      -> independent GET verification
      -> close/resolve the incident
      -> ADOS execution records
      -> evaluate_mission() decides, from those records alone

NO SILENT FALLBACK. If ServiceNow is missing, unreachable, or misconfigured,
this run FAILS. It never falls back to ConsoleConnector and never reports a
simulated success, because a green run that notified nobody is precisely the
false-success class this whole integration exists to prevent. The connector
that ran is asserted to be `servicenow` BEFORE the execution is treated as
successful.

THE VERDICT IS NOT THE AGENT'S TO GIVE. evaluate_mission() sees the observed
session outcome and the capability rows ADOS wrote — never the agent's report.

CLEANUP. The incident is CLOSED (state 7), not deleted: closing is the normal
ServiceNow lifecycle and preserves the audit trail this run exists to produce.
Every record carries a marker containing the mission id, so anything orphaned
by an interrupted run is trivially findable. If cleanup fails, this exits
non-zero and prints the sys_id in a form you cannot miss.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from backend.app.mcp_gateway import hash_token
from db.engine import async_session_factory, engine
from db.tenancy import all_tenants_session  # P17 -- see p15_multiprocess_concurrency_proof.py's identical reasoning
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from orchestrate.runtime.acceptance import evaluate_mission
from orchestrate.runtime.base import AgentSessionSpec
from orchestrate.runtime.build_identity import REPO_ROOT, verify_gateway_matches_source
from orchestrate.runtime.prime import PrimeAgentRuntime, mint_session_token, token_expiry

ADOS_HTTP = "http://127.0.0.1:8077"
MCP_URL = "http://host.docker.internal:8077/mcp/"
MARKER = "[ADOS PRIME-AGENT INTEGRATION TEST]"
REQUIRED = ["FetchIncidentEvidence", "NotifyITHelpdesk"]

# The case file. Lives ONLY in ADOS — never written into the workspace. Ground
# truth: connection-pool exhaustion, DB_POOL_SIZE 10 -> 100 across 6 pods
# against max_connections=200. An agent that cannot execute its tool cannot
# reach any of this, which is what makes a fabricated report detectable in SQL.
EVIDENCE = {
    "incident_id": "SYN-4417",
    "service": "checkout-api",
    "started_at": "2026-08-09T09:14:00Z",
    "symptom": "502 error rate rose from 0.1% to 37% within 4 minutes",
    "deploy_log": [
        "09:12 UTC  release 2026.8.9-rc3 rolled out to 6/6 pods",
        "09:13 UTC  connection pool warnings begin",
        "09:14 UTC  502 rate climbs",
    ],
    "app_log": [
        "ERROR asyncpg.exceptions.TooManyConnectionsError: too many clients already",
        "ERROR pool timeout acquiring connection after 5.0s",
        "WARN  pool size=100 in_use=100 waiters=284",
    ],
    "release_diff": {
        "release": "2026.8.9-rc3",
        "changes": [{"setting": "DB_POOL_SIZE", "before": 10, "after": 100}],
    },
    "topology": {"pods": 6, "postgres_max_connections": 200},
}


class RunFailed(Exception):
    """A demonstration that did not demonstrate what it claims to. Raised
    rather than returned so no later step can proceed on a false premise."""


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


_BOUNDARY_PROBE = r"""
import socket, sys
gw_host, gw_port, m_host, m_port = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
def reach(host, port):
    try:
        s = socket.create_connection((host, port), timeout=4); s.close(); return "REACHABLE"
    except Exception as e:
        return f"BLOCKED({type(e).__name__})"
def resolves(name):
    try:
        return socket.gethostbyname(name)
    except Exception as e:
        return f"NO-RESOLVE({type(e).__name__})"
print("ROUTE_COUNT", open("/proc/net/route").read().count("\n") - 1)
print("DNS_EXTERNAL", resolves("example.com"))
print("IP_DIRECT_1111", reach("1.1.1.1", 443))
print("IP_DIRECT_8888", reach("8.8.8.8", 53))
print("ALLOWED_GATEWAY", reach(gw_host, gw_port))
print("ALLOWED_MODEL", reach(m_host, m_port))
print("HOST_POSTGRES_5432", reach(gw_host, 5432))
print("HOST_SSH_22", reach(gw_host, 22))
"""


async def _probe_boundary(runtime: PrimeAgentRuntime) -> Dict[str, str]:
    """Measure the network boundary from inside the live mission container."""
    destinations = runtime.egress.destinations
    gateway = destinations[0]
    model = destinations[1] if len(destinations) > 1 else destinations[0]
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", runtime.container_name,
        "/home/prime/kernel-venv/bin/python", "-c", _BOUNDARY_PROBE,
        gateway.host, str(gateway.port), model.host, str(model.port),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
    return dict(
        line.split(" ", 1)
        for line in out.decode(errors="replace").splitlines()
        if " " in line
    )


async def _preflight(connector: ServiceNowConnector) -> None:
    """FAIL, never skip. Being asked to demonstrate a real external side effect
    without an external system to demonstrate it against is a failure of the
    request — reporting success would be the exact lie this run guards against.

    Reachability is probed through the connector's own `fetch_record` rather
    than a second HTTP client: a 404 for a sentinel sys_id proves the instance
    answered and accepted the credentials, while 401/403 and transport errors
    are each distinguishable in the message.
    """
    if not connector.is_configured():
        raise RunFailed(
            "ServiceNow is not configured. Set SERVICENOW_INSTANCE_URL, "
            "SERVICENOW_USERNAME, SERVICENOW_PASSWORD (e.g. `set -a && source .env`). "
            "This run must not fall back to the console connector."
        )

    ok, detail = await connector.fetch_record("incident", "0" * 32)
    if ok:
        return  # improbable, but a real record answering is still a live instance
    error = str(detail.get("error", ""))
    if "404" in error:
        print("[0] preflight  ServiceNow reachable and authenticated")
        return
    raise RunFailed(f"ServiceNow preflight failed: {error}. Refusing to start a run that cannot finish.")


def _objective(marker: str) -> str:
    return (
        "Incident SYN-4417 on checkout-api is under investigation. You have NOT been "
        "given the incident data — ADOS holds it.\n\n"
        "Your tool is a PERSISTENT IPYTHON KERNEL. Everything you send it is\n"
        "plain Python source, executed directly in that kernel. Top-level `await`\n"
        "works. Do NOT use `!` shell escapes, do NOT use `%%bash`, and do NOT try\n"
        "to invoke `python` as a program — there is no `python` on PATH and the\n"
        "kernel IS the interpreter. Variables persist between cells.\n\n"
        "Use exactly TWO kernel cells. Do not explore, do not read skill files.\n\n"
        "Cell 1 — fetch the evidence and keep it in a variable. Print ONLY the\n"
        "small parts you need to reason about, not the whole payload:\n"
        "    import ados\n"
        "    r = await ados.run_capability('FetchIncidentEvidence', {})\n"
        "    ev = r['result']['outcome']['output']['evidence']\n"
        "    print(ev['symptom'])\n"
        "    print(ev['app_log'])\n"
        "    print(ev['release_diff'], ev['topology'])\n\n"
        "Cell 2 — having READ the values above, write the report and notify the IT\n"
        "helpdesk. `ev` is still in the kernel, so use it directly.\n\n"
        "The notification raises a REAL ticket in a live IT service management\n"
        "system, so the summary MUST begin with this exact tag, character for\n"
        "character, so the ticket can be traced back to this run:\n\n"
        f"    {marker}\n\n"
        "After the tag, add ONE SHORT sentence naming the root cause and the\n"
        "numbers that support it. Keep it under 70 characters — the ticket's\n"
        "summary field is short and anything longer is truncated.\n\n"
        "    open('/work/report.md','w').write(<your full root-cause report, "
        "quoting the specific values that support it>)\n"
        f"    await ados.run_capability('NotifyITHelpdesk', {{'summary': "
        f"'{marker} ' + '<one short root-cause line>'}})\n\n"
        "Then give your final answer.\n\n"
        "If you cannot retrieve the evidence, stop and report that you could not. "
        "Do not infer, guess, or reconstruct what the incident probably was."
    )


async def main() -> int:
    started = time.time()

    # First, before anything else: is the running gateway actually serving
    # this source tree? See scripts/prime_agent_approval_e2e.py's identical
    # preflight (P7-B) and orchestrate/runtime/build_identity.py.
    actual_build = verify_gateway_matches_source(ADOS_HTTP, REPO_ROOT)
    print(f"[preflight] gateway build verified: {actual_build.label} (matches expected source)")

    connector = ServiceNowConnector()
    await _preflight(connector)

    # The marker is generated BEFORE the run and carries the mission id, so an
    # orphaned ticket from an interrupted run is unambiguous without needing
    # anything ADOS recorded. mission_id is client-side (MissionRow defaults to
    # uuid.uuid4) precisely so it can be embedded in the objective.
    mission_id = uuid.uuid4()
    marker = f"{MARKER} mission={mission_id}"
    print(f"[0] marker     {marker}")

    async with all_tenants_session(async_session_factory) as db:
        mission = MissionRow(
            mission_id=mission_id,
            title=f"{MARKER} Root-cause the checkout-api 502 incident (SYN-4417)",
            objective=_objective(marker),
            domain="it",
            allowed_capabilities=REQUIRED,
            evidence=EVIDENCE,
            status="running",
            created_by="prime-agent-servicenow-e2e",
        )
        db.add(mission)
        await db.flush()
        token = mint_session_token()
        sess = RuntimeSessionRow(
            mission_id=mission_id, state="starting", token_hash=hash_token(token),
            # Same lifecycle as the production path, so these runs exercise
            # the expiry rather than a NULL that is never checked.
            token_expires_at=token_expiry(1800.0),
        )
        db.add(sess)
        await db.commit()
        session_id, objective = sess.session_id, mission.objective

    print(f"[1] mission    {mission_id}   evidence held by ADOS, not in the workspace")
    print(f"[2] session    {session_id}   token minted, only its SHA-256 stored")

    spec = AgentSessionSpec(
        mission_id=str(mission_id),
        session_id=str(session_id),
        objective=objective,
        success_criteria=(
            "The incident evidence was retrieved from ADOS, /work/report.md names the "
            "root cause with the values that support it, and the IT helpdesk was notified."
        ),
        allowed_capabilities=REQUIRED,
        workspace_files={},  # deliberately empty: no facts handed over
        max_wall_clock_seconds=1800.0,
    )

    runtime = PrimeAgentRuntime(
        mcp_url=MCP_URL,
        provider="ollama-local",
        model="qwen3-4b-16k:latest",
        provider_key_env="OLLAMA_API_KEY",
        provider_key="ollama",
        models_json={
            "providers": {
                "ollama-local": {
                    "baseUrl": "http://host.docker.internal:11434/v1",
                    "api": "openai-completions",
                    "apiKey": "OLLAMA_API_KEY",
                    "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
                    "models": [{"id": "qwen3-4b-16k:latest"}],
                }
            }
        },
    )

    report = None
    try:
        await runtime.start(spec, token)
        print(f"[3] container  {runtime.container_name} on {runtime.egress.internal_network} "
              f"(--internal; egress allowlist: "
              f"{', '.join(f'{d.host}:{d.port}' for d in runtime.egress.destinations)})")
        print(f"[4] workspace  {runtime.workspace} (empty of facts)")

        # The egress boundary, probed from INSIDE the live mission container —
        # not from its configuration. A `--network` argument is a claim; what
        # matters is what this process can open a socket to while the mission
        # is actually running.
        boundary = await _probe_boundary(runtime)
        print("[4b] egress boundary, measured inside the running container:")
        for key, value in boundary.items():
            print(f"       {key:34} {value}")
        if boundary.get("ROUTE_COUNT") != "1":
            raise RunFailed(f"the runtime has a default route — the boundary is not in force: {boundary}")
        if not boundary.get("DNS_EXTERNAL", "").startswith("NO-RESOLVE"):
            raise RunFailed(f"external DNS resolves inside the runtime: {boundary}")
        for probe in ("IP_DIRECT_1111", "IP_DIRECT_8888"):
            if not boundary.get(probe, "").startswith("BLOCKED"):
                raise RunFailed(f"{probe} is reachable — arbitrary egress is not blocked: {boundary}")
        for probe in ("ALLOWED_GATEWAY", "ALLOWED_MODEL"):
            if boundary.get(probe) != "REACHABLE":
                raise RunFailed(
                    f"{probe} is not reachable; the mission cannot run and the boundary is "
                    f"blocking what it is supposed to permit: {boundary}"
                )

        async with all_tenants_session(async_session_factory) as db:
            row = await db.get(RuntimeSessionRow, session_id)
            row.state, row.container_name = "running", runtime.container_name
            row.workspace_path = str(runtime.workspace)
            await db.commit()

        print("[5] objective sent over RPC, consuming the event stream...")
        outcome = await runtime.run_objective(spec)
        print(
            f"[6] runtime finished: state={outcome.state.value} "
            f"tools={outcome.tool_execution_count} ok={outcome.tool_success_count} "
            f"err={outcome.tool_error_count}"
        )

        rp = runtime.workspace / "report.md"
        if rp.exists():
            report = rp.read_text()

        async with all_tenants_session(async_session_factory) as db:
            requests = (
                await db.execute(
                    select(CapabilityRequestRow)
                    .where(CapabilityRequestRow.mission_id == mission_id)
                    .order_by(CapabilityRequestRow.created_at)
                )
            ).scalars().all()
            executed = [r.capability for r in requests if r.status == "executed"]
            verdict = evaluate_mission(
                outcome=outcome,
                executed_capabilities=executed,
                required_capabilities=REQUIRED,
            )
            print(
                f"[7] ADOS verdict: {'ACCEPTED' if verdict.succeeded else 'REJECTED'} "
                f"— {verdict.summary}"
            )

            row = await db.get(RuntimeSessionRow, session_id)
            row.state = outcome.state.value
            row.runtime_session_id = outcome.runtime_session_id
            row.tool_execution_count = outcome.tool_execution_count
            row.capability_request_count = len(executed)
            row.failure_reason = outcome.failure_reason
            row.events = [{"type": e.type, "at": e.at, "detail": e.detail} for e in outcome.events]

            m = await db.get(MissionRow, mission_id)
            m.status = "completed" if verdict.succeeded else "failed"
            m.result = outcome.final_answer  # narrative, stored, never consulted
            m.failure_reason = None if verdict.succeeded else verdict.summary
            await db.commit()
    finally:
        await runtime.teardown()
        print("[8] container removed, workspace deleted")

    # ---------------------------------------------------------------- trace --
    async with all_tenants_session(async_session_factory) as db:
        m = await db.get(MissionRow, mission_id)
        s = await db.get(RuntimeSessionRow, session_id)
        requests = (
            await db.execute(
                select(CapabilityRequestRow)
                .where(CapabilityRequestRow.mission_id == mission_id)
                .order_by(CapabilityRequestRow.created_at)
            )
        ).scalars().all()

    _rule("1. INSIDE PRIME AGENT — what the runtime did (observed, not self-reported)")
    print(f"runtime_session_id : {s.runtime_session_id}")
    print(f"session state      : {s.state}")
    print(f"kernel executions  : {outcome.tool_execution_count} "
          f"(ok {outcome.tool_success_count}, err {outcome.tool_error_count}, "
          f"indeterminate {outcome.tool_unknown_count})")

    # Per-execution kernel verdicts, taken from `details.status` rather than
    # `isError`. The previous run reported 4/4 successes while three cells
    # raised SyntaxError, because `isError` answers "did the tool throw?".
    print("\nkernel verdicts (from details.status, NOT isError):")
    for event in outcome.events:
        if event.type == "runtime.tool.finished":
            detail = event.detail or {}
            print(f"  verdict={detail.get('kernel_verdict')!s:<8} "
                  f"details.status={detail.get('kernel_status')!s:<8} "
                  f"isError={detail.get('isError')!s:<6} "
                  f"{('error=' + str(detail.get('kernel_error'))) if detail.get('kernel_error') else ''}")

    print("\nmodel calls:")
    for event in outcome.events:
        if event.type == "runtime.model.message":
            usage = (event.detail or {}).get("usage") or {}
            if usage:
                print(f"  in={usage.get('input')} out={usage.get('output')} "
                      f"cacheRead={usage.get('cacheRead')} total={usage.get('totalTokens')}")
    for e in outcome.events:
        if e.type == "runtime.tool.started":
            code = (e.detail or {}).get("code")
            if code:
                print("\n--- code the model sent to the kernel ---")
                print(code)
    print("\n--- agent final answer (NARRATIVE, NOT EVIDENCE) ---")
    print((m.result or "(none)")[:1200])
    if report:
        print("\n--- /work/report.md (artifact, recovered before teardown) ---")
        print(report[:1200])

    _rule("2. WHAT MCP RETURNED — the gateway's own record of what it sent back")
    for r in requests:
        print(f"\n{r.capability}: {json.dumps(r.result)[:600] if r.result else '(no result)'}")

    _rule("3. WHAT ADOS GOVERNANCE ALLOWED")
    print(f"mission grant (server-side, runtime cannot widen it): {m.allowed_capabilities}")
    for r in requests:
        print(f"  {r.capability:26} status={r.status:10} tier={r.policy_tier} risk={r.risk_class}"
              + (f"  reason={r.reason}" if r.reason else ""))

    _rule("4. WHAT CONNECTOR EXECUTED")
    notify_row = None
    for r in requests:
        out = (r.result or {}).get("outcome") or {}
        print(f"  {r.capability:26} connector={out.get('connector')} status={out.get('status')}")
        if r.capability == "NotifyITHelpdesk" and r.status == "executed":
            notify_row = r

    # THE ASSERTION THAT MAKES THIS RUN MEAN ANYTHING. A SUCCEEDED from
    # `console` reads "[console] simulated NotifyITHelpdesk" — a green run in
    # which nobody was notified.
    if notify_row is None:
        raise RunFailed("NotifyITHelpdesk was never executed by ADOS — nothing to verify.")
    notify_outcome = (notify_row.result or {}).get("outcome") or {}
    if notify_outcome.get("connector") != "servicenow":
        raise RunFailed(
            f"NotifyITHelpdesk ran on connector {notify_outcome.get('connector')!r}, not "
            "'servicenow'. A console result is a simulated success and fails this run."
        )
    sys_id = (notify_outcome.get("output") or {}).get("sys_id")
    number = (notify_outcome.get("output") or {}).get("number")
    if not sys_id or not number:
        raise RunFailed(f"ServiceNow returned no identifiers: {notify_outcome.get('output')}")

    ok_run = True
    try:
        _rule("5. WHAT SERVICENOW ACTUALLY CREATED — read back independently")
        # A 201 says ADOS sent something. Reading the record back says a ticket
        # exists. Only the second is evidence.
        ok, record = await connector.fetch_record("incident", sys_id)
        if not ok:
            raise RunFailed(f"could not read incident {number} back from ServiceNow: {record}")
        print(f"number            : {record.get('number')}")
        print(f"sys_id            : {record.get('sys_id')}")
        print(f"short_description : {record.get('short_description')}")
        print(f"state             : {record.get('state')}")
        print(f"opened_at         : {record.get('opened_at')}")
        print(f"description       :\n{record.get('description')}")

        if record.get("number") != number:
            raise RunFailed(f"read back {record.get('number')}, expected {number}")
        if marker not in (record.get("short_description") or ""):
            raise RunFailed(
                "the ticket exists but does not carry this run's marker: "
                f"short_description={record.get('short_description')!r}"
            )
        if str(mission_id) not in (record.get("description") or ""):
            raise RunFailed(
                "provenance missing: an operator could not trace this ticket to its mission"
            )

        # The canonical request id, followed the way an operator would: take the
        # id ADOS wrote into the ticket and look it up. The previous run's
        # ticket carried an id that resolved to nothing (fixed in 4edbb6b);
        # this is the check that would have caught it.
        description = record.get("description") or ""
        if "Capability request: " not in description:
            raise RunFailed("the ticket carries no capability request id")
        in_ticket = description.split("Capability request: ")[1].split("\n")[0].strip()
        async with all_tenants_session(async_session_factory) as db:
            resolved = await db.get(CapabilityRequestRow, uuid.UUID(in_ticket))
        if resolved is None:
            raise RunFailed(
                f"the request id in the ticket ({in_ticket}) resolves to no capability_requests "
                "row — provenance that does not resolve is worse than none"
            )
        if str(resolved.request_id) != str(notify_row.request_id):
            raise RunFailed(
                f"the ticket points at {in_ticket}, but the executing row is {notify_row.request_id}"
            )
        print(f"\nVERIFIED: sys_id, number, marker, and mission id all match.")
        print(f"VERIFIED: ticket request id {in_ticket} resolves to the executing audit row "
              f"({resolved.capability}, status={resolved.status}).")

        _rule("6. WHAT ADOS RECORDED")
        print(f"mission.status         : {m.status}")
        print(f"mission.failure_reason : {m.failure_reason}")
        print(f"session.state          : {s.state}")
        print(f"runtime_session_id     : {s.runtime_session_id}")
        print(f"capability_requests    : {len(requests)}")
        for r in requests:
            out = (r.result or {}).get("outcome") or {}
            print(f"  - {r.capability}  request_id={r.request_id}  status={r.status}")
            print(f"      connector={out.get('connector')} connector_status={out.get('status')}")
            print(f"      output={json.dumps(out.get('output'))[:280]}")
        print(f"\nthe audit row's sys_id matches the live record: "
              f"{notify_outcome['output'].get('sys_id') == record.get('sys_id')}")

        _rule("7. WHY evaluate_mission() DECIDED WHAT IT DECIDED")
        print(f"verdict   : {'ACCEPTED' if verdict.succeeded else 'REJECTED'}")
        print(f"summary   : {verdict.summary}")
        print("observed  :")
        for k, v in verdict.observed.items():
            print(f"    {k:32} {v}")
        print(
            "\nevaluate_mission() received the observed SessionOutcome, the capability\n"
            "names ADOS recorded as executed, and the mission's requirements. It has no\n"
            "parameter for the agent's text — no final_answer, no report, no confidence."
        )
        if not verdict.succeeded:
            ok_run = False
    except RunFailed:
        ok_run = False
        raise
    finally:
        # ------------------------------------------------------- cleanup ----
        _rule("CLEANUP — close the incident and confirm the external state")
        closed, detail = await connector.resolve_record(
            "incident",
            sys_id,
            close_notes=f"{marker} — automated cleanup after the ADOS end-to-end run. No action required.",
        )
        if not closed:
            ok_run = False
            print(f"\n*** LEFT AN OPEN RECORD IN SERVICENOW: {number} (sys_id {sys_id}) ***")
            print(f"*** Cleanup failed: {detail} ***")
            print(f"*** Close it manually. It is tagged: {marker} ***")
        else:
            print(f"closed incident {number} (state={detail})")
            # Trust the PATCH's echo no further than any other 200: read it back.
            ok, final = await connector.fetch_record("incident", sys_id)
            final_state = final.get("state") if ok else None
            print(f"final external state (re-read): state={final_state} "
                  f"close_code={final.get('close_code') if ok else '?'}")
            if not ok or str(final_state) != "7":
                ok_run = False
                print(f"\n*** INCIDENT {number} (sys_id {sys_id}) IS NOT CLOSED. "
                      f"state={final_state}. Close it manually; it is tagged {marker} ***")

    elapsed = time.time() - started
    _rule(f"RESULT: {'PASS' if ok_run else 'FAIL'}   ({elapsed:.1f}s)")
    print(f"mission   {mission_id}")
    print(f"incident  {number} (sys_id {sys_id}) — created, verified, closed")
    await engine.dispose()
    return 0 if ok_run else 1


if __name__ == "__main__":
    from orchestrate.runtime.build_identity import StaleGatewayError

    try:
        raise SystemExit(asyncio.run(main()))
    except StaleGatewayError as exc:
        print(f"\n*** PREFLIGHT FAILED (stale gateway): {exc}", file=sys.stderr)
        raise SystemExit(1)
    except RunFailed as exc:
        print(f"\n*** RUN FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
