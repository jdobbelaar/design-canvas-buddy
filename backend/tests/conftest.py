"""Test fixtures.

By default every test gets its own private in-memory SQLite database. To run
the same suite against Postgres, point TEST_DATABASE_URL at a *throwaway*
database, e.g.:

    docker run -d --name pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=dcb_test \\
        -p 55432:5432 postgres:17-alpine
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/dcb_test \\
        uv run pytest

The fixtures drop and recreate every table around each test, so the database
name must contain "test" (enforced below).
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

from app.db import init_db, normalize_database_url
from app.db_models import Base
from app.main import create_app
from app.seed import seed

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_URL = normalize_database_url(TEST_DATABASE_URL)
_IS_SQLITE = _URL.get_backend_name() == "sqlite"

if not _IS_SQLITE and "test" not in (_URL.database or "").lower():
    raise RuntimeError(
        f"Refusing to run tests against database {_URL.database!r}: the fixtures "
        "drop every table, so TEST_DATABASE_URL must point at a database whose "
        "name contains 'test'."
    )

# asyncpg connections are bound to the event loop that opened them. These tests
# reach the database from several short-lived loops (asyncio.run in fixtures and
# helpers, plus TestClient's own thread), so a pooled connection would be reused
# from a dead loop. NullPool opens a fresh connection each time instead.
_ENGINE_KWARGS: dict[str, object] = {} if _IS_SQLITE else {"poolclass": NullPool}


def _make_app(*, with_seed_data: bool):
    """Build an app on a clean database, with tables created (and optionally seeded).

    FastAPI only runs `lifespan` (where main.py normally does this) once the
    app is actually started via TestClient. Fixtures that hand back the bare
    `app` without wrapping it in TestClient need the database ready anyway,
    so do it eagerly here instead of relying on lifespan. init_db/seed are
    both idempotent, so TestClient re-running lifespan afterward is harmless.
    """
    fastapi_app = create_app(
        database_url=TEST_DATABASE_URL,
        with_seed_data=with_seed_data,
        engine_kwargs=_ENGINE_KWARGS,
    )

    async def _init():
        engine = fastapi_app.state.db_engine
        # Start from nothing even if a previous run died mid-test (a no-op for
        # a fresh in-memory SQLite database).
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await init_db(engine)
        if with_seed_data:
            async with fastapi_app.state.db_sessionmaker() as db:
                await seed(db)

    asyncio.run(_init())
    return fastapi_app


def _teardown(fastapi_app):
    async def _drop():
        engine = fastapi_app.state.db_engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_drop())


@pytest.fixture
def app():
    """A freshly seeded app with its own isolated database."""
    fastapi_app = _make_app(with_seed_data=True)
    yield fastapi_app
    _teardown(fastapi_app)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bare_app():
    """An app with no seed data, for tests that want a clean slate."""
    fastapi_app = _make_app(with_seed_data=False)
    yield fastapi_app
    _teardown(fastapi_app)


@pytest.fixture
def bare_client(bare_app):
    with TestClient(bare_app) as c:
        yield c


def run_db(app, coro_factory):
    """Run a one-off async DB query against *app*'s database from a sync test.

    `coro_factory` is a zero-arg callable returning a coroutine that takes
    the AsyncSession as its argument, e.g.:
        run_db(app, lambda db: store.get_session_objects(db, "s1"))
    """

    async def _run():
        async with app.state.db_sessionmaker() as db:
            return await coro_factory(db)

    return asyncio.run(_run())
