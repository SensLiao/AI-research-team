"""Deterministic core of the goal-alignment-checker (ANALYZE check-panel).

H2 FIX: provides a REAL deterministic helper so the mechanizable checks actually bite
(contract rule 3). The agent spec's deterministic gates are backed by this checker.

Deterministic scans (pure text / keyword matching — no LLM):

  1. GENERALIZATION CLAIM WITHOUT OOD RESULTS:
     If the RQ text contains any of: "generaliz", "out-of-distribution", "external",
     "transfer", "robust" — AND no finding/condition is tagged as external/held-out/ood
     (checked in finding.condition_id, result_summary.findings[].condition_id,
     experiment_matrix.conditions[].id) — emit a violation.

  2. SOTA/BEATS CLAIM WITHOUT BASELINE CONDITION:
     If the RQ text contains any of: "state-of-the-art", "sota", "beats", "outperforms",
     "surpasses", "better than" — AND no condition in experiment_matrix.conditions has
     a factor "baseline": true or an id containing "baseline"/"sota" — emit a violation.

Profile-driven: no domain hardcoding. Pure function; no I/O, no network, no LLM.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Keywords that signal a generalization/OOD claim in the RQ text
_OOD_KEYWORDS = (
    "generaliz",       # generalizes, generalization, generalizability
    "out-of-distribution",
    "external",
    "transfer",
    "robust",
)

# Tags in condition ids / findings that indicate external/held-out/ood results.
# NOTE: "transfer" is intentionally NOT here. It is an OOD *claim* keyword (_OOD_KEYWORDS), so listing it
# as an evidence tag let any condition merely NAMED "*transfer*" (even an internal baseline like
# "transfer_time_ablation") self-satisfy the check — a generalization claim cleared by name coincidence.
# Real OOD evidence must carry an unambiguous external/held-out/ood/domain-shift tag, not just the claim word.
_OOD_CONDITION_TAGS = (
    "external",
    "ood",
    "held-out",
    "heldout",
    "held_out",
    "out_of_distribution",
    "domain_shift",
)

# Keywords that signal a SOTA / beats-X claim in the RQ
_SOTA_KEYWORDS = (
    "state-of-the-art",
    "state of the art",
    "sota",
    "beats",
    "outperforms",
    "surpasses",
    "better than",
)

# Tags in condition ids that indicate a baseline / SOTA comparison condition
_BASELINE_CONDITION_TAGS = (
    "baseline",
    "sota",
    "comparison",
    "reference",
)


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_goal_alignment(
    experiment_matrix: dict,
    result_summary: dict,
    profile: Optional[dict] = None,
) -> List[str]:
    """Return violation strings (empty == aligned).

    Deterministic checks only; LLM should call this and build its verdict from
    the returned violations list.
    """
    violations: List[str] = []

    rq_text = _extract_rq_text(experiment_matrix)
    rq_lower = rq_text.lower()

    condition_ids = _extract_condition_ids(experiment_matrix)
    finding_condition_ids = _extract_finding_condition_ids(result_summary)
    all_ids_lower = {c.lower() for c in (condition_ids | finding_condition_ids)}

    # --- Check 1: generalization/OOD keywords vs OOD results --------------------
    if rq_lower and _text_matches_any(rq_lower, _OOD_KEYWORDS):
        if not _any_id_matches_tags(all_ids_lower, _OOD_CONDITION_TAGS):
            matched_kw = [kw for kw in _OOD_KEYWORDS if kw in rq_lower]
            violations.append(
                f"RQ contains generalization/OOD keyword(s) {matched_kw!r} but no "
                "finding or condition is tagged as external/held-out/ood — "
                "generalization claim is unsupported by the results."
            )

    # --- Check 2: SOTA/beats claim vs baseline condition ----------------------
    if rq_lower and _text_matches_any(rq_lower, _SOTA_KEYWORDS):
        # Look for a condition with factor baseline=True or id matching baseline tags
        has_baseline = _has_baseline_condition(experiment_matrix)
        if not has_baseline:
            matched_kw = [kw for kw in _SOTA_KEYWORDS if kw in rq_lower]
            violations.append(
                f"RQ contains SOTA/comparison keyword(s) {matched_kw!r} but no condition "
                "in experiment_matrix has a baseline flag or baseline-tagged id — "
                "SOTA/beats claim cannot be verified without a baseline condition."
            )

    return violations


def build_verdict(
    experiment_matrix: dict,
    result_summary: dict,
    profile: Optional[dict] = None,
    notes: str = "",
) -> dict:
    """Build an analysis_check_verdict payload with panel_role='goal_alignment'.

    pass is derived from violations — never set by hand.
    """
    violations = check_goal_alignment(experiment_matrix, result_summary, profile)

    rq_text = _extract_rq_text(experiment_matrix)
    condition_ids = list(_extract_condition_ids(experiment_matrix))

    return {
        "panel_role": "goal_alignment",
        "pass": len(violations) == 0,
        "violations": violations,
        "checked_items": ([rq_text] if rq_text else []) + condition_ids,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _extract_rq_text(experiment_matrix: dict) -> str:
    """Extract the research question text from the experiment_matrix."""
    rq = experiment_matrix.get("research_question") or ""
    if isinstance(rq, list):
        return " ".join(str(r) for r in rq)
    return str(rq)


def _extract_condition_ids(experiment_matrix: dict) -> set:
    """Return the set of condition ids from experiment_matrix.conditions."""
    ids = set()
    for cond in (experiment_matrix.get("conditions") or []):
        cid = cond.get("id")
        if cid:
            ids.add(str(cid))
    return ids


def _extract_finding_condition_ids(result_summary: dict) -> set:
    """Return the set of condition_id values from result_summary.findings."""
    ids = set()
    for f in (result_summary.get("findings") or []):
        cid = f.get("condition_id")
        if cid:
            ids.add(str(cid))
    return ids


def _text_matches_any(text: str, keywords: tuple) -> bool:
    """Return True if any keyword substring is found in text (case already lowered)."""
    return any(kw in text for kw in keywords)


def _any_id_matches_tags(ids_lower: set, tags: tuple) -> bool:
    """Return True if any id (already lowered) contains one of the tag substrings."""
    for id_lower in ids_lower:
        for tag in tags:
            if tag in id_lower:
                return True
    return False


def _has_baseline_condition(experiment_matrix: dict) -> bool:
    """Return True if any condition has factor baseline=True or a baseline-tagged id."""
    for cond in (experiment_matrix.get("conditions") or []):
        cid = str(cond.get("id") or "").lower()
        factors = cond.get("factors") or {}
        if factors.get("baseline") is True:
            return True
        if any(tag in cid for tag in _BASELINE_CONDITION_TAGS):
            return True
    return False
