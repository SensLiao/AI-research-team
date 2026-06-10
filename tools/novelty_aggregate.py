"""Deterministic novelty aggregator for the DISCOVER-stage novelty-scorer agent.

Assigns a novelty score and feasibility signal to every classified gap — SCORE-ONLY,
never a cut or filter.  This enforces the novelty-paradox guard from the contract:
every input gap receives a score and NONE are dropped, regardless of how low the
novelty estimate is.

Design principles:
  - novelty is derived from the NUMBER of distinct named signals in ``derived_from``
    relative to a soft ceiling, producing a value in [0, 1].
  - feasibility_signal is derived from the gap_type and optional signal counts,
    producing a value in [0, 1].  No domain number is hardcoded; defaults are neutral (0.5).
  - Same input dict → same output float (reproducible ordering via sorted()).
  - Returns a score for EVERY gap; never drops or filters any entry.

Signal → novelty mapping:
  The novelty score for a gap is:  min(n_signals / NOVELTY_CEIL, 1.0)
  where n_signals = len(set(derived_from)) and NOVELTY_CEIL = 4.
  A gap with 1 signal → 0.25, 2 → 0.50, 3 → 0.75, 4+ → 1.0.
  The single-signal case (n=1) deliberately produces a LOW (0.25) novelty score to prove
  that low-novelty gaps are retained in the output (novelty-paradox guard).

Feasibility signal defaults by gap_type (profile-overridable in future extension):
  stated_open_problem  → 0.6  (author stated it; direction is known)
  methodological_gap   → 0.7  (technique gap; reuse of existing framework likely)
  coverage_gap         → 0.5  (neutral; depends on data availability)
  transfer_gap         → 0.55 (moderate; cross-domain effort uncertain)
  assumption_gap       → 0.45 (harder; requires rethinking core assumptions)
  evidence_gap         → 0.65 (likely addressable by running more experiments)
  empirical_gap        → 0.60 (testable once dataset/condition is available)
  (unknown / missing)  → 0.5  (neutral default; never crashes)

Pure function: no I/O, no network, no LLM.  Deterministic on the same input.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Soft ceiling: n_signals at or above this value saturates novelty to 1.0.
_NOVELTY_CEIL: int = 4

# Default feasibility signal per gap_type.  Profile-driven extension: pass a profile
# with a ``feasibility_defaults`` dict to override these without changing the code.
_FEASIBILITY_DEFAULTS: Dict[str, float] = {
    "stated_open_problem": 0.6,
    "methodological_gap": 0.7,
    "coverage_gap": 0.5,
    "transfer_gap": 0.55,
    "assumption_gap": 0.45,
    "evidence_gap": 0.65,
    "empirical_gap": 0.60,
}

_FEASIBILITY_FALLBACK: float = 0.5

# Deterministic provenance bridge: a gap emitted by gap-classifier always carries a reason_code.
# Map it to a provenance signal so the novelty-scorer derives derived_from from gap_classification
# ALONE — no runtime re-injection of upstream signal dicts, no agent prose (HARD RULE 3). Explicit
# cross-hunter signals carried on the gap (derived_from) merge in for richer multi-signal novelty.
_REASON_TO_SIGNAL: Dict[str, str] = {
    "FW_STATED": "future_work",
    "XFER_BIND": "transfer_potential",
    "ASSUMPTION": "contrarian_angle",
    "WEAK_LOCUS": "weakness_opportunity",
    "WHITESPACE": "white_space_present",
    "UNDER_EVIDENCED": "under_evidenced",
    "UNTESTED_SETTING": "empirically_untested",
}


def _provenance(gap: dict) -> List[str]:
    """Deterministic provenance signals for a gap: explicit cross-hunter ``derived_from``
    (order-preserving, de-duplicated) PLUS the classifier ``reason_code``'s signal tag. Because a
    gap from gap_classification always has a reason_code, a classified gap always yields >=1 signal
    WITHOUT any agent prose. A gap with neither an explicit ``derived_from`` nor a known reason_code
    yields ``[]`` — legitimately novelty 0.0 (a zero-signal gap stays representable, never cut)."""
    sigs: List[str] = list(dict.fromkeys(gap.get("derived_from", []) or []))
    rc = gap.get("reason_code")
    tag = _REASON_TO_SIGNAL.get(rc) if isinstance(rc, str) else None
    if tag and tag not in sigs:
        sigs.append(tag)
    return sigs


def _compute_novelty(derived_from: List[str]) -> float:
    """Derive novelty from the count of distinct named signals.

    Args:
        derived_from: List of signal name strings (may contain duplicates; set is taken).

    Returns:
        Float in [0, 1].  min(n_distinct / NOVELTY_CEIL, 1.0).
    """
    n_distinct = len(set(derived_from))
    return min(n_distinct / _NOVELTY_CEIL, 1.0)


def _compute_feasibility(gap: dict, profile: Optional[dict]) -> float:
    """Derive the feasibility signal from the gap's type and optional profile overrides.

    Args:
        gap: A gap dict (must have at minimum a ``gap_type`` key).
        profile: Optional domain profile.  If it carries a ``feasibility_defaults``
                 dict, those values override _FEASIBILITY_DEFAULTS for the gap_type.

    Returns:
        Float in [0, 1].
    """
    gap_type: str = gap.get("gap_type", "")

    # Profile-driven override (optional extension; safe if key absent)
    profile_defaults: Dict[str, float] = {}
    if isinstance(profile, dict):
        profile_defaults = profile.get("feasibility_defaults", {})

    base = profile_defaults.get(gap_type, _FEASIBILITY_DEFAULTS.get(gap_type, _FEASIBILITY_FALLBACK))
    # Clamp to [0, 1] for safety
    return max(0.0, min(1.0, float(base)))


def aggregate_novelty(
    gaps: List[dict],
    signals: Optional[dict] = None,
    profile: Optional[dict] = None,
) -> dict:
    """Compute a novelty_score payload for every gap — SCORE-ONLY, drops NONE.

    This is the primary entry point for the novelty-scorer agent.  It returns one
    score entry per input gap.  A gap with low novelty still appears in the output;
    the caller (and only the director via /idea-bet) decides what to act on.

    Args:
        gaps: List of gap dicts.  Each should carry:
              - ``gap_id`` (str): identifies the gap being scored.
              - ``gap_type`` (str): the 7-type enum from gap_classification.
              - ``derived_from`` (list of str): named signals that distinguish this gap.
              - ``evidence_ref`` (list of str, minItems 1): anti-slop pointer.
              Any missing keys are handled gracefully (score still produced).
        signals: Optional supplementary named signals per gap: ``{gap_id: [signal, ...]}``.
                 Absorption wave 1 wires the live-retrieval grounding signal through here —
                 ``paper_search.no_semantic_neighbor_found`` adds ``"no_semantic_neighbor_found"``
                 for a gap whose search query surfaced no semantically-near title (a positive,
                 retrieval-grounded novelty signal). Extra signals MERGE into the gap's
                 provenance (order-preserving, de-duplicated); they never replace it and never
                 cut anything. Default None keeps the pre-wave-1 behaviour byte-identical.
        profile: Optional domain profile (passed to _compute_feasibility).

    Returns:
        A dict conforming to novelty_score.schema.json with a ``scores`` list containing
        exactly one entry per input gap (stable order: same as input).
    """
    scores: List[dict] = []

    for gap in gaps:
        gap_id: str = str(gap.get("gap_id", ""))
        derived_from: List[str] = _provenance(gap)   # explicit signals + reason_code bridge
        for extra in (signals or {}).get(gap_id, []) or []:
            if isinstance(extra, str) and extra.strip() and extra not in derived_from:
                derived_from.append(extra)           # wave-1 injection point (e.g. retrieval grounding)
        evidence_ref: List[str] = list(gap.get("evidence_ref", []))

        novelty: float = _compute_novelty(derived_from)
        feasibility: float = _compute_feasibility(gap, profile)

        score_entry: dict = {
            "gap_id": gap_id,
            "novelty": novelty,
            "feasibility_signal": feasibility,
            "derived_from": derived_from,
            "evidence_ref": evidence_ref,
        }
        scores.append(score_entry)

    return {"scores": scores}
