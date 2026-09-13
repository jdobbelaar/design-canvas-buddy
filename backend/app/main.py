"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, sessions, ws
from app.store import Store, seed


def create_app(*, with_seed_data: bool = True) -> FastAPI:
    app = FastAPI(
        title="System Design Interview — Collaboration Backend",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.store = Store()
    if with_seed_data:
        seed(app.state.store)

    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(ws.router)

    return app


app = create_app()
