# ADR-0009: Executive Intelligence Module (`executive/`) Placement & Architecture

Status: Accepted
Date: 2026-07-22

## Context

Phase 3B introduces Layer 6 (Executive Intelligence & Strategic Reasoning). It computes high-level enterprise KPIs (MTTR, Revenue Protected, Supplier Resilience, Autonomy Index, Recommendation Acceptance), generates strategic recommendations, performs pattern analysis (EDI), calculates predictive risk signals, and powers an NL Executive Copilot.

We needed to decide how to structure the Layer 6 codebase within the ADOS monorepo.

## Decision

Create a dedicated top-level module `executive/` containing:
- `kpi_engine.py`
- `recommendation_engine.py`
- `edi.py`
- `predictive_risk.py`
- `copilot.py`
- `seed_data.py`
- `models.py`

## Rationale

1. **Clear Layer Ownership**: Layer 6 (L6) reads L4/L5 operational state (`contracts.IncidentRecord`) and L2 knowledge stores (`knowledge.KnowledgeGraph`, `knowledge.CausalGraph`) but has no write path back into incident orchestration.
2. **Decoupled Strategic Reasoning**: Keeping executive analytics separate from real-time agent execution (`agents/`) ensures reporting queries and KPI computations never block decision loop latency.
3. **Audit Trail Contract Alignment**: The module relies exclusively on `contracts.IncidentRecord` as the canonical audit trail entry shape, ensuring complete independence from Phase 3A orchestrator internals.

## Consequences

- The `executive/` module can be tested against seeded `IncidentRecord` collections independently of backend/orchestration availability.
- The NL Executive Copilot queries `kpi_engine` and structured analytics, ensuring outputs remain grounded in verifiable audit data.
