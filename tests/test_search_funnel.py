"""search_funnel — the AgentSearch-pattern four-stage funnel + recursive related-query search.

Offline by construction: every provider answer is canned bytes through the injectable transport.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from research_agent_teams.tools import search_funnel as sf
from research_agent_teams.tools.evidence_search_trace import evaluate_search_trace
from research_agent_teams.tools.paper_search import search, to_evidence_sources
from research_agent_teams.tools.scholar_clients import ScholarLookupError
from research_agent_teams.tools.validate_artifact import validate_against

QUERY = "skeleton recall loss tubular segmentation"

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v1</id>
    <title>Skeleton Recall Loss for Tubular Segmentation</title>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>A. One</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <title>Tubular Segmentation with Topology-Aware Recall</title>
    <published>2024-02-01T00:00:00Z</published>
    <author><name>D. Four</name></author>
  </entry>
</feed>"""

OPENALEX_SEARCH = json.dumps({"results": [
    {   # same work as the first arXiv record (same DOI) -> two channels agree
        "id": "https://openalex.org/W1", "display_name": "Skeleton Recall Loss for Tubular Segmentation",
        "publication_year": 2024, "doi": "https://doi.org/10.48550/arXiv.2403.12345",
        "cited_by_count": 10, "primary_location": {"source": {"display_name": "arXiv"}},
        "authorships": [{"author": {"display_name": "A. One"}}],
    },
    {
        "id": "https://openalex.org/W2", "display_name": "Centerline Recall Loss for Vessel Segmentation",
        "publication_year": 2025, "doi": "https://doi.org/10.1000/beta.7",
        "cited_by_count": 990, "primary_location": {"source": {"display_name": "Conf B"}},
        "authorships": [],
    },
    {   # off-topic API noise -> the title-relevance gate must drop it
        "id": "https://openalex.org/W3", "display_name": "Buckwheat Germplasm Conservation Review",
        "publication_year": 2020, "doi": "https://doi.org/10.1000/noise.1",
        "cited_by_count": 5000, "primary_location": {"source": {"display_name": "Plants"}},
        "authorships": [],
    },
]}).encode()

OPENALEX_ABSTRACTS = json.dumps({"results": [
    {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.48550/arXiv.2403.12345",
     "abstract_inverted_index": {
         "Thin": [0], "structures": [1], "break.": [2],
         "We": [3], "propose": [4], "a": [5], "skeleton": [6], "recall": [7], "loss": [8],
         "for": [9], "tubular": [10], "segmentation.": [11],
         "Experiments": [12], "use": [13], "three": [14], "datasets.": [15]}},
    {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.1000/beta.7",
     "abstract_inverted_index": {"Vessels": [0], "are": [1], "thin.": [2],
                                 "A": [3], "centerline": [4], "recall": [5], "term": [6], "helps.": [7]}},
]}).encode()

S2 = json.dumps({"data": [{
    "paperId": "ccc", "title": "Tubular Segmentation Benchmarks", "year": 2022, "venue": "",
    "authors": [], "externalIds": {}, "citationCount": 1, "url": "https://s2/ccc"}]}).encode()


def routing_transport(url, headers):
    if "export.arxiv.org" in url:
        return ARXIV
    if "api.openalex.org" in url:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        return OPENALEX_ABSTRACTS if "filter" in query else OPENALEX_SEARCH
    if "api.crossref.org" in url:
        raise ScholarLookupError("network failure for crossref: simulated outage")
    if "semanticscholar.org" in url:
        return S2
    raise AssertionError(f"unexpected url {url}")


# --------------------------------------------------------------------------- stage 1 + 2

def test_search_now_keeps_each_channels_own_ranking_additively():
    res = search(QUERY, transport=routing_transport)
    rankings = res["channel_rankings"]
    assert set(rankings) == {"arxiv", "openalex", "crossref", "s2"}
    assert rankings["crossref"] == []                                   # errored -> named + empty
    assert rankings["arxiv"] == ["doi:10.48550/arxiv.2403.12345", "doi:10.48550/arxiv.2401.00001"]
    assert rankings["openalex"][0] == "doi:10.48550/arxiv.2403.12345"  # provider order kept
    assert {"query", "records", "source_errors"} <= set(res)            # old keys untouched


def test_channel_ranks_are_one_based_and_respect_the_keep_set():
    ranks = sf.channel_ranks({"a": ["x", "y", "y", "z"], "b": []}, keep={"y", "z"})
    assert ranks == {"a": {"y": 1, "z": 2}}                             # x dropped, no gap left behind


def test_funnel_prefers_the_record_two_channels_agree_on_and_drops_noise():
    res = sf.funnel(QUERY, transport=routing_transport)
    titles = [r["title"] for r in res["records"]]
    assert titles[0] == "Skeleton Recall Loss for Tubular Segmentation"
    assert "Buckwheat Germplasm Conservation Review" not in titles    # gated despite 5000 citations
    top = res["records"][0]
    assert sorted(top["found_in"]) == ["arxiv", "openalex"]
    assert top["channel_ranks"] == {"arxiv": 1, "openalex": 1}
    assert top["dataset"] == "arxiv"
    counts = res["stage_counts"]
    assert counts["broad_raw"] == 6 and counts["broad_unique"] == 5        # arXiv 2 + OpenAlex 3 + S2 1
    assert counts["rejected_offtopic"] == 1 and counts["fused"] == 4 and counts["final"] == 4
    assert res["channels_lost"] == ["crossref"] and "crossref" in res["source_errors"]
    assert res["source_yield"] == {"arxiv": 2, "openalex": 3, "crossref": 0, "s2": 1}


# --------------------------------------------------------------------------- stage 3

def test_best_passage_picks_the_sentence_carrying_the_query_anchors():
    text = ("Thin structures break. We propose a skeleton recall loss for tubular segmentation. "
            "Experiments use three datasets.")
    passage = sf.best_passage(QUERY, text)
    assert passage["index"] == 1 and passage["text"].startswith("We propose a skeleton recall loss")
    assert passage["score"] == 1.0
    assert sf.best_passage(QUERY, "") == {"text": "", "score": 0.0, "index": -1}
    assert sf.best_passage(QUERY, "Nothing relevant here at all.")["score"] == 0.0
    assert len(sf.best_passage("alpha", "alpha " * 500)["text"]) <= 400


def test_funnel_fetches_abstracts_in_one_batched_openalex_request_and_scores_passages():
    seen = []

    def transport(url, headers):
        seen.append(url)
        return routing_transport(url, headers)

    res = sf.funnel(QUERY, transport=transport)
    abstract_calls = [u for u in seen if "api.openalex.org" in u and "filter=" in u]
    assert len(abstract_calls) == 1
    decoded = urllib.parse.parse_qs(urllib.parse.urlsplit(abstract_calls[0]).query)
    assert decoded["filter"][0].startswith("doi:")
    assert "10.48550/arxiv.2403.12345" in decoded["filter"][0]
    assert decoded["select"][0] == "id,doi,abstract_inverted_index"
    by_title = {r["title"]: r for r in res["records"]}
    top = by_title["Skeleton Recall Loss for Tubular Segmentation"]
    assert top["text"].startswith("We propose a skeleton recall loss")
    assert top["passage_score"] == 1.0
    no_doi = by_title["Tubular Segmentation Benchmarks"]                # the S2 record has no DOI
    assert no_doi["text"] == "" and no_doi["passage_score"] is None
    assert res["stage_counts"]["with_passage_text"] == 2


def test_abstract_fetch_failure_is_named_and_never_blocks_the_ranking():
    def transport(url, headers):
        if "api.openalex.org" in url and "filter=" in url:
            raise ScholarLookupError("network failure for https://api.openalex.org/works?filter=secret: boom")
        return routing_transport(url, headers)

    res = sf.funnel(QUERY, transport=transport)
    assert res["records"]
    assert all(r["passage_score"] is None for r in res["records"])
    assert "openalex_abstracts" in res["source_errors"]
    assert "secret" not in res["source_errors"]["openalex_abstracts"]   # sanitized like every error


def test_caller_supplied_text_wins_over_the_network_and_no_abstracts_disables_the_fetch():
    seen = []

    def transport(url, headers):
        seen.append(url)
        return routing_transport(url, headers)

    def provider(record):
        return "Local full text. Tubular segmentation with skeleton recall loss here." \
            if record.get("arxiv_id") == "2403.12345" else None

    res = sf.funnel(QUERY, transport=transport, text_provider=provider, fetch_abstracts=False)
    assert not [u for u in seen if "filter=" in u]
    top = res["records"][0]
    assert top["text"].startswith("Tubular segmentation with skeleton recall loss")
    assert top["passage_score"] == 1.0


# --------------------------------------------------------------------------- stage 4

def test_authority_score_is_bounded_and_monotonic_in_citations_and_recency():
    low = sf.authority_score({"cited_by_count": 0, "year": 2006})
    mid = sf.authority_score({"cited_by_count": 30, "year": 2020})
    high = sf.authority_score({"cited_by_count": 5000, "year": 2026})
    assert 0.0 <= low < mid < high <= 1.0
    assert high == 1.0                                                  # saturates, never exceeds
    assert sf.authority_score({"cited_by_count": "bad", "year": None}) == sf.authority_score({})


def test_alpha_zero_is_pure_relevance_and_alpha_one_is_pure_authority():
    relevance_only = sf.funnel(QUERY, transport=routing_transport, alpha=0.0)
    authority_only = sf.funnel(QUERY, transport=routing_transport, alpha=1.0)
    assert relevance_only["records"][0]["title"] == "Skeleton Recall Loss for Tubular Segmentation"
    assert authority_only["records"][0]["title"] == "Centerline Recall Loss for Vessel Segmentation"
    for r in relevance_only["records"]:
        assert r["score"] == r["relevance"]
    for r in authority_only["records"]:
        assert r["score"] == r["authority"]
    with pytest.raises(ValueError):
        sf.funnel(QUERY, transport=routing_transport, alpha=1.5)
    with pytest.raises(ValueError):
        sf.funnel("   ", transport=routing_transport)


def test_scores_never_leak_into_evidence_rows():
    res = sf.funnel(QUERY, transport=routing_transport)
    rows = to_evidence_sources(res["records"])
    assert rows and all(set(r) <= {"id", "kind", "ref", "title", "year", "claim_support", "notes"}
                        for r in rows)
    assert all(r["claim_support"] == "none" for r in rows)


# --------------------------------------------------------------------------- related queries

def test_related_queries_add_one_new_title_term_to_the_query_anchors():
    res = sf.funnel(QUERY, transport=routing_transport)
    proposals = res["related_queries"]
    assert proposals and len(proposals) <= 5
    for p in proposals:
        assert p["query"].startswith("skeleton recall loss")
        assert p["new_term"] not in QUERY.split()
        assert not {"for", "with", "the"} & set(p["new_term"].split())  # stopwords are not leads
        assert p["support"] >= 1
    supports = [p["support"] for p in proposals]
    assert supports == sorted(supports, reverse=True)
    # adjacent title pairs are preferred leads: "topology aware" outranks the single word "aware"
    assert proposals[0]["new_term"] in {"centerline recall", "topology aware", "aware recall",
                                        "vessel segmentation"}
    assert " " in proposals[0]["new_term"]
    assert sf.propose_related_queries("", res["records"]) == []
    assert sf.propose_related_queries(QUERY, []) == []


def test_related_queries_join_cjk_anchors_without_spaces():
    records = [{"title": "医学图像涂鸦交互分割方法"}, {"title": "医学图像分割新方法"}]
    proposals = sf.propose_related_queries("医学图像分割", records, k=2)
    assert proposals and all(" " not in p["query"] for p in proposals)
    assert all(p["query"].startswith("医学") for p in proposals)


# --------------------------------------------------------------------------- recursion

def test_recursive_search_stops_after_two_rounds_that_add_nothing():
    res = sf.recursive_search(QUERY, depth=5, breadth=1, transport=routing_transport)
    assert [r["n_new_records"] for r in res["rounds"]] == [4, 0, 0]
    assert res["expansion_stop_reason"] == "trailing_rounds_added_nothing"
    assert res["not_a_saturation_verdict"] is True
    assert res["n_queries_searched"] == 3 and res["n_records"] == 4
    assert res["query_tree"][0] == {"query": QUERY, "parent": None, "round": 0, "searched": True}
    assert res["query_tree"][1]["parent"] == QUERY and res["query_tree"][1]["round"] == 1
    assert res["query_tree"][2]["parent"] == res["query_tree"][1]["query"]
    assert [row["searched"] for row in res["query_tree"]] == [True, True, True, False]  # 4th proposed, never run
    assert res["records"][0]["matched_queries"][0] == QUERY
    assert any(k.startswith("r0:crossref:") for k in res["source_errors"])


def test_recursive_search_respects_depth_and_breadth_and_never_repeats_a_query():
    res = sf.recursive_search(QUERY, depth=2, breadth=2, transport=routing_transport)
    assert len(res["rounds"]) == 2 and res["expansion_stop_reason"] == "depth_reached"
    children = [row for row in res["query_tree"] if row["parent"] == QUERY]
    assert len(children) == 2
    searched = [row["query"].lower() for row in res["query_tree"]]
    assert len(searched) == len(set(searched))
    with pytest.raises(ValueError):
        sf.recursive_search(QUERY, depth=0, transport=routing_transport)


def test_follow_up_rounds_cannot_drift_off_the_seed_question(monkeypatch):
    """A follow-up query's own funnel may accept a title the SEED question never asked for
    ("Road Network Recall Benchmarks" passes "tubular recall road network" at 0.75 but scores
    0.25 against the seed); the merged list must reject it and count it as drift."""
    follow_up = "tubular recall road network"
    monkeypatch.setattr(sf, "propose_related_queries",
                        lambda query, records, k=5, max_anchors=4: [
                            {"query": follow_up, "new_term": "road network", "support": 1,
                             "basis": "test"}])
    drift = json.dumps({"results": [{
        "id": "https://openalex.org/W9", "display_name": "Road Network Recall Benchmarks",
        "publication_year": 2021, "doi": "https://doi.org/10.1000/drift.9", "cited_by_count": 40,
        "primary_location": {"source": {"display_name": "GIS"}}, "authorships": []}]}).encode()

    def transport(url, headers):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if "api.openalex.org" in url and query.get("search", [None])[0] == follow_up:
            return drift                                    # only the follow-up query sees it
        return routing_transport(url, headers)

    res = sf.recursive_search(QUERY, depth=2, breadth=1, transport=transport)
    titles = [r["title"] for r in res["records"]]
    assert "Road Network Recall Benchmarks" not in titles
    assert res["rounds"][1]["queries"] == [follow_up]
    assert res["rounds"][1]["n_drift_rejected"] == 1 and res["rounds"][0]["n_drift_rejected"] == 0
    assert all(r["seed_title_relevance"] >= 0.5 for r in res["records"])
    relevances = [r["seed_title_relevance"] for r in res["records"]]
    assert relevances == sorted(relevances, reverse=True)     # seed relevance orders the merge


def test_trace_rounds_are_a_valid_but_incomplete_evidence_search_trace_skeleton():
    res = sf.recursive_search(QUERY, depth=3, breadth=1, transport=routing_transport)
    rounds = sf.trace_rounds(res)
    assert [r["round_index"] for r in rounds] == list(range(len(rounds)))
    assert rounds[0]["questions"] == [QUERY]
    assert {"source_ref"} == set(rounds[0]["source_hits"][0])
    trace = {
        "search_contract_version": "evidence-search-trace/v1",
        "research_question": QUERY,
        "critical_claims": [{"claim_id": "c1", "question": "does it help?", "importance": "critical"}],
        "representativeness_dimensions": ["dataset"],
        "rounds": rounds,
        "stop_reason": "inconclusive",
        "budget_exhausted": False,
    }
    assert validate_against("evidence_search_trace.schema.json", trace) == []
    audit = evaluate_search_trace(trace)
    assert audit["status"] == "INCOMPLETE"                              # the moderator still has to judge
    assert audit["semantic_complete"] is False


# --------------------------------------------------------------------------- bundle + CLI

def test_bundle_writes_run_local_only_and_refuses_the_vault(tmp_path):
    res = sf.funnel(QUERY, transport=routing_transport)
    path = sf.write_funnel_bundle(tmp_path / "runs" / "r1", res, "2026-09-05T12:00:00Z")
    data = json.loads((tmp_path / "runs" / "r1" / "inbox" / "search-funnel.json").read_text(encoding="utf-8"))
    assert path.endswith("search-funnel.json")
    assert data["funnel_version"] == "search-funnel/v1" and data["retrieved_at"] == "2026-09-05T12:00:00Z"
    assert data["records"][0]["title"] == "Skeleton Recall Loss for Tubular Segmentation"
    with pytest.raises(ValueError):
        sf.write_funnel_bundle(tmp_path / "AI agent database" / "PhD-Research-OS" / "runs" / "x", res, "t")


def test_cli_prints_the_stage_counts_and_writes_json(tmp_path, capsys):
    out = tmp_path / "funnel.json"
    assert sf.main([QUERY, "--json", str(out), "--final", "2"], transport=routing_transport) == 0
    printed = capsys.readouterr().out
    assert "funnel: raw 6 -> unique 5 -> fused 4 -> passage-ranked 4 -> final 2" in printed
    assert "related:" in printed and "!! crossref" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["records"]) == 2
    assert sf.main([QUERY, "--depth", "2", "--breadth", "1", "--no-abstracts"],
                   transport=routing_transport) == 0
    assert "recursive search:" in capsys.readouterr().out
    with pytest.raises(ValueError):
        sf.main([QUERY, "--json", str(tmp_path / "phd-research-os" / "leak.json")],
                transport=routing_transport)


# --------------------------------------------------------------------------- operated pre-search wiring

def test_combine_and_merge_keep_the_bundle_metadata_only_and_reorder_it():
    first = sf.funnel(QUERY, transport=routing_transport)
    second = sf.funnel("tubular segmentation benchmarks", transport=routing_transport)
    combined = sf.combine_funnel_results([first, second])
    keys = [sf._dedup_key(r) for r in combined]
    assert len(keys) == len(set(keys)) == 4                              # deduped across queries
    assert combined[0]["title"] == "Skeleton Recall Loss for Tubular Segmentation"
    assert combined[0]["matched_queries"][0] == QUERY
    facade = search(QUERY, transport=routing_transport)          # citation order: noise, B, A, C, D
    result = {"records": facade["records"][:3], "source_errors": {"q1:crossref": "x"}}
    sf.merge_funnel_into_search_result(result, combined, summary={"status": "ok"})
    assert result["funnel"]["n_annotated_records"] == 2 and result["funnel"]["n_added_records"] == 2
    assert [r.get("funnel_rank") for r in result["records"]] == [1, 2, 3, 4, None]
    assert result["records"][0]["title"] == "Skeleton Recall Loss for Tubular Segmentation"
    assert result["records"][-1]["title"] == "Buckwheat Germplasm Conservation Review"  # unranked stays last
    added = [r for r in result["records"] if r.get("found_via") == "search-funnel"]
    assert len(added) == 2 and all("text" not in r and "score" not in r for r in added)
    assert all("relevance_score" in r for r in added)
    assert result["source_errors"] == {"q1:crossref": "x"}               # facade accounting untouched
    proposals = sf.combine_related_queries([first, second])
    assert proposals and [p["support"] for p in proposals] == sorted(
        [p["support"] for p in proposals], reverse=True)              # best-supported lead first
    assert any(p["query"].startswith("skeleton recall loss") for p in proposals)


def test_pre_search_runs_the_funnel_by_default_and_keeps_the_facade_bundle_intact(tmp_path):
    from research_agent_teams.operate.modes import _shared
    run_dir = tmp_path / "runs" / "r1"
    path = _shared.pre_search(run_dir, QUERY, "2026-09-05T12:00:00Z", transport=routing_transport)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["funnel"]["status"] == "ok" and data["funnel"]["depth"] == 1
    assert data["funnel"]["n_funnel_records"] == 4 and data["funnel"]["channels_lost"] == ["crossref"]
    assert data["records"][0]["funnel_rank"] == 1
    assert data["records"][0]["title"] == "Skeleton Recall Loss for Tubular Segmentation"
    assert all("text" not in r for r in data["records"])                # metadata by reference
    assert set(data["source_errors"]) == {"q1:crossref"}                # facade accounting untouched
    assert "q1:crossref" in data["funnel"]["source_errors"]
    assert data["related_queries"][0]["query"].startswith("skeleton recall loss")
    assert len(data["evidence_rows"]) == len(data["records"])
    side = json.loads((run_dir / "inbox" / "search-funnel.json").read_text(encoding="utf-8"))
    assert side["depth"] == 1 and side["queries"] == [QUERY]
    assert side["records"][0]["text"].startswith("We propose a skeleton recall loss")
    assert "crossref" in side["results"][0]["source_errors"]


def test_pre_search_can_skip_the_funnel_and_the_language_guard_never_runs_it(tmp_path):
    from research_agent_teams.operate.modes import _shared
    off = json.loads(Path(_shared.pre_search(tmp_path / "runs" / "r2", QUERY, "t",
                                             transport=routing_transport, funnel=False)
                          ).read_text(encoding="utf-8"))
    assert "funnel" not in off and "related_queries" not in off
    assert not (tmp_path / "runs" / "r2" / "inbox" / "search-funnel.json").exists()
    cjk = json.loads(Path(_shared.pre_search(tmp_path / "runs" / "r3", "医学图像分割", "t",
                                             transport=routing_transport)).read_text(encoding="utf-8"))
    assert "query_language_block" in cjk and "funnel" not in cjk
    assert not (tmp_path / "runs" / "r3" / "inbox" / "search-funnel.json").exists()


def test_funnel_failure_is_recorded_and_never_breaks_pre_search(tmp_path, monkeypatch):
    from research_agent_teams.operate.modes import _shared

    def boom(*args, **kwargs):
        raise RuntimeError("boom secret=hunter2")

    monkeypatch.setattr(_shared, "run_funnel", boom)
    data = json.loads(Path(_shared.pre_search(tmp_path / "runs" / "r4", QUERY, "t",
                                              transport=routing_transport)).read_text(encoding="utf-8"))
    assert data["funnel"]["status"] == "failed" and "boom" in data["funnel"]["error"]
    assert "hunter2" not in data["funnel"]["error"]                     # sanitized like every error
    assert len(data["records"]) == 4 and set(data["source_errors"]) == {"q1:crossref"}
    assert all("funnel_rank" not in r for r in data["records"])


def test_deep_research_pre_search_follows_one_round_of_related_queries_by_default(tmp_path):
    from research_agent_teams.operate.modes import deep_research
    run_dir = tmp_path / "runs" / "r5"
    data = json.loads(Path(deep_research.pre_search(str(run_dir), QUERY, "t", transport=routing_transport)
                          ).read_text(encoding="utf-8"))
    assert data["funnel"]["depth"] == 2 and data["funnel"]["breadth"] == 2
    assert data["funnel"]["expansion_stop_reasons"] == ["depth_reached"]
    side = json.loads((run_dir / "inbox" / "search-funnel.json").read_text(encoding="utf-8"))
    assert side["results"][0]["recursion_version"] == "search-funnel-recursion/v1"
    assert len(side["results"][0]["rounds"]) == 2
    assert data["records"][0]["funnel_rank"] == 1
    shallow = json.loads(Path(deep_research.pre_search(str(tmp_path / "runs" / "r6"), QUERY, "t",
                                                       transport=routing_transport, funnel_depth=1)
                              ).read_text(encoding="utf-8"))
    assert shallow["funnel"]["depth"] == 1
