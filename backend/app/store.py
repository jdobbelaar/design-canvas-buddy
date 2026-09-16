"""Data-access layer: async CRUD functions over the SQLAlchemy models.

Routers call these instead of talking to SQLAlchemy directly, so the
database layer stays swappable (SQLite today, Postgres later) behind one
seam. Each function takes the request's `AsyncSession` (see app/db.py's
`get_db` dependency) as its first argument.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import BoardObjectRecord, BoardSessionRecord, TokenRecord, UserRecord


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)}"


# -- users ---------------------------------------------------------------


async def get_user_by_email(db: AsyncSession, email: str) -> UserRecord | None:
    result = await db.execute(select(UserRecord).where(UserRecord.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: str) -> UserRecord | None:
    return await db.get(UserRecord, user_id)


async def create_user(
    db: AsyncSession, *, email: str, name: str | None, password_hash: str
) -> UserRecord:
    user = UserRecord(id=_new_id("u"), email=email.lower(), name=name, password_hash=password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# -- tokens ----------------------------------------------------------------


async def issue_token(db: AsyncSession, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.add(TokenRecord(token=token, user_id=user_id))
    await db.commit()
    return token


async def get_user_by_token(db: AsyncSession, token: str) -> UserRecord | None:
    token_record = await db.get(TokenRecord, token)
    if token_record is None:
        return None
    return await get_user(db, token_record.user_id)


# -- sessions ----------------------------------------------------------------


async def create_session(db: AsyncSession) -> BoardSessionRecord:
    session = BoardSessionRecord(id=_new_id("s"))
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> BoardSessionRecord | None:
    return await db.get(BoardSessionRecord, session_id)


async def get_session_objects(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(BoardObjectRecord).where(BoardObjectRecord.session_id == session_id)
    )
    return [row.data for row in result.scalars()]


async def add_objects(db: AsyncSession, session_id: str, objects: list[dict]) -> None:
    for obj in objects:
        await db.merge(BoardObjectRecord(id=obj["id"], session_id=session_id, data=obj))
    await db.commit()


async def update_objects(
    db: AsyncSession, session_id: str, updates: list[tuple[str, dict]]
) -> None:
    for object_id, patch in updates:
        record = await db.get(BoardObjectRecord, object_id)
        if record is None or record.session_id != session_id:
            continue
        record.data = {**record.data, **patch}
    await db.commit()


async def delete_objects(db: AsyncSession, session_id: str, ids: list[str]) -> None:
    for object_id in ids:
        record = await db.get(BoardObjectRecord, object_id)
        if record is not None and record.session_id == session_id:
            await db.delete(record)
    await db.commit()
