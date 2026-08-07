> **Superseded 2026-08-04, same day.** This doc's original verdict below
> ("don't build Kafka/Redpanda now") was the evidence-based recommendation
> at the time, but the user explicitly chose to adopt Kafka anyway rather
> than wait for the trigger condition described here. Kept in place as
> the honest record of the reasoning that came before that call, not
> rewritten as if Kafka were always the plan. What actually got built:
> real Apache Kafka (KRaft mode, no ZooKeeper, Apache 2.0) via
> `docker-compose.yml`'s `kafka` service, `backend/app/eventbus/
> kafka_bus.py` (`KafkaEventBus`, using `aiokafka`), wired through the
> existing `EventBus` abstraction exactly as this doc's "Recommendation"
> section anticipated it eventually would be. Live-tested end-to-end
> (`tests/test_kafka_bus.py`, 4 tests against a real broker, plus a live
> smoke test through the actual FastAPI app: publish → Kafka →
> `GET /events` round-trip, confirmed working). One unrelated, pre-existing
> bug found while smoke-testing, not introduced by this work: the
> `/events/stream` SSE route never actually delivers a live event past the
> initial ping in either backend (reproduced identically on the default
> in-memory backend) — a `request.is_disconnected()` interaction, not a
> Kafka issue. See the vault TODO for status.

# Kafka/Redpanda vs. the Existing Event Bus — Comparison

Resolves the open question in
[`docs/010-api-contracts.md`](../docs/010-api-contracts.md) ("Kafka vs. a
managed event bus for the MVP") and the vision doc's core-substrate item
("Stand up Kafka/Redpanda ... EventEnvelope v2"). Written 2026-08-04
alongside the EventEnvelope v2 schema change (`correlation_id`/`trace_id`/
`idempotency_key` — see `contracts/event_envelope.py`), which is the part
of that item that's now done regardless of this doc's outcome.

## Scope & Methodology

Unlike the custom-orchestrator-vs-LangGraph comparison
(`orchestrate_langgraph/COMPARISON.md`), this is not a build-both-and-
measure exercise. That comparison was warranted because the question was
genuinely undecided and the stakes were high (replacing the live
orchestrator). Here, the codebase already contains a real answer to
inspect: `backend/app/eventbus/` implements the `EventBus` abstraction
(`base.py`) with two backends, `InMemoryEventBus` and `RedisEventBus`, both
read in full for this comparison rather than assumed from familiarity with
Kafka/Redis in general. Standing up an actual Kafka or Redpanda broker to
benchmark throughput against a workload that doesn't exist yet (see
"Who's actually consuming this today" below) would produce numbers that
don't reflect any real future usage pattern — so this stays a grounded
architectural comparison, not a synthetic benchmark.

## Current state (verified, not assumed)

- **Default backend is `memory`** (`backend/app/config.py:29`,
  `event_bus_backend: str = "memory"`). `InMemoryEventBus` is a Python list
  + `asyncio.Queue` per subscriber — zero external infra, not durable
  across a process restart, not shared across processes.
- **`RedisEventBus` exists and is real code** — Redis Streams (`XADD`,
  `XREVRANGE`, `XREAD`), opt-in via `EVENT_BUS_BACKEND=redis`. But it is
  **not stood up anywhere in this project today**: `docker-compose.yml`
  runs only Postgres, with an explicit comment that Redis is "a separate,
  existing concern" left for whoever needs it. And it has **zero test
  coverage** — no test in `tests/` or `backend/tests/` constructs a
  `RedisEventBus` or exercises it, mocked or otherwise. It's implemented,
  plausible, and unverified.
- **Who's actually consuming this today**: one producer process (the
  orchestrator, via `orchestrate/orchestrator.py` + `agent_runner.py` +
  `agents/sdk/base.py`), consumed by browser SSE connections
  (`events_stream.py`), simple HTTP polling (`events.py`'s `GET /events`),
  and one demo script. Every domain agent runs as an in-process Python
  call, not a separately deployed service — confirmed both in code and in
  [[agentic-org-reuse-survey]]'s finding that this is structural, not a
  gap, until domain agents actually decouple.

## A real gap found, independent of Kafka vs. Redis

`RedisEventBus.stream()` uses plain `XREAD` starting from `"$"` (only
entries from subscription time onward), not Redis Streams' consumer-group
API (`XREADGROUP`/`XACK`). `last_id` lives only in the Python generator's
local variable — nothing commits a consumer's read position anywhere
Redis-side. If a `stream()` consumer's process restarts, it silently
resumes from "now," not from where it left off. This is the actual
durable-offset gap the vision doc's Kafka framing was reaching for — but
it's an **implementation gap in the existing Redis backend**, fixable
without adding a new broker technology (Redis Streams natively supports
consumer groups; this code just doesn't use that feature yet).

Separately: the one place the vision doc explicitly wants this property —
§5.4's async governance approval, "an incident paused waiting for approval
survives a restart" — is **already solved**, but by Postgres, not the
event bus: [[ados-database-persistence-migration]]'s Phase 4 verified
exactly this end-to-end (incident paused mid-approval → server restarted →
still there → approved correctly) via `audit_trail`/`PendingApproval`
rows, live-tested before the event-bus question was ever revisited. The
event bus's own durability is not what's carrying that guarantee today.

## Kafka/Redpanda: what it would genuinely add

- Native partitioned topics + consumer groups with committed offsets,
  enabling multiple independently-scaled consumer *services* (not just
  fan-out to browser tabs) to each track their own durable read position.
- Stronger built-in replication/durability guarantees than a single Redis
  instance.
- Log compaction, if a topic's "latest value per key" semantics become
  useful later.

All three matter most once domain agents are separate deployable services
consuming the same event stream independently — which hasn't started (see
[[ados-orchestration-platform-vision]]'s MOA/domain-pod backlog, still at
zero built domains). Redpanda specifically removes Kafka's JVM/ZooKeeper
weight (single Kafka-API-compatible binary), which narrows but doesn't
close the operational gap against Redis: it's still a new stateful broker
service to run, monitor, and back up, layered on top of the Postgres this
project just took on as new required infrastructure
([[ados-database-persistence-migration]]).

## Recommendation

**Don't stand up Kafka or Redpanda now.** Nothing in ADOS's current
architecture has more than one producer or needs partition-level parallel
consumption — introducing a new broker technology ahead of that need
repeats a pattern this project has deliberately avoided elsewhere (Redis
was rejected for `cascade_breaker.py` for the same reason: "would add
cross-process durability nothing here currently needs").

Two concrete, smaller follow-ups instead, neither requiring new
infrastructure:

1. **Fix the `RedisEventBus.stream()` gap** — switch it to Streams
   consumer groups (`XREADGROUP`/`XACK`) so that *if/when* the Redis
   backend is turned on, it actually gets durable per-consumer offsets.
   Small, contained, no interface change (`EventBus`'s abstract methods
   don't change), and it's the one concrete correctness gap this
   investigation found. Not done as part of this pass — flagged for a
   deliberate follow-up, not silently bundled in.
2. **Revisit Kafka/Redpanda specifically when domain agents decouple into
   separately deployed services** — the same trigger condition already
   established for `cascade_breaker.py`'s cross-domain cascade scenario
   and the event-schema `StageInput`/`StageOutput` gap. Until then, this
   doc's answer to `docs/010-api-contracts.md`'s open question is: stay on
   the existing `EventBus` abstraction (memory today, Redis when
   multi-process is needed), not Kafka/Redpanda.
