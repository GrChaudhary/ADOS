# ADR-0008: Digital Twin Placement under `knowledge/digital_twin.py`

Status: Accepted
Date: 2026-07-22

## Context

Phase 2 requires a Digital Twin model to represent factory production line states, active machine operating parameters (CNC spindle speeds, tool offsets, feed rates), live telemetry, and soft reservations. We needed to decide whether to place the Digital Twin inside the `knowledge/` module or create a top-level `digital-twin/` directory.

## Decision

Position the Digital Twin module in `knowledge/digital_twin.py` as an L2/L3 bridge component within the `knowledge/` package for Phase 2.

## Rationale

1. **State Cohesion**: Reasoning agents (such as `ParameterAdjustmentAgent` and `ReroutingAgent`) read line states and tool parameters alongside Knowledge Graph and Causal Graph entities.
2. **Minimal Service Boundary Overhead**: During Phase 2, keeping the Digital Twin co-located in `knowledge/` provides direct typed in-memory access for agents while preserving a clean boundary for external event updates.
3. **Reservation Interface**: The Digital Twin store exposes soft reservation capabilities (`reserve_line_capacity`), preparing the interface for L3 Global Planning integration in subsequent phases.

## Consequences

- Agents import line states through `knowledge.DigitalTwinStore`.
- L3 Global Planning in Phase 3 can wrap or consume `DigitalTwinStore` without altering agent interfaces.
