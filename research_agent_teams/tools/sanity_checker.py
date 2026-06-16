"""Deterministic core of the result-sanity-checker (ANALYZE hard gate).

Screen a result_summary BEFORE any reviewer reads the numbers, for the mechanical red flags:
  1. NaN / Inf / non-numeric finding value                              (broken computation)
  2. a value outside the metric's declared valid_range (per profile)    (impossible result)
  3. a corrupt baseline_value (NaN/Inf/non-numeric)                     (cannot screen leakage)
  4. leakage-smell: a value that improves implausibly far over baseline (a classic leakage tell),
     judged in the metric's OWN direction (higher_is_better)            — so a legitimate regression
                                                                          on a lower-is-better metric
                                                                          is not mistaken for leakage.

The LLM agent gathers the result_summary; this checker — not the LLM — decides PASS/BLOCK. Metric
ranges, directions, and the leakage delta come from the domain profile (`metrics[].valid_range`,
`metrics[].higher_is_better`, `leakage_delta`). Nothing is hardcoded per field; a metric the profile
does not declare a range for simply skips the range check (its NaN check still always runs).
"""
from __future__ import annotations

import math
from typing import List, Optional

DEFAULT_LEAKAGE_DELTA = 0.5


def _finite_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isnan(x) and not math.isinf(x)


def _metric_index(profile: Optional[dict]) -> dict:
    """lowercased-name -> {higher_is_better, valid_range} from the profile's metrics list.

    Keyed case-insensitively so a profile metric `Dice` matches a finding `dice` — otherwise a
    case mismatch would silently skip BOTH the range and leakage checks (an impossible value would
    slip the gate)."""
    idx = {}
    for m in (profile or {}).get("metrics", []) or []:
        name = m.get("name")
        if name:
            idx[str(name).lower()] = {"higher_is_better": m.get("higher_is_better", True),
                                      "valid_range": m.get("valid_range")}
    return idx


def check_sanity(result_summary: dict, run_record: Optional[dict] = None,
                 profile: Optional[dict] = None) -> dict:
    """Return {violations, nan_or_inf, out_of_range, leakage_smell, checked_metrics}."""
    prof = profile or {}
    idx = _metric_index(prof)
    leakage_delta = prof.get("leakage_delta", DEFAULT_LEAKAGE_DELTA)

    violations: List[str] = []
    out_of_range: List[str] = []
    nan_or_inf = False
    leakage_smell = False
    checked: List[str] = []

    for f in result_summary.get("findings", []) or []:
        metric = f.get("metric")
        value = f.get("value")
        checked.append(metric)

        if not _finite_number(value):
            nan_or_inf = True
            violations.append(f"{metric}={value!r} is NaN/Inf/non-numeric (broken computation)")
            continue

        spec = idx.get(str(metric).lower()) if metric is not None else None

        # 2. out-of-range (only when the profile declares a range; either bound may be null = unbounded)
        rng = spec.get("valid_range") if spec else None
        if rng is not None:
            lo, hi = rng[0], rng[1]
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                out_of_range.append(metric)
                violations.append(f"{metric}={value} out of valid range [{lo}, {hi}]")

        # 3 + 4. baseline integrity + direction-aware leakage smell
        baseline = f.get("baseline_value")
        if baseline is not None:
            if not _finite_number(baseline):
                violations.append(f"{metric} baseline_value={baseline!r} is corrupt (cannot screen for leakage)")
            elif spec is not None:
                higher_better = spec.get("higher_is_better", True)
                improvement = (value - baseline) if higher_better else (baseline - value)
                if improvement >= leakage_delta:
                    leakage_smell = True
                    violations.append(
                        f"leakage smell: {metric} improves by +{round(improvement, 6)} over baseline "
                        f"(>= {leakage_delta}), implausibly good")

    return {
        "violations": violations,
        "nan_or_inf": nan_or_inf,
        "out_of_range": out_of_range,
        "leakage_smell": leakage_smell,
        "checked_metrics": checked,
    }


def build_report(result_summary: dict, run_record: Optional[dict] = None,
                 profile: Optional[dict] = None) -> dict:
    """Build a sanity_verdict payload (verdict derived from violations — never set by hand)."""
    r = check_sanity(result_summary, run_record, profile)
    return {
        "verdict": "BLOCK" if r["violations"] else "PASS",
        "violations": r["violations"],
        "nan_or_inf": r["nan_or_inf"],
        "out_of_range": r["out_of_range"],
        "leakage_smell": r["leakage_smell"],
        "checked_metrics": r["checked_metrics"],
    }
