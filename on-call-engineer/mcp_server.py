#!/usr/bin/env python3
"""A Model Context Protocol server that gives the on-call agent read-only eyes.

This is how the agent looks at the world. It has NO shell, so there is no command
line to smuggle a second command into, no redirect that writes a file, and no way to
run anything but the ten tools below. Each is a thin wrapper over observe.py:
a GET against a fixed Grafana endpoint, or a fixed read-only git invocation.

It speaks MCP over stdin/stdout (one JSON message per line) and is started by the
agent itself (see poll.py). Configuration comes from the environment, never from the
agent: GRAFANA_URL and GRAFANA_TOKEN.

Standard library only.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import observe

SERVER_NAME = "oncall"
SERVER_VERSION = "1.0"
DEFAULT_PROTOCOL = "2025-06-18"

_STR = {"type": "string"}
_INT = {"type": "integer"}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str],
          handler: Callable[..., str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required,
                        "additionalProperties": False},
        "handler": handler,
    }


TOOLS: list[dict[str, Any]] = [
    _tool("firing_alerts", "The alerts firing right now (silenced ones excluded).", {}, [], observe.alerts),
    _tool(
        "prometheus_query",
        "Run a PromQL query. Instant by default; give `range` (e.g. 2h) to get a time series. "
        "Metrics carry deployment_environment_name and service_version labels.",
        {"query": _STR, "range": {**_STR, "description": "e.g. 30m, 2h, 1d"}, "step": {**_STR, "description": "default 1m"}},
        ["query"], observe.prometheus,
    ),
    _tool(
        "loki_query",
        "Run a LogQL query and return log lines, newest first.",
        {"query": _STR, "since": {**_STR, "description": "default 1h"}, "limit": {**_INT, "description": "default 50, max 200"}},
        ["query"], observe.loki,
    ),
    _tool(
        "tempo_search",
        "Search traces with TraceQL.",
        {"query": _STR, "since": {**_STR, "description": "default 1h"}, "limit": {**_INT, "description": "default 20, max 50"}},
        ["query"], observe.tempo,
    ),
    _tool("tempo_trace", "Fetch one trace by id.", {"trace_id": _STR}, ["trace_id"], observe.trace),
    _tool(
        "repo_files",
        "List the files in the repository as committed at `ref` (default HEAD), optionally under a path.",
        {"path": _STR, "ref": {**_STR, "description": "HEAD or a commit sha, e.g. the one in a version tag"}},
        [], observe.repo_files,
    ),
    _tool(
        "repo_read",
        "Read a text file as committed at `ref` (default HEAD), with line numbers. Only committed "
        "files exist here.",
        {"path": _STR, "ref": _STR, "start": {**_INT, "description": "first line, default 1"},
         "lines": {**_INT, "description": "default 300, max 400"}},
        ["path"], observe.repo_read,
    ),
    _tool(
        "repo_search",
        "Search committed files for lines matching an extended regular expression.",
        {"pattern": _STR, "path": {**_STR, "description": "limit to this file or directory"}, "ref": _STR},
        ["pattern"], observe.repo_search,
    ),
    _tool(
        "git_history",
        "Recent commits, optionally only those touching a path in the repository.",
        {"path": _STR, "n": {**_INT, "description": "default 20, max 100"}}, [], observe.history,
    ),
    _tool("git_show", "What one commit changed (stat and patch).", {"sha": _STR}, ["sha"], observe.commit),
]
BY_NAME = {t["name"]: t for t in TOOLS}

TYPES = {"string": str, "integer": int}


def call_tool(name: str, arguments: Any) -> tuple[str, bool]:
    """Run a tool. Returns (text, is_error). Problems become text for the agent to read;
    nothing here can raise out of the server, and nothing internal is revealed."""
    tool = BY_NAME.get(name)
    if tool is None:
        return f"unknown tool {name!r}", True
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "arguments must be an object", True
    schema = tool["inputSchema"]
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if spec is None:
            return f"unexpected argument {key!r}", True
        expected = TYPES[spec["type"]]
        if isinstance(value, bool) or not isinstance(value, expected):
            return f"argument {key!r} must be a {spec['type']}", True
    for key in schema["required"]:
        if key not in arguments:
            return f"missing argument {key!r}", True
    try:
        return tool["handler"](**arguments), False
    except observe.ObserveError as exc:
        return f"error: {exc}", True
    except Exception:  # noqa: BLE001 -- a tool must never take the server down or leak internals
        return "error: the query failed unexpectedly", True


def handle(message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message in, the reply (if it wants one) out."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method = message.get("method")
    ident = message.get("id")
    params = message.get("params") or {}

    if ident is None:  # a notification (for example notifications/initialized): no reply
        return None
    if method == "initialize":
        version = params.get("protocolVersion") if isinstance(params, dict) else None
        result = {
            "protocolVersion": version if isinstance(version, str) else DEFAULT_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]}
    elif method == "tools/call":
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "invalid params"}}
        text, is_error = call_tool(str(params.get("name")), params.get("arguments"))
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            stdout.flush()


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
    serve()
