"""Deterministic protocol for staged, mutually blind venue-readiness review.

Worker prose is never trusted as proof of ordering or independence. This module freezes the venue
profile/config before review, validates per-seat read attestations, freezes review hashes before
meta-review, and checks that the meta-review exposes disagreements and repair obligations.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..operate.artifacts import GateBlock, envelope, write_artifact
from .validate_artifact import validate_artifact


PERSONAS = ("methodology", "domain", "adversarial")
PROTOCOL_VERSION = "venue-blind-review/v2"

PROFILE_BUNDLE_REL = Path("inbox/VERIFY.profile.bundle.json")
CONFIG_BUNDLE_REL = Path("inbox/VERIFY.review-config.bundle.json")
PRECOMMIT_RECEIPT_REL = Path("inbox/VERIFY.precommit.receipt.json")
PANEL_RECEIPT_REL = Path("inbox/VERIFY.reviews.receipt.json")
META_BUNDLE_REL = Path("inbox/VERIFY.meta.bundle.json")
PROFILE_ARTIFACT_REL = Path("evidence/VERIFY/venue-profile.artifact.json")
CONFIG_ARTIFACT_REL = Path("evidence/VERIFY/review-config.artifact.json")

PROFILE_REF = PROFILE_ARTIFACT_REL.as_posix()
CONFIG_REF = CONFIG_ARTIFACT_REL.as_posix()
PRECOMMIT_REF = PRECOMMIT_RECEIPT_REL.as_posix()
PANEL_RECEIPT_REF = PANEL_RECEIPT_REL.as_posix()

_PRECOMMIT_KEYS = {
    "protocol_version", "frozen_at", "profile_ref", "config_ref", "profile_hash",
    "config_hash", "precommit_hash", "profile_candidate_ref", "config_candidate_ref",
    "personas", "allowed_reviewer_inputs", "forbidden_reviewer_inputs",
}
_ATTESTATION_KEYS = {
    "protocol_version", "persona", "reviewer_instance_id", "precommit_hash", "profile_ref",
    "config_ref", "precommit_ref", "anchor_echo", "input_refs", "other_review_refs_seen",
    "output_ref",
}
_PANEL_RECEIPT_KEYS = {
    "protocol_version", "frozen_at", "precommit_hash", "precommit_ref", "profile_hash",
    "review_refs", "review_hashes", "reviewer_instance_ids",
}
_META_KEYS = {
    "protocol_version", "precommit_hash", "review_receipt_ref", "review_hashes",
    "reviewer_disagreements", "strongest_reject_reason", "fatal_gaps", "repairable_gaps",
    "repair_sequence", "human_gates", "advisory_only",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path, purpose: str) -> dict:
    if not path.is_file():
        raise GateBlock(f"venue VERIFY: missing {purpose} at {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"venue VERIFY: invalid JSON in {purpose} at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateBlock(f"venue VERIFY: {purpose} must be a JSON object: {path}")
    return value


def require_exact_keys(value: dict, expected: set, purpose: str) -> None:
    actual = set(value)
    if actual != expected:
        raise GateBlock(
            f"venue VERIFY: {purpose} keys must be exactly {sorted(expected)}; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _validate_payload(artifact_type: str, created_by: str, payload: dict, ts: str) -> None:
    errors = validate_artifact(envelope(artifact_type, created_by, payload, ts))
    if errors:
        raise GateBlock(f"venue VERIFY: invalid {artifact_type} candidate: {errors}")


def _artifact_payload(path: Path, artifact_type: str) -> dict:
    artifact = read_json(path, artifact_type)
    errors = validate_artifact(artifact)
    if errors:
        raise GateBlock(f"venue VERIFY: frozen {artifact_type} failed schema validation: {errors}")
    if artifact.get("artifact_type") != artifact_type:
        raise GateBlock(
            f"venue VERIFY: expected {artifact_type} at {path}, found "
            f"{artifact.get('artifact_type')!r}"
        )
    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        raise GateBlock(f"venue VERIFY: frozen {artifact_type} payload is not an object")
    return payload


def review_path(run_dir: str, persona: str) -> Path:
    return Path(run_dir) / "inbox" / f"VERIFY.review.{persona}.bundle.json"


def review_ref(persona: str) -> str:
    return f"inbox/VERIFY.review.{persona}.bundle.json"


def anchor_map(config: dict) -> Dict[str, str]:
    anchors: Dict[str, str] = {}
    for row in config.get("lenses") or []:
        if isinstance(row, dict) and row.get("lens"):
            anchors[str(row["lens"])] = str(row.get("anchor") or "").strip()
    return anchors


def forbidden_review_ref(ref: str) -> bool:
    normalized = ref.replace("\\", "/").lower()
    if any(token in normalized for token in (
        "verify.profile.bundle.json",
        "verify.review-config.bundle.json",
        "verify.review.",
        "verify.reviews.receipt.json",
        "verify.meta.bundle.json",
    )):
        return True
    return any(
        f"evidence/verify/review-{persona}.artifact.json" in normalized
        for persona in PERSONAS
    )


def validate_profile_config(profile: dict, config: dict) -> None:
    declared = list(profile.get("personas") or [])
    if len(declared) != len(set(declared)):
        raise GateBlock("venue VERIFY: venue profile contains duplicate persona seats")
    if set(declared) != set(PERSONAS):
        raise GateBlock(
            "venue VERIFY: strict venue-readiness v2 requires methodology, domain, and "
            f"adversarial seats; profile declared {declared}"
        )
    anchors = anchor_map(config)
    if set(anchors) != set(declared):
        raise GateBlock(
            f"venue VERIFY: review config lenses {sorted(anchors)} do not match profile personas "
            f"{sorted(declared)}"
        )
    if any(not anchor for anchor in anchors.values()):
        raise GateBlock("venue VERIFY: every blind reviewer needs a non-empty frozen anchor")
    if len(set(anchors.values())) != len(anchors):
        raise GateBlock("venue VERIFY: reviewer anchors must be distinct, not duplicated prose")
    reviewer_agents = [str(row.get("reviewer_agent") or "") for row in config.get("lenses") or []]
    if len(reviewer_agents) != len(set(reviewer_agents)) or any(not x for x in reviewer_agents):
        raise GateBlock("venue VERIFY: each lens needs a distinct reviewer_agent instance")
    inputs = [str(x).strip() for x in config.get("inputs_to_review") or [] if str(x).strip()]
    if not inputs:
        raise GateBlock(
            "venue VERIFY: review_config.inputs_to_review is empty; reviewers need an explicit "
            "manuscript/result/code input set"
        )
    forbidden_inputs = [ref for ref in inputs if forbidden_review_ref(ref)]
    if forbidden_inputs:
        raise GateBlock(
            "venue VERIFY: review_config.inputs_to_review contains future/private panel files: "
            f"{forbidden_inputs}"
        )


def _allowed_inputs(config: dict) -> List[str]:
    return list(dict.fromkeys([
        "task_frame.artifact.json", PROFILE_REF, CONFIG_REF, PRECOMMIT_REF,
        *[str(x) for x in config.get("inputs_to_review") or []],
    ]))


def _forbidden_inputs() -> List[str]:
    return [
        "inbox/VERIFY.profile.bundle.json",
        "inbox/VERIFY.review-config.bundle.json",
        "inbox/VERIFY.review.*.bundle.json",
        "inbox/VERIFY.reviews.receipt.json",
        "inbox/VERIFY.meta.bundle.json",
        *[f"evidence/VERIFY/review-{persona}.artifact.json" for persona in PERSONAS],
    ]


def prepare_review_precommit(run_dir: str, ts: Optional[str] = None) -> dict:
    """Validate and freeze profile/config before any reviewer output exists."""
    run_path = Path(run_dir)
    receipt_path = run_path / PRECOMMIT_RECEIPT_REL
    profile_artifact = run_path / PROFILE_ARTIFACT_REL
    config_artifact = run_path / CONFIG_ARTIFACT_REL
    if receipt_path.exists():
        profile, config, receipt = load_precommit(run_dir)
        validate_profile_config(profile, config)
        return receipt

    started = [p for p in (review_path(run_dir, x) for x in PERSONAS) if p.exists()]
    if started or (run_path / META_BUNDLE_REL).exists() or (run_path / PANEL_RECEIPT_REL).exists():
        raise GateBlock(
            "venue VERIFY: reviewer/meta output exists before the venue profile/config precommit; "
            "discard the tainted review outputs and restart this review cycle"
        )
    if profile_artifact.exists() or config_artifact.exists():
        raise GateBlock(
            "venue VERIFY: partial frozen venue artifacts exist without a precommit receipt; "
            "do not silently trust or overwrite them"
        )

    profile_bundle = read_json(run_path / PROFILE_BUNDLE_REL, "venue profile candidate bundle")
    config_bundle = read_json(run_path / CONFIG_BUNDLE_REL, "review config candidate bundle")
    require_exact_keys(profile_bundle, {"venue_profile"}, "profile candidate bundle")
    require_exact_keys(config_bundle, {"review_config"}, "review config candidate bundle")
    profile = profile_bundle["venue_profile"]
    config = config_bundle["review_config"]
    if not isinstance(profile, dict) or not isinstance(config, dict):
        raise GateBlock("venue VERIFY: profile/config candidate payloads must be objects")

    frozen_at = ts or utc_now()
    _validate_payload("venue_profile", "venue-selector", profile, frozen_at)
    _validate_payload("review_config", "venue-review-configurator", config, frozen_at)
    validate_profile_config(profile, config)
    write_artifact(
        run_dir, "VERIFY", PROFILE_ARTIFACT_REL.name, "venue_profile", "venue-selector",
        profile, frozen_at,
    )
    write_artifact(
        run_dir, "VERIFY", CONFIG_ARTIFACT_REL.name, "review_config",
        "venue-review-configurator", config, frozen_at,
    )
    profile_hash = canonical_hash(profile)
    config_hash = canonical_hash(config)
    precommit_hash = canonical_hash({
        "protocol_version": PROTOCOL_VERSION,
        "profile_hash": profile_hash,
        "config_hash": config_hash,
    })
    receipt = {
        "protocol_version": PROTOCOL_VERSION,
        "frozen_at": frozen_at,
        "profile_ref": PROFILE_REF,
        "config_ref": CONFIG_REF,
        "profile_hash": profile_hash,
        "config_hash": config_hash,
        "precommit_hash": precommit_hash,
        "profile_candidate_ref": PROFILE_BUNDLE_REL.as_posix(),
        "config_candidate_ref": CONFIG_BUNDLE_REL.as_posix(),
        "personas": list(profile.get("personas") or []),
        "allowed_reviewer_inputs": _allowed_inputs(config),
        "forbidden_reviewer_inputs": _forbidden_inputs(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return receipt


def load_precommit(run_dir: str) -> Tuple[dict, dict, dict]:
    run_path = Path(run_dir)
    profile_path = run_path / PROFILE_ARTIFACT_REL
    config_path = run_path / CONFIG_ARTIFACT_REL
    receipt_path = run_path / PRECOMMIT_RECEIPT_REL
    profile = _artifact_payload(profile_path, "venue_profile")
    config = _artifact_payload(config_path, "review_config")
    receipt = read_json(receipt_path, "venue precommit receipt")
    require_exact_keys(receipt, _PRECOMMIT_KEYS, "venue precommit receipt")
    validate_profile_config(profile, config)

    profile_hash = canonical_hash(profile)
    config_hash = canonical_hash(config)
    precommit_hash = canonical_hash({
        "protocol_version": PROTOCOL_VERSION,
        "profile_hash": profile_hash,
        "config_hash": config_hash,
    })
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "profile_ref": PROFILE_REF,
        "config_ref": CONFIG_REF,
        "profile_hash": profile_hash,
        "config_hash": config_hash,
        "precommit_hash": precommit_hash,
        "profile_candidate_ref": PROFILE_BUNDLE_REL.as_posix(),
        "config_candidate_ref": CONFIG_BUNDLE_REL.as_posix(),
        "personas": list(profile.get("personas") or []),
        "allowed_reviewer_inputs": _allowed_inputs(config),
        "forbidden_reviewer_inputs": _forbidden_inputs(),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise GateBlock(
                f"venue VERIFY: frozen precommit {key} mismatch; profile/config changed after freeze"
            )
    if receipt_path.stat().st_mtime_ns < max(
        profile_path.stat().st_mtime_ns, config_path.stat().st_mtime_ns
    ):
        raise GateBlock("venue VERIFY: precommit receipt predates its frozen profile/config artifacts")

    profile_candidate = read_json(run_path / PROFILE_BUNDLE_REL, "venue profile candidate bundle")
    config_candidate = read_json(run_path / CONFIG_BUNDLE_REL, "review config candidate bundle")
    require_exact_keys(profile_candidate, {"venue_profile"}, "profile candidate bundle")
    require_exact_keys(config_candidate, {"review_config"}, "review config candidate bundle")
    if profile_candidate["venue_profile"] != profile:
        raise GateBlock("venue VERIFY: profile candidate diverged from the frozen profile")
    if config_candidate["review_config"] != config:
        raise GateBlock("venue VERIFY: config candidate diverged from the frozen review config")
    return profile, config, receipt


def load_review_bundle_strict(run_dir: str, persona: str, profile: dict, config: dict,
                              precommit: dict) -> Tuple[dict, dict, dict]:
    path = review_path(run_dir, persona)
    bundle = read_json(path, f"{persona} blind review bundle")
    require_exact_keys(
        bundle, {"venue_review", "blind_review_attestation"},
        f"{persona} blind review bundle",
    )
    review = bundle["venue_review"]
    attestation = bundle["blind_review_attestation"]
    if not isinstance(review, dict) or not isinstance(attestation, dict):
        raise GateBlock(f"venue VERIFY: {persona} review and attestation must be objects")
    _validate_payload("venue_review", "venue-reviewer-persona", review, precommit["frozen_at"])
    require_exact_keys(attestation, _ATTESTATION_KEYS, f"{persona} blind attestation")

    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "persona": persona,
        "precommit_hash": precommit["precommit_hash"],
        "profile_ref": PROFILE_REF,
        "config_ref": CONFIG_REF,
        "precommit_ref": PRECOMMIT_REF,
        "output_ref": review_ref(persona),
        "anchor_echo": anchor_map(config)[persona],
    }
    for key, value in expected.items():
        if attestation.get(key) != value:
            raise GateBlock(
                f"venue VERIFY: {persona} blind attestation {key} mismatch; reviewer did not "
                "use the frozen profile/config contract"
            )
    reviewer_id = str(attestation.get("reviewer_instance_id") or "").strip()
    if not reviewer_id:
        raise GateBlock(f"venue VERIFY: {persona} reviewer_instance_id is empty")
    if attestation.get("other_review_refs_seen") != []:
        raise GateBlock(
            f"venue VERIFY: {persona} reviewer saw another review before emitting its own: "
            f"{attestation.get('other_review_refs_seen')}"
        )
    input_refs = attestation.get("input_refs")
    if not isinstance(input_refs, list) or any(not isinstance(ref, str) for ref in input_refs):
        raise GateBlock(f"venue VERIFY: {persona} input_refs must be a string list")
    required = {"task_frame.artifact.json", PROFILE_REF, CONFIG_REF, PRECOMMIT_REF}
    if not required.issubset(set(input_refs)):
        raise GateBlock(
            f"venue VERIFY: {persona} did not attest to all frozen inputs; missing "
            f"{sorted(required - set(input_refs))}"
        )
    work_inputs = set(str(ref) for ref in config.get("inputs_to_review") or [])
    if not work_inputs.intersection(input_refs):
        raise GateBlock(
            f"venue VERIFY: {persona} attested to no manuscript/result/code input; a rubric-only "
            "review is not a scientific review"
        )
    allowed = set(precommit.get("allowed_reviewer_inputs") or [])
    outside = [ref for ref in input_refs if ref not in allowed]
    forbidden = [ref for ref in input_refs if forbidden_review_ref(ref)]
    if outside or forbidden:
        raise GateBlock(
            f"venue VERIFY: {persona} exceeded its blind read scope; outside={outside}, "
            f"forbidden={forbidden}"
        )
    if str(review.get("persona") or "") != persona:
        raise GateBlock(f"venue VERIFY: {persona} output declares persona {review.get('persona')!r}")
    if str(review.get("venue_id") or "") != str(profile.get("venue_id") or ""):
        raise GateBlock(
            f"venue VERIFY: {persona} review venue_id {review.get('venue_id')!r} does not match "
            f"frozen profile {profile.get('venue_id')!r}"
        )
    if path.stat().st_mtime_ns < (Path(run_dir) / PRECOMMIT_RECEIPT_REL).stat().st_mtime_ns:
        raise GateBlock(
            f"venue VERIFY: {persona} review predates the frozen precommit (review-before-profile)"
        )
    return review, attestation, bundle


def prepare_review_panel_receipt(run_dir: str, ts: Optional[str] = None) -> dict:
    """Validate and hash every blind review before the area chair can see the panel."""
    run_path = Path(run_dir)
    receipt_path = run_path / PANEL_RECEIPT_REL
    profile, config, precommit = load_precommit(run_dir)
    bundles: Dict[str, dict] = {}
    reviewer_ids: Dict[str, str] = {}
    for persona in PERSONAS:
        _review, attestation, bundle = load_review_bundle_strict(
            run_dir, persona, profile, config, precommit,
        )
        bundles[persona] = bundle
        reviewer_ids[persona] = str(attestation["reviewer_instance_id"])
    if len(set(reviewer_ids.values())) != len(PERSONAS):
        raise GateBlock("venue VERIFY: blind reviewer_instance_id values must be unique")

    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "precommit_hash": precommit["precommit_hash"],
        "precommit_ref": PRECOMMIT_REF,
        "profile_hash": precommit["profile_hash"],
        "review_refs": {persona: review_ref(persona) for persona in PERSONAS},
        "review_hashes": {persona: canonical_hash(bundles[persona]) for persona in PERSONAS},
        "reviewer_instance_ids": reviewer_ids,
    }
    if receipt_path.exists():
        receipt = read_json(receipt_path, "blind review panel receipt")
        require_exact_keys(receipt, _PANEL_RECEIPT_KEYS, "blind review panel receipt")
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise GateBlock(
                    f"venue VERIFY: panel receipt {key} mismatch; a blind review changed after freeze"
                )
    else:
        if (run_path / META_BUNDLE_REL).exists():
            raise GateBlock("venue VERIFY: area-chair meta bundle exists before the review panel was frozen")
        receipt = {"frozen_at": ts or utc_now(), **expected}
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    latest_review = max(review_path(run_dir, p).stat().st_mtime_ns for p in PERSONAS)
    if receipt_path.stat().st_mtime_ns < latest_review:
        raise GateBlock("venue VERIFY: panel receipt predates one or more blind reviews")
    return receipt


def _score_disagreements(reviews: Dict[str, dict]) -> Dict[str, int]:
    by_dim: Dict[str, List[int]] = {}
    for review in reviews.values():
        for dim, row in (review.get("dimension_scores") or {}).items():
            if isinstance(row, dict) and isinstance(row.get("score"), int):
                by_dim.setdefault(str(dim), []).append(row["score"])
    return {
        dim: max(scores) - min(scores)
        for dim, scores in by_dim.items()
        if len(scores) >= 2 and max(scores) != min(scores)
    }


def _validate_gap_rows(rows: object, classification: str) -> List[dict]:
    if not isinstance(rows, list):
        raise GateBlock(f"venue VERIFY: meta {classification}_gaps must be a list")
    out: List[dict] = []
    required = {"gap_id", "reason", "evidence_ref", "responsible_stage"}
    allowed = required | {"trigger_id"}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict) or not required.issubset(row) or set(row) - allowed:
            raise GateBlock(f"venue VERIFY: malformed {classification} gap at index {idx}")
        if not str(row.get("gap_id") or "").strip() or not str(row.get("reason") or "").strip():
            raise GateBlock(f"venue VERIFY: {classification} gap {idx} is empty")
        if not isinstance(row.get("evidence_ref"), list) or not row["evidence_ref"]:
            raise GateBlock(f"venue VERIFY: {classification} gap {idx} lacks evidence_ref")
        out.append(row)
    return out


def load_meta_review(run_dir: str, reviews: Dict[str, dict], panel_receipt: dict) -> dict:
    run_path = Path(run_dir)
    meta_path = run_path / META_BUNDLE_REL
    bundle = read_json(meta_path, "area-chair meta-review bundle")
    require_exact_keys(bundle, {"venue_meta_review"}, "area-chair meta-review bundle")
    meta = bundle["venue_meta_review"]
    if not isinstance(meta, dict):
        raise GateBlock("venue VERIFY: venue_meta_review must be an object")
    require_exact_keys(meta, _META_KEYS, "venue meta-review")
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "precommit_hash": panel_receipt["precommit_hash"],
        "review_receipt_ref": PANEL_RECEIPT_REF,
        "review_hashes": panel_receipt["review_hashes"],
        "human_gates": ["/venue-pick", "/venue-decide"],
        "advisory_only": True,
    }
    for key, value in expected.items():
        if meta.get(key) != value:
            raise GateBlock(f"venue VERIFY: meta-review {key} does not match the frozen panel")
    if meta_path.stat().st_mtime_ns < (run_path / PANEL_RECEIPT_REL).stat().st_mtime_ns:
        raise GateBlock("venue VERIFY: area-chair meta-review predates the completed blind panel")

    disagreements = meta.get("reviewer_disagreements")
    if not isinstance(disagreements, list):
        raise GateBlock("venue VERIFY: reviewer_disagreements must be a list")
    expected_disagreements = _score_disagreements(reviews)
    seen_dims: Dict[str, dict] = {}
    for row in disagreements:
        required = {"dimension", "personas", "score_span", "synthesis", "evidence_ref"}
        if not isinstance(row, dict) or set(row) != required:
            raise GateBlock("venue VERIFY: malformed reviewer disagreement row")
        dim = str(row.get("dimension") or "")
        if dim in seen_dims:
            raise GateBlock(f"venue VERIFY: duplicate meta disagreement row for {dim}")
        seen_dims[dim] = row
        if row.get("score_span") != expected_disagreements.get(dim):
            raise GateBlock(f"venue VERIFY: meta disagreement span is wrong for {dim}")
        if not row.get("personas") or not row.get("evidence_ref") or not str(row.get("synthesis") or ""):
            raise GateBlock(f"venue VERIFY: meta disagreement for {dim} is not decision-useful")
        scoring_personas = {
            persona for persona, review in reviews.items()
            if dim in (review.get("dimension_scores") or {})
        }
        if set(row["personas"]) != scoring_personas:
            raise GateBlock(f"venue VERIFY: meta disagreement for {dim} omits/adds reviewers")
        needed_refs = {review_ref(persona) for persona in scoring_personas}
        if not needed_refs.issubset(set(row["evidence_ref"])):
            raise GateBlock(f"venue VERIFY: meta disagreement for {dim} lacks source review refs")
    missing_dims = set(expected_disagreements) - set(seen_dims)
    if missing_dims:
        raise GateBlock(f"venue VERIFY: meta-review hides disagreements for {sorted(missing_dims)}")

    strongest = meta.get("strongest_reject_reason")
    strongest_keys = {"status", "reason", "source_personas", "evidence_ref"}
    if not isinstance(strongest, dict) or set(strongest) != strongest_keys:
        raise GateBlock("venue VERIFY: strongest_reject_reason contract is malformed")
    if strongest.get("status") not in {"fatal", "repairable", "none"}:
        raise GateBlock("venue VERIFY: strongest reject status must be fatal, repairable, or none")
    if not str(strongest.get("reason") or "").strip():
        raise GateBlock("venue VERIFY: strongest rejection case needs an explicit reason")
    source_personas = strongest.get("source_personas")
    if not isinstance(source_personas, list) or not set(source_personas).issubset(set(PERSONAS)):
        raise GateBlock("venue VERIFY: strongest rejection case names an unknown reviewer")
    strongest_refs = strongest.get("evidence_ref")
    if not isinstance(strongest_refs, list):
        raise GateBlock("venue VERIFY: strongest rejection evidence_ref must be a list")
    if strongest.get("status") != "none":
        if not source_personas:
            raise GateBlock("venue VERIFY: strongest rejection case lacks a source reviewer")
        if not {review_ref(p) for p in source_personas}.issubset(set(strongest_refs)):
            raise GateBlock("venue VERIFY: strongest rejection case lacks source review refs")

    fatal = _validate_gap_rows(meta.get("fatal_gaps"), "fatal")
    repairable = _validate_gap_rows(meta.get("repairable_gaps"), "repairable")
    gaps = fatal + repairable
    gap_ids = [str(row["gap_id"]) for row in gaps]
    if len(gap_ids) != len(set(gap_ids)):
        raise GateBlock("venue VERIFY: fatal/repairable gap ids must be unique")
    fired = {
        str(trigger.get("trigger_id"))
        for review in reviews.values()
        for trigger in (review.get("reject_triggers_fired") or [])
    }
    classified = {str(row.get("trigger_id")) for row in gaps if row.get("trigger_id")}
    if not fired.issubset(classified):
        raise GateBlock(
            f"venue VERIFY: meta-review failed to classify triggers {sorted(fired - classified)}"
        )
    if gaps and strongest.get("status") == "none":
        raise GateBlock("venue VERIFY: meta lists gaps but suppresses the strongest rejection case")

    sequence = meta.get("repair_sequence")
    if not isinstance(sequence, list):
        raise GateBlock("venue VERIFY: repair_sequence must be a list")
    priorities: List[int] = []
    sequenced_gaps = set()
    for row in sequence:
        required = {"priority", "gap_id", "action", "responsible_stage", "verification"}
        if not isinstance(row, dict) or set(row) != required:
            raise GateBlock("venue VERIFY: malformed repair_sequence row")
        if not isinstance(row.get("priority"), int) or row["priority"] < 1:
            raise GateBlock("venue VERIFY: repair priority must be a positive integer")
        priorities.append(row["priority"])
        sequenced_gaps.add(str(row.get("gap_id")))
    if priorities != sorted(set(priorities)):
        raise GateBlock("venue VERIFY: repair priorities must be unique and ascending")
    if not set(gap_ids).issubset(sequenced_gaps):
        raise GateBlock("venue VERIFY: every fatal/repairable gap needs a repair-sequence step")
    return meta
