"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import create_engine, database_url_from_env, init_db, make_sessionmaker
from app.routers import auth, sessions, ws
from app.seed import seed

load_dotenv()


def create_app(*, database_url: str | None = None, with_seed_data: bool = True) -> FastAPI:
    engine = create_engine(database_url or database_url_from_env())
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

    return app


app = create_app()
