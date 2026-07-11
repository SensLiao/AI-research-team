"""Tests for the feasibility_score deterministic tool.

Verifies:
  - Higher-feasibility ideas rank above lower-feasibility ideas.
  - Stable tiebreak by idea_id (lexicographic ascending) when scores are equal.
  - Ranks are contiguous integers 1..N.
  - build_idea_backlog output validates against idea_backlog.schema.json.
  - An idea with empty evidence_ref is schema-rejected (anti-slop).
  - An idea_backlog with an extra 'selected' field is schema-rejected (no-self-bet).
  - Absent budget/signals produce a neutral fallback score (never crashes).
  - Absent feasibility object on idea is handled gracefully.
  - All scores are in [0, 1].
  - Ranking is reproducible (same input -> same output).
  - Budget compute ceiling modulates compute-heavy ideas.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.feasibility_score import (
    build_idea_backlog,
    rank_ideas,
    score_feasibility,
)
from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "idea_backlog.schema.json"


# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _make_idea(
    idea_id: str,
    compute: object = None,
    data: object = None,
    time: object = None,
    evidence_ref: list | None = None,
) -> dict:
    """Build a minimal valid idea dict."""
    feas: dict = {}
    if compute is not None:
        feas["compute"] = compute
    if data is not None:
        feas["data"] = data
    if time is not None:
        feas["time"] = time
    return {
        "idea_id": idea_id,
        "summary": f"Research idea {idea_id}",
        "feasibility": feas,
        "evidence_ref": evidence_ref if evidence_ref is not None else ["gap-001"],
    }


# --------------------------------------------------------------------------- #
#  score_feasibility tests                                                     #
# --------------------------------------------------------------------------- #

class TestScoreFeasibility:

    def test_all_signals_present_returns_expected_score(self) -> None:
        idea = _make_idea("A", compute="low", data="available", time="short")
        feas = score_feasibility(idea)
        assert feas["score"] == pytest.approx(1.0, abs=1e-4)

    def test_all_signals_absent_returns_neutral(self) -> None:
        """When no signals are declared, neutral fallback = 1.0 for each sub-score."""
        idea = _make_idea("A")
        feas = score_feasibility(idea)
        assert feas["score"] == pytest.approx(1.0, abs=1e-4)

    def test_no_feasibility_object_returns_neutral(self) -> None:
        """When the idea has no 'feasibility' key at all, fallback to neutral."""
        idea = {"idea_id": "A", "summary": "X", "evidence_ref": ["g1"]}
        feas = score_feasibility(idea)
        assert 0.0 <= feas["score"] <= 1.0

    def test_high_compute_low_score(self) -> None:
        idea = _make_idea("A", compute="high", data="available", time="short")
        feas = score_feasibility(idea)
        # compute "high" -> 0.2; data "available" -> 1.0; time "short" -> 1.0
        expected = round((0.2 + 1.0 + 1.0) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_unavailable_data_low_score(self) -> None:
        idea = _make_idea("A", compute="low", data="unavailable", time="short")
        feas = score_feasibility(idea)
        expected = round((1.0 + 0.1 + 1.0) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_long_time_low_score(self) -> None:
        idea = _make_idea("A", compute="low", data="available", time="long")
        feas = score_feasibility(idea)
        expected = round((1.0 + 1.0 + 0.2) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_numeric_compute_above_threshold(self) -> None:
        idea = _make_idea("A", compute=10.0, data="available", time="short")
        feas = score_feasibility(idea)
        # compute numeric 10 > 3 -> 0.2
        expected = round((0.2 + 1.0 + 1.0) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_numeric_compute_low(self) -> None:
        idea = _make_idea("A", compute=0.5, data="available", time="short")
        feas = score_feasibility(idea)
        # compute numeric 0.5 <= 1 -> 1.0
        expected = round((1.0 + 1.0 + 1.0) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_numeric_data_in_range(self) -> None:
        idea = _make_idea("A", data=0.7)
        feas = score_feasibility(idea)
        # data numeric 0.7 in [0,1] -> 0.7
        expected = round((1.0 + 0.7 + 1.0) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_score_always_in_unit_interval(self) -> None:
        ideas = [
            _make_idea("A", compute="high", data="unavailable", time="long"),
            _make_idea("B", compute="low", data="public", time="short"),
            _make_idea("C"),
        ]
        for idea in ideas:
            feas = score_feasibility(idea)
            assert 0.0 <= feas["score"] <= 1.0

    def test_budget_compute_ceiling_modulates_score(self) -> None:
        """When compute > budget ceiling, score is penalised."""
        idea = _make_idea("A", compute=5.0)
        budget = {"max_agent_hops": 10, "max_gpu_runs_before_review": 3}
        feas_with_budget = score_feasibility(idea, budget=budget)
        feas_without_budget = score_feasibility(idea)
        # With budget: compute 5 > 3 -> penalised; without: no penalty
        assert feas_with_budget["score"] <= feas_without_budget["score"]

    def test_budget_ceiling_absent_no_crash(self) -> None:
        idea = _make_idea("A", compute="high")
        feas = score_feasibility(idea, budget=None)
        assert 0.0 <= feas["score"] <= 1.0

    def test_profile_ignored_no_crash(self) -> None:
        idea = _make_idea("A")
        feas = score_feasibility(idea, profile={"profile_id": "cv-medical-segmentation"})
        assert 0.0 <= feas["score"] <= 1.0

    def test_unrecognised_string_signal_neutral(self) -> None:
        """Unrecognised string signals fall back to neutral 0.5."""
        idea = _make_idea("A", compute="unknown-level", data="???", time="???")
        feas = score_feasibility(idea)
        expected = round((0.5 + 0.5 + 0.5) / 3.0, 4)
        assert feas["score"] == pytest.approx(expected, abs=1e-4)

    def test_raw_signals_preserved_in_output(self) -> None:
        idea = _make_idea("A", compute="medium", data="restricted", time="long")
        feas = score_feasibility(idea)
        assert feas["compute"] == "medium"
        assert feas["data"] == "restricted"
        assert feas["time"] == "long"


# --------------------------------------------------------------------------- #
#  rank_ideas tests                                                            #
# --------------------------------------------------------------------------- #

class TestRankIdeas:

    def test_higher_feasibility_ranks_first(self) -> None:
        """GOLDEN TEST: a higher-feasibility idea ranks above a lower-feasibility one."""
        ideas = [
            _make_idea("IDEA-LOW", compute="high", data="unavailable", time="long"),
            _make_idea("IDEA-HIGH", compute="low", data="public", time="short"),
        ]
        ranked = rank_ideas(ideas)
        assert ranked[0]["idea_id"] == "IDEA-HIGH", (
            "Higher-feasibility idea must rank first (rank=1)"
        )
        assert ranked[0]["rank"] == 1
        assert ranked[1]["idea_id"] == "IDEA-LOW"
        assert ranked[1]["rank"] == 2

    def test_stable_tiebreak_by_idea_id(self) -> None:
        """When scores are equal, ideas are ranked by idea_id ascending (lexicographic)."""
        ideas = [
            _make_idea("IDEA-C"),
            _make_idea("IDEA-A"),
            _make_idea("IDEA-B"),
        ]
        # All neutral signals -> all same score
        ranked = rank_ideas(ideas)
        idea_ids = [r["idea_id"] for r in ranked]
        assert idea_ids == ["IDEA-A", "IDEA-B", "IDEA-C"], (
            "Equal-score ideas must be ranked by idea_id ascending (stable tiebreak)"
        )

    def test_ranks_are_contiguous_1_to_n(self) -> None:
        """Ranks must be the contiguous integers 1..N."""
        ideas = [
            _make_idea("IDEA-001", compute="low", data="public"),
            _make_idea("IDEA-002", compute="medium", data="restricted"),
            _make_idea("IDEA-003", compute="high", data="unavailable"),
            _make_idea("IDEA-004"),
        ]
        ranked = rank_ideas(ideas)
        ranks = sorted(r["rank"] for r in ranked)
        assert ranks == list(range(1, len(ideas) + 1)), (
            "Ranks must be contiguous integers 1..N"
        )

    def test_ranking_is_reproducible(self) -> None:
        """Same input -> same ranking on repeated calls (determinism)."""
        ideas = [
            _make_idea("IDEA-001", compute="high", data="unavailable", time="long"),
            _make_idea("IDEA-002", compute="low", data="public", time="short"),
            _make_idea("IDEA-003", compute="medium", data="restricted", time="medium"),
        ]
        ranked_first = rank_ideas(ideas)
        ranked_second = rank_ideas(ideas)
        first_order = [r["idea_id"] for r in ranked_first]
        second_order = [r["idea_id"] for r in ranked_second]
        assert first_order == second_order, "Ranking must be reproducible"

    def test_single_idea_ranks_as_1(self) -> None:
        ideas = [_make_idea("IDEA-001")]
        ranked = rank_ideas(ideas)
        assert len(ranked) == 1
        assert ranked[0]["rank"] == 1

    def test_rank_ideas_does_not_crash_with_no_feasibility(self) -> None:
        ideas = [
            {"idea_id": "IDEA-001", "summary": "X", "evidence_ref": ["g1"]},
        ]
        ranked = rank_ideas(ideas)
        assert ranked[0]["rank"] == 1
        assert 0.0 <= ranked[0]["feasibility"]["score"] <= 1.0

    def test_rank_ideas_budget_respected(self) -> None:
        ideas = [
            _make_idea("IDEA-CHEAP", compute=0.5),
            _make_idea("IDEA-EXPENSIVE", compute=10.0),
        ]
        budget = {"max_agent_hops": 10, "max_gpu_runs_before_review": 3}
        ranked = rank_ideas(ideas, budget=budget)
        assert ranked[0]["idea_id"] == "IDEA-CHEAP"


# --------------------------------------------------------------------------- #
#  build_idea_backlog + schema validation tests                                #
# --------------------------------------------------------------------------- #

class TestBuildIdeaBacklog:

    def _make_raw_ideas(self) -> list:
        return [
            {
                "idea_id": "IDEA-001",
                "summary": "Contrastive pre-training on unlabelled CT volumes.",
                "feasibility": {"score": 0.5, "compute": "low", "data": "public", "time": "medium"},
                "evidence_ref": ["IH1", "gap-001"],
            },
            {
                "idea_id": "IDEA-002",
                "summary": "Cross-modal transfer via domain-adversarial training.",
                "feasibility": {"score": 0.3, "compute": "high", "data": "restricted", "time": "long"},
                "evidence_ref": ["IH2", "gap-002"],
            },
        ]

    def test_produced_payload_validates_against_schema(self) -> None:
        """build_idea_backlog output must validate against idea_backlog.schema.json."""
        ideas = self._make_raw_ideas()
        payload = build_idea_backlog(ideas)
        errors = validate_against(SCHEMA, payload)
        assert errors == [], f"idea_backlog payload failed schema validation: {errors}"

    def test_higher_ranked_idea_scores_higher(self) -> None:
        """Rank 1 idea must have a higher or equal feasibility score than rank 2."""
        ideas = [
            _make_idea("IDEA-LOW", compute="high", data="unavailable", time="long"),
            _make_idea("IDEA-HIGH", compute="low", data="public", time="short"),
        ]
        payload = build_idea_backlog(ideas)
        ranked = payload["ranked_ideas"]
        rank1 = next(r for r in ranked if r["rank"] == 1)
        rank2 = next(r for r in ranked if r["rank"] == 2)
        assert rank1["feasibility"]["score"] >= rank2["feasibility"]["score"]

    def test_ranks_contiguous_in_output(self) -> None:
        ideas = [_make_idea(f"IDEA-{i:03d}") for i in range(5)]
        payload = build_idea_backlog(ideas)
        ranks = sorted(r["rank"] for r in payload["ranked_ideas"])
        assert ranks == [1, 2, 3, 4, 5]

    # --- schema-reject tests (anti-slop + no-self-bet) ---

    def test_idea_with_empty_evidence_ref_is_schema_rejected(self) -> None:
        """Anti-slop: an idea with empty evidence_ref must be rejected by the schema."""
        ideas = self._make_raw_ideas()
        payload = build_idea_backlog(ideas)
        # Mutate the output to inject an empty evidence_ref
        payload["ranked_ideas"][0]["evidence_ref"] = []
        errors = validate_against(SCHEMA, payload)
        assert errors != [], (
            "idea_backlog schema must reject an idea with empty evidence_ref (anti-slop)"
        )

    def test_payload_with_selected_field_is_schema_rejected(self) -> None:
        """NO-SELF-BET: idea_backlog with a 'selected' field must be schema-rejected.

        This is the definitive structural no-self-bet test: the model produces ranked_ideas,
        and the schema's additionalProperties:false ensures no self-bet can be injected.
        """
        ideas = self._make_raw_ideas()
        payload = build_idea_backlog(ideas)
        payload["selected"] = True  # simulate a model trying to self-bet
        errors = validate_against(SCHEMA, payload)
        assert errors != [], (
            "idea_backlog schema must reject 'selected' field — structural no-self-bet guarantee"
        )

    def test_payload_with_chosen_field_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'chosen' field must be rejected."""
        ideas = self._make_raw_ideas()
        payload = build_idea_backlog(ideas)
        payload["chosen"] = "IDEA-001"
        errors = validate_against(SCHEMA, payload)
        assert errors != []

    def test_payload_with_winner_field_is_schema_rejected(self) -> None:
        """NO-SELF-BET: 'winner' field must be rejected."""
        ideas = self._make_raw_ideas()
        payload = build_idea_backlog(ideas)
        payload["winner"] = "IDEA-001"
        errors = validate_against(SCHEMA, payload)
        assert errors != []
