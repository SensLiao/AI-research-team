"""Tests for CLUSTER D2 schemas: venue_review and venue_readiness_verdict.

Uses validate_against() — validates directly against schema files, NO PAYLOAD_SCHEMAS
registration needed. All tests GREEN before main-thread integration.

Governance invariants tested:
  venue_review:
    - NO verdict/meets_bar/decision/status/accept field (additionalProperties:false)
    - Anti-slop: evidence_ref minItems:1 with pattern \\S on items
    - dim scores are integers 1-4; evidence_ref per dim is non-empty
    - reject_triggers_fired structure enforced
    - confidence is integer 1-5

  venue_readiness_verdict:
    - allOf crown-jewel: non-empty unresolved_reject_triggers FORCES verdict NOT in {MEETS-BAR, BORDERLINE}
    - Anti-slop: evidence_ref minItems:1, dimension_synthesis argument pattern \\S
    - verdict enum enforced
    - dimension_synthesis structure enforced
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ===========================================================================
# Helpers
# ===========================================================================

def _dim_score(score: int = 3) -> dict:
    return {"score": score, "evidence_ref": ["evidence/path/result.json"]}


def _trigger(trigger_id: str = "RT-D4-BASELINE") -> dict:
    return {
        "trigger_id": trigger_id,
        "dimension": "D4",
        "locus": "Table 2, comparison with Baseline B",
        "required_fix": "Re-run with the baseline's published hyperparameters.",
    }


def _good_venue_review(
    persona: str = "methodology",
    triggers: list | None = None,
) -> dict:
    return {
        "persona": persona,
        "venue_id": "NeurIPS-2025",
        "dimension_scores": {
            "D1": _dim_score(3),
            "D2": _dim_score(3),
            "D3": _dim_score(3),
            "D4": _dim_score(3),
        },
        "reject_triggers_fired": triggers if triggers is not None else [],
        "overall": "Weak Accept",
        "confidence": 4,
        "evidence_ref": ["runs/r001/evidence/ANALYZE/result-summary.artifact.json"],
    }


def _good_venue_readiness_verdict(
    verdict: str = "MEETS-BAR",
    unresolved: list | None = None,
) -> dict:
    return {
        "verdict": verdict,
        "unresolved_reject_triggers": unresolved if unresolved is not None else [],
        "dimension_synthesis": [
            {
                "dimension": "D1",
                "argument": "Both methodology and adversarial reviewers found strong evidence chain.",
                "agreed_score": 3,
            }
        ],
        "evidence_ref": [
            "runs/r001/evidence/VERIFY/review-methodology-001.artifact.json",
        ],
    }


# ===========================================================================
# 1. venue_review schema
# ===========================================================================

class TestVenueReviewSchema:
    SCHEMA = "venue_review.schema.json"

    # --- Happy path ---

    def test_minimal_valid_review(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_review()) == []

    def test_adversarial_persona_validates(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_review(persona="adversarial")) == []

    def test_domain_persona_validates(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_review(persona="domain")) == []

    def test_with_trigger_fired_validates(self) -> None:
        review = _good_venue_review(triggers=[_trigger()])
        assert validate_against(self.SCHEMA, review) == []

    def test_with_optional_minimal_fix_validates(self) -> None:
        review = _good_venue_review()
        review["minimal_fix"] = "Add ablation study for the proposed module."
        assert validate_against(self.SCHEMA, review) == []

    def test_dim_score_with_notes_validates(self) -> None:
        review = _good_venue_review()
        review["dimension_scores"]["D1"]["notes"] = "Strong claims but baseline D1 is borderline."
        assert validate_against(self.SCHEMA, review) == []

    def test_all_seven_dims_validates(self) -> None:
        review = _good_venue_review()
        review["dimension_scores"].update({
            "D5": _dim_score(3),
            "D6": _dim_score(3),
            "D7": _dim_score(3),
        })
        assert validate_against(self.SCHEMA, review) == []

    def test_min_confidence_1_validates(self) -> None:
        review = _good_venue_review()
        review["confidence"] = 1
        assert validate_against(self.SCHEMA, review) == []

    def test_max_confidence_5_validates(self) -> None:
        review = _good_venue_review()
        review["confidence"] = 5
        assert validate_against(self.SCHEMA, review) == []

    def test_min_dim_score_1_validates(self) -> None:
        review = _good_venue_review()
        review["dimension_scores"]["D1"] = _dim_score(1)
        assert validate_against(self.SCHEMA, review) == []

    def test_max_dim_score_4_validates(self) -> None:
        review = _good_venue_review()
        review["dimension_scores"]["D1"] = _dim_score(4)
        assert validate_against(self.SCHEMA, review) == []

    # --- No-self-decision: the governance invariant ---

    def test_meets_bar_field_rejected(self) -> None:
        """THE GOVERNANCE INVARIANT: venue_review with 'meets_bar' field is REJECTED.

        Reviewers never self-decide. additionalProperties:false prevents any verdict field.
        This is the hard proof that the schema structurally blocks self-decision.
        """
        bad = _good_venue_review()
        bad["meets_bar"] = "yes"
        errs = validate_against(self.SCHEMA, bad)
        assert errs != [], (
            "GOVERNANCE VIOLATION: schema must REJECT a venue_review with 'meets_bar' field "
            "— reviewers never self-decide, additionalProperties:false is the structural guard"
        )

    def test_verdict_field_rejected(self) -> None:
        """No 'verdict' field allowed on venue_review."""
        bad = _good_venue_review()
        bad["verdict"] = "ACCEPT"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject venue_review with 'verdict' field"
        )

    def test_decision_field_rejected(self) -> None:
        """No 'decision' field allowed."""
        bad = _good_venue_review()
        bad["decision"] = "accept"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject venue_review with 'decision' field"
        )

    def test_status_field_rejected(self) -> None:
        """No 'status' field allowed."""
        bad = _good_venue_review()
        bad["status"] = "meets_bar"
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject venue_review with 'status' field"
        )

    def test_accept_field_rejected(self) -> None:
        """No 'accept' field allowed."""
        bad = _good_venue_review()
        bad["accept"] = True
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject venue_review with 'accept' field"
        )

    def test_extra_top_level_field_rejected(self) -> None:
        """additionalProperties:false — any unknown top-level key is rejected."""
        bad = _good_venue_review()
        bad["recommendation"] = "Accept"
        assert validate_against(self.SCHEMA, bad) != []

    # --- Anti-slop: evidence_ref ---

    def test_empty_evidence_ref_rejected(self) -> None:
        """Anti-slop: evidence_ref must have minItems:1."""
        bad = _good_venue_review()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject empty evidence_ref (anti-slop guard)"
        )

    def test_whitespace_evidence_ref_rejected(self) -> None:
        """Anti-slop: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = _good_venue_review()
        bad["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- Anti-slop: dim evidence_ref ---

    def test_dim_empty_evidence_ref_rejected(self) -> None:
        """Per-dimension evidence_ref must have minItems:1."""
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 3, "evidence_ref": []}
        assert validate_against(self.SCHEMA, bad) != []

    def test_dim_whitespace_evidence_ref_rejected(self) -> None:
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 3, "evidence_ref": ["  "]}
        assert validate_against(self.SCHEMA, bad) != []

    def test_dim_missing_evidence_ref_rejected(self) -> None:
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 3}
        assert validate_against(self.SCHEMA, bad) != []

    # --- Score range enforcement ---

    def test_dim_score_0_rejected(self) -> None:
        """Score must be >= 1."""
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 0, "evidence_ref": ["ref"]}
        assert validate_against(self.SCHEMA, bad) != []

    def test_dim_score_5_rejected(self) -> None:
        """Score must be <= 4."""
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 5, "evidence_ref": ["ref"]}
        assert validate_against(self.SCHEMA, bad) != []

    def test_dim_score_float_rejected(self) -> None:
        """Score must be integer."""
        bad = _good_venue_review()
        bad["dimension_scores"]["D1"] = {"score": 3.5, "evidence_ref": ["ref"]}
        assert validate_against(self.SCHEMA, bad) != []

    # --- Confidence range ---

    def test_confidence_0_rejected(self) -> None:
        bad = _good_venue_review()
        bad["confidence"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    def test_confidence_6_rejected(self) -> None:
        bad = _good_venue_review()
        bad["confidence"] = 6
        assert validate_against(self.SCHEMA, bad) != []

    # --- Required fields ---

    def test_missing_persona_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["persona"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_persona_rejected(self) -> None:
        bad = _good_venue_review()
        bad["persona"] = "scientific-critic"
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_venue_id_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["venue_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_venue_id_rejected(self) -> None:
        bad = _good_venue_review()
        bad["venue_id"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_overall_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["overall"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_overall_rejected(self) -> None:
        bad = _good_venue_review()
        bad["overall"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_confidence_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["confidence"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_dimension_scores_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["dimension_scores"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_reject_triggers_fired_rejected(self) -> None:
        bad = _good_venue_review()
        del bad["reject_triggers_fired"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- Reject-trigger structure ---

    def test_trigger_missing_trigger_id_rejected(self) -> None:
        t = _trigger()
        del t["trigger_id"]
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_whitespace_trigger_id_rejected(self) -> None:
        t = _trigger()
        t["trigger_id"] = "  "
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_invalid_dimension_rejected(self) -> None:
        t = _trigger()
        t["dimension"] = "D8"
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_missing_locus_rejected(self) -> None:
        t = _trigger()
        del t["locus"]
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_whitespace_locus_rejected(self) -> None:
        t = _trigger()
        t["locus"] = " "
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_missing_required_fix_rejected(self) -> None:
        t = _trigger()
        del t["required_fix"]
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []

    def test_trigger_extra_field_rejected(self) -> None:
        """additionalProperties:false on trigger items."""
        t = _trigger()
        t["extra"] = "oops"
        bad = _good_venue_review(triggers=[t])
        assert validate_against(self.SCHEMA, bad) != []


# ===========================================================================
# 2. venue_readiness_verdict schema
# ===========================================================================

class TestVenueReadinessVerdictSchema:
    SCHEMA = "venue_readiness_verdict.schema.json"

    # --- Happy path ---

    def test_meets_bar_no_triggers_validates(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_readiness_verdict("MEETS-BAR")) == []

    def test_borderline_no_triggers_validates(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_readiness_verdict("BORDERLINE")) == []

    def test_not_yet_no_triggers_validates(self) -> None:
        assert validate_against(self.SCHEMA, _good_venue_readiness_verdict("NOT-YET")) == []

    def test_not_yet_with_trigger_validates(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        assert validate_against(self.SCHEMA, v) == []

    def test_wrong_path_with_trigger_validates(self) -> None:
        v = _good_venue_readiness_verdict("WRONG-PATH", unresolved=["RT-D1-OVERCLAIM"])
        assert validate_against(self.SCHEMA, v) == []

    def test_degraded_review_validates(self) -> None:
        v = _good_venue_readiness_verdict("DEGRADED-REVIEW")
        assert validate_against(self.SCHEMA, v) == []

    def test_with_gaps_validates(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"gap": "Weak baseline comparison", "stage": "S3-EXECUTE", "what_to_add": "Run against SOTA."}]
        assert validate_against(self.SCHEMA, v) == []

    def test_with_strengths_and_shore_up_validates(self) -> None:
        v = _good_venue_readiness_verdict("MEETS-BAR")
        v["strengths"] = ["D1=4 (excellent soundness)"]
        v["shore_up"] = ["D6 clarity could be improved in Section 4."]
        assert validate_against(self.SCHEMA, v) == []

    def test_with_independence_ref_validates(self) -> None:
        v = _good_venue_readiness_verdict("MEETS-BAR")
        v["independence_ref"] = "runs/r001/evidence/VERIFY/independence-report.json"
        assert validate_against(self.SCHEMA, v) == []

    def test_with_agreed_score_in_synthesis_validates(self) -> None:
        v = _good_venue_readiness_verdict("MEETS-BAR")
        v["dimension_synthesis"][0]["agreed_score"] = 3
        assert validate_against(self.SCHEMA, v) == []

    # --- Crown-jewel allOf: triggered -> NOT in {MEETS-BAR, BORDERLINE} ---

    def test_meets_bar_with_trigger_rejected(self) -> None:
        """THE CROWN-JEWEL: MEETS-BAR + unresolved trigger is structurally impossible.

        This tests the allOf constraint:
        if unresolved_reject_triggers.minItems >= 1 then verdict NOT in {MEETS-BAR, BORDERLINE}.
        """
        bad = _good_venue_readiness_verdict("MEETS-BAR", unresolved=["RT-D4-LEAKAGE"])
        errs = validate_against(self.SCHEMA, bad)
        assert errs != [], (
            "GOVERNANCE VIOLATION: schema allOf must REJECT MEETS-BAR with non-empty "
            "unresolved_reject_triggers — the crown-jewel derivation guard"
        )

    def test_borderline_with_trigger_rejected(self) -> None:
        """allOf also blocks BORDERLINE when triggers present."""
        bad = _good_venue_readiness_verdict("BORDERLINE", unresolved=["RT-D3-INCREMENTAL"])
        errs = validate_against(self.SCHEMA, bad)
        assert errs != [], (
            "Schema allOf must REJECT BORDERLINE with non-empty unresolved_reject_triggers"
        )

    def test_not_yet_with_trigger_passes_allof(self) -> None:
        """NOT-YET + trigger is allowed by allOf."""
        ok = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-LEAKAGE"])
        assert validate_against(self.SCHEMA, ok) == []

    def test_wrong_path_with_trigger_passes_allof(self) -> None:
        """WRONG-PATH + trigger is allowed by allOf."""
        ok = _good_venue_readiness_verdict("WRONG-PATH", unresolved=["RT-D1-OVERCLAIM"])
        assert validate_against(self.SCHEMA, ok) == []

    def test_degraded_review_with_trigger_passes_allof(self) -> None:
        """DEGRADED-REVIEW + trigger is allowed by allOf."""
        ok = _good_venue_readiness_verdict("DEGRADED-REVIEW", unresolved=["RT-D4-BASELINE"])
        assert validate_against(self.SCHEMA, ok) == []

    # --- Anti-slop: evidence_ref ---

    def test_empty_evidence_ref_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject empty evidence_ref (anti-slop guard)"
        )

    def test_whitespace_evidence_ref_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["evidence_ref"] = ["  "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- dimension_synthesis argument anti-slop ---

    def test_whitespace_argument_in_synthesis_rejected(self) -> None:
        """Argument must be non-whitespace (pattern \\S)."""
        bad = _good_venue_readiness_verdict()
        bad["dimension_synthesis"][0]["argument"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_argument_in_synthesis_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["dimension_synthesis"][0]["argument"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_dimension_in_synthesis_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["dimension_synthesis"][0]["dimension"] = "D9"
        assert validate_against(self.SCHEMA, bad) != []

    def test_synthesis_missing_argument_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["dimension_synthesis"][0]["argument"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_synthesis_missing_dimension_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["dimension_synthesis"][0]["dimension"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_synthesis_extra_field_rejected(self) -> None:
        """additionalProperties:false on dimension_synthesis items."""
        bad = _good_venue_readiness_verdict()
        bad["dimension_synthesis"][0]["extra"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    # --- verdict enum ---

    def test_invalid_verdict_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["verdict"] = "ACCEPT"
        assert validate_against(self.SCHEMA, bad) != []

    def test_lowercase_verdict_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        bad["verdict"] = "meets-bar"
        assert validate_against(self.SCHEMA, bad) != []

    # --- Required fields ---

    def test_missing_verdict_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["verdict"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_unresolved_triggers_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["unresolved_reject_triggers"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_dimension_synthesis_rejected(self) -> None:
        bad = _good_venue_readiness_verdict()
        del bad["dimension_synthesis"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- Extra top-level fields ---

    def test_extra_top_level_field_rejected(self) -> None:
        """additionalProperties:false — extra field at top level rejected."""
        bad = _good_venue_readiness_verdict()
        bad["recommendation"] = "Submit now."
        assert validate_against(self.SCHEMA, bad) != []

    # --- gaps item structure ---

    def test_gaps_item_missing_gap_rejected(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"stage": "S3", "what_to_add": "Add ablation."}]
        assert validate_against(self.SCHEMA, v) != []

    def test_gaps_item_whitespace_gap_rejected(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"gap": "  ", "stage": "S3", "what_to_add": "Add ablation."}]
        assert validate_against(self.SCHEMA, v) != []

    def test_gaps_item_missing_stage_rejected(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"gap": "Weak evaluation", "what_to_add": "Add ablation."}]
        assert validate_against(self.SCHEMA, v) != []

    def test_gaps_item_missing_what_to_add_rejected(self) -> None:
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"gap": "Weak evaluation", "stage": "S3"}]
        assert validate_against(self.SCHEMA, v) != []

    def test_gaps_extra_field_rejected(self) -> None:
        """additionalProperties:false on gaps items."""
        v = _good_venue_readiness_verdict("NOT-YET", unresolved=["RT-D4-BASELINE"])
        v["gaps"] = [{"gap": "Weak eval", "stage": "S3", "what_to_add": "Fix.", "extra": "x"}]
        assert validate_against(self.SCHEMA, v) != []
