"""Real tests for the adversarial-reviewer's deterministic core (5-check refutation, default BLOCK)."""
from __future__ import annotations

import copy

from research_agent_teams.tools.review_checker import build_report
from research_agent_teams.tools.validate_artifact import validate_against

ALL_PASS = {
    "leakage": {"pass": True, "evidence": "re-derived data path; no test mask read (loader.py:88)"},
    "fairness": {"pass": True, "evidence": "same split/eval-frame/n as baseline (run r-2:eval.json)"},
    "eval_frame": {"pass": True, "evidence": "Dice computed on raw frame, aggregated per-case (metrics.py:31)"},
    "provenance": {"pass": True, "evidence": "git 9f2a1 + data-v3 reconstruct the number"},
    "overclaim": {"pass": True, "evidence": "wording matches a +1.2 Dice implementation detail, not an RQ win"},
}


def test_all_checks_pass_with_evidence_approves():
    rep = build_report(ALL_PASS)
    assert rep["verdict"] == "APPROVE-FREEZE"
    assert rep["blocking_reasons"] == []
    assert rep["default_block_applied"] is False


def test_one_failing_check_blocks():
    bad = copy.deepcopy(ALL_PASS)
    bad["leakage"] = {"pass": False, "evidence": "val set overlaps train by patient id"}
    rep = build_report(bad)
    assert rep["verdict"] == "BLOCK"
    assert any("leakage" in r for r in rep["blocking_reasons"])


def test_pass_without_evidence_defaults_to_block():
    bad = copy.deepcopy(ALL_PASS)
    bad["provenance"] = {"pass": True}                 # claims pass, cites nothing
    rep = build_report(bad)
    assert rep["verdict"] == "BLOCK"
    assert rep["default_block_applied"] is True
    assert any("provenance" in r and "no evidence" in r for r in rep["blocking_reasons"])


def test_uninvestigated_check_defaults_to_block():
    bad = copy.deepcopy(ALL_PASS)
    del bad["eval_frame"]                               # never investigated
    rep = build_report(bad)
    assert rep["verdict"] == "BLOCK"
    assert rep["default_block_applied"] is True
    assert any("eval_frame" in r and "not investigated" in r for r in rep["blocking_reasons"])


def test_report_is_schema_valid_both_verdicts():
    assert validate_against("review_report.schema.json", build_report(ALL_PASS)) == []
    assert validate_against("review_report.schema.json", build_report({})) == []
