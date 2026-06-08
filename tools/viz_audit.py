"""Deterministic core of the visualization-auditor (ANALYZE producer, advisory).

Checks figure specs (from figure_spec_bundle) against the domain profile's metric
valid_range to detect axis truncation — a classic way to visually exaggerate
a small difference.

Example: a y-axis starting at 0.94 on a [0, 1] metric like Dice makes a 0.02
improvement look enormous. This checker flags it.

Profile-driven: metric valid_range comes from domain profile. Nothing hardcoded.
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _metric_valid_range(profile: Optional[dict], metric_name: str) -> Optional[List]:
    """Return [lo, hi] for the named metric from the profile, or None if not declared."""
    for m in (profile or {}).get("metrics", []) or []:
        if str(m.get("name", "")).lower() == metric_name.lower():
            vrange = m.get("valid_range")
            if vrange is not None and len(vrange) == 2:
                return vrange
    return None


def _is_truncated(declared_min: Optional[float], valid_min: Optional[float]) -> bool:
    """Return True if declared_min is significantly above valid_min (truncation present).

    Truncation is defined as declared_min > valid_min by more than a small epsilon,
    where valid_min is the domain-declared minimum for that metric.
    """
    if declared_min is None or valid_min is None:
        return False
    # Truncated if the declared min is above the valid min (chart starts above the bottom)
    return float(declared_min) > float(valid_min)


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_viz_truncation(
    figure_spec_bundle: dict,
    profile: Optional[dict] = None,
) -> List[dict]:
    """Return list of axis_truncation_flag dicts (empty == clean).

    Each flag has: figure_id, metric, axis, declared_min, valid_min, detail.

    Checks y-axis (and x-axis where a metric is declared for it) min against the
    profile's valid_range lower bound for each metric in the figure spec.
    """
    flags: List[dict] = []

    for fig in (figure_spec_bundle.get("figures") or []):
        figure_id = fig.get("figure_id", "unknown")
        metrics = fig.get("metrics") or []

        # Check y-axis truncation for each declared metric
        y_axis = fig.get("y_axis") or {}
        y_min = y_axis.get("min") if isinstance(y_axis, dict) else None

        for metric in metrics:
            vrange = _metric_valid_range(profile, metric)
            if vrange is None:
                continue  # no declared range — skip (no false positive)

            valid_min = vrange[0]

            # Y-axis truncation check
            if y_min is not None and _is_truncated(y_min, valid_min):
                flags.append({
                    "figure_id": figure_id,
                    "metric": metric,
                    "axis": "y",
                    "declared_min": y_min,
                    "valid_min": valid_min,
                    "detail": (
                        f"Figure '{figure_id}': y-axis min={y_min} for metric '{metric}' "
                        f"is above the valid_range lower bound {valid_min}. "
                        "This truncates the axis and may visually exaggerate differences."
                    ),
                })

        # Check x-axis truncation if x_axis also declares a metric
        x_axis = fig.get("x_axis") or {}
        if isinstance(x_axis, dict):
            x_metric = x_axis.get("metric")
            x_min = x_axis.get("min")
            if x_metric and x_min is not None:
                vrange_x = _metric_valid_range(profile, x_metric)
                if vrange_x is not None:
                    valid_min_x = vrange_x[0]
                    if _is_truncated(x_min, valid_min_x):
                        flags.append({
                            "figure_id": figure_id,
                            "metric": x_metric,
                            "axis": "x",
                            "declared_min": x_min,
                            "valid_min": valid_min_x,
                            "detail": (
                                f"Figure '{figure_id}': x-axis min={x_min} for metric "
                                f"'{x_metric}' is above the valid_range lower bound "
                                f"{valid_min_x}. Axis truncation detected."
                            ),
                        })

    return flags


def build_report(
    figure_spec_bundle: dict,
    profile: Optional[dict] = None,
) -> dict:
    """Build a viz_audit_report payload.

    clean is derived from axis_truncation_flags — never set by hand.
    """
    flags = check_viz_truncation(figure_spec_bundle, profile)
    audited = [
        fig.get("figure_id", "unknown")
        for fig in (figure_spec_bundle.get("figures") or [])
    ]
    return {
        "figures_audited": audited,
        "axis_truncation_flags": flags,
        "clean": len(flags) == 0,
        "notes": "",
    }
