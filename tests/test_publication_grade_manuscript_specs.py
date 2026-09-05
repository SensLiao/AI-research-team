"""Publication-grade scientific-content contracts for manuscript workers.

These tests intentionally inspect the worker specifications rather than an operated
recipe.  The specs are the durable least-privilege and quality contract consumed by
the scheduler, so publication-critical duties must be explicit there and must not be
left to an author's taste or a prompt assembled at runtime.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "research_agent_teams" / "agents"


def _spec(name: str) -> str:
    return (AGENTS / name).read_text(encoding="utf-8").lower()


def _assert_terms(text: str, *terms: str) -> None:
    missing = [term for term in terms if term.lower() not in text]
    assert not missing, f"missing publication contract terms: {missing}"


def test_architect_gates_systematic_manuscripts_on_an_executed_workflow_manifest() -> None:
    text = _spec("manuscript-architect.md")
    _assert_terms(
        text,
        "workflow_execution_manifest",
        "search execution",
        "deduplication",
        "screening",
        "data extraction",
        "risk-of-bias",
        "planned workflow is not executed workflow",
    )


def test_evidence_admission_requires_verified_direct_identity_and_exact_locus() -> None:
    text = _spec("manuscript-evidence-steward.md")
    _assert_terms(
        text,
        "verified direct source identity",
        "primary-source snapshot",
        "exact locus",
        "secondary map",
        "cannot substitute",
    )


def test_synthesis_sections_answer_five_part_scientific_questions() -> None:
    for filename in (
        "manuscript-related-work-author.md",
        "manuscript-section-author.md",
    ):
        text = _spec(filename)
        _assert_terms(
            text,
            "synthesis_question",
            "consensus",
            "contradiction",
            "boundary",
            "implication",
        )


def test_introduction_uses_an_evidence_bounded_argument_chain() -> None:
    text = _spec("manuscript-introduction-author.md")
    _assert_terms(
        text,
        "problem_context",
        "evidence_gap",
        "research_question",
        "contribution_boundary",
        "answer preview",
    )


def test_methods_separates_protocol_from_executed_systematic_workflow() -> None:
    text = _spec("manuscript-methods-author.md")
    _assert_terms(
        text,
        "workflow_execution_manifest",
        "protocol",
        "executed",
        "screening decisions",
        "extraction records",
        "risk-of-bias",
    )


def test_results_reports_review_flow_and_synthesis_not_only_counts() -> None:
    text = _spec("manuscript-results-author.md")
    _assert_terms(
        text,
        "selection flow",
        "evidence synthesis matrix",
        "negative evidence",
        "heterogeneity",
        "workflow_execution_manifest",
    )


def test_claim_surface_has_one_owner_and_deduplicates_repeated_claims() -> None:
    for filename in (
        "manuscript-architect.md",
        "manuscript-integrator.md",
        "manuscript-synthesis-editor.md",
    ):
        text = _spec(filename)
        _assert_terms(
            text,
            "claim_surface_owner",
            "one canonical locus",
            "duplicate claim",
            "cross-reference",
        )


def test_integrator_builds_real_bibtex_and_sentence_adjacent_citations() -> None:
    text = _spec("manuscript-integrator.md")
    _assert_terms(
        text,
        "actual bibtex entry",
        "refs.bib",
        "citation_adjacency_ledger",
        "sentence-adjacent",
        "citation dump",
    )


def test_citation_review_reopens_bibtex_identity_and_adjacency() -> None:
    text = _spec("manuscript-citation-auditor.md")
    _assert_terms(
        text,
        "actual bibtex entry",
        "citation_adjacency_ledger",
        "sentence-adjacent",
        "duplicate identity",
        "exact locus",
    )


def test_asset_engineer_closes_asset_type_to_realized_bytes() -> None:
    text = _spec("manuscript-figure-table-engineer.md")
    _assert_terms(
        text,
        "asset_type",
        "generated_from_results",
        "external_source_excerpt",
        "conceptual_original",
        "table",
        "realization_status",
        "realized bytes",
        "exact page",
        "permission",
    )


def test_publication_visuals_use_reader_facing_names_not_repository_ids() -> None:
    text = _spec("manuscript-figure-table-engineer.md")
    _assert_terms(
        text,
        "reader-facing method name",
        "short paper title",
        "repository identifier",
        "provenance-only",
        "row_display_labels",
    )


def test_asset_review_reopens_type_specific_realization_evidence() -> None:
    text = _spec("manuscript-figure-table-reviewer.md")
    _assert_terms(
        text,
        "asset_type",
        "realization_status",
        "external_source_excerpt",
        "exact page",
        "realized bytes",
    )


def test_synthesis_editor_runs_content_convergence_without_self_review() -> None:
    text = _spec("manuscript-synthesis-editor.md")
    _assert_terms(
        text,
        "content convergence",
        "deterministic reconciliation",
        "six independent",
        "final manuscript hash",
        "zero open blocking",
        "zero open major",
        "fresh blind review",
    )
    _assert_terms(text, "vault writes", "direct network access", "submission")


def test_submission_gate_requires_all_six_fresh_review_seats() -> None:
    text = _spec("manuscript-synthesis-editor.md")
    _assert_terms(
        text,
        "six independent",
        "final manuscript hash",
        "zero open blocking",
        "zero open major",
        "content convergence",
    )


def test_each_review_seat_preserves_source_only_and_pdf_truth() -> None:
    review_specs = (
        "manuscript-domain-contribution-reviewer.md",
        "manuscript-methods-reproducibility-reviewer.md",
        "manuscript-figure-table-reviewer.md",
        "manuscript-factual-auditor.md",
        "manuscript-citation-auditor.md",
        "manuscript-style-latex-auditor.md",
    )
    for filename in review_specs:
        text = _spec(filename)
        _assert_terms(
            text,
            "source_only",
            "pdf_rendered",
            "not_assessed",
            "never fabricate a pdf",
        )
