"""Real tests for the baseline-comparison-auditor deterministic core.

Verifies that check_baseline_asymmetry flags asymmetric budget/data/metric/postprocess
conditions between a baseline and a method, and that a fair comparison returns no flags.
The 'real-profile' test uses the shipped cv-medical-segmentation profile to prove no
false positives on a well-formed comparison.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.baseline_audit import (
    build_report,
    check_baseline_asymmetry,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_FAIR_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "epochs": 200,
                "metric_impl_ref": "monai_dice_v2",
                "postprocess": "threshold_0.5",
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "epochs": 200,
                "metric_impl_ref": "monai_dice_v2",
                "postprocess": "threshold_0.5",
                "baseline": False,
            },
        },
    ]
}

_BUDGET_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "epochs": 100,
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "epochs": 400,   # <-- budget asymmetry
                "baseline": False,
            },
        },
    ]
}

_DATA_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "aaa111",
                "epochs": 200,
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "bbb222",   # <-- data asymmetry
                "epochs": 200,
                "baseline": False,
            },
        },
    ]
}

_METRIC_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "metric_impl_ref": "sklearn_dice",   # <-- different impl
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "metric_impl_ref": "monai_dice_v2",
                "baseline": False,
            },
        },
    ]
}

_POSTPROCESS_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "postprocess": "threshold_0.5",
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "postprocess": "crf_refinement",   # <-- postprocess asymmetry
                "baseline": False,
            },
        },
    ]
}


# --------------------------------------------------------------------------- #
#  Tests — happy path                                                          #
# --------------------------------------------------------------------------- #

def test_clean_comparison_has_no_flags():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _FAIR_MATRIX
    )
    assert flags == [], f"Expected no flags for a fair comparison; got: {flags}"


def test_build_report_clean_is_true_when_no_flags():
    report = build_report("baseline_unet", "method_sam", _FAIR_MATRIX)
    assert report["clean"] is True
    assert report["asymmetry_flags"] == []
    assert "baseline_unet" in report["conditions_compared"]
    assert "method_sam" in report["conditions_compared"]


# --------------------------------------------------------------------------- #
#  Tests — crafted-bad inputs that the checker must flag                       #
# --------------------------------------------------------------------------- #

def test_budget_asymmetry_is_flagged():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _BUDGET_ASYMMETRIC_MATRIX
    )
    assert len(flags) >= 1, "Budget asymmetry should produce at least one flag"
    dimensions = [f["dimension"] for f in flags]
    assert "budget" in dimensions, f"Expected 'budget' in flagged dimensions; got {dimensions}"


def test_data_asymmetry_is_flagged():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _DATA_ASYMMETRIC_MATRIX
    )
    assert len(flags) >= 1, "Data asymmetry should produce at least one flag"
    dimensions = [f["dimension"] for f in flags]
    assert "data" in dimensions, f"Expected 'data' in flagged dimensions; got {dimensions}"


def test_metric_impl_asymmetry_is_flagged():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _METRIC_ASYMMETRIC_MATRIX
    )
    assert len(flags) >= 1, "Metric impl_ref asymmetry should produce at least one flag"
    dimensions = [f["dimension"] for f in flags]
    assert "metric" in dimensions, f"Expected 'metric' in flagged dimensions; got {dimensions}"


def test_postprocess_asymmetry_is_flagged():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _POSTPROCESS_ASYMMETRIC_MATRIX
    )
    assert len(flags) >= 1, "Postprocess asymmetry should produce at least one flag"
    dimensions = [f["dimension"] for f in flags]
    assert "postprocess" in dimensions, (
        f"Expected 'postprocess' in flagged dimensions; got {dimensions}"
    )


def test_build_report_clean_is_false_when_flags_present():
    report = build_report("baseline_unet", "method_sam", _BUDGET_ASYMMETRIC_MATRIX)
    assert report["clean"] is False
    assert len(report["asymmetry_flags"]) >= 1


def test_flag_includes_condition_pair():
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _DATA_ASYMMETRIC_MATRIX
    )
    assert len(flags) >= 1
    assert flags[0]["condition_pair"] == ["baseline_unet", "method_sam"]


# --------------------------------------------------------------------------- #
#  Real-profile test (no false positives on a well-formed profile-shaped input) #
# --------------------------------------------------------------------------- #

def test_real_profile_no_false_positives_on_fair_comparison():
    """Load the real cv-medical profile; a fair comparison with equal factors must pass."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # Build a fair matrix using the profile's canonical metric names
    primary_metric = profile["metrics"][0]["name"]  # "Dice"
    fair_matrix = {
        "conditions": [
            {
                "id": "baseline_unet3d",
                "factors": {
                    "data_hash": "sha256_medical_train_v1",
                    "epochs": 300,
                    "metric_impl_ref": "monai_dice_metric",
                    "postprocess": "connected_components_largest",
                    "primary_metric": primary_metric,
                    "baseline": True,
                },
            },
            {
                "id": "method_sammed3d",
                "factors": {
                    "data_hash": "sha256_medical_train_v1",
                    "epochs": 300,
                    "metric_impl_ref": "monai_dice_metric",
                    "postprocess": "connected_components_largest",
                    "primary_metric": primary_metric,
                    "baseline": False,
                },
            },
        ]
    }

    flags = check_baseline_asymmetry("baseline_unet3d", "method_sammed3d", fair_matrix, profile)
    assert flags == [], (
        f"Real-profile fair comparison should produce no flags; got: {flags}"
    )


def test_real_profile_budget_asymmetry_fires():
    """Load the real cv-medical profile; a budget asymmetry must be flagged."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    matrix = {
        "conditions": [
            {
                "id": "baseline_unet3d",
                "factors": {"data_hash": "same_hash", "epochs": 100, "baseline": True},
            },
            {
                "id": "method_sammed3d",
                "factors": {"data_hash": "same_hash", "epochs": 500, "baseline": False},
            },
        ]
    }

    flags = check_baseline_asymmetry("baseline_unet3d", "method_sammed3d", matrix, profile)
    assert any(f["dimension"] == "budget" for f in flags), (
        "Real-profile budget asymmetry (100 vs 500 epochs) must be flagged"
    )


# --------------------------------------------------------------------------- #
#  H1 REGRESSION TESTS                                                        #
# --------------------------------------------------------------------------- #

# H1(a): Absence on both conditions must be flagged (not treated as equal/clean)

_BOTH_BUDGET_ABSENT_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                # no budget key at all
                "data_hash": "abc123",
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                # no budget key at all
                "data_hash": "abc123",
                "baseline": False,
            },
        },
    ]
}

_BOTH_DATA_ABSENT_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {"baseline": True},
        },
        {
            "id": "method_sam",
            "factors": {"baseline": False},
        },
    ]
}


def test_h1a_both_conditions_missing_budget_is_flagged():
    """H1(a): When both conditions omit budget keys, that is a flag (not clean).

    Before fix: both sides return None → None==None → no flag → clean=True
    After fix: both absent → flag with '<absent>' sentinel → not clean
    """
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _BOTH_BUDGET_ABSENT_MATRIX
    )
    budget_flags = [f for f in flags if f["dimension"] == "budget"]
    assert len(budget_flags) >= 1, (
        "Both conditions omitting budget keys must produce a budget flag "
        "(absence is itself unverifiable — cannot confirm fairness). "
        f"Got flags: {flags}"
    )
    # Clean must be False
    report = build_report("baseline_unet", "method_sam", _BOTH_BUDGET_ABSENT_MATRIX)
    assert report["clean"] is False, (
        "build_report clean must be False when budget is absent on both conditions"
    )


def test_h1a_both_conditions_missing_data_hash_is_flagged():
    """H1(a): When both conditions omit data_hash, that is a flag (not clean)."""
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _BOTH_DATA_ABSENT_MATRIX
    )
    data_flags = [f for f in flags if f["dimension"] == "data"]
    assert len(data_flags) >= 1, (
        "Both conditions omitting data_hash must produce a data flag. "
        f"Got flags: {flags}"
    )


# H1(b): Profile-driven budget keys — max_epochs 4× asymmetry must be flagged

_MAX_EPOCHS_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "max_epochs": 50,    # 4× asymmetry vs method
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "max_epochs": 200,   # <-- 4× more budget
                "baseline": False,
            },
        },
    ]
}


def test_h1b_max_epochs_4x_asymmetry_is_flagged():
    """H1(b): max_epochs 4× asymmetry must be flagged (default budget key set includes max_epochs)."""
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _MAX_EPOCHS_ASYMMETRIC_MATRIX
    )
    budget_flags = [f for f in flags if f["dimension"] == "budget"]
    assert len(budget_flags) >= 1, (
        "max_epochs 50 vs 200 (4× asymmetry) must produce a budget flag. "
        f"Got flags: {flags}"
    )


_NUM_ITERATIONS_ASYMMETRIC_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "num_iterations": 25000,   # 4× asymmetry vs method
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "num_iterations": 100000,  # <-- 4× more iterations
                "baseline": False,
            },
        },
    ]
}


def test_fix5_num_iterations_4x_asymmetry_is_flagged_as_budget():
    """FIX 5: a num_iterations 4× asymmetry must be reported as a BUDGET asymmetry.

    Before fix: 'num_iterations' was not in _DEFAULT_BUDGET_KEYS, so a step/iteration-budgeted
    comparison fell through to the "no budget key declared on either condition" ABSENCE flag —
    the real 4× imbalance was masked as a generic absence note rather than a value asymmetry.
    After fix: num_iterations is a recognised default budget key → the 25000-vs-100000 gap is a
    genuine budget value asymmetry.
    """
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _NUM_ITERATIONS_ASYMMETRIC_MATRIX
    )
    budget_flags = [f for f in flags if f["dimension"] == "budget"]
    assert len(budget_flags) >= 1, (
        "num_iterations 25000 vs 100000 (4× asymmetry) must produce a budget flag. "
        f"Got flags: {flags}"
    )
    # It must be a VALUE asymmetry (both sides present, differing), not an absence flag.
    bf = budget_flags[0]
    assert bf["baseline_value"] == "25000" and bf["method_value"] == "100000", (
        "The budget flag must report the actual num_iterations values (a value asymmetry), "
        f"not an absence sentinel; got baseline_value={bf['baseline_value']!r}, "
        f"method_value={bf['method_value']!r}"
    )
    assert "<absent>" not in (bf["baseline_value"], bf["method_value"]), (
        "num_iterations is present on both sides — must not be reported as an absence flag"
    )


def test_h1b_profile_budget_keys_override_default():
    """H1(b): When profile declares budget_keys=['train_steps'], that key is checked instead."""
    profile_with_budget_keys = {
        "metrics": [
            {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
        ],
        "budget_keys": ["train_steps"],
    }
    matrix = {
        "conditions": [
            {
                "id": "baseline",
                "factors": {"data_hash": "abc", "train_steps": 10000, "baseline": True},
            },
            {
                "id": "method",
                "factors": {"data_hash": "abc", "train_steps": 100000, "baseline": False},
            },
        ]
    }
    flags = check_baseline_asymmetry("baseline", "method", matrix, profile_with_budget_keys)
    assert any(f["dimension"] == "budget" for f in flags), (
        "Profile-declared budget key 'train_steps' with 10x asymmetry must be flagged"
    )


# H1(c): primary_metric Dice-vs-IoU must be flagged without impl_map

_PRIMARY_METRIC_MISMATCH_NO_PROFILE_MATRIX = {
    "conditions": [
        {
            "id": "baseline_unet",
            "factors": {
                "data_hash": "abc123",
                "epochs": 200,
                "primary_metric": "Dice",
                "baseline": True,
            },
        },
        {
            "id": "method_sam",
            "factors": {
                "data_hash": "abc123",
                "epochs": 200,
                "primary_metric": "IoU",   # <-- different primary metric
                "baseline": False,
            },
        },
    ]
}


def test_h1c_dice_vs_iou_primary_metric_flagged_without_profile():
    """H1(c): Dice vs IoU as primary_metric must be flagged even with no profile/impl_map.

    Before fix: only flagged when impl_map was non-empty (required a profile with
    implementation_ref entries). IoU-vs-Dice comparison was silently permitted.
    After fix: primary_metric mismatch is flagged regardless of impl_map.
    """
    flags = check_baseline_asymmetry(
        "baseline_unet", "method_sam", _PRIMARY_METRIC_MISMATCH_NO_PROFILE_MATRIX,
        profile=None  # no profile → no impl_map
    )
    metric_flags = [f for f in flags if f["dimension"] == "metric"]
    assert len(metric_flags) >= 1, (
        "primary_metric Dice vs IoU must produce a metric flag even without a profile. "
        f"Got flags: {flags}"
    )


def test_h1c_same_primary_metric_no_false_positive():
    """H1(c): Same primary_metric on both sides must not produce a metric flag."""
    matrix = {
        "conditions": [
            {
                "id": "baseline",
                "factors": {"data_hash": "abc", "epochs": 200, "primary_metric": "Dice", "baseline": True},
            },
            {
                "id": "method",
                "factors": {"data_hash": "abc", "epochs": 200, "primary_metric": "Dice", "baseline": False},
            },
        ]
    }
    flags = check_baseline_asymmetry("baseline", "method", matrix, profile=None)
    metric_flags = [f for f in flags if f["dimension"] == "metric"]
    assert len(metric_flags) == 0, (
        "Same primary_metric on both sides must not produce a metric flag. "
        f"Got flags: {metric_flags}"
    )
