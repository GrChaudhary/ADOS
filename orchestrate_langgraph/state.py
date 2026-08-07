"""Graph state shape for the LangGraph representative slice."""

from typing import Any, List, Optional, TypedDict


class IncidentGraphState(TypedDict, total=False):
    incident_id: str
    plant_id: str
    line_id: str
    part_number: str
    vision_data: dict

    vision_result: dict          # VisionSpecAgent StageOutput.result
    severity_result: dict        # SeverityTriageAgent StageOutput.result
    causal_result: dict          # CausalIsolationAgent StageOutput.result
    causal_confidence: float
    causal_chain: List[dict]     # shaped like contracts.CausalChainEntry
    alternatives: List[dict]

    policy_tier: int             # contracts.PolicyTier value
    approval_decision: Optional[str]   # "approved" | "rejected"
    approved_by: Optional[str]

    capability_status: Optional[str]
    capability_output: dict
