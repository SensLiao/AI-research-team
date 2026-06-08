"""Real tests for the protocol-compiler's deterministic core."""
from __future__ import annotations

import copy

from research_agent_teams.tools.protocol_compiler import compile_protocol
from research_agent_teams.tools.validate_artifact import validate_against

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MATRIX_2 = {
    "research_question": "Does LR schedule matter?",
    "variables": {
        "studied": ["lr_schedule"],
        "controlled": ["batch_size"],
        "frozen": ["architecture"],
    },
    "conditions": [
        {"id": "cond-A", "factors": {"lr_schedule": "cosine", "batch_size": 32}},
        {"id": "cond-B", "factors": {"lr_schedule": "step", "batch_size": 32}},
    ],
    "ranked_batch": [
        {"rank": 1, "condition_id": "cond-A", "hypothesis": "cosine is smoother"},
        {"rank": 2, "condition_id": "cond-B", "hypothesis": "step is baseline"},
    ],
    "leakage_declaration": "No leakage risk; all splits fixed before this run.",
}

SHARED = {"epochs": 50, "optimizer": "adam", "lr_schedule": "constant"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_two_conditions_produce_two_configs_with_correct_merge_and_schema():
    """(a) 2-condition matrix → 2 configs; factors WIN over shared; schema-valid."""
    payload = compile_protocol(MATRIX_2, from_matrix_ref="matrix-v1.json", shared=SHARED, seed=42)

    assert len(payload["configs"]) == 2

    # cond-A: lr_schedule should be "cosine" (factor overrides shared "constant")
    cfg_a = next(c for c in payload["configs"] if c["condition_id"] == "cond-A")
    assert cfg_a["config"]["lr_schedule"] == "cosine", "factor must override shared"
    assert cfg_a["config"]["epochs"] == 50, "shared key must be present when not overridden"
    assert cfg_a["config"]["batch_size"] == 32
    assert cfg_a["seed"] == 42

    # cond-B: lr_schedule should be "step"
    cfg_b = next(c for c in payload["configs"] if c["condition_id"] == "cond-B")
    assert cfg_b["config"]["lr_schedule"] == "step"
    assert cfg_b["seed"] == 42

    errors = validate_against("protocol_spec.schema.json", payload)
    assert errors == [], f"Schema validation failed: {errors}"


def test_from_matrix_ref_is_carried_through():
    """(b) from_matrix_ref in the return payload matches what was passed in."""
    ref = "runs/2026-experiment/matrix.artifact.json"
    payload = compile_protocol(MATRIX_2, from_matrix_ref=ref)
    assert payload["from_matrix_ref"] == ref


def test_shared_defaults_to_empty_dict_and_payload_is_schema_valid():
    """(c) shared omitted → shared={} in payload; still schema-valid."""
    payload = compile_protocol(MATRIX_2, from_matrix_ref="matrix-no-shared.json")

    assert payload["shared"] == {}
    # Each config contains only what the condition's factors supplied.
    cfg_a = next(c for c in payload["configs"] if c["condition_id"] == "cond-A")
    assert set(cfg_a["config"].keys()) == {"lr_schedule", "batch_size"}

    errors = validate_against("protocol_spec.schema.json", payload)
    assert errors == [], f"Schema validation failed: {errors}"


def test_input_matrix_and_shared_are_not_mutated():
    """(d) compile_protocol must not mutate its inputs."""
    matrix_before = copy.deepcopy(MATRIX_2)
    shared_before = copy.deepcopy(SHARED)

    compile_protocol(MATRIX_2, from_matrix_ref="ref", shared=SHARED, seed=7)

    assert MATRIX_2 == matrix_before, "matrix was mutated"
    assert SHARED == shared_before, "shared was mutated"
