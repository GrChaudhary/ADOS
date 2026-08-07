"""
Postgres Database-to-Vault Reconciliation and Backfill Engine.
Scans database records (onboarding sessions, capability manifests, incidents, users) and generates a complete, consistent Obsidian Vault.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow
from orchestrate.moa.finance_domain import FINANCE_ACTIONS
from orchestrate.moa.hr_domain import HR_ACTIONS
from orchestrate.moa.it_domain import IT_ACTIONS
from .renderer import (
    render_cascade_canvas,
    render_cascade_note,
    render_capability_note,
    render_domain_pod_note,
    render_moa_root_note,
)

logger = logging.getLogger("ados.obsidian.reconciler")
from .writer import ObsidianVaultWriter

DOMAIN_POD_SPECS = {
    "HR Domain Pod": {
        "description": "Human Resources administrative workflow and access management pod.",
        "actions": HR_ACTIONS,
        "default_risk_tier": "Tier 1 Manager Approval",
    },
    "IT Domain Pod": {
        "description": "Information Technology infrastructure, licensing, and cloud role management pod.",
        "actions": IT_ACTIONS,
        "default_risk_tier": "Tier 1 Manager Approval",
    },
    "Finance Domain Pod": {
        "description": "Accounts Payable, expense approvals, and corporate wire transfer management pod.",
        "actions": FINANCE_ACTIONS,
        "default_risk_tier": "Tier 1 Manager Approval",
    },
}

CROSS_DOMAIN_CASCADES = [
    {
        "name": "Employee Offboarding Cascade",
        "description": "Multi-pod cascade touching HR, IT, and Finance upon employee termination.",
        "pods": ["HR Domain Pod", "IT Domain Pod", "Finance Domain Pod"],
        "steps": [
            "[[RevokeBuildingAccess]] (HR — Tier 0)",
            "[[RevokeAWSRole]] (IT — Tier 1)",
            "[[DisableITAccess]] (HR — Tier 1)",
            "[[IssueVendorPaymentHold]] (Finance — Tier 1)",
            "[[StopPayroll]] (HR — Tier 2)",
        ],
    },
    {
        "name": "Vendor Onboarding & Payment Hold Cascade",
        "description": "Multi-pod cascade touching Finance and IT for vendor governance.",
        "pods": ["Finance Domain Pod", "IT Domain Pod"],
        "steps": [
            "[[FlagInvoiceDiscrepancy]] (Finance — Tier 0)",
            "[[IssueVendorPaymentHold]] (Finance — Tier 1)",
            "[[GrantJiraAccess]] (IT — Tier 1)",
        ],
    },
]


class ObsidianReconciler:
    """Full database-to-vault backfill and reconciliation manager."""

    def __init__(self, writer: Optional[ObsidianVaultWriter] = None):
        self.writer = writer or ObsidianVaultWriter()

    async def reconcile_full_vault(self) -> Dict[str, Any]:
        """Scans database and updates all Obsidian notes and canvas files."""
        written_files: List[str] = []

        # 1. MOA Root Note
        root_content = render_moa_root_note(
            domain_pods=list(DOMAIN_POD_SPECS.keys()),
            cascades=CROSS_DOMAIN_CASCADES,
        )
        if await self.writer.write_note("00_Overview/Main Orchestrating Agent (MOA).md", root_content):
            written_files.append("00_Overview/Main Orchestrating Agent (MOA).md")

        # 2. Domain Pod Notes & Built-in Capability Notes
        for pod_name, spec in DOMAIN_POD_SPECS.items():
            pod_content = render_domain_pod_note(
                pod_name=pod_name,
                description=spec["description"],
                actions=spec["actions"],
                default_risk_tier=spec["default_risk_tier"],
            )
            if await self.writer.write_note(f"01_Domain_Pods/{pod_name}.md", pod_content):
                written_files.append(f"01_Domain_Pods/{pod_name}.md")

            # Built-in Capability Notes
            domain_key = pod_name.split()[0].lower()
            for action_key, action_obj in spec["actions"].items():
                cap_enum = getattr(action_obj, "capability", None)
                cap_id = cap_enum.value if hasattr(cap_enum, "value") else str(action_key)
                desc = getattr(action_obj, "description", "(Built-in capability)")
                cost = getattr(action_obj, "estimated_cost_usd", 0.0)

                cap_content = render_capability_note(
                    capability_id=cap_id,
                    domain=domain_key,
                    action_key=action_key,
                    description=desc,
                    estimated_cost_usd=cost,
                    status="ACTIVE",
                    source="built-in",
                )
                if await self.writer.write_note(f"02_Capabilities/{cap_id}.md", cap_content):
                    written_files.append(f"02_Capabilities/{cap_id}.md")

        # 3. Onboarded Dynamic Capabilities (from Postgres database)
        try:
            async with async_session_factory() as session:
                rows = (await session.execute(select(OnboardingSessionRow))).scalars().all()
                for r in rows:
                    if r.capability_id and r.synthesized_manifest:
                        manifest = r.synthesized_manifest
                        cap_id = r.capability_id
                        domain_key = r.domain or "general"
                        action_key = manifest.get("key", cap_id)
                        desc = manifest.get("description", "Onboarded capability")
                        cost = manifest.get("estimated_cost_usd", 0.0)
                        status = r.status.upper() if r.status else "SYNTHESIZED"

                        cap_content = render_capability_note(
                            capability_id=cap_id,
                            domain=domain_key,
                            action_key=action_key,
                            description=desc,
                            estimated_cost_usd=cost,
                            status=status,
                            source=r.source_url,
                            sandbox_evidence=r.sandbox_result.get("evidence_summary") if r.sandbox_result else None,
                        )
                        if await self.writer.write_note(f"02_Capabilities/{cap_id}.md", cap_content):
                            written_files.append(f"02_Capabilities/{cap_id}.md")
        except Exception as e:
            # Vault reconciliation is best-effort against the DB (tests and
            # offline runs have no Postgres), but swallowing silently hid
            # real query failures behind a "success" response.
            logger.warning("Skipped DB-backed capability notes: %s", e)

        # 4. Cross-Domain Cascades & Native Canvas Flowcharts
        for cascade in CROSS_DOMAIN_CASCADES:
            cascade_md = render_cascade_note(cascade)
            if await self.writer.write_note(f"03_Cascades/{cascade['name']}.md", cascade_md):
                written_files.append(f"03_Cascades/{cascade['name']}.md")

            canvas_json = render_cascade_canvas(cascade["name"], cascade["steps"])
            canvas_path = f"00_Overview/{cascade['name']}.canvas"
            if await self.writer.write_note(canvas_path, canvas_json):
                written_files.append(canvas_path)

        # Count total notes in vault directory
        total_count = len(list(self.writer.target_dir.rglob("*.md"))) + len(list(self.writer.target_dir.rglob("*.canvas")))

        return {
            "status": "success",
            "target_dir": str(self.writer.target_dir),
            "generated_notes_count": len(written_files),
            "reconciled_files_count": len(written_files),
            "total_vault_notes": total_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
