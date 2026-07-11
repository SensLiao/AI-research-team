"""Tests for CLUSTER F (IDEATE-ring completion) schemas:
  idea_tournament  — pairwise bracket output of idea-tournament-ranker.
  evolved_ideas    — mutation/recombination output of idea-evolver.

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required.  All tests are GREEN before main-thread integration.

Anti-slop structural guards tested:
  - idea_tournament: matchups + ranking + evidence_ref all required; winner constraint
    (winner must equal pair_a or pair_b — tool-level guarantee, schema-level structural test).
  - evolved_ideas: parent_ids minItems:1 — an evolved idea with no parents is rejected
    (the core anti-slop provenance guard: 'where did this come from').
  - Both schemas: empty/whitespace evidence_ref rejected; additionalProperties:false;
    extra fields rejected.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. idea_tournament
# ==============================================================================

class TestIdeaTournamentSchema:
    SCHEMA = "idea_tournament.schema.json"

    def _good_matchup(
        self,
        pair_a: str = "IDEA-A",
        pair_b: str = "IDEA-B",
        winner: str = "IDEA-A",
    ) -> dict:
        return {"pair_a": pair_a, "pair_b": pair_b, "winner": winner}

    def _good_ranking_entry(
        self, idea_id: str = "IDEA-A", rank: int = 1, wins: int = 3
    ) -> dict:
        return {"idea_id": idea_id, "rank": rank, "wins": wins}

    def _good(self) -> dict:
        """A well-formed idea_tournament for 4 ideas (6 matchups, 4 ranking entries)."""
        return {
            "matchups": [
                self._good_matchup("IDEA-A", "IDEA-B", "IDEA-A"),
                self._good_matchup("IDEA-A", "IDEA-C", "IDEA-A"),
                self._good_matchup("IDEA-A", "IDEA-D", "IDEA-A"),
                self._good_matchup("IDEA-B", "IDEA-C", "IDEA-B"),
                self._good_matchup("IDEA-B", "IDEA-D", "IDEA-B"),
                self._good_matchup("IDEA-C", "IDEA-D", "IDEA-C"),
            ],
            "ranking": [
                self._good_ranking_entry("IDEA-A", rank=1, wins=3),
                self._good_ranking_entry("IDEA-B", rank=2, wins=2),
                self._good_ranking_entry("IDEA-C", rank=3, wins=1),
                self._good_ranking_entry("IDEA-D", rank=4, wins=0),
            ],
            "evidence_ref": ["hypothesis-set-001", "gap-ref-002"],
        }

    # --- happy-path ---

    def test_wellformed_validates(self) -> None:
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_minimal_two_idea_tournament_validates(self) -> None:
        """A minimal tournament with 2 ideas (1 matchup, 2 ranking entries) is valid."""
        good = {
            "matchups": [self._good_matchup("IDEA-X", "IDEA-Y", "IDEA-X")],
            "ranking": [
                self._good_ranking_entry("IDEA-X", rank=1, wins=1),
                self._good_ranking_entry("IDEA-Y", rank=2, wins=0),
            ],
            "evidence_ref": ["hyp-set-001"],
        }
        assert validate_against(self.SCHEMA, good) == []

    def test_winner_equals_pair_a_validates(self) -> None:
        good = self._good()
        good["matchups"][0]["winner"] = good["matchups"][0]["pair_a"]
        assert validate_against(self.SCHEMA, good) == []

    def test_winner_equals_pair_b_validates(self) -> None:
        good = self._good()
        good["matchups"][0]["winner"] = good["matchups"][0]["pair_b"]
        assert validate_against(self.SCHEMA, good) == []

    # --- required-field guards ---

    def test_missing_matchups_rejected(self) -> None:
        bad = self._good()
        del bad["matchups"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_ranking_rejected(self) -> None:
        bad = self._good()
        del bad["ranking"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        bad = self._good()
        del bad["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- matchup item guards ---

    def test_missing_pair_a_rejected(self) -> None:
        bad = self._good()
        del bad["matchups"][0]["pair_a"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_pair_b_rejected(self) -> None:
        bad = self._good()
        del bad["matchups"][0]["pair_b"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_winner_in_matchup_rejected(self) -> None:
        bad = self._good()
        del bad["matchups"][0]["winner"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_blank_pair_a_rejected(self) -> None:
        bad = self._good()
        bad["matchups"][0]["pair_a"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_blank_pair_b_rejected(self) -> None:
        bad = self._good()
        bad["matchups"][0]["pair_b"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_blank_winner_rejected(self) -> None:
        bad = self._good()
        bad["matchups"][0]["winner"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_winner_rejected(self) -> None:
        """Anti-slop: whitespace-only winner is rejected (pattern \\S)."""
        bad = self._good()
        bad["matchups"][0]["winner"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    # --- ranking item guards ---

    def test_missing_idea_id_in_ranking_rejected(self) -> None:
        bad = self._good()
        del bad["ranking"][0]["idea_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_rank_in_ranking_rejected(self) -> None:
        bad = self._good()
        del bad["ranking"][0]["rank"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_wins_in_ranking_rejected(self) -> None:
        bad = self._good()
        del bad["ranking"][0]["wins"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_rank_zero_rejected(self) -> None:
        """rank minimum:1 — rank=0 is rejected."""
        bad = self._good()
        bad["ranking"][0]["rank"] = 0
        assert validate_against(self.SCHEMA, bad) != []

    def test_wins_negative_rejected(self) -> None:
        """wins minimum:0 — negative wins are rejected."""
        bad = self._good()
        bad["ranking"][0]["wins"] = -1
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop evidence_ref guards ---

    def test_empty_evidence_ref_rejected(self) -> None:
        """Anti-slop: evidence_ref minItems:1 — empty list rejected."""
        bad = self._good()
        bad["evidence_ref"] = []
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject idea_tournament with empty evidence_ref (anti-slop guard)"
        )

    def test_whitespace_evidence_ref_rejected(self) -> None:
        """Anti-slop: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_evidence_ref_rejected(self) -> None:
        bad = self._good()
        bad["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false guards ---

    def test_extra_top_level_field_rejected(self) -> None:
        """additionalProperties:false — unknown top-level key is rejected."""
        bad = self._good()
        bad["selected"] = "IDEA-A"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_matchup_field_rejected(self) -> None:
        """additionalProperties:false on matchup items — extra field rejected."""
        bad = self._good()
        bad["matchups"][0]["score_delta"] = 0.5
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_ranking_field_rejected(self) -> None:
        """additionalProperties:false on ranking items — extra field rejected."""
        bad = self._good()
        bad["ranking"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_winner_field_on_tournament_rejected(self) -> None:
        """No winner/selected/picked field on the tournament itself (no-self-pick)."""
        bad = self._good()
        bad["winner"] = "IDEA-A"
        assert validate_against(self.SCHEMA, bad) != []

    # --- minItems guards ---

    def test_empty_matchups_rejected(self) -> None:
        """matchups minItems:1 — empty list rejected."""
        bad = self._good()
        bad["matchups"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_ranking_rejected(self) -> None:
        """ranking minItems:1 — empty list rejected."""
        bad = self._good()
        bad["ranking"] = []
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 2. evolved_ideas
# ==============================================================================

class TestEvolvedIdeasSchema:
    SCHEMA = "evolved_ideas.schema.json"

    def _good_idea(
        self,
        idea_id: str = "EV-001",
        parent_ids: list | None = None,
        mutation_type: str | None = "mutate",
    ) -> dict:
        idea: dict = {
            "idea_id": idea_id,
            "summary": "Evolved contrastive pre-training by swapping loss to SimCLR.",
            "parent_ids": parent_ids if parent_ids is not None else ["IDEA-A"],
            "evidence_ref": ["idea-tournament-001", "gap-ref-002"],
        }
        if mutation_type is not None:
            idea["mutation_type"] = mutation_type
        return idea

    def _good(self) -> dict:
        return {
            "ideas": [
                self._good_idea("EV-001", ["IDEA-A"], "mutate"),
                self._good_idea("EV-002", ["IDEA-A", "IDEA-B"], "recombine"),
                self._good_idea("EV-003", ["IDEA-B"], "strengthen"),
            ]
        }

    # --- happy-path ---

    def test_wellformed_validates(self) -> None:
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_single_evolved_idea_validates(self) -> None:
        good = {"ideas": [self._good_idea()]}
        assert validate_against(self.SCHEMA, good) == []

    def test_two_parents_recombine_validates(self) -> None:
        good = {"ideas": [self._good_idea("EV-001", ["IDEA-A", "IDEA-B"], "recombine")]}
        assert validate_against(self.SCHEMA, good) == []

    def test_without_optional_mutation_type_validates(self) -> None:
        """mutation_type is optional; omitting it is valid."""
        good = {"ideas": [self._good_idea(mutation_type=None)]}
        assert validate_against(self.SCHEMA, good) == []

    def test_all_mutation_types_validate(self) -> None:
        for mtype in ("mutate", "recombine", "strengthen"):
            good = {"ideas": [self._good_idea(mutation_type=mtype)]}
            assert validate_against(self.SCHEMA, good) == [], (
                f"mutation_type='{mtype}' should be valid"
            )

    # --- required-field guards ---

    def test_missing_ideas_rejected(self) -> None:
        assert validate_against(self.SCHEMA, {}) != []

    def test_missing_idea_id_rejected(self) -> None:
        bad = self._good()
        del bad["ideas"][0]["idea_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_summary_rejected(self) -> None:
        bad = self._good()
        del bad["ideas"][0]["summary"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_parent_ids_rejected(self) -> None:
        bad = self._good()
        del bad["ideas"][0]["parent_ids"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_ref_rejected(self) -> None:
        bad = self._good()
        del bad["ideas"][0]["evidence_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    # --- CORE ANTI-SLOP: parent_ids provenance guard ---

    def test_empty_parent_ids_rejected(self) -> None:
        """PROVENANCE GUARD: parent_ids minItems:1 — an evolved idea with no parents
        is schema-rejected ('where did this come from' anti-slop).
        This is the core structural guarantee for the idea-evolver."""
        bad = self._good()
        bad["ideas"][0]["parent_ids"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], (
            "Schema must reject an evolved idea with empty parent_ids "
            "(anti-slop provenance guard: 'where did this come from')"
        )

    def test_whitespace_parent_id_rejected(self) -> None:
        """Anti-slop: whitespace-only parent_id item rejected (pattern \\S)."""
        bad = self._good()
        bad["ideas"][0]["parent_ids"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_parent_id_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["parent_ids"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    # --- anti-slop evidence_ref guards ---

    def test_empty_evidence_ref_rejected(self) -> None:
        """Anti-slop: evidence_ref minItems:1 — empty list rejected."""
        bad = self._good()
        bad["ideas"][0]["evidence_ref"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], (
            "Schema must reject an evolved idea with empty evidence_ref (anti-slop guard)"
        )

    def test_whitespace_evidence_ref_rejected(self) -> None:
        """Anti-slop: whitespace-only evidence_ref item rejected (pattern \\S)."""
        bad = self._good()
        bad["ideas"][0]["evidence_ref"] = ["   "]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_string_evidence_ref_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["evidence_ref"] = [""]
        assert validate_against(self.SCHEMA, bad) != []

    # --- blank string guards ---

    def test_blank_idea_id_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["idea_id"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_idea_id_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["idea_id"] = "  "
        assert validate_against(self.SCHEMA, bad) != []

    def test_blank_summary_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["summary"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_whitespace_summary_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["summary"] = "   "
        assert validate_against(self.SCHEMA, bad) != []

    # --- invalid enum guard ---

    def test_invalid_mutation_type_rejected(self) -> None:
        bad = self._good()
        bad["ideas"][0]["mutation_type"] = "clone"
        assert validate_against(self.SCHEMA, bad) != []

    # --- additionalProperties:false guards ---

    def test_extra_top_level_field_rejected(self) -> None:
        """additionalProperties:false — unknown top-level key rejected."""
        bad = self._good()
        bad["selected"] = "EV-001"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_idea_field_rejected(self) -> None:
        """additionalProperties:false on idea items — unknown field rejected."""
        bad = self._good()
        bad["ideas"][0]["winner"] = True
        assert validate_against(self.SCHEMA, bad) != []

    def test_selected_field_on_idea_rejected(self) -> None:
        """No self-selection: 'selected' on an idea item must be rejected."""
        bad = self._good()
        bad["ideas"][0]["selected"] = True
        assert validate_against(self.SCHEMA, bad) != []

    # --- minItems on ideas ---

    def test_empty_ideas_rejected(self) -> None:
        """ideas minItems:1 — empty list rejected."""
        bad = self._good()
        bad["ideas"] = []
        assert validate_against(self.SCHEMA, bad) != []
