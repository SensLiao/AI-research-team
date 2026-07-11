from __future__ import annotations

from research_agent_teams.tools.research_brief_markdown import (
    REQUIRED_HEADINGS,
    build_research_brief_markdown,
    lint_research_brief_markdown,
)
from research_agent_teams.tools.research_output_quality import audit_markdown_text


def _evidence_inputs():
    evidence_table = {
        "query": "should the current project use method A?",
        "saturation_reached": True,
        "sources": [
            {"id": "s1", "kind": "paper", "ref": "[[page-a]]", "title": "Direct study",
             "year": 2025, "claim_support": "strong"},
            {"id": "s2", "kind": "paper", "ref": "doi:10.1000/x", "title": "External study",
             "year": 2024, "claim_support": "moderate"},
            {"id": "s3", "kind": "paper", "ref": "arXiv:2403.12345", "title": "Early study",
             "year": 2024, "claim_support": "weak"},
        ],
    }
    claim_list = {"source_scope": "vault+search", "claims": [
        {"claim_id": "c1", "text": "method A improves the in-domain metric over B",
         "source_ref": "[[page-a]]", "kind": "performance", "confidence": "high"},
        {"claim_id": "c2", "text": "method A has uncertain cross-dataset robustness",
         "source_ref": "doi:10.1000/x", "kind": "limitation", "confidence": "medium"},
    ]}
    claim_evidence_map = {"mappings": [
        {"claim_id": "c1", "overall_support": "supported",
         "claim_risk": {"level": "low", "note": "direct protocol-matched result"},
         "loci": [{"locus_id": "l1", "source_ref": "[[page-a]]", "location": "Table 2",
                    "kind": "table", "reported_result": "A 0.91 versus B 0.85",
                    "supports_claim": True, "directness": "direct"}]},
        {"claim_id": "c2", "overall_support": "partial",
         "claim_risk": {"level": "medium", "note": "only one external dataset"},
         "loci": [{"locus_id": "l2", "source_ref": "doi:10.1000/x", "location": "Section 4",
                    "kind": "text", "reported_result": "performance drops on Dataset Z",
                    "supports_claim": True, "directness": "indirect"}]},
    ]}
    return evidence_table, claim_list, claim_evidence_map


def _deep_inputs():
    source_quality = {
        "ranked_sources": [
            {"source_ref": "[[page-a]]", "rank": 1, "tier": "peer-reviewed",
             "rigor_score": 0.91, "year": 2025, "venue": "Venue A", "rank_notes": "direct"},
            {"source_ref": "doi:10.1000/x", "rank": 2, "tier": "peer-reviewed",
             "rigor_score": 0.82, "year": 2024, "venue": "Venue B", "rank_notes": "external"},
            {"source_ref": "arXiv:2403.12345", "rank": 3, "tier": "preprint",
             "rigor_score": 0.5, "year": 2024, "venue": None, "rank_notes": "early"},
        ],
        "ranking_rationale": "Direct peer-reviewed evidence outranks indirect preprint evidence.",
        "n_sources_ranked": 3,
    }
    contradiction = {
        "n_claims_checked": 2,
        "summary": "the external result limits the scope of the in-domain result",
        "conflicts": [{"conflict_id": "conf1", "claim_ref_a": "c1", "claim_ref_b": "c2",
                       "kind": "scope-mismatch",
                       "description": "an in-domain win does not establish external robustness",
                       "resolution_status": "explained-by-scope"}],
    }
    landscape = {
        "domain_query": "method A",
        "methods": [],
        "coverage_gaps": [{"gap_id": "gap1",
                           "description": "a protocol-matched external validation is missing",
                           "gap_kind": "evaluation", "severity": "major"}],
    }
    return source_quality, contradiction, landscape


def _report():
    return {
        "evidence_gate": "PASS",
        "citation_gate": "PASS",
        "existence_gate": "PASS",
        "existence_warnings": 0,
        "n_strong_sources": 1,
    }


def test_deep_evidence_renderer_produces_decision_grade_brief_and_passes_lint():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, landscape = _deep_inputs()

    text = build_research_brief_markdown(
        mode="evidence_deep",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        landscape_map=landscape,
        staleness_reports=[{"source_ref": "doi:10.1000/x", "status": "AGING",
                            "staleness_rationale": "the field moved since publication"}],
    )

    for heading in REQUIRED_HEADINGS:
        assert heading in text
    assert "Evidence grade: `MODERATE`" in text
    assert "### `c1`" in text and "Table 2" in text and "A 0.91 versus B 0.85" in text
    assert "`conf1`" in text and "explained-by-scope" in text
    assert "Starting position:" in text and "Net update:" in text
    assert "For the current project/idea/experiment" in text
    assert "Decision it unlocks:" in text and "protocol-matched external validation" in text
    assert lint_research_brief_markdown(
        text,
        mode="evidence_deep",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
    ) == []
    assert audit_markdown_text("evidence_deep", text)["status"] == "pass"
    omissions = text.replace("`conf1`", "`conflict-omitted`", 1).replace(
        "arXiv:2403.12345", "ranked-source-omitted"
    )
    omission_errors = lint_research_brief_markdown(
        omissions,
        mode="evidence_deep",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
    )
    assert "Markdown brief omits conflict: conf1" in omission_errors
    assert "Markdown brief omits ranked source: arXiv:2403.12345" in omission_errors


def test_light_review_is_honest_about_quality_and_counterevidence_ceiling():
    evidence_table, claim_list, claim_map = _evidence_inputs()

    text = build_research_brief_markdown(
        mode="evidence_review",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
    )

    assert "Evidence grade: `LIMITED`" in text
    assert "source quality was not independently ranked" in text
    assert "not evidence of absence" in text
    assert "independent, high-rigor direct evidence" in text
    assert lint_research_brief_markdown(
        text,
        mode="evidence_review",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
    ) == []
    assert audit_markdown_text("evidence_review", text)["status"] == "pass"


def test_existence_warnings_cap_grade_and_become_the_next_evidence_priority():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, landscape = _deep_inputs()
    report = _report()
    report["existence_warnings"] = 2

    text = build_research_brief_markdown(
        mode="evidence_deep",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=report,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        landscape_map=landscape,
    )

    assert "Evidence grade: `LIMITED`" in text
    assert "Decision posture: `HOLD`" in text
    assert "Resolve 2 source-existence warnings" in text
    assert "2 source existence warnings leave cited records unverified" in text


def test_partial_source_quality_ranking_caps_grade_and_names_missing_refs():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, landscape = _deep_inputs()
    source_quality["ranked_sources"] = source_quality["ranked_sources"][:2]

    text = build_research_brief_markdown(
        mode="evidence_deep",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        landscape_map=landscape,
    )

    assert "Evidence grade: `LIMITED`" in text
    assert "ranked source coverage=2/3" in text
    assert "Complete independent source-quality ranking for `arXiv:2403.12345`" in text


def test_deep_research_renderer_preserves_perspectives_but_owns_final_markdown():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, _landscape = _deep_inputs()
    notes = [
        {"perspective_id": "P1", "angle": "methods", "finding_summary": "A wins in-domain.",
         "source_refs": ["[[page-a]]"], "coverage_limits": ["one benchmark"],
         "actionable_opportunities": ["run external validation"],
         "kill_criteria": ["A loses after matched tuning"], "confidence": "medium"},
        {"perspective_id": "P2", "angle": "open problems", "finding_summary": "Robustness is open.",
         "source_refs": ["doi:10.1000/x"], "coverage_limits": ["few negative results"],
         "actionable_opportunities": ["collect failure cases"],
         "kill_criteria": ["failures dominate target slice"], "confidence": "medium"},
        {"perspective_id": "P3", "angle": "transfer", "finding_summary": "Transfer is conditional.",
         "source_refs": ["arXiv:2403.12345"], "coverage_limits": ["indirect analogy"],
         "actionable_opportunities": ["state the mechanism"],
         "kill_criteria": ["mechanism does not apply"], "confidence": "low"},
    ]
    research_brief = {
        "bottom_line": "A is promising in-domain, but robustness should be tested before adoption.",
        "consensus": ["the in-domain result is credible"],
        "live_disagreements": ["whether the result transfers"],
        "evidence_gaps": ["protocol-matched external validation"],
        "actionable_next_questions": ["run a matched external validation with a preregistered kill rule"],
    }

    text = build_research_brief_markdown(
        mode="deep_research",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        perspective_notes=notes,
        research_brief=research_brief,
    )

    assert "## Perspective Synthesis" in text
    assert all(f"### `{pid}`" in text for pid in ("P1", "P2", "P3"))
    assert "run a matched external validation with a preregistered kill rule" in text
    assert "A is promising in-domain" in text
    assert lint_research_brief_markdown(
        text,
        mode="deep_research",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        perspective_ids=["P1", "P2", "P3"],
    ) == []
    assert audit_markdown_text("deep_research", text)["status"] == "pass"
    perspective_errors = lint_research_brief_markdown(
        text.replace("### `P1`", "### perspective-one", 1),
        mode="deep_research",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        perspective_ids=["P1", "P2", "P3"],
    )
    assert "Markdown brief omits perspective: P1" in perspective_errors


def test_markdown_lint_blocks_missing_semantics_and_locus_coverage():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    text = build_research_brief_markdown(
        mode="evidence_review",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
    )
    broken = (
        text.replace("## Belief Update", "## Update", 1)
        .replace("Table 2", "location omitted", 1)
        .replace("Most valuable next evidence:", "Deferred evidence:", 1)
    )

    errors = lint_research_brief_markdown(
        broken,
        mode="evidence_review",
        claim_list=claim_list,
        claim_evidence_map=claim_map,
    )

    assert "missing heading: ## Belief Update" in errors
    assert any("c1" in error and "Table 2" in error for error in errors)
    assert "## Bottom Line missing semantic: Most valuable next evidence:" in errors
