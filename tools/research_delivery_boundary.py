"""Deterministic delivery boundary for a deep-research dossier.

Content convergence is intentionally narrower than scientific clearance.  This
module derives the handoff-facing boundary from already validated artifacts; it
never asks the convergence chair to decide citation validity or novelty.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, Mapping, Optional


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PASS = "PASS"


def _require_hash(value: object, label: str) -> str:
    text = str(value or "")
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{label} must be sha256:<64 lowercase hex>")
    return text


def _review_blockers(source_reviews: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], dict]:
    indexed: dict[tuple[str, str], dict] = {}
    for review in source_reviews:
        review_id = str(review.get("review_id") or "")
        if not review_id:
            raise ValueError("source review is missing review_id")
        for raw in review.get("external_blockers") or []:
            blocker = dict(raw)
            blocker_id = str(blocker.get("blocker_id") or "")
            key = (review_id, blocker_id)
            if not blocker_id:
                raise ValueError(f"source review {review_id} has a blocker without blocker_id")
            if key in indexed:
                raise ValueError(f"duplicate source blocker {review_id}:{blocker_id}")
            indexed[key] = blocker
    return indexed


def _preserved_external_blockers(
    convergence_verdict: Mapping[str, object],
    source_reviews: Iterable[Mapping[str, object]],
) -> list[dict]:
    """Return original reviewer blocker fields after checking chair fidelity.

    The chair may consolidate identical blockers, but it cannot change their
    ``kind`` or ``required_input``.  Delivery deliberately renders the source
    description as well, so a chair summary can never erase the original need.
    """
    source = _review_blockers(source_reviews)
    seen: list[tuple[str, str]] = []
    output: list[dict] = []
    chair_ids: set[str] = set()
    for raw_chair in convergence_verdict.get("external_blockers") or []:
        chair = dict(raw_chair)
        chair_id = str(chair.get("blocker_id") or "")
        if not chair_id or chair_id in chair_ids:
            raise ValueError("convergence chair has a missing or duplicate blocker_id")
        chair_ids.add(chair_id)
        refs = [
            (str(ref.get("review_id") or ""), str(ref.get("blocker_id") or ""))
            for ref in chair.get("source_blockers") or []
        ]
        if not refs:
            raise ValueError(f"chair blocker {chair_id} has no source_blockers")
        for key in refs:
            if key not in source:
                raise ValueError(f"chair blocker {chair_id} references unknown source blocker {key}")
            original = source[key]
            if chair.get("kind") != original.get("kind"):
                raise ValueError(
                    f"chair blocker {chair_id} changed kind for {key[0]}:{key[1]}"
                )
            if chair.get("required_input") != original.get("required_input"):
                raise ValueError(
                    f"chair blocker {chair_id} changed required_input for {key[0]}:{key[1]}"
                )
            seen.append(key)
            output.append({
                "blocker_id": key[1],
                "source_review_id": key[0],
                "chair_blocker_id": chair_id,
                "kind": str(original.get("kind") or "OTHER"),
                "description": str(original.get("description") or ""),
                "required_input": str(original.get("required_input") or ""),
                "evidence_refs": [str(ref) for ref in original.get("evidence_refs") or []],
            })
    if sorted(seen) != sorted(source):
        raise ValueError("convergence chair must preserve every source external blocker exactly once")
    return output


def _novelty_binding_passes(
    gate: Optional[Mapping[str, object]],
    *,
    gate_artifact_ref: Optional[str],
    gate_artifact_sha256: Optional[str],
    reviewed_artifact_ref: str,
    reviewed_artifact_sha256: str,
) -> bool:
    if not gate or gate.get("gate") != _PASS:
        return False
    if gate.get("independent_of_author") is not True:
        return False
    if gate.get("reviewed_artifact_ref") != reviewed_artifact_ref:
        return False
    if gate.get("reviewed_artifact_sha256") != reviewed_artifact_sha256:
        return False
    return bool(
        gate_artifact_ref
        and _SHA256.fullmatch(str(gate_artifact_sha256 or ""))
    )


def derive_research_delivery_boundary(
    *,
    reviewed_artifact_ref: str,
    reviewed_artifact_sha256: str,
    convergence_artifact_ref: str,
    convergence_artifact_sha256: str,
    convergence_verdict: Mapping[str, object],
    source_reviews: Iterable[Mapping[str, object]],
    evidence_gate: object,
    citation_gate: object,
    citation_attribution_gate: object,
    existence_gate: object,
    novelty_gate: Optional[Mapping[str, object]] = None,
    novelty_gate_artifact_ref: Optional[str] = None,
    novelty_gate_artifact_sha256: Optional[str] = None,
) -> dict:
    """Build the machine-derived boundary used by Markdown and run handoffs.

    ``novelty_gate`` is deliberately strict: a PASS counts only when an
    independent gate binds the exact reviewed artifact and the gate artifact is
    itself hash-addressed.  Current deep-research runs have no such independent
    gate, so their honest novelty status is ``UNVERIFIED``.
    """
    reviewed_hash = _require_hash(reviewed_artifact_sha256, "reviewed_artifact_sha256")
    convergence_hash = _require_hash(convergence_artifact_sha256, "convergence_artifact_sha256")
    if (
        convergence_verdict.get("reviewed_artifact_ref") != reviewed_artifact_ref
        or convergence_verdict.get("reviewed_artifact_sha256") != reviewed_hash
    ):
        raise ValueError(
            "delivery boundary reviewed artifact must exactly match the convergence chair binding"
        )
    blockers = _preserved_external_blockers(convergence_verdict, source_reviews)
    scientific_gates = {
        "evidence": str(evidence_gate or "UNVERIFIED"),
        "citation": str(citation_gate or "UNVERIFIED"),
        "citation_attribution": str(citation_attribution_gate or "UNVERIFIED"),
        "existence": str(existence_gate or "UNVERIFIED"),
    }
    reasons: list[str] = []
    gate_bound = _novelty_binding_passes(
        novelty_gate,
        gate_artifact_ref=novelty_gate_artifact_ref,
        gate_artifact_sha256=novelty_gate_artifact_sha256,
        reviewed_artifact_ref=reviewed_artifact_ref,
        reviewed_artifact_sha256=reviewed_hash,
    )
    if not gate_bound:
        reasons.append("NO_INDEPENDENT_HASH_BOUND_NOVELTY_GATE_PASS")
    for name, value in scientific_gates.items():
        if value != _PASS:
            reasons.append(f"{name.upper()}_GATE_NOT_PASS")
    if blockers:
        reasons.append("UNRESOLVED_EXTERNAL_BLOCKERS")

    novelty_status = "VERIFIED_PASS" if gate_bound and not reasons else "UNVERIFIED"
    disposition = str(convergence_verdict.get("disposition") or "NOT_REVIEWED")
    delivery_caveats = bool(
        blockers
        or any(value != _PASS for value in scientific_gates.values())
        or disposition != "CONTENT_CONVERGED"
    )
    identity_input = {
        "reviewed_artifact_ref": reviewed_artifact_ref,
        "reviewed_artifact_sha256": reviewed_hash,
        "convergence_artifact_ref": convergence_artifact_ref,
        "convergence_artifact_sha256": convergence_hash,
        "scientific_gates": scientific_gates,
        "novelty_status": novelty_status,
        "external_blockers": blockers,
    }
    digest = hashlib.sha256(
        json.dumps(identity_input, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "contract_version": "research-delivery-boundary/v1",
        "delivery_id": f"research-delivery-{digest[:20]}",
        "reviewed_artifact_ref": reviewed_artifact_ref,
        "reviewed_artifact_sha256": reviewed_hash,
        "convergence_artifact_ref": convergence_artifact_ref,
        "convergence_artifact_sha256": convergence_hash,
        "content_convergence": disposition,
        "scientific_gates": scientific_gates,
        "novelty": {
            "status": novelty_status,
            "independent_hash_bound_gate_pass": gate_bound,
            "gate_artifact_ref": str(novelty_gate_artifact_ref) if gate_bound else None,
            "gate_artifact_sha256": str(novelty_gate_artifact_sha256) if gate_bound else None,
            "reasons": reasons,
        },
        "external_blockers": blockers,
        "delivery_status": "USABLE_WITH_CAVEATS" if delivery_caveats else "USABLE",
        "claim_boundaries": {
            "content_convergence_only": True,
            "novelty_claim_allowed": novelty_status == "VERIFIED_PASS",
            "project_approval": False,
        },
        "rationale": (
            "Delivery status is machine-derived from content convergence, scientific gates, "
            "source-preserved external blockers, and an optional independent hash-bound novelty gate."
        ),
    }
