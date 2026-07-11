"""Real tests for the lit-scout's deterministic core (evidence_scout)."""
from __future__ import annotations

from research_agent_teams.tools.evidence_scout import build_evidence_table, count_strong
from research_agent_teams.tools.validate_artifact import validate_against

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SOURCES_3 = [
    {
        "id": "vaswani2017attention",
        "kind": "paper",
        "ref": "arXiv:1706.03762",
        "title": "Attention Is All You Need",
        "year": 2017,
        "claim_support": "strong",
        "notes": "Foundational transformer architecture.",
    },
    {
        "id": "brown2020gpt3",
        "kind": "paper",
        "ref": "arXiv:2005.14165",
        "title": "Language Models are Few-Shot Learners",
        "year": 2020,
        "claim_support": "strong",
    },
    {
        "id": "huggingface-transformers",
        "kind": "repo",
        "ref": "https://github.com/huggingface/transformers",
        "claim_support": "moderate",
    },
]


# ---------------------------------------------------------------------------
# Test (a): 3 sources -> schema-valid payload with n_sources == 3
# ---------------------------------------------------------------------------

def test_three_sources_schema_valid_n_sources():
    payload = build_evidence_table(
        query="transformer architectures for NLP",
        sources=SOURCES_3,
    )
    assert payload["n_sources"] == 3
    errors = validate_against("evidence_table.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"


# ---------------------------------------------------------------------------
# Test (b): empty source list is schema-valid with n_sources == 0
# ---------------------------------------------------------------------------

def test_empty_sources_schema_valid():
    payload = build_evidence_table(
        query="zero-shot learning survey",
        sources=[],
    )
    assert payload["n_sources"] == 0
    assert payload["sources"] == []
    errors = validate_against("evidence_table.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"


# ---------------------------------------------------------------------------
# Test (c): saturation_reached passes through True and False
# ---------------------------------------------------------------------------

def test_saturation_reached_passthrough():
    for flag in (True, False):
        payload = build_evidence_table(
            query="continual learning benchmarks",
            sources=[],
            saturation_reached=flag,
        )
        assert payload["saturation_reached"] is flag


# ---------------------------------------------------------------------------
# Test (d): count_strong counts correctly
# ---------------------------------------------------------------------------

def test_count_strong_counts_correctly():
    # SOURCES_3 has 2 strong entries
    assert count_strong(SOURCES_3) == 2

    # No sources -> 0
    assert count_strong([]) == 0

    # All weak / moderate / none -> 0
    weak_sources = [
        {"id": "s1", "kind": "blog", "ref": "https://example.com/1", "claim_support": "weak"},
        {"id": "s2", "kind": "doc",  "ref": "https://example.com/2", "claim_support": "none"},
        {"id": "s3", "kind": "paper","ref": "arXiv:0000.00000",      "claim_support": "moderate"},
    ]
    assert count_strong(weak_sources) == 0

    # All strong -> full count
    strong_sources = [
        {"id": f"s{i}", "kind": "paper", "ref": f"doi:10.0/{i}", "claim_support": "strong"}
        for i in range(5)
    ]
    assert count_strong(strong_sources) == 5


# ---------------------------------------------------------------------------
# Test (e): sources are passed through unchanged (no mutation, no fabrication)
# ---------------------------------------------------------------------------

def test_sources_passed_through_unchanged():
    import copy
    original = copy.deepcopy(SOURCES_3)
    payload = build_evidence_table(
        query="attention mechanisms",
        sources=SOURCES_3,
    )
    # Source dicts in payload equal the originals
    assert payload["sources"] == original
    # No extra keys injected into source dicts
    for src_out, src_in in zip(payload["sources"], original):
        assert src_out == src_in
