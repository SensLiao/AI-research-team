"""Run-to-run chaining: the `handoff.accepts` contract and the not-chained advisory.

Runs are independent by design — only `begin --upstream-run <prev>` links them. Three defects made
that link unusable for half the roster, and all three were silent:

  1. Ten operated modes declared `handoff.accepts: []`. Empty was read as "refuses every upstream",
     so `--upstream-run` into `design_experiment` / `power_analysis_review` / `verify_result` / … raised
     `mode handoff mismatch: accepts []` — the modes were structurally unchainable.
  2. The two validators disagreed about empty `accepts`: `validate_upstream_grounding` skipped the
     check (permissive), `_validate_downstream_compatibility` refused (strict). Whether a chain was
     legal depended on which one happened to run.
  3. Nothing said anything when a mode that DOES declare `accepts` was begun with no `--upstream-run`.
     The chain simply did not happen, and the cost surfaced only when the downstream product turned
     out to contradict a finding it never read.

`ingest_paper` stays empty on purpose: it is the root of every chain and consumes a PDF, not a run.
That is what makes empty a meaningful state rather than an unfinished one — so these tests pin the
distinction rather than just asserting "no mode has an empty list".
"""
from __future__ import annotations

import json

import pytest
import yaml

from research_agent_teams.tools import research_plan


def _registry() -> dict:
    return research_plan.load_mode_registry()["modes"]


def _operated() -> dict:
    return {m: s for m, s in _registry().items() if s.get("operated")}


# ------------------------------------------------------------------ 1. every mode declares a contract

def test_only_the_entry_point_mode_declares_no_upstream_contract():
    """An empty `accepts` must mean "entry point", never "nobody filled this in".

    2026-08-07: ideate_ring (grounded input is the director's own opportunity-set TEXT, read
    verbatim from task_frame.payload.request_text — no upstream artifact contract) and
    aers_enhanced_research_pack (reads the vault plus its own internal AERS catalog snapshot,
    never a prior run's artifact) joined ingest_paper as genuine entry points."""
    empty = sorted(m for m, spec in _operated().items()
                   if not ((spec.get("handoff") or {}).get("accepts") or []))
    assert empty == ["aers_enhanced_research_pack", "ideate_ring", "ingest_paper"], (
        f"{empty} declare no upstream contract. Empty `handoff.accepts` makes a mode unchainable, "
        f"so it is only correct for a true entry point (ingest_paper takes a PDF, not a run).")


def test_every_declared_accept_is_a_product_some_mode_actually_emits():
    """A mode cannot accept a contract nothing produces — that is an unreachable chain."""
    produced = {str((s.get("handoff") or {}).get("product_version") or "")
                for s in _registry().values()}
    produced.discard("")
    # Historical product versions stay acceptable so an older completed run can still be chained in.
    legacy = {"paper-reading/v2", "idea-investment-memo/v1"}
    for mode, spec in _operated().items():
        for accepted in (spec.get("handoff") or {}).get("accepts") or []:
            assert accepted in produced or accepted in legacy, (
                f"{mode} accepts {accepted!r}, which no mode in the registry produces")


def test_no_mode_accepts_its_own_product():
    """Self-acceptance would let a mode chain into itself and call that progress."""
    for mode, spec in _operated().items():
        handoff = spec.get("handoff") or {}
        assert str(handoff.get("product_version") or "") not in (handoff.get("accepts") or []), (
            f"{mode} accepts its own product — a chain link that adds nothing")


# ------------------------------------------------------------------ 2. one rule for empty `accepts`

def _fake_run(tmp_path, run_id: str, mode: str, *, status: str = "done"):
    """A minimal on-disk run the handoff reader can parse: task frame + manifest + report note."""
    run_dir = tmp_path / run_id
    (run_dir / "evidence" / "REPORT").mkdir(parents=True)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(
        {"payload": {"mode": mode, "task_id": run_id, "request_text": "r", "project": "p"}}),
        encoding="utf-8")
    (run_dir / "manifest.yaml").write_text(yaml.safe_dump({"status": status}), encoding="utf-8")
    (run_dir / "evidence" / "REPORT" / "report-note.artifact.json").write_text(json.dumps(
        {"payload": {"summary": f"{mode} done", "delivery_status": "USABLE"}}), encoding="utf-8")
    return run_dir


def test_a_declared_upstream_product_is_accepted(tmp_path):
    """The defect that started this: gap_breadth -> design_experiment used to raise."""
    up = _fake_run(tmp_path, "gap-1", "gap_breadth")
    grounding = research_plan.upstream_grounding([str(up)], "design_experiment")
    assert grounding["upstream_runs"][0]["mode"] == "gap_breadth"


def test_an_entry_point_mode_refuses_a_chain_and_says_why(tmp_path):
    """Refusal is right for a root mode — but the message must name the reason, not print `accepts []`."""
    up = _fake_run(tmp_path, "gap-1", "gap_breadth")
    with pytest.raises(ValueError) as excinfo:
        research_plan.upstream_grounding([str(up)], "ingest_paper")
    message = str(excinfo.value)
    assert "entry-point mode" in message and "gap-dossier/v1" in message
    assert "accepts []" not in message, "the old message read as a registry gap, not a design property"


def test_both_validators_agree_about_an_entry_point_mode(tmp_path):
    """They used to disagree: one skipped an empty `accepts`, the other refused. Same rule now."""
    up = _fake_run(tmp_path, "gap-1", "gap_breadth")
    grounding = research_plan.upstream_grounding([str(up)], "design_experiment")  # DOES accept it
    grounding["downstream_mode"] = "ingest_paper"                          # now judge it as the root mode
    grounding["downstream_contract"] = dict(grounding.get("downstream_contract") or {}, accepts=[])
    errors = research_plan.validate_upstream_grounding(grounding)
    assert any("entry-point mode" in e for e in errors), (
        f"validate_upstream_grounding stayed silent where _validate_downstream_compatibility raises: {errors}")


def test_a_mismatched_but_non_empty_contract_still_reports_the_mismatch(tmp_path):
    """Filling in `accepts` must not turn the compatibility check into a rubber stamp."""
    up = _fake_run(tmp_path, "ingest-1", "ingest_paper")     # produces ingest-paper/v1
    with pytest.raises(ValueError, match="mode handoff mismatch"):
        research_plan.upstream_grounding([str(up)], "power_analysis_review")


# ------------------------------------------------------------------ 3. say when the chain was skipped

def test_advisory_names_the_runs_that_were_available_but_not_chained(tmp_path):
    runs = tmp_path / "runs"
    project = runs / "p"
    project.mkdir(parents=True)
    _fake_run(project, "gap-1", "gap_breadth")
    advisory = research_plan.unchained_upstream_advisory(str(runs), "p", "design_experiment")
    assert advisory["status"] == "NOT_CHAINED"
    assert [r["run_id"] for r in advisory["available_upstream_runs"]] == ["gap-1"]
    assert "--upstream-run gap-1" in advisory["note"], "the advisory must be actionable, not just a warning"


def test_advisory_is_silent_for_an_entry_point_mode(tmp_path):
    runs = tmp_path / "runs"
    project = runs / "p"
    project.mkdir(parents=True)
    _fake_run(project, "gap-1", "gap_breadth")
    assert research_plan.unchained_upstream_advisory(str(runs), "p", "ingest_paper") is None


def test_advisory_ignores_an_unfinished_upstream_run(tmp_path):
    """An in-flight run is not a handoff — readiness validation would refuse it, so do not offer it."""
    runs = tmp_path / "runs"
    project = runs / "p"
    project.mkdir(parents=True)
    _fake_run(project, "gap-1", "gap_breadth", status="running")
    assert research_plan.unchained_upstream_advisory(str(runs), "p", "design_experiment") is None


def test_advisory_is_silent_when_nothing_compatible_exists(tmp_path):
    runs = tmp_path / "runs"
    project = runs / "p"
    project.mkdir(parents=True)
    _fake_run(project, "ing-1", "ingest_paper")    # produces ingest-paper/v1, which design_experiment
    assert research_plan.unchained_upstream_advisory(     # does not accept
        str(runs), "p", "design_experiment") is None
