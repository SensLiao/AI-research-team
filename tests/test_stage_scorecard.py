"""Tests for the cross-stage quality-scorecard aggregator (the genuinely-new AGGREGATION layer).

Proves the aggregator READS the existing analysis_check_verdict shape and rolls per-stage verdicts
up into a global scorecard with a deterministic, structurally-enforced ``can_finish``:

  * a stage rollup ANDs its verdicts' pass bits into stage_pass
  * all required dimensions passing → can_finish True, blocking_reasons empty
  * any required dimension failing → can_finish False, and blocking_reasons NAMES it
  * determinism (same input → byte-identical output)
  * the verdict pass bit is consumed from the EXISTING analysis_check_verdict shape (panel_role +
    pass + violations) — not a re-invented format
  * built samples VALIDATE against BOTH schemas via jsonschema's Draft202012Validator directly
    (NOT via PAYLOAD_SCHEMAS registration)
  * NEGATIVE: a global scorecard with can_finish:true but a failing dimension is SCHEMA-REJECTED
    (the allOf conditional makes "finish with a failing dimension" structurally impossible)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.stage_scorecard import (
    REQUIRED_DIMENSIONS,
    build_global_scorecard,
    build_stage_scorecard,
    can_finish_run,
)

# ──────────────────────────────────────────────────────────────────────────────
# Schema loading — read the schema files directly and validate with jsonschema
# (deliberately NOT through tools.validate_artifact.PAYLOAD_SCHEMAS, per the brief).
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


STAGE_SCHEMA = _load_schema("stage_scorecard.schema.json")
GLOBAL_SCHEMA = _load_schema("global_quality_scorecard.schema.json")
STAGE_VALIDATOR = Draft202012Validator(STAGE_SCHEMA)
GLOBAL_VALIDATOR = Draft202012Validator(GLOBAL_SCHEMA)


def _stage_errors(payload: dict) -> list[str]:
    return [e.message for e in STAGE_VALIDATOR.iter_errors(payload)]


def _global_errors(payload: dict) -> list[str]:
    return [e.message for e in GLOBAL_VALIDATOR.iter_errors(payload)]


# ──────────────────────────────────────────────────────────────────────────────
# Builders that exercise EVERY required dimension across the real FSM stages.
# ──────────────────────────────────────────────────────────────────────────────

# The full set of stages whose cards are needed so all six required dimensions are satisfiable.
# (_DIMENSION_STAGE_MAP: grounding<-DISCOVER, novelty<-DISCOVER/IDEATE,
#  method_completeness<-DESIGN/EXECUTE, analysis_validity<-ANALYZE,
#  integrity<-EXECUTE/ANALYZE, review<-VERIFY.)
_ALL_DIMENSION_STAGES = ["DISCOVER", "IDEATE", "DESIGN", "EXECUTE", "ANALYZE", "VERIFY"]


def _verdict(panel_role: str, ok: bool) -> dict:
    """A verdict in the EXISTING analysis_check_verdict shape (panel_role + pass + violations).

    pass is consistent with violations exactly as analysis_check_verdict.schema.json derives it.
    """
    return {
        "panel_role": panel_role,
        "pass": ok,
        "violations": [] if ok else [f"{panel_role} violation"],
        "evidence_ref": f"runs/demo/evidence/{panel_role}.artifact.json",
    }


def _all_pass_stage_cards() -> list[dict]:
    """One passing stage card per stage needed to satisfy all six required dimensions."""
    return [
        build_stage_scorecard(stage, [_verdict("goal_alignment", True)])
        for stage in _ALL_DIMENSION_STAGES
    ]


# ==============================================================================
# Stage rollup — AND logic
# ==============================================================================

def test_stage_rollup_all_pass_is_true():
    card = build_stage_scorecard("ANALYZE", [
        _verdict("fairness", True),
        _verdict("compliance", True),
        _verdict("goal_alignment", True),
    ])
    assert card["stage"] == "ANALYZE"
    assert card["stage_pass"] is True
    assert len(card["dimension_results"]) == 3
    assert all(d["pass"] for d in card["dimension_results"])


def test_stage_rollup_one_fail_makes_stage_fail():
    """AND logic: a single failing verdict makes the whole stage fail."""
    card = build_stage_scorecard("ANALYZE", [
        _verdict("fairness", True),
        _verdict("compliance", False),  # one failure
        _verdict("goal_alignment", True),
    ])
    assert card["stage_pass"] is False


def test_stage_rollup_empty_is_vacuously_true():
    """No verdicts → vacuously passing stage (nothing failed)."""
    card = build_stage_scorecard("REPORT", [])
    assert card["stage_pass"] is True
    assert card["dimension_results"] == []


def test_stage_rollup_reads_pass_from_existing_verdict_shape():
    """The pass bit is consumed from the existing analysis_check_verdict shape, not recomputed."""
    failing_verdict = _verdict("compliance", False)
    # The verdict already carries pass=False (derived from its violations by that schema).
    assert failing_verdict["pass"] is False and failing_verdict["violations"]
    card = build_stage_scorecard("ANALYZE", [failing_verdict])
    assert card["dimension_results"][0]["pass"] is False
    assert card["dimension_results"][0]["dimension"] == "compliance"  # from panel_role


def test_stage_rollup_unknown_stage_raises():
    with pytest.raises(ValueError, match="unknown stage"):
        build_stage_scorecard("NOT_A_STAGE", [_verdict("fairness", True)])


def test_stage_rollup_verdict_without_bool_pass_raises():
    """We never guess a pass/fail — a verdict missing a boolean pass raises."""
    with pytest.raises(ValueError, match="boolean 'pass'"):
        build_stage_scorecard("ANALYZE", [{"panel_role": "fairness", "violations": []}])


# ==============================================================================
# Global rollup — can_finish AND over required dimensions
# ==============================================================================

def test_global_all_pass_can_finish_true_no_blocking_reasons():
    g = build_global_scorecard("run-001", _all_pass_stage_cards())
    assert g["run_id"] == "run-001"
    assert g["can_finish"] is True
    assert g["blocking_reasons"] == []
    # Every required dimension present and passing.
    for dim in REQUIRED_DIMENSIONS:
        assert g["dimensions"][dim]["pass"] is True


def test_global_one_dimension_fail_blocks_and_names_it():
    """A failing VERIFY stage fails the 'review' dimension → can_finish False, named in reasons."""
    cards = []
    for stage in _ALL_DIMENSION_STAGES:
        ok = stage != "VERIFY"  # make VERIFY fail
        cards.append(build_stage_scorecard(stage, [_verdict("goal_alignment", ok)]))
    g = build_global_scorecard("run-002", cards)
    assert g["can_finish"] is False
    assert g["dimensions"]["review"]["pass"] is False
    assert any("review" in reason for reason in g["blocking_reasons"]), g["blocking_reasons"]


def test_global_missing_stage_fails_dependent_dimension():
    """A dimension whose required stage card is absent cannot pass (nothing established it)."""
    # Drop VERIFY entirely → 'review' has no card.
    cards = [
        build_stage_scorecard(stage, [_verdict("goal_alignment", True)])
        for stage in _ALL_DIMENSION_STAGES if stage != "VERIFY"
    ]
    g = build_global_scorecard("run-003", cards)
    assert g["dimensions"]["review"]["pass"] is False
    assert g["can_finish"] is False
    assert any("review" in r for r in g["blocking_reasons"])


def test_global_empty_blocks_every_dimension():
    """No stage cards at all → every required dimension fails, can_finish False."""
    g = build_global_scorecard("run-004", [])
    assert g["can_finish"] is False
    assert len(g["blocking_reasons"]) == len(REQUIRED_DIMENSIONS)


def test_global_empty_run_id_raises():
    with pytest.raises(ValueError, match="run_id"):
        build_global_scorecard("   ", _all_pass_stage_cards())


def test_global_unknown_stage_card_raises():
    with pytest.raises(ValueError, match="unknown stage"):
        build_global_scorecard("run-x", [{"stage": "BOGUS", "dimension_results": [], "stage_pass": True}])


# ==============================================================================
# can_finish_run — independent re-derivation
# ==============================================================================

def test_can_finish_run_matches_built_field_when_all_pass():
    g = build_global_scorecard("run-005", _all_pass_stage_cards())
    assert can_finish_run(g) is True
    assert can_finish_run(g) == g["can_finish"]


def test_can_finish_run_false_when_a_dimension_fails():
    cards = []
    for stage in _ALL_DIMENSION_STAGES:
        ok = stage != "ANALYZE"  # fails analysis_validity + integrity
        cards.append(build_stage_scorecard(stage, [_verdict("goal_alignment", ok)]))
    g = build_global_scorecard("run-006", cards)
    assert can_finish_run(g) is False
    assert can_finish_run(g) == g["can_finish"]


def test_can_finish_run_missing_dimension_raises():
    """A required dimension absent from the object is never assumed to pass."""
    broken = {
        "run_id": "r",
        "stage_scorecards": [],
        "dimensions": {"grounding": {"pass": True, "evidence_ref": []}},  # missing the other five
        "can_finish": False,
        "blocking_reasons": ["incomplete"],
    }
    with pytest.raises(ValueError, match="absent or lacks"):
        can_finish_run(broken)


# ==============================================================================
# Determinism
# ==============================================================================

def test_build_stage_scorecard_deterministic():
    verdicts = [_verdict("fairness", True), _verdict("compliance", False)]
    assert build_stage_scorecard("ANALYZE", verdicts) == build_stage_scorecard("ANALYZE", verdicts)


def test_build_global_scorecard_deterministic():
    a = build_global_scorecard("run-det", _all_pass_stage_cards())
    b = build_global_scorecard("run-det", _all_pass_stage_cards())
    assert a == b
    # And byte-identical when serialised (no set/dict ordering nondeterminism leaks out).
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ==============================================================================
# Schema conformance — validate built payloads against BOTH schemas via jsonschema
# ==============================================================================

def test_built_stage_scorecard_validates_against_schema():
    card = build_stage_scorecard("ANALYZE", [
        _verdict("fairness", True),
        _verdict("compliance", False),
    ])
    assert _stage_errors(card) == [], _stage_errors(card)


def test_built_global_scorecard_all_pass_validates_against_schema():
    g = build_global_scorecard("run-schema-1", _all_pass_stage_cards())
    assert _global_errors(g) == [], _global_errors(g)


def test_built_global_scorecard_with_failure_validates_against_schema():
    """A legitimately-failing scorecard (can_finish False) is still a VALID document."""
    cards = []
    for stage in _ALL_DIMENSION_STAGES:
        ok = stage != "VERIFY"
        cards.append(build_stage_scorecard(stage, [_verdict("goal_alignment", ok)]))
    g = build_global_scorecard("run-schema-2", cards)
    assert g["can_finish"] is False
    assert _global_errors(g) == [], _global_errors(g)


# ==============================================================================
# NEGATIVE schema tests — the can_finish conditional bites
# ==============================================================================

def test_schema_rejects_can_finish_true_with_failing_dimension():
    """The crux: can_finish:true while a required dimension has pass:false is SCHEMA-REJECTED.
    Makes it structurally impossible to 'finish' a run with a failing dimension — even if a
    producer hand-forged the boolean, the schema refuses the document."""
    forged = {
        "run_id": "run-forged",
        "stage_scorecards": [],
        "dimensions": {
            "grounding": {"pass": True, "evidence_ref": ["DISCOVER"]},
            "novelty": {"pass": True, "evidence_ref": ["DISCOVER"]},
            "method_completeness": {"pass": True, "evidence_ref": ["DESIGN"]},
            "analysis_validity": {"pass": False, "evidence_ref": ["ANALYZE"]},  # FAILING
            "integrity": {"pass": True, "evidence_ref": ["ANALYZE"]},
            "review": {"pass": True, "evidence_ref": ["VERIFY"]},
        },
        "can_finish": True,  # forged: claims finish despite a failing dimension
        "blocking_reasons": [],
    }
    errors = _global_errors(forged)
    assert errors != [], "schema must reject can_finish:true with a failing required dimension"


def test_schema_allows_can_finish_false_with_failing_dimension():
    """Control for the negative test: the SAME failing dimension with can_finish:false is VALID
    (the conditional only constrains the can_finish:true branch)."""
    honest = {
        "run_id": "run-honest",
        "stage_scorecards": [],
        "dimensions": {
            "grounding": {"pass": True, "evidence_ref": ["DISCOVER"]},
            "novelty": {"pass": True, "evidence_ref": ["DISCOVER"]},
            "method_completeness": {"pass": True, "evidence_ref": ["DESIGN"]},
            "analysis_validity": {"pass": False, "evidence_ref": ["ANALYZE"]},  # FAILING
            "integrity": {"pass": True, "evidence_ref": ["ANALYZE"]},
            "review": {"pass": True, "evidence_ref": ["VERIFY"]},
        },
        "can_finish": False,  # honest
        "blocking_reasons": ["analysis_validity did not pass"],
    }
    assert _global_errors(honest) == [], _global_errors(honest)


def test_schema_rejects_additional_properties_stage():
    """additionalProperties:false on the stage card."""
    bad = {
        "stage": "ANALYZE",
        "dimension_results": [],
        "stage_pass": True,
        "sneaky_extra": 1,
    }
    assert _stage_errors(bad) != []


def test_schema_rejects_additional_properties_global():
    """additionalProperties:false on the global scorecard."""
    g = build_global_scorecard("run-extra", _all_pass_stage_cards())
    g["sneaky_extra"] = "nope"
    assert _global_errors(g) != []


def test_schema_rejects_stage_pass_true_with_failing_dimension_result():
    """The stage-level allOf also bites: stage_pass:true with a failing dimension_result is rejected."""
    bad = {
        "stage": "ANALYZE",
        "dimension_results": [
            {"dimension": "fairness", "pass": False, "evidence_ref": "x"},
        ],
        "stage_pass": True,  # contradicts the failing dimension_result
    }
    assert _stage_errors(bad) != []
