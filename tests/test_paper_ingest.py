"""Real tests for the literature-ingest agent's deterministic core."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.paper_ingest import ingest_paper
from research_agent_teams.tools.validate_artifact import validate_against

FULL_FACTS = {
    "title": "Attention Is All You Need",
    "source_ref": "arxiv:1706.03762",
    "year": 2017,
    "venue": "NeurIPS",
    "summary": "Introduces the Transformer architecture based solely on attention mechanisms.",
    "claims": [
        "Self-attention outperforms recurrent models on MT benchmarks.",
        "Multi-head attention enables parallel computation over sequence positions.",
    ],
    "methods": ["multi-head self-attention", "positional encoding"],
    "datasets": ["WMT 2014 English-German", "WMT 2014 English-French"],
    "metrics": ["BLEU"],
}


def test_full_facts_produce_schema_valid_payload():
    """Full facts dict → schema-valid paper_note via validate_against."""
    payload = ingest_paper(FULL_FACTS)
    errors = validate_against("paper_note.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"


def test_missing_summary_raises_value_error():
    """Missing summary must raise ValueError before any schema work."""
    facts = {k: v for k, v in FULL_FACTS.items() if k != "summary"}
    with pytest.raises(ValueError, match="summary"):
        ingest_paper(facts)


def test_defaults_applied_when_optional_fields_omitted():
    """Optional fields (methods/datasets/metrics/year/venue) default to [] / None and remain schema-valid."""
    minimal_facts = {
        "title": "A Minimal Paper",
        "source_ref": "arxiv:0000.00000",
        "summary": "A paper with no optional metadata provided.",
        "claims": ["Some atomic claim."],
    }
    payload = ingest_paper(minimal_facts)

    assert payload["methods"] == []
    assert payload["datasets"] == []
    assert payload["metrics"] == []
    assert payload["year"] is None
    assert payload["venue"] is None

    errors = validate_against("paper_note.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"


def test_claims_passed_through_unchanged():
    """Claims list is carried through to the payload without modification."""
    expected_claims = [
        "Claim alpha: model achieves SOTA on benchmark X.",
        "Claim beta: training converges in fewer steps than baseline.",
        "Claim gamma: the method generalises to three additional datasets.",
    ]
    facts = {
        "title": "Claims Test Paper",
        "source_ref": "arxiv:1234.56789",
        "summary": "Testing that claims pass through.",
        "claims": expected_claims,
    }
    payload = ingest_paper(facts)
    assert payload["claims"] == expected_claims


def test_missing_title_raises_value_error():
    """Missing title must raise ValueError."""
    facts = {k: v for k, v in FULL_FACTS.items() if k != "title"}
    with pytest.raises(ValueError, match="title"):
        ingest_paper(facts)


def test_missing_claims_raises_value_error():
    """Missing claims key must raise ValueError."""
    facts = {k: v for k, v in FULL_FACTS.items() if k != "claims"}
    with pytest.raises(ValueError, match="claims"):
        ingest_paper(facts)


def test_empty_string_source_ref_raises_value_error():
    """Empty string for source_ref must raise ValueError (fail-fast boundary check)."""
    facts = {**FULL_FACTS, "source_ref": "   "}
    with pytest.raises(ValueError, match="source_ref"):
        ingest_paper(facts)
