"""Workspace control-plane tests — workspace_state pointer, derived project index/dashboard (mirrors
the vault registry, read-only), current-stage derivation, and blocker detection."""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.tools import workspace as ws
from research_agent_teams.tools.runstore import create_run, find_run_dir, record_gate

TS = "2026-06-16T00:00:00Z"
REGISTRY_MD = """# Registry
| project-slug | title | status |
|---|---|---|
| iac-cbct-seg | IAC seg | active |
| parked-proj | Parked | parked |
"""


@pytest.fixture()
def env(tmp_path):
    vault = tmp_path / "vault"
    (vault / "05-registry").mkdir(parents=True)
    (vault / "05-registry" / "project-registry.md").write_text(REGISTRY_MD, encoding="utf-8")
    (tmp_path / "projects").mkdir()
    return {"vault": str(vault), "runs": str(tmp_path / "runs"), "projects": str(tmp_path / "projects")}


def _bindings(projects, slug, aliases):
    from pathlib import Path
    d = Path(projects) / slug
    d.mkdir(parents=True, exist_ok=True)
    binds = {"project": slug,
             "bindings": [{"alias": a, "resource_ref": "x", "allowed_capabilities": ["c"]} for a in aliases]}
    (d / "resource_bindings.yaml").write_text(yaml.safe_dump(binds), encoding="utf-8")


def test_workspace_state_roundtrip(tmp_path):
    wsr = str(tmp_path / "ws")
    assert ws.read_workspace_state(wsr)["active_project"] is None
    ws.set_active_project("iac-cbct-seg", TS, ws_root=wsr)
    st = ws.read_workspace_state(wsr)
    assert st["active_project"] == "iac-cbct-seg" and st["last_touched"] == TS


def test_project_runs_newest_first_and_stage(env):
    create_run(env["runs"], "r-old", "new_direction", "DISCOVER", "2026-06-15T00:00:00Z",
               project="iac-cbct-seg")
    create_run(env["runs"], "r-new", "full_rigor_minimal", "DESIGN", "2026-06-16T00:00:00Z",
               project="iac-cbct-seg")
    runs = ws.project_runs("iac-cbct-seg", env["runs"])
    assert [r["run_id"] for r in runs] == ["r-new", "r-old"]
    assert runs[0]["stage"] == "DESIGN"


def test_dashboard_gpu_blocker_toggles_with_binding(env):
    create_run(env["runs"], "r1", "full_rigor_minimal", "EXECUTE", TS, project="iac-cbct-seg")
    d = ws.dashboard("iac-cbct-seg", projects_root=env["projects"], runs_dir=env["runs"],
                     vault_root=env["vault"])
    assert d["registered"] is True and d["current_stage"] == "EXECUTE"
    assert any(b["type"] == "no_gpu_binding" for b in d["blockers"])
    _bindings(env["projects"], "iac-cbct-seg", ["primary_gpu"])
    d2 = ws.dashboard("iac-cbct-seg", projects_root=env["projects"], runs_dir=env["runs"],
                      vault_root=env["vault"])
    assert not any(b["type"] == "no_gpu_binding" for b in d2["blockers"])
    assert "primary_gpu" in d2["resources"]


def test_dashboard_rejected_run_blocker(env):
    create_run(env["runs"], "r1", "venue_readiness", "VERIFY", TS, project="iac-cbct-seg")
    record_gate(find_run_dir(env["runs"], "r1"), "VERIFY", "reject", TS, reason="not ready")
    d = ws.dashboard("iac-cbct-seg", projects_root=env["projects"], runs_dir=env["runs"],
                     vault_root=env["vault"])
    assert any(b["type"] == "run_rejected" for b in d["blockers"])


def test_project_index_hides_archived(env):
    from pathlib import Path
    create_run(env["runs"], "r1", "new_direction", "DISCOVER", TS, project="iac-cbct-seg")
    (Path(env["projects"]) / "iac-cbct-seg").mkdir(parents=True, exist_ok=True)
    (Path(env["projects"]) / "iac-cbct-seg" / "lifecycle.yaml").write_text(
        yaml.safe_dump({"project": "iac-cbct-seg", "status": "archived"}), encoding="utf-8")
    idx = ws.project_index(projects_root=env["projects"], runs_dir=env["runs"], vault_root=env["vault"])
    assert "iac-cbct-seg" not in [r["project"] for r in idx]
    idx2 = ws.project_index(projects_root=env["projects"], runs_dir=env["runs"], vault_root=env["vault"],
                            include_hidden=True)
    assert "iac-cbct-seg" in [r["project"] for r in idx2]


def test_write_project_state_snapshot(env):
    create_run(env["runs"], "r1", "new_direction", "DISCOVER", TS, project="iac-cbct-seg")
    out = ws.write_project_state("iac-cbct-seg", TS, projects_root=env["projects"], runs_dir=env["runs"],
                                 vault_root=env["vault"])
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["project"] == "iac-cbct-seg" and data["generated_at"] == TS
    assert data["current_stage"] == "DISCOVER"
