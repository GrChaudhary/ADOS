"""
Structured logging, request ids, and trace propagation
(backend/app/observability.py, contracts/trace_context.py).

The property worth pinning: one id ties an HTTP request to every log line AND
every event produced while handling it. EventEnvelope.trace_id has existed
since the v2 schema with no producer ever setting it -- these tests are what
stop it silently going back to always-None.
"""

import json
import logging

import pytest

from backend.app.observability import (
    REQUEST_ID_HEADER,
    JsonLogFormatter,
    configure_logging,
    current_request_id,
)
from contracts import EventEnvelope
from contracts.trace_context import reset_trace_id, set_trace_id


def _format(record_kwargs=None, **extra) -> dict:
    logger = logging.getLogger("ados.test")
    record = logger.makeRecord(
        "ados.test", logging.INFO, "f.py", 1, "hello %s", ("world",), None,
        extra=extra or None,
    )
    return json.loads(JsonLogFormatter().format(record))


# --------------------------------------------------------------------------
# JSON formatting
# --------------------------------------------------------------------------

def test_log_lines_are_json_with_the_expected_fields():
    payload = _format()
    assert payload["level"] == "INFO"
    assert payload["logger"] == "ados.test"
    assert payload["message"] == "hello world"
    assert "timestamp" in payload


def test_extra_fields_are_emitted_as_real_json_fields():
    """The point of structured logs: `extra={"incident_count": 3}` has to be
    an indexable field, not prose a shipper has to regex out."""
    payload = _format(incident_count=3, domain="hr")
    assert payload["incident_count"] == 3
    assert payload["domain"] == "hr"


def test_an_unserialisable_extra_never_breaks_the_log_line():
    """A log call must not raise just because someone passed an object. Losing
    fidelity on one field beats losing the line -- or worse, crashing the code
    that was trying to report a problem."""
    payload = _format(weird=object())
    assert "weird" in payload
    assert isinstance(payload["weird"], str)


def test_exceptions_are_captured():
    logger = logging.getLogger("ados.test")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logger.makeRecord(
            "ados.test", logging.ERROR, "f.py", 1, "failed", (), sys.exc_info()
        )
    payload = json.loads(JsonLogFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_configure_logging_is_idempotent():
    """Called once per app construction, which under pytest is once per test.
    Stacking handlers would multiply every log line."""
    configure_logging()
    configure_logging()
    configure_logging()
    assert len(logging.getLogger().handlers) == 1


# --------------------------------------------------------------------------
# Trace propagation — the part that ties logs to events
# --------------------------------------------------------------------------

def test_trace_id_is_none_outside_a_request():
    """Scripts, background tasks and tests have no request. None is a normal
    value here, not a failure."""
    assert current_request_id() is None
    assert EventEnvelope(
        event_type="Test", correlation_id="c", produced_by="test", payload={}
    ).trace_id is None


def test_every_envelope_built_during_a_request_carries_its_id():
    """No producer sets trace_id explicitly -- all 7 of them get it for free
    from the default_factory. That is what makes this survive new producers
    being added later."""
    token = set_trace_id("req-abc123")
    try:
        envelope = EventEnvelope(
            event_type="Test", correlation_id="c", produced_by="test", payload={}
        )
        assert envelope.trace_id == "req-abc123"
        assert _format()["request_id"] == "req-abc123"
    finally:
        reset_trace_id(token)


def test_the_id_does_not_leak_after_reset():
    token = set_trace_id("req-leaky")
    reset_trace_id(token)
    assert current_request_id() is None
    assert EventEnvelope(
        event_type="Test", correlation_id="c", produced_by="test", payload={}
    ).trace_id is None


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_share_a_trace_id():
    """contextvars, not thread-locals: two requests in flight must not see
    each other's id. This is the bug a thread-local would have."""
    import asyncio

    seen = {}

    async def handler(name: str):
        token = set_trace_id(name)
        try:
            await asyncio.sleep(0.01)  # force interleaving
            seen[name] = EventEnvelope(
                event_type="Test", correlation_id="c", produced_by="test", payload={}
            ).trace_id
        finally:
            reset_trace_id(token)

    await asyncio.gather(handler("req-A"), handler("req-B"), handler("req-C"))
    assert seen == {"req-A": "req-A", "req-B": "req-B", "req-C": "req-C"}


@pytest.mark.asyncio
async def test_trace_id_follows_work_offloaded_to_a_thread():
    """orchestrate/agent_runner.py now runs agents via asyncio.to_thread, so
    anything they log or publish must still carry the request's id."""
    import asyncio

    token = set_trace_id("req-threaded")
    try:
        envelope = await asyncio.to_thread(
            lambda: EventEnvelope(
                event_type="Test", correlation_id="c", produced_by="test", payload={}
            )
        )
        assert envelope.trace_id == "req-threaded"
    finally:
        reset_trace_id(token)
