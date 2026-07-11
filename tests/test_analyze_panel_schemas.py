"""Schema validation tests for all 7 SUB-TEAM 2.4 (ANALYZE panel) schemas.

Validates well-formed samples and rejects crafted-bad inputs, for:
  - baseline_audit_report.schema.json
  - variance_report.schema.json
  - analysis_check_verdict.schema.json  (the critical panel-role / allOf test)
  - failure_inventory.schema.json
  - figure_spec_bundle.schema.json
  - viz_audit_report.schema.json
  - calibrated_claims.schema.json

Critical test: an analysis_check_verdict with violations[] non-empty but pass=true
MUST be schema-rejected (allOf structural rule).
"""
from __future__ import annotations

from research_agent_teams.tools.validate_artifact import validate_against


# =========================================================================== #
#  1. baseline_audit_report                                                    #
# =========================================================================== #

_GOOD_BASELINE_AUDIT = {
    "conditions_compared": ["baseline_unet", "method_sam"],
    "asymmetry_flags": [],
    "clean": True,
    "notes": "",
}

_BAD_BASELINE_AUDIT_MISSING_CLEAN = {
    "conditions_compared": ["baseline_unet", "method_sam"],
    "asymmetry_flags": [],
    # missing "clean"
}

_BAD_BASELINE_AUDIT_EXTRA_FIELD = {
    "conditions_compared": ["baseline_unet"],
    "asymmetry_flags": [],
    "clean": True,
    "extra_field": "should_not_be_here",  # additionalProperties: false
}


def test_baseline_audit_report_wellformed():
    assert validate_against("baseline_audit_report.schema.json", _GOOD_BASELINE_AUDIT) == []


def test_baseline_audit_report_missing_clean_rejected():
    assert validate_against("baseline_audit_report.schema.json", _BAD_BASELINE_AUDIT_MISSING_CLEAN) != []


def test_baseline_audit_report_extra_field_rejected():
    assert validate_against("baseline_audit_report.schema.json", _BAD_BASELINE_AUDIT_EXTRA_FIELD) != []


def test_baseline_audit_report_empty_conditions_rejected():
    bad = {**_GOOD_BASELINE_AUDIT, "conditions_compared": []}  # minItems 1
    assert validate_against("baseline_audit_report.schema.json", bad) != []


# =========================================================================== #
#  2. variance_report                                                          #
# =========================================================================== #

_GOOD_VARIANCE_REPORT = {
    "condition_id": "method_sam",
    "n_seeds": 5,
    "min_seeds_required": 3,
    "seed_count_insufficient": False,
    "per_metric_variance": [
        {"metric": "Dice", "mean": 0.85, "std": 0.01, "values": [0.84, 0.85, 0.86, 0.85, 0.85]}
    ],
    "stability_label": "stable",
}

_BAD_VARIANCE_REPORT_MISSING_N_SEEDS = {
    "condition_id": "method_sam",
    # missing n_seeds
    "seed_count_insufficient": False,
    "per_metric_variance": [],
}


def test_variance_report_wellformed():
    assert validate_against("variance_report.schema.json", _GOOD_VARIANCE_REPORT) == []


def test_variance_report_missing_n_seeds_rejected():
    assert validate_against("variance_report.schema.json", _BAD_VARIANCE_REPORT_MISSING_N_SEEDS) != []


def test_variance_report_missing_seed_count_insufficient_rejected():
    bad = {k: v for k, v in _GOOD_VARIANCE_REPORT.items() if k != "seed_count_insufficient"}
    assert validate_against("variance_report.schema.json", bad) != []


def test_variance_report_invalid_stability_label_rejected():
    bad = {**_GOOD_VARIANCE_REPORT, "stability_label": "perfect"}  # not in enum
    assert validate_against("variance_report.schema.json", bad) != []


def test_variance_report_negative_n_seeds_rejected():
    bad = {**_GOOD_VARIANCE_REPORT, "n_seeds": -1}  # minimum 0
    assert validate_against("variance_report.schema.json", bad) != []


# =========================================================================== #
#  3. analysis_check_verdict  — THE CRITICAL PANEL VERDICT-INTEGRITY TEST     #
# =========================================================================== #

_GOOD_ANALYSIS_CHECK_VERDICT_PASS = {
    "panel_role": "fairness",
    "pass": True,
    "violations": [],
    "checked_items": ["class_imbalance", "stratification"],
    "notes": "All checks passed.",
}

_GOOD_ANALYSIS_CHECK_VERDICT_FAIL = {
    "panel_role": "compliance",
    "pass": False,
    "violations": ["Condition 'method_c' declared but not run."],
    "checked_items": ["method_c"],
    "notes": "",
}

_GOOD_ANALYSIS_CHECK_VERDICT_GOAL = {
    "panel_role": "goal_alignment",
    "pass": False,
    "violations": ["RQ claims generalization but only in-distribution results present."],
    "checked_items": [],
    "notes": "",
}

# THE CRITICAL REJECTION: violations non-empty + pass=true → MUST be schema-rejected
_BAD_VERDICT_VIOLATION_BUT_PASS_TRUE = {
    "panel_role": "fairness",
    "pass": True,  # <-- hand-set True while violations is non-empty — MUST be rejected
    "violations": ["Unlabeled class imbalance detected."],
    "checked_items": [],
    "notes": "",
}

_BAD_VERDICT_INVALID_PANEL_ROLE = {
    "panel_role": "unknown_role",  # not in enum
    "pass": True,
    "violations": [],
}

_BAD_VERDICT_MISSING_PANEL_ROLE = {
    "pass": True,
    "violations": [],
}


def test_analysis_check_verdict_pass_wellformed():
    assert validate_against("analysis_check_verdict.schema.json", _GOOD_ANALYSIS_CHECK_VERDICT_PASS) == []


def test_analysis_check_verdict_fail_wellformed():
    assert validate_against("analysis_check_verdict.schema.json", _GOOD_ANALYSIS_CHECK_VERDICT_FAIL) == []


def test_analysis_check_verdict_goal_alignment_wellformed():
    assert validate_against("analysis_check_verdict.schema.json", _GOOD_ANALYSIS_CHECK_VERDICT_GOAL) == []


def test_all_three_panel_roles_are_valid():
    """Each of the three panel_role values must be accepted."""
    for role in ("fairness", "compliance", "goal_alignment"):
        instance = {
            "panel_role": role,
            "pass": True,
            "violations": [],
        }
        errors = validate_against("analysis_check_verdict.schema.json", instance)
        assert errors == [], f"panel_role='{role}' should be accepted; got: {errors}"


# CRITICAL: violations present + pass=True MUST be rejected (allOf structural rule)
def test_violation_present_but_pass_true_is_rejected():
    """THE critical verdict-integrity test: non-empty violations with pass=true must fail."""
    errors = validate_against(
        "analysis_check_verdict.schema.json", _BAD_VERDICT_VIOLATION_BUT_PASS_TRUE
    )
    assert errors != [], (
        "analysis_check_verdict with violations=['...'] and pass=true MUST be schema-rejected "
        "by the allOf structural integrity rule. Got no errors — the gate is broken!"
    )


def test_invalid_panel_role_rejected():
    assert validate_against("analysis_check_verdict.schema.json", _BAD_VERDICT_INVALID_PANEL_ROLE) != []


def test_missing_panel_role_rejected():
    assert validate_against("analysis_check_verdict.schema.json", _BAD_VERDICT_MISSING_PANEL_ROLE) != []


def test_missing_violations_field_rejected():
    bad = {"panel_role": "compliance", "pass": True}
    assert validate_against("analysis_check_verdict.schema.json", bad) != []


def test_extra_field_rejected():
    bad = {**_GOOD_ANALYSIS_CHECK_VERDICT_PASS, "extra": "not_allowed"}
    assert validate_against("analysis_check_verdict.schema.json", bad) != []


# =========================================================================== #
#  4. failure_inventory                                                        #
# =========================================================================== #

_GOOD_FAILURE_INVENTORY = {
    "condition_id": "method_sam",
    "failures": [
        {
            "type": "boundary_error",
            "description": "Prediction misses the vessel boundary near bifurcation.",
            "case_ref": "patient_042",
            "metric_context": "Dice=0.12",
            "hypothesized_cause": "Low contrast at vessel wall",
        }
    ],
    "summary": "One boundary error detected.",
}

_BAD_FAILURE_INVENTORY_EMPTY_FAILURES = {
    "condition_id": "method_sam",
    "failures": [],  # minItems 1
    "summary": "",
}

_BAD_FAILURE_INVENTORY_MISSING_TYPE = {
    "condition_id": "method_sam",
    "failures": [
        {
            "description": "Some failure",  # missing "type"
        }
    ],
}


def test_failure_inventory_wellformed():
    assert validate_against("failure_inventory.schema.json", _GOOD_FAILURE_INVENTORY) == []


def test_failure_inventory_empty_failures_rejected():
    assert validate_against("failure_inventory.schema.json", _BAD_FAILURE_INVENTORY_EMPTY_FAILURES) != []


def test_failure_inventory_missing_type_rejected():
    assert validate_against("failure_inventory.schema.json", _BAD_FAILURE_INVENTORY_MISSING_TYPE) != []


def test_failure_inventory_missing_condition_id_rejected():
    bad = {k: v for k, v in _GOOD_FAILURE_INVENTORY.items() if k != "condition_id"}
    assert validate_against("failure_inventory.schema.json", bad) != []


def test_failure_inventory_missing_description_rejected():
    bad = {
        "condition_id": "c1",
        "failures": [{"type": "boundary_error"}],  # missing description
    }
    assert validate_against("failure_inventory.schema.json", bad) != []


# =========================================================================== #
#  5. figure_spec_bundle                                                       #
# =========================================================================== #

_GOOD_FIGURE_SPEC_BUNDLE = {
    "run_ref": "run_001",
    "figures": [
        {
            "figure_id": "fig1_dice",
            "figure_type": "bar",
            "title": "Dice Score Comparison",
            "data_source": "result_summary",
            "x_axis": None,
            "y_axis": {"min": 0.0, "max": 1.0, "label": "Dice"},
            "conditions": ["baseline", "method"],
            "metrics": ["Dice"],
            "caption": "Comparison of Dice scores.",
            "notes": "",
        }
    ],
}

_BAD_FIGURE_SPEC_BUNDLE_EMPTY_FIGURES = {
    "run_ref": "run_001",
    "figures": [],  # minItems 1
}

_BAD_FIGURE_SPEC_BUNDLE_MISSING_TITLE = {
    "figures": [
        {
            "figure_id": "fig1",
            "figure_type": "bar",
            # missing title
            "data_source": "result_summary",
        }
    ]
}

_BAD_FIGURE_SPEC_BUNDLE_INVALID_TYPE = {
    "figures": [
        {
            "figure_id": "fig1",
            "figure_type": "pie",  # not in enum
            "title": "Pie Chart",
            "data_source": "result_summary",
        }
    ]
}


def test_figure_spec_bundle_wellformed():
    assert validate_against("figure_spec_bundle.schema.json", _GOOD_FIGURE_SPEC_BUNDLE) == []


def test_figure_spec_bundle_empty_figures_rejected():
    assert validate_against("figure_spec_bundle.schema.json", _BAD_FIGURE_SPEC_BUNDLE_EMPTY_FIGURES) != []


def test_figure_spec_bundle_missing_title_rejected():
    assert validate_against("figure_spec_bundle.schema.json", _BAD_FIGURE_SPEC_BUNDLE_MISSING_TITLE) != []


def test_figure_spec_bundle_invalid_figure_type_rejected():
    assert validate_against("figure_spec_bundle.schema.json", _BAD_FIGURE_SPEC_BUNDLE_INVALID_TYPE) != []


def test_figure_spec_bundle_missing_figure_id_rejected():
    bad = {
        "figures": [
            {
                "figure_type": "bar",
                "title": "T",
                "data_source": "src",
            }
        ]
    }
    assert validate_against("figure_spec_bundle.schema.json", bad) != []


# =========================================================================== #
#  6. viz_audit_report                                                         #
# =========================================================================== #

_GOOD_VIZ_AUDIT_CLEAN = {
    "figures_audited": ["fig1_dice"],
    "axis_truncation_flags": [],
    "clean": True,
    "notes": "",
}

_GOOD_VIZ_AUDIT_WITH_FLAG = {
    "figures_audited": ["fig2"],
    "axis_truncation_flags": [
        {
            "figure_id": "fig2",
            "metric": "Dice",
            "axis": "y",
            "declared_min": 0.94,
            "valid_min": 0.0,
            "detail": "y-axis truncated for Dice",
        }
    ],
    "clean": False,
    "notes": "Truncated y-axis detected.",
}

_BAD_VIZ_AUDIT_MISSING_CLEAN = {
    "figures_audited": [],
    "axis_truncation_flags": [],
    # missing "clean"
}

_BAD_VIZ_AUDIT_FLAG_MISSING_DETAIL = {
    "figures_audited": ["fig1"],
    "axis_truncation_flags": [
        {
            "figure_id": "fig1",
            "metric": "Dice",
            "axis": "y",
            "declared_min": 0.94,
            "valid_min": 0.0,
            # missing "detail" — required
        }
    ],
    "clean": False,
}

_BAD_VIZ_AUDIT_INVALID_AXIS = {
    "figures_audited": ["fig1"],
    "axis_truncation_flags": [
        {
            "figure_id": "fig1",
            "metric": "Dice",
            "axis": "z",  # not in enum ["x", "y"]
            "declared_min": 0.94,
            "valid_min": 0.0,
            "detail": "bad axis",
        }
    ],
    "clean": False,
}


def test_viz_audit_report_clean_wellformed():
    assert validate_against("viz_audit_report.schema.json", _GOOD_VIZ_AUDIT_CLEAN) == []


def test_viz_audit_report_with_flag_wellformed():
    assert validate_against("viz_audit_report.schema.json", _GOOD_VIZ_AUDIT_WITH_FLAG) == []


def test_viz_audit_report_missing_clean_rejected():
    assert validate_against("viz_audit_report.schema.json", _BAD_VIZ_AUDIT_MISSING_CLEAN) != []


def test_viz_audit_report_flag_missing_detail_rejected():
    assert validate_against("viz_audit_report.schema.json", _BAD_VIZ_AUDIT_FLAG_MISSING_DETAIL) != []


def test_viz_audit_report_invalid_axis_rejected():
    assert validate_against("viz_audit_report.schema.json", _BAD_VIZ_AUDIT_INVALID_AXIS) != []


# =========================================================================== #
#  7. calibrated_claims                                                        #
# =========================================================================== #

_GOOD_CALIBRATED_CLAIMS = {
    "source_ref": "result_summary_001",
    "calibrated": [
        {
            "original_claim": "+0.3% significant improvement on Dice",
            "metric": "Dice",
            "delta": 0.003,
            "variance": 0.010,
            "strength": "inconclusive",
            "calibrated_claim": "[calibrated: inconclusive] +0.3% significant improvement on Dice",
            "caveat": "Claim downgraded: delta=0.003 vs variance=0.010.",
            "downgraded": True,
        }
    ],
}

_GOOD_CALIBRATED_CLAIMS_STRONG = {
    "source_ref": None,
    "calibrated": [
        {
            "original_claim": "+10% improvement on Dice",
            "metric": "Dice",
            "delta": 0.10,
            "variance": 0.01,
            "strength": "strong",
            "calibrated_claim": "+10% improvement on Dice",
            "caveat": "Calibrated strength 'strong': delta=0.1, variance=0.01.",
            "downgraded": False,
        }
    ],
}

_BAD_CALIBRATED_CLAIMS_EMPTY = {
    "calibrated": [],  # minItems 1
}

_BAD_CALIBRATED_CLAIMS_INVALID_STRENGTH = {
    "calibrated": [
        {
            "original_claim": "some claim",
            "strength": "excellent",  # not in enum
            "calibrated_claim": "some claim",
        }
    ]
}

_BAD_CALIBRATED_CLAIMS_MISSING_STRENGTH = {
    "calibrated": [
        {
            "original_claim": "some claim",
            # missing "strength"
            "calibrated_claim": "some claim",
        }
    ]
}


def test_calibrated_claims_wellformed_inconclusive():
    assert validate_against("calibrated_claims.schema.json", _GOOD_CALIBRATED_CLAIMS) == []


def test_calibrated_claims_wellformed_strong():
    assert validate_against("calibrated_claims.schema.json", _GOOD_CALIBRATED_CLAIMS_STRONG) == []


def test_calibrated_claims_empty_list_rejected():
    assert validate_against("calibrated_claims.schema.json", _BAD_CALIBRATED_CLAIMS_EMPTY) != []


def test_calibrated_claims_invalid_strength_rejected():
    assert validate_against("calibrated_claims.schema.json", _BAD_CALIBRATED_CLAIMS_INVALID_STRENGTH) != []


def test_calibrated_claims_missing_strength_rejected():
    assert validate_against("calibrated_claims.schema.json", _BAD_CALIBRATED_CLAIMS_MISSING_STRENGTH) != []


def test_calibrated_claims_missing_original_claim_rejected():
    bad = {
        "calibrated": [
            {
                # missing original_claim
                "strength": "moderate",
                "calibrated_claim": "some calibrated text",
            }
        ]
    }
    assert validate_against("calibrated_claims.schema.json", bad) != []
