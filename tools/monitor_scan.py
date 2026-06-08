"""Deterministic core of monitor (EXECUTE/DISCOVER producer, advisory).

Scans run_record / run_manifest dicts for alert conditions — no network, no LLM,
no nondeterminism.  All alerts are advisory; no BLOCK verdict is emitted.

Alert rules (applied in this order, all conditions checked independently):
  - status == "stalled"       → alert_type "stalled",      severity "warn"
  - status == "failed"        → alert_type "failed",        severity "critical"
  - declared_cost > budget    → alert_type "over_budget",   severity "warn"
  - cost spike (>2× mean)     → alert_type "cost_spike",    severity "info"
    (only when ≥2 runs have a declared cost; single-run lists never produce cost_spike)

Same value in → same value out (deterministic, stable order).
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

_STALLED_STATUSES = {"stalled"}
_FAILED_STATUSES = {"failed"}


def _get_run_id(run: dict) -> str:
    """Return the best available run identifier from a run_record or run_manifest."""
    return (
        run.get("run_id")
        or run.get("condition_id")
        or "unknown_run"
    )


def _get_declared_cost(run: dict) -> Optional[float]:
    """Extract a declared cost value from a run dict, if present.

    Looks in:
      - run["cost"]                  (direct, numeric)
      - run["metrics"]["cost"]       (run_record metrics bag)
      - run["metrics"]["total_cost"] (alternative key)
    """
    # Direct top-level key
    cost = run.get("cost")
    if cost is not None:
        try:
            return float(cost)
        except (TypeError, ValueError):
            pass

    # Inside metrics bag (run_record schema)
    metrics = run.get("metrics") or {}
    for key in ("cost", "total_cost", "gpu_cost", "gpu_hours_cost"):
        val = metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    # Inside a resources bag (alternative shape) — so an over-budget run cannot hide
    # its cost under resources.{cost,gpu_cost} (M3-e review de-F5).
    resources = run.get("resources") or {}
    for key in ("cost", "gpu_cost", "total_cost"):
        val = resources.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    return None


def _budget_limit(budget: Optional[dict]) -> Optional[float]:
    """Extract a cost ceiling from a budget dict (task_frame budget shape).

    Looks for 'max_cost' or 'cost_limit' keys.
    """
    if not budget:
        return None
    for key in ("max_cost", "cost_limit"):
        val = budget.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _status_alerts(run: dict) -> List[dict]:
    """Return status-derived alerts (stalled, failed)."""
    alerts: List[dict] = []
    run_id = _get_run_id(run)
    status = run.get("status", "")

    if status in _STALLED_STATUSES:
        alerts.append({
            "run_ref": run_id,
            "alert_type": "stalled",
            "severity": "warn",
            "evidence_ref": [f"run/{run_id}/status={status}"],
            "detail": (
                f"Run '{run_id}' has status '{status}'. "
                "The run appears to have stopped making progress."
            ),
        })
    elif status in _FAILED_STATUSES:
        alerts.append({
            "run_ref": run_id,
            "alert_type": "failed",
            "severity": "critical",
            "evidence_ref": [f"run/{run_id}/status={status}"],
            "detail": (
                f"Run '{run_id}' has status '{status}'. "
                "Manual review required before continuing."
            ),
        })

    return alerts


def _budget_alert(run: dict, budget_limit: Optional[float]) -> Optional[dict]:
    """Return an over_budget alert if the run's declared cost exceeds the limit."""
    if budget_limit is None:
        return None
    cost = _get_declared_cost(run)
    if cost is None or cost <= budget_limit:
        return None

    run_id = _get_run_id(run)
    return {
        "run_ref": run_id,
        "alert_type": "over_budget",
        "severity": "warn",
        "evidence_ref": [f"run/{run_id}/cost={cost}/budget_limit={budget_limit}"],
        "detail": (
            f"Run '{run_id}' declared cost {cost:.4g} exceeds budget limit "
            f"{budget_limit:.4g}."
        ),
    }


def _cost_spike_alerts(runs: List[dict]) -> List[dict]:
    """Return cost_spike alerts for runs whose cost is >2× the mean across all runs.

    Only fires when ≥2 runs have a declared cost (avoids spurious alerts on single runs).
    """
    alerts: List[dict] = []
    costs = [(run, _get_declared_cost(run)) for run in runs]
    valid = [(run, c) for run, c in costs if c is not None]
    if len(valid) < 2:
        return alerts

    mean_cost = sum(c for _, c in valid) / len(valid)
    if mean_cost <= 0:
        return alerts

    threshold = 2.0 * mean_cost
    for run, cost in valid:
        if cost > threshold:
            run_id = _get_run_id(run)
            alerts.append({
                "run_ref": run_id,
                "alert_type": "cost_spike",
                "severity": "info",
                "evidence_ref": [
                    f"run/{run_id}/cost={cost:.4g}/mean={mean_cost:.4g}/threshold={threshold:.4g}"
                ],
                "detail": (
                    f"Run '{run_id}' cost {cost:.4g} is more than 2× the mean "
                    f"({mean_cost:.4g}) across {len(valid)} runs."
                ),
            })
    return alerts


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def scan_runs(
    runs: List[dict],
    budget: Optional[dict] = None,
) -> List[dict]:
    """Scan a list of run_record / run_manifest dicts and return advisory alerts.

    Args:
        runs:   List of run dicts (run_record or run_manifest payloads).
        budget: Optional budget dict (task_frame budget shape).  When provided,
                runs whose declared cost exceeds budget["max_cost"] / ["cost_limit"]
                produce an over_budget alert.

    Returns:
        List of alert dicts (may be empty).  Each alert validates against
        monitor_alert.schema.json's items schema.
    """
    limit = _budget_limit(budget)
    alerts: List[dict] = []

    # Per-run checks (status + over_budget)
    for run in runs:
        alerts.extend(_status_alerts(run))
        ba = _budget_alert(run, limit)
        if ba:
            alerts.append(ba)

    # Cross-run cost spike check
    alerts.extend(_cost_spike_alerts(runs))

    # Stable order: (run_ref, alert_type)
    alerts.sort(key=lambda a: (a.get("run_ref", ""), a.get("alert_type", "")))

    return alerts


def build_alerts(
    runs: List[dict],
    budget: Optional[dict] = None,
) -> dict:
    """Build a monitor_alert payload from a list of run dicts.

    Args:
        runs:   List of run_record / run_manifest payloads.
        budget: Optional budget dict.

    Returns:
        A monitor_alert dict with "alerts" key.  Validates against
        monitor_alert.schema.json.
    """
    return {"alerts": scan_runs(runs, budget)}
