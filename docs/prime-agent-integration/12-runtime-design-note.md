# Runtime Design Note — containerized Prime Agent, first vertical slice

Answers A–J before implementation. Grounded in the Prime Agent source at
`../prime-agent` (v0.7.1) and in runs actually executed against the installed
binary. Supersedes nothing in `11-runtime-boundary-design.md`; it fills in the
mechanics that document deferred.

Decision recorded up front: **the container boundary is part of the
architecture, not a later hardening step.** No host-permissioned slice is
built first.

---

## A. Exact Prime Agent RPC lifecycle

`prime-agent --mode rpc` speaks strict JSONL over stdin/stdout.

```
ADOS                                     Prime Agent (in container)
 |  spawn: cli.js --mode rpc --provider groq --model ... --session-dir /work/.sessions
 |------------------------------------------------>|
 |  {"id":"r1","type":"prompt","message":<objective>}|
 |------------------------------------------------>|
 |<--- {"type":"response","command":"prompt","success":true}
 |<--- {"type":"agent_start"}
 |<--- {"type":"turn_start"}
 |<--- {"type":"message_update", ...}          (streaming deltas)
 |<--- {"type":"tool_execution_start","toolName":...}   <-- kernel work
 |<--- {"type":"tool_execution_end","result":...,"isError":false}
 |<--- {"type":"turn_end","message":...,"toolResults":[...]}
 |<--- {"type":"agent_end","messages":[...]}    <-- terminal for this prompt
```

Framing rule from `docs/rpc.md`, and it is load-bearing: **split on `\n` only.**
Generic line readers that also split on U+2028/U+2029 are explicitly
non-compliant, because those characters are legal inside JSON strings.

Commands used by the slice: `prompt` only. `steer` / `follow_up` /
`interrupt` exist and are how cancellation and mid-flight correction will work
later; they are not needed to prove the loop.

**There is no `session` event.** An earlier draft of this note asserted one, on
the assumption that a mode built for automation would announce its session id.
It does not: the first thing on stdout after a `prompt` is
`{"type":"response","command":"prompt","success":true}`, and Prime Agent's
session id is reachable over the protocol only by *asking* — the `get_state`
command, which returns an `RpcSessionState` carrying `sessionId`
(`src/modes/rpc/rpc-types.ts`).

ADOS does not ask. `recover_runtime_session_id()` reads the id from the session
file's basename instead (`src/core/session-file-actions.ts`), since the file
lives in `--session-dir` inside our own workspace — a read rather than a
protocol change. It runs in `run_objective()`, before `teardown()` deletes the
workspace. Fixed 2026-08-10; `runtime_sessions.runtime_session_id` is populated.

## B. Container lifecycle

```
build (once, cached)   ados-prime-runtime:<tag>
   |
create workspace       host temp dir -> bind-mounted at /work
   |
docker run -d          name=ados-prime-<session_id>
   |                   --memory / --cpus / --pids-limit
   |                   --network ados-runtime-net
   |                   -e ADOS_MCP_TOKEN / -e provider key
   |                   -w /work
   |                   holds `sleep infinity`; the RPC process is exec'd in
   |
docker exec -i         cli.js --mode rpc     <-- stdin/stdout is the RPC channel
   |
teardown               docker rm -f  +  workspace deletion (always, in finally)
```

Why `run -d` + `exec` rather than `docker run -i` directly: the container must
outlive one RPC process so a session can be re-entered, and so teardown is an
explicit, auditable step rather than a side effect of a pipe closing. It also
keeps the container's identity (`ados-prime-<session_id>`) stable for
`docker kill`, which is the same reasoning
`orchestrate/onboarding/sandbox_runner.py` already documents — the local client
process and the container are decoupled.

### Where this deliberately diverges from `sandbox_runner.py`

`sandbox_runner` runs `--network=none`. **That is impossible here**: Prime
Agent must reach an LLM API to think at all, and must reach the ADOS gateway to
request capabilities. Forcing the existing abstraction would produce a
container that cannot run. So this is a sibling runner, not a reuse:

| | onboarding sandbox | prime runtime |
|---|---|---|
| network | `none` | dedicated bridge, egress required |
| lifetime | one call | a session |
| stdio | collect output | bidirectional RPC |
| credentials | none | LLM key + session token only |

Shared where genuinely shared: docker availability probing, image build/caching,
subprocess timeout handling.

**Honest limit on "restricted network".** Docker gives us network *placement*,
not per-destination egress filtering. Slice 1 uses a dedicated user-defined
bridge network with no other ADOS services on it, and no host network access.
It does **not** prevent the container reaching arbitrary internet hosts. A
real egress allowlist needs a filtering proxy (agent traffic forced through it,
only the LLM endpoint + the gateway permitted). Recorded as a gap, not claimed
as done.

## C. Runtime session state machine

```
CREATED ──launch──> STARTING ──ready──> RUNNING ──agent_end──> COMPLETED
   │                    │                  │
   │                    │                  ├──capability pending──> WAITING_APPROVAL ──decided──> RUNNING
   │                    │                  │
   └──────────────┬─────┴──────────────────┴──error/timeout──> FAILED
                  │
                  └──cancel──> CANCELLED

every terminal state ──> TORN_DOWN   (container removed, workspace deleted)
```

`WAITING_APPROVAL` is a state of the **ADOS session row**, not of the Prime
process — Prime Agent has no suspend primitive. The agent is polling inside its
own kernel while ADOS holds the decision. This distinction is real and is not
papered over.

Persisted in `runtime_sessions`; the mission row is authoritative for outcome.

## D. MCP gateway contract

ADOS hosts an MCP server over HTTP. HTTP is forced, not chosen:
`docs/mcp-integrations.md` states stdio servers "are not yet wired through to
the kernel — the host drops non-HTTP entries."

Three tools, deliberately few:

| Tool | Input | Output |
|---|---|---|
| `list_capabilities` | — | the capabilities **this session** is granted, resolved server-side |
| `request_capability` | `capability`, `arguments`, `idempotency_key` | `{status: executed\|pending_approval\|denied, request_id, result?, reason?}` |
| `get_capability_request` | `request_id` | current state; `result` once decided |

`list_capabilities` exists so the agent discovers its grant rather than
guessing — and so a denial is informative rather than mysterious.

## E. Session token lifecycle

```
mint    at session creation: secrets.token_urlsafe(32), stored as a SHA-256
        hash (never plaintext) on the runtime_sessions row
inject  only as container env ADOS_MCP_TOKEN
use     Authorization: Bearer <token> on every MCP request
resolve gateway hashes the presented token and looks up the session row
expire  on session terminal state; also a wall-clock TTL
revoke  teardown marks the row terminal, which invalidates the token
```

The token is **opaque and identity-only**. It carries no capability list, no
role, no claims — deliberately not a JWT, so nothing the runtime holds can be
decoded, forged, or widened. Everything it authorizes is looked up server-side.

## F. Capability authorization flow

```
request_capability(capability, arguments, idempotency_key)
   │
   ├─ 1. authenticate      token hash -> runtime_session (else 401)
   ├─ 2. session live?     state in (RUNNING, WAITING_APPROVAL) (else 409)
   ├─ 3. resolve grant     mission.allowed_capabilities  <-- SERVER SIDE ONLY
   ├─ 4. membership        requested ∈ grant?            (else denied + audit)
   ├─ 5. idempotency       key seen? -> return the ORIGINAL result, do not re-execute
   ├─ 6. policy/risk       orchestrate/governance.assign_policy_tier(...)
   │        Tier 0  ────────────────────────────────> execute
   │        Tier 1/2 ──> persist pending_approval ──> return request_id
   ├─ 7. execute           IntegrationHub -> connector (the same governed path
   │                       the MOA uses; no side channel)
   ├─ 8. audit             capability, decision, tier, actor=session/mission, result
   └─ 9. return            structured dict
```

Step 3 is the whole security model. **The runtime never supplies its own
permission list**, and there is no request field by which it could. A widened
grant requires an ADOS-side mission change.

## G. Approval / polling flow

No held connections. A Tier 1/2 request returns immediately:

```python
req = await ados.request_capability(...)      # {"status":"pending_approval","request_id":"..."}
while True:
    st = await ados.get_capability_request(request_id=req["request_id"])
    if st["status"] != "pending_approval":
        break
    await asyncio.sleep(5)
```

The pending row is durable, so a human can decide minutes or hours later,
across an ADOS restart. This reuses the durability work from Stage 2b rather
than inventing a second pause mechanism.

Slice 1 exercises a **Tier 0** capability end to end and covers the denial path
by test; the full human-approval round trip is the immediate next increment.

## H. Runtime → ADOS event flow

Prime Agent's `AgentEvent` stream is normalized into ADOS events at the
adapter, so nothing downstream depends on Prime Agent's shapes:

| Prime Agent | ADOS |
|---|---|
| `session` header | `runtime.session.started` |
| `tool_execution_start` / `_end` | `runtime.tool.started` / `.finished` |
| `turn_end` | `runtime.turn.completed` |
| `agent_end` | `runtime.session.completed` |
| stderr / non-zero exit | `runtime.session.failed` |
| (gateway-side) | `runtime.capability.requested` / `.governed` / `.executed` |

Events are appended to the mission's evidence trail. Capability events come
from the **gateway**, not the agent's self-report — the agent cannot claim to
have done something ADOS did not do.

## I. Workspace lifecycle

- Created per session as a host temp dir, bind-mounted at `/work`.
- Seeded with the synthetic incident artifacts for the mission. Nothing else.
- **Never** the ADOS repo, never `$HOME`, never a path with credentials.
- Sessions dir inside it (`/work/.sessions`) so Prime Agent's own session JSONL
  is captured as mission evidence and dies with the workspace.
- Deleted on teardown in a `finally`, together with the container.

Evidence worth keeping (final report, event log) is copied into ADOS's
database *before* teardown, because the workspace is disposable by design.

## J. Failure / restart behavior

| Failure | Behavior |
|---|---|
| container won't start | session `FAILED`, mission stays `pending`, no partial audit |
| agent exits 0 having done nothing | **`FAILED`, not completed** — success requires observed effects (see A) |
| model hangs | wall-clock timeout kills the container; session `FAILED` |
| gateway unreachable from container | capability call errors inside the kernel; the agent sees a real error, ADOS records nothing executed |
| ADOS restarts mid-session | container keeps running but is orphaned; the session row is `RUNNING` with no attached process. Slice 1 marks such rows `FAILED` at startup and tears down stray `ados-prime-*` containers. **True resume is explicitly out of scope for slice 1** and is the next milestone. |
| capability executed but response lost | idempotency key makes the retry return the original result instead of re-executing |
| teardown fails | logged, and a startup sweep removes stray containers |

The asymmetry is deliberate: ADOS would rather record *less* than the runtime
did than claim more. A capability is only ever marked executed by the gateway
that executed it.

---

## K. Mission acceptance — agent narrative is never authoritative evidence

**Permanent invariant.** Prime Agent saying "the root cause is X" does not mean
the mission succeeded. It is a claim: worth storing, worth showing a human,
never a reason to mark work complete.

ADOS determines truth only from things it observed or performed:

- governed capability executions ADOS itself carried out
- evidence ADOS served through those capabilities
- connector results
- independently verifiable effects
- persisted artifacts

and refuses this family of substitutions, each of which has cost a real
debugging session here:

```
tool attempt      != tool success
process exit 0    != mission success
HTTP 200          != capability success
agent narrative   != evidence
model completion  != mission completion
```

Implemented in `orchestrate/runtime/acceptance.py`. `evaluate_mission()` takes
the observed `SessionOutcome`, the capability names ADOS actually executed (read
from `capability_requests`, written by the gateway that performed the call), and
the mission's required capabilities. **It has no parameter for the agent's
text** — no `final_answer`, no `report`, no `confidence`. A function that cannot
see the narrative cannot be persuaded by it, and a future change that wants to
consult it must alter the signature in a diff a reviewer will notice.
`test_mission_acceptance.py` asserts that signature directly.

### The corollary: evidence must be fetched, not handed over

The invariant only bites if the agent can be *deprived* of facts. A runtime
pre-loaded with the incident file in its workspace can write a plausible report
with a completely broken kernel — and did, attributing a checkout outage to disk
-space exhaustion on a database server that appeared nowhere in the data it
never read.

So the mission's case file lives on `missions.evidence` and is reachable only
through `FetchIncidentEvidence` (`integrations/connectors/mission_evidence.py`),
scoped server-side to the caller's own mission. Broken kernel → no capability
call → no evidence → mission rejected, decided in SQL rather than by reading
prose. `MissionEvidenceConnector` is registered **before** `ConsoleConnector` in
`default_hub()` for a concrete reason: Console declares `set(Capability)` and
would return `SUCCEEDED` with `"[console] simulated FetchIncidentEvidence"` — a
green audit row and no evidence.

---

## L. Model and provider requirements — measured, not assumed

Prime Agent's harness prompt is large. A single first request measured
**~36,300 tokens** before the model has done anything, because the system prompt
carries the kernel contract, the skill manifests, and the harness API. Every
tool result is appended to that, and the agent is a multi-turn loop, so the
context grows from there.

That makes the model a **runtime requirement**, not a preference. A provider that
cannot hold ~40k tokens of input, or cannot sustain a double-digit tool-call
loop without rate limiting, does not merely make the runtime slower — it makes
it non-functional, and the failure surfaces as an agent that "did nothing" or,
worse, one that fills the gap with invention.

| Provider / model | Measured result |
|---|---|
| Groq free tier (`llama-3.3-70b-versatile`) | **Unusable.** 12,000 TPM limit vs a 36,313-token request → HTTP 413 before the first turn. |
| Google `gemini-2.5-flash` | HTTP 404, "no longer available to new users". |
| Google `gemini-2.0-flash` | HTTP 429 on the free tier. |
| Google `gemini-flash-latest` | Runs, but 429s repeatedly under Prime Agent's call volume; a run cannot be relied on to finish. |
| Ollama `qwen3:4b` (local) | Not viable as configured: 32k native window against a ~36k prompt, and Ollama defaults `num_ctx` to 4096 — silent truncation, not an error. |
| NVIDIA NIM `openai/gpt-oss-120b` | **Sustains the loop.** Completed a full multi-turn mission with real tool calls. Used for acceptance. |

**This is a test configuration, not an architectural dependency.** Nothing in
`orchestrate/runtime/` names NVIDIA: the provider, model, key env var and a full
`models.json` are constructor arguments on `PrimeAgentRuntime`, written into the
session's own agent dir at start-up. Swapping providers is a caller-side change.

The requirement that *is* architectural: whatever model is configured must hold
the harness prompt and sustain a tool loop. Choosing one that cannot is a
silent-failure mode, and the honest place to catch it is the provider-error
mapping (`auto_retry_start`/`auto_retry_end` → `runtime.provider.retry*`), which
exists because two acceptance runs were spent rediscovering a 429 and a 413 that
were sitting unread in the event stream the whole time.

Model selection is deliberately **not** optimized yet. Correctness of the loop
first; cost and latency after there is a working loop to measure.

---

## M. The kernel contract (why the runtime was inert for three runs)

`PRIME_AGENT_KERNEL_PYTHON` is validated, not trusted.
`ensureKernelPythonUncached()` requires **three** things of the pinned
interpreter — `ipykernel`, a `prime-agent-runtime` satisfying
`RUNTIME_READY_CHECK`, and **every** package in `DEFAULT_RLM_EXTRA_PACKAGES`
(requests, httpx, pyyaml, tomli, python-dotenv, pandas, numpy, scipy,
beautifulsoup4, lxml, pydantic, tyro) — and throws if any is absent.

An image satisfying the first two looks entirely healthy: the venv exists,
`import rlm` works, the container starts, the model runs, tool calls are
attempted. The check is **lazy, on first tool use**, so the only symptom is that
every tool execution fails identically. Because the kernel is the agent's *only*
tool, that one missing dependency set is indistinguishable from a total runtime
outage — and the model, still able to write, produced a confident fabricated
root cause.

Three separate image defects produced the same signature and were fixed in turn:

| Defect | Symptom |
|---|---|
| kernel venv under root-owned `/opt` | `EACCES … mkdir '/opt/kernel-venv.bootstrap.lock'` |
| `chown` running before the skill `pip install` | `EACCES … unlink '.../site-packages/ados/__init__.py'` |
| 9 of 12 `DEFAULT_RLM_EXTRA_PACKAGES` missing | `PRIME_AGENT_KERNEL_PYTHON points to a Python missing default Python packages (…)` |

`backend/tests/test_prime_runtime_image.py` parses `DEFAULT_RLM_EXTRA_PACKAGES`
and `RUNTIME_READY_CHECK` **out of Prime Agent's own source** and asserts both
the Dockerfile and the built image satisfy them, so an upstream version that adds
a required package fails a test instead of silently disabling the runtime.

---

## Scope of slice 1

**In:** mission row, runtime session row + token, container build/run/teardown,
real RPC drive, real kernel execution, ADOS skill in the kernel, MCP gateway
with server-side grant + policy + idempotency + audit, two Tier 0 capabilities
(one read — `FetchIncidentEvidence` — and one write — `NotifyITHelpdesk`), an
acceptance rule grounded in ADOS's own rows, mission result persisted, clean
teardown.

**Out:** resume after ADOS restart, heartbeats, schedules, subagents, agent
messaging, `/refine`, multi-session missions, egress allowlist proxy, human
approval round trip (denial path tested; full pause/resume next).
