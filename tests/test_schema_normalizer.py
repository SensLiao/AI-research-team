from __future__ import annotations

from research_agent_teams.operate.modes import _shared
from research_agent_teams.tools.schema_normalizer import normalize_payload
from research_agent_teams.tools.validate_artifact import validate_payload


def test_evidence_table_rich_aliases_are_projected_losslessly_for_delivery():
    source_shapes = [
        ("paper", "paper"),
        ("paper", "paper"),
        ("preprint", "paper"),
        ("preprint", "paper"),
        ("benchmark", "benchmark"),
        ("paper", "paper"),
        ("dataset", "dataset"),
    ]
    payload = {
        "evidence_contract_version": "evidence-table/v2",
        "source_quality_report_ref": "evidence/source-quality.json",
        "search_trace_ref": "evidence/search-trace.json",
        "query": "PET/CT intent residual correction",
        "sources": [
            {
                "id": f"s{index}",
                "ref": f"doi:10.1/{index}",
                "type": rich_type,
                "kind": canonical_kind,
                "note": f"source {index} boundary",
                "notes": f"source {index} boundary",
            }
            for index, (rich_type, canonical_kind) in enumerate(source_shapes, start=1)
        ],
        "saturation_reached": False,
    }

    normalized, report = normalize_payload("evidence_table", payload)

    assert not validate_payload("evidence_table", normalized)
    assert normalized["n_sources"] is None
    assert all("type" not in row and "note" not in row for row in normalized["sources"])
    assert [row["kind"] for row in normalized["sources"]][2:4] == ["paper", "paper"]
    assert len(report["preserved_extras"]) == 14
    assert report["representation_conflicts"] == []
    assert payload["sources"][2]["type"] == "preprint"
    assert "n_sources" not in payload


def test_evidence_table_alias_conflict_is_never_silently_selected():
    payload = {
        "query": "q",
        "sources": [{
            "id": "s1", "ref": "doi:10.1/x", "kind": "paper", "type": "dataset",
            "notes": "canonical account", "note": "different account",
        }],
        "saturation_reached": False,
    }

    normalized, report = normalize_payload("evidence_table", payload)

    assert normalized["sources"][0]["kind"] == "paper"
    assert normalized["sources"][0]["notes"] == "canonical account"
    assert {row["rule"] for row in report["representation_conflicts"]} == {
        "conflicting-evidence-note-alias",
        "conflicting-evidence-type-alias",
    }


def test_valid_canonical_evidence_fields_win_over_conflicting_aliases_with_advisory(tmp_path):
    payload = {
        "query": "q",
        "sources": [{
            "id": "s1", "ref": "doi:10.1/x", "kind": "paper", "type": "dataset",
            "notes": "canonical account", "note": "different account",
        }],
        "saturation_reached": False,
    }

    normalized, errors, report = _shared.normalize_worker_payload(
        tmp_path, "DISCOVER", "lit-scout", "evidence_table", payload,
    )

    assert errors == []
    assert normalized["sources"][0]["kind"] == "paper"
    assert normalized["sources"][0]["notes"] == "canonical account"
    assert len(report["representation_advisories"]) == 2
    assert report["blocking_representation_conflicts"] == []


def test_normalization_is_idempotent_and_preserves_richer_fields_in_sidecar():
    payload = {
        "source_ref": "doi:10.1/example",
        "verdict": "needs reread",
        "coverage": "partial",
        "single_paper_completeness": "partial",
        "source_fidelity": "mixed",
        "visual_coverage": "not applicable",
        "evidence_saturation": "not assessed single paper",
        "anchoring": "mixed",
        "method_depth": "mixed",
        "figure_table_coverage": "partial",
        "result_table_depth": "mixed",
        "algorithmic_depth": "not applicable",
        "reproducibility_depth": "mixed",
        "project_alignment": "mixed",
        "domain_transfer_honesty": "strong",
        "independent_critique_resolution": "resolved",
        "markdown_ready": False,
        "promotion_ready": False,
        "worker_extra_analysis": {"useful": "preserve me"},
    }
    normalized, report = normalize_payload("paper_reading_quality", payload)
    assert normalized["verdict"] == "NEEDS_SUPPLEMENT"
    assert normalized["visual_coverage"] == "not-applicable"
    assert "worker_extra_analysis" not in normalized
    assert report["preserved_extras"][0]["value"] == {"useful": "preserve me"}
    assert not validate_payload("paper_reading_quality", normalized)
    twice, second = normalize_payload("paper_reading_quality", normalized)
    assert twice == normalized
    assert second["changes"] == []


def test_normalizer_never_coerces_scientific_types_or_values():
    payload = {"source_ref": "x", "verdict": "PASS", "markdown_ready": "true"}
    normalized, _report = normalize_payload("paper_reading_quality", payload)
    assert normalized["markdown_ready"] == "true"
    assert validate_payload("paper_reading_quality", normalized)


def test_unknown_nullable_enum_is_never_silently_erased_to_null():
    payload = {
        "title": "Paper", "source_ref": "paper.pdf", "summary": "Summary",
        "claims": [], "paper_type": "not-a-real-paper-type",
    }

    normalized, report = normalize_payload("paper_note", payload)

    assert normalized["paper_type"] == "not-a-real-paper-type"
    assert validate_payload("paper_note", normalized)
    assert not any(
        row["pointer"] == "/paper_type" and row["rule"] == "canonical-enum"
        for row in report["changes"]
    )


def test_normalizer_losslessly_serializes_richer_structured_text_fields():
    payload = {
        "source_ref": "paper",
        "applicability": "applicable",
        "formal_objects": [{"object": "x", "definition": "y"}],
        "equations_or_rules": ["x=y"],
        "implementation_assumptions": [{"assumption": "closed set", "risk": "open set"}],
        "algorithm_flow": {"train": ["a", "b"], "infer": "c"},
        "equation_consistency": "internally mixed",
        "complexity_or_cost": None,
        "numerical_stability": "not reported",
        "edge_cases": ["empty target"],
        "red_flags": [{"severity": "high", "issue": "scope"}],
        "overall": "mixed",
    }
    normalized, report = normalize_payload("math_algorithm_audit", payload)
    assert not validate_payload("math_algorithm_audit", normalized)
    assert '"object":"x"' in normalized["formal_objects"][0]
    assert '"risk":"open set"' in normalized["implementation_assumptions"][0]
    assert '"train":["a","b"]' in normalized["algorithm_flow"]
    assert any(row["rule"] == "structured-value-to-canonical-json-text" for row in report["changes"])


def test_normalizer_adapts_path_style_blind_reader_receipts_without_broadening_scope():
    payload = {
        "source_ref": "paper.pdf",
        "reading_mode": "blind_second_read",
        "primary_analysis_seen": False,
        "allowed_input_classes": [
            "task_frame.artifact.json", "inbox/fulltext-docs/**",
            "inbox/fulltext-qa.json", "inbox/citation-snapshots/**",
            "inbox/paper-visual-manifest.json", "inbox/paper-visuals/**",
        ],
        "consumed_inputs": [
            "task_frame.artifact.json", "inbox/fulltext-docs/paper.pdf",
            "inbox/fulltext-qa.json", "inbox/citation-snapshots/context.txt",
            "inbox/paper-visual-manifest.json", "inbox/paper-visuals/doc/page.png",
        ],
        "independent_summary": {
            "claims": ["claim"], "method": "method", "key_results": "result",
            "limitations": ["limit"],
        },
        "verdict": "PASS_WITH_CAVEATS",
        "disagreements": [], "overclaim_risks": [], "required_repairs": [],
    }
    normalized, report = normalize_payload("independent_reading_critique", payload)
    assert not validate_payload("independent_reading_critique", normalized)
    assert normalized["allowed_input_classes"] == [
        "task_frame", "source_document", "fulltext_snapshot", "visual_snapshot"
    ]
    assert normalized["consumed_inputs"][3] == {
        "input_class": "fulltext_snapshot", "ref": "inbox/citation-snapshots/context.txt"
    }
    assert normalized["independent_summary"]["key_results"] == ["result"]
    assert {row["rule"] for row in report["changes"]} >= {
        "blind-paths-to-input-classes", "blind-path-receipts-to-objects", "single-text-to-array"
    }


def test_normalizer_applies_receipt_and_promotion_only_verdict_adapters_together():
    payload = {
        "source_ref": "paper.pdf",
        "reading_mode": "blind_second_read",
        "primary_analysis_seen": False,
        "allowed_input_classes": [
            "task_frame.artifact.json", "inbox/fulltext-docs/**",
        ],
        "consumed_inputs": [
            "task_frame.artifact.json", "inbox/fulltext-docs/paper.pdf",
        ],
        "independent_summary": {
            "claims": ["claim"], "method": "method",
            "key_results": ["result"], "limitations": ["limit"],
        },
        "verdict": "BLOCK_FOR_PROMOTION",
        "disagreements": [], "overclaim_risks": [], "required_repairs": [],
    }
    normalized, report = normalize_payload("independent_reading_critique", payload)
    assert not validate_payload("independent_reading_critique", normalized)
    assert normalized["allowed_input_classes"] == ["task_frame", "source_document"]
    assert normalized["consumed_inputs"][1] == {
        "input_class": "source_document", "ref": "inbox/fulltext-docs/paper.pdf"
    }
    assert normalized["verdict"] == "PASS_WITH_CAVEATS"
    assert {row["rule"] for row in report["changes"]} >= {
        "blind-paths-to-input-classes", "blind-path-receipts-to-objects",
        "promotion-only-block-to-delivery-caveat",
    }


def test_normalizer_preserves_blind_narrative_summary_in_typed_shape():
    payload = {
        "source_ref": "paper.pdf",
        "reading_mode": "blind_second_read",
        "primary_analysis_seen": False,
        "allowed_input_classes": [
            "task_frame", "source_document", "fulltext_snapshot", "visual_snapshot"
        ],
        "consumed_inputs": [
            {"input_class": "task_frame", "ref": "task_frame.artifact.json"},
            {"input_class": "source_document", "ref": "inbox/fulltext-docs/paper.pdf"},
            {"input_class": "fulltext_snapshot", "ref": "inbox/fulltext-qa.json"},
            {"input_class": "visual_snapshot", "ref": "inbox/paper-visual-manifest.json"},
        ],
        "independent_summary": "A complete blind narrative with method, results, and limits.",
        "verdict": "PASS_WITH_CAVEATS",
        "disagreements": [],
        "missed_claims": [],
        "overclaim_risks": ["Do not overclaim transfer."],
        "alternative_interpretations": [],
        "required_repairs": [],
        "director_warning": None,
    }
    normalized, report = normalize_payload("independent_reading_critique", payload)
    assert not validate_payload("independent_reading_critique", normalized)
    assert normalized["independent_summary"]["claims"] == [payload["independent_summary"]]
    assert normalized["independent_summary"]["method"] == payload["independent_summary"]
    assert normalized["independent_summary"]["limitations"] == payload["overclaim_risks"]
    assert "blind-narrative-summary-to-typed-summary" in {
        row["rule"] for row in report["changes"]
    }


def test_normalizer_maps_rich_blind_reader_summary_without_losing_scientific_content():
    payload = {
        "source_ref": "paper.pdf",
        "reading_mode": "blind_second_read",
        "primary_analysis_seen": False,
        "allowed_input_classes": [
            "task_frame", "source_document", "fulltext_snapshot", "visual_snapshot"
        ],
        "consumed_inputs": [
            {"input_class": "task_frame", "ref": "task_frame.artifact.json"},
            {"input_class": "source_document", "ref": "paper.pdf"},
        ],
        "independent_summary": {
            "problem_and_claims": "claim boundary",
            "hard_cldice": "hard method",
            "theorem_scope": "narrow theorem",
            "soft_cldice_and_training": "soft method",
            "key_results_and_numbers": "mixed results",
            "limitations_and_failure_boundary": "transfer limit",
            "iac_cbct_no_harm_boundary": "not a safety proof",
        },
        "verdict": "PASS_WITH_CAVEATS",
        "disagreements": [],
        "missed_claims": [],
        "overclaim_risks": [],
        "alternative_interpretations": [],
        "required_repairs": [],
        "director_warning": None,
    }
    normalized, report = normalize_payload("independent_reading_critique", payload)
    assert not validate_payload("independent_reading_critique", normalized)
    assert normalized["independent_summary"]["claims"] == ["claim boundary"]
    assert "hard method" in normalized["independent_summary"]["method"]
    assert "narrow theorem" in normalized["independent_summary"]["method"]
    assert normalized["independent_summary"]["key_results"] == ["mixed results"]
    assert normalized["independent_summary"]["limitations"] == ["transfer limit"]
    assert "rich-blind-summary-to-typed-summary" in {
        row["rule"] for row in report["changes"]
    }


def test_normalizer_maps_rich_paper_structure_status_and_supplement_aliases():
    payload = {
        "source_ref": "paper.pdf",
        "sections": [
            {"section": "Abstract", "status": "read", "role": "states claims", "pages": [1]},
            {"section": "References", "status": "available_not_deep_read", "role": "bibliography"},
        ],
        "figures": [{
            "figure_ref": "Figure 1", "status": "read", "load_bearing": True,
            "caption_role": "motivation", "page": 1,
        }],
        "tables": [{
            "table_ref": "Table 1", "status": "read", "load_bearing": True,
            "boundary": "no uncertainty", "page": 7,
        }],
        "supplements": [
            {"supplement_ref": "Supplement", "status": "not_available_in_run", "reason": "missing"},
            {"supplement_ref": "Code", "status": "reference_visible_not_inspected", "reference": "url"},
        ],
    }
    normalized, report = normalize_payload("paper_structure", payload)
    assert not validate_payload("paper_structure", normalized)
    assert normalized["sections"][0] == {
        "section_ref": "Abstract", "role": "states claims", "read_status": "read",
        "key_points": ["states claims"],
    }
    assert normalized["sections"][1]["read_status"] == "skimmed"
    assert normalized["figures"][0]["read_status"] == "read"
    assert normalized["tables"][0]["reason"] == "no uncertainty"
    assert normalized["supplements"][0]["ref"] == "Supplement"
    assert normalized["supplements"][0]["read_status"] == "not-available"
    assert normalized["supplements"][1]["read_status"] == "not-read"
    assert "paper-inventory-aliases-to-typed-coverage" in {
        row["rule"] for row in report["changes"]
    }


def test_normalizer_maps_qualified_claim_support_and_figure_region():
    payload = {
        "source_ref": "paper.pdf",
        "mappings": [
            {
                "claim_id": "c1", "overall_support": "supported", "claim_risk": "high",
                "loci": [{
                    "locus_id": "c1-l1", "source_ref": "paper.pdf", "location": "Figure 5",
                    "kind": "figure", "reported_result": "selected examples",
                    "supports_claim": True, "support_relation": "bounds", "directness": "derived",
                    "span_id": "s1", "snapshot_ref": "snapshot.txt", "document_hash": "a" * 64,
                    "parser_version": "p/v1", "exact_quote": "caption", "page": 7,
                    "locator_confidence": "high", "extraction_ref": "manifest#1",
                }],
            },
            {
                "claim_id": "c2", "overall_support": "supported", "claim_risk": "high",
                "loci": [{
                    "locus_id": "c2-l1", "source_ref": "paper.pdf", "location": "Table 1",
                    "kind": "table", "reported_result": "no intervals",
                    "supports_claim": True, "support_relation": "supports_absence",
                    "directness": "complete-source-absence", "span_id": "s2",
                    "snapshot_ref": "snapshot.txt", "document_hash": "b" * 64,
                    "parser_version": "p/v1", "exact_quote": "table", "char_start": 0,
                    "char_end": 5, "page": 7, "locator_confidence": "high",
                    "extraction_ref": "manifest#2",
                }],
            },
        ],
    }
    normalized, report = normalize_payload("claim_evidence_map", payload)
    assert not validate_payload("claim_evidence_map", normalized)
    first = normalized["mappings"][0]["loci"][0]
    second = normalized["mappings"][1]["loci"][0]
    assert (first["support_relation"], first["directness"]) == ("partial", "indirect")
    assert first["figure_region_ref"] == "Figure 5"
    assert (second["support_relation"], second["directness"]) == ("entails", "indirect")
    assert "figure-location-to-region-ref" in {row["rule"] for row in report["changes"]}


def test_normalizer_uses_hash_bound_caption_span_instead_of_fake_visual_locator():
    payload = {
        "source_ref": "paper.pdf",
        "mappings": [{
            "claim_id": "c1",
            "overall_support": "supported",
            "loci": [{
                "locus_id": "c1-l1",
                "source_ref": "paper.pdf",
                "location": "Figure 2 labels and caption",
                "kind": "figure",
                "reported_result": "the caption states the conditioning mechanism",
                "supports_claim": True,
                "support_relation": "entails",
                "directness": "direct",
                "span_id": "span-c1",
                "snapshot_ref": "inbox/citation-snapshots/fulltext-contexts.txt",
                "document_hash": "a" * 64,
                "parser_version": "pymupdf-page-text/v1",
                "exact_quote": "caption text",
                "char_start": 10,
                "char_end": 22,
                "figure_region_ref": "Figure 2, labels and caption",
            }],
        }],
    }

    normalized, report = normalize_payload("claim_evidence_map", payload)

    assert not validate_payload("claim_evidence_map", normalized)
    assert normalized["mappings"][0]["loci"][0]["kind"] == "text"
    assert "figure-caption-char-span-to-text-locus" in {
        row["rule"] for row in report["changes"]
    }


def test_normalizer_preserves_keyed_paper_note_sections_as_lines():
    payload = {
        "title": "Paper", "source_ref": "doi:test", "summary": "Summary", "claims": [],
        "methods": {"architecture": "A", "losses": ["L1", "L2"]},
        "datasets": {"training": ["D1"], "boundary": "2D only"},
        "metrics": {"primary": "Dice", "direction": {"Dice": "higher"}},
    }
    normalized, report = normalize_payload("paper_note", payload)
    assert not validate_payload("paper_note", normalized)
    assert normalized["methods"] == ["architecture: A", 'losses: ["L1", "L2"]']
    assert normalized["datasets"][0] == 'training: ["D1"]'
    assert normalized["metrics"][1] == 'direction: {"Dice": "higher"}'
    assert {row["rule"] for row in report["changes"]} >= {
        "keyed-note-section-to-lossless-lines"
    }


def test_normalizer_maps_structured_paper_note_status_and_relation():
    payload = {
        "title": "Paper", "source_ref": "doi:test", "summary": "Summary",
        "claims": [], "methods": [], "datasets": [], "metrics": [],
        "relation_to_thesis": {
            "direct_collision": ["broad claim"],
            "remaining_distinction": ["narrow claim"],
        },
        "reading_status": {
            "stage": "Stage-0 + Pass-1 complete",
            "confidence": "provisional_pending_specialist_audit",
        },
    }
    normalized, report = normalize_payload("paper_note", payload)
    assert not validate_payload("paper_note", normalized)
    assert normalized["relation_to_thesis"] == "A-core"
    assert normalized["reading_status"] == "skimmed"
    assert {row["rule"] for row in report["changes"]} >= {
        "structured-thesis-relation-to-class",
        "structured-reading-status-to-stage",
    }


def test_normalizer_maps_json_encoded_structured_project_relevance():
    payload = {
        "source_ref": "doi:test", "project_context": "p",
        "relevance": '{"overall":"A-core for baseline; not semantic proof","notes":["x"]}',
        "thesis_fit": "baseline only", "downstream_decisions": ["d"], "misuse_risks": ["r"],
    }
    normalized, report = normalize_payload("project_context_alignment", payload)
    assert not validate_payload("project_context_alignment", normalized)
    assert normalized["relevance"] == "A-core"
    assert "structured-relevance-to-class" in {row["rule"] for row in report["changes"]}


def test_normalizer_maps_qualified_claim_locus_relations_without_losing_quote():
    quote = "q" * 700
    payload = {
        "attribution_contract_version": "claim-span/v1",
        "mappings": [{
            "claim_id": "c1", "overall_support": "partial",
            "claim_risk": {"level": "medium", "note": "n"},
            "loci": [{
                "locus_id": "l1", "source_ref": "doi:test", "location": "p.1",
                "kind": "text", "reported_result": "r", "supports_claim": True,
                "support_relation": "absence_audit", "directness": "inferential",
                "span_id": "s1", "snapshot_ref": "snap", "document_hash": "a" * 64,
                "parser_version": "p", "exact_quote": quote, "char_start": 0,
                "char_end": len(quote),
            }],
        }],
    }
    normalized, _ = normalize_payload("claim_evidence_map", payload)
    assert not validate_payload("claim_evidence_map", normalized)
    locus = normalized["mappings"][0]["loci"][0]
    assert locus["support_relation"] == "partial"
    assert locus["directness"] == "indirect"
    assert locus["exact_quote"] == quote


def test_normalizer_preserves_keyed_loss_terms_as_lines():
    payload = {
        "source_ref": "doi:test", "problem_definition": "p", "core_assumptions": ["a"],
        "representation": "r", "loss_terms": {"objective": "NFL", "detail": {"gamma": None}},
        "training_flow": ["t"], "inference_flow": ["i"],
        "train_infer_consistency": "partial", "data": "d", "cost": "c",
        "baseline_difference": "b",
    }
    normalized, report = normalize_payload("method_teardown", payload)
    assert not validate_payload("method_teardown", normalized)
    assert normalized["loss_terms"] == [
        {"term": "objective", "role": "NFL", "ablate_effect": ""},
        {"term": "detail", "role": '{"gamma": null}', "ablate_effect": ""},
    ]
    assert "keyed-loss-terms-to-lossless-lines" in {row["rule"] for row in report["changes"]}


def test_normalizer_preserves_keyed_formal_objects_as_lines():
    payload = {
        "source_ref": "doi:test", "applicability": "applicable",
        "formal_objects": {"state": ["x", "y"], "loss": "NFL"},
        "algorithm_flow": "flow", "equation_consistency": "mixed",
        "complexity_or_cost": None, "implementation_assumptions": [], "red_flags": [],
        "overall": "mixed",
    }
    normalized, report = normalize_payload("math_algorithm_audit", payload)
    assert not validate_payload("math_algorithm_audit", normalized)
    assert normalized["formal_objects"] == ['state: ["x", "y"]', "loss: NFL"]
    assert "keyed-formal-objects-to-lossless-lines" in {row["rule"] for row in report["changes"]}


def test_normalizer_descends_into_nullable_objects_and_preserves_extras():
    payload = {
        "title": "Paper", "source_ref": "doi:test", "summary": "Summary", "claims": [],
        "paper_contract": {
            "category": "protocol", "contract_sentence": "problem -> evidence",
            "richer_boundary": {"useful": "keep in sidecar"},
        },
    }
    normalized, report = normalize_payload("paper_note", payload)
    assert not validate_payload("paper_note", normalized)
    assert "richer_boundary" not in normalized["paper_contract"]
    assert report["preserved_extras"] == [{
        "pointer": "/paper_contract/richer_boundary",
        "value": {"useful": "keep in sidecar"},
    }]


def test_normalizer_adapts_human_paper_section_inventory():
    payload = {
        "source_ref": "paper.pdf",
        "sections": [{
            "title": "Methods", "pages": "3-5",
            "coverage": "training and inference flow", "load_bearing": True,
        }],
        "figures": [], "tables": [],
    }
    normalized, report = normalize_payload("paper_structure", payload)
    assert not validate_payload("paper_structure", normalized)
    assert normalized["sections"] == [{
        "section_ref": "Methods", "role": "training and inference flow",
        "read_status": "read", "key_points": ["training and inference flow"],
    }]
    assert any(
        row["rule"] == "human-section-inventory-to-typed-sections"
        for row in report["changes"]
    )


def test_normalizer_adapts_paper_visual_inventory_aliases_losslessly():
    payload = {
        "source_ref": "paper.pdf",
        "sections": [],
        "figures": [{
            "id": "Figure 1", "read": True,
            "load_bearing": True, "title_or_content": "method overview",
        }],
        "tables": [{
            "id": "Table 1", "inspection_status": "inspected",
            "load_bearing": True, "title_or_content": "results",
        }],
        "supplements": [{
            "id": "Video 1", "read_status": "unread",
            "availability_in_run": "not provided",
        }, {
            "id": "Appendix", "read_status": "unknown",
            "availability_in_run": "not identified",
        }],
    }
    normalized, report = normalize_payload("paper_structure", payload)
    assert not validate_payload("paper_structure", normalized)
    assert normalized["figures"][0] == {
        "figure_ref": "Figure 1", "read_status": "read", "load_bearing": True,
    }
    assert normalized["tables"][0] == {
        "table_ref": "Table 1", "read_status": "read", "load_bearing": True,
    }
    assert normalized["supplements"] == [
        {"ref": "Video 1", "read_status": "not-read", "reason": "not provided"},
        {"ref": "Appendix", "read_status": "not-available", "reason": "not identified"},
    ]
    assert sum(
        row["rule"] == "paper-inventory-aliases-to-typed-coverage"
        for row in report["changes"]
    ) == 4


def test_normalizer_extracts_project_relevance_class_from_richer_note():
    payload = {
        "source_ref": "paper.pdf",
        "project_context": {"project": "p", "decision": "d"},
        "relevance": {"class": "A-core", "reason": "changes the baseline"},
        "thesis_fit": {"supports": ["baseline"]},
        "downstream_decisions": [{"decision": "use", "recommendation": "with caveats"}],
    }
    normalized, report = normalize_payload("project_context_alignment", payload)
    assert not validate_payload("project_context_alignment", normalized)
    assert normalized["relevance"] == "A-core"
    assert '"project":"p"' in normalized["project_context"]
    assert any(row["rule"] == "structured-relevance-to-class" for row in report["changes"])
    assert report["scientific_fields_modified"] is True
    assert {row["rule"] for row in report["heuristic_scientific_changes"]} == {
        "structured-relevance-to-class"
    }


def test_heuristic_scientific_projection_is_readable_but_requires_worker_confirmation(tmp_path):
    payload = {
        "source_ref": "paper.pdf",
        "project_context": {"project": "p", "decision": "d"},
        "relevance": {"class": "A-core", "reason": "changes the baseline"},
        "thesis_fit": {"supports": ["baseline"]},
        "downstream_decisions": [{"decision": "use", "recommendation": "with caveats"}],
    }

    normalized, errors, report = _shared.normalize_worker_payload(
        tmp_path, "DISCOVER", "project-aligner", "project_context_alignment", payload,
    )

    assert normalized["relevance"] == "A-core"
    assert any("requires worker confirmation" in error for error in errors)
    assert report["scientific_fields_modified"] is True


def test_normalizer_adapts_richer_claim_locus_representation():
    payload = {
        "attribution_contract_version": "claim-span/v1",
        "mappings": [{
            "claim_id": "c1", "overall_support": "partial",
            "claim_risk": "high; absence depends on full-document review",
            "loci": [{
                "source_ref": "paper", "location": "p.1", "kind": "text_span",
                "reported_result": "planned release", "supports_claim": True,
                "support_relation": "partial_context_only",
                "directness": "indirect_absence_inference", "span_id": "SPAN-1",
                "snapshot_ref": "snapshot.txt", "document_hash": "a" * 64,
                "parser_version": "v1", "char_start": 0, "char_end": 15,
                "exact_quote": "planned release",
            }],
        }],
    }
    normalized, report = normalize_payload("claim_evidence_map", payload)
    assert not validate_payload("claim_evidence_map", normalized)
    locus = normalized["mappings"][0]["loci"][0]
    assert locus["locus_id"] == "SPAN-1"
    assert locus["kind"] == "text"
    assert locus["support_relation"] == "partial"
    assert locus["directness"] == "indirect"
    assert normalized["mappings"][0]["claim_risk"] == {
        "level": "high", "note": "absence depends on full-document review"
    }
    assert {row["rule"] for row in report["changes"]} >= {
        "stable-locus-id", "canonical-locus-kind", "canonical-support-relation",
        "canonical-directness", "risk-text-to-object",
    }


def test_normalizer_canonicalizes_boundary_and_absence_locus_labels():
    payload = {
        "attribution_contract_version": "claim-span/v1",
        "mappings": [{
            "claim_id": "c1", "overall_support": "partial", "claim_risk": "high",
            "loci": [{
                "locus_id": "c1-l1", "source_ref": "paper", "location": "complete PDF",
                "kind": "text", "reported_result": "seed is not reported",
                "supports_claim": True, "support_relation": "absence_boundary",
                "directness": "inferred_from_complete_source_absence",
                "span_id": "SPAN-1",
                "snapshot_ref": "snapshot.txt", "document_hash": "a" * 64,
                "parser_version": "v1", "char_start": 0, "char_end": 20,
                "exact_quote": "seed is not reported",
            }],
        }, {
            "claim_id": "c2", "overall_support": "supported", "claim_risk": "medium",
            "loci": [{
                "locus_id": "c2-l1", "source_ref": "paper", "location": "table footnote",
                "kind": "table", "reported_result": "comparator is defined",
                "supports_claim": True, "support_relation": "boundary_support",
                "directness": "direct_for_reported_comparator; inferred_for_absence",
                "span_id": "SPAN-2",
                "snapshot_ref": "snapshot.txt", "document_hash": "a" * 64,
                "parser_version": "v1", "char_start": 21, "char_end": 42,
                "exact_quote": "comparator is defined",
            }],
        }],
    }
    normalized, _ = normalize_payload("claim_evidence_map", payload)
    assert not validate_payload("claim_evidence_map", normalized)
    first = normalized["mappings"][0]["loci"][0]
    second = normalized["mappings"][1]["loci"][0]
    assert (first["support_relation"], first["directness"]) == ("entails", "indirect")
    assert (second["support_relation"], second["directness"]) == ("entails", "indirect")


def test_normalizer_extracts_not_applicable_result_table_verdict():
    payload = {
        "source_ref": "protocol.pdf", "applicability": "not_applicable",
        "audited_items": [], "metric_direction_checks": [],
        "baseline_binding_checks": [], "statistical_reporting": "none observed",
        "overall": {
            "verdict": "NOT_APPLICABLE_FOR_RESULT_TABLES",
            "evidence_strength": "protocol only",
        },
    }
    normalized, report = normalize_payload("result_table_audit", payload)
    assert not validate_payload("result_table_audit", normalized)
    assert normalized["applicability"] == "not-applicable"
    assert normalized["overall"] == "not-applicable"
    assert any(
        row["rule"] == "structured-result-verdict-to-enum"
        for row in report["changes"]
    )


def test_normalizer_adapts_rich_result_items_and_keyed_split_risks():
    payload = {
        "source_ref": "paper.pdf", "applicability": "applicable",
        "audited_items": [{
            "item_ref": "Table 1", "claim_ids": [],
            "comparison": "A versus B", "numeric_check": "values match",
            "statistical_check": "no CI", "fairness": "matched input",
            "verdict": "supports with caveats",
        }],
        "metric_direction_checks": "Dice higher is better",
        "baseline_binding_checks": "bound to rows",
        "statistical_reporting": "limited",
        "leakage_or_split_risks": {
            "cohort": {"split": "case-level", "risk": "small test set"},
        },
        "overall": "mixed",
    }
    normalized, report = normalize_payload("result_table_audit", payload)
    assert not validate_payload("result_table_audit", normalized)
    item = normalized["audited_items"][0]
    assert item["claim_id"] == "unmapped"
    assert item["metric"] == "multiple reported metrics"
    assert item["reported_comparison"] == "A versus B"
    assert "numeric_check: values match" in item["audit"]
    assert normalized["leakage_or_split_risks"] == [
        'cohort: {"risk":"small test set","split":"case-level"}'
    ]
    assert {row["rule"] for row in report["changes"]} >= {
        "rich-result-item-to-typed-audit", "keyed-split-risks-to-lossless-lines",
    }


def test_normalizer_wraps_medical_imaging_checklist_list():
    payload = {
        "source_ref": "paper.pdf",
        "dimensions": [{
            "dim": "domain_validity", "score": None,
            "note": "not applicable to a methodological paper",
        }],
        "medical_imaging_checklist": [{
            "standard_ref": "claim", "item_id": "CLAIM-MI-01",
            "category": "patient_split", "status": "partial",
            "evidence_ref": "Methods", "risk": "Exact IDs are missing.",
            "required_fix": "publish IDs",
        }, {
            "standard_ref": "cross_standard", "item_id": "CROSS-MI-01",
            "category": "clinical_claim_boundary", "status": "met",
            "evidence_ref": "Discussion", "risk": "Technical scope is explicit.",
            "required_fix": None,
        }],
    }
    normalized, report = normalize_payload("paper_appraisal", payload)
    assert not validate_payload("paper_appraisal", normalized)
    assert normalized["medical_imaging_checklist"]["standard_refs"] == ["claim"]
    assert len(normalized["medical_imaging_checklist"]["items"]) == 2
    first, second = normalized["medical_imaging_checklist"]["items"]
    assert first["risk"] == "medium"
    assert "Risk rationale: Exact IDs are missing." in first["required_fix"]
    assert second["risk"] == "low"
    assert "required_fix" not in second
    assert "risk rationale: Technical scope is explicit." in second["evidence_ref"]
    assert any(
        row["rule"] == "medical-checklist-list-to-typed-object"
        for row in report["changes"]
    )


def test_normalizer_adapts_keyed_domain_transfer_notes_losslessly():
    payload = {
        "source_ref": "paper.pdf", "target_context": "target",
        "transfer_level": "indirect",
        "usable_for": {"legitimate_uses": ["baseline"], "bottom_line": "indirect only"},
        "not_usable_for": ["target performance"],
        "evidence_limits": {"coverage_gap": "no target data"},
        "required_local_validation": ["paired local test"],
    }
    normalized, report = normalize_payload("domain_transfer_note", payload)
    assert not validate_payload("domain_transfer_note", normalized)
    assert normalized["usable_for"] == [
        'legitimate_uses: ["baseline"]', 'bottom_line: indirect only',
    ]
    assert normalized["evidence_limits"] == ["coverage_gap: no target data"]
    assert sum(
        row["rule"] == "keyed-transfer-note-to-lossless-lines"
        for row in report["changes"]
    ) == 2


def test_normalizer_adapts_keyed_reproducibility_notes_losslessly():
    payload = {
        "source_ref": "paper.pdf", "code_availability": "missing",
        "data_availability": "controlled", "config_availability": "partial",
        "license_or_access_constraints": {
            "paper": {"status": "present", "license": "CC BY"},
        },
        "reproduction_steps": {
            "status": "reimplementation only", "steps": ["obtain data", "train"],
        },
        "missing_materials": [], "reproducibility_risk": "high",
    }
    normalized, report = normalize_payload("reproducibility_materials_audit", payload)
    assert not validate_payload("reproducibility_materials_audit", normalized)
    assert normalized["license_or_access_constraints"] == [
        'paper: {"license":"CC BY","status":"present"}'
    ]
    assert normalized["reproduction_steps"] == [
        "status: reimplementation only", 'steps: ["obtain data","train"]',
    ]
    assert sum(
        row["rule"] == "keyed-reproducibility-note-to-lossless-lines"
        for row in report["changes"]
    ) == 2


def test_normalizer_adapts_structured_reconciliation_receipt_and_global_repair():
    payload = {
        "source_ref": "paper.pdf",
        "comparison_performed": {"performed": True, "scope": "full chain"},
        "blind_bundle_ref": "blind.json",
        "primary_bundle_refs": ["a.json", "b.json", "c.json", "d.json"],
        "agreements": [], "disagreements": [],
        "repair_ledger": [{
            "repair_id": "R-010", "disagreement_id": None,
            "status": "accepted-limitation", "writer_repair": "show simulator boundary",
            "verification": "present in Markdown",
            "evidence_ref": "writer-evidence.md#R-010",
        }],
        "unresolved_repairs": [],
        "verdict": {"status": "PASS", "unresolved_count": 0},
    }
    normalized, report = normalize_payload("paper_reading_reconciliation", payload)
    assert not validate_payload("paper_reading_reconciliation", normalized)
    assert normalized["comparison_performed"] is True
    assert normalized["verdict"] == "PASS"
    repair = normalized["repair_ledger"][0]
    assert repair["disagreement_id"] == "GLOBAL-R-010"
    assert repair["issue"] == "show simulator boundary"
    assert repair["resolution_note"] == "show simulator boundary"
    assert {row["rule"] for row in report["changes"]} >= {
        "structured-comparison-receipt-to-boolean",
        "structured-reconciliation-verdict-to-status",
        "unlinked-writer-repair-to-global-id",
    }


def test_normalizer_never_invents_reconciliation_truth_or_evidence():
    payload = {
        "source_ref": "paper.pdf",
        "comparison_performed": {"performed": True},
        "blind_bundle_ref": "blind.json",
        "primary_bundle_refs": ["a.json", "b.json", "c.json", "d.json"],
        "agreements": [], "disagreements": [],
        "repair_ledger": [{
            "repair_id": "R-010", "disagreement_id": None,
            "status": "accepted-limitation", "writer_repair": "show boundary",
        }],
        "unresolved_repairs": [],
        "verdict": {"unresolved_count": 0},
    }

    normalized, report = normalize_payload("paper_reading_reconciliation", payload)

    assert normalized["verdict"] == '{"unresolved_count":0}'
    assert "evidence_ref" not in normalized["repair_ledger"][0]
    assert validate_payload("paper_reading_reconciliation", normalized)
    rules = {row["rule"] for row in report["changes"]}
    assert "structured-reconciliation-verdict-to-status" not in rules
    assert "linked-disagreement-evidence-reference" not in rules


def test_normalizer_never_invents_ambiguous_quality_rating():
    payload = {
        "source_ref": "paper.pdf", "verdict": "PASS_WITH_CAVEATS",
        "coverage": {"assessment": "reviewed"},
        "single_paper_completeness": "partial", "source_fidelity": "mixed",
        "visual_coverage": "partial", "evidence_saturation": "not-assessed-single-paper",
        "anchoring": "mixed", "method_depth": "mixed",
        "figure_table_coverage": "partial", "result_table_depth": "mixed",
        "algorithmic_depth": "mixed", "reproducibility_depth": "mixed",
        "project_alignment": "mixed", "domain_transfer_honesty": "mixed",
        "independent_critique_resolution": "resolved", "markdown_ready": True,
        "promotion_ready": False,
    }

    normalized, report = normalize_payload("paper_reading_quality", payload)

    assert normalized["coverage"] == '{"assessment":"reviewed"}'
    assert validate_payload("paper_reading_quality", normalized)
    assert not any(
        row["rule"] == "structured-quality-assessment-to-enum"
        and row["pointer"] == "/coverage"
        for row in report["changes"]
    )


def test_promotion_only_block_remains_a_delivery_caveat():
    payload = {
        "source_ref": "paper.pdf", "verdict": "BLOCK_FOR_PROMOTION",
        "coverage": "partial", "single_paper_completeness": "partial",
        "source_fidelity": "mixed", "visual_coverage": "partial",
        "evidence_saturation": "not-assessed-single-paper", "anchoring": "mixed",
        "method_depth": "mixed", "figure_table_coverage": "partial",
        "result_table_depth": "mixed", "algorithmic_depth": "mixed",
        "reproducibility_depth": "mixed", "project_alignment": "mixed",
        "domain_transfer_honesty": "mixed",
        "independent_critique_resolution": "resolved", "markdown_ready": True,
        "promotion_ready": False,
    }

    normalized, report = normalize_payload("paper_reading_quality", payload)

    assert normalized["verdict"] == "PASS_WITH_CAVEATS"
    assert normalized["promotion_ready"] is False
    assert not validate_payload("paper_reading_quality", normalized)
    assert "promotion-only-block-to-delivery-caveat" in {
        row["rule"] for row in report["changes"]
    }


def test_promotion_only_alias_never_overrides_conflicting_ready_flag():
    payload = {
        "source_ref": "paper.pdf", "verdict": "BLOCK_FOR_PROMOTION",
        "coverage": "partial", "single_paper_completeness": "partial",
        "source_fidelity": "mixed", "visual_coverage": "partial",
        "evidence_saturation": "not-assessed-single-paper", "anchoring": "mixed",
        "method_depth": "mixed", "figure_table_coverage": "partial",
        "result_table_depth": "mixed", "algorithmic_depth": "mixed",
        "reproducibility_depth": "mixed", "project_alignment": "mixed",
        "domain_transfer_honesty": "mixed",
        "independent_critique_resolution": "resolved", "markdown_ready": True,
        "promotion_ready": True,
    }

    normalized, report = normalize_payload("paper_reading_quality", payload)

    assert normalized["verdict"] == "BLOCK_FOR_PROMOTION"
    assert validate_payload("paper_reading_quality", normalized)
    assert "promotion-only-block-to-delivery-caveat" not in {
        row["rule"] for row in report["changes"]
    }


def test_normalizer_canonicalizes_qualified_claim_kinds():
    payload = {
        "source_scope": ["paper"],
        "claims": [
            {"claim_id": "c1", "text": "task", "source_ref": "paper", "kind": "task_definition", "confidence": "high"},
            {"claim_id": "c2", "text": "result", "source_ref": "paper", "kind": "ablation_result", "confidence": "medium"},
            {"claim_id": "c3", "text": "boundary", "source_ref": "paper", "kind": "evidence_boundary", "confidence": "high"},
        ],
    }
    normalized, report = normalize_payload("claim_list", payload)
    assert not validate_payload("claim_list", normalized)
    assert [row["kind"] for row in normalized["claims"]] == [
        "method", "comparison", "limitation",
    ]
    assert sum(
        row["rule"] == "qualified-claim-kind-to-enum"
        for row in report["changes"]
    ) == 3


def test_normalizer_adapts_qualified_math_audit_enums():
    payload = {
        "source_ref": "protocol.pdf",
        "applicability": "PARTIALLY_APPLICABLE_PROTOCOL_AUDIT: evaluator only",
        "formal_objects": ["AUC"], "equations_or_rules": ["trapezoid"],
        "implementation_assumptions": ["fixed steps"], "algorithm_flow": "sequential",
        "equation_consistency": "partial", "complexity_or_cost": None,
        "numerical_stability": "not reported", "edge_cases": ["empty mask"],
        "red_flags": ["DMM undefined"], "overall": "USABLE_WITH_CAVEATS: mixed definitions",
    }
    normalized, report = normalize_payload("math_algorithm_audit", payload)
    assert not validate_payload("math_algorithm_audit", normalized)
    assert normalized["applicability"] == "applicable"
    assert normalized["overall"] == "mixed"
    assert {row["rule"] for row in report["changes"]} >= {
        "qualified-applicability-to-enum", "qualified-math-verdict-to-enum"
    }


def test_normalizer_adapts_qualified_paper_relation_labels():
    payload = {
        "source_ref": "paper",
        "edges": [
            {"target_ref": "dataset", "relation": "uses_dataset", "note": "uses data"},
            {"target_ref": "prior", "relation": "extends_challenge_lineage", "note": "extends"},
        ],
    }
    normalized, report = normalize_payload("paper_relations", payload)
    assert not validate_payload("paper_relations", normalized)
    assert [row["relation"] for row in normalized["edges"]] == ["uses", "extends"]
    assert all(row["rule"] == "qualified-relation-to-enum" for row in report["changes"])


def test_normalizer_adapts_rich_domain_transfer_matrix():
    payload = {
        "source_ref": "paper", "target_context": {"project": "p"},
        "transfer_level": {"overall": "conditional_protocol_transfer_only"},
        "usable_for": [{"use": "protocol", "boundary": "only"}],
        "not_usable_for": ["clinical claim"],
        "required_local_validation": [{"priority": "P0", "validation": "local"}],
        "risk_of_overclaim": {"level": "high", "primary_risk": "oracle"},
        "transfer_matrix": [{
            "axis": "anatomy/task", "source": "lesion", "target": "canal",
            "transfer": "protocol_proxy_only", "reusable": "episode",
            "non_reusable": "effect", "local_validation": "target data",
        }],
    }
    normalized, report = normalize_payload("domain_transfer_note", payload)
    assert not validate_payload("domain_transfer_note", normalized)
    assert normalized["transfer_level"] == "indirect"
    assert normalized["risk_of_overclaim"] == "high"
    assert normalized["transfer_matrix"][0]["axis"] == "anatomy_or_task"
    assert normalized["transfer_matrix"][0]["match_level"] == "distant"
    assert {row["rule"] for row in report["changes"]} >= {
        "structured-transfer-level-to-enum", "structured-risk-to-level",
        "rich-transfer-rows-to-contract",
    }


def test_normalizer_maps_axis_aliases_on_already_typed_transfer_rows():
    payload = {
        "source_ref": "paper", "target_context": "project",
        "transfer_level": "indirect", "usable_for": ["metric"],
        "not_usable_for": ["safety"], "evidence_limits": ["single paper"],
        "required_local_validation": ["target data"], "risk_of_overclaim": "high",
        "transfer_matrix": [{
            "axis": "scanner_site", "source_setting": "MRI", "target_setting": "CBCT",
            "match_level": "distant", "implication": "validate spacing",
        }, {
            "axis": "supervision_prompting", "source_setting": "mask", "target_setting": "click",
            "match_level": "distant", "implication": "does not transfer mechanism",
        }],
    }
    normalized, report = normalize_payload("domain_transfer_note", payload)
    assert not validate_payload("domain_transfer_note", normalized)
    assert [row["axis"] for row in normalized["transfer_matrix"]] == [
        "scanner_or_site", "supervision_or_prompting"
    ]
    assert "canonical-transfer-axis" in {row["rule"] for row in report["changes"]}


def test_normalizer_links_rich_reconciliation_evidence_and_repairs():
    payload = {
        "source_ref": "paper", "comparison_performed": True,
        "blind_bundle_ref": "inbox/blind.json",
        "primary_bundle_refs": ["a", "b", "c", "d"],
        "agreements": [{"topic": "same", "finding": "agreed"}],
        "disagreements": [{
            "disagreement_id": "D1", "topic": "count mismatch",
            "primary_position": "1", "blind_position": "2", "resolution": "keep both",
            "source_evidence": [{"location": "p.1"}], "repair_required": True,
        }],
        "repair_ledger": [{
            "repair_id": "R1", "disagreement_id": "D1", "status": "accepted-limitation",
            "action": "show both counts",
        }],
        "unresolved_repairs": [], "verdict": "PASS_WITH_CAVEATS",
    }
    normalized, report = normalize_payload("paper_reading_reconciliation", payload)
    assert not validate_payload("paper_reading_reconciliation", normalized)
    assert normalized["repair_ledger"][0]["issue"] == "count mismatch"
    assert normalized["repair_ledger"][0]["resolution_note"] == "show both counts"
    assert "p.1" in normalized["disagreements"][0]["evidence_ref"]
    assert {row["rule"] for row in report["changes"]} >= {
        "source-evidence-to-reference-text", "repair-topic-to-issue",
        "linked-disagreement-evidence-reference", "repair-action-to-resolution-note",
    }


def test_normalizer_maps_human_first_markdown_section_aliases():
    payload = {
        "source_ref": "paper", "title": "Card", "markdown": "x" * 600,
        "evidence_refs": [], "covered_claim_ids": [], "covered_figure_refs": [],
        "covered_sections": [
            "decision_summary", "paper_problem_and_contribution", "data_and_design",
            "visual_audit_text_equivalent", "ev1_next_actions",
        ],
    }
    normalized, report = normalize_payload("paper_markdown_card", payload)
    assert not validate_payload("paper_markdown_card", normalized)
    assert normalized["covered_sections"] == [
        "decision-need", "claims-and-evidence", "figures-and-tables", "next-actions"
    ]
    assert any(row["rule"] == "semantic-section-aliases" for row in report["changes"])
