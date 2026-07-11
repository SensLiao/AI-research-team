"""elo_tournament — deterministic Elo over judged debates, Swiss pairing, schema conformance (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.elo_tournament import (
    build_elo_tournament,
    expected_score,
    run_elo,
    swiss_pairings,
)
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"


def match(rnd, a, b, w, ref="inbox/IDEATE.bundle.json#m1"):
    return {"round": rnd, "pair_a": a, "pair_b": b, "winner": w, "rationale_ref": ref}


def test_elo_moves_toward_the_winner_and_is_deterministic():
    ms = [match(1, "A", "B", "A"), match(1, "C", "D", "D"), match(2, "A", "D", "A")]
    r1 = run_elo(ms)
    r2 = run_elo(list(reversed(ms)))                       # input order must not matter
    assert r1 == r2
    by_id = {r["idea_id"]: r for r in r1}
    assert by_id["A"]["elo"] > 1000 and by_id["B"]["elo"] < 1000
    assert by_id["A"]["rank"] == 1 and by_id["A"]["wins"] == 2 and by_id["A"]["losses"] == 0
    ranks = sorted(r["rank"] for r in r1)
    assert ranks == [1, 2, 3, 4]                           # contiguous


def test_expected_score_symmetry():
    assert abs(expected_score(1000, 1000) - 0.5) < 1e-9
    assert expected_score(1200, 1000) + expected_score(1000, 1200) == pytest.approx(1.0)


def test_fail_loud_validation():
    with pytest.raises(ValueError):
        run_elo([match(1, "A", "B", "C")])                 # winner not in pair
    with pytest.raises(ValueError):
        run_elo([match(1, "A", "A", "A")])                 # self-match
    with pytest.raises(ValueError):
        run_elo([match(0, "A", "B", "A")])                 # bad round
    with pytest.raises(ValueError):
        run_elo([{"round": 1, "pair_a": "A", "pair_b": "B", "winner": "A", "rationale_ref": " "}])
    with pytest.raises(ValueError):
        run_elo([match(1, "A", "B", "A"), match(1, "B", "A", "B")])   # duplicate judgment


def test_unmatched_participants_keep_base_rating():
    r = run_elo([match(1, "A", "B", "A")], all_ids=["A", "B", "E"])
    by_id = {x["idea_id"]: x for x in r}
    assert by_id["E"]["elo"] == 1000.0 and by_id["E"]["wins"] == 0
    assert by_id["A"]["rank"] == 1 and by_id["B"]["rank"] == 3


def test_swiss_pairings_avoid_rematches_and_assign_bye():
    current = [{"idea_id": "A", "elo": 1100}, {"idea_id": "B", "elo": 1050},
               {"idea_id": "C", "elo": 1000}, {"idea_id": "D", "elo": 950},
               {"idea_id": "E", "elo": 900}]
    history = [match(1, "A", "B", "A")]
    out = swiss_pairings(current, history)
    assert ["A", "C"] in out["pairs"]                      # A skips B (already played) -> next closest
    assert ["B", "D"] in out["pairs"]
    assert out["bye"] == "E"                               # lowest-rated odd one out
    flat = {x for p in out["pairs"] for x in p} | {out["bye"]}
    assert flat == {"A", "B", "C", "D", "E"}               # nobody vanishes


def test_payload_passes_schema_and_no_chosen_field():
    ms = [match(1, "A", "B", "A"), match(1, "C", "D", "C"), match(2, "A", "C", "C")]
    payload = build_elo_tournament(ms, evidence_ref=["hypothesis-set.artifact.json"])
    assert payload["rounds"] == 2 and payload["format"] == "swiss"
    assert "chosen" not in payload and "selected" not in payload
    art = envelope("elo_tournament", "idea-tournament-ranker", payload, TS)
    assert validate_artifact(art) == []
    bad = dict(payload, matchups=[dict(payload["matchups"][0], winner="ZZZ")])
    assert validate_artifact(envelope("elo_tournament", "idea-tournament-ranker", bad, TS)) == []  # schema can't see cross-field
    with pytest.raises(ValueError):                        # ...but the tool fails loud on it
        build_elo_tournament([match(1, "A", "B", "ZZZ")], evidence_ref=["x"])
    with pytest.raises(ValueError):
        build_elo_tournament(ms, evidence_ref=[])
