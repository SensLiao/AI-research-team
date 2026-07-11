"""Regression tests for the fairness-auditor deterministic core (fairness_audit.py).

H2: Every test has a clear before/after narrative: before this helper existed the
fairness-auditor gate had no deterministic backing (pass-emitting prose only).
Now it bites on a crafted-bad input shaped like the real cv-medical profile.

Test structure:
  - flagged case: profile declares stratification_keys, result_summary has no per-stratum
    findings → violation emitted → pass=False
  - clean case: result_summary has per-stratum findings for all declared keys → pass=True
  - real-profile test: uses cv-medical-segmentation.profile.yaml
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.fairness_audit import (
    build_verdict,
    check_fairness,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

_PROFILE_WITH_STRAT_KEYS = {
    "split_policy": {
        "stratification_keys": ["anatomy_region", "pathology_status"],
        "default_split_unit": "patient",
        "allowed_split_units": ["patient", "case"],
    },
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
    ],
}

_PROFILE_NO_STRAT_KEYS = {
    "split_policy": {
        "stratification_keys": [],
        "default_split_unit": "patient",
    },
    "metrics": [
        {"name": "Dice", "higher_is_better": True, "valid_range": [0.0, 1.0]},
    ],
}

# result_summary with NO per-stratum findings (only overall)
_RESULT_SUMMARY_NO_STRATA = {
    "findings": [
        {"condition_id": "method_sam", "metric": "Dice", "value": 0.85},
        {"condition_id": "method_sam", "metric": "IoU", "value": 0.75},
    ]
}

# result_summary with per-stratum findings for anatomy_region and pathology_status
_RESULT_SUMMARY_WITH_STRATA = {
    "findings": [
        {"condition_id": "anatomy_region_liver_sam", "metric": "Dice", "value": 0.88},
        {"condition_id": "anatomy_region_kidney_sam", "metric": "Dice", "value": 0.82},
        {"condition_id": "pathology_status_benign_sam", "metric": "Dice", "value": 0.87},
        {"condition_id": "pathology_status_malignant_sam", "metric": "Dice", "value": 0.81},
    ]
}

# result_summary with per-stratum for anatomy_region but MISSING pathology_status
_RESULT_SUMMARY_PARTIAL_STRATA = {
    "findings": [
        {"condition_id": "anatomy_region_liver_sam", "metric": "Dice", "value": 0.88},
        # no pathology_status-tagged finding
    ]
}


# --------------------------------------------------------------------------- #
#  Flagged cases — gate must BITE                                              #
# --------------------------------------------------------------------------- #

def test_h2_missing_strata_findings_is_flagged():
    """H2 FLAGGED: Profile declares stratification_keys; result_summary has none → violation.

    This is the core gate that was missing before this helper was created.
    Before: fairness-auditor had no deterministic backing — always emitted pass.
    After: check_fairness returns violations for each missing stratum key.
    """
    violations = check_fairness(
        _RESULT_SUMMARY_NO_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert len(violations) >= 1, (
        "Profile declares stratification_keys=['anatomy_region', 'pathology_status'] "
        "but result_summary has no per-stratum findings — must produce at least 1 violation. "
        f"Got violations: {violations}"
    )
    # Each declared key should appear in some violation
    violation_text = " ".join(violations).lower()
    assert "anatomy_region" in violation_text or "pathology_status" in violation_text, (
        f"Violation text must mention the missing stratum keys; got: {violations}"
    )


def test_h2_build_verdict_no_strata_pass_is_false():
    """H2: build_verdict with no per-stratum findings must produce pass=False."""
    verdict = build_verdict(
        _RESULT_SUMMARY_NO_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert verdict["panel_role"] == "fairness"
    assert verdict["pass"] is False, (
        f"build_verdict must return pass=False when strata are missing; got pass={verdict['pass']}"
    )
    assert len(verdict["violations"]) >= 1


def test_h2_partial_strata_missing_key_flagged():
    """H2 FLAGGED: anatomy_region present but pathology_status missing → violation for missing key."""
    violations = check_fairness(
        _RESULT_SUMMARY_PARTIAL_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    violation_text = " ".join(violations).lower()
    assert "pathology_status" in violation_text, (
        f"pathology_status is missing from findings; must be flagged. Got: {violations}"
    )
    # anatomy_region IS covered — must NOT appear as a missing violation
    # (it's OK for it to appear in other violation strings, but not as "not found")
    anatomy_violations = [v for v in violations if "anatomy_region" in v.lower()
                          and "absent" in v.lower() or "not found" in v.lower() or
                          "no per-stratum" in v.lower()]
    # The anatomy_region key IS covered, so the per-key violation for it should not fire
    # (the class-imbalance-overall violation may fire but the per-key anatomy one should not)
    per_key_anatomy_violations = [
        v for v in violations
        if "anatomy_region" in v.lower() and "stratification_key" in v.lower()
    ]
    assert len(per_key_anatomy_violations) == 0, (
        f"anatomy_region IS covered; should not have a per-key violation. "
        f"Got: {per_key_anatomy_violations}"
    )


# --------------------------------------------------------------------------- #
#  Clean cases — no false positives                                            #
# --------------------------------------------------------------------------- #

def test_h2_clean_all_strata_covered_no_violations():
    """H2 CLEAN: result_summary has per-stratum findings for all declared keys → pass=True."""
    violations = check_fairness(
        _RESULT_SUMMARY_WITH_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert violations == [], (
        f"All declared strata covered — must return no violations; got: {violations}"
    )


def test_h2_build_verdict_all_strata_covered_pass_is_true():
    """H2 CLEAN: build_verdict with all strata covered must produce pass=True."""
    verdict = build_verdict(
        _RESULT_SUMMARY_WITH_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert verdict["pass"] is True
    assert verdict["violations"] == []


def test_h2_no_strat_keys_in_profile_no_violations():
    """H2 CLEAN: Profile with empty stratification_keys — no violations even with bare findings."""
    violations = check_fairness(
        _RESULT_SUMMARY_NO_STRATA,
        run_records=[],
        profile=_PROFILE_NO_STRAT_KEYS,
    )
    assert violations == [], (
        "Profile with no stratification_keys declared must never flag the findings. "
        f"Got: {violations}"
    )


def test_h2_no_profile_no_violations():
    """H2 CLEAN: Without a profile there are no declared keys → no false BLOCK."""
    violations = check_fairness(
        _RESULT_SUMMARY_NO_STRATA,
        run_records=None,
        profile=None,
    )
    assert violations == [], (
        f"Without a profile no strat keys are declared; must return no violations. Got: {violations}"
    )


def test_h2_stratum_found_in_run_records():
    """H2 CLEAN: Stratum referenced in run_records (not findings) must count as covered."""
    run_records = [
        {"condition_id": "anatomy_region_liver", "status": "provisional"},
        {"condition_id": "pathology_status_benign", "status": "provisional"},
    ]
    violations = check_fairness(
        _RESULT_SUMMARY_NO_STRATA,  # findings don't reference strata
        run_records=run_records,
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    # Both keys are covered via run_records
    anatomy_key_violations = [
        v for v in violations if "anatomy_region" in v.lower() and "stratification_key" in v.lower()
    ]
    pathology_key_violations = [
        v for v in violations if "pathology_status" in v.lower() and "stratification_key" in v.lower()
    ]
    assert anatomy_key_violations == [], (
        f"anatomy_region is covered via run_records; must not be flagged. Got: {violations}"
    )
    assert pathology_key_violations == [], (
        f"pathology_status is covered via run_records; must not be flagged. Got: {violations}"
    )


# --------------------------------------------------------------------------- #
#  Round-2 FIX 3: legitimate per-VALUE stratification must PASS                #
#                                                                              #
#  Before fix: the per-key check required the condition_id to ECHO the key     #
#  NAME (`key_lower in condition_id`). Real per-subgroup findings carry stratum #
#  VALUES (e.g. condition_id 'ours_aorta', stratum 'aorta'), not the key name  #
#  ('anatomy_region') — so a genuine stratified result set was wrongly flagged.#
#  After fix: an explicit `stratum`/`stratum_key` tag proves stratification and #
#  the result set PASSES regardless of whether the key name appears.           #
# --------------------------------------------------------------------------- #

# Per-VALUE stratified findings: condition_ids carry stratum VALUES (aorta/vein),
# NOT the key name 'anatomy_region'; an explicit `stratum` field tags each finding.
_RESULT_SUMMARY_PER_VALUE_STRATA = {
    "findings": [
        {"condition_id": "ours_aorta", "stratum": "aorta", "metric": "Dice", "value": 0.88},
        {"condition_id": "ours_vein", "stratum": "vein", "metric": "Dice", "value": 0.82},
    ]
}

# Aggregate-only findings: no stratum tag at all (the genuine bad case).
_RESULT_SUMMARY_AGGREGATE_ONLY = {
    "findings": [
        {"condition_id": "ours", "metric": "Dice", "value": 0.85},
    ]
}


def test_fix3_per_value_stratification_passes():
    """FIX 3 (no over-correction): per-VALUE stratified findings (ours_aorta/ours_vein,
    explicit stratum tags) must PASS even though the condition_id never spells out the
    key name 'anatomy_region'."""
    violations = check_fairness(
        _RESULT_SUMMARY_PER_VALUE_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert violations == [], (
        "Per-value stratified findings (with explicit stratum tags) must not be flagged "
        f"just because the condition_id does not echo the key name. Got: {violations}"
    )
    verdict = build_verdict(
        _RESULT_SUMMARY_PER_VALUE_STRATA,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert verdict["pass"] is True


def test_fix3_per_value_stratification_via_run_records_passes():
    """FIX 3: explicit stratum tag on run_records (not findings) also proves stratification."""
    run_records = [
        {"condition_id": "ours_aorta", "stratum": "aorta", "status": "provisional"},
        {"condition_id": "ours_vein", "stratum": "vein", "status": "provisional"},
    ]
    violations = check_fairness(
        _RESULT_SUMMARY_AGGREGATE_ONLY,  # findings have no stratum tag
        run_records=run_records,
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert violations == [], (
        f"Explicit stratum tags on run_records must clear the fairness check. Got: {violations}"
    )


def test_fix3_aggregate_only_still_flagged():
    """FIX 3 (keep the real bite): aggregate-only results (zero stratum tags) are still flagged."""
    violations = check_fairness(
        _RESULT_SUMMARY_AGGREGATE_ONLY,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert len(violations) >= 1, (
        "Aggregate-only results (no per-stratum tag at all) must still be flagged — "
        f"fairness across subgroups is unverifiable. Got: {violations}"
    )
    verdict = build_verdict(
        _RESULT_SUMMARY_AGGREGATE_ONLY,
        run_records=[],
        profile=_PROFILE_WITH_STRAT_KEYS,
    )
    assert verdict["pass"] is False


# --------------------------------------------------------------------------- #
#  Real-profile test                                                           #
# --------------------------------------------------------------------------- #

def test_h2_real_profile_missing_strata_fires():
    """H2 REAL PROFILE: cv-medical profile declares stratification_keys; bare findings → flagged."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # Verify the real profile has stratification_keys (sanity check)
    strat_keys = profile.get("split_policy", {}).get("stratification_keys", [])
    assert len(strat_keys) >= 1, (
        "cv-medical profile must declare at least one stratification_key for this test to be meaningful"
    )

    # Findings with NO per-stratum tags
    result_summary = {
        "findings": [
            {"condition_id": "method_sam", "metric": "Dice", "value": 0.85},
        ]
    }

    violations = check_fairness(result_summary, run_records=[], profile=profile)
    assert len(violations) >= 1, (
        f"cv-medical profile declares stratification_keys={strat_keys}; "
        "a result_summary with no per-stratum findings must produce at least 1 violation. "
        f"Got: {violations}"
    )


def test_h2_real_profile_with_strata_covered_passes():
    """H2 REAL PROFILE: cv-medical profile; findings that cover all declared keys → pass."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    strat_keys = profile.get("split_policy", {}).get("stratification_keys", [])

    # Build findings that reference each declared stratification key
    findings = []
    for key in strat_keys:
        findings.append({
            "condition_id": f"{key}_group_a_sam",
            "metric": "Dice",
            "value": 0.85,
        })
    result_summary = {"findings": findings}

    violations = check_fairness(result_summary, run_records=[], profile=profile)
    per_key_violations = [v for v in violations if "stratification_key" in v]
    assert per_key_violations == [], (
        f"All real-profile strat keys covered in findings; must not flag. Got: {violations}"
    )
