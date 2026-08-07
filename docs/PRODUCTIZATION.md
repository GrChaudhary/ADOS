# Productization roadmap — "this is a product now, not a demo"

Created: 2026-08-07. Stage 1 completed the same day; see the status markers
below.

**This tracks a different axis than the feature roadmap.** That one asks
"what can the platform *do*?" — and the answer is genuinely a lot. This one
asks "can anyone other than one developer on one laptop actually *run* it?"
Every item below was verified against the actual code on 2026-08-07, not
taken from any existing doc.

[In plain terms: the system has an impressive amount of real, working intelligence in it. What it doesn't have is the boring layer underneath — a way to install it, a way to watch it run, a way for two people to use it at once without breaking each other. That layer is what separates a demo from a product, and it's what this list is about.]

---

## Verified baseline (2026-08-07) — what's genuinely solid

Checked directly, not read from a doc:

- **446/446 tests pass** (`pytest -q`, 2m19s) with Postgres + Kafka up.
- Real Postgres persistence, 8 Alembic migrations, real bcrypt+JWT RBAC.
- Real Apache Kafka event bus (KRaft), real Docker-sandboxed capability
  onboarding, 4 MOA domain pods, action-level governance, cascade breaker,
  per-capability tier calibration.
- ~69,000 lines of Python across 688 files; 18 frontend routes; clean
  `.gitignore` discipline on secrets (`.env` is correctly ignored).

**This is not a criticism list. The engineering depth is real.** The gaps
below are all in the layer *beneath* the features, which is exactly the layer
a hackathon never needs and a product cannot exist without.

---

## Stage 1 — Stop the bleeding — **DONE 2026-08-07**

[In plain terms: four things that are cheap to do, and until they're done, everything else is built on sand.]

- [x] **Commit and push. Today.** Last commit is `0c6927c`, dated
  **2026-07-31**. There are **198 changed/untracked files** in the working
  tree. That means MOA, all 4 domain pods, capability onboarding, the whole
  Postgres migration, Kafka, and every fix from the last week exist *only* on
  one disk, with no backup and no history. This is the single highest-risk
  fact about the project right now, and it is also the easiest to fix.
  [In plain terms: about a week of the most valuable work in this project has never been saved anywhere except this one laptop. If the disk dies tomorrow, it's all gone. Nothing else on this list matters more than fixing that, and it takes an hour.]
  **Done 2026-08-07** — three thematic commits (platform / frontend / docs),
  pushed. Split by concern rather than faked into atomic history, since the
  work genuinely landed intertwined across the same files.

- [x] **Dockerfile + a real `docker compose up`.** There is currently **no
  Dockerfile anywhere in the repo**. `docker-compose.yml` starts Postgres and
  Kafka only — the app itself has no packaged form. The only way to run ADOS
  is `scripts/run-backend.sh`, which shells `uvicorn --reload` (a *dev* flag)
  against a hand-built `.venv`. Deliverable: backend image, frontend image,
  one compose file that brings the whole system up on a clean machine.
  [In plain terms: right now there is no way to hand this to anyone. Not to a customer, not to a colleague, not to a server. It only runs on this specific laptop, set up by hand. A packaged version is the thing every other step depends on.]
  **Done 2026-08-07** — `Dockerfile` (1.25GB, non-root, healthchecked),
  `frontend-next/Dockerfile` (285MB, Next.js standalone), and a compose stack
  where `docker compose up --build` brings up everything including a one-shot
  migration service. Verified live end to end, not just built: backend
  healthy, frontend 200, and the onboarding sandbox reaching the host Docker
  daemon from inside the backend container.

- [x] **CI (GitHub Actions): lint + typecheck + `pytest` against service
  containers + `npm run build`.** There is no `.github/` directory at all.
  This matters more than it looks: running `pytest` today with Postgres
  stopped gives **260 passed, 186 errors** — and nothing anywhere would tell
  you. Every "N/N passing" claim in the project's own history is true only on
  a machine that happened to have Docker running.
  [In plain terms: the tests are good, but they quietly need a database running to work, and nothing checks that. So "all tests pass" currently means "all tests passed on one laptop that day." CI turns that into a fact anyone can verify on every change.]
  **Done 2026-08-07** — `.github/workflows/ci.yml`: full pytest against real
  Postgres and Kafka service containers, frontend typecheck/lint/build, and
  both image builds.

- [x] **Make the demo seed opt-in.** `backend/app/main.py` unconditionally
  seeds **220 fabricated manufacturing incidents** (`INCIDENT_RECORDS_SEED`:
  20 hero + 200 generated) into the dashboard and KPIs on every single
  startup. Gate it behind a flag, default off.
  [In plain terms: the first thing a real customer would see on first login is 220 fake factory incidents that never happened. That's the most literal "this is still a demo" artifact in the codebase.]
  **Done 2026-08-07** — `SEED_DEMO_DATA`, default `false`, gating both seeding
  paths (the orchestrator's audit trail and the Decision Memory index).
  Verified through the real stack: 0 incidents off, seeded on. The suite
  forces it on in `conftest.py`, since hundreds of existing tests assert
  against those specific records and the default flip shouldn't silently
  rewrite what they test.

---

## Stage 2 — Survive more than one user (the concurrency + durability floor)

[In plain terms: today the system is architecturally a single-person tool. Not by accident — several deliberate MVP shortcuts add up to "one process, one user, one restart away from losing work." This stage is what makes it a real server.]

- [ ] **Durable MOA / agent state.** Every paused LangGraph lives in
  `InMemorySaver` (`orchestrate/moa/graph.py:477`,
  `orchestrate/langgraph_agents/itsm_agent.py:245`) with the live graph object
  held in a plain process dict (`app.state.moa_pending_tasks`,
  `app.state.itsm_pending_proposals`). Two consequences, both real:
  1. **A restart loses every in-flight approval.** Incidents got real
     Postgres durability in the 8-phase migration (`resume_pending_approvals()`);
     MOA and ITSM never did. An offboarding paused on "stop payroll" is gone
     on restart.
  2. **The app cannot run more than one worker or replica.** A second uvicorn
     worker has a different `app.state`, so `POST /moa/tasks/{id}/approve`
     would 404 roughly half the time. This caps the product at one process
     forever.
  Fix: a Postgres-backed LangGraph checkpointer (`langgraph-checkpoint-postgres`
  — only the base `langgraph-checkpoint` 4.1.1 is installed today), keyed by
  task id, replacing both the saver and the dicts.
  [In plain terms: when the AI pauses to ask a human "should I really stop this person's paycheck?", that paused state is only held in the server's short-term memory. Restart the server and the question — and the half-finished task behind it — vanishes. It also means you can never run a second copy of the app for capacity or reliability, because the two copies can't see each other's pending questions.]

- [ ] **Unblock the event loop.** `orchestrate/agent_runner.py:75` calls
  `agent.run(...)` — a *synchronous* method — from inside an `async def`, and
  those agents (`causal_isolation_agent.py`, `impact_simulation_agent.py`,
  `substitution_agent.py`) call `knowledge/local_llm_client.py`, which uses a
  blocking `httpx.Client(timeout=90.0)`. So one incident's LLM call freezes
  **every other request in the process** for up to 90 seconds. The fix is one
  line in one place: `await asyncio.to_thread(agent.run, ...)` — exactly what
  the MOA and LangGraph paths already do correctly
  (`orchestrate/moa/graph.py:179`).
  [In plain terms: while the AI is thinking about one factory incident, the entire server stops answering anyone else — up to a minute and a half of everything frozen. The newer parts of the codebase already avoid this correctly; the eight original agents don't. It's a small, well-understood fix.]

- [ ] **Per-process LLM settings cache breaks replicas.**
  `local_llm_client.hydrate_settings_cache()` is push-based into process
  memory, written by the Settings router. Save an API key on replica A and
  replica B never sees it. Needs a read-through/invalidated cache once there's
  more than one process.
  [In plain terms: another spot that quietly assumes there will only ever be one copy of the app running.]

- [ ] **Observability: there is none.** Zero hits for `prometheus`,
  `opentelemetry`, `structlog`, or `sentry` across the entire codebase.
  Startup diagnostics are `print()` statements. `EventEnvelope` already
  carries a `trace_id` field that no producer populates — wire it. Minimum
  viable: structured JSON logs, `/metrics`, request IDs, error tracking.
  [In plain terms: if this were running for a customer right now and something went wrong, there would be no way to find out what — no logs worth searching, no alerts, no way to see how slow or how often anything runs. You cannot operate what you cannot see.]

---

## Stage 3 — Earn trust (security posture)

[In plain terms: this system's entire pitch is "let AI take real actions safely." That claim has to survive someone looking at it hard.]

- [ ] **JWT lives in `localStorage`** (`frontend-next/src/lib/api.ts:11`) —
  readable by any XSS. Move to an httpOnly cookie.
- [ ] **SSE passes the token in the query string** (`api.ts:799`,
  `/events/stream?token=...`) — query strings land in access logs, proxies,
  and browser history. Use a cookie or a short-lived one-time stream ticket.
- [ ] **Postgres runs as a superuser**, which silently voids the append-only
  rule on the tamper-evident approval ledger. The migration documents this
  honestly rather than faking it — good — but a non-superuser role is what
  makes the guarantee real. (Already flagged in the pivot TODO; it belongs
  here too, since "tamper-evident audit trail" is a product claim.)
- [ ] **No rate limiting, no quotas, anywhere.** Every endpoint, including the
  ones that call a paid LLM per request.
- [ ] **`.env` hygiene**: still carries dead `WO_*` and `CLOUDANT_*` keys for
  two fully-removed products, and **no `DATABASE_URL`** — so it silently falls
  back to the dev-only `ados:ados@localhost` superuser default in
  `config.py`.
- [ ] **The third IBM dependency is still live.** `knowledge/nlu_client.py` +
  `tts_client.py` (Watson NLU/TTS via IBM Cloud IAM) are called from
  `orchestrate/orchestrator.py` and `agents/causal_isolation_agent.py`. Decide
  it explicitly: remove it, or amend the "zero dependency on any paid
  platform" principle to match reality. Right now the code and the vision doc
  disagree.
- [ ] **Pin `httpx` in `requirements.txt`.** Every connector imports it at
  runtime; it's currently only present transitively (via `fastmcp`/`mcp`). A
  dependency bump could break every integration silently.
- [ ] Dependency/CVE scanning in CI (the OpenAPI vendoring pass already found
  real runtime-path vulnerabilities once — that shouldn't depend on someone
  happening to look).

---

## Stage 4 — Prove the hands are real (the highest-value item on this list)

- [ ] **Land one real end-to-end workflow against one real external system.**

  Today, `ConsoleConnector` declares `capabilities = set(Capability)` — it
  fulfills **every capability in the system** and returns
  `"[console] simulated {capability}"`. It's the registered fallback for
  anything without a configured real connector. The two real connectors
  (`servicenow.py`, `sap.py`) both say in their own docstrings that they have
  **never been tested against a live instance** — only against mocked
  transports.

  So: the governance layer, the risk tiering, the cascade breaker, the
  approval RBAC, the tamper-evident ledger — all of it is currently governing
  simulated actions. That is the gap between "impressive system" and
  "product."

  Recommended target: **ServiceNow HR offboarding** (free Personal Developer
  Instance, no procurement needed) — MOA plans it, a human approves the Tier-2
  step, a *real ticket* appears in a *real* ServiceNow instance, and the audit
  trail records it. One real workflow proven end to end is worth more than
  four more domain pods.

  **In progress 2026-08-07 — code side done, awaiting a real instance.**
  Everything that doesn't need credentials has landed; full walkthrough in
  [SERVICENOW_PILOT.md](SERVICENOW_PILOT.md).
  - Found and fixed the defect that would have made this fail silently: the
    connector posted `CapabilityCall.input` raw, but MOA sends
    `{"employee_name", "action"}` and ServiceNow ignores unknown fields while
    still returning 201 — so an offboarding would have created a blank ticket
    and written SUCCEEDED to the tamper-evident audit trail. Translation now
    lives in `integrations/connectors/servicenow_fields.py`, per capability.
  - The three state-changing HR offboarding actions now route to ServiceNow
    at all. Before this they had no connector but Console, so no ServiceNow
    configuration could ever have made an offboarding touch a real system.
    `notify_manager` deliberately stays simulated — no mail connector exists,
    and routing it to ServiceNow would dress up a gap.
  - `scripts/servicenow_smoke.py` drives the real Hub → policy engine →
    connector → Table API path, then reads the record back by `sys_id`.
    Verified end to end against a stand-in Table API server; the only
    unproven link left is service-now.com itself.
  - 12 new tests asserting on the actual posted body, not just status codes
    (455 → 467 suite-wide).

  **Still open:** run the smoke script against a real PDI, then drive a full
  offboarding through `POST /moa/tasks` with real approvals.
  [In plain terms: the system has a very sophisticated brain and, so far, imaginary hands. Every action it "takes" is currently a log line saying it pretended to do the thing. Making one single real action happen against one real outside system — a real ticket in a real ticketing system — is the moment this becomes a product rather than a very good simulation of one.]

---

## Stage 5 — One product, one story (UI consolidation)

[In plain terms: the app currently has three different names and personalities layered on top of each other, plus leftovers pointing at deleted features.]

- [ ] **Pick one identity.** The frontend currently ships three overlapping
  product concepts: **ADOS** (manufacturing incidents), **Novus** (a marketing
  landing page at `/novus` with a particle orb and a 3D architecture carousel,
  plus a 593-line `/novus-studio` dashboard), and **Jarvis** (`/jarvis`, the
  actual MOA console — and the real product surface going forward). Novus is a
  pitch artifact. It should be a marketing site or deleted, not a route inside
  the application.
- [ ] **Remove dead call paths.** `api.testWatsonxConnection()`
  (`api.ts:606`) still calls `POST /integrations/watsonx/test-connection` —
  an endpoint that was **deleted from the backend**. That button is a
  guaranteed 404.
- [ ] **Purge stale user-visible strings** referencing removed tech:
  `novus-studio/page.tsx:20` ("Executes automatically via watsonx Orchestrate
  ADK"), `:155`, `:522`, `agents/network/page.tsx:716`,
  `integrations/page.tsx:216` ("live Cloudant NoSQL document stores").
- [ ] **Decide the manufacturing surface's fate in the UI.** `/digital-twin`,
  `/knowledge`, `/replay`, `/decisions` are Operations-pod-specific. The pivot
  TODO already decided these fold into a future Operations pod — the UI hasn't
  caught up. 18 top-level routes is a demo surface, not a product's
  information architecture.
- [ ] **No frontend tests of any kind** — no Jest, Vitest, or Playwright in
  `package.json`. At minimum: one Playwright smoke test that logs in and
  drives an MOA approval end to end.
- [ ] Retire `scripts/` demo tooling (`generate_voiceover.py`,
  `extract_recording_frames.py`, `run_*_demo.py`, `convert_to_pdf.py`) or move
  it to a clearly-marked `demo/` directory.

---

## What NOT to build next

- **Stop adding domain pods.** There are already 4 (HR, IT, Finance,
  Manufacturing), all with simulated hands. A fifth adds no product value.
  Stage 4 does.
- **Stop adding capabilities to the onboarding meta-agent.** It's the most
  impressive thing in the codebase and it is finished enough.
- **OPA and Keycloak stay deferred** — the existing reasoning
  (`infrastructure/OPA_POLICY_SPIKE.md`, `KEYCLOAK_IDENTITY_DECISION.md`)
  still holds: their trigger is real service decoupling, which Stage 2 does
  not create.
- **Don't reopen the custom-vs-LangGraph core engine question.** Settled with
  real measurements; nothing here changes the inputs.

---

## The one open question that changes the plan

Stages 1–3 are identical no matter what. Stage 4 and 5 fork on **who runs
this first**:

1. **Self-hosted open-source product** (someone clones and deploys it) →
   Stage 1's packaging becomes the primary deliverable; add versioning,
   upgrade/migration path, install docs, a real README (there is currently
   **no top-level README**).
2. **SaaS you operate** → multi-tenancy becomes mandatory and it is currently
   *absent by design* (`tenant_id` appears nowhere; `db/engine.py` explicitly
   notes "single-deployment, not a high-QPS multi-tenant SaaS"). That is a
   deep, cross-cutting retrofit — every table, every query, every event.
3. **One real pilot user/customer** → Stage 4 first, everything else in
   support of it. Cheapest path to a truthful product claim.

Recommendation: **(3), then (1).** A single real workflow against a real
system is the fastest way to convert "very sophisticated demo" into
"working product," and it's the evidence any of the other paths will need
anyway.
