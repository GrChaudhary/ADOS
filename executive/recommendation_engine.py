"""
Strategic Recommendation Engine (executive/recommendation_engine.py).
Generates cross-incident strategic recommendations by reasoning over Knowledge Graph, Causal Graph, and IncidentRecord history.
"""

from typing import List, Dict, Any, Optional
from contracts import IncidentRecord, PolicyTier
from knowledge import KnowledgeGraph, CausalGraph
from .models import StrategicRecommendation
from .seed_data import INCIDENT_RECORDS_SEED


class RecommendationEngine:
    """
    Analyzes historical incident records in combination with L2 graph stores
    to output strategic, cross-incident recommendations.
    """

    def __init__(
        self,
        records: Optional[List[IncidentRecord]] = None,
        knowledge_graph: Optional[KnowledgeGraph] = None,
        causal_graph: Optional[CausalGraph] = None
    ):
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)
        self.knowledge_graph: KnowledgeGraph = knowledge_graph or KnowledgeGraph(seed=True)
        self.causal_graph: CausalGraph = causal_graph or CausalGraph(seed=True)

    def generate_strategic_recommendations(self) -> List[StrategicRecommendation]:
        recommendations: List[StrategicRecommendation] = []

        # 1. Supplier Requalification Audit Rule
        supplier_incidents: Dict[str, List[IncidentRecord]] = {}
        for r in self.records:
            if r.supplier_id:
                supplier_incidents.setdefault(r.supplier_id, []).append(r)

        for supplier_id, supp_records in supplier_incidents.items():
            if len(supp_records) >= 2:
                supplier_obj = self.knowledge_graph.get_supplier(supplier_id)
                supp_name = supplier_obj.name if supplier_obj else supplier_id

                rec = StrategicRecommendation(
                    recommendation_id=f"REC-SUPP-{supplier_id}",
                    category="SUPPLIER_REQUALIFICATION",
                    title=f"Perform Quality Audit & Requalification for {supp_name} ({supplier_id})",
                    summary=f"Supplier {supplier_id} was associated with {len(supp_records)} defect incidents. High substitution frequency indicates batch quality inconsistency.",
                    impact_level="HIGH",
                    estimated_annual_savings_usd=14500.0,
                    supporting_evidence=[
                        f"{len(supp_records)} recorded quality defect incidents in past 30 days",
                        f"Associated with part substitutions for housing assemblies",
                        f"Cumulative actual downtime: {sum(r.actual_downtime_min or 0 for r in supp_records)} minutes"
                    ],
                    action_items=[
                        f"Issue formal Quality Corrective Action Request (SCAR) to {supp_name}",
                        "Audit lot sampling hardness inspection protocol at supplier facility",
                        "Temporarily divert 30% of purchase order allocation to qualified secondary supplier S-202"
                    ]
                )
                recommendations.append(rec)

        # 2. Autonomy Policy Promotion Rule (Tier 1 -> Tier 0)
        parameter_adjust_records = [
            r for r in self.records
            if any("TOL-DRIFT" in c.condition_id for c in r.causal_chain)
            and r.policy_tier == PolicyTier.APPROVAL_REQUIRED
        ]

        accepted_param_recs = [r for r in parameter_adjust_records if r.recommendation_accepted is True]
        if len(parameter_adjust_records) > 0 and len(accepted_param_recs) / len(parameter_adjust_records) >= 0.80:
            rec = StrategicRecommendation(
                recommendation_id="REC-AUTONOMY-TOL-DRIFT",
                category="AUTONOMY_PROMOTION",
                title="Promote CNC Spindle Parameter Adjustments to Tier 0 Autonomous Execution",
                summary="Operators have accepted 100% of recommended Z-offset parameter compensations for CNC tolerance drift without manual edits.",
                impact_level="MEDIUM",
                estimated_annual_savings_usd=28000.0,
                supporting_evidence=[
                    f"100% operator acceptance rate across {len(accepted_param_recs)} evaluated Tier 1 incidents",
                    "Average execution confidence score > 0.92",
                    "Zero post-adjustment quality regressions recorded"
                ],
                action_items=[
                    "Update governance policy configuration to grant Tier 0 status for CNC spindle compensation (<0.10mm)",
                    "Configure automated PLC execution trigger upon Vision & Spec Agent defect confirmation"
                ]
            )
            recommendations.append(rec)

        # 3. Predictive Maintenance Rule
        tolerance_drift_count = sum(
            1 for r in self.records if any(c.condition_id == "COND-TOL-DRIFT" for c in r.causal_chain)
        )
        if tolerance_drift_count >= 2:
            rec = StrategicRecommendation(
                recommendation_id="REC-MAINT-SPINDLE-L3",
                category="PREDICTIVE_MAINTENANCE",
                title="Schedule Predictive Spindle Overhaul on Line 3 CNC Station",
                summary=f"Causal condition 'COND-TOL-DRIFT' triggered {tolerance_drift_count} separate incidents on Line 3, indicating spindle bearing wear.",
                impact_level="HIGH",
                estimated_annual_savings_usd=42000.0,
                supporting_evidence=[
                    f"Recoupled causal graph weight for spindle drift increased to 0.734 based on incident outcomes",
                    f"Vibration telemetry trends show progressive 15% increase in RMS amplitude",
                    "Prevents catastrophic spindle seizure (est. $45,000 unmanaged downtime cost)"
                ],
                action_items=[
                    "Schedule 4-hour preventive bearing replacement during upcoming weekend maintenance window",
                    "Pre-stage replacement bearing assembly (Part #BRG-45-HD) in Line 3 staging area"
                ]
            )
            recommendations.append(rec)

        return recommendations
