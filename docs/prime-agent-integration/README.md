# Prime Agent Runtime Integration

**ADOS is the organizational control plane. Prime Agent is an execution plane
underneath it.**

Prime Agent decides what it wants to do. ADOS decides what it is allowed to do.

This directory documents a real integration: a containerized Prime Agent driven
over RPC by ADOS, reaching back into ADOS only through a governed MCP capability
gateway. It replaced a facade in which `execute_rlm_task` returned hardcoded
dictionaries and no runtime existed at all.

| Document | Contents |
|---|---|
| [10-current-runtime-state.md](10-current-runtime-state.md) | Audit of the pre-existing integration, and what was actually there |
| [11-runtime-boundary-design.md](11-runtime-boundary-design.md) | Where the boundary sits and why |
| [12-runtime-design-note.md](12-runtime-design-note.md) | RPC lifecycle, container lifecycle, gateway contract, token lifecycle, acceptance semantics, kernel contract |
| [13-acceptance-report.md](13-acceptance-report.md) | The end-to-end acceptance run, with its full trace |
| [14-known-limitations.md](14-known-limitations.md) | Everything observed to be limited, incomplete, or provider-specific |
| [15-provider-benchmark.md](15-provider-benchmark.md) | NVIDIA NIM vs Groq vs local Ollama, measured |

---

## Architecture

```
   ADOS (control plane)                         Prime Agent (execution plane)
   ─────────────────────                        ────────────────────────────
   missions, policy, risk,
   approvals, audit, connectors

   PrimeAgentRuntime  ──── docker run ────────▶  container (non-root, uid 10001)
   (orchestrate/runtime/)                          │
        │                                          ├─ /work  disposable bind mount
        │  docker exec -i … --mode rpc              ├─ .agent/ per-session config
        └──── JSONL over stdin/stdout ────────▶     └─ IPython kernel  ← the ONLY tool
                                                          │
   MCP capability gateway  ◀──── HTTP MCP ────────────────┘
   (backend/app/mcp_gateway.py)                     via the `ados` Python skill
        │
        ├─ authenticate session token (identity only)
        ├─ resolve mission grant  ← SERVER SIDE, never from the request
        ├─ policy tier + risk class
        ├─ idempotency
        ├─ IntegrationHub → connector
        └─ audit row written by the executor
```

The two halves are deliberately separate. `orchestrate/runtime/prime.py` drives
the runtime *downward* and never relays capability requests; the runtime reaches
ADOS *upward* over HTTP MCP. **The adapter cannot forge a capability call**,
because it is not on that path.

## Execution flow

1. ADOS creates a `MissionRow` carrying the capability grant and the evidence.
2. ADOS creates a `RuntimeSessionRow` and mints an opaque session token, storing
   only its SHA-256.
3. `PrimeAgentRuntime.start()` prepares a disposable workspace, writes the
   per-session agent config, and starts the container on a dedicated network.
4. ADOS `docker exec`s `cli.js --mode rpc` and sends the objective as JSONL.
5. The model works inside the persistent IPython kernel — its only tool.
6. To act or to retrieve organizational data, it calls the `ados` skill, which
   speaks HTTP MCP to the gateway.
7. The gateway authenticates, re-resolves the grant server-side, applies policy,
   executes through `IntegrationHub`, and writes the audit row itself.
8. ADOS consumes the event stream, persists normalized events, and decides the
   mission's outcome from its own records.
9. Teardown always runs: container removed, workspace deleted.

## Trust boundaries

| Boundary | What crosses it | What never crosses it |
|---|---|---|
| ADOS → container | objective, workspace files, LLM provider key, session token | database URL, connector credentials, ADOS user identity |
| container → ADOS | capability name + arguments + idempotency key | any grant, role, or tier |
| gateway → connectors | a validated `CapabilityCall` with governance attached | anything the runtime asserted about itself |

**The runtime cannot widen its own permissions.** No request field carries a
capability list. The grant is read from the mission row on every call, so a
confused or compromised agent can ask for anything and still receive exactly
what the mission allowed.

## Model and provider abstraction

Nothing in `orchestrate/runtime/` names a provider. `provider`, `model`,
`provider_key_env`, `provider_key` and a full `models_json` are constructor
arguments on `PrimeAgentRuntime`, written into the session's own agent directory
at start-up. Switching providers is a caller-side change; the image itself
carries no provider choice and no ADOS endpoint.

The requirement that *is* architectural: the configured model must hold the
harness prompt (measured 4–9k tokens in-container) and sustain a multi-turn tool
loop. See [15-provider-benchmark.md](15-provider-benchmark.md).

## Security model

* **The container is the boundary.** Prime Agent executes model-generated Python
  with the permissions of whoever runs it, and its README states the kernel is
  not a security sandbox. Nothing here ever runs it on the host.
* Non-root (uid 10001), `--memory 2g --cpus 2 --pids-limit 512`.
* Dedicated bridge network with no other ADOS service on it. **This is network
  placement, not egress filtering** — see the limitations document.
* Workspace is a disposable temp directory, never the ADOS repo and never `$HOME`.
* Exactly two secrets injected: the LLM provider key and an identity-only
  session token that is opaque, carries no claims, and is stored hashed.
* The image is built from a staged two-repo context containing only Prime Agent
  source plus the ADOS skill — no ADOS source, no credentials.

## Acceptance criteria

**A mission succeeds only when the required governed capabilities actually
executed.** Implemented in `orchestrate/runtime/acceptance.py`.

Two rules make that meaningful:

1. **Agent narrative is never authoritative evidence.** `evaluate_mission()`
   has no `final_answer`, `report`, or `confidence` parameter, and a test
   asserts that signature. A runtime whose kernel could not execute a single
   statement once produced a fluent root-cause report blaming disk-space
   exhaustion on a database server that appeared nowhere in the incident it
   never read. Nothing in the prose gave it away; what gave it away was that
   ADOS had executed no capability.

2. **Evidence must be retrieved, not pre-loaded.** The case file lives on
   `missions.evidence`, reachable only through `FetchIncidentEvidence`. A
   runtime handed its evidence up front can write a plausible report with a
   broken kernel. Force it through a capability and a broken runtime produces no
   facts — detectable in SQL rather than by reading prose.

Related, enforced repository-wide by `backend/tests/test_execution_semantics.py`:

```
tool attempt      != tool success
process exit 0    != mission success
HTTP 200          != capability success
agent narrative   != evidence
model completion  != mission completion
```

## The kernel contract

The model's only tool is a **persistent IPython kernel**. Everything sent to it
is plain Python source, executed directly in that kernel.

* Write Python source directly. Top-level `await` is supported.
* **Do not** use `!` shell escapes, `!python`, `!python3`, `%%bash`, or
  `subprocess` as a substitute for writing Python. There is no `python` on
  `PATH`; the kernel *is* the interpreter.
* Variables persist between cells. Bind results to names instead of re-fetching
  or re-printing them — this is Prime Agent's own documented design ("IPython is
  the agent's long-lived notebook… preserve useful state across turns"), and it
  is why large payloads should stay in the kernel rather than being dumped into
  the model's context.
* Reach ADOS through the provided `ados` Python skill, never by constructing
  HTTP calls.

Violating this is observable rather than silent: a `!python` escape returns
`Couldn't find program: 'python'`, and no `python` symlink was added to the
image — making the container forgiving of the wrong idiom would hide contract
violations instead of surfacing them.

## Status

**Prime Agent is genuinely integrated into ADOS with a working governed
execution path and a successfully demonstrated end-to-end mission.**

Demonstrated on 2026-08-10: a synthetic incident mission retrieved its evidence
through `FetchIncidentEvidence`, reasoned over it in the kernel, and invoked
`NotifyITHelpdesk` — both recorded as `executed` by the gateway, and the mission
accepted by `evaluate_mission()` on those rows. Full trace, including the exact
model-generated code, in [13-acceptance-report.md](13-acceptance-report.md).

Read that report's caveats. In particular, `NotifyITHelpdesk` resolved to the
**console** connector and returned `"[console] simulated NotifyITHelpdesk"` — the
governed path is real end to end, but no IT helpdesk was actually notified. What
is demonstrated is the control path, not a real downstream side effect.

**This is not production ready, and is not described as such.** Production
hardening is a separate phase. The honest inventory of what is missing is in
[14-known-limitations.md](14-known-limitations.md) — including no egress
filtering, no approval round trip, single-session missions only, and a NULL
`runtime_session_id`.
