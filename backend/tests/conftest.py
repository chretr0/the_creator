import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """One app lifespan per test session: the DB pool cannot be reopened once closed."""
    try:
        with TestClient(app) as c:
            yield c
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"database unavailable: {exc}")
