from __future__ import annotations

import copy
import json
import socket
import subprocess
import urllib.request

import pytest

from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools import research_capability_router as router

# Derived, never hardcoded. A literal `<= 5` here is what let the external-method channel stay
# capped at five lenses per run while the catalog grew — the assertion agreed with the cap instead
# of describing it. Reading the policy means widening the channel needs no test edit.
_POLICY = json.loads(router.DEFAULT_OVERLAY_CATALOG.read_text(encoding="utf-8"))["policy"]
_POLICY_MIN = int(_POLICY["selection_min"])
_POLICY_MAX = int(_POLICY["selection_max"])


REQUIRED_OVERLAYS = {
    "hypothesis_prediction_contract",
    "power_unit_of_analysis_contract",
    "results_to_claim_contract",
    "blind_handoff_contract",
    "submission_freshness_contract",
    "dicom_data_audit",
    "figure_contract_qa",
    "offline_drawio_adapter",
    "cross_domain_mechanism_translation",
    "methods_motivation_mechanism_evidence",
    "review_axes_contract",
}


def _overlay_ids(route):
    return {item["overlay_id"] for item in route["capability_overlays"]}


def test_catalog_is_safe_provenance_bound_metadata():
    catalog = router.load_overlay_catalog()
    assert catalog["policy"]["network_default"] == "DENY"
    assert catalog["policy"]["external_execution"] is False
    assert catalog["policy"]["copy_third_party_code"] is False
    assert catalog["policy"]["copy_third_party_long_text"] is False
    assert REQUIRED_OVERLAYS.issubset({o["overlay_id"] for o in catalog["overlays"]})
    source_ids = {source["source_id"] for source in catalog["sources"]}
    for overlay in catalog["overlays"]:
        assert overlay["provenance_refs"]
        assert set(overlay["provenance_refs"]).issubset(source_ids)
    for source in catalog["sources"]:
        assert len(source["commit"]) == 40
        int(source["commit"], 16)


def test_chinese_experiment_request_auto_routes_operated_full_rigor_and_dicom_overlay():
    route = router.route_research_capabilities(
        "请为 PET/CT DICOM 患者级数据设计实验，并明确样本量和预测。"
    )
    known_modes = load_mode_registry()["modes"]
    assert route["routing"]["mode"] == "full_rigor_minimal"
    assert route["routing"]["mode"] in known_modes
    assert route["routing"]["selection_source"] == "automatic_suggestion"
    assert route["routing"]["honesty"]["state"] == "operated"
    assert route["routing"]["honesty"]["one_button_operable"] is True
    assert "dicom_data_audit" in _overlay_ids(route)
    assert "power_unit_of_analysis_contract" in _overlay_ids(route)
    assert _POLICY_MIN <= len(route["capability_overlays"]) <= _POLICY_MAX


def test_english_request_auto_routes_existing_evidence_mode():
    route = router.route_research_capabilities(
        "Run a literature review and evidence synthesis for the proposed biomarker."
    )
    assert route["routing"]["mode"] == "evidence_deep"
    assert route["routing"]["honesty"]["state"] == "operated"
    assert "results_to_claim_contract" in _overlay_ids(route)


def test_cross_domain_request_requires_mechanism_not_analogy_as_evidence():
    route = router.route_research_capabilities(
        "把教育学最小提示和认知科学主动感知用于医学交互分割，并设计可证伪实验。"
    )
    overlay = next(
        item for item in route["capability_overlays"]
        if item["overlay_id"] == "cross_domain_mechanism_translation"
    )
    assert "treat_analogy_as_evidence" in overlay["non_goals"]
    contract = " ".join([overlay["summary"], *overlay["non_goals"]])
    for required in {
        "source_ref",
        "borrowed_principle",
        "target_mapping",
        "preserved_and_broken_assumptions",
        "evidence_status",
        "prior_art_collision_status",
        "falsifier",
        "UNVERIFIED",
    }:
        assert required in contract


def test_routine_request_does_not_force_mechanism_council():
    route = router.route_research_capabilities("请精读这篇论文并提取主要结论。")
    assert route["mechanism_council_plan"]["enabled"] is False
    assert route["mechanism_council_plan"]["selected_roles"] == []


def test_state_relative_cross_disciplinary_request_activates_full_council():
    route = router.route_research_capabilities(
        "研究 M0 状态相对的 scribble intent，并由数学、认知和工程角色设计可证伪机制。"
    )
    council = route["mechanism_council_plan"]
    assert council["enabled"] is True
    assert len(council["selected_roles"]) == 7
    assert council["waves"][-1] == ["hypothesis_compiler"]


def test_manual_compiler_override_adds_dependency_closure():
    route = router.route_research_capabilities(
        "普通研究请求。",
        manual_council_roles=["hypothesis_compiler"],
    )
    council = route["mechanism_council_plan"]
    assert council["enabled"] is True
    assert council["selection_source"] == "manual_override"
    assert len(council["selected_roles"]) == 7
    assert set(council["auto_added_dependencies"]) == set(council["selected_roles"]) - {
        "hypothesis_compiler"
    }


def test_manual_mode_override_has_priority_over_request_and_preserves_honesty():
    route = router.route_research_capabilities(
        "Design an experiment and calculate power.",
        explicit_mode="read_paper_deep",
    )
    assert route["routing"]["mode"] == "read_paper_deep"
    assert route["routing"]["selection_source"] == "manual_override"
    assert route["routing"]["matched_signals"] == ["explicit_mode:read_paper_deep"]
    assert route["routing"]["honesty"]["state"] == "operated"
    assert route["routing"]["honesty"]["one_button_operable"] is True


def test_unknown_manual_mode_is_rejected_instead_of_invented():
    with pytest.raises(router.ResearchCapabilityRouterError, match="unknown explicit mode"):
        router.route_research_capabilities("Do research.", explicit_mode="magic_new_mode")


@pytest.mark.parametrize(
    ("kind", "prompt_text", "expected_mode", "expected_overlays"),
    [
        (
            "quantitative_figure",
            "Create a result plot with uncertainty and a caption.",
            # _PUBLICATION_MODE_PREFERENCES has always listed analysis_audit_panel FIRST for this
            # kind, with manuscript_authoring as the fallback for while it was spec-only. Wave 2
            # (2026-08-04) wired it, so the declared first preference is finally the live one — the
            # expected overlays are unchanged, which is what says the routing is still right.
            "analysis_audit_panel",
            {"figure_contract_qa", "results_to_claim_contract"},
        ),
        (
            "scientific_diagram",
            "Create an offline drawio architecture diagram.",
            "manuscript_authoring",
            {"offline_drawio_adapter", "figure_contract_qa"},
        ),
        (
            "manuscript_methods",
            "Write reproducible methods for this model and experiment.",
            "manuscript_authoring",
            {
                "methods_motivation_mechanism_evidence",
                "power_unit_of_analysis_contract",
            },
        ),
        (
            "manuscript_review",
            "Conduct an independent manuscript review.",
            "manuscript_review",
            {"review_axes_contract", "blind_handoff_contract"},
        ),
    ],
)
def test_publication_kinds_select_bounded_purpose_specific_overlays(
    kind, prompt_text, expected_mode, expected_overlays
):
    route = router.route_research_capabilities(prompt_text, publication_kind=kind)
    assert route["publication_kind"] == kind
    assert route["routing"]["mode"] == expected_mode
    assert expected_overlays.issubset(_overlay_ids(route))
    assert _POLICY_MIN <= len(route["capability_overlays"]) <= _POLICY_MAX


def test_every_automatic_suggestion_is_operated_in_live_mode_registry():
    known = {
        mode for mode, spec in load_mode_registry()["modes"].items()
        if spec.get("operated") is True
    }
    requests = [
        "Find a research gap.",
        "Deep read this paper.",
        "Audit the repository code.",
        "Verify result claims.",
        "Write the paper.",
        "Completely unfamiliar general request.",
    ]
    for request in requests:
        route = router.route_research_capabilities(request)
        assert route["routing"]["mode"] in known
        assert route["routing"]["honesty"]["one_button_operable"] is True


@pytest.mark.parametrize(
    ("request_text", "expected_mode"),
    [
        ("帮我精读这篇论文", "read_paper_deep"),
        ("把这篇论文收进库", "ingest_paper"),
        ("设计这个实验", "full_rigor_minimal"),
        ("审一遍我的稿", "manuscript_review"),
        ("帮我写论文初稿", "manuscript_authoring"),
        ("够投顶会吗", "venue_readiness"),
        ("扫一遍空白点", "gap_breadth"),
    ],
)
def test_utf8_plan_catalog_phrasing_routes_to_expected_operated_mode(request_text, expected_mode):
    resolution = router.resolve_operated_mode(request_text)
    assert resolution["mode"] == expected_mode
    route = router.route_research_capabilities(request_text)
    assert route["routing"]["mode"] == expected_mode
    assert route["routing"]["honesty"]["one_button_operable"] is True


def test_route_is_metadata_only_and_does_not_call_network_or_process(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    route = router.route_research_capabilities(
        "设计一张离线科研流程图。",
        publication_kind="scientific_diagram",
    )
    assert route["safety"] == {
        "network_default": "DENY",
        "external_execution": False,
        "third_party_code_copied": False,
        "third_party_long_text_copied": False,
        "forbidden_actions": [
            "auto_update",
            "hook",
            "installer",
            "mcp",
            "whole_repo_execution",
        ],
        "side_effects": [],
    }


def test_selected_overlays_expand_commit_pinned_provenance():
    route = router.route_research_capabilities(
        "Review the manuscript figures and claims.",
        publication_kind="manuscript_review",
    )
    for overlay in route["capability_overlays"]:
        assert overlay["provenance"]
        for source in overlay["provenance"]:
            assert source["repository"].startswith("https://github.com/")
            assert len(source["commit"]) == 40
            int(source["commit"], 16)
            assert source["admission"]


def test_utf8_json_output_preserves_chinese(tmp_path):
    out = tmp_path / "route.json"
    exit_code = router.main(
        [
            "请设计 PET/CT 实验并审计 DICOM 数据。",
            "--mode",
            "design_experiment",
            "--out",
            str(out),
        ]
    )
    assert exit_code == 0
    raw = out.read_bytes()
    assert "请设计".encode("utf-8") in raw
    decoded = json.loads(raw.decode("utf-8"))
    assert decoded["request_text"].startswith("请设计")
    assert decoded["routing"]["selection_source"] == "manual_override"


def test_unknown_publication_kind_is_rejected():
    with pytest.raises(router.ResearchCapabilityRouterError, match="unknown publication_kind"):
        router.route_research_capabilities("Make output.", publication_kind="poster")


def test_in_memory_catalog_cannot_reference_rejected_source():
    catalog = copy.deepcopy(router.load_overlay_catalog())
    catalog["overlays"][0]["provenance_refs"] = ["drawio_scientific_illustrator"]
    with pytest.raises(router.ResearchCapabilityRouterError, match="non-selectable"):
        router.route_research_capabilities("Do research.", overlay_catalog=catalog)


def test_in_memory_catalog_cannot_mutate_source_lock():
    catalog = copy.deepcopy(router.load_overlay_catalog())
    catalog["sources"][0]["commit"] = "0" * 40
    with pytest.raises(router.ResearchCapabilityRouterError, match="differs from source lock"):
        router.route_research_capabilities("Do research.", overlay_catalog=catalog)
