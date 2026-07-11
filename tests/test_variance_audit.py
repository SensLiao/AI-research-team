"""Real tests for the variance-analyzer deterministic core.

Verifies that check_variance flags insufficient seed counts (1 seed labeled 'stable',
fewer seeds than the profile threshold or built-in default), and that an adequate
seed count returns seed_count_insufficient=False.
Uses the real cv-medical profile for the 'no false positive' test.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.variance_audit import (
    DEFAULT_MIN_SEEDS,
    STABILITY_FRACTION,
    build_report,
    check_variance,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures: run_records                                                       #
# --------------------------------------------------------------------------- #

def _make_run_records(n: int, base_dice: float = 0.85) -> list:
    return [
        {
            "condition_id": "method_sam",
            "status": "provisional",
            "provenance": {"config_hash": f"cfg{i}", "seed": i},
            "metrics": {"Dice": base_dice + i * 0.005},
        }
        for i in range(n)
    ]


_PROFILE_WITH_MIN_SEEDS = {
    "min_seeds": 5,
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
    ],
    "hard_invariants": ["all splits must be patient-level"],
}

_PROFILE_WITHOUT_MIN_SEEDS = {
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
    ],
    "hard_invariants": ["all splits must be patient-level"],
}


# --------------------------------------------------------------------------- #
#  Tests — happy path                                                          #
# --------------------------------------------------------------------------- #

def test_adequate_seeds_no_insufficiency():
    """DEFAULT_MIN_SEEDS runs should not be flagged as insufficient."""
    result = check_variance(n_seeds=DEFAULT_MIN_SEEDS, profile=None)
    assert result["seed_count_insufficient"] is False


def test_more_than_default_seeds_passes():
    result = check_variance(n_seeds=DEFAULT_MIN_SEEDS + 2, profile=None)
    assert result["seed_count_insufficient"] is False


def test_build_report_adequate_seeds():
    run_records = _make_run_records(DEFAULT_MIN_SEEDS)
    report = build_report("method_sam", run_records, profile=None)
    assert report["seed_count_insufficient"] is False
    assert report["n_seeds"] == DEFAULT_MIN_SEEDS
    assert len(report["per_metric_variance"]) == 1


# --------------------------------------------------------------------------- #
#  Tests — crafted-bad inputs that the checker must flag                       #
# --------------------------------------------------------------------------- #

def test_one_seed_flags_insufficient():
    """1 seed is below the default minimum of 3."""
    result = check_variance(n_seeds=1, profile=None)
    assert result["seed_count_insufficient"] is True, (
        "1 seed should be flagged as insufficient (below default min=3)"
    )


def test_one_seed_labeled_stable_flags_insufficient():
    """1 seed labeled 'stable' must be flagged regardless of threshold."""
    result = check_variance(n_seeds=1, profile=None, stability_label="stable")
    assert result["seed_count_insufficient"] is True, (
        "stability_label='stable' with 1 seed must be flagged as insufficient"
    )


def test_profile_min_seeds_5_with_3_seeds_flags():
    """Profile declares min_seeds=5; 3 seeds should be flagged."""
    result = check_variance(n_seeds=3, profile=_PROFILE_WITH_MIN_SEEDS)
    assert result["seed_count_insufficient"] is True, (
        "3 seeds < profile min_seeds=5 must be flagged"
    )
    assert result["min_seeds_required"] == 5


def test_profile_min_seeds_5_with_5_seeds_passes():
    result = check_variance(n_seeds=5, profile=_PROFILE_WITH_MIN_SEEDS)
    assert result["seed_count_insufficient"] is False
    assert result["min_seeds_required"] == 5


def test_build_report_one_seed_flags():
    """build_report with 1 run_record must produce seed_count_insufficient=True."""
    run_records = _make_run_records(1)
    report = build_report("method_sam", run_records, profile=None)
    assert report["seed_count_insufficient"] is True
    assert report["n_seeds"] == 1


def test_build_report_per_metric_variance_computed():
    """Check that per_metric_variance aggregates correctly across seeds."""
    run_records = _make_run_records(5, base_dice=0.80)
    report = build_report("method_sam", run_records, profile=_PROFILE_WITHOUT_MIN_SEEDS)
    assert report["seed_count_insufficient"] is False
    assert len(report["per_metric_variance"]) == 1
    mv = report["per_metric_variance"][0]
    assert mv["metric"] == "Dice"
    assert mv["mean"] is not None
    assert mv["std"] is not None


def test_zero_seeds_is_insufficient():
    result = check_variance(n_seeds=0, profile=None)
    assert result["seed_count_insufficient"] is True


# --------------------------------------------------------------------------- #
#  Real-profile test                                                           #
# --------------------------------------------------------------------------- #

def test_real_profile_adequate_seeds_not_flagged():
    """Load the real cv-medical profile; 5 seeds should not be flagged."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    run_records = _make_run_records(5, base_dice=0.85)
    report = build_report("baseline_unet3d", run_records, profile=profile)
    assert report["seed_count_insufficient"] is False, (
        "5 seeds should not be flagged as insufficient under cv-medical profile "
        f"(min_seeds_required={report['min_seeds_required']})"
    )


def test_real_profile_one_seed_labeled_stable_fires():
    """Real profile: 1 seed labeled 'stable' must fire seed_count_insufficient."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    run_records = _make_run_records(1, base_dice=0.85)
    report = build_report("baseline_unet3d", run_records, profile=profile,
                          stability_label="stable")
    assert report["seed_count_insufficient"] is True, (
        "1 seed labeled 'stable' must fire seed_count_insufficient under real profile"
    )


# --------------------------------------------------------------------------- #
#  C2 REGRESSION TESTS — distinct-seed counting                               #
# --------------------------------------------------------------------------- #

def _make_run_records_same_seed(n: int, seed: int = 42, base_dice: float = 0.85) -> list:
    """All n records share the SAME seed — re-running one seed n times."""
    return [
        {
            "condition_id": "method_sam",
            "status": "provisional",
            "provenance": {"config_hash": f"cfg{i}", "seed": seed},
            "metrics": {"Dice": base_dice},
        }
        for i in range(n)
    ]


def _make_run_records_distinct_seeds(n: int, base_dice: float = 0.85) -> list:
    """n records each with a distinct seed value."""
    return [
        {
            "condition_id": "method_sam",
            "status": "provisional",
            "provenance": {"config_hash": f"cfg{i}", "seed": i + 100},
            "metrics": {"Dice": base_dice + i * 0.005},
        }
        for i in range(n)
    ]


def test_c2_three_records_same_seed_not_stable():
    """C2: 3 run_records all with seed=42 must NOT be treated as 3 distinct seeds.

    Before fix: len(run_records)=3 → n_seeds=3 → "stable"
    After fix:  distinct seeds={42} → n_seeds=1 → seed_count_insufficient=True
    """
    run_records = _make_run_records_same_seed(3, seed=42)
    report = build_report("method_sam", run_records, profile=None)

    assert report["seed_count_insufficient"] is True, (
        "3 run_records all sharing seed=42 must be detected as 1 distinct seed "
        f"and flagged insufficient (got n_seeds={report['n_seeds']}, "
        f"seed_count_insufficient={report['seed_count_insufficient']})"
    )
    assert report["n_seeds"] == 1, (
        f"Expected n_seeds=1 (one distinct seed=42); got n_seeds={report['n_seeds']}"
    )
    # stability_label must NOT be "stable" when seed_count_insufficient is True
    assert report["stability_label"] != "stable", (
        f"stability_label must not be 'stable' when seed_count_insufficient=True; "
        f"got '{report['stability_label']}'"
    )


def test_c2_three_distinct_seeds_is_sufficient():
    """C2: 3 records each with a distinct seed must be counted as 3 seeds → sufficient."""
    run_records = _make_run_records_distinct_seeds(3)
    report = build_report("method_sam", run_records, profile=None)

    assert report["seed_count_insufficient"] is False, (
        "3 run_records with 3 distinct seeds must be flagged sufficient "
        f"(got n_seeds={report['n_seeds']}, insufficient={report['seed_count_insufficient']})"
    )
    assert report["n_seeds"] == 3, (
        f"Expected n_seeds=3; got n_seeds={report['n_seeds']}"
    )


def test_c2_provenance_seed_key_is_read():
    """C2: seed stored inside provenance dict (common pattern) must be recognised."""
    run_records = [
        {"condition_id": "c1", "provenance": {"seed": 10}, "metrics": {"Dice": 0.80}},
        {"condition_id": "c1", "provenance": {"seed": 20}, "metrics": {"Dice": 0.82}},
        {"condition_id": "c1", "provenance": {"seed": 30}, "metrics": {"Dice": 0.84}},
    ]
    report = build_report("c1", run_records, profile=None)
    assert report["n_seeds"] == 3
    assert report["seed_count_insufficient"] is False


def test_c2_records_without_seed_counted_as_zero():
    """C2: records that have no seed key yield n_seeds=0 → insufficient."""
    run_records = [
        {"condition_id": "c1", "metrics": {"Dice": 0.80}},
        {"condition_id": "c1", "metrics": {"Dice": 0.82}},
        {"condition_id": "c1", "metrics": {"Dice": 0.84}},
    ]
    report = build_report("c1", run_records, profile=None)
    assert report["n_seeds"] == 0, (
        "Records with no seed key must yield n_seeds=0"
    )
    assert report["seed_count_insufficient"] is True


def test_c2_duplicate_and_new_seeds_count_distinct():
    """C2: 5 records with seeds [42, 42, 42, 43, 44] → n_seeds=3 (distinct: 42, 43, 44)."""
    run_records = [
        {"condition_id": "c1", "seed": 42, "metrics": {"Dice": 0.80}},
        {"condition_id": "c1", "seed": 42, "metrics": {"Dice": 0.81}},
        {"condition_id": "c1", "seed": 42, "metrics": {"Dice": 0.79}},
        {"condition_id": "c1", "seed": 43, "metrics": {"Dice": 0.82}},
        {"condition_id": "c1", "seed": 44, "metrics": {"Dice": 0.83}},
    ]
    report = build_report("c1", run_records, profile=None)
    assert report["n_seeds"] == 3, (
        f"5 records with seeds [42,42,42,43,44] → 3 distinct seeds; got {report['n_seeds']}"
    )
    assert report["seed_count_insufficient"] is False


# --------------------------------------------------------------------------- #
#  Round-2 FIX 4 — profile-derived stability threshold + seed normalization   #
# --------------------------------------------------------------------------- #

# A profile that declares an open-ended metric (HD95, like the real cv-medical profile:
# valid_range [0, null]) plus a [0,1] metric. min_seeds is low so seed count is sufficient.
_PROFILE_HD95 = {
    "min_seeds": 3,
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
        {"name": "HD95", "higher_is_better": False, "valid_range": [0.0, None]},
    ],
    "hard_invariants": ["all splits must be patient-level"],
}


def test_fix4a_hd95_scale_std_not_labeled_stable():
    """FIX 4(a): an HD95 (mm-scale) std must NOT be auto-labeled 'stable'.

    HD95 in mm has no finite valid_range span (valid_range [0, null]) so the threshold
    falls back to the absolute default (0.02 mm). Real HD95 variation across seeds is on
    the order of millimetres (here std ≈ 1.5 mm) — far above 0.02 — so the run must be
    'unstable', not 'stable'. The old hardcoded `max_std < 0.02` had no notion of metric
    scale, but here the point is that mm-scale variance is correctly NOT stable.
    """
    # 3 distinct seeds; HD95 swings 2.0 / 4.0 / 6.0 mm (std ≈ 1.63 mm); Dice rock-steady
    run_records = [
        {"condition_id": "c1", "seed": 1, "metrics": {"Dice": 0.850, "HD95": 2.0}},
        {"condition_id": "c1", "seed": 2, "metrics": {"Dice": 0.851, "HD95": 4.0}},
        {"condition_id": "c1", "seed": 3, "metrics": {"Dice": 0.850, "HD95": 6.0}},
    ]
    report = build_report("c1", run_records, profile=_PROFILE_HD95)
    assert report["seed_count_insufficient"] is False
    assert report["stability_label"] == "unstable", (
        "An HD95 std of ~1.6 mm must not be labeled 'stable' — it exceeds the threshold; "
        f"got stability_label={report['stability_label']!r}"
    )


def test_fix4a_finite_range_threshold_scales_with_span():
    """FIX 4(a): threshold is STABILITY_FRACTION * (hi-lo), not a fixed 0.02.

    For a metric with valid_range [0, 100], the threshold is 0.02*100 = 2.0. A std of ~0.82
    (well above the old hardcoded 0.02 but below the derived 2.0) must count as STABLE —
    proving the threshold is derived from the profile span, not hardcoded.
    """
    profile = {
        "min_seeds": 3,
        "metrics": [{"name": "ScaledScore", "higher_is_better": True, "valid_range": [0.0, 100.0]}],
    }
    assert STABILITY_FRACTION * 100.0 == 2.0  # sanity: derived threshold
    run_records = [
        {"condition_id": "c1", "seed": 1, "metrics": {"ScaledScore": 50.0}},
        {"condition_id": "c1", "seed": 2, "metrics": {"ScaledScore": 51.0}},
        {"condition_id": "c1", "seed": 3, "metrics": {"ScaledScore": 49.0}},
    ]  # std == pstdev(50,51,49) ≈ 0.816 < 2.0 → stable
    report = build_report("c1", run_records, profile=profile)
    assert report["seed_count_insufficient"] is False
    assert report["stability_label"] == "stable", (
        "A std of ~0.82 on a [0,100] metric (threshold 2.0) must be 'stable'; "
        "the old hardcoded 0.02 would have wrongly called it 'unstable'. "
        f"Got stability_label={report['stability_label']!r}"
    )


def test_fix4b_seed_string_and_int_count_as_one():
    """FIX 4(b): seed '42' (str) and 42 (int) must canonicalize to the SAME distinct seed.

    Before fix: {'42', 42} → 2 distinct seeds. After fix: both coerce to int 42 → 1 seed.
    """
    run_records = [
        {"condition_id": "c1", "seed": "42", "metrics": {"Dice": 0.80}},
        {"condition_id": "c1", "seed": 42, "metrics": {"Dice": 0.81}},
    ]
    report = build_report("c1", run_records, profile=None)
    assert report["n_seeds"] == 1, (
        f"seed '42' and 42 must count as ONE distinct seed; got n_seeds={report['n_seeds']}"
    )
    # 1 distinct seed is below the default min of 3 → insufficient
    assert report["seed_count_insufficient"] is True


def test_fix4b_seed_bool_true_and_int_one_count_as_one():
    """FIX 4(b): seed True and seed 1 must canonicalize to the same seed (int(True)==1)."""
    run_records = [
        {"condition_id": "c1", "seed": True, "metrics": {"Dice": 0.80}},
        {"condition_id": "c1", "seed": 1, "metrics": {"Dice": 0.81}},
        {"condition_id": "c1", "seed": 2, "metrics": {"Dice": 0.82}},
    ]
    report = build_report("c1", run_records, profile=None)
    assert report["n_seeds"] == 2, (
        f"seed True and 1 collapse to one seed → 2 distinct seeds (1, 2); got {report['n_seeds']}"
    )
