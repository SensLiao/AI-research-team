---
phase: 01-operated-ai-manuscript-authoring
plan: "16"
subsystem: manuscript-delivery
tags: [markdown, director-review, provenance, review-separation]
status: complete
completed: 2026-07-22
---

# Phase 01 Plan 16: Human-First Delivery Summary

The manuscript product now has a readable, provenance-linked report set and the top-level director packet keeps authoring self-audits separate from an independently evidenced manuscript review.

## Delivered

- Added `tools/manuscript_renderer.py`, which renders the required `director-review/manuscript/` Markdown set from validated data and hash-verifies its derived LaTeX projection.
- Added delivery regression coverage for daily status, toolchain-missing truth, evidence links, redaction, deterministic rerendering, and distinct independent-review identity.
- Extended `tools/director_packet.py` so authoring links only its overview, while a review packet links `reviewer-report.md` only after run-id, independent-review, frozen-manuscript, verdict-hash, and blind-receipt checks pass.
- Unsafe, cross-run, malformed, or secret-bearing review references fail closed without replacing the readable top-level packet.

## Verification

- `python -m pytest tests/test_manuscript_renderer.py -q` — 8 passed.
- `python -m pytest tests/test_director_packet.py tests/test_manuscript_renderer.py -q` — 22 passed.

## Task Commits

1. `a140f16` — renderer RED contract tests.
2. `160c902` — human-first manuscript renderer.
3. `6837a58` — top-level authoring/review packet routing.

## Boundaries Preserved

- Markdown remains available for usable and caveated states; it never upgrades build, submission, or scientific truth.
- `manuscript_authoring` never impersonates `manuscript_review`; the latter requires separately bound evidence.
- No vault promotion, database write, downloader, GPU execution, or autonomous submission route was introduced.

## Next Readiness

Plans 17 and 18 can consume the renderer and packet contracts to create their concrete operated authoring and review recipes.
