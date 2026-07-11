# Internal AERS Catalog Snapshot

This directory is the RAT-owned, metadata-only snapshot of the
Auto-Empirical-Research-Skills catalog.

It exists so `research_agent_teams` can keep its AERS-informed governance layer
working after the external `Auto-Empirical-Research-Skills/` checkout is
deleted.

## What Is Stored

- `skills-enriched.json`
- `provenance.json`
- `skill-audit.json`
- `path-existence-overrides.json`

These files are catalog metadata only. RAT does not copy, load, or execute child
AERS `SKILL.md` bodies by default.

## How It Is Used

`research_agent_teams.tools.aers_catalog_router` defaults to this directory.
Explicit callers may still pass `--aers-root <path>` to point at a full upstream
AERS checkout for refresh or compatibility audits.

## Boundaries

- No AERS reference is executable by default.
- No AERS metadata writes `PhD-Research-OS`.
- `review_required` candidates still need `/aers-reference-approve`.
- `do_not_use` candidates remain blocked.
