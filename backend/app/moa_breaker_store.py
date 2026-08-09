"""
Persistence for a paused MOA task's cascade circuit breaker
(orchestrate/cascade_breaker.py) — the durable half of what
app.state.moa_pending_tasks used to hold in memory.

The other half, the graph's own state, is handled by db/checkpointer.py. The
split is deliberate and worth stating plainly, because "the task is paused"
is now recorded in two places:

    checkpoints table   -> what the graph was doing (LangGraph owns this)
    moa_task_breakers   -> the streak of auto-approved actions (we own this)

A row here is what makes a task "live" for governance purposes, mirroring
exactly when the old dict had an entry: written when a task pauses on an
interrupt, deleted when it reaches a final answer.

Why the breaker can't just be rebuilt like the graph can: the graph is pure
structure, so `build_graph()` reconstructs an identical one and the
checkpointer supplies the state. The breaker IS state — its `_streak` is the
running count of individually-safe actions that nobody has reviewed as a
batch. Rebuilding a fresh CascadeCircuitBreaker on resume would silently
reset that count to zero, which is worse than having no breaker at all,
because the system would still report itself as protected. See
docs/DESIGN_DURABLE_MOA_STATE.md.
"""

from typing import Dict, List, Optional

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.moa_task_breaker import MOATaskBreakerRow
from orchestrate.cascade_breaker import AutoApprovedAction, CascadeCircuitBreaker, CascadeState


def _to_breaker(row: MOATaskBreakerRow) -> CascadeCircuitBreaker:
    return CascadeCircuitBreaker(
        threshold=row.threshold,
        state=CascadeState(row.state),
        _streak=[AutoApprovedAction(capability=a["capability"], summary=a["summary"]) for a in (row.streak or [])],
    )


def _streak_json(breaker: CascadeCircuitBreaker) -> List[dict]:
    return [{"capability": a.capability, "summary": a.summary} for a in breaker.review_batch()]


async def save(session: AsyncSession, task_id: str, breaker: CascadeCircuitBreaker, domain: str = "hr") -> None:
    """Upsert — a task pauses more than once (one interrupt per proposed
    action), and each pause must overwrite the previous snapshot rather than
    conflict with it."""
    row = await session.get(MOATaskBreakerRow, task_id)
    if row is None:
        row = MOATaskBreakerRow(task_id=task_id, domain=domain)
        session.add(row)
    row.state = breaker.state.value
    row.streak = _streak_json(breaker)
    row.threshold = breaker.threshold
    row.domain = domain


async def load(session: AsyncSession, task_id: str) -> Optional[CascadeCircuitBreaker]:
    """None means no such paused task — the 404 case that
    `moa_pending_tasks.pop(task_id, None)` used to answer."""
    row = await session.get(MOATaskBreakerRow, task_id)
    return None if row is None else _to_breaker(row)


async def delete(session: AsyncSession, task_id: str) -> bool:
    row = await session.get(MOATaskBreakerRow, task_id)
    if row is None:
        return False
    await session.delete(row)
    return True


async def list_live(session: AsyncSession) -> Dict[str, CascadeCircuitBreaker]:
    """Every currently-paused task's breaker, for the honest aggregate
    GET /governance/circuit-breaker reports. Replaces iterating the dict."""
    rows = (await session.execute(select(MOATaskBreakerRow))).scalars().all()
    return {row.task_id: _to_breaker(row) for row in rows}


async def clear_all_open(session: AsyncSession) -> int:
    """POST /governance/circuit-breaker/clear — the explicit human
    batch-review sign-off. Clears the streak in place rather than deleting
    rows: the tasks are still paused and still need their thread_id to
    resume, so removing them would strand the approvals."""
    rows = (await session.execute(select(MOATaskBreakerRow))).scalars().all()
    cleared = 0
    for row in rows:
        if row.state == CascadeState.OPEN.value or row.streak:
            row.state = CascadeState.CLOSED.value
            row.streak = []
            cleared += 1
    return cleared


async def delete_all(session: AsyncSession) -> None:
    """Test helper — truncating between tests without importing the model."""
    await session.execute(sql_delete(MOATaskBreakerRow))
