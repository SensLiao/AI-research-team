"""Deterministic core of the metric-implementation-auditor (DESIGN hard gate).

Audits that ALL conditions in an experiment use IDENTICAL metric implementations
for each metric declared in the active domain profile. Two sources of BLOCK:

  1. Implementation mismatch: two conditions declare different ``impl_ref``,
     ``spacing``, or ``postprocess`` for the same metric.
  2. Missing metric: a metric declared in the domain profile is absent from
     at least one condition's metric_impls map.

Profile-driven: the canonical ``implementation_ref`` for each metric comes from
``profile.metrics[].implementation_ref``. Nothing is hardcoded per metric name.
A metric the profile does not declare is skipped (no false BLOCK); always-on
structural checks (dict shape) still run.

The agent gathers the per-condition metric_impls; this checker — not the LLM —
decides PASS/BLOCK.

=== Declared treatment variation (R3 A3, 2026-08-07) ===
Check 2's cross-condition implementation mismatch is not always a defect: an experiment
that studies e.g. postprocessing threshold AS A VARIABLE will legitimately have a
different ``postprocess`` per condition. When every condition's
``metric_impls[metric]`` entry names the SAME kind of variation via a ``varies_by``
list, and every named variable is one the caller declares as actually studied
(``studied_variables``, case-insensitive), the mismatch is recorded on
``treatment_variation`` instead of ``violations`` — advisory, never a BLOCK reason.
Omitting ``studied_variables`` (the default) reproduces the old behaviour exactly:
every Check-2 mismatch is a violation, because nothing can ever be "declared".
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


# Keys compared across conditions for implementation consistency
_IMPL_KEYS: Tuple[str, ...] = ("impl_ref", "spacing", "postprocess")


def _profile_metric_index(profile: Optional[dict]) -> Dict[str, Optional[str]]:
    """Return {metric_name_lower: implementation_ref_or_None} from the profile.

    Only includes metrics the profile explicitly declares. The canonical impl_ref
    is the value from ``profile.metrics[].implementation_ref`` (may be null/missing).
    """
    idx: Dict[str, Optional[str]] = {}
    for m in (profile or {}).get("metrics", []) or []:
        name = m.get("name")
        if name:
            idx[str(name).lower()] = m.get("implementation_ref")
    return idx


def check_metric_impls(
    conditions: List[dict],
    profile: Optional[dict] = None,
    *,
    studied_variables: Optional[set] = None,
) -> List[str]:
    """Return violations (empty == all metrics implemented consistently, or every
    cross-condition difference is a declared, in-scope treatment variation).

    Args:
        conditions: List of condition dicts, each with shape:
            {
              "condition_id": str,
              "metric_impls": {
                "<metric_name>": {
                  "impl_ref": str | null,
                  "spacing": <any> | null,
                  "postprocess": <any> | null,
                  "varies_by": [str, ...] | null,   # R3 A3, see module docstring
                }
              }
            }
        profile: Optional domain profile dict. Used to:
            - enumerate which metrics must be present in every condition.
            - supply the canonical impl_ref for each metric.
        studied_variables: Optional set of variable names the experiment actually
            studies (case-insensitive). See collect_treatment_variation.

    Returns:
        List of human-readable violation strings. Empty = PASS.
    """
    violations, _treatment_variation = _run_metric_impl_checks(conditions, profile, studied_variables)
    return violations


def collect_treatment_variation(
    conditions: List[dict],
    profile: Optional[dict] = None,
    *,
    studied_variables: Optional[set] = None,
) -> List[str]:
    """Return the Check-2 cross-condition implementation differences let through as a
    declared, in-scope treatment variation rather than flagged as a violation.

    R3 A3 (2026-08-07): non-blocking by construction — this is advisory context for the
    director, never a reason to BLOCK. See the module docstring for the exact condition.
    """
    _violations, treatment_variation = _run_metric_impl_checks(conditions, profile, studied_variables)
    return treatment_variation


def _run_metric_impl_checks(
    conditions: List[dict],
    profile: Optional[dict],
    studied_variables: Optional[set],
) -> Tuple[List[str], List[str]]:
    """Shared core for check_metric_impls / collect_treatment_variation — one pass, one truth."""
    violations: List[str] = []
    treatment_variation: List[str] = []

    if not conditions:
        violations.append("no conditions provided — cannot audit metric implementations")
        return violations, treatment_variation

    # Extract per-condition metric_impls maps
    cond_impls: Dict[str, dict] = {}
    for cond in conditions:
        cid = cond.get("condition_id") or "<unknown>"
        impls = cond.get("metric_impls")
        if impls is None:
            impls = {}
        cond_impls[cid] = impls

    profile_idx = _profile_metric_index(profile)
    studied_casefold = {str(v).strip().casefold() for v in (studied_variables or set()) if str(v).strip()}

    # --- Check 1: Missing metrics (profile-driven) ---
    # Every metric declared in the profile must appear in EVERY condition's metric_impls
    for metric_lower, canonical_impl in profile_idx.items():
        missing_from: List[str] = []
        for cid, impls in cond_impls.items():
            # Match case-insensitively
            present = any(k.lower() == metric_lower for k in impls)
            if not present:
                missing_from.append(cid)
        if missing_from:
            violations.append(
                f"metric={metric_lower!r} (declared in profile) is missing from "
                f"condition(s): {missing_from}"
            )

    # --- Check 2: Implementation consistency across conditions ---
    # Collect all metric names across all conditions (case-normalised)
    all_metric_keys: set = set()
    for impls in cond_impls.values():
        for k in impls:
            all_metric_keys.add(k.lower())

    for metric_lower in sorted(all_metric_keys):
        # Collect per-key values across conditions
        per_cond: Dict[str, dict] = {}
        for cid, impls in cond_impls.items():
            # Find the entry (case-insensitive)
            entry = None
            for k, v in impls.items():
                if k.lower() == metric_lower:
                    entry = v if isinstance(v, dict) else {}
                    break
            if entry is not None:
                per_cond[cid] = entry

        if len(per_cond) < 2:
            # Only one condition has this metric — consistency check is trivially OK
            # (missing-from-profile check above handles the profile-declared case)
            continue

        for impl_key in _IMPL_KEYS:
            values: Dict[str, object] = {
                cid: entry.get(impl_key) for cid, entry in per_cond.items()
            }
            unique_vals = set(
                repr(v) for v in values.values()
            )
            if len(unique_vals) > 1:
                # Build a readable diff
                diff_str = "; ".join(
                    f"{cid}={v!r}" for cid, v in sorted(values.items())
                )
                # R3 A3: a difference every condition explains via varies_by, fully
                # covered by variables the experiment actually studies, is a declared
                # treatment — not an accidental drift.
                varies_by_sets = [
                    {str(x).strip().casefold() for x in (entry.get("varies_by") or []) if str(x).strip()}
                    for entry in per_cond.values()
                ]
                declared_treatment = bool(studied_casefold) and all(varies_by_sets) and (
                    set().union(*varies_by_sets) <= studied_casefold
                )
                if declared_treatment:
                    treatment_variation.append(
                        f"metric={metric_lower!r} {impl_key!r} varies across conditions as a "
                        f"declared studied treatment: {diff_str}"
                    )
                else:
                    violations.append(
                        f"metric={metric_lower!r} has inconsistent {impl_key!r} "
                        f"across conditions: {diff_str} (if this variation is a studied "
                        f"treatment, declare metric_impls[{metric_lower!r}].varies_by naming "
                        f"the studied variable(s))"
                    )

    # --- Check 3: Canonical impl_ref (profile-driven) ---
    # When the profile declares a non-null implementation_ref for a metric,
    # EVERY condition that declares that metric must use the canonical impl_ref.
    for metric_lower, canonical_impl in profile_idx.items():
        if canonical_impl is None:
            continue  # No canonical impl declared — skip this check
        for cid, impls in cond_impls.items():
            entry = None
            for k, v in impls.items():
                if k.lower() == metric_lower:
                    entry = v if isinstance(v, dict) else {}
                    break
            if entry is None:
                continue  # Already caught by missing-metric check above
            used_impl = entry.get("impl_ref")
            if used_impl != canonical_impl:
                violations.append(
                    f"metric={metric_lower!r} condition={cid!r}: "
                    f"impl_ref={used_impl!r} does not match profile canonical "
                    f"implementation_ref={canonical_impl!r}"
                )

    return violations, treatment_variation


def build_report(
    conditions: List[dict],
    profile: Optional[dict] = None,
    *,
    studied_variables: Optional[set] = None,
) -> dict:
    """Build a metric_impl_report payload (verdict derived from violations, never set by hand).

    Args:
        conditions: List of condition dicts with metric_impls (see check_metric_impls).
        profile: Optional domain profile dict.
        studied_variables: Optional set of variable names the experiment actually studies
            (case-insensitive) — see check_metric_impls / collect_treatment_variation.

    Returns:
        dict conforming to metric_impl_report.schema.json.
    """
    violations, treatment_variation = _run_metric_impl_checks(conditions, profile, studied_variables)

    # Collect checked_metrics = all metric names across conditions + profile
    checked: set = set()
    for cond in conditions:
        for k in (cond.get("metric_impls") or {}):
            checked.add(k.lower())
    profile_idx = _profile_metric_index(profile)
    checked.update(profile_idx.keys())

    # Collect missing_metrics and impl_mismatches from violations text
    missing: List[str] = [v for v in violations if "missing from condition" in v]
    mismatches: List[str] = [
        v for v in violations
        if "inconsistent" in v or "does not match profile canonical" in v
    ]

    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "checked_metrics": sorted(checked),
        "missing_metrics": missing,
        "impl_mismatches": mismatches,
        "treatment_variation": treatment_variation,
    }
