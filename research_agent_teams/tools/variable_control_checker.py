"""Deterministic core of the variable-control-auditor (hard gate).

Given an experiment_matrix (the studied/controlled/frozen variable declaration + the conditions and
their factor settings), prove that each non-baseline condition isolates the STUDIED variable: between
it and the baseline, only studied factors may differ. Anything else is a confound — a two-variable
change that makes the comparison uninterpretable. Frozen params must never move; a declared leakage
flag is an automatic refusal. The LLM agent extracts the factor settings; this checker — not the LLM
— decides PASS/BLOCK.
"""
from __future__ import annotations

from typing import List, Optional, Tuple


def _baseline(conditions: List[dict]) -> Optional[dict]:
    for c in conditions:
        if c.get("baseline"):
            return c
    return None


def _changed_factors(base: dict, cond: dict) -> set:
    bf, cf = base.get("factors", {}) or {}, cond.get("factors", {}) or {}
    return {k for k in set(bf) | set(cf) if bf.get(k) != cf.get(k)}


def check_variable_control(matrix: dict, profile: Optional[dict] = None) -> Tuple[List[str], int]:
    """Return (violations, n_confounded_conditions). Empty violations == every contrast is clean."""
    violations: List[str] = []
    conditions = matrix.get("conditions", []) or []
    studied = set(matrix.get("variables", {}).get("studied", []) or [])
    frozen = set(matrix.get("variables", {}).get("frozen", []) or [])

    base = _baseline(conditions)
    if base is None:
        violations.append("no baseline condition declared (cannot isolate the studied variable)")
        return violations, 0

    n_confounded = 0
    for c in conditions:
        if c.get("baseline"):
            continue
        changed = _changed_factors(base, c)
        non_studied = changed - studied
        if not non_studied:
            continue
        n_confounded += 1
        frozen_hit = sorted(non_studied & frozen)
        other = sorted(non_studied - frozen)
        if frozen_hit:
            violations.append(f"condition {c.get('id')!r} changes frozen param(s) {frozen_hit} (must stay frozen)")
        if other:
            violations.append(
                f"condition {c.get('id')!r} is confounded: also changes non-studied factor(s) {other} "
                f"(only studied {sorted(studied)} may change vs baseline)"
            )
    return violations, n_confounded


def build_report(matrix: dict, profile: Optional[dict] = None, leakage_flagged: bool = False) -> dict:
    """Build a variable_control_report payload (verdict derived from violations, never set by hand)."""
    violations, n_conf = check_variable_control(matrix, profile)
    if leakage_flagged:
        violations.append("leakage flagged: a condition's input derives from test labels / a case-specific oracle")
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "n_confounded_conditions": n_conf,
        "checked_invariants": list((profile or {}).get("control_invariants", [])),
    }
