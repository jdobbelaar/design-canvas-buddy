"""Integration tests: the real docker-compose.yaml stack (app + Postgres).

Nothing here is mocked. A session-scoped fixture brings the stack up under a
throwaway project name and a random host port -- so it cannot collide with a
stack you run yourself, or anything already on port 8000 -- and tears it down
(volumes and built image included) afterwards.

    make test-integration
    cd backend && uv run pytest integration_tests -v

Needs a running Docker daemon. The first run builds the image (a few minutes);
later runs reuse Docker's layer cache. These live outside `tests/`, so a plain
`pytest` stays fast and Docker-free.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"

# Must match the defaults in docker-compose.yaml.
DEFAULT_CREDENTIALS = {
    "POSTGRES_USER": "designcanvas",
    "POSTGRES_PASSWORD": "designcanvas",
    "POSTGRES_DB": "designcanvas",
}


def wait_until(
    check: Callable[[], Any], *, timeout: float = 30, interval: float = 0.5, what: str = "condition"
) -> Any:
    """Poll `check` until it returns something truthy, and return that."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001 -- keep polling, report the last one
            last_error = exc
        time.sleep(interval)
    detail = f" (last error: {last_error!r})" if last_error else ""
    raise AssertionError(f"timed out after {timeout}s waiting for {what}{detail}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _require_docker() -> None:
    try:
        subprocess.run(
            ["docker", "compose", "version"], capture_output=True, check=True, timeout=30
        )
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        # Fail rather than skip: a skipped integration suite reads as a green one.
        pytest.fail(
            "Integration tests need Docker with the compose plugin and a running "
            f"daemon, but it isn't available ({exc}).",
            pytrace=False,
        )


class Stack:
    """One running instance of docker-compose.yaml."""

    def __init__(self, project: str, port: int, env_file: str, credentials: dict[str, str]):
        self.project = project
        self.port = port
        self.credentials = credentials
        self._env_file = env_file
        # Explicit environment: the developer's shell (POSTGRES_PASSWORD, ...) or a
        # root .env must not change what these tests exercise.
        self._env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("POSTGRES_") and k not in ("APP_PORT", "DATABASE_URL")
        }
        self._env.update(credentials)
        self._env["APP_PORT"] = str(port)
        self.http = httpx.Client(base_url=self.base_url, timeout=15)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ws_url(self, session_id: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/{session_id}"

    def compose(self, *args: str, check: bool = True, timeout: int = 300):
        result = subprocess.run(
            [
                "docker", "compose", "-p", self.project, "--env-file", self._env_file,
                "-f", str(COMPOSE_FILE), *args,
            ],
            cwd=REPO_ROOT,
            env=self._env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"`docker compose {' '.join(args)}` exited {result.returncode}\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
        return result

    def up(self, *, build: bool = False) -> None:
        args = ["up", "-d", "--wait", "--wait-timeout", "180"]
        if os.environ.get("APP_IMAGE"):
            # CI tests the exact image it will ship. --no-build makes a missing
            # one an error rather than a quiet rebuild of something else.
            args.append("--no-build")
        elif build:
            args.append("--build")
        try:
            self.compose(*args, timeout=1200)
        except RuntimeError as exc:
            logs = self.compose("logs", "--tail", "60", check=False).stdout
            raise RuntimeError(f"{exc}\n--- container logs ---\n{logs}") from exc

    def down(self, *, volumes: bool = False) -> None:
        args = ["down", "--remove-orphans"]
        if volumes:
            # --rmi local drops the image built for this throwaway project name,
            # so repeated runs don't leave a tagged image behind each time.
            args += ["-v", "--rmi", "local"]
        self.compose(*args, check=False, timeout=180)

    def services(self) -> dict[str, dict]:
        out = self.compose("ps", "--format", "json").stdout.strip()
        rows = json.loads(out) if out.startswith("[") else [json.loads(l) for l in out.splitlines()]
        return {row["Service"]: row for row in rows}

    def inspect(self, service: str) -> dict:
        container = self.compose("ps", "-q", service).stdout.strip()
        raw = subprocess.run(
            ["docker", "inspect", container], capture_output=True, text=True, check=True
        ).stdout
        return json.loads(raw)[0]

    def logs(self, service: str) -> str:
        return self.compose("logs", "--no-color", service).stdout

    def psql(self, sql: str) -> str:
        """Run SQL directly in the Postgres container and return the bare result."""
        c = self.credentials
        result = self.compose(
            "exec", "-T", "postgres", "psql", "-U", c["POSTGRES_USER"], "-d", c["POSTGRES_DB"],
            "-Atc", sql,
        )
        return result.stdout.strip()

    def wait_for_api(self, timeout: float = 60) -> None:
        wait_until(
            lambda: self.http.get("/openapi.json").status_code == 200,
            timeout=timeout,
            what="the app to answer /openapi.json",
        )

    def new_session(self) -> str:
        response = self.http.post("/sessions")
        assert response.status_code == 201, response.text
        return response.json()["sessionId"]


@contextlib.contextmanager
def running_stack(credentials: dict[str, str] | None = None) -> Iterator[Stack]:
    _require_docker()
    creds = {**DEFAULT_CREDENTIALS, **(credentials or {})}
    with tempfile.TemporaryDirectory() as tmp:
        # An empty --env-file stops compose from picking up a developer's root .env.
        env_file = Path(tmp, "empty.env")
        env_file.write_text("")
        stack = Stack(f"dcb-it-{uuid.uuid4().hex[:8]}", _free_port(), str(env_file), creds)
        try:
            # CI tests the exact image it will ship: APP_IMAGE names one that is
            # already loaded, so nothing is rebuilt.
            stack.up(build=not os.environ.get("APP_IMAGE"))
            stack.wait_for_api()
            yield stack
        finally:
            stack.http.close()
            stack.down(volumes=True)


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    with running_stack() as s:
        yield s


@pytest.fixture
def session_id(stack: Stack) -> str:
    """A fresh, empty collaboration session, so tests can't affect each other."""
    return stack.new_session()
