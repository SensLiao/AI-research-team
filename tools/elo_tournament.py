"""Elo tournament over pairwise-debate judgments (absorption wave 1; Google co-scientist pattern).

The co-scientist's Nature-validated idea ranking is an Elo tournament over PAIRWISE SIMULATED
DEBATES — not a score-mean, not a score-sort. Division of labour in this machine:

  - the idea-tournament-ranker AGENT judges each matchup (a short simulated debate; it names a
    winner and writes a rationale) — that is reading/judgment work, an LLM's job;
  - THIS tool does everything deterministic: Swiss pairing bookkeeping (AI-Researcher pattern:
    closest-rated unplayed opponents), Elo updates, ranking — math is never an LLM call;
  - the output is EVIDENCE for the /idea-bet menu: per-matchup rationale refs make every rating
    auditable, and there is structurally no chosen/selected field — the director bets.

Design invariants (mirrors tournament_bracket.py):
  - Pure functions, deterministic: matches are processed in (round, pair_a, pair_b) order;
    same judgments -> same ratings; stable tiebreak by idea_id ASC everywhere.
  - Fail loud: winner must equal pair_a or pair_b; ids and rationale_ref non-empty; a duplicate
    (round, pair) is an error (one judgment per matchup per round).
  - rank assigned 1..N contiguously by Elo DESC then idea_id ASC.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

BASE_ELO = 1000.0
K_FACTOR = 32.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expectation for A vs B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _validate_match(m: dict) -> None:
    for f in ("pair_a", "pair_b", "winner", "rationale_ref"):
        v = m.get(f)
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"matchup field {f!r} must be a non-empty string: {m!r}")
    if not isinstance(m.get("round"), int) or m["round"] < 1:
        raise ValueError(f"matchup round must be an int >= 1: {m!r}")
    if m["pair_a"] == m["pair_b"]:
        raise ValueError(f"degenerate self-match: {m!r}")
    if m["winner"] not in (m["pair_a"], m["pair_b"]):
        raise ValueError(f"winner must equal pair_a or pair_b: {m!r}")


def run_elo(matches: List[dict], base: float = BASE_ELO, k: float = K_FACTOR,
            all_ids: Optional[List[str]] = None) -> List[dict]:
    """Compute Elo ratings from judged matchups; returns the schema-shaped ratings list.

    all_ids optionally registers unmatched participants (e.g. a Swiss bye) at the base rating —
    nobody vanishes from the ranking just because they sat a round out.
    """
    for m in matches:
        _validate_match(m)
    seen: Set[Tuple[int, str, str]] = set()
    for m in matches:
        key = (m["round"],) + tuple(sorted((m["pair_a"], m["pair_b"])))
        if key in seen:
            raise ValueError(f"duplicate judgment for pair {key[1:]} in round {key[0]}")
        seen.add(key)

    ratings: Dict[str, float] = {}
    wins: Dict[str, int] = {}
    losses: Dict[str, int] = {}
    for pid in (all_ids or []):
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError(f"all_ids entries must be non-empty strings: {all_ids!r}")
        ratings.setdefault(pid, base)

    ordered = sorted(matches, key=lambda m: (m["round"], m["pair_a"], m["pair_b"]))
    for m in ordered:
        a, b, w = m["pair_a"], m["pair_b"], m["winner"]
        ra, rb = ratings.setdefault(a, base), ratings.setdefault(b, base)
        ea = expected_score(ra, rb)
        sa = 1.0 if w == a else 0.0
        ratings[a] = ra + k * (sa - ea)
        ratings[b] = rb + k * ((1.0 - sa) - (1.0 - ea))
        wins[w] = wins.get(w, 0) + 1
        loser = b if w == a else a
        losses[loser] = losses.get(loser, 0) + 1

    ranked_ids = sorted(ratings, key=lambda i: (-ratings[i], i))
    return [{"idea_id": iid, "elo": round(ratings[iid], 2), "rank": pos,
             "wins": wins.get(iid, 0), "losses": losses.get(iid, 0)}
            for pos, iid in enumerate(ranked_ids, start=1)]


def swiss_pairings(current: List[dict], history: List[dict]) -> dict:
    """Next-round Swiss pairings: sort by Elo DESC (tie: idea_id ASC), greedily pair each idea
    with the closest-rated opponent it has NOT yet played; odd participant count -> the
    lowest-rated unpaired idea gets the bye. Deterministic. ``current`` entries need
    idea_id (+ optional elo, default base); ``history`` is prior matchups (pair_a/pair_b)."""
    ids = [c.get("idea_id") for c in current]
    if any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError(f"every participant needs a non-empty idea_id: {ids}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate participants: {sorted(x for x in ids if ids.count(x) > 1)}")
    played: Set[frozenset] = {frozenset((m["pair_a"], m["pair_b"])) for m in history}
    order = sorted(current, key=lambda c: (-(c.get("elo") if c.get("elo") is not None else BASE_ELO),
                                           c["idea_id"]))
    remaining = [c["idea_id"] for c in order]
    pairs: List[List[str]] = []
    while len(remaining) >= 2:
        a = remaining.pop(0)
        partner_idx = None
        for idx, b in enumerate(remaining):
            if frozenset((a, b)) not in played:
                partner_idx = idx
                break
        if partner_idx is None:               # everyone left already played a — allow the rematch
            # Greedy approximation (intentional): for the machine's small ideation brackets (<=8 ideas,
            # 2-3 rounds) this can occasionally force an avoidable rematch a global matching would dodge.
            # Acceptable at this scale; documented in the absorption-wave-1 build record. A rematch is
            # strictly better than dropping a participant from the round.
            partner_idx = 0
        pairs.append([a, remaining.pop(partner_idx)])
    return {"pairs": pairs, "bye": remaining[0] if remaining else None}


def build_elo_tournament(matches: List[dict], evidence_ref: List[str],
                         fmt: str = "swiss", all_ids: Optional[List[str]] = None,
                         base: float = BASE_ELO, k: float = K_FACTOR) -> dict:
    """Assemble the ``elo_tournament`` payload (schema-ready, fail-loud)."""
    if fmt not in ("swiss", "round_robin"):
        raise ValueError(f"format must be swiss|round_robin, got {fmt!r}")
    if not matches:
        raise ValueError("build_elo_tournament requires at least one judged matchup")
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list (anti-slop binding)")
    ratings = run_elo(matches, base=base, k=k, all_ids=all_ids)
    ordered = sorted(matches, key=lambda m: (m["round"], m["pair_a"], m["pair_b"]))
    return {"format": fmt,
            "rounds": max(m["round"] for m in matches),
            "matchups": [{"round": m["round"], "pair_a": m["pair_a"], "pair_b": m["pair_b"],
                          "winner": m["winner"], "rationale_ref": m["rationale_ref"]}
                         for m in ordered],
            "ratings": ratings,
            "evidence_ref": list(evidence_ref)}
