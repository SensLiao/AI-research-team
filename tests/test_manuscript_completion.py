"""Fast, deterministic completion gate for the operated manuscript phase."""
from __future__ import annotations

import pytest

import json
from pathlib import Path

from research_agent_teams.operate import spine
from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools.capability_catalog import build_capability_catalog
from research_agent_teams.tools.director_packet import PACKET_REL, REQUIRED_HEADINGS, write_packet
from research_agent_teams.tools.manuscript_literature import (
    COVERAGE_AXES,
    assess_local_coverage,
    build_targeted_query_plan,
    route_coverage_deficits,
)
from research_agent_teams.tools.validate_artifact import validate_payload


ROOT = Path(__file__).resolve().parents[2] / "research_agent_teams"
WORKSPACE = ROOT.parent
TS = "2026-07-22T00:00:00Z"
EXPECTED_OPERATED = {
    "new_direction", "deep_ideation", "gap_breadth", "evidence_review", "evidence_deep",
    "deep_research", "venue_readiness", "full_rigor_minimal", "ingest_paper", "read_paper_deep",
    "manuscript_authoring", "manuscript_review",
    # wave 2 (2026-08-04): the modes that were registry-defined but hand-driven, now one-button.
    "gap_scan", "full_new_direction", "design_experiment", "power_analysis_review", "m2_accept",
    "analysis_audit_panel", "verify_result", "check_run", "repo_code_audit",
    # wave-2 backlog closed (2026-08-07): the last two modules had recipes written but no tests,
    # so they were deliberately left unregistered until now.
    "ideate_ring", "aers_enhanced_research_pack",
    # 2026-08-20 team upgrade: responding to a real external review is a routed run, not
    # freehand main-thread work (catalog E4).
    "manuscript_reconstruction",
}
GOLD_CASE_IDS = {
    "local-sufficient", "local-named-deficit", "retrieval-provider-matrix",
    "retrieval-exhaustive-no-evidence", "token-official-hard-override",
    "snapshot-targeted-invalidation", "bundle-section-and-integrator-closure",
    "dag-bounded-repair-and-authorization", "truth-unsupported-load-bearing-claim",
    "truth-citation-identity-entailment", "truth-numeric-receipt-false-execution",
    "asset-path-escape-matrix", "asset-director-owned-immutability",
    "build-fake-compiler-matrix", "build-toolchain-missing",
    "review-frozen-input-separation", "end-to-end-authoring",
}
GOLD_CASE_FAMILIES = {
    "local_corpus", "retrieval_truth", "token_snapshot", "bundle_dag", "scientific_truth",
    "asset_path", "build", "review_separation", "end_to_end",
}
MANUSCRIPT_HANDOFFS = {
    "manuscript_authoring": {
        "product_version": "manuscript-authoring/v2",
        "primary_markdown": "director-review/manuscript/00-OVERVIEW.md",
        "evidence_namespace": "evidence/manuscript-authoring/",
        "reusable_artifacts": {
            "manuscript-contract.artifact.json",
            "local-literature-coverage.artifact.json",
            "manuscript-integration.artifact.json",
            "manuscript-asset-manifest.artifact.json",
            "manuscript-build-receipt.artifact.json",
            "manuscript-quality-report.artifact.json",
        },
    },
    "manuscript_review": {
        "product_version": "manuscript-review/v1",
        "primary_markdown": "director-review/manuscript/reviewer-report.md",
        "evidence_namespace": "evidence/manuscript-review/",
        "reusable_artifacts": {
            "manuscript-review-verdicts.artifact.json",
            "manuscript-review-reconciliation.artifact.json",
            "manuscript-submission-package.artifact.json",
        },
    },
}
DIRECTOR_ENTRY_FILES = (
    ROOT / "README.md",
    WORKSPACE / "AGENTS.md",
    WORKSPACE / ".claude" / "CLAUDE.md",
    WORKSPACE / ".agents" / "skills" / "research-orchestrator" / "SKILL.md",
    WORKSPACE / ".agents" / "skills" / "source-command-run-mode" / "SKILL.md",
    WORKSPACE / ".agents" / "skills" / "source-command-start-research" / "SKILL.md",
)


def _names_both_manuscript_products(text: str) -> bool:
    return "manuscript_authoring" in text and "manuscript_review" in text


def _delegates_to_a_guarded_entry(path: Path, texts: dict[Path, str]) -> bool:
    """An entry doc may point at another guarded entry instead of duplicating it.

    De-duplication is only acceptable when the pointer names a workspace-relative path
    that is itself guarded here AND whose target discloses both operated manuscript
    products. A stub that points nowhere, or points at an unguarded file, still fails.
    """
    text = texts[path]
    for other, other_text in texts.items():
        if other == path:
            continue
        rel = other.resolve().relative_to(WORKSPACE).as_posix()
        if rel in text and _names_both_manuscript_products(other_text):
            return True
    return False


def _catalog_modes() -> dict[str, dict]:
    return {row["mode"]: row for row in build_capability_catalog()["modes"]}


def _empty_local_coverage(tmp_path: Path) -> dict:
    vault = tmp_path / "vault"
    (vault / "00-system").mkdir(parents=True)
    (vault / "02-wiki").mkdir()
    criteria = {
        axis: {"criterion": f"coverage for {axis}", "recall_query": f"local {axis}"}
        for axis in COVERAGE_AXES
    }
    return assess_local_coverage(
        coverage_id="local-literature-coverage",
        manuscript_snapshot_sha256="a" * 64,
        assessed_at=TS,
        criteria=criteria,
        vault_root=vault,
        allowed_vault_roots=(vault,),
        recall_fn=lambda *_args, **_kwargs: {"citations": []},
    )


def test_exactly_twelve_real_operated_modes_and_no_phantom_review_pack():
    registry = load_mode_registry()["modes"]
    catalog = _catalog_modes()
    assert set(REGISTRY) == EXPECTED_OPERATED
    assert {name for name, spec in registry.items() if spec.get("operated")} == EXPECTED_OPERATED
    assert {name for name, row in catalog.items() if row["status"] == "operated"} == EXPECTED_OPERATED
    assert len(EXPECTED_OPERATED) == 24
    assert "manuscript_review_pack" not in REGISTRY
    assert "manuscript_review_pack" not in registry
    assert "manuscript_review_pack" not in catalog
    for mode, expected in MANUSCRIPT_HANDOFFS.items():
        handoff = registry[mode]["handoff"]
        assert handoff["contract_version"] == "mode-handoff/v2"
        assert handoff["product_version"] == expected["product_version"]
        assert handoff["primary_markdown"] == expected["primary_markdown"]
        assert handoff["evidence_namespace"] == expected["evidence_namespace"]
        assert set(handoff["reusable_artifacts"]) == expected["reusable_artifacts"]
        assert handoff["primary_markdown"].startswith("director-review/")
        assert ".." not in Path(handoff["primary_markdown"]).parts


def test_all_seventeen_gold_cases_remain_the_single_completion_matrix():
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "manuscript" / "gold_cases.json").read_text(encoding="utf-8")
    )
    cases = fixture["cases"]
    assert fixture["case_count"] == 17
    assert len(cases) == 17
    assert {row["case_id"] for row in cases} == GOLD_CASE_IDS
    assert {row["family"] for row in cases} == GOLD_CASE_FAMILIES
    assert sum(fixture["family_counts"].values()) == len(cases)
    required = {
        "case_id", "input_manifest", "expected_tool_calls", "expected_bundles",
        "expected_hard_findings", "expected_status", "rationale",
    }
    assert all(required <= set(row) for row in cases)
    assert all(isinstance(row["expected_status"]["submission_ready"], bool) for row in cases)
    for row in cases:
        for call in row["expected_tool_calls"]:
            if call.get("tool") == "paper_search":
                if "port" in call:
                    assert call["port"] == "existing"
                assert call["live_network"] is False
    assert "manuscript_review_pack" not in json.dumps(fixture, sort_keys=True)


def test_director_packet_is_a_real_markdown_first_entry_for_an_operated_run(tmp_path):
    run = spine.begin(
        str(tmp_path / "runs"), "packet-001", "author a paper", "manuscript_authoring", TS
    )
    packet = write_packet(Path(run["run_dir"]), generated_at=TS)
    assert packet == Path(run["run_dir"]) / PACKET_REL
    assert packet.is_file()
    text = packet.read_text(encoding="utf-8")
    assert "# Director Review Packet" in text
    assert "manuscript_authoring" in text
    assert all(heading in text for heading in REQUIRED_HEADINGS)
    assert (Path(run["run_dir"]) / "task_frame.artifact.json").is_file()
    assert not list(packet.parent.glob("*.json"))


def test_d07_calls_no_search_before_local_coverage_names_a_deficit(tmp_path):
    coverage = _empty_local_coverage(tmp_path)
    assert validate_payload("local_literature_coverage", coverage) == []
    calls: list[dict] = []

    def search_spy(queries, *, sources, limit_per_source, transport):
        calls.append({"queries": list(queries), "sources": sources, "transport": transport})
        return {"queries": list(queries), "records": [], "source_errors": {}}

    unchanged = route_coverage_deficits(
        coverage, query_plans=(), search_many_fn=search_spy, transport=object()
    )
    assert calls == []
    assert unchanged["frozen_query_plans"] == []
    assert all(
        axis["status"] != "DEFICIT" for axis in unchanged["coverage"]["axes"].values()
    )

    plan = build_targeted_query_plan(
        coverage,
        axis="technical_method",
        deficit_id="DEF-technical-method",
        query="bounded AI technical method literature",
        providers=("ARXIV",),
        plan_id="plan-technical-method",
        created_at=TS,
    )
    transport = object()
    routed = route_coverage_deficits(
        coverage, query_plans=(plan,), search_many_fn=search_spy, transport=transport
    )
    assert calls == [
        {
            "queries": ["bounded AI technical method literature"],
            "sources": ("arxiv",),
            "transport": transport,
        }
    ]
    assert plan["search_port"] == "paper_search.search_many"
    assert plan["metadata_only"] is True
    assert routed["coverage"]["axes"]["technical_method"]["query_authorization"]["deficit_id"] == (
        "DEF-technical-method"
    )
    assert routed["frozen_query_plans"] == [plan]


def test_every_director_entry_is_synchronized_to_the_two_operated_manuscript_products():
    if not all(path.is_file() for path in DIRECTOR_ENTRY_FILES[1:]):
        pytest.skip("workspace entry docs are not part of this checkout")
    assert DIRECTOR_ENTRY_FILES[0] == ROOT / "README.md"
    assert all(path.is_file() for path in DIRECTOR_ENTRY_FILES)
    for path in DIRECTOR_ENTRY_FILES[1:]:
        assert path.resolve().is_relative_to(WORKSPACE)
        assert not path.resolve().is_relative_to(ROOT)
    texts = {path: path.read_text(encoding="utf-8") for path in DIRECTOR_ENTRY_FILES}
    for path, text in texts.items():
        assert _names_both_manuscript_products(text) or _delegates_to_a_guarded_entry(
            path, texts
        ), path
        assert "manuscript_review_pack" not in text, path
    facts = (ROOT / "PLATFORM-FACTS.md").read_text(encoding="utf-8")
    # The count is re-derived by tests/test_governance_census.py; pinning the integer in two
    # places is how it drifted. Here we only pin that the section exists and is honest.
    assert "operated modes" in facts
    assert "GPU" in facts and "not operated" in facts.casefold()
    assert "manuscript_review_pack" not in facts

    route_text = "\n".join(texts.values()).casefold()
    assert "local" in route_text and "deficit" in route_text
    assert "paper_search" in route_text
