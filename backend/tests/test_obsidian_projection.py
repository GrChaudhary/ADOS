"""
Tests for Section 9 Obsidian Architecture Graph Generator and governance router endpoint.
"""

from pathlib import Path
import pytest
from orchestrate.obsidian_projection import ObsidianGraphGenerator, generate_obsidian_projection
from backend.app.rbac import Role, User, create_access_token


ADMIN_AUTH = {"Authorization": f"Bearer {create_access_token(User(user_id='admin', username='admin', display_name='Admin User', role=Role.ADMIN, approval_limit_usd=1e9))}"}
AUDITOR_AUTH = {"Authorization": f"Bearer {create_access_token(User(user_id='auditor', username='auditor', display_name='Auditor User', role=Role.AUDITOR, approval_limit_usd=0.0))}"}


def test_obsidian_graph_generator_file_creation(tmp_path):
    """Verify that ObsidianGraphGenerator creates all expected markdown notes with valid backlinks."""
    generator = ObsidianGraphGenerator(target_dir=tmp_path)
    res = generator.generate()

    assert res["status"] == "success"
    assert res["generated_notes_count"] >= 15

    # Each note lives in exactly one place. Obsidian resolves [[WikiLinks]]
    # by basename across the whole vault, so writing a second copy at the
    # vault root (as this generator used to) makes every link ambiguous.
    # 1. Root MOA Note
    moa_note = tmp_path / "00_Overview" / "Main Orchestrating Agent (MOA).md"
    assert moa_note.exists()
    moa_content = moa_note.read_text(encoding="utf-8")
    assert "[[HR Domain Pod]]" in moa_content
    assert "[[IT Domain Pod]]" in moa_content
    assert "[[Finance Domain Pod]]" in moa_content

    # 2. Domain Pod Notes
    hr_note = tmp_path / "01_Domain_Pods" / "HR Domain Pod.md"
    assert hr_note.exists()
    hr_content = hr_note.read_text(encoding="utf-8")
    assert "[[RevokeBuildingAccess]]" in hr_content
    assert "[[DisableITAccess]]" in hr_content

    it_note = tmp_path / "01_Domain_Pods" / "IT Domain Pod.md"
    assert it_note.exists()
    it_content = it_note.read_text(encoding="utf-8")
    assert "[[RevokeAWSRole]]" in it_content

    # 3. Capability Notes
    jira_note = tmp_path / "02_Capabilities" / "GrantJiraAccess.md"
    assert jira_note.exists()
    jira_content = jira_note.read_text(encoding="utf-8")
    assert "[[IT Domain Pod]]" in jira_content
    assert "[[Main Orchestrating Agent (MOA)]]" in jira_content

    # 4. Cross Domain Cascade Notes
    offboard_note = tmp_path / "03_Cascades" / "Employee Offboarding Cascade.md"
    assert offboard_note.exists()
    offboard_content = offboard_note.read_text(encoding="utf-8")
    assert "[[HR Domain Pod]]" in offboard_content
    assert "[[IT Domain Pod]]" in offboard_content
    assert "[[Finance Domain Pod]]" in offboard_content

    # No basename appears twice anywhere in the vault.
    names = [p.name for p in tmp_path.rglob("*.md")]
    assert len(names) == len(set(names)), f"duplicate note basenames: {names}"


def test_obsidian_projection_api_endpoint(client):
    """Test POST /governance/obsidian-projection REST route."""
    response = client.post("/governance/obsidian-projection", headers=ADMIN_AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["generated_notes_count"] >= 15


def test_obsidian_projection_auditor_access_denied(client):
    """Verify that Auditor role is forbidden from triggering projection generation."""
    response = client.post("/governance/obsidian-projection", headers=AUDITOR_AUTH)
    assert response.status_code == 403
    assert "Auditors have read-only access" in response.json()["detail"]
