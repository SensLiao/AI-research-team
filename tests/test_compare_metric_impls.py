"""Tests for compare_metric_impls.py — deterministic core of the metric-implementation-auditor gate.

Verifies:
- Consistent metric implementations across conditions -> PASS.
- Different impl_ref for same metric across conditions -> BLOCK.
- Different spacing for same metric -> BLOCK.
- Different postprocess for same metric -> BLOCK.
- Profile-declared metric missing from a condition -> BLOCK.
- Profile canonical impl_ref mismatch -> BLOCK.
- Proven against the REAL cv-medical-segmentation.profile.yaml (no dead gate).
"""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.tools.compare_metric_impls import build_report, check_metric_impls
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# ---- helpers ------------------------------------------------------------------

def _cond(
    cid: str,
    metric_impls: dict | None = None,
) -> dict:
    """Build a condition dict with metric_impls."""
    return {
        "condition_id": cid,
        "metric_impls": metric_impls or {},
    }


def _impl(
    impl_ref: str | None = "monai.metrics.DiceMetric",
    spacing: object = None,
    postprocess: str | None = "argmax",
) -> dict:
    return {"impl_ref": impl_ref, "spacing": spacing, "postprocess": postprocess}


# Profile stub with Dice declared and a canonical implementation_ref
_PROFILE_WITH_CANONICAL = {
    "profile_id": "test-profile",
    "display_name": "Test Profile",
    "split_policy": {
        "default_split_unit": "patient",
        "allowed_split_units": ["patient"],
        "forbidden_split_units": [],
    },
    "metrics": [
        {
            "name": "Dice",
            "higher_is_better": True,
            "implementation_ref": "monai.metrics.DiceMetric",
            "valid_range": [0.0, 1.0],
        },
        {
            "name": "HD95",
            "higher_is_better": False,
            "implementation_ref": "monai.metrics.HausdorffDistanceMetric",
            "valid_range": [0.0, None],
        },
    ],
    "hard_invariants": ["test"],
}

_PROFILE_NO_CANONICAL = {
    "profile_id": "test-no-canonical",
    "display_name": "Test No Canonical",
    "split_policy": {
        "default_split_unit": "patient",
        "allowed_split_units": ["patient"],
        "forbidden_split_units": [],
    },
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "implementation_ref": None},
    ],
    "hard_invariants": ["test"],
}


# ---- happy-path tests ---------------------------------------------------------

def test_identical_impls_passes():
    """Two conditions with identical metric implementations -> PASS."""
    conditions = [
        _cond("c0", {"Dice": _impl(), "HD95": _impl("monai.metrics.HausdorffDistanceMetric")}),
        _cond("c1", {"Dice": _impl(), "HD95": _impl("monai.metrics.HausdorffDistanceMetric")}),
    ]
    r = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert r["verdict"] == "PASS"
    assert r["violations"] == []


def test_no_profile_consistent_impls_passes():
    """No profile provided; conditions have identical impls -> PASS."""
    conditions = [
        _cond("c0", {"Dice": _impl()}),
        _cond("c1", {"Dice": _impl()}),
    ]
    r = build_report(conditions)
    assert r["verdict"] == "PASS"


def test_empty_conditions_blocks():
    """No conditions at all -> BLOCK (structural error)."""
    r = build_report([])
    assert r["verdict"] == "BLOCK"
    assert any("no conditions" in v for v in r["violations"])


# ---- impl_ref mismatch tests --------------------------------------------------

def test_different_impl_ref_blocks():
    """Two conditions use different impl_ref for Dice -> BLOCK."""
    conditions = [
        _cond("c0", {"Dice": _impl("monai.metrics.DiceMetric")}),
        _cond("c1", {"Dice": _impl("custom.dice_v2")}),
    ]
    r = build_report(conditions)
    assert r["verdict"] == "BLOCK"
    assert any("impl_ref" in v for v in r["violations"])


def test_different_spacing_blocks():
    """Two conditions use different spacing for the same metric -> BLOCK."""
    conditions = [
        _cond("c0", {"Dice": {"impl_ref": "monai.metrics.DiceMetric", "spacing": [1, 1, 1], "postprocess": "argmax"}}),
        _cond("c1", {"Dice": {"impl_ref": "monai.metrics.DiceMetric", "spacing": [0.5, 0.5, 0.5], "postprocess": "argmax"}}),
    ]
    r = build_report(conditions)
    assert r["verdict"] == "BLOCK"
    assert any("spacing" in v for v in r["violations"])


def test_different_postprocess_blocks():
    """Two conditions use different postprocess for the same metric -> BLOCK."""
    conditions = [
        _cond("c0", {"Dice": {"impl_ref": "monai.metrics.DiceMetric", "spacing": None, "postprocess": "argmax"}}),
        _cond("c1", {"Dice": {"impl_ref": "monai.metrics.DiceMetric", "spacing": None, "postprocess": "sigmoid_threshold"}}),
    ]
    r = build_report(conditions)
    assert r["verdict"] == "BLOCK"
    assert any("postprocess" in v for v in r["violations"])


# ---- missing metric tests -----------------------------------------------------

def test_missing_profile_metric_in_one_condition_blocks():
    """Profile declares HD95 but one condition omits it -> BLOCK."""
    conditions = [
        _cond("c0", {
            "Dice": _impl(),
            "HD95": _impl("monai.metrics.HausdorffDistanceMetric"),
        }),
        _cond("c1", {
            "Dice": _impl(),
            # HD95 missing from c1
        }),
    ]
    r = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert r["verdict"] == "BLOCK"
    assert any("hd95" in v.lower() and "missing" in v.lower() for v in r["violations"])


def test_all_profile_metrics_missing_from_both_blocks():
    """Profile declares Dice and HD95 but neither condition has them -> BLOCK."""
    conditions = [
        _cond("c0", {}),
        _cond("c1", {}),
    ]
    r = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert r["verdict"] == "BLOCK"


# ---- canonical impl_ref mismatch tests ----------------------------------------

def test_condition_uses_wrong_canonical_impl_blocks():
    """Condition uses an impl_ref that differs from profile's canonical -> BLOCK."""
    conditions = [
        _cond("c0", {"Dice": _impl("monai.metrics.DiceMetric")}),
        _cond("c1", {"Dice": _impl("wrong.impl")}),
    ]
    r = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert r["verdict"] == "BLOCK"
    assert any("canonical" in v for v in r["violations"])


def test_no_canonical_impl_skips_canonical_check():
    """When profile.implementation_ref is null, canonical check is skipped -> PASS."""
    conditions = [
        _cond("c0", {"Dice": _impl("anything")}),
        _cond("c1", {"Dice": _impl("anything")}),
    ]
    r = build_report(conditions, _PROFILE_NO_CANONICAL)
    assert r["verdict"] == "PASS"


# ---- check_metric_impls unit test ---------------------------------------------

def test_check_returns_empty_for_clean():
    """check_metric_impls returns [] for consistent impls."""
    conditions = [
        _cond("c0", {"Dice": _impl()}),
        _cond("c1", {"Dice": _impl()}),
    ]
    v = check_metric_impls(conditions, _PROFILE_NO_CANONICAL)
    assert v == []


# ---- report structure tests ---------------------------------------------------

def test_checked_metrics_populated():
    """build_report populates checked_metrics with all known metric names."""
    conditions = [
        _cond("c0", {"Dice": _impl(), "HD95": _impl("monai.metrics.HausdorffDistanceMetric")}),
        _cond("c1", {"Dice": _impl(), "HD95": _impl("monai.metrics.HausdorffDistanceMetric")}),
    ]
    r = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert "dice" in r["checked_metrics"]
    assert "hd95" in r["checked_metrics"]


# ---- real-profile BLOCK proof (CRITICAL — no dead gate) -----------------------

def test_real_shipped_profile_blocks_missing_metric():
    """CRITICAL: Load the REAL cv-medical-segmentation.profile.yaml.
    The profile declares Dice, HD95, IoU, clDice, etc.
    A crafted input where one condition is missing 'Dice' must BLOCK.
    This proves the gate actually fires on the production profile shape."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # Build conditions: c0 has Dice, c1 is missing Dice
    conditions = [
        _cond("c0", {
            "Dice": _impl("monai.metrics.DiceMetric"),
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
        _cond("c1", {
            # Dice deliberately omitted
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
    ]
    r = build_report(conditions, profile)
    assert r["verdict"] == "BLOCK", (
        f"Expected BLOCK because Dice is missing from c1, got PASS. Violations: {r['violations']}"
    )
    assert any("dice" in v.lower() for v in r["violations"])


def test_real_shipped_profile_blocks_impl_mismatch():
    """CRITICAL: With the REAL cv-medical profile, two conditions using different
    impl_ref for Dice must BLOCK."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # All profile metrics present in both conditions, but Dice impl_ref differs
    all_metrics = [m["name"] for m in profile.get("metrics", [])]
    base_impl: dict = {}
    for mn in all_metrics:
        base_impl[mn] = {"impl_ref": f"canonical.{mn.lower()}", "spacing": None, "postprocess": None}

    c0_impl = dict(base_impl)
    c1_impl = dict(base_impl)
    c1_impl["Dice"] = {**c0_impl["Dice"], "impl_ref": "different.DiceImpl"}

    conditions = [
        _cond("c0", c0_impl),
        _cond("c1", c1_impl),
    ]
    r = build_report(conditions, profile)
    assert r["verdict"] == "BLOCK", (
        f"Expected BLOCK because Dice impl_ref differs, got PASS. Violations: {r['violations']}"
    )


def test_real_shipped_profile_passes_when_consistent():
    """With the REAL cv-medical profile, all conditions consistent -> PASS.
    Note: profile has no implementation_ref values (all null), so canonical check is skipped."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    all_metrics = [m["name"] for m in profile.get("metrics", [])]
    shared_impl: dict = {
        mn: {"impl_ref": f"monai.{mn.lower()}", "spacing": None, "postprocess": "argmax"}
        for mn in all_metrics
    }

    conditions = [
        _cond("c0", dict(shared_impl)),
        _cond("c1", dict(shared_impl)),
    ]
    r = build_report(conditions, profile)
    assert r["verdict"] == "PASS", (
        f"Expected PASS for consistent impls, got BLOCK. Violations: {r['violations']}"
    )


# ---- M5 regression: Check 3 alive when profile DOES declare implementation_ref -----

def test_check3_fires_when_profile_has_implementation_ref():
    """M5 regression: proves Check 3 (canonical impl_ref) is ALIVE and enforced when
    the profile declares a non-null implementation_ref for a metric.
    Uses _PROFILE_WITH_CANONICAL (synthetic profile with Dice -> 'monai.metrics.DiceMetric').
    A condition that uses a different impl_ref must BLOCK via Check 3."""
    conditions = [
        _cond("c0", {
            "Dice": _impl("monai.metrics.DiceMetric"),  # matches canonical
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
        _cond("c1", {
            "Dice": _impl("monai.metrics.DiceMetric"),  # matches canonical
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
    ]
    # Sanity: consistent impls with canonical refs -> PASS
    r_pass = build_report(conditions, _PROFILE_WITH_CANONICAL)
    assert r_pass["verdict"] == "PASS", (
        f"Expected PASS with canonical impls, got BLOCK. Violations: {r_pass['violations']}"
    )

    # Now one condition diverges from the canonical implementation_ref
    conditions_bad = [
        _cond("c0", {
            "Dice": _impl("monai.metrics.DiceMetric"),  # canonical
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
        _cond("c1", {
            "Dice": _impl("non_canonical.dice_impl"),  # diverges from canonical
            "HD95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": None, "postprocess": None},
        }),
    ]
    r_block = build_report(conditions_bad, _PROFILE_WITH_CANONICAL)
    assert r_block["verdict"] == "BLOCK", (
        f"Expected BLOCK because c1 Dice impl_ref diverges from canonical, "
        f"got PASS. Violations: {r_block['violations']}"
    )
    assert any("canonical" in v for v in r_block["violations"]), (
        f"Expected a 'canonical' violation message, got: {r_block['violations']}"
    )
