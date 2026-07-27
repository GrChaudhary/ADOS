"""
Unit & integration tests for the Knowledge Graph REST Router (GET /knowledge/graph).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from knowledge import KnowledgeGraph


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_build_graph_snapshot_covers_seed_data():
    graph = KnowledgeGraph()
    snapshot = graph.build_graph_snapshot()

    node_ids = {n.id for n in snapshot.nodes}
    node_types = {n.id: n.type for n in snapshot.nodes}

    # The substitute part variant is only reachable via a SUBSTITUTE edge,
    # not the base product's BOM list - must still appear as a PART node.
    assert "MH-8820-PC" in node_ids
    assert node_types["MH-8820-PC"] == "PART"

    # SUP-305 (SKF Industrial) is seeded but unused by any part - it should
    # still render as an isolated SUPPLIER node.
    assert "SUP-305" in node_ids
    assert node_types["SUP-305"] == "SUPPLIER"

    assert node_types["EV-POW-800V"] == "PRODUCT"

    edge_types = {e.type for e in snapshot.edges}
    assert edge_types == {"BOM", "SUPPLIES", "SUBSTITUTE"}

    substitute_edges = [e for e in snapshot.edges if e.type == "SUBSTITUTE"]
    assert len(substitute_edges) == 1
    assert substitute_edges[0].source == "MH-8820"
    assert substitute_edges[0].target == "MH-8820-PC"


def test_get_knowledge_graph_unauthorized(client):
    response = client.get("/knowledge/graph")
    assert response.status_code == 401


def test_get_knowledge_graph_success(client):
    response = client.get(
        "/knowledge/graph",
        headers={"Authorization": "Bearer dev-local-only-token"}
    )
    assert response.status_code == 200
    data = response.json()

    node_ids = {n["id"] for n in data["nodes"]}
    assert "EV-POW-800V" in node_ids
    assert "MH-8820-PC" in node_ids
    assert "SUP-305" in node_ids

    bom_edges = [e for e in data["edges"] if e["type"] == "BOM"]
    assert len(bom_edges) == 5
