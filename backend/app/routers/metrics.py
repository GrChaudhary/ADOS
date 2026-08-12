"""
P11 — GET /metrics, the Prometheus text exposition endpoint.

Unauthenticated, matching /healthz's existing posture (health.py) — a
scraper does not carry a session JWT, and neither endpoint returns anything
secret: counts, gauges, and a git commit hash. Keeping this endpoint out from
behind a network boundary is an operator's job, documented in the runbook
(docs/prime-agent-integration/20-operator-runbook.md), not an app-level auth
feature this file builds.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.mission import CapabilityRequestRow
from db.session import get_db_session

from ..metrics import (
    approval_queue_depth,
    approval_queue_oldest_age_seconds,
    outcome_unknown_open,
    outcome_unknown_oldest_age_seconds,
)

router = APIRouter(tags=["metrics"])


async def _refresh_backlog_gauges(session: AsyncSession) -> None:
    """Live COUNT/MIN queries against Postgres, run once per scrape — see
    backend/app/metrics.py's own docstring for why these are gauges set here
    rather than in-process running totals."""
    now = datetime.now(timezone.utc)

    pending_count, pending_oldest = (
        await session.execute(
            select(func.count(CapabilityRequestRow.request_id), func.min(CapabilityRequestRow.created_at))
            .where(CapabilityRequestRow.status == "pending_approval")
        )
    ).one()
    approval_queue_depth.set(pending_count or 0)
    approval_queue_oldest_age_seconds.set(
        (now - pending_oldest.replace(tzinfo=timezone.utc)).total_seconds() if pending_oldest else 0.0
    )

    unknown_count, unknown_oldest = (
        await session.execute(
            select(func.count(CapabilityRequestRow.request_id), func.min(CapabilityRequestRow.updated_at))
            .where(CapabilityRequestRow.status == "outcome_unknown")
        )
    ).one()
    outcome_unknown_open.set(unknown_count or 0)
    outcome_unknown_oldest_age_seconds.set(
        (now - unknown_oldest.replace(tzinfo=timezone.utc)).total_seconds() if unknown_oldest else 0.0
    )


@router.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_db_session)) -> Response:
    await _refresh_backlog_gauges(session)
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
