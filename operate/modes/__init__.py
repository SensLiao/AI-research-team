"""Per-mode operate recipes.

A recipe declares, for each stage of a mode: the LLM worker(s) to dispatch (the reading / reasoning
WORK that only a sub-agent can do, with a ready-to-use prompt) and the deterministic producers/gates
to run as plain Python (scoring, classification, hard gates). The spine drives the boundaries; the
recipe fills the WORK slot. `new_direction` was the first wired mode (the one walked in the
first-run demo); absorption wave 1 (2026-06-10) wired three more — `evidence_review`,
`evidence_deep`, and the new `deep_research` — each carrying the bounded revise loop
(`run_dets_with_repair`, the OpenScholar draft->critique->revise shape over the machine's own
deterministic gates). Add a module here to wire another mode without touching the spine.
"""
from . import deep_research, evidence_deep, evidence_review, new_direction

REGISTRY = {
    "new_direction": new_direction,
    "evidence_review": evidence_review,
    "evidence_deep": evidence_deep,
    "deep_research": deep_research,
}

__all__ = ["REGISTRY", "new_direction", "evidence_review", "evidence_deep", "deep_research"]
