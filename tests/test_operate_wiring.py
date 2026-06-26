"""Wiring tests (audit B2/M14): the registry's `operated` flags mirror the REGISTRY exactly,
and every operated mode is genuinely drivable — '1900 green' must mean WIRED, not just tested."""
from __future__ import annotations

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.orchestrator.engine import _resolve_path
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
                  "ingest_paper", "read_paper_deep"}


def test_operated_flags_mirror_the_registry_exactly():
    registry = load_mode_registry()
    flagged = {m for m, spec in registry["modes"].items() if spec.get("operated")}
    assert flagged == set(REGISTRY) == EXPECTED_WIRED, (
        "a mode is either wired in operate/modes/REGISTRY AND flagged operated:true, or neither — "
        "'works now' claims must never outrun the code (audit H8)")


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
    spec = mod.llm_step(plan["run_dir"], stages[0], "study canal segmentation prompts")
    if spec is not None:
        workers = spec["workers"] if "workers" in spec else [spec]
        assert workers, f"{mode}: llm_step returned an empty worker panel"
        for w in workers:
            assert "NORTH STAR" in w["prompt"], (
                f"{mode}/{w.get('label')}: worker prompt is missing the north-star block (audit A2)")
            assert w.get("model") in ("opus", "sonnet")
            assert w.get("output", "").endswith(".bundle.json")
    with pytest.raises(ValueError):
        mod.run_dets(plan["run_dir"], "NO_SUCH_STAGE", TS)
