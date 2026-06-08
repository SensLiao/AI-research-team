"""Real tests for the visualization-auditor deterministic core.

Verifies that check_viz_truncation flags y-axis truncation when the axis min is above
the metric's valid_range lower bound (e.g. y-axis starts at 0.94 for a [0,1] metric),
and that properly ranged figures pass.
Uses the real cv-medical profile for the 'gate fires on real profile' test.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.viz_audit import (
    build_report,
    check_viz_truncation,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PROFILE = {
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
        {"name": "HD95", "higher_is_better": False, "valid_range": [0.0, None]},
        {"name": "clDice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
    ],
}


def _bundle(figures: list) -> dict:
    return {"run_ref": "run_001", "figures": figures}


def _fig(figure_id: str, metrics: list, y_min: float, y_max: float = 1.0) -> dict:
    return {
        "figure_id": figure_id,
        "figure_type": "bar",
        "title": f"Figure {figure_id}",
        "data_source": "result_summary",
        "metrics": metrics,
        "conditions": ["baseline", "method"],
        "y_axis": {"min": y_min, "max": y_max, "label": metrics[0] if metrics else ""},
        "x_axis": None,
    }


# --------------------------------------------------------------------------- #
#  Tests — happy path                                                          #
# --------------------------------------------------------------------------- #

def test_full_range_axis_is_clean():
    """y-axis min=0.0 for a [0,1] metric → no truncation flag."""
    bundle = _bundle([_fig("fig1", ["Dice"], y_min=0.0, y_max=1.0)])
    flags = check_viz_truncation(bundle, _PROFILE)
    assert flags == [], f"Expected no truncation flags for full-range axis; got: {flags}"


def test_clean_report_builds_correctly():
    bundle = _bundle([_fig("fig1", ["Dice"], y_min=0.0)])
    report = build_report(bundle, _PROFILE)
    assert report["clean"] is True
    assert report["axis_truncation_flags"] == []
    assert "fig1" in report["figures_audited"]


def test_metric_without_profile_range_not_flagged():
    """Metric not in profile → no valid_range → no flag (no false positive)."""
    bundle = _bundle([{
        "figure_id": "fig_custom",
        "figure_type": "line",
        "title": "Custom Metric",
        "data_source": "result_summary",
        "metrics": ["custom_score"],
        "conditions": [],
        "y_axis": {"min": 0.5, "max": 1.0},
        "x_axis": None,
    }])
    flags = check_viz_truncation(bundle, _PROFILE)
    assert flags == [], "Metric without declared profile range should not produce a flag"


# --------------------------------------------------------------------------- #
#  Tests — crafted-bad inputs                                                  #
# --------------------------------------------------------------------------- #

def test_truncated_yaxis_min_094_on_01_metric_is_flagged():
    """The golden test: y-axis min=0.94 for Dice [0,1] must be flagged."""
    bundle = _bundle([_fig("fig2", ["Dice"], y_min=0.94, y_max=1.0)])
    flags = check_viz_truncation(bundle, _PROFILE)
    assert len(flags) >= 1, (
        "y-axis min=0.94 for Dice (valid range [0,1]) must produce an axis_truncation flag"
    )
    assert flags[0]["figure_id"] == "fig2"
    assert flags[0]["metric"] == "Dice"
    assert flags[0]["axis"] == "y"
    assert flags[0]["declared_min"] == 0.94


def test_build_report_clean_false_on_truncated_axis():
    bundle = _bundle([_fig("fig2", ["Dice"], y_min=0.94)])
    report = build_report(bundle, _PROFILE)
    assert report["clean"] is False
    assert len(report["axis_truncation_flags"]) >= 1


def test_multiple_figures_one_truncated():
    """Two figures: one clean, one truncated — only the truncated one flagged."""
    bundle = _bundle([
        _fig("fig_clean", ["Dice"], y_min=0.0),
        _fig("fig_truncated", ["Dice"], y_min=0.90),
    ])
    flags = check_viz_truncation(bundle, _PROFILE)
    flagged_ids = {f["figure_id"] for f in flags}
    assert "fig_truncated" in flagged_ids
    assert "fig_clean" not in flagged_ids


def test_cldice_truncation_flagged():
    """clDice [0,1]: y-axis min=0.85 is truncation."""
    bundle = _bundle([_fig("fig3", ["clDice"], y_min=0.85)])
    flags = check_viz_truncation(bundle, _PROFILE)
    assert any(f["metric"] == "clDice" for f in flags), (
        "clDice axis truncation (min=0.85 vs valid_min=0.0) should be flagged"
    )


def test_hd95_non_zero_min_flagged():
    """HD95 valid_range [0, None]: y-axis min=5.0 is truncation (starts above 0)."""
    bundle = _bundle([{
        "figure_id": "fig_hd95",
        "figure_type": "bar",
        "title": "HD95",
        "data_source": "result_summary",
        "metrics": ["HD95"],
        "conditions": [],
        "y_axis": {"min": 5.0, "max": 100.0},
        "x_axis": None,
    }])
    flags = check_viz_truncation(bundle, _PROFILE)
    assert any(f["metric"] == "HD95" for f in flags), (
        "HD95 axis min=5.0 when valid_min=0.0 should be flagged"
    )


# --------------------------------------------------------------------------- #
#  Real-profile test                                                           #
# --------------------------------------------------------------------------- #

def test_real_profile_truncated_dice_axis_fires():
    """Load the real cv-medical profile; truncated Dice y-axis must fire."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    bundle = _bundle([_fig("fig_real", ["Dice"], y_min=0.95, y_max=1.0)])
    flags = check_viz_truncation(bundle, profile)
    assert len(flags) >= 1, (
        "Dice y-axis min=0.95 should fire axis_truncation against real cv-medical profile"
    )
    assert flags[0]["valid_min"] == 0.0


def test_real_profile_full_range_no_truncation():
    """Real profile: Dice y-axis min=0.0 should not be flagged."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    bundle = _bundle([_fig("fig_full", ["Dice"], y_min=0.0, y_max=1.0)])
    flags = check_viz_truncation(bundle, profile)
    assert flags == [], (
        "Full-range Dice axis [0, 1] should not produce any truncation flags"
    )
