"""M3-b integration: the variable-touch ⛔ gate, proven through the REGISTERED schema.

The constitution: an EXECUTE menu (auto-debugger / experiment-tree-explorer) may fix bugs
but NEVER touch a studied or frozen variable. This test proves the gate BITES on a realistic
bad input and that the resulting verdict validates through validate_payload (the registered path).
"""
from __future__ import annotations

from research_agent_teams.tools import variable_touch_guard
from research_agent_teams.tools.validate_artifact import validate_payload


def _matrix() -> dict:
    """A schema-valid experiment_matrix: lr is STUDIED, batch_size CONTROLLED, seed FROZEN."""
    m = {
        "research_question": "Does a higher learning rate improve segmentation Dice?",
        "variables": {
            "studied": ["lr"],
            "controlled": ["batch_size"],
            "frozen": ["seed"],
        },
        "conditions": [
            {"id": "c1", "factors": {"lr": 0.001}, "baseline": True},
            {"id": "c2", "factors": {"lr": 0.01}},
        ],
        "ranked_batch": [
            {"rank": 1, "condition_id": "c2", "hypothesis": "higher lr converges faster"},
        ],
        "leakage_declaration": "train/val/test are patient-disjoint; no test data touches training.",
    }
    assert validate_payload("experiment_matrix", m) == [], "fixture matrix must be schema-valid"
    return m


def test_debug_session_touching_studied_variable_is_blocked():
    matrix = _matrix()
    session = {
        "session_id": "dbg-1",
        "failed_run_ref": "run-007",
        "proposed_patch": {"summary": "raise the learning rate to escape the plateau"},
        "touched_variables": ["lr"],   # lr is STUDIED — forbidden
        "evidence_ref": ["triage_report:run-007"],
    }
    assert validate_payload("debug_session", session) == []
    verdict = variable_touch_guard.check_debug_session(session, matrix)
    assert verdict["verdict"] == "BLOCK"
    assert any("lr" in v for v in verdict["violations"])
    assert validate_payload("variable_touch_verdict", verdict) == []


def test_debug_session_touching_frozen_variable_is_blocked():
    matrix = _matrix()
    session = {
        "session_id": "dbg-2",
        "failed_run_ref": "run-008",
        "proposed_patch": {"summary": "reseed to dodge a bad initialisation"},
        "touched_variables": ["seed"],   # seed is FROZEN — forbidden
        "evidence_ref": ["triage_report:run-008"],
    }
    verdict = variable_touch_guard.check_debug_session(session, matrix)
    assert verdict["verdict"] == "BLOCK"
    assert validate_payload("variable_touch_verdict", verdict) == []


def test_debug_session_touching_only_controlled_variable_passes():
    matrix = _matrix()
    session = {
        "session_id": "dbg-3",
        "failed_run_ref": "run-009",
        "proposed_patch": {"summary": "shrink batch size to fit the GPU — a real OOM bug fix"},
        "touched_variables": ["batch_size"],   # controlled = explorable, allowed
        "evidence_ref": ["triage_report:run-009"],
    }
    verdict = variable_touch_guard.check_debug_session(session, matrix)
    assert verdict["verdict"] == "PASS"
    assert verdict["violations"] == []
    assert validate_payload("variable_touch_verdict", verdict) == []


def test_experiment_tree_branch_changing_studied_variable_is_blocked():
    matrix = _matrix()
    tree = {
        "tree_id": "tree-1",
        "root_run_ref": "run-010",
        "branches": [
            {"branch_id": "b1", "changed_factors": {"batch_size": 8}, "touched_variables": ["batch_size"], "depth": 1},
            {"branch_id": "b2", "changed_factors": {"lr": 0.05}, "touched_variables": ["lr"], "depth": 1},
        ],
        "budget_bound": {"max_depth": 2, "max_width": 3},
        "evidence_ref": ["experiment_matrix:em-1"],
    }
    assert validate_payload("experiment_tree", tree) == []
    verdict = variable_touch_guard.check_experiment_tree(tree, matrix)
    assert verdict["verdict"] == "BLOCK"
    assert any("b2" in v and "lr" in v for v in verdict["violations"]), verdict["violations"]
    assert validate_payload("variable_touch_verdict", verdict) == []


# --------------------------------------------------------------------------- #
#  M3-b adversarial-review fixes (paired proof tests)                          #
# --------------------------------------------------------------------------- #

def test_branch_hiding_studied_change_in_changed_factors_is_blocked():
    """B-1 (CRITICAL): a branch that changes the STUDIED variable via changed_factors but
    declares an EMPTY touched_variables must still BLOCK. The guard must not rely on the
    LLM-declared list alone — it reconciles touched_variables with changed_factors.keys()."""
    matrix = _matrix()
    tree = {
        "tree_id": "tree-evil",
        "root_run_ref": "run-011",
        "branches": [
            # changed_factors literally changes 'lr' (studied) but touched_variables hides it.
            {"branch_id": "sneaky", "changed_factors": {"lr": 0.05}, "touched_variables": [], "depth": 1},
        ],
        "budget_bound": {"max_depth": 2, "max_width": 3},
        "evidence_ref": ["experiment_matrix:em-1"],
    }
    assert validate_payload("experiment_tree", tree) == []
    verdict = variable_touch_guard.check_experiment_tree(tree, matrix)
    assert verdict["verdict"] == "BLOCK", "a hidden studied-variable change must not slip through"
    assert any("sneaky" in v and "lr" in v for v in verdict["violations"]), verdict["violations"]


def test_whitespace_padded_studied_variable_is_blocked():
    """B-2 (HIGH): a padded name ' lr ' must not dodge the gate (the \\S schema pattern is
    unanchored, so padding passes the schema — the tool normalizes before matching)."""
    matrix = _matrix()
    session = {
        "session_id": "dbg-pad",
        "failed_run_ref": "run-012",
        "proposed_patch": {"summary": "sneak the studied var past with a leading space"},
        "touched_variables": ["  lr "],
        "evidence_ref": ["triage_report:run-012"],
    }
    verdict = variable_touch_guard.check_debug_session(session, matrix)
    assert verdict["verdict"] == "BLOCK", "a whitespace-padded studied variable must be blocked"


def test_case_flipped_studied_variable_is_blocked():
    """B-2 (HIGH): a case flip 'LR' must not dodge a studied 'lr' (the gate errs toward BLOCK)."""
    matrix = _matrix()
    session = {
        "session_id": "dbg-case",
        "failed_run_ref": "run-013",
        "proposed_patch": {"summary": "sneak the studied var past with a case flip"},
        "touched_variables": ["LR"],
        "evidence_ref": ["triage_report:run-013"],
    }
    verdict = variable_touch_guard.check_debug_session(session, matrix)
    assert verdict["verdict"] == "BLOCK", "a case-flipped studied variable must be blocked"
