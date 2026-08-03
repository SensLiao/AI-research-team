"""operate/modes/_shared — the cross-recipe deterministic helpers (audit waves A-B)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate import cli as operate_cli
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _shared

TS = "2026-06-13T00:00:00Z"


def test_operate_cli_forces_utf8_for_current_and_child_commands(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setattr(operate_cli.sys, "stdout", Stream())
    monkeypatch.setattr(operate_cli.sys, "stderr", Stream())

    operate_cli._configure_utf8_stdio()

    assert operate_cli.os.environ["PYTHONUTF8"] == "1"
    assert operate_cli.os.environ["PYTHONIOENCODING"] == "utf-8"
    assert calls == [
        {"encoding": "utf-8", "errors": "strict"},
        {"encoding": "utf-8", "errors": "strict"},
    ]


def _run(tmp_path, request="study canal segmentation prompts", **kw):
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    plan = spine.begin(str(runs), kw.pop("run_id", "sh1"), request, "evidence_review", TS, **kw)
    return plan["run_dir"]


def test_north_star_block_carries_the_contract(tmp_path):
    rd = _run(tmp_path, north_star={"statement": "the ONE direction",
                                    "in_scope": ["prompts"], "out_of_scope": ["pricing"]})
    block = _shared.north_star_block(rd)
    assert "NORTH STAR" in block and "the ONE direction" in block
    assert "prompts" in block and "pricing" in block


def test_require_bundle_keys_blocks_readably():
    with pytest.raises(GateBlock, match="missing required key"):
        _shared.require_bundle_keys({"a": 1}, ("a", "b", "c"), stage="DISCOVER", mode="m")
    _shared.require_bundle_keys({"a": 1, "b": 2}, ("a", "b"), stage="DISCOVER", mode="m")


def test_run_drift_gate_blocks_out_of_scope_and_writes_the_verdict(tmp_path):
    rd = _run(tmp_path, north_star={"statement": "canal segmentation prompts",
                                    "in_scope": [], "out_of_scope": ["pricing"]})
    path, facts = _shared.run_drift_gate(rd, "DISCOVER", TS, ["better canal segmentation prompts"])
    assert Path(path).exists() and facts["violations"] == []
    with pytest.raises(GateBlock, match="drift gate BLOCK"):
        _shared.run_drift_gate(rd, "DISCOVER", TS, ["a pricing strategy for canal segmentation"])
    blocked = json.loads(Path(rd, "evidence", "DISCOVER", "drift-verdict.artifact.json").read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked" and blocked["payload"]["pass"] is False


def test_referential_integrity_rules():
    known = {"GAP-1", "IH1"}
    v, w = _shared.check_referential_integrity(
        ["GAP-1", "IH1", "[[real-page]]", "[[ghost-page]]", "GAP-9", "doi:10.1/x", ""],
        known, vault_slug_set={"real-page"})
    assert any("ghost-page" in x for x in v)            # invented slug
    assert any("GAP-9" in x for x in v)                 # fabricated internal id
    assert any("empty evidence_ref" in x for x in v)
    assert not any("doi:10.1/x" in x for x in v)        # external refs belong to the existence gate
    v2, w2 = _shared.check_referential_integrity(["[[anything]]"], set(), vault_slug_set=None)
    assert v2 == [] and any("unverified" in x for x in w2)   # no vault -> warning, never a false block


def test_existence_gate_offline_is_warnings_never_a_false_block(tmp_path):
    rd = _run(tmp_path)
    path, verdict = _shared.run_existence_gate(rd, "DISCOVER", TS,
                                               ["doi:10.1234/fake", "[[slug-ref]]"])
    assert verdict["verdict"] == "PASS"                 # offline transport -> lookup_error warnings
    assert verdict["n_lookup_error"] == 1 and verdict["n_skipped"] == 1
    assert Path(path).exists()


def test_existence_gate_blocks_on_confirmed_not_found(tmp_path, monkeypatch):
    rd = _run(tmp_path)
    monkeypatch.setattr(_shared, "build_existence_verdict",
                        lambda refs, ts, transport=None, cache=None: {
                            "checked": [], "n_verified": 0, "n_not_found": 1, "n_lookup_error": 0,
                            "n_skipped": 0, "verdict": "BLOCK",
                            "violations": ["doi:10.1/ghost: confirmed not found"], "warnings": []})
    with pytest.raises(GateBlock, match="citation existence gate BLOCK"):
        _shared.run_existence_gate(rd, "DISCOVER", TS, ["doi:10.1/ghost"])


def test_pre_search_degrades_honestly_and_records_are_readable(tmp_path):
    rd = _run(tmp_path)
    from research_agent_teams.tools.scholar_clients import ScholarLookupError

    def dead(url, headers):
        raise ScholarLookupError("offline")
    bundle = _shared.pre_search(rd, "canal prompts", TS, transport=dead)
    data = json.loads(Path(bundle).read_text(encoding="utf-8"))
    assert data["records"] == [] and data["source_errors"]          # degrade, never fabricate
    assert _shared.search_records(rd) == []


def test_pre_search_keeps_pinned_request_but_runs_explicit_utf8_query_plan(tmp_path):
    rd = _run(tmp_path)
    body = json.dumps({"message": {"items": [{
        "title": ["医学图像涂鸦交互分割"], "DOI": "10.1000/utf8",
        "issued": {"date-parts": [[2025]]}, "container-title": ["Medical Imaging"],
    }]}}, ensure_ascii=False).encode("utf-8")

    bundle = _shared.pre_search(
        rd,
        "建立一份来源可核验的补充证据包",
        TS,
        transport=lambda url, headers: body,
        sources=("crossref",),
        queries=["医学图像 涂鸦 交互分割"],
    )
    data = json.loads(Path(bundle).read_text(encoding="utf-8"))
    assert data["task_request"] == "建立一份来源可核验的补充证据包"
    assert data["queries"] == ["医学图像 涂鸦 交互分割"]
    assert data["records"][0]["title"] == "医学图像涂鸦交互分割"
    assert data["relevance_filter"]["n_rejected"] == 0
    assert data["retrieval_channels"]["local_fulltext"] == "fulltext-pre"


def test_novelty_signals_only_when_no_near_neighbor():
    gaps = [{"gap_id": "GAP-1", "statement": "prompt efficiency for canal segmentation"},
            {"gap_id": "GAP-2", "statement": "totally novel underwater basket weaving"}]
    records = [{"title": "Prompt efficiency for canal segmentation networks"}]
    sig = _shared.novelty_signals_from_search(gaps, records)
    assert "GAP-1" not in sig                                       # near neighbor found
    assert sig.get("GAP-2") == ["no_semantic_neighbor_found"]
    assert _shared.novelty_signals_from_search(gaps, []) == {}      # no records -> no claim


def test_negative_result_caveats_match_vault_pages(tmp_path):
    vault = tmp_path / "vault"
    nr = vault / "02-wiki" / "negative-results"
    nr.mkdir(parents=True)
    (nr / "lora-rank64-canal-segmentation.md").write_text(
        "# LoRA rank-64 canal segmentation fails\nbody", encoding="utf-8")
    ideas = [{"idea_id": "IDEA-1", "summary": "try LoRA rank-64 canal segmentation again"},
             {"idea_id": "IDEA-2", "summary": "an unrelated benchmark suite for retrieval"}]
    out = _shared.negative_result_caveats(str(vault), ideas)
    assert "IDEA-1" in out and "lora-rank64-canal-segmentation" in out["IDEA-1"][0]
    assert "IDEA-2" not in out
    assert _shared.negative_result_caveats(None, ideas) == {}
