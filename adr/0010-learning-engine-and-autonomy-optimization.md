# ADR-0010: Learning Engine, Memory RAG, and Autonomous Optimization

Status: Accepted
Date: 2026-07-22

## Context

Phase 4B introduces continuous self-learning, memory-augmented reasoning (RAG over historical incident audit trails), and autonomous policy optimization for ADOS. We needed to design how these components interact with L2 graph stores, L2 agent SDKs, and L6 executive analytics without creating tight coupling to backend database infrastructure.

## Decision

1. **Decision Memory Index (`knowledge/decision_memory_index.py`)**: Provide an indexed search abstraction supporting `contracts.DecisionMemoryQuery` and `contracts.DecisionMemorySearchResult`.
2. **Learning Engine (`knowledge/learning_engine.py`)**: Implement batch outcome replay that recalibrates `CausalGraph` edge weights using Bayesian updates and Exponential Moving Averages (EMA).
3. **Agent Precedent RAG (`agents/sdk/memory_rag.py`)**: Add memory retrieval capabilities to specialist AI agents, allowing agents to attach historical precedent evidence (`source_type="PRECEDENT"`) and boost confidence for verified historical solutions.
4. **Autonomous Policy Optimizer (`executive/autonomy_optimizer.py`)**: Analyze Decision Memory clusters to recommend promoting low-risk decision classes from Tier 1 (Approval Required) to Tier 0 (Autonomous).

## Rationale

- **Decoupled Contracts**: Using `contracts.DecisionMemoryQuery` allows agents and the Learning Engine to work seamlessly offline, during unit testing, and with Phase 4A's backend database persistence.
- **Explainable Autonomy Promotion**: Tier 0 promotion candidates must be backed by empirical evidence (operator acceptance rate >= 90%, confidence >= 0.85, sample size >= 3), upholding governance requirements from `docs/007-governance.md`.

## Consequences

- Causal weights adapt dynamically to real plant recovery outcomes over time.
- Reasoning agents cite past incident resolutions as explicit evidence, enhancing decision explainability.
