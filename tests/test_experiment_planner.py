"""Real tests for the experiment-planner's deterministic core (the design assembler)."""
from __future__ import annotations

import copy

import pytest

from research_agent_teams.tools.experiment_planner import build_matrix
from research_agent_teams.tools.validate_artifact import validate_against

# ---------------------------------------------------------------------------
# Minimal valid fixture — 2 conditions, 1 baseline, ranks [1, 2]
# ---------------------------------------------------------------------------
VARIABLES = {
    "studied": ["adapter"],
    "controlled": ["lr", "epochs"],
    "frozen": ["backbone", "split"],
}

CONDITIONS = [
    {
        "id": "c0",
        "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50},
        "baseline": True,
    },
    {
        "id": "c1",
        "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50},
    },
]

RANKED_BATCH = [
    {
        "rank": 1,
        "condition_id": "c0",
        "hypothesis": "Full fine-tune is the baseline reference point.",
        "cost_gpu_hours": 8.0,
    },
    {
        "rank": 2,
        "condition_id": "c1",
        "hypothesis": "LoRA matches full fine-tune at a fraction of the GPU cost.",
        "cost_gpu_hours": 2.0,
    },
]

LEAKAGE = "All inputs derive from training images only; test masks are never read during design."

QUESTION = "Does a LoRA adapter match full fine-tuning quality at equal data budget?"


# ---------------------------------------------------------------------------
# (a) Valid matrix validates against schema
# ---------------------------------------------------------------------------

def test_valid_matrix_passes_schema_validation():
    payload = build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, LEAKAGE)
    errors = validate_against("experiment_matrix.schema.json", payload)
    assert errors == [], f"Schema errors: {errors}"


def test_valid_matrix_single_rank_passes():
    """Single-condition baseline with ranks [1] is the minimum valid design."""
    single_condition = [copy.deepcopy(CONDITIONS[0])]  # only baseline
    single_batch = [
        {
            "rank": 1,
            "condition_id": "c0",
            "hypothesis": "Baseline run establishes the reference metric.",
        }
    ]
    payload = build_matrix(QUESTION, VARIABLES, single_condition, single_batch, LEAKAGE)
    errors = validate_against("experiment_matrix.schema.json", payload)
    assert errors == []
    assert payload["research_question"] == QUESTION
    assert payload["leakage_declaration"] == LEAKAGE


# ---------------------------------------------------------------------------
# (b) Zero baselines raises ValueError
# ---------------------------------------------------------------------------

def test_zero_baselines_raises():
    no_baseline_conditions = [
        {"id": "c0", "factors": {"adapter": "none"}},
        {"id": "c1", "factors": {"adapter": "lora"}},
    ]
    with pytest.raises(ValueError, match="exactly one baseline"):
        build_matrix(QUESTION, VARIABLES, no_baseline_conditions, RANKED_BATCH, LEAKAGE)


# ---------------------------------------------------------------------------
# (c) Two baselines raises ValueError
# ---------------------------------------------------------------------------

def test_two_baselines_raises():
    two_baseline_conditions = [
        {"id": "c0", "factors": {"adapter": "none"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora"}, "baseline": True},
    ]
    with pytest.raises(ValueError, match="exactly one baseline"):
        build_matrix(QUESTION, VARIABLES, two_baseline_conditions, RANKED_BATCH, LEAKAGE)


# ---------------------------------------------------------------------------
# (d) Non-contiguous ranks raise ValueError
# ---------------------------------------------------------------------------

def test_non_contiguous_ranks_raises():
    bad_batch = [
        {"rank": 1, "condition_id": "c0", "hypothesis": "h1"},
        {"rank": 3, "condition_id": "c1", "hypothesis": "h2"},  # gap: missing rank 2
    ]
    with pytest.raises(ValueError, match="contiguous set"):
        build_matrix(QUESTION, VARIABLES, CONDITIONS, bad_batch, LEAKAGE)


def test_duplicate_ranks_raises():
    bad_batch = [
        {"rank": 1, "condition_id": "c0", "hypothesis": "h1"},
        {"rank": 1, "condition_id": "c1", "hypothesis": "h2"},  # duplicate rank 1
    ]
    with pytest.raises(ValueError, match="contiguous set"):
        build_matrix(QUESTION, VARIABLES, CONDITIONS, bad_batch, LEAKAGE)


# ---------------------------------------------------------------------------
# (e) Empty leakage_declaration raises ValueError
# ---------------------------------------------------------------------------

def test_empty_leakage_declaration_raises():
    with pytest.raises(ValueError, match="leakage_declaration must be non-empty"):
        build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, "")


def test_whitespace_only_leakage_declaration_raises():
    with pytest.raises(ValueError, match="leakage_declaration must be non-empty"):
        build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, "   ")


# ---------------------------------------------------------------------------
# Structural checks — output fields and no schema-forbidden extra fields
# ---------------------------------------------------------------------------

def test_payload_structure_has_required_fields():
    payload = build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, LEAKAGE)
    assert set(payload.keys()) == {
        "research_question",
        "variables",
        "conditions",
        "ranked_batch",
        "leakage_declaration",
    }
    assert set(payload["variables"].keys()) == {"studied", "controlled", "frozen"}


def test_payload_conditions_carry_only_schema_fields():
    payload = build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, LEAKAGE)
    allowed = {"id", "factors", "baseline"}
    for cond in payload["conditions"]:
        assert set(cond.keys()) <= allowed


def test_ranked_batch_entries_carry_only_schema_fields():
    payload = build_matrix(QUESTION, VARIABLES, CONDITIONS, RANKED_BATCH, LEAKAGE)
    allowed = {"rank", "condition_id", "hypothesis", "cost_gpu_hours", "expected_signal"}
    for entry in payload["ranked_batch"]:
        assert set(entry.keys()) <= allowed
