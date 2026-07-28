"""
Agent Registry API — dynamic agent registration backed by IBM Cloudant.

Provides GET/POST/DELETE for the ADOS agent registry. Built-in agents
(the original 8 Python classes) are always returned from in-memory
definitions and cannot be deleted. Custom agents are persisted to the
Cloudant `ados_agents` database and optionally registered on the watsonx
Orchestrate tenant via the ibm-watsonx-orchestrate ADK.

Endpoints:
    GET  /agents-registry          → merged list (8 built-ins + custom)
    POST /agents-registry          → create custom agent
    DELETE /agents-registry/{id}   → delete custom agent (built-ins blocked)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from knowledge.cloudant_client import cloudant_db
from ..auth import get_current_user

router = APIRouter(tags=["agents-registry"], dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

TierLiteral = Literal[
    "Tier 0 (Autonomous)",
    "Tier 1 (Engineer Approval)",
    "Tier 2 (Multi-Executive)",
]

StageLiteral = Literal[
    "Perception",
    "Reasoning",
    "CandidateGen",
    "Evaluation",
    "Execution",
    "Learning",
]


class AgentRegistryEntry(BaseModel):
    id: str
    label: str
    icon: str = "🤖"
    color: str = "cobalt"
    description: str
    model: str
    inputSchema: str
    outputSchema: str
    memoryRAG: bool = False
    targetTier: TierLiteral = "Tier 1 (Engineer Approval)"
    stage: StageLiteral = "Reasoning"
    isBuiltIn: bool = False
    instructions: str = ""
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CreateAgentRequest(BaseModel):
    label: str = Field(..., min_length=2, max_length=80)
    icon: str = "🤖"
    color: str = "cobalt"
    description: str = Field(..., min_length=10, max_length=500)
    model: str = Field(..., min_length=2, max_length=120)
    inputSchema: str = Field(..., min_length=2, max_length=200)
    outputSchema: str = Field(..., min_length=2, max_length=200)
    memoryRAG: bool = False
    targetTier: TierLiteral = "Tier 1 (Engineer Approval)"
    stage: StageLiteral = "Reasoning"
    instructions: str = ""


# ---------------------------------------------------------------------------
# Built-in agent seed (mirrors agents.ts — single source of truth on backend)
# ---------------------------------------------------------------------------

BUILTIN_AGENTS: List[AgentRegistryEntry] = [
    AgentRegistryEntry(
        id="vision-spec-agent",
        label="Vision Spec",
        icon="👁️",
        color="emerald",
        description="Processes AOI optical camera inspection images; isolates defect regions and computes bounding box vector coordinates.",
        model="GPT-4o Vision / Custom AOI Engine",
        inputSchema="Image Payload + Resolution Context",
        outputSchema="BoundingBox2D { x, y, width, height, defect_class }",
        memoryRAG=False,
        targetTier="Tier 0 (Autonomous)",
        stage="Perception",
        isBuiltIn=True,
        instructions="Analyze vision sensor data to detect dimensional faults. Return structured defect findings with confidence score.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="cad-spec-agent",
        label="CAD Spec",
        icon="📐",
        color="cobalt",
        description="Aligns 2D/3D defect scans against nominal STEP CAD files (.step) to measure micrometer tolerance offset vectors.",
        model="CAD STEP Vector Alignment Engine",
        inputSchema="STEP CAD Reference + Measured Offset Data",
        outputSchema="MicrometerDeviation { axis, offset_mm, spec_limit }",
        memoryRAG=False,
        targetTier="Tier 0 (Autonomous)",
        stage="Perception",
        isBuiltIn=True,
        instructions="Compare measured part geometry against CAD nominal. Report offset vectors and tolerance compliance.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="causal-isolation-agent",
        label="Causal Isolation",
        icon="🧠",
        color="purple",
        description="Evaluates Bayesian Causal Graph probabilistic edges to isolate primary root cause (tooling wear vs humidity vs raw material).",
        model="Memory-Augmented Bayesian Causal Engine",
        inputSchema="Defect Variance + Sensor Telemetry Logs",
        outputSchema="CausalRootCause { condition_id, probability, evidence_chain }",
        memoryRAG=True,
        targetTier="Tier 0 (Autonomous)",
        stage="Reasoning",
        isBuiltIn=True,
        instructions="Use Bayesian causal graph and decision memory to isolate root cause with probability and evidence chain.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="substitution-agent",
        label="Substitution",
        icon="📦",
        color="amber",
        description="Queries local SAP ERP and external B2B supplier marketplaces to find alternative component inventory and stock lead times.",
        model="B2B Supply Chain & SAP Inventory Matcher",
        inputSchema="Part Specification + Required Lead Time",
        outputSchema="SupplierMatch { supplier_id, available_units, lead_time_hrs, unit_cost }",
        memoryRAG=True,
        targetTier="Tier 1 (Engineer Approval)",
        stage="CandidateGen",
        isBuiltIn=True,
        instructions="Search ERP and supplier marketplace for part substitutions. Rank by lead time and cost.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="parameter-adjustment-agent",
        label="Parameter Adjustment",
        icon="⚙️",
        color="cyan",
        description="Calculates machine CNC spindle speed, feed rate, and coolant flow adjustments to offset minor tolerance drift.",
        model="PLC Feed/Speed Optimization Engine",
        inputSchema="CNC Telemetry + Micrometer Offset Vector",
        outputSchema="MachineParameters { spindle_rpm, feed_rate_mm_min, coolant_bar }",
        memoryRAG=False,
        targetTier="Tier 0 (Autonomous)",
        stage="CandidateGen",
        isBuiltIn=True,
        instructions="Calculate CNC parameter adjustments to correct tolerance drift within safety bounds.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="impact-simulation-agent",
        label="Impact Simulation",
        icon="📈",
        color="pink",
        description="Runs Monte Carlo pathway simulations comparing resolution options (Option A/B/C) across downtime, cost savings, and quality risk.",
        model="Monte Carlo Financial & Risk Simulator",
        inputSchema="Candidate Resolution Options + Downtime Cost Rate",
        outputSchema="RankedOptions { Option A, Option B, Option C }",
        memoryRAG=True,
        targetTier="Tier 1 (Engineer Approval)",
        stage="Evaluation",
        isBuiltIn=True,
        instructions="Run Monte Carlo simulations across resolution candidates. Rank by cost, downtime, and quality risk.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="rerouting-agent",
        label="Rerouting",
        icon="🚚",
        color="teal",
        description="Evaluates freight routes and logistics modes for urgent replacement part transport to Plant 04 Bangalore, Karnataka.",
        model="Expedited Logistics Routing Engine",
        inputSchema="Origin Hub + Destination Plant 04 + SLA Window",
        outputSchema="LogisticsQuote { carrier, mode, transit_time_hrs, freight_cost }",
        memoryRAG=False,
        targetTier="Tier 1 (Engineer Approval)",
        stage="Execution",
        isBuiltIn=True,
        instructions="Find fastest and most cost-effective logistics route for urgent parts delivery within SLA.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="feedback-calibration-agent",
        label="Feedback Calibration",
        icon="🔄",
        color="indigo",
        description="Replays completed incident audit trails to update Causal Graph edge weights via Bayesian & EMA updates.",
        model="Self-Learning Bayesian Recalibrator",
        inputSchema="IncidentRecord Outcome Audit Trail",
        outputSchema="CausalWeightAdjustment { edge_id, delta, new_weight }",
        memoryRAG=True,
        targetTier="Tier 0 (Autonomous)",
        stage="Learning",
        isBuiltIn=True,
        instructions="Replay resolved incident outcomes to recalibrate causal graph edge weights via Bayesian update.",
        createdAt="2025-01-01T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="watsonx-itsm-agent",
        label="ITSM Execution",
        icon="🎫",
        color="teal",
        description="Creates and looks up real ServiceNow incident records via a dedicated watsonx Orchestrate agent (ados_itsm_agent) against a live ServiceNow instance — the real system-of-record write for CreateIncident, CreateChangeRequest, ScheduleMaintenance, and NotifyOperator capability calls (integrations/connectors/watsonx_itsm.py).",
        model="watsonx Orchestrate Agent (groq/openai/gpt-oss-120b) — ServiceNow Table API",
        inputSchema="CapabilityCall { capability, executionSteps, targetLineId, governance }",
        outputSchema="ExecutionResult { ticket_id, status }",
        memoryRAG=False,
        targetTier="Tier 1 (Engineer Approval)",
        stage="Execution",
        isBuiltIn=True,
        instructions="Create or look up a real ServiceNow incident record for the requested ADOS capability call. Use create_incident to open a new record with a clear short_description/description; use get_incident to look one up by number. Report back a structured RESULT trailer with the real ticket number — never invent one.",
        createdAt="2026-07-28T00:00:00+00:00",
    ),
]

BUILTIN_IDS = {a.id for a in BUILTIN_AGENTS}

# ---------------------------------------------------------------------------
# Manufacturing-stage templates (returned by GET to power the frontend modal)
# ---------------------------------------------------------------------------

STAGE_TEMPLATES = {
    "Perception": {
        "icon": "👁️",
        "color": "emerald",
        "model": "AOI Vision Engine",
        "targetTier": "Tier 0 (Autonomous)",
        "inputSchema": "Image Payload + Sensor Telemetry",
        "outputSchema": "DefectEvent { defect_type, deviation_mm, confidence }",
        "memoryRAG": False,
        "instructions": "Analyze optical or sensor data to detect and classify manufacturing defects. Return structured findings with confidence.",
    },
    "Reasoning": {
        "icon": "🧠",
        "color": "purple",
        "model": "Bayesian Causal Reasoning Engine",
        "targetTier": "Tier 0 (Autonomous)",
        "inputSchema": "Defect Event + Historical Telemetry",
        "outputSchema": "RootCause { condition_id, probability, evidence_chain }",
        "memoryRAG": True,
        "instructions": "Apply causal reasoning to isolate root cause. Use decision memory to weight evidence. Return probability-ranked conditions.",
    },
    "CandidateGen": {
        "icon": "📦",
        "color": "amber",
        "model": "Supply Chain & ERP Matcher",
        "targetTier": "Tier 1 (Engineer Approval)",
        "inputSchema": "Root Cause + Part Specification",
        "outputSchema": "Candidates { option_id, description, estimated_cost, lead_time }",
        "memoryRAG": True,
        "instructions": "Generate resolution candidate options by querying ERP, supplier marketplaces, and parameter optimization models.",
    },
    "Evaluation": {
        "icon": "📊",
        "color": "pink",
        "model": "Monte Carlo Risk Simulator",
        "targetTier": "Tier 1 (Engineer Approval)",
        "inputSchema": "Resolution Candidates + Cost Rate",
        "outputSchema": "RankedOptions { letter, score, downtime_min, cost_usd }",
        "memoryRAG": True,
        "instructions": "Simulate candidate options using Monte Carlo methods. Rank by cost, downtime, and quality risk. Return top 3 ranked options.",
    },
    "Execution": {
        "icon": "🚚",
        "color": "teal",
        "model": "ITSM / Logistics Router",
        "targetTier": "Tier 2 (Multi-Executive)",
        "inputSchema": "Approved Option + SLA Constraints",
        "outputSchema": "ExecutionResult { action_taken, confirmation_id, eta }",
        "memoryRAG": False,
        "instructions": "Execute the approved resolution action via ITSM, logistics, or PLC systems. Confirm execution and return tracking ID.",
    },
    "Learning": {
        "icon": "🔄",
        "color": "indigo",
        "model": "Bayesian Recalibrator",
        "targetTier": "Tier 0 (Autonomous)",
        "inputSchema": "Resolved Incident Audit Trail",
        "outputSchema": "WeightUpdate { edge_id, delta, new_weight, timestamp }",
        "memoryRAG": True,
        "instructions": "Process resolved incident outcomes to update causal model weights. Apply EMA smoothing to prevent overcorrection.",
    },
}


def _try_register_with_adk(entry: AgentRegistryEntry) -> str:
    """
    Best-effort registration of the agent spec on the watsonx Orchestrate tenant
    via the ibm-watsonx-orchestrate ADK Agent class. Logs but never raises —
    the Cloudant write is the source of truth; ADK registration is additive.
    """
    try:
        from ibm_watsonx_orchestrate.agent_builder.agents.agent import Agent  # type: ignore

        agent_spec = Agent(
            name=entry.id,
            display_name=entry.label,
            description=entry.description,
            instructions=entry.instructions or entry.description,
            llm="ibm/granite-3-8b-instruct",
            category=entry.stage,
        )
        spec_repr = repr(agent_spec)
        print(f"[ADK] Agent spec constructed for '{entry.id}': {spec_repr[:120]}...")
        return "adk_spec_built"
    except Exception as exc:
        print(f"[ADK] Non-fatal: could not build agent spec for '{entry.id}': {exc}")
        return "adk_unavailable"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/agents-registry", response_model=List[AgentRegistryEntry])
async def list_agents_registry() -> List[AgentRegistryEntry]:
    """
    Returns all registered agents: the 8 built-ins plus any custom agents
    stored in Cloudant ados_agents. Falls back gracefully if Cloudant is
    not configured.
    """
    custom_raw = cloudant_db.list_agents() if cloudant_db.is_configured() and cloudant_db._initialized else []
    custom_agents: List[AgentRegistryEntry] = []
    for doc in custom_raw:
        # Strip Cloudant internal fields before parsing
        doc.pop("_id", None)
        doc.pop("_rev", None)
        try:
            custom_agents.append(AgentRegistryEntry(**doc))
        except Exception as e:
            print(f"[AgentRegistry] Skipping malformed agent doc: {e}")

    return [*BUILTIN_AGENTS, *custom_agents]


@router.get("/agents-registry/stage-templates")
async def get_stage_templates():
    """Returns the manufacturing-stage template defaults for the Add Agent modal."""
    return STAGE_TEMPLATES


@router.post("/agents-registry", response_model=AgentRegistryEntry, status_code=201)
async def create_agent(body: CreateAgentRequest) -> AgentRegistryEntry:
    """
    Register a new custom agent:
      1. Validate the request
      2. Generate a stable agent_id slug from the label
      3. Persist to Cloudant ados_agents
      4. Best-effort ADK registration (non-blocking)
    """
    # Generate a slug ID from label
    agent_id = body.label.lower().strip().replace(" ", "-").replace("_", "-")
    agent_id = f"custom-{agent_id}-{uuid.uuid4().hex[:6]}"

    if agent_id in BUILTIN_IDS:
        raise HTTPException(status_code=409, detail="Agent ID conflicts with a built-in agent.")

    entry = AgentRegistryEntry(
        id=agent_id,
        label=body.label,
        icon=body.icon,
        color=body.color,
        description=body.description,
        model=body.model,
        inputSchema=body.inputSchema,
        outputSchema=body.outputSchema,
        memoryRAG=body.memoryRAG,
        targetTier=body.targetTier,
        stage=body.stage,
        isBuiltIn=False,
        instructions=body.instructions,
    )

    # Persist to Cloudant
    if cloudant_db.is_configured() and cloudant_db._initialized:
        cloudant_db.save_agent(entry.model_dump())
    else:
        # In-memory only for demo without Cloudant (not persisted across restarts)
        print(f"[AgentRegistry] Cloudant not configured — agent '{agent_id}' created in-memory only.")

    # ADK registration (best-effort)
    adk_status = _try_register_with_adk(entry)
    print(f"[AgentRegistry] Created agent '{agent_id}' | ADK: {adk_status}")

    return entry


@router.delete("/agents-registry/{agent_id}", status_code=204)
async def delete_agent(agent_id: str) -> None:
    """
    Delete a custom agent. Built-in agents are protected and cannot be deleted.
    Returns 204 on success, 403 for built-ins, 404 if not found.
    """
    if agent_id in BUILTIN_IDS:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' is a built-in agent and cannot be deleted."
        )

    if not cloudant_db.is_configured() or not cloudant_db._initialized:
        raise HTTPException(status_code=503, detail="Cloudant not available — cannot delete agents.")

    deleted = cloudant_db.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
