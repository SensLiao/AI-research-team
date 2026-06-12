"""Real tests for the literature-ingest agent's deterministic core."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.paper_ingest import ingest_paper
from research_agent_teams.tools.validate_artifact import validate_against


def _make_vault_page(vault_root, folder, slug, *, title, body_extra=""):
    """Write a minimal frontmatter page into a FAKE vault's 02-wiki/papers/<folder>/<slug>.md."""
    d = vault_root / "02-wiki" / "papers" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(
        f"---\ntitle: \"{title}\"\ntype: paper\n{body_extra}---\n\n# {title}\n\nBody.\n",
        encoding="utf-8",
    )

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


# ---------- L7 vault dedup (read-only cross-check) ----------

def test_no_vault_root_is_byte_identical_to_legacy(tmp_path):
    """Without vault_root the payload is byte-identical to the pre-dedup behaviour: the two new keys
    are simply ABSENT (not present-as-null)."""
    payload = ingest_paper(FULL_FACTS)
    assert "vault_slug" not in payload
    assert "possible_duplicate" not in payload
    # the exact legacy shape
    assert set(payload) == {"title", "source_ref", "year", "venue", "summary",
                            "claims", "methods", "datasets", "metrics"}


def test_vault_title_match_flags_duplicate(tmp_path):
    """A page whose normalized title equals this paper's is flagged (punctuation/case differences ignored)."""
    _make_vault_page(tmp_path, "sam-foundation", "vaswani-2017-attention",
                     title="Attention Is All You Need")
    # incoming facts use different casing/punctuation but the same title
    facts = {**FULL_FACTS, "title": "ATTENTION is all you need!!!"}
    payload = ingest_paper(facts, vault_root=str(tmp_path))
    assert payload["vault_slug"] == "vaswani-2017-attention"
    assert payload["possible_duplicate"] is True
    assert validate_against("paper_note.schema.json", payload) == []


def test_vault_source_ref_match_flags_duplicate(tmp_path):
    """A title MISS but a source-ref hit (the arxiv id appears in the page) still flags the duplicate."""
    _make_vault_page(tmp_path, "sam-foundation", "vaswani-2017-attention",
                     title="A Totally Different Title",
                     body_extra="venue: 'NeurIPS 2017 (arxiv:1706.03762)'\n")
    facts = {**FULL_FACTS, "title": "Some Unrelated Incoming Title", "source_ref": "arxiv:1706.03762"}
    payload = ingest_paper(facts, vault_root=str(tmp_path))
    assert payload["vault_slug"] == "vaswani-2017-attention"
    assert payload["possible_duplicate"] is True


def test_vault_no_match_adds_no_keys(tmp_path):
    """A genuinely new paper against a populated vault adds NEITHER key (advisory absence, schema-valid)."""
    _make_vault_page(tmp_path, "peft-adapters", "hu-2021-lora",
                     title="LoRA: Low-Rank Adaptation of Large Language Models",
                     body_extra="venue: 'ICLR 2022 (arxiv:2106.09685)'\n")
    facts = {
        "title": "A Brand New Method Nobody Has Published",
        "source_ref": "arxiv:2599.99999",
        "summary": "Novel.",
        "claims": ["c1"],
    }
    payload = ingest_paper(facts, vault_root=str(tmp_path))
    assert "vault_slug" not in payload and "possible_duplicate" not in payload
    assert validate_against("paper_note.schema.json", payload) == []


def test_vault_root_without_papers_dir_is_safe_miss(tmp_path):
    """A vault_root with no 02-wiki/papers/ directory yields no match and does not crash."""
    (tmp_path / "00-system").mkdir(parents=True)   # a vault-ish root but no papers dir
    payload = ingest_paper(FULL_FACTS, vault_root=str(tmp_path))
    assert "vault_slug" not in payload


def test_weak_short_source_ref_does_not_false_match(tmp_path):
    """A source ref whose only number is a short, non-discriminating token must NOT match a page that
    merely happens to contain that number — source-ref matching requires a strong (long) identifier."""
    _make_vault_page(tmp_path, "misc", "some-paper",
                     title="Some Paper", body_extra="note: 'see table 1000 for details'\n")
    facts = {"title": "Unrelated Incoming", "source_ref": "doi:10.1000",  # idents: only '1000'
             "summary": "s", "claims": ["c"]}
    payload = ingest_paper(facts, vault_root=str(tmp_path))
    assert "vault_slug" not in payload          # weak ref did not loosely match


def test_vault_scan_first_match_is_deterministic(tmp_path):
    """Two pages share a normalized title; the sorted-first slug wins (deterministic, no flI/O order dep)."""
    _make_vault_page(tmp_path, "z-folder", "zzz-second", title="Shared Title")
    _make_vault_page(tmp_path, "a-folder", "aaa-first", title="Shared Title")
    facts = {**FULL_FACTS, "title": "Shared Title"}
    a = ingest_paper(facts, vault_root=str(tmp_path))
    b = ingest_paper(facts, vault_root=str(tmp_path))
    assert a["vault_slug"] == b["vault_slug"]                    # deterministic
    assert a["vault_slug"] in {"aaa-first", "zzz-second"}
