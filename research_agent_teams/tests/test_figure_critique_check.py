"""Tests for the figure_critique_check deterministic core.

Key invariants:
  - A truncated-axis bar chart figure_spec → a truncated_axis finding bound to its figure_id.
  - A clean bar chart (y-axis min=0) → no critical finding.
  - Dual y-axis → dual_axis_confusion finding.
  - viz_audit_report flags are merged as misleading_axis / truncated_axis findings.
  - Deterministic: same input → same output on two calls.
  - build_critique output validates against figure_critique.schema.json.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.figure_critique_check import (
    build_critique,
    critique_figure,
)
from research_agent_teams.tools.validate_artifact import validate_against, validate_payload

_SCHEMA = "figure_critique.schema.json"


# --------------------------------------------------------------------------- #
#  Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #

def _bar_fig(
    figure_id: str,
    y_min: float,
    y_max: float = 1.0,
    metrics: list | None = None,
) -> dict:
    return {
        "figure_id": figure_id,
        "figure_type": "bar",
        "title": f"Figure {figure_id}",
        "data_source": "result_summary",
        "metrics": metrics or ["Dice"],
        "conditions": ["baseline", "method"],
        "y_axis": {"min": y_min, "max": y_max, "label": "Dice"},
        "x_axis": None,
    }


def _line_fig(figure_id: str, y_min: float) -> dict:
    return {
        "figure_id": figure_id,
        "figure_type": "line",
        "title": f"Line {figure_id}",
        "data_source": "result_summary",
        "metrics": ["loss"],
        "conditions": [],
        "y_axis": {"min": y_min, "max": 2.0},
        "x_axis": None,
    }


def _bundle(figures: list) -> dict:
    return {"run_ref": "run_001", "figures": figures}


# --------------------------------------------------------------------------- #
#  critique_figure — truncated axis (bar chart, y-min != 0)                   #
# --------------------------------------------------------------------------- #

class TestTruncatedAxis:

    def test_truncated_axis_bar_chart_raises_finding(self):
        """Golden test: bar chart with y-axis min=0.9 must produce a truncated_axis finding."""
        fig = _bar_fig("fig_trunc", y_min=0.9)
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "truncated_axis" in types, (
            f"Expected truncated_axis finding for y_min=0.9 bar chart; got: {findings}"
        )
        # Finding must be bound to the correct figure_id
        trunc_findings = [f for f in findings if f["finding_type"] == "truncated_axis"]
        assert trunc_findings[0]["figure_id"] == "fig_trunc"

    def test_truncated_axis_evidence_ref_nonempty(self):
        """Anti-slop: truncated_axis finding must have non-empty evidence_ref."""
        fig = _bar_fig("fig_ev", y_min=0.85)
        findings = critique_figure(fig)
        trunc = [f for f in findings if f["finding_type"] == "truncated_axis"]
        assert trunc, "Expected at least one truncated_axis finding"
        for f in trunc:
            assert f["evidence_ref"], "evidence_ref must not be empty"
            assert all(s.strip() for s in f["evidence_ref"]), "evidence_ref items must be non-blank"

    def test_non_bar_type_not_flagged_for_truncation(self):
        """Truncation is bar-specific. figure_spec_bundle has no 'area' type, and a non-zero
        y-min on scatter/heatmap is often legitimate — a scatter with y-min!=0 is NOT flagged."""
        fig = {
            "figure_id": "fig_scatter",
            "figure_type": "scatter",
            "title": "Scatter Fig",
            "data_source": "result_summary",
            "metrics": ["score"],
            "conditions": [],
            "y_axis": {"min": 0.5, "max": 1.0},
            "x_axis": None,
        }
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "truncated_axis" not in types

    def test_clean_bar_chart_zero_ymin_no_truncated_axis(self):
        """Bar chart with y-axis min=0 must produce no truncated_axis finding."""
        fig = _bar_fig("fig_clean", y_min=0.0)
        findings = critique_figure(fig)
        critical_findings = [f for f in findings if f["severity"] == "critical"]
        assert not critical_findings, (
            f"A clean bar chart (y-min=0) must have no critical findings; got: {critical_findings}"
        )
        trunc = [f for f in findings if f["finding_type"] == "truncated_axis"]
        assert not trunc, f"y-min=0 must not produce truncated_axis; got: {trunc}"

    def test_line_chart_nonzero_ymin_not_truncated_axis(self):
        """Line charts are NOT in the bar/area family — non-zero y-min must not flag truncated_axis."""
        fig = _line_fig("fig_line", y_min=0.5)
        findings = critique_figure(fig)
        trunc = [f for f in findings if f["finding_type"] == "truncated_axis"]
        assert not trunc, (
            f"Line chart should not produce truncated_axis; got: {trunc}"
        )


# --------------------------------------------------------------------------- #
#  critique_figure — dual axis                                                 #
# --------------------------------------------------------------------------- #

class TestDualAxis:

    def test_dual_axis_raises_finding(self):
        """Figure whose y_axis declares a secondary scale → dual_axis_confusion.

        The dual axis is encoded inside y_axis (additionalProperties:true) — a top-level
        secondary_y_axis is not schema-valid (the figure item is additionalProperties:false)."""
        fig = {
            "figure_id": "fig_dual",
            "figure_type": "line",
            "title": "Dual Axis",
            "data_source": "result_summary",
            "metrics": ["Dice", "loss"],
            "conditions": [],
            "y_axis": {"min": 0.0, "max": 1.0, "secondary": {"min": 0.0, "max": 5.0}},
            "x_axis": None,
        }
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "dual_axis_confusion" in types

    def test_single_axis_no_dual_finding(self):
        """Figure with only y_axis → no dual_axis_confusion."""
        fig = _bar_fig("fig_single", y_min=0.0)
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "dual_axis_confusion" not in types


# --------------------------------------------------------------------------- #
#  critique_figure — missing error bars                                        #
# --------------------------------------------------------------------------- #

class TestMissingErrorBars:

    def test_bar_without_error_bars_raises_info(self):
        """Bar chart with no error_bars field → missing_error_bars (info)."""
        fig = _bar_fig("fig_noerr", y_min=0.0)
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "missing_error_bars" in types
        info = [f for f in findings if f["finding_type"] == "missing_error_bars"]
        assert info[0]["severity"] == "info"

    def test_bar_with_error_bars_no_missing_finding(self):
        """Bar chart with error_bars declared inside y_axis → no missing_error_bars finding.

        error_bars lives in y_axis (additionalProperties:true), not as a top-level figure key
        (the figure item is additionalProperties:false)."""
        fig = _bar_fig("fig_err", y_min=0.0)
        fig["y_axis"] = {**fig["y_axis"], "error_bars": {"type": "std"}}
        findings = critique_figure(fig)
        types = [f["finding_type"] for f in findings]
        assert "missing_error_bars" not in types


# --------------------------------------------------------------------------- #
#  critique_figure — viz_audit_report merge                                    #
# --------------------------------------------------------------------------- #

class TestVizAuditMerge:

    def _make_viz_audit(self, figure_id: str, metric: str = "Dice") -> dict:
        return {
            "figures_audited": [figure_id],
            "axis_truncation_flags": [
                {
                    "figure_id": figure_id,
                    "metric": metric,
                    "axis": "y",
                    "declared_min": 0.92,
                    "valid_min": 0.0,
                    "detail": (
                        f"Figure '{figure_id}': y-axis min=0.92 for metric '{metric}' "
                        "is above the valid_range lower bound 0.0."
                    ),
                }
            ],
            "clean": False,
            "notes": "",
        }

    def test_viz_audit_flag_produces_finding(self):
        """A viz_audit_report axis_truncation_flag → at least one finding for that figure."""
        fig = _bar_fig("fig_audit", y_min=0.0)  # structurally clean
        viz_audit = self._make_viz_audit("fig_audit")
        findings = critique_figure(fig, viz_audit)
        figure_findings = [f for f in findings if f["figure_id"] == "fig_audit"]
        assert figure_findings, "viz_audit flag must produce a finding for the figure"

    def test_viz_audit_for_other_figure_not_merged(self):
        """viz_audit flag for a different figure_id must not appear in this figure's findings."""
        fig = _bar_fig("fig_a", y_min=0.0)
        viz_audit = self._make_viz_audit("fig_b")  # flag is for fig_b
        findings = critique_figure(fig, viz_audit)
        assert all(f["figure_id"] == "fig_a" for f in findings), (
            "No finding should reference fig_b when critiquing fig_a"
        )

    def test_viz_audit_flag_gets_misleading_axis_when_structural_also_fires(self):
        """When structural check also raises truncated_axis, the viz_audit finding
        must be promoted to misleading_axis to avoid exact duplicate finding_types."""
        fig = _bar_fig("fig_both", y_min=0.94)  # structural check fires
        viz_audit = self._make_viz_audit("fig_both")
        findings = critique_figure(fig, viz_audit)
        types = [f["finding_type"] for f in findings]
        assert "truncated_axis" in types
        assert "misleading_axis" in types


# --------------------------------------------------------------------------- #
#  build_critique — bundle-level + schema validation                           #
# --------------------------------------------------------------------------- #

class TestBuildCritique:

    def test_build_critique_schema_valid_truncated(self):
        """build_critique output with findings validates against figure_critique.schema.json."""
        bundle = _bundle([_bar_fig("fig_t", y_min=0.85)])
        result = build_critique(bundle)
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_build_critique_schema_valid_clean(self):
        """build_critique output with no findings (empty list) also validates."""
        # Use a line chart with y_min=0 and error_bars to produce 0 findings
        fig = {
            "figure_id": "fig_c",
            "figure_type": "line",
            "title": "Clean Line",
            "data_source": "result_summary",
            "metrics": ["loss"],
            "conditions": [],
            "y_axis": {"min": 0.0, "max": 2.0},
            "x_axis": None,
        }
        bundle = _bundle([fig])
        result = build_critique(bundle)
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema validation errors on clean result: {errors}"

    def test_build_critique_no_critical_for_clean_bar(self):
        """A bar chart with y-min=0 → build_critique produces no critical finding."""
        bundle = _bundle([_bar_fig("fig_ok", y_min=0.0)])
        result = build_critique(bundle)
        critical = [f for f in result["findings"] if f["severity"] == "critical"]
        assert not critical, f"Clean bar chart must have no critical findings; got: {critical}"

    def test_build_critique_truncated_finding_bound_to_figure_id(self):
        """Golden integration: truncated-axis finding must carry the correct figure_id."""
        bundle = _bundle([_bar_fig("fig_golden", y_min=0.88)])
        result = build_critique(bundle)
        trunc = [f for f in result["findings"] if f["finding_type"] == "truncated_axis"]
        assert trunc, "Expected at least one truncated_axis finding"
        assert trunc[0]["figure_id"] == "fig_golden"

    def test_build_critique_multiple_figures_independent(self):
        """Findings for different figures are independent and bound to correct figure_id."""
        bundle = _bundle([
            _bar_fig("fig_bad", y_min=0.90),
            _bar_fig("fig_good", y_min=0.00),
        ])
        result = build_critique(bundle)
        bad_trunc = [
            f for f in result["findings"]
            if f["figure_id"] == "fig_bad" and f["finding_type"] == "truncated_axis"
        ]
        good_trunc = [
            f for f in result["findings"]
            if f["figure_id"] == "fig_good" and f["finding_type"] == "truncated_axis"
        ]
        assert bad_trunc, "fig_bad must have a truncated_axis finding"
        assert not good_trunc, "fig_good must NOT have a truncated_axis finding"

    def test_build_critique_deterministic(self):
        """Two calls with the same input return identical results."""
        bundle = _bundle([
            _bar_fig("fig_d1", y_min=0.80),
            _bar_fig("fig_d2", y_min=0.00),
        ])
        r1 = build_critique(bundle)
        r2 = build_critique(bundle)
        assert r1 == r2, "build_critique must be deterministic"

    def test_build_critique_empty_figures_list(self):
        """A figure_spec_bundle with 0 figures → empty findings (edge case)."""
        # Note: figure_spec_bundle schema requires minItems:1, but our tool
        # handles the edge case gracefully regardless.
        bundle = {"run_ref": "run_empty", "figures": []}
        result = build_critique(bundle)
        assert result["findings"] == []
        errors = validate_against(_SCHEMA, result)
        assert errors == [], f"Schema errors on empty bundle: {errors}"

    def test_critique_fires_on_a_REGISTERED_schema_valid_bundle(self):
        """Honesty proof: the tool fires on a figure_spec_bundle that itself passes
        validate_payload (the registered path) — not on fabricated, schema-impossible input.
        Both the truncated-axis (bar y-min!=0) and dual-axis (y_axis.secondary) signals are
        encoded in a way the real schema accepts, and both findings are produced + bound."""
        trunc = _bar_fig("fig_real_trunc", y_min=0.9)
        dual = {
            "figure_id": "fig_real_dual",
            "figure_type": "line",
            "title": "Real Dual",
            "data_source": "result_summary",
            "metrics": ["Dice", "loss"],
            "conditions": [],
            "y_axis": {"min": 0.0, "max": 1.0, "secondary": {"min": 0.0, "max": 5.0}},
            "x_axis": None,
        }
        bundle = _bundle([trunc, dual])
        # The INPUT bundle is real (passes the registered figure_spec_bundle schema).
        assert validate_payload("figure_spec_bundle", bundle) == [], "input bundle must be schema-valid"
        result = build_critique(bundle)
        by_fig = {(f["figure_id"], f["finding_type"]) for f in result["findings"]}
        assert ("fig_real_trunc", "truncated_axis") in by_fig
        assert ("fig_real_dual", "dual_axis_confusion") in by_fig
        assert validate_against(_SCHEMA, result) == []
