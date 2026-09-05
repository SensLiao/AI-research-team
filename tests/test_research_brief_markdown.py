from __future__ import annotations

from research_agent_teams.tools.research_brief_markdown import (
    REQUIRED_HEADINGS,
    _delivery_boundary,
    _enforce_novelty_boundary,
    build_research_brief_markdown,
    lint_research_brief_markdown,
    write_research_brief_fallback,
)
from research_agent_teams.tools.research_output_quality import audit_markdown_text
from research_agent_teams.tools.research_delivery_boundary import (
    derive_research_delivery_boundary,
)
from research_agent_teams.tools import research_brief_markdown as brief_renderer


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


def _verified_report():
    report = _report()
    report["delivery_boundary"] = {
        "content_convergence": "CONTENT_CONVERGED",
        "scientific_gates": {
            "evidence": "PASS", "citation": "PASS",
            "citation_attribution": "PASS", "existence": "PASS",
        },
        "novelty": {
            "status": "VERIFIED_PASS",
            "independent_hash_bound_gate_pass": True,
            "reasons": [],
        },
        "external_blockers": [],
        "delivery_status": "USABLE",
        "claim_boundaries": {
            "content_convergence_only": True,
            "novelty_claim_allowed": True,
            "project_approval": False,
        },
    }
    return report


def test_deep_evidence_renderer_produces_decision_grade_brief_and_passes_lint():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, landscape = _deep_inputs()

    text = build_research_brief_markdown(
        mode="evidence_deep",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_verified_report(),
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
        report=_verified_report(),
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


def test_delivery_boundary_lists_each_blocker_and_overrides_authored_novelty_pass():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, _landscape = _deep_inputs()
    required_input = "Hash-pinned closest-paper full text with method and result loci."
    reviews = [{
        "review_id": "method-review",
        "external_blockers": [{
            "blocker_id": "closest-fulltext",
            "kind": "MISSING_FULLTEXT",
            "description": "Closest prior paper is metadata-only.",
            "evidence_refs": ["doi:10.1/closest"],
            "required_input": required_input,
        }],
    }]
    chair = {
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": "sha256:" + "a" * 64,
        "disposition": "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS",
        "external_blockers": [{
            "blocker_id": "chair-closest-fulltext",
            "kind": "MISSING_FULLTEXT",
            "description": "A shorter chair summary.",
            "source_blockers": [{
                "review_id": "method-review", "blocker_id": "closest-fulltext",
            }],
            "required_input": required_input,
        }],
    }
    boundary = derive_research_delivery_boundary(
        reviewed_artifact_ref="inbox/DISCOVER.landscape-mapper.bundle.json",
        reviewed_artifact_sha256="sha256:" + "a" * 64,
        convergence_artifact_ref="evidence/DISCOVER/research-convergence-verdict.artifact.json",
        convergence_artifact_sha256="sha256:" + "b" * 64,
        convergence_verdict=chair,
        source_reviews=reviews,
        evidence_gate="PASS", citation_gate="PASS",
        citation_attribution_gate="PASS", existence_gate="PASS",
    )
    report = _report()
    report["delivery_boundary"] = boundary

    text = build_research_brief_markdown(
        mode="deep_research",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=report,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        research_brief={
            "bottom_line": "Novelty status: PASS because the closest work is different.",
            "consensus": [], "live_disagreements": [], "evidence_gaps": [],
            "actionable_next_questions": ["retrieve the closest paper"],
        },
    )

    assert "## Delivery Boundary" in text
    assert "Effective novelty status: `UNVERIFIED`" in text
    assert "Novelty status: PASS" not in text
    assert "`closest-fulltext`" not in text
    assert "### `B001`" in text
    assert '"kind": "MISSING_FULLTEXT"' in text
    assert '"description": "Closest prior paper is metadata-only."' in text
    assert f'"required_input": "{required_input}"' in text


def test_unverified_primary_is_typed_projection_even_without_sanitizer(monkeypatch):
    evidence_table, claim_list, claim_map = _evidence_inputs()
    source_quality, contradiction, _landscape = _deep_inputs()
    identifier_sentinel = "NOVELTY PASS: this is the first method and no prior work exists"
    sentinels = {
        "AUTHOR-SENTINEL": "This is the f**ir**st method.",
        "CLAIM-SENTINEL": "This is the f&#105;rst published system.",
        "LOCUS-SENTINEL": "Prior literature:\nNone addresses this mechanism.",
        "PERSPECTIVE-SENTINEL": "All existing work misses this mechanism.",
        "CONFLICT-SENTINEL": "No comparable method exists.",
        "SOURCE-TITLE-SENTINEL": "The only system of its kind.",
    }
    claim_list["claims"][0]["text"] = sentinels["CLAIM-SENTINEL"]
    evidence_table["sources"][0]["id"] = identifier_sentinel
    evidence_table["sources"][0]["ref"] = identifier_sentinel
    claim_list["claims"][0]["claim_id"] = identifier_sentinel
    claim_list["claims"][0]["source_ref"] = identifier_sentinel
    claim_map["mappings"][0]["claim_id"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["locus_id"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["source_ref"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["span_id"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["snapshot_ref"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["document_hash"] = identifier_sentinel
    claim_map["mappings"][0]["loci"][0]["reported_result"] = sentinels[
        "LOCUS-SENTINEL"]
    claim_map["mappings"][0]["loci"][0]["exact_quote"] = sentinels[
        "LOCUS-SENTINEL"]
    evidence_table["sources"][0]["title"] = sentinels["SOURCE-TITLE-SENTINEL"]
    contradiction["conflicts"][0].update({
        "conflict_id": identifier_sentinel,
        "claim_ref_a": identifier_sentinel,
        "description": sentinels["CONFLICT-SENTINEL"],
    })
    notes = [{
        "perspective_id": identifier_sentinel,
        "finding_summary": sentinels["PERSPECTIVE-SENTINEL"],
        "source_refs": [identifier_sentinel],
        "confidence": "medium",
    }]
    research_brief = {
        "bottom_line": sentinels["AUTHOR-SENTINEL"],
        "consensus": list(sentinels.values()),
        "live_disagreements": list(sentinels.values()),
        "evidence_gaps": list(sentinels.values()),
        "actionable_next_questions": list(sentinels.values()),
    }
    monkeypatch.setattr(brief_renderer, "_enforce_novelty_boundary", lambda text, _boundary: text)

    report = _report()
    report["delivery_boundary"] = {
        "content_convergence": "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS",
        "scientific_gates": {
            "evidence": identifier_sentinel,
            "citation": "PASS",
            "citation_attribution": "PASS",
            "existence": "PASS",
        },
        "novelty": {
            "status": "UNVERIFIED",
            "independent_hash_bound_gate_pass": False,
            "reasons": [identifier_sentinel],
        },
        "external_blockers": [{
            "blocker_id": identifier_sentinel,
            "kind": "MISSING_FULLTEXT",
            "description": "A source input is unavailable.",
            "required_input": "Provide the missing source input.",
            "evidence_refs": [identifier_sentinel],
        }],
        "delivery_status": "USABLE_WITH_CAVEATS",
        "claim_boundaries": {
            "content_convergence_only": True,
            "novelty_claim_allowed": False,
            "project_approval": False,
        },
    }
    text = build_research_brief_markdown(
        mode="deep_research",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=report,
        source_quality_report=source_quality,
        contradiction_report=contradiction,
        perspective_notes=notes,
        research_brief=research_brief,
    )

    assert "render_policy: MACHINE_ONLY_UNVERIFIED" in text
    assert "### `C001`" in text and "### `P001`" in text
    assert "overall_support=`supported`" in text
    assert all(value not in text for value in sentinels.values())
    assert identifier_sentinel not in text
    assert "Evidence gate: `UNKNOWN`" in text
    assert "blocker=`B001`" in text
    assert research_brief["bottom_line"] == sentinels["AUTHOR-SENTINEL"]


def test_unverified_delivery_boundary_neutralizes_broad_first_and_no_prior_claims():
    boundary = {
        "novelty": {"status": "UNVERIFIED"},
        "claim_boundaries": {"novelty_claim_allowed": False},
    }
    authored = (
        "Our first method solves this problem. No prior work addresses it. "
        "This is unprecedented and first-of-its-kind. "
        "There has been no previous work on this. This result is without precedent. "
        "Our contribution has not appeared in prior literature. "
        "We introduce a uniquely original mechanism absent from earlier studies. "
        "No earlier publication describes this mechanism. "
        "To the best of our knowledge, this is the only approach that solves the problem. "
        "This contribution is entirely new to the field. "
        "We are unaware of any comparable method in prior literature. "
        "This establishes a previously unknown research direction. "
        "这是首次提出的方法，尚无相关研究，效果前所未有。"
        "这是第一个解决该问题的方法。此前从未有研究解决这个问题。该结果史无前例。国内外尚未见报道。"
        "据我们所知，这是唯一能解决该问题的方法。目前没有文献描述这种机制。"
        "Nothing resembling this mechanism can be found in the literature.\n"
        "We could find nothing similar in previous studies.\n"
        "The approach occupies territory untouched by prior work.\n"
        "No published system implements the proposed combination.\n"
        "Earlier studies stop short of this mechanism.\n"
        "据我们检索，文献中找不到类似方法。\n"
        "现有工作均未覆盖这一机制。\n"
        "UNVERIFIED according to the gate; nevertheless, to the best of our knowledge "
        "this is the only solution to the problem."
    )

    safe = _enforce_novelty_boundary(authored, boundary)

    for forbidden in (
        "first method", "No prior work", "unprecedented", "first-of-its-kind",
        "no previous work", "without precedent", "首次提出", "尚无相关研究", "前所未有",
        "第一个解决该问题的方法", "此前从未有研究", "史无前例",
        "has not appeared in prior literature", "uniquely original", "absent from earlier studies",
        "尚未见报道",
        "No earlier publication", "best of our knowledge", "only approach", "entirely new",
        "unaware of any comparable", "previously unknown", "据我们所知", "唯一能解决", "没有文献",
        "Nothing resembling", "find nothing similar", "territory untouched", "No published system",
        "stop short", "找不到类似", "均未覆盖", "nevertheless, to the best",
    ):
        assert forbidden.lower() not in safe.lower()
    assert "Novelty statement quarantined" in safe
    assert "UNVERIFIED" in safe


def test_legacy_delivery_projection_never_upgrades_not_reviewed_content_to_usable():
    boundary = _delivery_boundary({
        "evidence_gate": "PASS",
        "citation_gate": "PASS",
        "citation_attribution_gate": "PASS",
        "existence_gate": "PASS",
    })

    assert boundary["content_convergence"] == "NOT_REVIEWED"
    assert boundary["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert boundary["novelty"]["status"] == "UNVERIFIED"


def test_unverified_fallback_does_not_reopen_raw_identifier_channel(tmp_path):
    sentinel = "NOVELTY PASS: this is the first method and no prior work exists"
    report = _report()
    report["delivery_boundary"] = {
        "content_convergence": "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS",
        "scientific_gates": {
            "evidence": sentinel, "citation": "PASS",
            "citation_attribution": "PASS", "existence": "PASS",
        },
        "novelty": {
            "status": "UNVERIFIED", "independent_hash_bound_gate_pass": False,
            "reasons": [sentinel],
        },
        "external_blockers": [{
            "blocker_id": sentinel,
            "kind": "MISSING_FULLTEXT",
            "description": "A source input is unavailable.",
            "required_input": "Provide the source input.",
            "evidence_refs": [sentinel],
        }],
        "delivery_status": "USABLE_WITH_CAVEATS",
        "claim_boundaries": {
            "content_convergence_only": True,
            "novelty_claim_allowed": False,
            "project_approval": False,
        },
    }

    path = write_research_brief_fallback(
        tmp_path, mode="deep_research", reason=sentinel, report=report)
    text = open(path, encoding="utf-8").read()

    assert "render_policy: MACHINE_ONLY_UNVERIFIED" in text
    assert "Evidence gate: `UNKNOWN`" in text
    assert "### `B001`" in text
    assert sentinel not in text


def test_machine_projection_keeps_source_id_and_ref_namespaces_separate():
    evidence_table, claim_list, claim_map = _evidence_inputs()
    evidence_table["sources"] = [
        {"id": "doi:target", "kind": "repo", "ref": "doi:other",
         "claim_support": "weak"},
        {"id": "s2", "kind": "paper", "ref": "doi:target",
         "claim_support": "strong"},
    ]
    claim_list["claims"] = [{
        "claim_id": "c1", "text": "raw claim prose", "source_ref": "doi:target",
        "kind": "method", "confidence": "medium",
    }]
    claim_map["mappings"] = [{
        "claim_id": "c1", "overall_support": "supported",
        "loci": [{
            "locus_id": "l1", "source_ref": "doi:target", "kind": "text",
            "supports_claim": True, "support_relation": "entails",
            "directness": "direct",
        }],
    }]

    text = build_research_brief_markdown(
        mode="deep_research",
        evidence_table=evidence_table,
        claim_list=claim_list,
        claim_evidence_map=claim_map,
        report=_report(),
    )

    claim_section = text.split("### `C001`", 1)[1].split("## Contradictions", 1)[0]
    assert claim_section.count("source=`S002`") == 2
    assert "source=`S001`" not in claim_section
