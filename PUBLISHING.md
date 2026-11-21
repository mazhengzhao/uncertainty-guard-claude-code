# Publishing uncertainty-guard for Claude Code

Plugin: `uncertainty-guard`, version 0.1.0.
Repository: https://github.com/mazhengzhao/uncertainty-guard-claude-code.
Marketplace: `agent-confidence-plugins`. Publishing the GitHub marketplace and
submitting to the official directory are separate actions.

## Independent repository layout

Extract the source archive or ZIP and use its `uncertainty-guard-claude-code/`
directory as the repository root. Include hidden `.claude-plugin/` and
`.github/` directories. `plugin.json` describes the plugin; `marketplace.json`
lists that same root using `source: "./"`. Hooks stay in `hooks/hooks.json` and
are automatically discovered. Do not add a second copy of the hook manifest
to `plugin.json`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export UNCERTAINTY_GUARD_PYTHON="$PWD/.venv/bin/python"
"$UNCERTAINTY_GUARD_PYTHON" scripts/doctor.py
"$UNCERTAINTY_GUARD_PYTHON" -m unittest discover -s tests
claude plugin validate "$PWD" --strict
claude plugin marketplace add "$PWD"
claude plugin install uncertainty-guard@agent-confidence-plugins
```

Use a persistent absolute Python path. Local installation can also use
`claude --plugin-dir "$PWD"`. Do not combine both loading methods in one
session. The companion monorepo marketplace shares the same name; remove its
registration before testing this independent marketplace. Use a temporary
`CLAUDE_CONFIG_DIR` to avoid touching normal Claude Code configuration during
an installation test.

## Public release and self-hosted marketplace

1. Create or verify the public GitHub repository and its URLs. Push only
   reviewed plugin source, tests and docs. Keep both license files and notices.
2. Run CI, strict manifest validation, the local self-check and a real tool-call
   audit check. CI validates structure and local scoring; it does not call a
   model or establish public-directory approval.
3. Tag `v0.1.0`, create a release with source archives and SHA-256 checksums.
   Keep the plugin and marketplace versions synchronized for future updates.
4. Once the repository exists, users can install with:

   ```bash
   claude plugin marketplace add mazhengzhao/uncertainty-guard-claude-code
   claude plugin install uncertainty-guard@agent-confidence-plugins
   ```

Marketplace installation does not install Python/NumPy. Users must first
prepare their persistent interpreter as described in README.

## Optional official-directory submission

Submit through https://claude.ai/directory/manage after the repository and
installation documentation are public. The current portal requires an eligible
paid Claude account/role and connected GitHub account with write permission.
Do not submit a pull request to `claude-plugins-official` to request listing.

Use this description in the submission:

> Local RUPA trajectory risk auditing and optional tool-call gating for Claude
> Code. Reads the current session transcript, scores with Python/NumPy, and
> records a local audit before tool calls. No external decision-model service
> or telemetry is used. Heuristic scores are not calibrated failure probabilities.

Disclose the Python command hook, separate NumPy installation, Linux/macOS
support, fail-open behavior, transcript access and local audit storage. Python
hooks may require additional review; passing `claude plugin validate --strict`
does not guarantee approval. Ship text source, not interpreter binaries,
environments or model weights. The portal's review determines listing status.

Official references:

- https://code.claude.com/docs/en/plugins/publish
- https://claude.com/docs/plugins/pre-submission-checklist
- https://claude.com/docs/plugins/submit

Author: Zhengzhao Ma, https://github.com/mazhengzhao. MIT license, with the
upstream scorer notice retained. Report issues in the source repository
with Claude/Python/NumPy versions, redacted audit errors and self-check output.
