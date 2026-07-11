"""Connectivity contract for the Research Agent Teams roster.

This is the regression test for the orchestration audit: every non-control
agent must be reachable through the router, while control/hook agents stay out
of ordinary worker dispatch.
"""
from __future__ import annotations

from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.operate.modes import _deep_ideate
from research_agent_teams.orchestrator.agent_connectivity import (
    build_agent_connectivity,
    load_roster_groups,
    validate_agent_connectivity,
)
from research_agent_teams.operate.panel_scheduler import canonical_agent_label
from research_agent_teams.operate.panel_scheduler import validate_worker_spec_connectivity
from research_agent_teams.operate.modes import deep_research, evidence_deep, evidence_review


def test_agent_connectivity_contract_is_clean():
    assert validate_agent_connectivity() == []


def test_every_non_control_agent_has_graph_and_mode_entry():
    report = build_agent_connectivity()
    summary = report["summary"]
    assert summary["roster_agents"] == 140
    assert summary["control_agents"] == 6
    assert summary["non_control_agents"] == 134
    assert summary["graph_connected_non_control"] == 134
    assert summary["mode_connected_non_control"] == 134

    for agent, spec in report["agents"].items():
        if spec["status"] == "control":
            assert spec["roster_group"] == "control"
            assert spec["graph_stages"] == []
            assert spec["modes"] == []
        else:
            assert spec["graph_stages"], f"{agent} missing graph stage"
            assert spec["modes"], f"{agent} missing mode entry"
            assert spec["status"] in {"operated", "mode-routable"}


def test_operated_surface_stays_honest_and_separate_from_routable_surface():
    report = build_agent_connectivity()
    operated_modes = set(report["summary"]["operated_modes"])
    assert operated_modes == set(REGISTRY)
    assert operated_modes == {
        "new_direction",
        "deep_ideation",
        "evidence_review",
        "evidence_deep",
        "deep_research",
        "gap_breadth",
        "venue_readiness",
        "full_rigor_minimal",
        "ingest_paper",
        "read_paper_deep",
    }
    assert report["summary"]["operated_agent_count"] < report["summary"]["non_control_agents"]


def test_coverage_closure_modes_cover_previous_dark_matter_agents():
    report = build_agent_connectivity()["agents"]
    expected = {
        "repo_code_audit": {
            "repo-code-verifier",
            "patch-planner",
            "code-implementer",
            "unit-test-writer",
            "sandbox-runner",
            "repro-runner",
        },
        "analysis_audit_panel": {
            "baseline-comparison-auditor",
            "variance-analyzer",
            "fairness-auditor",
            "compliance-auditor",
            "goal-alignment-checker",
            "failure-case-miner",
            "figure-generator",
            "visualization-auditor",
            "claim-strength-calibrator",
            "figure-vlm-critic",
        },
        "manuscript_review_pack": {
            "synthesis-writer",
            "contribution-ledger-builder",
            "threats-to-validity-writer",
            "review-response-simulator",
        },
        "power_analysis_review": {"statistics-power-auditor"},
        "aers_enhanced_research_pack": {
            "aers-sop-curator",
            "literature-search-strategist",
            "data-wrangling-auditor",
            "reproducibility-packager",
            "benchmark-evidence-auditor",
            "submission-guideline-scout",
            "bibliography-validator",
            "manuscript-polish-editor",
        },
    }
    for mode, agents in expected.items():
        for agent in agents:
            assert mode in report[agent]["modes"], f"{agent} not connected through {mode}"


def test_deep_ideation_worker_labels_are_real_roster_agents(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "task_frame.artifact.json").write_text(
        '{"payload":{"request_text":"study canal segmentation","north_star":{"statement":"study canal segmentation","in_scope":[],"out_of_scope":[]}}}',
        encoding="utf-8",
    )
    roster = {name for names in load_roster_groups().values() for name in names}
    workers = _deep_ideate.discover_deep_workers(str(run_dir), "study", "vault", "max_quality",
                                                 with_analogy=True)
    workers.append(_deep_ideate.experiment_worker(str(run_dir), "study", "max_quality"))
    for worker in workers:
        label = canonical_agent_label(worker["label"])
        assert label in roster, f"{worker['label']} -> {label} is not a real agent"


def test_ambiguous_direction_label_has_one_explicit_canonical_role():
    roster = {name for names in load_roster_groups().values() for name in names}
    assert "discover-worker" not in roster
    assert canonical_agent_label("discover-worker") == "direction-grounding-scout"
    assert "direction-grounding-scout" in roster


def test_venue_persona_workers_are_distinct_traceable_agents():
    roster = {name for names in load_roster_groups().values() for name in names}
    personas = {
        "venue-reviewer-methodology",
        "venue-reviewer-domain",
        "venue-reviewer-adversarial",
    }
    assert personas <= roster
    report = build_agent_connectivity()["agents"]
    for persona in personas:
        assert "VERIFY" in report[persona]["graph_stages"]
        assert "venue_readiness" in report[persona]["modes"]


def test_operated_evidence_panel_labels_match_roster_graph_and_mode(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "task_frame.artifact.json").write_text(
        '{"payload":{"request_text":"review q","north_star":{"statement":"q","in_scope":["q"],"out_of_scope":[]}}}',
        encoding="utf-8",
    )
    for mode, module in (
        ("evidence_review", evidence_review),
        ("evidence_deep", evidence_deep),
        ("deep_research", deep_research),
    ):
        spec = module.llm_step(str(run_dir), "DISCOVER", "review q")
        assert validate_worker_spec_connectivity(mode, "DISCOVER", spec) == []
