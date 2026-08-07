# OPA (Rego) Policy-Interception Spike

Resolves the vision doc's core-substrate item ("Stand up OPA (Rego)
skeleton + policy interception sidecar in front of one existing agent's
tool layer, as a spike"). Written 2026-08-04, same session as
[`EVENT_BUS_COMPARISON.md`](EVENT_BUS_COMPARISON.md).

## Scope & Methodology

Unlike the Kafka/Redpanda question, this one was explicitly scoped as "a
spike" — a real, working trial, not a whole-system rollout. So this
built an actual thing: `infrastructure/opa_spike/` contains a real Rego
policy (`policy.rego`) re-implementing the two rules that exist today in
`integrations/policy_engine.py` (`require_governance`,
`hot_disable_policy_rule` from `integrations/capability_manifest.py`),
an async Python client (`opa_client.py`) that queries a locally running
`opa run --server` process over its REST API the way a real sidecar
deployment would, and a correctness + latency comparison
(`compare.py`) run against the same scenarios through both paths. Nothing
here is wired into the live `ConnectorPolicyEngine` or `IntegrationHub` —
same posture as `orchestrate_langgraph/`'s comparison work: a standalone
experiment informing a decision, not a silent replacement.

## Correctness

All three scenarios matched between the existing Python rules and the
Rego policy queried over HTTP:

```
[MATCH] governed, active capability: python=True   opa=True
[MATCH] hot-disabled capability:     python=False  opa=False ('capability NotifyOperator is hot-disabled')
[MATCH] missing governance:          python=False  opa=False ('capability call missing required governance context')
```

**A real correctness pitfall found along the way, not glossed over**:
the first version of `capability_call_to_opa_input()` serialized a
missing `governance` as JSON `null`. Rego's `not input.governance` only
treats a **fully absent key** as falsy — an explicit `null` is a defined,
present value, so `not null` does *not* trigger the deny rule. That first
version silently let ungoverned calls through OPA while the in-process
Python rule correctly denied them — a genuine, easy-to-miss divergence
between "Python's single `None`" and "JSON/Rego's null-vs-absent
distinction." Fixed by omitting the key entirely rather than nulling it
(see `opa_client.py`'s docstring). Concrete illustration of the real cost
of maintaining policy logic in a second language: it's not just a
syntax port, the semantics of "missing" don't automatically carry over.

## Latency

Measured 200 calls each, allow-path, after switching the client to a
single pooled `httpx.AsyncClient` (keep-alive) rather than a fresh
connection per call — the first version measured ~3.5ms/call, almost
entirely TCP handshake cost, not a fair steady-state number:

```
in-process Python rule: ~0.0000 ms/call
OPA sidecar over HTTP:  ~0.39 ms/call (pooled connection, keep-alive)
overhead: ~10,000x relative, ~0.4ms absolute
```

In relative terms a network hop is always going to dwarf a bare function
call — that ratio isn't a meaningful verdict by itself. In absolute
terms, 0.4ms is small against ADOS's actual call pattern: one governance
check per capability invocation, not a hot path evaluated thousands of
times per second (`run_incident()` issues exactly one `hub.invoke()` per
incident today — same single-call shape noted when `cascade_breaker.py`
was investigated). Latency is not the blocker here.

## What OPA would genuinely add over the existing Python rule engine

`integrations/policy_engine.py`'s own docstring already states its
design goal: *"real rules get added here as policy data grows, without
orchestration/agent code changing."* That's also OPA's core pitch. The
difference is *where* that data-not-code property lives:

- **Today**: policy rules are Python functions, edited by whoever can
  open a PR and ship a deploy. Auditable via git, testable via pytest,
  but coupled to a Python deploy cycle.
- **With OPA**: policy rules are `.rego` files, editable independently of
  the application's deploy cycle (by compliance/security reviewers who
  don't need to touch application code), and queryable uniformly by any
  service in any language — relevant once domain agents are separately
  deployed services rather than one shared Python process, the same
  precondition already established for the Kafka/Redpanda question.

## A real cautionary data point from prior research

[[agentic-org-reuse-survey]]'s findings apply directly here:
`agentic-org/auth/opa.py` is a real ~34-line OPA REST client, but the
repo has **zero `.rego` files** and zero real call sites outside one unit
test that mocks the client directly — despite that codebase's own
architecture docs prominently diagramming "L8: OPA Policy Engine." A
mature, funded, production platform added OPA to its architecture and
never actually used it. That's not a reason to avoid OPA here — this
spike proves it works and is cheap enough to run — but it's a real signal
that OPA gets adopted architecturally before it's actually needed more
often than the reverse, and this project has been deliberately avoiding
that exact pattern (see the Kafka/Redpanda verdict).

## Recommendation

**The spike succeeds — OPA is correct, fast enough, and cheap to run
(a single static Go binary, no JVM, Apache-2.0, consistent with the
vision doc's OSS stack).** But don't wire it into the live
`ConnectorPolicyEngine` yet. The concrete reason to adopt it — a shared
policy decision point queried uniformly by multiple independently
deployed services — has no consumer today, same as Kafka/Redpanda's
verdict, and for the same reason: domain agents are still one in-process
Python codebase, not separate services. Until that changes, the existing
`ConnectorPolicyEngine` already delivers OPA's main practical benefit
(new rules don't require touching orchestrator/agent code) without taking
on a new process to run, monitor, and define fail-open/fail-closed
behavior for if it's unreachable.

**Revisit when domain agents actually decouple into separate services**
— the same trigger condition now established for three separate
core-substrate questions this session (cascade breaker, Kafka/Redpanda,
and this one). At that point, `policy.rego` in this directory is a real
starting point, not a throwaway — it already passes the correctness bar
against the two rules that exist today.
