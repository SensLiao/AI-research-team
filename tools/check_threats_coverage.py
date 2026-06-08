"""Deterministic core of the threats-to-validity-writer coverage check (VERIFY panel).

Validates that a threats_report covers all four canonical validity dimensions:
  - internal
  - external
  - construct
  - statistical

A threats section that omits any of these four is incomplete — a reviewer will notice,
and the omission signals that the authors have not thought through the validity of their work.

The check is PURELY structural: it scans the ``validity_dimension`` field of each threat
and reports which of the four dimensions are missing.

Input consumed: ``threats_report`` payload dict.
"""
from __future__ import annotations

from typing import List

REQUIRED_DIMENSIONS: frozenset[str] = frozenset(
    ["internal", "external", "construct", "statistical"]
)


def check_threats_coverage(threats_report: dict) -> List[str]:
    """Return violations (empty list == all four validity dimensions are covered).

    Parameters
    ----------
    threats_report : dict
        threats_report payload dict (has ``threats[]``).

    Returns
    -------
    List[str]
        Human-readable violations listing each missing dimension; empty == complete.
    """
    violations: List[str] = []
    threats = threats_report.get("threats") or []

    covered: set[str] = set()
    for threat in threats:
        dim = threat.get("validity_dimension", "")
        if dim in REQUIRED_DIMENSIONS:
            covered.add(dim)

    missing = sorted(REQUIRED_DIMENSIONS - covered)
    for dim in missing:
        violations.append(
            f"validity dimension '{dim}' is missing from threats_report; "
            "all four validity dimensions must be covered"
        )

    return violations


def build_report(threats_report: dict) -> dict:
    """Build a threats-coverage check report.

    ``verdict`` is derived from violations — never set by hand.
    ``missing_dimensions`` lists the uncovered dimensions (empty == all covered),
    computed directly from the covered set rather than parsed from violation strings.
    """
    threats = threats_report.get("threats") or []
    covered: set[str] = set()
    for threat in threats:
        dim = threat.get("validity_dimension", "")
        if dim in REQUIRED_DIMENSIONS:
            covered.add(dim)

    missing = sorted(REQUIRED_DIMENSIONS - covered)
    v = check_threats_coverage(threats_report)
    return {
        "verdict": "BLOCK" if v else "PASS",
        "violations": v,
        "missing_dimensions": missing,
    }
