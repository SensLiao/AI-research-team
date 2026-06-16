---
description: "Director-only human gate — bet on ONE research direction from the ranked idea_backlog (rejecting all = pivot). The model never self-bets."
argument-hint: "<run-id>"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /idea-bet — Director Gate (human-only)

> Full spec & invariants: `research_agent_teams/gates/idea-bet.md`.
> `disable-model-invocation: true` — only the director runs this; the model never self-bets.

1. Open `runs/<run-id>/evidence/IDEATE/idea-backlog.artifact.json`, or print the ranked menu:
   ```powershell
   python -m research_agent_teams.operate menu --run-id <run-id>
   ```
2. Review the ranked ideas (rank 1 = highest feasibility). Pick exactly ONE `idea_id` to bet on — or
   bet on NONE (pivot / re-scope). The `idea_backlog` schema has no `selected`/`chosen`/`bet` field,
   so the machine cannot have pre-picked.
3. Record your bet as an `adr` (this gate is the SOLE writer of the bet).
4. If you reject all directions, make the veto durable + terminal (it lands on the tamper-evident ledger):
   ```powershell
   python -m research_agent_teams.operate reject --run-id <run-id> --stage IDEATE --reason "none of these — pivot"
   ```
