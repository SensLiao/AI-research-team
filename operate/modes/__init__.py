"""Per-mode operate recipes.

A recipe declares, for each stage of a mode: the LLM worker(s) to dispatch (the reading / reasoning
WORK that only a sub-agent can do, with a ready-to-use prompt) and the deterministic producers/gates
to run as plain Python (scoring, classification, hard gates). The spine drives the boundaries; the
recipe fills the WORK slot. `new_direction` was the first wired mode; absorption wave 1 (2026-06-10)
wired `evidence_review` / `evidence_deep` / `deep_research`; audit waves A-D (2026-06-13, see
_design/review/ai-capability-audit-2026-06-12.md) wired `gap_breadth` (the 5-hunter panel, really
parallel), `venue_readiness` (the mock blind-review chain) and `full_rigor_minimal` (the
DESIGN→VERIFY experiment tail with preflight/parity/sanity/goal-alignment/prereg gates live);
RAT-2 Wave-3 (2026-06-19, see _design/idea-engine/IDEA-ENGINE-LEDGER.md) wired `deep_ideation` (the
full deep-ideation chain: formalize → mechanism graph → cross-domain analogy → saturation →
contradiction → experiment sketches → idea lineage → quality scorecard + integrity + blind eval,
composed on new_direction's proven base via _deep_ideate, zero drift). Every recipe now carries the
north-star drift gate, bundle prechecks, referential integrity, the live citation-existence gate, and
`run_dets_with_repair`. Add a module here to wire another mode without touching the spine. The
registry's `operated: true` flag mirrors THIS dict (a wiring test enforces the mirror — a mode is
never claimed operable unless it really is).
"""
from . import (
    deep_ideation,
    deep_research,
    evidence_deep,
    evidence_review,
    full_rigor_minimal,
    gap_breadth,
    ingest_paper,
    manuscript_authoring,
    manuscript_review,
    new_direction,
    read_paper_deep,
    venue_readiness,
)

REGISTRY = {
    "new_direction": new_direction,
    "deep_ideation": deep_ideation,
    "evidence_review": evidence_review,
    "evidence_deep": evidence_deep,
    "deep_research": deep_research,
    "gap_breadth": gap_breadth,
    "venue_readiness": venue_readiness,
    "full_rigor_minimal": full_rigor_minimal,
    # paper-reading upgrade (2026-06-26): single-paper reading modes — record_only (reading = draft
    # knowledge; the human gate is /promote-to-vault). Hard gates fire as deterministic cores in-recipe.
    "ingest_paper": ingest_paper,
    "read_paper_deep": read_paper_deep,
    # Paper authoring and independent review are deliberately separate operated products.
    "manuscript_authoring": manuscript_authoring,
    "manuscript_review": manuscript_review,
}

__all__ = ["REGISTRY", "deep_ideation", "deep_research", "evidence_deep", "evidence_review",
           "full_rigor_minimal", "gap_breadth", "ingest_paper", "manuscript_authoring",
           "manuscript_review", "new_direction", "read_paper_deep", "venue_readiness"]
