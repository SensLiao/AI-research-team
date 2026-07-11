---
description: "Recompute claimed metrics from run records, result rows, run journal, and live hash manifest."
argument-hint: "--run-records <json> --result-artifact <json> --hash-manifest <json> --journal <json>"
allowed-tools: Bash, Read
---

# /numeric-benchmark - Evidence-First Metric Verification

```powershell
python -m research_agent_teams.operate numeric-benchmark `
  --run-records <run-records.json> `
  --result-artifact <result-rows.json> `
  --hash-manifest <hash-manifest.json> `
  --journal <journal.json> `
  --required-path <remote/result/path> `
  --out <report.json>
```

The adapter does not trust prose summaries; missing evidence or metric mismatch
returns `BLOCK`.
