"""Tests for the two CLUSTER E (advisory) schemas:
  figure_critique, monitor_alert.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required.  All tests are GREEN before main-thread integration.

Key invariants tested per schema:
  - A well-formed valid instance validates (returns []).
  - Each required field missing → rejected.
  - Each anti-slop guard (empty/whitespace evidence_ref) → rejected.
  - additionalProperties:false (extra field) → rejected.
  - No BLOCK / verdict / decision field exists (advisory-only; schema closed against it).
  - Empty findings/alerts array is ALLOWED (clean result is representable).
  - Enum values are enforced (finding_type, alert_type, severity).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. figure_critique
# ==============================================================================

class TestFigureCritique:
    SCHEMA = "figure_critique.schema.json"

    def _good(self) -> dict:
        return {
            "findings": [
                {
                    "figure_id": "fig1_dice",
                    "finding_type": "truncated_axis",
                    "severity": "warn",
                    "evidence_ref": ["figure_spec/fig1_dice/y_axis.min=0.9"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "findings": [
                {
                    "figure_id": "fig2_dual",
                    "finding_type": "dual_axis_confusion",
                    "severity": "info",
                    "evidence_ref": ["figure_spec/fig2_dual/dual_axis_detected"],
                    "detail": "Figure has both y_axis and secondary_y_axis.",
                }
            ]
        }

    def _good_empty(self) -> dict:
        return {"findings": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_findings_array_is_allowed(self):
        """An empty findings array must validate — no findings is a valid clean result."""
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_all_finding_types_validate(self):
        """Every finding_type enum value must be schema-valid."""
        for ftype in [
            "misleading_axis",
            "truncated_axis",
            "dual_axis_confusion",
            "missing_error_bars",
            "cherry_picked_range",
            "unclear",
            "ok",
        ]:
            instance = {
                "findings": [{
                    "figure_id": "fig_x",
                    "finding_type": ftype,
                    "severity": "info",
                    "evidence_ref": ["ref-001"],
                }]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"finding_type={ftype!r} should validate but got: {errors}"

    def test_all_severity_values_validate(self):
        for sev in ["info", "warn", "critical"]:
            instance = {
                "findings": [{
                    "figure_id": "fig_sev",
                    "finding_type": "ok",
                    "severity": sev,
                    "evidence_ref": ["ref"],
                }]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"severity={sev!r} should validate but got: {errors}"

    def test_multiple_findings_validate(self):
        instance = {
            "findings": [
                {
                    "figure_id": "fig_a",
                    "finding_type": "truncated_axis",
                    "severity": "warn",
                    "evidence_ref": ["fig_a/y_min=0.9"],
                },
                {
                    "figure_id": "fig_b",
                    "finding_type": "missing_error_bars",
                    "severity": "info",
                    "evidence_ref": ["fig_b/error_bars=missing"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, instance) == []

    # --- required fields missing ---

    def test_missing_findings_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_figure_id_rejected(self):
        bad = self._good()
        del bad["findings"][0]["figure_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_finding_type_rejected(self):
        bad = self._good()
        del bad["findings"][0]["finding_type"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_severity_rejected(self):
        bad = self._good()
        del bad["findings"][0]["severity"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["findings"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace evidence_ref rejected ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["findings"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop guard: empty string in evidence_ref rejected."""
        bad = self._good()
        bad["findings"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        """Anti-slop guard: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["findings"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_figure_id_rejected(self):
        """Anti-slop guard: whitespace-only figure_id rejected (pattern \\S)."""
        bad = self._good()
        bad["findings"][0]["figure_id"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum validation ---

    def test_invalid_finding_type_rejected(self):
        bad = self._good()
        bad["findings"][0]["finding_type"] = "bad_type"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_severity_rejected(self):
        bad = self._good()
        bad["findings"][0]["severity"] = "blocker"
        assert validate_against(self.SCHEMA, bad) != []

    # --- advisory-only: no verdict/block/decision field ---

    def test_extra_verdict_field_rejected(self):
        """Advisory-only guard: a 'verdict' field must be schema-rejected
        (additionalProperties:false on the finding item)."""
        bad = self._good()
        bad["findings"][0]["verdict"] = "BLOCK"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_block_field_rejected(self):
        bad = self._good()
        bad["findings"][0]["block"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_decision_field_rejected(self):
        bad = self._good()
        bad["findings"][0]["decision"] = "reject"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["unexpected"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_finding_field_rejected(self):
        bad = self._good()
        bad["findings"][0]["unknown"] = "x"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. monitor_alert
# ==============================================================================

class TestMonitorAlert:
    SCHEMA = "monitor_alert.schema.json"

    def _good(self) -> dict:
        return {
            "alerts": [
                {
                    "run_ref": "run_001",
                    "alert_type": "stalled",
                    "severity": "warn",
                    "evidence_ref": ["run/run_001/status=stalled"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "alerts": [
                {
                    "run_ref": "run_002",
                    "alert_type": "over_budget",
                    "severity": "warn",
                    "evidence_ref": ["run/run_002/cost=200.0/budget_limit=100.0"],
                    "detail": "Run cost 200.0 exceeds budget limit 100.0.",
                }
            ]
        }

    def _good_empty(self) -> dict:
        return {"alerts": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_alerts_array_is_allowed(self):
        """An empty alerts array must validate — no alerts means all runs are healthy."""
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_all_alert_types_validate(self):
        """Every alert_type enum value must be schema-valid."""
        for atype in ["stalled", "over_budget", "failed", "cost_spike"]:
            instance = {
                "alerts": [{
                    "run_ref": "run_x",
                    "alert_type": atype,
                    "severity": "info",
                    "evidence_ref": ["ref-001"],
                }]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"alert_type={atype!r} should validate but got: {errors}"

    def test_all_severity_values_validate(self):
        for sev in ["info", "warn", "critical"]:
            instance = {
                "alerts": [{
                    "run_ref": "run_sev",
                    "alert_type": "stalled",
                    "severity": sev,
                    "evidence_ref": ["ref"],
                }]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"severity={sev!r} should validate but got: {errors}"

    def test_multiple_alerts_validate(self):
        instance = {
            "alerts": [
                {
                    "run_ref": "run_a",
                    "alert_type": "stalled",
                    "severity": "warn",
                    "evidence_ref": ["run/run_a/status=stalled"],
                },
                {
                    "run_ref": "run_b",
                    "alert_type": "failed",
                    "severity": "critical",
                    "evidence_ref": ["run/run_b/status=failed"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, instance) == []

    # --- required fields missing ---

    def test_missing_alerts_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_run_ref_rejected(self):
        bad = self._good()
        del bad["alerts"][0]["run_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_alert_type_rejected(self):
        bad = self._good()
        del bad["alerts"][0]["alert_type"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_severity_rejected(self):
        bad = self._good()
        del bad["alerts"][0]["severity"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["alerts"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace evidence_ref rejected ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["alerts"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop guard: empty string in evidence_ref rejected."""
        bad = self._good()
        bad["alerts"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        """Anti-slop guard: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["alerts"][0]["evidence_ref"] = ["\t  "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_run_ref_rejected(self):
        """Anti-slop guard: whitespace-only run_ref rejected (pattern \\S)."""
        bad = self._good()
        bad["alerts"][0]["run_ref"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum validation ---

    def test_invalid_alert_type_rejected(self):
        bad = self._good()
        bad["alerts"][0]["alert_type"] = "crashed"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_severity_rejected(self):
        bad = self._good()
        bad["alerts"][0]["severity"] = "blocker"
        assert validate_against(self.SCHEMA, bad) != []

    # --- advisory-only: no verdict/block/decision field ---

    def test_extra_verdict_field_rejected(self):
        """Advisory-only guard: a 'verdict' field must be schema-rejected
        (additionalProperties:false on the alert item)."""
        bad = self._good()
        bad["alerts"][0]["verdict"] = "BLOCK"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_block_field_rejected(self):
        bad = self._good()
        bad["alerts"][0]["block"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_decision_field_rejected(self):
        bad = self._good()
        bad["alerts"][0]["decision"] = "halt"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["unexpected"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_alert_field_rejected(self):
        bad = self._good()
        bad["alerts"][0]["unknown"] = "x"
        assert validate_against(self.SCHEMA, bad) != []
