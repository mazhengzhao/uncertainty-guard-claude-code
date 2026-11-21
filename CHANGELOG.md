# Changelog

## [0.1.0] - 2026-11-21

Initial standalone release.

- Claude Code `PreToolUse` adapter with bundled local RUPA scoring.
- Transcript mapping, tool-use deduplication, audit-only/ask/deny decisions,
  noninteractive mode and locked JSONL audits.
- Independent plugin and marketplace manifests, installation self-check,
  release instructions and CI.
- NumPy is installed separately; no model endpoint is required by the hook.

The scorer snapshot and default policy match the companion pi plugin.
Harness-specific transcript and permission behavior still differ; no identical
benchmark-performance claim is made.
