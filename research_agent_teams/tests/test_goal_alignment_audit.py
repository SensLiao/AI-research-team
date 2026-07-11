"""Regression tests for the goal-alignment-checker deterministic core (goal_alignment_audit.py).

H2: Every test has a clear before/after narrative: before this helper existed the
goal-alignment-checker gate had no deterministic backing (pass-emitting prose only).
Now it bites on crafted-bad inputs shaped like real experiment_matrix structures.

Test structure:
  - flagged generalization case: RQ contains "generalization" but no OOD condition → violation
  - flagged SOTA case: RQ contains "beats state-of-the-art" but no baseline condition → violation
  - clean case: RQ with generalization claim AND an external/held-out condition → pass
  - clean SOTA case: RQ with SOTA claim AND a baseline-flagged condition → pass
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.goal_alignment_audit import (
    _has_baseline_condition,
    build_verdict,
    check_goal_alignment,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_RESULT_SUMMARY_INDISTR = {
    "findings": [
        {"condition_id": "method_sam_train_dist", "metric": "Dice", "value": 0.85},
        {"condition_id": "baseline_unet_train_dist", "metric": "Dice", "value": 0.80},
    ]
}

_RESULT_SUMMARY_WITH_OOD = {
    "findings": [
        {"condition_id": "method_sam_train_dist", "metric": "Dice", "value": 0.85},
        {"condition_id": "method_sam_external_test", "metric": "Dice", "value": 0.78},
    ]
}

_MATRIX_GENERALIZATION_CLAIM_NO_OOD = {
    "research_question": (
        "Does SAM-Med generalize to unseen hospitals? "
        "We evaluate generalization across site-level domain shift."
    ),
    "conditions": [
        {"id": "baseline_unet", "factors": {"data_hash": "abc", "baseline": True}},
        {"id": "method_sam", "factors": {"data_hash": "abc", "baseline": False}},
    ],
}

_MATRIX_GENERALIZATION_CLAIM_WITH_EXTERNAL = {
    "research_question": "Does SAM-Med generalize to unseen hospitals?",
    "conditions": [
        {"id": "baseline_unet", "factors": {"baseline": True}},
        {"id": "method_sam_external_holdout", "factors": {"baseline": False}},
    ],
}

_MATRIX_SOTA_CLAIM_NO_BASELINE = {
    "research_question": "Our method beats state-of-the-art in 3D cardiac segmentation.",
    "conditions": [
        {"id": "method_sam", "factors": {"data_hash": "abc", "baseline": False}},
    ],
}

_MATRIX_SOTA_CLAIM_WITH_BASELINE = {
    "research_question": "Our method outperforms the current state-of-the-art.",
    "conditions": [
        {"id": "baseline_unet3d", "factors": {"data_hash": "abc", "baseline": True}},
        {"id": "method_sam", "factors": {"data_hash": "abc", "baseline": False}},
    ],
}

_MATRIX_NO_SPECIAL_CLAIM = {
    "research_question": "How does SAM-Med perform on liver segmentation?",
    "conditions": [
        {"id": "method_sam", "factors": {"baseline": False}},
    ],
}


# --------------------------------------------------------------------------- #
#  Flagged cases — gate must BITE                                              #
# --------------------------------------------------------------------------- #

def test_h2_generalization_claim_no_ood_flagged():
    """H2 FLAGGED: RQ mentions 'generalization' but no OOD/external condition → violation.

    Before this helper existed: goal-alignment-checker emitted pass by default (prose only).
    After: check_goal_alignment deterministically flags this case.
    """
    violations = check_goal_alignment(
        _MATRIX_GENERALIZATION_CLAIM_NO_OOD,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert len(violations) >= 1, (
        "RQ contains 'generalization' but no OOD condition exists — "
        "must produce at least 1 violation. "
        f"Got violations: {violations}"
    )
    violation_text = " ".join(violations).lower()
    assert "generaliz" in violation_text or "ood" in violation_text or "external" in violation_text, (
        f"Violation must mention generalization/OOD; got: {violations}"
    )


def test_h2_build_verdict_generalization_no_ood_pass_false():
    """H2 FLAGGED: build_verdict with generalization claim and no OOD must produce pass=False."""
    verdict = build_verdict(
        _MATRIX_GENERALIZATION_CLAIM_NO_OOD,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert verdict["panel_role"] == "goal_alignment"
    assert verdict["pass"] is False, (
        f"build_verdict must return pass=False for generalization-no-OOD; got pass={verdict['pass']}"
    )
    assert len(verdict["violations"]) >= 1


def test_h2_sota_claim_no_baseline_flagged():
    """H2 FLAGGED: RQ says 'beats state-of-the-art' but no baseline condition → violation."""
    violations = check_goal_alignment(
        _MATRIX_SOTA_CLAIM_NO_BASELINE,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert len(violations) >= 1, (
        "RQ mentions 'state-of-the-art' / 'beats' but no baseline condition exists — "
        f"must produce at least 1 violation. Got: {violations}"
    )
    violation_text = " ".join(violations).lower()
    assert "sota" in violation_text or "baseline" in violation_text or "state-of-the-art" in violation_text, (
        f"Violation must mention SOTA/baseline; got: {violations}"
    )


def test_h2_build_verdict_sota_no_baseline_pass_false():
    """H2: build_verdict SOTA-no-baseline → pass=False."""
    verdict = build_verdict(
        _MATRIX_SOTA_CLAIM_NO_BASELINE,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert verdict["pass"] is False
    assert len(verdict["violations"]) >= 1


def test_h2_out_of_distribution_keyword_flagged():
    """H2 FLAGGED: RQ uses literal 'out-of-distribution' keyword with no OOD condition."""
    matrix = {
        "research_question": "Evaluate out-of-distribution robustness of our method.",
        "conditions": [
            {"id": "method_a", "factors": {"baseline": False}},
        ],
    }
    violations = check_goal_alignment(matrix, _RESULT_SUMMARY_INDISTR, profile=None)
    assert any("generaliz" in v.lower() or "ood" in v.lower() or "external" in v.lower()
               or "out-of-distribution" in v.lower() for v in violations), (
        f"'out-of-distribution' in RQ without OOD condition must flag; got: {violations}"
    )


def test_h2_outperforms_keyword_flagged():
    """H2 FLAGGED: RQ uses 'outperforms' with no baseline condition → violation."""
    matrix = {
        "research_question": "Our method outperforms existing approaches.",
        "conditions": [
            {"id": "method_only", "factors": {"baseline": False}},
        ],
    }
    violations = check_goal_alignment(matrix, _RESULT_SUMMARY_INDISTR, profile=None)
    assert len(violations) >= 1, (
        f"'outperforms' in RQ without baseline must flag; got: {violations}"
    )


# --------------------------------------------------------------------------- #
#  Clean cases — no false positives                                            #
# --------------------------------------------------------------------------- #

def test_h2_generalization_claim_with_external_condition_clean():
    """H2 CLEAN: RQ claims generalization AND an external/held-out condition exists → no violation."""
    violations = check_goal_alignment(
        _MATRIX_GENERALIZATION_CLAIM_WITH_EXTERNAL,
        _RESULT_SUMMARY_WITH_OOD,
        profile=None,
    )
    ood_violations = [
        v for v in violations
        if "generaliz" in v.lower() or "ood" in v.lower()
    ]
    assert ood_violations == [], (
        f"Generalization claim with external condition present must NOT produce OOD violation; "
        f"got: {violations}"
    )


def test_h2_sota_claim_with_baseline_condition_clean():
    """H2 CLEAN: RQ claims outperforms AND a baseline condition exists → no SOTA violation."""
    violations = check_goal_alignment(
        _MATRIX_SOTA_CLAIM_WITH_BASELINE,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    sota_violations = [v for v in violations if "sota" in v.lower() or "baseline" in v.lower()]
    assert sota_violations == [], (
        f"SOTA claim with baseline condition must NOT produce a violation; got: {violations}"
    )


def test_h2_no_special_claim_no_violations():
    """H2 CLEAN: RQ with no generalization/SOTA keywords → no violations."""
    violations = check_goal_alignment(
        _MATRIX_NO_SPECIAL_CLAIM,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert violations == [], (
        f"RQ with no special claim keywords must produce no violations; got: {violations}"
    )


def test_h2_build_verdict_no_claim_pass_true():
    """H2 CLEAN: build_verdict with benign RQ → pass=True."""
    verdict = build_verdict(
        _MATRIX_NO_SPECIAL_CLAIM,
        _RESULT_SUMMARY_INDISTR,
        profile=None,
    )
    assert verdict["pass"] is True
    assert verdict["violations"] == []


def test_h2_empty_rq_no_false_violations():
    """H2 CLEAN: Empty or absent RQ → no false violations (nothing to check)."""
    matrix_empty_rq = {"research_question": "", "conditions": []}
    violations = check_goal_alignment(matrix_empty_rq, {"findings": []}, profile=None)
    assert violations == [], (
        f"Empty RQ must produce no violations; got: {violations}"
    )


def test_h2_has_baseline_condition_true_for_factor():
    """Helper: _has_baseline_condition returns True when a condition has factors.baseline=True."""
    matrix = {
        "conditions": [
            {"id": "baseline_unet", "factors": {"baseline": True}},
            {"id": "method_sam", "factors": {"baseline": False}},
        ]
    }
    assert _has_baseline_condition(matrix) is True


def test_h2_has_baseline_condition_true_for_id_tag():
    """Helper: _has_baseline_condition returns True when a condition id contains 'baseline'."""
    matrix = {
        "conditions": [
            {"id": "baseline_unet3d", "factors": {}},
            {"id": "method_sam", "factors": {}},
        ]
    }
    assert _has_baseline_condition(matrix) is True


def test_h2_has_baseline_condition_false_when_none():
    """Helper: _has_baseline_condition returns False when no condition is a baseline."""
    matrix = {
        "conditions": [
            {"id": "method_a", "factors": {"baseline": False}},
            {"id": "method_b", "factors": {"baseline": False}},
        ]
    }
    assert _has_baseline_condition(matrix) is False


# --------------------------------------------------------------------------- #
#  Real-profile test (using cv-medical profile structure)                     #
# --------------------------------------------------------------------------- #

def test_h2_real_profile_generalization_no_ood_fires():
    """H2 REAL PROFILE: cv-medical profile loaded; generalization RQ without OOD → flagged."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    matrix = {
        "research_question": (
            "Does the model generalize to external sites unseen during training? "
            "We test out-of-distribution transfer on scanner_site B."
        ),
        "conditions": [
            {"id": "method_sam_internal", "factors": {"baseline": False}},
            {"id": "baseline_unet_internal", "factors": {"baseline": True}},
        ],
        # Note: no condition with 'external'/'ood'/'held_out' in the id
    }

    result_summary = {
        "findings": [
            {"condition_id": "method_sam_internal", "metric": "Dice", "value": 0.85},
        ]
    }

    violations = check_goal_alignment(matrix, result_summary, profile=profile)
    ood_violations = [
        v for v in violations
        if "generaliz" in v.lower() or "ood" in v.lower() or "external" in v.lower()
        or "transfer" in v.lower()
    ]
    assert len(ood_violations) >= 1, (
        "cv-medical profile; RQ claims generalization/OOD transfer but only internal "
        f"conditions exist — must produce at least 1 violation. Got: {violations}"
    )


def test_h2_real_profile_clean_comparison_no_false_violation():
    """H2 REAL PROFILE: cv-medical profile; benign RQ with valid baseline → no violation."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    matrix = {
        "research_question": (
            "Does SAM-Med3D achieve competitive Dice on liver segmentation?"
        ),
        "conditions": [
            {"id": "baseline_unet3d", "factors": {"baseline": True}},
            {"id": "method_sammed3d", "factors": {"baseline": False}},
        ],
    }

    result_summary = {
        "findings": [
            {"condition_id": "method_sammed3d", "metric": "Dice", "value": 0.85},
            {"condition_id": "baseline_unet3d", "metric": "Dice", "value": 0.80},
        ]
    }

    violations = check_goal_alignment(matrix, result_summary, profile=profile)
    assert violations == [], (
        f"cv-medical profile; benign RQ with baseline condition must produce no violations. "
        f"Got: {violations}"
    )
