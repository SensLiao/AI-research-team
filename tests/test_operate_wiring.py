"""Wiring tests (audit B2/M14): the registry's `operated` flags mirror the REGISTRY exactly,
and every operated mode is genuinely drivable — '1900 green' must mean WIRED, not just tested."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.cli import cmd_run_dets, cmd_worker
from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.operate.modes import manuscript_authoring, manuscript_review, venue_readiness
from research_agent_teams.operate.panel_scheduler import validate_worker_spec_connectivity
from research_agent_teams.orchestrator.engine import _resolve_path
from research_agent_teams.orchestrator.model_policy import decorate_worker_runtime
from research_agent_teams.orchestrator.graph_spec import (
    load_mode_registry,
    validate_graph,
    validate_mode_registry,
)
from research_agent_teams.orchestrator.router import resolve_task

TS = "2026-06-13T00:00:00Z"

EXPECTED_WIRED = {"new_direction", "deep_ideation", "evidence_review", "evidence_deep", "deep_research",
                  "gap_breadth", "venue_readiness", "full_rigor_minimal",
                  # paper-reading upgrade (2026-06-26): the single-paper reading family
                  "ingest_paper", "read_paper_deep",
                  # independent authoring and review are separate one-button products.
                  "manuscript_authoring", "manuscript_review",
                  # wave 2 (2026-08-04): every mode that is not STRUCTURALLY manual is now
                  # one-button. Nothing manual moved — the four human gates, GPU submission and
                  # patch application are unchanged; these recipes stop AT those boundaries.
                  "gap_scan", "full_new_direction", "design_experiment", "power_analysis_review",
                  "m2_accept", "analysis_audit_panel", "verify_result", "check_run",
                  "repo_code_audit",
                  # wave-2 backlog closed (2026-08-07): the last two modules had recipes written
                  # but no tests, so they were deliberately left unregistered until now.
                  "ideate_ring", "aers_enhanced_research_pack", "manuscript_reconstruction"}


def test_operated_flags_mirror_the_registry_exactly():
    registry = load_mode_registry()
    flagged = {m for m, spec in registry["modes"].items() if spec.get("operated")}
    assert flagged == set(REGISTRY) == EXPECTED_WIRED, (
        "a mode is either wired in operate/modes/REGISTRY AND flagged operated:true, or neither — "
        "'works now' claims must never outrun the code (audit H8)")


def test_manuscript_operated_entries_are_distinct_concrete_recipes():
    registry = load_mode_registry()["modes"]
    assert REGISTRY["manuscript_authoring"] is manuscript_authoring
    assert REGISTRY["manuscript_review"] is manuscript_review
    assert manuscript_authoring is not manuscript_review
    assert registry["manuscript_authoring"]["operated"] is True
    assert registry["manuscript_review"]["operated"] is True
    assert "manuscript_review_pack" not in REGISTRY
    assert "manuscript_review_pack" not in registry
    for module in (manuscript_authoring, manuscript_review):
        assert callable(module.llm_step)
        assert callable(module.run_dets)
        assert callable(module.run_dets_with_repair)


def test_graph_and_registry_still_validate():
    assert validate_graph() == []
    assert validate_mode_registry() == []


@pytest.mark.parametrize("mode", sorted(EXPECTED_WIRED))
def test_every_wired_mode_resolves_routes_and_carries_the_north_star(mode, tmp_path):
    tf = resolve_task("study canal segmentation prompts", mode, f"w-{mode}", TS)
    stages = _resolve_path(tf)
    assert stages[-1] == "REPORT" and len(stages) >= 2

    runs = tmp_path / "runs"
    runs.mkdir()
    plan = spine.begin(str(runs), f"w-{mode}", "study canal segmentation prompts", mode, TS)
    mod = REGISTRY[mode]
    assert hasattr(mod, "run_dets") and hasattr(mod, "run_dets_with_repair")
    if mode == "manuscript_reconstruction":
        path = Path(plan["run_dir"]) / mod.INPUT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"review_text": "Please clarify the title."}), encoding="utf-8")
    spec = mod.llm_step(plan["run_dir"], stages[0], "study canal segmentation prompts")
    if spec is not None:
        assert validate_worker_spec_connectivity(mode, stages[0], spec) == []
        spec = decorate_worker_runtime(spec)
        workers = spec["workers"] if "workers" in spec else [spec]
        assert workers, f"{mode}: llm_step returned an empty worker panel"
        for w in workers:
            assert "NORTH STAR" in w["prompt"], (
                f"{mode}/{w.get('label')}: worker prompt is missing the north-star block (audit A2)")
            assert w.get("model") in ("opus", "sonnet")
            assert w.get("model_tier") == w.get("model")
            assert w.get("capability_requirements", {}).get("provider") == "any"
            assert w.get("capability_requirements", {}).get("reasoning_quality") in {
                "strong", "frontier"
            }
            assert w.get("output", "").endswith(".bundle.json")
    with pytest.raises(ValueError):
        mod.run_dets(plan["run_dir"], "NO_SUCH_STAGE", TS)


@pytest.mark.parametrize("mode", sorted(EXPECTED_WIRED))
def test_every_actual_llm_step_label_is_connected_for_every_pure_stage(mode, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    plan = spine.begin(str(runs), f"labels-{mode}", "audit actual worker labels", mode, TS)
    mod = REGISTRY[mode]
    if mode == "manuscript_reconstruction":
        path = Path(plan["run_dir"]) / mod.INPUT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"review_text": "Please clarify the title."}), encoding="utf-8")
    for stage in plan["stages"]:
        # venue_readiness intentionally reveals later waves only after frozen receipts;
        # its dynamic builders are checked separately below.
        spec = mod.llm_step(plan["run_dir"], stage, "audit actual worker labels")
        assert validate_worker_spec_connectivity(mode, stage, spec) == []


def test_every_dynamic_venue_worker_builder_has_a_distinct_connected_label(tmp_path):
    run_path = tmp_path / "venue"
    run_path.mkdir()
    (run_path / "task_frame.artifact.json").write_text(
        json.dumps({"payload": {"request_text": "audit", "north_star": {
            "statement": "audit", "in_scope": [], "out_of_scope": []
        }}}),
        encoding="utf-8",
    )
    run_dir = str(run_path)
    profile = {"venue_id": "test-venue"}
    receipt = {
        "precommit_hash": "frozen-hash",
        "allowed_reviewer_inputs": [
            "task_frame.artifact.json",
            "evidence/VERIFY/venue-profile.artifact.json",
            "evidence/VERIFY/review-config.artifact.json",
            "inbox/VERIFY.precommit.receipt.json",
            "manuscript.md",
        ],
        "forbidden_reviewer_inputs": ["inbox/VERIFY.review.*.bundle.json"],
    }
    reviewers = [
        venue_readiness._review_worker(run_dir, "audit", "opus", persona, profile, receipt)
        for persona in ("methodology", "domain", "adversarial")
    ]
    review_panel = {"workers": reviewers}
    assert validate_worker_spec_connectivity("venue_readiness", "VERIFY", review_panel) == []
    assert {worker["label"] for worker in reviewers} == {
        "venue-reviewer-methodology",
        "venue-reviewer-domain",
        "venue-reviewer-adversarial",
    }

    meta = venue_readiness._meta_worker(
        run_dir,
        "audit",
        "opus",
        {"precommit_hash": "frozen-hash"},
        {
            "review_refs": {
                persona: f"inbox/VERIFY.review.{persona}.bundle.json"
                for persona in ("methodology", "domain", "adversarial")
            },
            "review_hashes": {
                persona: f"sha256:{persona}"
                for persona in ("methodology", "domain", "adversarial")
            },
        },
    )
    assert validate_worker_spec_connectivity("venue_readiness", "VERIFY", meta) == []


def test_cli_worker_exposes_only_the_next_authorized_wave(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    spine.begin(str(runs), "cli-wave", "audit evidence", "evidence_review", TS)

    class Args:
        runs_dir = str(runs)
        run_id = "cli-wave"
        stage = "DISCOVER"
        request = None
        vault = None
        ts = TS

    cmd_worker(Args())
    first = json.loads(capsys.readouterr().out)
    assert first["schedule"]["status"] == "wave_ready"
    assert [worker["label"] for worker in first["worker"]["workers"]] == ["lit-scout"]
    assert first["schedule"]["authorized_agent_hops"] == 1

    cmd_worker(Args())
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["schedule"]["status"] == "waiting_for_outputs"
    assert repeated["schedule"]["authorized_agent_hops"] == 1
    assert Path(repeated["schedule"]["scheduler_receipt"]).is_file()


def test_cli_canonicalizes_legacy_direction_worker_label(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    spine.begin(str(runs), "cli-direction", "find a grounded direction", "new_direction", TS)

    class Args:
        runs_dir = str(runs)
        run_id = "cli-direction"
        stage = "DISCOVER"
        request = None
        vault = None
        ts = TS

    cmd_worker(Args())
    output = json.loads(capsys.readouterr().out)
    worker = output["worker"]["workers"][0]
    assert worker["label"] == "direction-grounding-scout"
    assert "source_label" not in worker


def test_cli_run_dets_cannot_bypass_an_unfinished_panel(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    spine.begin(str(runs), "cli-no-bypass", "audit evidence", "evidence_review", TS)

    class Args:
        runs_dir = str(runs)
        run_id = "cli-no-bypass"
        stage = "DISCOVER"
        ts = TS
        no_repair = False

    with pytest.raises(SystemExit) as exc:
        cmd_run_dets(Args())
    assert exc.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["workers_incomplete"] is True
    assert output["schedule"]["status"] == "wave_ready"
