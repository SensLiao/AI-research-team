"""Deterministic mechanism-set matcher for the analogy-mapper agent (Explicit analogy mapping cluster).

Today the "is this retrieved cross-domain paper a real structural analog" judgment happens
informally inside cross-domain-transfer-scout. This helper turns the SCORED half of that judgment
into a structural guarantee: given the SOURCE-domain mechanisms and the TARGET-problem mechanisms,
it returns exactly which mechanisms are shared, which are source-only, which are target-only, and a
deterministic overlap_score (Jaccard of the two mechanism sets). The analogy-mapper agent calls this
function and copies its `shared` / `overlap_score` straight into the mechanism_mapping artifact — so
the overlap is COMPUTED, never hand-set, and the test can prove the math.

Overlap formula (Jaccard / intersection-over-union of mechanism SETS):

    overlap_score = |shared| / |union|        where union = source ∪ target
                  = 1.0   when both sets are non-empty and equal
                  = 0.0   when the sets are disjoint
                  = 0.0   when BOTH sets are empty (no mechanisms ⇒ no analogy; defined as 0.0)

Determinism / purity: a mechanism is normalized (trimmed + casefolded) so 'Segment Tube' and
'segment tube ' count as the same mechanism, blanks are dropped, and duplicates collapse (set
semantics). Output lists are SORTED so the same input always yields byte-identical output. No
network, no clock, no random, no I/O, no LLM. Pure function of its two list arguments.
"""
from __future__ import annotations

from typing import Dict, List


def _normalize(mechanisms: List[str]) -> set[str]:
    """Return the set of non-blank, trimmed + casefolded mechanism keys.

    Non-string and blank entries are dropped (anti-slop): a mechanism that is empty or
    whitespace-only carries no signal and must not inflate or deflate the overlap.
    Casefolding makes the match case-insensitive and deterministic.
    """
    out: set[str] = set()
    for m in mechanisms:
        if isinstance(m, str):
            key = m.strip().casefold()
            if key:
                out.add(key)
    return out


def overlap_score(source_mechanisms: List[str], target_mechanisms: List[str]) -> float:
    """Jaccard overlap of two mechanism sets, in [0.0, 1.0].

    Defined as |source ∩ target| / |source ∪ target|. Both-empty ⇒ 0.0 (no mechanisms means
    no analogy, never a vacuous 1.0). Deterministic and pure.
    """
    src = _normalize(source_mechanisms)
    tgt = _normalize(target_mechanisms)
    union = src | tgt
    if not union:
        return 0.0
    return len(src & tgt) / len(union)


def match_mechanisms(
    source_mechanisms: List[str],
    target_mechanisms: List[str],
) -> Dict[str, object]:
    """Match SOURCE-domain mechanisms against TARGET-problem mechanisms.

    Args:
        source_mechanisms: Mechanism-level phrases from the source domain (the analog's field).
        target_mechanisms: Mechanism-level phrases from the target problem (problem_abstraction).

    Returns:
        A dict with:
          - ``shared``:       sorted list of normalized mechanisms present in BOTH sets.
          - ``source_only``:  sorted list of normalized mechanisms only in the source set.
          - ``target_only``:  sorted list of normalized mechanisms only in the target set.
          - ``overlap_score`` float in [0,1] (Jaccard of the two sets); both-empty ⇒ 0.0.

        Lists are SORTED so the output is deterministic for any input ordering. Mechanisms are
        normalized (trimmed + casefolded, blanks dropped, duplicates collapsed) before matching.

    Pure function: no I/O, no network, no clock, no random. Same input ⇒ identical output.
    """
    src = _normalize(source_mechanisms)
    tgt = _normalize(target_mechanisms)
    union = src | tgt
    score = (len(src & tgt) / len(union)) if union else 0.0

    return {
        "shared": sorted(src & tgt),
        "source_only": sorted(src - tgt),
        "target_only": sorted(tgt - src),
        "overlap_score": score,
    }
