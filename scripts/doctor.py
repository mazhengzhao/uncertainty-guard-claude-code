#!/usr/bin/env python3
"""Offline check of dependencies and the packaged adapter; no agent/model call."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = {"ok": False, "python": sys.version.split()[0], "interpreter": sys.executable}
    started = time.perf_counter()
    try:
        if sys.version_info < (3, 10):
            raise RuntimeError("Python 3.10 or newer is required")
        import numpy
        report["numpy"] = numpy.__version__
        if not ((1, 24) <= tuple(int(v) for v in numpy.__version__.split(".")[:2]) < (3, 0)):
            raise RuntimeError("Install numpy>=1.24,<3 from requirements.txt")
        with tempfile.TemporaryDirectory(prefix="uncertainty guard check ") as directory:
            work = Path(directory)
            if (ROOT / "package.json").is_file():
                manifest = json.loads((ROOT / "package.json").read_text())
                payload = {"id": "doctor", "goal_text": "Inspect a file", "steps": [
                    {"role": "user", "content": "Inspect a file"},
                    {"role": "assistant", "content": "Read the file", "tool_calls": [
                        {"name": "read", "arguments": {"path": "example.txt"}}]}]}
                run = subprocess.run([sys.executable, str(ROOT / "bridge/server.py")],
                    input=json.dumps(payload) + "\n", text=True, capture_output=True,
                    cwd=work, check=True, timeout=15)
                response = json.loads(run.stdout)
                if "error" in response:
                    raise RuntimeError(response["error"])
                result = response["result"]
                score, steps = result["tau_score"], result["num_steps"]
            else:
                manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
                transcript = work / "transcript.jsonl"
                transcript.write_text(json.dumps({"uuid": "doctor-user", "message": {
                    "role": "user", "content": "Inspect a file"}}) + "\n")
                config = work / "config.json"
                config.write_text("{}\n")
                audit = work / "audit.jsonl"
                payload = {"hook_event_name": "PreToolUse", "session_id": "doctor",
                    "cwd": str(work), "transcript_path": str(transcript), "tool_name": "Read",
                    "tool_use_id": "doctor-read", "tool_input": {"file_path": "example.txt"}}
                env = dict(os.environ, UNCERTAINTY_GUARD_CONFIG=str(config),
                    UNCERTAINTY_GUARD_AUDIT=str(audit), UNCERTAINTY_GUARD_NONINTERACTIVE="1")
                run = subprocess.run([sys.executable, str(ROOT / "scripts/guard.py")],
                    input=json.dumps(payload), text=True, capture_output=True,
                    cwd=work, env=env, check=True, timeout=15)
                if json.loads(run.stdout) != {}:
                    raise RuntimeError("Expected an audit-only hook response")
                record = json.loads(audit.read_text())
                if record["kind"] != "audit":
                    raise RuntimeError(record.get("error", "No successful scoring audit"))
                score, steps = record["score"], record["numSteps"]
            if not math.isfinite(score) or steps < 1:
                raise RuntimeError("Scorer returned an invalid result")
            report.update(ok=True, plugin=manifest["name"], version=manifest["version"],
                          score=score, num_steps=steps)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
