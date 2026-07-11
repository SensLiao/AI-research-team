"""Tests for stats_test — the ANALYZE-stage significance layer (audit finding H6 fix).

True-value assertions, not key-existence checks: hand-verifiable exact permutation p-values,
a textbook Holm-Bonferroni example, determinism/reproducibility under a fixed seed, immutability of
enrich inputs, and a full envelope round-trip through validate_artifact (old payloads still valid).
"""
from __future__ import annotations

import copy
import math

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.result_analyzer import (
    build_result_summary,
    build_result_summary_with_stats,
)
from research_agent_teams.tools.stats_test import (
    approx_paired_power,
    bootstrap_ci,
    enrich_result_summary,
    holm_bonferroni,
    paired_permutation_test,
)
from research_agent_teams.tools.validate_artifact import validate_artifact, validate_against

TS = "2026-06-12T12:00:00Z"


# --------------------------------------------------------------------------- #
#  1. paired_permutation_test — exact branch (hand-verifiable)                 #
# --------------------------------------------------------------------------- #

def test_exact_all_positive_diffs_n4_p_is_two_sixteenths():
    """All-positive diffs, n=4: observed |sum| is maximal, only all-+ and all-- match → p=2/16."""
    xs = [4.0, 3.0, 2.0, 1.0]
    ys = [0.0, 0.0, 0.0, 0.0]  # diffs = [4,3,2,1], all positive
    out = paired_permutation_test(xs, ys, seed=0)
    assert out["method"] == "exact_permutation"
    assert out["n"] == 4
    assert out["p_value"] == pytest.approx(2.0 / 16.0)  # 0.125
    assert out["mean_diff"] == pytest.approx((4 + 3 + 2 + 1) / 4)


def test_exact_all_zero_diffs_p_is_one():
    """xs == ys → no effect → p_value 1.0 exactly."""
    xs = [1.0, 2.0, 3.0]
    out = paired_permutation_test(xs, xs, seed=123)
    assert out["p_value"] == 1.0
    assert out["mean_diff"] == 0.0
    assert out["method"] == "exact_permutation"


def test_exact_uses_exact_method_at_boundary_n12():
    """n == 12 is still the exact branch (2**12 = 4096 enumerations)."""
    xs = [float(i) for i in range(1, 13)]
    ys = [0.0] * 12
    out = paired_permutation_test(xs, ys, seed=0)
    assert out["method"] == "exact_permutation"
    assert out["n"] == 12
    # All-positive again → only all-+ / all-- reach the max |sum| → p = 2/4096.
    assert out["p_value"] == pytest.approx(2.0 / 4096.0)


def test_exact_seed_does_not_change_exact_result():
    """The exact branch is deterministic regardless of seed."""
    xs = [2.0, -1.0, 3.0, 0.5, -0.2, 1.1]
    ys = [1.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    a = paired_permutation_test(xs, ys, seed=1)
    b = paired_permutation_test(xs, ys, seed=999)
    assert a == b


def test_permutation_raises_on_length_mismatch_and_small_n():
    with pytest.raises(ValueError):
        paired_permutation_test([1.0, 2.0], [1.0], seed=0)       # length mismatch
    with pytest.raises(ValueError):
        paired_permutation_test([1.0], [0.0], seed=0)            # n < 2


# --------------------------------------------------------------------------- #
#  2. paired_permutation_test — Monte Carlo branch (n > 12)                    #
# --------------------------------------------------------------------------- #

def test_mc_branch_is_reproducible_under_fixed_seed():
    """n > 12 → mc_permutation; identical seed → byte-identical result across calls."""
    xs = [0.5 + 0.01 * i for i in range(20)]
    ys = [0.0 for _ in range(20)]
    a = paired_permutation_test(xs, ys, seed=42, n_resamples=2000)
    b = paired_permutation_test(xs, ys, seed=42, n_resamples=2000)
    assert a["method"] == "mc_permutation"
    assert a == b


def test_mc_branch_separated_data_is_significant():
    """A large, consistent positive shift over many seeds → p < 0.01."""
    xs = [10.0 + 0.001 * i for i in range(20)]   # tightly clustered around 10
    ys = [0.0 for _ in range(20)]                # baseline at 0
    out = paired_permutation_test(xs, ys, seed=7, n_resamples=5000)
    assert out["method"] == "mc_permutation"
    assert out["p_value"] < 0.01


def test_mc_branch_smoothing_keeps_p_positive():
    """+1 smoothing → the smallest possible MC p-value is 1/(n_resamples+1), never 0."""
    xs = [100.0 + 0.0001 * i for i in range(15)]
    ys = [0.0 for _ in range(15)]
    out = paired_permutation_test(xs, ys, seed=3, n_resamples=1000)
    assert out["p_value"] >= 1.0 / (1000 + 1)
    assert out["p_value"] > 0.0


# --------------------------------------------------------------------------- #
#  3. bootstrap_ci                                                             #
# --------------------------------------------------------------------------- #

def test_bootstrap_reproducible_and_ci_brackets_mean():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    a = bootstrap_ci(values, seed=11, n_resamples=2000)
    b = bootstrap_ci(values, seed=11, n_resamples=2000)
    assert a == b                                  # reproducible under fixed seed
    assert a["mean"] == pytest.approx(3.0)         # sample mean of original data
    assert a["n"] == 5
    assert a["low"] <= a["mean"] <= a["high"]      # CI brackets the point estimate


def test_bootstrap_ci_within_data_range_and_ordered():
    """Percentile bootstrap of the mean must lie inside [min, max] and be ordered low <= high."""
    values = [10.0, 12.0, 11.0, 13.0, 9.0, 14.0]
    out = bootstrap_ci(values, seed=5, n_resamples=3000)
    assert out["low"] <= out["high"]
    assert min(values) <= out["low"]
    assert out["high"] <= max(values)


def test_bootstrap_constant_data_gives_degenerate_ci():
    """All-equal values → every resample mean equals the constant → low == high == mean."""
    out = bootstrap_ci([7.0, 7.0, 7.0, 7.0], seed=1, n_resamples=500)
    assert out["low"] == pytest.approx(7.0)
    assert out["high"] == pytest.approx(7.0)
    assert out["mean"] == pytest.approx(7.0)


def test_bootstrap_raises_on_small_n():
    with pytest.raises(ValueError):
        bootstrap_ci([1.0], seed=0)


# --------------------------------------------------------------------------- #
#  4. holm_bonferroni (textbook example)                                       #
# --------------------------------------------------------------------------- #

def test_holm_textbook_example_input_order_preserved():
    """p=[0.01,0.04,0.03,0.005], alpha=0.05 → adjusted=[0.03,0.06,0.06,0.02] in INPUT order."""
    out = holm_bonferroni([0.01, 0.04, 0.03, 0.005], alpha=0.05)
    adjusted = out["adjusted"]
    assert adjusted[0] == pytest.approx(0.03)
    assert adjusted[1] == pytest.approx(0.06)
    assert adjusted[2] == pytest.approx(0.06)
    assert adjusted[3] == pytest.approx(0.02)
    assert out["significant"] == [True, False, False, True]


def test_holm_is_monotone_in_sorted_order_and_capped_at_one():
    """Adjusted values are non-decreasing along ascending raw p, and capped at 1.0."""
    raw = [0.2, 0.9, 0.5, 0.8, 0.95]
    out = holm_bonferroni(raw, alpha=0.05)
    # Re-sort adjusted by the raw ascending order and check monotonicity.
    order = sorted(range(len(raw)), key=lambda i: raw[i])
    in_order = [out["adjusted"][i] for i in order]
    assert all(in_order[k] <= in_order[k + 1] + 1e-12 for k in range(len(in_order) - 1))
    assert all(a <= 1.0 for a in out["adjusted"])
    assert any(a == 1.0 for a in out["adjusted"])   # large raw p's cap at 1.0


def test_holm_empty_input():
    out = holm_bonferroni([], alpha=0.05)
    assert out == {"adjusted": [], "significant": []}


def test_holm_single_p_value_unchanged():
    """m=1 → multiplier is 1 → adjusted == raw (capped)."""
    out = holm_bonferroni([0.03], alpha=0.05)
    assert out["adjusted"][0] == pytest.approx(0.03)
    assert out["significant"] == [True]


# --------------------------------------------------------------------------- #
#  5. approx_paired_power                                                      #
# --------------------------------------------------------------------------- #

def test_power_monotone_in_n():
    """Larger n → more power, holding effect and sd fixed."""
    p_small = approx_paired_power(mean_diff=0.5, sd_diff=1.0, n=5)
    p_large = approx_paired_power(mean_diff=0.5, sd_diff=1.0, n=50)
    assert 0.0 <= p_small <= p_large <= 1.0
    assert p_large > p_small


def test_power_monotone_in_effect():
    """Larger effect → more power, holding n and sd fixed."""
    p_small = approx_paired_power(mean_diff=0.2, sd_diff=1.0, n=20)
    p_large = approx_paired_power(mean_diff=1.0, sd_diff=1.0, n=20)
    assert p_large > p_small


def test_power_zero_for_degenerate_inputs():
    assert approx_paired_power(mean_diff=0.5, sd_diff=0.0, n=10) == 0.0   # sd <= 0
    assert approx_paired_power(mean_diff=0.5, sd_diff=-1.0, n=10) == 0.0  # sd < 0
    assert approx_paired_power(mean_diff=0.5, sd_diff=1.0, n=1) == 0.0    # n < 2


def test_power_at_critical_effect_is_about_half():
    """When sqrt(n)*|d|/sd == z_crit, power = Phi(0) = 0.5 (sanity check on the formula)."""
    # choose d so that sqrt(n)*d/sd == z_{0.975} ≈ 1.959964
    n = 16
    sd = 1.0
    z = 1.959963984540054
    d = z * sd / math.sqrt(n)
    assert approx_paired_power(mean_diff=d, sd_diff=sd, n=n) == pytest.approx(0.5, abs=1e-3)


# --------------------------------------------------------------------------- #
#  6. enrich_result_summary                                                    #
# --------------------------------------------------------------------------- #

def _synthetic_summary():
    """A result_summary with two findings: one pairable (cond-A vs baseline), one not."""
    findings = [
        {
            "metric": "dice",
            "value": 0.85,
            "condition_id": "cond-A",
            "baseline_value": 0.70,
            "baseline_condition_id": "baseline",
        },
        {
            "metric": "iou",
            "value": 0.60,
            "condition_id": "cond-B",   # no per-seed data, no baseline_condition_id
        },
    ]
    return build_result_summary(findings, caveats=["synthetic"])


def _synthetic_per_seed():
    return {
        "cond-A": {"dice": [0.84, 0.86, 0.85, 0.87]},
        "baseline": {"dice": [0.70, 0.71, 0.69, 0.70]},
        # cond-B intentionally absent → its finding must NOT be annotated
    }


def test_enrich_attaches_fields_to_pairable_finding_only():
    payload = _synthetic_summary()
    per_seed = _synthetic_per_seed()
    out = enrich_result_summary(payload, per_seed, seed=2024)

    paired = out["findings"][0]
    for field in ("p_value", "ci_low", "ci_high", "n_seeds",
                  "significant_after_correction", "stats_method"):
        assert field in paired, f"pairable finding must carry {field}"
    assert paired["n_seeds"] == 4
    assert paired["stats_method"] == "exact_permutation"   # n=4 → exact
    assert paired["ci_low"] <= paired["ci_high"]
    # cond-A (~0.855) is clearly above baseline (~0.70): the smallest exact two-sided p for n=4
    # is 2/16 = 0.125; it should be flagged significant after correction at alpha=0.05 here only if
    # that survives Holm — with a single tested finding the adjusted p equals the raw p.
    assert paired["p_value"] == pytest.approx(0.125)
    assert paired["significant_after_correction"] is False  # 0.125 > 0.05

    unpaired = out["findings"][1]
    for field in ("p_value", "ci_low", "ci_high", "n_seeds",
                  "significant_after_correction", "stats_method"):
        assert field not in unpaired, f"unpairable finding must NOT carry {field}"


def test_enrich_top_level_stats_block():
    out = enrich_result_summary(_synthetic_summary(), _synthetic_per_seed(), seed=2024)
    stats = out["stats"]
    assert stats["alpha"] == 0.05
    assert stats["correction"] == "holm"
    assert stats["seed"] == 2024
    assert stats["n_findings_tested"] == 1
    assert "note" not in stats


def test_enrich_no_pairable_data_adds_insufficient_note():
    """No per-seed data at all → stats.note explains nothing was computed; no fields fabricated."""
    out = enrich_result_summary(_synthetic_summary(), {}, seed=1)
    assert out["stats"]["n_findings_tested"] == 0
    assert out["stats"]["note"] == "insufficient per-seed data — no significance computed"
    for f in out["findings"]:
        assert "p_value" not in f


def test_enrich_does_not_mutate_inputs():
    """Immutability: the original payload and per_seed dicts are untouched (deep compare)."""
    payload = _synthetic_summary()
    per_seed = _synthetic_per_seed()
    payload_snapshot = copy.deepcopy(payload)
    per_seed_snapshot = copy.deepcopy(per_seed)

    _ = enrich_result_summary(payload, per_seed, seed=99)

    assert payload == payload_snapshot, "enrich must not mutate the input payload"
    assert per_seed == per_seed_snapshot, "enrich must not mutate per_seed"
    # and specifically no stats fields leaked onto the original findings
    assert "p_value" not in payload["findings"][0]
    assert "stats" not in payload


def test_enrich_unequal_seed_lengths_not_paired():
    """Condition and baseline vectors of unequal length are not pairable → no annotation."""
    payload = _synthetic_summary()
    per_seed = {
        "cond-A": {"dice": [0.84, 0.86, 0.85]},   # 3 seeds
        "baseline": {"dice": [0.70, 0.71]},        # 2 seeds → mismatch
    }
    out = enrich_result_summary(payload, per_seed, seed=1)
    assert out["stats"]["n_findings_tested"] == 0
    assert "p_value" not in out["findings"][0]


# --------------------------------------------------------------------------- #
#  7. Envelope round-trip through validate_artifact                            #
# --------------------------------------------------------------------------- #

def test_enriched_payload_passes_artifact_validation():
    """An enriched result_summary, wrapped in the standard envelope, validates clean."""
    out = enrich_result_summary(_synthetic_summary(), _synthetic_per_seed(), seed=2024)
    art = envelope("result_summary", "result-analyzer", out, TS)
    assert validate_artifact(art) == [], "enriched payload must validate against the schema"


def test_combined_builder_matches_enrich_and_validates():
    """build_result_summary_with_stats == build_result_summary + enrich, and validates clean."""
    findings = [
        {
            "metric": "dice",
            "value": 0.85,
            "condition_id": "cond-A",
            "baseline_value": 0.70,
            "baseline_condition_id": "baseline",
        },
    ]
    per_seed = {
        "cond-A": {"dice": [0.84, 0.86, 0.85, 0.87]},
        "baseline": {"dice": [0.70, 0.71, 0.69, 0.70]},
    }
    via_wrapper = build_result_summary_with_stats(
        findings, per_seed, seed=2024, caveats=["x"]
    )
    via_steps = enrich_result_summary(
        build_result_summary(findings, caveats=["x"]), per_seed, seed=2024
    )
    assert via_wrapper == via_steps
    art = envelope("result_summary", "result-analyzer", via_wrapper, TS)
    assert validate_artifact(art) == []


def test_old_payload_without_new_fields_still_valid():
    """Backward compatibility: a pre-H6 result_summary (no stats, no new finding fields) is valid."""
    legacy = {
        "status": "provisional",
        "findings": [
            {"metric": "dice", "value": 0.8, "condition_id": "c1",
             "baseline_value": 0.7, "delta": 0.1},
            {"metric": "iou", "value": 0.6, "condition_id": "c2"},
        ],
        "caveats": [],
        "can_cite_thesis": False,
    }
    assert validate_against("result_summary.schema.json", legacy) == []
    art = envelope("result_summary", "result-analyzer", legacy, TS)
    assert validate_artifact(art) == []
