"""Operate wave-1 modes: evidence_review / evidence_deep / deep_research recipes.

evidence_deep is now a real staged evidence panel. evidence_review remains a
small honest single-worker review, and deep_research is now a true staged
16-seat perspective, author, and convergence panel.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock, envelope
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
    """Wave 1's twelve are still exactly wired — wave 2 ADDED nine, it replaced nothing."""
    assert {"new_direction", "deep_ideation", "evidence_review", "evidence_deep",
            "deep_research", "gap_breadth", "venue_readiness", "full_rigor_minimal",
            "ingest_paper", "read_paper_deep",
            "manuscript_authoring", "manuscript_review"} <= set(REGISTRY)
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
    # (per-seat model routing is pinned exactly at the end of this test)
    assert "my question" in spec["workers"][0]["prompt"]
    assert "rigor_score" in spec["workers"][1]["prompt"]
    assert "Do not link or" in spec["workers"][2]["prompt"]
    assert "Never emit `saturation_reached`" in spec["workers"][3]["prompt"]
    assert "claim-span/v1" in spec["workers"][4]["prompt"]
    assert "independent citation auditor" in spec["workers"][5]["prompt"]
    assert all("NORTH STAR" in worker["prompt"] for worker in spec["workers"])
    assert evidence_review.llm_step(run_dir, "REPORT", "q") is None
    # Model routing under the DEFAULT policy (director's rule, 2026-08-05): the three seats that
    # gather and restate run on sonnet; the three that JUDGE evidence stay on opus. `max_quality`
    # remains the 全 OPUS override. Pinned per-seat so a future retier cannot silently cheapen a
    # judging seat — which is the exact regression this assertion exists to catch.
    by_label = {w["label"]: w["model"]
                for w in evidence_review.llm_step(run_dir, "DISCOVER", "q")["workers"]}
    assert by_label == {
        "lit-scout": "sonnet",
        "claim-extractor": "sonnet",
        "claim-evidence-linker": "sonnet",
        "source-quality-ranker": "opus",
        "evidence-search-moderator": "opus",
        "citation-coverage-auditor": "opus",
    }
    assert all(w["model"] == "opus" for w in
               evidence_review.llm_step(run_dir, "DISCOVER", "q",
                                        model_policy="max_quality")["workers"])


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


_DOSSIER_CHECKS = {
    "method-and-paper": [
        "prior-art-boundary", "comparator-identity", "intervention-legality",
        "representation-attribution", "venue-claim-scope",
    ],
    "implementation-and-project-state": [
        "source-of-truth", "live-state-freshness", "leakage-firewall",
        "implementation-feasibility", "experiment-budget", "seed-chain",
    ],
    "evidence-and-completeness": [
        "citation-readiness", "coverage-completeness", "status-truth",
        "internal-consistency", "formal-gate-separation",
    ],
}


def _sha256_ref(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run_relative_ref(run_dir, path):
    return Path(path).resolve().relative_to(Path(run_dir).resolve()).as_posix()


def _review_id(lens, round_no=0):
    return f"review-{lens}-round-{round_no}"


def _dispatch_id(agent, round_no=0):
    seed = hashlib.sha256(f"{agent}|{round_no}".encode("utf-8")).hexdigest()[:32]
    return f"dispatch-{seed}"


def _dossier_finding(finding_id, severity="MAJOR"):
    author_ref = "inbox/DISCOVER.landscape-mapper.bundle.json"
    return {
        "finding_id": finding_id,
        "severity": severity,
        "category": "internal-consistency",
        "anchor": "research_brief.bottom_line",
        "evidence": f"{finding_id} identifies a concrete internal dossier defect.",
        "evidence_refs": [author_ref],
        "responsible_agent": "landscape-mapper",
        "target_artifact_ref": author_ref,
        "repair_action": "Correct the conflicting statement in the frozen author bundle.",
        "acceptance_check": "A fresh blind reviewer finds no remaining conflict.",
        "allowed_json_pointers": ["/research_brief/bottom_line"],
        "status": "OPEN",
    }


def _consolidated_finding(finding_id, severity, source_findings):
    return {
        "finding_id": f"consolidated-{finding_id}",
        "severity": severity,
        "category": "internal-consistency",
        "source_findings": source_findings,
        "anchor": "research_brief.bottom_line",
        "evidence": f"H-Max consolidation for {finding_id}.",
        "responsible_agent": "landscape-mapper",
        "repair_action": "Correct the conflicting statement in the frozen author bundle.",
        "acceptance_check": "Fresh blind reviewers find no remaining conflict.",
        "allowed_json_pointers": ["/research_brief/bottom_line"],
        "status": "OPEN",
    }


def _install_deep_research_tail_receipt(run_dir, round_no=0):
    receipt_path = run_dir / "inbox" / "panel-scheduler" / "DISCOVER.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    agents = [
        "landscape-mapper", *deep_research.DOSSIER_REVIEWER_NAMES,
        deep_research.CONVERGENCE_CHAIR,
    ]
    for index, agent in enumerate(agents):
        path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        if not path.is_file():
            continue
        rows.append({
            "worker_id": f"test:{agent}:{round_no}",
            "agent": agent,
            "source_label": agent,
            "output": _run_relative_ref(run_dir, path),
            "logical_output": f"inbox/DISCOVER.{agent}.bundle.json",
            "cycle": round_no,
            "wave": index + 1,
            "authorized_at": TS,
            "authorization_kind": "initial" if round_no == 0 else "supplement",
            "dispatch_instance_id": _dispatch_id(agent, round_no),
        })
    receipt = {
        "contract_version": "panel-dispatch/v1",
        "stage": "DISCOVER",
        "authorizations": rows,
        "waves": [],
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")


def _write_deep_research_review_bundles(
        run_dir, *, findings_by_lens=None, consolidated_findings=None,
        round_no=0, skip_agents=(), wrapped=False):
    """Write the hash-bound reviewer/chair tail after the author bundle is frozen."""
    skip = set(skip_agents)
    author_path = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    if not author_path.is_file():
        return
    author_ref = _run_relative_ref(run_dir, author_path)
    author_hash = _sha256_ref(author_path)
    project_source = run_dir / "inbox" / "project-state" / "sources" / "live-manifest.json"
    project_source.parent.mkdir(parents=True, exist_ok=True)
    project_source.write_text(
        json.dumps({"project": "test-project", "state": "current"}), encoding="utf-8")
    project_source_ref = _run_relative_ref(run_dir, project_source)
    project_snapshot = (
        run_dir / "inbox" / "project-state" / "project-state-snapshot.artifact.json"
    )
    project_snapshot.parent.mkdir(parents=True, exist_ok=True)
    project_snapshot.write_text(
        json.dumps({
            "artifact_id": "project_state_snapshot",
            "artifact_type": "project_state_snapshot",
            "schema_version": "1.0.0",
            "created_by": "project-state-capture",
            "created_at": TS,
            "status": "approved",
            "input_artifact_hashes": [
                _sha256_ref(run_dir / "task_frame.artifact.json")
            ],
            "payload": {
                "contract_version": "project-state-snapshot/v1",
                "project_id": "test-project",
                "source_of_truth_id": "test-live-manifest",
                "captured_at": TS,
                "valid_until": "2026-06-11T12:00:00Z",
                "sources": [{
                    "source_ref": project_source_ref,
                    "source_sha256": _sha256_ref(project_source),
                    "role": "LIVE_MANIFEST",
                }],
                "facts": [{
                    "fact_id": "state-current",
                    "statement": "The test project state is current for this review fixture.",
                    "source_refs": [project_source_ref],
                }],
            },
        }, ensure_ascii=False), encoding="utf-8")
    findings_by_lens = findings_by_lens or {}
    review_rows = []
    missing_review = False
    for agent, lens in deep_research.DOSSIER_REVIEWERS:
        if agent in skip:
            missing_review = True
            continue
        findings = list(findings_by_lens.get(lens) or [])
        severe = any(row["severity"] in {"CRITICAL", "MAJOR"} for row in findings)
        review = {
            "contract_version": "research-dossier-review/v1",
            "review_id": _review_id(lens, round_no),
            "reviewer_lens": lens,
            "reviewer_instance_id": _dispatch_id(agent, round_no),
            "independent_of_author": True,
            "author_agent": "landscape-mapper",
            "reviewed_artifact_ref": author_ref,
            "reviewed_artifact_sha256": author_hash,
            "review_round": round_no,
            "coverage_checks": [
                {"check_id": check_id, "status": "PASS",
                 "evidence": f"Checked {check_id} against the frozen author bundle.",
                 "finding_refs": [], "external_blocker_refs": []}
                for check_id in _DOSSIER_CHECKS[lens]
            ],
            "findings": findings,
            "external_blockers": [],
            "recommendation": "REVISE" if severe else "PASS",
            "summary": f"Independent {lens} review of the frozen dossier.",
        }
        if lens == "implementation-and-project-state":
            review["project_state_assessment"] = {
                "status": "CURRENT_HASH_BOUND",
                "snapshot_ref": _run_relative_ref(run_dir, project_snapshot),
                "snapshot_sha256": _sha256_ref(project_snapshot),
                "rationale": "The run-local test project snapshot is hash-bound and current.",
            }
        bundle = {"research_dossier_review": review}
        if wrapped:
            bundle = {"payload": bundle}
        review_path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        review_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        review_rows.append({
            "review_id": review["review_id"],
            "reviewer_lens": lens,
            "reviewer_instance_id": review["reviewer_instance_id"],
            "artifact_ref": _run_relative_ref(run_dir, review_path),
            "artifact_sha256": _sha256_ref(review_path),
        })

    if missing_review or deep_research.CONVERGENCE_CHAIR in skip:
        return
    if consolidated_findings is None:
        consolidated_findings = []
        for lens, findings in findings_by_lens.items():
            for finding in findings:
                consolidated_findings.append(_consolidated_finding(
                    finding["finding_id"], finding["severity"],
                    [{"review_id": _review_id(lens, round_no),
                      "finding_id": finding["finding_id"]}],
                ))
    counts = {
        "critical": sum(row["severity"] == "CRITICAL" for row in consolidated_findings),
        "major": sum(row["severity"] == "MAJOR" for row in consolidated_findings),
        "minor": sum(row["severity"] == "MINOR" for row in consolidated_findings),
        "external_blockers": 0,
    }
    disposition = (
        "REVISE" if counts["critical"] or counts["major"] else "CONTENT_CONVERGED"
    )
    verdict = {
        "contract_version": "research-dossier-convergence/v1",
        "convergence_id": f"convergence-round-{round_no}",
        "chair_instance_id": _dispatch_id(deep_research.CONVERGENCE_CHAIR, round_no),
        "review_round": round_no,
        "reviewed_artifact_ref": author_ref,
        "reviewed_artifact_sha256": author_hash,
        "review_refs": review_rows,
        "hmax_policy": True,
        "counts": counts,
        "consolidated_findings": list(consolidated_findings),
        "external_blockers": [],
        "disposition": disposition,
        "status_boundaries": {
            "content_convergence_only": True,
            "novelty_clearance": False,
            "project_approval": False,
            "formal_citation_gate": "PENDING",
        },
        "rationale": "All source findings are reconciled under H-Max without granting external gates.",
    }
    bundle = {"research_convergence_verdict": verdict}
    if wrapped:
        bundle = {"payload": bundle}
    (run_dir / "inbox" / f"DISCOVER.{deep_research.CONVERGENCE_CHAIR}.bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _install_deep_research_tail_receipt(run_dir, round_no)


def _rebind_chair_to_current_reviews(run_dir):
    """Keep a deliberately mutated review frozen while updating only the chair's bundle hashes."""
    chair_path = run_dir / "inbox" / f"DISCOVER.{deep_research.CONVERGENCE_CHAIR}.bundle.json"
    chair_bundle = json.loads(chair_path.read_text(encoding="utf-8"))
    chair = chair_bundle["research_convergence_verdict"]
    refs = []
    for agent, lens in deep_research.DOSSIER_REVIEWERS:
        path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        review = json.loads(path.read_text(encoding="utf-8"))["research_dossier_review"]
        refs.append({
            "review_id": review["review_id"],
            "reviewer_lens": lens,
            "reviewer_instance_id": review["reviewer_instance_id"],
            "artifact_ref": _run_relative_ref(run_dir, path),
            "artifact_sha256": _sha256_ref(path),
        })
    chair["review_refs"] = refs
    chair_path.write_text(json.dumps(chair_bundle, ensure_ascii=False), encoding="utf-8")


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
    _write_deep_research_review_bundles(run_dir, skip_agents=skip)


def test_deep_research_happy_path_emits_brief(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 16,
                                        "max_iterations_without_new_evidence": 3,
                                        "max_fulltext_reads": 20,
                                        "max_debug_retries_per_run": 3})
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_perspectives"] == 4 and report["saturation_reached"] is True
    assert report["content_convergence"] == "CONTENT_CONVERGED"
    assert report["open_content_critical"] == report["open_content_major"] == 0
    assert any("research-brief" in p for p in paths)
    assert any("research-convergence-verdict" in p for p in paths)
    assert any("research-markdown-brief" in p for p in paths)
    assert Path(report["director_markdown_brief"]).is_file()
    md = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    assert "Perspective Synthesis" in md and "Evidence Grade And Source Quality" in md
    assert "Belief Update" in md and "Next Most Valuable Evidence" in md
    _validate_written(paths)


def test_deep_research_zero_critical_major_findings_pass_content_convergence(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())

    result = deep_research._convergence_checks(
        run_dir, deep_research._load_worker_bundles(run_dir))

    assert result["disposition"] == "CONTENT_CONVERGED"
    assert result["critical"] == result["major"] == result["minor"] == 0
    assert len(result["reviewer_instances"]) == 3


def test_deep_research_reviewers_must_bind_exact_frozen_author_hash(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    author_path = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    expected_ref = _run_relative_ref(run_dir, author_path)
    expected_hash = _sha256_ref(author_path)
    for agent, _lens in deep_research.DOSSIER_REVIEWERS:
        path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        review = json.loads(path.read_text(encoding="utf-8"))["research_dossier_review"]
        assert (review["reviewed_artifact_ref"], review["reviewed_artifact_sha256"]) == (
            expected_ref, expected_hash)

    method_path = run_dir / "inbox" / "DISCOVER.research-dossier-method-reviewer.bundle.json"
    method_bundle = json.loads(method_path.read_text(encoding="utf-8"))
    method_bundle["research_dossier_review"]["reviewed_artifact_sha256"] = "sha256:" + "0" * 64
    method_path.write_text(json.dumps(method_bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    defects = {row["defect_id"]: row for row in exc_info.value.defects}
    assert "review-author-binding-method-and-paper" in defects
    assert defects["review-author-binding-method-and-paper"]["target_agents"] == [
        "research-dossier-method-reviewer"]


def test_deep_research_reviewer_instance_must_equal_scheduler_receipt(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    method_path = run_dir / "inbox" / "DISCOVER.research-dossier-method-reviewer.bundle.json"
    bundle = json.loads(method_path.read_text(encoding="utf-8"))
    bundle["research_dossier_review"]["reviewer_instance_id"] = "dispatch-" + "f" * 32
    method_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(row["defect_id"] == "review-dispatch-binding-method-and-paper"
               for row in exc_info.value.defects)


def test_deep_research_tail_receipt_ids_are_globally_unique(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    receipt_path = run_dir / "inbox" / "panel-scheduler" / "DISCOVER.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["authorizations"][1]["dispatch_instance_id"] = \
        receipt["authorizations"][0]["dispatch_instance_id"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(GateBlock, match="globally unique"):
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))


def test_deep_research_receipt_ids_are_unique_across_non_tail_rows(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    receipt_path = run_dir / "inbox" / "panel-scheduler" / "DISCOVER.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    duplicate = dict(receipt["authorizations"][1])
    duplicate.update({
        "worker_id": "test:lit-scout:0",
        "agent": "lit-scout",
        "source_label": "lit-scout",
        "output": "inbox/DISCOVER.lit-scout.bundle.json",
        "logical_output": "inbox/DISCOVER.lit-scout.bundle.json",
    })
    receipt["authorizations"].append(duplicate)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(GateBlock, match="globally unique"):
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))


def test_deep_research_project_snapshot_rejects_task_frame_replay(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    snapshot = (
        run_dir / "inbox" / "project-state" / "project-state-snapshot.artifact.json"
    )
    task_frame = run_dir / "task_frame.artifact.json"
    current = json.loads(task_frame.read_text(encoding="utf-8"))
    current["payload"]["request_text"] = "a different task with the same project"
    task_frame.write_text(json.dumps(current), encoding="utf-8")
    defects = []

    accepted = deep_research._validate_current_project_snapshot(
        run_dir,
        _run_relative_ref(run_dir, snapshot),
        _sha256_ref(snapshot),
        TS,
        lambda defect_id, message: defects.append((defect_id, message)),
    )

    assert accepted is False
    assert defects[0][0] == "current-snapshot-task-frame-binding"


@pytest.mark.parametrize(
    ("mutation", "expected_defect"),
    [
        ("duplicate", "review-coverage-method-and-paper"),
        ("unmapped-fail", "review-fail-unmapped-method-and-paper-prior-art-boundary"),
        ("illegal-na", "review-na-not-allowed-evidence-and-completeness-formal-gate-separation"),
    ],
)
def test_deep_research_coverage_checks_are_exact_and_accountable(
        tmp_path, mutation, expected_defect):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    if mutation == "illegal-na":
        agent = "research-dossier-evidence-reviewer"
        target_id = "formal-gate-separation"
    else:
        agent = "research-dossier-method-reviewer"
        target_id = "prior-art-boundary"
    path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    checks = bundle["research_dossier_review"]["coverage_checks"]
    target = next(row for row in checks if row["check_id"] == target_id)
    if mutation == "duplicate":
        checks.append(dict(target))
    elif mutation == "unmapped-fail":
        target["status"] = "FAIL"
    else:
        target["status"] = "NOT_APPLICABLE"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(row["defect_id"] == expected_defect for row in exc_info.value.defects)


def test_deep_research_missing_project_snapshot_stays_external_blocker(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    agent = "research-dossier-implementation-reviewer"
    path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    review = bundle["research_dossier_review"]
    review["project_state_assessment"] = {
        "status": "MISSING", "snapshot_ref": None, "snapshot_sha256": None,
        "rationale": "No hash-bound current project snapshot was supplied.",
    }
    blocker = {
        "blocker_id": "PROJECT-STATE-MISSING", "kind": "MISSING_PROJECT_STATE",
        "description": "No current hash-bound project-state input is available.",
        "evidence_refs": ["task_frame.artifact.json"],
        "required_input": "A run-local current project snapshot and SHA-256 binding.",
    }
    review["external_blockers"] = [blocker]
    review["recommendation"] = "PASS_WITH_EXTERNAL_BLOCKERS"
    for check in review["coverage_checks"]:
        if check["check_id"] in {"source-of-truth", "live-state-freshness"}:
            check["status"] = "FAIL"
            check["external_blocker_refs"] = [blocker["blocker_id"]]
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    chair_path = run_dir / "inbox" / f"DISCOVER.{deep_research.CONVERGENCE_CHAIR}.bundle.json"
    chair_bundle = json.loads(chair_path.read_text(encoding="utf-8"))
    chair = chair_bundle["research_convergence_verdict"]
    chair["external_blockers"] = [{
        "blocker_id": "CONSOLIDATED-PROJECT-STATE-MISSING",
        "kind": "MISSING_PROJECT_STATE",
        "description": blocker["description"],
        "source_blockers": [{"review_id": review["review_id"],
                              "blocker_id": blocker["blocker_id"]}],
        "required_input": blocker["required_input"],
    }]
    chair["counts"]["external_blockers"] = 1
    chair["disposition"] = "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS"
    chair_path.write_text(json.dumps(chair_bundle, ensure_ascii=False), encoding="utf-8")

    result = deep_research._convergence_checks(
        run_dir, deep_research._load_worker_bundles(run_dir))
    assert result["disposition"] == "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS"
    assert result["external_blockers"] == 1


def test_deep_research_rejects_arbitrary_run_file_as_current_project_snapshot(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    agent = "research-dossier-implementation-reviewer"
    path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    review = bundle["research_dossier_review"]
    task_frame = run_dir / "task_frame.artifact.json"
    review["project_state_assessment"] = {
        "status": "CURRENT_HASH_BOUND",
        "snapshot_ref": _run_relative_ref(run_dir, task_frame),
        "snapshot_sha256": _sha256_ref(task_frame),
        "rationale": "A matching hash alone must not turn the task frame into project state.",
    }
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(
        row["defect_id"] == "review-project-state-current-snapshot-contract-path"
        for row in exc_info.value.defects
    )


def test_deep_research_project_snapshot_source_cannot_traverse_out_of_source_lane(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    snapshot = (
        run_dir / "inbox" / "project-state" / "project-state-snapshot.artifact.json"
    )
    artifact = json.loads(snapshot.read_text(encoding="utf-8"))
    escaped = "inbox/project-state/sources/../../../task_frame.artifact.json"
    artifact["payload"]["sources"][0]["source_ref"] = escaped
    artifact["payload"]["sources"][0]["source_sha256"] = _sha256_ref(
        run_dir / "task_frame.artifact.json"
    )
    artifact["payload"]["facts"][0]["source_refs"] = [escaped]
    snapshot.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    defects = []

    accepted = deep_research._validate_current_project_snapshot(
        run_dir,
        _run_relative_ref(run_dir, snapshot),
        _sha256_ref(snapshot),
        TS,
        lambda defect_id, summary: defects.append((defect_id, summary)),
    )

    assert accepted is False
    assert defects
    assert defects[0][0] == "current-snapshot-schema"


def test_deep_research_chair_cannot_rewrite_source_blocker_contract(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    agent = "research-dossier-implementation-reviewer"
    path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    review = bundle["research_dossier_review"]
    review["project_state_assessment"] = {
        "status": "MISSING", "snapshot_ref": None, "snapshot_sha256": None,
        "rationale": "No governed project-state snapshot was supplied.",
    }
    blocker = {
        "blocker_id": "PROJECT-STATE-MISSING", "kind": "MISSING_PROJECT_STATE",
        "description": "No governed current project-state input is available.",
        "evidence_refs": ["task_frame.artifact.json"],
        "required_input": "A valid project_state_snapshot artifact and source bindings.",
    }
    review["external_blockers"] = [blocker]
    review["recommendation"] = "PASS_WITH_EXTERNAL_BLOCKERS"
    for check in review["coverage_checks"]:
        if check["check_id"] in {"source-of-truth", "live-state-freshness"}:
            check["status"] = "FAIL"
            check["external_blocker_refs"] = [blocker["blocker_id"]]
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    chair_path = run_dir / "inbox" / f"DISCOVER.{deep_research.CONVERGENCE_CHAIR}.bundle.json"
    chair_bundle = json.loads(chair_path.read_text(encoding="utf-8"))
    chair = chair_bundle["research_convergence_verdict"]
    chair["external_blockers"] = [{
        "blocker_id": "CONSOLIDATED-PROJECT-STATE-MISSING",
        "kind": blocker["kind"],
        "description": blocker["description"],
        "source_blockers": [{"review_id": review["review_id"],
                              "blocker_id": blocker["blocker_id"]}],
        "required_input": "Rewrite the dossier instead of supplying project state.",
    }]
    chair["counts"]["external_blockers"] = 1
    chair["disposition"] = "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS"
    chair_path.write_text(json.dumps(chair_bundle, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(
        row["defect_id"].endswith("required-input")
        and row["target_agents"] == [deep_research.CONVERGENCE_CHAIR]
        for row in exc_info.value.defects
    )


def test_deep_research_chair_only_repair_keeps_unaffected_review_receipt_cycles(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    agent = "research-dossier-implementation-reviewer"
    review_path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
    review_bundle = json.loads(review_path.read_text(encoding="utf-8"))
    review = review_bundle["research_dossier_review"]
    review["project_state_assessment"] = {
        "status": "MISSING", "snapshot_ref": None, "snapshot_sha256": None,
        "rationale": "No governed project-state snapshot was supplied.",
    }
    blocker = {
        "blocker_id": "PROJECT-STATE-MISSING", "kind": "MISSING_PROJECT_STATE",
        "description": "No governed current project-state input is available.",
        "evidence_refs": ["task_frame.artifact.json"],
        "required_input": "A valid project_state_snapshot artifact and source bindings.",
    }
    review["external_blockers"] = [blocker]
    review["recommendation"] = "PASS_WITH_EXTERNAL_BLOCKERS"
    for check in review["coverage_checks"]:
        if check["check_id"] in {"source-of-truth", "live-state-freshness"}:
            check["status"] = "FAIL"
            check["external_blocker_refs"] = [blocker["blocker_id"]]
    review_path.write_text(json.dumps(review_bundle, ensure_ascii=False), encoding="utf-8")
    _rebind_chair_to_current_reviews(run_dir)

    chair_agent = deep_research.CONVERGENCE_CHAIR
    chair_logical = run_dir / "inbox" / f"DISCOVER.{chair_agent}.bundle.json"
    chair_bundle = json.loads(chair_logical.read_text(encoding="utf-8"))
    chair = chair_bundle["research_convergence_verdict"]
    chair["external_blockers"] = [{
        "blocker_id": "CONSOLIDATED-PROJECT-STATE-MISSING",
        "kind": blocker["kind"],
        "description": blocker["description"],
        "source_blockers": [{"review_id": review["review_id"],
                              "blocker_id": blocker["blocker_id"]}],
        "required_input": "Rewrite prose instead of supplying the missing snapshot.",
    }]
    chair["counts"]["external_blockers"] = 1
    chair["disposition"] = "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS"
    chair_logical.write_text(json.dumps(chair_bundle, ensure_ascii=False), encoding="utf-8")

    first = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert first[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    assert attempt["target_agents"] == [chair_agent]

    node = {
        "id": chair_agent,
        "label": chair_agent,
        "output_path": chair_logical,
        "output_rel": _run_relative_ref(run_dir, chair_logical),
    }
    plan = prepare_plan(run_dir, "DISCOVER", 1, [node], {chair_agent}, attempt)
    corrected_path = physical_output(run_dir, plan, chair_agent)
    corrected_bundle = json.loads(chair_logical.read_text(encoding="utf-8"))
    corrected = corrected_bundle["research_convergence_verdict"]
    corrected["chair_instance_id"] = _dispatch_id(chair_agent, 1)
    corrected["review_round"] = 1
    corrected["external_blockers"][0]["required_input"] = blocker["required_input"]
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(
        json.dumps(corrected_bundle, ensure_ascii=False), encoding="utf-8"
    )
    finalize_output(run_dir, "DISCOVER", 1, chair_agent, TS)

    receipt_path = run_dir / "inbox" / "panel-scheduler" / "DISCOVER.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["authorizations"].append({
        "worker_id": f"test:{chair_agent}:1",
        "agent": chair_agent,
        "source_label": chair_agent,
        "output": _run_relative_ref(run_dir, corrected_path),
        "logical_output": _run_relative_ref(run_dir, chair_logical),
        "cycle": 1,
        "wave": len(receipt.get("waves") or []) + 1,
        "authorized_at": TS,
        "authorization_kind": "supplement",
        "dispatch_instance_id": _dispatch_id(chair_agent, 1),
    })
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")

    second = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert second[0] == "ok"
    _paths, report = second[1]
    assert report["content_convergence"] == "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS"


def test_deep_research_author_schema_repair_receives_bounded_pointer_scope(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    logical = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    bundle = json.loads(logical.read_text(encoding="utf-8"))
    bundle["research_brief"].pop("bottom_line")
    logical.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

    outcome = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert outcome[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    defect = next(row for row in attempt["defects"]
                  if row["defect_id"] == "deep-research-schema-research-brief")
    assert defect["allowed_json_pointers"] == ["/research_brief"]
    node = {
        "id": "schema-repair:landscape-mapper",
        "label": "landscape-mapper",
        "output_path": logical,
        "output_rel": _run_relative_ref(run_dir, logical),
    }
    plan = prepare_plan(
        run_dir, "DISCOVER", 1, [node], {"landscape-mapper"}, attempt,
    )
    assert plan["outputs"][0]["repair_scope"]["allowed_json_pointers"] == [
        "/research_brief"
    ]


def test_deep_research_hmax_chair_cannot_lower_source_severity(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    source = _dossier_finding("METHOD-CRITICAL", "CRITICAL")
    lowered = _consolidated_finding(
        source["finding_id"], "MAJOR",
        [{"review_id": _review_id("method-and-paper"),
          "finding_id": source["finding_id"]}],
    )
    _write_deep_research_review_bundles(
        run_dir,
        findings_by_lens={"method-and-paper": [source]},
        consolidated_findings=[lowered],
    )

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(row["defect_id"] == "chair-hmax-consolidated-METHOD-CRITICAL"
               and "expected CRITICAL" in row["summary"]
               for row in exc_info.value.defects)


def test_deep_research_hmax_chair_cannot_omit_source_finding(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    source = _dossier_finding("EVIDENCE-MINOR", "MINOR")
    _write_deep_research_review_bundles(
        run_dir,
        findings_by_lens={"evidence-and-completeness": [source]},
        consolidated_findings=[],
    )

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(row["defect_id"] == "chair-finding-coverage"
               for row in exc_info.value.defects)


def test_deep_research_hmax_chair_cannot_widen_repair_pointers(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    source = _dossier_finding("METHOD-MAJOR", "MAJOR")
    consolidated = _consolidated_finding(
        source["finding_id"], "MAJOR",
        [{"review_id": _review_id("method-and-paper"),
          "finding_id": source["finding_id"]}],
    )
    consolidated["allowed_json_pointers"].append("/research_brief")
    _write_deep_research_review_bundles(
        run_dir, findings_by_lens={"method-and-paper": [source]},
        consolidated_findings=[consolidated])

    with pytest.raises(TargetedGateBlock) as exc_info:
        deep_research._convergence_checks(
            run_dir, deep_research._load_worker_bundles(run_dir))

    assert any(row["defect_id"] == "chair-pointer-union-consolidated-METHOD-MAJOR"
               for row in exc_info.value.defects)


def test_deep_research_critical_major_routes_author_repair_and_blind_panel_refresh(tmp_path):
    run_dir = _mk_run(tmp_path, budget={
        "max_agent_hops": 16,
        "max_iterations_without_new_evidence": 3,
        "max_fulltext_reads": 20,
        "max_debug_retries_per_run": 3,
    })
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    source = _dossier_finding("METHOD-MAJOR", "MAJOR")
    _write_deep_research_review_bundles(
        run_dir, findings_by_lens={"method-and-paper": [source]})

    outcome = deep_research.run_dets_with_repair(run_dir, "DISCOVER", TS)

    assert outcome[0] == "retry"
    attempt = load_state(run_dir)["attempts"][-1]
    assert attempt["target_agents"] == ["landscape-mapper"]
    assert attempt["refresh_agents"] == []
    assert set(attempt["blind_refresh_agents"]) == {
        *deep_research.DOSSIER_REVIEWER_NAMES,
        deep_research.CONVERGENCE_CHAIR,
    }
    assert any("METHOD-MAJOR" in row["summary"] for row in attempt["defects"])
    severe_defect = next(row for row in attempt["defects"]
                         if row["defect_id"] == "dossier-consolidated-METHOD-MAJOR")
    assert severe_defect["allowed_json_pointers"] == ["/research_brief/bottom_line"]
    assert severe_defect["target_artifact_sha256"].startswith("sha256:")


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
    _write_deep_research_review_bundles(run_dir, wrapped=True)

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
    _write_deep_research_review_bundles(run_dir)

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


def test_deep_research_normalizes_moderate_perspective_confidence_and_preserves_long_summary():
    """The prompt promises uncapped mid-pipeline text; representation aliases must not spend repairs."""
    long_summary = "Evidence-bounded finding. " * 420
    note = {
        "perspective_id": "P4",
        "angle": "failure modes",
        "questions": ["What fails?", "What evidence would reverse the decision?"],
        "finding_summary": long_summary,
        "source_refs": ["doi:10.1000/x"],
        "coverage_limits": ["bounded frozen source set"],
        "actionable_opportunities": ["run the falsifying test"],
        "confidence": "moderate",
    }
    bundle = {"perspective_notes": [note]}

    deep_research._normalize_compat_enums(bundle)

    normalized = bundle["perspective_notes"][0]
    assert normalized["confidence"] == "medium"
    assert normalized["finding_summary"] == long_summary
    assert len(long_summary) > 8000
    assert validate_artifact(
        envelope("research_perspective_note", "test", normalized, TS)
    ) == []


def test_deep_research_normalizes_study_design_vocabulary_before_schema_gate():
    """Project-record study-design labels are representation-only; normalize, never replay."""
    bundle = {
        "source_quality_report": {
            "ranked_sources": [
                {"id": "r1", "study_design": "challenge-overview"},
                {"id": "r2", "study_design": "dataset-card"},
                {"id": "r3", "study_design": "decision-record"},
                {"id": "r4", "study_design": "experiment-design"},
                {"id": "r5", "study_design": "randomized-controlled-trial"},
                {"id": "r6", "study_design": "benchmark", "directness": "partial"},
                {"id": "r7", "study_design": "benchmark", "directness": "direct"},
            ]
        }
    }

    deep_research._normalize_compat_enums(bundle)

    designs = {
        row["id"]: row["study_design"]
        for row in bundle["source_quality_report"]["ranked_sources"]
    }
    assert designs == {
        "r1": "benchmark",
        "r2": "documentation",
        "r3": "documentation",
        "r4": "methods-paper",
        "r5": "randomized-controlled-trial",
        "r6": "benchmark",
        "r7": "benchmark",
    }
    directness = {
        row["id"]: row["directness"]
        for row in bundle["source_quality_report"]["ranked_sources"]
        if "directness" in row
    }
    assert directness == {"r6": "indirect", "r7": "direct"}


def test_deep_research_reconciles_ranked_refs_to_anchored_table_refs():
    """A bare [[slug]] / doi:-prefixed ranked ref is the same frozen source the
    table anchors — representation-only reconciliation, never a panel replay."""
    bundle = {
        "evidence_table": {
            "sources": [
                {"id": "s1", "ref": "[[papers/foo]]+sha256:abc123"},
                {"id": "s2", "ref": "10.1007/s00371-026-04560-5"},
            ]
        },
        "source_quality_report": {
            "ranked_sources": [
                {"id": "r1", "source_ref": "[[papers/foo]]"},
                {"id": "r2", "source_ref": "doi:10.1007/s00371-026-04560-5"},
                {"id": "r3", "source_ref": "[[papers/absent]]"},
            ]
        },
    }

    deep_research._normalize_compat_enums(bundle)

    refs = {
        row["id"]: row["source_ref"]
        for row in bundle["source_quality_report"]["ranked_sources"]
    }
    assert refs == {
        "r1": "[[papers/foo]]+sha256:abc123",
        "r2": "10.1007/s00371-026-04560-5",
        "r3": "[[papers/absent]]",
    }


def test_deep_research_verifies_local_trace_provenance_without_treating_it_as_literature(tmp_path):
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    provenance = run_dir / "inbox/supplements/DISCOVER/repair-001/corrected/lit-scout.bundle.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_bytes(b"frozen evidence-table input")
    ref = "inbox/supplements/DISCOVER/repair-001/corrected/lit-scout.bundle.json"
    payload["evidence_search_trace"]["rounds"][0]["source_hits"].append({
        "source_ref": ref,
        "source_hash": hashlib.sha256(provenance.read_bytes()).hexdigest(),
    })

    deep_research._consistency_checks(run_dir, payload, TS)


def test_deep_research_blocks_invalid_local_trace_provenance_hash(tmp_path):
    run_dir = _mk_run(tmp_path)
    payload = _good_deep_research_panel()
    provenance = run_dir / "inbox/supplements/DISCOVER/repair-001/corrected/lit-scout.bundle.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_bytes(b"frozen evidence-table input")
    payload["evidence_search_trace"]["rounds"][0]["source_hits"].append({
        "source_ref": "inbox/supplements/DISCOVER/repair-001/corrected/lit-scout.bundle.json",
        "source_hash": "0" * 64,
    })

    with pytest.raises(TargetedGateBlock, match="invalid run-local provenance"):
        deep_research._consistency_checks(run_dir, payload, TS)


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
    boundary_path = next(Path(path) for path in paths if "research-delivery-boundary" in path)
    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))["payload"]
    chair = json.loads((
        run_dir / "inbox" / "DISCOVER.research-convergence-chair.bundle.json"
    ).read_text(encoding="utf-8"))["research_convergence_verdict"]
    assert boundary["reviewed_artifact_ref"] == chair["reviewed_artifact_ref"]
    assert boundary["reviewed_artifact_sha256"] == chair["reviewed_artifact_sha256"]
    assert boundary["novelty"]["status"] == "UNVERIFIED"
    assert boundary["claim_boundaries"]["novelty_claim_allowed"] is False
    assert report["delivery_boundary"] == boundary
    rendered = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    assert "Effective novelty status: `UNVERIFIED`" in rendered
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
    # Director lock 2026-08-16: trust/control extras are re-attached into the canonical payload,
    # never silently dropped. The retry reason must name the offending control field so it
    # cannot vanish as formatting noise.
    assert "selected" in attempt["reason"]


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


def _committed_clean_deep_research(
        tmp_path, task_id="report-boundary-test", before_commit=None):
    plan = spine.begin(
        str(tmp_path / "runs"), task_id, "scan a research field", "deep_research", TS)
    run_dir = Path(plan["run_dir"])
    _write_deep_research_bundles(run_dir, _good_deep_research_panel())
    spine.open_stage(run_dir, "DISCOVER", TS)
    paths, report = deep_research.run_dets(run_dir, "DISCOVER", TS)
    if before_commit is not None:
        before_commit(run_dir, paths, report)
    assert spine.commit_stage(run_dir, "DISCOVER", paths, TS)["next_stage"] == "REPORT"
    return run_dir, report


def _run_deep_research_report(run_dir):
    spine.open_stage(run_dir, "REPORT", TS)
    paths, _ = deep_research.run_dets(run_dir, "REPORT", TS)
    return json.loads(Path(paths[0]).read_text(encoding="utf-8"))["payload"]


def _make_checkpoint_boundary_usable(run_dir, _paths, _report):
    boundary = (
        run_dir / "evidence" / "DISCOVER" /
        "research-delivery-boundary.artifact.json"
    )
    artifact = json.loads(boundary.read_text(encoding="utf-8"))
    payload = artifact["payload"]
    payload["scientific_gates"]["existence"] = "PASS"
    payload["novelty"]["reasons"] = [
        reason for reason in payload["novelty"]["reasons"]
        if reason != "EXISTENCE_GATE_NOT_PASS"
    ]
    payload["delivery_status"] = "USABLE"
    assert validate_artifact(artifact) == []
    boundary.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")


def test_deep_research_report_rejects_malformed_delivery_boundary(tmp_path):
    run_dir, _report = _committed_clean_deep_research(tmp_path)
    boundary = (
        run_dir / "evidence" / "DISCOVER" /
        "research-delivery-boundary.artifact.json"
    )
    boundary.write_text(
        json.dumps({"payload": {"delivery_status": "USABLE"}}), encoding="utf-8")

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any("delivery boundary artifact schema validation failed" in reason
               for reason in note["delivery_caveats"])


def test_deep_research_report_rejects_checkpoint_replaced_delivery_boundary(tmp_path):
    run_dir, _report = _committed_clean_deep_research(tmp_path)
    boundary = (
        run_dir / "evidence" / "DISCOVER" /
        "research-delivery-boundary.artifact.json"
    )
    artifact = json.loads(boundary.read_text(encoding="utf-8"))
    artifact["payload"]["rationale"] += " Replaced after the DISCOVER checkpoint."
    assert validate_artifact(artifact) == []
    boundary.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any("delivery boundary artifact no longer matches its DISCOVER checkpoint hash" in reason
               for reason in note["delivery_caveats"])


def test_deep_research_report_revalidates_convergence_and_author_hashes(tmp_path):
    run_dir, _report = _committed_clean_deep_research(tmp_path)
    convergence = (
        run_dir / "evidence" / "DISCOVER" /
        "research-convergence-verdict.artifact.json"
    )
    convergence_artifact = json.loads(convergence.read_text(encoding="utf-8"))
    convergence_artifact["payload"]["rationale"] += " Replaced after convergence."
    assert validate_artifact(convergence_artifact) == []
    convergence.write_text(
        json.dumps(convergence_artifact, ensure_ascii=False), encoding="utf-8")

    author = run_dir / "inbox" / "DISCOVER.landscape-mapper.bundle.json"
    author_bundle = json.loads(author.read_text(encoding="utf-8"))
    author_bundle["research_brief"]["bottom_line"] += " Drifted after review."
    author.write_text(json.dumps(author_bundle, ensure_ascii=False), encoding="utf-8")

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any("convergence artifact hash no longer matches the delivery boundary" in reason
               for reason in note["delivery_caveats"])
    assert any("reviewed author bundle no longer matches the delivery boundary" in reason
               for reason in note["delivery_caveats"])


def test_deep_research_report_preserves_markdown_fallback_caveat(
        tmp_path, monkeypatch):
    def renderer_failure(*_args, **_kwargs):
        raise ValueError("forced deterministic renderer failure")

    monkeypatch.setattr(deep_research, "write_research_brief_markdown", renderer_failure)
    run_dir, discover_report = _committed_clean_deep_research(
        tmp_path, before_commit=_make_checkpoint_boundary_usable)
    boundary = json.loads((
        run_dir / "evidence" / "DISCOVER" /
        "research-delivery-boundary.artifact.json"
    ).read_text(encoding="utf-8"))["payload"]
    assert boundary["delivery_status"] == "USABLE"
    assert discover_report["markdown_delivery_status"] == "USABLE_WITH_CAVEATS"

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any("deterministic Markdown fallback used: forced deterministic renderer failure" in reason
               for reason in note["delivery_caveats"])


def test_deep_research_report_rejects_replaced_primary_markdown(tmp_path):
    run_dir, _report = _committed_clean_deep_research(
        tmp_path, before_commit=_make_checkpoint_boundary_usable)
    primary = run_dir / "director-review" / "research" / "research-brief.md"
    primary.write_text(
        "# Replaced delivery\n\nNovelty PASS.\n", encoding="utf-8")

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any(
        "primary research Markdown content does not exactly match the checkpointed "
        "research Markdown brief artifact" in reason
        for reason in note["delivery_caveats"]
    )


def test_deep_research_report_rejects_render_policy_boundary_mismatch(tmp_path):
    def force_full_policy(run_dir, _paths, _report):
        markdown = (
            run_dir / "evidence" / "DISCOVER" /
            "research-markdown-brief.artifact.json"
        )
        artifact = json.loads(markdown.read_text(encoding="utf-8"))
        artifact["payload"]["render_policy"] = "FULL_VERIFIED"
        assert validate_artifact(artifact) == []
        markdown.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")

    run_dir, _report = _committed_clean_deep_research(
        tmp_path, before_commit=force_full_policy)

    note = _run_deep_research_report(run_dir)

    assert note["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert any(
        "research Markdown render policy does not match the trusted delivery boundary" in reason
        for reason in note["delivery_caveats"]
    )


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
    assert len(spec["workers"]) == 16
    assert spec["worker_order"][0] == "lit-scout"
    assert spec["worker_order"][-1] == deep_research.CONVERGENCE_CHAIR
    assert all(w["output"].endswith(f"inbox/DISCOVER.{w['label']}.bundle.json") for w in spec["workers"])
    assert "parallel/blind" in spec["panel_note"]
    workers = {worker["label"]: worker for worker in spec["workers"]}
    by_label = {label: worker["prompt"] for label, worker in workers.items()}
    assert "what changed in belief" in by_label["model-dataset-scout"]
    assert "DISCOVER.future-work-miner.bundle.json" not in by_label["model-dataset-scout"]
    assert "DISCOVER.model-dataset-scout.bundle.json" not in by_label["future-work-miner"]
    assert "independently audit claim support" in by_label["citation-coverage-auditor"]
    assert "highest expected" in by_label["landscape-mapper"]
    assert spec["parallel_groups"] == deep_research.DEEP_RESEARCH_PARALLEL_GROUPS
    assert len(spec["parallel_groups"]) == 10
    assert spec["parallel_groups"][-2:] == [
        deep_research.DOSSIER_REVIEWER_NAMES,
        [deep_research.CONVERGENCE_CHAIR],
    ]
    assert workers["citation-coverage-auditor"]["depends_on"] == [
        "lit-scout", "claim-extractor", "claim-evidence-linker",
    ]
    assert "citation-coverage-auditor" not in workers["contradiction-miner"]["depends_on"]
    for reviewer in deep_research.DOSSIER_REVIEWER_NAMES:
        assert "landscape-mapper" in workers[reviewer]["depends_on"]
        assert not (set(workers[reviewer]["depends_on"]) &
                    (set(deep_research.DOSSIER_REVIEWER_NAMES) - {reviewer}))
        forbidden = set(workers[reviewer]["input_contract"]["forbidden_inputs"])
        expected_forbidden = {
            (Path(run_dir) / "inbox" / f"DISCOVER.{agent}.bundle.json").as_posix()
            for agent in [*deep_research.DOSSIER_REVIEWER_NAMES,
                          deep_research.CONVERGENCE_CHAIR]
            if agent != reviewer
        }
        expected_forbidden.update({
            (
                Path(run_dir) / "inbox" / "supplements" / "DISCOVER" /
                "repair-*" / location / f"{agent}.bundle.json"
            ).as_posix()
            for agent in [*deep_research.DOSSIER_REVIEWER_NAMES,
                          deep_research.CONVERGENCE_CHAIR]
            for location in ("originals", "corrected")
        })
        assert forbidden == expected_forbidden
        assert all(f"DISCOVER.{sibling}.bundle.json" not in by_label[reviewer]
                   for sibling in deep_research.DOSSIER_REVIEWER_NAMES
                   if sibling != reviewer)
    assert workers[deep_research.CONVERGENCE_CHAIR]["depends_on"] == [
        "landscape-mapper", *deep_research.DOSSIER_REVIEWER_NAMES,
    ]
    assert "H-Max" in by_label[deep_research.CONVERGENCE_CHAIR]
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
