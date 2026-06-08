"""Real tests for the compliance-auditor deterministic core.

Verifies that check_compliance flags conditions declared but not run, and undeclared
run_records, and that a fully compliant experiment returns no violations.
The real-profile test loads cv-medical to ensure no false positive on a correct run.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.compliance_audit import (
    build_verdict,
    check_compliance,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _matrix(condition_ids: list) -> dict:
    return {
        "research_question": "Does method X improve over baseline?",
        "variables": {"studied": ["method"], "controlled": [], "frozen": []},
        "conditions": [{"id": cid, "factors": {}} for cid in condition_ids],
        "ranked_batch": [],
        "leakage_declaration": "No leakage.",
    }


def _run_records(condition_ids: list) -> list:
    return [
        {
            "condition_id": cid,
            "status": "provisional",
            "provenance": {"config_hash": f"cfg_{cid}"},
        }
        for cid in condition_ids
    ]


# --------------------------------------------------------------------------- #
#  Tests — happy path (fully compliant)                                        #
# --------------------------------------------------------------------------- #

def test_all_conditions_run_no_violations():
    matrix = _matrix(["baseline", "method_a", "method_b"])
    runs = _run_records(["baseline", "method_a", "method_b"])
    violations = check_compliance(matrix, runs)
    assert violations == [], f"Expected no violations; got: {violations}"


def test_build_verdict_pass_true_when_compliant():
    matrix = _matrix(["c1", "c2"])
    runs = _run_records(["c1", "c2"])
    verdict = build_verdict(matrix, runs)
    assert verdict["panel_role"] == "compliance"
    assert verdict["pass"] is True
    assert verdict["violations"] == []


# --------------------------------------------------------------------------- #
#  Tests — crafted-bad: declared condition not run                             #
# --------------------------------------------------------------------------- #

def test_missing_run_condition_is_flagged():
    """4 declared / 3 run → compliance pass=false (the golden test for compliance)."""
    matrix = _matrix(["baseline", "method_a", "method_b", "method_c"])
    runs = _run_records(["baseline", "method_a", "method_b"])  # method_c not run
    violations = check_compliance(matrix, runs)
    assert len(violations) >= 1, "Missing run for method_c should produce a violation"
    assert any("method_c" in v for v in violations), (
        f"Violation should mention 'method_c'; got: {violations}"
    )


def test_build_verdict_pass_false_when_condition_missing():
    matrix = _matrix(["baseline", "method_a", "method_b", "method_c"])
    runs = _run_records(["baseline", "method_a", "method_b"])
    verdict = build_verdict(matrix, runs)
    assert verdict["pass"] is False
    assert len(verdict["violations"]) >= 1


def test_multiple_missing_conditions_flagged():
    matrix = _matrix(["c1", "c2", "c3", "c4"])
    runs = _run_records(["c1"])
    violations = check_compliance(matrix, runs)
    missing_in_violations = [v for v in violations if "declared" in v and "not" in v]
    assert len(missing_in_violations) >= 3, (
        f"Expected 3 missing-condition violations; got: {violations}"
    )


# --------------------------------------------------------------------------- #
#  Tests — crafted-bad: undeclared run_record                                  #
# --------------------------------------------------------------------------- #

def test_undeclared_run_is_flagged():
    """A run_record for a condition not in the experiment_matrix is flagged."""
    matrix = _matrix(["baseline", "method_a"])
    runs = _run_records(["baseline", "method_a", "ghost_run"])  # ghost_run not declared
    violations = check_compliance(matrix, runs)
    assert any("ghost_run" in v for v in violations), (
        f"Undeclared run 'ghost_run' should be flagged; got: {violations}"
    )


# --------------------------------------------------------------------------- #
#  Tests — edge cases                                                          #
# --------------------------------------------------------------------------- #

def test_empty_conditions_no_violation():
    """No declared conditions → nothing to check → no violations."""
    matrix = _matrix([])
    runs = _run_records(["something"])
    violations = check_compliance(matrix, runs)
    assert violations == []


def test_empty_runs_with_declared_conditions_flags():
    matrix = _matrix(["c1", "c2"])
    runs = []
    violations = check_compliance(matrix, runs)
    assert len(violations) >= 2  # both c1 and c2 unrun


# --------------------------------------------------------------------------- #
#  Real-profile test                                                           #
# --------------------------------------------------------------------------- #

def test_real_profile_fully_compliant_passes():
    """Load the real cv-medical profile; 3 conditions all with run_records should pass."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    condition_ids = ["unet3d_baseline", "sammed3d_finetune", "sammed3d_zero_shot"]
    matrix = _matrix(condition_ids)
    runs = _run_records(condition_ids)
    verdict = build_verdict(matrix, runs, profile)
    assert verdict["pass"] is True, (
        f"Fully compliant experiment under real profile should pass; got: {verdict}"
    )


def test_real_profile_missing_condition_fires():
    """Real profile: 3 declared, 2 run → compliance fail."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    matrix = _matrix(["unet3d_baseline", "sammed3d_finetune", "sammed3d_zero_shot"])
    runs = _run_records(["unet3d_baseline", "sammed3d_finetune"])  # missing sammed3d_zero_shot
    verdict = build_verdict(matrix, runs, profile)
    assert verdict["pass"] is False, (
        "Missing condition 'sammed3d_zero_shot' must cause compliance fail under real profile"
    )
    assert any("sammed3d_zero_shot" in v for v in verdict["violations"]), (
        f"Violation should name 'sammed3d_zero_shot'; got: {verdict['violations']}"
    )
