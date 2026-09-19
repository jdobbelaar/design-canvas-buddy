#!/bin/bash
# Runs ON the server (started over AWS Systems Manager by the CI pipeline), from
# the checked-out commit in /opt/app. Rebuilds and restarts the app for that
# commit, and only succeeds if /health reports that exact commit as running.
#
#   GIT_SHA=<commit> bash deploy/aws/deploy.sh
#
# Postgres is left running: its data lives in a Docker volume and is untouched.
# The app container is replaced, so open WebSockets drop for a few seconds and
# clients must refresh (the frontend has no reconnect logic yet).
set -euo pipefail

: "${GIT_SHA:?GIT_SHA must be set to the commit being deployed}"
cd /opt/app

# One deploy at a time: a second pipeline run, or a person on the server.
exec 9>/var/lock/design-canvas-buddy-deploy.lock
if ! flock -n 9; then
  echo "another deploy is already running" >&2
  exit 1
fi

export GIT_SHA
echo "==> building and starting $GIT_SHA"
# --wait returns only once every service reports healthy (the app's check is
# /health, which includes the database).
docker compose up -d --build --wait --wait-timeout 300

# Health can be green for the *previous* build until the old container is gone,
# so insist on the version, not just on a 200.
port=$(sed -n 's/^APP_PORT=//p' .env)
port=${port:-80}
echo "==> verifying /health reports $GIT_SHA"
body=""
for _ in $(seq 1 30); do
  body=$(curl -fsS --max-time 5 "http://localhost:$port/health" || true)
  if grep -q '"status":"ok"' <<<"$body" && grep -q "\"version\":\"$GIT_SHA\"" <<<"$body"; then
    echo "healthy: $body"
    # Keep the disk from filling over many deploys: drop superseded images and
    # build cache untouched for a week.
    docker image prune -f > /dev/null
    docker builder prune -f --filter "until=168h" > /dev/null
    exit 0
  fi
  sleep 2
done

echo "did not become healthy at $GIT_SHA; last /health response: ${body:-<none>}" >&2
docker compose logs --tail 60 app >&2
exit 1
