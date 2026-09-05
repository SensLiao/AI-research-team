"""Project dimension tests — registry validation, per-project workspaces, grouped run layout,
one-command deletion, promote-gate project discipline, and the execute layer's remote grouping.

The contract under test (director, 2026-06-12):
  - every NEW machine run belongs to ONE registered research project (runs/<project>/<run_id>/)
  - each project owns a durable workspace projects/<project>/ (results/scripts/figures/notes)
  - deleting a project is ONE deliberate command and removes ONLY machine-side scratch — the vault
    (promoted knowledge + the registry itself) is never touched
  - promoted pages must carry a REGISTERED project slug (no more 'unknown'-project knowledge)
  - legacy flat runs/<run_id>/ stay readable (find_run_dir / resume / status keep working)
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools import projects as pj
from research_agent_teams.tools.runstore import create_run, find_run_dir, run_dir_for

TS = "2026-06-12T00:00:00Z"

REGISTRY_MD = """---
type: registry
registry-of: projects
---

# Project Registry

Some prose around the table (the parser must not trip on it).

## Active projects

| project-slug | title | phase | supervisor | domain | status | started | hot.md | brief |
|---|---|---|---|---|---|---|---|---|
| iac-cbct-seg | IAC segmentation | phd-chapter | (TBD) | medical-imaging | active | 2026-06 | hot.md | [[b]] |
| nlp-side-quest | A second project | independent | (TBD) | nlp | parked | 2026-05 | hot.md | [[b2]] |
| old-thing | Finished work | phd-chapter | (TBD) | cv | completed | 2025-01 | hot.md | [[b3]] |

## Schema

| field | description |
|---|---|
| `project-slug` | lowercase-kebab |
"""


@pytest.fixture()
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "05-registry").mkdir(parents=True)
    (v / "05-registry" / "project-registry.md").write_text(REGISTRY_MD, encoding="utf-8")
    return v


# --------------------------------------------------------------------------- registry parsing

def test_parse_registry_reads_rows_and_status(vault):
    reg = pj.load_registered_projects(vault)
    assert set(reg) == {"iac-cbct-seg", "nlp-side-quest", "old-thing"}
    assert reg["iac-cbct-seg"]["status"] == "active"
    assert reg["nlp-side-quest"]["status"] == "parked"
    assert reg["old-thing"]["status"] == "completed"


def test_parse_registry_skips_schema_table_rows(vault):
    # the Schema section's `field` rows must never be parsed as projects
    reg = pj.load_registered_projects(vault)
    assert "field" not in reg and "project-slug" not in reg


def test_load_registered_projects_empty_when_no_registry(tmp_path):
    assert pj.load_registered_projects(tmp_path / "bare-vault") == {}
    assert pj.load_registered_projects(None) == {}


# --------------------------------------------------------------------------- require_project

def test_require_project_accepts_registered_active_and_parked(vault):
    assert pj.require_project("iac-cbct-seg", vault)["registered"] is True
    assert pj.require_project("nlp-side-quest", vault)["status"] == "parked"


def test_require_project_rejects_unregistered(vault):
    with pytest.raises(ValueError, match="not registered"):
        pj.require_project("never-heard-of-it", vault)


def test_require_project_rejects_closed(vault):
    with pytest.raises(ValueError, match="completed"):
        pj.require_project("old-thing", vault)


@pytest.mark.parametrize("bad", ["", "Has-Caps", "under_score", "a/b", "../etc", "a..b", "-lead", "trail-"])
def test_require_project_rejects_bad_format(bad, vault):
    with pytest.raises(ValueError, match="invalid project slug"):
        pj.require_project(bad, vault)


def test_require_project_format_only_without_registry(tmp_path):
    res = pj.require_project("any-kebab-slug", tmp_path / "bare")
    assert res["registered"] is False                       # format-only fallback for bare test trees


# --------------------------------------------------------------------------- workspace

def test_ensure_workspace_creates_and_is_idempotent(tmp_path):
    root = tmp_path / "projects"
    first = pj.ensure_workspace(root, "iac-cbct-seg")
    assert first["created"] is True
    for sub in ("results", "scripts", "figures", "notes"):
        assert (root / "iac-cbct-seg" / sub).is_dir()
    assert (root / "iac-cbct-seg" / "README.md").is_file()
    again = pj.ensure_workspace(root, "iac-cbct-seg")
    assert again["created"] is False                        # idempotent


def test_ensure_workspace_rejects_bad_slug(tmp_path):
    with pytest.raises(ValueError):
        pj.ensure_workspace(tmp_path, "../escape")


# --------------------------------------------------------------------------- run layout

def test_run_dir_for_layouts(tmp_path):
    assert run_dir_for(tmp_path, "r1") == tmp_path / "r1"
    assert run_dir_for(tmp_path, "r1", "proj-a") == tmp_path / "proj-a" / "r1"


def test_create_run_project_grouped_and_manifest_field(tmp_path):
    runs = tmp_path / "runs"
    m = create_run(runs, "r-grouped", "new_direction", "DISCOVER", TS, project="iac-cbct-seg")
    assert m["project"] == "iac-cbct-seg"
    assert (runs / "iac-cbct-seg" / "r-grouped" / "manifest.yaml").is_file()


def test_create_run_flat_legacy_still_works(tmp_path):
    runs = tmp_path / "runs"
    m = create_run(runs, "r-flat", "new_direction", "DISCOVER", TS)
    assert m["project"] is None
    assert (runs / "r-flat" / "manifest.yaml").is_file()


def test_find_run_dir_both_layouts(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "r-flat", "new_direction", "DISCOVER", TS)
    create_run(runs, "r-grouped", "new_direction", "DISCOVER", TS, project="proj-a")
    assert find_run_dir(runs, "r-flat") == runs / "r-flat"
    assert find_run_dir(runs, "r-grouped") == runs / "proj-a" / "r-grouped"
    with pytest.raises(FileNotFoundError):
        find_run_dir(runs, "no-such-run")


def test_find_run_dir_ambiguous_across_projects(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "dup", "new_direction", "DISCOVER", TS, project="proj-a")
    create_run(runs, "dup", "new_direction", "DISCOVER", TS, project="proj-b")
    with pytest.raises(RuntimeError, match="ambiguous"):
        find_run_dir(runs, "dup")


def test_router_rejects_bad_project_slug():
    from research_agent_teams.orchestrator.router import resolve_task
    with pytest.raises(ValueError, match="invalid project slug"):
        resolve_task("req", "new_direction", "r1", TS, project="NOT KEBAB")


def test_task_frame_carries_project():
    from research_agent_teams.orchestrator.router import resolve_task
    tf = resolve_task("req", "new_direction", "r1", TS, project="iac-cbct-seg")
    assert tf["payload"]["project"] == "iac-cbct-seg"
    tf_legacy = resolve_task("req", "new_direction", "r2", TS)
    assert "project" not in tf_legacy["payload"]            # legacy frames unchanged


# --------------------------------------------------------------------------- operate spine + CLI

def test_spine_begin_with_project_groups_the_run(tmp_path):
    from research_agent_teams.operate import spine
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-p1", "find a direction", "new_direction", TS, project="proj-a")
    assert plan["project"] == "proj-a"
    assert (runs / "proj-a" / "op-p1" / "task_frame.artifact.json").is_file()
    # status locates the grouped run through the same path the CLI uses
    st = spine.status(str(runs / "proj-a" / "op-p1"))
    assert st["run_id"] == "op-p1"


def test_operate_cli_project_lifecycle(tmp_path, capsys, vault):
    from research_agent_teams.operate import cli
    runs, projects = str(tmp_path / "runs"), str(tmp_path / "projects")

    # begin requires a REGISTERED project
    with pytest.raises(SystemExit):
        cli.main(["begin", "--mode", "new_direction", "--request", "x", "--run-id", "r-bad",
                  "--runs-dir", runs, "--ts", TS, "--project", "ghost-project",
                  "--vault", str(vault), "--projects-dir", projects])
    assert "not registered" in json.loads(capsys.readouterr().out)["error"]

    cli.main(["begin", "--mode", "new_direction", "--request", "x", "--run-id", "r-ok",
              "--runs-dir", runs, "--ts", TS, "--project", "iac-cbct-seg",
              "--vault", str(vault), "--projects-dir", projects])
    out = json.loads(capsys.readouterr().out)
    assert out["project"] == "iac-cbct-seg"

    # post-begin commands locate the grouped run by run-id alone
    cli.main(["status", "--run-id", "r-ok", "--runs-dir", runs, "--ts", TS])
    assert json.loads(capsys.readouterr().out)["run_id"] == "r-ok"

    # project-list sees the project (registered + workspace + 1 run)
    cli.main(["project-list", "--runs-dir", runs, "--projects-dir", projects,
              "--vault", str(vault), "--ts", TS])
    rows = {r["project"]: r for r in json.loads(capsys.readouterr().out)["projects"]}
    assert rows["iac-cbct-seg"]["runs"] == 1 and rows["iac-cbct-seg"]["workspace"] is True

    # project-delete: wrong confirmation refused; right confirmation wipes machine-side footprint
    with pytest.raises(SystemExit):
        cli.main(["project-delete", "--project", "iac-cbct-seg", "--confirm", "wrong",
                  "--runs-dir", runs, "--projects-dir", projects, "--ts", TS])
    assert "confirmation mismatch" in json.loads(capsys.readouterr().out)["error"]

    cli.main(["project-delete", "--project", "iac-cbct-seg", "--confirm", "iac-cbct-seg",
              "--runs-dir", runs, "--projects-dir", projects, "--vault", str(vault), "--ts", TS])
    res = json.loads(capsys.readouterr().out)
    assert res["runs_deleted"] == 1 and res["workspace_deleted"] is True
    assert not (tmp_path / "runs" / "iac-cbct-seg").exists()
    assert not (tmp_path / "projects" / "iac-cbct-seg").exists()
    # the vault registry survives deletion untouched
    assert (vault / "05-registry" / "project-registry.md").is_file()


# --------------------------------------------------------------------------- delete safety

def test_delete_project_requires_typed_confirmation(tmp_path):
    pj.ensure_workspace(tmp_path / "projects", "proj-a")
    with pytest.raises(ValueError, match="confirmation mismatch"):
        pj.delete_project(tmp_path / "projects", tmp_path / "runs", "proj-a", confirm="")
    assert (tmp_path / "projects" / "proj-a").exists()      # nothing deleted


def test_delete_project_never_touches_vault(tmp_path):
    # construct a hostile layout where the runs dir lives INSIDE the vault -> refuse outright
    vault = tmp_path / "vault"
    runs_inside_vault = vault / "runs"
    (runs_inside_vault / "proj-a").mkdir(parents=True)
    with pytest.raises(PermissionError, match="inside the vault"):
        pj.delete_project(tmp_path / "projects", runs_inside_vault, "proj-a",
                          confirm="proj-a", vault_root=vault)
    assert (runs_inside_vault / "proj-a").exists()


def test_delete_project_missing_dirs_is_clean(tmp_path):
    res = pj.delete_project(tmp_path / "projects", tmp_path / "runs", "proj-x",
                            confirm="proj-x", vault_root=None)
    assert res["deleted_paths"] == [] and res["runs_deleted"] == 0


# --------------------------------------------------------------------------- cross-review fixes
# (Codex adversarial review 2026-06-12 — all four P2 findings regression-locked)

def test_delete_project_refuses_flat_run_slug_collision(tmp_path):
    """Codex P2: a legacy flat RUN named exactly like a project slug must never be rmtree'd as if
    it were that project's run-group."""
    runs = tmp_path / "runs"
    create_run(runs, "proj-a", "new_direction", "DISCOVER", TS)   # flat run whose ID == slug
    with pytest.raises(ValueError, match="legacy flat RUN"):
        pj.delete_project(tmp_path / "projects", runs, "proj-a", confirm="proj-a", vault_root=None)
    assert (runs / "proj-a" / "manifest.yaml").is_file()          # untouched


def test_require_project_fails_closed_on_empty_registry(tmp_path):
    """Codex P2: a registry file that EXISTS but parses to zero rows must fail closed, not act
    like a bare vault."""
    v = tmp_path / "vault"
    (v / "05-registry").mkdir(parents=True)
    (v / "05-registry" / "project-registry.md").write_text("# emptied / malformed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fail-closed"):
        pj.require_project("any-slug", v)


def test_promote_fails_closed_on_empty_registry(tmp_path):
    """Codex P2: same fail-closed discipline at the promote gate."""
    from research_agent_teams.tools.promote import promote_to_vault
    v = tmp_path / "vault"
    (v / "05-registry").mkdir(parents=True)
    (v / "05-registry" / "project-registry.md").write_text("# emptied / malformed\n", encoding="utf-8")
    cand = {"slug": "r", "vault_type": "result", "project": "any-slug", "title": "T", "body": "b"}
    rec = promote_to_vault(cand, signals=_full_pass_signals(), human_freeze=True,
                           vault_root=v, decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert any("not a registered" in r for r in rec["reasons"])


def test_promote_gate_cli_surfaces_ambiguous_run_id(tmp_path, monkeypatch):
    """Codex P2: an ambiguous run id (same id in two project groups) must SURFACE, never silently
    fall back to a guessed flat path."""
    from research_agent_teams.tools import promote_gate
    monkeypatch.delenv("RAT_PROMOTE_AUTHORIZED", raising=False)
    runs = tmp_path / "runs"
    create_run(runs, "dup", "venue_readiness", "VERIFY", TS, project="proj-a")
    create_run(runs, "dup", "venue_readiness", "VERIFY", TS, project="proj-b")
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({"slug": "x", "vault_type": "result"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="ambiguous"):
        promote_gate.main(["--run-id", "dup", "--runs-dir", str(runs),
                           "--candidate", str(cand), "--vault", str(tmp_path / "v"), "--ts", TS])


def test_begin_validates_against_mode_default_vault(tmp_path, capsys, monkeypatch):
    """Codex P2: when --vault is absent and layout discovery fails, begin must still validate the
    project against the mode's DEFAULT_VAULT instead of silently downgrading to format-only."""
    from research_agent_teams.operate import cli
    from research_agent_teams.operate.modes import new_direction as nd
    monkeypatch.setattr(cli, "discover_vault_root", lambda: None)
    default_vault = tmp_path / "default-vault"
    (default_vault / "05-registry").mkdir(parents=True)
    (default_vault / "05-registry" / "project-registry.md").write_text(REGISTRY_MD, encoding="utf-8")
    monkeypatch.setattr(nd, "DEFAULT_VAULT", str(default_vault))
    with pytest.raises(SystemExit):
        cli.main(["begin", "--mode", "new_direction", "--request", "x", "--run-id", "r-dv",
                  "--runs-dir", str(tmp_path / "runs"), "--ts", TS, "--project", "ghost-project",
                  "--projects-dir", str(tmp_path / "projects")])
    assert "not registered" in json.loads(capsys.readouterr().out)["error"]


# --------------------------------------------------------------------------- engine end-to-end

def test_engine_run_with_project(tmp_path):
    """The FSM engine drives a project-grouped run exactly like a flat one."""
    from research_agent_teams.orchestrator import engine
    from .test_engine import _approve, _note_agent  # reuse the proven stubs

    runs = tmp_path / "runs"
    m = engine.run_task(runs, "eng-p1", "design the ablation", "design_experiment", TS,
                        _note_agent, _approve, domain_profile_ref="cv-medical-segmentation",
                        budget_override={"max_agent_hops": 10}, project="proj-a")
    assert m["status"] == "done" and m["project"] == "proj-a"
    assert (runs / "proj-a" / "eng-p1" / "manifest.yaml").is_file()


# --------------------------------------------------------------------------- promote discipline

def _full_pass_signals():
    return {"leakage_pass": True, "fairness_pass": True,
            "reviewer_approves_freeze": True, "reviewer_verdict": "APPROVE-FREEZE"}


def test_promote_rejects_unregistered_project(vault):
    from research_agent_teams.tools.promote import promote_to_vault
    cand = {"slug": "good-result", "vault_type": "result", "project": "ghost-project",
            "title": "T", "body": "b"}
    rec = promote_to_vault(cand, signals=_full_pass_signals(), human_freeze=True,
                           vault_root=vault, decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert any("not a registered" in r for r in rec["reasons"])
    assert not (vault / "02-wiki").exists()                  # nothing written


def test_promote_rejects_missing_project_when_registry_exists(vault):
    from research_agent_teams.tools.promote import promote_to_vault
    cand = {"slug": "good-result", "vault_type": "result", "title": "T", "body": "b"}  # no project
    rec = promote_to_vault(cand, signals=_full_pass_signals(), human_freeze=True,
                           vault_root=vault, decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert any("not a registered" in r for r in rec["reasons"])


def test_promote_admits_registered_project(vault):
    from research_agent_teams.tools.promote import promote_to_vault
    cand = {"slug": "good-result", "vault_type": "result", "project": "iac-cbct-seg",
            "title": "T", "body": "b"}
    rec = promote_to_vault(cand, signals=_full_pass_signals(), human_freeze=True,
                           vault_root=vault, decided_by="director", decided_at=TS)
    assert rec["admissible"] is True
    page = (vault / "02-wiki" / "results" / "good-result.md").read_text(encoding="utf-8")
    assert 'project: "iac-cbct-seg"' in page


def test_promote_without_registry_keeps_legacy_behavior(tmp_path):
    """A bare test vault (no registry) skips the project check — existing tests' contract."""
    from research_agent_teams.tools.promote import promote_to_vault
    cand = {"slug": "legacy-result", "vault_type": "result", "project": "p", "title": "T", "body": "b"}
    rec = promote_to_vault(cand, signals=_full_pass_signals(), human_freeze=True,
                           vault_root=tmp_path / "bare-vault", decided_by="director", decided_at=TS)
    assert rec["admissible"] is True


# --------------------------------------------------------------------------- execute layer

def test_jobspec_validates_project():
    from research_agent_teams.execute.job import JobSpec
    with pytest.raises(ValueError, match="unsafe project"):
        JobSpec(run_id="r1", script="train.py", project="Bad;Slug")
    assert JobSpec(run_id="r1", script="train.py", project="proj-a").project == "proj-a"


def test_remote_run_dir_groups_by_project():
    from research_agent_teams.execute.config import ServerConfig
    from research_agent_teams.execute.job import JobSpec, remote_run_dir
    cfg = ServerConfig(host="h", port=22, user="u", workdir="/data/rat", python="python3",
                       conda_env="", conda_sh="", scheduler="", results_pull_dir="runs",
                       known_hosts="", has_password=False, has_ssh_key=False)
    assert remote_run_dir(cfg, JobSpec(run_id="r1", script="t.py")) == "/data/rat/r1"
    assert remote_run_dir(cfg, JobSpec(run_id="r1", script="t.py", project="proj-a")) == "/data/rat/proj-a/r1"


def test_safe_pull_dest_groups_by_project(tmp_path):
    from research_agent_teams.execute.runner import _safe_pull_dest
    base = tmp_path / "runs"
    dest = _safe_pull_dest(str(base), "r1", None, project="proj-a")
    assert dest == (base / "proj-a" / "r1" / "pulled").resolve()
    dest_flat = _safe_pull_dest(str(base), "r1", None)
    assert dest_flat == (base / "r1" / "pulled").resolve()


# --------------------------------------------------------------------------- scope guard

def test_scope_guard_blocks_fenced_write_into_project_workspace(tmp_path):
    from research_agent_teams.tools.scope_guard import decide
    scope = {"run_root": str(tmp_path / "runs"), "run_id": "r1", "stage": "DESIGN",
             "vault_root": str(tmp_path / "vault"), "projects_root": str(tmp_path / "projects")}
    ok, reason = decide("Write", str(tmp_path / "projects" / "proj-a" / "results" / "x.json"), scope)
    assert ok is False and "operator-managed" in reason
    # the agent's own stage scope still allowed
    ok2, _ = decide("Write", str(tmp_path / "runs" / "r1" / "evidence" / "DESIGN" / "a.json"), scope)
    assert ok2 is True
