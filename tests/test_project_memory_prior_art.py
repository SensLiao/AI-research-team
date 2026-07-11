"""tools/project_memory — the known-prior-art ledger (novelty-collision-upgrade 2026-06-18).

Mirrors the gap-inventory cross-run memory (test_project_memory.py) for the prior-art channel: the
DEAD ideas a run cuts are appended (idempotent per run_id+fingerprint) so a FUTURE run pre-matches and
never re-outputs them. Same vault-path guard (machine scratch, NEVER the crown jewels), same lexical
matcher, same corrupt-line tolerance.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.project_memory import (
    PRIOR_ART_MATCH_THRESHOLD,
    append_prior_art,
    load_prior_art,
    prior_art_matches,
)

DEAD = [
    {"idea_id": "IDEA-1", "fingerprint": "tversky+boundary | canal segmentation | dental cbct",
     "summary": "Tversky + boundary loss on a frozen FM for canal segmentation",
     "colliding_refs": ["arXiv:2407.01517"], "experimentally_validated": True},
    {"idea_id": "IDEA-2", "fingerprint": "gated tta | promptable 3d seg | medical imaging",
     "summary": "gated test-time adaptation tail-rescue for promptable 3D segmentation",
     "colliding_refs": ["doi:10.1/abc"], "experimentally_validated": False},
]


def _machine(tmp_path):
    (tmp_path / "runs" / "proj-a" / "r1").mkdir(parents=True)
    ws = tmp_path / "projects" / "proj-a"
    (ws / "notes").mkdir(parents=True)
    return tmp_path


# --------------------------------------------------------------------------- append / load / idempotency

def test_append_is_idempotent_per_run_and_fingerprint(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    assert append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD) == 2
    assert append_prior_art(ws, "r1", "2026-06-18T00:00:01Z", DEAD) == 0   # re-run: no dupes
    assert append_prior_art(ws, "r2", "2026-06-18T00:00:02Z", DEAD[:1]) == 1  # new run -> new row
    rows = load_prior_art(ws)
    assert len(rows) == 3
    assert all(r["verdict"] == "DEAD" for r in rows)                       # every row is a DEAD record


def test_appended_row_carries_the_full_dead_shape(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD[:1])
    row = load_prior_art(ws)[0]
    assert row["run_id"] == "r1" and row["ts"] == "2026-06-18T00:00:00Z"
    assert row["idea_id"] == "IDEA-1"
    assert row["fingerprint"] == "tversky+boundary | canal segmentation | dental cbct"
    assert row["colliding_refs"] == ["arXiv:2407.01517"]
    assert row["experimentally_validated"] is True


def test_append_falls_back_to_summary_when_no_fingerprint_and_skips_empty(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    rows_in = [
        {"idea_id": "IDEA-9", "summary": "only a summary, no fingerprint"},  # fingerprint <- summary
        {"idea_id": "IDEA-10"},                                             # neither -> skipped
    ]
    assert append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", rows_in) == 1
    rows = load_prior_art(ws)
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "only a summary, no fingerprint"


# --------------------------------------------------------------------------- corrupt-line tolerance

def test_load_skips_corrupt_lines(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD)
    p = ws / "notes" / "known-prior-art.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    assert len(load_prior_art(ws)) == 2          # a corrupt line never breaks recall of the rest


def test_load_empty_when_no_ledger(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    assert load_prior_art(ws) == []


# --------------------------------------------------------------------------- vault-path guard

def test_ledger_refuses_to_live_in_the_vault(tmp_path):
    bad = tmp_path / "PhD-Research-OS" / "projects" / "p"
    (bad / "notes").mkdir(parents=True)
    with pytest.raises(ValueError):
        append_prior_art(bad, "r1", "2026-06-18T00:00:00Z", DEAD)


# --------------------------------------------------------------------------- prior_art_matches (lexical)

def test_prior_art_matches_a_new_idea_against_a_dead_row(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD)
    inv = load_prior_art(ws)
    # a near-restatement of the DEAD IDEA-1 summary, under a fresh idea_id, must match.
    new_ideas = [{"idea_id": "IDEA-NEW",
                  "summary": "Tversky + boundary loss on a frozen FM for canal segmentation tasks"}]
    hits = prior_art_matches(new_ideas, inv)
    assert "IDEA-NEW" in hits
    assert hits["IDEA-NEW"]["idea_id"] == "IDEA-1"          # matched the right ledger row
    assert hits["IDEA-NEW"]["verdict"] == "DEAD"


def test_prior_art_matches_returns_nothing_for_an_unrelated_idea(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD)
    inv = load_prior_art(ws)
    far = [{"idea_id": "IDEA-FAR", "summary": "an unrelated retrieval benchmark for pricing engines"}]
    assert prior_art_matches(far, inv) == {}


def test_prior_art_matches_on_fingerprint_probe(tmp_path):
    """A new idea carrying its own fingerprint matches a ledger row by fingerprint too (not only summary)."""
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_prior_art(ws, "r1", "2026-06-18T00:00:00Z", DEAD)
    inv = load_prior_art(ws)
    new_ideas = [{"idea_id": "IDEA-FP", "summary": "unrelated wording on the surface",
                  "fingerprint": "tversky+boundary | canal segmentation | dental cbct"}]
    hits = prior_art_matches(new_ideas, inv)
    assert hits.get("IDEA-FP", {}).get("idea_id") == "IDEA-1"


def test_prior_art_matches_empty_inventory_is_empty(tmp_path):
    ideas = [{"idea_id": "IDEA-1", "summary": "anything at all"}]
    assert prior_art_matches(ideas, []) == {}


def test_prior_art_match_threshold_is_the_documented_default():
    assert PRIOR_ART_MATCH_THRESHOLD == 0.6
    # an idea well below threshold (low lexical overlap) must not match a recorded row.
    inv = [{"fingerprint": "alpha beta gamma delta", "summary": "alpha beta gamma delta",
            "idea_id": "IDEA-1", "verdict": "DEAD"}]
    weak = [{"idea_id": "IDEA-X", "summary": "completely different epsilon zeta words here"}]
    assert prior_art_matches(weak, inv) == {}
