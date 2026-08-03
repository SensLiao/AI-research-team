"""`.workbench/` is a cache: it must round-trip every field, and be safe to delete."""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from research_agent_teams.workbench.model import ArtifactRow, ProjectRow, TaskRow
from research_agent_teams.workbench.store import (
    WorkbenchStore,
    destroy,
    fts_expression,
    workbench_root,
)


def _full_task() -> TaskRow:
    """Every field set to something distinctive, so a dropped column is visible."""
    return TaskRow(
        task_id="p:T-1", project="p", title="题目", work_state="ready",
        evidence_state="simulated", priority="P0", why_now="拖了就变成事后合理化",
        next_action="records/x.json", blockers=("等 N04",),
        source_path="records/n-task-ledger.json", source_status="BUILT_PENDING_N04",
        evidence_reason="只在 fixture 上跑过",
    )


def _full_artifact() -> ArtifactRow:
    return ArtifactRow(
        artifact_id="vault:results/a", project="p", kind="result", title="标题",
        path="/tmp/a.md", source="vault", updated="2026-08-03", run_id="r-1",
        evidence_state="frozen", evidence_reason="库自己的 result-status=frozen",
        lifecycle="active", text="scribble 与 M0 的状态相对意图",
    )


# ------------------------------------------------------- the drift guard (this is the point)

def test_every_task_field_survives_the_store(tmp_path):
    """A field added to the model but not to the schema would be silently dropped."""
    row = _full_task()
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(tasks=[row], built_at="T")
        stored = store.tasks()[0]
    missing = {f.name for f in fields(TaskRow)} - set(stored)
    assert not missing, f"store dropped TaskRow fields: {sorted(missing)}"
    assert stored["source_status"] == "BUILT_PENDING_N04"
    assert stored["evidence_reason"] == "只在 fixture 上跑过"
    assert stored["blockers"] == ["等 N04"]


def test_every_artifact_field_survives_the_store(tmp_path):
    """`text` is the one field held in the search index rather than a column — assert both."""
    row = _full_artifact()
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[row], built_at="T")
        stored = store.artifact(row.artifact_id)
        found = store.search("M0")
    declared = {f.name for f in fields(ArtifactRow)} - {"text"}
    missing = declared - set(stored)
    assert not missing, f"store dropped ArtifactRow fields: {sorted(missing)}"
    assert stored["lifecycle"] == "active"
    assert stored["evidence_reason"].startswith("库自己的")
    assert [h["artifact_id"] for h in found["hits"]] == [row.artifact_id], "body was not indexed"


def test_project_rows_round_trip_whole(tmp_path):
    row = ProjectRow(
        slug="p", title="P", question="M0 是否承载意图？",
        truth_boundary=("0 篇可发表的六分类结果",), lifecycle="active", active=True,
        latest_run_id="r-1", latest_run_stage="done", open_decisions=("要不要预注册",),
        blockers=("等 N04",), counts={"runs": 5, "decided": 1}, home_path="/tmp/PROJECT-HOME.md",
    )
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(projects=[row], built_at="T")
        stored = store.projects()[0]
    assert stored == row.as_dict()


# ---------------------------------------------------------------- rebuildable, and contained

def test_deleting_the_projection_loses_nothing_a_rebuild_cannot_restore(tmp_path):
    task, artifact = _full_task(), _full_artifact()
    store = WorkbenchStore(str(tmp_path))
    first = store.rebuild(tasks=[task], artifacts=[artifact], built_at="T")
    before = (store.tasks(), store.projects(), store.artifact(artifact.artifact_id))
    store.close()

    removed = destroy(str(tmp_path))
    assert "index.sqlite" in removed["removed"]
    assert not WorkbenchStore(str(tmp_path)).exists()

    store = WorkbenchStore(str(tmp_path))
    again = store.rebuild(tasks=[task], artifacts=[artifact], built_at="T")
    after = (store.tasks(), store.projects(), store.artifact(artifact.artifact_id))
    store.close()
    assert before == after
    assert first["counts"] == again["counts"]


def test_the_store_writes_nothing_outside_its_own_root(tmp_path):
    root = tmp_path / "inside"
    sibling = tmp_path / "untouched"
    sibling.mkdir()
    with WorkbenchStore(str(root)) as store:
        store.rebuild(tasks=[_full_task()], artifacts=[_full_artifact()], built_at="T")
    assert list(sibling.iterdir()) == []
    assert {p.name for p in root.iterdir()} >= {
        "index.sqlite", "meta.json", "tasks.jsonl", "artifacts.jsonl",
        "projects.jsonl", "capabilities.jsonl",
    }


def test_jsonl_views_are_line_per_row_for_an_agent_to_read_in_one_go(tmp_path):
    import dataclasses
    import json

    second = dataclasses.replace(_full_task(), task_id="p:T-2")
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(tasks=[_full_task(), second], built_at="T")
    lines = (tmp_path / "tasks.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["task_id"] for line in lines] == ["p:T-1", "p:T-2"]


def test_a_duplicate_id_fails_loudly_instead_of_being_silently_deduped(tmp_path):
    """Two rows claiming one id is an indexer defect; swallowing it would hide the defect."""
    import sqlite3

    import pytest

    with WorkbenchStore(str(tmp_path)) as store:
        with pytest.raises(sqlite3.IntegrityError):
            store.rebuild(tasks=[_full_task(), _full_task()], built_at="T")


# ----------------------------------------------------------------------------- search honesty

def test_search_reports_which_engine_answered(tmp_path):
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[_full_artifact()], built_at="T")
        assert store.search("M0")["engine"] in {"fts5", "like"}


def test_search_filters_by_project_and_source(tmp_path):
    other = ArtifactRow(
        artifact_id="machine:x", project="q", kind="note", title="别的",
        path="/tmp/x.md", source="machine", text="M0 也出现在这里",
    )
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[_full_artifact(), other], built_at="T")
        assert len(store.search("M0")["hits"]) == 2
        assert [h["project"] for h in store.search("M0", project="q")["hits"]] == ["q"]
        assert [h["source"] for h in store.search("M0", source="vault")["hits"]] == ["vault"]


def test_an_empty_query_or_a_missing_index_returns_empty_rather_than_raising(tmp_path):
    store = WorkbenchStore(str(tmp_path / "nothing-here"))
    assert store.search("M0")["hits"] == []
    assert store.projects() == [] and store.tasks() == []
    assert store.artifact("vault:results/a") is None
    assert store.meta()["available"] is False
    with WorkbenchStore(str(tmp_path)) as built:
        built.rebuild(artifacts=[_full_artifact()], built_at="T")
        assert built.search("   ")["hits"] == []


def test_prose_with_a_hyphen_is_not_read_as_a_full_text_operator(tmp_path):
    """`state-relative intent` used to fail with `no such column: relative`."""
    row = ArtifactRow(
        artifact_id="a", project="p", kind="k", title="t", path="/tmp/a.md", source="vault",
        text="a structured state-relative correction intent",
    )
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[row], built_at="T")
        result = store.search("state-relative intent")
    assert [h["artifact_id"] for h in result["hits"]] == ["a"]
    assert not result.get("note"), "a plain phrase should not produce a syntax complaint"


def test_quoting_turns_a_phrase_into_an_and_over_its_words():
    assert fts_expression("state-relative intent") == '"state" "relative" "intent"'
    assert fts_expression('"exact phrase" other') == '"exact phrase" "other"'
    assert fts_expression("!!! ???") == ""


def test_a_chinese_query_is_routed_to_substring_search_and_says_so(tmp_path):
    """FTS5's default tokenizer cannot segment CJK, so substring search is the honest engine."""
    row = ArtifactRow(
        artifact_id="cn", project="p", kind="k", title="残差纠错", path="/tmp/cn.md",
        source="machine", text="这一页讲的是残差区域的纠错意图",
    )
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[row], built_at="T")
        result = store.search("残差")
    assert result["engine"] == "like"
    assert [h["artifact_id"] for h in result["hits"]] == ["cn"]


def test_raw_mode_hands_the_query_to_full_text_verbatim(tmp_path):
    row = ArtifactRow(
        artifact_id="a", project="p", kind="k", title="t", path="/tmp/a.md", source="vault",
        text="alpha beta",
    )
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[row], built_at="T")
        if store.search_engine != "fts5":
            return
        assert store.search("alpha NOT gamma", raw=True)["hits"], "operators should work"
        assert not store.search("alpha NOT beta", raw=True)["hits"]


def test_a_query_that_looks_like_broken_syntax_is_sanitized_not_rejected(tmp_path):
    """Quoting every term means a director cannot hand us an unparseable expression."""
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[_full_artifact()], built_at="T")
        result = store.search('M0 AND ("')
    assert not result.get("note"), "sanitized input should not produce a syntax complaint"


def test_raw_mode_reports_a_syntax_complaint_rather_than_crashing(tmp_path):
    """A caller opting into operators owns the syntax — but still gets a message, not a stack."""
    with WorkbenchStore(str(tmp_path)) as store:
        store.rebuild(artifacts=[_full_artifact()], built_at="T")
        if store.search_engine != "fts5":
            return
        result = store.search('M0 AND ("', raw=True)
    assert result["hits"] == [] and result.get("note")


def test_meta_records_the_sources_and_says_it_is_not_a_source_of_truth(tmp_path):
    with WorkbenchStore(str(tmp_path)) as store:
        meta = store.rebuild(built_at="T", sources={"vault": "/v", "machine": "/m"})
    assert meta["built_at"] == "T"
    assert meta["sources"] == {"vault": "/v", "machine": "/m"}
    assert "不是任何事实的来源" in meta["note"]


# --------------------------------------------------------------------------------- root resolution

def test_the_root_is_overridable_so_a_test_never_touches_the_real_projection(tmp_path, monkeypatch):
    monkeypatch.delenv("RAT_WORKBENCH_ROOT", raising=False)
    assert workbench_root().name == ".workbench"
    monkeypatch.setenv("RAT_WORKBENCH_ROOT", str(tmp_path / "env"))
    assert workbench_root() == tmp_path / "env"
    assert workbench_root(str(tmp_path / "explicit")) == tmp_path / "explicit", "explicit wins"
