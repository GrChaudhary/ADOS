"""
Decision Memory router (backend/app/routers/memory.py).
Provides REST endpoints for searching and managing historical IncidentRecord audit trails.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from contracts import IncidentRecord, DecisionMemoryQuery, DecisionMemorySearchResult
from knowledge import DecisionMemoryIndex

from ..auth import get_current_user
from ..config import settings

router = APIRouter(prefix="/memory", tags=["Decision Memory"], dependencies=[Depends(get_current_user)])

# In-memory store singleton for Decision Memory REST API — topped up at
# startup from Postgres via hydrate_from_db() (backend/app/main.py's
# lifespan).
#
# DecisionMemoryIndex() with no argument self-seeds from
# executive/seed_data.py's 220 fabricated manufacturing incidents. That is a
# demo default, not a product one: a real deployment's Decision Memory should
# start empty and fill with that deployment's own history. Passing an explicit
# [] when the flag is off is what keeps it empty — see settings.seed_demo_data.
_MEMORY_INDEX = DecisionMemoryIndex(None if settings.seed_demo_data else [])


def get_memory_index() -> DecisionMemoryIndex:
    return _MEMORY_INDEX


@router.post("/search", response_model=DecisionMemorySearchResult)
async def search_decision_memory(query: DecisionMemoryQuery):
    """
    Search historical Decision Memory audit records by similarity, plant, defect type, or supplier.
    Queries IBM Cloudant NoSQL database when configured, falling back to the
    static seed set otherwise (knowledge/decision_memory_index.py's
    DecisionMemoryIndex.search — the same method Causal Isolation's
    precedent-retrieval RAG now calls too, so this endpoint and the agent's
    reasoning always see the same history).
    """
    idx = get_memory_index()
    return idx.search(query)


@router.get("/records/{incident_id}", response_model=IncidentRecord)
async def get_memory_record(incident_id: str, request: Request):
    """
    Fetch a specific historical incident audit record by its unique ID —
    checks the real Postgres-backed audit trail first (orchestrate/
    audit_trail.py, via app.state.orchestrator), falling back to this
    router's in-memory search index for anything only ever added there.
    """
    record = request.app.state.orchestrator.audit_trail.get(incident_id)
    if record is not None:
        return record

    idx = get_memory_index()
    query = DecisionMemoryQuery(limit=100)
    res = idx.search(query)

    for rec in res.records:
        if rec.incident_id == incident_id:
            return rec

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Incident record '{incident_id}' not found in Decision Memory"
    )


@router.post("/records", response_model=IncidentRecord, status_code=status.HTTP_201_CREATED)
async def create_memory_record(record: IncidentRecord, request: Request):
    """
    Persists a new incident audit trail record into Decision Memory & the
    real audit trail (orchestrate/audit_trail.py) — so a manually
    backfilled record survives a restart too, not just this process's
    in-memory search index.
    """
    await request.app.state.orchestrator.audit_trail.append(record)

    idx = get_memory_index()
    idx.add_record(record)
    return record
