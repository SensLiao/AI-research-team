from __future__ import annotations

import copy

import pytest

from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools import capability_catalog as capability_catalog_module
from research_agent_teams.tools.capability_catalog import (
    build_capability_catalog,
    main,
    query_modes,
)
from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.validate_artifact import validate_against


def _modes_by_name(catalog):
    return {row["mode"]: row for row in catalog["modes"]}


def test_capability_catalog_is_schema_valid_and_no_write_surface():
    catalog = build_capability_catalog()
    assert validate_against("rat_capability_catalog.schema.json", catalog) == []
    assert catalog["schema_version"] == "1.1.0"
    assert catalog["validation"]["mode_registry_errors"] == []
    assert catalog["summary"]["vault_write"] is False
    assert catalog["summary"]["external_skill_execution"] is False
    assert catalog["summary"]["aers_import_policy"] == "reference_only"


def test_operated_modes_are_exactly_the_real_operate_registry():
    catalog = build_capability_catalog()
    operated = {row["mode"] for row in catalog["modes"] if row["status"] == "operated"}
    assert operated == set(REGISTRY)
    assert catalog["summary"]["operated_modes"] == len(REGISTRY)
    assert catalog["validation"]["operate_registry_drift"] == []
    for row in catalog["modes"]:
        if row["mode"] in REGISTRY:
            assert row["runnable_surface"] == "one_button_operate"
            assert row["operate_recipe_present"] is True
            assert row["product_maturity"] is None


def test_spec_only_modes_are_honestly_not_push_button():
    modes = _modes_by_name(build_capability_catalog())
    assert modes["design_experiment"]["status"] == "spec_only"
    assert modes["design_experiment"]["runnable_surface"] == "registry_defined_not_one_button"
    assert modes["design_experiment"]["operate_recipe_present"] is False
    assert "spec_only_not_push_button" in modes["design_experiment"]["honesty_notes"]
    assert "target_product_contract_not_implemented" in modes["design_experiment"]["honesty_notes"]


def test_every_spec_only_mode_has_a_machine_readable_target_product_contract():
    catalog = build_capability_catalog()
    spec_only = [row for row in catalog["modes"] if row["status"] == "spec_only"]
    assert len(spec_only) == 15
    assert catalog["summary"]["spec_only_product_contracts"] == len(spec_only)

    for row in spec_only:
        maturity = row["product_maturity"]
        assert maturity["level"] in {
            "engine_tested_spec_only",
            "registry_routable_spec_only",
        }
        assert maturity["reason"].strip()
        assert maturity["evidence_refs"]
        assert maturity["target_markdown"]["path"].startswith("director-review/")
        assert maturity["target_markdown"]["path"].endswith(".md")
        assert len(maturity["target_markdown"]["required_sections"]) >= 3
        assert len(maturity["productization_gaps"]) >= 2

        pipeline = maturity["minimum_worker_pipeline"]
        workers = {
            worker
            for stage in pipeline["stages"]
            for worker in stage["workers"]
        }
        assert pipeline["minimum_distinct_workers"] >= 2
        assert len(workers) >= pipeline["minimum_distinct_workers"]
        assert len(pipeline["stages"]) >= 2


def test_spec_only_maturity_matrix_and_target_markdown_paths_are_pinned():
    modes = _modes_by_name(build_capability_catalog())
    engine_tested = {
        "check_run",
        "gap_scan",
        "design_experiment",
        "design_experiment_minimal",
        "verify_result",
        "full_new_direction",
        "m2_accept",
        "ideate_ring",
        "debug_failed_run",
        "tree_explore",
    }
    registry_routable = {
        "power_analysis_review",
        "repo_code_audit",
        "analysis_audit_panel",
        "manuscript_review_pack",
        "aers_enhanced_research_pack",
    }
    assert {
        name
        for name, row in modes.items()
        if (row.get("product_maturity") or {}).get("level") == "engine_tested_spec_only"
    } == engine_tested
    assert {
        name
        for name, row in modes.items()
        if (row.get("product_maturity") or {}).get("level")
        == "registry_routable_spec_only"
    } == registry_routable

    expected_markdown = {
        "check_run": "director-review/operations/run-health-brief.md",
        "gap_scan": "director-review/gaps/gap-scan.md",
        "design_experiment": "director-review/experiments/experiment-design.md",
        "design_experiment_minimal": "director-review/experiments/minimal-experiment-design.md",
        "power_analysis_review": "director-review/experiments/power-analysis-review.md",
        "verify_result": "director-review/verification/result-verification.md",
        "full_new_direction": "director-review/ideas/full-new-direction-brief.md",
        "m2_accept": "director-review/experiments/m2-acceptance-report.md",
        "ideate_ring": "director-review/ideas/idea-bet-menu.md",
        "debug_failed_run": "director-review/experiments/debug-rerun-brief.md",
        "tree_explore": "director-review/experiments/experiment-tree-menu.md",
        "repo_code_audit": "director-review/code/repo-code-audit.md",
        "analysis_audit_panel": "director-review/analysis/analysis-audit-report.md",
        "manuscript_review_pack": "director-review/manuscript/manuscript-review-pack.md",
        "aers_enhanced_research_pack": "director-review/research/aers-enhanced-research-pack.md",
    }
    assert {
        name: modes[name]["product_maturity"]["target_markdown"]["path"]
        for name in expected_markdown
    } == expected_markdown

    summary = build_capability_catalog()["summary"]
    assert summary["spec_only_engine_tested_modes"] == 10
    assert summary["spec_only_registry_routable_modes"] == 5


def test_aers_pack_and_m2_accept_keep_execution_claims_honest():
    modes = _modes_by_name(build_capability_catalog())

    aers = modes["aers_enhanced_research_pack"]
    assert aers["execute_stage_present"] is True
    assert aers["requires_server_for_real_experiment"] is False
    assert "execute_stage_present_no_execution_claim_without_run_evidence" in aers["honesty_notes"]
    assert "must not be read as evidence that an experiment ran" in aers["product_maturity"]["reason"]

    m2_accept = modes["m2_accept"]
    assert m2_accept["requires_server_for_real_experiment"] is True
    assert "real server execution" in " ".join(
        m2_accept["product_maturity"]["productization_gaps"]
    )


def test_catalog_validation_rejects_missing_contract_and_unknown_pipeline_worker(monkeypatch):
    registry = copy.deepcopy(load_mode_registry())
    del registry["modes"]["design_experiment"]["product_maturity"]
    registry["modes"]["power_analysis_review"]["product_maturity"][
        "minimum_worker_pipeline"
    ]["stages"][0]["workers"] = ["not-a-real-worker"]
    monkeypatch.setattr(capability_catalog_module, "load_mode_registry", lambda: registry)

    errors = build_capability_catalog()["validation"]["mode_registry_errors"]
    assert any("design_experiment.product_maturity missing" in error for error in errors)
    assert any("unknown agent: not-a-real-worker" in error for error in errors)


def test_capability_schema_requires_product_contract_for_spec_only_rows():
    catalog = build_capability_catalog()
    mode = next(row for row in catalog["modes"] if row["mode"] == "design_experiment")
    mode["product_maturity"] = None
    assert validate_against("rat_capability_catalog.schema.json", catalog) != []


def test_server_and_execute_boundaries_are_explicit():
    modes = _modes_by_name(build_capability_catalog())
    full_rigor = modes["full_rigor_minimal"]
    assert full_rigor["status"] == "operated"
    assert full_rigor["execute_stage_present"] is True
    assert full_rigor["requires_server_for_real_experiment"] is True
    assert "real_experiment_execution_requires_server_evidence" in full_rigor["honesty_notes"]

    repo_audit = modes["repo_code_audit"]
    assert repo_audit["execute_stage_present"] is True
    assert repo_audit["requires_server_for_real_experiment"] is False
    assert "execute_stage_present_no_execution_claim_without_run_evidence" in repo_audit["honesty_notes"]


def test_query_modes_filters_without_hiding_honesty_fields():
    venue_modes = query_modes(status="operated", stage="VERIFY", intent="prep_submission")
    assert {row["mode"] for row in venue_modes} == {"full_rigor_minimal", "venue_readiness"}
    assert all(row["runnable_surface"] == "one_button_operate" for row in venue_modes)

    server_modes = query_modes(requires_server_for_real_experiment=True)
    assert {row["mode"] for row in server_modes} >= {"full_rigor_minimal", "m2_accept"}
    assert all("real_experiment_execution_requires_server_evidence" in row["honesty_notes"]
               for row in server_modes)

    engine_tested_spec_only = query_modes(maturity_level="engine_tested_spec_only")
    assert {row["mode"] for row in engine_tested_spec_only} == {
        "check_run",
        "gap_scan",
        "design_experiment",
        "design_experiment_minimal",
        "verify_result",
        "full_new_direction",
        "m2_accept",
        "ideate_ring",
        "debug_failed_run",
        "tree_explore",
    }


def test_capability_catalog_cli_rejects_default_vault_out():
    blocked = default_vault_root() / "_blocked-capability-catalog.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        main(["--out", str(blocked)])
    assert not blocked.exists()
