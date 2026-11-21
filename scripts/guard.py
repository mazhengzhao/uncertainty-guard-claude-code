#!/usr/bin/env python3
"""Claude Code PreToolUse adapter. No network calls or repository dependencies."""
from __future__ import annotations

from collections import deque
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "enabled": True, "mediumThreshold": 0.6, "highThreshold": 1.2,
    "autoBlockThreshold": None, "strictMode": False, "maxStepsForBridge": 40,
    "maxStepTextLength": 2000, "requestTimeoutMs": 5000,
    "sensitiveBashPatterns": ["rm -rf", ":(){ :|:& };:", "dd if=", "mkfs", "> /dev/sd",
                              "> /dev/nvme", "chmod -r 777 /", "chown -r", "shutdown", "reboot"],
}


def load_config(cwd):
    path = Path(os.environ.get("UNCERTAINTY_GUARD_CONFIG", Path(cwd) / ".claude/uncertainty-guard.json"))
    config = DEFAULTS | (json.loads(path.read_text()) if path.is_file() else {})
    for key in ("mediumThreshold", "highThreshold", "autoBlockThreshold"):
        value = config[key]
        if key == "autoBlockThreshold" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid {key}")
    if config["mediumThreshold"] > config["highThreshold"]:
        raise ValueError("mediumThreshold exceeds highThreshold")
    for key in ("maxStepsForBridge", "maxStepTextLength", "requestTimeoutMs"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"Invalid {key}")
    if any(type(config[key]) is not bool for key in ("enabled", "strictMode")):
        raise ValueError("enabled/strictMode must be booleans")
    if not isinstance(config["sensitiveBashPatterns"], list) or any(not isinstance(x, str) or not x for x in config["sensitiveBashPatterns"]):
        raise ValueError("Invalid sensitiveBashPatterns")
    return config


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
    return ""


def transcript_steps(event, config):
    """Map persisted CC messages, deduplicate message UUIDs, omit private thinking.

    Tool-use input may not yet be persisted when the hook fires; append it only
    when tool_use_id is absent from the transcript. Each subagent is identified
    by the hook's transcript_path/session_id, without merging unrelated sessions.
    """
    steps = deque(maxlen=config["maxStepsForBridge"])
    goal = ""
    queued_goal = ""
    seen = set()
    candidate_seen = False
    path = Path(event["transcript_path"])
    with path.open(errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # transcript may end in a partially written line
            uid = row.get("uuid")
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            # CC can flush the queued prompt before it flushes the first user
            # message. Use it only as a fallback, never duplicate a real user.
            if row.get("type") == "queue-operation" and row.get("operation") == "enqueue" and not queued_goal:
                queued_goal = text_content(row.get("content", ""))
            message = row.get("message") or {}
            role = message.get("role") or row.get("type")
            content = message.get("content", "")
            if role == "user":
                text = text_content(content)
                if text:
                    if not goal:
                        goal = text
                    steps.append({"role": "user", "content": text[:config["maxStepTextLength"]]})
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            output = text_content(item.get("content", ""))
                            prefix = "[error] " if item.get("is_error") else ""
                            steps.append({"role": "environment", "observation": (prefix + output)[:config["maxStepTextLength"]]})
            elif role == "assistant":
                step = {"role": "assistant", "content": text_content(content)[:config["maxStepTextLength"]]}
                calls = []
                for item in content if isinstance(content, list) else []:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        calls.append({"name": normalize_tool(item.get("name", "")), "arguments": item.get("input", {})})
                        candidate_seen |= bool(event.get("tool_use_id")) and item.get("id") == event["tool_use_id"]
                if calls:
                    step["tool_calls"] = calls
                steps.append(step)
    if not goal and queued_goal:
        goal = queued_goal
        steps.appendleft({"role": "user", "content": goal[:config["maxStepTextLength"]]})
    if not candidate_seen:
        steps.append({"role": "assistant", "content": "", "tool_calls": [{
            "name": normalize_tool(event.get("tool_name", "")), "arguments": event.get("tool_input", {})}]})
    return list(steps), goal


def normalize_tool(name):
    return {"Bash": "bash", "Read": "read", "Write": "write", "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit"}.get(name, name)


def score(steps, goal):
    name = "uncertainty_guard_trajectory_tau"
    spec = importlib.util.spec_from_file_location(name, ROOT / "vendor/trajectory_tau.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    result = module.calculate_trajectory_tau_score(steps, goal_text=goal)
    if not math.isfinite(result["tau_score"]):
        raise ValueError("Nonfinite trajectory risk")
    return result


def decision(event, result, config):
    value = result["tau_score"]
    level = "low" if value < config["mediumThreshold"] else "medium" if value < config["highThreshold"] else "high"
    tool = normalize_tool(event.get("tool_name", ""))
    command = str((event.get("tool_input") or {}).get("command", "")).lower()
    sensitive = (tool == "bash" and any(p.lower() in command for p in config["sensitiveBashPatterns"])) or (config["strictMode"] and tool in ("write", "edit"))
    kind = "audit"
    output = {}
    reason = f"uncertainty-guard: RUPA trajectory risk {value:.3f}; review this action and gather evidence before proceeding."
    if config["autoBlockThreshold"] is not None and value >= config["autoBlockThreshold"]:
        kind = "auto-block"
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
    elif level == "high" and sensitive:
        # A headless benchmark cannot answer a human confirmation. Match pi's
        # noninteractive rejection explicitly; interactive users see an ask.
        noninteractive = os.environ.get("UNCERTAINTY_GUARD_NONINTERACTIVE") == "1"
        kind = "blocked" if noninteractive else "confirmation-requested"
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny" if noninteractive else "ask", "permissionDecisionReason": reason}
    return ({"hookSpecificOutput": output} if output else {}), {"kind": kind, "level": level, "score": value,
        "toolName": event.get("tool_name"), "numSteps": result.get("num_steps")}


def audit(event, record):
    path = Path(os.environ.get("UNCERTAINTY_GUARD_AUDIT", Path(event.get("cwd", ".")) / ".claude/uncertainty-guard/audit.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = record | {"session_id": event.get("session_id"), "tool_use_id": event.get("tool_use_id"), "time": time.time()}
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def handle(event):
    started = time.monotonic()
    try:
        config = load_config(event.get("cwd", "."))
        if not config["enabled"] or event.get("hook_event_name") != "PreToolUse":
            return {}
        steps, goal = transcript_steps(event, config)
        output, record = decision(event, score(steps, goal), config)
        elapsed = time.monotonic() - started
        if elapsed * 1000 > config["requestTimeoutMs"]:
            raise TimeoutError("RUPA scoring exceeded requestTimeoutMs")
        audit(event, record | {"elapsed_sec": elapsed, "goalAvailable": bool(goal)})
        return output
    except Exception as error:
        # Same fail-open policy as the original pi adapter, with durable error
        # evidence so an evaluation can reject an inactive plugin.
        try:
            audit(event, {"kind": "error", "error": f"{type(error).__name__}: {error}", "elapsed_sec": time.monotonic()-started})
        except OSError:
            pass
        print(f"uncertainty-guard: {type(error).__name__}: {error}", file=sys.stderr)
        return {}


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Hook input must be an object")
    except (ValueError, TypeError) as error:
        print(f"uncertainty-guard: invalid hook input: {error}", file=sys.stderr)
        print("{}")
        return
    print(json.dumps(handle(event), ensure_ascii=False))


if __name__ == "__main__":
    main()
