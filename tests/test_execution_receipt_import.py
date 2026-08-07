"""Tests for the non-LLM executor receipt/import boundary.

R3 §B①: signature verification and file/manifest hash-comparison are torn down (this is a
personal single-operator tool, not a multi-tenant trust boundary). Deleted:
test_llm_authored_or_wrongly_signed_receipt_is_rejected (ed25519 attestation),
test_receipt_bound_result_tampering_is_rejected and the command-hash half of what was
test_receipt_command_hash_and_run_replay_are_rejected (file/field hash comparison),
test_coherent_metrics_do_not_override_receipt_provenance (declared-hash-field comparison), and
test_stored_import_is_rederived_and_rehashed (whole-manifest + file hash re-equality on resume).
What is KEPT and still fail-closed: schema validation, path fencing/existence/symlink refusal
(`_safe_member`), timestamp ordering (finished >= started), and the run_id binding below (a plain
identity check, not a hash comparison). `_install_receipt` still signs its fixture receipt so the
schema shape stays realistic, even though nothing here verifies that signature any more.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_agent_teams.tools.execution_receipt_import import (
    ExecutionReceiptError,
    build_execution_import,
    canonical_json_bytes,
    receipt_attestation_message,
    receipt_bound_raw_rows,
    sha256_bytes,
    sha256_file,
    validate_records_against_import,
    verified_binding_index,
)


PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"test-only-external-executor-private-key").digest()
)
PUBLIC_KEY = PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
KEY_ID = "lab-runner-test"
TS = "2026-07-10T10:00:00Z"


def _write(path: Path, content: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _install_receipt(run_dir: Path, *, run_id: str = "run-1", value: float = 0.8,
                     role: str = "raw_result_rows",
                     key: Ed25519PrivateKey = PRIVATE_KEY) -> tuple[str, dict]:
    job_id = "job-c1-seed0"
    relative_root = Path("execution-results") / job_id
    stdout = _write(run_dir / relative_root / "stdout.log", "completed\n")
    stderr = _write(run_dir / relative_root / "stderr.log", "")
    row = {
        "job_id": job_id,
        "row_id": "c1-dice-0",
        "condition_id": "c1",
        "seed": 0,
        "metric": "Dice",
        "value": value,
    }
    result_payload = {"raw_result_rows": [row]} if role == "raw_result_rows" else {
        "diagnostic_id": "diag-1",
        "finding": "controlled intervention changed the suspected mechanism",
    }
    result = _write(
        run_dir / relative_root / "result.json",
        json.dumps(result_payload, sort_keys=True),
    )
    command = ["python", "run.py", "--condition", "c1", "--seed", "0"]
    receipt = {
        "receipt_version": "executor-receipt/v1",
        "producer_kind": "non-llm-executor",
        "run_id": run_id,
        "job_id": job_id,
        "condition_id": "c1",
        "seed": 0,
        "command": {
            "argv": command,
            "command_hash": sha256_bytes(canonical_json_bytes(command)),
        },
        "code_hash": sha256_bytes(b"code"),
        "config_hash": sha256_bytes(b"config-c1-seed0"),
        "data_hash": sha256_bytes(b"data"),
        "exit_status": 0,
        "started_at": "2026-07-10T09:59:00Z",
        "finished_at": "2026-07-10T10:00:00Z",
        "stdout": {**stdout, "path": stdout["path"].split(run_dir.as_posix() + "/", 1)[-1]},
        "stderr": {**stderr, "path": stderr["path"].split(run_dir.as_posix() + "/", 1)[-1]},
        "result_files": [{
            **result,
            "path": result["path"].split(run_dir.as_posix() + "/", 1)[-1],
            "role": role,
            "media_type": "application/json",
        }],
        "attestation": {
            "scheme": "ed25519",
            "key_id": KEY_ID,
            "signature": "ed25519:" + base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    receipt["attestation"]["signature"] = "ed25519:" + base64.b64encode(
        key.sign(receipt_attestation_message(receipt))
    ).decode("ascii")
    receipt_ref = f"executor-receipts/{job_id}.json"
    path = run_dir / receipt_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return receipt_ref, receipt


def _resolver(key_id: str) -> bytes | None:
    return PUBLIC_KEY if key_id == KEY_ID else None


def _record(receipt: dict, value: float = 0.8) -> dict:
    return {
        "condition_id": receipt["condition_id"],
        "status": "provisional",
        "provenance": {
            "config_hash": receipt["config_hash"],
            "data_hash": receipt["data_hash"],
            "git_sha": receipt["code_hash"],
            "seed": receipt["seed"],
        },
        "metrics": {"Dice": value},
    }


def test_signed_receipt_import_binds_job_files_and_run_record(tmp_path):
    run_dir = tmp_path / "run-1"
    ref, receipt = _install_receipt(run_dir)
    manifest = build_execution_import(
        run_dir, [ref], run_id="run-1", created_at=TS, key_resolver=_resolver
    )
    validate_records_against_import([_record(receipt)], manifest)
    rows = receipt_bound_raw_rows(run_dir, manifest)

    assert manifest["source_boundary"] == "attested-non-llm-executor"
    assert manifest["receipts"][0]["job_id"] == "job-c1-seed0"
    assert rows[0]["value"] == pytest.approx(0.8)
    assert verified_binding_index(manifest)[
        "execution-results/job-c1-seed0/result.json"
    ]["role"] == "raw_result_rows"


def test_receipt_replayed_into_a_different_run_is_rejected(tmp_path):
    """run_id binding is a plain identity check (not a hash comparison) — still fail-closed."""
    replay_dir = tmp_path / "run-2"
    ref, _ = _install_receipt(replay_dir, run_id="run-1")
    with pytest.raises(ExecutionReceiptError, match="run_id mismatch"):
        build_execution_import(
            replay_dir, [ref], run_id="run-2", created_at=TS, key_resolver=_resolver
        )
