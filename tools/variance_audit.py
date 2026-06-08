"""Deterministic core of the variance-analyzer (ANALYZE producer).

Checks that n_seeds meets the declared threshold from the domain profile before
treating variance estimates as reliable. If 1 seed is used but the experiment is
labeled 'stable', that is flagged as seed_count_insufficient.

Profile-driven: looks for a `min_seeds` key in the profile (hard_invariants or a
top-level field). Falls back to the built-in DEFAULT_MIN_SEEDS = 3 when the profile
does not declare a minimum.

C2 FIX: n_seeds is the count of DISTINCT seed values across run_records, not the
count of run_records. Re-running one seed N times must not be mistaken for N distinct
seeds. Records with a missing/None seed value are excluded from the distinct-seed count.
If seeds are absent on all records, n_seeds = 0 (insufficient). Per-metric variance is
also computed only across distinct seeds (one value per distinct seed; if a seed appears
multiple times in the records the last record for that seed is used for metrics).

Round-2 FIX 4:
  (a) Profile-derived stability threshold. The auto stability label no longer uses a
      hardcoded `max_std < 0.02` (which is meaningless for non-[0,1] metrics such as HD95
      in mm). The threshold for each metric is derived from that metric's profile
      `valid_range` span: STABILITY_FRACTION * (hi - lo) when the profile declares a finite
      range. When no finite range is available (range absent, or hi is null/open-ended like
      HD95 [0, null]), it falls back to the documented absolute default DEFAULT_STABILITY_STD.
      A run is labeled "stable" only when EVERY metric's std is below its own threshold.
  (b) Seed-type normalization. Seed values are coerced to a canonical type before the
      distinct-seed dedup (int where coercible, else str), so True/1 and "42"/42 do not
      mis-count as separate seeds.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

DEFAULT_MIN_SEEDS = 3  # conservative built-in threshold when profile is silent

# Round-2 FIX 4(a): stability thresholds.
# A metric is "stable" when its std is below STABILITY_FRACTION of its valid_range span.
# 0.02 of a [0,1] span == 0.02 absolute, reproducing the old [0,1] behaviour exactly.
STABILITY_FRACTION = 0.02
# Documented absolute fallback used ONLY when the metric has no finite profile range
# (e.g. an open-ended metric like HD95 with valid_range [0, null]).
DEFAULT_STABILITY_STD = 0.02


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _canonical_seed(seed: Any) -> Any:
    """Normalize a seed value to a canonical type for distinct-seed dedup.

    Coerce to int where coercible (so True/1 collapse, and "42"/42 collapse), else fall
    back to str.  bool is intentionally treated via int(): int(True) == 1, so a record
    with seed=True and one with seed=1 count as the SAME seed.
    """
    try:
        return int(seed)
    except (TypeError, ValueError):
        return str(seed)


def _metric_range_span(metric_name: str, profile: Optional[dict]) -> Optional[float]:
    """Return the finite (hi - lo) span for a metric from profile.metrics, or None.

    Returns None when: no profile, the metric is not declared, valid_range is absent or
    malformed, hi is null/open-ended (e.g. HD95 [0, null]), or the span is not positive.
    """
    if not profile:
        return None
    for m in profile.get("metrics", []) or []:
        if str(m.get("name", "")).lower() != metric_name.lower():
            continue
        vr = m.get("valid_range")
        if not isinstance(vr, (list, tuple)) or len(vr) != 2:
            return None
        lo, hi = vr[0], vr[1]
        if not isinstance(lo, (int, float)) or isinstance(lo, bool):
            return None
        if not isinstance(hi, (int, float)) or isinstance(hi, bool):
            return None  # open-ended (hi is null) → no finite span
        span = float(hi) - float(lo)
        return span if span > 0 else None
    return None


def _stability_threshold_for_metric(metric_name: str, profile: Optional[dict]) -> float:
    """Return the std threshold below which a metric counts as stable.

    Derived from the metric's profile valid_range span when finite
    (STABILITY_FRACTION * span); otherwise the documented absolute default.
    """
    span = _metric_range_span(metric_name, profile)
    if span is not None:
        return STABILITY_FRACTION * span
    return DEFAULT_STABILITY_STD


def _derive_stability_label(per_metric: List[dict], profile: Optional[dict]) -> str:
    """Return 'stable' iff EVERY metric's std is below its own profile-derived threshold.

    Empty per_metric → 'insufficient_data'.  Any metric over its threshold → 'unstable'.
    """
    if not per_metric:
        return "insufficient_data"
    for m in per_metric:
        std_val = m.get("std") or 0.0
        threshold = _stability_threshold_for_metric(m.get("metric", ""), profile)
        if std_val >= threshold:
            return "unstable"
    return "stable"


def _extract_min_seeds(profile: Optional[dict]) -> int:
    """Return the min_seeds threshold from the profile or the built-in default."""
    if not profile:
        return DEFAULT_MIN_SEEDS
    # explicit top-level field
    if "min_seeds" in profile:
        val = profile["min_seeds"]
        if isinstance(val, int) and val > 0:
            return val
    # search hard_invariants for a pattern like "min_seeds >= N"
    for inv in profile.get("hard_invariants", []) or []:
        inv_str = str(inv).lower()
        if "min_seeds" in inv_str or "minimum seeds" in inv_str:
            # try to parse the number
            import re
            m = re.search(r"(\d+)", inv_str)
            if m:
                return int(m.group(1))
    return DEFAULT_MIN_SEEDS


def _distinct_seed_records(run_records: List[dict]) -> List[dict]:
    """Return one representative record per distinct seed value.

    Records whose seed is None (or missing) are excluded — they cannot contribute
    to a distinct-seed count. If a seed value appears multiple times the last
    record with that seed is kept (deterministic: last-wins over ordered input).

    Returns an empty list when no record carries a seed value.
    """
    seen: Dict[Any, dict] = {}
    for rec in run_records or []:
        seed = rec.get("seed")
        # Also look inside a nested provenance dict (common pattern in run_records)
        if seed is None:
            seed = (rec.get("provenance") or {}).get("seed")
        if seed is not None:
            # FIX 4(b): canonicalize so True/1 and "42"/42 don't count as distinct seeds
            seen[_canonical_seed(seed)] = rec
    return list(seen.values())


def _compute_per_metric_variance(run_records: List[dict]) -> List[dict]:
    """Aggregate per-metric mean and std from DISTINCT-seed run_records.

    Each run_record may have a `metrics` dict of {metric_name: value}.
    Only distinct-seed records are used so that re-running one seed N times
    does not inflate the variance estimate.
    """
    from collections import defaultdict
    metric_values: Dict[str, List[float]] = defaultdict(list)

    distinct_records = _distinct_seed_records(run_records)
    for rec in distinct_records:
        for mname, mval in (rec.get("metrics") or {}).items():
            if isinstance(mval, (int, float)) and not isinstance(mval, bool):
                if not math.isnan(mval) and not math.isinf(mval):
                    metric_values[mname].append(float(mval))

    result = []
    for mname, vals in sorted(metric_values.items()):
        mean_val = statistics.mean(vals) if vals else None
        std_val = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        result.append({
            "metric": mname,
            "mean": mean_val,
            "std": std_val,
            "values": vals,
        })
    return result


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_variance(
    n_seeds: int,
    profile: Optional[dict] = None,
    stability_label: Optional[str] = None,
) -> dict:
    """Return {seed_count_insufficient, min_seeds_required, violations_text}.

    seed_count_insufficient is True iff n_seeds < min_seeds_required.
    A stability_label of 'stable' with only 1 seed is also flagged.
    """
    min_seeds = _extract_min_seeds(profile)
    insufficient = n_seeds < min_seeds

    # extra check: 1 seed labeled "stable" is always insufficient regardless of threshold
    forced = (stability_label == "stable" and n_seeds < 2)
    if forced:
        insufficient = True

    violation_parts = []
    if insufficient:
        violation_parts.append(
            f"n_seeds={n_seeds} is below min_seeds_required={min_seeds}"
        )
    if forced and n_seeds < 2:
        violation_parts.append(
            "stability_label='stable' requires at least 2 seeds"
        )

    return {
        "seed_count_insufficient": insufficient,
        "min_seeds_required": min_seeds,
        "violations_text": "; ".join(violation_parts),
    }


def build_report(
    condition_id: str,
    run_records: List[dict],
    profile: Optional[dict] = None,
    stability_label: Optional[str] = None,
) -> dict:
    """Build a variance_report payload.

    n_seeds is the count of DISTINCT seed values found in run_records.
    seed_count_insufficient is derived from n_seeds vs. the profile threshold.
    Never hand-set. Records with missing seeds are excluded from the count.
    """
    distinct_records = _distinct_seed_records(run_records or [])
    n_seeds = len(distinct_records)
    check = check_variance(n_seeds, profile, stability_label)
    per_metric = _compute_per_metric_variance(run_records or [])

    # derive stability label if not provided
    if stability_label is None:
        if check["seed_count_insufficient"]:
            derived_label = "insufficient_data"
        else:
            # FIX 4(a): per-metric, profile-derived thresholds (not a hardcoded 0.02)
            derived_label = _derive_stability_label(per_metric, profile)
    else:
        derived_label = stability_label

    return {
        "condition_id": condition_id,
        "n_seeds": n_seeds,
        "min_seeds_required": check["min_seeds_required"],
        "seed_count_insufficient": check["seed_count_insufficient"],
        "per_metric_variance": per_metric,
        "stability_label": derived_label,
    }
