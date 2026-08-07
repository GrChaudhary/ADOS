"""
Capability Manifest Registry — orchestration-platform-vision.md §8.4
(5-step onboarding pipeline, mandatory sandbox gate) and §8.7 (Capability
Registry: name, domain, version, risk profile, usage history, status).

Distinct from CapabilityRegistry (capability_registry.py), which maps a
Capability to the connector(s) that fulfill it at call time. This module
tracks the *governance lifecycle* of an onboarded capability — proposed by
the onboarding agent, sandbox-tested, activated by an admin, and later
deprecated or hot-disabled — independent of whether a connector for it has
been wired up yet. A capability can exist here in PROPOSED state before any
connector registration happens.

Two rules from the vision doc are enforced structurally here, not just by
convention:
  - §8.4: "sandbox testing is always mandatory, with no fast-forward or
    skip option" — activate() raises PolicyViolation unless the manifest
    has already passed through SANDBOX_TESTED with recorded evidence.
  - §8.3/8.4: "the agent proposes; it never self-approves" — activate()
    raises PolicyViolation if the activating actor is the same identity
    that proposed the capability.

The promotion history is hash-chained (adapted from a capability-readiness
ledger pattern seen in agentic-org) so a tampered or reordered history is
detectable via verify_integrity() — plain hashlib, no external ledger
service.

Persistence (db/ — real Postgres, replacing what used to be pure in-memory
state): every mutating method takes an optional `session_factory`. When
none is given (the default — matches every bare construction in tests and
scripts), everything works exactly as before, pure in-memory. When given
(how IntegrationHub wires it via app.state in the real app), writes go to
Postgres first, inside a transaction that locks the manifest row
(`SELECT ... FOR UPDATE`) before checking status or appending an event.

That lock matters for a reason that didn't exist before this had real
persistence: in-memory, `_append_event` was accidentally atomic — no
`await` anywhere inside it, so Python's cooperative scheduling could never
interleave two calls. Once appending requires an `await` (an INSERT), two
concurrent `activate()`/`hot_disable()` calls for the *same* capability_id
could genuinely race: both read SANDBOX_TESTED, both pass the check, both
compute the next hash-chain link off the same previous_event_hash. The
row lock serializes transitions per-capability (different capabilities
stay fully concurrent) and closes a real TOCTOU gap in the "never
self-approve" check too — `actor == proposed_by` is now checked against
the row fetched *inside* the lock, not a possibly-stale object.

`manifest_for()` stays synchronous on purpose — it's called on the hot
path of every capability invocation (policy_engine.py's ConnectorPolicyEngine,
whose PolicyRule type is deliberately synchronous), so the in-memory dict
remains the fast read path; mutating methods write Postgres then update it
to match.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from contracts import Capability, CapabilityCall, PolicyTier
from db.models.capability_manifest import CapabilityManifestRow, CapabilityPromotionEventRow

from .policy_engine import PolicyViolation

# CapabilityManifestRegistry.calibrate_tier()'s "real usage track record"
# bar — a hardcoded constant, same tuning posture as
# orchestrate/governance.py's LOW_EXPOSURE_MAX_USD/TIER0_CONFIDENCE_THRESHOLD
# (an MVP starting policy, not derived from anything, tunable later).
MIN_CALIBRATION_USAGE_COUNT = 10


class CapabilityStatus(str, Enum):
    PROPOSED = "proposed"
    SANDBOX_TESTED = "sandbox_tested"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    HOT_DISABLED = "hot_disabled"


@dataclass(frozen=True)
class RiskProfileEntry:
    """One action's proposed risk tier, per §8.3 Turn 3 — "proposed risk
    tier per action, with reasoning, not just a verdict"."""

    action: str
    tier: PolicyTier
    reasoning: str


@dataclass
class CapabilityManifest:
    capability_id: str
    domain: str
    version: str
    source: str  # repo URL, API base, or "built-in"
    proposed_by: str
    status: CapabilityStatus = CapabilityStatus.PROPOSED
    risk_profile: List[RiskProfileEntry] = field(default_factory=list)
    sandbox_evidence: Optional[str] = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    usage_count: int = 0
    last_used_at: Optional[datetime] = None
    failure_count: int = 0
    # None means "no admin calibration yet" -- the caller (orchestrate/moa/
    # graph.py's _effective_policy_tier) is responsible for falling back to
    # the fail-safe EXECUTIVE_APPROVAL floor in that case, same as
    # assign_policy_tier() already does for an unknown Capability.
    tier_override: Optional[PolicyTier] = None


@dataclass(frozen=True)
class CapabilityPromotionEvent:
    sequence: int
    capability_id: str
    event_type: str
    from_status: Optional[CapabilityStatus]
    to_status: CapabilityStatus
    actor: str
    reason: str
    previous_event_hash: Optional[str]
    event_hash: str
    occurred_at: datetime


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, CapabilityStatus):
        return value.value
    raise TypeError(f"Unsupported event value: {type(value).__name__}")


def compute_event_hash(previous_event_hash: Optional[str], payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(f"{previous_event_hash or ''}:{canonical}".encode()).hexdigest()


def _event_payload(event: CapabilityPromotionEvent) -> dict:
    return {
        "capability_id": event.capability_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "from_status": event.from_status.value if event.from_status else None,
        "to_status": event.to_status.value,
        "actor": event.actor,
        "reason": event.reason,
        "occurred_at": event.occurred_at,
    }


def verify_event_chain(events: List[CapabilityPromotionEvent]) -> Optional[str]:
    """Fail closed unless the ordered event list forms the canonical
    chain for a single capability. Returns the final hash, or raises
    PolicyViolation on any gap, reorder, or tampered payload. Caller is
    responsible for supplying events already ORDER BY sequence ASC — this
    function trusts the order it's given, never re-sorts."""
    previous_hash: Optional[str] = None
    capability_id: Optional[str] = None
    for expected_sequence, event in enumerate(events):
        if capability_id is None:
            capability_id = event.capability_id
        if event.capability_id != capability_id:
            raise PolicyViolation("promotion history crosses capability scope")
        if event.sequence != expected_sequence:
            raise PolicyViolation("promotion history sequence is not contiguous")
        if event.previous_event_hash != previous_hash:
            raise PolicyViolation("promotion history predecessor hash does not match")
        expected_hash = compute_event_hash(previous_hash, _event_payload(event))
        if not hmac.compare_digest(event.event_hash, expected_hash):
            raise PolicyViolation("promotion history event hash is invalid")
        previous_hash = event.event_hash
    return previous_hash


def _row_to_manifest(row: CapabilityManifestRow) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=row.capability_id,
        domain=row.domain,
        version=row.version,
        source=row.source,
        proposed_by=row.proposed_by,
        status=CapabilityStatus(row.status),
        risk_profile=[
            RiskProfileEntry(action=e["action"], tier=PolicyTier(e["tier"]), reasoning=e["reasoning"])
            for e in row.risk_profile
        ],
        sandbox_evidence=row.sandbox_evidence,
        registered_at=row.registered_at,
        usage_count=row.usage_count,
        last_used_at=row.last_used_at,
        failure_count=row.failure_count,
        tier_override=PolicyTier(row.tier_override) if row.tier_override is not None else None,
    )


def _row_to_event(row: CapabilityPromotionEventRow) -> CapabilityPromotionEvent:
    return CapabilityPromotionEvent(
        sequence=row.sequence,
        capability_id=row.capability_id,
        event_type=row.event_type,
        from_status=CapabilityStatus(row.from_status) if row.from_status else None,
        to_status=CapabilityStatus(row.to_status),
        actor=row.actor,
        reason=row.reason,
        previous_event_hash=row.previous_event_hash,
        event_hash=row.event_hash,
        occurred_at=row.occurred_at,
    )


class CapabilityManifestRegistry:
    def __init__(self, session_factory: Optional[async_sessionmaker] = None):
        self._manifests: Dict[str, CapabilityManifest] = {}
        self._events: Dict[str, List[CapabilityPromotionEvent]] = {}
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # In-memory path — unchanged behavior, used when no session_factory.
    # ------------------------------------------------------------------

    def _append_event_in_memory(
        self,
        capability_id: str,
        event_type: str,
        from_status: Optional[CapabilityStatus],
        to_status: CapabilityStatus,
        actor: str,
        reason: str,
    ) -> None:
        history = self._events.setdefault(capability_id, [])
        previous_hash = history[-1].event_hash if history else None
        sequence = len(history)
        occurred_at = datetime.now(timezone.utc)
        payload = {
            "capability_id": capability_id,
            "sequence": sequence,
            "event_type": event_type,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value,
            "actor": actor,
            "reason": reason,
            "occurred_at": occurred_at,
        }
        event_hash = compute_event_hash(previous_hash, payload)
        history.append(
            CapabilityPromotionEvent(
                sequence=sequence,
                capability_id=capability_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor=actor,
                reason=reason,
                previous_event_hash=previous_hash,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
        )

    # ------------------------------------------------------------------
    # Postgres path — used when session_factory is set. Both helpers
    # below assume the caller already holds the manifest row lock for
    # the duration of the transaction they're called in.
    # ------------------------------------------------------------------

    async def _locked_row(self, session, capability_id: str) -> CapabilityManifestRow:
        row = (
            await session.execute(
                select(CapabilityManifestRow).where(CapabilityManifestRow.capability_id == capability_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise PolicyViolation(f"no capability manifest registered for {capability_id}")
        return row

    async def _append_event_db(
        self,
        session,
        capability_id: str,
        event_type: str,
        from_status: Optional[CapabilityStatus],
        to_status: CapabilityStatus,
        actor: str,
        reason: str,
    ) -> None:
        last = (
            await session.execute(
                select(CapabilityPromotionEventRow.sequence, CapabilityPromotionEventRow.event_hash)
                .where(CapabilityPromotionEventRow.capability_id == capability_id)
                .order_by(CapabilityPromotionEventRow.sequence.desc())
                .limit(1)
            )
        ).first()
        sequence = (last.sequence + 1) if last else 0
        previous_hash = last.event_hash if last else None
        occurred_at = datetime.now(timezone.utc)
        payload = {
            "capability_id": capability_id,
            "sequence": sequence,
            "event_type": event_type,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value,
            "actor": actor,
            "reason": reason,
            "occurred_at": occurred_at,
        }
        event_hash = compute_event_hash(previous_hash, payload)
        session.add(
            CapabilityPromotionEventRow(
                capability_id=capability_id,
                sequence=sequence,
                event_type=event_type,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                actor=actor,
                reason=reason,
                previous_event_hash=previous_hash,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def propose(
        self,
        capability_id: str,
        *,
        domain: str,
        version: str,
        source: str,
        risk_profile: List[RiskProfileEntry],
        proposed_by: str,
        reason: str = "initial proposal",
    ) -> CapabilityManifest:
        if not risk_profile:
            raise PolicyViolation("a risk profile with at least one action is required to propose a capability")
        if any(not entry.reasoning.strip() for entry in risk_profile):
            raise PolicyViolation("every risk profile entry requires non-empty reasoning")

        if self._session_factory is None:
            if capability_id in self._manifests:
                raise PolicyViolation(f"capability {capability_id} is already registered")
            manifest = CapabilityManifest(
                capability_id=capability_id,
                domain=domain,
                version=version,
                source=source,
                proposed_by=proposed_by,
                risk_profile=list(risk_profile),
            )
            self._manifests[capability_id] = manifest
            self._append_event_in_memory(capability_id, "proposed", None, CapabilityStatus.PROPOSED, proposed_by, reason)
            return manifest

        risk_profile_json = [{"action": e.action, "tier": e.tier.value, "reasoning": e.reasoning} for e in risk_profile]
        registered_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    CapabilityManifestRow(
                        capability_id=capability_id,
                        domain=domain,
                        version=version,
                        source=source,
                        proposed_by=proposed_by,
                        status=CapabilityStatus.PROPOSED.value,
                        risk_profile=risk_profile_json,
                        registered_at=registered_at,
                        usage_count=0,
                    )
                )
                try:
                    await session.flush()
                except IntegrityError:
                    raise PolicyViolation(f"capability {capability_id} is already registered")
                await self._append_event_db(
                    session, capability_id, "proposed", None, CapabilityStatus.PROPOSED, proposed_by, reason
                )

        manifest = CapabilityManifest(
            capability_id=capability_id,
            domain=domain,
            version=version,
            source=source,
            proposed_by=proposed_by,
            risk_profile=list(risk_profile),
            registered_at=registered_at,
        )
        self._manifests[capability_id] = manifest
        return manifest

    async def record_sandbox_evidence(self, capability_id: str, evidence: str, *, actor: str) -> CapabilityManifest:
        """§8.4 step 4 — mandatory, no skip. Only valid from PROPOSED."""
        if not evidence or not evidence.strip():
            raise PolicyViolation("sandbox evidence must be non-empty — a description of what was actually run")

        if self._session_factory is None:
            manifest = self._require(capability_id)
            if manifest.status is not CapabilityStatus.PROPOSED:
                raise PolicyViolation(
                    f"capability {capability_id} must be in PROPOSED state to record sandbox evidence, "
                    f"is {manifest.status.value}"
                )
            manifest.sandbox_evidence = evidence
            manifest.status = CapabilityStatus.SANDBOX_TESTED
            self._append_event_in_memory(
                capability_id, "sandbox_tested", CapabilityStatus.PROPOSED, CapabilityStatus.SANDBOX_TESTED, actor, evidence
            )
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                if row.status != CapabilityStatus.PROPOSED.value:
                    raise PolicyViolation(
                        f"capability {capability_id} must be in PROPOSED state to record sandbox evidence, "
                        f"is {row.status}"
                    )
                row.sandbox_evidence = evidence
                row.status = CapabilityStatus.SANDBOX_TESTED.value
                await self._append_event_db(
                    session, capability_id, "sandbox_tested", CapabilityStatus.PROPOSED, CapabilityStatus.SANDBOX_TESTED,
                    actor, evidence,
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    async def activate(self, capability_id: str, *, actor: str, reason: str) -> CapabilityManifest:
        """§8.5 Turn 5 — last explicit human gate. Structurally enforces
        the two hard rules: no skipping sandbox, no self-approval."""
        if self._session_factory is None:
            manifest = self._require(capability_id)
            if manifest.status is not CapabilityStatus.SANDBOX_TESTED:
                raise PolicyViolation(
                    f"capability {capability_id} must pass sandbox testing before activation, "
                    f"is {manifest.status.value} — no fast-forward allowed"
                )
            if actor == manifest.proposed_by:
                raise PolicyViolation(
                    "the proposing agent cannot activate its own capability — an independent admin must approve"
                )
            manifest.status = CapabilityStatus.ACTIVE
            self._append_event_in_memory(
                capability_id, "activated", CapabilityStatus.SANDBOX_TESTED, CapabilityStatus.ACTIVE, actor, reason
            )
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                if row.status != CapabilityStatus.SANDBOX_TESTED.value:
                    raise PolicyViolation(
                        f"capability {capability_id} must pass sandbox testing before activation, "
                        f"is {row.status} — no fast-forward allowed"
                    )
                if actor == row.proposed_by:
                    raise PolicyViolation(
                        "the proposing agent cannot activate its own capability — an independent admin must approve"
                    )
                row.status = CapabilityStatus.ACTIVE.value
                await self._append_event_db(
                    session, capability_id, "activated", CapabilityStatus.SANDBOX_TESTED, CapabilityStatus.ACTIVE,
                    actor, reason,
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    async def deprecate(self, capability_id: str, *, actor: str, reason: str) -> CapabilityManifest:
        if self._session_factory is None:
            manifest = self._require(capability_id)
            if manifest.status is CapabilityStatus.DEPRECATED:
                raise PolicyViolation(f"capability {capability_id} is already deprecated")
            from_status = manifest.status
            manifest.status = CapabilityStatus.DEPRECATED
            self._append_event_in_memory(capability_id, "deprecated", from_status, CapabilityStatus.DEPRECATED, actor, reason)
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                if row.status == CapabilityStatus.DEPRECATED.value:
                    raise PolicyViolation(f"capability {capability_id} is already deprecated")
                from_status = CapabilityStatus(row.status)
                row.status = CapabilityStatus.DEPRECATED.value
                await self._append_event_db(
                    session, capability_id, "deprecated", from_status, CapabilityStatus.DEPRECATED, actor, reason
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    async def hot_disable(self, capability_id: str, *, actor: str, reason: str) -> CapabilityManifest:
        """§8.7 — capability-level circuit breaker: pull a misbehaving
        capability from service without touching the rest of the platform.
        Only valid from ACTIVE (nothing else is "in service" to pull)."""
        if self._session_factory is None:
            manifest = self._require(capability_id)
            if manifest.status is not CapabilityStatus.ACTIVE:
                raise PolicyViolation(f"only an ACTIVE capability can be hot-disabled, {capability_id} is {manifest.status.value}")
            manifest.status = CapabilityStatus.HOT_DISABLED
            self._append_event_in_memory(
                capability_id, "hot_disabled", CapabilityStatus.ACTIVE, CapabilityStatus.HOT_DISABLED, actor, reason
            )
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                if row.status != CapabilityStatus.ACTIVE.value:
                    raise PolicyViolation(f"only an ACTIVE capability can be hot-disabled, {capability_id} is {row.status}")
                row.status = CapabilityStatus.HOT_DISABLED.value
                await self._append_event_db(
                    session, capability_id, "hot_disabled", CapabilityStatus.ACTIVE, CapabilityStatus.HOT_DISABLED,
                    actor, reason,
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    async def resume(self, capability_id: str, *, actor: str, reason: str) -> CapabilityManifest:
        if self._session_factory is None:
            manifest = self._require(capability_id)
            if manifest.status is not CapabilityStatus.HOT_DISABLED:
                raise PolicyViolation(f"only a HOT_DISABLED capability can be resumed, {capability_id} is {manifest.status.value}")
            manifest.status = CapabilityStatus.ACTIVE
            self._append_event_in_memory(
                capability_id, "resumed", CapabilityStatus.HOT_DISABLED, CapabilityStatus.ACTIVE, actor, reason
            )
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                if row.status != CapabilityStatus.HOT_DISABLED.value:
                    raise PolicyViolation(f"only a HOT_DISABLED capability can be resumed, {capability_id} is {row.status}")
                row.status = CapabilityStatus.ACTIVE.value
                await self._append_event_db(
                    session, capability_id, "resumed", CapabilityStatus.HOT_DISABLED, CapabilityStatus.ACTIVE,
                    actor, reason,
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    async def record_usage(self, capability_id: str) -> None:
        if self._session_factory is None:
            manifest = self._require(capability_id)
            manifest.usage_count += 1
            manifest.last_used_at = datetime.now(timezone.utc)
            return

        last_used_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                row.usage_count += 1
                row.last_used_at = last_used_at
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest

    async def record_failure(self, capability_id: str) -> None:
        """The other half of a real usage track record — record_usage()
        only ever fires on a successful executor call (see
        integrations/connectors/dynamic.py's execute()), so without this
        usage_count alone can't distinguish "10 clean calls" from "10
        calls, 6 of them errors." calibrate_tier() below requires
        failure_count == 0, not just a high usage_count."""
        if self._session_factory is None:
            manifest = self._require(capability_id)
            manifest.failure_count += 1
            manifest.last_used_at = datetime.now(timezone.utc)
            return

        last_used_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                row.failure_count += 1
                row.last_used_at = last_used_at
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest

    def _validate_calibration(
        self, status: CapabilityStatus, usage_count: int, failure_count: int,
        current_tier: PolicyTier, target_tier: PolicyTier, capability_id: str,
    ) -> None:
        if status is not CapabilityStatus.ACTIVE:
            raise PolicyViolation(f"capability {capability_id} must be ACTIVE to calibrate its tier, is {status.value}")
        if target_tier.value >= current_tier.value:
            raise PolicyViolation(
                f"tier calibration must loosen risk (target {target_tier.name} is not safer than the "
                f"current effective tier {current_tier.name}) — tightening uses hot_disable instead"
            )
        if usage_count < MIN_CALIBRATION_USAGE_COUNT:
            raise PolicyViolation(
                f"capability {capability_id} has only {usage_count} recorded successful invocation(s), "
                f"needs at least {MIN_CALIBRATION_USAGE_COUNT} before tier calibration is allowed"
            )
        if failure_count > 0:
            raise PolicyViolation(
                f"capability {capability_id} has {failure_count} recorded failure(s) — tier calibration "
                "requires a clean track record (zero failures), not just a high usage count"
            )

    async def calibrate_tier(
        self, capability_id: str, *, target_tier: PolicyTier, actor: str, reason: str
    ) -> CapabilityManifest:
        """Real per-action risk-tier calibration (vision §5.2/§8.6) — the
        "autonomy only earned over time via a track record" mechanism
        orchestrate/onboarding/risk_proposal.py's docstring already
        promised but nothing implemented until now. Deliberately separate
        from orchestrate/governance.py's promote_policy_tier(): that
        function is keyed by the Capability ENUM, and every onboarded
        capability shares the single DYNAMIC_CAPABILITY sentinel value —
        calling it for one onboarded capability would silently loosen
        every onboarded capability's tier at once. tier_override is keyed
        by the real capability_id instead, so calibration is genuinely
        per-capability.

        Fails closed (PolicyViolation) unless real evidence supports the
        change — see _validate_calibration: ACTIVE only, strictly safer
        target tier than the current effective one (no tightening here,
        hot_disable already owns that), a minimum recorded usage_count,
        and zero recorded failures. No partial-credit percentage
        threshold — one real failure blocks a downgrade entirely until a
        clean record is re-earned, matching this codebase's other
        fail-safe-by-default floors rather than a fuzzier heuristic that's
        hard to justify on a small sample."""
        if self._session_factory is None:
            manifest = self._require(capability_id)
            current_tier = manifest.tier_override if manifest.tier_override is not None else PolicyTier.EXECUTIVE_APPROVAL
            self._validate_calibration(
                manifest.status, manifest.usage_count, manifest.failure_count, current_tier, target_tier, capability_id
            )
            manifest.tier_override = target_tier
            self._append_event_in_memory(
                capability_id, "tier_calibrated", manifest.status, manifest.status, actor,
                f"{reason} (usage_count={manifest.usage_count}, failure_count={manifest.failure_count}, "
                f"{current_tier.name} -> {target_tier.name})",
            )
            return manifest

        async with self._session_factory() as session:
            async with session.begin():
                row = await self._locked_row(session, capability_id)
                status = CapabilityStatus(row.status)
                current_tier = PolicyTier(row.tier_override) if row.tier_override is not None else PolicyTier.EXECUTIVE_APPROVAL
                self._validate_calibration(status, row.usage_count, row.failure_count, current_tier, target_tier, capability_id)
                row.tier_override = target_tier.value
                await self._append_event_db(
                    session, capability_id, "tier_calibrated", status, status, actor,
                    f"{reason} (usage_count={row.usage_count}, failure_count={row.failure_count}, "
                    f"{current_tier.name} -> {target_tier.name})",
                )
                manifest = _row_to_manifest(row)

        self._manifests[capability_id] = manifest
        return manifest

    def manifest_for(self, capability_id: str) -> Optional[CapabilityManifest]:
        """Synchronous on purpose — hot path, see module docstring."""
        return self._manifests.get(capability_id)

    async def list_manifests(self) -> List[CapabilityManifest]:
        """All registered manifests. With a session_factory, reads from
        Postgres (the authority) and refreshes the in-memory hot-path
        cache to match — which also repairs the cache after a process
        restart, when Postgres has rows but this instance's dict started
        empty (nothing else re-hydrates it today)."""
        if self._session_factory is None:
            return list(self._manifests.values())

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CapabilityManifestRow).order_by(CapabilityManifestRow.registered_at.asc())
                )
            ).scalars().all()
        manifests = [_row_to_manifest(row) for row in rows]
        for manifest in manifests:
            self._manifests[manifest.capability_id] = manifest
        return manifests

    async def history_for(self, capability_id: str) -> List[CapabilityPromotionEvent]:
        if self._session_factory is None:
            return list(self._events.get(capability_id, []))

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CapabilityPromotionEventRow)
                    .where(CapabilityPromotionEventRow.capability_id == capability_id)
                    .order_by(CapabilityPromotionEventRow.sequence.asc())
                )
            ).scalars().all()
        return [_row_to_event(row) for row in rows]

    async def verify_integrity(self, capability_id: str) -> bool:
        verify_event_chain(await self.history_for(capability_id))
        return True

    def _require(self, capability_id: str) -> CapabilityManifest:
        manifest = self._manifests.get(capability_id)
        if manifest is None:
            raise PolicyViolation(f"no capability manifest registered for {capability_id}")
        return manifest


def hot_disable_policy_rule(manifests: CapabilityManifestRegistry):
    """Builds a ConnectorPolicyEngine rule (policy_engine.PolicyRule shape
    — Callable[[CapabilityCall], None], raises PolicyViolation to deny)
    that enforces §8.7's capability-level circuit breaker: a HOT_DISABLED
    capability is blocked at the policy layer, before any connector is
    selected, so pulling a misbehaving capability doesn't require touching
    connector registration or orchestrator code.

    Deliberately only blocks HOT_DISABLED, not DEPRECATED — deprecation is
    a soft retirement signal, not an emergency pull; a deprecated
    capability keeps working until whatever depends on it migrates off.

    A capability with no manifest at all (true for every built-in
    Capability today — none of them have gone through the §8 onboarding
    pipeline) is allowed through unchanged. This rule only starts having
    an effect once something actually calls
    CapabilityManifestRegistry.propose() for a given capability_id.

    Dynamically onboarded capabilities (Capability.DYNAMIC_CAPABILITY, see
    integrations/connectors/dynamic.py) all share that one sentinel enum
    value — their real identity travels in call.input["capability_id"], not
    call.capability.value. Looking this rule up by call.capability.value
    alone would resolve every dynamic call to the same fixed string
    ("DynamicCapability") regardless of which onboarded capability it
    actually is, so hot-disabling one onboarded capability would never
    actually match it. Resolve by the real id for dynamic calls instead.
    """

    def _rule(call: CapabilityCall) -> None:
        if call.capability is Capability.DYNAMIC_CAPABILITY:
            lookup_id = call.input.get("capability_id", call.capability.value)
        else:
            lookup_id = call.capability.value
        manifest = manifests.manifest_for(lookup_id)
        if manifest is not None and manifest.status is CapabilityStatus.HOT_DISABLED:
            raise PolicyViolation(f"capability {lookup_id} is hot-disabled and cannot be invoked")

    return _rule
