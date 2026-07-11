"""Tests for hash-manifest validation as execution preflight evidence."""
from __future__ import annotations

import hashlib

from research_agent_teams.tools.hash_manifest_validator import validate_manifest


REQ = ["nnUNet_results/predictions/nnunet_s1_fold5_test_nomirror"]


def _live(lines):
    stdout = "\n".join(lines) + "\n"
    return {
        "mode": "live",
        "lines": lines,
        "missing": [],
        "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
    }


def test_live_manifest_covers_required_path():
    line = "a" * 64 + "  nnUNet_results/predictions/nnunet_s1_fold5_test_nomirror/case001.nii.gz"
    out = validate_manifest(_live([line]), REQ, manifest_ref="m1")
    assert out["verdict"] == "PASS"
    assert out["violations"] == []
    assert out["manifest_ref"] == "m1"


def test_plan_is_not_evidence():
    out = validate_manifest({"mode": "plan", "read_only_command": "sha256sum x"}, REQ)
    assert out["verdict"] == "BLOCK"
    assert any("not live evidence" in v for v in out["violations"])


def test_missing_path_blocks():
    line = "a" * 64 + "  other/path/case001.nii.gz"
    out = validate_manifest(_live([line]), REQ)
    assert out["verdict"] == "BLOCK"
    assert any("required path not covered" in v for v in out["violations"])


def test_malformed_hash_line_blocks():
    out = validate_manifest(
        _live(["abc123  nnUNet_results/predictions/nnunet_s1_fold5_test_nomirror/x"]),
        REQ,
    )
    assert out["verdict"] == "BLOCK"
    assert any("malformed" in v for v in out["violations"])
