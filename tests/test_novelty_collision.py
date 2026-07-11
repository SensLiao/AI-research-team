"""tools/novelty_collision — the deterministic prior-art COLLISION verdict (novelty-collision-upgrade).

The constitutional rule the machine encodes: a novelty SCORE never cuts; only an EVIDENCED collision
can — a SPECIFIC paper that PASSED citation_existence (exists ✓) AND did the SAME method×problem AND
(by default) actually RAN it. These tests pin every branch of ``build_collision_verdict``, with the
anti-false-cut guarantee (a collision on an UNVERIFIED / nonexistent paper degrades to UNVERIFIED,
never DEAD — the expensive error is killing a good idea) as the load-bearing case.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.novelty_collision import (
    SOURCE_LEDGER,
    SOURCE_WORKER,
    VERDICT_CLEAR,
    VERDICT_DEAD,
    VERDICT_UNVERIFIED,
    VERDICT_WHITE_SPACE,
    WORKER_ADJACENT,
    WORKER_CLEAR,
    WORKER_COLLISION,
    build_collision_verdict,
)

# A single menu of three ideas reused across the branch tests (every idea must appear in output).
IDEAS = [
    {"idea_id": "IDEA-1", "summary": "Tversky + boundary loss on a frozen FM for canal seg"},
    {"idea_id": "IDEA-2", "summary": "gated TTA tail-rescue for promptable 3D segmentation"},
    {"idea_id": "IDEA-3", "summary": "an orthogonal canal adapter for low-dose CBCT"},
]


def _finding(idea_id, verdict, papers=None, **extra):
    """A collision_findings[] entry by idea_id (mirrors the worker bundle shape)."""
    f = {"idea_id": idea_id, "method_combination": "m", "application": "a", "domain": "d",
         "queries": ["q"], "verdict": verdict, "colliding_papers": list(papers or []),
         "confidence": "high"}
    f.update(extra)
    return f


def _paper(ref, *, same=True, ran=True, title="A Paper"):
    return {"ref": ref, "title": title, "does_same_method_on_same_problem": same,
            "experimentally_validated": ran, "justification": "why"}


def _by_id(verdict):
    return {e["idea_id"]: e for e in verdict["ideas"]}


# --------------------------------------------------------------------------- 1. DEAD via worker

def test_dead_via_worker_when_verified_paper_does_same_and_ran():
    findings = [_finding("IDEA-1", WORKER_COLLISION, [_paper("arXiv:2407.01517")])]
    existence = {"arXiv:2407.01517": "verified"}
    v = build_collision_verdict(IDEAS, findings, existence, {})
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_DEAD
    assert e["cut"] is True
    assert e["source"] == SOURCE_WORKER
    assert "IDEA-1" in v["cut_ids"]
    assert "IDEA-1" not in v["survivors"]
    # recorded shape: the colliding paper carries its existence state + the experiments flag
    cp = e["colliding_papers"][0]
    assert cp == {"ref": "arXiv:2407.01517", "existence": "verified",
                  "experimentally_validated": True}
    # The other two ideas survive, but another idea's finding cannot silently clear them.
    assert v["survivors"] == ["IDEA-2", "IDEA-3"]
    assert _by_id(v)["IDEA-2"]["verdict"] == VERDICT_UNVERIFIED
    assert "per-idea coverage is missing" in _by_id(v)["IDEA-2"]["reason"]


def test_dead_via_worker_accepts_the_design_alias_EXISTS():
    """The core is robust to either existence convention: 'verified' (real) or 'EXISTS' (design §3.1)."""
    findings = [_finding("IDEA-1", WORKER_COLLISION, [_paper("doi:10.1/x")])]
    v = build_collision_verdict(IDEAS, findings, {"doi:10.1/x": "EXISTS"}, {})
    assert _by_id(v)["IDEA-1"]["verdict"] == VERDICT_DEAD


# --------------------------------------------------------------------------- 2. THE anti-false-cut guarantee

def test_collision_but_ref_not_verified_is_unverified_never_cut():
    """THE most important test: a worker 'collision' whose paper is not existence-verified
    (not_found / missing) can NEVER cut — absence of proof is never proof of prior art."""
    findings = [
        _finding("IDEA-1", WORKER_COLLISION, [_paper("doi:10.1/ghost")]),   # explicitly not_found
        _finding("IDEA-2", WORKER_COLLISION, [_paper("arXiv:9999.99999")]),  # missing from existence map
    ]
    existence = {"doi:10.1/ghost": "not_found"}  # IDEA-2's ref absent entirely
    v = build_collision_verdict(IDEAS, findings, existence, {})
    for iid in ("IDEA-1", "IDEA-2"):
        e = _by_id(v)[iid]
        assert e["verdict"] == VERDICT_UNVERIFIED, iid
        assert e["cut"] is False, iid
    assert v["cut_ids"] == []
    assert set(v["survivors"]) == {"IDEA-1", "IDEA-2", "IDEA-3"}


# --------------------------------------------------------------------------- 3. cut_requires_experiments knob

def test_verified_but_not_experimentally_validated_blocks_dead_when_experiments_required():
    """A verified paper that did the same method×problem but only PROPOSED it (no run) is not DEAD
    when cut_requires_experiments=True — proposed-only is publishable white space, never a cut."""
    findings = [_finding("IDEA-1", WORKER_COLLISION, [_paper("arXiv:1", ran=False)])]
    existence = {"arXiv:1": "verified"}
    v = build_collision_verdict(IDEAS, findings, existence, {}, cut_requires_experiments=True)
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_UNVERIFIED   # the code degrades (never up) — not DEAD
    assert e["cut"] is False


def test_verified_not_run_becomes_dead_when_experiments_not_required():
    """With cut_requires_experiments=False the same verified same-method paper IS a DEAD cut."""
    findings = [_finding("IDEA-1", WORKER_COLLISION, [_paper("arXiv:1", ran=False)])]
    existence = {"arXiv:1": "verified"}
    v = build_collision_verdict(IDEAS, findings, existence, {}, cut_requires_experiments=False)
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_DEAD
    assert e["cut"] is True


# --------------------------------------------------------------------------- 4. adjacent -> WHITE_SPACE

def test_adjacent_is_white_space_and_never_cut():
    findings = [_finding("IDEA-1", WORKER_ADJACENT, [_paper("arXiv:adj", same=False)])]
    v = build_collision_verdict(IDEAS, findings, {"arXiv:adj": "verified"}, {})
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_WHITE_SPACE
    assert e["cut"] is False
    assert "IDEA-1" in v["survivors"]


# --------------------------------------------------------------------------- 5. clear x retrieval_grounded

def test_clear_with_retrieval_grounded_is_clear():
    findings = [_finding("IDEA-1", WORKER_CLEAR, [])]
    v = build_collision_verdict(IDEAS, findings, {}, {}, retrieval_grounded=True)
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_CLEAR
    assert e["cut"] is False


def test_grounded_retrieval_missing_per_idea_finding_is_unverified_never_clear():
    findings = [_finding("IDEA-1", WORKER_CLEAR, [])]
    verdict = build_collision_verdict(IDEAS, findings, {}, {}, retrieval_grounded=True)
    assert _by_id(verdict)["IDEA-1"]["verdict"] == VERDICT_CLEAR
    for idea_id in ("IDEA-2", "IDEA-3"):
        row = _by_id(verdict)[idea_id]
        assert row["verdict"] == VERDICT_UNVERIFIED
        assert row["cut"] is False


def test_clear_without_retrieval_grounded_is_unverified():
    """A worker 'clear' is only trustworthy if retrieval actually ran — else it is UNVERIFIED."""
    findings = [_finding("IDEA-1", WORKER_CLEAR, [])]
    v = build_collision_verdict(IDEAS, findings, {}, {}, retrieval_grounded=False)
    # retrieval_grounded=False short-circuits EVERY non-ledger idea to UNVERIFIED.
    for e in v["ideas"]:
        assert e["verdict"] == VERDICT_UNVERIFIED
        assert e["cut"] is False
    assert v["retrieval_grounded"] is False


# --------------------------------------------------------------------------- 6. retrieval ungrounded, no findings

def test_retrieval_not_grounded_makes_everything_unverified_and_cuts_nothing():
    v = build_collision_verdict(IDEAS, [], {}, {}, retrieval_grounded=False)
    assert [e["verdict"] for e in v["ideas"]] == [VERDICT_UNVERIFIED] * 3
    assert v["cut_ids"] == []
    assert v["survivors"] == ["IDEA-1", "IDEA-2", "IDEA-3"]
    assert v["retrieval_grounded"] is False
    # default evidence_ref is the canonical bundle path when no finding stamped one.
    assert v["evidence_ref"] == ["inbox/COLLISION.bundle.json"]


# --------------------------------------------------------------------------- 7. ledger pre-match -> DEAD

def test_prior_art_ledger_hit_is_dead_from_ledger_even_with_no_worker_finding():
    """A known-dead idea (matched the cross-run ledger) stays DEAD with source='ledger' — the machine
    must not re-output it — even though there is no fresh worker finding this run."""
    row = {"run_id": "r-old", "idea_id": "IDEA-2", "summary": "x",
           "colliding_refs": ["arXiv:old"], "experimentally_validated": True, "verdict": "DEAD"}
    v = build_collision_verdict(IDEAS, [], {"arXiv:old": "verified"}, {"IDEA-2": row})
    e = _by_id(v)["IDEA-2"]
    assert e["verdict"] == VERDICT_DEAD
    assert e["source"] == SOURCE_LEDGER
    assert e["cut"] is True
    assert e["colliding_papers"][0]["ref"] == "arXiv:old"
    assert "IDEA-2" in v["cut_ids"]


def test_ledger_hit_wins_over_a_worker_clear_finding():
    """The ledger is authoritative: an idea the worker reports 'clear' is still DEAD if the ledger
    already cut it (the machine never re-outputs a known-dead idea)."""
    row = {"run_id": "r-old", "idea_id": "IDEA-1", "summary": "x",
           "colliding_refs": [], "experimentally_validated": False, "verdict": "DEAD"}
    findings = [_finding("IDEA-1", WORKER_CLEAR, [])]
    v = build_collision_verdict(IDEAS, findings, {}, {"IDEA-1": row})
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_DEAD and e["source"] == SOURCE_LEDGER and e["cut"] is True


# --------------------------------------------------------------------------- 8. hard_block=False -> flag-only

def test_hard_block_false_labels_dead_but_does_not_cut():
    findings = [_finding("IDEA-1", WORKER_COLLISION, [_paper("arXiv:1")])]
    v = build_collision_verdict(IDEAS, findings, {"arXiv:1": "verified"}, {}, hard_block=False)
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_DEAD     # still labelled DEAD
    assert e["cut"] is False                # ...but flag-only, never removed
    assert v["cut_ids"] == []
    assert "IDEA-1" in v["survivors"]
    assert v["policy"] == {"hard_block": False, "cut_requires_experiments": True}


def test_hard_block_false_keeps_a_ledger_dead_idea_too():
    row = {"run_id": "r-old", "idea_id": "IDEA-3", "summary": "x",
           "colliding_refs": ["arXiv:z"], "experimentally_validated": True, "verdict": "DEAD"}
    v = build_collision_verdict(IDEAS, [], {}, {"IDEA-3": row}, hard_block=False)
    e = _by_id(v)["IDEA-3"]
    assert e["verdict"] == VERDICT_DEAD and e["cut"] is False
    assert v["cut_ids"] == []


# --------------------------------------------------------------------------- 9. every idea appears exactly once

def test_every_input_idea_appears_exactly_once_in_input_order():
    findings = [
        _finding("IDEA-3", WORKER_COLLISION, [_paper("arXiv:1")]),   # finding order != idea order
        _finding("IDEA-1", WORKER_ADJACENT, [_paper("arXiv:2", same=False)]),
    ]
    v = build_collision_verdict(IDEAS, findings, {"arXiv:1": "verified", "arXiv:2": "verified"}, {})
    assert [e["idea_id"] for e in v["ideas"]] == ["IDEA-1", "IDEA-2", "IDEA-3"]  # INPUT order, stable
    ids = [e["idea_id"] for e in v["ideas"]]
    assert len(ids) == len(set(ids)) == len(IDEAS)                               # exactly once each
    # cut_ids / survivors partition the ideas with no overlap and no loss.
    assert set(v["cut_ids"]) | set(v["survivors"]) == set(ids)
    assert set(v["cut_ids"]) & set(v["survivors"]) == set()


# --------------------------------------------------------------------------- 10. input-validation raises

def test_empty_menu_raises():
    with pytest.raises(ValueError, match="at least one idea"):
        build_collision_verdict([], [], {}, {})


def test_missing_idea_id_raises():
    with pytest.raises(ValueError, match="idea_id"):
        build_collision_verdict([{"summary": "no id"}], [], {}, {})


def test_blank_idea_id_raises():
    with pytest.raises(ValueError, match="idea_id"):
        build_collision_verdict([{"idea_id": "   ", "summary": "x"}], [], {}, {})


def test_duplicate_idea_id_in_menu_raises():
    dup = [{"idea_id": "IDEA-1", "summary": "a"}, {"idea_id": "IDEA-1", "summary": "b"}]
    with pytest.raises(ValueError, match="duplicate idea_id"):
        build_collision_verdict(dup, [], {}, {})


def test_duplicate_idea_id_in_findings_raises():
    findings = [_finding("IDEA-1", WORKER_CLEAR, []), _finding("IDEA-1", WORKER_ADJACENT, [])]
    with pytest.raises(ValueError, match="duplicate idea_id in collision findings"):
        build_collision_verdict(IDEAS, findings, {}, {})


# --------------------------------------------------------------------------- 11. misc branch coverage

def test_collision_with_no_named_paper_is_unverified():
    """Worker says 'collision' but names no specific paper -> cannot cut without an existence-verified
    collider -> UNVERIFIED (mirrors the design: 'vaguely similar' never becomes DEAD)."""
    findings = [_finding("IDEA-1", WORKER_COLLISION, [])]
    v = build_collision_verdict(IDEAS, findings, {}, {})
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_UNVERIFIED and e["cut"] is False
    assert "named no specific paper" in e["reason"]


def test_unrecognized_worker_verdict_is_unverified_never_cut():
    findings = [_finding("IDEA-1", "totally-bogus", [])]
    v = build_collision_verdict(IDEAS, findings, {}, {})
    e = _by_id(v)["IDEA-1"]
    assert e["verdict"] == VERDICT_UNVERIFIED and e["cut"] is False


def test_evidence_ref_prefers_worker_stamped_bundle_ref():
    findings = [_finding("IDEA-1", WORKER_CLEAR, [], evidence_ref=["inbox/COLLISION.bundle.json"])]
    v = build_collision_verdict(IDEAS, findings, {}, {})
    assert v["evidence_ref"] == ["inbox/COLLISION.bundle.json"]


def test_policy_and_retrieval_grounded_echoed():
    v = build_collision_verdict(IDEAS, [_finding("IDEA-1", WORKER_CLEAR, [])], {}, {},
                                hard_block=True, cut_requires_experiments=False,
                                retrieval_grounded=True)
    assert v["policy"] == {"hard_block": True, "cut_requires_experiments": False}
    assert v["retrieval_grounded"] is True
