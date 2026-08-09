# Prime Agent Runtime — Architecture, Boundary, and First Vertical Slice

Written 2026-08-09 from the actual Prime Agent source at
`../prime-agent` (v0.7.1) and the actual ADOS source, after
`10-current-runtime-state.md` established that the existing integration is a
facade.

Every architectural claim below is grounded in a file in one of the two
repositories, or in a command that was run. Where something is still unproven
it is labelled **UNPROVEN**.

---

## 1. Prime Agent runtime architecture (from its source)

**It is a Node/TypeScript monorepo with a Python kernel runtime — not a Python
SDK and not a hosted API.** This is the single most important correction to the
assumption baked into `knowledge/prime_agent_client.py`, which was written as
if Prime Agent were an HTTP service with an API key.

```
prime-agent/  (v0.7.1, MIT, Node >= 22.8)
  packages/ai/            LLM provider layer (OpenAI/Anthropic/Google/… APIs)
  packages/agent/         core agent loop + AgentEvent types
  packages/coding-agent/  the product: modes, sessions, skills, MCP, daemon
  packages/tui/           terminal UI
  prime-agent-runtime/    Python: the `rlm` package that runs inside the kernel
```

Installed on this machine: `/opt/homebrew/bin/prime-agent`, version `0.7.1`,
with a prepared `~/.prime/agent/kernel-venv`.

### The execution model is "one tool, and the tool is a Python REPL"

From `README.md` and `docs/rlm.md`: Prime Agent deliberately does **not** expose
a broad tool surface to the model. The model's tool is a persistent IPython
kernel. File edits, shell commands, subagents, and MCP calls all happen as
Python code executed in that kernel.

This has a direct consequence for us, and it is the crux of the whole design:

> **ADOS capabilities cannot be handed to Prime Agent as "tools" in the usual
> sense.** They have to be reachable as Python callable inside the kernel.

`docs/mcp-integrations.md` states this explicitly: "Consistent with Prime
Agent's single-tool design, MCP integrations are **not** exposed as new agent
tools. Each integration is a Python-backed skill that the model imports and
calls from the IPython kernel."

### Process topology

From `docs/architecture.md` and `docs/daemon.md`: **daemon → worker → kernel**.
Sessions are daemon-backed, so they survive terminal detach and can be
reattached (`prime-agent attach`, `--resume`). This is real persistence, and it
is Prime Agent's, not ours.

### Headless surfaces (how ADOS can drive it)

| Surface | Command | Shape | Fit for ADOS |
|---|---|---|---|
| JSON mode | `prime-agent --mode json "prompt"` | one-shot; JSONL events on stdout | good for fire-and-collect |
| **RPC mode** | `prime-agent --mode rpc` | **bidirectional JSONL over stdin/stdout** | **the right one** |
| SDK | `@earendil-works/pi-coding-agent` | TypeScript in-process | wrong language for ADOS |
| ACP | `docs/acp.md` | editor protocol | not our use case |

RPC mode is the choice: it accepts commands (`prompt`, `steer`, `follow_up`,
session/state/interrupt commands) and streams events back, over plain JSONL —
language-agnostic, and `docs/rpc.md` ships a Python client example. Strict
framing rule to respect: split on `\n` only.

### Session model — real, and owned by Prime Agent

`docs/sessions.md`: sessions auto-save to `~/.prime/agent/sessions/` as JSONL
trees. `--resume <path|id>`, `--continue`, `--fork`, `--no-session`. Session
IDs are stable and are what we will store as `runtime_session_id`.

### What Prime Agent genuinely provides

Confirmed present in the source/docs (availability ≠ wired into ADOS):
persistent IPython context, subagents via `rlm(...)`, importable Python skills,
agent-to-agent messaging, persistent goals (`/goal`), heartbeats
(`/heartbeat`, `rlm_heartbeat`), schedules (`prime-agent schedule`), bounded
autonomous mode (`/autonomous`), and the Continual Harness (`/refine`).

### The security fact that shapes everything

`README.md`, verbatim: Prime Agent "executes model-generated Python and project
commands with your user permissions. Its worker and kernel processes improve
lifecycle isolation and recovery; they are **not** a security sandbox."

This matches the user's own rule 7. It means ADOS must never treat the Prime
process as a trust boundary. It is a *worker*, and the boundary has to be on
the ADOS side of the wire.

---

## 2. ADOS integration points (from its source)

| Concern | Where it lives | Reusable as-is? |
|---|---|---|
| Capability vocabulary | `contracts/capabilities.py` — closed enum + `DYNAMIC_CAPABILITY` sentinel | Yes |
| Risk → tier policy | `orchestrate/governance.py:assign_policy_tier()` | Yes |
| Capability execution | `integrations/` `IntegrationHub` + connectors, `CapabilityCall` | Yes |
| Human approval pause/resume | `orchestrate/moa/graph.py` `interrupt()` / `resume_moa_task(task_id, …)` | Pattern, yes |
| Durable paused state | `db/checkpointer.py` + `moa_task_breakers` (shipped 2026-08-09) | **Yes — directly** |
| Audit trail | `app.state.orchestrator.audit_trail`, event bus | Yes |
| MCP **server** libraries | `fastmcp` already installed (in `.venv`) | Yes |
| MCP **client** onboarding | `orchestrate/onboarding/` (BYOC) | Not needed here |

Two ADOS facts make this much cheaper than it would have been a week ago:

1. **Durable, cross-process task state already exists and is proven.** Stage 2b
   put paused approvals in a Postgres LangGraph checkpointer and demonstrated a
   task started by one process being resumed by another. A long-running Prime
   session that pauses for approval is the same problem, already solved.
2. **`fastmcp` is already a dependency**, so ADOS can host an MCP HTTP endpoint
   without adding anything.

---

## 3. Proposed runtime boundary

Two directions of traffic, two different mechanisms. Keeping them distinct is
the core of the design.

```
                    ADOS  (control plane, system of record)
   ┌──────────────────────────────────────────────────────────────┐
   │  Mission  ·  Agent identity  ·  Policy/Risk  ·  Approvals     │
   │  Capability bus (IntegrationHub)  ·  Audit  ·  Knowledge      │
   └───────────┬──────────────────────────────────┬───────────────┘
               │ (A) drive                        │ (B) serve
               │  subprocess JSONL                │  MCP over HTTP
               ▼                                  ▲
   ┌────────────────────────┐          ┌──────────┴───────────────┐
   │ PrimeAgentRuntime      │          │ ADOS Capability Gateway  │
   │ spawns:                │          │ (fastmcp, /mcp)          │
   │  prime-agent --mode rpc│          │  session-scoped token    │
   └───────────┬────────────┘          └──────────▲───────────────┘
               │ stdin: prompt/steer              │ tool call
               │ stdout: events                   │
               ▼                                  │
   ┌──────────────────────────────────────────────┴───────────────┐
   │            PRIME AGENT (execution plane, untrusted)           │
   │  persistent IPython kernel · subagents · skills · goals       │
   │  `import ados; await ados.request_capability(...)`            │
   └──────────────────────────────────────────────────────────────┘
```

### (A) Downward: ADOS drives the session

A new `orchestrate/runtime/` package:

- `AgentRuntime` — the protocol from `12-runtime-contract.md`, expressed with
  only the operations Prime Agent actually supports (create, start, send,
  status, cancel, resume; **no pause primitive exists**, so it is not in the
  interface — see Gaps).
- `PrimeAgentRuntime` — spawns `prime-agent --mode rpc`, writes JSONL commands,
  reads the event stream, and normalizes `AgentEvent`s into ADOS events.

`PrimeAgentClient.execute_rlm_task()` becomes a thin backward-compatibility
shim over this, so the existing capability keeps working — but the fabricated
"live" branch is deleted outright rather than extended.

### (B) Upward: Prime Agent requests ADOS capabilities

**ADOS hosts an MCP HTTP server.** Prime Agent connects to it as a declared
`mcpServers` entry consumed by a small Python skill inside the kernel.

Hard constraint from `docs/mcp-integrations.md`: *"stdio (local-subprocess)
servers are not yet wired through to the kernel — the host drops non-HTTP
entries — so an integration must target an HTTP endpoint."* HTTP is therefore
not a preference, it is the only option.

Authentication uses `bearerTokenEnvVar`, not OAuth — a **per-session token**
minted by ADOS when the runtime session is created and injected into the child
process environment.

That token is the whole authorization story, and it is why this is safe:

> The token identifies the *mission and session*. ADOS resolves it server-side
> to `allowed_capabilities`. Prime Agent cannot request a capability the
> mission did not grant, cannot widen its own grant, and never holds a
> credential for any downstream system. **Prime Agent decides what it wants;
> ADOS decides what it may do.**

### Handling approval without holding a connection open

A Tier 1/2 capability needs a human. Blocking the MCP HTTP call for minutes or
hours is the obvious approach and the wrong one — it ties a socket to a human's
attention span and dies on restart.

Instead the gateway is **two-phase and pollable**:

```python
req = await ados.request_capability(capability="...", arguments={...})
# -> {"status": "pending_approval", "request_id": "..."}  (or "executed")
res = await ados.await_capability(request_id=req["request_id"])
# polls; returns the governed result once decided
```

`pending_approval` persists as an ADOS row, survives restart, and is decided
through the existing approval UI. This reuses the Stage 2b durability work
rather than inventing a second pause mechanism.

---

## 4. Concrete end-to-end sequence (the first milestone)

Mission: *"Investigate a synthetic software incident and produce a root-cause
report."*

```
 1. POST /missions                     ADOS creates mission (durable row)
 2. assign agent                       mission -> prime-rlm-agent, allowed_capabilities=[CREATE_INCIDENT]
 3. mint session token                 scoped to (mission_id, session_id, allowed set)
 4. PrimeAgentRuntime.create()         spawn `prime-agent --mode rpc` in a disposable workspace,
                                       env: ADOS_MCP_TOKEN=<session token>, provider creds
 5. send objective                     {"type":"prompt","message": <objective + success criteria>}
 6. Prime Agent works                  real IPython kernel: reads the synthetic incident
                                       artifacts, reasons, forms a root cause
 7. Prime requests a capability        `await ados.request_capability("CreateIncident", {...})`
 8. ADOS gateway governs               token -> session -> allowed? -> assign_policy_tier()
                                          Tier 0  -> execute via IntegrationHub
                                          Tier 1+ -> persist pending_approval, return request_id
 9. result returns to Prime            structured dict; agent continues reasoning
10. agent_end                          ADOS captures the final report from the event stream
11. persist + audit                    mission.result, mission.status, audit trail entries
```

Steps 6–9 are the ones that make this a real integration rather than another
facade: an actual model, running actual code, calling back into ADOS
governance, and continuing based on what ADOS allowed.

---

## 5. Minimal implementation plan

Deliberately narrow. No agent factory, no self-improvement, no scheduling, no
subagent hierarchies — those are properties of a running system, and there
isn't one yet.

| # | Change | Why it is in the slice |
|---|---|---|
| 1 | `orchestrate/runtime/base.py` — `AgentRuntime` protocol, `AgentSessionSpec`, normalized event types | The boundary itself |
| 2 | `orchestrate/runtime/prime.py` — `PrimeAgentRuntime` over `--mode rpc` | Real execution |
| 3 | `db/models/mission.py` + `runtime_session` + migration | ADOS as system of record |
| 4 | `backend/app/mcp_gateway.py` — fastmcp app at `/mcp`, session-token auth, governance + audit | The controlled bridge |
| 5 | `integrations/prime_skill/` — the `ados` Python skill package + `settings.json` provisioning | How the kernel reaches ADOS |
| 6 | Rewrite `PrimeAgentClient` as a shim; delete the fabricated branch | Compatibility without the lie |
| 7 | Tests: real subprocess run, real MCP call, denied capability, approval pause, restart | Proof, per the project's own convention |

**Explicitly deferred:** heartbeats, schedules, `/refine`, subagent supervision,
agent messaging, multi-session missions, and the Domain-Pod → worker fan-out in
the second diagram. All are reachable from this boundary; none belong in slice
one.

---

## 6. Risks and tradeoffs

**Prime Agent is not a sandbox.** It executes model-generated code as the
invoking user. Mitigation for the slice: a disposable workspace directory, never
the ADOS repo or the user's home; no downstream credentials in its environment;
only the scoped MCP token. Longer term this wants the same container treatment
`orchestrate/onboarding/sandbox_runner.py` already uses. Accepting this as-is in
production would violate the project's own rule 6.

**The MCP endpoint must be network-reachable from the Prime process.** Fine
locally; in compose it means the backend must expose `/mcp` on a reachable host,
and the token becomes a real secret in transit. Needs TLS before any
non-localhost deployment.

**Two runtimes, two languages, one lifecycle.** A Node subprocess owned by a
Python async app introduces zombie processes, stdout backpressure, and partial
JSONL reads. The RPC framing rule (split on `\n` only) must be honoured
exactly; a naive line reader is documented as non-compliant.

**Prime Agent owns session storage; ADOS owns mission truth.** Deliberate, and
it means the two can disagree after a crash. ADOS's mission row is
authoritative; the Prime session is treated as an opaque, re-attachable handle.
`runtime_session_id` may dangle if `~/.prime/agent/sessions` is cleared — the
mission must survive that.

**No native pause.** Prime Agent supports interrupt/cancel and resume-from-saved
session, but not "suspend in place". So an approval wait is modelled as the
agent polling, not as a suspended runtime. That is a real semantic difference
from the MOA's `interrupt()` and should not be papered over.

**Model capability — RESOLVED, but it is model-specific.** Three models were
run through the real headless binary in a disposable workspace. Only some drive
Prime Agent's loop:

| Provider / model | Result |
|---|---|
| `groq` / `llama-3.3-70b-versatile` | **Works.** 1 kernel tool execution, file written. ~45s. First-class Prime Agent provider — no `models.json` needed. |
| `nvidia-nim` / `openai/gpt-oss-120b` | **Works.** 1 kernel tool execution, file written. ~100s. |
| `nvidia-nim` / `nvidia/llama-3.3-nemotron-super-49b-v1` | **Fails silently.** Real API call (3819 in / 11 out tokens, `stopReason: "stop"`) but `content: []` — no text, no tool call, no file. |
| `nvidia-nim` / `moonshotai/kimi-k2.6` | **Hangs.** Zero bytes of output after 5 minutes; killed. |

The nemotron failure mode matters for the runtime design: the agent reports a
clean `agent_end` and exits 0 having done **nothing**. A runtime adapter that
trusts exit codes would record that as success. The adapter must assert on
observed effects — tool executions, emitted result — not on process exit.

Recommended default: **Groq**, since it is natively supported, fastest, and its
key is already in `.env`.

**Cost and latency.** Each mission is a real multi-turn agent run.

---

## Provisioning notes (what was changed outside the repos)

- `~/.prime/agent/models.json` — **created** (did not previously exist) to add
  the OpenAI-compatible `nvidia-nim` provider pointing at
  `https://integrate.api.nvidia.com/v1`, reading `NEMOTRON_API_KEY`.
- `~/.prime/agent/` had no `auth.json` and no `settings.json`: Prime Agent had
  never been logged in or configured on this machine before this work.
