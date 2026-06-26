"""Tests for the saturation_meter deterministic evidence-saturation meter (DISCOVER-stage).

Proves that:
  - a clearly-saturated search history (new-result rate decays to ~0) -> SATURATED
  - a rising / steady new-result history -> NOT_SATURATED
  - fewer than MIN_ROUNDS_TO_JUDGE rounds -> INSUFFICIENT_DATA (never a silent cut)
  - the meter is deterministic (same history -> same payload)
  - duplicate_rate / new_result_rate_last_round / saturation_score math is exact
  - a sample report VALIDATES against evidence_saturation_report.schema.json
    (checked with jsonschema DIRECTLY against the schema file — NOT via PAYLOAD_SCHEMAS)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.saturation_meter import (
    MIN_ROUNDS_TO_JUDGE,
    SATURATION_RATE_THRESHOLD,
    SATURATION_WINDOW_ROUNDS,
    decide_verdict,
    duplicate_rate,
    measure_saturation,
    new_result_rate_last_round,
    saturation_score,
)

# Schema loaded DIRECTLY from the file (the prompt forbids relying on PAYLOAD_SCHEMAS
# registration). This is the strict 2020-12 validator over the report payload.
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "evidence_saturation_report.schema.json"
)


def _schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


def _round(idx: int, queries: int, new: int, cumulative: int) -> dict:
    return {
        "round_index": idx,
        "queries_run": queries,
        "new_unique_sources": new,
        "cumulative_unique_sources": cumulative,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures: distinct saturation histories
# ──────────────────────────────────────────────────────────────────────────────

def _saturated_history() -> list:
    """New-result rate decays to ~0: 1.0 -> 0.167 -> 0.032 -> 0.0.
    Last 2 rounds (0.032, 0.0) both <= 0.10 -> SATURATED."""
    return [
        _round(0, 3, 50, 50),   # rate 1.0
        _round(1, 3, 10, 60),   # rate 0.1667
        _round(2, 2, 2, 62),    # rate 0.0323 (<= 0.10)
        _round(3, 2, 0, 62),    # rate 0.0    (<= 0.10)
    ]


def _rising_history() -> list:
    """New-result rate stays high: 1.0 -> 0.556 -> 0.40.
    Last 2 rounds both > 0.10 -> NOT_SATURATED."""
    return [
        _round(0, 3, 20, 20),   # rate 1.0
        _round(1, 3, 25, 45),   # rate 0.5556
        _round(2, 3, 30, 75),   # rate 0.40
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Verdict tests
# ──────────────────────────────────────────────────────────────────────────────

def test_saturated_history_verdict_saturated():
    rounds = _saturated_history()
    assert decide_verdict(rounds) == "SATURATED"
    report = measure_saturation(rounds)
    assert report["verdict"] == "SATURATED"


def test_rising_history_verdict_not_saturated():
    rounds = _rising_history()
    assert decide_verdict(rounds) == "NOT_SATURATED"
    report = measure_saturation(rounds)
    assert report["verdict"] == "NOT_SATURATED"


def test_steady_high_yield_is_not_saturated():
    """A flat-but-high new-result rate (every round still finds plenty) is NOT saturated."""
    rounds = [
        _round(0, 2, 30, 30),   # 1.0
        _round(1, 2, 30, 60),   # 0.5
        _round(2, 2, 30, 90),   # 0.3333
    ]
    assert decide_verdict(rounds) == "NOT_SATURATED"


def test_too_few_rounds_insufficient_data():
    """Fewer than MIN_ROUNDS_TO_JUDGE rounds -> INSUFFICIENT_DATA (never a silent cut)."""
    one_round = [_round(0, 3, 40, 40)]
    assert len(one_round) < MIN_ROUNDS_TO_JUDGE
    assert decide_verdict(one_round) == "INSUFFICIENT_DATA"
    report = measure_saturation(one_round)
    assert report["verdict"] == "INSUFFICIENT_DATA"


def test_empty_history_insufficient_data():
    """No rounds at all -> INSUFFICIENT_DATA, and all rate fields are 0.0."""
    report = measure_saturation([])
    assert report["verdict"] == "INSUFFICIENT_DATA"
    assert report["new_result_rate_last_round"] == 0.0
    assert report["duplicate_rate"] == 0.0
    # saturation_score = 1 - 0.0 = 1.0 by definition (no new yield observed)
    assert report["saturation_score"] == 1.0


def test_borderline_at_threshold_counts_as_saturated():
    """A round whose marginal rate equals exactly SATURATION_RATE_THRESHOLD counts
    as saturated (the rule is <=, inclusive). new=10/cum=100 -> 0.10."""
    rounds = [
        _round(0, 2, 90, 90),    # 1.0
        _round(1, 2, 10, 100),   # exactly 0.10
        _round(2, 2, 10, 110),   # 0.0909 (< 0.10)
    ]
    # last 2 rounds: 0.0909 and ... need the window. Window is last 2: rounds[1],[2]
    # rates 0.10 and 0.0909, both <= 0.10 -> SATURATED
    assert SATURATION_WINDOW_ROUNDS == 2  # guard: fixture tuned to this window
    assert decide_verdict(rounds) == "SATURATED"


def test_one_dip_inside_window_still_not_saturated():
    """If only the final round dips below threshold but the prior window round is still
    high, the full window is NOT all-below -> NOT_SATURATED."""
    rounds = [
        _round(0, 2, 20, 20),    # 1.0
        _round(1, 2, 20, 40),    # 0.5   (> 0.10, inside window)
        _round(2, 2, 1, 41),     # 0.0244 (<= 0.10)
    ]
    assert decide_verdict(rounds) == "NOT_SATURATED"


# ──────────────────────────────────────────────────────────────────────────────
# Exact math tests
# ──────────────────────────────────────────────────────────────────────────────

def test_new_result_rate_last_round_exact():
    """Last round new=0/cum=10 -> rate 0.0."""
    rounds = [_round(0, 1, 10, 10), _round(1, 1, 0, 10)]
    assert new_result_rate_last_round(rounds) == 0.0


def test_new_result_rate_first_round_is_one():
    """The first non-empty round is all-new -> marginal rate 1.0."""
    rounds = [_round(0, 1, 7, 7)]
    assert new_result_rate_last_round(rounds) == 1.0


def test_duplicate_rate_exact_half():
    """Two rounds with marginal rates 1.0 and 0.0 -> mean 0.5 -> duplicate_rate 0.5."""
    rounds = [_round(0, 1, 10, 10), _round(1, 1, 0, 10)]
    assert duplicate_rate(rounds) == 0.5


def test_duplicate_rate_zero_when_every_round_all_new():
    """If each round's cumulative == its own new count (no prior overlap basis), the
    marginal rate is 1.0 every round -> duplicate_rate 0.0."""
    # Construct rounds where new_unique == cumulative each round (rate 1.0 each).
    rounds = [_round(0, 1, 5, 5), _round(1, 1, 5, 5)]
    assert duplicate_rate(rounds) == 0.0


def test_saturation_score_is_one_minus_last_rate():
    """saturation_score == 1 - new_result_rate_last_round."""
    rounds = _rising_history()
    last = new_result_rate_last_round(rounds)
    assert saturation_score(rounds) == pytest.approx(1.0 - last, abs=1e-6)


def test_rates_clamped_to_unit_interval():
    """Every reported rate/score stays within [0, 1] even for a fully-saturated tail."""
    report = measure_saturation(_saturated_history())
    for key in ("new_result_rate_last_round", "duplicate_rate", "saturation_score"):
        assert 0.0 <= report[key] <= 1.0, f"{key}={report[key]} out of [0,1]"


# ──────────────────────────────────────────────────────────────────────────────
# Determinism
# ──────────────────────────────────────────────────────────────────────────────

def test_measure_saturation_deterministic_same_input_same_output():
    rounds = _saturated_history()
    r1 = measure_saturation(rounds)
    r2 = measure_saturation(rounds)
    assert r1 == r2


def test_decide_verdict_deterministic():
    rounds = _rising_history()
    assert decide_verdict(rounds) == decide_verdict(rounds)


# ──────────────────────────────────────────────────────────────────────────────
# Schema validation (jsonschema DIRECTLY against the schema file)
# ──────────────────────────────────────────────────────────────────────────────

def test_schema_file_is_a_valid_draft_2020_12_schema():
    """The schema itself must be a well-formed Draft 2020-12 schema."""
    Draft202012Validator.check_schema(_schema())


def test_saturated_report_validates_against_schema():
    """A SATURATED report payload validates against the schema with zero errors."""
    report = measure_saturation(
        _saturated_history(),
        report_id="SAT-100",
        coverage_dimensions=["method", "dataset", "application-domain"],
    )
    errors = sorted(_validator().iter_errors(report), key=str)
    assert errors == [], f"saturated report failed schema validation: {[e.message for e in errors]}"


def test_not_saturated_report_validates_against_schema():
    report = measure_saturation(
        _rising_history(),
        report_id="SAT-101",
        coverage_dimensions=["baseline"],
    )
    errors = sorted(_validator().iter_errors(report), key=str)
    assert errors == [], f"not-saturated report failed schema validation: {[e.message for e in errors]}"


def test_insufficient_data_report_validates_against_schema():
    """The INSUFFICIENT_DATA payload (empty rounds, empty dims) is still schema-valid."""
    report = measure_saturation([], report_id="SAT-102")
    errors = sorted(_validator().iter_errors(report), key=str)
    assert errors == [], f"insufficient-data report failed schema validation: {[e.message for e in errors]}"


def test_schema_rejects_unknown_verdict():
    """additionalProperties:false + enum: a bogus verdict must be rejected (negative control)."""
    report = measure_saturation(_saturated_history())
    report["verdict"] = "MAYBE_SATURATED"  # not in the enum
    errors = list(_validator().iter_errors(report))
    assert errors, "schema must reject a verdict outside the enum"


def test_schema_rejects_additional_property():
    """additionalProperties:false must reject an unexpected top-level key (negative control)."""
    report = measure_saturation(_saturated_history())
    report["unexpected_field"] = "nope"
    errors = list(_validator().iter_errors(report))
    assert errors, "schema must reject an unexpected top-level property"


def test_schema_rejects_blank_report_id():
    """report_id pattern \\S must reject a blank id (negative control)."""
    report = measure_saturation(_saturated_history())
    report["report_id"] = "   "
    errors = list(_validator().iter_errors(report))
    assert errors, "schema must reject a blank report_id"
