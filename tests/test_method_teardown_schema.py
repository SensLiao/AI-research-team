"""Schema validate/reject tests for method_teardown.schema.json (P1, paper-reading upgrade).

Uses validate_against(schema_filename, instance) which validates directly against
a schema file — no PAYLOAD_SCHEMAS registration needed (green before the lead's
registry step).

Covers: (a) a valid full instance accepts, (b) a missing-required instance rejects,
(c) an unknown-property instance rejects (proves additionalProperties:false).
"""
from __future__ import annotations

from research_agent_teams.tools.validate_artifact import validate_against


# ===========================================================================
# method_teardown.schema.json — required [source_ref]
# ===========================================================================

_GOOD_METHOD_TEARDOWN = {
    "source_ref": "arxiv:2409.00001",
    "problem_definition": "Input: 3D CBCT volume. Output: per-voxel IAC mask. Task: thin-tubular segmentation.",
    "core_assumptions": [
        "The canal is a single connected tube per side.",
        "Training and test scanners share intensity statistics.",
    ],
    "representation": "Replaces voxel-wise BCE objective with a topology-aware loss over a tubular prior.",
    "loss_terms": [
        {
            "term": "Dice",
            "role": "region overlap",
            "ablate_effect": "Removing it collapses recall on small structures.",
        },
        {
            "term": "L_topo",
            "role": "enforce single connected component",
            "ablate_effect": "Removing it reintroduces broken-tube artifacts.",
        },
    ],
    "training_flow": "Two-stage: pretrain encoder frozen, then fine-tune decoder with combined loss.",
    "inference_flow": "Single forward pass + connected-component post-processing.",
    "train_infer_consistency": "Matched — same patch size and normalization at train and inference.",
    "data": "ToothFairy3, 443 cases, patient-level 70/30 split; low leakage risk.",
    "cost": "1 A100-day to train; sub-second inference per volume.",
    "baseline_difference": "The only change vs nnU-Net is the added topology loss term.",
}


def test_method_teardown_valid():
    assert validate_against("method_teardown.schema.json", _GOOD_METHOD_TEARDOWN) == []


def test_method_teardown_minimal_valid():
    """Only source_ref is required — a minimal instance is valid."""
    good = {"source_ref": "arxiv:2409.00001"}
    assert validate_against("method_teardown.schema.json", good) == []


def test_method_teardown_missing_source_ref_rejected():
    bad = {"problem_definition": "Some problem, but no source_ref."}
    assert validate_against("method_teardown.schema.json", bad) != []


def test_method_teardown_empty_source_ref_rejected():
    """Empty source_ref (minLength 1) is rejected."""
    bad = {"source_ref": ""}
    assert validate_against("method_teardown.schema.json", bad) != []


def test_method_teardown_unknown_property_rejected():
    """additionalProperties:false — an unknown top-level key is rejected."""
    bad = {"source_ref": "arxiv:2409.00001", "not_a_real_field": "leak"}
    assert validate_against("method_teardown.schema.json", bad) != []


def test_method_teardown_loss_term_missing_term_rejected():
    """Each loss_terms entry requires `term`."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "loss_terms": [{"role": "region overlap", "ablate_effect": "drops recall"}],
    }
    assert validate_against("method_teardown.schema.json", bad) != []


def test_method_teardown_loss_term_unknown_property_rejected():
    """Each loss_terms entry is additionalProperties:false."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "loss_terms": [{"term": "Dice", "weight": 1.0}],
    }
    assert validate_against("method_teardown.schema.json", bad) != []
