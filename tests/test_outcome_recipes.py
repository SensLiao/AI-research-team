"""The outcome menu's honesty floor — eight invariants, each with a negative control.

The menu is the surface a director actually reads before authorising a run, so a wrong number here
is worse than a missing feature. Every invariant below is checked twice: once against the shipped
`orchestrator/outcome_recipes.yaml`, and once against a deliberately-broken copy, to prove the check
really bites instead of passing vacuously.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest
import yaml

from research_agent_teams.reporting import briefing
from research_agent_teams.reporting.outcomes import render_menu, render_recipe
from research_agent_teams.tools import outcome_recipes as recipes
from research_agent_teams.tools import research_plan
from research_agent_teams.workbench.cli import main as workbench_main


def _broken(tmp_path, mutate: Callable[[dict[str, Any]], None]):
    """A copy of the real catalog with one thing wrong — the negative control."""
    data = recipes.load_recipes()
    mutate(data)
    path = tmp_path / "outcome_recipes.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _violations(tmp_path, mutate: Callable[[dict[str, Any]], None]) -> str:
    verdict = recipes.validate_all(path=_broken(tmp_path, mutate))
    assert not verdict["ok"], "the broken catalog was accepted — this guard does not bite"
    return "\n".join(verdict["violations"])


def _first(data: dict[str, Any]) -> dict[str, Any]:
    return next(iter(data["recipes"].values()))


# ------------------------------------------------------------------ the shipped catalog is sound

def test_the_shipped_menu_passes_every_invariant():
    verdict = recipes.validate_all()
    assert verdict["ok"], verdict["violations"]
    assert verdict["n_recipes"] == len(recipes.recipe_ids())


def test_every_operated_mode_is_reachable_from_some_outcome():
    """A capability the director cannot reach is a capability that does not exist to them."""
    cov = recipes.coverage()
    assert cov["missing"] == []
    assert cov["extra"] == []
    # the count is derived from the registry, never written down here
    assert set(cov["covered"]) == research_plan.wired_modes()


def test_every_intent_in_the_plan_catalog_has_an_outcome():
    """The menu must not orphan an arc the router can still land on."""
    covered = {
        str(intent)
        for recipe in recipes.load_recipes()["recipes"].values()
        for intent in (recipe or {}).get("covers_intents") or []
    }
    assert covered == set(research_plan.all_intents())


def test_no_outcome_offers_a_spec_only_mode_as_push_button():
    wired = research_plan.wired_modes()
    for view in recipes.resolve_all():
        for variant in view["variants"]:
            assert set(variant["modes"]) <= wired, view["id"]


def test_exactly_one_recommended_depth_per_outcome():
    for view in recipes.resolve_all():
        assert sum(1 for v in view["variants"] if v["recommended"]) == 1, view["id"]


def test_chains_never_run_a_later_phase_before_an_earlier_one():
    for view in recipes.resolve_all():
        for variant in view["variants"]:
            verdict = research_plan.validate_chain(variant["modes"])
            assert verdict["ok"], (view["id"], variant["id"], verdict["violations"])


# -------------------------------------------------------------- derived, never declared (inv. 3)

def test_seat_counts_equal_the_registry_agent_subsets():
    registry = research_plan.load_mode_registry()["modes"]
    for view in recipes.resolve_all():
        expected = sum(len(registry[m]["agent_subset"]) for m in view["modes"])
        assert view["seats"] == expected, view["id"]


def test_the_hop_budget_equals_the_registry_budget():
    registry = research_plan.load_mode_registry()["modes"]
    for view in recipes.resolve_all():
        expected = sum(int(registry[m]["budget"]["max_agent_hops"]) for m in view["modes"])
        assert view["cost"]["agent_hops"] == expected, view["id"]


def test_every_promised_deliverable_is_the_registry_handoff_file():
    """"你最后拿到什么" must resolve to a real declared file, not prose."""
    registry = research_plan.load_mode_registry()["modes"]
    for view in recipes.resolve_all():
        for item in view["deliverables"]:
            assert item["path"] == registry[item["mode"]]["handoff"]["primary_markdown"]
            assert item["path"].endswith(".md")


def test_a_recipe_may_not_restate_a_derived_fact(tmp_path):
    def declare_seats(data):
        _first(data)["seats"] = 99
    assert "DERIVED" in _violations(tmp_path, declare_seats)


def test_a_recipe_may_not_state_a_seat_count_in_prose(tmp_path):
    """The same defect wearing a sentence: right today, wrong after the next registry edit."""
    def prose_number(data):
        _first(data)["deliverable"] = "一份 20 席深读报告"
    assert "seat count in prose" in _violations(tmp_path, prose_number)


# ------------------------------------------------------------------------- human gates (inv. 5)

def test_gates_are_derived_from_the_plan_catalog_and_have_spec_files():
    specs = recipes.known_gate_names()
    for view in recipes.resolve_all():
        expected = research_plan.gates_in_chain(view["modes"])
        assert view["gates"] == expected, view["id"]
        for gate in (g["gate"] for g in view["gates"]):
            assert gate in specs, gate


def test_the_direction_route_stops_at_the_bet_gate_and_the_venue_route_at_both_venue_gates():
    direction = recipes.resolve("direction-to-bet")
    assert [g["gate"] for g in direction["gates"]] == ["/idea-bet"]
    venue = recipes.resolve("submit-or-not")
    assert [g["gate"] for g in venue["gates"]] == ["/venue-pick", "/venue-decide"]


# --------------------------------------------------------------------- honesty ceilings (inv. 6)

def test_every_experiment_route_states_the_no_gpu_receipt_limit():
    for view in recipes.resolve_all():
        if "full_rigor_minimal" in view["modes"]:
            assert any("GPU" in line for line in view["ceiling"]), view["id"]


def test_every_paper_route_states_that_only_the_gate_admits_it_to_the_vault():
    for view in recipes.resolve_all():
        modes = {m for variant in view["variants"] for m in variant["modes"]}
        if modes & {"ingest_paper", "read_paper_deep"}:
            assert any("/promote-to-vault" in line for line in view["ceiling"]), view["id"]


def test_dropping_the_gpu_ceiling_is_rejected(tmp_path):
    def strip_ceiling(data):
        for recipe in data["recipes"].values():
            modes = {m for v in recipe["variants"] for m in v["modes"]}
            if "full_rigor_minimal" in modes:
                recipe["ceiling"] = ["随便写点什么"]
    assert "'GPU'" in _violations(tmp_path, strip_ceiling)


# ------------------------------------------------------------ every seat is a sub-agent (inv. 7)

def test_no_seat_is_the_main_thread():
    """Director rule D7: the conductor never plays an instrument."""
    for view in recipes.resolve_all():
        for facts in view["mode_facts"]:
            assert facts["seats"] > 0, facts["mode"]
            assert recipes.MAIN_THREAD_AGENT not in facts["seat_names"], facts["mode"]


def test_the_step_table_calls_the_seats_sub_agents_so_the_director_is_never_told_i_do_the_work():
    card = render_recipe("direction-to-bet", project="demo")
    assert "sub-agent" in card
    assert "主线程只负责路由" in card


@pytest.mark.parametrize("render", [render_menu, lambda: render_recipe("direction-to-bet")],
                         ids=["menu", "recipe"])
def test_the_roster_is_never_presented_as_a_dispatch_promise(render):
    """`docs/03-WORKFLOWS.md` §1: agent_subset is the roster, max_agent_hops the ceiling, and the
    real dispatch count sits between them. Reading either as "this many will run" is an overclaim."""
    card = render()
    assert "席可上场" in card
    assert "真正派出去的在两者之间" in card
    assert "席 sub-agent" not in card


# ------------------------------------------------------------------ broken catalogs are rejected

def test_an_unknown_mode_is_rejected(tmp_path):
    def unknown(data):
        _first(data)["variants"][0]["modes"] = ["no_such_mode"]
    assert "unknown mode" in _violations(tmp_path, unknown)


def test_a_spec_only_mode_is_rejected(tmp_path):
    def spec_only(data):
        # exemplar swapped 2026-08-04: verify_result is one-button now.
        _first(data)["variants"][0]["modes"] = ["tree_explore"]
    assert "spec-only" in _violations(tmp_path, spec_only)


def test_an_unknown_intent_is_rejected(tmp_path):
    def unknown_intent(data):
        _first(data)["covers_intents"] = ["not_an_intent"]
    assert "unknown intent" in _violations(tmp_path, unknown_intent)


def test_two_recommended_depths_are_rejected(tmp_path):
    def two_stars(data):
        for variant in _first(data)["variants"]:
            variant["recommended"] = True
    assert "exactly ONE recommended" in _violations(tmp_path, two_stars)


def test_losing_coverage_of_a_mode_is_rejected(tmp_path):
    def drop_manuscripts(data):
        data["recipes"].pop("manuscript-and-review")
    text = _violations(tmp_path, drop_manuscripts)
    assert "reachable from NO outcome" in text
    assert "manuscript_authoring" in text


def test_a_broken_catalog_cannot_be_rendered_silently(tmp_path):
    path = _broken(tmp_path, lambda data: _first(data)["variants"][0].update(modes=["nope"]))
    with pytest.raises(ValueError, match="invalid"):
        recipes.assert_valid(path=path)


# ------------------------------------------------------------------------- the compiled commands

def test_link_two_onwards_is_threaded_to_the_previous_run():
    steps = recipes.command_chain("direction-to-bet", project="demo")
    assert len(steps) == 2
    assert "--upstream-run" not in steps[0]["commands"][0]
    assert "--upstream-run" in steps[1]["commands"][0]
    assert steps[1]["stops_at"] == ["/idea-bet"]


def test_the_north_star_is_never_defaulted_to_the_generic_want():
    """"我想要一个能下注的研究方向" bounds nothing; pinning it would make every drift check vacuous."""
    steps = recipes.command_chain("direction-to-bet", project="demo")
    begin = steps[0]["commands"][0]
    assert recipes.REQUEST_PLACEHOLDER in begin
    assert recipes.resolve("direction-to-bet")["want"] not in begin
    with_request = recipes.command_chain("direction-to-bet", project="demo", request="修好失败区")
    assert '--request "修好失败区"' in with_request[0]["commands"][0]


def test_only_modes_that_start_in_discover_get_a_pre_search_step():
    registry = research_plan.load_mode_registry()["modes"]
    for view in recipes.resolve_all():
        for step, facts in zip(recipes.command_chain(view["id"]), view["mode_facts"]):
            wants_search = any("pre-search" in c for c in step["commands"])
            assert wants_search == (registry[facts["mode"]]["entry_stage"] == "DISCOVER")


# ---------------------------------------------------------------------------------- the surfaces

def test_the_menu_never_shows_the_director_a_raw_mode_id():
    """Director lock 2026-08-01: no acronym soup. The commands may name modes; the menu may not."""
    card = render_menu()
    for mode in research_plan.wired_modes():
        assert mode not in card, mode
    for view in recipes.resolve_all():
        assert view["want"] in card
        assert view["deliverable"] in card


def test_the_recipe_card_carries_the_ceiling_and_the_gate_stop():
    card = render_recipe("submit-or-not", project="demo")
    assert "不能" in card
    assert "模拟盲审是内部预演" in card
    assert "/venue-pick" in card


def test_the_brief_and_the_menu_name_the_same_outcome_for_one_request(tmp_path):
    request = "帮我找个研究方向"
    data = briefing.build_briefing(request, project=None, vault_root=str(tmp_path / "nope"),
                                   runs_dir=str(tmp_path / "runs"))
    assert data["outcome"] == recipes.match_recipe(request)
    assert data["outcome"]["id"] == "direction-to-bet"


def test_an_unmatched_request_gets_no_outcome_so_the_caller_shows_the_menu():
    assert recipes.match_recipe("今天天气怎么样") is None


def test_the_workbench_prints_the_menu_and_refuses_an_unknown_outcome(capsys):
    workbench_main(["outcomes"])
    assert "你想得到什么" in capsys.readouterr().out
    workbench_main(["outcomes", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["validation"]["ok"] is True
    assert len(payload["menu"]) == len(recipes.recipe_ids())
    with pytest.raises(SystemExit) as exit_info:
        workbench_main(["outcome", "no-such-outcome"])
    assert exit_info.value.code == 2
    assert "known" in capsys.readouterr().out
