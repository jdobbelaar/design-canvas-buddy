"""Demo data: one login-able user and one pre-populated board session.

Seeding is idempotent (checks before inserting) since, unlike the old
in-memory store, the database persists across restarts -- re-running this
on every startup must not fail or duplicate rows.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.db_models import BoardObjectRecord, BoardSessionRecord, UserRecord
from app.store import get_session, get_user_by_email

SEED_USER_EMAIL = "demo@example.com"
SEED_USER_PASSWORD = "password123"
SEED_SESSION_ID = "demo"

_SEED_BOARD_OBJECTS: list[dict] = [
    {
        "id": "seed-client",
        "type": "shape",
        "kind": "box",
        "x": 80,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Client",
    },
    {
        "id": "seed-lb",
        "type": "shape",
        "kind": "loadbalancer",
        "x": 360,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Load Balancer",
    },
    {
        "id": "seed-api-1",
        "type": "shape",
        "kind": "box",
        "x": 640,
        "y": 100,
        "width": 160,
        "height": 80,
        "label": "API Server 1",
    },
    {
        "id": "seed-api-2",
        "type": "shape",
        "kind": "box",
        "x": 640,
        "y": 340,
        "width": 160,
        "height": 80,
        "label": "API Server 2",
    },
    {
        "id": "seed-queue",
        "type": "shape",
        "kind": "queue",
        "x": 920,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Job Queue",
    },
    {
        "id": "seed-db",
        "type": "shape",
        "kind": "database",
        "x": 1200,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Primary DB",
    },
    {
        "id": "seed-note",
        "type": "text",
        "x": 360,
        "y": 60,
        "text": "Walk through the request path, then discuss scaling the DB.",
    },
    {
        "id": "seed-edge-client-lb",
        "type": "connector",
        "from": {"objectId": "seed-client"},
        "to": {"objectId": "seed-lb"},
        "label": "",
    },
    {
        "id": "seed-edge-lb-api1",
        "type": "connector",
        "from": {"objectId": "seed-lb"},
        "to": {"objectId": "seed-api-1"},
        "label": "",
    },
    {
        "id": "seed-edge-lb-api2",
        "type": "connector",
        "from": {"objectId": "seed-lb"},
        "to": {"objectId": "seed-api-2"},
        "label": "",
    },
    {
        "id": "seed-edge-api1-queue",
        "type": "connector",
        "from": {"objectId": "seed-api-1"},
        "to": {"objectId": "seed-queue"},
        "label": "async",
    },
    {
        "id": "seed-edge-queue-db",
        "type": "connector",
        "from": {"objectId": "seed-queue"},
        "to": {"objectId": "seed-db"},
        "label": "",
    },
]


async def seed(db: AsyncSession) -> None:
    if await get_user_by_email(db, SEED_USER_EMAIL) is None:
        db.add(
            UserRecord(
                id="u_demo",
                email=SEED_USER_EMAIL,
                name="Demo Interviewer",
                password_hash=hash_password(SEED_USER_PASSWORD),
            )
        )

    if await get_session(db, SEED_SESSION_ID) is None:
        db.add(BoardSessionRecord(id=SEED_SESSION_ID))
        for seq, obj in enumerate(_SEED_BOARD_OBJECTS, start=1):
            db.add(BoardObjectRecord(id=obj["id"], session_id=SEED_SESSION_ID, seq=seq, data=obj))

    await db.commit()
