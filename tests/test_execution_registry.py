"""Execution-granularity tests (W4) — the stage / skill / bridge registries load + validate, the
manifest-grounded readiness check (ready / needs_prior / already_done / not_in_path / rejected), and
the operate run-stage / run-skill / run-bridge CLI (ready vs repair-menu exit 3). The control plane
NEVER fabricates a missing input — a not-ready target returns repair ACTIONS, never an empty artifact.
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.operate import cli, spine
from research_agent_teams.tools import execution_registry as exreg
from research_agent_teams.tools.runstore import (
    STAGES,
    checkpoint_stage,
    create_run,
    find_run_dir,
    mark_gate_pending,
    record_gate,
)

TS = "2026-06-16T00:00:00Z"


@pytest.fixture()
def design_run(tmp_path):
    """A fresh full_rigor_minimal run whose pending stage is DESIGN (entry=DESIGN, nothing committed)."""
    runs = str(tmp_path / "runs")
    create_run(runs, "r1", "full_rigor_minimal", "DESIGN", TS, project="p1")
    return runs, find_run_dir(runs, "r1")


# ----------------------------------------------------------------- registries load + validate

def test_stage_registry_has_the_seven_real_stages():
    assert list(exreg.load_stages()) == STAGES                     # all 7, FSM order, no extras


def test_skill_registry_maps_every_skill_to_a_real_stage():
    skills = exreg.load_skills()
    assert skills                                                  # non-empty
    assert all(s["stage"] in STAGES for s in skills.values())
    assert skills["experiment_matrix_builder"]["stage"] == "DESIGN"
    assert skills["server_query"]["stage"] == "EXECUTE"


def test_bridge_registry_endpoints_are_real_stages():
    bridges = exreg.load_bridges()
    assert len(bridges) == 6                                       # 6 transitions across 7 stages
    for b in bridges.values():
        assert b["from_stage"] in STAGES and b["to_stage"] in STAGES


# ----------------------------------------------------------------- stage readiness (manifest-grounded)

def test_stage_readiness_ready_future_and_not_in_path(design_run):
    _, rd = design_run
    assert exreg.stage_readiness(rd, "DESIGN")["status"] == "ready"
    ex = exreg.stage_readiness(rd, "EXECUTE")
    assert ex["ready"] is False and ex["status"] == "needs_prior" and ex["missing"] == ["DESIGN"]
    assert exreg.stage_readiness(rd, "DISCOVER")["status"] == "not_in_path"   # behind DESIGN, never run


def test_stage_readiness_after_commit(design_run):
    _, rd = design_run
    checkpoint_stage(rd, "DESIGN", [], "k-design", TS)             # commit DESIGN -> next EXECUTE
    assert exreg.stage_readiness(rd, "EXECUTE")["status"] == "ready"
    assert exreg.stage_readiness(rd, "DESIGN")["status"] == "already_done"
    an = exreg.stage_readiness(rd, "ANALYZE")
    assert an["status"] == "needs_prior" and an["missing"] == ["EXECUTE"]


def test_stage_readiness_uses_frozen_sparse_mode_path(tmp_path):
    runs = str(tmp_path / "runs")
    plan = spine.begin(runs, "sparse-ready", "rank directions", "new_direction", TS, project="p1")
    rd = plan["run_dir"]
    checkpoint_stage(rd, "DISCOVER", [], "k-discover", TS,
                     stage_path=["DISCOVER", "IDEATE", "REPORT"])

    report = exreg.stage_readiness(rd, "REPORT")

    assert report["ready"] is False
    assert report["status"] == "needs_prior"
    assert report["missing"] == ["IDEATE"]


def test_stage_readiness_rejected_is_terminal(design_run):
    _, rd = design_run
    record_gate(rd, "DESIGN", "reject", TS, reason="veto")
    r = exreg.stage_readiness(rd, "DESIGN")
    assert r["ready"] is False and r["status"] == "rejected"


def test_stage_readiness_refuses_next_stage_while_director_gate_is_pending(design_run):
    _, rd = design_run
    checkpoint_stage(rd, "DESIGN", [], "k-design", TS)
    mark_gate_pending(rd, "DESIGN", TS, "EXECUTE")

    r = exreg.stage_readiness(rd, "EXECUTE")

    assert r["ready"] is False
    assert r["status"] == "awaiting_director"


def test_stage_readiness_unknown_stage_raises(design_run):
    _, rd = design_run
    with pytest.raises(ValueError, match="unknown stage"):
        exreg.stage_readiness(rd, "BOGUS")


# ----------------------------------------------------------------- skill + bridge readiness

def test_skill_readiness_tracks_its_stage(design_run):
    _, rd = design_run
    assert exreg.skill_readiness(rd, "experiment_matrix_builder")["ready"] is True   # DESIGN is current
    sq = exreg.skill_readiness(rd, "server_query")                                    # EXECUTE is future
    assert sq["ready"] is False and sq["stage"] == "EXECUTE"
    checkpoint_stage(rd, "DESIGN", [], "k", TS)
    assert exreg.skill_readiness(rd, "server_query")["ready"] is True                 # EXECUTE now current
    assert exreg.skill_readiness(rd, "experiment_matrix_builder")["status"] == "stage_done"  # re-mine ok


def test_bridge_readiness_needs_from_committed(design_run):
    _, rd = design_run
    b = exreg.bridge_readiness(rd, "design_to_execute")
    assert b["ready"] is False and b["missing"] == ["DESIGN"]
    checkpoint_stage(rd, "DESIGN", [], "k", TS)
    assert exreg.bridge_readiness(rd, "design_to_execute")["ready"] is True
    assert exreg.bridge_readiness(rd, "analyze_to_verify")["ready"] is False          # 'to' not pending


def test_unknown_skill_and_bridge_raise(design_run):
    _, rd = design_run
    with pytest.raises(ValueError, match="unknown skill"):
        exreg.skill_readiness(rd, "nope")
    with pytest.raises(ValueError, match="unknown bridge"):
        exreg.bridge_readiness(rd, "nope")


# ----------------------------------------------------------------- operate CLI (ready vs repair menu)

def _run_cli(argv):
    """Run the operate CLI, capturing the exit code (0 when it returns without sys.exit)."""
    try:
        cli.main(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def test_cli_run_stage_ready_auto_resolves_latest_run(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    create_run(runs, "r1", "full_rigor_minimal", "DESIGN", TS, project="p1")
    code = _run_cli(["run-stage", "--runs-dir", runs, "--project", "p1", "--stage", "DESIGN"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ready"] is True and out["stage"] == "DESIGN" and out["run_id"] == "r1"


def test_cli_run_stage_repair_menu_exit3(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    create_run(runs, "r1", "full_rigor_minimal", "DESIGN", TS, project="p1")
    code = _run_cli(["run-stage", "--runs-dir", runs, "--project", "p1", "--stage", "EXECUTE"])
    out = json.loads(capsys.readouterr().out)
    assert code == 3 and out["ready"] is False and out["missing"] == ["DESIGN"] and out["repair_actions"]


def test_cli_approve_releases_only_a_persisted_idea_gate(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    plan = spine.begin(runs, "idea-gate", "rank directions", "new_direction", TS, project="p1")
    rd = plan["run_dir"]
    checkpoint_stage(rd, "DISCOVER", [], "k-discover", TS,
                     stage_path=["DISCOVER", "IDEATE", "REPORT"])
    checkpoint_stage(rd, "IDEATE", [], "k-ideate", TS,
                     stage_path=["DISCOVER", "IDEATE", "REPORT"])
    mark_gate_pending(rd, "IDEATE", TS, "REPORT")

    code = _run_cli([
        "approve", "--runs-dir", runs, "--run-id", "idea-gate", "--stage", "IDEATE",
        "--reason", "director selected IDEA-2 after reading the menu",
    ])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["status"] == "running"
    assert out["next_stage"] == "REPORT"


def test_cli_run_bridge_repair_then_ready(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    create_run(runs, "r1", "full_rigor_minimal", "DESIGN", TS, project="p1")
    code = _run_cli(["run-bridge", "--runs-dir", runs, "--project", "p1", "--bridge", "design_to_execute"])
    assert code == 3 and json.loads(capsys.readouterr().out)["ready"] is False
    checkpoint_stage(find_run_dir(runs, "r1"), "DESIGN", [], "k", TS)
    code2 = _run_cli(["run-bridge", "--runs-dir", runs, "--project", "p1", "--bridge", "design_to_execute"])
    assert code2 == 0 and json.loads(capsys.readouterr().out)["ready"] is True


def test_cli_run_skill_server_query_hint(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    create_run(runs, "r1", "full_rigor_minimal", "DESIGN", TS, project="p1")
    checkpoint_stage(find_run_dir(runs, "r1"), "DESIGN", [], "k", TS)      # EXECUTE now current
    code = _run_cli(["run-skill", "--runs-dir", runs, "--project", "p1", "--skill", "server_query"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ready"] is True and "server-query" in out["note"]


def test_cli_run_stage_no_run_is_repair(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    code = _run_cli(["run-stage", "--runs-dir", runs, "--project", "ghost", "--stage", "DESIGN"])
    out = json.loads(capsys.readouterr().out)
    assert code == 3 and out["ready"] is False and "no run found" in out["error"]
