"""observe.py: the agent's only window onto the world must stay narrow."""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest import mock

import fakes  # noqa: F401  (puts the on-call-engineer directory on sys.path)
import observe
from fakes import FakeGrafana, raw_alert


class Base(unittest.TestCase):
    def setUp(self):
        self.grafana = FakeGrafana()
        self.addCleanup(self.grafana.close)
        env = mock.patch.dict(os.environ, {"GRAFANA_URL": self.grafana.url, "GRAFANA_TOKEN": "viewer-secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def observe(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = observe.main(list(argv))
            except SystemExit as refused:  # argparse rejecting the arguments
                code = refused.code
        return code, out.getvalue(), err.getvalue()


class Queries(Base):
    def test_a_metrics_query_goes_to_prometheus_through_grafana_with_the_token(self):
        self.grafana.responses["/api/datasources/proxy/uid/prometheus/api/v1/query"] = {"status": "success", "data": {"result": []}}
        code, out, _ = self.observe("prometheus", "up")
        self.assertEqual(code, 0)
        path, headers = self.grafana.requests[-1]
        self.assertTrue(path.startswith("/api/datasources/proxy/uid/prometheus/api/v1/query?"))
        self.assertIn("query=up", path)
        self.assertEqual(headers["Authorization"], "Bearer viewer-secret-token")
        self.assertEqual(json.loads(out)["status"], "success")

    def test_a_range_query_uses_the_range_endpoint(self):
        self.observe("prometheus", "up", "--range", "2h", "--step", "5m")
        path, _ = self.grafana.requests[-1]
        self.assertIn("/api/v1/query_range?", path)
        self.assertIn("step=5m", path)

    def test_logs_and_traces_go_to_their_own_datasources(self):
        self.observe("loki", '{service_name="x"}', "--since", "30m", "--limit", "5")
        self.observe("tempo", "{}", "--limit", "3")
        paths = [p for p, _ in self.grafana.requests]
        self.assertTrue(paths[0].startswith("/api/datasources/proxy/uid/loki/loki/api/v1/query_range?"))
        self.assertIn("limit=5", paths[0])
        self.assertTrue(paths[1].startswith("/api/datasources/proxy/uid/tempo/api/search?"))

    def test_limits_are_capped(self):
        self.observe("loki", "{}", "--limit", "100000")
        self.assertIn("limit=200", self.grafana.requests[-1][0])

    def test_alerts_lists_the_firing_ones(self):
        self.grafana.alerts = [raw_alert()]
        code, out, _ = self.observe("alerts")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["labels"]["environment"], "production")

    def test_it_only_ever_makes_get_requests_under_the_configured_grafana(self):
        # The handler above only implements GET; anything else would have failed. The base
        # address comes from the environment, and no argument can change it.
        self.observe("prometheus", "up")
        self.assertTrue(all(p.startswith("/api/") for p, _ in self.grafana.requests))
        with self.assertRaises(SystemExit):
            observe.parser().parse_args(["prometheus", "up", "--url", "http://evil.example"])


class Robustness(Base):
    def test_a_huge_answer_is_cut(self):
        self.grafana.responses["/api/datasources/proxy/uid/loki"] = {"lines": ["x" * 100] * 2000}
        _, out, _ = self.observe("loki", "{}")
        self.assertLessEqual(len(out.encode()), observe.MAX_OUTPUT_BYTES + 200)
        self.assertIn("output cut", out)

    def test_grafana_errors_are_reported_and_never_leak_the_token(self):
        self.grafana.status = 500
        code, out, err = self.observe("prometheus", "up")
        self.assertEqual(code, 1)
        self.assertIn("500", err)
        self.assertNotIn("viewer-secret-token", out + err)

    def test_an_unreachable_grafana_is_reported_and_never_leaks_the_token(self):
        self.grafana.close()
        code, out, err = self.observe("prometheus", "up")
        self.assertEqual(code, 1)
        self.assertNotIn("viewer-secret-token", out + err)

    def test_bad_durations_are_refused(self):
        for bad in ("soon", "1w", "5"):
            code, _, err = self.observe("loki", "{}", "--since", bad)
            self.assertEqual(code, 1, bad)
            self.assertIn("duration", err)
        self.assertNotEqual(self.observe("loki", "{}", "--since", "-5m")[0], 0)
        self.assertEqual(self.grafana.requests, [])  # none of them reached Grafana

    def test_a_non_http_grafana_address_is_refused(self):
        with mock.patch.dict(os.environ, {"GRAFANA_URL": "file:///etc/passwd"}):
            code, _, err = self.observe("alerts")
        self.assertEqual(code, 1)
        self.assertIn("http", err)


class GitAccess(Base):
    def test_trace_ids_and_commits_are_validated(self):
        self.assertEqual(self.observe("trace", "not-a-trace")[0], 1)
        self.assertEqual(self.observe("trace", "0123456789abcdef0123456789abcdef")[0], 0)
        for bad in ("HEAD", "main", "abc;rm", "ZZZZZZZ", "abc"):
            self.assertEqual(self.observe("commit", bad)[0], 1, bad)
        self.assertNotEqual(self.observe("commit", "--output=/tmp/x")[0], 0)  # argparse refuses it

    def test_history_cannot_smuggle_in_a_git_flag(self):
        for bad in ("a b", "x;y", "$(id)", "a`id`"):
            self.assertEqual(self.observe("history", "--path", bad)[0], 1, bad)
        for flaglike in ("--output=/tmp/x", "-p"):
            self.assertNotEqual(self.observe("history", "--path", flaglike)[0], 0, flaglike)
        # and a value that only *starts* with a dash, given in a form argparse accepts
        self.assertEqual(self.observe("history", "--path=--output=/tmp/x")[0], 1)

    def test_history_works_on_a_real_path(self):
        code, out, _ = self.observe("history", "-n", "3")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(out.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
