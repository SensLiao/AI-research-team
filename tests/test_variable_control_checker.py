"""Real tests for the variable-control-auditor's deterministic core (the confound gate)."""
from __future__ import annotations

import copy

from research_agent_teams.tools.variable_control_checker import build_report, check_variable_control
from research_agent_teams.tools.validate_artifact import validate_against

# A clean single-variable study: only `adapter` changes between baseline and the treatment.
CLEAN = {
    "research_question": "Does a LoRA adapter beat full fine-tune at equal data/budget?",
    "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"], "frozen": ["backbone", "split"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft at equal budget"}],
    "leakage_declaration": "All inputs derive from training images only; test masks never read.",
}


def test_clean_single_variable_matrix_passes():
    violations, n = check_variable_control(CLEAN)
    assert violations == [] and n == 0
    assert build_report(CLEAN)["verdict"] == "PASS"


def test_two_variable_change_blocks():
    bad = copy.deepcopy(CLEAN)
    bad["conditions"][1]["factors"]["lr"] = 3e-4          # changes adapter AND lr -> confound
    violations, n = check_variable_control(bad)
    assert n == 1 and any("confounded" in v and "lr" in v for v in violations)
    assert build_report(bad)["verdict"] == "BLOCK"


def test_changing_a_frozen_param_blocks():
    bad = copy.deepcopy(CLEAN)
    bad["conditions"][1]["factors"]["backbone"] = "sam-vit-h"   # backbone is frozen
    violations, _ = check_variable_control(bad)
    assert any("frozen" in v and "backbone" in v for v in violations)
    assert build_report(bad)["verdict"] == "BLOCK"


def test_missing_baseline_blocks():
    bad = copy.deepcopy(CLEAN)
    for c in bad["conditions"]:
        c["baseline"] = False
    assert any("no baseline" in v for v in check_variable_control(bad)[0])
    assert build_report(bad)["verdict"] == "BLOCK"


def test_leakage_flag_forces_block():
    rep = build_report(CLEAN, leakage_flagged=True)
    assert rep["verdict"] == "BLOCK" and any("leakage" in v for v in rep["violations"])


def test_report_is_schema_valid_and_carries_invariants():
    profile = {"control_invariants": ["theta_frozen unchanged across conditions"]}
    rep = build_report(CLEAN, profile=profile)
    assert validate_against("variable_control_report.schema.json", rep) == []
    assert "theta_frozen unchanged across conditions" in rep["checked_invariants"]
