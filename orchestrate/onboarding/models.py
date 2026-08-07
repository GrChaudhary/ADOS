"""Shared data shapes for the Capability Onboarding pipeline — see
orchestrate/onboarding/__init__.py for the pipeline this backs."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OnboardingTrack(str, Enum):
    MCP_NATIVE = "mcp_native"
    OPENAPI = "openapi"
    RAW_CODE = "raw_code"


class OnboardingSessionStatus(str, Enum):
    SUBMITTED = "submitted"
    INSPECTED = "inspected"
    SYNTHESIZED = "synthesized"
    RISK_REVIEWED = "risk_reviewed"
    SANDBOX_TESTED = "sandbox_tested"
    ACTIVATED = "activated"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class DiscoveredTool:
    """One capability exposed by the inspected source, ready to be shown to
    the admin at Turn 1 for selection — see inspector.py."""

    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    # Track-specific info an executor will need later (e.g. MCP-native's
    # launch_command, OpenAPI's method/pathTemplate) — opaque here,
    # interpreted by wrapper_generator.py's synthesize_* functions.
    runtime: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InspectionReport:
    source: str
    track: Optional[OnboardingTrack]
    confidence: str  # "high" | "inferred" — see inspector.detect_track()
    local_path: Optional[str] = None
    resolved_ref: Optional[str] = None  # git SHA, when source was a remote URL
    language: Optional[str] = None
    tools: List[DiscoveredTool] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    launch_command: Optional[List[str]] = None  # MCP-native only
    openapi_spec_path: Optional[str] = None  # OpenAPI only
    raw_code_entrypoint: Optional[str] = None  # raw_code only — the admin-supplied relative path


@dataclass
class SynthesizedAction:
    """One admin-selected DiscoveredTool, mapped into the shape the rest of
    the pipeline (risk_proposal.py, the registry, DynamicCapabilityConnector)
    needs — see wrapper_generator.py."""

    key: str
    description: str
    capability_id: str
    domain: str
    version: str
    estimated_cost_usd: float
    track: OnboardingTrack
    runtime: Dict[str, Any]
