"""Tests for project-isolated RECALL (tools/recall.recall(..., project=)).

The director's #1 concern: once the vault holds >1 project, a run for project B must NOT retrieve
project A's pages. Isolation is enforced by filtering the candidate pool to pages whose `project:`
facet intersects {active_project, 'meta'}. `project=None` keeps the legacy whole-vault behaviour.
"""
from __future__ import annotations

from pathlib import Path

from research_agent_teams.tools import recall


def _mk_vault(tmp_path: Path) -> Path:
    (tmp_path / "00-system").mkdir()
    (tmp_path / "02-wiki").mkdir()
    (tmp_path / "00-system" / "index.md").write_text(
        "# Index\n- [[adapter-alpha]]\n- [[adapter-beta]]\n- [[adapter-shared]]\n- [[adapter-orphan]]\n",
        encoding="utf-8",
    )

    def _page(slug: str, project_line: str, body: str) -> None:
        (tmp_path / "02-wiki" / f"{slug}.md").write_text(
            f"---\ntitle: {slug}\ntype: method\nstatus: active\nconfidence: medium\n"
            f"created: 2026-06-16\nupdated: 2026-06-16\n{project_line}---\n\n# {slug}\n\n{body}\n",
            encoding="utf-8",
        )

    _page("adapter-alpha", "project: proj-a\n", "an adapter method for proj a")
    _page("adapter-beta", "project: proj-b\n", "an adapter method for proj b")
    _page("adapter-shared", "project: meta\n", "a shared adapter concept usable by all")
    _page("adapter-orphan", "", "an adapter with no project facet at all")
    return tmp_path


def test_recall_scopes_to_project_plus_meta(tmp_path):
    v = _mk_vault(tmp_path)
    recall.clear_page_cache()
    note = recall.recall("adapter", vault_root=v, project="proj-a")
    slugs = {c["slug"] for c in note["citations"]}
    assert "adapter-alpha" in slugs            # the active project's page
    assert "adapter-shared" in slugs           # meta is visible to all projects
    assert "adapter-beta" not in slugs         # the OTHER project is isolated out
    assert "adapter-orphan" not in slugs       # an unscoped page is excluded under a scoped recall


def test_recall_other_project_isolated(tmp_path):
    v = _mk_vault(tmp_path)
    recall.clear_page_cache()
    note = recall.recall("adapter", vault_root=v, project="proj-b")
    slugs = {c["slug"] for c in note["citations"]}
    assert slugs <= {"adapter-beta", "adapter-shared"}
    assert "adapter-alpha" not in slugs


def test_recall_unscoped_sees_all(tmp_path):
    v = _mk_vault(tmp_path)
    recall.clear_page_cache()
    note = recall.recall("adapter", vault_root=v)          # project=None → legacy whole-vault
    slugs = {c["slug"] for c in note["citations"]}
    assert {"adapter-alpha", "adapter-beta", "adapter-shared", "adapter-orphan"} <= slugs


def test_page_projects_parses_all_forms():
    assert recall._page_projects("---\nproject: a\n---\n") == frozenset({"a"})
    assert recall._page_projects("---\nproject: [a, b]\n---\n") == frozenset({"a", "b"})
    assert recall._page_projects("---\nproject:\n- a\n- meta\nstatus: active\n---\n") == frozenset({"a", "meta"})
    assert recall._page_projects("---\ntitle: x\n---\n") == frozenset()
