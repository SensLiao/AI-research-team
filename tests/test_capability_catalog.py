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
    # Exemplar swapped 2026-08-04: design_experiment is one-button now, so the honesty note it used
    # to demonstrate had to move to a mode that is still hand-driven.
    assert modes["tree_explore"]["status"] == "spec_only"
    assert modes["tree_explore"]["runnable_surface"] == "registry_defined_not_one_button"
    assert modes["tree_explore"]["operate_recipe_present"] is False
    assert "spec_only_not_push_button" in modes["tree_explore"]["honesty_notes"]
    assert "target_product_contract_not_implemented" in modes["tree_explore"]["honesty_notes"]

def test_every_spec_only_mode_has_a_machine_readable_target_product_contract():
    catalog = build_capability_catalog()
    spec_only = [row for row in catalog["modes"] if row["status"] == "spec_only"]
    # 5 -> 3 (2026-08-07): ideate_ring and aers_enhanced_research_pack closed the wave-2 backlog.
    assert len(spec_only) == 3
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
    # Wave 2 (2026-08-04) wired nine of these; the 2026-08-07 backlog close wired the remaining
    # two (ideate_ring, aers_enhanced_research_pack). A wired mode MUST NOT keep a
    # product_maturity block (the catalog validator calls it "reserved for modes without
    # operated:true"), so its director-Markdown contract moved into `handoff` — asserted below,
    # so wiring a mode can never silently drop the path that used to be pinned here.
    engine_tested = {
        "design_experiment_minimal",
        "debug_failed_run",
        "tree_explore",
    }
    registry_routable: set[str] = set()
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
        "design_experiment_minimal": "director-review/experiments/minimal-experiment-design.md",
        "debug_failed_run": "director-review/experiments/debug-rerun-brief.md",
        "tree_explore": "director-review/experiments/experiment-tree-menu.md",
    }
    assert {
        name: modes[name]["product_maturity"]["target_markdown"]["path"]
        for name in expected_markdown
    } == expected_markdown

    # The eleven wave-2 modes keep the SAME director-facing paths they were promised as
    # spec-only — now under `handoff`, where an operated mode's product contract lives. Same
    # promise, new home.
    registry = load_mode_registry()["modes"]
    wired_markdown = {
        "check_run": "director-review/operations/run-health-brief.md",
        "gap_scan": "director-review/gaps/gap-scan.md",
        "design_experiment": "director-review/experiments/experiment-design.md",
        "power_analysis_review": "director-review/experiments/power-analysis-review.md",
        "verify_result": "director-review/verification/result-verification.md",
        "full_new_direction": "director-review/ideas/full-new-direction-brief.md",
        "m2_accept": "director-review/experiments/m2-acceptance-report.md",
        "repo_code_audit": "director-review/code/repo-code-audit.md",
        "analysis_audit_panel": "director-review/analysis/analysis-audit-report.md",
        "ideate_ring": "director-review/ideas/idea-bet-menu.md",
        "aers_enhanced_research_pack": "director-review/research/aers-enhanced-research-pack.md",
    }
    assert {
        name: registry[name]["handoff"]["primary_markdown"] for name in wired_markdown
    } == wired_markdown
    for name in wired_markdown:
        assert "product_maturity" not in registry[name], (
            f"{name} is operated and must not keep a target contract it has already met")
        assert registry[name]["handoff"]["required_sections"], (
            f"{name} lost the required_sections its renderer BLOCKs on")

    summary = build_capability_catalog()["summary"]
    assert summary["spec_only_engine_tested_modes"] == 3
    assert summary["spec_only_registry_routable_modes"] == 0


def test_manuscript_modes_are_distinct_operated_contracts_with_no_phantom_review_pack():
    registry_modes = load_mode_registry()["modes"]
    catalog_modes = _modes_by_name(build_capability_catalog())

    assert "manuscript_review_pack" not in registry_modes
    assert "manuscript_review_pack" not in catalog_modes
    assert {"manuscript_authoring", "manuscript_review"} <= set(REGISTRY)

    authoring = registry_modes["manuscript_authoring"]
    review = registry_modes["manuscript_review"]
    assert authoring["operated"] is True
    assert review["operated"] is True
    assert "product_maturity" not in authoring
    assert "product_maturity" not in review
    for name in ("manuscript_authoring", "manuscript_review"):
        assert catalog_modes[name]["status"] == "operated"
        assert catalog_modes[name]["runnable_surface"] == "one_button_operate"
        assert catalog_modes[name]["operate_recipe_present"] is True
    assert authoring["stage_path"] == ["DISCOVER", "DESIGN", "ANALYZE", "VERIFY", "REPORT"]
    assert review["stage_path"] == ["VERIFY", "REPORT"]
    assert authoring["handoff"]["product_version"] == "manuscript-authoring/v1"
    assert review["handoff"]["product_version"] == "manuscript-review/v1"
    assert review["handoff"]["accepts"] == ["manuscript-authoring/v1"]
    assert authoring["handoff"]["evidence_namespace"] != review["handoff"]["evidence_namespace"]
    assert set(authoring["handoff"]["reusable_artifacts"]).isdisjoint(
        review["handoff"]["reusable_artifacts"]
    )


def test_capability_catalog_rejects_a_yaml_only_manuscript_operated_claim(monkeypatch):
    recipes = set(REGISTRY)
    recipes.remove("manuscript_review")
    monkeypatch.setattr(capability_catalog_module, "operate_recipe_names", lambda: recipes)

    catalog = build_capability_catalog()

    assert "manuscript_review:claimed_operated_without_recipe" in catalog["validation"][
        "operate_registry_drift"
    ]


def test_manuscript_authoring_contract_is_sparse_adaptive_and_section_complete():
    mode = load_mode_registry()["modes"]["manuscript_authoring"]
    contract = mode["authoring_contract"]
    scheduler = mode["scheduler_contract"]
    fixture_contract = mode["paper_type_contract_fixtures"]
    fixtures = fixture_contract["cases"]

    specialized = {
        "introduction": "manuscript-introduction-author",
        "related_work": "manuscript-related-work-author",
        "methods": "manuscript-methods-author",
        "results": "manuscript-results-author",
    }
    assert contract["specialized_owners"] == specialized
    assert contract["remaining_required_section_owner"] == "manuscript-section-author"
    assert contract["candidate_artifact_type"] == "manuscript_section_bundle"
    assert contract["candidate_bundles_per_required_section"] == 1
    assert contract["integrator"] == "manuscript-integrator"
    assert contract["integrator_may_author_missing_prose"] is False
    assert contract["generation_evidence_eligible_as_independent_review"] is False
    assert contract["instance_isolation"]["cross_mode_instance_or_receipt_reuse"] == "forbidden"
    assert scheduler["dependency_model"] == "sparse_dag"
    assert scheduler["adaptive_instances"]["fixed_section_worker_count"] is False
    assert fixture_contract["fixed_section_count"] is False
    assert set(fixtures) == {"empirical", "theory", "dataset", "survey", "system"}

    section_lengths = set()
    for fixture in fixtures.values():
        sections = fixture["required_sections"]
        section_lengths.add(len(sections))
        assert len(sections) == len(set(sections))
        assert "abstract" in sections
        assert {"discussion", "conclusion"} & set(sections)
        assert {"limitations", "ethics_statement"} & set(sections)
        assert "appendix" in sections
        assert any(section.startswith("venue_") for section in sections)
        assignments = {
            section: specialized.get(section, contract["remaining_required_section_owner"])
            for section in sections
        }
        assert set(assignments) == set(sections)
        assert all(assignments[section] == specialized[section]
                   for section in set(sections) & set(specialized))
        assert all(
            assignments[section] == "manuscript-section-author"
            for section in set(sections) - set(specialized)
        )
    assert len(section_lengths) > 1

    groups = {row["id"]: row for row in scheduler["parallel_groups"]}
    assert len(groups) == len(scheduler["parallel_groups"])
    assert "manuscript-section-author" in groups["author_candidates"]["workers"]
    assert groups["integrate_canonical_tree"]["depends_on"] == ["author_candidates"]
    assert groups["independent_authoring_audits"]["depends_on"] == [
        "integrate_canonical_tree"
    ]


def test_manuscript_review_contract_requires_blind_capability_closure_and_join():
    mode = load_mode_registry()["modes"]["manuscript_review"]
    contract = mode["review_contract"]
    required_capabilities = {
        "domain_contribution",
        "methods_reproducibility",
        "figure_table",
        "factual",
        "citation",
        "venue_style_latex",
    }

    assert set(contract["frozen_input_hashes"]) == {
        "contract_sha256", "manuscript_sha256", "source_tree_sha256", "pdf_sha256"
    }
    assert set(contract["required_capability_ids"]) == required_capabilities
    assert set(contract["capability_workers"]) == required_capabilities
    assert set(contract["capability_workers"].values()) <= set(mode["agent_subset"])
    blind = contract["blind_authorization"]
    assert blind["minimum_distinct_reviewer_receipts"] == 2
    assert blind["distinct_reviewer_instance_ids"] is True
    assert blind["review_run_must_differ_from_authoring_run"] is True
    assert blind["authoring_receipts_count_as_review_receipts"] is False
    assert blind["authoring_reviewer_instance_ids_may_be_reused"] is False
    assert blind["one_capability_bound_receipt_per_verdict"] is True
    assert blind["sibling_conclusions_visible_before_freeze"] is False
    assert blind["generation_evidence_counts_as_independent_review"] is False

    join = contract["reconciliation_join"]
    assert join["kind"] == "deterministic_meta_review"
    assert join["strategy"] == "deterministic_reducer_then_meta_review"
    assert join["require_exact_capability_set"] is True
    assert join["require_frozen_verdicts"] is True
    assert join["preserve_minority_findings"] is True
    groups = {row["id"]: row for row in contract["parallel_groups"]}
    assert set(groups["blind_capability_reviews"]["workers"]) == set(
        contract["capability_workers"].values()
    )
    authoring_contract = load_mode_registry()["modes"]["manuscript_authoring"][
        "authoring_contract"
    ]
    authoring_isolation = authoring_contract["instance_isolation"]
    review_isolation = contract["instance_isolation"]
    assert authoring_isolation["cross_mode_instance_or_receipt_reuse"] == "forbidden"
    assert review_isolation["cross_mode_instance_or_receipt_reuse"] == "forbidden"
    assert authoring_isolation["run_id_scope"] != review_isolation["run_id_scope"]
    assert authoring_isolation["authorization_receipt_scope"] != review_isolation[
        "authorization_receipt_scope"
    ]
    assert authoring_isolation["blind_scope"] != review_isolation["blind_scope"]
    assert groups["deterministic_reconciliation_and_meta_review"]["depends_on"] == [
        "blind_capability_reviews"
    ]


def test_aers_pack_and_m2_accept_keep_execution_claims_honest():
    modes = _modes_by_name(build_capability_catalog())

    aers = modes["aers_enhanced_research_pack"]
    assert aers["status"] == "operated"
    assert aers["execute_stage_present"] is True
    assert aers["requires_server_for_real_experiment"] is False
    assert "execute_stage_present_no_execution_claim_without_run_evidence" in aers["honesty_notes"]
    # aers_enhanced_research_pack became one-button on 2026-08-07, so `product_maturity` is now
    # None (reserved for spec-only modes) — the honesty text it used to carry moved verbatim into
    # the registry's own `handoff.purpose`, asserted directly rather than through the catalog row.
    assert aers["product_maturity"] is None
    registry_aers = load_mode_registry()["modes"]["aers_enhanced_research_pack"]
    assert "must not be read as evidence that an experiment ran" in registry_aers["handoff"]["purpose"]

    # m2_accept became one-button on 2026-08-04, so the promise that used to live in its
    # productization_gaps ("integrate real server execution before any result claim") is no longer a
    # TODO — it is enforced in the recipe. Assert the enforcement, not the removed prose: the mode
    # still declares it needs a server, and its recipe routes every metric through the one canonical
    # planned-vs-ran classifier, which refuses numbers without a verified receipt.
    import inspect

    from research_agent_teams.operate.modes import m2_accept as m2_recipe

    m2_accept = modes["m2_accept"]
    assert m2_accept["status"] == "operated"
    assert m2_accept["requires_server_for_real_experiment"] is True
    assert "real_experiment_execution_requires_server_evidence" in m2_accept["honesty_notes"]
    source = inspect.getsource(m2_recipe)
    assert "refuse_metrics_without_receipt" in source, (
        "m2_accept must gate every metric on a verified execution receipt")
    assert "execution_truth" in source, (
        "m2_accept must use the single canonical planned-vs-ran classifier, not a local re-decision")


def test_catalog_validation_rejects_missing_contract_and_unknown_pipeline_worker(monkeypatch):
    # Exemplar swapped 2026-08-07: ideate_ring is one-button now and no longer carries a
    # product_maturity block to corrupt, so debug_failed_run (still spec-only) demonstrates the
    # unknown-pipeline-worker half of this test instead.
    registry = copy.deepcopy(load_mode_registry())
    del registry["modes"]["tree_explore"]["product_maturity"]
    registry["modes"]["debug_failed_run"]["product_maturity"][
        "minimum_worker_pipeline"
    ]["stages"][0]["workers"] = ["not-a-real-worker"]
    monkeypatch.setattr(capability_catalog_module, "load_mode_registry", lambda: registry)

    errors = build_capability_catalog()["validation"]["mode_registry_errors"]
    assert any("tree_explore.product_maturity missing" in error for error in errors)
    assert any("unknown agent: not-a-real-worker" in error for error in errors)


def test_capability_schema_requires_product_contract_for_spec_only_rows():
    catalog = build_capability_catalog()
    mode = next(row for row in catalog["modes"] if row["mode"] == "tree_explore")
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
        "design_experiment_minimal",
        "debug_failed_run",
        "tree_explore",
    }


def test_capability_catalog_cli_rejects_default_vault_out():
    blocked = default_vault_root() / "_blocked-capability-catalog.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        main(["--out", str(blocked)])
    assert not blocked.exists()
