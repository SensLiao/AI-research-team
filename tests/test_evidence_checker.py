"""Real tests for the evidence-verifier's deterministic core (the two-tier evidence gate)."""
from __future__ import annotations

import copy

from research_agent_teams.tools.evidence_checker import build_verdict, check_evidence
from research_agent_teams.tools.validate_artifact import validate_against

GOOD = {
    "query": "text-prompted medical segmentation",
    "sources": [
        {"id": "s1", "kind": "paper", "ref": "[[ma-2023-medsam]]#sha1", "claim_support": "strong"},
        {"id": "s2", "kind": "paper", "ref": "arXiv:2304.12306", "claim_support": "moderate"},
        {"id": "s3", "kind": "repo", "ref": "https://github.com/x/y", "claim_support": "moderate"},
    ],
    "saturation_reached": True,
}


def test_sufficient_saturated_evidence_passes():
    reasons, facts = check_evidence(GOOD)
    assert reasons == []
    assert facts == {"n_sources": 3, "n_strong": 1, "saturation_reached": True}
    assert build_verdict(GOOD)["verdict"] == "PASS"


def test_too_few_sources_blocks():
    thin = copy.deepcopy(GOOD)
    thin["sources"] = thin["sources"][:1]
    assert any("too few sources" in r for r in check_evidence(thin)[0])
    assert build_verdict(thin)["verdict"] == "BLOCK"


def test_no_strong_support_blocks():
    weak = copy.deepcopy(GOOD)
    for s in weak["sources"]:
        s["claim_support"] = "weak"
    assert any("strong-support" in r for r in check_evidence(weak)[0])
    assert build_verdict(weak)["verdict"] == "BLOCK"


def test_unsaturated_search_blocks():
    unsat = copy.deepcopy(GOOD)
    unsat["saturation_reached"] = False
    assert any("saturation" in r for r in check_evidence(unsat)[0])
    assert build_verdict(unsat)["verdict"] == "BLOCK"


def test_profile_can_tighten_threshold_not_loosen():
    # profile tightens min_strong to 2 -> the otherwise-good base now BLOCKs (gates only go up)
    strict = {"evidence_thresholds": {"min_strong": 2}, "evidence_invariants": [">=2 peer-reviewed strong sources"]}
    v = build_verdict(GOOD, profile=strict)
    assert v["verdict"] == "BLOCK"
    assert ">=2 peer-reviewed strong sources" in v["checked_invariants"]


def test_verdict_is_schema_valid():
    assert validate_against("evidence_verdict.schema.json", build_verdict(GOOD)) == []
    assert validate_against("evidence_verdict.schema.json", build_verdict({"query": "q", "sources": [], "saturation_reached": False})) == []
