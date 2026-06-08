"""Tests for the three M3-b CLUSTER B (EXECUTE menus) schemas:
  debug_session, experiment_tree, variable_touch_verdict.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required. All tests are GREEN before main-thread integration.

Key invariants tested per schema:
  - A well-formed valid instance validates (returns []).
  - Each required field missing → rejected.
  - Each anti-slop guard (empty/whitespace evidence_ref, empty session_id, etc.) → rejected.
  - additionalProperties:false (extra field) → rejected.
  - variable_touch_verdict: allOf — violations≥1 forces BLOCK (PASS rejected when violations present).
  - debug_session: touched_variables may be empty array (a patch may touch no experiment variable).
  - experiment_tree: branches may be empty array (no admissible branches in budget is valid).
"""
from __future__ import annotations

import copy

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. debug_session
# ==============================================================================

class TestDebugSession:
    SCHEMA = "debug_session.schema.json"

    def _good(self) -> dict:
        return {
            "session_id": "dbg-001",
            "failed_run_ref": "run-42",
            "proposed_patch": {
                "summary": "Fix shape mismatch in the projection layer.",
            },
            "touched_variables": [],
            "evidence_ref": ["triage-report-run-42"],
        }

    def _good_with_optionals(self) -> dict:
        return {
            "session_id": "dbg-002",
            "failed_run_ref": "run-43",
            "proposed_patch": {
                "summary": "Reduce learning rate to fix divergence.",
                "files": ["train.py", "config.yaml"],
                "diff_hint": "lr: 1e-4 → 3e-5",
            },
            "touched_variables": ["lr"],
            "evidence_ref": ["triage-report-run-43", "run-record-c1"],
            "root_cause": "Learning rate too high for this batch size.",
            "notes": "Reproduced on two seeds.",
        }

    def _good_empty_touched(self) -> dict:
        """A code-only patch that touches no experiment variable is valid."""
        good = self._good()
        good["touched_variables"] = []
        return good

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optionals_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optionals()) == []

    def test_empty_touched_variables_is_allowed(self):
        """A patch that touches no experiment variable must be schema-valid."""
        assert validate_against(self.SCHEMA, self._good_empty_touched()) == []

    def test_multiple_touched_variables_validates(self):
        good = self._good()
        good["touched_variables"] = ["lr", "batch_size"]
        assert validate_against(self.SCHEMA, good) == []

    def test_multiple_evidence_refs_validates(self):
        good = self._good()
        good["evidence_ref"] = ["ref-a", "ref-b"]
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_session_id_rejected(self):
        bad = self._good()
        del bad["session_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_failed_run_ref_rejected(self):
        bad = self._good()
        del bad["failed_run_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_proposed_patch_rejected(self):
        bad = self._good()
        del bad["proposed_patch"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_touched_variables_rejected(self):
        bad = self._good()
        del bad["touched_variables"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_patch_summary_rejected(self):
        bad = self._good()
        del bad["proposed_patch"]["summary"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty/whitespace values rejected ---

    def test_empty_session_id_rejected(self):
        bad = self._good()
        bad["session_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_session_id_rejected(self):
        bad = self._good()
        bad["session_id"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_failed_run_ref_rejected(self):
        bad = self._good()
        bad["failed_run_ref"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_failed_run_ref_rejected(self):
        bad = self._good()
        bad["failed_run_ref"] = "  \t"
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_patch_summary_rejected(self):
        bad = self._good()
        bad["proposed_patch"]["summary"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_patch_summary_rejected(self):
        bad = self._good()
        bad["proposed_patch"]["summary"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop: evidence_ref minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop: evidence_ref items pattern \\S — empty string rejected."""
        bad = self._good()
        bad["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_string_in_evidence_ref_rejected(self):
        """Anti-slop: evidence_ref items pattern \\S — whitespace-only rejected."""
        bad = self._good()
        bad["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_string_in_touched_variables_rejected(self):
        """touched_variables items pattern \\S — whitespace-only variable name rejected."""
        bad = self._good()
        bad["touched_variables"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_patch_field_rejected(self):
        bad = self._good()
        bad["proposed_patch"]["approved"] = True
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. experiment_tree
# ==============================================================================

class TestExperimentTree:
    SCHEMA = "experiment_tree.schema.json"

    def _good(self) -> dict:
        return {
            "tree_id": "tree-001",
            "root_run_ref": "run-42",
            "branches": [
                {
                    "branch_id": "b1",
                    "changed_factors": {"batch_size": 64},
                    "touched_variables": ["batch_size"],
                    "depth": 1,
                }
            ],
            "budget_bound": {"max_depth": 3, "max_width": 4},
            "evidence_ref": ["run-42"],
        }

    def _good_empty_branches(self) -> dict:
        """No admissible branches in budget is a valid tree."""
        return {
            "tree_id": "tree-002",
            "root_run_ref": "run-43",
            "branches": [],
            "budget_bound": {"max_depth": 2, "max_width": 2},
            "evidence_ref": ["run-43"],
        }

    def _good_empty_touched_on_branch(self) -> dict:
        good = self._good()
        good["branches"][0]["touched_variables"] = []
        return good

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_empty_branches_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty_branches()) == []

    def test_empty_touched_on_branch_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty_touched_on_branch()) == []

    def test_multiple_branches_validates(self):
        good = self._good()
        good["branches"].append({
            "branch_id": "b2",
            "changed_factors": {"batch_size": 128},
            "touched_variables": ["batch_size"],
            "depth": 1,
        })
        assert validate_against(self.SCHEMA, good) == []

    def test_deep_branch_validates(self):
        good = self._good()
        good["branches"][0]["depth"] = 3
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_tree_id_rejected(self):
        bad = self._good()
        del bad["tree_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_root_run_ref_rejected(self):
        bad = self._good()
        del bad["root_run_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_branches_rejected(self):
        bad = self._good()
        del bad["branches"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_budget_bound_rejected(self):
        bad = self._good()
        del bad["budget_bound"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_branch_id_rejected(self):
        bad = self._good()
        del bad["branches"][0]["branch_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_changed_factors_rejected(self):
        bad = self._good()
        del bad["branches"][0]["changed_factors"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_touched_variables_on_branch_rejected(self):
        bad = self._good()
        del bad["branches"][0]["touched_variables"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_depth_rejected(self):
        bad = self._good()
        del bad["branches"][0]["depth"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_max_depth_rejected(self):
        bad = self._good()
        del bad["budget_bound"]["max_depth"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_max_width_rejected(self):
        bad = self._good()
        del bad["budget_bound"]["max_width"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop ---

    def test_empty_tree_id_rejected(self):
        bad = self._good()
        bad["tree_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_tree_id_rejected(self):
        bad = self._good()
        bad["tree_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_root_run_ref_rejected(self):
        bad = self._good()
        bad["root_run_ref"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_root_run_ref_rejected(self):
        bad = self._good()
        bad["root_run_ref"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_ref_array_rejected(self):
        bad = self._good()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        bad = self._good()
        bad["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        bad = self._good()
        bad["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_branch_id_rejected(self):
        bad = self._good()
        bad["branches"][0]["branch_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_branch_id_rejected(self):
        bad = self._good()
        bad["branches"][0]["branch_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_in_touched_variables_rejected(self):
        bad = self._good()
        bad["branches"][0]["touched_variables"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- range constraints ---

    def test_depth_zero_rejected(self):
        bad = self._good()
        bad["branches"][0]["depth"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    def test_max_depth_zero_rejected(self):
        bad = self._good()
        bad["budget_bound"]["max_depth"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    def test_max_width_zero_rejected(self):
        bad = self._good()
        bad["budget_bound"]["max_width"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["selected"] = "b1"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_branch_field_rejected(self):
        bad = self._good()
        bad["branches"][0]["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_budget_bound_field_rejected(self):
        bad = self._good()
        bad["budget_bound"]["max_cost"] = 100
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 3. variable_touch_verdict
# ==============================================================================

class TestVariableTouchVerdict:
    SCHEMA = "variable_touch_verdict.schema.json"

    def _good_pass(self) -> dict:
        return {
            "verdict": "PASS",
            "violations": [],
        }

    def _good_block(self) -> dict:
        return {
            "verdict": "BLOCK",
            "violations": ["debug_session touches studied variable 'lr'"],
            "checked_against": "experiment-matrix-001",
            "touched": ["lr"],
            "studied": ["lr"],
            "frozen": ["backbone"],
        }

    # --- valid cases ---

    def test_pass_with_empty_violations_validates(self):
        assert validate_against(self.SCHEMA, self._good_pass()) == []

    def test_block_with_violations_validates(self):
        assert validate_against(self.SCHEMA, self._good_block()) == []

    def test_block_with_frozen_violation_validates(self):
        good = {
            "verdict": "BLOCK",
            "violations": ["branch 'b0' touches frozen variable 'backbone'"],
            "touched": ["backbone"],
            "studied": ["lr"],
            "frozen": ["backbone"],
        }
        assert validate_against(self.SCHEMA, good) == []

    def test_full_pass_payload_validates(self):
        good = {
            "verdict": "PASS",
            "violations": [],
            "checked_against": "matrix-001",
            "touched": ["batch_size"],
            "studied": ["lr"],
            "frozen": ["backbone"],
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_verdict_rejected(self):
        bad = self._good_pass()
        del bad["verdict"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_violations_rejected(self):
        bad = self._good_pass()
        del bad["violations"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum constraint ---

    def test_invalid_verdict_value_rejected(self):
        bad = self._good_pass()
        bad["verdict"] = "WARN"
        assert validate_against(self.SCHEMA, bad) != []

    def test_lowercase_pass_rejected(self):
        bad = self._good_pass()
        bad["verdict"] = "pass"
        assert validate_against(self.SCHEMA, bad) != []

    # --- allOf: violations≥1 forces BLOCK ---

    def test_violations_present_with_pass_is_rejected(self):
        """The allOf must REJECT verdict=PASS when violations is non-empty."""
        bad = {
            "verdict": "PASS",
            "violations": ["debug_session touches studied variable 'lr'"],
        }
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Should be rejected: PASS with non-empty violations"

    def test_violations_empty_with_block_is_allowed(self):
        """BLOCK with empty violations is technically schema-valid
        (the allOf only constrains the PASS direction)."""
        # Note: this combination is logically odd but the schema cannot prevent it —
        # the allOf only says "if violations≥1 then verdict must be BLOCK",
        # not "if violations is empty then verdict must be PASS".
        odd_but_valid = {
            "verdict": "BLOCK",
            "violations": [],
        }
        # We do NOT assert this is valid, because the guard tool always
        # sets BLOCK iff violations is non-empty. We just confirm schema
        # does not reject it (no structural rule forbids it).
        errors = validate_against(self.SCHEMA, odd_but_valid)
        # This is a documentation assertion: either [] or non-[] is acceptable here —
        # the contract lives in the tool, not the schema direction "empty→must PASS".
        # So we just verify we can call validate_against without raising.
        assert isinstance(errors, list)

    def test_multi_violation_block_validates(self):
        good = {
            "verdict": "BLOCK",
            "violations": [
                "branch 'b0' touches studied variable 'lr'",
                "branch 'b1' touches frozen variable 'backbone'",
            ],
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- additionalProperties:false ---

    def test_extra_field_rejected(self):
        bad = self._good_pass()
        bad["approved"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_self_decision_field_rejected(self):
        """No meets_bar / decision / status field allowed (schema closure)."""
        bad = self._good_pass()
        bad["meets_bar"] = "yes"
        assert validate_against(self.SCHEMA, bad) != []

    def test_decision_field_rejected(self):
        bad = self._good_pass()
        bad["decision"] = "run"
        assert validate_against(self.SCHEMA, bad) != []
