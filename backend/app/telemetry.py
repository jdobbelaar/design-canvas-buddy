"""OpenTelemetry: traces and metrics for the API, WebSockets, and database.

Every span and metric carries the same three resource attributes, so telemetry
from different deployments can be told apart:

    service.name                 OTEL_SERVICE_NAME, default "design-canvas-buddy"
    deployment.environment.name  APP_ENVIRONMENT: "dev" or "production" on the
                                 servers (set by the deploy), "local" otherwise
    service.version              APP_VERSION: the image tag, e.g.
                                 20260924-010156-0615bf4 ("dev" for a local build)

Exporting is opt-in, so nothing is sent (and nothing can fail) unless configured:

    OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://collector:4318 -- traces and metrics
                                  are sent there over OTLP/HTTP; the standard
                                  OTEL_EXPORTER_OTLP_HEADERS etc. apply
    OTEL_TRACES_EXPORTER          otlp | console | none   (default: otlp if an
    OTEL_METRICS_EXPORTER         otlp | console | none    endpoint is set, else none)
    OTEL_SDK_DISABLED=true        no instrumentation at all

`console` prints to stdout, which is handy when running locally.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import FastAPI, WebSocket
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import get_current_span
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "design-canvas-buddy"
DEPLOYMENT_ENVIRONMENT = "deployment.environment.name"

# The container health check calls /health every 30 seconds; tracing it would
# bury real traffic. (A regex, matched against the request URL.)
UNTRACED_URLS = "/health$"


def _setting(name: str, default: str) -> str:
    # docker compose passes an unset variable through as an empty string.
    return os.environ.get(name, "").strip() or default


def build_resource() -> Resource:
    """Who is producing the telemetry: service, environment, and deployed version."""
    return Resource.create(
        {
            SERVICE_NAME: _setting("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME),
            DEPLOYMENT_ENVIRONMENT: _setting("APP_ENVIRONMENT", "local"),
            SERVICE_VERSION: _setting("APP_VERSION", "dev"),
        }
    )


def _exporter_kind(variable: str, endpoint_vars: Sequence[str]) -> str:
    kind = os.environ.get(variable, "").strip().lower()
    if kind:
        return kind
    return "otlp" if any(os.environ.get(v) for v in endpoint_vars) else "none"


def name_websocket_span(websocket: WebSocket) -> None:
    """Give the connection's span a useful name, e.g. "WEBSOCKET /ws/{session_id}".

    The instrumentation names it just "HTTP", because a WebSocket request has no
    method and the route is not known yet when the span starts. Inside the
    endpoint it is, so call this first thing there. A no-op when not tracing.
    """
    span = get_current_span()
    route = websocket.scope.get("route")
    if route is not None and span.is_recording():
        span.update_name(f"WEBSOCKET {route.path}")
        span.set_attribute("http.route", route.path)


@dataclass
class Telemetry:
    """The providers behind an instrumented app; shut down to flush what is buffered."""

    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None

    def shutdown(self) -> None:
        for provider in (self.tracer_provider, self.meter_provider):
            if provider is not None:
                try:
                    provider.shutdown()
                except Exception:  # telemetry must never take the app down
                    log.exception("OpenTelemetry shutdown failed")


def configure_telemetry(
    app: FastAPI,
    engine: AsyncEngine,
    *,
    span_processors: Sequence[SpanProcessor] = (),
    metric_readers: Sequence[MetricReader] = (),
) -> Telemetry:
    """Instrument `app` (HTTP and WebSocket requests) and `engine` (queries).

    `span_processors` and `metric_readers` are added to whatever the environment
    configures; the tests use them to capture telemetry in memory.
    """
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return Telemetry()

    resource = build_resource()

    tracer_provider = TracerProvider(resource=resource)
    kind = _exporter_kind(
        "OTEL_TRACES_EXPORTER",
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
    )
    if kind == "otlp":
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    elif kind == "console":
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    for processor in span_processors:
        tracer_provider.add_span_processor(processor)

    readers: list[MetricReader] = list(metric_readers)
    kind = _exporter_kind(
        "OTEL_METRICS_EXPORTER",
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
    )
    if kind == "otlp":
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
    elif kind == "console":
        readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=UNTRACED_URLS,
        # A WebSocket connection lasts as long as an interview; a span for every
        # message received and sent would be noise.
        exclude_spans=["receive", "send"],
    )

    # The SQLAlchemy instrumentor is process-wide and instruments once, which is
    # right for the one engine the running server has.
    instrumentor = SQLAlchemyInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        log.debug("SQLAlchemy is already instrumented; leaving it as it is")
    else:
        instrumentor.instrument(
            engine=engine.sync_engine,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
        )

    return Telemetry(tracer_provider=tracer_provider, meter_provider=meter_provider)
