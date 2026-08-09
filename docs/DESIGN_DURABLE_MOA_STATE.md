# Durable MOA state — scoping the two options

Stage 2's headline item ([PRODUCTIZATION.md](PRODUCTIZATION.md)). Written
2026-08-07, before any code, so the driver decision is made on evidence.

[In plain terms: right now, when the AI pauses to ask a human "should I really
stop this person's paycheck?", that question exists only in the server's
short-term memory. Restart the server and the question — plus the
half-finished task behind it — is gone. You also can't run a second copy of
the app, because the two copies can't see each other's pending questions.
This document is about how to fix that, and the one real trade-off involved.]

---

## The problem is three pieces of state, not one

This is the thing that makes it more than "swap the checkpointer". A paused
MOA task is held in three places, and **all three** have to survive a
restart and be reachable from a different process:

**1. The graph's own state** — `orchestrate/moa/graph.py:477` compiles with
`InMemorySaver()`. Dies with the process.

**2. The live Python objects** — `backend/app/routers/moa.py:82` stores
`(graph, config, cascade_breaker)` in `app.state.moa_pending_tasks`, and
`resume_moa_task(graph, config, ...)` takes the *live graph object* as its
first argument. A second replica has a different `app.state`, so it 404s.
`langgraph_agents.py` does the same thing with `itsm_pending_proposals`.

**3. The cascade breaker's streak** — and this is the one that hides.
`build_graph(hub, cascade_breaker)` bakes the breaker into the compiled
graph through the `_make_act_node(hub, cascade_breaker)` closure. Its
`_streak` list is what stops many individually-safe auto-approved actions
adding up to something nobody reviewed. **Rebuilding the graph on another
replica without restoring that streak silently resets the safety property
to zero** — no error, no test failure, just a protection that quietly stops
protecting. Any design that forgets this is worse than doing nothing,
because the system would still *look* safe.

---

## Work required regardless of which option we pick

None of this depends on the driver decision:

- `resume_moa_task(graph, config, ...)` → `resume_moa_task(task_id, ...)`,
  rebuilding the graph from `build_graph()` + `{"configurable":
  {"thread_id": task_id}}`. Compiling is cheap; the checkpointer holds the
  state, not the graph object.
- Delete `app.state.moa_pending_tasks` and `app.state.itsm_pending_proposals`.
- Persist the cascade breaker streak per task, and restore it when
  rebuilding. New table or a column on an existing one + Alembic migration.
- `GET /governance/circuit-breaker` currently aggregates over
  `app.state.moa_pending_tasks` — must read from the store instead.
- Tests: kill-and-restart mid-approval; two app instances sharing one
  database, approving through the "wrong" one.

That's the majority of the work, and it's identical either way. **The driver
choice only decides how item 1 gets stored.**

---

## Option A — the official `langgraph-checkpoint-postgres`

Version 3.1.1, requires `langgraph-checkpoint >=4.1.0,<5.0.0`. We have
4.1.1, so it's compatible today.

**Cost:** pulls in `psycopg>=3.2.0` and `psycopg-pool>=3.2.0` — a second
Postgres driver and a second connection pool alongside asyncpg.

`requirements.txt` says *"asyncpg only, no second sync DB driver; Alembic
drives it via the async bridge instead."* Worth being precise about what
that rules out: psycopg 3 has native async support, so this isn't the *sync*
driver that note was guarding against. But it is a second driver against the
same database, which is the spirit of it.

**What you get:** `AsyncPostgresSaver`, maintained upstream, with a
`.setup()` that creates its own tables. It already handles checkpoint
versioning, pending writes, and blob storage for large channel values —
the parts that are easy to get subtly wrong.

**Extra operational surface:** two pools to size, two places a connection
leak can happen, and its tables live outside Alembic's migration history
(created by `.setup()`), so schema provenance is split.

---

## Option B — hand-rolled on SQLAlchemy/asyncpg

Implement `BaseCheckpointSaver` against the existing stack. One driver, one
pool, tables in Alembic like everything else.

**The real cost, measured rather than guessed.** I checked which methods
raise `NotImplementedError` on the installed base class:

```
acopy_thread, adelete_for_runs, adelete_thread, aget_tuple, alist,
aprune, aput, aput_writes, get_next_version
(+ their 7 sync twins)
```

Only `aget`, `aget_delta_channel_history` and `with_allowlist` have usable
defaults. So it is **9 async methods plus sync equivalents**, not the three
or four you'd assume from the interrupt/resume flow alone. `aput_writes` and
`get_next_version` in particular encode LangGraph's internal versioning
semantics, which are undocumented and can change across minor versions.

**The risk that matters:** this is the store protecting paused approvals. A
subtle bug in checkpoint serialisation doesn't announce itself — it
corrupts a paused offboarding, and you find out when a human clicks approve
and something wrong executes. That is the single worst failure mode this
system has.

**Ongoing:** every `langgraph` upgrade becomes a compatibility review of our
own checkpointer.

---

## Recommendation

**Option A.** The principle in `requirements.txt` is a good one, and I'd
normally defend it — but it was written to avoid dragging in a sync driver
for Alembic's convenience, not to rule out the maintained implementation of
the most safety-critical store in the system.

Hand-rolling nine methods against undocumented internals, to protect exactly
the state we least want corrupted, to avoid one dependency, is the wrong
trade. If the second pool becomes a real operational problem it can be
revisited with evidence; a corrupted approval cannot be revisited at all.

**If Option B is preferred anyway**, the mitigation is to build it behind
the same interface and run both in parallel against the test suite for a
period — writing to both, reading from asyncpg, comparing. That's real extra
work, and worth it only if the second driver is genuinely unacceptable.

---

## Either way, this lands in three steps

1. **Checkpointer swap** — `InMemorySaver` → durable, wired through
   `main.py`'s lifespan. Restart survival is provable at this point.
2. **Kill the process-local dicts** — rebuild graphs on demand, change the
   resume signatures. Multi-replica becomes possible here.
3. **Persist the cascade streak** — the safety property that would otherwise
   silently reset. Test that an open breaker is still open after a restart.

Step 3 is the one to not skip. It is the least visible and the most
load-bearing.

---

## What actually shipped (2026-08-09)

Option A, as recommended. Steps 1-3 all landed; a few things differed from
the plan above and are worth recording.

**Steps 2 and 3 could not be separated.** The plan lists them as sequential.
They aren't: deleting `moa_pending_tasks` without persisting the streak means
every resume rebuilds a fresh `CascadeCircuitBreaker`, silently zeroing the
protection. Shipping step 2 alone would have left the tree in exactly the
state this document warns about, so both went in together.

**`graph.get_state()` had to become `await graph.aget_state()` everywhere.**
Not in the plan because it isn't visible until you try it: `AsyncPostgresSaver`
rejects synchronous access from the running loop outright
(`InvalidStateError: Synchronous calls to AsyncPostgresSaver are only allowed
from a different thread`). The sync form keeps working against `InMemorySaver`,
so tests would have stayed green while production failed at the moment a human
clicked approve.

**Autogenerate tried to delete the checkpointer's tables.** They're created by
the library's own `.setup()`, so they're absent from `Base.metadata` and look
like tables someone removed from the models. The first generated revision
contained `drop_table()` for all four — applying it would have destroyed every
paused approval. `alembic/env.py` now filters them via `include_object`.

**The breaker went in its own table, not into MOAGraphState.** Folding it into
the graph state would have been durable for free, but
`GET /governance/circuit-breaker` aggregates across tasks and would then have
had to scan and deserialise every thread's latest checkpoint. A row per paused
task answers it with an ordinary query. See `db/models/moa_task_breaker.py`.

**ITSM needed no companion table.** `itsm_pending_proposals` is gone too, but
that flow has no breaker, so the checkpoint is the whole of the state and
"still pending?" is answered by whether the thread is interrupted
(`snapshot.next`).

**Durable state broke test isolation.** The old dict was rebuilt per
TestClient, so isolation was free. Rows are not: `backend/tests/conftest.py`
now truncates `moa_task_breakers`, which is why three governance tests began
failing only when run as a file.

Proof, in `backend/tests/test_moa_durability.py`: restart survival, approving
through a second replica, rejection-after-restart still not invoking the
connector, a resolved task 404ing rather than re-executing, and the streak
surviving a cold read. All five were confirmed to fail against the old
behaviour before being kept.
