"""Review registry for external AERS skill references.

External skills are not RAT capabilities. This module records AERS catalog
candidates as review items and exports only reviewed references into a run inbox.
It never reads child skill bodies, executes external hooks, or writes the vault.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

from research_agent_teams.tools import aers_catalog_router
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.validate_artifact import validate_against

REGISTRY_SCHEMA = "external_skill_review_registry.schema.json"
REFERENCE_SCHEMA = "external_skill_reference.schema.json"
DEFAULT_REVIEWER = "codex-system"


class ExternalSkillReviewError(ValueError):
    """Raised when an external skill review operation would cross a boundary."""


def empty_registry() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "registry": "external_skill_review",
        "source": "Auto-Empirical-Research-Skills",
        "entries": [],
    }


def _validate(schema: str, payload: dict[str, Any]) -> None:
    errors = validate_against(schema, payload)
    if errors:
        raise ExternalSkillReviewError(f"{schema} validation failed: {errors}")


def load_registry(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return empty_registry()
    data = json.loads(p.read_text(encoding="utf-8"))
    _validate(REGISTRY_SCHEMA, data)
    return data


def save_registry(registry: dict[str, Any], path: str | Path) -> str:
    _validate(REGISTRY_SCHEMA, registry)
    p = assert_not_vault_path(path, purpose="write external skill review registry")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(p)


def _review_id(candidate: dict[str, Any]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "")
        for key in ("collection", "path", "source_url", "license")
    )
    return "aers-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _candidate_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(candidate.get("name") or ""),
        "path": str(candidate.get("path") or ""),
        "collection": str(candidate.get("collection") or ""),
        "license": str(candidate.get("license") or ""),
        "commercial_use": str(candidate.get("commercial_use") or ""),
        "source_url": str(candidate.get("source_url") or ""),
        "source_confidence": str(candidate.get("source_confidence") or ""),
        "recommendation": str(candidate.get("recommendation") or ""),
        "risk_level": str(candidate.get("risk_level") or ""),
        "risk_reasons": list(candidate.get("risk_reasons") or []),
        "skill_path_exists": bool(candidate.get("skill_path_exists")),
        "catalog_only": bool(candidate.get("catalog_only")),
    }


def entry_from_candidate(
    candidate: dict[str, Any],
    *,
    intended_use: str,
    rat_stage: Optional[str],
    requested_by: str = DEFAULT_REVIEWER,
    ts: str = "",
) -> dict[str, Any]:
    snapshot = _candidate_snapshot(candidate)
    recommendation = snapshot["recommendation"]
    if recommendation == "do_not_use":
        status = "rejected"
        decision_note = "candidate is blocked by AERS catalog risk checks"
    else:
        status = "pending_review"
        decision_note = ""
    return {
        "review_id": _review_id(snapshot),
        "status": status,
        "candidate": snapshot,
        "intended_use": intended_use,
        "rat_stage": rat_stage,
        "requested_by": requested_by,
        "requested_at": ts,
        "reviewed_by": None,
        "reviewed_at": None,
        "decision_note": decision_note,
        "requires_license_review": recommendation == "review_required",
        "reference_allowed": False,
        "execution_allowed": False,
        "vault_write": False,
        "child_skill_body_read": False,
        "run_inbox_only": True,
    }


def upsert_entry(registry: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    _validate(REGISTRY_SCHEMA, {**registry, "entries": [entry]})
    entries = list(registry.get("entries") or [])
    for idx, existing in enumerate(entries):
        if existing.get("review_id") == entry["review_id"]:
            entries[idx] = entry
            break
    else:
        entries.append(entry)
    registry["entries"] = sorted(entries, key=lambda row: row["review_id"])
    _validate(REGISTRY_SCHEMA, registry)
    return registry


def stage_candidates(
    *,
    query: str,
    intended_use: str,
    rat_stage: Optional[str] = None,
    include_review_required: bool = False,
    aers_root: Optional[str | Path] = None,
    registry: Optional[dict[str, Any]] = None,
    limit: int = 10,
    requested_by: str = DEFAULT_REVIEWER,
    ts: str = "",
) -> dict[str, Any]:
    out = registry if registry is not None else empty_registry()
    candidates = aers_catalog_router.query_candidates(
        query=query,
        rat_stage=rat_stage,
        include_review_required=include_review_required,
        root=aers_root,
        limit=limit,
    )
    for candidate in candidates:
        entry = entry_from_candidate(
            candidate,
            intended_use=intended_use,
            rat_stage=rat_stage,
            requested_by=requested_by,
            ts=ts,
        )
        upsert_entry(out, entry)
    return out


def _find_entry(registry: dict[str, Any], review_id: str) -> dict[str, Any]:
    for entry in registry.get("entries") or []:
        if entry.get("review_id") == review_id:
            return entry
    raise ExternalSkillReviewError(f"review id not found: {review_id}")


def approve_reference(
    registry: dict[str, Any],
    review_id: str,
    *,
    reviewed_by: str,
    decision_note: str,
    ts: str = "",
    allow_review_required: bool = False,
) -> dict[str, Any]:
    entry = _find_entry(registry, review_id)
    if entry["status"] == "rejected":
        raise ExternalSkillReviewError(f"{review_id} is rejected and cannot be approved")
    if entry["candidate"]["recommendation"] == "do_not_use":
        raise ExternalSkillReviewError(f"{review_id} is do_not_use and cannot be approved")
    if entry["requires_license_review"] and not allow_review_required:
        raise ExternalSkillReviewError(f"{review_id} requires explicit license/security review")
    entry["status"] = "approved_reference"
    entry["reviewed_by"] = reviewed_by
    entry["reviewed_at"] = ts
    entry["decision_note"] = decision_note
    entry["reference_allowed"] = True
    entry["execution_allowed"] = False
    entry["vault_write"] = False
    entry["child_skill_body_read"] = False
    _validate(REGISTRY_SCHEMA, registry)
    return entry


def reject_reference(
    registry: dict[str, Any],
    review_id: str,
    *,
    reviewed_by: str,
    decision_note: str,
    ts: str = "",
) -> dict[str, Any]:
    entry = _find_entry(registry, review_id)
    entry["status"] = "rejected"
    entry["reviewed_by"] = reviewed_by
    entry["reviewed_at"] = ts
    entry["decision_note"] = decision_note
    entry["reference_allowed"] = False
    entry["execution_allowed"] = False
    entry["vault_write"] = False
    entry["child_skill_body_read"] = False
    _validate(REGISTRY_SCHEMA, registry)
    return entry


def apply_gate_decision(
    registry: dict[str, Any],
    review_id: str,
    *,
    decision: str,
    reviewed_by: str,
    decision_note: str,
    confirm_review_id: str,
    ts: str = "",
    allow_review_required: bool = False,
) -> dict[str, Any]:
    """Apply the human `/aers-reference-approve` gate decision.

    This gate can only approve reference use. It never permits execution,
    vault writes, or child skill body reads. The typed confirmation prevents
    accidental approval of a different candidate.
    """
    if confirm_review_id != review_id:
        raise ExternalSkillReviewError("confirm_review_id must exactly equal review_id")
    if decision == "approve":
        return approve_reference(
            registry,
            review_id,
            reviewed_by=reviewed_by,
            decision_note=decision_note,
            ts=ts,
            allow_review_required=allow_review_required,
        )
    if decision == "reject":
        return reject_reference(
            registry,
            review_id,
            reviewed_by=reviewed_by,
            decision_note=decision_note,
            ts=ts,
        )
    raise ExternalSkillReviewError(f"unknown gate decision: {decision}")


def build_run_inbox_reference(entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("status") != "approved_reference" or not entry.get("reference_allowed"):
        raise ExternalSkillReviewError(f"{entry.get('review_id')} is not approved for run inbox reference")
    ref = {
        "schema_version": "1.0.0",
        "reference_type": "aers_skill_reference",
        "review_id": entry["review_id"],
        "source": "Auto-Empirical-Research-Skills",
        "candidate": entry["candidate"],
        "intended_use": entry["intended_use"],
        "rat_stage": entry["rat_stage"],
        "constraints": {
            "catalog_only": True,
            "child_skill_body_read": False,
            "execution_allowed": False,
            "vault_write": False,
            "run_inbox_only": True,
        },
    }
    _validate(REFERENCE_SCHEMA, ref)
    return ref


def export_run_inbox_reference(entry: dict[str, Any], run_dir: str | Path) -> str:
    ref = build_run_inbox_reference(entry)
    run_root = assert_not_vault_path(run_dir, purpose="export external skill reference")
    out_dir = run_root / "inbox" / "external-skill-references"
    out_path = assert_not_vault_path(
        out_dir / f"{entry['review_id']}.json",
        purpose="export external skill reference",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out_path)


def summarize_registry(registry: dict[str, Any]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_recommendation: dict[str, int] = {}
    for entry in registry.get("entries") or []:
        status = entry["status"]
        rec = entry["candidate"]["recommendation"]
        by_status[status] = by_status.get(status, 0) + 1
        by_recommendation[rec] = by_recommendation.get(rec, 0) + 1
    return {
        "entry_count": len(registry.get("entries") or []),
        "by_status": by_status,
        "by_recommendation": by_recommendation,
        "execution_allowed": False,
        "vault_write": False,
        "child_skill_body_read": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Stage/review AERS catalog candidates.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    stage = sub.add_parser("stage", help="stage AERS catalog candidates into a review registry")
    stage.add_argument("--query", required=True)
    stage.add_argument("--intended-use", required=True)
    stage.add_argument("--rat-stage")
    stage.add_argument("--include-review-required", action="store_true")
    stage.add_argument("--aers-root")
    stage.add_argument("--registry")
    stage.add_argument("--out", required=True)
    stage.add_argument("--limit", type=int, default=10)
    stage.add_argument("--requested-by", default=DEFAULT_REVIEWER)
    stage.add_argument("--ts", default="")

    gate = sub.add_parser("gate", help="apply the human /aers-reference-approve decision")
    gate.add_argument("--registry", required=True)
    gate.add_argument("--out", required=True)
    gate.add_argument("--review-id", required=True)
    gate.add_argument("--decision", required=True, choices=["approve", "reject"])
    gate.add_argument("--reviewed-by", required=True)
    gate.add_argument("--decision-note", required=True)
    gate.add_argument("--confirm-review-id", required=True)
    gate.add_argument("--allow-review-required", action="store_true")
    gate.add_argument("--export-run-dir")
    gate.add_argument("--ts", default="")

    raw = list(argv) if argv is not None else sys.argv[1:]
    if raw and raw[0] not in {"stage", "gate"}:
        raw = ["stage", *raw]
    args = parser.parse_args(raw)

    if args.cmd == "gate":
        registry = load_registry(args.registry)
        entry = apply_gate_decision(
            registry,
            args.review_id,
            decision=args.decision,
            reviewed_by=args.reviewed_by,
            decision_note=args.decision_note,
            confirm_review_id=args.confirm_review_id,
            ts=args.ts,
            allow_review_required=args.allow_review_required,
        )
        exported = None
        if args.export_run_dir and entry.get("reference_allowed"):
            exported = export_run_inbox_reference(entry, args.export_run_dir)
        save_registry(registry, args.out)
        print(json.dumps({
            **summarize_registry(registry),
            "decision": args.decision,
            "review_id": args.review_id,
            "exported_reference": exported,
        }, ensure_ascii=False, indent=2))
        return 0

    registry = load_registry(args.registry) if args.registry else empty_registry()
    registry = stage_candidates(
        query=args.query,
        intended_use=args.intended_use,
        rat_stage=args.rat_stage,
        include_review_required=args.include_review_required,
        aers_root=args.aers_root,
        registry=registry,
        limit=args.limit,
        requested_by=args.requested_by,
        ts=args.ts,
    )
    save_registry(registry, args.out)
    print(json.dumps(summarize_registry(registry), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ExternalSkillReviewError",
    "apply_gate_decision",
    "approve_reference",
    "build_run_inbox_reference",
    "empty_registry",
    "entry_from_candidate",
    "export_run_inbox_reference",
    "load_registry",
    "reject_reference",
    "save_registry",
    "stage_candidates",
    "summarize_registry",
    "upsert_entry",
]
