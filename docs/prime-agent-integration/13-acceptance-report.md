# Acceptance Report — end-to-end governed mission

**Result: PASS.** Every value below is read from ADOS's own database rows, not
from the agent's account of itself.

```
mission.status        : completed
ADOS verdict          : ACCEPTED — mission accepted
executed capabilities : ['FetchIncidentEvidence', 'NotifyITHelpdesk']
required              : ['FetchIncidentEvidence', 'NotifyITHelpdesk']
elapsed               : 281.6s   (budget 1800s)
```

Read [Caveats](#caveats-what-this-does-not-prove) before treating this as more
than it is. One of the two capabilities executed against a **simulated**
connector.

---

## Environment

| | |
|---|---|
| Date | 2026-08-10 |
| Image | `ados-prime-runtime:0.7.1`, built from Prime Agent source (v0.7.1) |
| Container | `ados-prime-70973644-d15`, non-root uid 10001, `--memory 2g --cpus 2 --pids-limit 512` |
| Network | `ados-runtime-net` (dedicated bridge), `host.docker.internal:host-gateway` |
| Provider | Ollama, local |
| Model | `qwen3-4b-16k:latest` (`FROM qwen3:4b` + `PARAMETER num_ctx 16384`) |
| Gateway | ADOS MCP over HTTP at `host.docker.internal:8077/mcp/` |
| Budget | 1800s wall clock |
| Workspace | temp dir, bind-mounted at `/work`, **seeded with no facts** |

Secrets injected into the container: the provider key and `ADOS_MCP_TOKEN`.
No database URL, no connector credentials, no ADOS user identity.

## Mission

Root-cause synthetic incident SYN-4417 (checkout-api 502s). The incident data
lives **only** on `missions.evidence` and is reachable only through the
`FetchIncidentEvidence` capability. The workspace contained no incident file.

Ground truth: `DB_POOL_SIZE` raised 10 → 100 across 6 pods against
`max_connections = 200`.

## Execution timeline

| # | Event | Detail |
|---|---|---|
| 1 | mission created | `b2ca8fca-a9c1-438a-b4ae-4254bef36e46` |
| 2 | session created | `70973644-d155-4cdc-902d-9ce841812d04`, token minted, **only its SHA-256 stored** |
| 3 | container started | on `ados-runtime-net` |
| 4 | workspace prepared | empty of facts |
| 5 | objective sent | JSONL over `docker exec -i … --mode rpc` |
| 6 | model call 1 | 4,628 in / 5,157 out, `cacheRead 0`, 209.6s |
| 7 | kernel tool call | `isError=false`, result 1,868 chars |
| 8 | model call 2 | 10,130 in / 616 out, `cacheRead 0`, 57.4s |
| 9 | session completed | 4 model calls, 1 tool call, 1 success, 0 failures |
| 10 | teardown | container removed, workspace deleted |

Event span 268.3s; total 281.6s.

### The code the model ran

Recorded by ADOS as `runtime.tool.started.code` — the workspace is disposable,
so if ADOS does not record this it is gone:

```python
import ados
r = await ados.run_capability('FetchIncidentEvidence', {})
ev = r['result']['outcome']['output']['evidence']
print(ev['symptom'])
print(ev['app_log'])
print(ev['release_diff'], ev['topology'])

open('/work/report.md', 'w').write(f"Root cause: {ev['symptom']}. App log: {ev['app_log']}. Release diff: {ev['release_diff']}. Topology: {ev['topology']}.")
await ados.run_capability('NotifyITHelpdesk', {'summary': f"Root cause: {ev['symptom']}"})
```

One cell: retrieve, reason, write, act.

## Capability execution records

Written by the gateway that performed the call — never by the runtime.

**1. FetchIncidentEvidence**

```
request_id : bcf88eaf-c326-4a51-bfd9-4c41fb5d9201
status     : executed
policy tier: 0 (autonomous)   risk class: low
connector  : mission-evidence
connector status: succeeded
output     : {"mission_id": "b2ca8fca-…", "evidence": {"incident_id": "SYN-4417",
              "service": "checkout-api", "symptom": "502 error rate rose from
              0.1% to 37% within 4 minutes", …}}
```

**2. NotifyITHelpdesk**

```
request_id : 7569b17e-58a5-49cf-974a-ebcec96f296a
status     : executed
policy tier: 0 (autonomous)   risk class: low
connector  : console
connector status: succeeded
output     : {"message": "[console] simulated NotifyITHelpdesk"}
```

## Why success came from ADOS records

`evaluate_mission()` received exactly three things: the observed
`SessionOutcome`, the capability names ADOS recorded as `executed` (queried from
`capability_requests`), and the mission's required capabilities. **It has no
parameter for the agent's text** — no `final_answer`, no `report`, no
`confidence` — and `test_mission_acceptance.py` asserts that signature.

The verdict is `ACCEPTED` because both required capabilities have `status =
'executed'` rows written by the gateway, not because the report reads well.

**The agent's narrative was correct here, and it is still not the evidence.**
Its conclusion — pool size 10 → 100 in release 2026.8.9-rc3, 6 pods against
`max_connections = 200` — matches the ground truth, and matches data that exists
*nowhere* except ADOS's `missions.evidence`. It could only have come through the
governed retrieval. That is corroboration, not proof; the proof is the row.

### The counter-example, from the previous run

Run #4 is the strongest evidence that the gate works:

```
runtime finished : state=completed  tools=1  ok=1  err=0
tool result      : status 'ok', isError False
ADOS verdict     : REJECTED — required capabilities were never executed by ADOS
```

The model had emitted a `!python` shell escape. IPython reported
`Couldn't find program: 'python'` as a **successful** execution (`status: 'ok'`,
`isError: False`), so the adapter counted `tool_ok = 1` and the session state
became `completed`. The agent then wrote a lucid, accurate explanation of its
own failure.

Every signal short of ADOS's own records said "completed". ADOS recorded
`mission.status: failed` because `capability_requests` was empty. This is
exactly the substitution `evaluate_mission()` exists to refuse:

```
model completion != mission completion
```

## Performance

| Metric | Value |
|---|---|
| Total elapsed | 281.6s (15.6% of the 1800s budget) |
| Model calls | 4 (2 with token usage) |
| Tool calls | 1 (1 success, 0 failures) |
| Kernel execution time | milliseconds; the MCP round trip + connector is inside it |
| Input tokens | 4,628 → 10,130 |
| Output tokens | 5,773 total — **reasoning tokens dominate** |
| `cacheRead` | 0 on every call (no prompt caching) |

Latency is almost entirely model generation. ADOS, MCP, and connector overhead
were not measurable above noise — consistent with the dedicated instrumentation
run, where kernel tool execution accounted for 1.2s out of 3,225s (0.04%).

## Caveats — what this does NOT prove

* **`NotifyITHelpdesk` executed against the `console` connector**, which returns
  `"[console] simulated NotifyITHelpdesk"`. The governance path is real
  end-to-end — request, authentication, server-side grant resolution, policy
  tier, connector selection, audit row — but **no IT helpdesk was actually
  notified**. What is proven is the *governed path*, not a real downstream
  side effect. A real helpdesk connector is not configured.

  *Superseded for the final step only:* a later run of the same mission with
  ServiceNow configured created, verified and closed a real incident
  (`INC0010027`, mission `6a7c5991`) — see
  [16-external-side-effect-run.md](16-external-side-effect-run.md). This report
  describes the run it describes, and that run's helpdesk step was simulated.
* `FetchIncidentEvidence` is genuinely real: `mission-evidence` reads ADOS's own
  database and returned the actual stored payload.
* One mission, one model, one provider, one run. Not a stability claim.
* No human-approval round trip was exercised (the denial path is tested
  separately; a Tier 1/2 pause/resume is not).
* `runtime_session_id` is still NULL — see
  [14-known-limitations.md](14-known-limitations.md).

## The Prime Agent ↔ IPython ↔ ADOS contract

Made explicit after Run #4, because the contract being implicit is what broke it.

**The tool is a persistent IPython kernel.** Everything sent to it is plain
Python source executed directly in that kernel.

* Write Python source directly. Top-level `await` is supported.
* **Do not** use `!` shell escapes, `!python`, `!python3`, `%%bash`, or
  `subprocess` as a substitute for writing Python. There is no `python` on
  `PATH`; the kernel *is* the interpreter.
* Variables persist between cells — bind results to names rather than
  re-fetching or re-printing them.
* Reach ADOS through the provided `ados` Python skill, not by constructing HTTP
  calls.

A deliberate non-fix: **no `python` symlink was added to the image.** Making the
container silently forgiving of the wrong idiom would hide contract violations
instead of surfacing them.

## Integration history — bugs found by running it for real

Each of these was found only by executing the real path, and each is now pinned
by a test.

| Defect | Symptom | Fix |
|---|---|---|
| Kernel venv missing 9 of 12 `DEFAULT_RLM_EXTRA_PACKAGES` | every tool execution failed; agent fabricated a root cause | install the full set; `test_prime_runtime_image.py` parses the list from Prime Agent's source |
| Kernel venv under root-owned `/opt` | `EACCES … mkdir '/opt/kernel-venv.bootstrap.lock'` | move to `/home/prime` |
| `chown` before the skill `pip install` | `EACCES … unlink '.../site-packages/ados/__init__.py'` | reorder |
| **MCP response shape** | `AttributeError: 'str' object has no attribute 'get'` inside the skill — **capability executed, result lost** | `_decoded()` handles dict and JSON-string; 16 tests |
| Gateway reported `ok: True` on a failed connector response | success claimed for work that failed | `CallStatus` is authoritative |
| `hub.execute` / bare `IntegrationHub()` | no connector registered | `hub.invoke()`, `default_hub()` |
| Missing `governance` on `CapabilityCall` | row stranded at `pending_approval` | construct inside the try, always resolve the row |

### The MCP response-shape bug, in detail

`rlm.mcp_base._parse_result` prefers the MCP response's `structuredContent` and
returns a dict; when the server sends only text blocks — which is what FastMCP
emits for these tools — it joins them and returns a **JSON string**. The skill
then called `res.get("status")` on a `str`.

The failure mode is what makes it worth recording: **ADOS executed the
capability correctly every time.** Three `FetchIncidentEvidence` rows with
`status = executed` and real payloads sat in the audit trail while the agent
received nothing. Work done, result lost, and the agent — correctly — reported
that it could not retrieve the evidence.

The model diagnosed it accurately (`if isinstance(r, str): r = json.loads(r)`)
and could not fix it, because the exception is raised inside the skill before
anything is returned.

This also retired an earlier, wrong diagnosis of ours. `gpt-oss-120b`'s "17-call
loop" was **rational debugging of this real bug**, not pathological looping: it
retried with a traceback, read `inspect.getsource`, read `SKILL.md`, listed
capabilities, checked `os.environ`, then bypassed the helper. No ADOS-side loop
control was added, and none is warranted.
