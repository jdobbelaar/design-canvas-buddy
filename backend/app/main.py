"""FastAPI application factory."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import create_engine, database_url_from_env, init_db, make_sessionmaker
from app.routers import auth, sessions, ws
from app.seed import seed
from app.spa import mount_frontend

load_dotenv()


def create_app(
    *,
    database_url: str | None = None,
    with_seed_data: bool = True,
    frontend_dir: str | None = None,
    engine_kwargs: dict[str, object] | None = None,
) -> FastAPI:
    engine = create_engine(database_url or database_url_from_env(), **(engine_kwargs or {}))
    sessionmaker = make_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await init_db(engine)
        if with_seed_data:
            async with sessionmaker() as db:
                await seed(db)
        yield
        await engine.dispose()

    app = FastAPI(
        title="System Design Interview — Collaboration Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.db_engine = engine
    app.state.db_sessionmaker = sessionmaker

    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(ws.router)

    # Last: this mounts a catch-all at "/", so the API routes above must win.
    frontend_dir = frontend_dir or os.environ.get("FRONTEND_DIR")
    if frontend_dir:
        mount_frontend(app, frontend_dir)

    return app


app = create_app()
