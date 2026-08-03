"""paper_search facade — merge/dedup, evidence rows, novelty signal, operate bundle (absorption wave 1)."""
from __future__ import annotations

import json
import urllib.parse

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.paper_search import (
    neighbor_overlap,
    no_semantic_neighbor_found,
    query_title_relevance,
    search,
    search_many,
    to_evidence_sources,
    write_search_bundle,
)
from research_agent_teams.tools.scholar_clients import ScholarLookupError
from research_agent_teams.tools.validate_artifact import validate_artifact

ARXIV_A = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v1</id>
    <title>Alpha Paper on Tubular Segmentation</title>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>A. One</name></author>
  </entry>
</feed>"""

OPENALEX_AB = json.dumps({"results": [
    {  # same work as the arXiv record (same DOI) -> must merge
        "id": "https://openalex.org/W1", "display_name": "Alpha Paper on Tubular Segmentation",
        "publication_year": 2024, "doi": "https://doi.org/10.48550/arXiv.2403.12345",
        "cited_by_count": 10, "primary_location": {"source": {"display_name": "arXiv"}},
        "authorships": [{"author": {"display_name": "A. One"}}],
    },
    {
        "id": "https://openalex.org/W2", "display_name": "Beta Work on Calibration",
        "publication_year": 2025, "doi": "https://doi.org/10.1000/beta.7",
        "cited_by_count": 99, "primary_location": {"source": {"display_name": "Conf B"}},
        "authorships": [],
    },
]}).encode()

S2_C = json.dumps({"data": [{
    "paperId": "ccc", "title": "Gamma Delta Epsilon", "year": 2022, "venue": "",
    "authors": [], "externalIds": {}, "citationCount": 1, "url": "https://s2/ccc"}]}).encode()


def routing_transport(url, headers):
    if "export.arxiv.org" in url:
        return ARXIV_A
    if "api.openalex.org" in url:
        return OPENALEX_AB
    if "api.crossref.org" in url:
        raise ScholarLookupError("network failure for crossref: simulated outage")
    if "semanticscholar.org" in url:
        return S2_C
    raise AssertionError(f"unexpected url {url}")


def test_search_merges_dedups_and_reports_source_errors():
    res = search("tubular segmentation", transport=routing_transport)
    recs = res["records"]
    assert len(recs) == 3                                  # A merged across arxiv+openalex, B, C
    by_title = {r["title"]: r for r in recs}
    alpha = by_title["Alpha Paper on Tubular Segmentation"]
    assert sorted(alpha["found_in"]) == ["arxiv", "openalex"]
    assert alpha["cited_by_count"] == 10                   # filled from the richer source
    assert recs[0]["title"] == "Beta Work on Calibration"  # ordered by cited_by_count desc
    assert "crossref" in res["source_errors"]
    assert "simulated outage" in res["source_errors"]["crossref"]


def test_search_rejects_empty_query_and_unknown_source():
    with pytest.raises(ValueError):
        search("   ", transport=routing_transport)
    with pytest.raises(ValueError):
        search("q", sources=("arxiv", "scihub"), transport=routing_transport)


def test_evidence_rows_pass_the_real_evidence_table_schema():
    res = search("tubular segmentation", transport=routing_transport)
    rows = to_evidence_sources(res["records"])
    assert all(set(r) <= {"id", "kind", "ref", "title", "year", "claim_support", "notes"} for r in rows)
    assert all(r["claim_support"] == "none" for r in rows)           # grading is the worker's job
    assert any(r["ref"].startswith("doi:") for r in rows)
    art = envelope("evidence_table",
                   "lit-scout",
                   {"query": "tubular segmentation", "sources": rows,
                    "saturation_reached": False, "n_sources": len(rows)},
                   "2026-06-10T12:00:00Z")
    assert validate_artifact(art) == []


def test_novelty_signal_no_neighbor_vs_neighbor():
    far = [{"title": "Completely Unrelated Botany Catalogue"}]
    near = [{"title": "Skeleton recall loss for thin tubular structure segmentation"}]
    q = "skeleton recall loss tubular segmentation"
    sig_far = no_semantic_neighbor_found(q, far)
    sig_near = no_semantic_neighbor_found(q, near)
    assert sig_far["no_semantic_neighbor_found"] is True
    assert sig_near["no_semantic_neighbor_found"] is False
    assert sig_near["best_overlap"] > sig_far["best_overlap"]
    empty = no_semantic_neighbor_found(q, [])
    assert empty["no_semantic_neighbor_found"] is True and empty["n_results"] == 0


def test_neighbor_overlap_bounds():
    assert 0.0 <= neighbor_overlap("a b c", "totally different words") <= 1.0
    assert neighbor_overlap("same exact title", "same exact title") == 1.0


def test_write_search_bundle(tmp_path):
    res = search("tubular segmentation", transport=routing_transport)
    p = write_search_bundle(tmp_path / "run-1", "tubular segmentation", res, "2026-06-10T12:00:00Z")
    data = json.loads((tmp_path / "run-1" / "inbox" / "search-results.json").read_text(encoding="utf-8"))
    assert p.endswith("search-results.json")
    assert data["query"] == "tubular segmentation"
    assert len(data["evidence_rows"]) == 3 and data["retrieved_at"] == "2026-06-10T12:00:00Z"
    assert "crossref" in data["source_errors"]


def test_multilingual_query_plan_is_utf8_and_filters_off_topic_crossref_noise():
    query = "医学图像 涂鸦 交互分割"
    body = json.dumps({"message": {"items": [
        {"title": ["医学图像涂鸦交互分割方法"], "DOI": "10.1000/relevant",
         "issued": {"date-parts": [[2025]]}, "container-title": ["Medical Imaging"]},
        {"title": ["科学家故事融入初中科学教育的模式构建和实践验证"],
         "DOI": "10.1000/noise", "issued": {"date-parts": [[2025]]},
         "container-title": ["Education"]},
    ]}}, ensure_ascii=False).encode("utf-8")
    seen = []

    def transport(url, headers):
        seen.append(url)
        return body

    result = search_many([query], sources=("crossref",), transport=transport)
    decoded_query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0]).query)["query"][0]
    assert decoded_query == query
    assert result["queries"] == [query]
    assert [record["doi"] for record in result["records"]] == ["10.1000/relevant"]
    assert result["relevance_filter"]["n_candidates"] == 2
    assert result["relevance_filter"]["n_accepted"] == 1
    assert result["relevance_filter"]["n_rejected"] == 1
    assert query_title_relevance(query, "医学图像涂鸦交互分割方法") > 0
    assert query_title_relevance(query, "教学模式构建与验证") == 0


def test_query_filter_rejects_generic_budget_match_and_supplement_components():
    query = "interactive segmentation baseline fairness prompt budget same initial mask"
    body = json.dumps({"message": {"items": [
        {"title": ["Deep Interactive Segmentation of Medical Images"],
         "DOI": "10.1000/interactive", "issued": {"date-parts": [[2024]]}},
        {"title": ["When to Repair a Graph Index: A Matched-Budget Baseline"],
         "DOI": "10.1000/graph", "issued": {"date-parts": [[2025]]}},
        {"title": ["Interactive Segmentation with Prompt Masks_supp1-123.mp4"],
         "DOI": "10.1000/interactive/mm1", "issued": {"date-parts": [[2024]]}},
    ]}}).encode("utf-8")

    result = search_many([query], sources=("crossref",), transport=lambda *_: body)

    assert [record["doi"] for record in result["records"]] == ["10.1000/interactive"]
    assert result["relevance_filter"] == {
        "kind": "multilingual_query_title_lexical/v1",
        "min_score": 0.5,
        "n_candidates": 3,
        "n_accepted": 1,
        "n_rejected": 2,
        "n_merged_duplicates": 0,
    }


def test_vault_path_is_refused_by_both_write_paths(tmp_path):
    # Adversarial (reviewer HIGH): neither the operate bundle nor the CLI --json may write the vault.
    res = {"query": "q", "records": [], "source_errors": {}}
    vault_run = tmp_path / "AI agent database" / "PhD-Research-OS" / "runs" / "r1"
    with pytest.raises(ValueError):
        write_search_bundle(vault_run, "q", res, "2026-06-10T12:00:00Z")
    from research_agent_teams.tools.paper_search import _reject_vault_path
    with pytest.raises(ValueError):
        _reject_vault_path(tmp_path / "phd-research-os" / "02-wiki" / "leak.json")
    # a normal runs/ path is fine
    write_search_bundle(tmp_path / "runs" / "ok", "q", res, "2026-06-10T12:00:00Z")


def test_openalex_key_failure_does_not_suppress_other_provider_results(monkeypatch):
    key = "openalex-key-sentinel"
    contact = "contact-sentinel@example.invalid"
    monkeypatch.setenv("RAT_OPENALEX_API_KEY", key)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)
    crossref_body = json.dumps({"message": {"items": [{
        "DOI": "10.5555/safe",
        "title": ["Safe Crossref Metadata"],
        "issued": {"date-parts": [[2026]]},
    }]}}).encode()
    seen = []

    def transport(url, _headers):
        seen.append(url)
        if "crossref.org" in url:
            return crossref_body
        if "openalex.org" in url:
            return OPENALEX_AB
        raise AssertionError(f"unexpected URL {url}")

    result = search(
        "safe metadata",
        sources=("openalex", "crossref"),
        transport=transport,
    )

    assert all("openalex.org" not in url for url in seen)
    assert [record["doi"] for record in result["records"]] == ["10.5555/safe"]
    assert set(result["source_errors"]) == {"openalex"}
    detail = result["source_errors"]["openalex"]
    assert "blocked before transport" in detail.lower()
    assert key not in detail
    assert contact not in detail


def test_source_errors_are_redacted_when_collected_and_persisted(monkeypatch, tmp_path):
    key = "credential-sentinel"
    contact = "contact-sentinel@example.invalid"
    query_value = "private-query-sentinel"
    monkeypatch.setenv("RAT_OPENALEX_API_KEY", key)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)
    unsafe_detail = (
        "network failure for https://api.crossref.org/works?"
        f"query={query_value}&api_key={key}&mailto={contact}: token={key}"
    )

    def failing_transport(_url, _headers):
        raise ScholarLookupError(unsafe_detail)

    result = search("safe metadata", sources=("crossref",), transport=failing_transport)
    collected = result["source_errors"]["crossref"]
    assert "crossref" in collected.lower()
    assert "api.crossref.org/works" in collected
    assert "?" not in collected
    assert query_value not in collected
    assert key not in collected
    assert contact not in collected

    result["source_errors"]["crossref"] = unsafe_detail
    output = write_search_bundle(
        tmp_path / "run-redaction",
        "safe metadata",
        result,
        "2026-07-21T00:00:00Z",
    )
    persisted = json.loads(open(output, encoding="utf-8").read())
    persisted_detail = persisted["source_errors"]["crossref"]
    assert "api.crossref.org/works" in persisted_detail
    assert "?" not in persisted_detail
    assert query_value not in persisted_detail
    assert key not in persisted_detail
    assert contact not in persisted_detail


def test_openalex_results_remain_metadata_only(monkeypatch):
    monkeypatch.delenv("RAT_OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("RAT_CONTACT_MAIL", raising=False)
    result = search(
        "metadata only",
        sources=("openalex",),
        transport=lambda _url, _headers: OPENALEX_AB,
    )

    forbidden_acquisition_fields = {
        "content", "full_text", "pdf", "pdf_path", "pdf_url", "download",
    }
    assert result["records"]
    assert all(forbidden_acquisition_fields.isdisjoint(record) for record in result["records"])
    assert all(
        row["claim_support"] == "none"
        for row in to_evidence_sources(result["records"])
    )
