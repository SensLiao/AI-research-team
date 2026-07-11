"""Tests for the /idea-bet human gate (M3-a CLUSTER 2, IDEATE).

Verifies:
  1. A recorded bet (ADR) built according to the /idea-bet gate spec validates
     against the existing adr.schema.json.
  2. Structural no-self-bet proof: the idea_backlog schema rejects any attempt
     to add a 'selected' or similar field (the model cannot self-bet).

The /idea-bet gate is disable-model-invocation: true — the model is never invoked.
The bet is recorded ONLY by the human director as an ADR. This test suite verifies:
  (a) that a correctly constructed ADR validates (the gate works when used correctly),
  (b) that the idea_backlog schema structurally prevents the model from self-betting
      (additionalProperties:false + no selected/chosen/bet/winner fields).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against

ADR_SCHEMA = "adr.schema.json"
BACKLOG_SCHEMA = "idea_backlog.schema.json"


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _good_idea_backlog() -> dict:
    """A minimal valid idea_backlog with two ideas (needed so ADR can have >=2 options)."""
    return {
        "ranked_ideas": [
            {
                "idea_id": "IDEA-001",
                "rank": 1,
                "summary": "Contrastive pre-training on unlabelled CT volumes to close the annotation gap.",
                "feasibility": {"score": 0.8333},
                "evidence_ref": ["IH1", "gap-001"],
            },
            {
                "idea_id": "IDEA-002",
                "rank": 2,
                "summary": "Cross-modal transfer from natural images to medical scans via domain-adversarial training.",
                "feasibility": {"score": 0.4667},
                "evidence_ref": ["IH2", "gap-002"],
            },
        ]
    }


def _good_bet_adr() -> dict:
    """A well-formed ADR representing a director's recorded bet from the /idea-bet gate."""
    return {
        "decision_id": "ADR-0100",
        "question": "Which idea to bet on for run r-20260609-001?",
        "options": [
            "IDEA-001: Contrastive pre-training on unlabelled CT volumes to close the annotation gap.",
            "IDEA-002: Cross-modal transfer from natural images to medical scans via domain-adversarial training.",
        ],
        "chosen_option": (
            "IDEA-001: Contrastive pre-training on unlabelled CT volumes to close the annotation gap."
        ),
        "reason": (
            "Lower compute demand and public data availability; IDEA-001 aligns with the Q3 "
            "GPU budget ceiling and the domain profile's annotation-scarcity hard invariant."
        ),
        "status": "approved",
        "approved_by": "director",
        "approved_at": "2026-06-09T10:00:00Z",
        "downstream_locked_artifacts": ["idea_backlog"],
    }


# --------------------------------------------------------------------------- #
#  1. Recorded bet ADR validates against adr.schema.json                      #
# --------------------------------------------------------------------------- #

class TestIdeaBetAdr:

    def test_recorded_bet_validates(self) -> None:
        """A correctly built /idea-bet ADR must validate against adr.schema.json.

        This confirms the /idea-bet gate spec produces a valid ADR when the director
        fills it in correctly.
        """
        bet = _good_bet_adr()
        errors = validate_against(ADR_SCHEMA, bet)
        assert errors == [], (
            f"A well-formed /idea-bet ADR must validate: {errors}"
        )

    def test_bet_adr_with_evidence_list_validates(self) -> None:
        """ADR with an evidence list (optional field) also validates."""
        bet = _good_bet_adr()
        bet["evidence"] = ["idea-backlog.artifact.json", "hypothesis-set.artifact.json"]
        errors = validate_against(ADR_SCHEMA, bet)
        assert errors == []

    def test_bet_adr_missing_decision_id_rejected(self) -> None:
        """decision_id is required by adr schema."""
        bet = _good_bet_adr()
        del bet["decision_id"]
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_wrong_decision_id_format_rejected(self) -> None:
        """decision_id must match ^ADR-[0-9]{4,}$ — short numeric rejected."""
        bet = _good_bet_adr()
        bet["decision_id"] = "ADR-01"
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_single_option_rejected(self) -> None:
        """options minItems:2 — a single option is rejected (idea_backlog must have >=2 ideas)."""
        bet = _good_bet_adr()
        bet["options"] = ["IDEA-001: Only one idea"]
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_invalid_status_rejected(self) -> None:
        """status must be one of proposed/approved/rejected."""
        bet = _good_bet_adr()
        bet["status"] = "pending"
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_missing_question_rejected(self) -> None:
        bet = _good_bet_adr()
        del bet["question"]
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_missing_status_rejected(self) -> None:
        bet = _good_bet_adr()
        del bet["status"]
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_extra_field_rejected(self) -> None:
        """additionalProperties:false on adr — unknown fields rejected."""
        bet = _good_bet_adr()
        bet["extra_field"] = "not_allowed"
        assert validate_against(ADR_SCHEMA, bet) != []

    def test_bet_adr_proposed_status_validates(self) -> None:
        """A proposed (not yet approved) ADR is also valid per the schema."""
        bet = _good_bet_adr()
        bet["status"] = "proposed"
        bet.pop("approved_by", None)
        bet.pop("approved_at", None)
        errors = validate_against(ADR_SCHEMA, bet)
        assert errors == []

    def test_single_idea_backlog_plus_pivot_option_validates(self) -> None:
        """ROUND-2 FIX (1-idea dead-end): the /idea-bet gate ALWAYS appends a standing PIVOT option,
        so even a SINGLE-idea backlog forms a valid adr (options >= 2) and the director always has a
        real 'none of these' choice — never structurally forced to bet on a thin menu."""
        one_idea_backlog = {"ranked_ideas": [{
            "idea_id": "IDEA-001", "rank": 1, "summary": "The only defensible direction.",
            "feasibility": {"score": 0.7}, "evidence_ref": ["IH1"],
        }]}
        assert validate_against(BACKLOG_SCHEMA, one_idea_backlog) == []  # 1-idea backlog is valid
        options = [f"{i['idea_id']}: {i['summary']}" for i in one_idea_backlog["ranked_ideas"]]
        options.append("PIVOT: do not bet on any listed idea — re-scope the direction")
        bet = _good_bet_adr()
        bet["options"] = options
        bet["chosen_option"] = options[0]
        assert len(options) == 2
        assert validate_against(ADR_SCHEMA, bet) == []


# --------------------------------------------------------------------------- #
#  2. Structural no-self-bet proof                                             #
# --------------------------------------------------------------------------- #

class TestNoSelfBetStructuralProof:
    """The structural no-self-bet guarantee: the idea_backlog schema has NO selected/
    chosen/bet/winner/director_* field and is additionalProperties:false.

    These tests prove that a model CANNOT inject a self-bet into idea_backlog —
    the schema will reject any such attempt. The bet is recorded ONLY by the human
    /idea-bet gate as a separate ADR.
    """

    def test_idea_backlog_is_valid_without_any_bet_field(self) -> None:
        """Baseline: the clean idea_backlog validates (no bet field required or allowed)."""
        backlog = _good_idea_backlog()
        errors = validate_against(BACKLOG_SCHEMA, backlog)
        assert errors == [], f"Clean idea_backlog must validate: {errors}"

    def test_selected_on_backlog_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'selected' injected at top level is schema-rejected.

        This is the primary structural no-self-bet proof.  The model produces ranked_ideas;
        additionalProperties:false ensures it cannot mark a self-pick by adding 'selected'.
        """
        backlog = _good_idea_backlog()
        backlog["selected"] = True
        errors = validate_against(BACKLOG_SCHEMA, backlog)
        assert errors != [], (
            "CRITICAL: idea_backlog schema MUST reject 'selected' field — "
            "no-self-bet structural guarantee"
        )

    def test_chosen_on_backlog_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'chosen' is not in the schema."""
        backlog = _good_idea_backlog()
        backlog["chosen"] = "IDEA-001"
        assert validate_against(BACKLOG_SCHEMA, backlog) != [], (
            "idea_backlog schema must reject 'chosen' field — no-self-bet guard"
        )

    def test_bet_on_backlog_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'bet' is not in the schema."""
        backlog = _good_idea_backlog()
        backlog["bet"] = "IDEA-001"
        assert validate_against(BACKLOG_SCHEMA, backlog) != []

    def test_winner_on_backlog_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'winner' is not in the schema."""
        backlog = _good_idea_backlog()
        backlog["winner"] = "IDEA-001"
        assert validate_against(BACKLOG_SCHEMA, backlog) != []

    def test_director_pick_on_backlog_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'director_pick' (director_* pattern) is not in the schema."""
        backlog = _good_idea_backlog()
        backlog["director_pick"] = "IDEA-001"
        assert validate_against(BACKLOG_SCHEMA, backlog) != []

    def test_selected_on_ranked_idea_item_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'selected' injected onto a ranked_idea item is also rejected."""
        backlog = _good_idea_backlog()
        backlog["ranked_ideas"][0]["selected"] = True
        errors = validate_against(BACKLOG_SCHEMA, backlog)
        assert errors != [], (
            "idea_backlog schema must reject 'selected' on a ranked idea item — "
            "no-self-bet guard extends to item level"
        )

    def test_chosen_option_on_ranked_idea_item_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'chosen_option' (an ADR field leaked onto an idea item) is rejected."""
        backlog = _good_idea_backlog()
        backlog["ranked_ideas"][0]["chosen_option"] = "this idea"
        assert validate_against(BACKLOG_SCHEMA, backlog) != []

    def test_bet_recorded_only_as_adr_not_in_backlog(self) -> None:
        """Integration proof: the bet is the ADR, not any field in the backlog.

        A clean backlog + a valid bet ADR is the correct pattern.
        Neither the backlog nor any idea item carries the bet.
        """
        backlog = _good_idea_backlog()
        bet_adr = _good_bet_adr()

        # Backlog validates cleanly (no bet field)
        assert validate_against(BACKLOG_SCHEMA, backlog) == [], (
            "Backlog must be valid with no bet field"
        )
        # Bet ADR validates cleanly
        assert validate_against(ADR_SCHEMA, bet_adr) == [], (
            "Bet ADR must be valid"
        )
        # Confirm bet field is NOT in the backlog
        assert "selected" not in backlog
        assert "chosen" not in backlog
        assert "bet" not in backlog
        assert "winner" not in backlog
        for idea in backlog["ranked_ideas"]:
            assert "selected" not in idea
            assert "chosen" not in idea
