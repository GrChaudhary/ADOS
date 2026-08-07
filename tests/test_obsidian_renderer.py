"""
Tests for Obsidian Markdown and Native Canvas renderer engine.
"""

from orchestrate.obsidian.renderer import (
    render_cascade_canvas,
    render_capability_note,
    render_decision_note,
    render_domain_pod_note,
    render_moa_root_note,
    render_task_note,
)


def test_render_moa_root_note():
    content = render_moa_root_note(
        domain_pods=["HR Domain Pod", "IT Domain Pod"],
        cascades=[{"name": "Offboarding Cascade", "description": "HR to IT cascade"}],
    )
    assert "# Main Orchestrating Agent (MOA)" in content
    assert "[[HR Domain Pod]]" in content
    assert "[[Offboarding Cascade]]" in content
    assert "type: \"moa_root\"" in content


def test_render_domain_pod_note():
    content = render_domain_pod_note(
        pod_name="HR Domain Pod",
        description="HR Pod Description",
        actions={},
    )
    assert "# HR Domain Pod" in content
    assert "HR Pod Description" in content
    assert "type: \"domain_pod\"" in content


def test_render_capability_note():
    content = render_capability_note(
        capability_id="RevokeBuildingAccess",
        domain="hr",
        action_key="revoke_building_access",
        description="Revoke badge access",
        risk_class="LOW",
        estimated_cost_usd=100.0,
    )
    assert "# Capability: RevokeBuildingAccess" in content
    assert "[[HR Domain Pod]]" in content
    assert "$100.00" in content
    assert "type: \"capability\"" in content


def test_render_task_note():
    content = render_task_note(
        task_id="task-test-1234",
        domain="hr",
        employee_name="Marcus Vance",
        instruction="Offboard employee Marcus Vance",
        status="running",
        trajectory_log=[
            {"thought": "Checking access", "action": "RevokeBuildingAccess", "status": "ok", "policy_tier": 0}
        ],
    )
    assert "# Task: Offboard employee Marcus Vance..." in content
    assert "[[Marcus Vance]]" in content
    assert "Step 1 — RevokeBuildingAccess" in content
    assert "```mermaid" in content


def test_render_decision_note():
    content = render_decision_note(
        decision_id="dec-1234",
        task_id="task-1234",
        action_key="stop_payroll",
        capability_id="StopPayroll",
        tier=2,
        cost_usd=5000.0,
        decision="approved",
        actor="Sophia (Executive)",
        reasoning="Approved termination protocol",
    )
    assert "# Decision Audit Record: dec-1234" in content
    assert "[[StopPayroll]]" in content
    assert "[[Sophia (Executive)]]" in content
    assert "$5,000.00" in content


def test_render_cascade_canvas():
    json_str = render_cascade_canvas(
        cascade_title="Employee Offboarding Cascade",
        steps=["[[RevokeBuildingAccess]] (HR — Tier 0)", "[[StopPayroll]] (HR — Tier 2)"],
    )
    assert "nodes" in json_str
    assert "edges" in json_str
    assert "Employee Offboarding Cascade" in json_str
