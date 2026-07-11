"""Tests for M3-a CLUSTER 2 (IDEATE) schemas: hypothesis_set and idea_backlog.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required. All tests are GREEN before main-thread integration.

Schemas tested:
  hypothesis_set — IDEATE producer, mirrors rq_hypothesis_chain + anti-slop evidence_ref.
  idea_backlog   — IDEATE exit artifact, no-self-bet guarantee (additionalProperties:false).

Anti-slop structural guards tested:
  - every hypothesis requires non-empty falsifiable_prediction + >=1 evidence_needed + >=1 evidence_ref
  - every idea requires feasibility.score + >=1 evidence_ref
  - idea_backlog rejects any selected/chosen/bet/winner/director_* field (no-self-bet)
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. hypothesis_set
# ==============================================================================

class TestHypothesisSet:
    SCHEMA = "hypothesis_set.schema.json"

    def _good_hypothesis(self) -> dict:
        return {
            "hypothesis_id": "IH1",
            "statement": "Contrastive pre-training on unlabelled CT reduces annotation demand.",
            "falsifiable_prediction": (
                "A model pre-trained with contrastive loss on 10k unlabelled CTs achieves "
                "Dice >= 0.80 on the held-out test set when fine-tuned on only 50 labelled "
                "volumes, vs Dice < 0.70 for the same architecture trained from scratch."
            ),
            "evidence_needed": [
                "Ablation: contrastive pre-train vs random init at equal fine-tune data budgets",
                "Held-out test evaluation on standard benchmark",
            ],
            "evidence_ref": ["gap-001", "novelty-gap-001"],
        }

    def _good(self) -> dict:
        return {"hypotheses": [self._good_hypothesis()]}

    # --- happy-path ---

    def test_wellformed_validates(self) -> None:
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_multiple_hypotheses_validates(self) -> None:
        good = self._good()
        good["hypotheses"].append({
            "hypothesis_id": "IH2",
            "statement": "Domain-adversarial training bridges the natural-image to medical-scan gap.",
            "falsifiable_prediction": (
                "Fine-tuning a domain-adversarially trained backbone on 100 labelled CT scans "
                "outperforms ImageNet-only pre-training by >= 3% mean Dice."
            ),
            "evidence_needed": ["Transfer experiment on benchmark dataset"],
            "evidence_ref": ["gap-002"],
            "depends_on": ["IH1"],
        })
        assert validate_against(self.SCHEMA, good) == []

    def test_with_optional_fields_validates(self) -> None:
        good = self._good()
        good["hypotheses"][0]["source_gap_ref"] = "gap-001"
        good["hypotheses"][0]["depends_on"] = []
        good["hypotheses"][0]["notes"] = "Uncertainty: annotation count may need tuning."
        assert validate_against(self.SCHEMA, good) == []

    # --- structural anti-slop guards ---

    def test_empty_hypotheses_rejected(self) -> None:
        """hypotheses minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["hypotheses"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_hypotheses_rejected(self) -> None:
        bad = {}
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_falsifiable_prediction_rejected(self) -> None:
        """Each hypothesis requires falsifiable_prediction."""
        bad = self._good()
        del bad["hypotheses"][0]["falsifiable_prediction"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_falsifiable_prediction_rejected(self) -> None:
        """Empty string violates minLength:1."""
        bad = self._good()
        bad["hypotheses"][0]["falsifiable_prediction"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_needed_rejected(self) -> None:
        """Each hypothesis requires evidence_needed."""
        bad = self._good()
        del bad["hypotheses"][0]["evidence_needed"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_needed_rejected(self) -> None:
        """evidence_needed minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["hypotheses"][0]["evidence_needed"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_evidence_needed_empty_string_rejected(self) -> None:
        """Each item in evidence_needed requires minLength:1."""
        bad = self._good()
        bad["hypotheses"][0]["evidence_needed"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        """Anti-slop: each hypothesis requires evidence_ref."""
        bad = self._good()
        del bad["hypotheses"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_ref_rejected(self) -> None:
        """evidence_ref minItems:1 — empty list is schema-rejected (anti-slop core guard)."""
        bad = self._good()
        bad["hypotheses"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject a hypothesis with empty evidence_ref (anti-slop guard)"
        )

    def test_evidence_ref_empty_string_rejected(self) -> None:
        """Each item in evidence_ref requires minLength:1."""
        bad = self._good()
        bad["hypotheses"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_hypothesis_id_rejected(self) -> None:
        bad = self._good()
        del bad["hypotheses"][0]["hypothesis_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_statement_rejected(self) -> None:
        bad = self._good()
        del bad["hypotheses"][0]["statement"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_top_level_property_rejected(self) -> None:
        """additionalProperties:false — unknown top-level key is rejected."""
        bad = self._good()
        bad["selected"] = "IH1"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_hypothesis_property_rejected(self) -> None:
        """additionalProperties:false on items — unknown field is rejected."""
        bad = self._good()
        bad["hypotheses"][0]["winner"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_falsifiable_prediction_rejected(self) -> None:
        """ROUND-2 anti-slop fix: a whitespace-only falsifiable_prediction is rejected (pattern \\S)."""
        bad = self._good()
        bad["hypotheses"][0]["falsifiable_prediction"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self) -> None:
        bad = self._good()
        bad["hypotheses"][0]["evidence_ref"] = [" "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_needed_rejected(self) -> None:
        bad = self._good()
        bad["hypotheses"][0]["evidence_needed"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. idea_backlog — includes no-self-bet structural guarantee tests
# ==============================================================================

class TestIdeaBacklog:
    SCHEMA = "idea_backlog.schema.json"

    def _good_idea(self, idea_id: str = "IDEA-001", rank: int = 1) -> dict:
        return {
            "idea_id": idea_id,
            "rank": rank,
            "summary": "Contrastive pre-training on unlabelled CT volumes to close the annotation gap.",
            "feasibility": {"score": 0.8333},
            "evidence_ref": ["IH1", "gap-001"],
        }

    def _good(self) -> dict:
        return {
            "ranked_ideas": [
                self._good_idea("IDEA-001", 1),
                {
                    "idea_id": "IDEA-002",
                    "rank": 2,
                    "summary": "Cross-modal transfer from natural images to medical scans.",
                    "feasibility": {"score": 0.6},
                    "evidence_ref": ["IH2", "gap-002"],
                },
            ]
        }

    # --- happy-path ---

    def test_wellformed_validates(self) -> None:
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_with_optional_fields_validates(self) -> None:
        good = self._good()
        good["ranked_ideas"][0]["from_hypothesis_ref"] = "IH1"
        good["ranked_ideas"][0]["novelty_ref"] = "gap-001"
        good["ranked_ideas"][0]["caveats"] = ["GPU budget may need to be negotiated."]
        good["ranked_ideas"][0]["feasibility"]["compute"] = "low"
        good["ranked_ideas"][0]["feasibility"]["data"] = "public"
        good["ranked_ideas"][0]["feasibility"]["time"] = "medium"
        assert validate_against(self.SCHEMA, good) == []

    def test_single_idea_validates(self) -> None:
        good = {"ranked_ideas": [self._good_idea()]}
        assert validate_against(self.SCHEMA, good) == []

    # --- structural anti-slop guards ---

    def test_empty_ranked_ideas_rejected(self) -> None:
        """ranked_ideas minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["ranked_ideas"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_ranked_ideas_rejected(self) -> None:
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        """Anti-slop: each idea requires evidence_ref."""
        bad = self._good()
        del bad["ranked_ideas"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_ref_rejected(self) -> None:
        """evidence_ref minItems:1 — empty list is schema-rejected (anti-slop core guard)."""
        bad = self._good()
        bad["ranked_ideas"][0]["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject an idea with empty evidence_ref (anti-slop guard)"
        )

    def test_evidence_ref_empty_string_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_feasibility_rejected(self) -> None:
        bad = self._good()
        del bad["ranked_ideas"][0]["feasibility"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_feasibility_missing_score_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["feasibility"] = {}
        assert validate_against(self.SCHEMA, bad) != []

    def test_feasibility_score_out_of_range_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["feasibility"] = {"score": 1.5}
        assert validate_against(self.SCHEMA, bad) != []

    def test_feasibility_score_negative_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["feasibility"] = {"score": -0.1}
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_rank_rejected(self) -> None:
        bad = self._good()
        del bad["ranked_ideas"][0]["rank"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_rank_zero_rejected(self) -> None:
        """rank minimum:1 — rank=0 is rejected."""
        bad = self._good()
        bad["ranked_ideas"][0]["rank"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_summary_rejected(self) -> None:
        bad = self._good()
        del bad["ranked_ideas"][0]["summary"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_idea_id_rejected(self) -> None:
        bad = self._good()
        del bad["ranked_ideas"][0]["idea_id"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- NO-SELF-BET structural guarantee tests (HARD requirement) ---

    def test_selected_field_rejected(self) -> None:
        """NO-SELF-BET GUARD: adding 'selected' to idea_backlog must be schema-rejected.

        This is the structural no-self-bet proof: additionalProperties:false on the
        top-level idea_backlog object means the model CANNOT mark a self-bet by adding
        any field not declared in the schema.  A reviewer trying to inject 'selected:true'
        into the backlog will be rejected here.
        """
        bad = self._good()
        bad["selected"] = True
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], (
            "Schema must reject idea_backlog with 'selected' field — no-self-bet guard"
        )

    def test_chosen_field_rejected(self) -> None:
        """NO-SELF-BET GUARD: 'chosen' is not in the schema."""
        bad = self._good()
        bad["chosen"] = "IDEA-001"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject idea_backlog with 'chosen' field — no-self-bet guard"
        )

    def test_bet_field_rejected(self) -> None:
        """NO-SELF-BET GUARD: 'bet' is not in the schema."""
        bad = self._good()
        bad["bet"] = "IDEA-001"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject idea_backlog with 'bet' field — no-self-bet guard"
        )

    def test_winner_field_rejected(self) -> None:
        """NO-SELF-BET GUARD: 'winner' is not in the schema."""
        bad = self._good()
        bad["winner"] = "IDEA-001"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject idea_backlog with 'winner' field — no-self-bet guard"
        )

    def test_director_pick_field_rejected(self) -> None:
        """NO-SELF-BET GUARD: 'director_pick' (director_* pattern) is not in the schema."""
        bad = self._good()
        bad["director_pick"] = "IDEA-001"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject idea_backlog with 'director_pick' field — no-self-bet guard"
        )

    def test_selected_on_idea_item_rejected(self) -> None:
        """NO-SELF-BET GUARD: 'selected' on an individual idea item must also be rejected."""
        bad = self._good()
        bad["ranked_ideas"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject an idea item with 'selected' field — no-self-bet guard"
        )

    def test_extra_top_level_field_rejected(self) -> None:
        """additionalProperties:false — any unknown top-level key is rejected."""
        bad = self._good()
        bad["unexpected_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_idea_field_rejected(self) -> None:
        """additionalProperties:false on items — any unknown idea field is rejected."""
        bad = self._good()
        bad["ranked_ideas"][0]["unknown_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_feasibility_field_rejected(self) -> None:
        """additionalProperties:false on feasibility object — extra field is rejected."""
        bad = self._good()
        bad["ranked_ideas"][0]["feasibility"]["unknown_signal"] = "medium"
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_evidence_ref_rejected(self) -> None:
        """ROUND-2 anti-slop fix: a whitespace-only evidence_ref is rejected (pattern \\S)."""
        bad = self._good()
        bad["ranked_ideas"][0]["evidence_ref"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_summary_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["summary"] = " "
        assert validate_against(self.SCHEMA, bad) != []

    def test_from_hypothesis_ref_without_digit_rejected(self) -> None:
        """ROUND-2 smuggle-block: from_hypothesis_ref must look like a real ref (contain a digit),
        so a flag-word like 'SELECTED'/'WINNER' cannot be smuggled through this free-text field."""
        bad = self._good()
        bad["ranked_ideas"][0]["from_hypothesis_ref"] = "SELECTED"
        assert validate_against(self.SCHEMA, bad) != []

    def test_novelty_ref_without_digit_rejected(self) -> None:
        bad = self._good()
        bad["ranked_ideas"][0]["novelty_ref"] = "WINNER"
        assert validate_against(self.SCHEMA, bad) != []

    def test_ref_fields_with_digit_validate(self) -> None:
        """Real refs (containing a digit) pass the smuggle-block guard."""
        good = self._good()
        good["ranked_ideas"][0]["from_hypothesis_ref"] = "IH1"
        good["ranked_ideas"][0]["novelty_ref"] = "GAP-2"
        assert validate_against(self.SCHEMA, good) == []
