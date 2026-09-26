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

## On AWS

The same stack also runs in AWS, as its own CloudFormation stack
(`design-canvas-buddy-observability`, from `deploy/aws/observability.yaml`) with its
own server and network, separate from the application stacks. Both **dev** and
**production** send their telemetry to it, and its dashboard's Environment selector
tells them apart.

```
dev server ───────┐   HTTPS + token                        ┌─ Grafana (login required)
                  ├──> CloudFront ──> observability server ┤
production server ┘                                        └─ collector -> Tempo / Prometheus / Loki
```

- **Grafana:** the `GrafanaUrl` output of the stack. Log in as `admin`; the password
  is generated by AWS and kept in Secrets Manager, so it never appears in the
  repository. Show it in your own terminal (needs Secrets Manager read access):
  `aws secretsmanager get-secret-value --secret-id design-canvas-buddy/observability/grafana-admin --query SecretString --output text`
  (the `password` field of the JSON).
- **Sending telemetry:** applications POST OTLP to the `OtlpEndpoint` output with the
  header `Authorization: Bearer <token>`; anything without the right token gets a
  401. The token is the secret `design-canvas-buddy/observability/ingest-token`.
  You do not do this by hand: each application deploy looks the endpoint up, reads
  the token with the server's own role, and configures the app
  (`deploy/aws/deploy.sh`). If the observability stack is absent, apps deploy without telemetry.
- **Updating it:** changing anything under `observability/` and pushing to `main`
  runs the **deploy observability** workflow, which checks the configuration on the
  server before touching what is running, restarts the stack, and then verifies from
  the internet that Grafana wants a login and the collector wants the token.
- **Same files, two modes:** `docker-compose.aws.yaml` and
  `otel-collector/config.aws.yaml` are what differ from running it locally: a Grafana
  login instead of anonymous access, and token authentication on the collector.
- **Rotating the token:** change the `ingest-token` secret, then redeploy the
  observability stack and both applications (any push does the applications).

## Alerting

One alert is provisioned, in `grafana/provisioning/alerting/rules.yaml`:
**Canvas components repeatedly fail to be created.**

| | |
|---|---|
| **Fires when** | at least **3** component creations failed in the last 10 minutes **and** at least **5%** of creation attempts failed, on every check for **5 minutes** |
| **Checked** | every minute, separately for each service, environment, and deployed version |
| **Clears** | 5 minutes after the condition stops (so a flapping problem is one alert) |
| **Severity / owner** | `critical` / `jdobbelaar` (change `owner` in the rule) |

Why those numbers: a component that fails to be created is a real loss for the people
in the room, because it may not be saved or shown to the other participant, and
normal is zero failures. But one failure is a glitch, and a percentage of a handful of
attempts means nothing. So the alert needs both several failures (3) and a noticeable
share (5%), and it must persist (5 minutes), which filters bursts that clear on their
own while still reaching the owner within a few minutes, well inside a typical
interview. Data that disappears (a deploy replaces the version) counts as recovered.

Every alert carries: `service`, `environment`, `version`, and `owner` as labels, and
as annotations a `summary`, a `description` with the numbers, the user `impact`, a
`dashboard_url` (opens the dashboard already filtered to that environment and version,
last hour), a `runbook_url` (the section below), and short `what_to_do` steps. The
dashboard's **Component creation failures by reason** panel is where it points.

### Automatic first response

`on-call-engineer/` polls these alerts every minute and, when one fires, hands it to a
headless coding agent that investigates (read-only) and writes a report. See its README.

### Sending alerts somewhere

Alerts are evaluated and shown in Grafana (Alerting -> Alert rules), but **no delivery
channel is configured yet**: Grafana's built-in default has no address, so nothing is
sent. To deliver them, add two provisioning files next to `rules.yaml`, for example
for Slack (create an incoming webhook in Slack first):

```yaml
# grafana/provisioning/alerting/contact-points.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: slack-owners
    receivers:
      - uid: slack-owners
        type: slack
        settings:
          url: <the webhook URL>   # on AWS, keep the URL in Secrets Manager rather than in git
```

```yaml
# grafana/provisioning/alerting/policies.yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: slack-owners
    group_by: [alertname, environment]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
```

(A policy may only name a contact point that exists, and Grafana will not start if a
provisioning file is wrong, which is why these are not shipped half-configured.)

### Responding to component-creation failures

1. **Open the `dashboard_url` from the alert.** It is already filtered to the
   environment and version. Look at **Component creation failures by reason**.
2. **Did it start when the version changed?** The Version selector and the
   "Versions reporting" table show what is running and when a version appeared. If the
   failures began with a new version, go to step 3. If not, go to step 4.
3. **Roll back.** Run the **rollback** workflow (Actions -> rollback -> Run workflow),
   choose the environment and the tag of the last good version (the command in its
   header lists recent tags). Production asks for your approval, like a normal deploy.
   Then fix or revert the change before pushing anything else, since the next push to
   `main` deploys the newest commit again.
4. **Find the cause by reason:**
   - `error`: the server failed while saving. Check `/health` (is the database up?),
     then the **Logs** panel and the **Recent traces** panel for errors at the time the
     failures began.
   - `invalid`: the browser sent something the server does not accept. This is usually
     the browser and server being on different versions (someone with an old page open
     after a deploy, or a real contract change). Compare the request that fails with
     `openapi.yaml`.
   - `id_conflict`: a component's id already belongs to another room. Ids are meant to
     be unique, so look for a client reusing ids (a bug), not a server problem.
5. **Confirm it recovered:** the failures panel stops climbing, and the alert clears
   about 10 minutes later (its window) plus 5 minutes.

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
- On AWS it is a single small server with the data on its own disk: there are no
  backups, and if the server is replaced the history is gone. Telemetry is kept for
  7 days. The hop from CloudFront to the server is plain HTTP (an EC2 hostname cannot
  get a trusted certificate); everything on the internet leg is HTTPS.
