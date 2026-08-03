from __future__ import annotations

import pytest

from research_agent_teams.tools.research_visual_router import (
    ResearchVisualRouterError,
    route_visual,
)


def test_quantitative_plot_requires_frozen_real_data_for_citable_delivery():
    real = route_visual("metric_table", data_status="FROZEN_REAL_RESULTS")
    assert real["lane"] == "quantitative_plot"
    assert real["may_render_now"] is True
    assert real["delivery_status"] == "CITABLE_IF_UPSTREAM_AUDITS_PASS"

    missing = route_visual("result_table", data_status="UNVERIFIED")
    assert missing["may_render_now"] is False
    assert missing["delivery_status"] == "BLOCKED_MISSING_FROZEN_DATA"


def test_mock_plot_is_explicitly_watermarked_and_non_citable():
    route = route_visual("statistical_summary", data_status="MOCK")
    assert route["delivery_status"] == "PROTOTYPE_NON_CITABLE"
    assert route["watermark"] == "MOCK DATA — NOT A SCIENTIFIC RESULT"


def test_method_graph_and_editable_canvas_are_distinct_lanes():
    diagram = route_visual("mechanism_graph")
    canvas = route_visual("mechanism_graph", editable_required=True)
    assert diagram["lane"] == "scientific_diagram"
    assert canvas["lane"] == "editable_canvas"
    assert "DRAWIO" not in diagram["outputs"]
    assert "DRAWIO" in canvas["outputs"]
    assert canvas["implementation_status"] == "PLANNED_ADAPTER"
    assert canvas["may_render_now"] is False


def test_manual_override_is_preserved_but_cannot_violate_editable_requirement():
    route = route_visual("workflow", manual_lane="editable_canvas")
    assert route["selection_source"] == "manual_override"
    with pytest.raises(ResearchVisualRouterError, match="editable_required"):
        route_visual("workflow", editable_required=True, manual_lane="scientific_diagram")


def test_visual_router_never_enables_external_execution_or_network():
    for kind, kwargs in (
        ("metric_table", {"data_status": "MOCK"}),
        ("scientific_diagram", {}),
        ("drawio", {}),
    ):
        route = route_visual(kind, **kwargs)
        assert set(route["safety"].values()) == {False}

