"""
Incident lifecycle states — the state machine diagram in
docs/005-decision-orchestrator.md. Shared so orchestrate/ (producer),
backend/ (API surface), and IncidentRecord.final_state readers all agree
on the exact state names.
"""

from enum import Enum


class IncidentState(str, Enum):
    DETECTED = "Detected"
    DIAGNOSING = "Diagnosing"
    CANDIDATE_GENERATION = "CandidateGeneration"
    RESERVING = "Reserving"
    AWAITING_APPROVAL = "AwaitingApproval"
    EXECUTING = "Executing"
    RESOLVED = "Resolved"
    FAILED = "Failed"
    ESCALATED = "Escalated"
    PREEMPTED = "Preempted"
