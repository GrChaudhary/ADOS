# Known Limitations

Everything here was **observed**, not anticipated. Where something is a
suspicion rather than a measurement, it says so.

---

## Provider and model

### NVIDIA NIM `openai/gpt-oss-120b` — latency and call inefficiency

Median model call ~110s, worst observed **482.9s**, on prompts of 4–9k tokens
producing 6–204 output tokens. Latency does not correlate with prompt size
(the largest prompt was among the faster calls), which is the signature of
queueing rather than computation.

It also took **17 model calls** for a workload Qwen completed in 2. That is an
independent problem from latency.

*Assumption, not measured:* that this is specifically free-tier scheduling. We
have no visibility into NIM's scheduler and did not test a paid tier.

### Groq — hard TPM admission ceiling

```
413 Request too large ... on tokens per minute (TPM): Limit 12000, Requested 20729
```

Per-call latency is excellent (**1.71s**). The container prompt simply does not
fit the free tier's admission limit, so no call ever completes.

Recorded because it cost a wrong conclusion once: **providers count tokens very
differently.** NIM reports `input: 4132` for the prompt Groq counts as `20729`.
Groq's count gates admission, so NIM's accounting cannot predict it. Only a
direct test settles this.

*Unknown:* Groq's multi-turn behaviour on this workload. It never completed a
single call.

### Ollama `qwen3:4b` — reasoning-token cost, and a silent truncation trap

**5,978 output tokens across 2 model calls.** Thinking mode accounts for most of
the 212s runtime. It reached the correct answer in a single tool call, so this
is not obviously waste — but a 4B local model is not simply "fast", and the cost
is in generation, not prompt processing.

**`num_ctx` must be set explicitly.** Ollama defaults to **4096** regardless of
the model's native context (qwen3:4b's is 262,144). A 4–9k prompt is then
**silently truncated rather than rejected** — no error, no warning, just a model
that has not seen its instructions. The runtime model is created as:

```
FROM qwen3:4b
PARAMETER num_ctx 16384
```

*Not tested:* Qwen with thinking disabled.

### No prompt caching

`cacheRead: 0` on every model call measured, across every provider tested. The
full context is re-sent and re-billed each turn. At 4–9k tokens this is not the
bottleneck, but it will matter for longer missions on a metered provider.

---

## Runtime

### ~~`runtime_session_id` is always NULL~~ — FIXED 2026-08-10

Kept here because the shape of the bug is worth remembering: the column existed
from the start, the adapter appeared to populate it, and it was NULL in every
run ever executed.

Prime Agent's RPC surface emits **no `session` event**. An earlier design note
asserted one, on the reasonable assumption that a mode built for automation
would announce its session id; it does not, and the id is reachable over the
protocol only via the `get_state` command (`src/modes/rpc/rpc-types.ts`). The
`"session"` entry in `_EVENT_MAP` was therefore dead code that made the adapter
*look* like it captured the id while capturing nothing.

Fixed by reading it where Prime Agent actually writes it: the session file's
basename is the id (`src/core/session-file-actions.ts`), and the file lives in
`--session-dir` inside our own workspace. `recover_runtime_session_id()` is
called from `run_objective()` — **not** `teardown()` — because teardown deletes
the workspace, and a recovery attempted afterwards silently yields the same NULL
this change exists to remove.

Verified in a live run: `runtime_session_id = '019fe7e7-de3f-731b-bf6e-07686ca21091'`,
persisted to `runtime_sessions`. Covered by
`backend/tests/test_runtime_session_id.py`, including a structural test that the
dead `_EVENT_MAP["session"]` entry stays gone.

### ~~Network egress is placement, not filtering~~ — ENFORCED 2026-08-10

The container used to sit on a shared bridge (`ados-runtime-net`) with
`--add-host host.docker.internal:host-gateway`. That kept it off ADOS's compose
network but left it a default route and working DNS, so it could reach any host
on the internet. It was recorded here as a gap rather than claimed as an
allowlist.

It is now a per-session `--internal` network with **no default route at all**,
plus a destination-pinned relay. See `orchestrate/runtime/egress.py`.

Measured from inside the real runtime image, same probe, both topologies:

| probe | before (shared bridge) | now (enforced) |
|---|---|---|
| default routes | 2 | **1** (on-link only) |
| resolve `example.com` | `104.20.23.154` | **NO-RESOLVE** |
| TCP `1.1.1.1:443` | REACHABLE | **BLOCKED** |
| TCP `8.8.8.8:53` | REACHABLE | **BLOCKED** |
| resolve `host.docker.internal` | `192.168.65.254` (the host) | **NO-RESOLVE** |
| host port 5432 (Postgres) | **REACHABLE** | **BLOCKED** |
| the allowed destination | reachable | reachable, `HTTP 200` |

**The old topology could open a TCP connection to the Docker host's port 5432.**
The previous note said the runtime "cannot reach Postgres, Kafka, or any other
internal service" on the grounds that it was not on ADOS's compose network —
but published ports plus a host-gateway entry defeated that. It never had
database credentials, so this was a reachable port rather than a breach, and it
is closed now.

**What enforces it is the absence of a route, not the relay.** A component that
can be bypassed by ignoring it is decoration; here there is nowhere else to
send a packet. The relay decides which upstreams exist, the kernel decides that
nothing else is reachable.

**Why a relay rather than an HTTP proxy.** A proxy takes the destination from
the client (`CONNECT host:port`), which makes the client's cooperation part of
the security model. It would also simply not work: Prime Agent reaches
OpenAI-compatible providers through the OpenAI SDK on Node 22, whose fetch does
not honour `HTTP_PROXY`/`HTTPS_PROXY` — enforcing policy that way would mean
patching Prime Agent's networking. Each relay listener is pinned at start-up to
exactly one upstream, so **there is no field in which a caller can name a
destination**, and open-proxy abuse, redirect escape and connect-by-IP are all
excluded by construction rather than by validation.

Allowlist entries must be **hostnames, not IP literals** — the redirect works
through `/etc/hosts`, which cannot redirect an address. An IP-literal
destination is refused at construction rather than accepted into a policy where
it would silently be unreachable.

**Still open:** no full mission has been run through the boundary. What is
demonstrated is the boundary itself, from inside the real runtime image, not a
model completing work behind it. TLS is deliberately end-to-end, so this
constrains *where* the runtime can talk and not *what it says* — a permitted
destination can still receive anything the runtime chooses to send it.

### The kernel is not a security sandbox

Prime Agent executes model-generated Python with the permissions of whoever runs
it; its own README states the worker and kernel processes are not a security
sandbox. **The container is the boundary that makes this acceptable** — non-root
(uid 10001), disposable workspace, resource limits (2GB / 2 CPU / 512 pids), and
exactly two secrets injected: the LLM provider key and an identity-only session
token. No database URL, no connector credentials, no ADOS user identity.

### Pinned kernel Python is validated, and the failure is silent

`PRIME_AGENT_KERNEL_PYTHON` must satisfy three conditions or Prime Agent refuses
the kernel: `ipykernel`, a `prime-agent-runtime` passing `RUNTIME_READY_CHECK`,
and **every** package in `DEFAULT_RLM_EXTRA_PACKAGES`. The check is **lazy, on
first tool use**, so an image missing them looks entirely healthy — container
starts, model runs, tool calls are attempted — and every tool execution fails
identically.

Pinned by `backend/tests/test_prime_runtime_image.py`, which parses Prime
Agent's own source so an upstream addition fails a test rather than silently
disabling the runtime.

### ~~Kernel errors are counted as tool successes~~ — FIXED 2026-08-10

Found by the end-to-end ServiceNow run (mission `6a7c5991`), which reported
`tools=4 ok=4 err=0` when only **one** of the four executions actually ran. The
other three raised `SyntaxError` inside the kernel:

```
Cell In[5], line 2
  r = await ados.run_capability('FetchIncidentEvidence', {}
                               ^
SyntaxError: '(' was never closed
```

The result carried `details.status = 'error'` and `errorEname = 'SyntaxError'`,
and **`isError` was `false`** on all four.

**Why `isError` was false is the interesting part, and it is upstream.** The
ipython tool computes the right answer and returns it:

```js
// dist/core/tools/ipython.js
isError: r.status === "error" || r.status === "aborted",
```

and Prime Agent's core then throws that away:

```js
// executePreparedToolCall, dist/bundle/chunk-VNU2AJHD.js
    return { result, isError: false };        // <- hardcoded
  } catch (error) { ...  isError: true }
```

So `isError` on a finished execution answers **"did the tool function throw?"**,
not "did the code run". The kernel's verdict survives only in
`result.details.status`. This is the same confusion as run #4's `!python`, one
layer up: there IPython reported a missing program as `status: 'ok'`, here the
core reports a kernel exception as a successful call.

It mattered well beyond the counter. `did_real_work` is
`tool_success_count > 0`, and it is the check that catches a runtime which could
not act and wrote confident fiction anyway — **counting dispatches as successes
made it blind to exactly that.** A run in which every cell raised would have
passed it. The verdict was still correct for this run because check #2 reads
`capability_requests`, which miscounting cannot forge, but that was defence in
depth doing a broken check's job.

Fixed in the adapter, not the image, by `classify_tool_execution()`
(`orchestrate/runtime/prime.py`):

```
isError true                     -> error   (throw path; details is {})
details.status == "ok"           -> ok
details.status error|aborted     -> error
details.status unrecognised      -> unknown
no status, result.isError true   -> error
otherwise                        -> unknown
```

`unknown` is a third outcome, not a synonym for success — a result carrying no
verdict is never counted as work done, mirroring `CallStatus.UNKNOWN` in the
connector layer. `SessionOutcome.tool_unknown_count` reports them separately,
and the audit row now carries `kernel_verdict`, `kernel_status` and
`kernel_error` alongside the raw `isError`, deliberately: the two disagreeing is
the signature of this defect, and a row showing only the corrected value would
hide that it ever happened.

Covered by `backend/tests/test_kernel_execution_semantics.py` (19 tests),
including a negative control that restores the old `isError`-only rule and
demonstrates it scoring four SyntaxErrors as 4/4 successes.

### ~~The request id in a ServiceNow ticket resolves to nothing~~ — FIXED 2026-08-10

The gateway wrote `CapabilityRequestRow` (its own `request_id` primary key,
`backend/app/mcp_gateway.py:211`), then separately constructed a
`CapabilityCall` whose `request_id` was its own `uuid4` default. Two ids for one
action, and connectors write the *call's* id into the systems they touch:

```
ticket description : Capability request: c0258072-47d5-409a-a036-f5050cc8b37b
capability_requests: request_id       = cf4522b4-b3b3-4662-a907-9b763af6e4f5
```

An operator who opened INC0010027, read the id ADOS wrote there, and looked it
up found nothing. Provenance that does not resolve is worse than absent — it
looks like a working audit trail. The mission id in the same block *did*
resolve, which is what saved traceability for that run.

Fixed by threading the row's key through: `_execute_capability` now takes
`request_id` as a **required** keyword argument and passes it to the
`CapabilityCall`, so the contract's `uuid4` default can no longer fire on this
path. Covered by `backend/tests/test_capability_request_provenance.py`, which
drives the real `request_capability` gateway entry point against a mocked
ServiceNow, extracts the id from the posted ticket body, and resolves it back to
the row — plus a structural guard that the argument stays required.

### ~~No approval round trip yet~~ — BUILT 2026-08-10, not yet exercised by a live runtime

`WAITING_FOR_APPROVAL` is a state of the **ADOS session row**, not of the Prime
process — Prime Agent has no suspend primitive, so the agent polls while ADOS
holds the decision. That half was always there, and so was the `ados` skill's
polling loop. What was missing was anyone to answer: `mcp_gateway.py` was the
only writer of `capability_requests` and had no path out of `pending_approval`,
so every Tier 1/2 request parked forever and the agent raised
`CapabilityTimeout`.

`backend/app/routers/runtime_approvals.py` closes it:

```
GET  /runtime/capability-requests              the approver's queue
POST /runtime/capability-requests/{id}/approve executes via the gateway's own
                                               _execute_capability, audited
POST /runtime/capability-requests/{id}/reject  denied, with a reason, nothing runs
```

Approval does **not** execute anything itself — it calls
`mcp_gateway._execute_capability`, the same choke point the autonomous path
uses, so there is still exactly one place where a capability becomes a real side
effect. The RBAC rule is the one `moa.py` already had, extracted to
`rbac.authorize_governance_decision()` and now shared rather than copied.

Guards, each pinned by a test that fails when the guard is removed: a decided
request cannot be decided again (409, so a double approval cannot raise two
tickets); the mission grant is re-checked at decision time, not trusted from
when the request parked; a request whose runtime session has ended is refused
rather than fired into the void; auditors decide nothing; the approver's limit
must cover the claimed cost. The approver's verified username travels to the
connector as `GovernanceInfo.approved_by`, and Tier 0 still records `None` —
a negative-control test pins that, because a default that stamped somebody in
would make every autonomous action look human-approved.

**Still open:** no live Prime Agent container has been driven through this. The
round trip is proven at the gateway/API level with the real skill-side polling
contract, not by a running model waiting on a human. That run has not been done.

### Single-session missions only

No resume after ADOS restart, no heartbeats, no schedules, no subagents, no
agent-to-agent messaging, no multi-session missions.

---

## Model behaviour

### The 17-call loop is model-specific

`gpt-oss-120b` repeatedly re-ran equivalent work instead of progressing. Under
byte-identical conditions — same ADOS, same gateway, same container image, same
workspace, same prompt — Qwen issued **one** tool call.

That controls out the mission prompt, Prime Agent's runtime, and ADOS.

**No ADOS-side loop limit was added.** A guard against a defect exhibited by one
model would be a permanent tax on every future model, to work around a provider
we are not choosing.

### Malformed tool calls

`gpt-oss-120b` was separately observed emitting `ipython` tool calls with **empty
arguments** (`{}`), failing schema validation — 5 of 15 executions in one run.
Also model-specific.

---

## External side effects (ServiceNow)

### Two test modes, and why the separation is load-bearing

| | default suite | `pytest -m external` |
|---|---|---|
| ServiceNow | `httpx.MockTransport` | the real instance |
| external writes | none | **creates a real incident** |
| missing credentials | irrelevant | **FAILS** — never skips, never falls back |
| a Console result | n/a | **fails the test** |

`addopts = "-m 'not external'"` means no ordinary `pytest` run — CI, a hook, a
laptop — can create real records as a side effect. Running them requires having
typed the word `external`.

The external test asserts `response.connector == "servicenow"` before anything
else. A silent fallback to Console would return SUCCEEDED with
`"[console] simulated NotifyITHelpdesk"` and a green test proving nothing
happened — the exact false-success class this integration exists to prevent.

### `close_code` is version-dependent, and its failure is silent-shaped

Closing with `"Closed/Resolved by Caller"` — correct on older instances —
returned:

```
403 Data Policy Exception: The following fields are mandatory: Resolution code
```

The instance rejects an unrecognised choice value and then reports the field as
*unset*, so a wrong value is indistinguishable from a missing one. Configurable
via `SERVICENOW_CLOSE_CODE` (default `"Resolved by caller"`). Check a target
instance with:

```
GET /api/now/table/sys_choice?sysparm_query=name=incident^element=close_code
```

### Cleanup is close, not delete — and it has already failed once

Records are closed (state 7), not deleted: closing is the normal ServiceNow
lifecycle and preserves the audit trail the test exists to produce.

Three runs executed before the `close_code` problem was understood, and each
left an open incident behind. They were found by querying the marker and closed.
That is why every test-created record carries an unmistakable marker:

```
[ADOS PRIME-AGENT INTEGRATION TEST] <test-id>
```

If cleanup fails, the test **fails loudly with the sys_id**, because an orphaned
ticket in someone's instance is worse than a noisy test.

## Evidence and acceptance

### Evidence must be fetched, never pre-loaded

The mission's case file lives on `missions.evidence` and is reachable only
through `FetchIncidentEvidence`. This is load-bearing, not stylistic: a runtime
handed its evidence up front can produce a confident report with a completely
broken kernel — **and one did**, attributing a checkout outage to disk-space
exhaustion on a database server that appeared nowhere in data it never read.

Make the facts reachable only through a governed capability and a broken runtime
produces no facts, which ADOS can detect in SQL rather than by reading prose.

### Agent narrative is never authoritative evidence

`evaluate_mission()` takes no `final_answer`, `report`, or `confidence`
parameter, and a test asserts that signature. See
`orchestrate/runtime/acceptance.py`.

### Mission budget is a resource limit, not an acceptance criterion

Raising `max_wall_clock_seconds` changes how long ADOS waits, never what ADOS
accepts. Two runs were correctly **rejected** for running out of budget before
`NotifyITHelpdesk` executed, with the kernel working perfectly (10/10 successful
executions in one of them).
