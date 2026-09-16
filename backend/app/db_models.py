"""SQLAlchemy ORM models — the durable, database-agnostic schema.

Only data that must survive a restart lives here: users, auth tokens,
sessions, and board objects (the actual diagram content). Live presence
(cursors, viewports, open connections) is deliberately NOT modeled here —
it's high-frequency, ephemeral, per-connection state that belongs in memory
(see app/routers/ws.py), not written to a database on every mouse move.
"""

from __future__ import annotations

import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Portable JSON column: plain JSON (TEXT-backed) everywhere, but JSONB on
# Postgres specifically once that dialect is in use.
PortableJSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    tokens: Mapped[list["TokenRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class TokenRecord(Base):
    __tablename__ = "tokens"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["UserRecord"] = relationship(back_populates="tokens")


class BoardSessionRecord(Base):
    __tablename__ = "board_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    objects: Mapped[list["BoardObjectRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class BoardObjectRecord(Base):
    __tablename__ = "board_objects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("board_sessions.id", ondelete="CASCADE"), index=True
    )
    # The full BoardObject payload (shape/text/draw/connector), exactly as
    # sent over the wire -- see openapi.yaml's BoardObject schema.
    data: Mapped[dict] = mapped_column(PortableJSON)

    session: Mapped["BoardSessionRecord"] = relationship(back_populates="objects")
