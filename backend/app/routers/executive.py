"""
Executive Intelligence API — exposes Phase 3B's executive/ package (KPI
Engine, Recommendation Engine, EDI, Predictive Risk, NL Copilot) over the
real audit trail the orchestrator produces, not the seed/demo fixtures
executive/ defaults to when unwired. docs/008-executive-intelligence.md.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from executive import (
    CopilotResponse,
    EnterpriseDecisionIntelligence,
    IncidentComparison,
    KPIEngine,
    KPISummary,
    NLExecutiveCopilot,
    PredictiveRiskAnalytics,
    RecommendationComparisonEngine,
    RecommendationEngine,
    RiskSignal,
    StrategicRecommendation,
    EnterpriseIntelligenceSummary,
    OperationalIntelligenceSummary,
    ExecutiveIntelligenceOverview,
    IntelligenceFacade
)

from ..auth import require_service_auth

router = APIRouter(prefix="/executive", tags=["executive"], dependencies=[Depends(require_service_auth)])


class CopilotQuery(BaseModel):
    query: str


def _records(request: Request):
    """Real IncidentRecords from this process's orchestrator — explicitly
    passed (even when empty) so executive/'s classes don't fall back to
    their seed data, which is for demo/test use only."""
    return request.app.state.orchestrator.audit_trail.all()


@router.get("/kpis", response_model=KPISummary)
async def get_kpis(request: Request, plant_id: str | None = None):
    engine = KPIEngine(records=_records(request))
    return engine.compute_kpis(filter_plant_id=plant_id)


@router.get("/kpis/what-if")
async def get_what_if(request: Request, condition_id: str = "COND-TOL-DRIFT"):
    engine = KPIEngine(records=_records(request))
    return engine.run_what_if_simulation(target_condition_id=condition_id)


@router.get("/recommendations", response_model=List[StrategicRecommendation])
async def get_recommendations(request: Request):
    engine = RecommendationEngine(
        records=_records(request),
        knowledge_graph=request.app.state.orchestrator.knowledge_graph,
        causal_graph=request.app.state.orchestrator.causal_graph,
    )
    return engine.generate_strategic_recommendations()


@router.get("/incidents/{incident_id}/options", response_model=IncidentComparison)
async def get_incident_options(incident_id: str, request: Request):
    engine = RecommendationComparisonEngine(records=_records(request))
    comparison = engine.compare_options(incident_id)
    if comparison is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Incident {incident_id} not found")
    return comparison


@router.get("/risk")
async def get_risk(request: Request):
    engine = PredictiveRiskAnalytics(
        causal_graph=request.app.state.orchestrator.causal_graph,
        digital_twin=request.app.state.orchestrator.digital_twin,
        records=_records(request),
    )
    return engine.get_all_plant_risk_signals()


@router.get("/edi/root-causes")
async def get_root_cause_clusters(request: Request):
    edi = EnterpriseDecisionIntelligence(records=_records(request))
    return edi.analyze_root_cause_clusters()


@router.get("/edi/benchmarks")
async def get_plant_benchmarks(request: Request):
    edi = EnterpriseDecisionIntelligence(records=_records(request))
    return edi.generate_plant_benchmarks()


@router.post("/copilot/ask", response_model=CopilotResponse)
async def ask_copilot(body: CopilotQuery, request: Request):
    records = _records(request)
    orchestrator = request.app.state.orchestrator
    copilot = NLExecutiveCopilot(
        kpi_engine=KPIEngine(records=records),
        rec_engine=RecommendationEngine(
            records=records,
            knowledge_graph=orchestrator.knowledge_graph,
            causal_graph=orchestrator.causal_graph,
        ),
        edi=EnterpriseDecisionIntelligence(records=records),
        risk_analytics=PredictiveRiskAnalytics(
            causal_graph=orchestrator.causal_graph,
            digital_twin=orchestrator.digital_twin,
            records=records,
        ),
    )
    return copilot.ask(body.query)


@router.get("/enterprise", response_model=EnterpriseIntelligenceSummary)
async def get_enterprise_summary(request: Request):
    facade = IntelligenceFacade(records=_records(request))
    return facade.compute_enterprise_summary()


@router.get("/operational", response_model=OperationalIntelligenceSummary)
async def get_operational_summary(request: Request):
    facade = IntelligenceFacade(
        records=_records(request),
        digital_twin=request.app.state.orchestrator.digital_twin
    )
    return facade.compute_operational_summary()


@router.get("/overview", response_model=ExecutiveIntelligenceOverview)
async def get_executive_overview(request: Request):
    facade = IntelligenceFacade(
        records=_records(request),
        digital_twin=request.app.state.orchestrator.digital_twin
    )
    return facade.compute_overview()
