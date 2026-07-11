"""Tests for the novelty_aggregate deterministic novelty scorer (DISCOVER-stage).

Key invariants proved:
  - Every input gap receives a score — NONE are dropped (novelty-paradox guard).
  - A low-novelty gap (single signal) still appears in the output (test_low_novelty_is_not_filtered).
  - novelty and feasibility_signal are always in [0, 1].
  - Output is deterministic and reproducible: same input → same output.
  - Output validates against novelty_score.schema.json.
  - Gaps with more distinct derived_from signals score higher novelty than gaps with fewer.
  - Novelty caps at 1.0 for 4+ distinct signals.
  - No pass/verdict/include/cut/selected field can appear in the output (schema closure tested
    in test_m3a_gap_schemas.py; here we confirm the tool never inserts such fields).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.novelty_aggregate import aggregate_novelty
from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# Fixtures — crafted gap dicts for tests
# ==============================================================================

def _gap_high_novelty() -> dict:
    """4 distinct signals → novelty = 1.0 (ceiling)."""
    return {
        "gap_id": "GAP-HIGH",
        "gap_type": "transfer_gap",
        "derived_from": [
            "white_space_present",
            "contrarian_angle",
            "weakness_opportunity",
            "transfer_potential",
        ],
        "evidence_ref": ["[[smith2024]]", "[[doe2023]]"],
    }


def _gap_mid_novelty() -> dict:
    """2 distinct signals → novelty = 0.5."""
    return {
        "gap_id": "GAP-MID",
        "gap_type": "methodological_gap",
        "derived_from": ["weakness_opportunity", "empirically_untested"],
        "evidence_ref": ["[[jones2023]]"],
    }


def _gap_low_novelty() -> dict:
    """1 distinct signal → novelty = 0.25 (low, but MUST appear in output — paradox guard)."""
    return {
        "gap_id": "GAP-LOW",
        "gap_type": "stated_open_problem",
        "derived_from": ["stated_by_authors"],
        "evidence_ref": ["[[kim2024]]"],
    }


# ==============================================================================
# Core correctness
# ==============================================================================

def test_three_gaps_produce_three_scores():
    """aggregate_novelty returns exactly one score per input gap — no drops."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    assert len(result["scores"]) == 3


def test_gap_ids_preserved():
    """The gap_id of each input appears in the corresponding output score."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    out_ids = {s["gap_id"] for s in result["scores"]}
    assert out_ids == {"GAP-HIGH", "GAP-MID", "GAP-LOW"}


def test_low_novelty_is_not_filtered():
    """NOVELTY-PARADOX GUARD: a gap with a single weak signal (novelty=0.25) must appear
    in the output.  aggregate_novelty NEVER drops a gap regardless of its novelty score.

    This test is the primary structural proof of the no-cut invariant.
    """
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    out_ids = [s["gap_id"] for s in result["scores"]]
    assert "GAP-LOW" in out_ids, (
        "Low-novelty gap GAP-LOW was dropped from output — this violates the novelty-paradox guard. "
        "aggregate_novelty must return a score for EVERY input gap regardless of novelty level."
    )
    # Confirm its novelty is actually low (not silently inflated)
    low_score = next(s for s in result["scores"] if s["gap_id"] == "GAP-LOW")
    assert low_score["novelty"] < 0.5, (
        f"Expected low novelty (< 0.5) for single-signal gap; got {low_score['novelty']}"
    )


# ==============================================================================
# Score range [0, 1]
# ==============================================================================

def test_all_scores_in_range():
    """All novelty and feasibility_signal values must be in [0, 1]."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    for score in result["scores"]:
        assert 0.0 <= score["novelty"] <= 1.0, (
            f"novelty out of range for {score['gap_id']}: {score['novelty']}"
        )
        assert 0.0 <= score["feasibility_signal"] <= 1.0, (
            f"feasibility_signal out of range for {score['gap_id']}: {score['feasibility_signal']}"
        )


def test_high_novelty_gap_scores_one():
    """4 distinct signals → novelty must be exactly 1.0 (ceiling)."""
    result = aggregate_novelty([_gap_high_novelty()])
    score = result["scores"][0]
    assert score["novelty"] == 1.0


def test_mid_novelty_gap_scores_half():
    """2 distinct signals → novelty = 0.5."""
    result = aggregate_novelty([_gap_mid_novelty()])
    score = result["scores"][0]
    assert score["novelty"] == pytest.approx(0.5)


def test_low_novelty_gap_scores_quarter():
    """1 distinct signal → novelty = 0.25."""
    result = aggregate_novelty([_gap_low_novelty()])
    score = result["scores"][0]
    assert score["novelty"] == pytest.approx(0.25)


def test_novelty_monotone_with_signals():
    """More distinct signals → higher novelty (monotone relationship)."""
    gap_1_signal = {"gap_id": "G1", "gap_type": "coverage_gap",
                    "derived_from": ["white_space_present"], "evidence_ref": ["r1"]}
    gap_2_signals = {"gap_id": "G2", "gap_type": "coverage_gap",
                     "derived_from": ["white_space_present", "contrarian_angle"], "evidence_ref": ["r2"]}
    gap_3_signals = {"gap_id": "G3", "gap_type": "coverage_gap",
                     "derived_from": ["white_space_present", "contrarian_angle", "weakness_opportunity"],
                     "evidence_ref": ["r3"]}

    result = aggregate_novelty([gap_1_signal, gap_2_signals, gap_3_signals])
    scores_by_id = {s["gap_id"]: s["novelty"] for s in result["scores"]}

    assert scores_by_id["G1"] < scores_by_id["G2"] < scores_by_id["G3"]


def test_duplicate_signals_deduplicated():
    """Duplicate entries in derived_from count as one distinct signal."""
    gap_dup = {
        "gap_id": "G-DUP",
        "gap_type": "stated_open_problem",
        "derived_from": ["stated_by_authors", "stated_by_authors", "stated_by_authors"],
        "evidence_ref": ["r1"],
    }
    result = aggregate_novelty([gap_dup])
    score = result["scores"][0]
    # 3 entries but 1 distinct → novelty = 0.25
    assert score["novelty"] == pytest.approx(0.25)


def test_ceiling_at_four_or_more_signals():
    """5 distinct signals still produces novelty = 1.0 (ceiling at NOVELTY_CEIL=4)."""
    gap_5 = {
        "gap_id": "G5",
        "gap_type": "transfer_gap",
        "derived_from": ["a", "b", "c", "d", "e"],
        "evidence_ref": ["r1"],
    }
    result = aggregate_novelty([gap_5])
    assert result["scores"][0]["novelty"] == 1.0


# ==============================================================================
# Determinism / reproducibility
# ==============================================================================

def test_reproducible_same_input_same_output():
    """Same input always produces the same output (deterministic)."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    r1 = aggregate_novelty(gaps)
    r2 = aggregate_novelty(gaps)
    assert r1 == r2


def test_output_order_matches_input_order():
    """Output scores appear in the same order as input gaps (stable ordering)."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    out_ids = [s["gap_id"] for s in result["scores"]]
    assert out_ids == ["GAP-HIGH", "GAP-MID", "GAP-LOW"]


# ==============================================================================
# Schema validation
# ==============================================================================

def test_output_validates_against_schema():
    """Full payload from aggregate_novelty validates against novelty_score.schema.json."""
    gaps = [_gap_high_novelty(), _gap_mid_novelty(), _gap_low_novelty()]
    result = aggregate_novelty(gaps)
    errors = validate_against("novelty_score.schema.json", result)
    assert errors == [], f"aggregate_novelty output failed schema validation: {errors}"


def test_empty_input_produces_empty_scores():
    """Zero gaps in → zero scores out, and the payload is still schema-valid."""
    result = aggregate_novelty([])
    assert result == {"scores": []}
    errors = validate_against("novelty_score.schema.json", result)
    assert errors == []


def test_output_has_no_verdict_field():
    """The tool must NEVER insert a verdict/pass/cut/include/selected field (schema closure)."""
    result = aggregate_novelty([_gap_high_novelty()])
    score = result["scores"][0]
    forbidden = {"verdict", "pass", "cut", "include", "selected"}
    found = forbidden.intersection(score.keys())
    assert not found, (
        f"aggregate_novelty inserted forbidden fields {found} — violates novelty-paradox guard"
    )


# ==============================================================================
# Feasibility signal per gap_type
# ==============================================================================

def test_feasibility_differs_by_gap_type():
    """Different gap_types produce different feasibility_signal defaults."""
    gap_method = {"gap_id": "G-M", "gap_type": "methodological_gap",
                  "derived_from": ["weakness_opportunity"], "evidence_ref": ["r"]}
    gap_assumption = {"gap_id": "G-A", "gap_type": "assumption_gap",
                      "derived_from": ["contrarian_angle"], "evidence_ref": ["r"]}

    result = aggregate_novelty([gap_method, gap_assumption])
    scores = {s["gap_id"]: s["feasibility_signal"] for s in result["scores"]}

    # methodological (0.7) should be higher than assumption (0.45) by default
    assert scores["G-M"] > scores["G-A"]


def test_unknown_gap_type_uses_neutral_feasibility():
    """A gap with an unknown/missing gap_type uses the neutral default (0.5) and does not crash."""
    gap = {"gap_id": "G-UNKNOWN", "gap_type": "not_a_real_type",
           "derived_from": ["some_signal"], "evidence_ref": ["r"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["feasibility_signal"] == pytest.approx(0.5)
    assert 0.0 <= score["feasibility_signal"] <= 1.0


def test_missing_gap_type_uses_neutral_feasibility():
    """A gap missing the gap_type key uses the neutral default and does not crash."""
    gap = {"gap_id": "G-NOTYPE", "derived_from": ["signal_a"], "evidence_ref": ["r"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["feasibility_signal"] == pytest.approx(0.5)


# ==============================================================================
# Profile-driven feasibility override (extension point)
# ==============================================================================

def test_profile_feasibility_override():
    """A profile with feasibility_defaults overrides the built-in default for a gap_type."""
    custom_profile = {
        "feasibility_defaults": {
            "methodological_gap": 0.9,  # domain says method gaps are very feasible
        }
    }
    gap = {"gap_id": "G-OVER", "gap_type": "methodological_gap",
           "derived_from": ["weakness_opportunity"], "evidence_ref": ["r"]}
    result = aggregate_novelty([gap], profile=custom_profile)
    score = result["scores"][0]
    assert score["feasibility_signal"] == pytest.approx(0.9)


# ==============================================================================
# Edge / robustness
# ==============================================================================

def test_missing_derived_from_treated_as_empty():
    """A gap missing derived_from produces novelty=0.0 (0 distinct signals / 4 = 0)."""
    gap = {"gap_id": "G-NO-SIGNALS", "gap_type": "coverage_gap", "evidence_ref": ["r"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["novelty"] == pytest.approx(0.0)
    assert 0.0 <= score["feasibility_signal"] <= 1.0


def test_missing_evidence_ref_produces_empty_list_in_output():
    """A gap missing evidence_ref still produces a score (graceful handling); evidence_ref is [].
    Note: the resulting payload would fail schema validation (minItems:1) — that is expected
    and the agent is responsible for providing evidence_ref before emitting the artifact."""
    gap = {"gap_id": "G-NO-EV", "gap_type": "stated_open_problem",
           "derived_from": ["stated_by_authors"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["gap_id"] == "G-NO-EV"
    # The score is produced (not dropped); schema enforcement is the schema's job, not the tool's
    assert "novelty" in score
    assert "feasibility_signal" in score


# ==============================================================================
# Round-2 fixes: reason_code provenance bridge + zero-signal representability
# ==============================================================================

def test_reason_code_bridges_to_provenance():
    """A gap from gap_classification (carrying a reason_code, no explicit derived_from) still gets a
    provenance signal deterministically — novelty 0.25, derived_from=['future_work'] — no agent prose.
    This closes the runtime-impossible hand-off the reviewers found."""
    gap = {"gap_id": "GAP-1", "gap_type": "stated_open_problem", "reason_code": "FW_STATED",
           "evidence_ref": ["[[r]]"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["derived_from"] == ["future_work"]
    assert score["novelty"] == pytest.approx(0.25)
    assert validate_against("novelty_score.schema.json", result) == []


def test_explicit_signals_merge_with_reason_code():
    """Explicit cross-hunter derived_from MERGES with the reason_code tag -> richer novelty."""
    gap = {"gap_id": "GAP-1", "gap_type": "stated_open_problem", "reason_code": "FW_STATED",
           "derived_from": ["white_space_present"], "evidence_ref": ["[[r]]"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert set(score["derived_from"]) == {"white_space_present", "future_work"}
    assert score["novelty"] == pytest.approx(0.5)  # 2 distinct signals


def test_zero_signal_gap_is_scoreable_and_schema_valid():
    """ROUND-2 FIX: a gap with neither a reason_code nor derived_from is novelty 0.0 and the output
    VALIDATES (derived_from minItems:1 was dropped so a zero-signal gap is not a de-facto novelty cut)."""
    gap = {"gap_id": "GAP-ZERO", "gap_type": "coverage_gap", "evidence_ref": ["[[r]]"]}
    result = aggregate_novelty([gap])
    score = result["scores"][0]
    assert score["novelty"] == pytest.approx(0.0)
    assert score["derived_from"] == []
    assert validate_against("novelty_score.schema.json", result) == []
