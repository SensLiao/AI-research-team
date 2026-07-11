"""Tests for the analogy_graph_match deterministic mechanism matcher + mechanism_mapping schema.

The "Explicit analogy mapping" cluster turns the informal "is this retrieved cross-domain paper a
real structural analog" judgment into a TYPED, scored, checkable artifact. These tests prove:

  - overlap math: identical mechanism sets → 1.0, disjoint → 0.0, partial → the right Jaccard.
  - match_mechanisms partitions into shared / source_only / target_only correctly.
  - determinism: same input → byte-identical output (sorted, normalized).
  - empty-set handling: both-empty → 0.0 (no analogy, never a vacuous 1.0); one-empty → 0.0.
  - normalization: case / whitespace / duplicates collapse.
  - a sample mechanism_mapping payload VALIDATES against mechanism_mapping.schema.json directly via
    jsonschema (NOT via PAYLOAD_SCHEMAS registration — the schema file is loaded straight off disk).
  - NEGATIVE: a verdict:"PASS" mapping WITH a blocking_assumption is REJECTED by the schema's
    allOf/if-then (PASS structurally requires blocking_assumptions to be empty).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.analogy_graph_match import match_mechanisms, overlap_score

# Load mechanism_mapping.schema.json DIRECTLY off disk (the prompt forbids relying on the
# PAYLOAD_SCHEMAS registry for this artifact).
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "mechanism_mapping.schema.json"
)


def _schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


def _schema_errors(instance: dict) -> list[str]:
    return [e.message for e in _validator().iter_errors(instance)]


# ==============================================================================
# overlap_score math
# ==============================================================================

def test_identical_sets_overlap_is_one():
    """Identical non-empty mechanism sets → overlap 1.0."""
    mechs = ["propagate labels along a sparse graph", "segment thin elongated structure"]
    assert overlap_score(mechs, mechs) == 1.0
    assert match_mechanisms(mechs, mechs)["overlap_score"] == 1.0


def test_disjoint_sets_overlap_is_zero():
    """Fully disjoint mechanism sets → overlap 0.0."""
    src = ["mechanism a", "mechanism b"]
    tgt = ["mechanism c", "mechanism d"]
    assert overlap_score(src, tgt) == 0.0
    assert match_mechanisms(src, tgt)["overlap_score"] == 0.0


def test_partial_overlap_is_correct_jaccard():
    """Partial overlap → exact Jaccard (|∩| / |∪|).

    source = {a, b}, target = {b, c} → shared {b}=1, union {a,b,c}=3 → 1/3.
    """
    src = ["mechanism a", "mechanism b"]
    tgt = ["mechanism b", "mechanism c"]
    assert overlap_score(src, tgt) == pytest.approx(1 / 3)
    assert match_mechanisms(src, tgt)["overlap_score"] == pytest.approx(1 / 3)


def test_subset_overlap_is_correct_jaccard():
    """source = {a, b, c}, target = {a, b} → shared 2, union 3 → 2/3."""
    src = ["a", "b", "c"]
    tgt = ["a", "b"]
    assert overlap_score(src, tgt) == pytest.approx(2 / 3)


# ==============================================================================
# match_mechanisms partitioning
# ==============================================================================

def test_match_partitions_shared_source_only_target_only():
    """shared / source_only / target_only must partition the union correctly and be sorted."""
    src = ["b", "a", "c"]
    tgt = ["c", "d"]
    result = match_mechanisms(src, tgt)
    assert result["shared"] == ["c"]
    assert result["source_only"] == ["a", "b"]  # sorted
    assert result["target_only"] == ["d"]


def test_match_keys_present_and_typed():
    """The returned dict carries exactly the four documented keys with the right types."""
    result = match_mechanisms(["a"], ["a", "b"])
    assert set(result.keys()) == {"shared", "source_only", "target_only", "overlap_score"}
    assert isinstance(result["shared"], list)
    assert isinstance(result["source_only"], list)
    assert isinstance(result["target_only"], list)
    assert isinstance(result["overlap_score"], float)


# ==============================================================================
# normalization (case / whitespace / duplicates)
# ==============================================================================

def test_case_and_whitespace_insensitive():
    """'Segment Tube' and ' segment tube ' are the SAME mechanism."""
    assert overlap_score(["Segment Tube"], [" segment tube "]) == 1.0
    assert match_mechanisms(["Segment Tube"], [" segment tube "])["shared"] == ["segment tube"]


def test_duplicates_collapse():
    """Duplicate mechanisms collapse (set semantics) — they do not inflate the union."""
    src = ["a", "a", "a", "b"]
    tgt = ["a", "b", "b"]
    # normalized sets: {a, b} vs {a, b} → identical → 1.0
    assert overlap_score(src, tgt) == 1.0


def test_blank_mechanisms_dropped():
    """Empty / whitespace-only mechanism strings carry no signal and are dropped."""
    src = ["a", "", "   "]
    tgt = ["a"]
    assert overlap_score(src, tgt) == 1.0  # both normalize to {a}
    assert match_mechanisms(src, tgt)["source_only"] == []


# ==============================================================================
# empty-set handling
# ==============================================================================

def test_both_empty_overlap_is_zero():
    """Both sets empty → 0.0 (no mechanisms means no analogy, never a vacuous 1.0)."""
    assert overlap_score([], []) == 0.0
    result = match_mechanisms([], [])
    assert result == {"shared": [], "source_only": [], "target_only": [], "overlap_score": 0.0}


def test_one_empty_overlap_is_zero():
    """One set empty → 0.0 and the other side becomes *_only."""
    assert overlap_score(["a", "b"], []) == 0.0
    assert match_mechanisms(["a", "b"], [])["source_only"] == ["a", "b"]
    assert overlap_score([], ["a", "b"]) == 0.0
    assert match_mechanisms([], ["a", "b"])["target_only"] == ["a", "b"]


# ==============================================================================
# determinism
# ==============================================================================

def test_deterministic_same_input_same_output():
    """Same input → identical output (pure function)."""
    src = ["m1", "m2", "m3"]
    tgt = ["m2", "m3", "m4"]
    r1 = match_mechanisms(src, tgt)
    r2 = match_mechanisms(src, tgt)
    assert r1 == r2


def test_deterministic_order_independent():
    """Reordering the input must NOT change the (sorted) output — order independence."""
    a = match_mechanisms(["c", "a", "b"], ["b", "d"])
    b = match_mechanisms(["a", "b", "c"], ["d", "b"])
    assert a == b


# ==============================================================================
# mechanism_mapping schema — POSITIVE
# ==============================================================================

def _sample_mapping(**overrides) -> dict:
    """A valid mechanism_mapping payload; overrides patch individual fields for negative tests."""
    src = ["propagate labels along a sparse graph", "segment thin elongated structure"]
    tgt = ["propagate labels along a sparse graph", "segment thin elongated structure"]
    m = match_mechanisms(src, tgt)
    base = {
        "mapping_id": "AM-001",
        "source_domain": "graph neural networks",
        "target_problem_id": "PA-tubular-seg-001",
        "shared_mechanisms": [
            {
                "mechanism": mech,
                "source_evidence_ref": ["arXiv:2401.00001"],
                "target_hook": "tubular structure segmentation",
            }
            for mech in m["shared"]
        ],
        "blocking_assumptions": [],
        "required_adaptations": [
            {
                "adaptation": "replace dense loss with a sparse-label variant",
                "addresses": "propagate labels along a sparse graph",
            }
        ],
        "overlap_score": m["overlap_score"],
        "verdict": "PASS",
    }
    base.update(overrides)
    return base


def test_sample_mapping_validates_against_schema():
    """A well-formed mechanism_mapping must validate against the schema (loaded directly)."""
    errors = _schema_errors(_sample_mapping())
    assert errors == [], f"valid mechanism_mapping failed schema validation: {errors}"


def test_repair_verdict_with_blocker_validates():
    """A REPAIR verdict WITH a blocking assumption is allowed (only PASS forbids blockers)."""
    mapping = _sample_mapping(
        verdict="REPAIR",
        blocking_assumptions=[
            {
                "assumption": "source method assumes dense supervision",
                "why_blocking": "the target problem has only sparse labels",
            }
        ],
    )
    errors = _schema_errors(mapping)
    assert errors == [], f"REPAIR-with-blocker should be valid: {errors}"


def test_reject_verdict_validates():
    """A REJECT verdict is a valid, legitimate outcome (not an error)."""
    errors = _schema_errors(_sample_mapping(verdict="REJECT"))
    assert errors == []


# ==============================================================================
# mechanism_mapping schema — NEGATIVE (the structural guarantee)
# ==============================================================================

def test_pass_with_blocking_assumption_is_rejected():
    """THE structural guarantee: verdict:'PASS' WITH a non-empty blocking_assumptions is REJECTED
    by the schema's allOf/if-then (PASS requires blocking_assumptions maxItems 0). 'PASS with an
    unresolved blocker' must be impossible to even write."""
    bad = _sample_mapping(
        verdict="PASS",
        blocking_assumptions=[
            {
                "assumption": "source method assumes dense supervision",
                "why_blocking": "the target problem has only sparse labels",
            }
        ],
    )
    errors = _schema_errors(bad)
    assert errors, "schema MUST reject verdict:'PASS' while blocking_assumptions is non-empty"


def test_empty_shared_mechanisms_is_rejected():
    """shared_mechanisms has minItems 1 — a mapping with zero shared mechanisms is not an analogy."""
    bad = _sample_mapping(shared_mechanisms=[])
    assert _schema_errors(bad), "schema MUST reject an empty shared_mechanisms array"


def test_invalid_verdict_enum_is_rejected():
    """verdict must be one of PASS / REPAIR / REJECT."""
    assert _schema_errors(_sample_mapping(verdict="MAYBE"))


def test_overlap_score_out_of_range_is_rejected():
    """overlap_score must be in [0,1]."""
    assert _schema_errors(_sample_mapping(overlap_score=1.5))
    assert _schema_errors(_sample_mapping(overlap_score=-0.1))


def test_additional_property_is_rejected():
    """additionalProperties:false — an unknown top-level field is rejected."""
    assert _schema_errors(_sample_mapping(unexpected_field="nope"))


def test_missing_required_field_is_rejected():
    """Dropping a required field (e.g. mapping_id) is rejected."""
    bad = _sample_mapping()
    del bad["mapping_id"]
    assert _schema_errors(bad)


def test_blank_mapping_id_is_rejected():
    """mapping_id must be non-blank (pattern \\S)."""
    assert _schema_errors(_sample_mapping(mapping_id="   "))
