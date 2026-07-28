"""
Knowledge Graph REST Router (backend/app/routers/knowledge_graph.py).
Provides a nodes/edges projection of the Enterprise Knowledge Graph (BOM &
supplier relationships) for the Knowledge Explorer screen (/knowledge).
"""

from fastapi import APIRouter, Depends, Request

from knowledge import KnowledgeGraphSnapshot

from ..auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["Knowledge Graph"], dependencies=[Depends(get_current_user)])


@router.get("/graph", response_model=KnowledgeGraphSnapshot)
async def get_knowledge_graph(request: Request):
    """
    Returns the current Knowledge Graph (products, parts, suppliers, and
    their BOM/supply/substitute relationships) as a graph-viz-ready
    nodes/edges snapshot, read from the orchestrator's live
    KnowledgeGraph instance (app.state.orchestrator.knowledge_graph).
    """
    return request.app.state.orchestrator.knowledge_graph.build_graph_snapshot()
