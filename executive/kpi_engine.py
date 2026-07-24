"""
KPI Engine implementation (executive/kpi_engine.py).
Computes enterprise metrics and What-If simulations over IncidentRecord audit trail collections.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
import statistics
from contracts import IncidentRecord, PolicyTier
from .models import KPISummary
from .seed_data import INCIDENT_RECORDS_SEED


class KPIEngine:
    """
    Computes MTTR, Revenue Protected, Supplier Resilience, Autonomy Index,
    and Recommendation Acceptance over a collection of IncidentRecords.
    """

    def __init__(self, records: Optional[List[IncidentRecord]] = None):
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)

    def add_record(self, record: IncidentRecord) -> None:
        self.records.append(record)

    def _calculate_duration_minutes(self, rec: IncidentRecord) -> Optional[float]:
        # Prefer actual_downtime_min if explicitly set or modified by simulation
        if rec.actual_downtime_min is not None:
            return rec.actual_downtime_min

        if not rec.detected_at or not rec.resolved_at:
            return None
        try:
            # Parse ISO 8601 timestamps
            t_start = datetime.fromisoformat(rec.detected_at.replace("Z", "+00:00"))
            t_end = datetime.fromisoformat(rec.resolved_at.replace("Z", "+00:00"))
            delta_sec = (t_end - t_start).total_seconds()
            return max(0.0, delta_sec / 60.0)
        except Exception:
            return None

    def compute_kpis(self, filter_plant_id: Optional[str] = None) -> KPISummary:
        """Computes executive KPIs over current incident record history."""
        dataset = self.records
        if filter_plant_id:
            dataset = [r for r in dataset if r.plant_id == filter_plant_id]

        if not dataset:
            return KPISummary(
                totalIncidents=0,
                resolvedIncidents=0,
                failedIncidents=0,
                mttrAvgMinutes=0.0,
                mttrMedianMinutes=0.0,
                revenueProtectedUsd=0.0,
                totalActualCostUsd=0.0,
                autonomyIndex=0.0,
                recommendationAcceptanceRate=0.0,
                tierDistribution={"Tier 0 (Autonomous)": 0, "Tier 1 (Approval)": 0, "Tier 2 (Executive)": 0},
                supplierResilience={}
            )

        total_incidents = len(dataset)
        resolved_incidents = sum(1 for r in dataset if r.final_state == "Resolved")
        failed_incidents = sum(1 for r in dataset if r.final_state == "Failed")

        # 1. MTTR Calculation
        durations: List[float] = []
        for r in dataset:
            if r.final_state == "Resolved":
                d = self._calculate_duration_minutes(r)
                if d is not None:
                    durations.append(d)
                elif r.actual_downtime_min is not None:
                    durations.append(r.actual_downtime_min)

        mttr_avg = round(statistics.mean(durations), 2) if durations else 0.0
        mttr_median = round(statistics.median(durations), 2) if durations else 0.0

        # 2. Revenue Protected ($)
        revenue_protected = 0.0
        total_actual_cost = 0.0
        for r in dataset:
            est_cost = r.estimated_cost_usd or 0.0
            act_cost = r.actual_cost_usd or 0.0
            total_actual_cost += act_cost
            if est_cost > act_cost:
                revenue_protected += (est_cost - act_cost)

        # 3. Autonomy Index (Tier 0 Share)
        tier0_count = sum(1 for r in dataset if r.policy_tier == PolicyTier.AUTONOMOUS or r.policy_tier == 0)
        tier1_count = sum(1 for r in dataset if r.policy_tier == PolicyTier.APPROVAL_REQUIRED or r.policy_tier == 1)
        tier2_count = sum(1 for r in dataset if r.policy_tier == PolicyTier.EXECUTIVE_APPROVAL or r.policy_tier == 2)
        autonomy_index = round(tier0_count / total_incidents, 4) if total_incidents > 0 else 0.0

        tier_distribution = {
            "Tier 0 (Autonomous)": tier0_count,
            "Tier 1 (Approval)": tier1_count,
            "Tier 2 (Executive)": tier2_count
        }

        # 4. Recommendation Acceptance Rate (Non-null Tier 1/2 records only)
        non_null_acceptance_recs = [r for r in dataset if r.recommendation_accepted is not None]
        accepted_count = sum(1 for r in non_null_acceptance_recs if r.recommendation_accepted is True)
        acceptance_rate = round(accepted_count / len(non_null_acceptance_recs), 4) if non_null_acceptance_recs else 1.0

        # 5. Supplier Resilience Analysis
        supplier_data: Dict[str, Dict[str, Any]] = {}
        for r in dataset:
            sid = r.supplier_id
            if sid:
                if sid not in supplier_data:
                    supplier_data[sid] = {
                        "incident_count": 0,
                        "total_actual_cost_usd": 0.0,
                        "total_downtime_min": 0.0,
                        "successful_resolutions": 0
                    }
                supplier_data[sid]["incident_count"] += 1
                supplier_data[sid]["total_actual_cost_usd"] += (r.actual_cost_usd or 0.0)
                supplier_data[sid]["total_downtime_min"] += (r.actual_downtime_min or 0.0)
                if r.final_state == "Resolved":
                    supplier_data[sid]["successful_resolutions"] += 1

        for sid, stats in supplier_data.items():
            cnt = stats["incident_count"]
            stats["resilience_score"] = round(stats["successful_resolutions"] / cnt, 4) if cnt > 0 else 1.0

        return KPISummary(
            totalIncidents=total_incidents,
            resolvedIncidents=resolved_incidents,
            failedIncidents=failed_incidents,
            mttrAvgMinutes=mttr_avg,
            mttrMedianMinutes=mttr_median,
            revenueProtectedUsd=round(revenue_protected, 2),
            totalActualCostUsd=round(total_actual_cost, 2),
            autonomyIndex=autonomy_index,
            recommendationAcceptanceRate=acceptance_rate,
            tierDistribution=tier_distribution,
            supplierResilience=supplier_data
        )

    def run_what_if_simulation(
        self,
        target_condition_id: str = "COND-TOL-DRIFT",
        promote_to_tier: PolicyTier = PolicyTier.AUTONOMOUS
    ) -> Dict[str, Any]:
        """
        Simulates what the KPIs would have been if incidents matching `target_condition_id`
        had been executed autonomously (Tier 0) instead of requiring manual approval delay.
        """
        baseline_kpis = self.compute_kpis()

        simulated_records: List[IncidentRecord] = []
        for r in self.records:
            sim_r = IncidentRecord.model_validate(r.model_dump())
            has_matching_cause = any(c.condition_id == target_condition_id for c in sim_r.causal_chain)

            if has_matching_cause and sim_r.policy_tier != PolicyTier.AUTONOMOUS:
                # Promote to Autonomous
                sim_r.policy_tier = PolicyTier.AUTONOMOUS
                sim_r.recommendation_accepted = None

                # Autonomous execution eliminates human approval wait time (60% MTTR reduction)
                base_downtime = r.actual_downtime_min if r.actual_downtime_min is not None else (self._calculate_duration_minutes(r) or 30.0)
                sim_r.actual_downtime_min = round(base_downtime * 0.4, 1)

                # Autonomous execution cuts operational coordination costs (50% cost reduction)
                if sim_r.actual_cost_usd is not None:
                    sim_r.actual_cost_usd = round(sim_r.actual_cost_usd * 0.5, 2)

            simulated_records.append(sim_r)

        sim_engine = KPIEngine(records=simulated_records)
        simulated_kpis = sim_engine.compute_kpis()

        return {
            "target_condition_id": target_condition_id,
            "promoted_to_tier": promote_to_tier.name,
            "baseline": {
                "mttr_avg_min": baseline_kpis.mttr_avg_minutes,
                "autonomy_index": baseline_kpis.autonomy_index,
                "revenue_protected_usd": baseline_kpis.revenue_protected_usd
            },
            "simulated": {
                "mttr_avg_min": simulated_kpis.mttr_avg_minutes,
                "autonomy_index": simulated_kpis.autonomy_index,
                "revenue_protected_usd": simulated_kpis.revenue_protected_usd
            },
            "delta": {
                "mttr_reduction_min": round(baseline_kpis.mttr_avg_minutes - simulated_kpis.mttr_avg_minutes, 2),
                "autonomy_increase_pct": round((simulated_kpis.autonomy_index - baseline_kpis.autonomy_index) * 100, 2),
                "additional_revenue_protected_usd": round(simulated_kpis.revenue_protected_usd - baseline_kpis.revenue_protected_usd, 2)
            }
        }
