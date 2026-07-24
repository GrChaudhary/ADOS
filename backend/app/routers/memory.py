"""
Decision Memory router (backend/app/routers/memory.py).
Provides REST endpoints for searching and managing historical IncidentRecord audit trails.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from contracts import IncidentRecord, DecisionMemoryQuery, DecisionMemorySearchResult
from knowledge import DecisionMemoryIndex

from ..auth import require_service_auth

router = APIRouter(prefix="/memory", tags=["Decision Memory"], dependencies=[Depends(require_service_auth)])

# In-memory store singleton for Decision Memory REST API
_MEMORY_INDEX = DecisionMemoryIndex()


def get_memory_index() -> DecisionMemoryIndex:
    return _MEMORY_INDEX


@router.post("/search", response_model=DecisionMemorySearchResult)
async def search_decision_memory(query: DecisionMemoryQuery):
    """
    Search historical Decision Memory audit records by similarity, plant, defect type, or supplier.
    """
    idx = get_memory_index()
    return idx.search(query)


@router.get("/records/{incident_id}", response_model=IncidentRecord)
async def get_memory_record(incident_id: str):
    """
    Fetch a specific historical incident audit record by its unique ID.
    """
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
async def create_memory_record(record: IncidentRecord):
    """
    Persists a new incident audit trail record into Decision Memory.
    """
    idx = get_memory_index()
    idx.add_record(record)
    return record
