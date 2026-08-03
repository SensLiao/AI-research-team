"""Deterministic gap classifier for the DISCOVER-stage gap-classifier agent.

Maps a signal dict to a ``(gap_type, reason_code)`` pair via a priority-ordered
field-presence rubric.  This turns the gap-classifier agent's golden test into a
structural guarantee: the agent calls this function; the test proves the correct
enum and reason_code are returned for every crafted signal type.

Gap types (7 types, aligned with gap_classification.schema.json enum):
  - "stated_open_problem"   Explicitly stated future work (source_ref + statement present)
  - "methodological_gap"    Identified methodological weakness (locus + opportunity)
  - "coverage_gap"          White-space / unexplored region (hole marker present)
  - "transfer_gap"          Cross-domain applicability gap (source_domain + target_hook)
  - "assumption_gap"        A challenged or untested assumption (challenged_assumption)
  - "evidence_gap"          Under-evidenced claim (under_evidenced marker)
  - "empirical_gap"         Untested condition or dataset (untested_condition marker)

Precedence order (most-specific first; first match wins):
  1. transfer_gap       — source_domain + target_hook both present (cross-domain specificity)
  2. assumption_gap     — challenged_assumption present
  3. methodological_gap — locus + opportunity both present
  4. coverage_gap       — hole OR white_space_present marker
  5. evidence_gap       — under_evidenced marker
  6. empirical_gap      — untested_condition OR untested_dataset marker
  7. stated_open_problem — statement + source_ref both non-empty (fallback explicit signal)
  default: classify_gap raises ValueError if no rule matches. build_classification RE-RAISES for any
           signal that carries a gap_id (an identified gap must never silently vanish — the dual of
           slop in the M3 risk model) and skips only un-identified noise (a signal with no gap_id).

Pure function: no I/O, no network, no LLM.  Deterministic on the same input.
"""
from __future__ import annotations

from typing import List, Optional, Tuple


SOURCE_KINDS = frozenset({
    "future_work", "weakness", "white_space", "transfer", "contrarian",
})
DERIVED_FROM_TO_SOURCE_KIND = {
    "future_work": "future_work",
    "weakness_opportunity": "weakness",
    "white_space_present": "white_space",
    "transfer_potential": "transfer",
    "contrarian_angle": "contrarian",
}


def classify_gap(signal: dict, profile: Optional[dict] = None) -> Tuple[str, str]:
    """Classify a gap signal dict into a (gap_type, reason_code) pair.

    Args:
        signal: Dict of distinguishing fields. See module docstring for keys.
        profile: Optional domain profile (unused in current rubric; reserved for
                 future profile-driven extensions without signature breakage).

    Returns:
        A ``(gap_type, reason_code)`` tuple.  gap_type is one of the 7 enum values
        in gap_classification.schema.json.  reason_code is a short non-empty string.

    Raises:
        ValueError: If no rule in the priority table matches the signal.

    Precedence (first match wins — documented in module docstring):
        1. transfer_gap        source_domain + target_hook
        2. assumption_gap      challenged_assumption
        3. methodological_gap  locus + opportunity
        4. coverage_gap        hole OR white_space_present
        5. evidence_gap        under_evidenced
        6. empirical_gap       untested_condition OR untested_dataset
        7. stated_open_problem statement + source_ref (non-empty strings)
    """
    if not isinstance(signal, dict):
        raise ValueError(f"classify_gap: signal must be a dict, got {type(signal).__name__!r}")

    # Rule 1: transfer_gap — cross-domain specificity (source + target both present)
    if _nonempty(signal.get("source_domain")) and _nonempty(signal.get("target_hook")):
        return ("transfer_gap", "XFER_BIND")

    # Rule 2: assumption_gap — a challenged or untested assumption
    if _nonempty(signal.get("challenged_assumption")):
        return ("assumption_gap", "ASSUMPTION")

    # Rule 3: methodological_gap — identified locus of weakness + opportunity
    if _nonempty(signal.get("locus")) and _nonempty(signal.get("opportunity")):
        return ("methodological_gap", "WEAK_LOCUS")

    # Rule 4: coverage_gap — white-space / unexplored region marker
    if signal.get("hole") or signal.get("white_space_present"):
        return ("coverage_gap", "WHITESPACE")

    # Rule 5: evidence_gap — under-evidenced claim marker
    if signal.get("under_evidenced"):
        return ("evidence_gap", "UNDER_EVIDENCED")

    # Rule 6: empirical_gap — untested condition or dataset
    if _nonempty(signal.get("untested_condition")) or _nonempty(signal.get("untested_dataset")):
        return ("empirical_gap", "UNTESTED_SETTING")

    # Rule 7: stated_open_problem — explicit future-work statement with source
    if _nonempty(signal.get("statement")) and _nonempty(signal.get("source_ref")):
        return ("stated_open_problem", "FW_STATED")

    raise ValueError(
        f"classify_gap: signal matches no rule in the priority table. "
        f"Signal keys present: {sorted(signal.keys())}"
    )


def build_classification(
    signals: List[dict],
    profile: Optional[dict] = None,
) -> dict:
    """Assemble a gap_classification payload from a list of signal dicts.

    Each signal must have at least:
      - a ``gap_id`` field (string, used as the gap identifier)
      - an ``evidence_ref`` field (list of non-empty strings, anti-slop)
      - sufficient fields to satisfy one classify_gap rule

    Signals that raise ValueError in classify_gap are skipped (with no side-effects).
    The output list is in the same order as the input list (stable ordering).

    Args:
        signals: List of signal dicts.  Each must carry gap_id + evidence_ref.
        profile: Optional domain profile (passed through to classify_gap).

    Returns:
        A dict conforming to gap_classification.schema.json (required fields only;
        the agent enriches with optional source_kind / notes before writing).
    """
    gaps: List[dict] = []

    for sig in signals:
        try:
            gap_type, reason_code = classify_gap(sig, profile=profile)
        except (ValueError, TypeError):
            # An IDENTIFIED gap (one carrying a gap_id) that matches no rule is a bug, not noise.
            # Fail loud so a real gap can NEVER silently vanish (the dual of slop in the M3 risk
            # model). Only un-identified noise (a signal with no gap_id) is skipped.
            gid = sig.get("gap_id") if isinstance(sig, dict) else None
            if gid:
                raise ValueError(
                    f"build_classification: signal with gap_id {gid!r} matches no classify_gap rule "
                    f"(an identified gap must never be silently dropped). "
                    f"Signal keys: {sorted(sig.keys()) if isinstance(sig, dict) else type(sig).__name__}"
                )
            continue

        gap: dict = {
            "gap_id": str(sig.get("gap_id", "")),
            "gap_type": gap_type,
            "reason_code": reason_code,
            "evidence_ref": list(sig.get("evidence_ref", [])),
        }
        # Carry provenance / optional fields forward. derived_from (the cross-hunter signals that
        # flagged this gap) is carried so the novelty-scorer can aggregate it deterministically
        # from gap_classification ALONE — no runtime re-injection, no agent prose.
        if isinstance(sig, dict) and sig.get("derived_from"):
            gap["derived_from"] = list(sig["derived_from"])
        source_kind = _canonical_source_kind(sig)
        if source_kind is not None:
            gap["source_kind"] = source_kind
        if "notes" in sig:
            gap["notes"] = sig["notes"]

        gaps.append(gap)

    return {"gaps": gaps}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nonempty(value: object) -> bool:
    """Return True if value is a non-empty string (or coerces to one)."""
    return isinstance(value, str) and bool(value.strip())


def _canonical_source_kind(signal: dict) -> Optional[str]:
    """Return the schema enum for optional provenance, never worker prose.

    Hunter bundles already expose authoritative machine provenance through
    ``derived_from``.  A worker may also attach a human-readable label such as
    ``author-stated future work``; copying that label verbatim makes the
    deterministic classification artifact fail its own JSON schema.  Prefer an
    explicit canonical enum, otherwise derive the enum from the unambiguous
    machine provenance.  Unknown optional prose is intentionally omitted.
    """
    raw = signal.get("source_kind")
    if isinstance(raw, str) and raw.strip() in SOURCE_KINDS:
        return raw.strip()

    derived = signal.get("derived_from")
    if not isinstance(derived, list):
        return None
    candidates = {
        DERIVED_FROM_TO_SOURCE_KIND[item]
        for item in derived
        if isinstance(item, str) and item in DERIVED_FROM_TO_SOURCE_KIND
    }
    return next(iter(candidates)) if len(candidates) == 1 else None
