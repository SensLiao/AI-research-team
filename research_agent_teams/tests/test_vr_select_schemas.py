"""Tests for CLUSTER D1 schemas: venue_candidates and venue_profile.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required. All tests are GREEN before main-thread integration.

Key invariants tested per schema:

venue_candidates:
  - A well-formed instance validates (returns []).
  - Required fields missing → rejected.
  - Anti-slop: empty evidence_ref array → rejected.
  - Anti-slop: whitespace-only string fields → rejected.
  - Anti-slop: empty-string evidence_ref item → rejected.
  - No-auto-pick invariant: {..."selected": True} is REJECTED (additionalProperties:false).
  - Enum enforcement: invalid tier → rejected; invalid paper_type → rejected.
  - Optional rank present → validates.

venue_profile:
  - A well-formed instance validates (returns []).
  - Required fields missing → rejected.
  - Anti-slop: empty evidence_ref → rejected.
  - Anti-slop: whitespace-only evidence_ref item → rejected.
  - Enum enforcement: tier and paper_type enforced.
  - dimension_weights: D1..D7 keys required; additionalProperties:false.
  - reject_triggers: required sub-fields enforced; dimension enum enforced.
  - personas: minItems:1 enforced; enum values enforced.
  - Extra field on top-level object → rejected (closed schema).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. venue_candidates
# ==============================================================================

class TestVenueCandidates:
    SCHEMA = "venue_candidates.schema.json"

    def _good(self) -> dict:
        return {
            "candidates": [
                {
                    "venue_id": "NeurIPS",
                    "tier": "conf",
                    "paper_type": "methodological",
                    "hit_reason": "Strong novelty score and D4 evaluation rigor align with NeurIPS standards.",
                    "deadliest_reject_trigger": "Weak/unfair baseline comparison (RT-D4-BASELINE).",
                    "evidence_ref": ["runs/r001/evidence/DISCOVER/novelty-score.artifact.json"],
                    "rank": 1,
                }
            ]
        }

    def _good_multiple(self) -> dict:
        return {
            "candidates": [
                {
                    "venue_id": "NeurIPS",
                    "tier": "conf",
                    "paper_type": "methodological",
                    "hit_reason": "Methodological novelty in self-supervised learning aligns with NeurIPS scope.",
                    "deadliest_reject_trigger": "RT-D4-BASELINE: baselines may not be well-tuned.",
                    "evidence_ref": ["gap-classification-artifact"],
                    "rank": 1,
                },
                {
                    "venue_id": "MICCAI",
                    "tier": "med",
                    "paper_type": "methodological",
                    "hit_reason": "Method targets medical segmentation; MICCAI is primary venue.",
                    "deadliest_reject_trigger": "RT-D3-SCOPE: no method advance would put this out of scope.",
                    "evidence_ref": ["result-summary-artifact", "novelty-score-artifact"],
                    "rank": 2,
                },
            ]
        }

    # --- valid cases ---

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_multiple_candidates_validates(self):
        assert validate_against(self.SCHEMA, self._good_multiple()) == []

    def test_rank_is_optional(self):
        """rank is optional; omitting it must still validate."""
        good = self._good()
        del good["candidates"][0]["rank"]
        assert validate_against(self.SCHEMA, good) == []

    def test_all_tier_enums_validate(self):
        """All three tier values (conf, med, journal) must be schema-valid."""
        for tier in ["conf", "med", "journal"]:
            instance = {
                "candidates": [
                    {
                        "venue_id": f"Venue-{tier}",
                        "tier": tier,
                        "paper_type": "methodological",
                        "hit_reason": "Valid hit reason.",
                        "deadliest_reject_trigger": "Valid reject trigger.",
                        "evidence_ref": ["ref-001"],
                    }
                ]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"tier={tier!r} should validate but got: {errors}"

    def test_all_paper_type_enums_validate(self):
        """Both paper_type values must be schema-valid."""
        for pt in ["methodological", "application-clinical"]:
            instance = {
                "candidates": [
                    {
                        "venue_id": "SomeVenue",
                        "tier": "conf",
                        "paper_type": pt,
                        "hit_reason": "Valid hit reason.",
                        "deadliest_reject_trigger": "Valid reject trigger.",
                        "evidence_ref": ["ref-001"],
                    }
                ]
            }
            errors = validate_against(self.SCHEMA, instance)
            assert errors == [], f"paper_type={pt!r} should validate but got: {errors}"

    # --- no-auto-pick invariant (the crown-jewel test) ---

    def test_selected_field_rejected(self):
        """NO-AUTO-PICK invariant: a venue_candidates instance with a 'selected' field
        MUST be rejected by additionalProperties:false. The director picks via /venue-pick."""
        bad = self._good()
        bad["candidates"][0]["selected"] = True
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], (
            "INVARIANT VIOLATED: 'selected' field was accepted — "
            "additionalProperties:false must reject it to prevent auto-pick."
        )

    def test_chosen_field_rejected(self):
        """Schema closure must reject a 'chosen' field on a candidate."""
        bad = self._good()
        bad["candidates"][0]["chosen"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_picked_field_rejected(self):
        """Schema closure must reject a 'picked' field on a candidate."""
        bad = self._good()
        bad["candidates"][0]["picked"] = "director"
        assert validate_against(self.SCHEMA, bad) != []

    def test_director_choice_field_rejected(self):
        """Schema closure must reject any 'director_*' style field on a candidate."""
        bad = self._good()
        bad["candidates"][0]["director_choice"] = True
        assert validate_against(self.SCHEMA, bad) != []

    # --- required fields missing ---

    def test_missing_candidates_field_rejected(self):
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_venue_id_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["venue_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_tier_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["tier"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_paper_type_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["paper_type"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_hit_reason_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["hit_reason"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_deadliest_reject_trigger_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["deadliest_reject_trigger"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["candidates"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref rejected ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1 — empty array is schema-rejected."""
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_in_evidence_ref_rejected(self):
        """Anti-slop guard: evidence_ref items pattern '\\S' — empty string is rejected."""
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_in_evidence_ref_rejected(self):
        """Anti-slop guard: whitespace-only evidence_ref item is schema-rejected."""
        bad = self._good()
        bad["candidates"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: whitespace strings in required fields rejected ---

    def test_whitespace_venue_id_rejected(self):
        bad = self._good()
        bad["candidates"][0]["venue_id"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_hit_reason_rejected(self):
        bad = self._good()
        bad["candidates"][0]["hit_reason"] = "\t  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_deadliest_reject_trigger_rejected(self):
        bad = self._good()
        bad["candidates"][0]["deadliest_reject_trigger"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum enforcement ---

    def test_invalid_tier_rejected(self):
        bad = self._good()
        bad["candidates"][0]["tier"] = "preprint"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_paper_type_rejected(self):
        bad = self._good()
        bad["candidates"][0]["paper_type"] = "empirical"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false at top level ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["director_pick"] = "NeurIPS"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_candidate_field_rejected(self):
        bad = self._good()
        bad["candidates"][0]["unexpected"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    # --- minItems:1 on candidates array ---

    def test_empty_candidates_array_rejected(self):
        """candidates minItems:1 — an empty list is rejected (no vacuous nomination)."""
        bad = {"candidates": []}
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. venue_profile
# ==============================================================================

class TestVenueProfile:
    SCHEMA = "venue_profile.schema.json"

    def _good_dim_weights(self) -> dict:
        """Minimal valid dimension_weights block for a conf paper."""
        return {
            "D1": {"weight": 0.22, "gating": True},
            "D2": {"weight": 0.12, "gating": False},
            "D3": {"weight": 0.18, "gating": False},
            "D4": {"weight": 0.28, "gating": False},
            "D5": {"weight": 0.10, "gating": False},
            "D6": {"weight": 0.10, "gating": False},
            "D7": {"weight": 0.00, "gating": False},
        }

    def _good(self) -> dict:
        return {
            "venue_id": "NeurIPS",
            "tier": "conf",
            "paper_type": "methodological",
            "dimension_weights": self._good_dim_weights(),
            "reject_triggers": [
                {
                    "trigger_id": "RT-D4-BASELINE",
                    "dimension": "D4",
                    "description": "Weak or unfair baseline comparison; test-set tuning.",
                    "our_risk": "Our baselines may not be fully tuned to published hyperparameters.",
                }
            ],
            "accept_condition": (
                "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger fire "
                "AND (paper_type=application-clinical => D7>=3)"
            ),
            "personas": ["methodology", "domain", "adversarial"],
            "evidence_ref": [
                "agents/references/venue-rubrics/tier1-conf-ml.md",
                "agents/references/venue-rubrics/rubric-7d.md",
            ],
            "anti_bias_suppressors": ["ABS-1: did-not-beat-SOTA is not sole grounds"],
            "overall_scale": "1-10 NeurIPS",
            "confidence_note": "Public reviewer guidelines; no login required.",
        }

    def _good_journal(self) -> dict:
        """A valid journal (Nature) venue_profile with D5 gating and D2 gating."""
        return {
            "venue_id": "Nature",
            "tier": "journal",
            "paper_type": "methodological",
            "dimension_weights": {
                "D1": {"weight": 0.18, "gating": True},
                "D2": {"weight": 0.22, "gating": True},
                "D3": {"weight": 0.20, "gating": True},
                "D4": {"weight": 0.18, "gating": False},
                "D5": {"weight": 0.12, "gating": True},
                "D6": {"weight": 0.10, "gating": False},
                "D7": {"weight": 0.00, "gating": False},
            },
            "reject_triggers": [
                {
                    "trigger_id": "RT-D5-REPRO",
                    "dimension": "D5",
                    "description": "Code not publicly available — hard gate at Nature-family.",
                }
            ],
            "accept_condition": (
                "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger fire "
                "AND D5>=3 (journal mandatory) AND (paper_type=application-clinical => D7>=3)"
            ),
            "personas": ["methodology", "domain", "adversarial"],
            "evidence_ref": [
                "agents/references/venue-rubrics/tier3-journal.md",
            ],
            "confidence_note": "Nature guide-to-referees is login-gated — verify verbatim before submission.",
        }

    def _good_med(self) -> dict:
        """A valid med-imaging (MICCAI) venue_profile with D7 gating for application-clinical."""
        return {
            "venue_id": "MICCAI",
            "tier": "med",
            "paper_type": "application-clinical",
            "dimension_weights": {
                "D1": {"weight": 0.20, "gating": True},
                "D2": {"weight": 0.12, "gating": False},
                "D3": {"weight": 0.20, "gating": True},
                "D4": {"weight": 0.24, "gating": False},
                "D5": {"weight": 0.10, "gating": False},
                "D6": {"weight": 0.10, "gating": False},
                "D7": {"weight": 0.04, "gating": True},
            },
            "reject_triggers": [
                {
                    "trigger_id": "RT-D7-CLINICAL",
                    "dimension": "D7",
                    "description": "Single-center data, no external validation.",
                    "our_risk": "Our dataset is single-center; external validation not yet performed.",
                }
            ],
            "accept_condition": (
                "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger fire "
                "AND D7>=3 (application-clinical at med)"
            ),
            "personas": ["methodology", "domain", "adversarial"],
            "evidence_ref": [
                "agents/references/venue-rubrics/tier2-med-imaging.md",
            ],
            "confidence_note": "MICCAI review form changes annually — re-check before submission.",
        }

    # --- valid cases ---

    def test_wellformed_conf_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_wellformed_journal_validates(self):
        assert validate_against(self.SCHEMA, self._good_journal()) == []

    def test_wellformed_med_application_clinical_validates(self):
        assert validate_against(self.SCHEMA, self._good_med()) == []

    def test_optional_fields_absent_validates(self):
        """overall_scale, confidence_note, anti_bias_suppressors are all optional."""
        good = self._good()
        del good["overall_scale"]
        del good["confidence_note"]
        del good["anti_bias_suppressors"]
        assert validate_against(self.SCHEMA, good) == []

    def test_empty_reject_triggers_array_validates(self):
        """A venue_profile with no active reject_triggers is structurally valid."""
        good = self._good()
        good["reject_triggers"] = []
        assert validate_against(self.SCHEMA, good) == []

    def test_trigger_without_our_risk_validates(self):
        """our_risk on a reject_trigger is optional."""
        good = self._good()
        del good["reject_triggers"][0]["our_risk"]
        assert validate_against(self.SCHEMA, good) == []

    def test_all_tier_enums_validate(self):
        for tier in ["conf", "med", "journal"]:
            inst = self._good()
            inst["tier"] = tier
            errors = validate_against(self.SCHEMA, inst)
            assert errors == [], f"tier={tier!r} should validate but got: {errors}"

    def test_all_paper_type_enums_validate(self):
        for pt in ["methodological", "application-clinical"]:
            inst = self._good()
            inst["paper_type"] = pt
            errors = validate_against(self.SCHEMA, inst)
            assert errors == [], f"paper_type={pt!r} should validate but got: {errors}"

    def test_all_persona_enum_values_validate(self):
        """All three persona values are valid."""
        for persona in ["methodology", "domain", "adversarial"]:
            inst = self._good()
            inst["personas"] = [persona]
            errors = validate_against(self.SCHEMA, inst)
            assert errors == [], f"persona={persona!r} should validate but got: {errors}"

    def test_multiple_reject_triggers_validate(self):
        good = self._good()
        good["reject_triggers"].append({
            "trigger_id": "RT-D1-OVERCLAIM",
            "dimension": "D1",
            "description": "Core claim not supported by evidence.",
        })
        assert validate_against(self.SCHEMA, good) == []

    # --- required top-level fields missing ---

    def test_missing_venue_id_rejected(self):
        bad = self._good()
        del bad["venue_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_tier_rejected(self):
        bad = self._good()
        del bad["tier"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_paper_type_rejected(self):
        bad = self._good()
        del bad["paper_type"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_dimension_weights_rejected(self):
        bad = self._good()
        del bad["dimension_weights"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_reject_triggers_rejected(self):
        bad = self._good()
        del bad["reject_triggers"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_accept_condition_rejected(self):
        bad = self._good()
        del bad["accept_condition"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_personas_rejected(self):
        bad = self._good()
        del bad["personas"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self):
        bad = self._good()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop: empty evidence_ref rejected ---

    def test_empty_evidence_ref_array_rejected(self):
        """Anti-slop guard: evidence_ref minItems:1."""
        bad = self._good()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_item_rejected(self):
        """Anti-slop guard: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["evidence_ref"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_evidence_ref_item_rejected(self):
        """Anti-slop guard: empty string evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    # --- enum enforcement ---

    def test_invalid_tier_rejected(self):
        bad = self._good()
        bad["tier"] = "workshop"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_paper_type_rejected(self):
        bad = self._good()
        bad["paper_type"] = "empirical"
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_persona_enum_rejected(self):
        bad = self._good()
        bad["personas"] = ["statistics"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_trigger_dimension_enum_rejected(self):
        bad = self._good()
        bad["reject_triggers"][0]["dimension"] = "D8"
        assert validate_against(self.SCHEMA, bad) != []

    # --- dimension_weights: required keys and additionalProperties ---

    def test_missing_D1_in_dimension_weights_rejected(self):
        bad = self._good()
        del bad["dimension_weights"]["D1"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_D4_in_dimension_weights_rejected(self):
        bad = self._good()
        del bad["dimension_weights"]["D4"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_dimension_D8_in_weights_rejected(self):
        """additionalProperties:false on dimension_weights must reject D8."""
        bad = self._good()
        bad["dimension_weights"]["D8"] = {"weight": 0.05}
        assert validate_against(self.SCHEMA, bad) != []

    def test_negative_weight_rejected(self):
        """weight has minimum:0 — negative value rejected."""
        bad = self._good()
        bad["dimension_weights"]["D1"]["weight"] = -0.1
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_weight_in_dimension_rejected(self):
        """weight is required in each dimension object."""
        bad = self._good()
        del bad["dimension_weights"]["D1"]["weight"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_field_in_dimension_rejected(self):
        """additionalProperties:false on each dimension object."""
        bad = self._good()
        bad["dimension_weights"]["D1"]["reviewer_note"] = "should not be here"
        assert validate_against(self.SCHEMA, bad) != []

    # --- reject_triggers: required sub-fields ---

    def test_missing_trigger_id_rejected(self):
        bad = self._good()
        del bad["reject_triggers"][0]["trigger_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_trigger_dimension_rejected(self):
        bad = self._good()
        del bad["reject_triggers"][0]["dimension"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_trigger_description_rejected(self):
        bad = self._good()
        del bad["reject_triggers"][0]["description"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_trigger_id_rejected(self):
        bad = self._good()
        bad["reject_triggers"][0]["trigger_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_trigger_description_rejected(self):
        bad = self._good()
        bad["reject_triggers"][0]["description"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_field_in_trigger_rejected(self):
        """additionalProperties:false on reject_trigger items."""
        bad = self._good()
        bad["reject_triggers"][0]["weight"] = 5
        assert validate_against(self.SCHEMA, bad) != []

    # --- personas: minItems:1 ---

    def test_empty_personas_array_rejected(self):
        """personas minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["personas"] = []
        assert validate_against(self.SCHEMA, bad) != []

    # --- accept_condition anti-slop ---

    def test_whitespace_accept_condition_rejected(self):
        bad = self._good()
        bad["accept_condition"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false at top level ---

    def test_extra_top_level_field_rejected(self):
        bad = self._good()
        bad["verdict"] = "MEETS-BAR"
        assert validate_against(self.SCHEMA, bad) != []

    def test_selected_field_rejected(self):
        """Closure: no 'selected' field is valid on venue_profile either."""
        bad = self._good()
        bad["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []
