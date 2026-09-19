from __future__ import annotations

import asyncio

from app.routers import health


class _DatabaseDown:
    async def __aenter__(self):
        raise ConnectionRefusedError("connection to server at 10.0.0.5 refused")

    async def __aexit__(self, *exc):
        return False


class _DatabaseHangs:
    async def __aenter__(self):
        await asyncio.sleep(60)

    async def __aexit__(self, *exc):
        return False


def test_health_is_ok_when_the_database_answers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_health_needs_no_authentication(client):
    # Deploy checks and load balancers call it with no credentials.
    assert client.get("/health").status_code == 200


def test_version_is_the_build_the_app_was_started_with(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "3f2c1a9")
    assert client.get("/health").json()["version"] == "3f2c1a9"


def test_version_defaults_to_dev_outside_a_ci_build(client, monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert client.get("/health").json()["version"] == "dev"


def test_health_is_503_when_the_database_is_unreachable(client, app):
    app.state.db_sessionmaker = lambda: _DatabaseDown()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["database"] == "unreachable"
    # The failure reason (an internal address here) must not leak to callers.
    assert "10.0.0.5" not in response.text


def test_a_hanging_database_reads_as_unhealthy_instead_of_hanging_the_check(
    client, app, monkeypatch
):
    monkeypatch.setattr(health, "DB_CHECK_TIMEOUT", 0.05)
    app.state.db_sessionmaker = lambda: _DatabaseHangs()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_health_still_reports_the_version_when_unhealthy(client, app, monkeypatch):
    # A failed deploy check needs to say *which build* is failing.
    monkeypatch.setenv("APP_VERSION", "deadbeef")
    app.state.db_sessionmaker = lambda: _DatabaseDown()
    assert client.get("/health").json()["version"] == "deadbeef"
