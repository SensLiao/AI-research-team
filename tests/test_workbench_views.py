"""The generated pages and the CLI: what the director actually reads must not mislead."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.workbench.cli import main
from research_agent_teams.workbench.model import ArtifactRow, ProjectRow, TaskRow
from research_agent_teams.workbench.projectors import (
    render_project_home,
    render_research_home,
    write_home_pages,
)

TS = "2026-08-03T00:00:00Z"


def _project(**kw) -> ProjectRow:
    base = dict(
        slug="petct", title="petct", question="M0 是否承载状态相对的意图？",
        truth_boundary=("0 篇可发表的六分类结果", "（上次运行守住的）no GPU job submitted"),
        lifecycle="active", active=True, latest_run_id="r-1", latest_run_stage="done",
        counts={"runs": 5, "docs": 60, "tasks": 13, "decided": 1},
    )
    base.update(kw)
    return ProjectRow(**base)


def _vault_rows() -> list[ArtifactRow]:
    def row(i: int, state: str) -> ArtifactRow:
        return ArtifactRow(artifact_id=f"vault:results/{state}{i}", project="", kind="result",
                           title=f"{state}{i}", path=f"/v/{state}{i}.md", source="vault",
                           evidence_state=state)
    return ([row(i, "frozen") for i in range(3)]
            + [row(i, "observed") for i in range(5)]
            + [row(i, "superseded") for i in range(2)]
            + [row(i, "proposed") for i in range(4)])


# ----------------------------------------------------------------- the pages say what they are

def test_a_generated_page_tells_the_reader_not_to_edit_it():
    for page in (render_project_home(_project(), built_at=TS),
                 render_research_home([_project()], built_at=TS)):
        assert "自动生成" in page and "不要手改" in page
        assert "不是这一页" in page, "the page must disclaim being a source of truth"


def test_the_vault_numbers_are_printed_per_axis_and_never_summed():
    page = render_research_home([_project()], artifacts=_vault_rows(), built_at=TS)
    assert "可以进论文的：3 页" in page
    assert "真测出来但还不能引用的：5 页" in page
    assert "已作废／被取代的：2 页" in page
    assert "库里一共 14 页" in page
    assert "不要相加当成实力" in page
    assert "可以进论文的：8" not in page, "frozen and provisional must never be added together"


def test_a_project_link_is_relative_not_an_absolute_windows_path(tmp_path):
    workbench = tmp_path / ".workbench"
    workspace = tmp_path / "projects" / "petct"
    workspace.mkdir(parents=True)
    project = _project(home_path=str(workspace / "PROJECT-HOME.md"))
    result = write_home_pages(projects=[project], built_at=TS, workbench_dir=workbench)
    page = (workbench / "RESEARCH-HOME.md").read_text(encoding="utf-8")
    assert "../projects/petct/PROJECT-HOME.md" in page
    assert "C:\\" not in page and str(tmp_path) not in page
    assert len(result["written"]) == 2


def test_a_project_with_no_materialised_workspace_gets_no_page(tmp_path):
    project = _project(home_path=str(tmp_path / "absent" / "PROJECT-HOME.md"))
    result = write_home_pages(projects=[project], built_at=TS,
                             workbench_dir=tmp_path / ".workbench")
    assert not any("absent" in p for p in result["written"])


# -------------------------------------------------------------- decisions and the two axes

def test_a_decision_owed_to_the_director_shows_its_reason_and_its_material():
    decision = TaskRow(
        task_id="petct:decision:D-1", project="petct", title="预注册读数表",
        work_state="needs_decision", source_status="MUST_FREEZE_BEFORE_THE_NUMBER_IS_SEEN",
        why_now="先看到数再写读数表就是事后合理化", next_action="director-review/x.md",
    )
    for page in (render_project_home(_project(), tasks=[decision], built_at=TS),
                 render_research_home([_project()], tasks=[decision], built_at=TS)):
        assert "预注册读数表" in page
        assert "事后合理化" in page, "the director needs the reason, not just the title"
        assert "director-review/x.md" in page
        assert "MUST_FREEZE_BEFORE_THE_NUMBER_IS_SEEN" in page, "keep the project's own word"


def test_the_task_table_shows_work_and_evidence_side_by_side():
    """A finished task carrying the weakest evidence must be legible as exactly that."""
    task = TaskRow(task_id="petct:T-1", project="petct", title="写完了但没证据",
                   work_state="done", evidence_state="proposed", source_status="DONE")
    page = render_project_home(_project(), tasks=[task], built_at=TS)
    assert "| 写完了但没证据 | 做完了 | 只是提议，还没跑 | `DONE` |" in page


def test_an_empty_project_says_so_rather_than_rendering_blank_sections():
    page = render_project_home(_project(counts={}), built_at=TS)
    assert "没有立刻可动的任务" in page
    assert "没有待你拍板的事" in page
    assert "还没有机器可读的任务账本" in page


def test_the_home_page_never_presents_a_spec_only_mode_as_runnable():
    caps = [{"mode": "new_direction", "one_button": True},
            {"mode": "tree_explore", "one_button": False}]
    page = render_research_home([_project()], capabilities=caps, built_at=TS)
    assert "1 个（共 2 个有定义）" in page
    assert "`new_direction`" in page
    assert "不要当成能跑的说" in page


# ------------------------------------------------------------------------------------- CLI

@pytest.fixture()
def fixture_world(tmp_path, monkeypatch):
    """A miniature machine + vault, so the CLI never reads the director's real data."""
    monkeypatch.delenv("RAT_WORKBENCH_ROOT", raising=False)
    vault = tmp_path / "vault"
    (vault / "02-wiki" / "results").mkdir(parents=True)
    (vault / "02-wiki" / "results" / "r1.md").write_text(
        "---\ntype: result\nstatus: active\nresult-status: frozen\n"
        "can-cite-thesis: true\ntitle: 冻结的结果\n---\n\n# 冻结的结果\n\nclDice 相关内容\n",
        encoding="utf-8")
    projects = tmp_path / "projects"
    (projects / "petct" / "records").mkdir(parents=True)
    (projects / "petct" / "CANONICAL-PROJECT.md").write_text(
        "# 契约\n\n## Frozen paper question\n\nM0 是否承载意图？\n\n"
        "## Truth boundary\n\n- 0 篇可发表结果\n", encoding="utf-8")
    (projects / "petct" / "records" / "n-task-ledger.json").write_text(json.dumps({
        "tasks": [{"id": "N04", "name": "signed scribble episodes",
                   "status": "UNBLOCKED_PENDING_RERUN", "evidence": "e.json",
                   "facts": {"cases": 597}}],
        "pending_director_decisions": [
            {"id": "D-1", "title": "预注册读数表", "status": "MUST_FREEZE_BEFORE_THE_NUMBER_IS_SEEN",
             "record": "director-review/x.md", "why_now": "否则是事后合理化"}],
    }, ensure_ascii=False), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    return {
        "argv": ["--workbench-root", str(tmp_path / ".workbench"),
                 "--projects-dir", str(projects), "--runs-dir", str(runs),
                 "--vault", str(vault), "--ts", TS],
        "root": tmp_path,
    }


def _run(fixture_world, verb: str, *extra: str) -> None:
    main([verb, *extra, *fixture_world["argv"]])


def test_reindex_then_read_the_whole_way_round(fixture_world, capsys):
    _run(fixture_world, "reindex")
    payload = json.loads(capsys.readouterr().out)
    assert payload["rebuilt"] is True
    assert payload["meta"]["counts"]["projects"] == 1
    assert payload["meta"]["counts"]["tasks"] == 2, "one task plus one pending decision"

    _run(fixture_world, "home")
    home = capsys.readouterr().out
    assert "预注册读数表" in home and "可以进论文的：1 页" in home

    _run(fixture_world, "status", "--json")
    status = json.loads(capsys.readouterr().out)
    assert status["projects"][0]["question"] == "M0 是否承载意图？"

    _run(fixture_world, "next", "--json")
    nxt = json.loads(capsys.readouterr().out)
    assert [t["title"] for t in nxt["ready"]] == ["signed scribble episodes"]
    assert [t["title"] for t in nxt["needs_decision"]] == ["预注册读数表"]

    _run(fixture_world, "search", "clDice", "--json")
    hits = json.loads(capsys.readouterr().out)["hits"]
    assert [h["artifact_id"] for h in hits] == ["vault:results/r1"]

    _run(fixture_world, "open", "vault:results/r1", "--json")
    opened = json.loads(capsys.readouterr().out)
    assert opened["evidence_state"] == "frozen"
    assert Path(opened["path"]).is_file()


def test_the_projection_is_provably_disposable(fixture_world, capsys):
    _run(fixture_world, "reindex")
    capsys.readouterr()
    _run(fixture_world, "destroy")
    assert "完整恢复" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        _run(fixture_world, "status")
    assert "reindex" in capsys.readouterr().err
    _run(fixture_world, "reindex")
    assert json.loads(capsys.readouterr().out)["meta"]["counts"]["tasks"] == 2


def test_home_can_render_without_an_index_at_all(fixture_world, capsys):
    _run(fixture_world, "home", "--fresh")
    assert "研究首页" in capsys.readouterr().out


def test_an_unknown_project_or_artifact_fails_with_a_useful_message(fixture_world, capsys):
    _run(fixture_world, "reindex")
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _run(fixture_world, "status", "--project", "nope")
    assert "petct" in capsys.readouterr().out, "list what does exist"
    with pytest.raises(SystemExit):
        _run(fixture_world, "open", "vault:results/absent")
    assert "索引里没有" in capsys.readouterr().out
