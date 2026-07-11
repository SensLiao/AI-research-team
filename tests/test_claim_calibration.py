"""Real tests for the claim-strength-calibrator deterministic core.

Verifies that calibrate_claim correctly downgrades "+0.3% significant" claims when
variance >= delta (the golden test), and that strong well-separated claims are preserved.
"""
from __future__ import annotations

from research_agent_teams.tools.claim_calibration import (
    _calibrate_strength,
    _strength_rank,
    build_report,
    calibrate_claim,
)


# --------------------------------------------------------------------------- #
#  Tests — _calibrate_strength rules                                          #
# --------------------------------------------------------------------------- #

def test_strong_when_delta_ge_2x_variance():
    """delta=0.10, variance=0.03 → ratio=3.33 >= 2 → strong"""
    assert _calibrate_strength(0.10, 0.03) == "strong"


def test_moderate_when_delta_ge_1x_variance():
    """delta=0.05, variance=0.04 → ratio=1.25 in [1, 2) → moderate"""
    assert _calibrate_strength(0.05, 0.04) == "moderate"


def test_marginal_when_delta_ge_half_variance():
    """delta=0.02, variance=0.03 → ratio=0.67 in [0.5, 1) → marginal"""
    assert _calibrate_strength(0.02, 0.03) == "marginal"


def test_inconclusive_when_delta_lt_half_variance():
    """The golden test: delta=0.003 (0.3%), variance=0.01 → ratio=0.3 < 0.5 → inconclusive"""
    result = _calibrate_strength(0.003, 0.01)
    assert result == "inconclusive", (
        f"+0.3% delta with variance=0.01 must be calibrated to 'inconclusive'; got '{result}'"
    )


def test_marginal_when_variance_exactly_equals_delta():
    """delta == variance → ratio=1.0 → exactly 'moderate' (boundary at 1.0)"""
    assert _calibrate_strength(0.05, 0.05) == "moderate"


def test_zero_variance_nonzero_delta_is_strong():
    """Zero variance with positive delta → strong."""
    assert _calibrate_strength(0.05, 0.0) == "strong"


def test_zero_variance_zero_delta_is_inconclusive():
    """No movement at all → inconclusive."""
    assert _calibrate_strength(0.0, 0.0) == "inconclusive"


def test_none_delta_returns_inconclusive():
    """Missing delta → cannot calibrate → inconclusive (M2 fix: was 'moderate', now 'inconclusive')."""
    assert _calibrate_strength(None, 0.01) == "inconclusive"


def test_none_variance_returns_inconclusive():
    """Missing variance → cannot calibrate → inconclusive (M2 fix: was 'moderate', now 'inconclusive')."""
    assert _calibrate_strength(0.05, None) == "inconclusive"


# --------------------------------------------------------------------------- #
#  Tests — calibrate_claim end-to-end                                         #
# --------------------------------------------------------------------------- #

def test_overlapping_variance_claim_downgraded():
    """The golden scenario: '+0.3% significant' with std=1.0% → downgraded."""
    entry = calibrate_claim(
        original_claim="+0.3% significant improvement on Dice",
        delta=0.003,
        variance=0.010,
        original_strength="strong",
        metric="Dice",
    )
    assert entry["strength"] in ("marginal", "inconclusive"), (
        f"+0.3% delta with variance=1.0% must be downgraded; got strength='{entry['strength']}'"
    )
    assert entry["downgraded"] is True
    assert "calibrated" in entry["calibrated_claim"].lower() or entry["strength"] in entry["calibrated_claim"]


def test_well_separated_claim_stays_strong():
    """Large delta relative to variance → preserved as 'strong'."""
    entry = calibrate_claim(
        original_claim="+10% improvement on Dice",
        delta=0.10,
        variance=0.01,
        original_strength="strong",
        metric="Dice",
    )
    assert entry["strength"] == "strong"
    assert entry["downgraded"] is False


def test_downgraded_flag_set_when_strength_drops():
    entry = calibrate_claim(
        original_claim="moderate improvement",
        delta=0.01,
        variance=0.05,
        original_strength="moderate",
        metric="Dice",
    )
    assert entry["downgraded"] is True
    assert _strength_rank(entry["strength"]) < _strength_rank("moderate")


def test_not_downgraded_when_strength_unchanged():
    entry = calibrate_claim(
        original_claim="strong improvement",
        delta=0.20,
        variance=0.05,
        original_strength="strong",
        metric="Dice",
    )
    assert entry["downgraded"] is False
    assert entry["strength"] == "strong"


# --------------------------------------------------------------------------- #
#  Tests — build_report                                                        #
# --------------------------------------------------------------------------- #

def test_build_report_returns_calibrated_list():
    raw_claims = [
        {"original_claim": "+0.3% on Dice", "metric": "Dice",
         "delta": 0.003, "variance": 0.010, "original_strength": "strong"},
        {"original_claim": "+10% on Dice", "metric": "Dice",
         "delta": 0.10, "variance": 0.01, "original_strength": "strong"},
    ]
    report = build_report(raw_claims, source_ref="result_summary_001")
    assert report["source_ref"] == "result_summary_001"
    assert len(report["calibrated"]) == 2


def test_build_report_first_claim_is_downgraded_second_is_not():
    raw_claims = [
        {"original_claim": "+0.3%", "delta": 0.003, "variance": 0.010, "original_strength": "strong"},
        {"original_claim": "+10%", "delta": 0.10, "variance": 0.01, "original_strength": "strong"},
    ]
    report = build_report(raw_claims)
    calibrated = report["calibrated"]
    assert calibrated[0]["downgraded"] is True, "First claim should be downgraded"
    assert calibrated[1]["downgraded"] is False, "Second claim should not be downgraded"


def test_build_report_empty_claims_list_returns_empty_calibrated():
    """Empty claims list → empty calibrated list (build_report does not add phantom entries)."""
    report = build_report([])
    assert report["calibrated"] == []


def test_calibrate_claim_with_absolute_delta_0003_and_variance_001():
    """Named scenario from contract: '+0.3% significant' with overlapping variance."""
    # 0.3% = 0.003 absolute; if std ~ 0.010, ratio = 0.3 < 0.5 → inconclusive
    entry = calibrate_claim(
        original_claim="+0.3% significant",
        delta=0.003,
        variance=0.010,
        original_strength="strong",
    )
    assert entry["strength"] == "inconclusive", (
        "Contract golden test: '+0.3% significant' with variance 1.0% must be 'inconclusive'"
    )
    assert entry["downgraded"] is True


# --------------------------------------------------------------------------- #
#  M2 REGRESSION TESTS — None delta/variance → inconclusive, not moderate     #
# --------------------------------------------------------------------------- #

def test_m2_none_delta_returns_inconclusive_not_moderate():
    """M2: Missing delta → strength MUST be 'inconclusive', NOT 'moderate'.

    Before fix: _calibrate_strength(None, 0.01) returned 'moderate'
    After fix:  must return 'inconclusive' (weakest/neutral label)
    """
    result = _calibrate_strength(None, 0.01)
    assert result == "inconclusive", (
        f"Missing delta must yield 'inconclusive', not 'moderate'; got '{result}'"
    )


def test_m2_none_variance_returns_inconclusive_not_moderate():
    """M2: Missing variance → strength MUST be 'inconclusive', NOT 'moderate'.

    Before fix: _calibrate_strength(0.05, None) returned 'moderate'
    After fix:  must return 'inconclusive'
    """
    result = _calibrate_strength(0.05, None)
    assert result == "inconclusive", (
        f"Missing variance must yield 'inconclusive', not 'moderate'; got '{result}'"
    )


def test_m2_both_none_returns_inconclusive():
    """M2: Both delta and variance missing → 'inconclusive'."""
    result = _calibrate_strength(None, None)
    assert result == "inconclusive", (
        f"Both missing must yield 'inconclusive'; got '{result}'"
    )


def test_m2_calibrate_claim_no_delta_no_variance_is_inconclusive_and_downgraded():
    """M2: calibrate_claim with no numeric context must produce 'inconclusive' and set downgraded.

    This is the full integration test: a claim with original_strength='strong'
    but delta=None, variance=None must be downgraded to 'inconclusive'.
    """
    entry = calibrate_claim(
        original_claim="This method significantly improves performance",
        delta=None,
        variance=None,
        original_strength="strong",
        metric="Dice",
    )
    assert entry["strength"] == "inconclusive", (
        f"Uncalibratable claim must yield 'inconclusive'; got '{entry['strength']}'"
    )
    assert entry["downgraded"] is True, (
        "Claim downgraded from 'strong' to 'inconclusive' must have downgraded=True"
    )
    # caveat must mention that calibration was not possible
    assert "calibrat" in entry["caveat"].lower(), (
        f"Caveat should mention calibration; got: {entry['caveat']!r}"
    )


def test_m2_build_report_claim_with_no_delta_is_inconclusive():
    """M2: build_report with a raw claim that has no delta/variance → inconclusive in output."""
    raw_claims = [
        {
            "original_claim": "Our method is strongly better",
            "metric": "Dice",
            "delta": None,
            "variance": None,
            "original_strength": "strong",
        }
    ]
    report = build_report(raw_claims)
    calibrated_entry = report["calibrated"][0]
    assert calibrated_entry["strength"] == "inconclusive", (
        f"Expected 'inconclusive' for no-delta claim; got '{calibrated_entry['strength']}'"
    )
    assert calibrated_entry["downgraded"] is True
