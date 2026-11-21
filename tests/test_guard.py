import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cc_guard", ROOT / "scripts/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.transcript = self.root / "transcript.jsonl"
        self.rows = [
            {"uuid": "u1", "message": {"role": "user", "content": "inspect file"}},
            {"uuid": "a1", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "PRIVATE_REASONING"},
                {"type": "text", "text": "read file"},
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat a.py"}}]}},
            {"uuid": "r1", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "missing"}]}}]
        self.transcript.write_text("\n".join(json.dumps(r) for r in self.rows + [self.rows[1]]))
        self.event = {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(self.root),
                      "transcript_path": str(self.transcript), "tool_name": "Bash",
                      "tool_use_id": "t1", "tool_input": {"command": "cat a.py"}}
        self.env = patch.dict(os.environ, {"UNCERTAINTY_GUARD_CONFIG": str(self.root / "config.json"),
                                          "UNCERTAINTY_GUARD_AUDIT": str(self.root / "audit.jsonl"),
                                          "UNCERTAINTY_GUARD_NONINTERACTIVE": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_transcript_mapping_and_dedup(self):
        steps, goal = guard.transcript_steps(self.event, guard.DEFAULTS)
        self.assertEqual(goal, "inspect file")
        self.assertEqual([s["role"] for s in steps], ["user", "assistant", "environment"])
        self.assertEqual(steps[1]["tool_calls"][0]["name"], "bash")
        self.assertEqual(steps[2]["observation"], "[error] missing")
        self.assertNotIn("PRIVATE_REASONING", json.dumps(steps))

    def test_pending_call_appended_once(self):
        event = self.event | {"tool_use_id": "t2", "tool_name": "Write", "tool_input": {"file_path": "b.py"}}
        steps, _ = guard.transcript_steps(event, guard.DEFAULTS)
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[-1]["tool_calls"][0]["name"], "write")

    def test_queued_prompt_before_first_user_flush(self):
        self.transcript.write_text(json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "inspect file"}))
        steps, goal = guard.transcript_steps(self.event, guard.DEFAULTS)
        self.assertEqual(goal, "inspect file")
        self.assertEqual([s["role"] for s in steps], ["user", "assistant"])
        self.transcript.write_text(self.transcript.read_text() + '\n' + json.dumps(self.rows[0]))
        steps, _ = guard.transcript_steps(self.event, guard.DEFAULTS)
        self.assertEqual(sum(s["role"] == "user" for s in steps), 1)

    def test_high_risk_ordinary_action_is_audit_only(self):
        output, record = guard.decision(self.event, {"tau_score": 2}, guard.DEFAULTS)
        self.assertEqual(output, {})
        self.assertEqual(record["kind"], "audit")

    def test_sensitive_confirm_and_noninteractive_deny(self):
        event = self.event | {"tool_input": {"command": "RM -RF /tmp/test"}}
        output, _ = guard.decision(event, {"tau_score": 2}, guard.DEFAULTS)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")
        with patch.dict(os.environ, {"UNCERTAINTY_GUARD_NONINTERACTIVE": "1"}):
            output, record = guard.decision(event, {"tau_score": 2}, guard.DEFAULTS)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(record["kind"], "blocked")

    def test_auto_block_and_strict_write(self):
        output, record = guard.decision(self.event, {"tau_score": 0.8}, guard.DEFAULTS | {"autoBlockThreshold": 0.7})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(record["kind"], "auto-block")
        output, _ = guard.decision(self.event | {"tool_name": "Write"}, {"tau_score": 2}, guard.DEFAULTS | {"strictMode": True})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_invalid_config_is_fail_open_with_error_evidence(self):
        (self.root / "config.json").write_text('{"highThreshold": -1}')
        self.assertEqual(guard.handle(self.event), {})
        audit = json.loads((self.root / "audit.jsonl").read_text())
        self.assertEqual(audit["kind"], "error")
        self.assertIn("highThreshold", audit["error"])

    def test_standalone_hook_real_scorer(self):
        target = self.root / "standalone"
        shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__", ".venv"))
        run = subprocess.run([sys.executable, str(target / "scripts/guard.py")], cwd=self.root,
                             input=json.dumps(self.event), text=True, capture_output=True, check=True, timeout=15)
        self.assertEqual(json.loads(run.stdout), {})
        audit = json.loads((self.root / "audit.jsonl").read_text())
        self.assertEqual(audit["kind"], "audit")
        self.assertIsInstance(audit["score"], (int, float))
        self.assertGreater(audit["numSteps"], 0)
        self.assertNotIn("command", audit)


if __name__ == "__main__":
    unittest.main()
