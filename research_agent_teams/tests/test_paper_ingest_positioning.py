"""P3 tests for the Stage-0 positioning + Pass-1 contract extension of the literature-ingest core.

These cover the ADDITIVE / BACKWARD-COMPATIBLE contract: the new positioning + paper_contract facts are
conditional-add (present in the payload only when present in `facts`), the resulting payload validates
against paper_note.schema.json, and a call WITHOUT them produces a payload carrying NONE of the new keys
(the byte-identical-shape guarantee). Mirrors test_paper_ingest.py FULL_FACTS.
"""
from __future__ import annotations

from research_agent_teams.tools.paper_ingest import ingest_paper
from research_agent_teams.tools.validate_artifact import validate_payload

# The five Stage-0 positioning keys + the Pass-1 contract key, all OPTIONAL.
NEW_KEYS = {
    "paper_type",
    "read_purpose",
    "relation_to_thesis",
    "reading_objective",
    "reading_status",
    "paper_contract",
}

BASE_FACTS = {
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
    "datasets": ["WMT 2014 English-German"],
    "metrics": ["BLEU"],
}

POSITIONING_FACTS = {
    "paper_type": "method",
    "read_purpose": "method",
    "relation_to_thesis": "A-core",
    "reading_objective": "Establish whether pure attention can replace recurrence for the thesis encoder.",
    "reading_status": "deep-read",
    "paper_contract": {
        "category": "A sequence-transduction method paper.",
        "context": "Sits among RNN/CNN encoder-decoder MT models with attention bolted on.",
        "correctness_prior": "Strong: standard MT benchmarks, multiple seeds, ablations.",
        "contributions": [
            "Replaces recurrence/convolution entirely with self-attention.",
            "Introduces multi-head attention and positional encodings.",
        ],
        "clarity": "Clear; architecture and training fully specified.",
        "contract_sentence": (
            "Problem: sequential MT is slow -> Method: attention-only Transformer -> vs prior: "
            "drops recurrence -> Evidence: SOTA BLEU on WMT14 -> Applies when: parallelizable seq tasks."
        ),
    },
}


def test_positioning_facts_added_and_schema_valid():
    """(a) the payload contains every new positioning + contract key; (b) it validates via the registry."""
    facts = {**BASE_FACTS, **POSITIONING_FACTS}
    payload = ingest_paper(facts)

    # (a) present, carried through verbatim
    for key, value in POSITIONING_FACTS.items():
        assert key in payload, f"expected positioning key '{key}' in payload"
        assert payload[key] == value

    # (b) schema-valid through the registered validator
    errors = validate_payload("paper_note", payload)
    assert errors == [], f"Schema violations: {errors}"


def test_partial_positioning_only_adds_supplied_keys():
    """A skim that fills only positioning + a short contract adds exactly those keys, no unsupplied ones."""
    partial = {
        "paper_type": "review",
        "relation_to_thesis": "C-background",
        "reading_status": "skimmed",
        "paper_contract": {
            "category": "A survey of PEFT methods.",
            "context": "Background reading.",
            "contract_sentence": "Surveys parameter-efficient fine-tuning; used here as background.",
        },
    }
    payload = ingest_paper({**BASE_FACTS, **partial})

    assert payload["paper_type"] == "review"
    assert payload["relation_to_thesis"] == "C-background"
    assert payload["reading_status"] == "skimmed"
    assert payload["paper_contract"] == partial["paper_contract"]
    # the positioning keys NOT supplied are absent (conditional-add, never present-as-null)
    assert "read_purpose" not in payload
    assert "reading_objective" not in payload

    assert validate_payload("paper_note", payload) == []


def test_without_positioning_facts_no_new_keys():
    """(c) a call WITHOUT the new facts produces a payload with NONE of the new keys — byte-identical shape."""
    payload = ingest_paper(BASE_FACTS)

    assert NEW_KEYS.isdisjoint(payload), (
        f"unexpected positioning keys leaked into the default payload: {NEW_KEYS & set(payload)}"
    )
    # the exact legacy shape (matches test_paper_ingest.py's byte-identical guarantee)
    assert set(payload) == {
        "title", "source_ref", "year", "venue", "summary",
        "claims", "methods", "datasets", "metrics",
    }
    assert validate_payload("paper_note", payload) == []
