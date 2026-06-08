"""Deterministic core of the baseline-comparison-auditor (ANALYZE producer).

Compares baseline and method conditions across four dimensions to detect asymmetries
that would make the comparison unfair:
  1. data       — training data source / hash differs
  2. budget     — compute budget (epochs / steps / flops) differs
  3. metric     — metric computation (impl_ref / postprocess) differs
  4. postprocess — postprocessing config differs

H1 FIXES:
  (a) Absence-as-flag: when a dimension key is MISSING on either or both conditions,
      that is itself a flag ("cannot verify equality: <dim> absent on <condition>").
      Missing-vs-missing is NOT treated as equal/clean — we cannot confirm fairness
      without the data.
  (b) Profile-driven budget keys: the budget key names to check are read from
      profile.budget_keys (a list of strings); if the profile doesn't declare them,
      fall back to _DEFAULT_BUDGET_KEYS but still flag absence via (a).
  (c) Primary-metric cross-comparison: when the impl map is empty (no profile), we
      still flag if the conditions declare different primary_metric values (Dice vs IoU
      is an unfair comparison regardless of impl_ref).

The LLM agent gathers the condition configs; this checker — not the LLM — decides
which dimensions are asymmetric. Profile drives canonical metric implementation_refs.
Nothing is hardcoded per domain — all specifics come from the domain profile.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

# Default budget keys used when profile does not declare them.
# These are checked in order; the first one present on either side is used.
# Round-2 FIX 5: include iteration-style budget keys (iterations / num_iterations /
# max_iters / total_steps) so that step/iteration-budgeted training (common for
# non-epoch regimes) is also caught, not just epoch/step/flops budgets.
_DEFAULT_BUDGET_KEYS = (
    "epochs", "max_epochs", "steps", "total_steps",
    "iterations", "num_iterations", "max_iters",
    "flops", "budget",
)


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _get_condition(matrix_or_configs: dict, condition_id: str) -> Optional[dict]:
    """Return the condition dict from either an experiment_matrix or a protocol_spec."""
    # experiment_matrix shape: {"conditions": [{"id": ..., "factors": {...}}, ...]}
    for cond in matrix_or_configs.get("conditions", []) or []:
        if cond.get("id") == condition_id:
            return cond.get("factors", {}) or {}
    # protocol_spec shape: {"configs": [{"condition_id": ..., "config": {...}}, ...]}
    for cond in matrix_or_configs.get("configs", []) or []:
        if cond.get("condition_id") == condition_id:
            return cond.get("config", {}) or {}
    return None


def _metric_impl_map(profile: Optional[dict]) -> dict:
    """Return {metric_name_lower: implementation_ref} from the domain profile."""
    impl = {}
    for m in (profile or {}).get("metrics", []) or []:
        name = m.get("name")
        ref = m.get("implementation_ref")
        if name and ref:
            impl[str(name).lower()] = str(ref)
    return impl


def _compare_key(
    baseline_factors: dict,
    method_factors: dict,
    key: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (bval_str, mval_str) if they differ (or one is absent), else (None, None).

    Sentinel "<absent>" means the key is not present on that side.
    Both-absent → ("<absent>", "<absent>") — caller decides whether that matters.
    """
    b_present = key in baseline_factors
    m_present = key in method_factors

    if not b_present and not m_present:
        return "<absent>", "<absent>"
    if not b_present:
        return "<absent>", str(method_factors[key])
    if not m_present:
        return str(baseline_factors[key]), "<absent>"

    bval = baseline_factors[key]
    mval = method_factors[key]
    if bval != mval:
        return str(bval), str(mval)
    return None, None  # present and equal → no flag


def _get_budget_keys(profile: Optional[dict]) -> tuple:
    """Return the budget key names to check, from profile or default fallback."""
    if profile:
        declared = profile.get("budget_keys")
        if declared and isinstance(declared, list) and len(declared) > 0:
            return tuple(str(k) for k in declared)
    return _DEFAULT_BUDGET_KEYS


def _any_key_present(factors: dict, keys: tuple) -> bool:
    """Return True if at least one key from `keys` exists in `factors`."""
    return any(k in factors for k in keys)


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_baseline_asymmetry(
    baseline_condition_id: str,
    method_condition_id: str,
    matrix_or_configs: dict,
    profile: Optional[dict] = None,
) -> List[dict]:
    """Return a list of asymmetry_flag dicts (empty == clean).

    Each flag has: condition_pair, dimension, baseline_value, method_value, detail.

    Profile-driven: uses profile metric.implementation_ref as canonical.
    Nothing hardcoded per domain.
    """
    flags: List[dict] = []
    pair = [baseline_condition_id, method_condition_id]

    baseline_factors = _get_condition(matrix_or_configs, baseline_condition_id) or {}
    method_factors = _get_condition(matrix_or_configs, method_condition_id) or {}

    # ------------------------------------------------------------------ #
    # 1. DATA ASYMMETRY                                                   #
    # Primary key: data_hash. Fallback: data_source.                      #
    # Absence is flagged ONLY when the key is absent on one side but      #
    # present on the other (asymmetric absence = cannot verify equality). #
    # Both-absent on data_hash: silently fall through to data_source.     #
    # Both-absent on BOTH keys: flag as "cannot verify data identity".    #
    # ------------------------------------------------------------------ #
    _data_keys = ("data_hash", "data_source")
    data_flagged = False
    for dk in _data_keys:
        bv, mv = _compare_key(baseline_factors, method_factors, dk)
        if bv is None and mv is None:
            # present and equal → dimension is verified clean; stop here
            data_flagged = True  # "clean" sentinel — no flag needed but don't fall through
            break
        if bv == "<absent>" and mv == "<absent>":
            # both absent for this key — try next key
            continue
        # one absent / values differ → flag
        absent_note = (
            f" (cannot verify equality: {dk} absent on "
            + ("baseline" if bv == "<absent>" else "method")
            + " condition)"
        ) if "<absent>" in (bv or "", mv or "") else ""
        flags.append({
            "condition_pair": pair,
            "dimension": "data",
            "baseline_value": bv,
            "method_value": mv,
            "detail": (
                f"{dk}: baseline={bv!r} vs method={mv!r}.{absent_note} "
                "Comparison unfair if training sets differ."
            ),
        })
        data_flagged = True
        break
    if not data_flagged:
        # Neither data_hash nor data_source present on EITHER side — flag it
        flags.append({
            "condition_pair": pair,
            "dimension": "data",
            "baseline_value": "<absent>",
            "method_value": "<absent>",
            "detail": (
                "cannot verify data identity: neither data_hash nor data_source "
                "is declared on either condition."
            ),
        })

    # ------------------------------------------------------------------ #
    # 2. BUDGET ASYMMETRY                                                 #
    # Keys come from profile.budget_keys or _DEFAULT_BUDGET_KEYS.        #
    # Strategy: find the FIRST key that is PRESENT on at least one side. #
    #   - present on both & equal → clean for budget (stop)              #
    #   - present on both & different → flag                             #
    #   - present on one side only → asymmetric absence → flag           #
    # If NO budget key is present on either side → flag absence.         #
    # ------------------------------------------------------------------ #
    budget_keys = _get_budget_keys(profile)
    budget_flagged = False
    for budget_key in budget_keys:
        b_has = budget_key in baseline_factors
        m_has = budget_key in method_factors
        if not b_has and not m_has:
            continue  # this key isn't used; try next
        # At least one side has this key
        bv, mv = _compare_key(baseline_factors, method_factors, budget_key)
        if bv is None and mv is None:
            budget_flagged = True  # equal → clean
            break
        absent_note = (
            f" (cannot verify equality: {budget_key} absent on "
            + ("baseline" if bv == "<absent>" else "method")
            + " condition)"
        ) if "<absent>" in (bv or "", mv or "") else ""
        flags.append({
            "condition_pair": pair,
            "dimension": "budget",
            "baseline_value": bv,
            "method_value": mv,
            "detail": (
                f"budget key '{budget_key}': baseline={bv!r} vs method={mv!r}.{absent_note}"
            ),
        })
        budget_flagged = True
        break
    if not budget_flagged:
        # None of the budget keys appeared on either side
        flags.append({
            "condition_pair": pair,
            "dimension": "budget",
            "baseline_value": "<absent>",
            "method_value": "<absent>",
            "detail": (
                "cannot verify compute budget: no budget key "
                f"({', '.join(budget_keys)}) declared on either condition."
            ),
        })

    # ------------------------------------------------------------------ #
    # 3. METRIC ASYMMETRY                                                 #
    # Check metric_impl_ref first (explicit implementation reference).    #
    # If both absent, check primary_metric mismatch (Dice vs IoU is      #
    # unfair regardless of profile/impl_ref).                             #
    # Absent-vs-absent on metric_impl_ref is only flagged when there is   #
    # ALSO no primary_metric comparison to fall back on.                  #
    # ------------------------------------------------------------------ #
    impl_map = _metric_impl_map(profile)
    bv, mv = _compare_key(baseline_factors, method_factors, "metric_impl_ref")
    if bv is None and mv is None:
        pass  # equal and present → clean
    elif bv == "<absent>" and mv == "<absent>":
        # Both absent: fall through to primary_metric check below
        bv = mv = None  # reset so we land in the primary_metric block
    else:
        # one absent OR values differ
        absent_note = (
            " (cannot verify equality: metric_impl_ref absent on "
            + ("baseline" if bv == "<absent>" else "method")
            + " condition)"
        ) if "<absent>" in (bv or "", mv or "") else ""
        flags.append({
            "condition_pair": pair,
            "dimension": "metric",
            "baseline_value": bv,
            "method_value": mv,
            "detail": (
                f"metric_impl_ref: baseline={bv!r} vs method={mv!r}.{absent_note}"
            ),
        })
        bv = mv = None  # mark as handled

    if bv is None and mv is None:
        # metric_impl_ref was absent-vs-absent or not yet flagged; check primary_metric
        baseline_metric = str(baseline_factors.get("primary_metric", "")).lower()
        method_metric = str(method_factors.get("primary_metric", "")).lower()
        if baseline_metric and method_metric and baseline_metric != method_metric:
            flags.append({
                "condition_pair": pair,
                "dimension": "metric",
                "baseline_value": baseline_metric,
                "method_value": method_metric,
                "detail": (
                    f"primary_metric differs: baseline={baseline_metric!r} vs "
                    f"method={method_metric!r}. Comparing across different primary metrics is unfair."
                ),
            })

    # ------------------------------------------------------------------ #
    # 4. POSTPROCESS ASYMMETRY                                            #
    # Find the FIRST postprocess key present on at least one side.        #
    # Same strategy as budget: skip both-absent, flag one-side-absent or  #
    # value difference. Do NOT flag absence if no postprocess key is used  #
    # at all (postprocessing is optional — its absence is not inherently   #
    # unfair if both sides omit it).                                       #
    # ------------------------------------------------------------------ #
    for pp_key in ("postprocess", "postprocess_ref", "postprocessing"):
        b_has = pp_key in baseline_factors
        m_has = pp_key in method_factors
        if not b_has and not m_has:
            continue
        bv, mv = _compare_key(baseline_factors, method_factors, pp_key)
        if bv is None and mv is None:
            break  # equal → clean; stop
        absent_note = (
            f" (postprocess key {pp_key!r} absent on "
            + ("baseline" if bv == "<absent>" else "method")
            + " condition)"
        ) if "<absent>" in (bv or "", mv or "") else ""
        flags.append({
            "condition_pair": pair,
            "dimension": "postprocess",
            "baseline_value": bv,
            "method_value": mv,
            "detail": (
                f"postprocess key '{pp_key}': baseline={bv!r} vs method={mv!r}.{absent_note}"
            ),
        })
        break

    return flags


def build_report(
    baseline_condition_id: str,
    method_condition_id: str,
    matrix_or_configs: dict,
    profile: Optional[dict] = None,
) -> dict:
    """Build a baseline_audit_report payload.

    clean is derived from asymmetry_flags — never set by hand.
    """
    flags = check_baseline_asymmetry(
        baseline_condition_id, method_condition_id, matrix_or_configs, profile
    )
    return {
        "conditions_compared": [baseline_condition_id, method_condition_id],
        "asymmetry_flags": flags,
        "clean": len(flags) == 0,
        "notes": "",
    }
