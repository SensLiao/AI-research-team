"""Deterministic core of figure-vlm-critic (ANALYZE producer, advisory).

Derives figure-quality findings from a figure_spec_bundle structure — no image
rendering, no network, no LLM.  Real PNG/VLM critique is an out-of-band step
until a render/GPU server exists.

Two families of checks are applied:
  1. Structural checks on figure_spec_bundle fields (truncated_axis, dual_axis_confusion,
     missing_error_bars).
  2. Merge of signals from an optional viz_audit_report (axis_truncation_flags → each
     flag produces a misleading_axis / truncated_axis finding if not already raised).

All findings are advisory (severity info/warn/critical).  No BLOCK verdict is emitted.
Same value in → same value out (deterministic, stable order).
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

# figure_spec_bundle.figure_type enum is {bar,boxplot,line,scatter,table,heatmap,other};
# a truncated y-axis is misleading specifically on a BAR chart (there is no "area" type, and a
# non-zero min on line/scatter is often legitimate). The dual-axis and error-bar signals live
# INSIDE the y_axis object (which is additionalProperties:true) — they are NOT top-level figure
# keys (the figure item is additionalProperties:false), so the tool reads them from y_axis.
_TRUNCATION_SENSITIVE_TYPES = {"bar"}


def _check_truncated_axis(fig: dict) -> List[dict]:
    """Return a truncated_axis finding if the y-axis min is non-zero on a bar chart."""
    findings: List[dict] = []
    figure_id = fig.get("figure_id", "unknown")
    figure_type = fig.get("figure_type", "")
    y_axis = fig.get("y_axis") or {}

    if figure_type in _TRUNCATION_SENSITIVE_TYPES and isinstance(y_axis, dict):
        y_min = y_axis.get("min")
        # Numeric guard: a non-numeric min ("auto"/"none"/str) is not a non-zero truncation we can assert
        # — skip instead of crashing on float("auto"). (bool excluded so True/False isn't read as 1/0.)
        if isinstance(y_min, (int, float)) and not isinstance(y_min, bool) and float(y_min) != 0.0:
            findings.append({
                "figure_id": figure_id,
                "finding_type": "truncated_axis",
                "severity": "warn",
                "evidence_ref": [
                    f"figure_spec/{figure_id}/y_axis.min={y_min}"
                ],
                "detail": (
                    f"Figure '{figure_id}' is a {figure_type} chart with y-axis min={y_min} "
                    "(non-zero). A truncated y-axis on a bar/area chart can visually exaggerate "
                    "differences between conditions."
                ),
            })
    return findings


def _check_dual_axis(fig: dict) -> List[dict]:
    """Return a dual_axis_confusion finding if the y_axis declares a secondary scale.

    A dual axis is encoded INSIDE the y_axis object (``y_axis.secondary`` /
    ``y_axis.secondary_axis``) because the figure item itself is additionalProperties:false
    (a top-level ``secondary_y_axis`` key is not schema-valid). Reading it from y_axis
    (additionalProperties:true) makes this check reachable on real data.
    """
    findings: List[dict] = []
    figure_id = fig.get("figure_id", "unknown")

    y_axis = fig.get("y_axis") or {}
    has_secondary = isinstance(y_axis, dict) and (
        y_axis.get("secondary") is not None or y_axis.get("secondary_axis") is not None
    )

    if has_secondary:
        findings.append({
            "figure_id": figure_id,
            "finding_type": "dual_axis_confusion",
            "severity": "warn",
            "evidence_ref": [
                f"figure_spec/{figure_id}/dual_axis_detected"
            ],
            "detail": (
                f"Figure '{figure_id}' declares both y_axis and secondary_y_axis. "
                "Dual-axis charts are prone to misinterpretation when the two scales are "
                "not clearly labelled."
            ),
        })
    return findings


def _check_missing_error_bars(fig: dict) -> List[dict]:
    """Return a missing_error_bars finding if no error_bars field is declared for a bar/boxplot chart."""
    findings: List[dict] = []
    figure_id = fig.get("figure_id", "unknown")
    figure_type = fig.get("figure_type", "")

    # Only flag bar charts (not boxplots — those show spread by design). The error_bars
    # signal lives inside y_axis (additionalProperties:true), not as a top-level figure key
    # (the figure item is additionalProperties:false), so a figure-generator can declare
    # y_axis.error_bars to suppress this advisory.
    if figure_type == "bar":
        y_axis = fig.get("y_axis") or {}
        has_error_bars = isinstance(y_axis, dict) and y_axis.get("error_bars") is not None
        if not has_error_bars:
            findings.append({
                "figure_id": figure_id,
                "finding_type": "missing_error_bars",
                "severity": "info",
                "evidence_ref": [
                    f"figure_spec/{figure_id}/error_bars=missing"
                ],
                "detail": (
                    f"Figure '{figure_id}' is a bar chart with no error_bars declared. "
                    "Consider adding standard deviation or confidence interval bars to show "
                    "result variability."
                ),
            })
    return findings


def _merge_viz_audit_findings(
    fig: dict,
    viz_audit: Optional[dict],
    existing_figure_ids_with_truncation: set,
) -> List[dict]:
    """Merge axis_truncation_flags from viz_audit_report for the given figure.

    Avoids duplicating a finding when _check_truncated_axis already raised one.
    Each viz_audit flag produces a misleading_axis finding (the viz_audit tool uses
    the domain profile's valid_range; the structural check above is profile-agnostic).
    """
    findings: List[dict] = []
    if not viz_audit:
        return findings

    figure_id = fig.get("figure_id", "unknown")
    flags = viz_audit.get("axis_truncation_flags") or []

    for flag in flags:
        if flag.get("figure_id") != figure_id:
            continue
        # If we already raised a truncated_axis from the structural check, add a
        # complementary misleading_axis finding from the profile-based audit instead.
        finding_type = (
            "misleading_axis"
            if figure_id in existing_figure_ids_with_truncation
            else "truncated_axis"
        )
        detail_base = flag.get("detail", "")
        metric = flag.get("metric", "unknown")
        axis = flag.get("axis", "y")
        declared_min = flag.get("declared_min")
        valid_min = flag.get("valid_min")

        findings.append({
            "figure_id": figure_id,
            "finding_type": finding_type,
            "severity": "warn",
            "evidence_ref": [
                f"viz_audit/{figure_id}/{metric}/{axis}/declared_min={declared_min}/valid_min={valid_min}"
            ],
            "detail": detail_base or (
                f"Figure '{figure_id}': {axis}-axis min={declared_min} for metric '{metric}' "
                f"is above the valid_range lower bound {valid_min} (from domain profile)."
            ),
        })
    return findings


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def critique_figure(
    spec: dict,
    viz_audit: Optional[dict] = None,
) -> List[dict]:
    """Derive advisory findings for a single figure spec dict.

    Args:
        spec:      One figure dict from figure_spec_bundle["figures"].
        viz_audit: Optional viz_audit_report payload.  When provided, its
                   axis_truncation_flags for this figure are merged in.

    Returns:
        List of finding dicts (may be empty).  Each finding validates against
        figure_critique.schema.json's items schema.
    """
    findings: List[dict] = []

    # 1. Structural checks (deterministic, no profile)
    trunc_findings = _check_truncated_axis(spec)
    findings.extend(trunc_findings)
    findings.extend(_check_dual_axis(spec))
    findings.extend(_check_missing_error_bars(spec))

    # 2. Merge viz_audit signals (profile-driven, if available)
    figure_ids_with_trunc = {
        f["figure_id"] for f in trunc_findings if f["finding_type"] == "truncated_axis"
    }
    findings.extend(_merge_viz_audit_findings(spec, viz_audit, figure_ids_with_trunc))

    return findings


def build_critique(
    specs: dict,
    viz_audit: Optional[dict] = None,
) -> dict:
    """Build a figure_critique payload from a figure_spec_bundle.

    Args:
        specs:     A figure_spec_bundle payload dict (must have "figures" list).
        viz_audit: Optional viz_audit_report payload.

    Returns:
        A figure_critique dict with "findings" key.  Validates against
        figure_critique.schema.json.
    """
    all_findings: List[dict] = []
    for fig in (specs.get("figures") or []):
        all_findings.extend(critique_figure(fig, viz_audit))

    # Stable order: by (figure_id, finding_type)
    all_findings.sort(key=lambda f: (f.get("figure_id", ""), f.get("finding_type", "")))

    return {"findings": all_findings}
