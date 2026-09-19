"""A real WebSocket participant, speaking the wire protocol from openapi.yaml."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from websockets.sync.client import connect

from .conftest import Stack


def unique(name: str) -> str:
    """An object id no other test will use.

    Object ids are the database's *global* primary key -- not scoped to a
    session -- so tests sharing one stack must not reuse them.
    """
    return f"{name}-{uuid.uuid4().hex[:8]}"


def shape(object_id: str, label: str = "", *, x: int = 0, y: int = 0, padding: str = "") -> dict:
    return {
        "id": object_id, "type": "shape", "kind": "box",
        "x": x, "y": y, "width": 100, "height": 60,
        "label": label + padding,
    }


class Participant:
    def __init__(self, stack: Stack, session_id: str, participant_id: str, role: str = "candidate"):
        self.session_id = session_id
        self.id = participant_id
        self.role = role
        # max_queue=None: a test client that is not reading yet must not push back on
        # the server (and stall it) while the other side sends a burst of edits.
        # websockets wants connect() used as a context manager; we hold it open
        # for the participant's lifetime and exit it in close().
        self._connection = connect(
            stack.ws_url(session_id), open_timeout=10, close_timeout=2, max_queue=None)
        self.ws = self._connection.__enter__()
        self._closed = False

    def __enter__(self) -> Participant:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.__exit__(None, None, None)

    # -- sending ---------------------------------------------------------

    def send(self, event: dict[str, Any]) -> None:
        self.ws.send(json.dumps(event))

    def join(self) -> dict:
        """Join the session and return the snapshot the server answers with."""
        self.send({
            "type": "join",
            "sessionId": self.session_id,
            "participant": {"id": self.id, "color": "#2f6df6", "role": self.role},
        })
        return self.recv_until("snapshot")

    def ops(self, *ops: dict) -> None:
        self.send({"type": "ops", "sessionId": self.session_id, "from": self.id, "ops": list(ops)})

    def add(self, *objects: dict) -> None:
        self.ops({"op": "add", "objects": list(objects)})

    def update(self, object_id: str, **patch: Any) -> None:
        self.ops({"op": "update", "updates": [{"id": object_id, "patch": patch}]})

    def delete(self, *ids: str) -> None:
        self.ops({"op": "delete", "ids": list(ids)})

    def cursor(self, x: float, y: float) -> None:
        self.send({"type": "cursor", "sessionId": self.session_id, "from": self.id,
                   "cursor": {"x": x, "y": y}})

    def viewport(self, x: float, y: float, width: float, height: float) -> None:
        self.send({"type": "viewport", "sessionId": self.session_id, "from": self.id,
                   "viewport": {"x": x, "y": y, "width": width, "height": height}})

    def leave(self) -> None:
        self.send({"type": "leave", "sessionId": self.session_id, "participantId": self.id})

    # -- receiving -------------------------------------------------------

    def recv(self, timeout: float = 5) -> dict:
        return json.loads(self.ws.recv(timeout=timeout))

    def recv_until(self, kind: str, timeout: float = 10) -> dict:
        """Read messages until one of type `kind` arrives, discarding the rest."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no {kind!r} message within {timeout}s")
            message = self.recv(timeout=remaining)
            if message["type"] == kind:
                return message

    def recv_ops_containing(self, predicate, timeout: float = 30) -> dict:
        """Read `ops` messages until one satisfies `predicate` (a sync barrier:
        the server applies and persists ops in order, so once a later one is
        relayed, every earlier one is already in the database)."""
        deadline = time.monotonic() + timeout
        while True:
            message = self.recv_until("ops", timeout=max(deadline - time.monotonic(), 0.1))
            if predicate(message):
                return message


def snapshot_ids(stack: Stack, session_id: str, who: str = "reader") -> list[str]:
    """Object ids in the order a fresh participant is shown them."""
    with Participant(stack, session_id, who) as p:
        return [o["id"] for o in p.join()["objects"]]


def drawn_and_synced(stack: Stack, session_id: str, draw) -> None:
    """Run `draw(alice)` and return only once every op is in the database.

    Ops are applied and persisted in order, then relayed. So once Bob has been
    sent a final marker edit, everything Alice sent before it is committed.
    """
    marker = unique("sync-marker")
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")
        draw(alice)
        alice.add(shape(marker))
        bob.recv_ops_containing(
            lambda m: any(o["id"] == marker for op in m["ops"] for o in op.get("objects", [])))
