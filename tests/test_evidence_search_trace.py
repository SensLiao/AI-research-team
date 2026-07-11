from __future__ import annotations

import copy

from research_agent_teams.tools.evidence_search_trace import evaluate_search_trace
from research_agent_teams.tools.validate_artifact import validate_against


def complete_trace() -> dict:
    return {
        "search_contract_version": "evidence-search-trace/v1",
        "research_question": "Does intervention A improve outcome B, and where does it fail?",
        "critical_claims": [
            {"claim_id": "c1", "question": "Does A improve B?", "importance": "critical"},
            {"claim_id": "c2", "question": "Does the effect transfer?", "importance": "major"},
        ],
        "representativeness_dimensions": ["population", "dataset"],
        "rounds": [
            {
                "round_index": 0,
                "questions": ["primary effect", "negative results", "external validity"],
                "source_hits": [{"source_ref": "s1"}, {"source_ref": "s2"}, {"source_ref": "s3"}],
                "claim_ids_addressed": ["c1", "c2"],
                "contradiction_claim_ids_queried": ["c1", "c2"],
                "representativeness_dimensions_queried": ["population", "dataset"],
                "findings": [
                    {"finding_id": "f1", "source_refs": ["s1"], "claim_ids": ["c1"], "finding_kind": "supportive"},
                    {"finding_id": "f2", "source_refs": ["s2", "s3"], "claim_ids": ["c2"], "finding_kind": "boundary"},
                ],
            },
            {
                "round_index": 1,
                "questions": ["citation snowball and adversarial query"],
                "source_hits": [{"source_ref": "s1"}, {"source_ref": "s2"}],
                "claim_ids_addressed": ["c1", "c2"],
                "contradiction_claim_ids_queried": ["c1", "c2"],
                "representativeness_dimensions_queried": ["population", "dataset"],
                "findings": [],
            },
            {
                "round_index": 2,
                "questions": ["last adversarial query family"],
                "source_hits": [{"source_ref": "s2"}, {"source_ref": "s3"}],
                "claim_ids_addressed": ["c1", "c2"],
                "contradiction_claim_ids_queried": ["c1", "c2"],
                "representativeness_dimensions_queried": ["population", "dataset"],
                "findings": [],
            },
        ],
        "stop_reason": "semantic_complete",
        "budget_exhausted": False,
    }


def test_semantic_completion_is_derived_from_coverage_and_low_gain_rounds():
    trace = complete_trace()
    result = evaluate_search_trace(trace)
    assert result["status"] == "COMPLETE"
    assert result["semantic_complete"] is True
    assert result["critical_claim_coverage"] == 1.0
    assert result["contradiction_coverage"] == 1.0
    assert result["representativeness_coverage"] == 1.0
    assert result["round_information_gain"][-2:] == [0.0, 0.0]
    assert validate_against("evidence_search_trace.schema.json", trace) == []


def test_budget_exhaustion_is_needs_human_not_saturation():
    trace = complete_trace()
    trace["stop_reason"] = "budget_exhausted"
    trace["budget_exhausted"] = True
    result = evaluate_search_trace(trace)
    assert result["status"] == "NEEDS_HUMAN"
    assert result["semantic_complete"] is False
    assert any("budget exhaustion" in reason for reason in result["reasons"])


def test_worker_claim_of_semantic_complete_cannot_hide_missing_counterevidence_search():
    trace = complete_trace()
    for round_row in trace["rounds"]:
        round_row["contradiction_claim_ids_queried"] = ["c1"]
    result = evaluate_search_trace(trace)
    assert result["status"] == "INCOMPLETE"
    assert result["contradiction_coverage"] == 0.5


def test_ungrounded_finding_does_not_cover_a_critical_claim():
    trace = complete_trace()
    trace["rounds"][0]["findings"][1]["source_refs"] = ["invented-source"]
    result = evaluate_search_trace(trace)
    assert result["status"] == "INCOMPLETE"
    assert result["critical_claim_coverage"] == 0.5
    assert any("not grounded" in reason for reason in result["reasons"])


def test_nonchronological_rounds_are_incomplete_even_when_coverage_is_full():
    trace = complete_trace()
    trace["rounds"][2]["round_index"] = 9
    assert evaluate_search_trace(trace)["status"] == "INCOMPLETE"


def test_schema_rejects_worker_supplied_saturation_field():
    trace = copy.deepcopy(complete_trace())
    trace["saturation_reached"] = True
    assert validate_against("evidence_search_trace.schema.json", trace)

