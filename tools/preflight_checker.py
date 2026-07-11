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

from typing import Iterable, List, Optional

from research_agent_teams.tools.hash_manifest_validator import validate_manifest


def build_file_identity_checks(file_identity_manifests: Optional[Iterable[dict]]) -> List[dict]:
    """Validate optional sha256 manifests supplied as preflight evidence."""
    checks: List[dict] = []
    if not file_identity_manifests:
        return checks
    for idx, item in enumerate(file_identity_manifests):
        item = item or {}
        checks.append(validate_manifest(
            item.get("manifest") or {},
            item.get("required_paths") or [],
            manifest_ref=item.get("manifest_ref") or f"file_identity_manifests[{idx}]",
        ))
    return checks


def check_preflight(train_script: dict, test_script: dict, protocol_spec: dict,
                    alignment_report: dict, profile: Optional[dict] = None,
                    file_identity_manifests: Optional[Iterable[dict]] = None) -> List[str]:
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

    for check in build_file_identity_checks(file_identity_manifests):
        violations.extend([f"{check['manifest_ref']}: {v}" for v in check["violations"]])

    return violations


def build_report(train_script: dict, test_script: dict, protocol_spec: dict, alignment_report: dict,
                 profile: Optional[dict] = None, protocol_ref: Optional[str] = None,
                 alignment_ref: Optional[str] = None,
                 file_identity_manifests: Optional[Iterable[dict]] = None) -> dict:
    """Build a preflight_report payload (verdict derived from violations — never set by hand)."""
    file_identity_checks = build_file_identity_checks(file_identity_manifests)
    violations = check_preflight(
        train_script, test_script, protocol_spec, alignment_report, profile, file_identity_manifests)
    checks = ["data_hash", "config_frozen", "alignment_pass", "test_freeze"]
    if file_identity_checks:
        checks.append("file_identity_manifest")
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "checks_performed": checks,
        "protocol_ref": protocol_ref,
        "alignment_ref": alignment_ref,
        "file_identity_checks": file_identity_checks,
    }
