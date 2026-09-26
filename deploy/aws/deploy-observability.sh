#!/bin/bash
# Runs ON the observability server (started over AWS Systems Manager by the
# "deploy observability" workflow), from the repository checkout in
# /opt/observability at the commit being deployed. Starts or updates the stack
# in observability/ with the AWS overrides, and only succeeds if it is healthy and
# authentication is actually being enforced.
#
#   AWS_REGION=us-east-1 GRAFANA_ROOT_URL=https://<id>.cloudfront.net \
#     bash deploy/aws/deploy-observability.sh
#
# Secrets (the Grafana admin password and the telemetry ingest token) are read
# from AWS Secrets Manager with the instance's own role and written only to
# observability/.env on this machine, readable by root alone.
set -euo pipefail

: "${AWS_REGION:?AWS_REGION must be set}"
: "${GRAFANA_ROOT_URL:?GRAFANA_ROOT_URL must be the public https address of Grafana}"
SECRET_PREFIX=${SECRET_PREFIX:-design-canvas-buddy/observability}
cd /opt/observability

# One deploy at a time.
exec 9>/var/lock/design-canvas-buddy-observability-deploy.lock
if ! flock -n 9; then
  echo "another deploy is already running" >&2
  exit 1
fi

# The AWS CLI is not part of the Ubuntu image, so fetch it once.
if ! command -v aws > /dev/null; then
  echo "==> installing the AWS CLI"
  snap install aws-cli --classic
fi

echo "==> reading secrets"
secret() {
  aws secretsmanager get-secret-value --region "$AWS_REGION" --secret-id "$SECRET_PREFIX/$1" \
    --query SecretString --output text
}
grafana_password=$(secret grafana-admin | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')
ingest_token=$(secret ingest-token)

# Compose reads .env from the directory of the compose file.
umask 077
cat > observability/.env <<ENV
GRAFANA_ADMIN_PASSWORD=$grafana_password
INGEST_TOKEN=$ingest_token
GRAFANA_ROOT_URL=$GRAFANA_ROOT_URL
GRAFANA_BIND=0.0.0.0
OTLP_HTTP_BIND=0.0.0.0
ENV
umask 022
export INGEST_TOKEN=$ingest_token

compose=(docker compose -f observability/docker-compose.yaml -f observability/docker-compose.aws.yaml)

echo "==> checking the configuration before touching what is running"
"${compose[@]}" config --quiet
"${compose[@]}" pull --quiet
collector_image=$("${compose[@]}" config --images | grep opentelemetry-collector)
prometheus_image=$("${compose[@]}" config --images | grep prometheus)
docker run --rm -e INGEST_TOKEN \
  -v "$PWD/observability/otel-collector/config.aws.yaml:/etc/otelcol/config.yaml:ro" \
  "$collector_image" validate --config=/etc/otelcol/config.yaml
docker run --rm --entrypoint promtool \
  -v "$PWD/observability/prometheus/prometheus.yml:/prometheus.yml:ro" \
  "$prometheus_image" check config /prometheus.yml

echo "==> starting"
"${compose[@]}" up -d --remove-orphans

wait_for() { # description, command...
  local what=$1
  shift
  for _ in $(seq 1 60); do
    if "$@" > /dev/null 2>&1; then
      echo "ready: $what"
      return 0
    fi
    sleep 3
  done
  echo "not ready after 3 minutes: $what" >&2
  "${compose[@]}" logs --tail 40 >&2
  return 1
}
wait_for grafana curl -fsS http://localhost:3000/api/health
wait_for prometheus curl -fsS http://localhost:9090/-/ready
wait_for loki curl -fsS http://localhost:3100/ready
wait_for tempo curl -fsS http://localhost:3200/ready

# Telemetry must be rejected without the token and accepted with it, and Grafana
# must refuse anonymous access. Anything else means this is open to the internet.
otlp() { # optional extra curl args
  curl -sS -o /dev/null -w '%{http_code}' -X POST http://localhost:4318/v1/traces \
    -H 'Content-Type: application/json' -d '{}' "$@"
}
for _ in $(seq 1 20); do
  [ "$(otlp -H "Authorization: Bearer $ingest_token" || true)" = 200 ] && break
  sleep 3
done
[ "$(otlp -H "Authorization: Bearer $ingest_token")" = 200 ] || { echo "collector rejects the right token" >&2; exit 1; }
[ "$(otlp)" = 401 ] || { echo "collector accepts telemetry WITHOUT a token" >&2; exit 1; }
[ "$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:3000/api/search)" = 401 ] \
  || { echo "Grafana allows anonymous access" >&2; exit 1; }
echo "authentication is enforced"

# The alert must be loaded: an alert that silently is not there is worse than none.
# (The password goes through stdin, not the command line, so it is not in `ps`.)
rule_status=$(printf 'user = "admin:%s"\n' "$grafana_password" \
  | curl -sS -K - -o /dev/null -w '%{http_code}' \
    http://localhost:3000/api/v1/provisioning/alert-rules/canvas-creation-failures)
[ "$rule_status" = 200 ] || { echo "the alert rule was not loaded (HTTP $rule_status)" >&2; exit 1; }
echo "alert rule is loaded"

# Keep the disk from filling over many deploys: drop images nothing uses that
# are over a week old.
docker image prune -af --filter "until=168h" > /dev/null
echo "observability stack is up"
