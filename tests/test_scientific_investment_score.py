from research_agent_teams.tools.scientific_investment_score import (
    rank_scientific_investments,
    validate_assessments,
)


def _assessment(idea_id, score):
    return {
        "idea_id": idea_id,
        "dimension_scores": {
            "importance": score,
            "mechanism_coherence": score,
            "novelty_exposure": score,
            "falsifiability": score,
            "information_gain": score,
            "downstream_leverage": score,
        },
        "strongest_rejection_case": "A skeptical reviewer can reject the mechanism claim.",
    }


def test_scientific_value_can_outrank_easy_but_shallow_idea():
    ideas = [
        {
            "idea_id": "DEEP",
            "rank": 2,
            "summary": "High-information mechanism test",
            "feasibility": {"score": 0.35},
            "evidence_ref": ["GAP-1"],
        },
        {
            "idea_id": "EASY",
            "rank": 1,
            "summary": "Easy descriptive audit",
            "feasibility": {"score": 1.0},
            "evidence_ref": ["GAP-2"],
        },
    ]
    ranked = rank_scientific_investments(
        ideas,
        assessments=[_assessment("DEEP", 5), _assessment("EASY", 2)],
        tournament={
            "ratings": [
                {"idea_id": "DEEP", "elo": 1510},
                {"idea_id": "EASY", "elo": 1490},
            ]
        },
        grounding={"ideas": [
            {"idea_id": "DEEP", "soundness": 0.8},
            {"idea_id": "EASY", "soundness": 0.8},
        ]},
        sketches=[
            {"idea_ref": "DEEP", "experiment": "test", "baselines": ["b"],
             "controls": ["c"], "metrics": ["m"], "success_thresholds": ["go"],
             "failure_thresholds": ["stop"], "kill_criteria": ["kill"],
             "execution_order": ["first"], "stages": [{"stage_id": "S1"}]},
            {"idea_ref": "EASY", "experiment": "test", "baselines": ["b"],
             "controls": ["c"], "metrics": ["m"], "success_thresholds": ["go"],
             "failure_thresholds": ["stop"], "kill_criteria": ["kill"],
             "execution_order": ["first"], "stages": [{"stage_id": "S1"}]},
        ],
    )
    assert [row["idea_id"] for row in ranked] == ["DEEP", "EASY"]
    assert ranked[0]["scientific_investment"]["confidence"] == "provisional"


def test_assessment_contract_rejects_missing_dimension_and_rejection_case():
    row = _assessment("IDEA-1", 4)
    row["dimension_scores"].pop("information_gain")
    row["strongest_rejection_case"] = ""
    errors = validate_assessments([row], ["IDEA-1"])
    assert any("information_gain" in error for error in errors)
    assert any("strongest_rejection_case" in error for error in errors)
