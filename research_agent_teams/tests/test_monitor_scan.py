"""Tests for the monitor_scan deterministic core.

Key invariants:
  - A stalled run → a stalled alert with severity warn, bound to its run_ref.
  - An over-budget run → an over_budget alert when budget limit is provided.
  - A failed run → a failed alert with severity critical.
  - A healthy run (provisional/planned) → empty alerts.
  - Deterministic: same input → same output on two calls.
  - build_alerts output validates against monitor_alert.schema.json.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.monitor_scan import (
    build_alerts,
    scan_runs,
)
from research_agent_teams.tools.validate_artifact import validate_against

_SCHEMA = "monitor_alert.schema.json"


# --------------------------------------------------------------------------- #
#  Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #

def _run_record(condition_id: str, status: str, cost: float | None = None) -> dict:
    """Build a minimal run_record-like dict."""
    r: dict = {
        "condition_id": condition_id,
        "status": status,
        "provenance": {"config_hash": "abc123"},
    }
    if cost is not None:
        r["metrics"] = {"cost": cost}
    return r


def _run_manifest(run_id: str, status: str) -> dict:
    """Build a minimal run_manifest-like dict."""
    return {
        "run_id": run_id,
        "status": status,
        "schema_version": "1.0.0",
        "created_at": "2026-06-09T00:00:00Z",
        "updated_at": "2026-06-09T00:00:00Z",
        "mode": "check_run",
        "entry_stage": "EXECUTE",
        "next_step": None,
        "completed_work": [],
    }


def _budget(max_cost: float) -> dict:
    return {"max_agent_hops": 10, "max_cost": max_cost}


# --------------------------------------------------------------------------- #
#  scan_runs — stalled                                                         #
# --------------------------------------------------------------------------- #

class TestStalledRun:

    def test_stalled_run_raises_alert(self):
        """Golden test: a stalled run → a stalled alert."""
        runs = [_run_record("cond_stall", "stalled")]
        alerts = scan_runs(runs)
        types = [a["alert_type"] for a in alerts]
        assert "stalled" in types, f"Expected stalled alert; got: {alerts}"

    def test_stalled_alert_bound_to_run_ref(self):
        """Stalled alert must carry the correct run_ref."""
        runs = [_run_record("cond_stall_id", "stalled")]
        alerts = scan_runs(runs)
        stalled = [a for a in alerts if a["alert_type"] == "stalled"]
        assert stalled, "Expected at least one stalled alert"
        assert stalled[0]["run_ref"] == "cond_stall_id"

    def test_stalled_alert_severity_warn(self):
        """Stalled alert must have severity warn."""
        runs = [_run_record("cond_s", "stalled")]
        alerts = scan_runs(runs)
        stalled = [a for a in alerts if a["alert_type"] == "stalled"]
        assert stalled[0]["severity"] == "warn"

    def test_stalled_alert_evidence_ref_nonempty(self):
        """Anti-slop: stalled alert must have non-empty evidence_ref."""
        runs = [_run_record("cond_ev", "stalled")]
        alerts = scan_runs(runs)
        stalled = [a for a in alerts if a["alert_type"] == "stalled"]
        assert stalled[0]["evidence_ref"], "evidence_ref must not be empty"
        assert all(s.strip() for s in stalled[0]["evidence_ref"])


# --------------------------------------------------------------------------- #
#  scan_runs — over_budget                                                     #
# --------------------------------------------------------------------------- #

class TestOverBudget:

    def test_over_budget_run_raises_alert(self):
        """A run whose cost exceeds budget limit → over_budget alert."""
        runs = [_run_record("cond_ob", "provisional", cost=150.0)]
        alerts = scan_runs(runs, budget=_budget(100.0))
        types = [a["alert_type"] for a in alerts]
        assert "over_budget" in types, f"Expected over_budget alert; got: {alerts}"

    def test_over_budget_alert_severity_warn(self):
        """over_budget alert must have severity warn."""
        runs = [_run_record("cond_ob2", "provisional", cost=200.0)]
        alerts = scan_runs(runs, budget=_budget(100.0))
        ob = [a for a in alerts if a["alert_type"] == "over_budget"]
        assert ob[0]["severity"] == "warn"

    def test_within_budget_no_over_budget_alert(self):
        """A run whose cost is within budget → no over_budget alert."""
        runs = [_run_record("cond_ok", "provisional", cost=50.0)]
        alerts = scan_runs(runs, budget=_budget(100.0))
        types = [a["alert_type"] for a in alerts]
        assert "over_budget" not in types

    def test_no_budget_no_over_budget_alert(self):
        """When no budget is provided, no over_budget alert is raised even for high cost."""
        runs = [_run_record("cond_nb", "provisional", cost=9999.0)]
        alerts = scan_runs(runs, budget=None)
        types = [a["alert_type"] for a in alerts]
        assert "over_budget" not in types


# --------------------------------------------------------------------------- #
#  scan_runs — failed                                                          #
# --------------------------------------------------------------------------- #

class TestFailedRun:

    def test_failed_run_raises_critical_alert(self):
        """A failed run → failed alert with severity critical."""
        runs = [_run_record("cond_fail", "failed")]
        alerts = scan_runs(runs)
        failed = [a for a in alerts if a["alert_type"] == "failed"]
        assert failed, "Expected a failed alert"
        assert failed[0]["severity"] == "critical"
        assert failed[0]["run_ref"] == "cond_fail"

    def test_failed_run_evidence_ref_nonempty(self):
        runs = [_run_record("cond_fail_ev", "failed")]
        alerts = scan_runs(runs)
        failed = [a for a in alerts if a["alert_type"] == "failed"]
        assert failed[0]["evidence_ref"], "evidence_ref must not be empty"


# --------------------------------------------------------------------------- #
#  scan_runs — healthy / empty                                                 #
# --------------------------------------------------------------------------- #

class TestHealthyRun:

    def test_provisional_run_no_alert(self):
        """A provisional run with no cost issue → empty alerts."""
        runs = [_run_record("cond_prov", "provisional")]
        alerts = scan_runs(runs)
        assert alerts == [], f"Healthy provisional run must produce no alerts; got: {alerts}"

    def test_planned_run_no_alert(self):
        """A planned run → empty alerts."""
        runs = [_run_record("cond_plan", "planned")]
        alerts = scan_runs(runs)
        assert alerts == [], f"Planned run must produce no alerts; got: {alerts}"

    def test_empty_runs_list_no_alert(self):
        """An empty runs list → empty alerts."""
        alerts = scan_runs([])
        assert alerts == []

    def test_run_manifest_stalled_status_fires(self):
        """run_manifest with stalled status → stalled alert."""
        runs = [_run_manifest("run_manifest_stall", "stalled")]
        alerts = scan_runs(runs)
        types = [a["alert_type"] for a in alerts]
        assert "stalled" in types


# --------------------------------------------------------------------------- #
#  scan_runs — cost spike                                                      #
# --------------------------------------------------------------------------- #

class TestCostSpike:

    def test_cost_spike_fires_when_one_run_far_above_mean(self):
        """One run with cost >2× mean across the batch → cost_spike alert."""
        runs = [
            _run_record("cond_cheap1", "provisional", cost=10.0),
            _run_record("cond_cheap2", "provisional", cost=10.0),
            _run_record("cond_spike", "provisional", cost=100.0),
        ]
        alerts = scan_runs(runs)
        types = [a["alert_type"] for a in alerts]
        assert "cost_spike" in types

    def test_cost_spike_bound_to_correct_run(self):
        runs = [
            _run_record("cond_cheap1", "provisional", cost=10.0),
            _run_record("cond_cheap2", "provisional", cost=10.0),
            _run_record("cond_spike", "provisional", cost=100.0),
        ]
        alerts = scan_runs(runs)
        spike = [a for a in alerts if a["alert_type"] == "cost_spike"]
        assert spike, "Expected cost_spike alert"
        assert spike[0]["run_ref"] == "cond_spike"

    def test_no_cost_spike_for_single_run(self):
        """Single run — cost_spike check requires ≥2 runs with cost, so no spike."""
        runs = [_run_record("cond_single", "provisional", cost=9999.0)]
        alerts = scan_runs(runs)
        types = [a["alert_type"] for a in alerts]
        assert "cost_spike" not in types

    def test_no_cost_spike_when_costs_uniform(self):
        """Uniform costs → no cost_spike."""
        runs = [
            _run_record("cond_a", "provisional", cost=50.0),
            _run_record("cond_b", "provisional", cost=50.0),
            _run_record("cond_c", "provisional", cost=50.0),
        ]
        alerts = scan_runs(runs)
        types = [a["alert_type"] for a in alerts]
        assert "cost_spike" not in types


# --------------------------------------------------------------------------- #
#  build_alerts — bundle-level + schema validation                             #
# --------------------------------------------------------------------------- #

class TestBuildAlerts:

    def test_build_alerts_schema_valid_stalled(self):
        """build_alerts output with alerts validates against monitor_alert.schema.json."""
        runs = [_run_record("cond_sv", "stalled")]
        result = build_alerts(runs)
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_build_alerts_schema_valid_empty(self):
        """build_alerts output with empty alerts also validates."""
        runs = [_run_record("cond_empty", "provisional")]
        result = build_alerts(runs)
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema errors on clean result: {errors}"

    def test_build_alerts_healthy_run_empty(self):
        """Healthy provisional run → build_alerts returns {"alerts": []}."""
        runs = [_run_record("cond_h", "provisional")]
        result = build_alerts(runs)
        assert result == {"alerts": []}

    def test_build_alerts_deterministic(self):
        """Two calls with the same input return identical results."""
        runs = [
            _run_record("cond_d1", "stalled"),
            _run_record("cond_d2", "provisional", cost=200.0),
        ]
        budget = _budget(100.0)
        r1 = build_alerts(runs, budget)
        r2 = build_alerts(runs, budget)
        assert r1 == r2, "build_alerts must be deterministic"

    def test_build_alerts_multiple_issues(self):
        """A stalled run + an over-budget run → both alert types present."""
        runs = [
            _run_record("cond_s2", "stalled"),
            _run_record("cond_ob3", "provisional", cost=500.0),
        ]
        result = build_alerts(runs, budget=_budget(100.0))
        types = {a["alert_type"] for a in result["alerts"]}
        assert "stalled" in types
        assert "over_budget" in types
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema errors on multi-alert result: {errors}"
