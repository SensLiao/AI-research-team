"""Deterministic core of the review-configurator independence check (VERIFY panel).

Validates a candidate review_config payload before it is emitted:
  1. At least 2 distinct non-empty lens values must be present (independence requires
     multiple distinct perspectives; a panel with 0 or 1 distinct lens cannot guarantee
     independent review).
  2. No duplicate lens values (two entries with the same lens = one reviewer's perspective
     dominates; the other is redundant and the independence guarantee is lost).
  3. No empty anchor string for any lens entry (an empty anchor is a placeholder, not an
     independence guarantee; the reviewer has no defined scope).
  4. No two lenses may share byte-identical anchor text (identical anchors mean the two
     reviewers are scoped to the exact same passage — independence is lost).

The LLM agent drafts the config; this checker — not the LLM — decides whether the config
is valid. If violations are found the config is NOT emitted.
"""
from __future__ import annotations

from typing import List


def check_review_independence(config: dict) -> List[str]:
    """Return violations (empty list == independent and fully anchored).

    Parameters
    ----------
    config : dict
        Candidate review_config payload (the ``lenses`` list is the relevant part).

    Returns
    -------
    List[str]
        Human-readable violation strings; empty == clean.
    """
    violations: List[str] = []
    lenses_list = config.get("lenses") or []

    # 0. Require at least 2 distinct non-empty lenses for independence.
    distinct_nonempty_lenses = {
        entry.get("lens", "").strip()
        for entry in lenses_list
        if entry.get("lens", "").strip()
    }
    if len(distinct_nonempty_lenses) < 2:
        violations.append(
            f"independence requires ≥2 distinct reviewer lenses but only "
            f"{len(distinct_nonempty_lenses)} distinct non-empty lens(es) found; "
            "add a second reviewer with a different lens"
        )

    # 1. Collect lens values and detect duplicates.
    seen_lenses: dict[str, int] = {}  # lens -> first occurrence index
    for i, entry in enumerate(lenses_list):
        lens_val = entry.get("lens", "")
        if lens_val in seen_lenses:
            violations.append(
                f"duplicate lens '{lens_val}' at index {i} "
                f"(first seen at index {seen_lenses[lens_val]}); "
                "each lens must appear at most once"
            )
        else:
            seen_lenses[lens_val] = i

    # 2. Check for empty anchors.
    for i, entry in enumerate(lenses_list):
        anchor = entry.get("anchor", "")
        if not isinstance(anchor, str) or not anchor.strip():
            lens_val = entry.get("lens", f"<entry {i}>")
            violations.append(
                f"lens '{lens_val}' at index {i} has an empty or missing anchor; "
                "each reviewer must have a non-empty independence anchor"
            )

    # 3. Detect byte-identical anchor text across different lenses (independence lost).
    seen_anchors: dict[str, str] = {}  # anchor_text -> first lens name
    for i, entry in enumerate(lenses_list):
        anchor = entry.get("anchor", "")
        lens_val = entry.get("lens", f"<entry {i}>")
        if not isinstance(anchor, str) or not anchor.strip():
            continue  # already flagged in check 2 above
        anchor_key = anchor  # byte-exact comparison, no normalization
        if anchor_key in seen_anchors:
            violations.append(
                f"lens '{lens_val}' at index {i} has byte-identical anchor text as "
                f"lens '{seen_anchors[anchor_key]}'; "
                "two reviewers with the same anchor text cannot provide independent perspectives"
            )
        else:
            seen_anchors[anchor_key] = lens_val

    return violations


def build_report(config: dict) -> dict:
    """Build a review-independence check report.

    The ``valid`` field is ``True`` iff no violations found.
    """
    v = check_review_independence(config)
    return {
        "valid": len(v) == 0,
        "violations": v,
    }
