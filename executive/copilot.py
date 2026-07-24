"""
Natural Language Executive Copilot implementation (executive/copilot.py).
Provides evidence-grounded question answering over executive KPIs, audit trail records, and predictive risk analytics.
"""

from typing import List, Dict, Any, Optional
from .models import CopilotResponse
from .kpi_engine import KPIEngine
from .recommendation_engine import RecommendationEngine
from .edi import EnterpriseDecisionIntelligence
from .predictive_risk import PredictiveRiskAnalytics


class NLExecutiveCopilot:
    """
    Evidence-grounded NL assistant for executive decision support.
    Answers queries strictly using verifiable data citations from KPI Engine, EDI, and Risk Analytics.
    """

    def __init__(
        self,
        kpi_engine: Optional[KPIEngine] = None,
        rec_engine: Optional[RecommendationEngine] = None,
        edi: Optional[EnterpriseDecisionIntelligence] = None,
        risk_analytics: Optional[PredictiveRiskAnalytics] = None
    ):
        self.kpi_engine: KPIEngine = kpi_engine or KPIEngine()
        self.rec_engine: RecommendationEngine = rec_engine or RecommendationEngine()
        self.edi: EnterpriseDecisionIntelligence = edi or EnterpriseDecisionIntelligence()
        self.risk_analytics: PredictiveRiskAnalytics = risk_analytics or PredictiveRiskAnalytics()

    def ask(self, query: str) -> CopilotResponse:
        """
        Parses executive natural language query and generates an evidence-grounded answer.
        """
        query_lower = query.lower()

        # Intent 1: KPI Summary / MTTR / Autonomy Index
        if any(term in query_lower for term in ["mttr", "kpi", "autonomy", "performance"]):
            kpis = self.kpi_engine.compute_kpis()
            answer = (
                f"Overall ADOS system performance across {kpis.total_incidents} recorded incidents:\n"
                f"• Average MTTR: {kpis.mttr_avg_minutes} minutes (Median: {kpis.mttr_median_minutes} min)\n"
                f"• Autonomy Index: {round(kpis.autonomy_index * 100, 1)}% executed autonomously (Tier 0)\n"
                f"• Recommendation Acceptance: {round(kpis.recommendation_acceptance_rate * 100, 1)}% approved at Tier 1/2\n"
                f"• Revenue Protected: ${kpis.revenue_protected_usd:,.2f}"
            )
            citations = [
                {"source": "KPI_ENGINE", "metric": "MTTR_AVG", "value": kpis.mttr_avg_minutes},
                {"source": "KPI_ENGINE", "metric": "AUTONOMY_INDEX", "value": kpis.autonomy_index},
                {"source": "KPI_ENGINE", "metric": "REVENUE_PROTECTED_USD", "value": kpis.revenue_protected_usd}
            ]
            return CopilotResponse(
                query=query,
                answer=answer,
                confidence=0.98,
                dataCitations=citations,
                visualChartType="SUMMARY_CARD"
            )

        # Intent 2: Supplier Performance / Resilience
        elif any(term in query_lower for term in ["supplier", "vendor", "sup-201", "resilience"]):
            kpis = self.kpi_engine.compute_kpis()
            supp_data = kpis.supplier_resilience
            lines = ["Supplier Resilience Breakdown:"]
            citations = []

            for sid, info in supp_data.items():
                lines.append(f"• Supplier {sid}: {info['incident_count']} incidents, {info['total_downtime_min']} min total downtime, Resilience Score: {round(info['resilience_score']*100, 1)}%")
                citations.append({"source": "SUPPLIER_RESILIENCE", "supplier_id": sid, "incidents": info["incident_count"], "score": info["resilience_score"]})

            recs = self.rec_engine.generate_strategic_recommendations()
            supp_recs = [r for r in recs if r.category == "SUPPLIER_REQUALIFICATION"]
            if supp_recs:
                lines.append(f"\nStrategic Action: {supp_recs[0].title}")

            return CopilotResponse(
                query=query,
                answer="\n".join(lines),
                confidence=0.95,
                dataCitations=citations,
                visualChartType="BAR_CHART"
            )

        # Intent 3: What-If Simulation / Autonomy Promotion
        elif any(term in query_lower for term in ["what-if", "what if", "simulate", "promote", "automate"]):
            sim_res = self.kpi_engine.run_what_if_simulation(target_condition_id="COND-TOL-DRIFT")
            delta = sim_res["delta"]
            answer = (
                f"What-If Simulation Results (Promoting 'COND-TOL-DRIFT' to Tier 0 Autonomy):\n"
                f"• Projected MTTR Reduction: -{delta['mttr_reduction_min']} minutes\n"
                f"• Projected Autonomy Increase: +{delta['autonomy_increase_pct']}%\n"
                f"• Projected Additional Revenue Protected: +${delta['additional_revenue_protected_usd']:,.2f}"
            )
            citations = [
                {"source": "WHAT_IF_ENGINE", "target_condition": "COND-TOL-DRIFT", "delta": delta}
            ]
            return CopilotResponse(
                query=query,
                answer=answer,
                confidence=0.92,
                dataCitations=citations,
                visualChartType="COMPARISON_PIE"
            )

        # Intent 4: Predictive Risk / Plant Risks
        elif any(term in query_lower for term in ["risk", "predictive", "line 3", "critical", "warning"]):
            signals = self.risk_analytics.get_all_plant_risk_signals()
            critical_signals = [s for s in signals if s.risk_level in ["CRITICAL", "ELEVATED"]]
            lines = ["Current Predictive Plant Risk Assessment:"]
            citations = []

            for sig in critical_signals:
                lines.append(f"• Plant {sig.plant_id} ({sig.line_id}): Risk Score {sig.risk_score} [{sig.risk_level}] - Driver: {sig.primary_risk_driver}")
                citations.append({"source": "PREDICTIVE_RISK", "line_id": sig.line_id, "score": sig.risk_score, "level": sig.risk_level})

            return CopilotResponse(
                query=query,
                answer="\n".join(lines),
                confidence=0.94,
                dataCitations=citations,
                visualChartType="HEATMAP"
            )

        # Fallback for general executive queries
        else:
            kpis = self.kpi_engine.compute_kpis()
            recs = self.rec_engine.generate_strategic_recommendations()
            answer = (
                f"ADOS Executive Summary:\n"
                f"Currently tracking {kpis.total_incidents} incidents across facilities with MTTR of {kpis.mttr_avg_minutes} minutes "
                f"and ${kpis.revenue_protected_usd:,.2f} in protected revenue.\n"
                f"Top strategic recommendation: '{recs[0].title if recs else 'No active critical alerts'}'."
            )
            citations = [
                {"source": "EXECUTIVE_AUDIT_LOG", "records_evaluated": kpis.total_incidents}
            ]
            return CopilotResponse(
                query=query,
                answer=answer,
                confidence=0.88,
                dataCitations=citations,
                visualChartType="TEXT_CARD"
            )
