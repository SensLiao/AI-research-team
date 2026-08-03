"""Pre-registered smoke matrix for the 2026-07-31 single-entry capability overlays.

These fixtures validate routing and research-quality lens selection only.  They do not create
projects, operate spec-only modes, contact external systems, or claim scientific improvement.
"""
from __future__ import annotations

from research_agent_teams.tools.research_capability_router import route_research_capabilities


def _ids(route: dict) -> set[str]:
    return {item["overlay_id"] for item in route["capability_overlays"]}


def test_s1_petct_bidirectional_experiment_design():
    route = route_research_capabilities(
        "为 patient-disjoint PSMA PET/CT 六类 ADD/REMOVE residual correction 做实验设计，"
        "给出患者级功效依据、竞争假设和能推翻 intent 机制的预测。"
    )
    assert route["routing"]["mode"] == "full_rigor_minimal"
    assert route["routing"]["honesty"]["state"] == "operated"
    assert {"hypothesis_prediction_contract", "power_unit_of_analysis_contract"}.issubset(_ids(route))


def test_s2_cross_domain_idea_is_forced_into_mechanism_and_falsifier():
    route = route_research_capabilities(
        "寻找研究方向：把认知科学主动感知、教育学最小提示和控制论反馈用于医学交互分割。"
    )
    assert route["routing"]["mode"] == "new_direction"
    assert "cross_domain_mechanism_translation" in _ids(route)
    selected = next(
        item for item in route["capability_overlays"]
        if item["overlay_id"] == "cross_domain_mechanism_translation"
    )
    assert "treat_analogy_as_evidence" in selected["non_goals"]
    contract = " ".join([selected["summary"], *selected["non_goals"]])
    for required in (
        "source_ref",
        "borrowed_principle",
        "target_mapping",
        "preserved_and_broken_assumptions",
        "evidence_status",
        "prior_art_collision_status",
        "falsifier",
        "UNVERIFIED",
    ):
        assert required in contract


def test_s3_conflicting_evidence_keeps_result_claim_boundary():
    route = route_research_capabilities(
        "做文献综述和证据综合：两篇 AI-for-science 论文结论冲突，检查结果、分析单位和过度主张。"
    )
    assert route["routing"]["mode"] == "evidence_deep"
    assert "results_to_claim_contract" in _ids(route)


def test_s4_quantitative_figure_and_diagram_use_distinct_output_lenses():
    quantitative = route_research_capabilities(
        "根据冻结结果表生成带不确定性的主结果图和 caption。",
        publication_kind="quantitative_figure",
    )
    diagram = route_research_capabilities(
        "生成离线 drawio 方法流程图。",
        publication_kind="scientific_diagram",
    )
    assert "figure_contract_qa" in _ids(quantitative)
    assert "offline_drawio_adapter" not in _ids(quantitative)
    assert {"figure_contract_qa", "offline_drawio_adapter"}.issubset(_ids(diagram))
    assert quantitative["safety"]["external_execution"] is False
    assert diagram["safety"]["network_default"] == "DENY"


def test_s5_submission_review_selects_blindness_review_and_freshness():
    route = route_research_capabilities(
        "对完整稿件做同行评审和投稿就绪检查，复核 claims、统计、图表、引用和新证据。",
        publication_kind="manuscript_review",
    )
    assert route["routing"]["mode"] == "manuscript_review"
    assert route["routing"]["honesty"]["state"] == "operated"
    assert {
        "blind_handoff_contract",
        "review_axes_contract",
        "submission_freshness_contract",
    }.issubset(_ids(route))
