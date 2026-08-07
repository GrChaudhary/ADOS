"""
ORM models for integrations/capability_manifest.py's registry — see that
module for the actual state machine / hash-chain logic this backs. The
promotion-events FK to manifests is deliberate (unlike incidents.approved_by
in the incidents domain): these are one aggregate, always created and read
together, with no audit-vs-deletion tension.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import CHAR, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class CapabilityManifestRow(Base):
    __tablename__ = "capability_manifests"

    capability_id: Mapped[str] = mapped_column(primary_key=True)
    domain: Mapped[str]
    version: Mapped[str]
    source: Mapped[str]
    proposed_by: Mapped[str]
    status: Mapped[str]
    risk_profile: Mapped[list] = mapped_column(JSONB)  # List[{action, tier, reasoning}]
    sandbox_evidence: Mapped[Optional[str]]
    registered_at: Mapped[datetime]
    usage_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[Optional[datetime]]
    # Real per-action risk-tier calibration (vision §5.2/§8.6) —
    # integrations/capability_manifest.py's calibrate_tier(). failure_count
    # is tracked separately from usage_count (successes only, pre-existing)
    # so calibration can require a genuinely clean track record, not just
    # "used a lot." tier_override stores a PolicyTier's raw int value
    # (None until an admin calibrates it) rather than adding a second
    # Postgres enum type for one nullable column.
    failure_count: Mapped[int] = mapped_column(default=0)
    tier_override: Mapped[Optional[int]]

    events: Mapped[List["CapabilityPromotionEventRow"]] = relationship(
        back_populates="manifest", order_by="CapabilityPromotionEventRow.sequence"
    )


class CapabilityPromotionEventRow(Base):
    __tablename__ = "capability_promotion_events"
    __table_args__ = (UniqueConstraint("capability_id", "sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    capability_id: Mapped[str] = mapped_column(ForeignKey("capability_manifests.capability_id"))
    sequence: Mapped[int]
    event_type: Mapped[str]
    from_status: Mapped[Optional[str]]
    to_status: Mapped[str]
    actor: Mapped[str]
    reason: Mapped[str]
    previous_event_hash: Mapped[Optional[str]] = mapped_column(CHAR(64))
    event_hash: Mapped[str] = mapped_column(CHAR(64))
    occurred_at: Mapped[datetime]

    manifest: Mapped["CapabilityManifestRow"] = relationship(back_populates="events")
