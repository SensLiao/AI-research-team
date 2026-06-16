"""Project lifecycle tests — archive/restore, reversible soft_delete (revokes leases, deletes nothing),
and guarded hard_purge (refuses while hidden-not-set / active run / active lease / promoted claims;
never touches the vault; purged is terminal)."""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.tools import lifecycle as lc
from research_agent_teams.tools import projects as pj
from research_agent_teams.tools import runstore as rst
from research_agent_teams.tools.lease_manager import LeaseManager

TS = "2026-06-16T00:00:00Z"


def test_archive_and_restore(tmp_path):
    proot = str(tmp_path / "projects")
    pj.ensure_workspace(proot, "p1")
    lc.archive("p1", TS, projects_root=proot)
    assert lc.read_lifecycle(proot, "p1")["status"] == "archived"
    lc.restore("p1", TS, projects_root=proot)
    assert lc.read_lifecycle(proot, "p1")["status"] == "active"


def test_transition_rejects_bad_state(tmp_path):
    with pytest.raises(ValueError, match="invalid lifecycle state"):
        lc.transition("p1", "bogus", TS, projects_root=str(tmp_path / "projects"))


def test_soft_delete_revokes_leases_and_is_reversible(tmp_path):
    proot = str(tmp_path / "projects")
    wsr = str(tmp_path / "ws")
    pj.ensure_workspace(proot, "p1")
    LeaseManager(wsr).acquire(resource_ref="server.honor.gpu", capability="query_status",
                              project="p1", run_id="r1", ttl_seconds=3600)
    res = lc.soft_delete("p1", TS, projects_root=proot, workspace_root_path=wsr)
    assert res["status"] == "soft_deleted" and len(res["leases_revoked"]) == 1
    assert LeaseManager(wsr).active_leases("r1") == []          # lease revoked
    from pathlib import Path
    assert (Path(proot) / "p1").exists()                        # nothing deleted (reversible)
    lc.restore("p1", TS, projects_root=proot, workspace_root_path=wsr)
    assert lc.read_lifecycle(proot, "p1")["status"] == "active"


def test_hard_purge_requires_hidden_first(tmp_path):
    proot = str(tmp_path / "projects")
    pj.ensure_workspace(proot, "p1")
    with pytest.raises(ValueError, match="archive or soft_delete it first"):
        lc.hard_purge("p1", TS, confirm="p1", projects_root=proot, runs_dir=str(tmp_path / "runs"),
                      vault_root=None, workspace_root_path=str(tmp_path / "ws"))


def test_hard_purge_refuses_active_run(tmp_path):
    proot = str(tmp_path / "projects")
    runs = str(tmp_path / "runs")
    pj.ensure_workspace(proot, "p1")
    rst.create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="p1")  # status running
    lc.archive("p1", TS, projects_root=proot)
    with pytest.raises(ValueError, match="active .running. runs"):
        lc.hard_purge("p1", TS, confirm="p1", projects_root=proot, runs_dir=runs, vault_root=None,
                      workspace_root_path=str(tmp_path / "ws"))


def test_hard_purge_refuses_promoted_claims(tmp_path):
    proot = str(tmp_path / "projects")
    vault = tmp_path / "vault"
    (vault / "02-wiki" / "results").mkdir(parents=True)
    (vault / "02-wiki" / "results" / "x.md").write_text('---\nproject: "p1"\n---\nbody', encoding="utf-8")
    pj.ensure_workspace(proot, "p1")
    lc.soft_delete("p1", TS, projects_root=proot, workspace_root_path=str(tmp_path / "ws"))
    with pytest.raises(ValueError, match="PROMOTED knowledge"):
        lc.hard_purge("p1", TS, confirm="p1", projects_root=proot, runs_dir=str(tmp_path / "runs"),
                      vault_root=str(vault), workspace_root_path=str(tmp_path / "ws"))


def test_hard_purge_confirm_mismatch(tmp_path):
    proot = str(tmp_path / "projects")
    pj.ensure_workspace(proot, "p1")
    lc.archive("p1", TS, projects_root=proot)
    with pytest.raises(ValueError, match="confirmation mismatch"):
        lc.hard_purge("p1", TS, confirm="WRONG", projects_root=proot, runs_dir=str(tmp_path / "runs"),
                      vault_root=None, workspace_root_path=str(tmp_path / "ws"))


def test_hard_purge_happy_path_removes_scratch_not_vault(tmp_path):
    proot = str(tmp_path / "projects")
    runs = str(tmp_path / "runs")
    vault = tmp_path / "vault"
    wsr = str(tmp_path / "ws")
    (vault / "05-registry").mkdir(parents=True)
    (vault / "05-registry" / "project-registry.md").write_text("# reg\n", encoding="utf-8")
    pj.ensure_workspace(proot, "p1")
    rst.create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="p1")
    # mark the run done so it is not 'active'
    rd = rst.find_run_dir(runs, "r1")
    m = rst.read_manifest(rd)
    m["status"] = "done"
    rst.atomic_write_text(rd / "manifest.yaml", yaml.safe_dump(m, sort_keys=False))
    lc.soft_delete("p1", TS, projects_root=proot, workspace_root_path=wsr)
    res = lc.hard_purge("p1", TS, confirm="p1", projects_root=proot, runs_dir=runs,
                        vault_root=str(vault), workspace_root_path=wsr)
    assert res["lifecycle_status"] == "purged"
    from pathlib import Path
    assert not (Path(proot) / "p1").exists() and not (Path(runs) / "p1").exists()
    assert (vault / "05-registry" / "project-registry.md").is_file()        # vault untouched
    assert lc.is_purged("p1", wsr) is True
    with pytest.raises(ValueError, match="purged"):                          # terminal
        lc.restore("p1", TS, projects_root=proot, workspace_root_path=wsr)
