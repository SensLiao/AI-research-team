---
description: "One-button director health panel: capability catalog, eval scorecard, and run manifest status."
argument-hint: "[--aers-root <path>] [--run-limit N] [--no-manual]"
allowed-tools: Bash, Read
---

# /scoreboard - Director Health Panel

```powershell
python -m research_agent_teams.operate scoreboard
```

Read-only: scans capability status, eval status, and run manifest metadata.
It does not read secrets, child AERS skill bodies, vault pages, or scratch
evidence payloads.

By default it uses the RAT-owned internal AERS metadata snapshot at
`research_agent_teams/agents/references/aers-catalog`. Use `--aers-root <path>`
only when deliberately auditing a fresh upstream AERS checkout.
