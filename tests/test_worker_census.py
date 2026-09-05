"""Seat accounting: no orphan seats, no undeclared dispatch, and a ceiling never read as a promise.

P4 was specified from a memo claim ("157 workers, 120 used, 37 spec-only") and an assumption (that
dormant workers need dynamic dispatch). Measuring turned one into a verified fact and refuted the
other. These tests keep both answers true as the tree changes.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools import outcome_recipes, research_plan, worker_census as census


@pytest.fixture(scope="module")
def data() -> dict:
    return census.census()


@pytest.fixture(scope="module")
def teams() -> dict:
    return census.mode_teams()


# --------------------------------------------------------------------------- the invariants

def test_the_census_invariants_hold():
    result = census.verify()
    assert result["ok"], result["violations"]


def test_the_roster_and_the_agent_files_agree_both_ways():
    assert set(census.roster()) == census.agent_files()


def test_no_seat_is_an_orphan(data):
    """A rostered agent nothing can dispatch is a capability that does not exist."""
    assert data["totals"]["unreachable"] == 0
    for row in data["agents"]:
        assert row["reachable_from"], row["agent"]


def test_control_plane_roles_are_never_declared_as_seats(data):
    """D7: one main thread; control is not a worker."""
    for row in data["agents"]:
        if row["group"] == census.CONTROL_GROUP:
            assert row["declared_by_operated"] == [], row["agent"]
            assert row["declared_by_spec_only"] == [], row["agent"]


def test_the_main_thread_is_the_only_recipe_name_without_a_subset():
    """Everything else a recipe dispatches must be bounded by some mode's agent_subset."""
    registry = research_plan.load_mode_registry()["modes"]
    declared = {a for spec in registry.values() for a in (spec.get("agent_subset") or [])}
    undeclared = {a for a in census.roster()
                  if census.dispatched_by_recipe(a) and a not in declared}
    assert undeclared == {census.MAIN_THREAD}


def test_every_declared_seat_is_a_real_agent():
    registry = research_plan.load_mode_registry()["modes"]
    rostered = set(census.roster())
    for mode, spec in registry.items():
        for agent in spec.get("agent_subset") or []:
            assert agent in rostered, (mode, agent)


# ------------------------------------------------------------------ the memo's claim, measured

def test_the_memo_split_is_verified_not_assumed(data):
    """"157 workers, 120 used by operated modes, 37 spec-only" — checked in code, and it holds."""
    totals = data["totals"]
    # Roster is the truth (2026-08-09: +5 multi-view IDEATE panel seats); the memo numbers are
    # re-derived from the live census, never pinned by hand.
    assert totals["rostered"] == len(data["agents"])
    assert totals["control"] == 7
    assert totals["workers"] == len(data["agents"]) - 7
    # Wave 2 (2026-08-04) moved 27 seats from hand-driven to one-button; the 2026-08-07 backlog
    # close (ideate_ring, aers_enhanced_research_pack) moved 8 more; the same-day registry HANDOFF
    # (B1 divergence-operator-runner + B5 direction-decision-advisor into new_direction/deep_ideation,
    # B4 research-trajectory-extractor into read_paper_deep) added 3 rostered seats; 2026-08-09
    # added the 5 multi-view IDEATE panel seats — all reachable.
    # These are REACHABILITY numbers only — how many seats a director could dispatch with one
    # command. How many have ever actually run is a different axis with a different source
    # (governance census over run bundles), pinned separately in
    # test_agent_connectivity::test_reachable_is_never_reported_as_exercised.
    assert totals["declared_by_operated"] == totals["workers"] - totals["spec_only"]
    assert totals["spec_only"] == 2
    assert totals["in_no_subset"] == 0
    assert totals["workers"] == totals["declared_by_operated"] + totals["spec_only"]


def test_there_are_no_dormant_workers_to_wake_up(data):
    """The refuted half of P4: nothing is dormant, so nothing needs dynamic dispatch."""
    assert [r["agent"] for r in data["agents"] if not r["reachable_from"]] == []


# ------------------------------------------------------------------- roster vs actual dispatch

def test_the_roster_ceiling_is_never_below_what_the_recipe_dispatches(teams):
    for team in teams["teams"]:
        assert team["recipe_floor"] <= team["ceiling"], team["mode"]
        assert team["recipe_floor"] + len(team["council_only"]) == team["ceiling"], team["mode"]


def test_the_council_only_gap_is_named_seat_by_seat(teams):
    """Seats that fire only on the mechanism-council path — say WHICH, not just how many.

    The count is derived, never pinned: it was 15 before wave 2 and is smaller after, because a seat
    stops being council-only the moment some wired mode declares it. Pinning the integer is what made
    this test stale twice; the invariant that matters is that every council-only seat is NAMED and is
    genuinely reachable-but-not-recipe-dispatched.
    """
    gap = {t["mode"]: t["council_only"] for t in teams["teams"] if t["council_only"]}
    assert "full_rigor_minimal" in gap
    assert "manuscript_review" not in gap  # all six declared manuscript reviewers are recipe-dispatched
    assert sum(len(v) for v in gap.values()) == teams["totals"]["council_only"] > 0
    for mode, seats in gap.items():
        assert seats == sorted(seats), mode
        for seat in seats:
            assert not census.dispatched_by_recipe(seat), seat
            assert census.reachable_from(seat), seat        # reachable, just not from the recipe


def test_only_the_modes_with_a_real_knob_are_called_scalable(teams):
    """A policy that claimed to shrink the other eleven would be claiming a control that is absent."""
    scalable = [t["mode"] for t in teams["teams"] if t["depth_knob"]]
    assert scalable == ["deep_research"]
    assert teams["totals"]["scalable_modes"] == 1
    for team in teams["teams"]:
        plan = census.team_plan(team["mode"])
        assert plan["scalable"] is bool(team["depth_knob"])
        assert ("团队是固定的" in plan["note"]) is not plan["scalable"]


def test_team_plan_rejects_a_mode_that_is_not_one_button():
    with pytest.raises(KeyError):
        census.team_plan("tree_explore")


# ------------------------------------------------------------------------- feeds the outcome card

def test_the_outcome_card_numbers_come_from_the_same_census(teams):
    by_mode = {t["mode"]: t for t in teams["teams"]}
    for view in outcome_recipes.resolve_all():
        for facts in view["mode_facts"]:
            team = by_mode[facts["mode"]]
            assert facts["seats"] == team["ceiling"]
            assert facts["recipe_seats"] == team["recipe_floor"]
            assert facts["council_only"] == len(team["council_only"])
        assert view["council_only"] == sum(f["council_only"] for f in view["mode_facts"])


def test_a_card_whose_route_has_a_council_gap_discloses_it():
    from research_agent_teams.reporting.outcomes import render_recipe
    card = render_recipe("runnable-experiment")
    assert "只在 council 路径上场" in card
    clean = render_recipe("paper-understood")
    assert "council" not in clean          # no gap on that route -> no confusing clause


# -------------------------------------------------------------------------------- the report

def test_the_report_states_the_ceiling_is_not_a_promise():
    report = census.render_report()
    assert "不是承诺会派这么多" in report
    assert "独立性机制" in report
    assert "没有闲置 agent" in report
