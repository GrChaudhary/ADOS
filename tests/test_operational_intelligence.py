"""
Unit & REST API tests for Enterprise and Operational Intelligence split.
"""

import sys
from pathlib import Path
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from executive import (
    OperationalIntelligenceEngine,
    IntelligenceFacade,
    EnterpriseIntelligenceSummary,
    OperationalIntelligenceSummary,
    ExecutiveIntelligenceOverview
)


def test_operational_intelligence_engine():
    engine = OperationalIntelligenceEngine()
    summary = engine.compute_operational_summary()

    assert summary.total_agent_invocations > 0
    assert summary.agent_failure_rate >= 0.0
    assert summary.queue_depth >= 0
    assert summary.avg_workflow_latency_ms > 0.0
    assert summary.total_connector_calls >= 0
    assert summary.inventory_locks_count >= 0
    assert "vision-spec-agent" in summary.agent_health_breakdown


def test_intelligence_facade_split():
    facade = IntelligenceFacade()

    ent_summary = facade.compute_enterprise_summary()
    assert isinstance(ent_summary, EnterpriseIntelligenceSummary)
    assert ent_summary.revenue_protected_usd >= 0.0
    assert ent_summary.mttr_avg_minutes >= 0.0

    op_summary = facade.compute_operational_summary()
    assert isinstance(op_summary, OperationalIntelligenceSummary)
    assert op_summary.total_agent_invocations > 0

    overview = facade.compute_overview()
    assert isinstance(overview, ExecutiveIntelligenceOverview)
    assert overview.enterprise.revenue_protected_usd == ent_summary.revenue_protected_usd
    assert overview.operational.total_agent_invocations == op_summary.total_agent_invocations
