"""scholar_clients — offline tests with canned API bodies and injected transports (absorption wave 1)."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools.scholar_clients import (
    ScholarLookupError,
    _HTTPStatusError,
    get_references_s2,
    lookup_arxiv,
    lookup_doi_crossref,
    lookup_doi_openalex,
    normalize_arxiv_id,
    normalize_doi,
    search_arxiv,
    search_crossref,
    search_openalex,
    search_s2,
)

ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v2</id>
    <title>Skeleton Recall Loss for Tubular Structures</title>
    <published>2024-03-19T00:00:00Z</published>
    <author><name>A. Kirchhoff</name></author>
    <author><name>B. Maier</name></author>
  </entry>
</feed>"""

ARXIV_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""

OPENALEX_BODY = json.dumps({"results": [{
    "id": "https://openalex.org/W123",
    "display_name": "A Grand Survey of Things",
    "publication_year": 2025,
    "doi": "https://doi.org/10.1234/Survey.1",
    "cited_by_count": 42,
    "primary_location": {"source": {"display_name": "Journal of Things"}},
    "authorships": [{"author": {"display_name": "C. Writer"}}],
}]}).encode()

CROSSREF_LIST = json.dumps({"message": {"items": [{
    "DOI": "10.5555/xyz",
    "title": ["Cross Referenced Work"],
    "issued": {"date-parts": [[2023, 5]]},
    "container-title": ["Proc. of Stuff"],
    "author": [{"given": "D", "family": "Author"}],
    "is-referenced-by-count": 7,
    "URL": "https://doi.org/10.5555/xyz",
}]}}).encode()

CROSSREF_ONE = json.dumps({"message": {
    "DOI": "10.5555/xyz",
    "title": ["Cross Referenced Work"],
    "issued": {"date-parts": [[2023]]},
    "container-title": ["Proc. of Stuff"],
}}).encode()

S2_SEARCH = json.dumps({"data": [{
    "paperId": "abc123",
    "title": "Semantic Paper",
    "year": 2026,
    "venue": "S2 Venue",
    "authors": [{"name": "E. Person"}],
    "externalIds": {"DOI": "10.9999/s2paper", "ArXiv": "2501.00001"},
    "citationCount": 3,
    "url": "https://www.semanticscholar.org/paper/abc123",
}]}).encode()

S2_REFS = json.dumps({"data": [{"citedPaper": {
    "paperId": "ref1", "title": "An Upstream Work", "year": 2020,
    "externalIds": {}, "authors": [], "venue": "", "citationCount": 1, "url": ""}}]}).encode()


def fixed(body, capture=None):
    def transport(url, headers):
        if capture is not None:
            capture.append((url, headers))
        return body
    return transport


def test_arxiv_search_parses_normalized_record():
    recs = search_arxiv("skeleton recall", transport=fixed(ARXIV_ATOM))
    assert len(recs) == 1
    r = recs[0]
    assert r["source"] == "arxiv" and r["arxiv_id"] == "2403.12345"
    assert r["year"] == 2024 and r["doi"] == "10.48550/arxiv.2403.12345"
    assert r["authors"] == ["A. Kirchhoff", "B. Maier"]
    assert r["url"].endswith("/abs/2403.12345")


def test_openalex_search_normalizes_doi_and_venue():
    recs = search_openalex("survey", transport=fixed(OPENALEX_BODY))
    r = recs[0]
    assert r["doi"] == "10.1234/survey.1"          # lowercased, url prefix stripped
    assert r["venue"] == "Journal of Things" and r["cited_by_count"] == 42
    assert r["id"] == "W123"


def test_crossref_search_and_s2_search():
    r = search_crossref("stuff", transport=fixed(CROSSREF_LIST))[0]
    assert r["doi"] == "10.5555/xyz" and r["year"] == 2023 and r["authors"] == ["D Author"]
    s = search_s2("semantic", transport=fixed(S2_SEARCH))[0]
    assert s["arxiv_id"] == "2501.00001" and s["doi"] == "10.9999/s2paper" and s["cited_by_count"] == 3


def test_lookup_doi_404_means_none_other_errors_raise():
    def t404(url, headers):
        raise _HTTPStatusError(404, url)
    assert lookup_doi_crossref("10.5555/nope", transport=t404) is None

    def t500(url, headers):
        raise _HTTPStatusError(500, url)
    with pytest.raises(ScholarLookupError):
        lookup_doi_crossref("10.5555/boom", transport=t500)

    ok = lookup_doi_crossref("10.5555/xyz", transport=fixed(CROSSREF_ONE))
    assert ok is not None and ok["title"] == "Cross Referenced Work"


def test_lookup_arxiv_empty_feed_means_none():
    assert lookup_arxiv("2403.99999", transport=fixed(ARXIV_EMPTY)) is None
    rec = lookup_arxiv("arXiv:2403.12345v2", transport=fixed(ARXIV_ATOM))
    assert rec is not None and rec["arxiv_id"] == "2403.12345"


def test_invalid_ids_short_circuit_without_network():
    assert lookup_doi_crossref("not-a-doi") is None
    assert lookup_arxiv("not-an-id") is None


def test_polite_headers_and_s2_key(monkeypatch):
    monkeypatch.setenv("RAT_CONTACT_MAIL", "director@example.org")
    monkeypatch.setenv("RAT_S2_API_KEY", "k-123")
    seen = []
    search_s2("q", transport=fixed(S2_SEARCH, capture=seen))
    url, headers = seen[0]
    assert "mailto:director@example.org" in headers["User-Agent"]
    assert headers["x-api-key"] == "k-123"
    seen.clear()
    monkeypatch.delenv("RAT_S2_API_KEY")
    search_s2("q", transport=fixed(S2_SEARCH, capture=seen))
    assert "x-api-key" not in seen[0][1]


def test_get_references_s2_unwraps_cited_papers():
    refs = get_references_s2("abc123", transport=fixed(S2_REFS))
    assert len(refs) == 1 and refs[0]["title"] == "An Upstream Work" and refs[0]["source"] == "s2"


def test_malformed_body_becomes_lookup_error_not_a_crash():
    # Adversarial (reviewer MEDIUM): a provider returning junk must degrade that source, never crash.
    bad_xml = b"<not valid xml"
    bad_json = b"{not json"
    with pytest.raises(ScholarLookupError):
        search_arxiv("q", transport=fixed(bad_xml))
    with pytest.raises(ScholarLookupError):
        search_openalex("q", transport=fixed(bad_json))
    with pytest.raises(ScholarLookupError):
        search_crossref("q", transport=fixed(bad_json))
    with pytest.raises(ScholarLookupError):
        search_s2("q", transport=fixed(bad_json))


def test_lookup_doi_openalex_states():
    work = json.dumps({"id": "https://openalex.org/W5", "display_name": "X", "publication_year": 2024,
                       "primary_location": {"source": {"display_name": "Zenodo"}},
                       "authorships": []}).encode()
    assert lookup_doi_openalex("10.5281/zenodo.1", transport=fixed(work))["id"] == "W5"

    def t404(url, headers):
        raise _HTTPStatusError(404, url)
    assert lookup_doi_openalex("10.5281/zenodo.2", transport=t404) is None
    assert lookup_doi_openalex("not-a-doi") is None


def test_normalizers():
    assert normalize_doi("https://doi.org/10.1234/ABC.5") == "10.1234/abc.5"
    assert normalize_doi("garbage") is None
    assert normalize_arxiv_id("arXiv:2403.12345v3") == "2403.12345"
    assert normalize_arxiv_id("2403.12345") == "2403.12345"
    assert normalize_arxiv_id("v3") is None


def test_openalex_contact_stays_in_user_agent_and_out_of_url(monkeypatch):
    from urllib.parse import quote, urlsplit

    contact = "contact-sentinel@example.invalid"
    monkeypatch.delenv("RAT_OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)
    seen = []

    search_openalex("safe metadata", transport=fixed(OPENALEX_BODY, capture=seen))

    assert len(seen) == 1
    url, headers = seen[0]
    assert urlsplit(url).query == "search=safe+metadata&per-page=10"
    assert contact not in url
    assert quote(contact, safe="") not in url
    assert f"mailto:{contact}" in headers["User-Agent"]


def test_openalex_key_fails_closed_before_transport(monkeypatch):
    key = "openalex-key-sentinel"
    contact = "contact-sentinel@example.invalid"
    monkeypatch.setenv("RAT_OPENALEX_API_KEY", key)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)
    seen = []

    with pytest.raises(ScholarLookupError) as caught:
        search_openalex("safe metadata", transport=fixed(OPENALEX_BODY, capture=seen))

    detail = str(caught.value)
    assert seen == []
    assert "openalex" in detail.lower()
    assert "blocked before transport" in detail.lower()
    assert key not in detail
    assert contact not in detail


def test_scholar_errors_keep_safe_request_identity_but_strip_query_values(monkeypatch):
    key = "credential-sentinel"
    contact = "contact-sentinel@example.invalid"
    query_value = "private-query-sentinel"
    monkeypatch.setenv("RAT_OPENALEX_API_KEY", key)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)
    unsafe_url = (
        "https://api.crossref.org/works?"
        f"query={query_value}&api_key={key}&mailto={contact}"
    )

    http_detail = str(_HTTPStatusError(503, unsafe_url))
    network_detail = str(ScholarLookupError(
        f"network failure for {unsafe_url}: credential={key}; contact={contact}"
    ))

    for detail in (http_detail, network_detail):
        assert "crossref" in detail.lower()
        assert "api.crossref.org/works" in detail
        assert "?" not in detail
        assert query_value not in detail
        assert key not in detail
        assert contact not in detail
    assert "HTTP 503" in http_detail


def test_parse_failure_redacts_request_query(monkeypatch):
    query_value = "parse-query-sentinel"
    contact = "parse-contact@example.invalid"
    monkeypatch.delenv("RAT_OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("RAT_CONTACT_MAIL", contact)

    with pytest.raises(ScholarLookupError) as caught:
        search_crossref(query_value, transport=fixed(b"{not-json"))

    detail = str(caught.value)
    assert "crossref" in detail.lower()
    assert "api.crossref.org/works" in detail
    assert query_value not in detail
    assert contact not in detail
