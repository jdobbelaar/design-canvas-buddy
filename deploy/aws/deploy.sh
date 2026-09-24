#!/bin/bash
# Runs ON the server (started over AWS Systems Manager by the CI pipeline), from
# the repository checkout in /opt/app at the commit the image was built from.
# Pulls a prebuilt image from the registry (ECR) and starts it; nothing is built
# here. Succeeds only if /health reports that exact image tag as running.
#
#   APP_IMAGE=<registry>/design-canvas-buddy:<tag> APP_VERSION=<tag> bash deploy/aws/deploy.sh
#
# Postgres is left running: its data lives in a Docker volume and is untouched.
# The app container is replaced, so open WebSockets drop for a few seconds and
# clients must refresh (the frontend has no reconnect logic yet).
set -euo pipefail

: "${APP_IMAGE:?APP_IMAGE must be the full image reference to run}"
: "${APP_VERSION:?APP_VERSION must be the image tag being deployed}"
cd /opt/app

# One deploy at a time: a second pipeline run, or a person on the server.
exec 9>/var/lock/design-canvas-buddy-deploy.lock
if ! flock -n 9; then
  echo "another deploy is already running" >&2
  exit 1
fi

# The server authenticates to the registry with its instance role (no stored
# credentials). The AWS CLI is not part of the Ubuntu image, so fetch it once.
if ! command -v aws > /dev/null; then
  echo "==> installing the AWS CLI"
  snap install aws-cli --classic
fi
registry=${APP_IMAGE%%/*}
region=$(cut -d. -f4 <<<"$registry")
echo "==> logging in to $registry"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

# Remember the image in .env so a later plain `docker compose up -d` (a reboot
# recovery, someone on the server) runs this image rather than trying to build.
touch .env
grep -v '^APP_IMAGE=' .env > .env.new || true
echo "APP_IMAGE=$APP_IMAGE" >> .env.new
chmod --reference=.env .env.new
mv .env.new .env

export APP_IMAGE
echo "==> pulling $APP_IMAGE"
docker compose pull app
echo "==> starting $APP_VERSION"
# --wait returns only once every service reports healthy (the app's check is
# /health, which includes the database).
docker compose up -d --no-build --wait --wait-timeout 300

# Health can be green for the *previous* version until the old container is
# gone, so insist on the version, not just on a 200.
port=$(sed -n 's/^APP_PORT=//p' .env)
port=${port:-80}
echo "==> verifying /health reports $APP_VERSION"
body=""
for _ in $(seq 1 30); do
  body=$(curl -fsS --max-time 5 "http://localhost:$port/health" || true)
  if grep -q '"status":"ok"' <<<"$body" && grep -q "\"version\":\"$APP_VERSION\"" <<<"$body"; then
    echo "healthy: $body"
    # Keep the disk from filling over many deploys: drop images no container
    # uses that are over a week old (recent ones stay for a quick rollback).
    docker image prune -af --filter "until=168h" > /dev/null
    exit 0
  fi
  sleep 2
done

echo "did not become healthy at $APP_VERSION; last /health response: ${body:-<none>}" >&2
docker compose logs --tail 60 app >&2
exit 1
