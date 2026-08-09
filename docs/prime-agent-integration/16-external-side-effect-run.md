# End-to-end run with a real external side effect

**Result: PASS.** One explicitly invoked run, one real ticket, created and
closed. Reproduce with:

```
set -a && source .env && set +a
./.venv/bin/python scripts/prime_agent_servicenow_e2e.py
```

Not a pytest test and never collected by one — `pytest` must not be able to
write to someone's ServiceNow instance as a side effect of running a suite.

```
mission   6a7c5991-bafc-4da2-8d16-0dc28f10ebcc
marker    [ADOS PRIME-AGENT INTEGRATION TEST] mission=6a7c5991-…
incident  INC0010027 (sys_id 98dd092283a68710be487765eeaad346)
verdict   ACCEPTED — mission accepted
elapsed   973.6s (budget 1800s)
```

Read [What this run also exposed](#what-this-run-also-exposed) before treating
the runtime as sound. The mission verdict is correct; two defects in the layers
around it are not.

---

## What was demonstrated

The whole chain, in one execution, with no mock at any layer:

```
Prime Agent container  ados-prime-218db5bd-66d on ados-runtime-net
  -> ADOS Python skill in the IPython kernel
  -> MCP HTTP gateway   host.docker.internal:8077/mcp/
  -> ADOS governance    session token -> mission -> server-side grant -> tier -> risk
  -> FetchIncidentEvidence          connector=mission-evidence
  -> the model reasons from the retrieved evidence
  -> NotifyITHelpdesk               connector=servicenow
  -> a real ServiceNow incident     INC0010027
  -> independent GET verification
  -> close (state 7), re-read to confirm
  -> ADOS execution records
  -> evaluate_mission() = ACCEPTED, from those records alone
```

The previous acceptance run proved the governed path with a simulated final
step. The external pytest test proved a real side effect while calling the hub
directly. Neither proved the chain end to end. This does.

## 1. Inside Prime Agent

```
runtime_session_id : 019fe809-3491-74eb-9361-bf9f0927294e
session state      : completed
kernel executions  : 4 reported (see the defect below — one actually ran)
```

The code the model ran, recorded by ADOS because the workspace is disposable:

```python
import ados
r = await ados.run_capability('FetchIncidentEvidence', {})
try:
    ev = r['result']['outcome']['output']['evidence']
    print(ev['symptom']); print(ev['app_log'])
    print(f"{ev['release_diff']} {ev['topology']}")
except KeyError:
    raise Exception('Incident evidence retrieval failed')

with open('/work/report.md', 'w') as f:
    f.write(f"[ADOS PRIME-AGENT INTEGRATION TEST] mission=… {ev['symptom']}: {ev['release_diff']}")
await ados.run_capability('NotifyITHelpdesk', {'summary': …})
```

## 2. What MCP returned

The gateway's own record of what it sent back — not the agent's account of it:

```
FetchIncidentEvidence  {"ok": true, "outcome": {"status": "succeeded",
                        "connector": "mission-evidence", "output": {"evidence": {…}}}}
NotifyITHelpdesk       {"ok": true, "outcome": {"status": "succeeded",
                        "connector": "servicenow",  "output": {"number": "INC0010027", …}}}
```

## 3. What governance allowed

```
mission grant (server-side, the runtime cannot widen it):
    ['FetchIncidentEvidence', 'NotifyITHelpdesk']

FetchIncidentEvidence   status=executed  tier=0 (autonomous)  risk=low
NotifyITHelpdesk        status=executed  tier=0 (autonomous)  risk=low
```

## 4. What connector executed

```
FetchIncidentEvidence   connector=mission-evidence  succeeded
NotifyITHelpdesk        connector=servicenow        succeeded
```

The run asserts `connector == "servicenow"` **before** treating the execution as
successful, and fails outright on a Console result. A `SUCCEEDED` from `console`
reads `"[console] simulated NotifyITHelpdesk"` — a green run in which nobody was
notified, which is the exact false-success class this integration exists to
prevent.

Selection is not left to chance in either direction: had ServiceNow been
unconfigured, the hub would have fallen back to Console and this run would have
**failed**, by design. Configuration is checked up front — a 404 on a sentinel
`sys_id` proves the instance answered and accepted the credentials, and 401/403
or a transport error aborts before a container is ever started.

## 5. What ServiceNow actually created

Read back with an independent GET. A 201 says ADOS sent something; reading the
record back says a ticket exists.

```
number            : INC0010027
sys_id            : 98dd092283a68710be487765eeaad346
opened_at         : 2026-08-09 19:54:03
short_description : [ADOS PRIME-AGENT INTEGRATION TEST] mission=6a7c5991-… 502 error
                    rate rose from 0.1% to 37% within 4 minutes: {'release': '2026.8.9-r…
description       : … Raised automatically by ADOS and approved through its
                    governance layer.
                    Mission: 6a7c5991-bafc-4da2-8d16-0dc28f10ebcc
                    Capability request: c0258072-47d5-409a-a036-f5050cc8b37b
                    Requested by: prime-runtime:mission:6a7c5991-…
```

Verified: `sys_id`, `number`, the run marker, and the mission id all match. The
`short_description` truncation at 160 characters is expected and the marker
survives because it is at the front — the full text is preserved in
`description`.

## 6. What ADOS recorded

```
mission.status       : completed
session.state        : completed
runtime_session_id   : 019fe809-3491-74eb-9361-bf9f0927294e
capability_requests  : 2, both status=executed, both written by the gateway

the audit row's sys_id matches the live record: True
```

## 7. Why evaluate_mission() accepted

```
tool_executions                4        (reported; see the defect below)
tool_successes                 4        (reported; only 1 was real)
capabilities_executed_by_ados  ['FetchIncidentEvidence', 'NotifyITHelpdesk']
required_capabilities          ['FetchIncidentEvidence', 'NotifyITHelpdesk']
session_state                  completed
```

Both required capabilities have `status='executed'` rows written by the gateway
that performed them. `evaluate_mission()` has no parameter for the agent's text
— no `final_answer`, no `report`, no `confidence` — and a test asserts that
signature.

**The narrative was partly wrong, and it did not matter.** The agent's final
answer claimed the incident had been "resolved… while maintaining SLA
compliance" and was "approved and now actively monitored". None of that
happened: ADOS created a ticket. Had the verdict been drawn from the report,
this run would have recorded a resolution that does not exist. It was drawn from
two rows instead.

## Cleanup

```
closed incident INC0010027 (state=7)
final external state (re-read): state=7  close_code=Resolved by caller
```

Closed, not deleted, and the PATCH's echo is trusted no further than any other
200 — the state is re-read from the instance. Cleanup failure exits non-zero and
prints the `sys_id`. Sweep across every marked record afterwards: **5 total, 0
open.**

## What this run also exposed

Both are recorded in [14-known-limitations.md](14-known-limitations.md) and both
are open.

1. **Kernel errors are counted as tool successes.** `ok=4 err=0` when three of
   the four executions raised `SyntaxError`. `isError` was `false` on all four;
   the kernel's real verdict was in `details.status`. `evaluate_mission()`'s
   `did_real_work` check is therefore currently blind to kernel failures.
2. **The request id written into the ticket resolves to nothing.** The gateway
   mints one id for the audit row and a different one for the `CapabilityCall`,
   and the ticket carries the latter.

Neither affects this verdict — it rests on capability rows, which cannot be
forged by miscounting — but the first means a check designed to catch fabricated
reports is not currently doing its job, and the second means a working-looking
audit trail has a dead link in it.

## What this run does NOT prove

* One run, one model (`qwen3-4b-16k` on local Ollama), one instance. Not a
  stability claim, and 973.6s is not a latency claim.
* The model needed four attempts to emit syntactically valid Python. It
  recovered without help, and no ADOS-side retry logic was involved, but this is
  a 4B local model and the cost shows.
* No human-approval round trip (both capabilities are tier 0).
* Egress is still placement, not filtering.
