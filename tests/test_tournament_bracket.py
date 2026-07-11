"""Tests for tournament_bracket.py deterministic tool (CLUSTER F).

Verifies:
  - 4 ideas -> exactly 6 matchups (C(4,2) = 6), complete round-robin.
  - Every matchup winner equals pair_a or pair_b.
  - Ranking is 1..N contiguous.
  - Ranking is stable and deterministic across two calls on the same input.
  - Higher-score idea wins matchups; tiebreak is lexicographically smaller idea_id.
  - A missing score_key defaults to 0.0 (documented behaviour).
  - build_bracket output validates against idea_tournament.schema.json (after
    binding a non-empty evidence_ref).
  - build_bracket with empty ideas raises ValueError.
  - Single-idea bracket: 0 matchups is not valid (minItems:1 on matchups);
    bracket is only meaningful for N>=2.
"""
from __future__ import annotations

from itertools import combinations

import pytest

from research_agent_teams.tools.tournament_bracket import build_bracket, _play_match
from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "idea_tournament.schema.json"


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _idea(idea_id: str, score: float = 0.5) -> dict:
    """Build a minimal idea dict with an explicit score."""
    return {"idea_id": idea_id, "score": score}


def _four_ideas() -> list:
    """Four ideas with distinct scores: A=0.9, B=0.7, C=0.5, D=0.3."""
    return [
        _idea("IDEA-A", 0.9),
        _idea("IDEA-B", 0.7),
        _idea("IDEA-C", 0.5),
        _idea("IDEA-D", 0.3),
    ]


# --------------------------------------------------------------------------- #
#  Core completeness + correctness                                             #
# --------------------------------------------------------------------------- #

class TestBuildBracketCompleteness:

    def test_four_ideas_produce_six_matchups(self) -> None:
        """GOLDEN TEST: C(4,2) = 6 matchups for 4 ideas."""
        result = build_bracket(_four_ideas(), evidence_ref=["hyp-set-ref-001"])
        assert len(result["matchups"]) == 6, (
            f"Expected 6 matchups for 4 ideas, got {len(result['matchups'])}"
        )

    def test_all_pairs_present(self) -> None:
        """Every distinct pair of ideas must appear exactly once as a matchup."""
        ideas = _four_ideas()
        result = build_bracket(ideas, evidence_ref=["hyp-set-ref-001"])
        ids = sorted(i["idea_id"] for i in ideas)
        expected_pairs = set(
            (a, b) for a, b in combinations(ids, 2)
        )
        actual_pairs = set(
            (m["pair_a"], m["pair_b"]) for m in result["matchups"]
        )
        assert actual_pairs == expected_pairs, (
            f"Matchup pairs mismatch.\nExpected: {expected_pairs}\nGot: {actual_pairs}"
        )

    def test_winner_always_one_of_the_pair(self) -> None:
        """HARD GUARANTEE: winner must equal pair_a or pair_b for every matchup."""
        result = build_bracket(_four_ideas(), evidence_ref=["hyp-set-ref-001"])
        for m in result["matchups"]:
            assert m["winner"] in (m["pair_a"], m["pair_b"]), (
                f"winner '{m['winner']}' is not one of pair_a='{m['pair_a']}' "
                f"or pair_b='{m['pair_b']}'"
            )

    def test_higher_score_wins_matchup(self) -> None:
        """Higher-score idea wins each matchup."""
        ideas = [_idea("IDEA-HIGH", 0.9), _idea("IDEA-LOW", 0.1)]
        result = build_bracket(ideas, evidence_ref=["hyp-set-ref-001"])
        assert len(result["matchups"]) == 1
        assert result["matchups"][0]["winner"] == "IDEA-HIGH"

    def test_tiebreak_lexicographic_smaller_wins(self) -> None:
        """When scores are equal, the lexicographically smaller idea_id wins."""
        ideas = [_idea("IDEA-Z", 0.5), _idea("IDEA-A", 0.5)]
        result = build_bracket(ideas, evidence_ref=["hyp-set-ref-001"])
        # IDEA-A < IDEA-Z lexicographically -> IDEA-A wins the tie
        assert result["matchups"][0]["winner"] == "IDEA-A"

    def test_missing_score_key_defaults_to_zero(self) -> None:
        """An idea without the score_key field is treated as score=0.0 (documented)."""
        ideas = [
            {"idea_id": "IDEA-NO-SCORE"},
            {"idea_id": "IDEA-WITH-SCORE", "score": 0.5},
        ]
        result = build_bracket(ideas, evidence_ref=["ref-001"])
        # IDEA-WITH-SCORE has 0.5 > 0.0, should win
        assert result["matchups"][0]["winner"] == "IDEA-WITH-SCORE"

    def test_custom_score_key(self) -> None:
        """build_bracket respects a custom score_key argument."""
        ideas = [
            {"idea_id": "IDEA-A", "priority": 0.8},
            {"idea_id": "IDEA-B", "priority": 0.3},
        ]
        result = build_bracket(ideas, score_key="priority", evidence_ref=["ref-001"])
        assert result["matchups"][0]["winner"] == "IDEA-A"


# --------------------------------------------------------------------------- #
#  Ranking correctness                                                         #
# --------------------------------------------------------------------------- #

class TestBuildBracketRanking:

    def test_ranking_is_1_to_n_contiguous(self) -> None:
        """Ranks must be the contiguous integers 1..N."""
        result = build_bracket(_four_ideas(), evidence_ref=["ref-001"])
        ranks = sorted(r["rank"] for r in result["ranking"])
        n = len(_four_ideas())
        assert ranks == list(range(1, n + 1)), (
            f"Ranks must be 1..{n} contiguous, got {ranks}"
        )

    def test_top_ranked_has_most_wins(self) -> None:
        """Rank-1 idea has the most wins (or shares wins with tiebreak applied)."""
        result = build_bracket(_four_ideas(), evidence_ref=["ref-001"])
        rank1 = next(r for r in result["ranking"] if r["rank"] == 1)
        assert rank1["idea_id"] == "IDEA-A", (
            "IDEA-A has the highest score (0.9) and should win all 3 matchups -> rank 1"
        )
        assert rank1["wins"] == 3  # beats B, C, D

    def test_bottom_ranked_has_fewest_wins(self) -> None:
        """Rank-N idea has the fewest wins in a distinct-score bracket."""
        result = build_bracket(_four_ideas(), evidence_ref=["ref-001"])
        rank4 = next(r for r in result["ranking"] if r["rank"] == 4)
        assert rank4["idea_id"] == "IDEA-D"
        assert rank4["wins"] == 0  # loses to A, B, C

    def test_ranking_len_equals_ideas_count(self) -> None:
        """ranking must contain exactly one entry per idea."""
        ideas = _four_ideas()
        result = build_bracket(ideas, evidence_ref=["ref-001"])
        assert len(result["ranking"]) == len(ideas)

    def test_wins_sum_equals_matchup_count(self) -> None:
        """Total wins across all ideas must equal the number of matchups (each matchup
        has exactly one winner)."""
        result = build_bracket(_four_ideas(), evidence_ref=["ref-001"])
        total_wins = sum(r["wins"] for r in result["ranking"])
        assert total_wins == len(result["matchups"])

    def test_tie_ranking_stable_by_idea_id(self) -> None:
        """When win-counts are equal, ranking is broken by idea_id ASC."""
        # Three ideas with equal score -> same wins (1 each in a 3-idea bracket)
        # after all matchups; the order is determined by idea_id.
        ideas = [_idea("IDEA-C", 0.5), _idea("IDEA-A", 0.5), _idea("IDEA-B", 0.5)]
        result = build_bracket(ideas, evidence_ref=["ref-001"])
        ranked_ids = [r["idea_id"] for r in result["ranking"]]
        # With equal scores, tiebreak within matchups is by idea_id (smaller wins).
        # IDEA-A beats IDEA-B (A<B), IDEA-A beats IDEA-C (A<C), IDEA-B beats IDEA-C (B<C)
        # -> A wins 2, B wins 1, C wins 0 -> ranks: A=1, B=2, C=3
        assert ranked_ids[0] == "IDEA-A"
        assert ranked_ids[1] == "IDEA-B"
        assert ranked_ids[2] == "IDEA-C"


# --------------------------------------------------------------------------- #
#  Determinism                                                                 #
# --------------------------------------------------------------------------- #

class TestBuildBracketDeterminism:

    def test_stable_across_two_calls(self) -> None:
        """GOLDEN TEST: same input -> same output on two separate calls (deterministic)."""
        ideas = _four_ideas()
        first = build_bracket(ideas, evidence_ref=["ref-001"])
        second = build_bracket(ideas, evidence_ref=["ref-001"])
        assert first["matchups"] == second["matchups"], "matchups differ between calls"
        assert first["ranking"] == second["ranking"], "ranking differs between calls"

    def test_stable_regardless_of_input_order(self) -> None:
        """The bracket is the same whether ideas are passed sorted or reversed."""
        ideas = _four_ideas()
        reversed_ideas = list(reversed(ideas))
        result_forward = build_bracket(ideas, evidence_ref=["ref-001"])
        result_reversed = build_bracket(reversed_ideas, evidence_ref=["ref-001"])
        assert result_forward["matchups"] == result_reversed["matchups"]
        assert result_forward["ranking"] == result_reversed["ranking"]

    def test_two_ideas_one_matchup(self) -> None:
        """C(2,2) = 1 matchup for 2 ideas; ranking has 2 entries."""
        ideas = [_idea("IDEA-X", 0.8), _idea("IDEA-Y", 0.3)]
        result = build_bracket(ideas, evidence_ref=["ref-001"])
        assert len(result["matchups"]) == 1
        assert len(result["ranking"]) == 2


# --------------------------------------------------------------------------- #
#  Schema validation                                                           #
# --------------------------------------------------------------------------- #

class TestBuildBracketSchemaValidation:

    def test_output_validates_against_schema(self) -> None:
        """build_bracket output must validate against idea_tournament.schema.json."""
        result = build_bracket(_four_ideas(), evidence_ref=["hypothesis-set-001"])
        errors = validate_against(SCHEMA, result)
        assert errors == [], f"Schema validation failed: {errors}"

    def test_output_with_two_ideas_validates(self) -> None:
        """Minimal bracket (2 ideas, 1 matchup) must validate."""
        ideas = [_idea("IDEA-P", 0.9), _idea("IDEA-Q", 0.4)]
        result = build_bracket(ideas, evidence_ref=["hyp-ref-001"])
        errors = validate_against(SCHEMA, result)
        assert errors == [], f"Schema validation failed: {errors}"


# --------------------------------------------------------------------------- #
#  Edge cases and error handling                                               #
# --------------------------------------------------------------------------- #

class TestBuildBracketEdgeCases:

    def test_empty_ideas_raises_value_error(self) -> None:
        """build_bracket with an empty list must raise ValueError."""
        with pytest.raises(ValueError, match="at least one idea"):
            build_bracket([], evidence_ref=["ref-001"])

    def test_evidence_ref_preserved(self) -> None:
        """Caller-supplied evidence_ref is preserved in the output."""
        refs = ["hyp-set-001", "gap-ref-002"]
        result = build_bracket(_four_ideas(), evidence_ref=refs)
        assert result["evidence_ref"] == refs

    def test_empty_evidence_ref_not_validated_by_tool(self) -> None:
        """The tool returns the empty evidence_ref as-is; the schema rejects it.
        The agent is responsible for binding a non-empty evidence_ref before emitting."""
        result = build_bracket(_four_ideas())
        # The tool itself returns [] for evidence_ref when none is provided;
        # schema validation on this output will fail (minItems:1) -- that is expected.
        schema_errors = validate_against(SCHEMA, result)
        assert schema_errors != [], (
            "Schema must reject a tournament with empty evidence_ref (anti-slop guard)"
        )
