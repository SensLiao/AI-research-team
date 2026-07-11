"""Real tests for the train-test-alignment-auditor's deterministic core (the '对齐人')."""
from __future__ import annotations

import copy

from research_agent_teams.tools.alignment_checker import build_report, check_alignment
from research_agent_teams.tools.validate_artifact import validate_against

TRAIN = {
    "preprocessing": {"spacing": [1, 1, 1], "normalize": "zscore"},
    "augmentation": {"enabled": True, "ops": ["flip", "rotate"]},
    "pretrained": "none",
    "precision": "fp32",
    "inference": {"threshold": 0.5},
    "label_space": ["bg", "vessel"],
}
TEST = {
    "preprocessing": {"spacing": [1, 1, 1], "normalize": "zscore"},
    "augmentation": {"enabled": False},
    "pretrained": "none",
    "precision": "fp32",
    "inference": {"threshold": 0.5},
    "label_space": ["bg", "vessel"],
}


def test_aligned_pipelines_pass():
    assert check_alignment(TRAIN, TEST) == []
    assert build_report(TRAIN, TEST)["verdict"] == "PASS"


def test_preprocessing_mismatch_blocks():
    bad = copy.deepcopy(TEST)
    bad["preprocessing"]["spacing"] = [2, 2, 2]
    assert any("preprocessing mismatch" in v for v in check_alignment(TRAIN, bad))
    assert build_report(TRAIN, bad)["verdict"] == "BLOCK"


def test_eval_augmentation_blocks():
    bad = copy.deepcopy(TEST)
    bad["augmentation"] = {"enabled": True, "ops": ["flip"]}
    assert any("augmentation must be disabled" in v for v in check_alignment(TRAIN, bad))


def test_precision_mismatch_blocks():
    bad = copy.deepcopy(TEST)
    bad["precision"] = "fp16"
    assert any("precision mismatch" in v for v in check_alignment(TRAIN, bad))


def test_undeclared_pretraining_blocks():
    bad_train = copy.deepcopy(TRAIN)
    del bad_train["pretrained"]
    assert any("pretrained" in v for v in check_alignment(bad_train, TEST))


def test_missing_eval_inference_blocks():
    bad = copy.deepcopy(TEST)
    del bad["inference"]
    assert any("inference" in v for v in check_alignment(TRAIN, bad))


def test_report_is_schema_valid_and_carries_profile_invariants():
    profile = {"alignment_invariants": ["train_spacing == test_spacing", "test augmentation disabled"]}
    report = build_report(TRAIN, TEST, profile=profile, train_ref="run-1", test_ref="run-1")
    assert validate_against("alignment_report.schema.json", report) == []
    assert "train_spacing == test_spacing" in report["checked_invariants"]
