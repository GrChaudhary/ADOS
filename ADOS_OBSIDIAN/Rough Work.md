| #   | Item                                    | Status                                                                                                                                                                                                                                       |
| --- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Third IBM dependency (Watson NLU/TTS)   | **Still pending** — `knowledge/nlu_client.py`/`tts_client.py` still live-called from `orchestrator.py` and `causal_isolation_agent.py`                                                                                                       |
| 2   | Doc prose cleanup                       | **Still pending** — 8 files under `documentation/` still mention watsonx (Product Bible, Governance/Autonomy Policy, Integration Security Policy included)                                                                                   |
| 3   | Non-superuser Postgres role             | **Still pending** — no `CREATE ROLE`/least-privilege role anywhere; the `REVOKE` is still a documented no-op                                                                                                                                 |
| 4   | Weighted per-action risk scoring (§5.2) | **Still pending** — `assign_policy_tier()` is unchanged, still the static cost/confidence/capability-class formula                                                                                                                           |
| 5   | Async approval via Kafka topic          | **Still pending** — no `governance.pending_approval` topic anywhere                                                                                                                                                                          |
| 6   | Repo cleanup deletions committed        | **Still pending** — the handoff-doc deletions are still staged (`D`), not committed. Bigger picture: **nothing in this whole engagement has been committed** — `git status` shows 188 uncommitted changes total, this is a small slice of it |
| 7   | Vision doc wording clarification        | **Still pending** — no SAP/ServiceNow/substrate-vs-connector clarification exists in the doc                                                                                                                                                 |

**"Deeper research pass" list:**

|#|Item|Status|
|---|---|---|
|8|Raw-code onboarding track|**Actually done, contradicting its own "deliberately deferred" note.** Full router support, real Docker-sandboxed test, live invocation, and `test_full_raw_code_happy_path_activates_and_is_dispatchable` passes for real. Another stale-TODO case, same pattern as #9/#10 last round.|
|9|MOA argument-passing|**Done** (last session: ARGS protocol + human-edit-before-approve backend; frontend spec written, not built)|
|10|Docker image caching|**Done** (already existed, confirmed last session)|
|11|Risk-tier calibration for onboarded capabilities|**Still pending** — confirmed still a fixed fail-safe floor (Tier 2 for every onboarded action), no calibration against real outcomes|
|12|Cloned onboarding repo cleanup|**Done** (built last session)|


### 🟢 Completed Milestones (What is Built & Working)

1. **IBM Watsonx Orchestrate Removal**:
    - Replaced Watsonx with custom LangGraph agents (`itsm_agent.py`, `executive_copilot.py`). Uninstalled `ibm-watsonx-orchestrate` package completely.
2. **Full PostgreSQL 16 Database Persistence**:
    - Migrated all data stores (user accounts, incident history, capability manifests, custom agent registry, LLM provider settings) to PostgreSQL 16 via Alembic & SQLAlchemy. Completely retired Cloudant.
3. **Core Substrate & Messaging**:
    - Upgraded to `EventEnvelope` v2 schema with generic `correlation_id` (supporting non-manufacturing events).
    - Deployed **Apache Kafka (KRaft mode)** event bus in Docker, live-tested end-to-end.
    - Eviction-safe SSE `/events/stream` live event stream fix.
4. **MOA ReAct Engine & Governance**:
    - Multi-agent orchestrator in `orchestrate/moa/` with dynamic planning (`reason ⇄ act` loop) across `hr`, `it`, `finance`, and `manufacturing` domains.
    - Dynamic tier-based governance, cascade circuit breaker (`cascade_breaker.py`), and **human argument editing prior to approval** (Phase 7 Addendum).
5. **Phase 7 — BYOC Studio (Capability Onboarding Pipeline)**:
    - 5-turn governed onboarding pipeline (`submitted` → `inspected` → `synthesized` → `risk_reviewed` → `sandbox_tested` → `activated`).
    - MCP-Native & OpenAPI tool discovery, risk classification, Docker container sandbox testing, tier calibration (`calibrate_tier`), and session cleanup.
    - Next.js BYOC Studio wizard page, session history, audit log drawer, and integrations page link.

---

### 🟡 Pending Items & Future Roadmap (What is Pending)

Here is the list of remaining unbuilt/pending items from the vision doc:

#### 1. Third IBM Dependency Removal (IBM Watson NLU & TTS)

- **File**: `knowledge/nlu_client.py` & `knowledge/tts_client.py`
- **Current State**: Still uses `ibm_iam.py` (IBM Cloud IAM) for Watson Text-to-Speech audio briefings.
- **Pending Work**: Replace Watson NLU/TTS with a local/open-source model (e.g. Kokoro, Piper, or Whisper) to achieve 100% vendor independence.

#### 2. Action-Level Weighted Risk Scoring Engine (Section 5)

- **Current State**: `orchestrate/governance.py` uses a static Tier × Capability mapping table (`ADR-0004`).
- **Pending Work**: Replace the static table with a dynamic, multi-factor risk engine evaluating blast radius, reversibility, domain sensitivity, agent confidence, and historical precedent.

#### 3. Keycloak Service-to-Service Identity (Section 5.5)

- **Current State**: Authenticates human users via JWT/RBAC (`rbac.py`). Service-to-service calls currently run in a single process.
- **Pending Work**: Deploy Keycloak realm with OAuth2 client-credentials for service-to-service authentication when domain agents scale into decoupled microservices behind Kafka.

#### 4. Operations Pod & Deep Multi-Domain Cross-Domain Workflows (Section 11, Step 3)

- **Current State**: MOA supports basic domain routing (`hr`, `it`, `finance`, `manufacturing`).
- **Pending Work**: Fold the original 8 hackathon manufacturing agents into a dedicated Operations/Supply Chain vertical pod, and enable multi-pod cascading workflows (e.g. an IT system failure cascading into an Operations capacity adjustment and HR notification).

#### 5. Async Approval Kafka Topic (`governance.pending_approval`)

- **Current State**: Pending approval states reside in PostgreSQL and in-memory state machines.
- **Pending Work**: Publish and consume pending human approvals over a dedicated Kafka governance topic (`governance.pending_approval`).

#### 6. Real-Time Obsidian Projection Layer (Section 6, 9 & 11 Step 5)

- **Current State**: Basic Obsidian vault integration test exists.
- **Pending Work**: Build the automated audit & decision graph projection layer that populates Obsidian markdown notes in real time as governance events fire.

#### 7. Documentation Prose Cleanup

- **Current State**: Architecture documentation (`documentation/*.md`) still contains references to Watsonx & Cloudant.
- **Pending Work**: Perform a documentation editing pass to update architectural docs to match the actual PostgreSQL, Kafka, and LangGraph implementation.
  ![[Pasted image 20260807114258.png]]