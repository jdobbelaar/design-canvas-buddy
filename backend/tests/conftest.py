from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app
from app.seed import seed

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _prepare(fastapi_app, *, with_seed_data: bool):
    """Create tables (and optionally seed) up front.

    FastAPI only runs `lifespan` (where main.py normally does this) once the
    app is actually started via TestClient. Fixtures that hand back the bare
    `app` without wrapping it in TestClient need the database ready anyway,
    so do it eagerly here instead of relying on lifespan. init_db/seed are
    both idempotent, so TestClient re-running lifespan afterward is harmless.
    """

    async def _init():
        await init_db(fastapi_app.state.db_engine)
        if with_seed_data:
            async with fastapi_app.state.db_sessionmaker() as db:
                await seed(db)

    asyncio.run(_init())
    return fastapi_app


@pytest.fixture
def app():
    """A freshly seeded app with its own isolated in-memory database."""
    fastapi_app = create_app(database_url=TEST_DATABASE_URL, with_seed_data=True)
    return _prepare(fastapi_app, with_seed_data=True)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bare_app():
    """An app with no seed data, for tests that want a clean slate."""
    fastapi_app = create_app(database_url=TEST_DATABASE_URL, with_seed_data=False)
    return _prepare(fastapi_app, with_seed_data=False)


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
