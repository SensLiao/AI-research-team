---
name: ghost
description: "Surface orphan pages, broken links, stubs, missing source, stale low-confidence — vault health check"
when_to_use: "Run after a batch INGEST or weekly. Report-only — never auto-deletes."
usage: "/ghost"
---

# /ghost

Vault health check. Report-only. Never auto-fix, never delete.

## Procedure

1. Run `python 06-scripts/lint_vault.py` to get the structured report.
2. Group by check class (orphans, broken links, stubs, etc.).
3. Compile the report (see Output format below).
4. Append a `LINT:` entry to `07-logs/log.md`:
   ```
   - LINT: <N> errors, <N> warnings. <one-line summary of top categories>.
   ```

## Output format

```
## Ghost / Lint Report — YYYY-MM-DD

### Errors (N)
- [<code>] [[slug]] — <detail>

### Warnings (N)
- [<code>] [[slug]] — <detail>

### Recommendations
- Per-category quick fixes (e.g., "5 orphan pages — link from index or delete with status: deprecated")
```

## Rules

- Never delete pages — only report.
- Templates and meta-docs are intentionally excluded from orphan checks (the lint script handles this).
- For citation-gate violations: NEVER manually flip `can-cite-thesis`; fix the underlying audits.
