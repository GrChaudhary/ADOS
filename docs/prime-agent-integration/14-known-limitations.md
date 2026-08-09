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

### `runtime_session_id` is always NULL

`runtime_sessions.runtime_session_id` exists and is never populated. Prime
Agent's RPC surface emits **no `session` event** — an earlier design note
asserted one, on the assumption that a mode built for automation would announce
its session id. It does not. The id is reachable only by *asking*, via the
`get_state` command returning an `RpcSessionState`
(`src/modes/rpc/rpc-types.ts`).

Consequence: ADOS cannot correlate its session row with Prime Agent's own
session file after the container is gone. The `"session"` entry in
`_EVENT_MAP` is dead code.

Cheap fix available, not yet applied: the session file's **basename is the id**
(`/work/.sessions/<uuid>.jsonl`), readable at teardown without touching the RPC
protocol.

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
