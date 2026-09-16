"""Database engine and session setup.

Database-agnostic: everything here is driven by a single `DATABASE_URL`
connection string (SQLAlchemy async dialect + driver, e.g.
``sqlite+aiosqlite:///./app.db`` or, later, ``postgresql+asyncpg://...``).
SQLite-specific tuning (WAL mode, thread-safety connect args) only kicks in
when the URL's dialect is actually SQLite; nothing else in this module or
in db_models.py assumes SQLite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db_models import Base

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./app.db"


def database_url_from_env() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine(database_url: str) -> AsyncEngine:
    url = make_url(database_url)
    is_sqlite = url.get_backend_name() == "sqlite"
    is_memory = is_sqlite and (url.database in (None, "", ":memory:"))

    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {}
    if is_sqlite:
        # aiosqlite serializes access onto one thread per connection; this
        # just relaxes sqlite3's own same-thread check for that thread.
        connect_args["check_same_thread"] = False
    if is_memory:
        # An in-memory SQLite DB is private to the connection that created
        # it. Force a single shared connection so every request sees the
        # same database (used by tests).
        kwargs["poolclass"] = StaticPool

    engine = create_async_engine(database_url, connect_args=connect_args, **kwargs)

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


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session
