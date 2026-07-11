"""Tests for the four CLUSTER C (gap-hunting breadth) schemas:
  weakness_report, white_space_map, transfer_candidates, contrarian_angles.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required.  All tests are GREEN before main-thread integration.

Key invariants tested per schema:
  - A well-formed valid instance validates (returns []).
  - An empty items/regions/candidates/angles array is ALLOWED (clean literature → zero items).
  - Each required field missing → rejected.
  - Anti-slop guards (empty evidence_ref array / empty string in evidence_ref / whitespace-only
    evidence_ref) → rejected.
  - Non-blank string fields (gap_id, locus, opportunity, region, source_domain, target_hook,
    challenged_assumption) must reject empty and whitespace-only values.
  - additionalProperties:false (extra field on item or top-level) → rejected.
  - white_space_map: hole field must be boolean; hole:true emits; hole:false (if admitted by
    schema, which does not enum-restrict it) would still be valid schema-wise but must carry
    the required fields — the TEST proves the intended use (only hole:true regions are emitted).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. weakness_report
# ==============================================================================

class TestWeaknessReport:
    SCHEMA = "weakness_report.schema.json"

    def _good(self) -> dict:
        return {
            "weaknesses": [
                {
                    "gap_id": "WK-001",
                    "locus": "loss function design in UNet-family models",
                    "opportunity": "topology-aware loss for tubular structure segmentation",
                    "evidence_ref": ["[[chen2023]]"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "weaknesses": [
                {
                    "gap_id": "WK-001",
                    "locus": "data augmentation strategy",
                    "opportunity": "class-conditional augmentation for imbalanced classes",
                    "evidence_ref": ["[[doe2024]]", "[[smith2023]]"],
                    "severity": "major",
                    "source_ref": "[[doe2024]]",
                }
            ]
        }

    def _good_empty(self) -> dict:
        return {"weaknesses": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_weaknesses_is_allowed(self):
        """An empty weaknesses array is valid — clean surveyed work yields zero weaknesses."""
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_multiple_weaknesses_validates(self):
        good = {
            "weaknesses": [
                {
                    "gap_id": "WK-001",
                    "locus": "evaluation protocol",
                    "opportunity": "blind hold-out test set",
                    "evidence_ref": ["[[ref1]]"],
                },
                {
                    "gap_id": "WK-002",
                    "locus": "sample size in ablation study",
                    "opportunity": "power-adequate ablation with 3 seeds",
                    "evidence_ref": ["[[ref2]]"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_weaknesses_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["weaknesses"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_locus_rejected(self):
        bad = self._good()
        del bad["weaknesses"][0]["locus"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_opportunity_rejected(self):
        bad = self._good()
        del bad["weaknesses"][0]["opportunity"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["weaknesses"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop: evidence_ref minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["weaknesses"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop: evidence_ref items minLength:1 — empty string rejected."""
        bad = self._good()
        bad["weaknesses"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        """Anti-slop: a whitespace-only evidence_ref must be rejected (pattern \\S)."""
        bad = self._good()
        bad["weaknesses"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace required string fields ---

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_gap_id_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["gap_id"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_locus_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["locus"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_locus_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["locus"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_opportunity_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["opportunity"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_opportunity_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["opportunity"] = "\t"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["unexpected"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_item_field_rejected(self):
        bad = self._good()
        bad["weaknesses"][0]["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. white_space_map
# ==============================================================================

class TestWhiteSpaceMap:
    SCHEMA = "white_space_map.schema.json"

    def _good(self) -> dict:
        return {
            "regions": [
                {
                    "gap_id": "WS-001",
                    "region": "3D-aware multi-scale feature fusion for small tubular structures in CT",
                    "hole": True,
                    "evidence_ref": ["[[landscape-map-001]]"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "regions": [
                {
                    "gap_id": "WS-001",
                    "region": "few-shot organ segmentation under extreme label scarcity",
                    "hole": True,
                    "evidence_ref": ["[[landscape-map-001]]", "[[chen2023]]"],
                    "density": "absent",
                    "notes": "No paper in the set addresses fewer than 10 labeled samples.",
                }
            ]
        }

    def _good_empty(self) -> dict:
        """A fully-covered landscape yields zero regions (valid)."""
        return {"regions": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_regions_is_allowed(self):
        """An empty regions array is valid — a fully-covered landscape yields zero holes."""
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_hole_true_validates(self):
        """hole:true is the canonical emitted value."""
        good = self._good()
        good["regions"][0]["hole"] = True
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_regions_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["regions"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_region_rejected(self):
        bad = self._good()
        del bad["regions"][0]["region"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_hole_rejected(self):
        bad = self._good()
        del bad["regions"][0]["hole"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["regions"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref ---

    def test_empty_evidence_ref_array_rejected(self):
        bad = self._good()
        bad["regions"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        bad = self._good()
        bad["regions"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        bad = self._good()
        bad["regions"][0]["evidence_ref"] = [" "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace required string fields ---

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["regions"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_gap_id_rejected(self):
        bad = self._good()
        bad["regions"][0]["gap_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_region_rejected(self):
        bad = self._good()
        bad["regions"][0]["region"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_region_rejected(self):
        bad = self._good()
        bad["regions"][0]["region"] = "\t\n"
        assert validate_against(self.SCHEMA, bad) != []

    # --- hole must be boolean ---

    def test_hole_must_be_boolean_not_string(self):
        bad = self._good()
        bad["regions"][0]["hole"] = "true"  # string, not boolean
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_item_field_rejected(self):
        bad = self._good()
        bad["regions"][0]["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 3. transfer_candidates
# ==============================================================================

class TestTransferCandidates:
    SCHEMA = "transfer_candidates.schema.json"

    def _good(self) -> dict:
        return {
            "candidates": [
                {
                    "gap_id": "XF-001",
                    "source_domain": "natural language processing",
                    "target_hook": "attention-based feature selection for radiology reports",
                    "evidence_ref": ["[[vaswani2017]]"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "candidates": [
                {
                    "gap_id": "XF-001",
                    "source_domain": "graph neural networks",
                    "target_hook": "anatomical topology constraints for organ segmentation",
                    "evidence_ref": ["[[xu2022]]", "[[landscape-map-001]]"],
                    "method_ref": "[[xu2022]]",
                }
            ]
        }

    def _good_empty(self) -> dict:
        return {"candidates": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_candidates_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_multiple_candidates_validates(self):
        good = {
            "candidates": [
                {
                    "gap_id": "XF-001",
                    "source_domain": "signal processing",
                    "target_hook": "frequency-domain feature extraction for MRI reconstruction",
                    "evidence_ref": ["[[ref1]]"],
                },
                {
                    "gap_id": "XF-002",
                    "source_domain": "reinforcement learning",
                    "target_hook": "adaptive scan protocol selection",
                    "evidence_ref": ["[[ref2]]"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_candidates_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_source_domain_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["source_domain"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_target_hook_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["target_hook"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref ---

    def test_empty_evidence_ref_array_rejected(self):
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace required string fields ---

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["candidates"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_gap_id_rejected(self):
        bad = self._good()
        bad["candidates"][0]["gap_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_source_domain_rejected(self):
        bad = self._good()
        bad["candidates"][0]["source_domain"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_source_domain_rejected(self):
        bad = self._good()
        bad["candidates"][0]["source_domain"] = "\t"
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_target_hook_rejected(self):
        bad = self._good()
        bad["candidates"][0]["target_hook"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_target_hook_rejected(self):
        bad = self._good()
        bad["candidates"][0]["target_hook"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["chosen"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_item_field_rejected(self):
        bad = self._good()
        bad["candidates"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 4. contrarian_angles
# ==============================================================================

class TestContrarianAngles:
    SCHEMA = "contrarian_angles.schema.json"

    def _good(self) -> dict:
        return {
            "angles": [
                {
                    "gap_id": "CA-001",
                    "challenged_assumption": (
                        "Pre-training on ImageNet always improves performance "
                        "on medical imaging tasks."
                    ),
                    "evidence_ref": ["[[raghu2019]]"],
                }
            ]
        }

    def _good_with_optional(self) -> dict:
        return {
            "angles": [
                {
                    "gap_id": "CA-001",
                    "challenged_assumption": (
                        "Larger model capacity monotonically improves "
                        "segmentation on small datasets."
                    ),
                    "evidence_ref": ["[[raghu2019]]", "[[chen2023]]"],
                    "supporting_argument": (
                        "raghu2019 shows random-weight CNNs match pre-trained on limited data; "
                        "inductive bias may be more valuable than pre-trained features."
                    ),
                }
            ]
        }

    def _good_empty(self) -> dict:
        return {"angles": []}

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_with_optional_validates(self):
        assert validate_against(self.SCHEMA, self._good_with_optional()) == []

    def test_empty_angles_is_allowed(self):
        assert validate_against(self.SCHEMA, self._good_empty()) == []

    def test_multiple_angles_validates(self):
        good = {
            "angles": [
                {
                    "gap_id": "CA-001",
                    "challenged_assumption": "Attention is all you need for medical segmentation.",
                    "evidence_ref": ["[[ref1]]"],
                },
                {
                    "gap_id": "CA-002",
                    "challenged_assumption": "Dice loss is sufficient for class-imbalanced tasks.",
                    "evidence_ref": ["[[ref2]]"],
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == []

    # --- required fields missing ---

    def test_missing_angles_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_gap_id_rejected(self):
        bad = self._good()
        del bad["angles"][0]["gap_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_challenged_assumption_rejected(self):
        bad = self._good()
        del bad["angles"][0]["challenged_assumption"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["angles"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop: evidence_ref minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["angles"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        bad = self._good()
        bad["angles"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self):
        bad = self._good()
        bad["angles"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty / whitespace required string fields ---

    def test_empty_gap_id_rejected(self):
        bad = self._good()
        bad["angles"][0]["gap_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_gap_id_rejected(self):
        bad = self._good()
        bad["angles"][0]["gap_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_challenged_assumption_rejected(self):
        bad = self._good()
        bad["angles"][0]["challenged_assumption"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_challenged_assumption_rejected(self):
        bad = self._good()
        bad["angles"][0]["challenged_assumption"] = "  \t  "
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["verdict"] = "PASS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_item_field_rejected(self):
        bad = self._good()
        bad["angles"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []
