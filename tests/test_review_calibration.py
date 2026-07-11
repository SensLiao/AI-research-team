"""review_calibration — SPECS-lite seeding, deterministic catch-scoring, schema conformance (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.review_calibration import score_catch, seed_errors
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"

PAPER = """# A Method for Canal Segmentation

We train on 80% of the data and evaluate on the remaining 20%.
Our method reaches 0.91 Dice on the held-out split.
All seeds and configs are released.
"""

SPECS = [
    {
        "error_id": "E1", "criterion": "soundness",
        "description": "test-set leakage: evaluation split used for early stopping",
        "injection": {"mode": "replace",
                      "anchor": "evaluate on the remaining 20%.",
                      "replacement": "evaluate on the remaining 20%, which we also use for early stopping."},
        "detect_patterns": ["early stopping", "leakage", "test set used during training"],
    },
    {
        "error_id": "E2", "criterion": "reproducibility",
        "description": "seed policy removed",
        "injection": {"mode": "replace",
                      "anchor": "All seeds and configs are released.",
                      "replacement": "Configs are released."},
        "detect_patterns": ["seed", "random seed"],
    },
    {
        "error_id": "E3", "criterion": "significance",
        "description": "inflated real-world claim appended",
        "injection": {"mode": "append",
                      "text": "Our system is ready for immediate clinical deployment worldwide."},
        "detect_patterns": ["clinical deployment", "overclaim", "ready for deployment"],
    },
]


def test_seed_errors_injects_and_returns_key():
    seeded, planted = seed_errors(PAPER, SPECS)
    assert "early stopping" in seeded and "All seeds" not in seeded
    assert seeded.rstrip().endswith("worldwide.")
    assert [p["error_id"] for p in planted] == ["E1", "E2", "E3"]
    assert all(set(p) == {"error_id", "criterion", "description"} for p in planted)


def test_seed_errors_fail_loud():
    with pytest.raises(ValueError):                            # anchor not present
        seed_errors("different text", SPECS[:1])
    with pytest.raises(ValueError):                            # anchor ambiguous
        seed_errors("dup anchor. dup anchor.", [dict(SPECS[0],
                    injection={"mode": "replace", "anchor": "dup anchor.", "replacement": "x"})])
    with pytest.raises(ValueError):                            # missing patterns
        seed_errors(PAPER, [dict(SPECS[0], detect_patterns=[])])
    with pytest.raises(ValueError):                            # bad criterion
        seed_errors(PAPER, [dict(SPECS[0], criterion="elegance")])
    with pytest.raises(ValueError):                            # duplicate error_id
        seed_errors(PAPER, [SPECS[0], dict(SPECS[1], error_id="E1")])


def test_score_catch_recall_math_and_schema():
    reviews = [
        {"by": "adversarial-reviewer", "review_ref": "r1.artifact.json",
         "text": "Serious flaw: the held-out split is used for EARLY STOPPING — that is leakage."},
        {"by": "venue-reviewer-persona:methodology", "review_ref": "r2.artifact.json",
         "text": "Well written overall; I could not find the random seed policy anywhere."},
    ]
    payload = score_catch(SPECS, reviews, fixture_ref="tests/fixtures/seeded-paper.md",
                          evidence_ref=["r1.artifact.json", "r2.artifact.json"],
                          leniency_anchor=0.7)
    assert payload["recall_overall"] == pytest.approx(2 / 3, abs=1e-4)
    assert payload["recall_by_criterion"]["soundness"] == 1.0
    assert payload["recall_by_criterion"]["reproducibility"] == 1.0
    assert payload["recall_by_criterion"]["significance"] == 0.0
    assert payload["missed"] == ["E3"]
    assert {c["error_id"] for c in payload["caught"]} == {"E1", "E2"}
    art = envelope("calibration_report", "review-calibration-harness", payload, TS)
    assert validate_artifact(art) == []


def test_explicit_adjudicated_catches_merge_in():
    reviews = [{"by": "domain-reviewer", "review_ref": "r3.artifact.json",
                "text": "The deployment claim in the last line is wildly beyond the evidence."}]
    # pattern match misses E3's phrasing ('wildly beyond the evidence') -> adjudicator maps it
    base = score_catch(SPECS, reviews, "fx.md", ["r3.artifact.json"])
    assert "E3" in base["missed"]
    adj = score_catch(SPECS, reviews, "fx.md", ["r3.artifact.json"],
                      explicit_catches={"E3": [{"by": "domain-reviewer", "review_ref": "r3.artifact.json"}]})
    assert "E3" not in adj["missed"]
    assert adj["recall_by_criterion"]["significance"] == 1.0


def test_score_catch_requires_fixture_and_evidence():
    with pytest.raises(ValueError):
        score_catch(SPECS, [], "  ", ["e"])
    with pytest.raises(ValueError):
        score_catch(SPECS, [], "fx.md", [])
