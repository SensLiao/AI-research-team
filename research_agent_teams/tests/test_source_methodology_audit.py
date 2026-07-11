from __future__ import annotations

import copy

from research_agent_teams.tools.source_methodology_audit import (
    LEGACY_UNVERIFIED,
    audit_source,
    audit_source_quality_report,
)
from research_agent_teams.tools.validate_artifact import validate_against


def reviewed_source(ref: str = "s1", *, directness: str = "direct", applicability: str = "direct") -> dict:
    return {
        "source_ref": ref,
        "rank": 1,
        "tier": "peer-reviewed",
        "rigor_score": 0.01,
        "year": 2025,
        "venue": "Journal",
        "rank_notes": "methodology reviewed",
        "review_status": "VERIFIED",
        "directness": directness,
        "study_design": "controlled-experiment",
        "methodology_review": {
            "design_appropriateness": "strong",
            "bias_control": "adequate",
            "measurement_validity": "strong",
            "statistical_validity": "adequate",
            "reproducibility": "adequate",
        },
        "sample_evaluation_review": {
            "sample_adequacy": "adequate",
            "evaluation_independence": "adequate",
            "comparator_fairness": "strong",
            "uncertainty_reporting": "adequate",
        },
        "applicability": applicability,
        "evidence_refs": [{
            "evidence_ref": ref,
            "locator": "Methods section 3 and Table 2",
            "reported_result": "pre-registered primary endpoint",
        }],
        "limitations": ["single external cohort"],
    }


def current_report(rows: list[dict]) -> dict:
    return {
        "quality_contract_version": "source-methodology/v1",
        "review_status": "CURRENT",
        "ranked_sources": rows,
        "ranking_rationale": "Categorical methodology review with inspectable locators.",
        "n_sources_ranked": len(rows),
    }


def test_low_scalar_cannot_hide_a_methodologically_high_source():
    result = audit_source(reviewed_source())
    assert result["derived_strength"] == "HIGH"
    assert result["n_inspectable_evidence_refs"] == 1


def test_adversarial_perfect_scalar_cannot_grant_high_without_review():
    row = {
        "source_ref": "spoof",
        "rank": 1,
        "tier": "peer-reviewed",
        "rigor_score": 1.0,
    }
    assert audit_source(row)["derived_strength"] == "UNVERIFIED"
    report = audit_source_quality_report({
        "ranked_sources": [row],
        "ranking_rationale": "perfect scalar",
    })
    assert report["contract_status"] == LEGACY_UNVERIFIED
    assert report["n_high"] == 0


def test_weak_methodology_blocks_high_despite_perfect_scalar():
    row = reviewed_source()
    row["rigor_score"] = 1.0
    row["methodology_review"]["statistical_validity"] = "weak"
    result = audit_source(row)
    assert result["derived_strength"] != "HIGH"


def test_missing_locator_makes_current_source_unverified():
    row = reviewed_source()
    row["evidence_refs"] = [{"evidence_ref": "s1", "locator": "", "exact_quote": "claim"}]
    result = audit_source(row)
    assert result["derived_strength"] == "UNVERIFIED"
    assert any("locator" in reason for reason in result["reasons"])


def test_current_report_requires_review_fields_in_schema():
    good = current_report([reviewed_source()])
    assert validate_against("source_quality_report.schema.json", good) == []
    bad = copy.deepcopy(good)
    del bad["ranked_sources"][0]["methodology_review"]
    assert validate_against("source_quality_report.schema.json", bad)


def test_report_audit_requires_full_evidence_table_coverage():
    report = current_report([reviewed_source("s1")])
    table = {"sources": [{"id": "1", "ref": "s1"}, {"id": "2", "ref": "s2"}]}
    audit = audit_source_quality_report(report, table)
    assert audit["audit_status"] == "INCOMPLETE"
    assert audit["missing_source_refs"] == ["s2"]
