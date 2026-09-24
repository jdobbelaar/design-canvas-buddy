"""The application's own metrics: rooms, participants, and canvas elements."""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app import store
from app.main import create_app
from app.models import BoardOpAdd
from app.routers.ws import _apply_ops
from app.telemetry import AppMetrics


def _points(client, name):
    """(resource attributes, data points) of the metric `name`, or ({}, [])."""
    for rm in client.metrics.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    return dict(rm.resource.attributes), list(metric.data.data_points)
    return {}, []


def _total(client, name, **attributes):
    _, points = _points(client, name)
    return sum(
        p.value
        for p in points
        if all(dict(p.attributes).get(k) == v for k, v in attributes.items())
    )


def _shape(object_id, kind="database"):
    return {
        "id": object_id, "type": "shape", "kind": kind, "x": 0, "y": 0,
        "width": 10, "height": 10, "label": "x",
    }


def _join(ws, session_id, participant_id="p1"):
    ws.send_json(
        {
            "type": "join",
            "sessionId": session_id,
            "participant": {"id": participant_id, "color": "#fff", "role": "interviewer"},
        }
    )
    assert ws.receive_json()["type"] == "snapshot"


def _add(ws, session_id, *objects):
    ws.send_json(
        {"type": "ops", "sessionId": session_id, "from": "p1",
         "ops": [{"op": "add", "objects": list(objects)}]}
    )


def _ops(ws, session_id, ops):
    ws.send_json({"type": "ops", "sessionId": session_id, "from": "p1", "ops": ops})


@contextlib.contextmanager
def _room(client, session_id):
    """Two participants in a room. Yields (p1, settle): p1 is the first
    participant's socket, and `settle()` returns once the server has handled
    everything p1 sent so far. The server handles a connection's messages in order and
    broadcasts each applied ops event to the others, so a harmless no-op update
    that p2 sees arrive proves the earlier messages were processed."""
    with client.websocket_connect(f"/ws/{session_id}") as p1:
        _join(p1, session_id, "p1")
        with client.websocket_connect(f"/ws/{session_id}") as p2:
            _join(p2, session_id, "p2")

            def settle():
                _ops(p1, session_id, [{"op": "update", "updates": [{"id": "barrier", "patch": {}}]}])
                while True:
                    event = p2.receive_json()
                    ops = event.get("ops") or []
                    if event["type"] == "ops" and ops and ops[0]["op"] == "update":
                        return

            yield p1, settle


def test_rooms_created_are_counted_with_environment_and_version(telemetry):
    telemetry.post("/sessions")
    telemetry.post("/sessions")

    resource, points = _points(telemetry, "interview.rooms.created")
    assert sum(p.value for p in points) == 2
    assert resource["deployment.environment.name"] == "test-env"
    assert resource["service.version"] == "20260101-000000-abc1234"
    assert resource["service.name"] == "design-canvas-buddy"


def test_counters_start_at_zero_so_the_first_event_is_visible_to_rate(telemetry):
    # Prometheus can only see an increase between two samples; a series that first
    # appears at 1 would hide that event. So every series exists, at 0, from the start.
    assert _total(telemetry, "interview.rooms.created") == 0
    _, rooms = _points(telemetry, "interview.rooms.created")
    assert len(rooms) == 1

    _, failures = _points(telemetry, "canvas.element.creation.failures")
    assert {dict(p.attributes)["reason"] for p in failures} == {"invalid", "id_conflict", "error"}
    assert {p.value for p in failures} == {0}

    _, elements = _points(telemetry, "canvas.elements.created")
    kinds = {dict(p.attributes)["element.type"] for p in elements}
    assert {"database", "loadbalancer", "box", "text", "connector", "draw"} <= kinds
    assert {p.value for p in elements} == {0}


def test_active_participants_follow_who_is_connected(telemetry):
    session_id = telemetry.post("/sessions").json()["sessionId"]
    assert _total(telemetry, "interview.participants.active") == 0

    with telemetry.websocket_connect(f"/ws/{session_id}") as one:
        _join(one, session_id, "p1")
        with telemetry.websocket_connect(f"/ws/{session_id}") as two:
            _join(two, session_id, "p2")
            assert _total(telemetry, "interview.participants.active") == 2
        one.receive_json()  # the presence update sent once p2 has gone
        assert _total(telemetry, "interview.participants.active") == 1
    assert _total(telemetry, "interview.participants.active") == 0


def test_the_participants_gauge_carries_environment_and_version(telemetry):
    resource, _ = _points(telemetry, "interview.participants.active")
    assert resource["deployment.environment.name"] == "test-env"
    assert resource["service.version"] == "20260101-000000-abc1234"


def test_new_elements_are_counted_by_kind_and_re_adds_are_not(telemetry):
    session_id = telemetry.post("/sessions").json()["sessionId"]

    with _room(telemetry, session_id) as (p1, settle):
        _add(p1, session_id, _shape("a", "database"), _shape("b", "database"), _shape("c", "queue"))
        _add(p1, session_id, _shape("a", "database"))  # already there: replaced, not created
        _add(p1, session_id, {"id": "t", "type": "text", "x": 0, "y": 0, "text": "hi"})
        settle()

    assert _total(telemetry, "canvas.elements.created") == 4  # a, b, c, t
    assert _total(telemetry, "canvas.elements.created", **{"element.type": "database"}) == 2
    assert _total(telemetry, "canvas.elements.created", **{"element.type": "queue"}) == 1
    assert _total(telemetry, "canvas.elements.created", **{"element.type": "text"}) == 1
    assert _total(telemetry, "canvas.element.creation.failures") == 0


def test_an_element_whose_id_belongs_to_another_room_is_a_failure(telemetry):
    first = telemetry.post("/sessions").json()["sessionId"]
    second = telemetry.post("/sessions").json()["sessionId"]

    with _room(telemetry, first) as (p1, settle):
        _add(p1, first, _shape("shared-id"))
        settle()
    with _room(telemetry, second) as (p1, settle):
        _add(p1, second, _shape("shared-id"), _shape("mine"))
        settle()

    assert _total(telemetry, "canvas.elements.created") == 2  # shared-id in first, mine
    assert _total(telemetry, "canvas.element.creation.failures", reason="id_conflict") == 1


def test_an_add_that_fails_validation_is_a_failure(telemetry):
    session_id = telemetry.post("/sessions").json()["sessionId"]

    with _room(telemetry, session_id) as (p1, settle):
        broken = {"id": "x", "type": "shape", "kind": "not-a-real-kind"}
        _add(p1, session_id, broken, broken)
        _ops(p1, session_id, [{"op": "nope"}])  # not an add: not a failed creation
        p1.send_json(["not", "an", "event"])  # not even an object: must not crash
        settle()

    assert _total(telemetry, "canvas.element.creation.failures", reason="invalid") == 2
    assert _total(telemetry, "canvas.elements.created") == 0


def test_a_server_error_while_adding_is_a_failure(monkeypatch):
    reader = InMemoryMetricReader()
    metrics = AppMetrics(MeterProvider(metric_readers=[reader]).get_meter("t"), lambda: 0)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(store, "add_objects", boom)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    op = BoardOpAdd(objects=[_shape("a"), _shape("b")])
    with pytest.raises(RuntimeError):
        asyncio.run(_apply_ops(FakeSession, "room", [op], metrics))

    points = [
        p
        for rm in reader.get_metrics_data().resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == "canvas.element.creation.failures"
        for p in m.data.data_points
    ]
    # Every series starts at zero; only the one that happened has moved.
    assert [(dict(p.attributes), p.value) for p in points if p.value] == [({"reason": "error"}, 2)]


def test_everything_still_works_with_telemetry_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    app = create_app(database_url="sqlite+aiosqlite:///:memory:", with_seed_data=False)
    with TestClient(app) as client:
        session_id = client.post("/sessions").json()["sessionId"]
        with _room(client, session_id) as (p1, settle):
            _add(p1, session_id, _shape("a"))
            settle()
