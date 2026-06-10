"""fulltext_qa — honest unavailable paths, engine mapping, vault fence, retraction check (wave 1)."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.fulltext_qa import ask, paperqa_available, retraction_check
from research_agent_teams.tools.scholar_clients import ScholarLookupError
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"


def _validate(payload) -> list:
    return validate_artifact(envelope("fulltext_qa_report", "fulltext-qa", payload, TS))


def test_no_docs_is_honestly_unavailable():
    rep = ask("what is the dice score?", [])
    assert rep["available"] is False and "no documents" in rep["reason"]
    assert _validate(rep) == []


def test_missing_paperqa_is_honestly_unavailable():
    if paperqa_available():  # environment-dependent guard: only meaningful without the optional dep
        pytest.skip("paper-qa installed in this environment")
    rep = ask("q?", ["some/doc.pdf"])
    assert rep["available"] is False and "paper-qa" in rep["reason"]
    assert _validate(rep) == []


def test_injected_engine_maps_contexts_and_truncates_excerpts():
    def engine(question, doc_paths, cache_dir):
        assert question == "q?" and doc_paths == ["a.pdf"]
        return {"answer": "Grounded answer.",
                "contexts": [
                    {"doc_ref": "a.pdf", "page": 7, "excerpt": "x" * 900, "relevance": 0.83},
                    {"doc_ref": "a.pdf", "page": 0, "excerpt": "valid short", "relevance": 7},
                    {"doc_ref": "", "page": 1, "excerpt": "dropped (no doc_ref)"},
                    {"doc_ref": "a.pdf", "page": 2, "excerpt": "   "},
                ]}

    rep = ask("q?", ["a.pdf"], engine=engine)
    assert rep["available"] is True and rep["answer_summary"] == "Grounded answer."
    assert len(rep["contexts"]) == 2                       # blank/ref-less contexts dropped
    assert len(rep["contexts"][0]["excerpt"]) == 500       # truncated to the schema bound
    assert rep["contexts"][0]["page"] == 7
    assert rep["contexts"][1]["page"] is None              # page 0 is not a real anchor
    assert rep["contexts"][1]["relevance"] == 1.0          # clamped into [0,1]
    assert _validate(rep) == []


def test_engine_crash_is_unavailable_never_fabricated():
    def engine(question, doc_paths, cache_dir):
        raise RuntimeError("index exploded")
    rep = ask("q?", ["a.pdf"], engine=engine)
    assert rep["available"] is False and "index exploded" in rep["reason"]
    assert rep["answer_summary"] == "" and rep["contexts"] == []
    assert _validate(rep) == []


def test_cache_dir_inside_vault_is_rejected():
    with pytest.raises(ValueError):
        ask("q?", ["a.pdf"], cache_dir="AI agent database/PhD-Research-OS/.cache",
            engine=lambda q, d, c: {"answer": "", "contexts": []})


def test_vault_doc_path_is_rejected_no_body_leak():
    # Adversarial (reviewer MEDIUM): reading a vault page as a 'doc' would copy vault body excerpts
    # into the report (PaperQA contexts), breaking the by-reference seam. Must be refused up front.
    with pytest.raises(ValueError):
        ask("what is the dice score?",
            ["AI agent database/PhD-Research-OS/02-wiki/results/medsam3-lora-ablation.md"],
            engine=lambda q, d, c: {"answer": "leaked", "contexts": [
                {"doc_ref": "medsam3-lora-ablation.md", "excerpt": "SECRET", "page": 1}]})


def test_empty_question_rejected():
    with pytest.raises(ValueError):
        ask("  ", ["a.pdf"])


# --------------------------------------------------------------------------- retraction check

def _crossref_updates_body(notices):
    return json.dumps({"message": {"items": notices}}).encode()


def test_retraction_check_states():
    def router(url, headers):
        if "updates%3A10.1000%2Fretracted" in url or "updates:10.1000/retracted" in url:
            return _crossref_updates_body([{
                "DOI": "10.1000/notice.1",
                "update-to": [{"DOI": "10.1000/retracted", "type": "retraction", "label": "Retraction"}]}])
        if "updates%3A10.1000%2Fconcern" in url or "updates:10.1000/concern" in url:
            return _crossref_updates_body([{
                "DOI": "10.1000/notice.2",
                "update-to": [{"DOI": "10.1000/concern", "type": "expression_of_concern",
                               "label": "Expression of concern"}]}])
        if "updates%3A10.1000%2Fdown" in url or "updates:10.1000/down" in url:
            raise ScholarLookupError("offline")
        return _crossref_updates_body([])

    flags = retraction_check(
        ["doi:10.1000/retracted", "10.1000/concern", "10.1000/clean", "10.1000/down", "not a doi"],
        transport=router)
    by_ref = {f["ref"]: f["status"] for f in flags}
    assert by_ref["doi:10.1000/retracted"] == "retracted"
    assert by_ref["10.1000/concern"] == "concern"
    assert by_ref["10.1000/clean"] == "ok"
    assert by_ref["10.1000/down"] == "unknown"             # offline is never 'ok'
    assert by_ref["not a doi"] == "unknown"

    rep = ask("q?", [], retraction_flags=flags)            # flags ride the report schema
    assert _validate(rep) == []
