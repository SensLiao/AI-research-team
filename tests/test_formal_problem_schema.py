"""Tests for the formal-problem classifier (UPSTREAM mathematical-formalizer tool).

Proves, with REAL assertions (no mocks, no skips):
  - classify_form is deterministic (same primitive set -> same form) and order-independent.
  - EVERY formal_form branch is reachable from at least one primitive
    (graph / manifold / variational / dynamical / statistical / optimization) plus the
    "none" default for empty / unknown primitive sets.
  - Priority resolution: a set triggering several forms resolves to the lowest-priority-number form.
  - Unknown / empty primitives are handled (classify_form -> "none"; build rejects unknowns).
  - An assembled problem_abstraction VALIDATES against problem_abstraction.schema.json — the schema
    is loaded DIRECTLY with jsonschema (Draft202012Validator), NOT via PAYLOAD_SCHEMAS registration
    (the artifact_type is intentionally not registered yet — wiring is a later phase).

Schema-direct loading mirrors how validate_artifact._load_schema works, but without depending on
the registry, so this suite is correct before the type is wired into PAYLOAD_SCHEMAS.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.cross_domain_query import abstract_problem
from research_agent_teams.tools.formal_problem_schema import (
    FORMAL_FORMS,
    KNOWN_PRIMITIVES,
    build_problem_abstraction,
    classify_form,
    forms_for_primitive,
)

# --------------------------------------------------------------------------- schema (loaded direct)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas" / "problem_abstraction.schema.json"
)


def _load_schema() -> dict:
    """Load problem_abstraction.schema.json directly (no PAYLOAD_SCHEMAS dependency)."""
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _schema_errors(instance: dict) -> List[str]:
    """Return human-readable validation errors for instance against the schema (empty == valid)."""
    validator = Draft202012Validator(_load_schema())
    return [
        f"{err.message} (at {'/'.join(str(p) for p in err.path) or '<root>'})"
        for err in sorted(validator.iter_errors(instance), key=str)
    ]


# ============================================================================
# classify_form — determinism + order independence
# ============================================================================

def test_classify_form_deterministic_same_input_same_output():
    prims = ["thin_structure", "boundary_uncertainty"]
    assert classify_form(prims) == classify_form(prims)


def test_classify_form_order_independent():
    """Priority is fixed by the rule table, not by input order."""
    a = classify_form(["topology_preservation", "class_imbalance"])
    b = classify_form(["class_imbalance", "topology_preservation"])
    assert a == b == "graph"


def test_classify_form_accepts_any_iterable():
    """A set/tuple/list all classify identically (set() is taken internally)."""
    assert (
        classify_form({"graph_connectivity"})
        == classify_form(("graph_connectivity",))
        == classify_form(["graph_connectivity"])
        == "graph"
    )


# ============================================================================
# classify_form — EVERY branch reachable
# ============================================================================

@pytest.mark.parametrize(
    "primitive, expected_form",
    [
        ("graph_connectivity", "graph"),
        ("topology_preservation", "graph"),
        ("dynamical_stability", "dynamical"),
        ("long_range_dependency", "dynamical"),
        ("energy_minimization", "variational"),
        ("boundary_uncertainty", "variational"),
        ("anisotropic_geometry", "manifold"),
        ("multi_scale_structure", "manifold"),
        ("thin_structure", "manifold"),
        ("constraint_satisfaction", "optimization"),
        ("class_imbalance", "statistical"),
        ("noise_robustness", "statistical"),
        ("partial_observability", "statistical"),
    ],
)
def test_each_primitive_maps_to_expected_form(primitive: str, expected_form: str):
    """Every known primitive, alone, maps to its documented formal_form."""
    assert primitive in KNOWN_PRIMITIVES
    assert classify_form([primitive]) == expected_form


def test_all_non_none_forms_are_reachable():
    """The union of single-primitive classifications covers every form except 'none'."""
    reachable = {classify_form([p]) for p in KNOWN_PRIMITIVES}
    expected_non_none = set(FORMAL_FORMS) - {"none"}
    assert reachable == expected_non_none, (
        f"unreachable forms: {expected_non_none - reachable}; "
        f"unexpected: {reachable - expected_non_none}"
    )


def test_classify_form_returns_only_enum_values():
    """classify_form must only ever return a value in the closed FORMAL_FORMS enum."""
    for p in KNOWN_PRIMITIVES:
        assert classify_form([p]) in FORMAL_FORMS
    assert classify_form([]) in FORMAL_FORMS


# ============================================================================
# classify_form — priority resolution
# ============================================================================

def test_graph_beats_statistical():
    """graph (priority 1) wins over statistical (priority 6)."""
    assert classify_form(["class_imbalance", "graph_connectivity"]) == "graph"


def test_dynamical_beats_variational():
    """dynamical (priority 2) wins over variational (priority 3)."""
    assert classify_form(["boundary_uncertainty", "dynamical_stability"]) == "dynamical"


def test_variational_beats_manifold():
    """variational (priority 3) wins over manifold (priority 4)."""
    assert classify_form(["thin_structure", "energy_minimization"]) == "variational"


def test_manifold_beats_optimization():
    """manifold (priority 4) wins over optimization (priority 5)."""
    assert classify_form(["constraint_satisfaction", "anisotropic_geometry"]) == "manifold"


def test_optimization_beats_statistical():
    """optimization (priority 5) wins over statistical (priority 6)."""
    assert classify_form(["noise_robustness", "constraint_satisfaction"]) == "optimization"


def test_full_stack_resolves_to_graph():
    """A primitive set spanning all groups resolves to graph (priority 1)."""
    every = list(KNOWN_PRIMITIVES)
    assert classify_form(every) == "graph"


# ============================================================================
# classify_form — empty / unknown handling
# ============================================================================

def test_empty_primitives_is_none():
    assert classify_form([]) == "none"


def test_unknown_primitive_only_is_none():
    """A list of only-unknown tokens triggers no rule -> 'none' (classify_form does not raise)."""
    assert classify_form(["totally_made_up", "another_unknown"]) == "none"


def test_unknown_primitive_ignored_known_still_classifies():
    """An unknown token alongside a known one is ignored; the known one still classifies."""
    assert classify_form(["totally_made_up", "graph_connectivity"]) == "graph"


# ============================================================================
# forms_for_primitive — introspection helper
# ============================================================================

def test_forms_for_primitive_known():
    assert forms_for_primitive("graph_connectivity") == ["graph"]
    assert forms_for_primitive("thin_structure") == ["manifold"]


def test_forms_for_primitive_unknown_is_empty():
    assert forms_for_primitive("not_a_primitive") == []


# ============================================================================
# build_problem_abstraction — assembly + schema validation
# ============================================================================

def _good_problem() -> str:
    return "segment the inferior alveolar canal in CBCT scans under label scarcity"


def test_build_assembles_required_fields():
    pa = build_problem_abstraction(
        _good_problem(),
        ["thin_structure", "boundary_uncertainty"],
        problem_id="PA-001",
    )
    assert pa["problem_id"] == "PA-001"
    assert pa["domain_surface"] == _good_problem()
    assert pa["mechanism_primitives"] == ["thin_structure", "boundary_uncertainty"]
    # thin_structure -> manifold (pri 4), boundary_uncertainty -> variational (pri 3): variational wins
    assert pa["formal_form"] == "variational"
    assert pa["abstraction_confidence"] == 0.5
    assert pa["failure_modes"] == []
    assert pa["constraints"] == []
    assert pa["success_metrics"] == []


def test_build_reuses_abstract_problem_for_mechanism_phrase():
    """The notes default carries the abstract_problem() reduction — proving REUSE, not reimplement."""
    problem = _good_problem()
    pa = build_problem_abstraction(problem, ["thin_structure"], problem_id="PA-XYZ")
    assert abstract_problem(problem) in pa["notes"]


def test_build_validates_against_schema_minimal():
    """An assembled abstraction validates against problem_abstraction.schema.json (loaded direct)."""
    pa = build_problem_abstraction(
        _good_problem(),
        ["thin_structure", "topology_preservation"],
        problem_id="PA-002",
    )
    errors = _schema_errors(pa)
    assert errors == [], f"assembled problem_abstraction failed schema validation: {errors}"


def test_build_validates_against_schema_full():
    """A fully-populated abstraction (every optional list filled) validates."""
    pa = build_problem_abstraction(
        _good_problem(),
        ["graph_connectivity", "class_imbalance"],
        problem_id="PA-003",
        failure_modes=["over-segmentation of thin branches", "broken connectivity at junctions"],
        constraints=["<= 50 labeled volumes", "single-GPU memory budget"],
        success_metrics=["centerline Dice", "topological connectivity preservation"],
        abstraction_confidence=0.8,
        notes="canal is a graph-connectivity problem with severe foreground imbalance",
    )
    assert pa["formal_form"] == "graph"
    assert pa["abstraction_confidence"] == 0.8
    assert pa["notes"] == "canal is a graph-connectivity problem with severe foreground imbalance"
    errors = _schema_errors(pa)
    assert errors == [], f"full problem_abstraction failed schema validation: {errors}"


def test_build_empty_primitives_validates_with_none_form():
    """A problem with no reducible mechanism -> empty primitives, formal_form 'none', still valid."""
    pa = build_problem_abstraction(
        "do something underspecified",
        [],
        problem_id="PA-EMPTY",
    )
    assert pa["mechanism_primitives"] == []
    assert pa["formal_form"] == "none"
    assert _schema_errors(pa) == []


def test_build_deterministic():
    """Same inputs -> identical assembled dict (pure function)."""
    args = (_good_problem(), ["thin_structure", "boundary_uncertainty"])
    a = build_problem_abstraction(*args, problem_id="PA-D")
    b = build_problem_abstraction(*args, problem_id="PA-D")
    assert a == b


# ============================================================================
# build_problem_abstraction — input validation (rejects schema-invalid before it forms)
# ============================================================================

def test_build_rejects_unknown_primitive():
    """An unknown primitive must raise (the schema enum is closed) rather than emit invalid data."""
    with pytest.raises(ValueError, match="unknown mechanism primitive"):
        build_problem_abstraction(_good_problem(), ["not_a_real_primitive"], problem_id="PA-BAD")


def test_build_rejects_blank_problem():
    with pytest.raises(ValueError, match="non-empty problem"):
        build_problem_abstraction("   ", ["thin_structure"], problem_id="PA-1")


def test_build_rejects_blank_problem_id():
    with pytest.raises(ValueError, match="non-empty problem_id"):
        build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="  ")


def test_build_rejects_confidence_out_of_range_high():
    with pytest.raises(ValueError, match="abstraction_confidence"):
        build_problem_abstraction(
            _good_problem(), ["thin_structure"], problem_id="PA-1", abstraction_confidence=1.5
        )


def test_build_rejects_confidence_out_of_range_low():
    with pytest.raises(ValueError, match="abstraction_confidence"):
        build_problem_abstraction(
            _good_problem(), ["thin_structure"], problem_id="PA-1", abstraction_confidence=-0.1
        )


def test_build_boundary_confidence_zero_and_one_valid():
    lo = build_problem_abstraction(
        _good_problem(), ["thin_structure"], problem_id="PA-LO", abstraction_confidence=0.0
    )
    hi = build_problem_abstraction(
        _good_problem(), ["thin_structure"], problem_id="PA-HI", abstraction_confidence=1.0
    )
    assert _schema_errors(lo) == []
    assert _schema_errors(hi) == []


# ============================================================================
# schema closure — a hand-built invalid instance is rejected (guards the schema itself)
# ============================================================================

def test_schema_rejects_unknown_formal_form():
    pa = build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="PA-1")
    pa["formal_form"] = "quantum"  # not in enum
    assert _schema_errors(pa) != []


def test_schema_rejects_extra_top_level_field():
    pa = build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="PA-1")
    pa["verdict"] = "PASS"  # additionalProperties:false
    assert _schema_errors(pa) != []


def test_schema_rejects_blank_problem_id_field():
    pa = build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="PA-1")
    pa["problem_id"] = "   "  # pattern \\S
    assert _schema_errors(pa) != []


def test_schema_rejects_missing_required_field():
    pa = build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="PA-1")
    del pa["formal_form"]
    assert _schema_errors(pa) != []


def test_schema_rejects_out_of_enum_primitive():
    pa = build_problem_abstraction(_good_problem(), ["thin_structure"], problem_id="PA-1")
    pa["mechanism_primitives"] = ["thin_structure", "made_up_primitive"]
    assert _schema_errors(pa) != []
