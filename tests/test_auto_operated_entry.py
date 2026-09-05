"""Regression tests for the single operated auto-entry resolver.

The director must see the same automatic entry in ``operate brief`` that
``operate begin --mode auto`` will start. Automatic routing may never cross the
spec-only boundary; explicit modes remain exact manual overrides.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_agent_teams.operate import cli
from research_agent_teams.operate.modes import REGISTRY
from research_agent_teams.reporting import briefing
from research_agent_teams.tools import research_plan
from research_agent_teams.tools.research_capability_router import (
    resolve_operated_mode,
    route_research_capabilities,
)


@pytest.mark.parametrize(
    ("request_text", "expected_mode"),
    [
        ("帮我找个研究方向", "new_direction"),
        ("评一下证据", "evidence_deep"),
        ("扫一遍空白点", "gap_breadth"),
        ("精读论文", "read_paper_deep"),
        ("把这篇论文收进库", "ingest_paper"),
        ("设计这个实验", "full_rigor_minimal"),
        ("帮我写论文初稿", "manuscript_authoring"),
        ("审稿", "manuscript_review"),
        ("回复审稿意见", "manuscript_reconstruction"),
        ("Audit the manuscript authoring control plane and router tests", "repo_code_audit"),
        ("够投吗", "venue_readiness"),
    ],
)
def test_brief_router_and_auto_begin_share_one_operated_resolution(
    tmp_path, request_text, expected_mode
):
    resolution = resolve_operated_mode(request_text)
    route = route_research_capabilities(request_text)
    begin_mode, begin_route = cli._resolve_begin_mode(request_text, "auto")
    card = briefing.build_briefing(
        request_text,
        vault_root=str(tmp_path / "vault"),
        projects_root=str(tmp_path / "projects"),
        runs_dir=str(tmp_path / "runs"),
        resources_root_path=str(tmp_path / "resources"),
    )

    assert resolution["mode"] == expected_mode
    assert route["routing"]["mode"] == expected_mode
    assert begin_mode == expected_mode
    assert begin_route == route
    assert card["routes"]["auto_mode"] == expected_mode
    assert expected_mode in REGISTRY
    assert route["routing"]["honesty"]["one_button_operable"] is True


def test_every_plan_catalog_intent_resolves_to_an_operated_entry():
    for intent_id, spec in research_plan.load_catalog()["intents"].items():
        request = spec["aliases"][0]
        resolution = resolve_operated_mode(request, intent=intent_id)
        assert resolution["mode"] in REGISTRY, (
            f"intent {intent_id!r} escaped the operated surface via {resolution['mode']!r}"
        )


def test_experiment_design_auto_never_selects_spec_only_design_experiment():
    mode, route = cli._resolve_begin_mode("请设计这个实验并明确样本量", "auto")
    assert mode == "full_rigor_minimal"
    assert mode in REGISTRY
    assert route["routing"]["honesty"]["state"] == "operated"


def test_explicit_operated_mode_has_priority_without_calling_auto_router(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("manual override called the automatic router")

    monkeypatch.setattr(cli, "route_research_capabilities", forbidden)
    mode, route = cli._resolve_begin_mode("设计这个实验", "read_paper_deep")
    assert mode == "read_paper_deep"
    assert route is None


def test_explicit_spec_only_mode_fails_closed_before_run_creation(capsys):
    args = SimpleNamespace(
        mode="tree_explore",
        request="设计这个实验",
        run_id=None,
        ts="2026-08-01T00:00:00Z",
    )
    with pytest.raises(SystemExit) as stopped:
        cli.cmd_begin(args)
    assert stopped.value.code == 2
    assert "not wired in the operate layer" in capsys.readouterr().out
