"""Deterministic core of the variable-touch-guard (EXECUTE hard gate).

Constitution: EXECUTE menus may fix bugs but NEVER touch a studied or frozen variable.
'controlled' is the explorable space — only those may be modified.

Given a debug_session or experiment_tree and an experiment_matrix
(the studied/controlled/frozen variable declaration), this tool computes whether
any of the touched_variables are in the forbidden set (studied ∪ frozen).
If any are, the verdict is BLOCK; otherwise PASS.

The LLM agent (variable-touch-guard) calls this tool; the tool — not the LLM — decides BLOCK/PASS.
"""
from __future__ import annotations

from typing import List


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalize a variable name for matching: strip surrounding whitespace + casefold.

    A constitution gate must not be dodgeable by a leading space (`" lr"`) or a case
    flip (`"LR"`) — both passed the unanchored `\\S` schema pattern. We err toward BLOCK
    (asymmetric cost: a false BLOCK is a director override; a false PASS silently breaks
    the constitution). Variable names are therefore matched case-insensitively after a strip.
    """
    return name.strip().casefold() if isinstance(name, str) else ""


def offenders(touched: List[str], variables: dict) -> List[str]:
    """Return the subset of *touched* that is in studied ∪ frozen (stable order).

    'controlled' is the explorable space and is explicitly allowed.
    Variables not declared in any category are treated as safe (not blocked).
    Matching is whitespace-stripped + case-insensitive (see ``_norm``) so a padded or
    case-flipped name cannot dodge the gate.

    Args:
        touched: Variable names the patch/branch would touch.
        variables: The 'variables' sub-object from an experiment_matrix payload,
                   with keys 'studied', 'controlled', 'frozen' (each a list[str]).

    Returns:
        Sorted list of variable names (stripped display form) that are forbidden to touch.
    """
    forbidden: set[str] = {_norm(v) for v in (variables.get("studied", []) or [])} | {
        _norm(v) for v in (variables.get("frozen", []) or [])
    }
    out: List[str] = []
    seen: set[str] = set()
    for v in touched:
        n = _norm(v)
        if n and n in forbidden and n not in seen:
            seen.add(n)
            out.append(v.strip() if isinstance(v, str) else v)
    # Preserve stable (sorted) order so the output is deterministic.
    return sorted(out)


def check_debug_session(session: dict, matrix: dict) -> dict:
    """Check a debug_session payload against an experiment_matrix.

    A debug_session touching a studied OR frozen variable → verdict BLOCK.
    A debug_session touching only controlled variables (or none) → verdict PASS.

    Args:
        session: A debug_session payload dict (must contain 'touched_variables').
        matrix:  An experiment_matrix payload dict (must contain 'variables').

    Returns:
        A variable_touch_verdict payload dict (schema-valid, allOf consistent).
    """
    touched: List[str] = session.get("touched_variables") or []
    variables: dict = matrix.get("variables") or {}

    bad = offenders(touched, variables)
    violations: List[str] = [
        f"debug_session touches {'studied' if _is_studied(v, variables) else 'frozen'} variable '{v}'"
        for v in bad
    ]

    return _verdict_payload(
        violations=violations,
        touched=list(touched),
        studied=list(variables.get("studied", []) or []),
        frozen=list(variables.get("frozen", []) or []),
    )


def check_experiment_tree(tree: dict, matrix: dict) -> dict:
    """Check an experiment_tree payload against an experiment_matrix.

    A branch's EFFECTIVE touched set is ``touched_variables ∪ changed_factors.keys()``.
    ``changed_factors`` is the STRUCTURAL record of what a branch actually changes; relying
    only on the LLM-declared ``touched_variables`` let a branch hide a studied-variable change
    by declaring an empty list (the M3-b review CRITICAL). The guard now reconciles both, so a
    branch that changes a studied/frozen factor is BLOCKED even if ``touched_variables`` omits it.
    Each violation names the branch_id and the offending variable.

    Args:
        tree:   An experiment_tree payload dict (contains 'branches').
        matrix: An experiment_matrix payload dict (contains 'variables').

    Returns:
        A variable_touch_verdict payload dict (schema-valid, allOf consistent).
    """
    variables: dict = matrix.get("variables") or {}
    branches: list = tree.get("branches") or []

    violations: List[str] = []
    all_touched: list[str] = []

    for branch in branches:
        branch_id: str = branch.get("branch_id", "<unknown>")
        declared: List[str] = branch.get("touched_variables") or []
        changed_factors = branch.get("changed_factors") or {}
        factor_keys: List[str] = list(changed_factors.keys()) if isinstance(changed_factors, dict) else []
        # Effective touched set: the declared list reconciled with the structural factor changes.
        effective: List[str] = list(dict.fromkeys(list(declared) + factor_keys))
        all_touched.extend(effective)
        bad = offenders(effective, variables)
        for v in bad:
            category = "studied" if _is_studied(v, variables) else "frozen"
            violations.append(
                f"branch '{branch_id}' touches {category} variable '{v}'"
            )

    return _verdict_payload(
        violations=violations,
        touched=sorted(set(all_touched)),
        studied=list(variables.get("studied", []) or []),
        frozen=list(variables.get("frozen", []) or []),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_studied(var: str, variables: dict) -> bool:
    return _norm(var) in {_norm(v) for v in (variables.get("studied", []) or [])}


def _verdict_payload(
    violations: List[str],
    touched: List[str],
    studied: List[str],
    frozen: List[str],
) -> dict:
    """Assemble a variable_touch_verdict payload.

    verdict is derived from violations — BLOCK iff violations is non-empty.
    This mirrors the allOf constraint in variable_touch_verdict.schema.json.
    """
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "touched": touched,
        "studied": studied,
        "frozen": frozen,
    }
