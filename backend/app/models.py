"""Pydantic models mirroring the wire schema in ``openapi.yaml``.

Field names and JSON shapes here must stay identical to
``frontend/src/lib/collab/types.ts``, which is the frontend's source of
truth for this contract.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, EmailStr, Field

# --------------------------------------------------------------------------
# Board primitives
# --------------------------------------------------------------------------


class Point(BaseModel):
    x: float
    y: float


class Viewport(BaseModel):
    x: float
    y: float
    width: float
    height: float


ShapeKind = Literal[
    "box", "database", "queue", "cloud", "loadbalancer", "decision", "junction"
]


class ShapeObject(BaseModel):
    id: str
    groupId: str | None = None
    type: Literal["shape"] = "shape"
    kind: ShapeKind
    x: float
    y: float
    width: float
    height: float
    label: str


class TextObject(BaseModel):
    id: str
    groupId: str | None = None
    type: Literal["text"] = "text"
    x: float
    y: float
    text: str


class DrawObject(BaseModel):
    id: str
    groupId: str | None = None
    type: Literal["draw"] = "draw"
    points: list[Point]


class ConnectorEndObject(BaseModel):
    objectId: str


class ConnectorEndPoint(BaseModel):
    point: Point


ConnectorEnd = Union[ConnectorEndObject, ConnectorEndPoint]


class ConnectorObject(BaseModel):
    id: str
    groupId: str | None = None
    type: Literal["connector"] = "connector"
    from_: ConnectorEnd = Field(alias="from")
    to: ConnectorEnd
    label: str

    model_config = {"populate_by_name": True}


BoardObject = Annotated[
    Union[ShapeObject, TextObject, DrawObject, ConnectorObject],
    Field(discriminator="type"),
]

# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


class BoardOpAdd(BaseModel):
    op: Literal["add"] = "add"
    objects: list[BoardObject]


class BoardOpUpdateItem(BaseModel):
    id: str
    patch: dict


class BoardOpUpdate(BaseModel):
    op: Literal["update"] = "update"
    updates: list[BoardOpUpdateItem]


class BoardOpDelete(BaseModel):
    op: Literal["delete"] = "delete"
    ids: list[str]


BoardOp = Annotated[
    Union[BoardOpAdd, BoardOpUpdate, BoardOpDelete], Field(discriminator="op")
]

# --------------------------------------------------------------------------
# Presence / events
# --------------------------------------------------------------------------


class Participant(BaseModel):
    id: str
    color: str
    role: Literal["interviewer", "candidate"]
    cursor: Point | None = None
    viewport: Viewport | None = None


class ClientEventJoin(BaseModel):
    type: Literal["join"] = "join"
    sessionId: str
    participant: Participant


class ClientEventLeave(BaseModel):
    type: Literal["leave"] = "leave"
    sessionId: str
    participantId: str


class ClientEventOps(BaseModel):
    type: Literal["ops"] = "ops"
    sessionId: str
    from_: str = Field(alias="from")
    ops: list[BoardOp]

    model_config = {"populate_by_name": True}


class ClientEventCursor(BaseModel):
    type: Literal["cursor"] = "cursor"
    sessionId: str
    from_: str = Field(alias="from")
    cursor: Point | None = None

    model_config = {"populate_by_name": True}


class ClientEventViewport(BaseModel):
    type: Literal["viewport"] = "viewport"
    sessionId: str
    from_: str = Field(alias="from")
    viewport: Viewport

    model_config = {"populate_by_name": True}


ClientEvent = Annotated[
    Union[
        ClientEventJoin,
        ClientEventLeave,
        ClientEventOps,
        ClientEventCursor,
        ClientEventViewport,
    ],
    Field(discriminator="type"),
]


class ServerEventSnapshot(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    objects: list[BoardObject]
    participants: list[Participant]


class ServerEventOps(BaseModel):
    type: Literal["ops"] = "ops"
    from_: str = Field(alias="from")
    ops: list[BoardOp]

    model_config = {"populate_by_name": True}


class ServerEventPresence(BaseModel):
    type: Literal["presence"] = "presence"
    participants: list[Participant]


ServerEvent = Annotated[
    Union[ServerEventSnapshot, ServerEventOps, ServerEventPresence],
    Field(discriminator="type"),
]

# --------------------------------------------------------------------------
# REST: sessions
# --------------------------------------------------------------------------


class CreateSessionResponse(BaseModel):
    sessionId: str


# --------------------------------------------------------------------------
# REST: auth
# --------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserPublic


# --------------------------------------------------------------------------
# REST: health
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "unhealthy"]
    database: Literal["ok", "unreachable"]
    # The build serving this request (a git commit SHA when deployed by CI,
    # "dev" otherwise), so a deploy can check that the *new* version is live.
    version: str
