"""Real tests for the preflight-checker deterministic core (EXECUTE hard gate).

The gate must clear a reproducible, aligned, frozen run and BLOCK anything that would make the run
unverifiable or the comparison invalid. verdict is derived from violations, never set by hand.
"""
from __future__ import annotations

from research_agent_teams.tools.preflight_checker import build_report, check_preflight

_TRAIN = {"split": "train", "script": "build_train()", "from_protocol_ref": "proto#1",
          "data_hash_expected": "dh-train"}
_TEST = {"split": "test", "script": "build_test()", "from_protocol_ref": "proto#1",
         "data_hash_expected": "dh-test", "augmentation_enabled": False, "frozen": True}
_PROTO = {"from_matrix_ref": "m#1", "shared": {}, "configs": [{"condition_id": "c1", "config": {}}]}
_ALIGN_PASS = {"verdict": "PASS", "violations": []}


def test_clean_run_clears_preflight():
    assert check_preflight(_TRAIN, _TEST, _PROTO, _ALIGN_PASS) == []
    r = build_report(_TRAIN, _TEST, _PROTO, _ALIGN_PASS)
    assert r["verdict"] == "PASS" and r["violations"] == []


def test_missing_data_hash_blocks():
    bad_train = {**_TRAIN, "data_hash_expected": None}
    v = check_preflight(bad_train, _TEST, _PROTO, _ALIGN_PASS)
    assert any("train data hash" in x for x in v)
    assert build_report(bad_train, _TEST, _PROTO, _ALIGN_PASS)["verdict"] == "BLOCK"


def test_unaligned_design_blocks():
    align_block = {"verdict": "BLOCK", "violations": ["preprocessing mismatch"]}
    assert build_report(_TRAIN, _TEST, _PROTO, align_block)["verdict"] == "BLOCK"
    assert any("alignment contract is not PASS" in x for x in check_preflight(_TRAIN, _TEST, _PROTO, align_block))


def test_unfrozen_or_augmented_test_set_blocks():
    leaky_test = {**_TEST, "frozen": False, "augmentation_enabled": True}
    v = check_preflight(_TRAIN, leaky_test, _PROTO, _ALIGN_PASS)
    assert any("not frozen" in x for x in v) and any("augmentation enabled" in x for x in v)


def test_unfrozen_config_blocks():
    no_config = {"from_matrix_ref": "m#1", "shared": {}, "configs": []}
    assert build_report(_TRAIN, _TEST, no_config, _ALIGN_PASS)["verdict"] == "BLOCK"


def test_malformed_config_blocks():
    # a truthy-but-empty config list (configs=[{}]) must NOT clear "config frozen" — it is content-free
    bad_proto = {"from_matrix_ref": "m#1", "shared": {}, "configs": [{}]}
    v = check_preflight(_TRAIN, _TEST, bad_proto, _ALIGN_PASS)
    assert any("malformed" in x for x in v)
    assert build_report(_TRAIN, _TEST, bad_proto, _ALIGN_PASS)["verdict"] == "BLOCK"


def test_test_script_without_split_blocks():
    no_split = {k: v for k, v in _TEST.items() if k != "split"}  # freeze checks must not be silently skipped
    v = check_preflight(_TRAIN, no_split, _PROTO, _ALIGN_PASS)
    assert any("not declared split='test'" in x for x in v)
    assert build_report(_TRAIN, no_split, _PROTO, _ALIGN_PASS)["verdict"] == "BLOCK"
