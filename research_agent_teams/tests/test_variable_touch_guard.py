"""Tests for the variable-touch-guard deterministic core (the EXECUTE ⛔ gate).

Constitution:
  - touching a STUDIED variable  → BLOCK
  - touching a FROZEN variable   → BLOCK
  - touching only CONTROLLED var → PASS
  - touching nothing             → PASS
  - multi-branch tree with one offending branch → BLOCK naming that branch

All verdicts are computed by the tool, then validated against the schema.
"""
from __future__ import annotations

import copy

import pytest

from research_agent_teams.tools.variable_touch_guard import (
    check_debug_session,
    check_experiment_tree,
    offenders,
)
from research_agent_teams.tools.validate_artifact import validate_against

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# A representative experiment_matrix variables block:
#   studied:    ["lr"]            ← the research question variable
#   controlled: ["batch_size"]    ← the explorable space
#   frozen:     ["backbone"]      ← the reproducibility lock
VARIABLES = {
    "studied": ["lr"],
    "controlled": ["batch_size"],
    "frozen": ["backbone"],
}

MATRIX = {
    "research_question": "Does lr affect convergence speed?",
    "variables": VARIABLES,
    "conditions": [
        {
            "id": "c0",
            "factors": {"lr": 1e-4, "batch_size": 32, "backbone": "resnet50"},
            "baseline": True,
        }
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c0", "hypothesis": "baseline"}],
    "leakage_declaration": "No leakage.",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session(touched: list[str]) -> dict:
    return {
        "session_id": "dbg-001",
        "failed_run_ref": "run-42",
        "proposed_patch": {"summary": "Fix shape mismatch in layer 3"},
        "touched_variables": touched,
        "evidence_ref": ["triage-report-run-42"],
    }


def _tree(branches_touched: list[list[str]]) -> dict:
    """Build a minimal experiment_tree with one branch per touched list."""
    branches = [
        {
            "branch_id": f"b{i}",
            "changed_factors": {},
            "touched_variables": tv,
            "depth": 1,
        }
        for i, tv in enumerate(branches_touched)
    ]
    return {
        "tree_id": "tree-001",
        "root_run_ref": "run-42",
        "branches": branches,
        "budget_bound": {"max_depth": 3, "max_width": 4},
        "evidence_ref": ["run-42"],
    }


# ---------------------------------------------------------------------------
# offenders()
# ---------------------------------------------------------------------------

class TestOffenders:
    def test_studied_variable_is_an_offender(self):
        result = offenders(["lr"], VARIABLES)
        assert result == ["lr"]

    def test_frozen_variable_is_an_offender(self):
        result = offenders(["backbone"], VARIABLES)
        assert result == ["backbone"]

    def test_controlled_variable_is_not_an_offender(self):
        result = offenders(["batch_size"], VARIABLES)
        assert result == []

    def test_empty_touched_returns_empty(self):
        result = offenders([], VARIABLES)
        assert result == []

    def test_mixed_returns_only_forbidden(self):
        result = offenders(["lr", "batch_size", "backbone"], VARIABLES)
        assert "batch_size" not in result
        assert "lr" in result
        assert "backbone" in result

    def test_result_is_sorted_stable(self):
        """Output order must be deterministic (sorted)."""
        r1 = offenders(["backbone", "lr"], VARIABLES)
        r2 = offenders(["lr", "backbone"], VARIABLES)
        assert r1 == r2 == sorted(r1)

    def test_unknown_variable_not_blocked(self):
        """A variable not declared in any category is not blocked."""
        result = offenders(["some_unknown_param"], VARIABLES)
        assert result == []


# ---------------------------------------------------------------------------
# check_debug_session()
# ---------------------------------------------------------------------------

class TestCheckDebugSession:
    def test_touching_studied_variable_is_blocked(self):
        out = check_debug_session(_session(["lr"]), MATRIX)
        assert out["verdict"] == "BLOCK"
        assert len(out["violations"]) >= 1
        assert any("lr" in v and "studied" in v for v in out["violations"])

    def test_touching_frozen_variable_is_blocked(self):
        out = check_debug_session(_session(["backbone"]), MATRIX)
        assert out["verdict"] == "BLOCK"
        assert any("backbone" in v and "frozen" in v for v in out["violations"])

    def test_touching_only_controlled_variable_passes(self):
        out = check_debug_session(_session(["batch_size"]), MATRIX)
        assert out["verdict"] == "PASS"
        assert out["violations"] == []

    def test_empty_touched_variables_passes(self):
        out = check_debug_session(_session([]), MATRIX)
        assert out["verdict"] == "PASS"
        assert out["violations"] == []

    def test_touching_studied_and_controlled_is_blocked(self):
        """Even one studied variable in the list forces BLOCK."""
        out = check_debug_session(_session(["batch_size", "lr"]), MATRIX)
        assert out["verdict"] == "BLOCK"

    def test_result_is_schema_valid(self):
        out = check_debug_session(_session(["batch_size"]), MATRIX)
        errors = validate_against("variable_touch_verdict.schema.json", out)
        assert errors == [], f"Schema errors: {errors}"

    def test_block_result_is_schema_valid(self):
        out = check_debug_session(_session(["lr"]), MATRIX)
        errors = validate_against("variable_touch_verdict.schema.json", out)
        assert errors == [], f"Schema errors: {errors}"

    def test_studied_list_copied_to_verdict(self):
        out = check_debug_session(_session([]), MATRIX)
        assert "lr" in out["studied"]

    def test_frozen_list_copied_to_verdict(self):
        out = check_debug_session(_session([]), MATRIX)
        assert "backbone" in out["frozen"]

    def test_deterministic_same_in_same_out(self):
        """Pure function: same inputs must produce identical outputs."""
        out1 = check_debug_session(_session(["lr"]), MATRIX)
        out2 = check_debug_session(_session(["lr"]), MATRIX)
        assert out1 == out2


# ---------------------------------------------------------------------------
# check_experiment_tree()
# ---------------------------------------------------------------------------

class TestCheckExperimentTree:
    def test_branch_touching_studied_blocks(self):
        out = check_experiment_tree(_tree([["lr"]]), MATRIX)
        assert out["verdict"] == "BLOCK"
        assert any("b0" in v and "lr" in v for v in out["violations"])

    def test_branch_touching_frozen_blocks(self):
        out = check_experiment_tree(_tree([["backbone"]]), MATRIX)
        assert out["verdict"] == "BLOCK"
        assert any("b0" in v and "backbone" in v for v in out["violations"])

    def test_branch_touching_only_controlled_passes(self):
        out = check_experiment_tree(_tree([["batch_size"]]), MATRIX)
        assert out["verdict"] == "PASS"
        assert out["violations"] == []

    def test_empty_touched_on_all_branches_passes(self):
        out = check_experiment_tree(_tree([[], []]), MATRIX)
        assert out["verdict"] == "PASS"
        assert out["violations"] == []

    def test_no_branches_passes(self):
        tree = _tree([])
        out = check_experiment_tree(tree, MATRIX)
        assert out["verdict"] == "PASS"
        assert out["violations"] == []

    def test_multi_branch_one_offender_blocks_and_names_branch(self):
        """Multi-branch tree: only b1 touches a studied variable; violation names b1."""
        out = check_experiment_tree(
            _tree([["batch_size"], ["lr"], ["batch_size"]]),
            MATRIX,
        )
        assert out["verdict"] == "BLOCK"
        # Exactly the offending branch is named
        assert any("b1" in v for v in out["violations"])
        # Clean branches do not generate violations
        assert not any("b0" in v for v in out["violations"])
        assert not any("b2" in v for v in out["violations"])

    def test_multi_branch_multiple_offenders_all_named(self):
        """When multiple branches offend, each is named in violations."""
        out = check_experiment_tree(
            _tree([["lr"], ["backbone"]]),
            MATRIX,
        )
        assert out["verdict"] == "BLOCK"
        assert any("b0" in v for v in out["violations"])
        assert any("b1" in v for v in out["violations"])

    def test_result_is_schema_valid_pass(self):
        out = check_experiment_tree(_tree([["batch_size"]]), MATRIX)
        errors = validate_against("variable_touch_verdict.schema.json", out)
        assert errors == [], f"Schema errors: {errors}"

    def test_result_is_schema_valid_block(self):
        out = check_experiment_tree(_tree([["lr"]]), MATRIX)
        errors = validate_against("variable_touch_verdict.schema.json", out)
        assert errors == [], f"Schema errors: {errors}"

    def test_deterministic_same_in_same_out(self):
        tree = _tree([["lr"], ["batch_size"]])
        out1 = check_experiment_tree(tree, MATRIX)
        out2 = check_experiment_tree(tree, MATRIX)
        assert out1 == out2

    def test_studied_and_frozen_lists_copied_to_verdict(self):
        out = check_experiment_tree(_tree([[]]), MATRIX)
        assert "lr" in out["studied"]
        assert "backbone" in out["frozen"]


# ---------------------------------------------------------------------------
# allOf constraint in schema: violations≥1 forces BLOCK
# ---------------------------------------------------------------------------

class TestAllOfConstraint:
    def test_violations_present_forces_block_in_schema(self):
        """The allOf in the schema must REJECT a payload with violations but verdict=PASS."""
        bad_payload = {
            "verdict": "PASS",    # wrong — violations is non-empty
            "violations": ["branch 'b0' touches studied variable 'lr'"],
        }
        errors = validate_against("variable_touch_verdict.schema.json", bad_payload)
        assert errors != [], "Schema should reject verdict=PASS when violations is non-empty"

    def test_no_violations_allows_pass_in_schema(self):
        good_payload = {
            "verdict": "PASS",
            "violations": [],
        }
        errors = validate_against("variable_touch_verdict.schema.json", good_payload)
        assert errors == [], f"Schema errors: {errors}"

    def test_violations_with_block_is_valid(self):
        good_payload = {
            "verdict": "BLOCK",
            "violations": ["debug_session touches studied variable 'lr'"],
        }
        errors = validate_against("variable_touch_verdict.schema.json", good_payload)
        assert errors == [], f"Schema errors: {errors}"
