"""Tests for the three M3-a CLUSTER 1 (GAP) schemas:
  future_work_items, gap_classification, novelty_score.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required.  All tests are GREEN before main-thread integration.

Key invariants tested per schema:
  - A well-formed valid instance validates (returns []).
  - Each required field missing → rejected.
  - Each anti-slop guard (empty source_ref / empty evidence_ref) → rejected.
  - additionalProperties:false (extra field) → rejected.
  - novelty_score: no pass/verdict/include/cut/selected field allowed (schema closure).
  - An empty items/gaps/scores array is ALLOWED (a clean paper yields zero items).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. future_work_items
# ==============================================================================

class TestFutureWorkItems:
    SCHEMA = "future_work_items.schema.json"

    def _good(self) -> dict:
        return {
            "items": [
                {
                    "item_id": "FW-001",
                    "statement": "Future work should explore multi-modal fusion.",
                    "source_ref": "[[smith2024]]",
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "items": [
                {
                    "item_id": "FW-001",
                    "statement": "Future work should explore multi-modal fusion.",
                    "source_ref": "[[smith2024]]",
                    "gap_hint": "transfer",
                    "tags": ["multi-modal", "fusion"],
                }
            ]
        }

    def _good_empty(self) -> dict:
        """An empty items array is valid (a clean paper yields zero future-work items)."""
        return {"items": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_fields_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_items_array_is_allowed(self):
        """An empty items array must validate — a clean paper yields zero items."""
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_multiple_items_validates(self):
        good = {
            "items": [
                {"item_id": "FW-001", "statement": "Explore transfer to NLP.", "source_ref": "[[doe2023]]"},
                {"item_id": "FW-002", "statement": "Test on larger datasets.", "source_ref": "[[doe2023]]"},
            ]
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_items_field_rejected(self):
        bad = {}
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_item_id_rejected(self):
        bad = self._good()
        del bad["items"][0]["item_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_statement_rejected(self):
        bad = self._good()
        del bad["items"][0]["statement"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_source_ref_rejected(self):
        bad = self._good()
        del bad["items"][0]["source_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty values rejected ---

    def test_empty_source_ref_rejected(self):
        """Anti-slop guard: source_ref minLength:1 — an item with empty source_ref is schema-rejected."""
        bad = self._good()
        bad["items"][0]["source_ref"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_item_id_rejected(self):
        bad = self._good()
        bad["items"][0]["item_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_statement_rejected(self):
        bad = self._good()
        bad["items"][0]["statement"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["unexpected_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_item_field_rejected(self):
        bad = self._good()
        bad["items"][0]["unknown"] = "x"
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_source_ref_rejected(self):
        """ROUND-2 anti-slop fix: a whitespace-only source_ref must be rejected (pattern \\S)."""
        bad = self._good()
        bad["items"][0]["source_ref"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_statement_rejected(self):
        bad = self._good()
        bad["items"][0]["statement"] = "\t  "
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. gap_classification
# ==============================================================================

class TestGapClassification:
    SCHEMA = "gap_classification.schema.json"

    def _good(self) -> dict:
        return {
            "gaps": [
                {
                    "gap_id": "GAP-001",
                    "gap_type": "stated_open_problem",
                    "reason_code": "FW_STATED",
                    "evidence_ref": ["[[smith2024]]"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "gaps": [
                {
                    "gap_id": "GAP-001",
                    "gap_type": "transfer_gap",
                    "reason_code": "XFER_BIND",
                    "evidence_ref": ["[[jones2023]]", "[[kim2024]]"],
                    "source_kind": "transfer",
                    "notes": "Cross-domain from CV to NLP",
                }
            ]
        }

    def _good_empty(self) -> dict:
        """An empty gaps array is valid — a clean literature set may yield zero classifiable gaps."""
        return {"gaps": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_gaps_array_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_all_seven_gap_types_validate(self):
        """Every gap_type enum value must be schema-valid."""
        gap_types = [
            ("stated_open_problem", "FW_STATED"),
            ("methodological_gap", "WEAK_LOCUS"),
            ("coverage_gap", "WHITESPACE"),
            ("transfer_gap", "XFER_BIND"),
            ("assumption_gap", "ASSUMPTION"),
            ("evidence_gap", "UNDER_EVIDENCED"),
            ("empirical_gap", "UNTESTED_SETTING"),
        ]
        for gap_type, reason_code in gap_types:
            instance = {
                "gaps": [{
                    "gap_id": f"GAP-{gap_type}",
                    "gap_type": gap_type,
                    "reason_code": reason_code,
                    "evidence_ref": ["ref-001"],
                }]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"gap_type={gap_type!r} should validate but got: {errors}"

    # --- required fields missing ---

    def test_missing_gaps_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["gaps"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_gap_type_rejected(self):
        bad = self._good()
        del bad["gaps"][0]["gap_type"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_reason_code_rejected(self):
        bad = self._good()
        del bad["gaps"][0]["reason_code"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["gaps"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref rejected ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1 — an item with [] is schema-rejected."""
        bad = self._good()
        bad["gaps"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop guard: evidence_ref items minLength:1 — empty string rejected."""
        bad = self._good()
        bad["gaps"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["gaps"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_reason_code_rejected(self):
        bad = self._good()
        bad["gaps"][0]["reason_code"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum validation ---

    def test_invalid_gap_type_rejected(self):
        bad = self._good()
        bad["gaps"][0]["gap_type"] = "unknown_type"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_source_kind_rejected(self):
        bad = self._good_with_optional()
        bad["gaps"][0]["source_kind"] = "invalid_kind"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["extra"] = "not_allowed"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_gap_field_rejected(self):
        bad = self._good()
        bad["gaps"][0]["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        """ROUND-2 anti-slop fix: a whitespace-only evidence_ref must be rejected (pattern \\S)."""
        bad = self._good()
        bad["gaps"][0]["evidence_ref"] = [" "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_reason_code_rejected(self):
        bad = self._good()
        bad["gaps"][0]["reason_code"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_gap_with_derived_from_validates(self):
        """gap_classification may carry optional derived_from (provenance forward to the novelty-scorer)."""
        good = self._good()
        good["gaps"][0]["derived_from"] = ["future_work", "white_space_present"]
        assert validate_against(self.SCHEMA, good) == []


# ==============================================================================
# 3. novelty_score
# ==============================================================================

class TestNoveltyScore:
    SCHEMA = "novelty_score.schema.json"

    def _good(self) -> dict:
        return {
            "scores": [
                {
                    "gap_id": "GAP-001",
                    "novelty": 0.75,
                    "feasibility_signal": 0.6,
                    "derived_from": ["white_space_present", "contrarian_angle", "weakness_opportunity"],
                    "evidence_ref": ["GAP-001", "[[smith2024]]"],
                }
            ]
        }

    def _good_empty(self) -> dict:
        """An empty scores array is valid — zero gaps in yields zero scores out."""
        return {"scores": []}

    def _low_novelty_gap(self) -> dict:
        """A gap with a single weak signal — novelty will be 0.25 (low, but valid)."""
        return {
            "scores": [
                {
                    "gap_id": "GAP-LOW",
                    "novelty": 0.25,
                    "feasibility_signal": 0.5,
                    "derived_from": ["stated_by_authors"],
                    "evidence_ref": ["[[jones2023]]"],
                }
            ]
        }

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_empty_scores_array_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_low_novelty_score_validates(self):
        """A low novelty score (0.25) is schema-valid — novelty-paradox guard."""
        assert validate_against(self.SCHEMA, self._low_novelty_gap()) == []

    def test_boundary_novelty_zero_validates(self):
        good = self._good()
        good["scores"][0]["novelty"] = 0.0
        assert validate_against(self.SCHEMA, good) == []

    def test_boundary_novelty_one_validates(self):
        good = self._good()
        good["scores"][0]["novelty"] = 1.0
        assert validate_against(self.SCHEMA, good) == []

    def test_boundary_feasibility_zero_validates(self):
        good = self._good()
        good["scores"][0]["feasibility_signal"] = 0.0
        assert validate_against(self.SCHEMA, good) == []

    def test_boundary_feasibility_one_validates(self):
        good = self._good()
        good["scores"][0]["feasibility_signal"] = 1.0
        assert validate_against(self.SCHEMA, good) == []

    def test_multiple_scores_validates(self):
        good = {
            "scores": [
                {
                    "gap_id": "GAP-001",
                    "novelty": 0.75,
                    "feasibility_signal": 0.6,
                    "derived_from": ["white_space_present", "contrarian_angle", "weakness_opportunity"],
                    "evidence_ref": ["ref-a"],
                },
                {
                    "gap_id": "GAP-002",
                    "novelty": 0.25,
                    "feasibility_signal": 0.5,
                    "derived_from": ["stated_by_authors"],
                    "evidence_ref": ["ref-b"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_scores_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["scores"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_novelty_rejected(self):
        bad = self._good()
        del bad["scores"][0]["novelty"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_feasibility_signal_rejected(self):
        bad = self._good()
        del bad["scores"][0]["feasibility_signal"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_derived_from_rejected(self):
        bad = self._good()
        del bad["scores"][0]["derived_from"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["scores"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty arrays rejected ---

    def test_empty_derived_from_is_allowed(self):
        """ROUND-2 FIX: derived_from MAY be empty — a genuinely zero-signal gap is novelty 0.0 and must
        stay representable. Forcing derived_from non-empty would make the schema a de-facto novelty cut
        (forbidden). evidence_ref still bites for anti-slop; derived_from (provenance) does not."""
        good = self._good()
        good["scores"][0]["derived_from"] = []
        assert validate_against(self.SCHEMA, good) == []

    def test_whitespace_in_derived_from_rejected(self):
        """When present, derived_from items must be non-blank (no fabricated empty/whitespace slop)."""
        bad = self._good()
        bad["scores"][0]["derived_from"] = [" "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        """ROUND-2 anti-slop fix: a whitespace-only evidence_ref must be rejected (pattern \\S)."""
        bad = self._good()
        bad["scores"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["scores"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop guard: evidence_ref items minLength:1 — empty string rejected."""
        bad = self._good()
        bad["scores"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    # --- novelty out-of-range rejected ---

    def test_novelty_above_one_rejected(self):
        bad = self._good()
        bad["scores"][0]["novelty"] = 1.01
        assert validate_against(self.SCHEMA, bad) != []

    def test_novelty_below_zero_rejected(self):
        bad = self._good()
        bad["scores"][0]["novelty"] = -0.01
        assert validate_against(self.SCHEMA, bad) != []

    def test_feasibility_above_one_rejected(self):
        bad = self._good()
        bad["scores"][0]["feasibility_signal"] = 1.5
        assert validate_against(self.SCHEMA, bad) != []

    def test_feasibility_below_zero_rejected(self):
        bad = self._good()
        bad["scores"][0]["feasibility_signal"] = -0.1
        assert validate_against(self.SCHEMA, bad) != []

    # --- novelty-paradox guard: no verdict/pass/cut/include/selected allowed ---

    def test_adding_pass_field_rejected(self):
        """Schema closure: a 'pass' field must be schema-rejected (additionalProperties:false)."""
        bad = self._good()
        bad["scores"][0]["pass"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_adding_verdict_field_rejected(self):
        """Schema closure: a 'verdict' field must be schema-rejected."""
        bad = self._good()
        bad["scores"][0]["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_adding_include_field_rejected(self):
        """Schema closure: an 'include' field must be schema-rejected."""
        bad = self._good()
        bad["scores"][0]["include"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_adding_cut_field_rejected(self):
        """Schema closure: a 'cut' field must be schema-rejected."""
        bad = self._good()
        bad["scores"][0]["cut"] = False
        assert validate_against(self.SCHEMA, bad) != []

    def test_adding_selected_field_rejected(self):
        """Schema closure: a 'selected' field must be schema-rejected."""
        bad = self._good()
        bad["scores"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false at top level ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["extra"] = "not_allowed"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_score_field_rejected(self):
        bad = self._good()
        bad["scores"][0]["unexpected"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["scores"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []
