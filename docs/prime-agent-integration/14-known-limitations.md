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

### Network egress is placement, not filtering

The container sits on a dedicated bridge network (`ados-runtime-net`) with no
other ADOS service on it, and no host network access. It **can still reach
arbitrary internet hosts** — it must, to call an LLM API.

This is deliberately **not** described as an egress allowlist. A real one needs
a filtering proxy with agent traffic forced through it and only the LLM endpoint
plus the ADOS gateway permitted. Recorded as a gap, not claimed as done.

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

### Kernel errors are counted as tool successes — OPEN

Found by the end-to-end ServiceNow run (mission `6a7c5991`), which reported
`tools=4 ok=4 err=0` when only **one** of the four executions actually ran. The
other three raised `SyntaxError` inside the kernel:

```
Cell In[5], line 2
  r = await ados.run_capability('FetchIncidentEvidence', {}
                               ^
SyntaxError: '(' was never closed
```

The MCP result carried `details.status = 'error'` and `errorEname =
'SyntaxError'`, and **`isError` was `false`** on all four. The adapter
(`orchestrate/runtime/prime.py:278`) counts successes from `isError` alone, so
it scored 4/4.

Prime Agent's `isError` means the tool call was *dispatched* successfully, not
that the code *ran*. This is the same confusion as run #4's `!python`, one layer
up: there IPython reported a missing program as `status: 'ok'`, here the MCP
envelope reports a kernel exception as a successful call.

Why it matters beyond the counter: `evaluate_mission()`'s first check is
`did_real_work` (`tool_success_count > 0`), which exists to catch a runtime that
could not act and wrote confident fiction anyway. **That check is currently
blind to kernel errors.** A run in which every cell raised would pass it. The
mission verdict was still correct here — check #2 reads `capability_requests`,
which no amount of miscounting can forge — but that is defence in depth doing
the work of a broken first check, not a working first check.

Fix is in the adapter, not the image: read `details.status`/`errorEname` from
the tool result rather than trusting `isError`.

### The request id in a ServiceNow ticket resolves to nothing — OPEN

The gateway writes `CapabilityRequestRow` (its own `request_id` primary key,
`backend/app/mcp_gateway.py:211`), then separately constructs a `CapabilityCall`
whose `request_id` is its own `uuid4` default (`:318`). Two ids for one action.

The ticket's provenance block carries the **call's** id, which appears in no
table:

```
ticket description : Capability request: c0258072-47d5-409a-a036-f5050cc8b37b
capability_requests: request_id       = cf4522b4-b3b3-4662-a907-9b763af6e4f5
```

So an operator who opens the incident, reads the id ADOS wrote there, and looks
it up finds nothing. Provenance that does not resolve is worse than absent —
it looks like a working audit trail. The mission id in the same block *does*
resolve, which is what saved traceability for this run.

Fix: pass `request_id=row.request_id` when constructing the `CapabilityCall`, so
one action has one id.

### No approval round trip yet

The denial path is tested; a full human-approval pause/resume through a runtime
session is not. `WAITING_FOR_APPROVAL` is a state of the **ADOS session row**,
not of the Prime process — Prime Agent has no suspend primitive, so the agent
polls while ADOS holds the decision.

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
