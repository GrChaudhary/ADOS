import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {settings.service_auth_token}"}
