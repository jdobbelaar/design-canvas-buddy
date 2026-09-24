"""OpenTelemetry: what is captured, and that it says who produced it."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.main import create_app
from app.telemetry import DEFAULT_SERVICE_NAME, _exporter_kind, build_resource

ENV_VARS = (
    "OTEL_SERVICE_NAME",
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "APP_ENVIRONMENT",
    "APP_VERSION",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ---- the resource: service, environment, version ---------------------------


def test_resource_defaults_for_a_local_run():
    attrs = build_resource().attributes
    assert attrs["service.name"] == DEFAULT_SERVICE_NAME == "design-canvas-buddy"
    assert attrs["deployment.environment.name"] == "local"
    assert attrs["service.version"] == "dev"


def test_resource_carries_the_deployed_environment_and_version(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_VERSION", "20260924-010156-0615bf4")
    attrs = build_resource().attributes
    assert attrs["deployment.environment.name"] == "production"
    assert attrs["service.version"] == "20260924-010156-0615bf4"


def test_the_service_name_can_be_overridden(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "canvas-api")
    assert build_resource().attributes["service.name"] == "canvas-api"


@pytest.mark.parametrize("value", ["", "  "])
def test_blank_values_fall_back_to_the_defaults(monkeypatch, value):
    # docker compose passes an unset variable through as an empty string.
    monkeypatch.setenv("APP_ENVIRONMENT", value)
    monkeypatch.setenv("APP_VERSION", value)
    attrs = build_resource().attributes
    assert attrs["deployment.environment.name"] == "local"
    assert attrs["service.version"] == "dev"


# ---- which exporters are switched on ---------------------------------------


def test_nothing_is_exported_unless_configured():
    assert _exporter_kind("OTEL_TRACES_EXPORTER", ("OTEL_EXPORTER_OTLP_ENDPOINT",)) == "none"


def test_an_endpoint_switches_on_otlp(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert _exporter_kind("OTEL_TRACES_EXPORTER", ("OTEL_EXPORTER_OTLP_ENDPOINT",)) == "otlp"


def test_an_explicit_exporter_wins_over_the_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    assert _exporter_kind("OTEL_TRACES_EXPORTER", ("OTEL_EXPORTER_OTLP_ENDPOINT",)) == "none"


# ---- what an instrumented app records --------------------------------------


def test_a_request_produces_a_server_span_tagged_with_service_environment_and_version(telemetry):
    assert telemetry.post("/sessions").status_code == 201

    server = [s for s in telemetry.spans.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert [s.attributes["http.route"] for s in server] == ["/sessions"]
    assert dict(server[0].resource.attributes).items() >= {
        "service.name": "design-canvas-buddy",
        "deployment.environment.name": "test-env",
        "service.version": "20260101-000000-abc1234",
    }.items()


def test_database_queries_are_child_spans_of_the_request(telemetry):
    telemetry.post("/sessions")

    spans = telemetry.spans.get_finished_spans()
    server = next(s for s in spans if s.kind == SpanKind.SERVER)
    queries = [s for s in spans if s.kind == SpanKind.CLIENT]
    assert queries, "expected the session insert to be traced"
    assert {q.context.trace_id for q in queries} == {server.context.trace_id}
    assert all(q.resource.attributes["service.version"] == "20260101-000000-abc1234" for q in queries)


def test_the_health_check_is_not_traced_at_all(telemetry):
    # Not the request, and not its "SELECT 1" either.
    assert telemetry.get("/health").json()["status"] == "ok"
    assert telemetry.spans.get_finished_spans() == ()


def test_metrics_carry_the_same_resource(telemetry):
    telemetry.post("/sessions")

    data = telemetry.metrics.get_metrics_data()
    resource_metrics = data.resource_metrics
    assert resource_metrics
    assert dict(resource_metrics[0].resource.attributes).items() >= {
        "service.name": "design-canvas-buddy",
        "deployment.environment.name": "test-env",
        "service.version": "20260101-000000-abc1234",
    }.items()
    names = {
        m.name for rm in resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    }
    assert any(name.startswith("http.server") for name in names), names


def test_a_websocket_connection_is_one_named_span_not_one_per_message(telemetry):
    session_id = telemetry.post("/sessions").json()["sessionId"]
    telemetry.spans.clear()

    with telemetry.websocket_connect(f"/ws/{session_id}") as ws:
        ws.send_json(
            {
                "type": "join",
                "sessionId": session_id,
                "participant": {"id": "p1", "color": "#fff", "role": "interviewer"},
            }
        )
        assert ws.receive_json()["type"] == "snapshot"

    spans = telemetry.spans.get_finished_spans()
    server = [s for s in spans if s.kind == SpanKind.SERVER]
    assert [s.name for s in server] == ["WEBSOCKET /ws/{session_id}"]
    assert server[0].attributes["http.route"] == "/ws/{session_id}"
    assert server[0].resource.attributes["deployment.environment.name"] == "test-env"
    # No per-message "receive"/"send" spans; only the connection and its queries.
    assert {s.kind for s in spans} == {SpanKind.SERVER, SpanKind.CLIENT}


def test_logs_carry_the_same_resource(telemetry):
    log = logging.getLogger("uvicorn.error")
    log.info("something happened")

    records = telemetry.logs.get_finished_logs()
    assert [r.log_record.body for r in records] == ["something happened"]
    assert dict(records[0].resource.attributes).items() >= {
        "service.name": "design-canvas-buddy",
        "deployment.environment.name": "test-env",
        "service.version": "20260101-000000-abc1234",
    }.items()


def test_access_logs_are_exported_except_for_the_health_check(telemetry):
    access = logging.getLogger("uvicorn.access")
    access.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", "/health", "1.1", 200)
    access.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "POST", "/sessions", "1.1", 201)

    bodies = [r.log_record.body for r in telemetry.logs.get_finished_logs()]
    assert len(bodies) == 1 and "/sessions" in bodies[0]


def test_log_handlers_are_removed_when_the_app_shuts_down():
    def handler_count():
        return sum(len(logging.getLogger(n).handlers) for n in ("", "uvicorn", "uvicorn.access"))

    before = handler_count()
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        with_seed_data=False,
        telemetry_kwargs={"log_processors": [SimpleLogRecordProcessor(InMemoryLogRecordExporter())]},
    )
    with TestClient(app):
        assert handler_count() > before
    assert handler_count() == before


def test_sdk_disabled_leaves_the_app_uninstrumented(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    spans = InMemorySpanExporter()
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        with_seed_data=False,
        telemetry_kwargs={"span_processors": [SimpleSpanProcessor(spans)]},
    )
    with TestClient(app) as client:
        assert client.post("/sessions").status_code == 201
    assert spans.get_finished_spans() == ()
