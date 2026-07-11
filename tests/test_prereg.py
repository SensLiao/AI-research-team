"""tools/prereg — preregistration freeze + deviation check (audit C3)."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.prereg import build_deviation_verdict, build_prereg, check_deviation
from research_agent_teams.tools.validate_artifact import validate_payload

MATRIX = {
    "research_question": "Does LoRA beat full fine-tune at equal budget?",
    "variables": {"studied": ["adapter"], "controlled": [], "frozen": []},
    "conditions": [{"id": "c0", "factors": {}, "baseline": True}, {"id": "c1", "factors": {}}],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft"}],
    "leakage_declaration": "no test labels read",
}


def _prereg(**over):
    kw = dict(primary_metric="dice", n_seeds_planned=3,
              stopping_rule="fixed 3 seeds per condition",
              analysis_plan="paired permutation vs baseline, Holm-corrected, alpha=0.05")
    kw.update(over)
    return build_prereg(MATRIX, **kw)


def test_build_prereg_freezes_the_contract_and_validates():
    p = _prereg(secondary_metrics=["hd95"])
    assert validate_payload("preregistration", p) == []
    assert p["primary_metric"] == "dice" and p["condition_ids"] == ["c0", "c1"]
    assert p["baseline_condition_id"] == "c0" and p["hypotheses"] == ["LoRA >= full-ft"]


@pytest.mark.parametrize("bad", [
    {"primary_metric": " "}, {"n_seeds_planned": 0}, {"stopping_rule": ""}, {"analysis_plan": " "}])
def test_build_prereg_fails_loud_on_unfrozen_plan(bad):
    with pytest.raises(ValueError):
        _prereg(**bad)


def _rs(findings):
    return {"status": "provisional", "findings": findings, "caveats": [], "can_cite_thesis": False}


def test_missing_primary_metric_is_a_violation():
    v, _ = check_deviation(_prereg(), _rs([{"metric": "hd95", "value": 2.0, "condition_id": "c1"}]))
    assert any("primary metric" in x for x in v)


def test_unregistered_metric_is_outcome_switching():
    v, _ = check_deviation(_prereg(), _rs([
        {"metric": "dice", "value": 0.8, "condition_id": "c1"},
        {"metric": "surprise_auc", "value": 0.9, "condition_id": "c1"}]))
    assert any("outcome switching" in x for x in v)


def test_undeclared_condition_is_a_violation():
    v, _ = check_deviation(_prereg(), _rs([{"metric": "dice", "value": 0.8, "condition_id": "c9"}]))
    assert any("NOT in the preregistered condition" in x for x in v)


def test_fewer_seeds_is_a_warning_not_a_violation():
    v, w = check_deviation(_prereg(), _rs([
        {"metric": "dice", "value": 0.8, "condition_id": "c1", "n_seeds": 2}]))
    assert v == [] and any("fewer" in x for x in w)


def test_clean_analysis_passes_and_verdict_validates():
    rs = _rs([{"metric": "dice", "value": 0.8, "condition_id": "c1"}])
    v, w = check_deviation(_prereg(), rs)
    assert v == []
    verdict = build_deviation_verdict(_prereg(), rs)
    assert validate_payload("analysis_check_verdict", verdict) == []
    assert verdict["panel_role"] == "compliance" and verdict["pass"] is True
