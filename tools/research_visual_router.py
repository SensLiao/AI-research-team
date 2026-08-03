"""Route research visuals into plot, scientific-diagram, or editable-canvas lanes.

This is a deterministic design/QA router.  It never renders, invents data, opens a browser, invokes an
MCP server, or upgrades a planned adapter to an implemented capability.
"""
from __future__ import annotations

from typing import Any, Optional


LANES: dict[str, dict[str, Any]] = {
    "quantitative_plot": {
        "accepts": {"result_table", "metric_table", "statistical_summary", "quantitative_figure"},
        "source_contract": "frozen numeric table + analysis unit + uncertainty + metric direction",
        "outputs": ["SVG", "PDF", "PNG", "plot-spec.json"],
        "implementation_status": "OPERATED_SPEC_AND_QA_RENDERER_OUT_OF_SCOPE",
        "qa": [
            "data-to-mark traceability",
            "analysis-unit and uncertainty visibility",
            "axis, scale, legend, palette, font, and DPI checks",
            "caption-to-claim consistency",
        ],
    },
    "scientific_diagram": {
        "accepts": {"mechanism_graph", "method_architecture", "workflow", "scientific_diagram"},
        "source_contract": "reviewed declarative graph + node/edge semantics + claim boundary",
        "outputs": ["SVG", "PDF", "PNG", "diagram-spec.json"],
        "implementation_status": "PLANNED_ADAPTER",
        "qa": [
            "semantic node and edge coverage",
            "reading order and visual hierarchy",
            "method-to-caption consistency",
            "no quantitative claim encoded without data",
        ],
    },
    "editable_canvas": {
        "accepts": {"editable_diagram", "drawio", "architecture_canvas", "flowchart"},
        "source_contract": "reviewed declarative graph + pinned offline adapter arguments",
        "outputs": ["DRAWIO", "SVG", "PDF", "adapter-receipt.json"],
        "implementation_status": "PLANNED_ADAPTER",
        "qa": [
            "source graph hash and adapter version receipt",
            "round-trip editable node identity",
            "offline allowlisted invocation only",
            "export readability and clipping checks",
        ],
    },
}


class ResearchVisualRouterError(ValueError):
    """Raised when a visual request would cross a truth or adapter boundary."""


def _automatic_lane(artifact_kind: str, *, editable_required: bool) -> str:
    if editable_required:
        return "editable_canvas"
    matches = [lane for lane, spec in LANES.items() if artifact_kind in spec["accepts"]]
    if len(matches) != 1:
        raise ResearchVisualRouterError(
            f"artifact_kind {artifact_kind!r} is not uniquely routable; use a supported kind or manual_lane"
        )
    return matches[0]


def route_visual(
    artifact_kind: str,
    *,
    data_status: str = "NOT_APPLICABLE",
    editable_required: bool = False,
    manual_lane: Optional[str] = None,
) -> dict[str, Any]:
    """Return one lane and its non-executing contract.

    For quantitative plots, only ``FROZEN_REAL_RESULTS`` is citable. ``MOCK`` remains visible as a
    prototype, while missing/unverified data blocks rendering. Diagrams may be designed without numeric
    results but cannot encode unsupported quantitative claims.
    """
    kind = str(artifact_kind or "").strip().lower()
    if not kind:
        raise ResearchVisualRouterError("artifact_kind must be non-empty")
    status = str(data_status or "").strip().upper()
    if manual_lane is not None:
        lane = str(manual_lane).strip()
        if lane not in LANES:
            raise ResearchVisualRouterError(f"unknown manual_lane {lane!r}; valid: {sorted(LANES)}")
        selection_source = "manual_override"
    else:
        lane = _automatic_lane(kind, editable_required=editable_required)
        selection_source = "automatic_kind_router"

    if editable_required and lane != "editable_canvas":
        raise ResearchVisualRouterError("editable_required can only route to editable_canvas")

    if lane == "quantitative_plot":
        if status == "FROZEN_REAL_RESULTS":
            delivery = "CITABLE_IF_UPSTREAM_AUDITS_PASS"
            may_render = True
            watermark = None
        elif status == "MOCK":
            delivery = "PROTOTYPE_NON_CITABLE"
            may_render = True
            watermark = "MOCK DATA — NOT A SCIENTIFIC RESULT"
        else:
            delivery = "BLOCKED_MISSING_FROZEN_DATA"
            may_render = False
            watermark = None
    else:
        delivery = "DESIGN_ONLY_NON_RESULT"
        may_render = LANES[lane]["implementation_status"] != "PLANNED_ADAPTER"
        watermark = None

    spec = LANES[lane]
    return {
        "contract_version": "research-visual-route/v1",
        "artifact_kind": kind,
        "lane": lane,
        "selection_source": selection_source,
        "data_status": status,
        "source_contract": spec["source_contract"],
        "outputs": list(spec["outputs"]),
        "implementation_status": spec["implementation_status"],
        "qa": list(spec["qa"]),
        "delivery_status": delivery,
        "may_render_now": may_render,
        "watermark": watermark,
        "safety": {
            "invent_data": False,
            "network": False,
            "live_mcp": False,
            "browser_automation": False,
            "external_skill_execution": False,
        },
    }

