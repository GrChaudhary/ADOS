"""
The ambient trace id for the current request or task.

Lives in contracts/ rather than backend/ on purpose. EventEnvelope.trace_id
needs to populate itself, and contracts/ is the lowest layer -- everything
imports it and it imports nothing of ours. Putting the ContextVar in
backend/app/ instead would mean contracts/ importing upward into the web
layer, which is exactly backwards, and would make the envelope unusable from
a script or a test that never builds a FastAPI app.

Uses contextvars, not threading.local: requests are asyncio tasks sharing one
thread, so a thread-local would bleed one request's id into another's events.
A ContextVar is copied into each task, and into asyncio.to_thread workers --
which matters now that orchestrate/agent_runner.py runs agents in a thread.
"""

import contextvars
from typing import Optional

_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "ados_trace_id", default=None
)


def current_trace_id() -> Optional[str]:
    """The trace id in scope, or None outside a request (background task, CLI
    script, test). None is a normal value, not an error -- EventEnvelope's
    trace_id has always been Optional."""
    return _trace_id.get()


def set_trace_id(value: Optional[str]):
    """Returns the token needed to reset() it. Callers that set this per
    request must reset in a finally block, or the id leaks into whatever
    the event loop runs next on that context."""
    return _trace_id.set(value)


def reset_trace_id(token) -> None:
    _trace_id.reset(token)
