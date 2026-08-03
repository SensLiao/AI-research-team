# Vendored upstream research-skill text — read-only reference

> Not ours. Not runnable. Not the machine's capability surface.
> Every number about this tree lives in [`MANIFEST.json`](MANIFEST.json) — read it there, never from
> this page, so a stale sentence here can never mislead anyone.

## What this is

The **text** of eight third-party research-skill repositories, pinned to the commits recorded in
`research_agent_teams/orchestrator/external_research_skill_sources.json` and fetched by
`tools/vendor_upstream_skills.py`. It exists so an agent in this machine can read what an upstream
skill *actually says*, instead of relying on our clean-room summaries in
`orchestrator/research_capability_overlays.json`.

It is **reference material**, not capability. The machine's own capabilities are still exactly the
modes in `orchestrator/mode_registry.yaml` and the agents in `agents/`. Nothing here is loaded,
dispatched, or executed, and nothing here is in the workbench index — a search over the machine's
knowledge does not return third-party text.

## Why it cannot run — structural, not a promise

The copy allowlist admits **markdown and license notices only**, scoped to *skill bundles* (a
directory containing a `SKILL.md`, and everything below it). Consequently this tree contains no
`.py`, `.js`, `.sh`, no `plugin.json` / marketplace manifest, no hook definition, no MCP server
config, and no installer. There is nothing here to execute or auto-load, and nothing that can
auto-update. `tests/test_vendor_upstream_skills.py` asserts that property on the real tree.

## What was deliberately left out, and why

- **`icebird1998/drawio-scientific-illustrator` — excluded entirely.** Rejected on safety grounds in
  the 2026-07-31 audit, not on preference: its route drives a live CDP-controlled browser, duplicating
  a safer offline path. It stays `selectable: false` in the source lock, and the overlay-catalog
  validation still fails if any overlay references it.
- **Everything outside a skill bundle** — an upstream repo's own `docs/`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `.github/` templates, and in one case several hundred files of the upstream's own
  eval run logs. Those are someone else's working notes. The count and total bytes of what was skipped
  are recorded per source in `MANIFEST.json` (`sources[].skipped`) — a bounded copy that hides what it
  dropped would read as "we took everything".
- **Every non-text file**, per the allowlist above.

## Governance record

Director decision 2026-08-04 on ledger `D5` ("really mount the upstream repos"). Of the five safety
decisions listed in `_design/RESEARCH-WORKBENCH-V4-LEDGER.md` §5, this reverses **two**:

| §5 item | Status |
|---|---|
| 1 — third-party files enter the repo tree | **reversed** (that is this directory) |
| 2 — mounting implies running installers / hooks / MCP / auto-update | **kept** — none is fetched or run |
| 3 — the drawio CDP source was rejected on safety grounds | **kept** — excluded |
| 4 — license findings recorded, not a veto | noted; license text vendored per source |
| 5 — the verifiable clean-room "no exact copy" property | **reversed** — it ends here, by design |

## Licenses / attribution

Per-source license status, SPDX id and `attribution_required` flag are in `MANIFEST.json`; each
source's own `LICENSE` / `NOTICE` file is vendored beside its text. Two findings from the audit are
recorded rather than treated as blockers, per the director's standing position that licenses are moot
for personal, local Route A use: `academic-research-skills` is **CC BY-NC 4.0** (non-commercial), and
`agent-research-skills` asserts **no license at all** (`NOASSERTION` — no grant either way).

## Re-verify or refresh

```bash
# offline: re-hash every file against the manifest and report anything unlisted
python -m research_agent_teams.tools.vendor_upstream_skills verify

# online: re-fetch at the pinned commits (wipes and rebuilds this tree)
python -m research_agent_teams.tools.vendor_upstream_skills fetch --retrieved-at YYYY-MM-DD
```

`fetch` re-checks the audit's 43 per-file SHA-256 receipts against what upstream serves today. A
source whose receipts no longer match is **BLOCKED and not copied**: upstream content changing under a
pinned commit is precisely the case where quietly vendoring it would be worst. Blocked sources are
listed in `MANIFEST.json.blocked` and make the command exit non-zero.
