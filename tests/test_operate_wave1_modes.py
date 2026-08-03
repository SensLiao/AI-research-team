"""Operate wave-1 modes: evidence_review / evidence_deep / deep_research recipes.

evidence_deep is now a real staged evidence panel. evidence_review remains a
small honest single-worker review, and deep_research is now a true staged
10-worker perspective panel.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock
from research_agent_teams.operate.bounded_repair import load_state
from research_agent_teams.operate import spine
from research_agent_teams.operate.modes import REGISTRY, deep_research, evidence_deep, evidence_review
from research_agent_teams.operate.output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
)
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools import fulltext_qa
from research_agent_teams.tools.budget_tracker import BudgetExceeded
from research_agent_teams.tools.runstore import read_manifest
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"
def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "test",
                      "request_text": "review the evidence for q",
                      "north_star": {"statement": "q", "in_scope": ["q"], "out_of_scope": []},
                      "budget": budget or {"max_agent_hops": 8, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _current_source_quality(sources):
    rows = []
    for index, source in enumerate(sources, start=1):
        ref = source["ref"]
        rows.append({
            "source_ref": ref, "rank": index,
            "tier": "peer-reviewed" if index < 3 else "preprint",
            "rigor_score": 1.0, "year": source.get("year") or 2024,
            "venue": "Test Venue" if index < 3 else None,
            "rank_notes": "inspectable methodology review",
            "review_status": "VERIFIED", "directness": "direct",
            "study_design": "controlled-experiment", "applicability": "direct",
            "methodology_review": {
                "design_appropriateness": "adequate", "bias_control": "adequate",
                "measurement_validity": "adequate", "statistical_validity": "adequate",
                "reproducibility": "adequate",
            },
            "sample_evaluation_review": {
                "sample_adequacy": "adequate", "evaluation_independence": "adequate",
                "comparator_fairness": "adequate", "uncertainty_reporting": "adequate",
            },
            "evidence_refs": [{"evidence_ref": ref, "locator": "Methods and results",
                               "reported_result": "Protocol and evaluation details inspected."}],
            "limitations": ["bounded to the stated protocol"],
        })
    return {
        "quality_contract_version": "source-methodology/v1", "review_status": "CURRENT",
        "ranked_sources": rows,
        "ranking_rationale": "Methodology dimensions, not rigor_score, determine strength.",
        "n_sources_ranked": len(rows),
    }


def _current_search_trace(claims, sources, query="q"):
    claim_ids = [row["claim_id"] for row in claims]
    critical = [
        {"claim_id": row["claim_id"], "question": row["text"],
         "importance": "critical" if index == 0 else "major"}
        for index, row in enumerate(claims)
    ]
    source_hits = [{"source_ref": row["ref"]} for row in sources]
    findings = [
        {"finding_id": f"F-{cid}", "source_refs": [sources[index % len(sources)]["ref"]],
         "claim_ids": [cid], "finding_kind": "supportive" if index == 0 else "boundary"}
        for index, cid in enumerate(claim_ids)
    ]
    dimensions = ["population", "protocol", "metric"]
    rounds = [{
        "round_index": index, "questions": [question], "source_hits": source_hits,
        "claim_ids_addressed": claim_ids, "contradiction_claim_ids_queried": claim_ids,
        "representativeness_dimensions_queried": dimensions, "findings": findings,
    } for index, question in enumerate((
        "support and boundaries", "counterevidence check", "stopping check"))]
    return {
        "search_contract_version": "evidence-search-trace/v1", "research_question": query,
        "critical_claims": critical, "representativeness_dimensions": dimensions,
        "rounds": rounds, "stop_reason": "semantic_complete", "budget_exhausted": False,
    }


def _good_evidence(query="q"):
    payload = {
        "evidence_table": {
            "evidence_contract_version": "evidence-table/v2",
            "source_quality_report_ref": "evidence/DISCOVER/source-quality-report.artifact.json",
            "search_trace_ref": "evidence/DISCOVER/evidence-search-trace.artifact.json",
            "query": query, "saturation_reached": False,
            "sources": [
                {"id": "s1", "kind": "paper", "ref": "[[page-a]]", "claim_support": "strong"},
                {"id": "s2", "kind": "paper", "ref": "doi:10.1000/x", "claim_support": "moderate"},
                {"id": "s3", "kind": "paper", "ref": "arXiv:2403.12345", "claim_support": "weak"}]},
        "claim_list": {"source_scope": "vault", "claims": [
            {"claim_id": "c1", "text": "method A beats B on metric M", "source_ref": "[[page-a]]"}]},
        "claim_evidence_map": {"mappings": [
            {"claim_id": "c1", "overall_support": "supported",
             "loci": [{"locus_id": "l1", "source_ref": "[[page-a]]", "location": "Table 2",
                       "kind": "table", "reported_result": "A 0.91 vs B 0.85",
                       "supports_claim": True}]}]},
    }
    payload["source_quality_report"] = _current_source_quality(payload["evidence_table"]["sources"])
    payload["evidence_search_trace"] = _current_search_trace(
        payload["claim_list"]["claims"], payload["evidence_table"]["sources"], query)
    return payload


def _good_evidence_deep_bundle(query="q"):
    b = _good_evidence(query)
    b["claim_list"] = {"source_scope": "vault+search", "claims": [
        {"claim_id": "c1", "text": "method A beats B on metric M",
         "source_ref": "[[page-a]]", "kind": "performance", "confidence": "high"},
        {"claim_id": "c2", "text": "method A has weaker cross-dataset robustness",
         "source_ref": "doi:10.1000/x", "kind": "limitation", "confidence": "medium"},
    ]}
    b["claim_evidence_map"] = {"mappings": [
        {"claim_id": "c1", "overall_support": "supported",
         "loci": [{"locus_id": "l1", "source_ref": "[[page-a]]", "location": "Table 2",
                   "kind": "table", "reported_result": "A 0.91 vs B 0.85",
                   "supports_claim": True, "directness": "direct"}],
         "claim_risk": {"level": "low", "note": "direct protocol-matched metric"}},
        {"claim_id": "c2", "overall_support": "partial",
         "loci": [{"locus_id": "l2", "source_ref": "doi:10.1000/x", "location": "Section 4",
                   "kind": "text", "reported_result": "external robustness drops on dataset Z",
                   "supports_claim": True, "directness": "indirect"}],
         "claim_risk": {"level": "medium", "note": "indirect robustness evidence"}},
    ]}
    b["source_quality_report"] = _current_source_quality(b["evidence_table"]["sources"])
    b["evidence_search_trace"] = _current_search_trace(
        b["claim_list"]["claims"], b["evidence_table"]["sources"], query)
    b["contradiction_report"] = {
        "n_claims_checked": 2,
        "summary": "one robustness caveat qualifies the headline performance claim",
        "conflicts": [{"conflict_id": "conf1", "claim_ref_a": "c1", "claim_ref_b": "c2",
                       "kind": "scope-mismatch",
                       "description": "single-dataset win does not imply cross-dataset robustness",
                       "resolution_status": "explained-by-scope"}],
    }
    b["dataset_cards"] = [{
        "dataset_ref": "dataset-z",
        "description": "external robustness test dataset",
        "year": 2024,
        "license": None,
        "modality": "image",
        "size": {"total_samples": 120, "unit": "cases"},
        "splits": [{"name": "test", "n_samples": 120, "split_unit": "patient"}],
        "known_overlaps": [],
        "leakage_risks": [],
        "provenance_notes": "reported by doi:10.1000/x",
    }]
    b["staleness_reports"] = [
        {"source_ref": "[[page-a]]", "status": "CURRENT", "age_years": 1,
         "successor_ref": None, "staleness_rationale": "recent peer-reviewed paper",
         "audit_year": 2026},
        {"source_ref": "doi:10.1000/x", "status": "AGING", "age_years": 2,
         "successor_ref": None, "staleness_rationale": "still relevant but aging",
         "audit_year": 2026},
    ]
    b["landscape_map"] = {
        "domain_query": query,
        "methods": [{"method_id": "m1", "name": "method A",
                     "covered_by_sources": ["[[page-a]]", "doi:10.1000/x"],
                     "representative_result": "0.91 vs 0.85", "notes": "strong in-domain"}],
        "datasets_in_landscape": [{"dataset_ref": "dataset-z", "name": "Dataset Z", "usage_count": 1}],
        "coverage_gaps": [{"gap_id": "gap1", "description": "cross-dataset robustness is only indirectly tested",
                           "gap_kind": "evaluation", "severity": "major"}],
        "n_methods_found": 1,
        "n_gaps_identified": 1,
    }
    b["invalidation_proposals"] = []
    return b


def _write_bundle(run_dir, payload):
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_legacy_marker(run_dir):
    (Path(run_dir) / "inbox" / "citation-legacy-replay.json").write_text(
        json.dumps({
            "contract_version": "citation-legacy-replay/v1",
            "legacy_replay": True,
            "reason": "historical test fixture predates exact claim-span attribution",
            "source_run_ref": "historical-run",
        }),
        encoding="utf-8",
    )


def _write_evidence_review_panel(run_dir, payload, skip_agents=()):
    payload = _with_strict_attribution(payload, run_dir)
    skip = set(skip_agents)
    bundles = {
        "lit-scout": {"evidence_table": payload["evidence_table"]},
        "source-quality-ranker": {"source_quality_report": payload["source_quality_report"]},
        "claim-extractor": {"claim_list": payload["claim_list"]},
        "evidence-search-moderator": {"evidence_search_trace": payload["evidence_search_trace"]},
        "claim-evidence-linker": {"claim_evidence_map": payload["claim_evidence_map"]},
        "citation-coverage-auditor": {"citation_audit": payload["citation_audit"]},
    }
    for agent, bundle in bundles.items():
        if agent in skip:
            continue
        (run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json").write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8")


def _write_evidence_deep_bundles(run_dir, payload, skip_agents=()):
    payload = _with_strict_attribution(payload, run_dir)
    skip = set(skip_agents)
    bundles = {
        "lit-scout": {"evidence_table": payload["evidence_table"]},
        "source-quality-ranker": {"source_quality_report": payload["source_quality_report"]},
        "claim-extractor": {"claim_list": payload["claim_list"]},
        "evidence-search-moderator": {"evidence_search_trace": payload["evidence_search_trace"]},
        "claim-evidence-linker": {"claim_evidence_map": payload["claim_evidence_map"]},
        "citation-coverage-auditor": {"citation_audit": payload.get("citation_audit")},
        "contradiction-miner": {
            "contradiction_report": payload["contradiction_report"],
            "invalidation_proposals": payload.get("invalidation_proposals", []),
        },
        "dataset-card-builder": {"dataset_cards": payload.get("dataset_cards", [])},
        "staleness-auditor": {"staleness_reports": payload.get("staleness_reports", [])},
        "landscape-mapper": {"landscape_map": payload["landscape_map"]},
    }
    for agent, bundle in bundles.items():
        if agent == "citation-coverage-auditor" and bundle["citation_audit"] is None:
            continue
        if agent in skip:
            continue
        (run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json").write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8")


def _with_strict_attribution(payload, run_dir):
    payload = json.loads(json.dumps(payload))
    payload["claim_evidence_map"]["attribution_contract_version"] = "claim-span/v1"
    for mapping in payload["claim_evidence_map"]["mappings"]:
        for locus in mapping["loci"]:
            quote = str(locus["reported_result"])
            snapshot_ref = f"inbox/citation-snapshots/{locus['locus_id']}.txt"
            snapshot = Path(run_dir) / snapshot_ref
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(quote, encoding="utf-8")
            locus.update({
                "support_relation": "entails" if mapping["overall_support"] == "supported" else "partial",
                "span_id": f"SPAN-{locus['locus_id']}",
                "snapshot_ref": snapshot_ref,
                "document_hash": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                "parser_version": "utf-8-char/v1",
                "exact_quote": quote,
                "char_start": 0,
                "char_end": len(quote),
            })
            if locus.get("kind") == "table":
                locus["table_cell_ref"] = "Table 2 / metric-M / method-A"
    payload["citation_audit"] = {
        "contract_version": "citation-attribution/v1",
        "independent_of_linker": True,
        "claim_results": [
            {"claim_id": mapping["claim_id"],
             "verdict": "entails" if mapping["overall_support"] == "supported" else "partial",
             "locator_verified": True,
             "verified_locus_ids": [row["locus_id"] for row in mapping["loci"]],
             "unsupported_locus_ids": [],
             "notes": "independent reread confirmed the exact locator and stated scope"}
            for mapping in payload["claim_evidence_map"]["mappings"]
        ],
    }
    return payload


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


# ---------------- registry + router ----------------

def test_registry_has_twelve_wired_modes():
    assert set(REGISTRY) == {"new_direction", "deep_ideation", "evidence_review", "evidence_deep",
                             "deep_research", "gap_breadth", "venue_readiness", "full_rigor_minimal",
                             "ingest_paper", "read_paper_deep",
                             "manuscript_authoring", "manuscript_review"}
    for mod in REGISTRY.values():
        assert callable(mod.llm_step) and callable(mod.run_dets)


@pytest.mark.parametrize("mode_module", [evidence_review, evidence_deep, deep_research])
def test_evidence_modes_can_prepare_hash_addressed_fulltext_snapshots(
        tmp_path, monkeypatch, mode_module):
    run_dir = _mk_run(tmp_path)
    source = run_dir / "inbox" / "fulltext-docs" / "paper.txt"
    source.parent.mkdir(parents=True)
    source.write_text("source body", encoding="utf-8")
    monkeypatch.setattr(fulltext_qa, "retraction_check", lambda docs: [])
    monkeypatch.setattr(fulltext_qa, "ask", lambda question, docs, retraction_flags=None: {
        "question": question,
        "available": True,
        "reason": "",
        "answer_summary": "local extraction",
        "contexts": [{
            "doc_ref": str(source), "page": 1,
            "excerpt": "The intervention improved the endpoint.", "relevance": 1.0,
        }],
        "retraction_flags": [],
    })
    report_path = mode_module.fulltext_pre(
        str(run_dir), "what changed?", [str(source)], TS)
    assert Path(report_path).is_file()
    manifest_path = run_dir / "inbox" / "citation-snapshots" / "fulltext-contexts.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = run_dir / manifest["snapshot_ref"]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == manifest["document_hash"]
    assert manifest["contexts"][0]["char_start"] == 0
    assert manifest["contexts"][0]["exact_quote"] == snapshot.read_text(encoding="utf-8")


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
    payload = _good_evidence()
    payload["evidence_table"]["sources"][0]["type"] = "paper"
    payload["evidence_table"]["sources"][0]["note"] = "richer worker note"
    payload["evidence_table"]["sources"][0]["notes"] = "richer worker note"
    _write_evidence_review_panel(run_dir, payload)
    paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)
    assert report["evidence_gate"] == "PASS" and report["citation_gate"] == "PASS"
    assert report["representation_normalization"]["preserved_extra_fields"] == 2
    assert any("evidence-table" in p for p in paths)
    assert (
        run_dir / "inbox" / "normalization" /
        "DISCOVER.lit-scout.evidence_table.json"
    ).is_file()
    md = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    assert "## Bottom Line" in md and "## Belief Update" in md
    assert "## Next Most Valuable Evidence" in md and "### `c1`" in md
    _validate_written(paths)
    rpaths, _ = evidence_review.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)
    report_note = json.loads(Path(rpaths[0]).read_text(encoding="utf-8"))["payload"]
    assert "director-review/evidence/evidence-review-brief.md" in report_note["summary"]


def test_evidence_review_accepts_one_unambiguous_bundle_wrapper(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_review_panel(run_dir, _good_evidence())
    for path in (run_dir / "inbox").glob("DISCOVER.*.bundle.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({"data": raw}), encoding="utf-8")

    paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)

    assert report["evidence_gate"] == "PASS"
    assert report["citation_gate"] == "PASS"
    _validate_written(paths)


def test_evidence_review_legacy_bundle_requires_explicit_marker_and_never_passes_attribution(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, _good_evidence())
    with pytest.raises(GateBlock, match="explicit citation-legacy-replay/v1"):
        evidence_review.run_dets(run_dir, "DISCOVER", TS)

    _write_legacy_marker(run_dir)
    paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_attribution_gate"] == "LEGACY_UNVERIFIED"
    assert report["citation_legacy_replay"] is True
    artifact = json.loads(Path(next(
        path for path in paths if "citation-attribution-report" in path
    )).read_text(encoding="utf-8"))
    assert artifact["status"] == "draft"
    assert artifact["payload"]["verdict"] == "UNVERIFIED"


def test_evidence_review_current_panel_cannot_omit_citation_auditor(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_review_panel(
        run_dir, _good_evidence(), skip_agents={"citation-coverage-auditor"})
    with pytest.raises(GateBlock, match="citation-coverage-auditor"):
        evidence_review.run_dets(run_dir, "DISCOVER", TS)


def test_evidence_review_repair_loop_feeds_back_then_escalates(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 6, "max_debug_retries_per_run": 2})
    bad = _good_evidence()
    bad["evidence_search_trace"]["stop_reason"] = "budget_exhausted"
    bad["evidence_search_trace"]["budget_exhausted"] = True
    _write_evidence_review_panel(run_dir, bad)

    first = evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert first[0] == "retry" and "semantic evidence search" in first[1]
    second = evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert second[0] == "retry"
    with pytest.raises(GateBlock):
        evidence_review.run_dets_with_repair(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "fresh")
    _write_evidence_review_panel(run_dir2, _good_evidence())
    ok = evidence_review.run_dets_with_repair(run_dir2, "DISCOVER", TS)
    assert ok[0] == "ok"


def test_evidence_review_llm_step_shape(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = evidence_review.llm_step(run_dir, "DISCOVER", "my question", model_policy="default")
    assert spec["label"] == "evidence-review-panel"
    assert [worker["label"] for worker in spec["workers"]] == [
        "lit-scout", "source-quality-ranker", "claim-extractor", "evidence-search-moderator",
        "claim-evidence-linker", "citation-coverage-auditor"]
    assert all(worker["model"] == "sonnet" for worker in spec["workers"])
    assert "my question" in spec["workers"][0]["prompt"]
    assert "rigor_score" in spec["workers"][1]["prompt"]
    assert "Do not link or" in spec["workers"][2]["prompt"]
    assert "Never emit `saturation_reached`" in spec["workers"][3]["prompt"]
    assert "claim-span/v1" in spec["workers"][4]["prompt"]
    assert "independent citation auditor" in spec["workers"][5]["prompt"]
    assert all("NORTH STAR" in worker["prompt"] for worker in spec["workers"])
    assert evidence_review.llm_step(run_dir, "REPORT", "q") is None
    assert all(worker["model"] == "opus" for worker in
               evidence_review.llm_step(run_dir, "DISCOVER", "q")["workers"])


def test_evidence_review_strict_panel_emits_independent_attribution(tmp_path):
    run_dir = _mk_run(tmp_path)
    payload = _good_evidence_deep_bundle()
    _write_evidence_review_panel(run_dir, payload)
    paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_attribution_gate"] == "PASS"
    assert report["claim_completeness"] == 0.5
    assert any("citation-attribution-report" in path for path in paths)


def test_evidence_review_markdown_quality_failure_delivers_fallback(tmp_path, monkeypatch):
    run_dir = _mk_run(tmp_path)
    _write_evidence_review_panel(run_dir, _good_evidence())

    def fail_markdown(*args, **kwargs):
        raise ValueError("evidence_review Markdown quality BLOCK: missing belief update")

    monkeypatch.setattr(evidence_review, "write_research_brief_markdown", fail_markdown)
    _paths, report = evidence_review.run_dets(run_dir, "DISCOVER", TS)
    assert report["markdown_delivery_status"] == "USABLE_WITH_CAVEATS"
    fallback = Path(report["director_markdown_brief"])
    assert fallback.is_file()
    assert "USABLE_WITH_CAVEATS" in fallback.read_text(encoding="utf-8")


# ---------------- evidence_deep ----------------

def test_evidence_deep_writes_panel_artifacts_and_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    b["invalidation_proposals"] = [{
        "claim_slug": "old-claim-page", "invalidated_by_slug": "newer-result-page",
        "edge_type": "supersedes", "invalid_at": "2026-05-01",
        "basis": "newer protocol-matched result replaces the old number",
        "evidence_ref": ["conf1", "[[newer-result-page]]"]}]
    _write_evidence_deep_bundles(run_dir, b)
    paths, report = evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_conflicts"] == 1 and report["n_invalidation_proposals"] == 1
    for needle in ("source-quality-report", "claim-list", "claim-evidence-map",
                   "contradiction-report", "dataset-card", "staleness", "landscape-map"):
        assert any(needle in p for p in paths), f"missing {needle}"
    md_path = Path(report["director_markdown_brief"])
    assert md_path.is_file()
    md = md_path.read_text(encoding="utf-8")
    assert "Evidence Grade And Source Quality" in md and "Claim-Evidence Ledger" in md
    assert "Belief Update" in md and "Next Most Valuable Evidence" in md
    _validate_written(paths)
    inv = json.loads(Path(next(p for p in paths if "invalidation" in p)).read_text(encoding="utf-8"))
    assert inv["status"] == "draft"


def test_evidence_deep_accepts_one_unambiguous_bundle_wrapper(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_deep_bundles(run_dir, _good_evidence_deep_bundle())
    for path in (run_dir / "inbox").glob("DISCOVER.*.bundle.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({"payload": raw}), encoding="utf-8")

    paths, report = evidence_deep.run_dets(run_dir, "DISCOVER", TS)

    assert report["citation_attribution_gate"] == "PASS"
    assert any("landscape-map" in path for path in paths)


def test_evidence_deep_strict_span_contract_runs_independent_attribution(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    _write_evidence_deep_bundles(run_dir, b)
    paths, report = evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_attribution_gate"] == "PASS"
    assert report["citation_correctness"] == 1.0
    assert report["claim_completeness"] == 0.5
    assert any("citation-attribution-report" in path for path in paths)
    md = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    assert "Independent span attribution: gate=`PASS`" in md
    assert "citation correctness=`1.0`" in md


def test_evidence_deep_blocks_invented_slug_proposal(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    b["invalidation_proposals"] = [{
        "claim_slug": "Not A Slug!", "invalidated_by_slug": "ok-page",
        "edge_type": "refutes", "invalid_at": "2026-05-01", "basis": "x", "evidence_ref": ["e"]}]
    _write_evidence_deep_bundles(run_dir, b)
    with pytest.raises(GateBlock) as ei:
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "never invent a slug" in str(ei.value)


def test_evidence_deep_missing_worker_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_deep_bundles(run_dir, _good_evidence_deep_bundle(), skip_agents={"staleness-auditor"})
    with pytest.raises(GateBlock) as ei:
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "staleness-auditor" in str(ei.value) and "missing worker bundle" in str(ei.value)


def test_evidence_deep_staleness_extra_is_zero_worker_normalization(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    b["staleness_reports"][0]["source_id"] = "redundant-but-forbidden"
    _write_evidence_deep_bundles(run_dir, b)

    paths, report = evidence_deep.run_dets(run_dir, "DISCOVER", TS)

    assert report["representation_normalization"]["preserved_extra_fields"] >= 1
    sidecar = (
        run_dir / "inbox" / "normalization" /
        "DISCOVER.staleness-auditor.staleness-report-1.json"
    )
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["preserved_extras"][0][
        "value"
    ] == "redundant-but-forbidden"
    assert b["staleness_reports"][0]["source_id"] == "redundant-but-forbidden"
    stale_path = next(Path(path) for path in paths if "staleness-1" in path)
    assert "source_id" not in json.loads(stale_path.read_text(encoding="utf-8"))["payload"]
    assert not (run_dir / "inbox" / "repair-state.json").exists()


def test_evidence_deep_source_quality_contract_targets_ranker(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    b["source_quality_report"].pop("quality_contract_version")
    b["source_quality_report"].pop("review_status")
    _write_evidence_deep_bundles(run_dir, b)

    with pytest.raises(TargetedGateBlock) as ei:
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)

    assert ei.value.defects[0]["target_agents"] == ["source-quality-ranker"]
    assert "source-methodology/v1" in str(ei.value)


def test_evidence_deep_uses_hash_linked_supplement_bundle(tmp_path):
    """A bounded repair must be consumed by the deterministic evidence gate."""
    run_dir = _mk_run(tmp_path)
    _write_evidence_deep_bundles(run_dir, _good_evidence_deep_bundle())
    logical = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    original = json.loads(logical.read_text(encoding="utf-8"))
    original["landscape_map"]["summary"] = "original landscape finding"
    logical.write_text(json.dumps(original), encoding="utf-8")
    node = {
        "id": "landscape-mapper",
        "label": "landscape-mapper",
        "output_path": logical,
        "output_rel": "inbox/DISCOVER.landscape-mapper.bundle.json",
    }
    plan = prepare_plan(
        run_dir, "DISCOVER", 1, [node], {"landscape-mapper"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected_path = physical_output(run_dir, plan, "landscape-mapper")
    corrected = json.loads(logical.read_text(encoding="utf-8"))
    corrected["landscape_map"]["summary"] = "corrected landscape finding"
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps(corrected), encoding="utf-8")
    finalize_output(run_dir, "DISCOVER", 1, "landscape-mapper", TS)

    bundles = evidence_deep._load_worker_bundles(run_dir)
    assert bundles["landscape_map"]["summary"] == "corrected landscape finding"
    assert json.loads(logical.read_text(encoding="utf-8"))["landscape_map"]["summary"] == (
        "original landscape finding"
    )


def test_evidence_deep_current_panel_cannot_omit_citation_auditor(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_deep_bundles(
        run_dir, _good_evidence_deep_bundle(), skip_agents={"citation-coverage-auditor"})
    with pytest.raises(GateBlock, match="citation-coverage-auditor"):
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)


def test_evidence_deep_evidence_shortfall_still_delivers_caveated_brief(tmp_path):
    """A non-pass evidence grade must not hide a readable attributed briefing."""
    run_dir = _mk_run(tmp_path)
    b = _good_evidence_deep_bundle()
    for row in b["source_quality_report"]["ranked_sources"]:
        row["applicability"] = "partial"
    _write_evidence_deep_bundles(run_dir, b)

    with pytest.raises(GateBlock, match="too few strong-support sources"):
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)

    brief = run_dir / "director-review" / "evidence" / "evidence-deep-brief.md"
    assert brief.is_file()
    text = brief.read_text(encoding="utf-8")
    assert "evidence=`BLOCK`" in text
    assert "## Claim-Evidence Ledger" in text


def test_evidence_deep_citation_block_still_renders_brief_without_checkpoint(tmp_path):
    """Usability-first delivery must not turn a citation BLOCK into a committed stage."""
    runs = tmp_path / "runs"
    plan = spine.begin(
        str(runs), "citation-block", "review evidence for q", "evidence_deep", TS,
        north_star={"statement": "q", "in_scope": ["q"], "out_of_scope": []},
    )
    run_dir = Path(plan["run_dir"])
    b = _good_evidence_deep_bundle()
    b["claim_evidence_map"]["mappings"][0]["loci"][0]["supports_claim"] = False
    _write_evidence_deep_bundles(run_dir, b)
    spine.open_stage(run_dir, "DISCOVER", TS)

    with pytest.raises(GateBlock, match="citation gate BLOCK"):
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)

    brief = run_dir / "director-review" / "evidence" / "evidence-deep-brief.md"
    assert brief.is_file()
    text = brief.read_text(encoding="utf-8")
    assert "citation=`BLOCK`" in text
    assert "## Claim-Evidence Ledger" in text
    assert read_manifest(run_dir)["completed_work"] == []
    assert spine.next_stage(run_dir) == "DISCOVER"


def test_evidence_deep_current_panel_cannot_drop_claim_span_version(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_evidence_deep_bundles(run_dir, _good_evidence_deep_bundle())
    linker = run_dir / "inbox" / "DISCOVER.claim-evidence-linker.bundle.json"
    payload = json.loads(linker.read_text(encoding="utf-8"))
    payload["claim_evidence_map"].pop("attribution_contract_version")
    linker.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GateBlock, match="must declare claim-span/v1"):
        evidence_deep.run_dets(run_dir, "DISCOVER", TS)


def test_evidence_deep_llm_step_is_panel(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = evidence_deep.llm_step(run_dir, "DISCOVER", "review evidence", model_policy="default")
    assert spec["label"] == "evidence-deep-panel"
    assert len(spec["workers"]) == 10
    assert spec["worker_order"][0] == "lit-scout"
    assert spec["worker_order"][-1] == "landscape-mapper"
    assert all(w["output"].endswith(f"inbox/DISCOVER.{w['label']}.bundle.json") for w in spec["workers"])
    assert "citation-coverage-auditor" in spec["panel_note"]
    by_label = {worker["label"]: worker["prompt"] for worker in spec["workers"]}
    assert "rigor_score" in by_label["source-quality-ranker"]
    assert "full research question" in by_label["source-quality-ranker"]
    assert "never upgrade applicability" in by_label["source-quality-ranker"]
    assert "Never emit or self-set saturation" in by_label["evidence-search-moderator"]
    assert "independently audit claim support" in by_label["citation-coverage-auditor"]
    assert "citation-attribution/v1" in by_label["citation-coverage-auditor"]
    assert "project/idea/experiment" in by_label["landscape-mapper"]
    assert spec["parallel_groups"] == evidence_deep.EVIDENCE_DEEP_PARALLEL_GROUPS
    assert len(spec["parallel_groups"]) == 7
    workers = {worker["label"]: worker for worker in spec["workers"]}
    assert workers["claim-extractor"]["depends_on"] == ["lit-scout"]
    assert workers["dataset-card-builder"]["depends_on"] == ["lit-scout"]
    assert "dataset-card-builder" in workers["landscape-mapper"]["depends_on"]
    assert evidence_deep.llm_step(run_dir, "REPORT", "q") is None


# ---------------- deep_research ----------------

def _research_markdown():
    return "\n".join([
        "# Research Brief - scan topic",
        "",
        "## Bottom Line",
        "The field has credible evidence that method A improves the in-domain metric, but the "
        "most useful research decision is to test robustness and failure modes before making a "
        "broad claim. The next good experiment is a protocol-matched cross-dataset validation.",
        "",
        "## Perspective Findings",
        "### P1 Methods and datasets",
        "Method A appears strongest when the benchmark matches its assumptions, but source quality "
        "still depends on protocol matching and whether the dataset split is patient-level.",
        "### P2 Open problems",
        "The open problem is not whether A can win one table; it is whether the win survives a "
        "domain shift and whether a negative result would still clarify the method boundary.",
        "### P3 Transfer",
        "Adjacent domains suggest the mechanism may transfer only when the target has comparable "
        "structure and annotation density. This should become an explicit transfer hypothesis.",
        "### P4 Weaknesses",
        "The strongest skepticism is that the current evidence is partly indirect and lacks a "
        "robustness-focused benchmark.",
        "",
        "## Evidence Map",
        "- Claim c1 is supported by [[page-a]] Table 2.",
        "- Claim c2 is partially supported by doi:10.1000/x Section 4.",
        "",
        "## Disagreements",
        "The main live disagreement is scope: in-domain performance does not prove robustness.",
        "",
        "## Actionable Next Questions",
        "- Run cross-dataset robustness on Dataset Z.",
        "- Define a kill criterion: if A loses under protocol-matched external validation, stop the broad claim.",
        "",
        "## Director Decision Boundary",
        "Use this brief to design the next evidence-gathering run. Do not treat it as a promoted "
        "database conclusion until the validation result is reviewed.",
    ])


def _good_deep_research_panel(iterations_wo_new=1, fulltext_reads=4):
    b = _good_evidence_deep_bundle("scan topic")
    notes = [
        {"perspective_id": "P1", "angle": "methods, models, datasets, and benchmark state",
         "questions": ["what methods dominate?", "which datasets define evidence?"],
         "finding_summary": "Method A has the clearest in-domain metric advantage, but the benchmark state still depends on protocol matching and patient-level splits. The director should not infer robustness from one table.",
         "source_refs": ["[[page-a]]", "doi:10.1000/x"],
         "coverage_limits": ["limited cross-dataset evidence"],
         "actionable_opportunities": ["run protocol-matched robustness validation"],
         "kill_criteria": ["A loses under external validation"], "confidence": "medium"},
        {"perspective_id": "P2", "angle": "open problems, unresolved gaps, and next experiments",
         "questions": ["what is unresolved?", "what should be tested first?"],
         "finding_summary": "The live open problem is whether the headline improvement survives domain shift. A useful next experiment would isolate data shift from architecture advantage.",
         "source_refs": ["[[page-a]]", "arXiv:2403.12345"],
         "coverage_limits": ["weak evidence for negative results"],
         "actionable_opportunities": ["design a robustness-first experiment"],
         "kill_criteria": ["no improvement over B after matched tuning"], "confidence": "medium"},
        {"perspective_id": "P3", "angle": "adjacent-field transfer and mechanism analogies",
         "questions": ["what mechanism transfers?", "where does analogy fail?"],
         "finding_summary": "Adjacent-field evidence suggests transfer is plausible only if the target task preserves the structural assumptions. The analogy is useful as a hypothesis, not as proof.",
         "source_refs": ["doi:10.1000/x"],
         "coverage_limits": ["transfer evidence is indirect"],
         "actionable_opportunities": ["state the transfer mechanism before experimenting"],
         "kill_criteria": ["mechanism does not apply under target annotations"], "confidence": "low"},
        {"perspective_id": "P4", "angle": "failure modes, negative evidence, and reasons not to overclaim",
         "questions": ["what would break the claim?", "what are the reviewer attacks?"],
         "finding_summary": "The main weakness is overclaim risk: a single benchmark can support a local performance claim but not a broad reliability claim. Reviewers will attack robustness and comparability.",
         "source_refs": ["doi:10.1000/x", "arXiv:2403.12345"],
         "coverage_limits": ["few reported failures"],
         "actionable_opportunities": ["collect failure cases and report them explicitly"],
         "kill_criteria": ["failure cases dominate the target deployment slice"], "confidence": "medium"},
    ]
    b["perspective_notes"] = notes
    b["research_brief"] = {
        "topic": "scan topic",
        "perspectives": [{"perspective_id": n["perspective_id"], "angle": n["angle"],
                          "questions": n["questions"]} for n in notes],
        "findings": [{"perspective_id": n["perspective_id"], "summary": n["finding_summary"],
                      "source_refs": n["source_refs"]} for n in notes],
        "bottom_line": "Method A is promising in-domain, but the decision-relevant next step is robustness validation.",
        "consensus": ["in-domain improvement is plausible", "robustness evidence is incomplete"],
        "live_disagreements": ["whether in-domain evidence transfers to external datasets"],
        "evidence_gaps": ["protocol-matched external validation", "negative result analysis"],
        "actionable_next_questions": ["run Dataset Z robustness", "define kill criteria before GPU spend"],
        "iterations_used": 2,
        "saturation_reached": False,
        "evidence_ref": ["inbox/search-results.json", "[[page-a]]", "doi:10.1000/x"],
    }
    b["usage"] = {"iterations_without_new_evidence": iterations_wo_new,
                  "fulltext_reads": fulltext_reads}
    b["research_markdown_brief"] = {
        "topic": "scan topic",
        "markdown": _research_markdown(),
        "evidence_refs": ["[[page-a]]", "doi:10.1000/x", "arXiv:2403.12345"],
        "perspective_ids": ["P1", "P2", "P3", "P4"],
        "quality_caveats": ["robustness evidence is incomplete"],
    }
    return b


def _write_deep_research_bundles(run_dir, payload, skip_agents=()):
    payload = _with_strict_attribution(payload, run_dir)
    skip = set(skip_agents)
    note_by_id = {n["perspective_id"]: n for n in payload["perspective_notes"]}
    bundles = {
        "lit-scout": {"evidence_table": payload["evidence_table"]},
        "source-quality-ranker": {"source_quality_report": payload["source_quality_report"]},
        "model-dataset-scout": {"research_perspective_note": note_by_id["P1"]},
        "future-work-miner": {"research_perspective_note": note_by_id["P2"]},
        "cross-domain-transfer-scout": {"research_perspective_note": note_by_id["P3"]},
        "weakness-spotter": {"research_perspective_note": note_by_id["P4"]},
        "claim-extractor": {"claim_list": payload["claim_list"]},
        "evidence-search-moderator": {"evidence_search_trace": payload["evidence_search_trace"]},
        "claim-evidence-linker": {"claim_evidence_map": payload["claim_evidence_map"]},
        "citation-coverage-auditor": {"citation_audit": payload.get("citation_audit")},
        "contradiction-miner": {"contradiction_report": payload["contradiction_report"]},
        "landscape-mapper": {"research_brief": payload["research_brief"],
                             "usage": payload.get("usage"),
                             "research_markdown_brief": payload["research_markdown_brief"]},
    }
    for agent, bundle in bundles.items():
        if agent == "citation-coverage-auditor" and bundle["citation_audit"] is None:
            continue
        if agent in skip:
            continue
        (run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json").write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8")


def test_deep_research_happy_path_emits_brief(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 10,
                                        "max_iterations_without_new_evidence": 3,
                                        "max_fulltext_reads": 20,
                                        "max_debug_retries_per_run": 3})
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_perspectives"] == 4 and report["saturation_reached"] is True
    assert any("research-brief" in p for p in paths)
    assert any("research-markdown-brief" in p for p in paths)
    assert Path(report["director_markdown_brief"]).is_file()
    md = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    assert "Perspective Synthesis" in md and "Evidence Grade And Source Quality" in md
    assert "Belief Update" in md and "Next Most Valuable Evidence" in md
    _validate_written(paths)


def test_deep_research_accepts_one_unambiguous_bundle_wrapper(tmp_path):
    run_dir = _mk_run(tmp_path, budget={
        "max_agent_hops": 10,
        "max_iterations_without_new_evidence": 3,
        "max_fulltext_reads": 20,
        "max_debug_retries_per_run": 3,
    })
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    for agent in deep_research.PANEL_AGENTS:
        path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({"payload": raw}), encoding="utf-8")

    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)

    assert report["citation_attribution_gate"] == "PASS"
    assert any("research-brief" in path for path in paths)


def test_deep_research_blank_worker_markdown_is_delivery_metadata_not_science_gate(tmp_path):
    run_dir = _mk_run(tmp_path, budget={
        "max_agent_hops": 10,
        "max_iterations_without_new_evidence": 3,
        "max_fulltext_reads": 20,
        "max_debug_retries_per_run": 3,
    })
    payload = _good_deep_research_panel()
    payload["research_markdown_brief"]["markdown"] = ""
    payload["research_markdown_brief"]["perspective_ids"] = []
    _write_deep_research_bundles(run_dir, payload)

    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)

    assert Path(report["director_markdown_brief"]).is_file()
    assert all(Path(path).is_file() for path in paths)


def test_deep_research_missing_worker_markdown_uses_rendered_brief_for_typed_artifact(tmp_path):
    run_dir = _mk_run(tmp_path, budget={
        "max_agent_hops": 10,
        "max_iterations_without_new_evidence": 3,
        "max_fulltext_reads": 20,
        "max_debug_retries_per_run": 3,
    })
    payload = _good_deep_research_panel()
    expected_refs = {
        str(source["ref"])
        for source in payload["evidence_table"]["sources"]
        if source.get("ref")
    }
    expected_perspectives = {
        str(note["perspective_id"]) for note in payload["perspective_notes"]
    }
    _write_deep_research_bundles(run_dir, payload)
    mapper_path = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    mapper_bundle = json.loads(mapper_path.read_text(encoding="utf-8"))
    mapper_bundle.pop("research_markdown_brief")
    mapper_path.write_text(json.dumps(mapper_bundle, ensure_ascii=False), encoding="utf-8")

    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)

    rendered = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    artifact_path = next(
        Path(path) for path in paths
        if path.endswith("research-markdown-brief.artifact.json")
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["payload"]["markdown"] == rendered
    assert set(artifact["payload"]["evidence_refs"]) == expected_refs
    assert set(artifact["payload"]["perspective_ids"]) == expected_perspectives
    assert artifact["created_by"] == "deterministic-research-brief-renderer"


def test_deep_research_normalizes_foundation_model_source_to_repo():
    """A worker's subject label must not terminally fail an otherwise valid evidence panel."""
    bundle = {"evidence_table": {"sources": [{"id": "s1", "kind": "model"}]}}

    deep_research._normalize_compat_enums(bundle)

    assert bundle["evidence_table"]["sources"][0]["kind"] == "repo"


def test_deep_research_normalizes_sourcebound_rich_json_before_truth_gates(tmp_path):
    """Reproduce the PET/CT run shape: formatting is projected, truth gates still run."""
    run_dir = _mk_run(tmp_path, budget={
        "max_agent_hops": 12,
        "max_iterations_without_new_evidence": 3,
        "max_fulltext_reads": 20,
        "max_debug_retries_per_run": 3,
    })
    payload = _good_deep_research_panel()
    for index, source in enumerate(payload["evidence_table"]["sources"]):
        source["type"] = "preprint" if index == 1 else source["kind"]
        source["note"] = source.get("notes") or f"rich source note {index}"
        source["notes"] = source["note"]
    payload["claim_list"]["source_scope"] = ["PET/CT", "intent correction"]
    rich_kinds = ["novelty_boundary", "mechanism_boundary"]
    for index, claim in enumerate(payload["claim_list"]["claims"]):
        claim["kind"] = rich_kinds[index % len(rich_kinds)]
        claim["confidence"] = 0.90 - index * 0.05
    first_locus = payload["claim_evidence_map"]["mappings"][0]["loci"][0]
    first_locus["kind"] = "figure"
    first_locus["figure_region_ref"] = "Figure 2, labels and caption"
    _write_deep_research_bundles(run_dir, payload)
    raw_scout = run_dir / "inbox" / "DISCOVER.lit-scout.bundle.json"
    raw_hash = hashlib.sha256(raw_scout.read_bytes()).hexdigest()

    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)

    assert report["citation_attribution_gate"] == "PASS"
    assert report["representation_normalization"]["normalized_payloads"] >= 3
    assert report["representation_normalization"]["preserved_extra_fields"] == (
        2 * len(payload["evidence_table"]["sources"])
    )
    assert hashlib.sha256(raw_scout.read_bytes()).hexdigest() == raw_hash
    table_path = next(Path(path) for path in paths if "evidence-table" in path)
    rows = json.loads(table_path.read_text(encoding="utf-8"))["payload"]["sources"]
    assert all("type" not in row and "note" not in row for row in rows)
    assert (
        run_dir / "inbox" / "normalization" /
        "DISCOVER.lit-scout.evidence_table.json"
    ).is_file()
    claim_sidecar = json.loads((
        run_dir / "inbox" / "normalization" /
        "DISCOVER.claim-evidence-linker.claim_evidence_map.json"
    ).read_text(encoding="utf-8"))
    assert "figure-caption-char-span-to-text-locus" in {
        row["rule"] for row in claim_sidecar["changes"]
    }
    assert not (run_dir / "inbox" / "repair-state.json").exists()


def test_deep_research_never_normalizes_away_control_or_truth_fields(tmp_path):
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    payload["evidence_table"]["selected"] = True
    _write_deep_research_bundles(run_dir, payload)

    outcome = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)

    assert outcome[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    assert attempt["target_agents"] == ["lit-scout"]
    assert "cannot be removed as formatting" in attempt["reason"]


def test_deep_research_resolves_local_source_ids_to_citable_refs():
    """Local evidence ids are join keys; citation outputs must carry the frozen source ref."""
    bundle = {
        "evidence_table": {"sources": [
            {"id": "s1", "ref": "https://example.org/paper", "kind": "paper"}
        ]},
        "claim_list": {"claims": [
            {"claim_id": "c1", "source_ref": "s1", "kind": "method"}
        ]},
        "claim_evidence_map": {"mappings": [{
            "claim_id": "c1", "loci": [{"source_ref": "s1"}]
        }]},
    }

    deep_research._normalize_compat_enums(bundle)

    assert bundle["claim_list"]["claims"][0]["source_ref"] == "https://example.org/paper"
    assert bundle["claim_evidence_map"]["mappings"][0]["loci"][0]["source_ref"] == \
        "https://example.org/paper"


def test_deep_research_strict_attribution_and_blind_perspectives(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 12,
                                        "max_iterations_without_new_evidence": 3,
                                        "max_fulltext_reads": 20,
                                        "max_debug_retries_per_run": 3})
    payload = _good_deep_research_panel()
    _write_deep_research_bundles(run_dir, payload)
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_attribution_gate"] == "PASS"
    assert report["claim_completeness"] == 0.5
    assert any("citation-attribution-report" in path for path in paths)


def test_deep_research_strength_shortfall_delivers_caveated_landscape(tmp_path):
    """A landscape can be readable without pretending that its narrow hypothesis is proven."""
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    for row in payload["source_quality_report"]["ranked_sources"]:
        row["applicability"] = "partial"
    _write_deep_research_bundles(run_dir, payload)

    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)

    assert report["evidence_gate"] == "BLOCK"
    assert report["markdown_delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any("too few strong-support sources" in reason
               for reason in report["evidence_gate_reasons"])
    assert Path(report["director_markdown_brief"]).is_file()
    verdict_path = next(Path(path) for path in paths if "evidence-verdict" in path)
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["payload"]["verdict"] == "BLOCK"
    assert verdict["status"] == "draft"
    assert all(json.loads(Path(path).read_text(encoding="utf-8"))["status"] != "blocked"
               for path in paths)


def test_caveated_deep_research_can_complete_and_record_its_caveat(tmp_path):
    """A strength-only gap is ledgered as a caveat, not an uncommittable retry loop."""
    plan = spine.begin(str(tmp_path / "runs"), "caveated-research", "scan a research field",
                       "deep_research", TS)
    run_dir = Path(plan["run_dir"])
    payload = _good_deep_research_panel()
    for row in payload["source_quality_report"]["ranked_sources"]:
        row["applicability"] = "partial"
    _write_deep_research_bundles(run_dir, payload)

    spine.open_stage(run_dir, "DISCOVER", TS)
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert report["markdown_delivery_status"] == "USABLE_WITH_CAVEATS"
    assert spine.commit_stage(run_dir, "DISCOVER", paths, TS)["next_stage"] == "REPORT"
    spine.open_stage(run_dir, "REPORT", TS)
    report_paths, _ = deep_research.run_dets(run_dir, "REPORT", TS)
    assert spine.commit_stage(run_dir, "REPORT", report_paths, TS)["done"] is True

    note = json.loads((run_dir / "evidence" / "REPORT" / "report-note.artifact.json")
                      .read_text(encoding="utf-8"))["payload"]
    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert note["delivery_caveats"]
    assert spine.status(run_dir)["run_status"] == "done"


def test_deep_research_repairs_non_strength_evidence_defects_at_input_owners(tmp_path):
    """Source/search defects must never be misrouted to the final landscape writer."""
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    payload["source_quality_report"]["ranked_sources"][0]["review_status"] = "UNVERIFIED"
    _write_deep_research_bundles(run_dir, payload)

    outcome = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)

    assert outcome[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    assert set(attempt["target_agents"]) == {
        "lit-scout", "source-quality-ranker", "evidence-search-moderator",
    }
    assert "landscape-mapper" in attempt["refresh_agents"]


def test_deep_research_repairs_unfrozen_search_hit_at_input_owners(tmp_path):
    """A hit absent from the frozen evidence table is a retrieval defect, never discarded."""
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    payload["evidence_search_trace"]["rounds"][0]["source_hits"].append({
        "source_ref": "doi:10.9999/unfrozen-counterevidence",
    })
    _write_deep_research_bundles(run_dir, payload)

    outcome = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)

    assert outcome[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    assert set(attempt["target_agents"]) == {
        "lit-scout", "source-quality-ranker", "evidence-search-moderator",
    }
    assert "landscape-mapper" in attempt["refresh_agents"]


def test_deep_research_budget_counters_are_live(tmp_path):
    budget = {"max_agent_hops": 10, "max_iterations_without_new_evidence": 3,
              "max_fulltext_reads": 20, "max_debug_retries_per_run": 3}
    run_dir = _mk_run(tmp_path, budget=budget)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel(iterations_wo_new=3))
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "ft", budget=budget)
    _write_deep_research_bundles(run_dir2, _good_deep_research_panel(fulltext_reads=20))
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets(run_dir2, "DISCOVER", TS)

    run_dir3 = _mk_run(tmp_path / "norepair", budget=budget)
    _write_deep_research_bundles(run_dir3, _good_deep_research_panel(iterations_wo_new=5))
    with pytest.raises(BudgetExceeded):
        deep_research.run_dets_with_repair(run_dir3, "DISCOVER", TS)


def test_deep_research_usage_omitted_or_null_is_gateblock_not_silent_pass(tmp_path):
    budget = {"max_agent_hops": 10, "max_iterations_without_new_evidence": 3,
              "max_fulltext_reads": 20, "max_debug_retries_per_run": 3}
    run_dir = _mk_run(tmp_path, budget=budget)
    b = _good_deep_research_panel()
    del b["usage"]
    _write_deep_research_bundles(run_dir, b)
    with pytest.raises(GateBlock):
        deep_research.run_dets(run_dir, "DISCOVER", TS)

    run_dir2 = _mk_run(tmp_path / "null", budget=budget)
    b2 = _good_deep_research_panel()
    b2["usage"] = {"iterations_without_new_evidence": None, "fulltext_reads": 4}
    _write_deep_research_bundles(run_dir2, b2)
    with pytest.raises(GateBlock):
        deep_research.run_dets(run_dir2, "DISCOVER", TS)


def test_deep_research_missing_perspective_worker_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel(), skip_agents={"future-work-miner"})
    with pytest.raises(GateBlock) as ei:
        deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert "future-work-miner" in str(ei.value) and "missing worker bundle" in str(ei.value)


def test_deep_research_uses_hash_linked_supplement_bundle(tmp_path):
    """The deep-research deterministic gate must consume a completed repair."""
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    logical = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    original = json.loads(logical.read_text(encoding="utf-8"))
    original["research_brief"]["bottom_line"] = "original research brief"
    logical.write_text(json.dumps(original), encoding="utf-8")
    node = {
        "id": "landscape-mapper",
        "label": "landscape-mapper",
        "output_path": logical,
        "output_rel": "inbox/DISCOVER.landscape-mapper.bundle.json",
    }
    plan = prepare_plan(
        run_dir, "DISCOVER", 1, [node], {"landscape-mapper"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected_path = physical_output(run_dir, plan, "landscape-mapper")
    corrected = json.loads(logical.read_text(encoding="utf-8"))
    corrected["research_brief"]["bottom_line"] = "corrected research brief"
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps(corrected), encoding="utf-8")
    finalize_output(run_dir, "DISCOVER", 1, "landscape-mapper", TS)

    bundles = deep_research._load_worker_bundles(run_dir)
    assert bundles["research_brief"]["bottom_line"] == "corrected research brief"


def test_deep_research_current_panel_cannot_omit_citation_auditor(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(
        run_dir, _good_deep_research_panel(), skip_agents={"citation-coverage-auditor"})
    with pytest.raises(GateBlock, match="citation-coverage-auditor"):
        deep_research.run_dets(run_dir, "DISCOVER", TS)


def test_deep_research_llm_step_is_panel(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = deep_research.llm_step(run_dir, "DISCOVER", "scan topic", model_policy="default")
    assert spec["label"] == "deep-research-panel"
    assert len(spec["workers"]) == 12
    assert spec["worker_order"][0] == "lit-scout"
    assert spec["worker_order"][-1] == "landscape-mapper"
    assert all(w["output"].endswith(f"inbox/DISCOVER.{w['label']}.bundle.json") for w in spec["workers"])
    assert "parallel/blind" in spec["panel_note"]
    by_label = {worker["label"]: worker["prompt"] for worker in spec["workers"]}
    assert "what changed in belief" in by_label["model-dataset-scout"]
    assert "DISCOVER.future-work-miner.bundle.json" not in by_label["model-dataset-scout"]
    assert "DISCOVER.model-dataset-scout.bundle.json" not in by_label["future-work-miner"]
    assert "independently audit claim support" in by_label["citation-coverage-auditor"]
    assert "highest expected" in by_label["landscape-mapper"]
    assert spec["parallel_groups"] == deep_research.DEEP_RESEARCH_PARALLEL_GROUPS
    assert len(spec["parallel_groups"]) == 8
    workers = {worker["label"]: worker for worker in spec["workers"]}
    assert workers["citation-coverage-auditor"]["depends_on"] == [
        "lit-scout", "claim-extractor", "claim-evidence-linker",
    ]
    assert "citation-coverage-auditor" not in workers["contradiction-miner"]["depends_on"]
    assert deep_research.llm_step(run_dir, "REPORT", "q") is None


def test_deep_research_pre_search_degrades_honestly(tmp_path):
    run_dir = _mk_run(tmp_path)

    def down(url, headers):
        from research_agent_teams.tools.scholar_clients import ScholarLookupError
        raise ScholarLookupError("offline")

    p = deep_research.pre_search(run_dir, "scan topic", TS, transport=down)
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    assert data["records"] == [] and len(data["source_errors"]) == 4
    assert data["evidence_rows"] == []
