"""Per-mode operate recipes.

A recipe declares, for each stage of a mode: the LLM worker(s) to dispatch (the reading / reasoning
WORK that only a sub-agent can do, with a ready-to-use prompt) and the deterministic producers/gates
to run as plain Python (scoring, classification, hard gates). The spine drives the boundaries; the
recipe fills the WORK slot. `new_direction` was the first wired mode; absorption wave 1 (2026-06-10)
wired `evidence_review` / `evidence_deep` / `deep_research`; audit waves A-D (2026-06-13, see
_design/review/ai-capability-audit-2026-06-12.md) wired `gap_breadth` (the 5-hunter panel, really
parallel), `venue_readiness` (the mock blind-review chain) and `full_rigor_minimal` (the
DESIGN→VERIFY experiment tail with preflight/parity/sanity/goal-alignment/prereg gates live) — and
every recipe now carries the north-star drift gate, bundle prechecks, referential integrity, the
live citation-existence gate, and `run_dets_with_repair`. Add a module here to wire another mode
without touching the spine. The registry's `operated: true` flag mirrors THIS dict (a wiring test
enforces the mirror — a mode is never claimed operable unless it really is).
"""
from . import (
    deep_research,
    evidence_deep,
    evidence_review,
    full_rigor_minimal,
    gap_breadth,
    new_direction,
    venue_readiness,
)

REGISTRY = {
    "new_direction": new_direction,
    "evidence_review": evidence_review,
    "evidence_deep": evidence_deep,
    "deep_research": deep_research,
    "gap_breadth": gap_breadth,
    "venue_readiness": venue_readiness,
    "full_rigor_minimal": full_rigor_minimal,
}

__all__ = ["REGISTRY", "deep_research", "evidence_deep", "evidence_review",
           "full_rigor_minimal", "gap_breadth", "new_direction", "venue_readiness"]
