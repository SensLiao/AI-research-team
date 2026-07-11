"""Tests for the COMBINATION layer (tools/research_plan.py + plan_catalog.yaml + the operate
`plan-propose` / `begin --upstream-run` wiring) — director lock 2026-06-19.

The contract under test: a request -> an intent -> TIERED mode-combinations (core <= mainline <= full
by cost), the chain is validated (unknown rejected, spec-only flagged, backwards-phase rejected), the
human gates a chain passes through are surfaced, and one link's output threads into the next.
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools import research_plan as rp


# --------------------------------------------------------------------------- catalog integrity

def test_catalog_loads_and_has_intents():
    cat = rp.load_catalog()
    assert cat.get("version") == 1
    assert cat.get("intents"), "catalog must define intents"


def test_every_default_tier_uses_only_wired_one_button_modes():
    """The honesty guarantee: a DEFAULT tier never silently contains a spec-only mode."""
    wired = rp.wired_modes()
    for intent in rp.all_intents():
        for tier in rp.propose(intent)["tiers"]:
            for m in tier["modes"]:
                assert m in wired, f"{intent}/{tier['id']} uses non-wired mode {m!r}"
            assert tier["validation"]["ok"], f"{intent}/{tier['id']} fails validation: {tier['validation']}"
            assert not tier["validation"]["spec_only"]


def test_each_intent_has_exactly_one_recommended_tier():
    for intent in rp.all_intents():
        tiers = rp.propose(intent)["tiers"]
        n_rec = sum(1 for t in tiers if t["recommended"])
        assert n_rec == 1, f"{intent} has {n_rec} recommended tiers (must be exactly 1)"


def test_tiers_are_cost_monotonic_within_each_intent():
    """core <= mainline <= full by agent-hops — the 'fastest/cheapest -> deepest' promise."""
    for intent in rp.all_intents():
        hops = [t["cost"]["agent_hops"] for t in rp.propose(intent)["tiers"]]
        assert hops == sorted(hops), f"{intent} tier costs not monotonic: {hops}"
        assert hops[0] <= hops[-1]


def test_tier_mode_counts_grow():
    """The director's mental model: core ~1 mode, then more — n_modes is non-decreasing."""
    for intent in rp.all_intents():
        counts = [t["cost"]["n_modes"] for t in rp.propose(intent)["tiers"]]
        assert counts == sorted(counts), f"{intent} mode counts not non-decreasing: {counts}"
        assert counts[0] >= 1


# --------------------------------------------------------------------------- cost / gates

def test_estimate_cost_sums_registry_hops():
    one = rp.estimate_cost(["new_direction"])
    assert one["agent_hops"] == 10 and one["n_modes"] == 1 and one["band"] == "medium"
    two = rp.estimate_cost(["new_direction", "deep_research"])
    assert two["agent_hops"] == 22 and two["n_modes"] == 2 and two["band"] == "heavy"


def test_gates_in_chain_surfaces_human_gates():
    assert rp.gates_in_chain(["new_direction"]) == [{"after": "new_direction", "gate": "/idea-bet"}]
    vg = rp.gates_in_chain(["venue_readiness"])
    assert {g["gate"] for g in vg} == {"/venue-pick", "/venue-decide"}
    # a chain with no gated mode pauses nowhere automatically
    assert rp.gates_in_chain(["gap_breadth", "deep_research"]) == []


def test_chain_routes_through_idea_bet_in_the_middle():
    """validate_idea mainline: deep_research -> new_direction (/idea-bet) -> full_rigor_minimal."""
    gates = rp.gates_in_chain(["deep_research", "new_direction", "full_rigor_minimal"])
    assert gates == [{"after": "new_direction", "gate": "/idea-bet"}]


# --------------------------------------------------------------------------- validation

def test_validate_chain_accepts_a_good_chain():
    v = rp.validate_chain(["deep_research", "new_direction", "full_rigor_minimal"])
    assert v["ok"] and not v["violations"] and not v["spec_only"]


def test_validate_chain_rejects_unknown_mode():
    v = rp.validate_chain(["new_direction", "totally_fake_mode"])
    assert not v["ok"]
    assert any("unknown mode" in x for x in v["violations"])


def test_validate_chain_flags_spec_only_mode_without_hard_failing():
    """A spec-only mode is honestly FLAGGED (hand-driven), not pretended one-button — but not a hard error."""
    v = rp.validate_chain(["ideate_ring"])
    assert "ideate_ring" in v["spec_only"]
    assert v["warnings"]
    assert v["ok"], "spec-only is a flag (warning), not a violation"


def test_validate_chain_rejects_backwards_phase_order():
    v = rp.validate_chain(["venue_readiness", "new_direction"])
    assert not v["ok"]
    assert any("phase order" in x for x in v["violations"])
    # design before evidence is also backwards
    v2 = rp.validate_chain(["full_rigor_minimal", "deep_research"])
    assert not v2["ok"]


def test_within_phase_order_is_free():
    """Scanning a gap before OR after deep-reading evidence is both fine (same phase rank)."""
    assert rp.validate_chain(["gap_breadth", "deep_research"])["ok"]
    assert rp.validate_chain(["deep_research", "gap_breadth"])["ok"]


# --------------------------------------------------------------------------- intent matching

def test_match_intents_picks_validate_idea():
    ranked = rp.match_intents("我有个想法验证一下")
    assert ranked[0][0] == "validate_idea"
    assert ranked[0][1] > 0


def test_match_intents_english():
    ranked = rp.match_intents("help me find a direction for next quarter")
    assert ranked[0][0] == "find_direction"


def test_best_intents_falls_back_to_all_when_no_match():
    ids, matched = rp.best_intents("zzz completely unrelated gibberish 12345")
    assert matched is False
    assert set(ids) == set(rp.all_intents())


# --------------------------------------------------------------------------- mode questions

def test_mode_questions_map_to_known_targets():
    known_targets = {"pre_search", "budget", "north_star", "note"}
    cat = rp.load_catalog()
    for mode, qs in (cat.get("mode_questions") or {}).items():
        assert mode in rp.all_modes(), f"mode_questions references unknown mode {mode!r}"
        for q in qs:
            assert q["maps_to"] in known_targets, f"{mode}.{q['key']} maps_to unknown {q['maps_to']!r}"
            assert q.get("options"), f"{mode}.{q['key']} has no options"


def test_every_wired_mode_in_a_default_tier_has_a_drill_down_or_is_intentionally_bare():
    """Every wired mode that appears in a tier should have a question row (so a drill-down round exists)."""
    cat = rp.load_catalog()
    mq = cat.get("mode_questions") or {}
    used = {m for intent in rp.all_intents() for t in rp.propose(intent)["tiers"] for m in t["modes"]}
    for m in used:
        assert m in mq, f"wired tier mode {m!r} has no mode_questions drill-down row"


# --------------------------------------------------------------------------- propose_for_request

def test_propose_for_request_matched():
    out = rp.propose_for_request("我有个想法验证一下")
    assert out["matched"] is True
    assert out["intents"][0]["intent"] == "validate_idea"
    assert out["mode_questions"]
    rec = rp.recommended_tier(out["intents"][0]["tiers"])
    assert rec["id"] == "mainline"


def test_propose_for_request_forced_intent():
    out = rp.propose_for_request("anything", intent="prep_submission")
    assert [i["intent"] for i in out["intents"]] == ["prep_submission"]


# --------------------------------------------------------------------------- chain threading

def _fake_prev_run(tmp_path, run_id="dr-1", mode="deep_research", summary="found 12 strong sources",
                   with_backlog=False):
    rd = tmp_path / "runs" / "proj" / run_id
    (rd / "evidence" / "REPORT").mkdir(parents=True)
    (rd / "task_frame.artifact.json").write_text(json.dumps(
        {"payload": {"mode": mode, "request_text": "validate my idea X", "task_id": run_id}}),
        encoding="utf-8")
    (rd / "evidence" / "REPORT" / "report-note.artifact.json").write_text(json.dumps(
        {"payload": {"summary": summary}}), encoding="utf-8")
    if with_backlog:
        (rd / "evidence" / "IDEATE").mkdir(parents=True)
        (rd / "evidence" / "IDEATE" / "idea-backlog.artifact.json").write_text(json.dumps(
            {"payload": {"ranked_ideas": [
                {"idea_id": "IDEA-1", "summary": "the top idea"},
                {"idea_id": "IDEA-2", "summary": "the runner up"}]}}), encoding="utf-8")
    return str(rd)


def test_upstream_grounding_extracts_summary_and_ideas(tmp_path):
    prev = _fake_prev_run(tmp_path, with_backlog=True)
    g = rp.upstream_grounding([prev])
    assert len(g["upstream_runs"]) == 1
    up = g["upstream_runs"][0]
    assert up["mode"] == "deep_research"
    assert up["summary"] == "found 12 strong sources"
    assert [i["idea_id"] for i in up["top_ideas"]] == ["IDEA-1", "IDEA-2"]
    assert any("report-note" in a for a in up["key_artifacts"])
    assert any("idea-backlog" in a for a in up["key_artifacts"])


def test_upstream_grounding_robust_to_empty_run(tmp_path):
    empty = tmp_path / "runs" / "proj" / "empty-1"
    empty.mkdir(parents=True)
    g = rp.upstream_grounding([str(empty)])
    assert g["upstream_runs"][0]["run_id"] == "empty-1"
    assert g["upstream_runs"][0]["summary"] == ""


def test_write_and_augment_single_worker(tmp_path):
    prev = _fake_prev_run(tmp_path)
    new_run = tmp_path / "runs" / "proj" / "nd-2"
    new_run.mkdir(parents=True)
    rp.write_upstream_grounding(str(new_run), [prev])
    worker = {"label": "x", "prompt": "ORIGINAL PROMPT BODY"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert "ORIGINAL PROMPT BODY" in out["prompt"]
    assert "PRIOR CHAIN CONTEXT" in out["prompt"]
    assert "found 12 strong sources" in out["prompt"]


def test_augment_panel_worker(tmp_path):
    prev = _fake_prev_run(tmp_path)
    new_run = tmp_path / "runs" / "proj" / "nd-3"
    new_run.mkdir(parents=True)
    rp.write_upstream_grounding(str(new_run), [prev])
    worker = {"workers": [{"prompt": "A"}, {"prompt": "B"}], "panel_note": "n"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert all("PRIOR CHAIN CONTEXT" in w["prompt"] for w in out["workers"])
    assert out["workers"][0]["prompt"].startswith("A")


def test_augment_panel_sends_full_upstream_only_to_root_workers(tmp_path):
    prev = _fake_prev_run(tmp_path)
    new_run = tmp_path / "runs" / "proj" / "nd-4"
    new_run.mkdir(parents=True)
    rp.write_upstream_grounding(str(new_run), [prev])
    panel = {"workers": [
        {"label": "root", "prompt": "ROOT"},
        {"label": "child", "prompt": "CHILD", "depends_on": ["root"]},
    ]}
    out = rp.augment_worker_with_upstream(panel, str(new_run))
    assert "found 12 strong sources" in out["workers"][0]["prompt"]
    assert "pointer only" in out["workers"][1]["prompt"]
    assert "found 12 strong sources" not in out["workers"][1]["prompt"]


def test_augment_is_noop_without_grounding(tmp_path):
    new_run = tmp_path / "runs" / "proj" / "solo-1"
    new_run.mkdir(parents=True)
    worker = {"prompt": "UNCHANGED"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert out["prompt"] == "UNCHANGED"


def test_augment_handles_none_worker(tmp_path):
    new_run = tmp_path / "runs" / "proj" / "solo-2"
    new_run.mkdir(parents=True)
    assert rp.augment_worker_with_upstream(None, str(new_run)) is None


# --------------------------------------------------------------------------- CLI plan-propose

def test_cli_plan_propose_emits_valid_json(capsys):
    from research_agent_teams.operate.cli import main
    main(["plan-propose", "--request", "帮我找个研究方向"])
    out = json.loads(capsys.readouterr().out)
    assert out["matched"] is True
    assert out["intents"][0]["intent"] == "find_direction"
    # the recommended tier is a real, validated chain
    tiers = out["intents"][0]["tiers"]
    rec = [t for t in tiers if t["recommended"]][0]
    assert rec["validation"]["ok"]
    assert rec["cost"]["agent_hops"] > 0


def test_cli_plan_propose_forced_intent(capsys):
    from research_agent_teams.operate.cli import main
    main(["plan-propose", "--request", "x", "--intent", "scan_gaps"])
    out = json.loads(capsys.readouterr().out)
    assert [i["intent"] for i in out["intents"]] == ["scan_gaps"]
