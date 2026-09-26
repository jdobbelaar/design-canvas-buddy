"""Test doubles: a fake Grafana on a local port, and stub agents."""

from __future__ import annotations

import http.server
import json
import sys
import textwrap
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def raw_alert(fingerprint="f1", starts_at="2026-09-26T20:00:00.000Z", state="active", **labels):
    """An alert as Grafana's Alertmanager API returns it."""
    return {
        "fingerprint": fingerprint,
        "startsAt": starts_at,
        "status": {"state": state, "silencedBy": [], "inhibitedBy": []},
        "labels": {
            "alertname": "Canvas components repeatedly fail to be created",
            "environment": "production",
            "version": "20260926-193908-1876f63",
            "service": "design-canvas-buddy",
            "owner": "jdobbelaar",
            **labels,
        },
        "annotations": {
            "description": "38 component creations failed in the last 10 minutes (40% of attempts).",
            "dashboard_url": "https://grafana.example/d/design-canvas-buddy?var-environment=production",
            "runbook_url": "https://example/runbook",
        },
        "generatorURL": "https://grafana.example/alerting/grafana/canvas/view",
    }


class FakeGrafana:
    """Answers the endpoints the scripts use, and remembers what it was asked."""

    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.responses: dict[str, object] = {}  # path prefix -> JSON to return
        self.status = 200
        self.requests: list[tuple[str, dict[str, str]]] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, dict(self.headers)))
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write(b'{"message": "nope"}')
                    return
                body: object = []
                if self.path.startswith("/api/alertmanager/grafana/api/v2/alerts"):
                    body = outer.alerts
                else:
                    for prefix, value in outer.responses.items():
                        if self.path.startswith(prefix):
                            body = value
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):  # keep test output clean
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def write_stub_agent(directory: Path, body: str) -> list[str]:
    """A stand-in for the coding agent: a Python script that gets the prompt on stdin."""
    script = directory / "stub_agent.py"
    script.write_text(
        "import sys\nprompt = sys.stdin.read()\n" + textwrap.dedent(body), encoding="utf-8"
    )
    return [sys.executable, str(script)]
