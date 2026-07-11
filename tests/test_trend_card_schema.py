"""Tests for trend_card.schema.json (Stage-4 concept-centric trend extraction).

Proves, with REAL assertions (no mocks, no skips):
  - a fully-populated instance validates (empty error list);
  - the minimal instance (only required `scope`) validates;
  - a missing-required field (scope, and per-shift `dimension`) is rejected;
  - a bad `dimension` enum value is rejected;
  - an unknown property (top-level and per-shift) is rejected by additionalProperties:false;
  - reproducibility_trend accepts both a string and null.

Loaded through tools.validate_artifact.validate_against("<filename>", instance), which reads the
schema file directly from schemas/ and does NOT depend on PAYLOAD_SCHEMAS registration (the lead
wires the registry in a later step; this suite is correct before that).
"""
from __future__ import annotations

import copy

from research_agent_teams.tools.validate_artifact import validate_against

_SCHEMA = "trend_card.schema.json"


def _good() -> dict:
    """A fully-populated, valid trend_card instance (every property exercised)."""
    return {
        "scope": "foundation-model adaptation for thin-structure CBCT segmentation",
        "shifts": [
            {
                "dimension": "method",
                "from": "fully-supervised nnU-Net",
                "to": "frozen foundation model + lightweight adapter",
            },
            {
                "dimension": "evaluation",
                "from": "DSC / HD95 only",
                "to": "topology + laterality-swap + human-seconds",
            },
            {"dimension": "resource"},
        ],
        "failure_modes": [
            "over-segmentation of thin branches",
            "broken connectivity at tube junctions",
        ],
        "mechanism_vs_result": "the field reports THAT adapters help but rarely explains WHY",
        "reproducibility_trend": "improving — more papers release weights and configs",
        "opportunities": [
            "no paper owns topology-preservation as the headline metric",
            "human-in-the-loop click budget is unmeasured",
        ],
        "source_refs": [
            "iac-cbct-seg/papers/medsam3",
            "iac-cbct-seg/papers/sam-adapter",
        ],
    }


# --------------------------------------------------------------------------- valid

def test_full_instance_valid():
    assert validate_against(_SCHEMA, _good()) == []


def test_minimal_instance_valid():
    """Only the required `scope` is enough."""
    assert validate_against(_SCHEMA, {"scope": "some sub-area"}) == []


def test_every_dimension_enum_value_valid():
    """Each allowed shift dimension validates."""
    for dim in ["problem", "method", "representation", "assumption", "evaluation", "resource"]:
        inst = {"scope": "s", "shifts": [{"dimension": dim}]}
        assert validate_against(_SCHEMA, inst) == [], f"dimension {dim!r} should be valid"


def test_reproducibility_trend_accepts_null():
    inst = _good()
    inst["reproducibility_trend"] = None
    assert validate_against(_SCHEMA, inst) == []


def test_reproducibility_trend_accepts_string():
    inst = _good()
    inst["reproducibility_trend"] = "stagnant"
    assert validate_against(_SCHEMA, inst) == []


# --------------------------------------------------------------------------- missing required

def test_missing_scope_rejected():
    bad = _good()
    del bad["scope"]
    assert validate_against(_SCHEMA, bad) != []


def test_empty_scope_rejected():
    bad = _good()
    bad["scope"] = ""
    assert validate_against(_SCHEMA, bad) != []


def test_shift_missing_dimension_rejected():
    bad = _good()
    del bad["shifts"][0]["dimension"]
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- bad enum / type

def test_bad_dimension_enum_rejected():
    bad = _good()
    bad["shifts"][0]["dimension"] = "cost"  # not in enum (it's 'resource')
    assert validate_against(_SCHEMA, bad) != []


def test_failure_modes_must_be_strings():
    bad = _good()
    bad["failure_modes"] = ["ok", 42]  # 42 is not a string
    assert validate_against(_SCHEMA, bad) != []


def test_reproducibility_trend_rejects_number():
    bad = _good()
    bad["reproducibility_trend"] = 3  # only string|null allowed
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- unknown property

def test_unknown_top_level_property_rejected():
    bad = _good()
    bad["verdict"] = "PASS"  # additionalProperties:false
    assert validate_against(_SCHEMA, bad) != []


def test_unknown_shift_property_rejected():
    bad = _good()
    bad["shifts"][0]["magnitude"] = "large"  # additionalProperties:false on the shift object
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- non-mutation guard

def test_good_fixture_is_independent():
    """_good() returns a fresh dict each call — mutating one instance never poisons another."""
    a = _good()
    b = _good()
    a["shifts"][0]["dimension"] = "problem"
    assert b == _good()
    assert b != a
    assert copy.deepcopy(a) == a
