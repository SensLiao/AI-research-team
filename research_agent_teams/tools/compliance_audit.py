"""Deterministic core of the compliance-auditor (ANALYZE check-panel).

Checks that every condition declared in the experiment_matrix was actually run
(has a corresponding run_record). A declared condition without a run_record is a
compliance violation — the comparison cannot be fair if a condition was skipped.

Produces an analysis_check_verdict with panel_role='compliance'.
pass is derived from violations — never set by hand.
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_compliance(
    experiment_matrix: dict,
    run_records: List[dict],
    profile: Optional[dict] = None,
) -> List[str]:
    """Return violation strings (empty == fully compliant).

    Checks:
    - Every condition declared in experiment_matrix.conditions has >=1 run_record
      with a matching condition_id.
    - run_records list is non-empty if conditions are declared.
    """
    violations: List[str] = []

    declared_conditions = [
        c.get("id") for c in (experiment_matrix.get("conditions") or [])
        if c.get("id")
    ]

    if not declared_conditions:
        # Nothing declared — skip check (no conditions to enforce)
        return violations

    # Build set of condition_ids present in run_records
    run_condition_ids = {
        r.get("condition_id")
        for r in (run_records or [])
        if r.get("condition_id")
    }

    for cid in declared_conditions:
        if cid not in run_condition_ids:
            violations.append(
                f"Declared condition '{cid}' has no matching run_record "
                "(condition was declared but not executed)."
            )

    # Also flag if there are run_records for condition_ids NOT in the matrix
    extra_runs = run_condition_ids - set(declared_conditions)
    for cid in sorted(extra_runs):
        violations.append(
            f"run_record found for condition '{cid}' which is NOT declared in "
            "the experiment_matrix (undeclared run)."
        )

    return violations


def build_verdict(
    experiment_matrix: dict,
    run_records: List[dict],
    profile: Optional[dict] = None,
    checked_items: Optional[List[str]] = None,
) -> dict:
    """Build an analysis_check_verdict payload with panel_role='compliance'.

    pass is derived from violations — never set by hand.
    """
    violations = check_compliance(experiment_matrix, run_records, profile)

    declared_conditions = [
        c.get("id") for c in (experiment_matrix.get("conditions") or [])
        if c.get("id")
    ]
    items = checked_items if checked_items is not None else declared_conditions

    return {
        "panel_role": "compliance",
        "pass": len(violations) == 0,
        "violations": violations,
        "checked_items": items,
        "notes": "",
    }
