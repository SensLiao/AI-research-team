"""Tests for paper_relations.schema.json (Stage-4 typed paper-to-paper edges).

Proves, with REAL assertions (no mocks, no skips):
  - a fully-populated instance validates (empty error list);
  - a missing-required field (source_ref / edges, and per-edge target_ref / relation) is rejected;
  - a bad `relation` enum value is rejected;
  - an unknown property (top-level and per-edge) is rejected by additionalProperties:false.

Loaded through tools.validate_artifact.validate_against("<filename>", instance), which reads the
schema file directly from schemas/ and does NOT depend on PAYLOAD_SCHEMAS registration (the lead
wires the registry in a later step; this suite is correct before that).
"""
from __future__ import annotations

import copy

from research_agent_teams.tools.validate_artifact import validate_against

_SCHEMA = "paper_relations.schema.json"


def _good() -> dict:
    """A fully-populated, valid paper_relations instance (every property exercised)."""
    return {
        "source_ref": "iac-cbct-seg/papers/medsam3",
        "edges": [
            {
                "target_ref": "iac-cbct-seg/papers/medsam2",
                "relation": "extends",
                "note": "adds a topology-aware adapter on top of the MedSAM2 backbone",
            },
            {
                "target_ref": "iac-cbct-seg/papers/nnunet",
                "relation": "refutes",
                "note": "shows the supervised baseline is beatable under label scarcity",
            },
            {
                "target_ref": "iac-cbct-seg/papers/sam-adapter",
                "relation": "uses",
            },
        ],
    }


# --------------------------------------------------------------------------- valid

def test_full_instance_valid():
    assert validate_against(_SCHEMA, _good()) == []


def test_minimal_instance_valid():
    """Only required fields, with an empty edge list, is valid."""
    assert validate_against(_SCHEMA, {"source_ref": "p/focal", "edges": []}) == []


def test_every_relation_enum_value_valid():
    """Each allowed relation value validates."""
    for rel in ["inherits", "refutes", "unifies", "replaces", "opens", "extends", "uses"]:
        inst = {"source_ref": "p/focal", "edges": [{"target_ref": "p/other", "relation": rel}]}
        assert validate_against(_SCHEMA, inst) == [], f"relation {rel!r} should be valid"


# --------------------------------------------------------------------------- missing required

def test_missing_source_ref_rejected():
    bad = _good()
    del bad["source_ref"]
    assert validate_against(_SCHEMA, bad) != []


def test_missing_edges_rejected():
    bad = _good()
    del bad["edges"]
    assert validate_against(_SCHEMA, bad) != []


def test_edge_missing_target_ref_rejected():
    bad = _good()
    del bad["edges"][0]["target_ref"]
    assert validate_against(_SCHEMA, bad) != []


def test_edge_missing_relation_rejected():
    bad = _good()
    del bad["edges"][0]["relation"]
    assert validate_against(_SCHEMA, bad) != []


def test_empty_source_ref_rejected():
    bad = _good()
    bad["source_ref"] = ""
    assert validate_against(_SCHEMA, bad) != []


def test_empty_target_ref_rejected():
    bad = _good()
    bad["edges"][0]["target_ref"] = ""
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- bad enum

def test_bad_relation_enum_rejected():
    bad = _good()
    bad["edges"][0]["relation"] = "contradicts"  # not in enum
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- unknown property

def test_unknown_top_level_property_rejected():
    bad = _good()
    bad["verdict"] = "PASS"  # additionalProperties:false
    assert validate_against(_SCHEMA, bad) != []


def test_unknown_edge_property_rejected():
    bad = _good()
    bad["edges"][0]["weight"] = 0.9  # additionalProperties:false on the edge object
    assert validate_against(_SCHEMA, bad) != []


# --------------------------------------------------------------------------- non-mutation guard

def test_good_fixture_is_independent():
    """_good() returns a fresh dict each call — mutating one instance never poisons another."""
    a = _good()
    b = _good()
    a["edges"][0]["relation"] = "opens"
    assert b == _good()
    assert b != a
    assert copy.deepcopy(a) == a
