"""Tests for the provider-call receipt import boundary.

R3 §B①: ed25519 signature verification and file-content hash comparison are torn down (same
rationale as test_execution_receipt_import.py — a personal single-operator tool, not a
multi-tenant trust boundary). Deleted: test_unsigned_tampering_and_wrong_signer_are_rejected, and
test_missing_trust_key_blocks_instead_of_accepting_self_report (its whole point — "reject an
unattested self-report" — stops being true once nothing verifies attestation any more). The
"artifact_binding" case is dropped from the parametrized fail-closed test for the same reason
(receipt-declared vs. recomputed file SHA-256).

What is KEPT and still fail-closed: schema validation (estimated_source/missing_usage), the
token-total arithmetic coherence check (not a hash), timeline ordering (finished >= started), and
challenge-binding identity checks (dispatch/nonce/cross_run) — these compare a receipt's claimed
identity against the frozen challenge it was issued against, which is a binding property (like
run_id in test_execution_receipt_import.py), not file-tamper detection, even though one of the
compared fields happens to be a sha256 string. The replay guard is likewise kept: it is dedup
bookkeeping (the same provider_request_id must not resolve to two different receipts), not a
trust mechanism.
"""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from research_agent_teams.tools import provider_call_receipt_import as receipts


PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_KEY = PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
NONCE = "a" * 64


def _resolver(key_id: str) -> bytes | None:
    return PUBLIC_KEY if key_id == "host-test" else None


def _challenge(*, nonce: str = NONCE, worker_id: str = "HB-01.X") -> dict:
    return receipts.create_provider_call_challenge(
        run_id="stage-b-test-run",
        task_id="HB-01",
        stage="STAGE_B_AUTHOR",
        worker_id=worker_id,
        dispatch_spec={
            "request_id": "HB-01",
            "blind_label": worker_id.rsplit(".", 1)[-1],
            "prompt_sha256": "f" * 64,
            "author_output_rel": f"authors/{worker_id}.md",
        },
        artifact_path=f"authors/{worker_id}.md",
        nonce=nonce,
    )


def _sign(receipt: dict, key: Ed25519PrivateKey = PRIVATE_KEY) -> dict:
    signed = copy.deepcopy(receipt)
    signed["attestation"]["signature"] = "ed25519:" + base64.b64encode(
        key.sign(receipts.receipt_attestation_message(signed))
    ).decode("ascii")
    return signed


def _install(
    root: Path,
    challenge: dict | None = None,
    *,
    provider_request_id: str = "provider-request-1",
    key: Ed25519PrivateKey = PRIVATE_KEY,
) -> tuple[dict, str, Path]:
    challenge = challenge or _challenge()
    artifact = root / challenge["artifact_path"]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("test-only author output\n", encoding="utf-8")
    receipt = {
        "receipt_version": receipts.PROVIDER_RECEIPT_VERSION,
        "producer_kind": receipts.PROVIDER_PRODUCER_KIND,
        "run_id": challenge["run_id"],
        "task_id": challenge["task_id"],
        "stage": challenge["stage"],
        "worker_id": challenge["worker_id"],
        "invocation_id": challenge["invocation_id"],
        "nonce": challenge["nonce"],
        "dispatch_spec_sha256": challenge["dispatch_spec_sha256"],
        "provider_request_id": provider_request_id,
        "requested": {
            "runtime_policy_id": "stage-b-test-policy-v1",
            "model": "requested-test-model",
            "service_tier": "requested-tier",
            "reasoning_effort": "requested-effort",
            "agent_type": "stage-b-author",
            "context_budget_tokens": 4096,
            "max_output_tokens": 1024,
        },
        "observed": {
            "resolved_model": {"value": "resolved-test-model", "source": "provider_response"},
            "service_tier": {"value": "observed-tier", "source": "provider_response"},
            "reasoning_effort": {"value": "observed-effort", "source": "provider_response"},
            "input_tokens": {"value": 101, "source": "provider_response"},
            "output_tokens": {"value": 50, "source": "provider_response"},
            "total_tokens": {"value": 151, "source": "provider_response"},
            "elapsed_ms": {"value": 1001, "source": "host_monotonic"},
        },
        "started_at": "2026-07-31T00:00:00Z",
        "finished_at": "2026-07-31T00:00:02Z",
        "artifact": {
            "path": challenge["artifact_path"],
            "sha256": receipts.sha256_file(artifact),
            "size_bytes": artifact.stat().st_size,
        },
        "attestation": {
            "scheme": "ed25519",
            "key_id": "host-test",
            "signature": "ed25519:" + base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    receipt = _sign(receipt, key)
    ref = f"runtime/{challenge['worker_id']}.json"
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt, ref, artifact


def _rewrite(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def test_schema_is_valid_and_module_exposes_no_signer():
    schema_path = Path(receipts.__file__).resolve().parent.parent / "schemas" / "provider_call_receipt.schema.json"
    Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))
    assert not any(name.startswith("sign") for name in receipts.__all__)


def test_challenge_binds_nonce_dispatch_and_artifact_path():
    challenge = _challenge()
    changed = receipts.create_provider_call_challenge(
        run_id="stage-b-test-run",
        task_id="HB-01",
        stage="STAGE_B_AUTHOR",
        worker_id="HB-01.X",
        dispatch_spec={"different": True},
        artifact_path="authors/HB-01.X.md",
        nonce=NONCE,
    )
    assert challenge["challenge_version"] == receipts.PROVIDER_CHALLENGE_VERSION
    assert challenge["nonce"] == NONCE
    assert challenge["dispatch_spec_sha256"].startswith("sha256:")
    assert challenge["invocation_id"] != changed["invocation_id"]
    with pytest.raises(receipts.ProviderCallReceiptError, match="safe relative path"):
        receipts.create_provider_call_challenge(
            run_id="run",
            task_id="task",
            stage="stage",
            worker_id="worker",
            dispatch_spec={"ok": True},
            artifact_path="../escape.md",
            nonce=NONCE,
        )


def test_verified_receipt_returns_only_normalized_provider_attested_usage(tmp_path):
    challenge = _challenge()
    _receipt, ref, _artifact = _install(tmp_path, challenge)
    guard: dict[str, str] = {}
    normalized = receipts.verify_provider_call_receipt(
        tmp_path,
        ref,
        expected_challenge=challenge,
        key_resolver=_resolver,
        replay_guard=guard,
    )
    assert normalized["status"] == "PROVIDER_ATTESTED"
    assert normalized["observed"] == {
        "resolved_model": "resolved-test-model",
        "service_tier": "observed-tier",
        "reasoning_effort": "observed-effort",
        "input_tokens": 101,
        "output_tokens": 50,
        "total_tokens": 151,
        "elapsed_ms": 1001,
    }
    assert normalized["observation_sources"]["elapsed_ms"] == "host_monotonic"
    assert all(
        normalized["observation_sources"][key] == "provider_response"
        for key in normalized["observation_sources"]
        if key != "elapsed_ms"
    )
    # 2026-08-07 de-governance: nothing here cryptographically verifies the ed25519 attestation any
    # more (see module docstring) — signature_verified is now honestly False, not a claim it can't
    # back up.
    assert normalized["attestation"]["signature_verified"] is False
    # Exact re-import is idempotent; a different receipt cannot occupy the same keys.
    again = receipts.verify_provider_call_receipt(
        tmp_path,
        ref,
        expected_challenge=challenge,
        key_resolver=_resolver,
        replay_guard=guard,
    )
    assert again["receipt_sha256"] == normalized["receipt_sha256"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("estimated_source", "schema BLOCK"),
        ("missing_usage", "schema BLOCK"),
        ("token_total", "token totals"),
        ("dispatch", "dispatch_spec_sha256"),
        ("nonce", "nonce"),
        ("cross_run", "run_id"),
        ("finished_before_started", "precedes"),
    ],
)
def test_fail_closed_for_unobserved_or_cross_bound_receipts(
    tmp_path, mutation, match
):
    challenge = _challenge()
    receipt, ref, _artifact = _install(tmp_path, challenge)
    path = tmp_path / ref
    if mutation == "estimated_source":
        receipt["observed"]["input_tokens"]["source"] = "estimated"
    elif mutation == "missing_usage":
        del receipt["observed"]["output_tokens"]
    elif mutation == "token_total":
        receipt["observed"]["total_tokens"]["value"] = 999
    elif mutation == "dispatch":
        receipt["dispatch_spec_sha256"] = "sha256:" + "0" * 64
    elif mutation == "nonce":
        receipt["nonce"] = "b" * 64
    elif mutation == "cross_run":
        receipt["run_id"] = "other-run"
    else:
        receipt["finished_at"] = "2026-07-30T23:59:59Z"
    _rewrite(path, _sign(receipt))
    with pytest.raises(receipts.ProviderCallReceiptError, match=match):
        receipts.verify_provider_call_receipt(
            tmp_path, ref, expected_challenge=challenge, key_resolver=_resolver
        )


def test_replay_guard_rejects_provider_request_reuse_across_invocations(tmp_path):
    first = _challenge(worker_id="HB-01.X")
    _receipt, first_ref, _artifact = _install(
        tmp_path, first, provider_request_id="provider-request-shared"
    )
    guard: dict[str, str] = {}
    receipts.verify_provider_call_receipt(
        tmp_path,
        first_ref,
        expected_challenge=first,
        key_resolver=_resolver,
        replay_guard=guard,
    )

    second = _challenge(nonce="b" * 64, worker_id="HB-01.Y")
    _receipt, second_ref, _artifact = _install(
        tmp_path, second, provider_request_id="provider-request-shared"
    )
    with pytest.raises(receipts.ProviderCallReceiptError, match="provider-request"):
        receipts.verify_provider_call_receipt(
            tmp_path,
            second_ref,
            expected_challenge=second,
            key_resolver=_resolver,
            replay_guard=guard,
        )
