"""Database engine and session setup.

Database-agnostic: everything here is driven by a single `DATABASE_URL`
connection string, e.g. ``sqlite+aiosqlite:///./app.db`` or
``postgresql+asyncpg://user:pass@host:5432/dbname``. Dialect-specific
tuning (SQLite's WAL mode and thread-safety connect args, Postgres
connection health checks) only applies when the URL's dialect matches;
nothing else in this module or in db_models.py assumes one backend.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db_models import Base

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./app.db"

# The async driver to use when a URL names only the database ("postgres://").
_ASYNC_DRIVERS = {
    "sqlite": "sqlite+aiosqlite",
    "postgres": "postgresql+asyncpg",
    "postgresql": "postgresql+asyncpg",
}


def database_url_from_env() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def normalize_database_url(database_url: str | URL) -> URL:
    """Turn the URL forms people actually have into one the async engine accepts.

    - ``postgres://`` / ``postgresql://`` / ``sqlite://`` (what Heroku, Neon,
      RDS and most docs hand out) name no driver, so SQLAlchemy would pick a
      *synchronous* one and refuse to run under asyncio. Select the async
      driver instead. An explicit ``+driver`` is always respected.
    - libpq-style ``?sslmode=require`` isn't understood by asyncpg, which
      calls the same setting ``ssl`` (with the same values).
    """
    url = make_url(database_url)
    async_driver = _ASYNC_DRIVERS.get(url.drivername)
    if async_driver:
        url = url.set(drivername=async_driver)
    if url.drivername.endswith("+asyncpg") and "sslmode" in url.query:
        query = dict(url.query)
        query["ssl"] = query.pop("sslmode")  # type: ignore[assignment]
        url = url.set(query=query)
    return url


def create_engine(database_url: str | URL, **engine_kwargs: object) -> AsyncEngine:
    """`engine_kwargs` pass straight through to `create_async_engine` (tests use
    this to pick a pool class)."""
    url = normalize_database_url(database_url)
    backend = url.get_backend_name()
    is_sqlite = backend == "sqlite"
    is_memory = is_sqlite and (url.database in (None, "", ":memory:"))

    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {}
    if is_sqlite:
        # aiosqlite serializes access onto one thread per connection; this
        # just relaxes sqlite3's own same-thread check for that thread.
        connect_args["check_same_thread"] = False
    else:
        # Server databases drop idle connections (restarts, failovers, proxy
        # timeouts). Without this, the first request after that gets a dead
        # pooled connection and fails instead of transparently reconnecting.
        kwargs["pool_pre_ping"] = True
    if is_memory:
        # An in-memory SQLite DB is private to the connection that created
        # it. Force a single shared connection so every request sees the
        # same database (used by tests).
        kwargs["poolclass"] = StaticPool
    kwargs.update(engine_kwargs)

    engine = create_async_engine(url, connect_args=connect_args, **kwargs)

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            # WAL lets readers proceed while a write is in flight -- this
            # app writes board-object ops frequently during drags/resizes.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# Columns added after a table first shipped. `create_all` only creates missing
# *tables*, so a database from an earlier version needs these added by hand.
# NOT NULL DEFAULT is valid ALTER TABLE syntax on both SQLite and Postgres.
# Real migrations (Alembic) are the right tool once there's a second change.
_ADDED_COLUMNS = [("board_objects", "seq", "INTEGER NOT NULL DEFAULT 0")]


def _add_missing_columns(conn) -> None:
    inspector = inspect(conn)
    for table, column, ddl in _ADDED_COLUMNS:
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session
