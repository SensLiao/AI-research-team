---
description: "HUMAN GATE: approve or reject one staged AERS reference. Never grants execution or vault write."
argument-hint: "--registry <path> --review-id <id> --decision approve|reject --reviewed-by <name> --decision-note <note> --confirm-review-id <id>"
allowed-tools: Bash, Read
disable-model-invocation: true
---

# /aers-reference-approve - Human AERS Reference Gate

```powershell
python -m research_agent_teams.operate aers-reference-approve `
  --registry <registry.json> `
  --review-id <aers-review-id> `
  --decision approve `
  --reviewed-by director `
  --decision-note "approved as reference-only for this run" `
  --confirm-review-id <aers-review-id>
```

Approval is reference-only. It never enables external execution, child skill
body reads, or vault writes.
