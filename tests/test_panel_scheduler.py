from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from research_agent_teams.operate.panel_scheduler import (
    PanelContractError,
    _infer_plain_repair_targets,
    _normalize_nodes,
    capability_overlay_block,
    canonical_agent_label,
    schedule_next_wave,
)
from research_agent_teams.operate.artifacts import TargetedGateBlock
from research_agent_teams.operate.bounded_repair import attempt_with_repair
from research_agent_teams.tools.budget_tracker import BudgetExceeded


TS = "2026-07-10T00:00:00Z"


def _run(tmp_path: Path, *, budget: int = 8, mode: str = "full_rigor_minimal") -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "inbox").mkdir(parents=True)
    payload = {
        "mode": mode,
        "budget": {"max_agent_hops": budget},
        "agent_subset": [
            "baseline-fairness-critic",
            "protocol-critic",
            "design-synthesizer",
            "script-author",
        ],
    }
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps({"payload": payload}), encoding="utf-8"
    )
    return run_dir


def _worker(run_dir: Path, label: str, filename: str, **extra) -> dict:
    return {
        "label": label,
        "model": "opus",
        "prompt": f"NORTH STAR\nwork as {label}",
        "output": str(run_dir / "inbox" / filename),
        **extra,
    }


def _write_output(worker: dict, payload: dict | None = None) -> None:
    path = Path(worker["output"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or {"ok": True}), encoding="utf-8")


def _link_directory_or_skip(link: Path, target: Path) -> str:
    """Create a real symlink, or a Windows junction where link privilege is absent."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symbolic links unavailable on this filesystem: {symlink_error}")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(
                "symbolic links and Windows junctions unavailable on this filesystem: "
                f"{symlink_error}; {result.stderr or result.stdout}"
            )
        return "junction"


def test_scheduler_releases_blind_wave_before_synthesizer(tmp_path):
    run_dir = _run(tmp_path)
    first = [
        _worker(run_dir, "baseline-fairness-critic", "baseline.bundle.json"),
        _worker(run_dir, "protocol-critic", "protocol.bundle.json"),
    ]
    synth = _worker(run_dir, "design-synthesizer", "synth.bundle.json")
    panel = {
        "label": "design-panel",
        "workers": [*first, synth],
        "worker_order": [worker["label"] for worker in [*first, synth]],
        "parallel_groups": [
            [worker["label"] for worker in first],
            [synth["label"]],
        ],
    }

    wave_1 = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert wave_1["status"] == "wave_ready"
    assert [worker["label"] for worker in wave_1["workers"]] == [
        "baseline-fairness-critic",
        "protocol-critic",
    ]
    assert "design-synthesizer" not in json.dumps(wave_1["dispatch"])

    _write_output(first[0])
    waiting = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert waiting["status"] == "waiting_for_outputs"
    assert [worker["label"] for worker in waiting["workers"]] == ["protocol-critic"]
    assert "design-synthesizer" not in json.dumps(waiting["dispatch"])

    _write_output(first[1])
    wave_2 = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in wave_2["workers"]] == ["design-synthesizer"]
    assert wave_2["workers"][0]["scheduler_contract"]["predecessor_outputs"]


def test_scheduler_receipt_write_rejects_linked_parent_before_touching_outside(tmp_path):
    """An actual symlink/reparse parent cannot redirect a receipt outside the run."""
    run_dir = _run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "director-owned.txt"
    marker.write_text("unchanged", encoding="utf-8")
    linked_parent = run_dir / "inbox" / "panel-scheduler"
    predictable_tmp = outside / "DESIGN.json.tmp"
    link_kind = _link_directory_or_skip(linked_parent, outside)
    if link_kind == "symlink":
        predictable_tmp.symlink_to(marker)

    worker = _worker(run_dir, "baseline-fairness-critic", "baseline.bundle.json")
    with pytest.raises(PanelContractError, match="unsafe scheduler receipt path.*(?:SYMLINK_PATH|REPARSE_PATH)"):
        schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)

    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (outside / "DESIGN.json").exists()


def test_scheduler_refuses_unknown_or_missing_predecessor(tmp_path):
    run_dir = _run(tmp_path)
    synth = _worker(
        run_dir,
        "design-synthesizer",
        "synth.bundle.json",
        depends_on=["worker-that-does-not-exist"],
    )
    with pytest.raises(PanelContractError, match="unknown predecessor"):
        schedule_next_wave(run_dir, "DESIGN", synth, ts=TS)


def test_evidence_deep_legacy_linker_bundle_blocks_citation_auditor_release(tmp_path):
    """A file-shaped old linker output must not unlock the strict citation wave."""
    run_dir = tmp_path / "run"
    (run_dir / "inbox").mkdir(parents=True)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "evidence_deep",
        "budget": {"max_agent_hops": 4},
        "agent_subset": ["claim-evidence-linker", "citation-coverage-auditor"],
    }}), encoding="utf-8")
    linker = _worker(run_dir, "claim-evidence-linker", "DISCOVER.claim-evidence-linker.bundle.json")
    auditor = _worker(
        run_dir,
        "citation-coverage-auditor",
        "DISCOVER.citation-coverage-auditor.bundle.json",
        depends_on=["claim-evidence-linker"],
    )
    panel = {
        "workers": [linker, auditor],
        "worker_order": [linker["label"], auditor["label"]],
        "parallel_groups": [[linker["label"]], [auditor["label"]]],
    }

    first = schedule_next_wave(run_dir, "DISCOVER", panel, ts=TS)
    assert [worker["label"] for worker in first["workers"]] == ["claim-evidence-linker"]
    _write_output(first["workers"][0], {
        "claim_evidence_map": {"claims": [{"evidence": "legacy shape"}]},
    })

    with pytest.raises(PanelContractError) as exc_info:
        schedule_next_wave(run_dir, "DISCOVER", panel, ts=TS)
    message = str(exc_info.value)
    assert "claim-span/v1" in message
    assert "Citation-coverage-auditor and downstream workers are not released" in message
    assert "Re-run claim-evidence-linker" in message
    assert "start a new evidence_deep run" in message


def test_scheduler_derives_maximal_wave_from_dependencies_when_groups_are_omitted(tmp_path):
    run_dir = _run(tmp_path)
    left = _worker(run_dir, "baseline-fairness-critic", "left.bundle.json")
    right = _worker(run_dir, "protocol-critic", "right.bundle.json")
    synth = _worker(
        run_dir,
        "design-synthesizer",
        "synth.bundle.json",
        depends_on=["baseline-fairness-critic", "protocol-critic"],
    )
    panel = {"workers": [left, right, synth]}

    first = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in first["workers"]] == [
        "baseline-fairness-critic", "protocol-critic",
    ]
    for worker in first["workers"]:
        _write_output(worker)
    second = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in second["workers"]] == ["design-synthesizer"]


def test_scheduler_keeps_legacy_no_dependency_panel_serial(tmp_path):
    run_dir = _run(tmp_path)
    panel = {"workers": [
        _worker(run_dir, "baseline-fairness-critic", "left.bundle.json"),
        _worker(run_dir, "protocol-critic", "right.bundle.json"),
    ]}
    first = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in first["workers"]] == [
        "baseline-fairness-critic",
    ]


def test_director_extension_expands_only_targeted_supplement_budget(tmp_path):
    run_dir = _run(tmp_path, budget=3)
    task_path = run_dir / "task_frame.artifact.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["payload"]["budget"]["max_supplement_agent_hops"] = 1
    task_path.write_text(json.dumps(task), encoding="utf-8")
    (run_dir / "inbox" / "director-supplement-budget-extension.json").write_text(
        json.dumps({
            "contract_version": "director-supplement-extension/v1",
            "authorized_by": "director",
            "dimension": "max_supplement_agent_hops",
            "base_limit": 1,
            "extended_limit": 2,
            "reason": "finish two targeted scientific corrections without replaying the panel",
        }),
        encoding="utf-8",
    )
    worker = _worker(run_dir, "baseline-fairness-critic", "a.bundle.json")
    first = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    _write_output(first["workers"][0])
    attempt_with_repair(
        run_dir, "DESIGN", {"max_debug_retries_per_run": 2}, TS,
        lambda: (_ for _ in ()).throw(TargetedGateBlock(
            "repair once", [{
                "defect_id": "D-EXT", "location": "a", "summary": "fix a",
                "target_agents": ["baseline-fairness-critic"], "refresh_agents": [],
            }],
        )),
    )
    supplement = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    assert supplement["status"] == "wave_ready"


def test_group_order_can_avoid_inventing_unrelated_freshness_dependencies(tmp_path):
    run_dir = _run(tmp_path)
    unrelated = _worker(run_dir, "protocol-critic", "unrelated.bundle.json")
    downstream = _worker(
        run_dir,
        "design-synthesizer",
        "downstream.bundle.json",
        depends_on=["baseline-fairness-critic"],
    )
    actual_parent = _worker(run_dir, "baseline-fairness-critic", "parent.bundle.json")
    panel = {
        "workers": [actual_parent, unrelated, downstream],
        "parallel_groups": [
            ["baseline-fairness-critic"],
            ["protocol-critic"],
            ["design-synthesizer"],
        ],
        "group_barriers": False,
    }
    nodes, _groups = _normalize_nodes(run_dir, panel)
    by_id = {node["id"]: node for node in nodes}
    target = next(node for node in nodes if node["label"] == "design-synthesizer")
    predecessor_labels = {by_id[node_id]["label"] for node_id in target["barrier_deps"]}
    assert predecessor_labels == {"baseline-fairness-critic"}


def test_scheduler_refuses_forbidden_read_scope_overlap(tmp_path):
    run_dir = _run(tmp_path)
    worker = _worker(
        run_dir,
        "baseline-fairness-critic",
        "baseline.bundle.json",
        input_contract={
            "allowed_inputs": ["inbox/frozen-input.json"],
            "allowed_bundle_agents": [],
            "forbidden_inputs": ["inbox/frozen-input.json"],
            "blind": True,
        },
    )
    with pytest.raises(PanelContractError, match="allowed.*forbidden"):
        schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)


def test_scheduler_enforces_real_worker_hop_budget_atomically(tmp_path):
    run_dir = _run(tmp_path, budget=1)
    panel = {
        "label": "blind-panel",
        "workers": [
            _worker(run_dir, "baseline-fairness-critic", "a.bundle.json"),
            _worker(run_dir, "protocol-critic", "b.bundle.json"),
        ],
        "parallel_groups": [["baseline-fairness-critic", "protocol-critic"]],
    }
    with pytest.raises(BudgetExceeded, match="max_agent_hops"):
        schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert not (run_dir / "inbox" / "panel-scheduler" / "DESIGN.json").exists()


def test_hop_budget_is_global_across_stage_receipts(tmp_path):
    run_dir = _run(tmp_path, budget=1)
    design = _worker(run_dir, "baseline-fairness-critic", "design.bundle.json")
    first = schedule_next_wave(run_dir, "DESIGN", design, ts=TS)
    assert first["authorized_agent_hops"] == 1
    _write_output(design)

    execute = _worker(run_dir, "script-author", "execute.bundle.json")
    with pytest.raises(BudgetExceeded, match="max_agent_hops"):
        schedule_next_wave(run_dir, "EXECUTE", execute, ts=TS)


def test_supplement_budget_is_independent_from_initial_budget(tmp_path):
    run_dir = _run(tmp_path, budget=1)
    task = json.loads((run_dir / "task_frame.artifact.json").read_text())
    task["payload"]["budget"]["max_supplement_agent_hops"] = 1
    task["payload"]["budget"]["max_debug_retries_per_run"] = 2
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(task), encoding="utf-8")
    worker = _worker(run_dir, "baseline-fairness-critic", "a.bundle.json")

    initial = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    _write_output(initial["workers"][0], {"version": 1})
    assert schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)["status"] == "complete"

    def blocked():
        raise TargetedGateBlock("repair a", [{
            "defect_id": "D-budget", "location": "a", "summary": "repair a",
            "target_agents": ["baseline-fairness-critic"], "refresh_agents": [],
        }])

    attempt_with_repair(run_dir, "DESIGN", task["payload"]["budget"], TS, blocked)
    supplement = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    assert supplement["authorized_initial_hops"] == 1
    assert supplement["authorized_supplement_hops"] == 1
    _write_output(supplement["workers"][0], {"version": 2})
    assert schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)["status"] == "complete"

    attempt_with_repair(run_dir, "DESIGN", task["payload"]["budget"], TS, blocked)
    with pytest.raises(BudgetExceeded, match="max_supplement_agent_hops"):
        schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)


def test_targeted_repair_targets_only_terminal_worker(tmp_path):
    run_dir = _run(tmp_path, budget=2)
    a = _worker(run_dir, "baseline-fairness-critic", "a.bundle.json")
    b = _worker(run_dir, "design-synthesizer", "b.bundle.json", depends_on=[a["label"]])
    panel = {
        "label": "legacy-local-repair",
        "workers": [a, b],
        "worker_order": [a["label"], b["label"]],
        "parallel_groups": [[a["label"]], [b["label"]]],
    }
    first = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(first["workers"][0])
    second = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(second["workers"][0])
    assert schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)["status"] == "complete"

    def targeted_block():
        raise TargetedGateBlock("legacy format gap", [{
            "defect_id": "D-format", "location": "DESIGN/synthesis",
            "summary": "repair the final synthesis format",
            "target_agents": ["design-synthesizer"], "refresh_agents": [],
        }])

    attempt_with_repair(run_dir, "DESIGN", {"max_debug_retries_per_run": 1}, TS, targeted_block)
    repair = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [row["label"] for row in repair["workers"]] == ["design-synthesizer"]


def test_targeted_repair_routes_named_bundle_to_owner_before_terminal_fallback(tmp_path):
    run_dir = _run(tmp_path, budget=2)
    mechanism = _worker(run_dir, "baseline-fairness-critic", "MECHANISM.bundle.json")
    analogy = _worker(
        run_dir,
        "design-synthesizer",
        "ANALOGY.bundle.json",
        depends_on=[mechanism["label"]],
    )
    panel = {
        "label": "named-local-repair",
        "workers": [mechanism, analogy],
        "worker_order": [mechanism["label"], analogy["label"]],
        "parallel_groups": [[mechanism["label"]], [analogy["label"]]],
    }
    first = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(first["workers"][0])
    second = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(second["workers"][0])
    assert schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)["status"] == "complete"

    def targeted_block():
        raise TargetedGateBlock("mechanism_graph schema wording mismatch", [{
            "defect_id": "D-mechanism", "location": "DESIGN/mechanism_graph",
            "summary": "repair the mechanism graph schema wording",
            "target_agents": ["baseline-fairness-critic"], "refresh_agents": [],
        }])

    attempt_with_repair(run_dir, "DESIGN", {"max_debug_retries_per_run": 1}, TS, targeted_block)
    repair = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [row["label"] for row in repair["workers"]] == ["baseline-fairness-critic"]


def test_plain_repair_routes_typed_staleness_collection_to_leaf_owner(tmp_path):
    del tmp_path  # The inference helper is intentionally independent of a mode graph.
    nodes = [
        {"label": "staleness-auditor", "output_rel": "inbox/DISCOVER.staleness-auditor.bundle.json"},
        {"label": "landscape-mapper", "output_rel": "inbox/DISCOVER.landscape-mapper.bundle.json"},
    ]
    targets = _infer_plain_repair_targets(
        nodes,
        {"reason": "evidence_deep artifact schema BLOCK: staleness_reports[1] payload"},
    )
    assert targets == {"staleness-auditor"}


def test_plain_repair_routes_source_quality_contract_to_ranker(tmp_path):
    del tmp_path
    nodes = [
        {"label": "source-quality-ranker", "output_rel": "inbox/DISCOVER.source-quality-ranker.bundle.json"},
        {"label": "landscape-mapper", "output_rel": "inbox/DISCOVER.landscape-mapper.bundle.json"},
    ]
    targets = _infer_plain_repair_targets(
        nodes,
        {"reason": "current source quality must declare source-methodology/v1"},
    )
    assert targets == {"source-quality-ranker"}


def test_preexisting_outputs_cannot_bypass_dispatch_receipt(tmp_path):
    run_dir = _run(tmp_path)
    worker = _worker(run_dir, "baseline-fairness-critic", "prewritten.bundle.json")
    _write_output(worker)
    decision = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    assert decision["status"] == "unverified_unreceipted_outputs"
    assert decision["dispatch"] is None


def test_stateful_mode_cannot_claim_complete_without_all_worker_receipts(tmp_path):
    run_dir = _run(tmp_path, mode="venue_readiness")
    payload = json.loads((run_dir / "task_frame.artifact.json").read_text(encoding="utf-8"))
    payload["payload"]["agent_subset"] = [
        "venue-selector",
        "venue-review-configurator",
        "venue-reviewer-methodology",
        "venue-reviewer-domain",
        "venue-reviewer-adversarial",
        "area-chair-synthesizer",
    ]
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(payload), encoding="utf-8")
    decision = schedule_next_wave(run_dir, "VERIFY", None, ts=TS)
    assert decision["status"] == "unverified_unreceipted_outputs"
    assert "area-chair-synthesizer" in decision["unreceipted_agents"]


def test_canonical_direction_label_is_explicit():
    assert canonical_agent_label("discover-worker") == "direction-grounding-scout"
    assert canonical_agent_label("lit-scout") == "lit-scout"


def test_cwd_relative_output_containing_run_root_is_resolved_once(tmp_path):
    run_dir = _run(tmp_path)
    output = run_dir / "inbox" / "relative.bundle.json"
    worker = _worker(run_dir, "baseline-fairness-critic", "unused.bundle.json")
    worker["output"] = os.path.relpath(output, Path.cwd())
    decision = schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    assert Path(decision["workers"][0]["output"]).resolve() == output.resolve()


def test_targeted_repair_preserves_originals_and_refreshes_only_named_consumers(tmp_path):
    run_dir = _run(tmp_path, budget=5)
    a = _worker(run_dir, "baseline-fairness-critic", "a.bundle.json")
    b = _worker(run_dir, "protocol-critic", "b.bundle.json")
    c = _worker(
        run_dir, "design-synthesizer", "c.bundle.json",
        depends_on=["baseline-fairness-critic"],
    )
    panel = {
        "label": "targeted-panel",
        "workers": [a, b, c],
        "parallel_groups": [
            ["baseline-fairness-critic", "protocol-critic"],
            ["design-synthesizer"],
        ],
    }
    wave = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    for worker in wave["workers"]:
        _write_output(worker, {"version": 1, "agent": worker["label"]})
    wave = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(wave["workers"][0], {"version": 1, "agent": "design-synthesizer"})
    assert schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)["status"] == "complete"
    original_a = Path(a["output"]).read_bytes()
    original_b = Path(b["output"]).read_bytes()

    def blocked():
        raise TargetedGateBlock(
            "one local fairness field is missing",
            [{
                "defect_id": "D-1",
                "location": "baseline.fairness",
                "summary": "add the missing field",
                "target_agents": ["baseline-fairness-critic"],
                "refresh_agents": ["design-synthesizer"],
            }],
        )

    assert attempt_with_repair(run_dir, "DESIGN", {"max_debug_retries_per_run": 1}, TS, blocked)[0] == "retry"
    repair_a = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in repair_a["workers"]] == ["baseline-fairness-critic"]
    assert Path(repair_a["workers"][0]["output"]) != Path(a["output"])
    _write_output(repair_a["workers"][0], {"version": 2, "agent": "baseline-fairness-critic"})
    repair_c = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [worker["label"] for worker in repair_c["workers"]] == ["design-synthesizer"]
    _write_output(repair_c["workers"][0], {"version": 2, "agent": "design-synthesizer"})
    done = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert done["status"] == "complete"
    assert done["authorized_agent_hops"] == 5
    assert Path(a["output"]).read_bytes() == original_a
    assert Path(b["output"]).read_bytes() == original_b
    plan = json.loads(next((run_dir / "inbox" / "supplements").rglob("repair-plan.json")).read_text())
    assert all(row["output_sha256"] for row in plan["outputs"])
    assert all(row["changed_paths"] for row in plan["outputs"])


def test_first_run_worker_after_completed_repair_uses_logical_output_without_repair_feedback(tmp_path):
    run_dir = _run(tmp_path, budget=4)
    a = _worker(run_dir, "baseline-fairness-critic", "a.bundle.json")
    c = _worker(run_dir, "design-synthesizer", "c.bundle.json", depends_on=["baseline-fairness-critic"])
    d = _worker(run_dir, "protocol-critic", "d.bundle.json")
    panel = {
        "label": "repair-then-continue",
        "workers": [a, c, d],
        "parallel_groups": [[a["label"]], [c["label"]], [d["label"]]],
    }
    first = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(first["workers"][0], {"version": 1})
    second = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(second["workers"][0], {"version": 1})

    def blocked():
        raise TargetedGateBlock("local repair", [{
            "defect_id": "D-2", "location": "a", "summary": "fix a",
            "target_agents": ["baseline-fairness-critic"], "refresh_agents": [],
        }])

    attempt_with_repair(run_dir, "DESIGN", {"max_debug_retries_per_run": 1}, TS, blocked)
    repair = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    _write_output(repair["workers"][0], {"version": 2})
    continued = schedule_next_wave(run_dir, "DESIGN", panel, ts=TS)
    assert [row["label"] for row in continued["workers"]] == ["protocol-critic"]
    assert Path(continued["workers"][0]["output"]) == Path(d["output"])
    assert "TARGETED REPAIR" not in continued["workers"][0]["prompt"]


def test_capability_overlay_block_is_stage_filtered_and_advisory(tmp_path):
    run_dir = _run(tmp_path)
    frame_path = run_dir / "task_frame.artifact.json"
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["payload"]["capability_overlay_plan"] = {
        "contract_version": "research-capability-route/v1",
        "overlays": [
            {
                "overlay_id": "hypothesis_prediction_contract",
                "title": "Hypothesis and prediction contract",
                "guidance": "Name a falsifier before looking at results.",
                "target_stages": ["DESIGN"],
                "non_goals": ["reinterpret_results_post_hoc"],
            },
            {
                "overlay_id": "results_to_claim_contract",
                "title": "Results-to-claim contract",
                "guidance": "Bind claims to named evidence.",
                "target_stages": ["REPORT"],
                "non_goals": ["create_results"],
            },
        ],
    }
    frame_path.write_text(json.dumps(frame), encoding="utf-8")

    block, contract = capability_overlay_block(run_dir, "DESIGN")
    assert "Name a falsifier" in block
    assert "Bind claims" not in block
    assert contract == {
        "contract_version": "research-capability-route/v1",
        "stage": "DESIGN",
        "overlay_ids": ["hypothesis_prediction_contract"],
        "advisory_only": True,
        "external_skill_execution": False,
        "network_access": False,
    }


def test_legacy_task_frame_has_no_capability_overlay_block(tmp_path):
    run_dir = _run(tmp_path)
    assert capability_overlay_block(run_dir, "DESIGN") == ("", None)
