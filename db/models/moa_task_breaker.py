"""
ORM model for a paused MOA task's cascade circuit breaker
(orchestrate/cascade_breaker.py, vision §5.3).

This is the durable replacement for backend/app/main.py's
`app.state.moa_pending_tasks` dict, and it carries the piece of that tuple
which could NOT simply be rebuilt: the breaker's streak.

Why a table rather than the LangGraph checkpoint. The graph's own state is
already durable via db/checkpointer.py, and the breaker's streak could have
been folded into MOAGraphState to ride along for free. It lives here instead
because two governance endpoints need to work *across* tasks —
`GET /governance/circuit-breaker` aggregates every live breaker, and
`POST /governance/circuit-breaker/clear` resets them — and answering "which
tasks currently have an open breaker" from checkpoint storage would mean
scanning every thread's latest checkpoint and deserialising it. A row per
paused task answers both with an ordinary query.

The row's lifecycle mirrors exactly what the dict did, so the semantics
carry over unchanged:

    task pauses on an interrupt  -> row exists   (task is "live")
    task reaches a final answer  -> row deleted  (nothing to count)

That is also why `GET /governance/circuit-breaker` reporting CLOSED/0 with
no rows is still the honest answer rather than a fabricated global zero —
the same reasoning the endpoint's own comment already gives.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MOATaskBreakerRow(Base):
    __tablename__ = "moa_task_breakers"

    # The LangGraph thread_id — the same value used as the checkpointer's
    # thread key and as the task_id in the REST API, so this row and the
    # task's checkpointed state are joinable without a second identifier.
    task_id: Mapped[str] = mapped_column(primary_key=True)

    # "closed" | "open" — CascadeState's values, stored as its plain str
    # rather than a DB enum so adding a state later doesn't need a migration
    # on a table this small.
    state: Mapped[str]

    # The run of auto-approved actions, as [{"capability": ..., "summary":
    # ...}] — AutoApprovedAction is a frozen dataclass, kept as JSON because
    # it is only ever read back as a whole batch for one task, never queried
    # field-by-field.
    streak: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Persisted per task rather than read from CascadeCircuitBreaker's class
    # default at restore time: a task that paused under threshold=4 must
    # keep being judged by 4 even if the default is retuned while it sits
    # paused, otherwise an admin changing the setting would retroactively
    # open or close breakers on tasks already in flight.
    threshold: Mapped[int]

    # The domain the task was started in ("hr", "it", ...). Not needed to
    # restore the breaker; kept so the governance endpoints can report which
    # pods have live tasks without rebuilding every graph to ask.
    domain: Mapped[str] = mapped_column(default="hr")

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
