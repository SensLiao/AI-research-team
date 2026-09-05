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


MANUSCRIPT_ROLE_CONNECTIVITY = {
    "manuscript-venue-corpus-scout": ("discover", "DISCOVER", ("manuscript_authoring",)),
    "manuscript-architect": ("design", "DESIGN", ("manuscript_authoring",)),
    "manuscript-evidence-steward": ("design", "DESIGN", ("manuscript_authoring",)),
    "manuscript-introduction-author": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-related-work-author": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-methods-author": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-results-author": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-section-author": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-figure-table-engineer": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-synthesis-editor": ("analyze", "ANALYZE", ("manuscript_authoring",)),
    "manuscript-factual-auditor": (
        "verify", "VERIFY",
        # 2026-08-20: also the independent claim-check verifier of manuscript_reconstruction.
        ("manuscript_authoring", "manuscript_reconstruction", "manuscript_review")
    ),
    "manuscript-citation-auditor": (
        "verify", "VERIFY", ("manuscript_authoring", "manuscript_review")
    ),
    "manuscript-style-latex-auditor": (
        "verify", "VERIFY", ("manuscript_authoring", "manuscript_review")
    ),
    "manuscript-domain-contribution-reviewer": (
        "verify", "VERIFY", ("manuscript_review",)
    ),
    "manuscript-methods-reproducibility-reviewer": (
        "verify", "VERIFY", ("manuscript_review",)
    ),
    "manuscript-figure-table-reviewer": ("verify", "VERIFY", ("manuscript_review",)),
}


def test_agent_connectivity_contract_is_clean():
    assert validate_agent_connectivity() == []


def test_every_non_control_agent_has_graph_and_mode_entry():
    report = build_agent_connectivity()
    summary = report["summary"]
    # Roster is the truth; the count below is derived from it, not pinned by hand —
    # update when the roster grows (2026-08-09: +5 multi-view IDEATE panel seats).
    expected_roster = len(report["agents"])
    assert summary["roster_agents"] == expected_roster
    assert summary["control_agents"] == 7
    assert summary["non_control_agents"] == expected_roster - 7
    assert summary["graph_connected_non_control"] == expected_roster - 7
    assert summary["mode_connected_non_control"] == expected_roster - 7

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
        "manuscript_authoring",
        "manuscript_review",
        # wave 2 (2026-08-04) — the director's call: every mode that is not STRUCTURALLY manual
        # becomes one-button. Nothing manual moved; these recipes stop AT the human gates, at GPU
        # submission and at patch application rather than around them.
        "gap_scan",
        "full_new_direction",
        "design_experiment",
        "power_analysis_review",
        "m2_accept",
        "analysis_audit_panel",
        "verify_result",
        "check_run",
        "repo_code_audit",
        # wave-2 backlog closed (2026-08-07): the last two modules had recipes written but no
        # tests, so they were deliberately left unregistered until now.
        "ideate_ring",
        "aers_enhanced_research_pack",
        "manuscript_reconstruction",  # 2026-08-20 team upgrade
    }
    # Still strictly smaller, because three modes remain spec-only. When the last one is wired
    # this becomes equality — that is the honest end state, not a weakened bar, and the
    # separation that actually protects the director survives it: see the exercised-vs-reachable
    # assertion below.
    assert report["summary"]["operated_agent_count"] < report["summary"]["non_control_agents"]


def test_reachable_is_never_reported_as_exercised():
    """Wiring a seat makes it REACHABLE. Only a real run makes it EXERCISED.

    Wave 2 moved 27 seats from hand-driven to one-button in a single day, which is exactly the
    moment a roster number starts getting quoted as if the work had been done. `workbench team`
    (reachable) and `workbench governance` (exercised) are deliberately different tools reading
    different sources — the census reads mode_registry.yaml, the governance count reads the bundles
    real runs left behind — and this test pins that they can never be collapsed into one number.
    """
    from research_agent_teams.tools import worker_census

    totals = worker_census.census()["totals"]
    # Reachability is a property of the registry, and it is now nearly total.
    assert totals["declared_by_operated"] + totals["spec_only"] == totals["workers"]
    assert totals["unreachable"] == 0
    # It says NOTHING about how many seats ever ran. That number comes from run evidence, is far
    # smaller, and must stay separately derived.
    assert "exercised" not in totals, (
        "the census must not grow an 'exercised' field — reachable and exercised come from "
        "different sources on purpose (governance census reads real run bundles)")


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


def test_manuscript_roles_have_exact_roster_graph_and_mode_connectivity():
    report = build_agent_connectivity()["agents"]

    for agent, (group, stage, modes) in MANUSCRIPT_ROLE_CONNECTIVITY.items():
        assert report[agent]["roster_group"] == group
        assert report[agent]["graph_stages"] == [stage]
        assert report[agent]["modes"] == sorted(modes)
        worker_spec = {"workers": [{"label": agent}]}
        for mode in modes:
            assert validate_worker_spec_connectivity(mode, stage, worker_spec) == []

    assert validate_worker_spec_connectivity(
        "manuscript_review", "VERIFY", {"workers": [{"label": "missing-manuscript-role"}]}
    ) != []


def test_manuscript_author_and_expert_reviewer_scopes_remain_disjoint():
    report = build_agent_connectivity()["agents"]
    section_author = report["manuscript-section-author"]
    assert section_author["graph_stages"] == ["ANALYZE"]
    assert section_author["modes"] == ["manuscript_authoring"]

    expert_reviewers = {
        "manuscript-domain-contribution-reviewer",
        "manuscript-methods-reproducibility-reviewer",
        "manuscript-figure-table-reviewer",
    }
    for reviewer in expert_reviewers:
        assert report[reviewer]["graph_stages"] == ["VERIFY"]
        assert report[reviewer]["modes"] == ["manuscript_review"]


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
