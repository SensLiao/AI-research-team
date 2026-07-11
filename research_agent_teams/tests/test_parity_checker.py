"""Real tests for the parity-checker deterministic core (EXECUTE hard gate).

Post-run, the actual pipeline captured in the journal must still satisfy the alignment contract.
Reuses the alignment checker, so designed-vs-executed drift (e.g. eval aug turned on at run time) is
caught with the same rule the DESIGN gate used.
"""
from __future__ import annotations

from research_agent_teams.tools.parity_checker import build_report, check_parity

# An aligned actual pipeline (parity holds) vs a drifted one (eval augmentation turned on at run time).
_ACTUAL_TRAIN = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True}, "pretrained": "none",
                 "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_ACTUAL_TEST_OK = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False}, "pretrained": "none",
                   "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_ACTUAL_TEST_DRIFT = {**_ACTUAL_TEST_OK, "augmentation": {"enabled": True}}  # eval aug at run time → drift

_ALIGN_PASS = {"verdict": "PASS", "violations": []}


def _journal(train=_ACTUAL_TRAIN, test=_ACTUAL_TEST_OK,
             designed_train=_ACTUAL_TRAIN, designed_test=_ACTUAL_TEST_OK):
    return {"condition_id": "c1", "config_hash": "cfg#1",
            "designed_train": designed_train, "designed_test": designed_test,
            "actual_train": train, "actual_test": test}


def test_held_contract_passes_parity():
    assert check_parity(_journal(), _ALIGN_PASS) == []
    assert build_report(_journal(), _ALIGN_PASS)["verdict"] == "PASS"


def test_self_consistent_drift_from_design_blocks():
    # both train+test silently switched fp32 -> fp16 at run time: INTERNALLY aligned (self-consistency
    # passes) but no longer the DESIGNED run — the designed-vs-actual check must still catch it.
    actual_train = {**_ACTUAL_TRAIN, "precision": "fp16"}
    actual_test = {**_ACTUAL_TEST_OK, "precision": "fp16"}
    j = _journal(train=actual_train, test=actual_test)  # designed_* stay fp32 (defaults)
    v = check_parity(j, _ALIGN_PASS)
    assert any("drifted from design" in x for x in v)
    assert build_report(j, _ALIGN_PASS)["verdict"] == "BLOCK"


def test_uncaptured_design_pipeline_is_unverifiable_and_blocks():
    bare = {"condition_id": "c1", "config_hash": "cfg#1",
            "actual_train": _ACTUAL_TRAIN, "actual_test": _ACTUAL_TEST_OK}  # no designed_*
    v = check_parity(bare, _ALIGN_PASS)
    assert any("designed pipeline" in x for x in v)
    assert build_report(bare, _ALIGN_PASS)["verdict"] == "BLOCK"


def test_post_run_drift_blocks():
    v = check_parity(_journal(test=_ACTUAL_TEST_DRIFT), _ALIGN_PASS)
    assert any("post-run drift" in x for x in v)
    assert build_report(_journal(test=_ACTUAL_TEST_DRIFT), _ALIGN_PASS)["verdict"] == "BLOCK"


def test_run_without_pass_alignment_blocks():
    align_block = {"verdict": "BLOCK", "violations": ["x"]}
    assert any("without a PASS alignment contract" in x for x in check_parity(_journal(), align_block))


def test_uncaptured_pipeline_is_unverifiable_and_blocks():
    bare = {"condition_id": "c1", "config_hash": "cfg#1"}  # no actual_train/actual_test
    v = check_parity(bare, _ALIGN_PASS)
    assert any("unverifiable" in x for x in v)
    assert build_report(bare, _ALIGN_PASS)["verdict"] == "BLOCK"
