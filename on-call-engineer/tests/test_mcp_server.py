"""mcp_server.py: exactly the intended tools, well-behaved, and nothing else."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import fakes
import mcp_server
import observe
from fakes import FakeGrafana, raw_alert

EXPECTED_TOOLS = {
    "firing_alerts", "prometheus_query", "loki_query", "tempo_search", "tempo_trace",
    "repo_files", "repo_read", "repo_search", "git_history", "git_show",
}
SERVER = Path(__file__).resolve().parent.parent / "mcp_server.py"


def rpc(method, params=None, ident=1):
    message = {"jsonrpc": "2.0", "id": ident, "method": method}
    if params is not None:
        message["params"] = params
    return message


class Protocol(unittest.TestCase):
    def test_initialize_answers_with_the_clients_protocol_version(self):
        reply = mcp_server.handle(rpc("initialize", {"protocolVersion": "2024-11-05"}))
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(reply["result"]["serverInfo"]["name"], "oncall")
        self.assertIn("tools", reply["result"]["capabilities"])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_ping_and_unknown_methods(self):
        self.assertEqual(mcp_server.handle(rpc("ping"))["result"], {})
        reply = mcp_server.handle(rpc("resources/list"))
        self.assertEqual(reply["error"]["code"], -32601)

    def test_the_tool_list_is_exactly_the_intended_read_only_tools(self):
        tools = mcp_server.handle(rpc("tools/list"))["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, EXPECTED_TOOLS)
        for tool in tools:
            self.assertNotIn("handler", tool)  # internals are not sent
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertTrue(tool["description"])

    def test_no_tool_can_write_run_or_fetch(self):
        # Every tool is one of observe.py's read-only functions.
        for tool in mcp_server.TOOLS:
            self.assertEqual(tool["handler"].__module__, "observe", tool["name"])

    def test_garbage_is_survivable(self):
        self.assertEqual(mcp_server.handle("not an object")["error"]["code"], -32600)
        self.assertEqual(mcp_server.handle(rpc("tools/call", "nope"))["error"]["code"], -32602)


class Calling(unittest.TestCase):
    def setUp(self):
        self.grafana = FakeGrafana()
        self.addCleanup(self.grafana.close)
        patch = mock.patch.dict(os.environ, {"GRAFANA_URL": self.grafana.url, "GRAFANA_TOKEN": "viewer-secret-token"})
        patch.start()
        self.addCleanup(patch.stop)

    def call(self, name, arguments=None):
        reply = mcp_server.handle(rpc("tools/call", {"name": name, "arguments": arguments}))
        result = reply["result"]
        return result["content"][0]["text"], result["isError"]

    def test_firing_alerts_returns_the_alerts(self):
        self.grafana.alerts = [raw_alert()]
        text, is_error = self.call("firing_alerts")
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)[0]["labels"]["environment"], "production")

    def test_a_metrics_query_reaches_prometheus_with_the_token(self):
        self.call("prometheus_query", {"query": "up", "range": "1h"})
        path, headers = self.grafana.requests[-1]
        self.assertIn("/uid/prometheus/api/v1/query_range", path)
        self.assertEqual(headers["Authorization"], "Bearer viewer-secret-token")

    def test_problems_come_back_as_errors_the_agent_can_read(self):
        cases = [
            ("no_such_tool", {}, "unknown tool"),
            ("prometheus_query", {}, "missing argument"),
            ("prometheus_query", {"query": "up", "url": "http://evil.example"}, "unexpected argument"),
            ("prometheus_query", {"query": 5}, "must be a string"),
            ("loki_query", {"query": "{}", "limit": "many"}, "must be a integer"),
            ("loki_query", {"query": "{}", "limit": True}, "must be a integer"),
            ("loki_query", {"query": "{}", "since": "soon"}, "duration"),
            ("tempo_trace", {"trace_id": "nope"}, "trace id"),
        ]
        for name, arguments, expected in cases:
            text, is_error = self.call(name, arguments)
            self.assertTrue(is_error, (name, arguments))
            self.assertIn(expected, text)

    def test_an_arguments_value_that_is_not_an_object_is_refused(self):
        text, is_error = self.call("firing_alerts", ["x"])
        self.assertTrue(is_error)

    def test_grafana_failures_never_reveal_the_token(self):
        self.grafana.status = 500
        text, is_error = self.call("prometheus_query", {"query": "up"})
        self.assertTrue(is_error)
        self.assertNotIn("viewer-secret-token", text)

    def test_an_unexpected_crash_is_reported_without_internals(self):
        with mock.patch.object(observe, "alerts", side_effect=RuntimeError("secret internal detail /home/x")):
            tool = mcp_server.BY_NAME["firing_alerts"]
            with mock.patch.dict(tool, {"handler": observe.alerts}):
                text, is_error = mcp_server.call_tool("firing_alerts", {})
        self.assertTrue(is_error)
        self.assertNotIn("secret internal detail", text)


class TheRepositoryAsCommitted(unittest.TestCase):
    """The agent's only view of the code: git, at a commit, tracked files only."""

    def call(self, name, arguments=None):
        reply = mcp_server.handle(rpc("tools/call", {"name": name, "arguments": arguments}))
        result = reply["result"]
        return result["content"][0]["text"], result["isError"]

    def test_a_committed_file_can_be_read_with_line_numbers(self):
        text, is_error = self.call("repo_read", {"path": "openapi.yaml", "lines": 3})
        self.assertFalse(is_error)
        self.assertRegex(text.splitlines()[0], r"^\s+1  ")

    def test_files_that_are_not_committed_do_not_exist(self):
        junk = observe.REPO_ROOT / "observability" / ".env"
        junk.write_text("SECRET=decoy\n", encoding="utf-8")
        self.addCleanup(junk.unlink)
        for path in ("observability/.env", ".git/config"):
            text, is_error = self.call("repo_read", {"path": path})
            self.assertTrue(is_error, path)
            self.assertNotIn("decoy", text)
        text, _ = self.call("repo_files", {"path": "observability"})
        self.assertNotIn(".env\n", text + "\n")
        text, _ = self.call("repo_search", {"pattern": "SECRET=decoy"})
        self.assertEqual(text, "no matches")

    def test_paths_cannot_leave_the_repository(self):
        for path in ("../secret", "/etc/passwd", "C:/Users/x/.claude/.credentials.json",
                     "a/../../b", "-p", "a b", "x;y", "$(id)", "a//b", ""):
            text, is_error = self.call("repo_read", {"path": path})
            self.assertTrue(is_error, path)

    def test_a_ref_must_be_head_or_a_commit_hash(self):
        for ref in ("main", "HEAD~1", "--all", "HEAD; rm", "origin/main"):
            self.assertTrue(self.call("repo_read", {"path": "openapi.yaml", "ref": ref})[1], ref)
        self.assertFalse(self.call("repo_read", {"path": "openapi.yaml", "ref": "HEAD"})[1])

    def test_a_search_pattern_cannot_be_an_option(self):
        text, is_error = self.call("repo_search", {"pattern": "--output=leaked.txt"})
        self.assertFalse(is_error)
        self.assertEqual(text, "no matches")
        self.assertFalse((observe.REPO_ROOT / "leaked.txt").exists())

    def test_search_finds_committed_text_and_limits_itself(self):
        text, _ = self.call("repo_search", {"pattern": "health", "path": "openapi.yaml"})
        self.assertIn("health", text)
        self.assertNotIn("HEAD:", text)  # the ref prefix is stripped
        many, _ = self.call("repo_search", {"pattern": "."})
        self.assertLessEqual(len(many.encode()), observe.MAX_OUTPUT_BYTES + 200)

    def test_binary_files_are_refused(self):
        binaries = subprocess.run(["git", "ls-files"], cwd=observe.REPO_ROOT, capture_output=True, text=True).stdout.split()
        binary = next((f for f in binaries if f.lower().endswith((".png", ".ico", ".jpg", ".woff2"))), None)
        if binary is None:
            self.skipTest("no committed binary file to try")
        text, is_error = self.call("repo_read", {"path": binary})
        self.assertTrue(is_error)

    def test_history_and_commits(self):
        self.assertFalse(self.call("git_history", {"n": 3})[1])
        self.assertTrue(self.call("git_show", {"sha": "--output=x"})[1])


class OverStdio(unittest.TestCase):
    """The real thing: a child process speaking the protocol on stdin and stdout."""

    def test_a_client_can_initialize_list_tools_and_call_one(self):
        grafana = FakeGrafana()
        self.addCleanup(grafana.close)
        grafana.alerts = [raw_alert()]
        env = {**os.environ, "GRAFANA_URL": grafana.url, "PYTHONUTF8": "1"}
        requests = [
            rpc("initialize", {"protocolVersion": "2025-06-18"}, 1),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc("tools/list", None, 2),
            rpc("tools/call", {"name": "firing_alerts", "arguments": {}}, 3),
        ]
        stdin = "\n".join(json.dumps(r) for r in requests) + "\nthis line is not json\n" + json.dumps(rpc("ping", None, 4)) + "\n"
        done = subprocess.run([sys.executable, str(SERVER)], input=stdin, capture_output=True, text=True,
                              encoding="utf-8", env=env, timeout=60)
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        by_id = {r["id"]: r for r in replies}
        self.assertEqual(len(replies), 5)  # the notification got none; the junk line got a parse error
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "oncall")
        self.assertEqual({t["name"] for t in by_id[2]["result"]["tools"]}, EXPECTED_TOOLS)
        self.assertIn("production", by_id[3]["result"]["content"][0]["text"])
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertIn(4, by_id)  # it kept serving after the junk
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
