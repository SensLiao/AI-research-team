---
type: readme
updated: 2026-05-01
---

# 06-scripts/ — vault integrity + automation scripts

> Python scripts that enforce the vault contract. Without these, the schema is just convention; with them, schema violations block commits.

## Scripts

| Script | Purpose | Exit code on failure |
|---|---|---|
| `bootstrap.py` | One-time vault instantiation from `bootstrap-intake.yml` | 1 |
| `lint_vault.py` | Full vault lint: 9 checks; pre-commit + CI | 1 |
| `check_citation_gate.py` | Fast standalone check: `can-cite-thesis` consistency | 1 |
| `render_claim_chain.py` | Render a synthesis page's `claim-chain:` into a draft thesis section | 2 if blocked |
| `close_day.py` | Print suggested hot.md refresh from recent log entries | 0/1 |

## Dependencies

```bash
pip install python-frontmatter pyyaml
```

Or use a project-level `requirements.txt` / `pyproject.toml`.

## Pre-commit setup

```bash
pip install pre-commit
pre-commit install
# now lint_vault.py runs automatically on every git commit
```

## CI integration

GitHub Actions example (`.github/workflows/lint.yml`):

```yaml
name: Vault lint
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install python-frontmatter pyyaml
      - run: python 06-scripts/lint_vault.py
      - run: python 06-scripts/check_citation_gate.py
```

## Adding a new script

1. Document the script's purpose, inputs, and exit codes in its module docstring
2. Add a row to the table above
3. If the script enforces a rule, add it to `.pre-commit-config.yaml`

## Anti-pattern

Don't write scripts that **modify** vault frontmatter without a `--dry-run` flag and a confirmation prompt. The lint script is read-only by design — agents should make changes, not bulk-mutating scripts.
