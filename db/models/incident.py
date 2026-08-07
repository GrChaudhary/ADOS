"""
ORM model for orchestrate/audit_trail.py's AuditTrail — see that module for
the read/write logic this backs. JSONB for causal_chain/alternatives/
execution_steps (always read/written whole, no per-field query need,
same typing rule capability_manifests.risk_profile uses). approved_by is
a plain column, not an FK to users: this is audit/compliance data, and an
FK with ON DELETE SET NULL would silently erase who approved a decision
if that user is later deleted — the wrong property for a governance
record. incident_id stays a plain string PK (not native UUID) because
seed data (executive/seed_data.py) mixes INC-2026-* IDs with real
uuid4()s.
"""

from typing import Optional

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class IncidentRow(Base):
    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(primary_key=True)
    plant_id: Mapped[str]
    line_id: Mapped[str]

    detected_at: Mapped[str]
    resolved_at: Mapped[Optional[str]]
    final_state: Mapped[str]

    causal_chain: Mapped[list] = mapped_column(JSONB)  # List[CausalChainEntry], alias-keyed
    confidence: Mapped[float]
    alternatives: Mapped[list] = mapped_column(JSONB)  # List[Dict[str, Any]]

    policy_tier: Mapped[int]  # PolicyTier is an IntEnum (contracts/capabilities.py)
    approved_by: Mapped[Optional[str]]
    recommendation_accepted: Mapped[Optional[bool]]

    capability_invoked: Mapped[Optional[str]]
    capability_status: Mapped[Optional[str]]
    supplier_id: Mapped[Optional[str]]

    execution_steps: Mapped[Optional[list]] = mapped_column(JSONB)  # List[str]
    target_line_id: Mapped[Optional[str]]

    estimated_cost_usd: Mapped[Optional[float]]
    actual_cost_usd: Mapped[Optional[float]]
    estimated_downtime_min: Mapped[Optional[float]]
    actual_downtime_min: Mapped[Optional[float]]

    created_at: Mapped[str]
