# Phase 4A handoff — Claude Code kickoff prompt

Coordination note, not an RFC chapter — same role as
[handoff-phase2-antigravity.md](handoff-phase2-antigravity.md) and
[handoff-phase3b-antigravity.md](handoff-phase3b-antigravity.md): Phase 4 splits along the backend/infrastructure vs. AI reasoning boundary so Claude Code and Antigravity can build Phase 4 in parallel with zero collisions.

---

```
You're starting Phase 4A of ADOS (Autonomous Defect & Orchestration System).
Antigravity is building Phase 4B (Learning Engine, Causal Recalibration, Memory-Augmented Agent RAG, and Autonomous Optimization) in parallel in the same repo.

YOUR SCOPE (Phase 4A — Infrastructure, Persistence & Connectors):

1. Decision Memory Persistence & Search API (backend/):
   - Implement storage & search over historical `contracts.IncidentRecord`s.
   - Add backend routes:
     - `POST /memory/search` (search incident history by similarity/defect_type/plant_id)
     - `GET  /memory/records/{id}` (fetch full audit record)

2. External Marketplace & Supplier Connectors (integrations/connectors/):
   - Add `marketplace` connector to `integrations/connectors/` for external B2B procurement and 3PL logistics.
   - Implement capabilities: `QueryExternalStock`, `CreateExternalPO`, `GetFreightQuote`.

3. Governance Policy Tier Promotion Infrastructure (orchestrate/):
   - Extend `orchestrate/policy_engine.py` to handle `PolicyPromotionRequest` events, dynamically updating decision routing rules between Tier 1 (Approval) and Tier 0 (Autonomous).

SHARED CONTRACTS (contracts/):
- Use `contracts/incident_record.py` for Decision Memory storage.
- Add `contracts/decision_memory_query.py` (`DecisionMemoryQuery`, `DecisionMemorySearchResult`) for search queries.

STAY OUT OF (Phase 4B / Antigravity's territory):
- `executive/autonomy_optimizer.py`, `knowledge/learning_engine.py`, and agent memory RAG logic in `agents/`.
```
