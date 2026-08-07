"""
Asynchronous EventBus listener for real-time Obsidian Vault projection.
Listens to event stream in a background worker queue, generating Markdown notes without blocking hot execution paths.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from contracts import EventEnvelope
from .renderer import (
    render_decision_note,
    render_task_note,
)
from .writer import ObsidianVaultWriter

logger = logging.getLogger("ados.obsidian.listener")

# The exact event_type strings real producers publish. Deliberately spelled
# out rather than matched by a dotted "moa.*"/"capability.*" prefix: no
# producer in this codebase emits dotted names, so prefix matching silently
# projected nothing at all. Keep this list honest — an entry here that
# nothing publishes is a note type that will never appear.
#   GovernancePendingApproval / GovernanceApprovalDecision
#       <- orchestrate/async_approvals.py, via backend/app/routers/moa.py
GOVERNANCE_PENDING_APPROVAL = "GovernancePendingApproval"
GOVERNANCE_APPROVAL_DECISION = "GovernanceApprovalDecision"

# How many pending-approval contexts to remember so a later decision event
# (whose payload carries only task_id/decision/actor) can be enriched with
# the capability and cost it decided on.
_MAX_PENDING_CONTEXT = 500


class ObsidianProjectionListener:
    """Consumes EventBus envelopes and projects live Markdown notes into Obsidian Vault."""

    def __init__(self, writer: Optional[ObsidianVaultWriter] = None):
        self.writer = writer or ObsidianVaultWriter()
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=1000)
        self._worker_task: Optional[asyncio.Task] = None
        self._last_projected_at: Optional[str] = None
        self._projected_count: int = 0
        # task_id -> the pending-approval details, so the matching decision
        # event can render a complete audit record.
        self._pending_context: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    async def start(self) -> None:
        """Starts the background worker queue task."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        """Stops the background queue worker cleanly."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def listen_to_bus(self, event_bus: Any) -> None:
        """Continuously streams events off the EventBus and queues them."""
        try:
            async for envelope in event_bus.stream():
                self.on_event(envelope)
        except asyncio.CancelledError:
            pass

    def on_event(self, envelope: EventEnvelope) -> None:
        """Non-blocking event callback handler registered with EventBus."""
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull:
            logger.warning("Obsidian projection queue full, dropping event %s", getattr(envelope, "event_id", "unknown"))

    async def _process_queue(self) -> None:
        while True:
            try:
                envelope = await self._queue.get()
            except asyncio.CancelledError:
                break
            cancelled = False
            try:
                await self._handle_envelope(envelope)
            except asyncio.CancelledError:
                cancelled = True
            except Exception as e:
                logger.error("Error processing Obsidian projection event: %s", e)
            finally:
                # Has to run even when projection raised, or the queue's
                # unfinished count leaks and join() blocks forever.
                self._queue.task_done()

            if cancelled:
                break

    async def _handle_envelope(self, envelope: EventEnvelope) -> None:
        event_type = getattr(envelope, "event_type", "") or ""
        payload = getattr(envelope, "payload", None) or {}

        if event_type == GOVERNANCE_PENDING_APPROVAL:
            await self._project_pending_approval(envelope, payload)
        elif event_type == GOVERNANCE_APPROVAL_DECISION:
            await self._project_approval_decision(envelope, payload)

    @staticmethod
    def _field(payload: Dict[str, Any], alias: str, snake: str, default: Any = None) -> Any:
        """Reads a payload field by camelCase alias first.

        Producers serialize with model_dump(by_alias=True), so the alias is
        what arrives over the wire — but the same payloads are constructed
        by field name in tests and by populate_by_name callers, so accept both.
        """
        if alias in payload:
            return payload[alias]
        return payload.get(snake, default)

    async def _write(self, filename: str, content: str) -> None:
        if await self.writer.write_note(filename, content):
            self._projected_count += 1
            self._last_projected_at = datetime.now(timezone.utc).isoformat()

    def _remember_pending(self, task_id: str, context: Dict[str, Any]) -> None:
        self._pending_context[task_id] = context
        self._pending_context.move_to_end(task_id)
        while len(self._pending_context) > _MAX_PENDING_CONTEXT:
            self._pending_context.popitem(last=False)

    async def _project_pending_approval(self, envelope: EventEnvelope, payload: Dict[str, Any]) -> None:
        """A governed action paused for human sign-off -> live task note."""
        task_id = self._field(payload, "taskId", "task_id") or envelope.correlation_id
        if not task_id:
            return

        action_key = self._field(payload, "actionKey", "action_key", "unknown")
        capability = payload.get("capability") or action_key
        summary = payload.get("summary") or ""
        context = {
            "domain": payload.get("domain") or "hr",
            "action_key": action_key,
            "capability": capability,
            "policy_tier": self._field(payload, "policyTier", "policy_tier", 1),
            "estimated_cost_usd": self._field(payload, "estimatedCostUsd", "estimated_cost_usd", 0.0),
            "summary": summary,
        }
        self._remember_pending(task_id, context)

        note = render_task_note(
            task_id=task_id,
            domain=context["domain"],
            employee_name=self._field(payload, "targetEntity", "target_entity", "System Target"),
            instruction=summary or f"Governed action '{action_key}' awaiting sign-off",
            status="pending_approval",
            proposed_action=context,
        )
        await self._write(f"04_Live_Tasks/Task-{task_id[:8]}.md", note)

    async def _project_approval_decision(self, envelope: EventEnvelope, payload: Dict[str, Any]) -> None:
        """A human approved/rejected a held action -> audit ledger record."""
        task_id = self._field(payload, "taskId", "task_id") or envelope.correlation_id
        if not task_id:
            return

        # Derived from the event id rather than time.time(), so replaying the
        # same event rewrites the same note instead of littering the ledger
        # with a fresh copy on every restart.
        event_id = getattr(envelope, "event_id", "") or ""
        decision_id = f"dec-{task_id[:8]}-{event_id[:8]}" if event_id else f"dec-{task_id[:8]}"

        context = self._pending_context.pop(task_id, {})
        decision = payload.get("decision") or "pending"
        actor = self._field(payload, "approvedBy", "approved_by") or "system"
        role = payload.get("role")
        capability_id = context.get("capability") or "governed_action"

        note = render_decision_note(
            decision_id=decision_id,
            task_id=task_id,
            action_key=context.get("action_key", "governed_action"),
            capability_id=capability_id,
            tier=context.get("policy_tier", 1),
            cost_usd=context.get("estimated_cost_usd", 0.0),
            decision=decision,
            actor=f"{actor} ({role})" if role else actor,
            reasoning=context.get("summary") or f"Governance decision record for {capability_id}",
        )
        await self._write(f"05_Audit_Ledger/Decision-{decision_id}.md", note)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "queue_depth": self._queue.qsize(),
            "projected_count": self._projected_count,
            "last_projected_at": self._last_projected_at,
            "target_dir": str(self.writer.target_dir),
            "rest_api_enabled": bool(self.writer.rest_api_url),
        }
