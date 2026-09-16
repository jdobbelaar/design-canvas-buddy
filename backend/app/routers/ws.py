"""GET /ws/{session_id} — the real-time collaboration WebSocket.

Implements the message protocol documented under the `/ws/{sessionId}`
path in openapi.yaml (ClientEvent in, ServerEvent out). No auth required.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

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
    ServerEvent,
    ServerEventOps,
    ServerEventPresence,
    ServerEventSnapshot,
)
from app.store import SessionState, Store

router = APIRouter(tags=["collaboration"])

_client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)
_board_object_adapter: TypeAdapter[BoardObject] = TypeAdapter(BoardObject)


class ConnectionManager:
    """Tracks live WebSocket connections per session, for broadcast.

    Runtime-only (not persisted state), so it lives outside Store.
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
        self, session_id: str, session: SessionState, *, exclude: str | None = None
    ) -> None:
        """Send each connected participant the presence list of *other* participants.

        Personalized per recipient (rather than one shared payload) so that
        nobody sees themselves in their own participant list — the frontend
        renders "you" separately and derives its head count as peers + 1.
        """
        for participant_id, ws in list(self._connections.get(session_id, {}).items()):
            if participant_id == exclude:
                continue
            await ws.send_json(_presence_for(session, participant_id).model_dump(by_alias=True))

    async def send(self, websocket: WebSocket, event: ServerEvent) -> None:
        await websocket.send_json(event.model_dump(by_alias=True))


manager = ConnectionManager()


def _apply_ops(session: SessionState, ops: list[BoardOp]) -> None:
    for op in ops:
        if isinstance(op, BoardOpAdd):
            for obj in op.objects:
                dumped = obj.model_dump(by_alias=True)
                session.objects[dumped["id"]] = dumped
        elif isinstance(op, BoardOpUpdate):
            for update in op.updates:
                existing = session.objects.get(update.id)
                if existing is None:
                    continue
                session.objects[update.id] = {**existing, **update.patch}
        elif isinstance(op, BoardOpDelete):
            for obj_id in op.ids:
                session.objects.pop(obj_id, None)


def _presence_for(session: SessionState, recipient_id: str) -> ServerEventPresence:
    """Presence as *recipient_id* should see it: everyone else, not themselves."""
    return ServerEventPresence(
        participants=[p for pid, p in session.participants.items() if pid != recipient_id]
    )


@router.websocket("/ws/{session_id}")
async def collaborate(websocket: WebSocket, session_id: str) -> None:
    store: Store = websocket.app.state.store
    await websocket.accept()

    session = store.get_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="Session not found")
        return

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
        session.participants[participant_id] = first_event.participant
        manager.add(session_id, participant_id, websocket)

        objects = [_board_object_adapter.validate_python(o) for o in session.objects.values()]
        await manager.send(
            websocket,
            ServerEventSnapshot(
                objects=objects,
                participants=[p for pid, p in session.participants.items() if pid != participant_id],
            ),
        )
        # The joiner already has the up-to-date list via their snapshot above;
        # only notify the others.
        await manager.broadcast_presence(session_id, session, exclude=participant_id)

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
                _apply_ops(session, event.ops)
                await manager.broadcast(
                    session_id,
                    ServerEventOps(from_=event.from_, ops=event.ops),
                    exclude=participant_id,
                )
            elif isinstance(event, ClientEventCursor):
                participant = session.participants.get(event.from_)
                if participant is not None:
                    participant.cursor = event.cursor
                await manager.broadcast_presence(session_id, session, exclude=participant_id)
            elif isinstance(event, ClientEventViewport):
                participant = session.participants.get(event.from_)
                if participant is not None:
                    participant.viewport = event.viewport
                await manager.broadcast_presence(session_id, session, exclude=participant_id)
            elif isinstance(event, ClientEventJoin):
                continue  # Duplicate join on an already-open connection; ignore.

    except WebSocketDisconnect:
        pass
    finally:
        if participant_id is not None:
            manager.remove(session_id, participant_id)
            session.participants.pop(participant_id, None)
            await manager.broadcast_presence(session_id, session)
