"""
RequestIdMiddleware through the real app (backend/app/observability.py).

The pure formatting/contextvar tests live in tests/test_observability.py;
these need the `client` fixture, which is scoped to backend/tests/.
"""

from backend.app.observability import REQUEST_ID_HEADER

def test_response_carries_a_request_id_header(client):
    response = client.get("/healthz")
    assert response.headers.get(REQUEST_ID_HEADER)


def test_an_inbound_request_id_is_honoured_not_replaced(client):
    """A gateway or caller that already set a correlation id should keep it,
    so the trail joins up across services."""
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "upstream-id-1"})
    assert response.headers[REQUEST_ID_HEADER] == "upstream-id-1"


def test_each_request_gets_a_distinct_id(client):
    first = client.get("/healthz").headers[REQUEST_ID_HEADER]
    second = client.get("/healthz").headers[REQUEST_ID_HEADER]
    assert first != second
