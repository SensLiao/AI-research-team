"""Operate wave-1 modes — evidence_review / evidence_deep / deep_research recipes + repair loop.

Proves: REGISTRY 1→4; router admits the new deep_research mode; each recipe's dets write
schema-valid artifacts; gates BLOCK and the bounded revise loop feeds back then escalates;
deep_research enforces the previously-dead budget counters.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import REGISTRY, deep_research, evidence_deep, evidence_review
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools.budget_tracker import BudgetExceeded
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "test",
                      "budget": budget or {"max_agent_hops": 6, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _good_evidence(query="q"):
    return {
        "evidence_table": {"query": query, "saturation_reached": True,
                           "sources": [
                               {"id": "s1", "kind": "paper", "ref": "[[page-a]]", "claim_support": "strong"},
                               {"id": "s2", "kind": "paper", "ref": "doi:10.1000/x", "claim_support": "moderate"},
                               {"id": "s3", "kind": "paper", "ref": "arXiv:2403.12345", "claim_support": "weak"}]},
        "claim_list": {"source_scope": "vault", "claims": [
            {"claim_id": "c1", "text": "method A beats B on metric M", "source_ref": "[[page-a]]"}]},
        "claim_evidence_map": {"mappings": [
            {"claim_id": "c1", "overall_support": "supported",
             "loci": [{"locus_id": "l1", "source_ref": "[[page-a]]", "location": "Table 2",
                       "kind": "table", "reported_result": "A 0.91 vs B 0.85", "supports_claim": True}]}]},
    }


def _write_bundle(run_dir, payload):
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


# ---------------- registry + router ----------------

def test_registry_has_seven_wired_modes():
    # wave 1 wired four; audit waves A-D (2026-06-13) wired gap_breadth + venue_readiness +
    # full_rigor_minimal — the operated surface is now SEVEN (mirror-tested in test_operate_wiring).
    assert set(REGISTRY) == {"new_direction", "evidence_review", "evidence_deep", "deep_research",
                             "gap_breadth", "venue_readiness", "full_rigor_minimal"}
    for mod in REGISTRY.values():
        assert callable(mod.llm_step) and callable(mod.run_dets)


def test_router_admits_deep_research():
    tf = resolve_task("scan the field", "deep_research", "run-x", TS)
    assert validate_routing(tf) == []
    p = tf["payload"]
    assert p["stage_path"] == ["DISCOVER", "REPORT"]
    assert p["budget"]["max_iterations_without_new_evidence"] == 3
    assert "evidence-verifier" in p["agent_subset"] and "citation-integrity-auditor" in p["agent_subset"]


# ---------------- evidence_review ----------------

def test_evidence_review_happy_path(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, _good_evidence())
    paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)
    assert report["evidence_gate"] == "PASS" and report["citation_gate"] == "PASS"
    assert any("evidence-table" in p for p in paths)
    _validate_written(paths)
    rpaths, _ = evidence_review.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)


def test_evidence_review_repair_loop_feeds_back_then_escalates(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 6, "max_debug_retries_per_run": 2})
    bad = _good_evidence()
    bad["evidence_table"]["saturation_reached"] = False          # deterministic floor violation
    _write_bundle(run_dir, bad)

    first = evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert first[0] == "retry" and "saturation" in first[1]      # gate feedback travels to the worker
    second = evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert second[0] == "retry"                                  # cap=2 is a RETRY budget: 2 retries allowed
    with pytest.raises(GateBlock):                               # 3rd failure exhausts the budget -> escalate
        evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "fresh")
    _write_bundle(run_dir2, _good_evidence())                    # worker revises -> loop exits ok
    ok = evidence_review.run_dets_with_repair(run_dir2, "DISCOVER", TS)
    assert ok[0] == "ok"


def test_evidence_review_llm_step_shape(tmp_path):
    run_dir = str(_mk_run(tmp_path))   # llm_step reads the run's task_frame for the north-star block
    spec = evidence_review.llm_step(run_dir, "DISCOVER", "my question", model_policy="default")
    assert spec["output"].endswith("inbox/DISCOVER.bundle.json")
    assert "my question" in spec["prompt"] and "REPAIR ATTEMPT" in spec["prompt"]
    assert "NORTH STAR" in spec["prompt"]
    assert spec["model"] == "sonnet"
    assert evidence_review.llm_step(run_dir, "REPORT", "q") is None
    assert evidence_review.llm_step(run_dir, "DISCOVER", "q")["model"] == "opus"  # max_quality default


# ---------------- evidence_deep ----------------

def test_evidence_deep_writes_contradictions_and_proposals(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence()
    b["contradictions"] = {"n_claims_checked": 2, "summary": "one numeric clash",
                           "conflicts": [{"conflict_id": "conf1", "claim_ref_a": "c1",
                                          "claim_ref_b": "c2", "kind": "numerical-disagreement",
                                          "description": "0.91 vs 0.79 same setup",
                                          "resolution_status": "unresolved"}]}
    b["invalidation_proposals"] = [{
        "claim_slug": "old-claim-page", "invalidated_by_slug": "newer-result-page",
        "edge_type": "supersedes", "invalid_at": "2026-05-01",
        "basis": "newer protocol-matched result replaces the old number",
        "evidence_ref": ["conf1", "[[newer-result-page]]"]}]
    _write_bundle(run_dir, b)
    paths, report = evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_conflicts"] == 1 and report["n_invalidation_proposals"] == 1
    _validate_written(paths)
    inv = json.loads(Path(next(p for p in paths if "invalidation" in p)).read_text(encoding="utf-8"))
    assert inv["status"] == "draft"                              # a PROPOSAL — only /promote lands it


def test_evidence_deep_blocks_invented_slug_proposal(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence()
    b["invalidation_proposals"] = [{
        "claim_slug": "Not A Slug!", "invalidated_by_slug": "ok-page",
        "edge_type": "refutes", "invalid_at": "2026-05-01", "basis": "x", "evidence_ref": ["e"]}]
    _write_bundle(run_dir, b)
    with pytest.raises(GateBlock) as ei:
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "never invent a slug" in str(ei.value)


# ---------------- deep_research ----------------

def _brief_bundle(iterations_wo_new=1, fulltext_reads=4):
    b = _good_evidence("scan topic")
    b["research_brief"] = {
        "topic": "scan topic",
        "perspectives": [{"perspective_id": "P1", "angle": "methods state",
                          "questions": ["what is sota?", "what is missing?"]}],
        "findings": [{"perspective_id": "P1", "summary": "compressed finding",
                      "source_refs": ["[[page-a]]", "doi:10.1000/x"]}],
        "iterations_used": 2, "saturation_reached": True,
        "evidence_ref": ["inbox/search-results.json"]}
    b["usage"] = {"iterations_without_new_evidence": iterations_wo_new,
                  "fulltext_reads": fulltext_reads}
    return b


def test_deep_research_happy_path_emits_brief(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 4,
                                        "max_iterations_without_new_evidence": 3,
                                        "max_fulltext_reads": 20,
                                        "max_debug_retries_per_run": 3})
    _write_bundle(run_dir, _brief_bundle())
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_perspectives"] == 1 and report["saturation_reached"] is True
    assert any("research-brief" in p for p in paths)
    _validate_written(paths)


def test_deep_research_budget_counters_are_live(tmp_path):
    budget = {"max_agent_hops": 4, "max_iterations_without_new_evidence": 3,
              "max_fulltext_reads": 20, "max_debug_retries_per_run": 3}
    run_dir = _mk_run(tmp_path, budget=budget)
    _write_bundle(run_dir, _brief_bundle(iterations_wo_new=3))   # cap reached
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "ft", budget=budget)
    _write_bundle(run_dir2, _brief_bundle(fulltext_reads=20))    # fulltext cap reached
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets(run_dir2, "DISCOVER", TS)
    # BudgetExceeded must NOT be absorbed by the repair loop (a budget stop is not repairable)
    run_dir3 = _mk_run(tmp_path / "norepair", budget=budget)
    _write_bundle(run_dir3, _brief_bundle(iterations_wo_new=5))
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets_with_repair(run_dir3, "DISCOVER", TS)


def test_deep_research_usage_omitted_or_null_is_gateblock_not_silent_pass(tmp_path):
    # Adversarial (reviewer LOW): omitting usage must NOT silently pass the budget gate, and a null
    # value must surface a named GateBlock (not a bare TypeError). Both are recoverable via repair.
    budget = {"max_agent_hops": 4, "max_iterations_without_new_evidence": 3,
              "max_fulltext_reads": 20, "max_debug_retries_per_run": 3}
    run_dir = _mk_run(tmp_path, budget=budget)
    b = _brief_bundle()
    del b["usage"]                                              # worker failed to report counts
    _write_bundle(run_dir, b)
    with pytest.raises(GateBlock):
        deep_research.run_dets(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "null", budget=budget)
    b2 = _brief_bundle()
    b2["usage"] = {"iterations_without_new_evidence": None, "fulltext_reads": 4}
    _write_bundle(run_dir2, b2)
    with pytest.raises(GateBlock):
        deep_research.run_dets(run_dir2, "DISCOVER", TS)


def test_deep_research_pre_search_degrades_honestly(tmp_path):
    run_dir = _mk_run(tmp_path)

    def down(url, headers):
        from research_agent_teams.tools.scholar_clients import ScholarLookupError
        raise ScholarLookupError("offline")

    p = deep_research.pre_search(run_dir, "scan topic", TS, transport=down)
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    assert data["records"] == [] and len(data["source_errors"]) == 4   # all sources recorded as failed
    assert data["evidence_rows"] == []                                  # nothing fabricated
