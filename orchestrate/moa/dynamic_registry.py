"""
In-process registry bridging onboarded capabilities
(orchestrate/onboarding/, integrations/capability_manifest.py's
CapabilityManifestRegistry) into MOA's action-selection dicts
(graph.py's _get_domain_actions) — orchestration-platform-vision.md §8's
"capability onboarding meta-agent" milestone, the last mile that actually
makes an onboarded capability choosable by the LLM, not just invocable.

Entries are registered once (orchestrate/onboarding/runtime_registry.py, at
onboarding-activation time and again at app-startup rehydration) and
filtered against the *live* manifest status on every read — manifest_for()
is synchronous/in-memory and already fresh within a process the instant
activate()/hot_disable()/deprecate() run (integrations/capability_manifest.py),
so a hot-disabled or deprecated capability disappears from the LLM's prompt
on the very next reasoning turn, no restart needed.

domain is read from the manifest itself (CapabilityManifest.domain), not
duplicated onto DynamicAction — there is exactly one place a capability's
domain placement lives, matching how the onboarding flow's Turn 2
("target domain: existing pod vs new pod") sets it once at synthesis time.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from contracts import Capability
from integrations.capability_manifest import CapabilityManifestRegistry, CapabilityStatus


@dataclass(frozen=True)
class DynamicAction:
    """Duck-type-compatible with HRAction/ITAction/FinanceAction/
    ManufacturingAction — graph.py only ever reads .key/.description/
    .capability/.estimated_cost_usd off whatever's in an actions dict, never
    isinstance-checks the type — plus .capability_id, which graph.py threads
    into CapabilityCall.input so DynamicCapabilityConnector can dispatch it
    (see integrations/connectors/dynamic.py), and .input_schema, which lets
    graph.py describe the action's real parameters to the LLM and validate
    an ARGS: response against them (the built-in HR/IT/Finance/Manufacturing
    action dataclasses have no equivalent field — none of them take a real
    per-call parameter beyond the fixed employee_name payload today)."""

    key: str
    description: str
    capability: Capability  # always Capability.DYNAMIC_CAPABILITY
    estimated_cost_usd: float
    capability_id: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


_ENTRIES: Dict[str, DynamicAction] = {}


def register(entry: DynamicAction) -> None:
    _ENTRIES[entry.key] = entry


def unregister(key: str) -> None:
    _ENTRIES.pop(key, None)


def clear() -> None:
    """Test-only escape hatch — _ENTRIES is module-level/process-global,
    same pattern as this codebase's other process-global registries."""
    _ENTRIES.clear()


def _live_entries(manifests: Optional[CapabilityManifestRegistry]):
    if manifests is None or not _ENTRIES:
        return
    for entry in _ENTRIES.values():
        manifest = manifests.manifest_for(entry.capability_id)
        if manifest is None or manifest.status is not CapabilityStatus.ACTIVE:
            continue
        yield entry, manifest


def dynamic_actions_for_domain(
    domain: Optional[str], manifests: Optional[CapabilityManifestRegistry]
) -> Dict[str, DynamicAction]:
    dom = (domain or "hr").lower()
    return {entry.key: entry for entry, manifest in _live_entries(manifests) if manifest.domain.lower() == dom}


def dynamic_actions_for_all_domains(manifests: Optional[CapabilityManifestRegistry]) -> Dict[str, DynamicAction]:
    return {entry.key: entry for entry, _ in _live_entries(manifests)}
