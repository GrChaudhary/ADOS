"""
Agent Registry API — dynamic agent registration backed by Postgres.

Provides GET/POST/DELETE for the ADOS agent registry. Built-in agents
(the original 8 Python classes, plus the ServiceNow ITSM execution entry)
are always returned from in-memory definitions and cannot be deleted.
Custom agents are persisted to the `custom_agents` table
(db/models/custom_agent.py).

Endpoints:
    GET  /agents-registry          → merged list (8 built-ins + custom)
    POST /agents-registry          → create custom agent
    DELETE /agents-registry/{id}   → delete custom agent (built-ins blocked)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import yaml
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.custom_agent import CustomAgentRow
from db.session import get_db_session
from knowledge.local_llm_client import local_llm_client
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
    division: Optional[str] = None
    vibe: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunAgentRequest(BaseModel):
    prompt: str = Field(..., min_length=2, max_length=5000)
    context: Optional[Dict[str, Any]] = None
    provider_override: Optional[str] = None


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
        id="servicenow-itsm-agent",
        label="ITSM Execution",
        icon="🎫",
        color="teal",
        description="Creates real ServiceNow incident/change_request records via the governed ServiceNow Table API connector (integrations/connectors/servicenow.py) — the real system-of-record write for CreateIncident, CreateChangeRequest, and ScheduleMaintenance capability calls. NotifyOperator falls through to the console connector, since ServiceNow has no equivalent table.",
        model="ServiceNow Table API (direct REST, no agent runtime)",
        inputSchema="CapabilityCall { capability, executionSteps, targetLineId, governance }",
        outputSchema="ExecutionResult { ticket_id, status }",
        memoryRAG=False,
        targetTier="Tier 1 (Engineer Approval)",
        stage="Execution",
        isBuiltIn=True,
        instructions="Create a real ServiceNow incident/change_request record for the requested ADOS capability call, using the mapped table (integrations/connectors/servicenow.py's _CAPABILITY_TABLE) and a clear short_description/description. Report back the real ticket number — never invent one.",
        createdAt="2026-07-28T00:00:00+00:00",
    ),
    AgentRegistryEntry(
        id="prime-rlm-agent",
        label="Prime RLM Agent",
        icon="🧬",
        color="purple",
        # Description matches what actually runs. It previously claimed
        # "self-improving", "harness prompt/tool auto-refinement" and "auto-fix
        # bugs" — none of which exist — and was backed by
        # PrimeAgentClient.execute_rlm_task(), a hardcoded trace that no code
        # path ever called. That module is deleted; RunPrimeRLMAgent now routes
        # to integrations/connectors/prime_runtime.py, which starts the real
        # container. See docs/prime-agent-integration/13-acceptance-report.md.
        description=(
            "Runs an analysis task inside a containerized Prime Agent, whose only tool "
            "is a persistent IPython kernel. Reasoning only: the sub-runtime is granted "
            "no ADOS capabilities, so it cannot act on the organization. Reaches ADOS "
            "solely through the governed MCP capability gateway."
        ),
        model="Prime Agent (containerized, model/provider configurable)",
        inputSchema="RLMTaskPrompt { prompt, domain, max_iterations }",
        outputSchema="RLMExecutionResult { taskId, status, harness, kernelTrace }",
        memoryRAG=True,
        targetTier="Tier 1 (Engineer Approval)",
        stage="Reasoning",
        isBuiltIn=True,
        instructions=(
            "Work inside the persistent IPython kernel. Write Python source directly; "
            "top-level await is supported. Do not use shell escapes or invoke python as "
            "a program. Request organizational actions and data only through the ADOS "
            "capability skill, which is the audited route."
        ),
        createdAt="2026-08-09T00:00:00+00:00",
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


AGENCY_AGENTS_REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "agency-agents-repo"))

def _row_to_entry(row: CustomAgentRow) -> AgentRegistryEntry:
    return AgentRegistryEntry(
        id=row.id,
        label=row.label,
        icon=row.icon,
        color=row.color,
        description=row.description,
        model=row.model,
        inputSchema=row.input_schema,
        outputSchema=row.output_schema,
        memoryRAG=row.memory_rag,
        targetTier=row.target_tier,
        stage=row.stage,
        isBuiltIn=False,
        instructions=row.instructions,
        division=getattr(row, "division", None),
        vibe=getattr(row, "vibe", None),
        createdAt=row.created_at,
    )


async def sync_agency_agents_to_db(session: AsyncSession) -> int:
    divisions_path = os.path.join(AGENCY_AGENTS_REPO_DIR, "divisions.json")
    if not os.path.exists(divisions_path):
        return 0

    with open(divisions_path, "r", encoding="utf-8") as f:
        divisions_data = json.load(f).get("divisions", {})

    # Ensure division and vibe columns exist
    try:
        await session.execute(text("ALTER TABLE custom_agents ADD COLUMN IF NOT EXISTS division VARCHAR;"))
        await session.execute(text("ALTER TABLE custom_agents ADD COLUMN IF NOT EXISTS vibe VARCHAR;"))
        await session.commit()
    except Exception:
        await session.rollback()

    count = 0
    for div_key, div_info in divisions_data.items():
        div_dir = os.path.join(AGENCY_AGENTS_REPO_DIR, div_key)
        if not os.path.exists(div_dir) or not os.path.isdir(div_dir):
            continue

        for file_name in os.listdir(div_dir):
            if not file_name.endswith(".md"):
                continue
            file_path = os.path.join(div_dir, file_name)
            agent_id = file_name[:-3]

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            meta = {}
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        meta = yaml.safe_load(parts[1]) or {}
                    except Exception:
                        pass
                    body = parts[2].strip()

            label = meta.get("name") or agent_id.replace("-", " ").title()
            description = meta.get("description") or f"Specialized {div_info.get('label')} agent"
            color = meta.get("color") or div_info.get("color", "cobalt")
            emoji = meta.get("emoji") or "🤖"
            vibe = meta.get("vibe") or ""

            stmt = text("""
                INSERT INTO custom_agents (id, label, icon, color, description, model, input_schema, output_schema, memory_rag, target_tier, stage, instructions, division, vibe, created_at)
                VALUES (:id, :label, :icon, :color, :description, 'Groq Cloud / Llama 3.3 70B', 'User Query & Domain Context', 'Structured Reasoning & Deliverables', true, 'Tier 1 (Engineer Approval)', 'Reasoning', :instructions, :division, :vibe, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    icon = EXCLUDED.icon,
                    color = EXCLUDED.color,
                    description = EXCLUDED.description,
                    instructions = EXCLUDED.instructions,
                    division = EXCLUDED.division,
                    vibe = EXCLUDED.vibe;
            """)
            await session.execute(stmt, {
                "id": agent_id,
                "label": label,
                "icon": emoji,
                "color": color,
                "description": description,
                "instructions": body if body else content,
                "division": div_key,
                "vibe": vibe,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            count += 1

    await session.commit()
    return count


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/agents-registry", response_model=List[AgentRegistryEntry])
async def list_agents_registry(session: AsyncSession = Depends(get_db_session)) -> List[AgentRegistryEntry]:
    """
    Returns all registered agents: the built-ins plus whatever agency agents
    are persisted in `custom_agents`.

    READ-ONLY, deliberately. Importing from agency-agents-repo is
    `POST /agents-registry/sync` and nothing else.

    This briefly auto-ingested when the table came back empty, and fell back to
    ingesting again inside a bare `except Exception`. Both were workarounds for
    a real defect rather than a feature: `custom_agents` was missing its
    `division` and `vibe` columns, because migration `c3d4e5f6a7b8` had been
    authored against a stale head and left Alembic with two heads — so
    `alembic upgrade head` failed, the migrate service exited 255, and the
    columns were never added. With the chain linearized the migration applies
    and the explicit sync works, so the workaround has nothing left to work
    around.

    Restoring read-only matters beyond tidiness. `sync_agency_agents_to_db`
    issues `ALTER TABLE`, so the old path ran DDL from a GET; the bare
    `except Exception` turned any transient database error into a write and
    swallowed the diagnosis; and two concurrent readers of an empty table both
    started importing 255 records. A catalog read should not be able to do any
    of that.
    """
    rows = (await session.execute(select(CustomAgentRow))).scalars().all()
    custom_agents = [_row_to_entry(row) for row in rows]
    return [*BUILTIN_AGENTS, *custom_agents]


@router.post("/agents-registry/sync")
async def sync_agents_registry(session: AsyncSession = Depends(get_db_session)):
    """Manually trigger ingestion of agency agents from agency-agents-repo."""
    count = await sync_agency_agents_to_db(session)
    return {"status": "success", "ingested_count": count}


@router.post("/agents-registry/{agent_id}/run")
async def run_agent(
    agent_id: str,
    body: RunAgentRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Executes a specific agent (built-in or agency agent) live with LLM generation.
    Uses Groq / configured LLM client.
    """
    agent_entry: Optional[AgentRegistryEntry] = None
    for b in BUILTIN_AGENTS:
        if b.id == agent_id:
            agent_entry = b
            break

    if agent_entry is None:
        try:
            row = await session.get(CustomAgentRow, agent_id)
            if row:
                agent_entry = _row_to_entry(row)
        except Exception:
            pass

    if agent_entry is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    system_instructions = agent_entry.instructions or agent_entry.description
    vibe_context = f"\nAgent Vibe: {agent_entry.vibe}" if agent_entry.vibe else ""
    division_context = f"\nDivision: {agent_entry.division}" if agent_entry.division else ""

    full_system_prompt = (
        f"You are operating as {agent_entry.label} ({agent_entry.icon}).{division_context}{vibe_context}\n\n"
        f"--- SYSTEM INSTRUCTIONS ---\n{system_instructions}\n"
        "--- END SYSTEM INSTRUCTIONS ---\n\n"
        "Analyze the user request carefully. Provide your expert reasoning and deliverables."
    )

    combined_user_prompt = f"{full_system_prompt}\n\nUSER REQUEST:\n{body.prompt}"
    if body.context:
        combined_user_prompt += f"\n\nADDITIONAL CONTEXT:\n{json.dumps(body.context, indent=2)}"

    start_time = time.time()

    def _call_llm():
        if body.provider_override:
            return local_llm_client._dispatch(body.provider_override, combined_user_prompt, max_tokens=2500, temperature=0.3)
        return local_llm_client._generate_text(combined_user_prompt, max_tokens=2500, temperature=0.3)

    result = await asyncio.to_thread(_call_llm)
    duration = time.time() - start_time

    if result.get("status") in ("error", "not_configured"):
        return {
            "agent_id": agent_id,
            "label": agent_entry.label,
            "division": agent_entry.division,
            "status": result.get("status"),
            "model_used": result.get("model_used"),
            "execution_time_seconds": round(duration, 2),
            "response": None,
            "error": result.get("error", "LLM call failed or provider not configured"),
        }

    return {
        "agent_id": agent_id,
        "label": agent_entry.label,
        "division": agent_entry.division,
        "status": "success",
        "model_used": result.get("model_used", "Groq Llama 3.3 70B"),
        "execution_time_seconds": round(duration, 2),
        "response": result.get("text", ""),
    }


@router.get("/agents-registry/stage-templates")
async def get_stage_templates():
    """Returns the manufacturing-stage template defaults for the Add Agent modal."""
    return STAGE_TEMPLATES


@router.post("/agents-registry", response_model=AgentRegistryEntry, status_code=201)
async def create_agent(body: CreateAgentRequest, session: AsyncSession = Depends(get_db_session)) -> AgentRegistryEntry:
    """
    Register a new custom agent:
      1. Validate the request
      2. Generate a stable agent_id slug from the label
      3. Persist to Postgres
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

    session.add(
        CustomAgentRow(
            id=entry.id,
            label=entry.label,
            icon=entry.icon,
            color=entry.color,
            description=entry.description,
            model=entry.model,
            input_schema=entry.inputSchema,
            output_schema=entry.outputSchema,
            memory_rag=entry.memoryRAG,
            target_tier=entry.targetTier,
            stage=entry.stage,
            instructions=entry.instructions,
            created_at=entry.createdAt,
        )
    )

    print(f"[AgentRegistry] Created agent '{agent_id}'")

    return entry


@router.delete("/agents-registry/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, session: AsyncSession = Depends(get_db_session)) -> None:
    """
    Delete a custom agent. Built-in agents are protected and cannot be deleted.
    Returns 204 on success, 403 for built-ins, 404 if not found.
    """
    if agent_id in BUILTIN_IDS:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' is a built-in agent and cannot be deleted."
        )

    row = await session.get(CustomAgentRow, agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    await session.delete(row)
