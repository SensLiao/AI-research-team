"""citation_existence — three-state checker, cache semantics, offline-safe verdict (absorption wave 1)."""
from __future__ import annotations

import hashlib
import json

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.citation_existence import (
    STATE_LOOKUP_ERROR,
    STATE_NOT_FOUND,
    STATE_SKIPPED,
    STATE_VERIFIED,
    ExistenceCache,
    build_existence_verdict,
    check_reference,
    classify_ref,
)
from research_agent_teams.tools.scholar_clients import ScholarLookupError, _HTTPStatusError
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"

CROSSREF_ONE = json.dumps({"message": {
    "DOI": "10.5555/xyz", "title": ["Cross Referenced Work"],
    "issued": {"date-parts": [[2023]]}, "container-title": ["Proc."],
}}).encode()

ARXIV_ONE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v1</id>
    <title>Real Arxiv Paper</title>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
</feed>"""

ARXIV_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""

S2_MATCH = json.dumps({"data": [{
    "paperId": "p1", "title": "A Very Specific Paper Title", "year": 2024, "venue": "",
    "authors": [], "externalIds": {}, "citationCount": 0, "url": ""}]}).encode()

S2_JUNK = json.dumps({"data": [{
    "paperId": "p2", "title": "Entirely Different Thing", "year": 2021, "venue": "",
    "authors": [], "externalIds": {}, "citationCount": 0, "url": ""}]}).encode()


def test_classify_ref_forms():
    assert classify_ref("10.1234/AbC") == {"kind": "doi", "value": "10.1234/abc"}
    assert classify_ref("doi:10.1000/X") == {"kind": "doi", "value": "10.1000/x"}
    assert classify_ref("doi:10.48550/arXiv.2304.05542") == {
        "kind": "arxiv", "value": "2304.05542"
    }
    assert classify_ref("arXiv:2403.12345v2") == {"kind": "arxiv", "value": "2403.12345"}
    assert classify_ref("2403.12345") == {"kind": "arxiv", "value": "2403.12345"}
    assert classify_ref("[[kirchhoff-2024-skeleton-recall]]")["kind"] == "slug"
    assert classify_ref("https://example.org/x")["kind"] == "url"
    assert classify_ref("Attention Is All You Need")["kind"] == "title"


def test_slug_and_url_are_skipped_without_network():
    def boom(url, headers):
        raise AssertionError("no network call expected")
    s = check_reference("[[some-page]]", TS, transport=boom)
    u = check_reference("https://example.org/page", TS, transport=boom)
    assert s["state"] == STATE_SKIPPED and u["state"] == STATE_SKIPPED


def test_hash_bound_local_files_verify_inside_run_or_workspace_without_network(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / "research_agent_teams" / "runs" / "p" / "run-1"
    run_file = run_dir / "inbox" / "source.json"
    workspace_file = workspace / "research_agent_teams" / "evidence" / "ledger.json"
    run_file.parent.mkdir(parents=True)
    workspace_file.parent.mkdir(parents=True)
    run_file.write_bytes(b"run evidence")
    workspace_file.write_bytes(b"workspace evidence")

    refs = [
        "inbox/source.json+sha:" + hashlib.sha256(run_file.read_bytes()).hexdigest(),
        "research_agent_teams/evidence/ledger.json+sha:"
        + hashlib.sha256(workspace_file.read_bytes()).hexdigest(),
    ]

    def boom(url, headers):
        raise AssertionError("local refs must never be sent to scholarly APIs")

    verdict = build_existence_verdict(
        refs, TS, transport=boom, local_roots=(run_dir, workspace)
    )
    assert verdict["verdict"] == "PASS"
    assert verdict["n_verified"] == 2
    assert all("local hash-bound file verified" in row["detail"]
               for row in verdict["checked"])
    assert validate_artifact(
        envelope("citation_existence_verdict", "citation-existence-checker", verdict, TS)
    ) == []


def test_hash_bound_local_missing_file_blocks_without_network(tmp_path):
    run_dir = tmp_path / "workspace" / "run"
    run_dir.mkdir(parents=True)

    def boom(url, headers):
        raise AssertionError("local refs must never be sent to scholarly APIs")

    verdict = build_existence_verdict(
        ["inbox/missing.json+sha:" + "a" * 64],
        TS,
        transport=boom,
        local_roots=(run_dir, tmp_path / "workspace"),
    )
    assert verdict["verdict"] == "BLOCK"
    assert verdict["n_not_found"] == 1
    assert "local evidence file does not exist" in verdict["violations"][0]


def test_run_relative_local_ref_cannot_escape_into_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / "runs" / "run-1"
    outside_run = workspace / "runs" / "outside.json"
    run_dir.mkdir(parents=True)
    outside_run.write_bytes(b"outside run")
    ref = (
        "inbox/../../outside.json+sha:"
        + hashlib.sha256(outside_run.read_bytes()).hexdigest()
    )

    def boom(url, headers):
        raise AssertionError("local refs must never be sent to scholarly APIs")

    verdict = build_existence_verdict(
        [ref], TS, transport=boom, local_roots=(run_dir, workspace)
    )
    assert verdict["verdict"] == "BLOCK"
    assert "escapes the authorized" in verdict["violations"][0]


def test_hash_bound_local_hash_mismatch_blocks_and_is_not_cached(tmp_path):
    run_dir = tmp_path / "run"
    source = run_dir / "inbox" / "source.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"actual bytes")
    cache = ExistenceCache()
    ref = "inbox/source.json+sha:" + "0" * 64

    def boom(url, headers):
        raise AssertionError("local refs must never be sent to scholarly APIs")

    first = build_existence_verdict(
        [ref], TS, transport=boom, cache=cache, local_roots=(run_dir,)
    )
    assert first["verdict"] == "BLOCK"
    assert "local evidence hash mismatch" in first["violations"][0]

    source.write_bytes(b"")
    empty_digest_ref = "inbox/source.json+sha:" + hashlib.sha256(b"").hexdigest()
    second = build_existence_verdict(
        [empty_digest_ref], TS, transport=boom, cache=cache, local_roots=(run_dir,)
    )
    assert second["verdict"] == "PASS"
    assert not second["checked"][0]["detail"].startswith("(cached")
    cache.close()


def test_external_doi_still_uses_scholarly_lookup_when_local_roots_supplied(tmp_path):
    calls = []

    def transport(url, headers):
        calls.append(url)
        return CROSSREF_ONE

    result = check_reference(
        "10.5555/xyz", TS, transport=transport, local_roots=(tmp_path,)
    )
    assert result["state"] == STATE_VERIFIED
    assert result["kind"] == "doi"
    assert calls and "api.crossref.org" in calls[0]


def test_doi_verified_not_found_and_lookup_error():
    ok = check_reference("10.5555/xyz", TS, transport=lambda u, h: CROSSREF_ONE)
    assert ok["state"] == STATE_VERIFIED and "Cross Referenced Work" in ok["detail"]

    def t404(url, headers):
        raise _HTTPStatusError(404, url)
    missing = check_reference("10.5555/nope", TS, transport=t404)
    assert missing["state"] == STATE_NOT_FOUND

    def tdown(url, headers):
        raise ScholarLookupError("network down")
    down = check_reference("10.5555/xyz", TS, transport=tdown)
    assert down["state"] == STATE_LOOKUP_ERROR


def test_doi_falls_back_to_openalex_for_datacite_dois():
    # Crossref 404s a Zenodo/DataCite DOI; OpenAlex resolves it -> verified (not a false not_found).
    OPENALEX_WORK = json.dumps({"id": "https://openalex.org/W9", "display_name": "Zenodo Dataset",
                                "publication_year": 2025,
                                "primary_location": {"source": {"display_name": "Zenodo"}},
                                "authorships": []}).encode()

    def router(url, headers):
        if "api.crossref.org" in url:
            raise _HTTPStatusError(404, url)
        if "api.openalex.org" in url:
            return OPENALEX_WORK
        raise AssertionError(url)

    res = check_reference("10.5281/zenodo.123456", TS, transport=router)
    assert res["state"] == STATE_VERIFIED and "OpenAlex" in res["detail"]


def test_doi_not_found_only_when_both_crossref_and_openalex_answer_absent():
    def router(url, headers):
        if "api.crossref.org" in url:
            raise _HTTPStatusError(404, url)
        if "api.openalex.org" in url:
            raise _HTTPStatusError(404, url)
        raise AssertionError(url)
    assert check_reference("10.9999/ghost", TS, transport=router)["state"] == STATE_NOT_FOUND


def test_doi_openalex_outage_after_crossref_404_is_lookup_error_not_block():
    def router(url, headers):
        if "api.crossref.org" in url:
            raise _HTTPStatusError(404, url)
        if "api.openalex.org" in url:
            raise ScholarLookupError("openalex down")
        raise AssertionError(url)
    # Crossref says 'not in Crossref' but OpenAlex can't confirm absence -> lookup_error, never BLOCK
    assert check_reference("10.5281/zenodo.7", TS, transport=router)["state"] == STATE_LOOKUP_ERROR


def test_arxiv_states():
    assert check_reference("arXiv:2403.12345", TS,
                           transport=lambda u, h: ARXIV_ONE)["state"] == STATE_VERIFIED
    assert check_reference("arXiv:2403.99999", TS,
                           transport=lambda u, h: ARXIV_EMPTY)["state"] == STATE_NOT_FOUND


def test_title_match_verified_junk_not_found_outage_lookup_error():
    ok = check_reference("A Very Specific Paper Title", TS, transport=lambda u, h: S2_MATCH)
    assert ok["state"] == STATE_VERIFIED and "title match" in ok["detail"]

    junk = check_reference("A Very Specific Paper Title", TS, transport=lambda u, h: S2_JUNK)
    assert junk["state"] == STATE_NOT_FOUND

    def tdown(url, headers):
        raise ScholarLookupError("offline")
    down = check_reference("A Very Specific Paper Title", TS, transport=tdown)
    assert down["state"] == STATE_LOOKUP_ERROR    # absence NOT confirmed when no source answered


def test_title_partial_outage_is_lookup_error_not_false_not_found():
    # Adversarial (reviewer HIGH): S2 errors, OpenAlex answers with no match. The title may exist
    # only in S2's index -> absence is unconfirmable -> lookup_error, never a confirmed not_found.
    def router(url, headers):
        if "semanticscholar.org" in url:
            raise ScholarLookupError("s2 jitter")
        if "api.openalex.org" in url:
            return json.dumps({"results": []}).encode()        # OpenAlex answered: no match
        raise AssertionError(url)
    res = check_reference("A Title Maybe Only In S2", TS, transport=router)
    assert res["state"] == STATE_LOOKUP_ERROR                  # NOT not_found -> would have false-BLOCKED
    v = build_existence_verdict(["A Title Maybe Only In S2"], TS, transport=router)
    # C2 (2026-08-07): zero confirmed verifications + a lookup error present -> UNVERIFIED, not a
    # false PASS. The single reference here can neither be confirmed nor confirmed-absent.
    assert v["verdict"] == "UNVERIFIED" and v["warnings"]


def test_cache_hits_and_never_caches_lookup_error(tmp_path):
    calls = []

    def counting(url, headers):
        calls.append(url)
        return CROSSREF_ONE

    db = str(tmp_path / "cite-cache.sqlite")
    cache = ExistenceCache(db)
    first = check_reference("10.5555/xyz", TS, transport=counting, cache=cache)
    assert first["state"] == STATE_VERIFIED and len(calls) == 1
    second = check_reference("10.5555/xyz", TS, transport=counting, cache=cache)
    assert second["state"] == STATE_VERIFIED and len(calls) == 1      # served from cache
    assert second["detail"].startswith("(cached")
    cache.close()

    cache2 = ExistenceCache(db)                                        # persists across instances
    third = check_reference("10.5555/xyz", TS, transport=counting, cache=cache2)
    assert third["state"] == STATE_VERIFIED and len(calls) == 1
    cache2.close()

    flaky_cache = ExistenceCache()                                     # in-memory
    def tdown(url, headers):
        raise ScholarLookupError("temporarily down")
    err = check_reference("10.5555/abc", TS, transport=tdown, cache=flaky_cache)
    assert err["state"] == STATE_LOOKUP_ERROR
    later = check_reference("10.5555/abc", TS, transport=counting, cache=flaky_cache)
    assert later["state"] == STATE_VERIFIED                            # error was NOT pinned


def test_verdict_blocks_only_on_confirmed_not_found():
    def router(url, headers):
        if "nope" in url:
            raise _HTTPStatusError(404, url)
        if "down" in url:
            raise ScholarLookupError("offline")
        return CROSSREF_ONE

    refs = ["10.5555/xyz", "10.5555/nope", "10.5555/down", "[[vault-page]]"]
    v = build_existence_verdict(refs, TS, transport=router)
    assert (v["n_verified"], v["n_not_found"], v["n_lookup_error"], v["n_skipped"]) == (1, 1, 1, 1)
    assert v["verdict"] == "BLOCK" and len(v["violations"]) == 1 and len(v["warnings"]) == 1

    offline_only = build_existence_verdict(["10.5555/down"], TS, transport=router)
    # C2 (2026-08-07): all-offline (zero verified, zero not_found, all lookup_error) is UNVERIFIED,
    # not a false PASS — nothing here was actually confirmed, only unreachable.
    assert offline_only["verdict"] == "UNVERIFIED"                     # offline never false-BLOCKs
    assert offline_only["warnings"] and not offline_only["violations"]


def test_verdict_artifact_passes_schema_and_tamper_fails():
    v = build_existence_verdict(["10.5555/xyz"], TS, transport=lambda u, h: CROSSREF_ONE)
    art = envelope("citation_existence_verdict", "citation-existence-checker", v, TS)
    assert validate_artifact(art) == []

    tampered = dict(v, verdict="PASS", n_not_found=2)                   # allOf consistency guard
    bad = envelope("citation_existence_verdict", "citation-existence-checker", tampered, TS)
    assert validate_artifact(bad) != []
