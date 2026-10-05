"""Offline checks for the regression gate's Discord failure notification."""

import json
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "regression-gate.yml"


def load_notifier():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Notify Discord (fail)\n", 1)[1].split("\n      - name:", 1)[0]
    run = step.split("        run: |\n", 1)[1]
    commands = "\n".join(line[10:] for line in run.splitlines())
    source = commands.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    module = types.ModuleType("regression_notifier")
    exec(compile(source, str(WORKFLOW), "exec"), module.__dict__)
    return module


class RegressionGateNotificationTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "DISCORD_WEBHOOK_URL": "https://example.invalid/webhook-secret",
            "GITHUB_SHA": "abcdef0123456789",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123",
            "GITHUB_SERVER_URL": "https://github.com",
        }

    def test_workflow_notifies_only_on_failure_including_earlier_steps(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("Notify Discord (pass", workflow)
        self.assertIn("if: ${{ failure() || steps.gate.outputs.status == 'FAILED' }}", workflow)
        self.assertIn("python3 - <<'PY'", workflow)

    def test_pytest_infrastructure_error_is_not_hidden_by_baseline_comparison(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('if [ "$TEST_EXIT" -gt 1 ]; then', workflow)

    def test_success_completion_sends_nothing(self):
        with patch.dict(os.environ, {**self.env, "GATE_STATUS": "PASSED"}, clear=True):
            with patch("urllib.request.urlopen") as send:
                self.assertEqual(load_notifier().main(), 0)
        send.assert_not_called()

    def test_regression_failure_sends_escaped_json_without_mentions(self):
        env = {**self.env, "GATE_STATUS": "FAILED", "NEW_FAILURES": 'tests/test_a.py::test_"quote"\n@everyone'}
        with patch.dict(os.environ, env, clear=True):
            with patch("urllib.request.urlopen") as send:
                self.assertEqual(load_notifier().main(), 0)
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, self.env["DISCORD_WEBHOOK_URL"])
        self.assertIn('test_"quote"', payload["content"])
        self.assertIn("@everyone", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_earlier_step_failure_sends_generic_error(self):
        with patch.dict(os.environ, {**self.env, "GATE_STATUS": ""}, clear=True):
            with patch("urllib.request.urlopen") as send:
                self.assertEqual(load_notifier().main(), 0)
        payload = json.loads(send.call_args.args[0].data)
        self.assertIn("failed", payload["content"].lower())
        self.assertIn("https://github.com/owner/repo/actions/runs/123", payload["content"])

    def test_http_error_fails_without_printing_webhook(self):
        error = HTTPError(self.env["DISCORD_WEBHOOK_URL"], 404, "Not Found", {}, None)
        with patch.dict(os.environ, {**self.env, "GATE_STATUS": "FAILED"}, clear=True):
            with patch("urllib.request.urlopen", side_effect=error):
                with patch("sys.stderr") as stderr:
                    self.assertEqual(load_notifier().main(), 1)
        output = "".join(str(call) for call in stderr.write.call_args_list)
        self.assertIn("404", output)
        self.assertNotIn(self.env["DISCORD_WEBHOOK_URL"], output)

    def test_invalid_webhook_fails_without_printing_its_value(self):
        with patch.dict(os.environ, {**self.env, "GATE_STATUS": "FAILED"}, clear=True):
            with patch("urllib.request.Request", side_effect=ValueError(self.env["DISCORD_WEBHOOK_URL"])):
                with patch("sys.stderr") as stderr:
                    self.assertEqual(load_notifier().main(), 1)
        output = "".join(str(call) for call in stderr.write.call_args_list)
        self.assertNotIn(self.env["DISCORD_WEBHOOK_URL"], output)


if __name__ == "__main__":
    unittest.main()
