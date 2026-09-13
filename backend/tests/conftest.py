from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """A freshly seeded app for each test, so tests don't share state."""
    return create_app(with_seed_data=True)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bare_app():
    """An app with no seed data, for tests that want a clean slate."""
    return create_app(with_seed_data=False)


@pytest.fixture
def bare_client(bare_app):
    with TestClient(bare_app) as c:
        yield c
