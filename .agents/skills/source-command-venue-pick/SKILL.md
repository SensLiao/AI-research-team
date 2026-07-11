---
name: "source-command-venue-pick"
description: "Director-only human gate — choose ONE target venue from the ranked venue_candidates. The model never self-picks a venue."
---

# source-command-venue-pick

Use this skill when the user asks to run the migrated source command `venue-pick`.

## Command Template

# /venue-pick — Director Gate (human-only)

> Full spec & invariants: `research_agent_teams/gates/venue-pick.md`.
> `disable-model-invocation: true` — only the director runs this.

1. Open `runs/<run-id>/evidence/VERIFY/venue-candidates.artifact.json`.
2. Review the ranked candidates and pick exactly ONE `venue_id` to target. The `venue_candidates` schema
   has no `selected`/`chosen`/`picked` field — the machine cannot have pre-chosen.
3. Record your choice as an `adr` (this gate is the SOLE writer of the venue choice). The chosen venue then
   drives `venue-selector`'s C path (it instantiates that venue's rubric into a `venue_profile` scorecard).
