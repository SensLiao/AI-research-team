from __future__ import annotations

import copy

from research_agent_teams.tools.evidence_checker import build_verdict
from research_agent_teams.tools.research_brief_quality import assess_evidence


def reviewed_source(ref: str, *, directness: str = "direct", applicability: str = "direct") -> dict:
    return {
        "source_ref": ref, "rank": 1, "tier": "peer-reviewed", "rigor_score": 0.01,
        "year": 2025, "venue": "Journal", "rank_notes": "methodology reviewed",
        "review_status": "VERIFIED", "directness": directness,
        "study_design": "controlled-experiment",
        "methodology_review": {
            "design_appropriateness": "strong", "bias_control": "adequate",
            "measurement_validity": "strong", "statistical_validity": "adequate",
            "reproducibility": "adequate",
        },
        "sample_evaluation_review": {
            "sample_adequacy": "adequate", "evaluation_independence": "adequate",
            "comparator_fairness": "strong", "uncertainty_reporting": "adequate",
        },
        "applicability": applicability,
        "evidence_refs": [{"evidence_ref": ref, "locator": "Methods 3 / Table 2",
                           "reported_result": "primary endpoint"}],
        "limitations": ["single external cohort"],
    }


def current_report(rows: list[dict]) -> dict:
    return {
        "quality_contract_version": "source-methodology/v1", "review_status": "CURRENT",
        "ranked_sources": rows,
        "ranking_rationale": "Categorical methodology review with inspectable locators.",
        "n_sources_ranked": len(rows),
    }


def complete_trace() -> dict:
    base = {
        "search_contract_version": "evidence-search-trace/v1",
        "research_question": "Does A improve B, and where does it fail?",
        "critical_claims": [
            {"claim_id": "c1", "question": "Does A improve B?", "importance": "critical"},
            {"claim_id": "c2", "question": "Does it transfer?", "importance": "major"},
        ],
        "representativeness_dimensions": ["population", "dataset"],
        "rounds": [{
            "round_index": 0, "questions": ["effect and counterevidence"],
            "source_hits": [{"source_ref": "s1"}, {"source_ref": "s2"}, {"source_ref": "s3"}],
            "claim_ids_addressed": ["c1", "c2"],
            "contradiction_claim_ids_queried": ["c1", "c2"],
            "representativeness_dimensions_queried": ["population", "dataset"],
            "findings": [
                {"finding_id": "f1", "source_refs": ["s1"], "claim_ids": ["c1"], "finding_kind": "supportive"},
                {"finding_id": "f2", "source_refs": ["s2", "s3"], "claim_ids": ["c2"], "finding_kind": "boundary"},
            ],
        }],
        "stop_reason": "semantic_complete", "budget_exhausted": False,
    }
    for index in (1, 2):
        base["rounds"].append({
            "round_index": index, "questions": [f"adversarial snowball {index}"],
            "source_hits": [{"source_ref": "s1"}, {"source_ref": "s2"}],
            "claim_ids_addressed": ["c1", "c2"],
            "contradiction_claim_ids_queried": ["c1", "c2"],
            "representativeness_dimensions_queried": ["population", "dataset"],
            "findings": [],
        })
    return base


def strict_inputs():
    table = {
        "evidence_contract_version": "evidence-table/v2",
        "source_quality_report_ref": "source-quality.artifact.json",
        "search_trace_ref": "evidence-search-trace.artifact.json",
        "query": "Does A work?",
        "sources": [
            {"id": "s1", "kind": "paper", "ref": "s1", "claim_support": "none"},
            {"id": "s2", "kind": "paper", "ref": "s2", "claim_support": "none"},
            {"id": "s3", "kind": "paper", "ref": "s3", "claim_support": "none"},
        ],
        "saturation_reached": True,
    }
    rows = [reviewed_source("s1"), reviewed_source("s2"), reviewed_source("s3", directness="indirect", applicability="partial")]
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    source_quality = current_report(rows)
    claims = {"claims": [
        {"claim_id": "c1", "text": "A improves B"},
        {"claim_id": "c2", "text": "Transfer is bounded"},
    ]}
    mappings = {"mappings": [
        {"claim_id": "c1", "overall_support": "supported", "claim_risk": {"level": "low"},
         "loci": [{"source_ref": "s1", "supports_claim": True, "directness": "direct"}]},
        {"claim_id": "c2", "overall_support": "supported", "claim_risk": {"level": "low"},
         "loci": [{"source_ref": "s2", "supports_claim": True, "directness": "direct"}]},
    ]}
    return table, source_quality, complete_trace(), claims, mappings


def test_strict_evidence_gate_uses_derived_strength_and_semantic_completion():
    table, source_quality, trace, _claims, _mappings = strict_inputs()
    verdict = build_verdict(
        table,
        source_quality_report=source_quality,
        search_trace=trace,
        strict_current=True,
    )
    assert verdict["verdict"] == "PASS"
    assert verdict["n_strong"] == 2
    assert verdict["saturation_reached"] is True


def test_perfect_scalar_and_true_legacy_flag_cannot_pass_strict_gate():
    table, _source_quality, trace, _claims, _mappings = strict_inputs()
    spoof = {
        "ranked_sources": [
            {"source_ref": ref, "rank": index, "tier": "peer-reviewed", "rigor_score": 1.0}
            for index, ref in enumerate(("s1", "s2", "s3"), start=1)
        ],
        "ranking_rationale": "all scalar scores are perfect",
    }
    verdict = build_verdict(table, source_quality_report=spoof, search_trace=trace, strict_current=True)
    assert verdict["verdict"] == "BLOCK"
    assert verdict["n_strong"] == 0
    assert any("legacy source quality" in reason for reason in verdict["reasons"])


def test_budget_exhaustion_overrides_true_saturation_mirror():
    table, source_quality, trace, _claims, _mappings = strict_inputs()
    trace["stop_reason"] = "budget_exhausted"
    trace["budget_exhausted"] = True
    verdict = build_verdict(table, source_quality_report=source_quality, search_trace=trace)
    assert verdict["verdict"] == "BLOCK"
    assert verdict["saturation_reached"] is False
    assert any("NEEDS_HUMAN" in reason for reason in verdict["reasons"])


def test_current_contract_can_earn_high_only_with_both_truth_helpers():
    table, source_quality, trace, claims, mappings = strict_inputs()
    assessment = assess_evidence(
        table,
        claims,
        mappings,
        source_quality,
        {"conflicts": []},
        {"coverage_gaps": []},
        None,
        {"existence_warnings": 0},
        search_trace=trace,
    )
    assert assessment.grade == "HIGH"
    assert assessment.source_quality_status == "PASS"
    assert assessment.search_completion_status == "COMPLETE"


def test_legacy_scalars_are_explicitly_unverified_and_never_earn_high():
    table, source_quality, _trace, claims, mappings = strict_inputs()
    table = copy.deepcopy(table)
    table.pop("evidence_contract_version")
    table.pop("source_quality_report_ref")
    table.pop("search_trace_ref")
    for source in table["sources"]:
        source["claim_support"] = "strong"
    for row in source_quality["ranked_sources"]:
        for field in (
            "review_status", "directness", "study_design", "methodology_review",
            "sample_evaluation_review", "applicability", "evidence_refs", "limitations",
        ):
            row.pop(field, None)
        row["rigor_score"] = 1.0
    source_quality.pop("quality_contract_version")
    source_quality.pop("review_status")
    assessment = assess_evidence(
        table, claims, mappings, source_quality, {"conflicts": []},
        {"coverage_gaps": []}, None, {"existence_warnings": 0},
    )
    assert assessment.grade != "HIGH"
    assert assessment.source_quality_status == "LEGACY_UNVERIFIED"
    assert assessment.search_completion_status == "LEGACY_UNVERIFIED"


def test_evidence_table_v2_schema_requires_bound_trace_refs():
    from research_agent_teams.tools.validate_artifact import validate_against

    table, _source_quality, _trace, _claims, _mappings = strict_inputs()
    assert validate_against("evidence_table.schema.json", table) == []
    del table["search_trace_ref"]
    assert validate_against("evidence_table.schema.json", table)
