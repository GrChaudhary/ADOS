"""
P12 -- a minimal, server-side-only, Postgres-backed rate limiter. See
db/models/rate_limit_event.py for the full rationale and why this is a
different mechanism from admission_control.py's concurrency ceilings.

Every limit this module enforces must document, here, in one place:
purpose, default, configuration, enforcement point, metric, alert/runbook
behavior -- per P12's own instructions. Currently one limiter.

MISSION-START RATE LIMIT
-------------------------
Purpose:     Bound how often Prime Agent missions (RunPrimeRLMAgent -- the
             one capability that starts a real Docker container and makes
             real paid-LLM-provider calls) can be STARTED, independent of
             how many are concurrently in flight. Closes doc 18's
             separately-named "Rate limiting: None... a hard TPM ceiling
             was already hit in testing" gap -- admission control's mission-
             concurrency gate does not cover this: a caller whose missions
             fail or get refused immediately could restart one every loop
             iteration and stay under any concurrency ceiling indefinitely.
Default:     20 starts per 300s (5 minutes) -- generous relative to
             max_concurrent_prime_missions' default of 3 (a real mission
             normally holds its slot far longer than 15s), but bounds a
             true hot-loop to a small, fixed multiple of the concurrency
             ceiling rather than leaving it completely unbounded.
Configuration: Settings.mission_start_rate_limit_max /
             Settings.mission_start_rate_limit_window_seconds
             (backend/app/config.py). Set max<=0 to disable.
Enforcement: integrations/hub.py::IntegrationHub.invoke(), immediately
             after the (already-proven) admission-control gates and before
             connector.execute() -- before any Docker container starts or
             any external call happens. Server-side only: nothing in
             `call.input` (agent-supplied) or any `_`-prefixed governance
             hint is ever consulted.
Metric:      ados_admission_rejections_total{gate="mission_start_rate"}
             (reuses the existing admission-rejections metric family and
             its fixed-enum `gate` label rather than inventing a parallel
             metric for what is, from an operator's dashboard, the same
             kind of event: "a mission start was refused, and here's why").
Alert/runbook: ADOSMissionStartRateLimited (infrastructure/prometheus/
             alert_rules.yml); operator runbook Model B section.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text

from db.models.rate_limit_event import RateLimitEventRow

GATE_MISSION_START_RATE = "mission_start_rate"


class RateLimiter:
    def __init__(self, *, session_factory: Optional[object] = None):
        # Same Optional[async_sessionmaker], loosely typed as
        # admission_control.py's own to avoid a hard db.engine dependency
        # for callers/tests that never set this. `session_factory=None`
        # (every test that constructs IntegrationHub() without one) means
        # the limiter is a no-op -- never refuses, matching every other
        # optional-DB-backed mechanism in this codebase.
        self._session_factory = session_factory

    @property
    def enabled(self) -> bool:
        return self._session_factory is not None

    async def try_admit_mission_start(self, *, limit: int, window_seconds: float) -> bool:
        """True if this start counts toward the window and is admitted.
        `limit <= 0` disables the limiter unconditionally (an operator
        opt-out, not a 0-means-zero-allowed footgun)."""
        if self._session_factory is None or limit <= 0:
            return True
        async with self._session_factory() as db:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"ados_rate_limit_{GATE_MISSION_START_RATE}"},
            )
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=float(window_seconds))
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(RateLimitEventRow)
                    .where(RateLimitEventRow.limiter == GATE_MISSION_START_RATE)
                    .where(RateLimitEventRow.occurred_at > cutoff)
                )
            ).scalar_one()
            if count >= limit:
                await db.rollback()
                return False
            db.add(RateLimitEventRow(limiter=GATE_MISSION_START_RATE))
            await db.commit()
            return True
