"""Fail-closed, evaluation-only A/B harness for research capability overlays.

This module does not call a model, network, process, third-party repository, or
the production operate entry.  It prepares blinded dispatch envelopes from a
frozen 20+ request manifest, seals already-produced author artifacts together
with observable runtime receipts, validates three independent judge sheets,
and deterministically reconciles the pre-registered paired evaluation.

The production ``research-orchestrator`` remains unchanged.  A Stage-B result
is admissible only when every input and receipt passes this harness; merely
preparing a plan is never reported as an evaluation pass.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.provider_call_receipt_import import (
    PROVIDER_RECEIPT_VERSION,
    ProviderCallReceiptError,
    create_provider_call_challenge,
    verify_provider_call_receipt,
)
from research_agent_teams.tools.research_capability_router import (
    DEFAULT_OVERLAY_CATALOG,
    route_research_capabilities,
)


_PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUEST_MANIFEST = (
    _PKG_ROOT
    / "_design"
    / "review"
    / "research-capability-overlay-stage-b-requests-v1.json"
)
CONDITION_SCHEMA = _PKG_ROOT / "schemas" / "overlay_ab_condition_manifest.schema.json"
JUDGE_SCHEMA = _PKG_ROOT / "schemas" / "overlay_ab_judge_sheet.schema.json"
AUTHOR_RUNTIME_POLICY_SCHEMA = (
    _PKG_ROOT / "schemas" / "overlay_ab_author_runtime_policy.schema.json"
)

REQUEST_CONTRACT = "research-capability-overlay-stage-b-requests/v1"
DISPATCH_CONTRACT = "research-capability-overlay-stage-b-dispatch/v2"
RUNTIME_CONTRACT = PROVIDER_RECEIPT_VERSION
CONDITION_CONTRACT = "research-capability-overlay-condition-manifest/v2"
JUDGE_CONTRACT = "research-capability-overlay-judge-sheet/v1"
REPORT_CONTRACT = "research-capability-overlay-stage-b-report/v1"
AUTHOR_RUNTIME_POLICY_CONTRACT = (
    "research-capability-overlay-author-runtime-policy/v1"
)

BLIND_LABELS = ("X", "Y")
TREATMENTS = ("baseline", "enhanced")
JUDGE_ROLES = ("domain_mechanism", "methods_statistics", "evidence_integrity")
SCORE_KEYS = tuple(f"Q{i}" for i in range(1, 9))
CORE_SCORE_KEYS = ("Q1", "Q3", "Q4", "Q6")


class OverlayABEvalError(ValueError):
    """A typed fail-closed stop for an invalid or incomplete evaluation."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file():
        raise OverlayABEvalError(f"required JSON file is missing: {candidate}")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OverlayABEvalError(f"cannot parse strict UTF-8 JSON: {candidate}") from exc
    if not isinstance(value, dict):
        raise OverlayABEvalError(f"JSON root must be an object: {candidate}")
    return value


def _validate_schema(value: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    schema = _read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors[:12]
        )
        raise OverlayABEvalError(f"{label} schema validation failed: {details}")


def _write_new_json(path: Path, value: Mapping[str, Any]) -> Path:
    if path.exists():
        raise OverlayABEvalError(f"refusing to overwrite immutable evaluation artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_new_text(path: Path, value: str) -> Path:
    if path.exists():
        raise OverlayABEvalError(f"refusing to overwrite immutable evaluation artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Disable platform newline translation so the hash calculated from UTF-8
    # bytes is identical on Windows and POSIX hosts.
    with path.open("w", encoding="utf-8", errors="strict", newline="") as handle:
        handle.write(value)
    return path


def _request_by_id(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    requests = manifest.get("requests")
    if not isinstance(requests, list) or len(requests) < 20:
        raise OverlayABEvalError("Stage B requires at least 20 frozen holdout requests")
    by_id: dict[str, dict[str, Any]] = {}
    stage_a_fingerprints = set(manifest.get("stage_a_prompt_sha256") or [])
    for index, item in enumerate(requests):
        if not isinstance(item, dict):
            raise OverlayABEvalError(f"request #{index + 1} must be an object")
        request_id = str(item.get("request_id") or "")
        request_text = str(item.get("request_text") or "").strip()
        expected_mode = str(item.get("expected_mode") or "")
        if not request_id or request_id in by_id:
            raise OverlayABEvalError(f"request_id is missing or duplicated: {request_id!r}")
        if not request_text or not expected_mode:
            raise OverlayABEvalError(f"{request_id} requires request_text and expected_mode")
        if _sha256_bytes(request_text.encode("utf-8")) in stage_a_fingerprints:
            raise OverlayABEvalError(f"{request_id} reuses a Stage-A prompt")
        source_packet = item.get("source_packet")
        if source_packet is not None and not isinstance(source_packet, dict):
            raise OverlayABEvalError(f"{request_id} source_packet must be an object or null")
        by_id[request_id] = dict(item)
    return by_id


def validate_request_manifest(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the frozen Stage-B holdout and pre-registration contract."""
    if manifest.get("schema_version") != REQUEST_CONTRACT:
        raise OverlayABEvalError(f"request manifest must use {REQUEST_CONTRACT}")
    if manifest.get("holdout_from_stage_a") is not True:
        raise OverlayABEvalError("request manifest must explicitly be held out from Stage A")
    stage_a_fingerprints = manifest.get("stage_a_prompt_sha256")
    if (
        not isinstance(stage_a_fingerprints, list)
        or len(stage_a_fingerprints) != 5
        or len(set(stage_a_fingerprints)) != 5
    ):
        raise OverlayABEvalError("request manifest must freeze five unique Stage-A prompt hashes")
    for fingerprint in stage_a_fingerprints:
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise OverlayABEvalError("every Stage-A prompt hash must be lowercase SHA-256")
        try:
            if fingerprint != fingerprint.lower():
                raise ValueError
            int(fingerprint, 16)
        except ValueError as exc:
            raise OverlayABEvalError(
                "every Stage-A prompt hash must be lowercase SHA-256"
            ) from exc
    prereg = manifest.get("preregistration")
    if not isinstance(prereg, dict):
        raise OverlayABEvalError("request manifest requires preregistration")
    required = {
        "minimum_pairs": 20,
        "judge_count": 3,
        "judge_aggregation": "mean_per_request_per_candidate",
        "primary_score": "sum_Q1_to_Q8_then_mean_three_judges",
        "minimum_mean_difference_points": 1.0,
        "missing_score_policy": "FAIL",
        "tie_rule": "equal_after_three_judge_mean",
        "core_dimensions": list(CORE_SCORE_KEYS),
        "core_non_degradation_floor": 0.0,
        "confidence_level": 0.95,
        "bootstrap_method": "paired_case_percentile",
        "bootstrap_resamples": 10000,
        "bootstrap_seed": 20260731,
        "permutation_method": "exact_sign_flip_for_20_pairs",
        "agreement_metric": "raw_exact_winner_agreement_fraction",
        "failure_disclosure": "ALL_CASES",
    }
    for key, expected in required.items():
        if prereg.get(key) != expected:
            raise OverlayABEvalError(
                f"preregistration field {key!r} must be frozen to {expected!r}"
            )
    by_id = _request_by_id(manifest)
    if len(by_id) != 20:
        raise OverlayABEvalError("v1 confirmatory manifest must contain exactly 20 holdout pairs")
    domains = {str(item.get("domain") or "") for item in by_id.values()}
    task_types = {str(item.get("task_type") or "") for item in by_id.values()}
    if len(domains) < 5 or len(task_types) < 4:
        raise OverlayABEvalError("Stage B requires at least five domains and four task types")
    return by_id


def _source_packet_hash(source_packet: Any) -> str:
    return _sha256_value({"source_packet": source_packet})


def _blind_mapping(request_id: str, prompt_sha256: str, salt: str) -> dict[str, str]:
    bit = int(_sha256_bytes(f"{salt}\n{request_id}\n{prompt_sha256}".encode("utf-8")), 16) & 1
    if bit:
        return {"X": "enhanced", "Y": "baseline"}
    return {"X": "baseline", "Y": "enhanced"}


def _overlay_prompt(route: Mapping[str, Any]) -> str:
    lines = [
        "RESEARCH CAPABILITY OVERLAYS (the intended A/B treatment; advisory quality lenses):"
    ]
    for item in route["capability_overlays"]:
        lines.append(f"- {item['title']}: {item['summary']}")
        non_goals = ", ".join(item.get("non_goals") or [])
        if non_goals:
            lines.append(f"  non_goals: {non_goals}")
    return "\n".join(lines)


def validate_author_runtime_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one global requested-runtime contract for all 40 authors.

    This is a requested dispatch policy, not evidence that a provider honored
    it.  Provider-resolved values still require a signed host receipt at seal.
    """
    if not isinstance(policy, Mapping):
        raise OverlayABEvalError("Stage-B requires one explicit author runtime policy")
    normalized = dict(policy)
    _validate_schema(
        normalized,
        AUTHOR_RUNTIME_POLICY_SCHEMA,
        label="author runtime policy",
    )
    return normalized


def _requested_runtime_projection(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Project the frozen experiment policy onto provider receipt fields."""
    return {
        "runtime_policy_id": policy["runtime_policy_id"],
        "requested_model": policy["model"],
        "requested_service_tier": policy["service_tier"],
        "requested_reasoning_effort": policy["reasoning_effort"],
        "agent_type": policy["agent_type"],
        "context_budget_tokens": policy["context_budget_tokens"],
        "max_output_tokens": policy["max_output_tokens"],
    }


def prepare_stage_b(
    request_manifest_path: str | Path = DEFAULT_REQUEST_MANIFEST,
    *,
    out_dir: str | Path,
    overlay_catalog_path: str | Path = DEFAULT_OVERLAY_CATALOG,
    author_runtime_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create immutable, condition-labelled author dispatch envelopes.

    The returned plan is private to the dispatcher.  Judges receive only the
    later blind packet, never this treatment mapping.
    """
    request_path = Path(request_manifest_path).resolve()
    overlay_path = Path(overlay_catalog_path).resolve()
    manifest = _read_json(request_path)
    by_id = validate_request_manifest(manifest)
    runtime_policy = validate_author_runtime_policy(author_runtime_policy or {})
    runtime_policy_sha256 = _sha256_value(runtime_policy)
    registry = load_mode_registry()
    known_modes = registry.get("modes") or {}
    salt = str(manifest.get("blinding_salt") or "")
    if len(salt) < 16:
        raise OverlayABEvalError("blinding_salt must contain at least 16 characters")

    overlay_catalog = _read_json(overlay_path)
    overlay_catalog_sha256 = _sha256_file(overlay_path)
    evaluation_id = (
        "stage-b-"
        + _sha256_value(
            {
                "request_manifest_sha256": _sha256_file(request_path),
                "overlay_catalog_sha256": overlay_catalog_sha256,
                "author_runtime_policy_sha256": runtime_policy_sha256,
            }
        )[:32]
    )
    challenge_nonces: set[str] = set()
    challenge_invocations: set[str] = set()
    pairs = []
    for request_id in sorted(by_id):
        item = by_id[request_id]
        expected_mode = item["expected_mode"]
        if expected_mode not in known_modes:
            raise OverlayABEvalError(f"{request_id} expected_mode is not in live registry")
        route = route_research_capabilities(
            item["request_text"],
            explicit_mode=expected_mode,
            publication_kind=item.get("publication_kind"),
            registry=registry,
            overlay_catalog=overlay_catalog,
        )
        if route["routing"]["mode"] != expected_mode:
            raise OverlayABEvalError(f"{request_id} routed to the wrong mode")
        base_prompt = str(item["request_text"]).strip()
        source_packet = item.get("source_packet")
        source_text = json.dumps(source_packet, ensure_ascii=False, sort_keys=True, indent=2)
        shared = (
            f"REQUEST\n{base_prompt}\n\nFROZEN SOURCE PACKET\n{source_text}\n\n"
            "Return a research-quality answer only. Treat missing evidence as unknown; do not invent "
            "sources, results, execution, novelty, or receipts."
        )
        prompt_sha256 = _sha256_bytes(shared.encode("utf-8"))
        mapping = _blind_mapping(request_id, prompt_sha256, salt)
        candidates = {}
        for label in BLIND_LABELS:
            treatment = mapping[label]
            prompt = shared
            overlay_ids: list[str] = []
            if treatment == "enhanced":
                prompt += "\n\n" + _overlay_prompt(route)
                overlay_ids = [entry["overlay_id"] for entry in route["capability_overlays"]]
            candidate = {
                "blind_label": label,
                "treatment": treatment,
                "author_output_rel": f"authors/{request_id}.{label}.md",
                "runtime_receipt_rel": f"runtime/{request_id}.{label}.json",
                "prompt": prompt,
                "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
                "overlay_ids": overlay_ids,
                # The full global policy is deliberately duplicated inside
                # every dispatch spec.  Therefore each challenge hash binds
                # the exact requested model/tier/effort/agent/budgets, not
                # merely a mutable plan-level reference.
                "author_runtime_policy": dict(runtime_policy),
            }
            # This is a pre-dispatch challenge, not an execution claim.  The
            # host adapter receives it out-of-band, binds it to the actual
            # provider response and author artifact, then signs the receipt.
            # The model must never receive the host signing key.
            challenge = create_provider_call_challenge(
                run_id=evaluation_id,
                task_id=request_id,
                stage="STAGE_B_AUTHOR",
                worker_id=f"{request_id}.{label}",
                dispatch_spec=candidate,
                artifact_path=candidate["author_output_rel"],
            )
            if (
                challenge["nonce"] in challenge_nonces
                or challenge["invocation_id"] in challenge_invocations
            ):
                raise OverlayABEvalError("provider receipt challenge collision during Stage-B prepare")
            challenge_nonces.add(challenge["nonce"])
            challenge_invocations.add(challenge["invocation_id"])
            candidate["provider_receipt_challenge"] = challenge
            candidates[label] = candidate
        pairs.append(
            {
                "request_id": request_id,
                "domain": item["domain"],
                "task_type": item["task_type"],
                "expected_mode": expected_mode,
                "mode_status": route["routing"]["honesty"]["state"],
                "base_prompt_sha256": prompt_sha256,
                "source_packet_sha256": _source_packet_hash(source_packet),
                "request_text": base_prompt,
                "source_packet": source_packet,
                "mapping": mapping,
                "candidates": candidates,
            }
        )

    plan = {
        "schema_version": DISPATCH_CONTRACT,
        "evaluation_state": "PREPARED_NOT_RUN",
        "evaluation_id": evaluation_id,
        "request_manifest": {
            "path": str(request_path),
            "sha256": _sha256_file(request_path),
        },
        "overlay_catalog": {
            "path": str(overlay_path),
            "sha256": overlay_catalog_sha256,
        },
        "author_runtime_policy": dict(runtime_policy),
        "author_runtime_policy_sha256": runtime_policy_sha256,
        "preregistration": manifest["preregistration"],
        "pairs": pairs,
        "safety": {
            "network": "DENY",
            "model_execution": False,
            "third_party_execution": False,
            "production_entry_modified": False,
        },
    }
    target = assert_not_vault_path(out_dir, purpose="write overlay A/B evaluation plan")
    output = _write_new_json(target / "dispatch-plan.json", plan)
    _write_new_text(target / "dispatch-plan.sha256", _sha256_file(output) + "\n")
    return plan


def _validate_runtime_receipt(
    receipt_ref: str,
    *,
    artifact_root: Path,
    challenge: Mapping[str, Any],
    request_id: str,
    blind_label: str,
    key_resolver: Callable[[str], bytes | None] | None,
    replay_guard: dict[str, str],
) -> dict[str, Any]:
    try:
        normalized = verify_provider_call_receipt(
            artifact_root,
            receipt_ref,
            expected_challenge=challenge,
            key_resolver=key_resolver,
            replay_guard=replay_guard,
        )
    except ProviderCallReceiptError as exc:
        raise OverlayABEvalError(
            f"{request_id}.{blind_label} requires a signed provider-attested runtime receipt: {exc}"
        ) from exc
    if normalized.get("status") != "PROVIDER_ATTESTED":
        # Defensive redundancy: the importer currently has no non-attested
        # success path, and Stage-B must never grow one implicitly.
        raise OverlayABEvalError(
            f"{request_id}.{blind_label} runtime usage is not PROVIDER_ATTESTED"
        )
    requested = normalized["requested"]
    observed = normalized["observed"]
    return {
        "runtime_receipt_id": normalized["invocation_id"],
        "provider_receipt_version": normalized["receipt_version"],
        "producer_kind": normalized["producer_kind"],
        "runtime_policy_id": requested["runtime_policy_id"],
        "requested_model": requested["model"],
        "requested_service_tier": requested["service_tier"],
        "requested_reasoning_effort": requested["reasoning_effort"],
        "resolved_model": observed["resolved_model"],
        "service_tier": observed["service_tier"],
        "reasoning_effort": observed["reasoning_effort"],
        "agent_type": requested["agent_type"],
        "context_budget_tokens": requested["context_budget_tokens"],
        "max_output_tokens": requested["max_output_tokens"],
        "provider_request_id": normalized["provider_request_id"],
        "dispatch_spec_sha256": normalized["dispatch_spec_sha256"],
        "attestation_key_id": normalized["attestation"]["key_id"],
        "observable_usage": {
            "status": "PROVIDER_ATTESTED",
            "input_tokens": observed["input_tokens"],
            "output_tokens": observed["output_tokens"],
            "total_tokens": observed["total_tokens"],
            "elapsed_ms": observed["elapsed_ms"],
        },
        "author_artifact": dict(normalized["artifact"]),
        "normalized_receipt_sha256": normalized["receipt_sha256"],
    }


def _resolve_beneath(root: Path, relative: Any, *, label: str) -> Path:
    """Resolve a dispatch artifact without permitting absolute or parent traversal."""
    if not isinstance(relative, str) or not relative.strip():
        raise OverlayABEvalError(f"{label} must be a non-empty relative path")
    raw = Path(relative)
    if raw.is_absolute():
        raise OverlayABEvalError(f"{label} must remain below the artifact root")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OverlayABEvalError(f"{label} escapes the artifact root") from exc
    return candidate


def _verify_file_binding(binding: Any, *, label: str) -> None:
    """2026-08-07 de-governance: existence-only — no longer re-hashes the file against the
    binding's recorded sha256 (that was tamper-evidence for edits after Stage-B prepare, not the
    safety property)."""
    if not isinstance(binding, dict):
        raise OverlayABEvalError(f"dispatch plan lacks {label} binding")
    path = binding.get("path")
    expected_sha = binding.get("sha256")
    if not isinstance(path, str) or not isinstance(expected_sha, str):
        raise OverlayABEvalError(f"dispatch plan has an invalid {label} binding")
    if not Path(path).is_file():
        raise OverlayABEvalError(f"{label} is missing")


def _parity_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: receipt[key]
        for key in (
            "runtime_policy_id",
            "requested_model",
            "requested_service_tier",
            "requested_reasoning_effort",
            "resolved_model",
            "service_tier",
            "reasoning_effort",
            "agent_type",
            "context_budget_tokens",
            "max_output_tokens",
        )
    }


def _observed_runtime_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: receipt[key]
        for key in ("resolved_model", "service_tier", "reasoning_effort")
    }


def seal_stage_b(
    dispatch_plan_path: str | Path,
    *,
    artifact_root: str | Path,
    out_dir: str | Path,
    provider_key_resolver: Callable[[str], bytes | None] | None = None,
) -> dict[str, Any]:
    """Seal author artifacts and runtime parity before any judge sees them."""
    plan_path = Path(dispatch_plan_path).resolve()
    plan = _read_json(plan_path)
    if plan.get("schema_version") != DISPATCH_CONTRACT:
        raise OverlayABEvalError(
            "invalid or legacy dispatch-plan contract; run fresh prepare"
        )
    sidecar = plan_path.with_name("dispatch-plan.sha256")
    if not sidecar.is_file():
        raise OverlayABEvalError("dispatch plan is missing its immutable SHA-256 sidecar")
    _verify_file_binding(plan.get("request_manifest"), label="request manifest")
    _verify_file_binding(plan.get("overlay_catalog"), label="overlay catalog")
    try:
        runtime_policy = validate_author_runtime_policy(plan.get("author_runtime_policy") or {})
    except OverlayABEvalError as exc:
        raise OverlayABEvalError(
            "dispatch plan is legacy or lacks a valid frozen global author runtime policy; "
            "run fresh prepare"
        ) from exc
    runtime_policy_sha256 = _sha256_value(runtime_policy)
    expected_requested_runtime = _requested_runtime_projection(runtime_policy)
    pairs = plan.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 20:
        raise OverlayABEvalError("dispatch plan must contain exactly 20 frozen pairs")
    request_ids = [str(pair.get("request_id") or "") for pair in pairs if isinstance(pair, dict)]
    if len(request_ids) != 20 or len(set(request_ids)) != 20 or any(not item for item in request_ids):
        raise OverlayABEvalError("dispatch plan request IDs must be 20 unique non-empty values")
    root = Path(artifact_root).resolve()
    replay_guard: dict[str, str] = {}
    global_runtime_projection: dict[str, Any] | None = None
    global_observed_runtime: dict[str, Any] | None = None
    sealed_pairs = []
    packet_lines = [
        "# Stage-B blinded capability-overlay evaluation packet",
        "",
        "Judges must not access the condition manifest, dispatch plan, author runtime receipts, or one another's sheets.",
        "",
    ]
    for pair in pairs:
        request_id = pair["request_id"]
        mapping = pair.get("mapping")
        if not isinstance(mapping, dict) or {mapping.get("X"), mapping.get("Y")} != set(TREATMENTS):
            raise OverlayABEvalError(f"{request_id} must map X/Y to opposing treatments")
        candidates = pair.get("candidates")
        if not isinstance(candidates, dict) or set(candidates) != set(BLIND_LABELS):
            raise OverlayABEvalError(f"{request_id} must contain exactly X and Y candidates")
        candidate_records: dict[str, Any] = {}
        receipts: dict[str, dict[str, Any]] = {}
        packet_lines.extend(
            [
                f"## {request_id}",
                "",
                f"Domain: {pair['domain']}  ",
                f"Task type: {pair['task_type']}  ",
                f"Request: {pair['request_text']}",
                "",
                "Frozen source packet:",
                "```json",
                json.dumps(pair.get("source_packet"), ensure_ascii=False, sort_keys=True, indent=2),
                "```",
                "",
            ]
        )
        for label in BLIND_LABELS:
            candidate = candidates[label]
            if candidate.get("blind_label") != label or candidate.get("treatment") != mapping[label]:
                raise OverlayABEvalError(f"{request_id}.{label} candidate disagrees with mapping")
            if candidate.get("author_runtime_policy") != runtime_policy:
                raise OverlayABEvalError(
                    f"{request_id}.{label} candidate differs from the frozen global author runtime policy"
                )
            author_rel = candidate.get("author_output_rel")
            receipt_rel = candidate.get("runtime_receipt_rel")
            author_path = _resolve_beneath(
                root, author_rel, label=f"{request_id}.{label} author_output_rel"
            )
            receipt_path = _resolve_beneath(
                root, receipt_rel, label=f"{request_id}.{label} runtime_receipt_rel"
            )
            if not author_path.is_file() or not receipt_path.is_file():
                raise OverlayABEvalError(f"missing author artifact or runtime receipt for {request_id}.{label}")
            author_text = author_path.read_text(encoding="utf-8").strip()
            if not author_text:
                raise OverlayABEvalError(f"empty author artifact for {request_id}.{label}")
            challenge = candidate.get("provider_receipt_challenge")
            if not isinstance(challenge, dict):
                raise OverlayABEvalError(
                    f"{request_id}.{label} lacks a frozen provider receipt challenge"
                )
            dispatch_projection = {
                key: value
                for key, value in candidate.items()
                if key != "provider_receipt_challenge"
            }
            try:
                expected_challenge = create_provider_call_challenge(
                    run_id=str(plan.get("evaluation_id") or ""),
                    task_id=request_id,
                    stage="STAGE_B_AUTHOR",
                    worker_id=f"{request_id}.{label}",
                    dispatch_spec=dispatch_projection,
                    artifact_path=author_rel,
                    nonce=challenge.get("nonce"),
                )
            except ProviderCallReceiptError as exc:
                raise OverlayABEvalError(
                    f"{request_id}.{label} has an invalid provider receipt challenge: {exc}"
                ) from exc
            if challenge != expected_challenge:
                raise OverlayABEvalError(
                    f"{request_id}.{label} provider receipt challenge differs from the frozen dispatch"
                )
            receipt = _validate_runtime_receipt(
                receipt_rel,
                artifact_root=root,
                challenge=expected_challenge,
                request_id=request_id,
                blind_label=label,
                key_resolver=provider_key_resolver,
                replay_guard=replay_guard,
            )
            requested_projection = {
                key: receipt[key] for key in expected_requested_runtime
            }
            if requested_projection != expected_requested_runtime:
                raise OverlayABEvalError(
                    f"{request_id}.{label} receipt differs from the frozen global author runtime policy"
                )
            receipt_projection = _parity_projection(receipt)
            observed_projection = _observed_runtime_projection(receipt)
            if global_runtime_projection is None:
                global_runtime_projection = receipt_projection
                global_observed_runtime = observed_projection
            elif receipt_projection != global_runtime_projection:
                raise OverlayABEvalError(
                    f"global author runtime parity failed at {request_id}.{label} across all 40 receipts"
                )
            receipts[label] = receipt
            candidate_records[label] = {
                "blind_label": label,
                "treatment": candidate["treatment"],
                "prompt_sha256": candidate["prompt_sha256"],
                "overlay_ids": candidate["overlay_ids"],
                "author_artifact": {
                    "path": author_rel,
                    "sha256": _sha256_file(author_path),
                },
                "runtime_receipt": {
                    "path": receipt_rel,
                    "sha256": _sha256_file(receipt_path),
                    "receipt_id": receipt["runtime_receipt_id"],
                    "provider_receipt_version": receipt["provider_receipt_version"],
                    "producer_kind": receipt["producer_kind"],
                    "runtime_policy_id": receipt["runtime_policy_id"],
                    "requested_model": receipt["requested_model"],
                    "requested_service_tier": receipt["requested_service_tier"],
                    "requested_reasoning_effort": receipt["requested_reasoning_effort"],
                    "resolved_model": receipt["resolved_model"],
                    "service_tier": receipt["service_tier"],
                    "reasoning_effort": receipt["reasoning_effort"],
                    "agent_type": receipt["agent_type"],
                    "context_budget_tokens": receipt["context_budget_tokens"],
                    "max_output_tokens": receipt["max_output_tokens"],
                    "provider_request_id": receipt["provider_request_id"],
                    "dispatch_spec_sha256": receipt["dispatch_spec_sha256"],
                    "attestation_key_id": receipt["attestation_key_id"],
                    "observable_usage": dict(receipt["observable_usage"]),
                },
            }
            packet_lines.extend([f"### Candidate {label}", "", author_text, ""])
        if _parity_projection(receipts["X"]) != _parity_projection(receipts["Y"]):
            raise OverlayABEvalError(f"A/B runtime or budget parity failed for {request_id}")
        if pair["candidates"]["X"]["prompt_sha256"] == pair["candidates"]["Y"]["prompt_sha256"]:
            raise OverlayABEvalError(f"{request_id} has no observable overlay treatment difference")
        sealed_pairs.append(
            {
                "request_id": request_id,
                "domain": pair["domain"],
                "task_type": pair["task_type"],
                "expected_mode": pair["expected_mode"],
                "mode_status": pair["mode_status"],
                "base_prompt_sha256": pair["base_prompt_sha256"],
                "source_packet_sha256": pair["source_packet_sha256"],
                "mapping": dict(pair["mapping"]),
                "candidates": candidate_records,
                "runtime_parity": "PASS",
            }
        )

    target = assert_not_vault_path(out_dir, purpose="write overlay A/B sealed evaluation")
    packet_text = "\n".join(packet_lines).rstrip() + "\n"
    packet_path = target / "blind-packet.md"
    manifest_path = target / "condition-manifest.json"
    if packet_path.exists() or manifest_path.exists():
        raise OverlayABEvalError("refusing to overwrite existing sealed evaluation artifacts")
    manifest = {
        "schema_version": CONDITION_CONTRACT,
        "evaluation_state": "SEALED_AWAITING_JUDGES",
        "dispatch_plan": {"path": str(plan_path), "sha256": _sha256_file(plan_path)},
        "request_manifest": dict(plan["request_manifest"]),
        "overlay_catalog": dict(plan["overlay_catalog"]),
        "author_runtime_policy": dict(runtime_policy),
        "author_runtime_policy_sha256": runtime_policy_sha256,
        "global_observed_runtime": dict(global_observed_runtime or {}),
        "global_runtime_parity": "PASS",
        "preregistration": dict(plan["preregistration"]),
        "blind_packet": {
            "path": "blind-packet.md",
            "sha256": _sha256_bytes(packet_text.encode("utf-8")),
        },
        "pairs": sealed_pairs,
        "judge_contract": {
            "required_roles": list(JUDGE_ROLES),
            "judge_count": 3,
            "judge_schema_sha256": _sha256_file(JUDGE_SCHEMA),
            "mutual_blindness_required": True,
        },
        "safety": {
            "condition_manifest_excluded_from_judge_inputs": True,
            "network": "DENY",
            "third_party_execution": False,
        },
    }
    _validate_schema(manifest, CONDITION_SCHEMA, label="condition manifest")
    _write_new_text(packet_path, packet_text)
    _write_new_json(manifest_path, manifest)
    return manifest


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise OverlayABEvalError("cannot take a percentile of an empty sample")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def paired_bootstrap_interval(
    deltas: Sequence[float], *, resamples: int, seed: int, confidence: float
) -> tuple[float, float]:
    if not deltas:
        raise OverlayABEvalError("paired bootstrap requires at least one delta")
    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(resamples):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)


def exact_sign_flip_pvalue(deltas: Sequence[float]) -> float:
    """Two-sided exact paired sign-flip p-value (20 pairs => 2^20 states)."""
    if not deltas:
        raise OverlayABEvalError("sign-flip test requires at least one delta")
    if len(deltas) > 20:
        raise OverlayABEvalError("v1 exact sign-flip contract supports at most 20 pairs")
    observed = abs(sum(deltas))
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(deltas)):
        signed_sum = abs(sum(sign * delta for sign, delta in zip(signs, deltas)))
        if signed_sum + 1e-12 >= observed:
            extreme += 1
        total += 1
    return extreme / total


def _judge_case_map(sheet: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    cases = sheet.get("cases") or []
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        request_id = case["request_id"]
        if request_id in result:
            raise OverlayABEvalError(f"judge sheet duplicates request {request_id}")
        result[request_id] = case
    return result


def _candidate_total(candidate: Mapping[str, Any]) -> int:
    return sum(int(candidate["scores"][key]) for key in SCORE_KEYS)


def reconcile_stage_b(
    condition_manifest_path: str | Path,
    *,
    judge_paths: Iterable[str | Path],
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate three mutually blind judges and apply the frozen Stage-B gate."""
    condition_path = Path(condition_manifest_path).resolve()
    condition = _read_json(condition_path)
    _validate_schema(condition, CONDITION_SCHEMA, label="condition manifest")
    condition_ids = [pair["request_id"] for pair in condition["pairs"]]
    if len(set(condition_ids)) != 20:
        raise OverlayABEvalError("condition manifest must contain 20 unique request IDs")
    for pair in condition["pairs"]:
        mapping = pair["mapping"]
        if {mapping["X"], mapping["Y"]} != set(TREATMENTS):
            raise OverlayABEvalError(
                f"condition pair {pair['request_id']} must map opposing treatments"
            )
        for label in BLIND_LABELS:
            candidate = pair["candidates"][label]
            if candidate["blind_label"] != label or candidate["treatment"] != mapping[label]:
                raise OverlayABEvalError(
                    f"condition pair {pair['request_id']}.{label} disagrees with mapping"
                )
    packet_path = _resolve_beneath(
        condition_path.parent,
        condition["blind_packet"]["path"],
        label="blind packet path",
    )
    if not packet_path.is_file():
        raise OverlayABEvalError("blind packet is missing")

    sheets: list[dict[str, Any]] = []
    sheet_evidence = []
    for raw_path in judge_paths:
        path = Path(raw_path).resolve()
        sheet = _read_json(path)
        _validate_schema(sheet, JUDGE_SCHEMA, label=f"judge sheet {path.name}")
        if sheet["packet_sha256"] != condition["blind_packet"]["sha256"]:
            raise OverlayABEvalError(f"judge {sheet['judge_id']} scored a different blind packet")
        sheets.append(sheet)
        sheet_evidence.append({"path": str(path), "sha256": _sha256_file(path)})
    if len(sheets) != 3:
        raise OverlayABEvalError("Stage B requires exactly three judge sheets")
    roles = [sheet["judge_role"] for sheet in sheets]
    if sorted(roles) != sorted(JUDGE_ROLES):
        raise OverlayABEvalError("Stage B requires one judge for each frozen role")
    judge_ids = [sheet["judge_id"] for sheet in sheets]
    if len(set(judge_ids)) != 3:
        raise OverlayABEvalError("judge_id values must be unique")

    expected_ids = [pair["request_id"] for pair in condition["pairs"]]
    case_maps = [_judge_case_map(sheet) for sheet in sheets]
    for sheet, cases in zip(sheets, case_maps):
        if set(cases) != set(expected_ids):
            raise OverlayABEvalError(
                f"judge {sheet['judge_id']} case set differs from the 20 frozen requests"
            )

    case_results = []
    fatal_defects = []
    deltas = []
    core_deltas = {key: [] for key in CORE_SCORE_KEYS}
    agreement_hits = 0
    for pair in condition["pairs"]:
        request_id = pair["request_id"]
        treatment_to_label = {treatment: label for label, treatment in pair["mapping"].items()}
        baseline_label = treatment_to_label["baseline"]
        enhanced_label = treatment_to_label["enhanced"]
        baseline_totals = []
        enhanced_totals = []
        judge_winners = []
        request_fatals = []
        for sheet, cases in zip(sheets, case_maps):
            case = cases[request_id]
            candidates = case["candidates"]
            x_total = _candidate_total(candidates["X"])
            y_total = _candidate_total(candidates["Y"])
            expected_winner = "X" if x_total > y_total else "Y" if y_total > x_total else "TIE"
            if case["winner"] != expected_winner:
                raise OverlayABEvalError(
                    f"judge {sheet['judge_id']} winner conflicts with Q1-Q8 totals for {request_id}"
                )
            baseline_totals.append(_candidate_total(candidates[baseline_label]))
            enhanced_totals.append(_candidate_total(candidates[enhanced_label]))
            for label in BLIND_LABELS:
                for defect in candidates[label]["fatal_defects"]:
                    entry = {
                        "request_id": request_id,
                        "judge_id": sheet["judge_id"],
                        "candidate": label,
                        **dict(defect),
                    }
                    request_fatals.append(entry)
                    fatal_defects.append(entry)
            judge_winners.append(case["winner"])
            for key in CORE_SCORE_KEYS:
                core_deltas[key].append(
                    candidates[enhanced_label]["scores"][key]
                    - candidates[baseline_label]["scores"][key]
                )
        baseline_mean = sum(baseline_totals) / 3.0
        enhanced_mean = sum(enhanced_totals) / 3.0
        delta = enhanced_mean - baseline_mean
        deltas.append(delta)
        if len(set(judge_winners)) == 1:
            agreement_hits += 1
        case_results.append(
            {
                "request_id": request_id,
                "baseline_label": baseline_label,
                "enhanced_label": enhanced_label,
                "baseline_mean_total": baseline_mean,
                "enhanced_mean_total": enhanced_mean,
                "paired_delta": delta,
                "judge_winners": judge_winners,
                "fatal_defects": request_fatals,
            }
        )

    prereg = condition["preregistration"]
    mean_delta = sum(deltas) / len(deltas)
    ci_low, ci_high = paired_bootstrap_interval(
        deltas,
        resamples=prereg["bootstrap_resamples"],
        seed=prereg["bootstrap_seed"],
        confidence=prereg["confidence_level"],
    )
    sign_flip_p = exact_sign_flip_pvalue(deltas)
    core_summary = {
        key: sum(values) / len(values) for key, values in core_deltas.items()
    }
    failures = []
    if fatal_defects:
        failures.append({"code": "FATAL_DEFECT", "affected_requests": sorted({d["request_id"] for d in fatal_defects})})
    if mean_delta < prereg["minimum_mean_difference_points"]:
        failures.append({"code": "MDES_NOT_MET", "observed": mean_delta})
    if ci_low <= 0.0:
        failures.append({"code": "PAIRED_INTERVAL_CROSSES_ZERO", "interval": [ci_low, ci_high]})
    for key, value in core_summary.items():
        if value < prereg["core_non_degradation_floor"]:
            failures.append({"code": "CORE_DIMENSION_REGRESSION", "dimension": key, "observed": value})
    for case in case_results:
        if case["paired_delta"] < 0 or case["fatal_defects"]:
            failures.append(
                {
                    "code": "CASE_FAILURE",
                    "request_id": case["request_id"],
                    "paired_delta": case["paired_delta"],
                    "fatal_count": len(case["fatal_defects"]),
                }
            )

    report = {
        "schema_version": REPORT_CONTRACT,
        "evaluation_state": "PAIRED_EVALUATION_PASS" if not failures else "PAIRED_EVALUATION_FAIL",
        "condition_manifest": {"path": str(condition_path), "sha256": _sha256_file(condition_path)},
        "blind_packet": dict(condition["blind_packet"]),
        "judge_sheets": sheet_evidence,
        "pair_count": len(case_results),
        "judge_count": len(sheets),
        "preregistration": prereg,
        "primary": {
            "mean_paired_difference_points": mean_delta,
            "minimum_mean_difference_points": prereg["minimum_mean_difference_points"],
            "paired_bootstrap_interval": [ci_low, ci_high],
            "confidence_level": prereg["confidence_level"],
            "exact_two_sided_sign_flip_p": sign_flip_p,
        },
        "core_dimension_mean_deltas": core_summary,
        "judge_agreement": {
            "metric": prereg["agreement_metric"],
            "value": agreement_hits / len(case_results),
            "exact_agreement_cases": agreement_hits,
        },
        "case_results": case_results,
        "fatal_defects": fatal_defects,
        "failure_cases": failures,
        "claim_boundary": (
            "A PASS supports the pre-registered paired quality claim for this frozen 20-request "
            "evaluation only; it does not prove general scientific superiority or replace real project validation."
        ),
    }
    if out_path is not None:
        target = assert_not_vault_path(out_path, purpose="write overlay A/B evaluation report")
        _write_new_json(target, report)
    return report


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare, seal, or reconcile overlay Stage-B A/B evaluation.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--request-manifest", default=str(DEFAULT_REQUEST_MANIFEST))
    prepare.add_argument("--overlay-catalog", default=str(DEFAULT_OVERLAY_CATALOG))
    prepare.add_argument("--author-runtime-policy", required=True)
    prepare.add_argument("--out-dir", required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--dispatch-plan", required=True)
    seal.add_argument("--artifact-root", required=True)
    seal.add_argument("--out-dir", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--condition-manifest", required=True)
    reconcile.add_argument("--judge", action="append", required=True)
    reconcile.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    _configure_utf8_stdio()
    try:
        if args.command == "prepare":
            result = prepare_stage_b(
                args.request_manifest,
                out_dir=args.out_dir,
                overlay_catalog_path=args.overlay_catalog,
                author_runtime_policy=_read_json(args.author_runtime_policy),
            )
        elif args.command == "seal":
            result = seal_stage_b(
                args.dispatch_plan,
                artifact_root=args.artifact_root,
                out_dir=args.out_dir,
            )
        else:
            result = reconcile_stage_b(
                args.condition_manifest,
                judge_paths=args.judge,
                out_path=args.out,
            )
    except OverlayABEvalError as exc:
        sys.stderr.write(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False) + "\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "status": "PASS",
                "artifact_state": result.get("evaluation_state"),
                "note": "PASS means the requested harness step completed; it is not a Stage-B scientific verdict unless artifact_state is PAIRED_EVALUATION_PASS.",
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONDITION_SCHEMA",
    "AUTHOR_RUNTIME_POLICY_SCHEMA",
    "AUTHOR_RUNTIME_POLICY_CONTRACT",
    "DEFAULT_REQUEST_MANIFEST",
    "JUDGE_SCHEMA",
    "OverlayABEvalError",
    "exact_sign_flip_pvalue",
    "main",
    "paired_bootstrap_interval",
    "prepare_stage_b",
    "reconcile_stage_b",
    "seal_stage_b",
    "validate_request_manifest",
    "validate_author_runtime_policy",
]
