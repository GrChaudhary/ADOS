"""
Digital Twin REST Router (backend/app/routers/digital_twin.py).
Provides REST endpoints for inspecting live line states and telemetry across plant lines.
"""

from typing import List

from fastapi import APIRouter, Depends

from knowledge import DigitalTwinStore, FactoryLineState

from ..auth import require_service_auth

router = APIRouter(prefix="/digital-twin", tags=["Digital Twin"], dependencies=[Depends(require_service_auth)])

# Singleton store for Digital Twin REST endpoints
_DIGITAL_TWIN_STORE = DigitalTwinStore()


def get_digital_twin_store() -> DigitalTwinStore:
    return _DIGITAL_TWIN_STORE


@router.get("/lines", response_model=List[FactoryLineState])
async def get_digital_twin_lines():
    """
    Returns live digital twin states for all production lines in the enterprise asset model.
    """
    store = get_digital_twin_store()
    return store.get_all_line_states()
