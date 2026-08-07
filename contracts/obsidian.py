"""
Pydantic contracts for the Obsidian Real-Time Projection Layer.
Defines schemas for metadata frontmatter, canvas flowcharts, and vault status.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ObsidianNoteType(str, Enum):
    MOA_ROOT = "moa_root"
    DOMAIN_POD = "domain_pod"
    CAPABILITY = "capability"
    LIVE_TASK = "live_task"
    DECISION_LEDGER = "decision_ledger"
    INCIDENT = "incident"
    CASCADE = "cascade"


class ObsidianNoteMetadata(BaseModel):
    type: ObsidianNoteType
    id: str
    title: str
    domain: Optional[str] = None
    status: Optional[str] = None
    policy_tier: Optional[int] = None
    actor: Optional[str] = None
    cost_usd: Optional[float] = None
    created_at: str
    updated_at: str
    tags: List[str] = Field(default_factory=list)
    custom_fields: Dict[str, Any] = Field(default_factory=dict)


class ObsidianCanvasNode(BaseModel):
    id: str
    type: str = "text"  # text, file, link
    text: Optional[str] = None
    file: Optional[str] = None
    url: Optional[str] = None
    x: int
    y: int
    width: int = 260
    height: int = 140
    color: Optional[str] = None  # 1 (red), 2 (orange), 3 (yellow), 4 (green), 5 (cyan), 6 (purple)


class ObsidianCanvasEdge(BaseModel):
    id: str
    fromNode: str
    fromSide: str = "bottom"  # top, right, bottom, left
    toNode: str
    toSide: str = "top"
    label: Optional[str] = None
    color: Optional[str] = None


class ObsidianCanvasData(BaseModel):
    nodes: List[ObsidianCanvasNode] = Field(default_factory=list)
    edges: List[ObsidianCanvasEdge] = Field(default_factory=list)


class ObsidianProjectionStatus(BaseModel):
    status: str
    target_dir: str
    total_notes_count: int
    queue_depth: int
    last_projected_at: Optional[str] = None
    local_rest_api_enabled: bool = False
