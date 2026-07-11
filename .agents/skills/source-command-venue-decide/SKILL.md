---
name: "source-command-venue-decide"
description: "Director-only human gate — the publish / iterate / pivot decision from the venue_readiness_verdict. The model never decides to publish or to pivot."
---

# source-command-venue-decide

Use this skill when the user asks to run the migrated source command `venue-decide`.

## Command Template

# /venue-decide — Director Gate (human-only)

> Full spec & invariants: `research_agent_teams/gates/venue-decide.md`.
> `disable-model-invocation: true` — only the director runs this.

1. Open `runs/<run-id>/evidence/VERIFY/venue-readiness-verdict.artifact.json`. The verdict
   (`MEETS-BAR` / `BORDERLINE` / `NOT-YET` / `WRONG-PATH` / `DEGRADED-REVIEW`) is DERIVED mechanically by
   `venue_score.py` — it carries no `status` and authorizes no action.
2. Decide what to actually DO: publish / add experiments / change methods / pivot. This is the crown-jewel
   red line — a more capable model still does not get to publish its own work or kill its own direction.
3. Record the decision as an `adr` (this gate is the SOLE writer of the publish/iterate/pivot decision).
