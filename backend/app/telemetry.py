"""OpenTelemetry: traces, metrics, and logs for the API, WebSockets, and database.

Every span and metric carries the same three resource attributes, so telemetry
from different deployments can be told apart:

    service.name                 OTEL_SERVICE_NAME, default "design-canvas-buddy"
    deployment.environment.name  APP_ENVIRONMENT: "dev" or "production" on the
                                 servers (set by the deploy), "local" otherwise
    service.version              APP_VERSION: the image tag, e.g.
                                 20260924-010156-0615bf4 ("dev" for a local build)

Exporting is opt-in, so nothing is sent (and nothing can fail) unless configured:

    OTEL_EXPORTER_OTLP_ENDPOINT   e.g. http://collector:4318 -- traces, metrics,
                                  and logs are sent there over OTLP/HTTP; the
                                  standard OTEL_EXPORTER_OTLP_HEADERS etc. apply
    OTEL_TRACES_EXPORTER          otlp | console | none   (default: otlp if an
    OTEL_METRICS_EXPORTER         otlp | console | none    endpoint is set, else none)
    OTEL_LOGS_EXPORTER            otlp | console | none
    OTEL_SDK_DISABLED=true        no instrumentation at all

`console` prints to stdout, which is handy when running locally. Logs are the
records of the `uvicorn` loggers (including the access log) and the root logger.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import get_args
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.metrics import Counter, Meter, NoOpMeterProvider, Observation
from opentelemetry.sdk._logs import LoggerProvider, LogRecordProcessor
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
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

from app.models import ShapeKind

log = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "design-canvas-buddy"
DEPLOYMENT_ENVIRONMENT = "deployment.environment.name"

# The container health check calls /health every 30 seconds; tracing it would
# bury real traffic. (A regex, matched against the request URL.)
UNTRACED_URLS = "/health$"

# Loggers whose records are exported: the root logger, plus uvicorn's (its access
# log in particular). uvicorn's usually do not propagate to the root logger, so
# they need the handler themselves -- but only where a record would not already
# reach it, or every line would be exported twice.
LOGGERS = ("", "uvicorn", "uvicorn.access")


def _reaches(logger: logging.Logger, handler: logging.Handler) -> bool:
    """Would a record logged to `logger` already be handled by `handler`?"""
    current: logging.Logger | None = logger
    while current is not None:
        if handler in current.handlers:
            return True
        current = current.parent if current.propagate else None
    return False


class DropHealthChecks(logging.Filter):
    """Keeps the health check's access-log line (every 30 s) out of the exported logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        is_health_check = (
            record.name == "uvicorn.access"
            and isinstance(args, tuple)
            and len(args) >= 3
            and args[2] == "/health"
        )
        return not is_health_check


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


# The values of the `element.type` and `reason` attributes, spelled out so every
# series can be started at zero (see AppMetrics).
ELEMENT_TYPES = (*get_args(ShapeKind), "text", "draw", "connector")
FAILURE_REASONS = ("invalid", "id_conflict", "error")


class AppMetrics:
    """What the application itself counts, as opposed to what the framework reports.

    All of them carry the resource attributes (service, environment, version) like
    every other signal, so any of them can be filtered by environment or version.

    `interview.rooms.created`             interview rooms (sessions) created
    `interview.participants.active`       participants connected right now
    `canvas.elements.created`             elements newly added to a canvas, by
                                          `element.type` (a shape's kind, e.g.
                                          database, else text/draw/connector); a
                                          re-add of an element the room already has
                                          is not a creation
    `canvas.element.creation.failures`    elements that could not be added, by
                                          `reason`: invalid (the message did not
                                          validate), id_conflict (the id belongs to
                                          another room), error (the server failed)
    """

    def __init__(self, meter: Meter, active_participants: Callable[[], int]) -> None:
        self.rooms_created: Counter = meter.create_counter(
            "interview.rooms.created",
            unit="{room}",
            description="Interview rooms created",
        )
        # Observed when metrics are collected rather than incremented and
        # decremented as people come and go, so it cannot drift from the truth.
        meter.create_observable_up_down_counter(
            "interview.participants.active",
            callbacks=[lambda _options: [Observation(active_participants())]],
            unit="{participant}",
            description="Participants connected to interview rooms right now",
        )
        self.elements_created: Counter = meter.create_counter(
            "canvas.elements.created",
            unit="{element}",
            description="Canvas elements created",
        )
        self.element_creation_failures: Counter = meter.create_counter(
            "canvas.element.creation.failures",
            unit="{element}",
            description="Canvas elements that could not be created",
        )

        # A counter's series only exists once something has been added to it, so
        # the first event ever would arrive as a series that starts at 1 -- and
        # Prometheus, having no earlier sample to compare with, would see no
        # increase and rate() would miss it. Start every series at 0 instead.
        self.rooms_created.add(0)
        for element_type in ELEMENT_TYPES:
            self.elements_created.add(0, {"element.type": element_type})
        for reason in FAILURE_REASONS:
            self.element_creation_failures.add(0, {"reason": reason})

    @classmethod
    def noop(cls) -> AppMetrics:
        """Instruments that record nothing, for when telemetry is disabled."""
        return cls(NoOpMeterProvider().get_meter(DEFAULT_SERVICE_NAME), lambda: 0)


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
    logger_provider: LoggerProvider | None = None
    log_handler: logging.Handler | None = None
    metrics: AppMetrics = field(default_factory=AppMetrics.noop)

    def shutdown(self) -> None:
        if self.log_handler is not None:
            for name in LOGGERS:
                logging.getLogger(name).removeHandler(self.log_handler)
        for provider in (self.tracer_provider, self.meter_provider, self.logger_provider):
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
    log_processors: Sequence[LogRecordProcessor] = (),
    active_participants: Callable[[], int] = lambda: 0,
) -> Telemetry:
    """Instrument `app` (HTTP and WebSocket requests) and `engine` (queries).

    `span_processors`, `metric_readers` and `log_processors` are added to whatever
    the environment configures; the tests use them to capture telemetry in memory.
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

    logger_provider = LoggerProvider(resource=resource)
    log_processors_list: list[LogRecordProcessor] = list(log_processors)
    kind = _exporter_kind(
        "OTEL_LOGS_EXPORTER",
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"),
    )
    if kind == "otlp":
        log_processors_list.append(BatchLogRecordProcessor(OTLPLogExporter()))
    elif kind == "console":
        log_processors_list.append(BatchLogRecordProcessor(ConsoleLogRecordExporter()))
    log_handler: logging.Handler | None = None
    if log_processors_list:
        for processor in log_processors_list:
            logger_provider.add_log_record_processor(processor)
        log_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        log_handler.addFilter(DropHealthChecks())
        for name in LOGGERS:
            logger = logging.getLogger(name)
            if not _reaches(logger, log_handler):
                logger.addHandler(log_handler)

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

    return Telemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        log_handler=log_handler,
        metrics=AppMetrics(meter_provider.get_meter(DEFAULT_SERVICE_NAME), active_participants),
    )
