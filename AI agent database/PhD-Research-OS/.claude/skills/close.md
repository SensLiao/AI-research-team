---
name: close
description: "Refresh 00-system/hot.md at end of session so next session starts without recap"
when_to_use: "Run at end of any session where new ingests, decisions, or major analyses happened. Also after a major result lands or scope changes."
usage: "/close"
---

# /close

End-of-session ritual. Refreshes `00-system/hot.md` from recent log entries.

## Procedure

1. Read current `00-system/hot.md`.
2. Run `python 06-scripts/close_day.py` — prints suggested refresh from recent log.
3. Read `07-logs/log.md` entries since the last `CLOSE` line.
4. Read any new wiki pages mentioned in those log entries (follow `INGEST [[slug]]` references).
5. Identify what has changed:
   - New facts / ingests / results / decisions
   - Scope changes
   - Open questions surfaced
   - Contradictions flagged but unresolved
6. Rewrite `00-system/hot.md` in full:
   - Keep section structure (Project status / Must-read / Next active task / Recently landed / Open questions / Hard rules)
   - Update with confirmed new facts; **delete outdated** facts (it's a state snapshot, not a log)
   - Total length ≤500 words (soft limit 600)
   - Bump `updated:` in frontmatter
   - Use `confidence: high` only for confirmed facts
7. Append to `07-logs/log.md`:
   ```
   - CLOSE: hot.md refreshed. Changes: <brief>. Open questions: <N>.
   ```

## Output

`hot.md refreshed. {N} changes captured, {N} open questions noted.`

## Rules

- hot.md is a **state snapshot**, not a session narrative. Replace outdated sections; don't append history.
- If nothing changed this session: update the date and confirm: "hot.md unchanged — no new facts this session."
- Do not embed long quotes from raw sources — hot.md points at wiki pages; wiki pages point at raw.
