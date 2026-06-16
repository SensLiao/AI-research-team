"""Deterministic core of the preflight-checker (EXECUTE hard gate).

Before a run commits (a real GPU now, or on a director-provided server later), verify the run is
reproducible and the comparison it will produce can be valid:
  1. train + test dataset scripts each declare an expected data hash   (data provenance pinned)
  2. the protocol has at least one compiled per-condition config        (config frozen, not prose)
  3. the train/test alignment contract is PASS                          (never run a misaligned design)
  4. the test set is frozen with augmentation disabled                  (test-set immutability)

The LLM agent gathers these artifacts (the two dataset_script_records, the protocol_spec, the
alignment_report); this checker — not the LLM — decides PASS/BLOCK, so the gate is mechanical.
"""
from __future__ import annotations

from typing import List, Optional


def check_preflight(train_script: dict, test_script: dict, protocol_spec: dict,
                    alignment_report: dict, profile: Optional[dict] = None) -> List[str]:
    """Return preflight violations; empty == cleared to run."""
    violations: List[str] = []

    if not train_script.get("data_hash_expected"):
        violations.append("train data hash not declared (data provenance must be pinned before a run)")
    if not test_script.get("data_hash_expected"):
        violations.append("test data hash not declared (data provenance must be pinned before a run)")

    configs = protocol_spec.get("configs") or []
    if not configs:
        violations.append("no compiled per-condition config (config must be frozen, not prose, before a run)")
    elif not all(isinstance(c, dict) and c.get("condition_id") and isinstance(c.get("config"), dict) for c in configs):
        violations.append("compiled config is malformed (each entry needs a condition_id and a config object)")

    if alignment_report.get("verdict") != "PASS":
        violations.append("train/test alignment contract is not PASS (a misaligned run is invalid)")

    if test_script.get("split") != "test":
        violations.append("test dataset script is not declared split='test' (cannot verify test-set freeze)")
    else:
        if test_script.get("frozen") is not True:
            violations.append("test set is not frozen before the run")
        if test_script.get("augmentation_enabled") is True:
            violations.append("test set has augmentation enabled (must be off before the run)")

    return violations


def build_report(train_script: dict, test_script: dict, protocol_spec: dict, alignment_report: dict,
                 profile: Optional[dict] = None, protocol_ref: Optional[str] = None,
                 alignment_ref: Optional[str] = None) -> dict:
    """Build a preflight_report payload (verdict derived from violations — never set by hand)."""
    violations = check_preflight(train_script, test_script, protocol_spec, alignment_report, profile)
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "checks_performed": ["data_hash", "config_frozen", "alignment_pass", "test_freeze"],
        "protocol_ref": protocol_ref,
        "alignment_ref": alignment_ref,
    }
