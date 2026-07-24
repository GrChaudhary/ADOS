"""
Enterprise Decision Intelligence (EDI) implementation (executive/edi.py).
Performs cross-incident pattern analysis, root-cause clustering, cost variance analysis, and plant benchmarking.
"""

from typing import List, Dict, Any, Optional
from contracts import IncidentRecord
from .seed_data import INCIDENT_RECORDS_SEED


class EnterpriseDecisionIntelligence:
    """
    Performs pattern analysis, root cause frequency clustering, cost variance auditing,
    and plant-to-plant benchmarking across Decision Memory incident logs.
    """

    def __init__(self, records: Optional[List[IncidentRecord]] = None):
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)

    def analyze_root_cause_clusters(self) -> List[Dict[str, Any]]:
        """Clusters recurring root causes by condition_id frequency and cumulative impact."""
        clusters: Dict[str, Dict[str, Any]] = {}

        for r in self.records:
            for c in r.causal_chain:
                cid = c.condition_id
                if cid not in clusters:
                    clusters[cid] = {
                        "condition_id": cid,
                        "description": c.description,
                        "incident_count": 0,
                        "total_downtime_min": 0.0,
                        "total_cost_usd": 0.0,
                        "avg_causal_weight": 0.0,
                        "weights": []
                    }

                clusters[cid]["incident_count"] += 1
                clusters[cid]["total_downtime_min"] += (r.actual_downtime_min or 0.0)
                clusters[cid]["total_cost_usd"] += (r.actual_cost_usd or 0.0)
                clusters[cid]["weights"].append(c.weight)

        result = []
        for cid, data in clusters.items():
            data["avg_causal_weight"] = round(sum(data["weights"]) / len(data["weights"]), 3)
            del data["weights"]
            result.append(data)

        # Sort by incident count descending
        result.sort(key=lambda x: x["incident_count"], reverse=True)
        return result

    def analyze_cost_variance(self) -> Dict[str, Any]:
        """Calculates cost variance (estimated vs. actual) across all incidents."""
        total_estimated = sum(r.estimated_cost_usd or 0.0 for r in self.records)
        total_actual = sum(r.actual_cost_usd or 0.0 for r in self.records)
        net_savings = total_estimated - total_actual

        variance_by_tier: Dict[str, float] = {}
        for r in self.records:
            t_key = f"Tier {r.policy_tier.value if hasattr(r.policy_tier, 'value') else r.policy_tier}"
            est = r.estimated_cost_usd or 0.0
            act = r.actual_cost_usd or 0.0
            variance_by_tier[t_key] = variance_by_tier.get(t_key, 0.0) + (est - act)

        return {
            "total_estimated_cost_usd": round(total_estimated, 2),
            "total_actual_cost_usd": round(total_actual, 2),
            "net_revenue_protected_usd": round(net_savings, 2),
            "variance_by_tier": {k: round(v, 2) for k, v in variance_by_tier.items()}
        }

    def generate_plant_benchmarks(self) -> Dict[str, Dict[str, Any]]:
        """Generates plant-to-plant comparative benchmarks."""
        plant_groups: Dict[str, List[IncidentRecord]] = {}
        for r in self.records:
            plant_groups.setdefault(r.plant_id, []).append(r)

        benchmarks: Dict[str, Dict[str, Any]] = {}
        for plant_id, recs in plant_groups.items():
            cnt = len(recs)
            downtimes = [r.actual_downtime_min for r in recs if r.actual_downtime_min is not None]
            avg_mttr = sum(downtimes) / len(downtimes) if downtimes else 0.0

            tier0_cnt = sum(1 for r in recs if r.policy_tier == 0 or (hasattr(r.policy_tier, 'value') and r.policy_tier.value == 0))
            autonomy_rate = tier0_cnt / cnt if cnt > 0 else 0.0

            benchmarks[plant_id] = {
                "plant_id": plant_id,
                "incident_count": cnt,
                "avg_mttr_min": round(avg_mttr, 1),
                "autonomy_index": round(autonomy_rate, 3),
                "total_cost_usd": round(sum(r.actual_cost_usd or 0.0 for r in recs), 2)
            }

        return benchmarks
