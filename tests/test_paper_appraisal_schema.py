"""Tests for paper_appraisal.schema.json (P1 NEW; see paper-reading-upgrade-LEDGER D5).

paper_appraisal is the venue 7-dimension rigor rubric RE-POINTED OUTWARD at an EXTERNAL
paper being READ. It is ADVISORY only — a reading aid — and must NEVER carry a verdict /
accept / reject / cut / decision field (additionalProperties:false makes that impossible).

The schema is validated DIRECTLY via tools.validate_artifact.validate_against, which loads
the named schema file out of schemas/ without depending on PAYLOAD_SCHEMAS registration
(the lead serializes the registry edit separately). validate_against returns a list of
human-readable error strings; an empty list means the instance is valid.

Covers (REAL assertions, no mocks, no skips):
  - a valid FULL instance (all 7 dimensions + a populated checklist + every optional field),
  - a realistic instance carrying all 7 rubric dimensions validates,
  - missing-required (no dimensions) -> error,
  - bad enum (a dimension `dim`, and a checklist `status`) -> error,
  - out-of-range score (5, and 0) -> error,
  - unknown property at every level -> error,
  - the structural guarantee: a verdict/decision/accept field cannot be added.
"""
from __future__ import annotations

import json
from pathlib import Path

from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "paper_appraisal.schema.json"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas" / SCHEMA
)


# --------------------------------------------------------------------------- builders

def _all_seven_dimensions() -> list:
    """One score object for each of the 7 rubric dimensions (advisory, never aggregated)."""
    return [
        {"dim": "soundness", "score": 3, "evidence_ref": "§4.2", "note": "main claim supported"},
        {"dim": "significance", "score": 2, "note": "narrow sub-community"},
        {"dim": "originality", "score": 3, "evidence_ref": "§1"},
        {"dim": "eval_rigor", "score": 2, "note": "one outdated baseline"},
        {"dim": "reproducibility", "score": 1, "evidence_ref": None},
        {"dim": "clarity", "score": 4},
        {"dim": "domain_validity", "score": 3, "note": "single-center but representative"},
    ]


def _full_instance() -> dict:
    """A maximally-populated, schema-valid appraisal — every optional field present."""
    return {
        "source_ref": "[[medsam3-iac-2025]]",
        "paper_type": "method",
        "dimensions": _all_seven_dimensions(),
        "assumptions": ["foreground class is rare", "test set is in-distribution"],
        "limitations_acknowledged": ["single dataset"],
        "limitations_unacknowledged": ["no variance reported across seeds"],
        "baseline_fairness": "baselines are from literature but one is under-tuned",
        "ablation_sufficiency": "loss-term ablation present; encoder-freeze ablation missing",
        "statistical_robustness": "single run, no confidence intervals",
        "selective_reporting": "only the best checkpoint's Dice is reported",
        "reproducibility_gaps": ["hyperparameters not fully documented", "code not public"],
        "generalization": "claims likely hold only on CBCT of similar resolution",
        "reviewer_questions": ["how were splits drawn?", "what is the variance across seeds?"],
        "checklist": {
            "standard": "neurips",
            "items": [
                {"item": "limitations section present", "status": "met"},
                {"item": "compute disclosed", "status": "partial", "note": "GPU count only"},
                {"item": "code released", "status": "unmet"},
                {"item": "human subjects ethics", "status": "na"},
            ],
        },
        "overall": "A solid methodological contribution with reproducibility gaps; "
        "trust the Dice numbers only after a seed-variance check. Advisory reading note.",
    }


# --------------------------------------------------------------------------- valid

def test_schema_file_is_valid_json():
    """The schema file itself must parse as JSON."""
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["$id"] == "https://research-os/schemas/paper_appraisal.schema.json"
    assert doc["additionalProperties"] is False
    assert doc["required"] == ["source_ref", "dimensions"]


def test_full_instance_validates():
    """The maximally-populated instance (incl. a checklist + several dimensions) is valid."""
    errors = validate_against(SCHEMA, _full_instance())
    assert errors == [], f"full instance should validate, got: {errors}"


def test_all_seven_dimensions_validates():
    """A realistic instance carrying all 7 rubric dimensions validates."""
    instance = {
        "source_ref": "papers/external/foo.pdf",
        "dimensions": _all_seven_dimensions(),
    }
    dims = {d["dim"] for d in instance["dimensions"]}
    assert dims == {
        "soundness",
        "significance",
        "originality",
        "eval_rigor",
        "reproducibility",
        "clarity",
        "domain_validity",
    }
    assert validate_against(SCHEMA, instance) == []


def test_minimal_required_only_validates():
    """source_ref + a single dimension is the floor and is valid."""
    instance = {
        "source_ref": "doi:10.1000/xyz",
        "dimensions": [{"dim": "soundness", "score": 3}],
    }
    assert validate_against(SCHEMA, instance) == []


def test_paper_type_null_validates():
    """paper_type accepts null (the documented default / unclassified state)."""
    instance = {
        "source_ref": "x",
        "paper_type": None,
        "dimensions": [{"dim": "clarity", "score": 4}],
    }
    assert validate_against(SCHEMA, instance) == []


def test_not_applicable_dimension_may_use_null_score_with_note():
    instance = {
        "source_ref": "x",
        "dimensions": [{
            "dim": "domain_validity", "score": None,
            "note": "Not applicable to this methodological paper.",
        }],
    }
    assert validate_against(SCHEMA, instance) == []


def test_null_checklist_validates():
    """checklist accepts null (no formal standard applies)."""
    instance = {
        "source_ref": "x",
        "dimensions": [{"dim": "clarity", "score": 4}],
        "checklist": None,
    }
    assert validate_against(SCHEMA, instance) == []


# --------------------------------------------------------------------------- missing required

def test_missing_dimensions_is_error():
    instance = {"source_ref": "x"}
    assert validate_against(SCHEMA, instance) != []


def test_missing_source_ref_is_error():
    instance = {"dimensions": [{"dim": "soundness", "score": 3}]}
    assert validate_against(SCHEMA, instance) != []


def test_empty_source_ref_is_error():
    """source_ref has minLength 1 — blank is rejected."""
    instance = {"source_ref": "", "dimensions": [{"dim": "soundness", "score": 3}]}
    assert validate_against(SCHEMA, instance) != []


def test_dimension_missing_required_keys_is_error():
    instance = {"source_ref": "x", "dimensions": [{"dim": "soundness"}]}  # no score
    assert validate_against(SCHEMA, instance) != []


def test_checklist_item_missing_status_is_error():
    instance = _full_instance()
    instance["checklist"]["items"].append({"item": "no status here"})
    assert validate_against(SCHEMA, instance) != []


# --------------------------------------------------------------------------- bad enum

def test_bad_dimension_enum_is_error():
    """A `dim` outside the 7-dimension enum is rejected."""
    instance = {
        "source_ref": "x",
        "dimensions": [{"dim": "vibes", "score": 3}],
    }
    assert validate_against(SCHEMA, instance) != []


def test_bad_checklist_status_enum_is_error():
    instance = _full_instance()
    instance["checklist"]["items"][0]["status"] = "maybe"  # not in enum
    assert validate_against(SCHEMA, instance) != []


def test_bad_checklist_standard_enum_is_error():
    instance = _full_instance()
    instance["checklist"]["standard"] = "made_up_standard"
    assert validate_against(SCHEMA, instance) != []


def test_bad_paper_type_enum_is_error():
    instance = {
        "source_ref": "x",
        "paper_type": "manifesto",  # not in enum
        "dimensions": [{"dim": "clarity", "score": 4}],
    }
    assert validate_against(SCHEMA, instance) != []


# --------------------------------------------------------------------------- out-of-range score

def test_score_above_range_is_error():
    instance = {"source_ref": "x", "dimensions": [{"dim": "soundness", "score": 5}]}
    assert validate_against(SCHEMA, instance) != []


def test_score_below_range_is_error():
    instance = {"source_ref": "x", "dimensions": [{"dim": "soundness", "score": 0}]}
    assert validate_against(SCHEMA, instance) != []


def test_score_non_integer_is_error():
    instance = {"source_ref": "x", "dimensions": [{"dim": "soundness", "score": 3.5}]}
    assert validate_against(SCHEMA, instance) != []


# --------------------------------------------------------------------------- unknown property (additionalProperties:false)

def test_unknown_top_level_property_is_error():
    instance = _full_instance()
    instance["bogus"] = "nope"
    assert validate_against(SCHEMA, instance) != []


def test_unknown_dimension_property_is_error():
    instance = {
        "source_ref": "x",
        "dimensions": [{"dim": "soundness", "score": 3, "weight": 0.4}],
    }
    assert validate_against(SCHEMA, instance) != []


def test_unknown_checklist_property_is_error():
    instance = _full_instance()
    instance["checklist"]["extra"] = "nope"
    assert validate_against(SCHEMA, instance) != []


def test_unknown_checklist_item_property_is_error():
    instance = _full_instance()
    instance["checklist"]["items"][0]["severity"] = "high"
    assert validate_against(SCHEMA, instance) != []


# --------------------------------------------------------------------------- advisory guarantee (no verdict field)

def test_verdict_field_is_structurally_impossible():
    """ADVISORY contract (D5): a self-decision field cannot be smuggled in."""
    for forbidden in ("verdict", "decision", "accept", "cut", "meets_bar", "status"):
        instance = _full_instance()
        instance[forbidden] = "PASS"
        assert validate_against(SCHEMA, instance) != [], (
            f"a '{forbidden}' field must be rejected — paper_appraisal is advisory, never a gate"
        )
