"""
Digital Twin REST Router (backend/app/routers/digital_twin.py).
Provides REST endpoints for inspecting live line states and telemetry across plant lines.
"""

from typing import List

from fastapi import APIRouter, Depends, Request

from knowledge import FactoryLineState

from ..auth import require_service_auth

router = APIRouter(prefix="/digital-twin", tags=["Digital Twin"], dependencies=[Depends(require_service_auth)])


@router.get("/lines", response_model=List[FactoryLineState])
async def get_digital_twin_lines(request: Request):
    """
    Returns live digital twin states for all production lines, read from the
    same DigitalTwinStore instance the orchestrator mutates while resolving
    incidents (app.state.orchestrator.digital_twin) — not a separate copy —
    so this reflects real-time status/parameter/reservation changes.
    """
    store = request.app.state.orchestrator.digital_twin
    return store.get_all_line_states()
