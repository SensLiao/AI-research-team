"""Tests for the model-dataset-scout's deterministic core."""
from __future__ import annotations

import copy

from research_agent_teams.tools.model_dataset_scout import build_candidates
from research_agent_teams.tools.validate_artifact import validate_against

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MODEL_A = {
    "kind": "model",
    "name": "SegResNet",
    "ref": "https://arxiv.org/abs/2004.10664",
    "modality": "3D MRI",
    "license": "Apache-2.0",
    "fit_notes": "Strong baseline for volumetric segmentation tasks.",
}

MODEL_B = {
    "kind": "model",
    "name": "SwinUNETR",
    "ref": "https://arxiv.org/abs/2201.01266",
    "modality": "3D CT/MRI",
    "license": "Apache-2.0",
    "fit_notes": "Transformer-based; good for large-scale datasets.",
}

DATASET_A = {
    "kind": "dataset",
    "name": "MSD Task09 Spleen",
    "ref": "http://medicaldecathlon.com/",
    "modality": "CT",
    "license": "CC-BY-SA 4.0",
    "fit_notes": "Single-organ; clean labels; widely used for benchmarking.",
}

DATASET_B = {
    "kind": "dataset",
    "name": "ToothFairy2",
    "ref": "https://toothfairy2.grand-challenge.org/",
    "modality": "CBCT",
    "license": "non-commercial research",
    "fit_notes": "Multi-class tooth + alveolar nerve; fits dental domain profile.",
}

SCHEMA = "model_dataset_candidates.schema.json"
TASK = "3D medical image segmentation — tooth and alveolar nerve"


# ---------------------------------------------------------------------------
# Test (a): mixed list → counts correct AND schema-valid
# ---------------------------------------------------------------------------

def test_mixed_list_counts_and_schema_valid() -> None:
    candidates = [MODEL_A, MODEL_B, DATASET_A, DATASET_B]
    payload = build_candidates(TASK, candidates)

    assert payload["n_models"] == 2
    assert payload["n_datasets"] == 2
    assert payload["task"] == TASK

    errors = validate_against(SCHEMA, payload)
    assert errors == [], f"Schema validation failed: {errors}"


# ---------------------------------------------------------------------------
# Test (b): empty list → schema-valid with counts 0
# ---------------------------------------------------------------------------

def test_empty_list_schema_valid_zero_counts() -> None:
    payload = build_candidates(TASK, [])

    assert payload["n_models"] == 0
    assert payload["n_datasets"] == 0
    assert payload["candidates"] == []

    errors = validate_against(SCHEMA, payload)
    assert errors == [], f"Schema validation failed: {errors}"


# ---------------------------------------------------------------------------
# Test (c): all-models case → n_datasets == 0
# ---------------------------------------------------------------------------

def test_all_models_case() -> None:
    candidates = [MODEL_A, MODEL_B]
    payload = build_candidates(TASK, candidates)

    assert payload["n_models"] == 2
    assert payload["n_datasets"] == 0

    errors = validate_against(SCHEMA, payload)
    assert errors == [], f"Schema validation failed: {errors}"


# ---------------------------------------------------------------------------
# Test (d): candidates passed through unmutated
# ---------------------------------------------------------------------------

def test_candidates_passed_through_unmutated() -> None:
    original = [copy.deepcopy(MODEL_A), copy.deepcopy(DATASET_A)]
    snapshot = copy.deepcopy(original)

    payload = build_candidates(TASK, original)

    # The returned list must equal the originals element-by-element
    assert payload["candidates"] == snapshot

    # The original list objects must not have been modified
    assert original == snapshot

    # The returned candidates list must be a new list object (not the same reference)
    assert payload["candidates"] is not original
