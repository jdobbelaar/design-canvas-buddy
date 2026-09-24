# Observability stack

A local telemetry stack, deliberately **its own Compose project** (own network and
volumes), separate from the application stack in `../docker-compose.yaml`. Start,
stop, or wipe either one without touching the other.

```
app (OTLP) ──> OpenTelemetry Collector ──┬─ traces  ──> Tempo
                                         ├─ metrics ──> Prometheus
                                         └─ logs    ──> Loki
                                                          │
                                       Grafana <──────────┘  (queries all three)
```

| Service | What it does | Local URL |
|---|---|---|
| OpenTelemetry Collector | The one endpoint apps send to; fans each signal out to its store | `http://localhost:4318` (HTTP), `localhost:4317` (gRPC) |
| Grafana | Dashboards and exploration. **No login** (bound to loopback only) | http://localhost:3000 |
| Prometheus | Metrics | http://localhost:9090 |
| Loki | Logs | http://localhost:3100 |
| Tempo | Traces | http://localhost:3200 |

## Run it

```
make observability-up        # or: docker compose -f observability/docker-compose.yaml up -d
make observability-down      # stop; collected data is kept
```

Reset everything (deletes all collected telemetry):
`docker compose -f observability/docker-compose.yaml down -v`.

## Send the application's telemetry to it

The backend exports nothing unless told where (see `backend/app/telemetry.py`).
Point it at the collector.

**Application stack in Docker** (`../docker-compose.yaml`; it can reach the host as
`host.docker.internal`):

```
APP_ENVIRONMENT=local OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318 docker compose up -d --build
```

**Backend run directly** (`make backend`):

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 APP_ENVIRONMENT=local make backend
```

In PowerShell, set the variables first instead:

```
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://host.docker.internal:4318"   # http://localhost:4318 when not in Docker
$env:APP_ENVIRONMENT = "local"
docker compose up -d --build
```

Every signal is tagged with `service.name`, `deployment.environment.name`
(`APP_ENVIRONMENT`), and `service.version` (the image tag, `dev` locally). Choose a
different `APP_ENVIRONMENT` per run and the dashboard's Environment selector
separates them.

Metrics are pushed once a minute, so the first numbers appear after about a minute.

## What to look at

Grafana opens on the **Design Canvas Buddy** dashboard: request rate and latency,
server errors, which versions are reporting, recent traces, and logs. Log lines
link to their trace, and a trace's spans link back to its logs.

### Application metrics

The backend counts what happens in the product itself. All of them carry the
environment and deployed version (as Prometheus labels), and the dashboard's
**Interview activity** panel plots them together:

| Metric (Prometheus name) | What it counts |
|---|---|
| `interview_rooms_created_total` | Interview rooms created |
| `interview_participants_active` | Participants connected right now (a gauge) |
| `canvas_elements_created_total{element_type}` | Elements newly added to a canvas, by kind: a shape's kind (`database`, `loadbalancer`, ...), `text`, `draw`, `connector`. Re-adding an element a room already has is not a creation |
| `canvas_element_creation_failures_total{reason}` | Elements that could not be created: `invalid` (the message did not validate), `id_conflict` (the id belongs to another room), `error` (the server failed) |

The **Environment** and **Version** selectors at the top of the dashboard filter
every panel; the version list only offers versions seen in the chosen environment.
Both accept several values, e.g. to compare the old and new version around a deploy.

How the tags become things you can filter on:

| Store | Environment | Version | Example |
|---|---|---|---|
| Prometheus | label `deployment_environment_name` | label `service_version` | `rate(http_server_duration_milliseconds_count{deployment_environment_name="dev"}[5m])` |
| Loki | index label `deployment_environment_name` | structured metadata `service_version` | `{service_name="design-canvas-buddy", deployment_environment_name="dev"} \| service_version="20260924-013005-44cc2e2"` |
| Tempo | span attribute | span attribute | `{resource.service.name="design-canvas-buddy" && resource.service.version="20260924-013005-44cc2e2"}` |

The version is not a Loki index label on purpose: it changes with every deploy, and
each new value would create new streams.

## Things to know

- Data is kept for 7 days, in the named volumes `prometheus-data`, `loki-data`,
  `tempo-data` and `grafana-data`.
- Everything is published on `127.0.0.1` only. Set `BIND_ADDRESS=0.0.0.0` to accept
  telemetry from other machines, but note that neither the collector nor Grafana
  has authentication here, so do not expose it beyond a network you trust.
- Ports can be changed with `GRAFANA_PORT`, `PROMETHEUS_PORT`, `LOKI_PORT`,
  `TEMPO_PORT`, `OTLP_HTTP_PORT`, and `OTLP_GRPC_PORT`.
- Tempo logs `no jobs found` errors now and then. That is its background workers
  polling an empty queue, not a problem.
- This is for local development. It is not deployed to the AWS environments, which
  do not export telemetry yet.
