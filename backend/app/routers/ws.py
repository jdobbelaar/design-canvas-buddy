"""GET /ws/{session_id} — the real-time collaboration WebSocket.

Implements the message protocol documented under the `/ws/{sessionId}`
path in openapi.yaml (ClientEvent in, ServerEvent out). No auth required.

Board objects (the actual diagram content) are persisted to the database
via app/store.py -- every "ops" message is written straight through.
Presence (who's connected, their cursor/viewport) is deliberately kept
in-memory only (`_presence`): it's high-frequency, purely ephemeral
per-connection state, not something that belongs in a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import store
from app.models import (
    BoardObject,
    BoardOp,
    BoardOpAdd,
    BoardOpDelete,
    BoardOpUpdate,
    ClientEvent,
    ClientEventCursor,
    ClientEventJoin,
    ClientEventLeave,
    ClientEventOps,
    ClientEventViewport,
    Participant,
    ServerEvent,
    ServerEventOps,
    ServerEventPresence,
    ServerEventSnapshot,
)

router = APIRouter(tags=["collaboration"])

_client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)
_board_object_adapter: TypeAdapter[BoardObject] = TypeAdapter(BoardObject)


@dataclass
class LivePresence:
    """In-memory-only presence for one session: who's connected right now."""

    participants: dict[str, Participant] = field(default_factory=dict)


_presence: dict[str, LivePresence] = {}


def _presence_for_session(session_id: str) -> LivePresence:
    return _presence.setdefault(session_id, LivePresence())


class ConnectionManager:
    """Tracks live WebSocket connections per session, for broadcast.

    Runtime-only (not persisted state).
    """

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, WebSocket]] = {}

    def add(self, session_id: str, participant_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(session_id, {})[participant_id] = websocket

    def remove(self, session_id: str, participant_id: str) -> None:
        self._connections.get(session_id, {}).pop(participant_id, None)
        if not self._connections.get(session_id):
            self._connections.pop(session_id, None)

    async def broadcast(
        self, session_id: str, event: ServerEvent, *, exclude: str | None = None
    ) -> None:
        payload = event.model_dump(by_alias=True)
        for participant_id, ws in list(self._connections.get(session_id, {}).items()):
            if participant_id == exclude:
                continue
            await ws.send_json(payload)

    async def broadcast_presence(
        self, session_id: str, presence: LivePresence, *, exclude: str | None = None
    ) -> None:
        """Send each connected participant the presence list of *other* participants.

        Personalized per recipient (rather than one shared payload) so that
        nobody sees themselves in their own participant list — the frontend
        renders "you" separately and derives its head count as peers + 1.
        """
        for participant_id, ws in list(self._connections.get(session_id, {}).items()):
            if participant_id == exclude:
                continue
            await ws.send_json(_presence_for(presence, participant_id).model_dump(by_alias=True))

    async def send(self, websocket: WebSocket, event: ServerEvent) -> None:
        await websocket.send_json(event.model_dump(by_alias=True))


manager = ConnectionManager()


def _presence_for(presence: LivePresence, recipient_id: str) -> ServerEventPresence:
    """Presence as *recipient_id* should see it: everyone else, not themselves."""
    return ServerEventPresence(
        participants=[p for pid, p in presence.participants.items() if pid != recipient_id]
    )


async def _apply_ops(
    sessionmaker: async_sessionmaker, session_id: str, ops: list[BoardOp]
) -> None:
    async with sessionmaker() as db:
        for op in ops:
            if isinstance(op, BoardOpAdd):
                dumped = [obj.model_dump(by_alias=True) for obj in op.objects]
                await store.add_objects(db, session_id, dumped)
            elif isinstance(op, BoardOpUpdate):
                updates = [(update.id, update.patch) for update in op.updates]
                await store.update_objects(db, session_id, updates)
            elif isinstance(op, BoardOpDelete):
                await store.delete_objects(db, session_id, op.ids)


@router.websocket("/ws/{session_id}")
async def collaborate(websocket: WebSocket, session_id: str) -> None:
    sessionmaker: async_sessionmaker = websocket.app.state.db_sessionmaker
    await websocket.accept()

    async with sessionmaker() as db:
        session = await store.get_session(db, session_id)
    if session is None:
        await websocket.close(code=4404, reason="Session not found")
        return

    presence = _presence_for_session(session_id)

    participant_id: str | None = None
    try:
        raw = await websocket.receive_json()
        try:
            first_event = _client_event_adapter.validate_python(raw)
        except ValidationError:
            await websocket.close(code=4400, reason="Expected a valid join event")
            return
        if not isinstance(first_event, ClientEventJoin):
            await websocket.close(code=4400, reason="Expected join event")
            return

        participant_id = first_event.participant.id
        presence.participants[participant_id] = first_event.participant
        manager.add(session_id, participant_id, websocket)

        async with sessionmaker() as db:
            objects_data = await store.get_session_objects(db, session_id)
        objects = [_board_object_adapter.validate_python(o) for o in objects_data]
        await manager.send(
            websocket,
            ServerEventSnapshot(
                objects=objects, participants=_presence_for(presence, participant_id).participants
            ),
        )
        # The joiner already has the up-to-date list via their snapshot above;
        # only notify the others.
        await manager.broadcast_presence(session_id, presence, exclude=participant_id)

        while True:
            raw = await websocket.receive_json()
            try:
                event: ClientEvent = _client_event_adapter.validate_python(raw)
            except ValidationError:
                # Ignore malformed messages rather than dropping the connection.
                continue

            if isinstance(event, ClientEventLeave):
                await websocket.close()
                break
            elif isinstance(event, ClientEventOps):
                await _apply_ops(sessionmaker, session_id, event.ops)
                await manager.broadcast(
                    session_id,
                    ServerEventOps(from_=event.from_, ops=event.ops),
                    exclude=participant_id,
                )
            elif isinstance(event, ClientEventCursor):
                participant = presence.participants.get(event.from_)
                if participant is not None:
                    participant.cursor = event.cursor
                await manager.broadcast_presence(session_id, presence, exclude=participant_id)
            elif isinstance(event, ClientEventViewport):
                participant = presence.participants.get(event.from_)
                if participant is not None:
                    participant.viewport = event.viewport
                await manager.broadcast_presence(session_id, presence, exclude=participant_id)
            elif isinstance(event, ClientEventJoin):
                continue  # Duplicate join on an already-open connection; ignore.

    except WebSocketDisconnect:
        pass
    finally:
        if participant_id is not None:
            manager.remove(session_id, participant_id)
            presence.participants.pop(participant_id, None)
            if not presence.participants:
                _presence.pop(session_id, None)
            await manager.broadcast_presence(session_id, presence)
