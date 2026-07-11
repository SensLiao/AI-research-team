"""Real tests for the sanity-checker deterministic core (ANALYZE hard gate).

Screens a result_summary for NaN/Inf/non-numeric, out-of-range values (per the profile's declared
metric ranges), corrupt baselines, and DIRECTION-AWARE leakage-smell (so a legitimate regression on a
lower-is-better metric is not mistaken for leakage). verdict derived from violations, never set by hand.
Ranges/directions/threshold come from the domain profile — proven here against the REAL shipped profile.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.sanity_checker import build_report, check_sanity
from research_agent_teams.tools.validate_artifact import PROFILE_DIR

# profile in the REAL shape (metrics[].valid_range + higher_is_better + leakage_delta)
_PROFILE = {
    "metrics": [
        {"name": "dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
        {"name": "hd95", "higher_is_better": False, "valid_range": [0.0, None]},  # lower better, unbounded above
    ],
    "leakage_delta": 0.5,
}


def _rs(findings):
    return {"status": "provisional", "findings": findings, "caveats": [], "can_cite_thesis": False}


def test_clean_results_pass():
    rs = _rs([{"metric": "dice", "value": 0.81, "condition_id": "c1", "baseline_value": 0.78}])
    r = build_report(rs, profile=_PROFILE)
    assert r["verdict"] == "PASS" and r["violations"] == []
    assert r["checked_metrics"] == ["dice"]


def test_nan_value_blocks():
    rs = _rs([{"metric": "dice", "value": float("nan"), "condition_id": "c1"}])
    assert check_sanity(rs, profile=_PROFILE)["nan_or_inf"] is True
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_inf_value_blocks():
    rs = _rs([{"metric": "dice", "value": float("inf"), "condition_id": "c1"}])
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_bool_value_blocks():
    rs = _rs([{"metric": "dice", "value": True, "condition_id": "c1"}])  # bool is not a real metric value
    out = check_sanity(rs, profile=_PROFILE)
    assert out["nan_or_inf"] is True and build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_out_of_range_value_blocks():
    rs = _rs([{"metric": "dice", "value": 1.5, "condition_id": "c1"}])  # dice > 1.0 is impossible
    out = check_sanity(rs, profile=_PROFILE)
    assert out["out_of_range"] == ["dice"]
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_unbounded_upper_range_allows_large_value():
    rs = _rs([{"metric": "hd95", "value": 500.0, "condition_id": "c1"}])  # hd95 range [0, null] -> ok
    assert build_report(rs, profile=_PROFILE)["verdict"] == "PASS"


def test_leakage_smell_higher_is_better_blocks():
    rs = _rs([{"metric": "dice", "value": 0.99, "condition_id": "c1", "baseline_value": 0.40}])  # +0.59 jump
    assert check_sanity(rs, profile=_PROFILE)["leakage_smell"] is True
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_lower_is_better_regression_is_not_leakage():
    # hd95 5 -> 500 is a legitimate (bad) regression on a lower-is-better metric — NOT leakage, must PASS
    rs = _rs([{"metric": "hd95", "value": 500.0, "condition_id": "c1", "baseline_value": 5.0}])
    r = build_report(rs, profile=_PROFILE)
    assert r["leakage_smell"] is False and r["verdict"] == "PASS"


def test_lower_is_better_impossible_improvement_blocks():
    # hd95 50 -> 0.01 is an implausibly large IMPROVEMENT on a lower-is-better metric — leakage smell
    rs = _rs([{"metric": "hd95", "value": 0.01, "condition_id": "c1", "baseline_value": 50.0}])
    assert check_sanity(rs, profile=_PROFILE)["leakage_smell"] is True
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_corrupt_baseline_blocks():
    rs = _rs([{"metric": "dice", "value": 0.8, "condition_id": "c1", "baseline_value": float("nan")}])
    assert any("corrupt" in x for x in check_sanity(rs, profile=_PROFILE)["violations"])
    assert build_report(rs, profile=_PROFILE)["verdict"] == "BLOCK"


def test_metric_without_declared_range_skips_range_and_leakage():
    # a metric the profile does not declare: NaN still checked, but range/leakage skipped (no false block)
    rs = _rs([{"metric": "custom", "value": 42.0, "condition_id": "c1", "baseline_value": 0.0}])
    assert build_report(rs, profile=_PROFILE)["verdict"] == "PASS"


def test_metric_name_matching_is_case_insensitive():
    # profile declares "Dice"; a finding reporting "dice" must still hit range/leakage (not silently skip)
    profile = {"metrics": [{"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]}],
               "leakage_delta": 0.5}
    rs = _rs([{"metric": "dice", "value": 1.5, "condition_id": "c1"}])
    assert build_report(rs, profile=profile)["verdict"] == "BLOCK"


def test_real_shipped_profile_blocks_impossible_dice():
    # CRITICAL-fix proof: load the REAL cv-medical profile (production shape) and confirm the
    # out-of-range gate actually fires (it was dead before metric ranges lived in the profile).
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)
    impossible = _rs([{"metric": "Dice", "value": 9.9, "condition_id": "c1"}])
    assert build_report(impossible, profile=profile)["verdict"] == "BLOCK"
    fine = _rs([{"metric": "Dice", "value": 0.85, "condition_id": "c1"}])
    assert build_report(fine, profile=profile)["verdict"] == "PASS"
