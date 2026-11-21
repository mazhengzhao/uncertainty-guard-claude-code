# uncertainty-guard for Claude Code

A self-contained Claude Code plugin adapting the pi uncertainty-guard policy to
`PreToolUse` hooks. It uses the same bundled RUPA `trajectory_tau` scoring source
and thresholds. No Agent-Confidence checkout, model API key, Harbor package, or
decision-model endpoint is required by the hook itself.

**Version 0.1.0.** Author: [Zhengzhao Ma](https://github.com/mazhengzhao).
MIT licensed. See
[CHANGELOG](CHANGELOG.md) and [publishing instructions](PUBLISHING.md).

## Install and load

Requirements: Claude Code with local `--plugin-dir` and command hooks (tested on
**2.1.296**), Python **3.10+**, NumPy, and Linux/macOS (`fcntl` is used for audit
locking). Native Windows is not validated.

Install from the GitHub-hosted plugin marketplace:

```bash
python3 -m venv "$HOME/.local/share/uncertainty-guard/venv"
export UNCERTAINTY_GUARD_PYTHON="$HOME/.local/share/uncertainty-guard/venv/bin/python"
"$UNCERTAINTY_GUARD_PYTHON" -m pip install 'numpy>=1.24,<3'
claude plugin marketplace add mazhengzhao/uncertainty-guard-claude-code
claude plugin install uncertainty-guard@agent-confidence-plugins
```

This is an independently hosted marketplace. Official Claude directory listing
is a separate review process. To use a source checkout or extracted release:

```bash
# Run from the extracted plugin root; keep this interpreter after installing.
python3 -m venv "$HOME/.local/share/uncertainty-guard/venv"
export UNCERTAINTY_GUARD_PYTHON="$HOME/.local/share/uncertainty-guard/venv/bin/python"
"$UNCERTAINTY_GUARD_PYTHON" -m pip install -r requirements.txt
"$UNCERTAINTY_GUARD_PYTHON" scripts/doctor.py
claude plugin validate "$PWD"
claude --plugin-dir "$PWD"
```

Alternatively install from the independent local marketplace:

```bash
claude plugin marketplace add "$PWD"
claude plugin install uncertainty-guard@agent-confidence-plugins
```

Choose either marketplace installation or `--plugin-dir` for a session.
The bundled marketplace points at this plugin's root; the parent research
repository is not required. Persist `UNCERTAINTY_GUARD_PYTHON` in your shell or
launcher. Hooks require this interpreter even when installed from a marketplace.
See [PUBLISHING.md](PUBLISHING.md) for marketplace maintenance and directory submission.

The plugin manifest is `.claude-plugin/plugin.json`, and `hooks/hooks.json` is
loaded automatically by Claude Code. Keep these directories at the plugin root.
Do not run with `--bare`, which skips hooks. The plugin does not change your
Claude Code authentication, provider or user-level settings.

Configuration defaults match the pi package. Copy
`uncertainty-guard.example.json` to your project's
`.claude/uncertainty-guard.json`, or set `UNCERTAINTY_GUARD_CONFIG` to an absolute
JSON path. Choose Python with the environment variable above (not `pythonBin`
in this adapter's JSON). Defaults are medium=0.6, high=1.2, auto-block disabled,
strict mode off, last 40 steps, and 2000 characters per step.

## Policy and audit

The hook reads the current transcript, maps text/tool calls/results into RUPA
steps, and scores them locally before the next tool call. Private thinking blocks
are omitted, matching the pi adapter. Missing pending tool calls are appended
once, matched by tool-use ID. Transcript messages are deduplicated by UUID.
If the first user message has not yet been flushed, the queued prompt supplies
the goal until the regular user message is available, without duplicating it.

| Situation | Hook output |
| --- | --- |
| Low/medium risk or nonsensitive high risk | Audit only; no permission override |
| High-risk sensitive operation | `permissionDecision=ask` |
| Same situation with `UNCERTAINTY_GUARD_NONINTERACTIVE=1` | `permissionDecision=deny` |
| Auto-block threshold reached | `permissionDecision=deny` |
| Scorer unavailable/error | Fail open, write error audit and stderr warning |

`Bash`, `Read`, `Write`, `Edit`, `MultiEdit`, and `NotebookEdit` are mapped to the pi tool
categories. Other tools are still scored and audited. The default sensitive
patterns are case-insensitive substrings, not a shell parser or security policy.
In headless evaluations, explicitly set `UNCERTAINTY_GUARD_NONINTERACTIVE=1` to
avoid unresolved human confirmation. Audit-only calls do not force an `allow`,
so they preserve Claude Code's normal permission checks.

Audit JSONL defaults to `.claude/uncertainty-guard/audit.jsonl` under the working
directory. Override with `UNCERTAINTY_GUARD_AUDIT`. Records include session ID,
tool-use ID, score, level, decision kind, number of steps and hook latency; tool
arguments and prompts are not copied into the audit. Concurrent writes use a
file lock. Full trajectory text is only read locally from Claude Code's own
transcript. RUPA scores are heuristic risk signals, not calibrated probabilities.

Unlike pi's persistent bridge, Claude Code starts a Python hook process for each
tool invocation. The runtime enforces a 10-second hook timeout; the default
5-second scoring budget is checked before applying any decision. Timeouts and
runtime-level hook failures can bypass the adapter, so a benchmark must verify
that tool calls produced successful audit records. Transcript layouts and
permission prompts differ between harnesses; this is a policy adaptation,
not a claim that CC and pi will receive identical trajectories or permissions.

## Verify, update and remove

The offline `scripts/doctor.py` command must return `"ok": true`. It invokes the
actual hook and scorer with a synthetic transcript in a temporary directory;
it does not contact a model or change the project's audit file. After a real
Claude Code tool call, check the project's audit JSONL for a new `kind: audit`
record with a finite score. A successful model response alone does not verify
that Claude Code has loaded the hook.

Use `claude plugin update uncertainty-guard@agent-confidence-plugins` to update
an installed marketplace plugin, or
`claude plugin uninstall uncertainty-guard@agent-confidence-plugins` to remove
it. For `--plugin-dir`, simply omit that option on the next launch. Uninstalling
does not erase project audit records; manage those according to your needs.

## Test and distribute

```bash
python3 -m unittest discover -s tests
claude plugin validate "$PWD" --strict
```

Copy this entire directory to distribute locally. Its only Python dependency is
NumPy. Do not include `.venv`, `__pycache__`, sessions, user settings, or API keys.
For a local marketplace, place this plugin directory beside a marketplace JSON
entry with `source` pointing at it; the repository's `plugins/.claude-plugin/marketplace.json`
provides a working example. Local `--plugin-dir` loading requires no marketplace.

The bundled scoring source is unmodified from the research repository; see
`THIRD_PARTY_NOTICES.md` and `vendor/LICENSE.tau2`. The hook adapter is MIT-licensed.
