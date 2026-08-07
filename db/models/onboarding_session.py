"""
ORM model for orchestrate/onboarding/'s conversational 5-turn pipeline
(orchestration-platform-vision.md §8.4/§8.5) — inspect -> synthesize ->
risk-proposal -> sandbox-test -> activate.

Deliberately a separate table from capability_manifests
(db/models/capability_manifest.py), not a widening of it: a session can
exist and fail before any CapabilityManifest row is ever created — that
row only starts existing once registry.propose() fires, which happens at
turn 3 (risk-proposal), not turn 1 (inspect). capability_id therefore has
no FK constraint here; it's simply unset until synthesize() runs, and the
manifest it eventually points to is the source of truth for governance
status once it exists (see integrations/capability_manifest.py).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class OnboardingSessionRow(Base):
    __tablename__ = "onboarding_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    track: Mapped[Optional[str]]  # "mcp_native" | "openapi" — unset until inspect() classifies it
    status: Mapped[str]  # OnboardingSessionStatus.value (orchestrate/onboarding/models.py)
    source_url: Mapped[str]
    domain: Mapped[Optional[str]]  # set at synthesize() (turn 2's domain placement)
    capability_id: Mapped[Optional[str]]  # set at synthesize(); not FK'd — see module docstring
    selected_tool_name: Mapped[Optional[str]]
    inspection_report: Mapped[Optional[dict]] = mapped_column(JSONB)
    synthesized_manifest: Mapped[Optional[dict]] = mapped_column(JSONB)
    sandbox_result: Mapped[Optional[dict]] = mapped_column(JSONB)
    audit_log: Mapped[list] = mapped_column(JSONB, default=list)  # [{turn, actor, at, detail}, ...]
    created_by: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    failure_reason: Mapped[Optional[str]]
    # orchestrate/onboarding/cleanup.py's marker that this row's cloned
    # workdir (inspection_report["local_path"], when it was a remote
    # source) has already been reclaimed — false by default so every
    # pre-existing row is treated as "not yet swept" rather than silently
    # assumed clean.
    workdir_cleaned_up: Mapped[bool] = mapped_column(default=False, server_default="false")
