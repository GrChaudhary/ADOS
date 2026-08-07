"""
Structured logging and request correlation.

Before this the app had no logging configuration at all: a handful of `ados.*`
loggers existed with no handler or formatter behind them (so they inherited
the root WARNING default and mostly went nowhere), and startup diagnostics
were bare `print()` calls. Nothing carried an identifier, so two concurrent
incidents produced interleaved lines with no way to tell them apart.

Three pieces, all stdlib -- no new dependency:

1. JSON log lines, so a log shipper can index them by field instead of
   regex-ing prose.
2. A request id generated per HTTP request and attached to every log line
   emitted while handling it, via contextvars (which follow async tasks
   correctly, unlike thread-locals).
3. The same id flows onto EventEnvelope.trace_id, a field that has existed
   since the v2 schema and that no producer has ever populated. That is what
   makes an incident's HTTP request and its event trail joinable.

Deliberately NOT included: a /metrics endpoint. This codebase has a strong,
consistently applied rule against building infrastructure with no consumer
(see infrastructure/OPA_POLICY_SPIKE.md and KEYCLOAK_IDENTITY_DECISION.md),
and there is no scraper to serve. Logs are useful the moment they exist;
metrics without Prometheus are decoration. Revisit when something scrapes.
"""

import json
import logging
import sys
import uuid
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from contracts.trace_context import current_trace_id, reset_trace_id, set_trace_id

# One id, two uses: it tags log lines here, and EventEnvelope picks up the
# same value as its trace_id via contracts/trace_context.py. Storing it once,
# in the lower layer, is what keeps those two from drifting apart.
REQUEST_ID_HEADER = "X-Request-ID"

# Attributes LogRecord always has; anything else a caller passed via
# `extra={...}` is application detail worth emitting.
_STANDARD_LOGRECORD_FIELDS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


def current_request_id() -> Optional[str]:
    """The id of the request being handled, or None outside a request (a
    background task, a CLI script, a test)."""
    return current_trace_id()


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_FIELDS:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Installs a single stdout handler on the root logger.

    Replaces (rather than adds to) existing handlers so repeated calls --
    which happen constantly under pytest, where the app is constructed per
    test -- can't stack up duplicate output.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonLogFormatter() if json_output else logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
        )
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; let them propagate to ours instead
    # so access logs and application logs share one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns every request an id, echoes it back on the response, and makes
    it available to every log line and event produced while handling it.

    An inbound X-Request-ID is honoured so a correlation id set by a gateway
    or a caller survives into this service rather than being replaced.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = set_trace_id(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            # Must reset, not just overwrite: without this the id leaks into
            # whatever the event loop runs next on this context.
            reset_trace_id(token)
