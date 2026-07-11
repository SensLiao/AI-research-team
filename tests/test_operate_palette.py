"""Operate palette tests (W5) — the director-facing CLI surface wrapping the workspace / lifecycle /
resource tools: dashboard / index / set-active, the GUARDED lifecycle (archive / restore / soft-delete /
purge), and the resource pool view + scoping binds. Asserts the pool view NEVER emits a secret and the
binds validate against the real pool. The vault is never touched by any palette command.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import cli
from research_agent_teams.tools import projects as pj
from research_agent_teams.tools import resources as rp
from research_agent_teams.tools.runstore import create_run

TS = "2026-06-16T00:00:00Z"
REGISTRY_MD = """# Registry
| project-slug | title | status |
|---|---|---|
| p1 | Demo | active |
"""


def _vault(tmp_path) -> Path:
    v = tmp_path / "vault"
    (v / "05-registry").mkdir(parents=True)
    (v / "05-registry" / "project-registry.md").write_text(REGISTRY_MD, encoding="utf-8")
    return v


def _run_cli(argv):
    try:
        cli.main(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


# --------------------------------------------------------------- resources.py new helpers (unit)

def test_pool_overview_emits_no_secret():
    pool = rp.pool_overview()
    blob = json.dumps(pool)
    assert "RAT_" not in blob and "secret_ref" not in blob          # never a credential name
    ids = {r["resource_id"] for r in pool}
    assert {"server.honor.gpu", "api.semantic_scholar"} <= ids
    gpu = next(r for r in pool if r["resource_id"] == "server.honor.gpu")
    assert "query_status" in gpu["capabilities"]


def test_pool_overview_scope_filter():
    personal = {r["resource_id"] for r in rp.pool_overview(scope="personal")}
    assert "connector.notion" in personal and "server.honor.gpu" not in personal


def test_add_binding_validates_and_appends(tmp_path):
    proot = str(tmp_path / "projects")
    b = rp.add_binding(proot, "p1", alias="papers", resource_ref="api.semantic_scholar",
                       capabilities=["paper_search"], stages=["DISCOVER"])
    assert b["alias"] == "papers" and b["requires_human_approval"] is False
    assert rp.binding_for(rp.load_bindings(proot, "p1"), "papers")["resource_ref"] == "api.semantic_scholar"


def test_add_binding_rejects_unknown_resource(tmp_path):
    with pytest.raises(ValueError, match="unknown resource_ref"):
        rp.add_binding(str(tmp_path / "projects"), "p1", alias="x", resource_ref="nope.nope",
                       capabilities=["paper_search"])


def test_add_binding_rejects_capability_not_provided(tmp_path):
    with pytest.raises(ValueError, match="does not provide"):
        rp.add_binding(str(tmp_path / "projects"), "p1", alias="x", resource_ref="api.semantic_scholar",
                       capabilities=["submit_job"])                 # S2 provides no submit_job


def test_add_binding_rejects_duplicate_alias(tmp_path):
    proot = str(tmp_path / "projects")
    rp.add_binding(proot, "p1", alias="dup", resource_ref="tool.exa", capabilities=["web_search"])
    with pytest.raises(ValueError, match="already bound"):
        rp.add_binding(proot, "p1", alias="dup", resource_ref="tool.exa", capabilities=["web_search"])


# --------------------------------------------------------------- CLI: resources

def test_cli_resources_list_no_secret(capsys):
    code = _run_cli(["resources"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and "RAT_" not in json.dumps(out)
    assert any(r["resource_id"] == "server.honor.gpu" for r in out["resources"])


def test_cli_resource_bind_then_shows_bound(tmp_path, capsys):
    proot = str(tmp_path / "projects")
    code = _run_cli(["resource-bind", "--projects-dir", proot, "--project", "p1",
                     "--alias", "papers", "--resource", "api.semantic_scholar",
                     "--capabilities", "paper_search,citation_existence", "--stages", "DISCOVER"])
    assert code == 0 and json.loads(capsys.readouterr().out)["binding"]["alias"] == "papers"
    code2 = _run_cli(["resources", "--projects-dir", proot, "--project", "p1"])
    out2 = json.loads(capsys.readouterr().out)
    s2 = next(r for r in out2["resources"] if r["resource_id"] == "api.semantic_scholar")
    assert code2 == 0 and s2["bound_as"] == "papers"


def test_cli_resource_bind_rejects_bad_capability(tmp_path, capsys):
    code = _run_cli(["resource-bind", "--projects-dir", str(tmp_path / "projects"), "--project", "p1",
                     "--alias", "x", "--resource", "api.semantic_scholar", "--capabilities", "submit_job"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "does not provide" in out["error"]


# --------------------------------------------------------------- CLI: lifecycle (guarded)

def test_cli_archive_restore_roundtrip(tmp_path, capsys):
    proot = str(tmp_path / "projects")
    pj.ensure_workspace(proot, "p1")
    assert _run_cli(["project-archive", "--projects-dir", proot, "--project", "p1"]) == 0
    assert json.loads(capsys.readouterr().out)["lifecycle_status"] == "archived"
    assert _run_cli(["project-restore", "--projects-dir", proot, "--project", "p1",
                     "--workspace-root", str(tmp_path / "ws")]) == 0
    assert json.loads(capsys.readouterr().out)["lifecycle_status"] == "active"


def test_cli_purge_refuses_when_not_hidden(tmp_path, capsys):
    proot = str(tmp_path / "projects")
    pj.ensure_workspace(proot, "p1")
    code = _run_cli(["project-purge", "--projects-dir", proot, "--project", "p1", "--confirm", "p1",
                     "--runs-dir", str(tmp_path / "runs"), "--workspace-root", str(tmp_path / "ws")])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "archive or soft_delete it first" in out["error"]


def test_cli_soft_delete_then_purge_keeps_vault(tmp_path, capsys):
    proot, runs, wsr = str(tmp_path / "projects"), str(tmp_path / "runs"), str(tmp_path / "ws")
    vault = _vault(tmp_path)
    pj.ensure_workspace(proot, "p1")
    assert _run_cli(["project-soft-delete", "--projects-dir", proot, "--project", "p1",
                     "--workspace-root", wsr]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "soft_deleted"
    code = _run_cli(["project-purge", "--projects-dir", proot, "--project", "p1", "--confirm", "p1",
                     "--runs-dir", runs, "--vault", str(vault), "--workspace-root", wsr])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["lifecycle_status"] == "purged"
    assert not (Path(proot) / "p1").exists()
    assert (vault / "05-registry" / "project-registry.md").is_file()       # vault untouched


# --------------------------------------------------------------- CLI: workspace

def test_cli_dashboard_index_set_active(tmp_path, capsys):
    proot, runs = str(tmp_path / "projects"), str(tmp_path / "runs")
    vault = _vault(tmp_path)
    create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="p1")
    assert _run_cli(["dashboard", "--projects-dir", proot, "--runs-dir", runs, "--vault", str(vault),
                     "--project", "p1"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["project"] == "p1" and d["current_stage"] == "DISCOVER"
    assert _run_cli(["index", "--projects-dir", proot, "--runs-dir", runs, "--vault", str(vault)]) == 0
    assert any(r["project"] == "p1" for r in json.loads(capsys.readouterr().out)["projects"])
    assert _run_cli(["set-active", "--project", "p1", "--workspace-root", str(tmp_path / "ws")]) == 0
    assert json.loads(capsys.readouterr().out)["active_project"] == "p1"
