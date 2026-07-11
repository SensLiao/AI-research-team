from __future__ import annotations

import json

import pytest

from research_agent_teams.operate.cli import main as operate_main
from research_agent_teams.tools import external_skill_review as review
from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-07-05T00:00:00Z"


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_aers_root(tmp_path):
    root = tmp_path / "AERS"
    for name in ("safe", "unknown"):
        (root / "skills" / name).mkdir(parents=True)
        (root / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    skills = [
        {
            "name": "safe-review-response",
            "path": "skills/safe/SKILL.md",
            "collection": "safe",
            "description_effective": "Review response workflow for peer review.",
            "tags": {"stage": ["peer-review"]},
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/safe",
            "source_confidence": "high",
            "quality_score": 95,
            "quality_flags": [],
            "line_count": 50,
            "has_references": True,
        },
        {
            "name": "unknown-license-paper-writing",
            "path": "skills/unknown/SKILL.md",
            "collection": "unknown",
            "description_effective": "Paper writing workflow with unknown license.",
            "tags": {"stage": ["writing"]},
            "license": "UNKNOWN - check upstream",
            "commercial_use": "unknown",
            "source_url": "https://example.test/unknown",
            "source_confidence": "medium",
            "quality_score": 80,
            "quality_flags": [],
            "line_count": 90,
            "has_references": False,
        },
        {
            "name": "missing-paper-workflow",
            "path": "skills/missing/SKILL.md",
            "collection": "safe",
            "description_effective": "Missing path must never export.",
            "tags": {"stage": ["workflow"]},
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/missing",
            "source_confidence": "high",
            "quality_score": 20,
            "quality_flags": [],
            "line_count": 40,
            "has_references": False,
        },
    ]
    _write_json(root / "catalog" / "skills-enriched.json", {"skills": skills})
    _write_json(
        root / "catalog" / "provenance.json",
        {
            "collections": [
                {
                    "id": "safe",
                    "path": "skills/safe",
                    "license": "MIT",
                    "commercial_use": "allowed",
                    "source_confidence": "high",
                    "source_url": "https://example.test/safe",
                    "security_review": "SECURITY.md",
                },
                {
                    "id": "unknown",
                    "path": "skills/unknown",
                    "license": "UNKNOWN - check upstream",
                    "commercial_use": "unknown",
                    "source_confidence": "medium",
                    "source_url": "https://example.test/unknown",
                    "security_review": "SECURITY.md",
                },
            ]
        },
    )
    _write_json(
        root / "catalog" / "skill-audit.json",
        {
            "records": [
                {
                    "path": s["path"],
                    "collection": s["collection"],
                    "exact_case": True,
                    "has_description": True,
                    "has_frontmatter": True,
                    "has_name": True,
                    "line_count": s["line_count"],
                }
                for s in skills
            ]
        },
    )
    return root


def test_stage_safe_candidate_is_pending_and_non_executable(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    assert validate_against("external_skill_review_registry.schema.json", registry) == []
    assert len(registry["entries"]) == 1
    entry = registry["entries"][0]
    assert entry["status"] == "pending_review"
    assert entry["candidate"]["recommendation"] == "safe_reference"
    assert entry["reference_allowed"] is False
    assert entry["execution_allowed"] is False
    assert entry["vault_write"] is False
    assert entry["child_skill_body_read"] is False


def test_review_required_candidate_needs_explicit_license_ack(tmp_path):
    registry = review.stage_candidates(
        query="paper writing",
        intended_use="inspect writing workflow",
        rat_stage="REPORT",
        include_review_required=True,
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    assert entry["requires_license_review"] is True
    with pytest.raises(review.ExternalSkillReviewError, match="requires explicit"):
        review.approve_reference(
            registry,
            entry["review_id"],
            reviewed_by="director",
            decision_note="approved",
            ts=TS,
        )
    review.approve_reference(
        registry,
        entry["review_id"],
        reviewed_by="director",
        decision_note="license reviewed as reference-only",
        ts=TS,
        allow_review_required=True,
    )
    assert entry["status"] == "approved_reference"
    assert entry["execution_allowed"] is False


def test_do_not_use_candidate_is_recorded_rejected_and_cannot_export(tmp_path):
    registry = review.stage_candidates(
        query="missing workflow",
        intended_use="should be blocked",
        rat_stage="REPORT",
        include_review_required=True,
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    assert entry["status"] == "rejected"
    assert entry["candidate"]["recommendation"] == "do_not_use"
    with pytest.raises(review.ExternalSkillReviewError, match="not approved"):
        review.build_run_inbox_reference(entry)


def test_approved_reference_exports_only_run_inbox_reference(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    review.approve_reference(
        registry,
        entry["review_id"],
        reviewed_by="director",
        decision_note="reference-only approved for this run",
        ts=TS,
    )
    path = review.export_run_inbox_reference(entry, tmp_path / "run-1")
    ref = json.loads((tmp_path / "run-1" / "inbox" / "external-skill-references" / f"{entry['review_id']}.json").read_text(encoding="utf-8"))
    assert str(path).endswith(f"{entry['review_id']}.json")
    assert validate_against("external_skill_reference.schema.json", ref) == []
    assert ref["constraints"]["execution_allowed"] is False
    assert ref["constraints"]["vault_write"] is False
    assert ref["constraints"]["child_skill_body_read"] is False
    assert ref["candidate"]["path"] == "skills/safe/SKILL.md"


def test_save_and_load_registry_roundtrip(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    out = tmp_path / "registry.json"
    review.save_registry(registry, out)
    assert review.load_registry(out) == registry
    summary = review.summarize_registry(registry)
    assert summary["entry_count"] == 1
    assert summary["execution_allowed"] is False
    assert summary["vault_write"] is False


def test_save_registry_rejects_default_vault_path(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    blocked = default_vault_root() / "_blocked-external-skill-review.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        review.save_registry(registry, blocked)
    assert not blocked.exists()


def test_export_run_inbox_reference_rejects_default_vault_path(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    review.approve_reference(
        registry,
        entry["review_id"],
        reviewed_by="director",
        decision_note="reference-only approved for this run",
        ts=TS,
    )
    with pytest.raises(PathBoundaryError, match="inside vault"):
        review.export_run_inbox_reference(entry, default_vault_root() / "runs" / "bad")


def test_aers_reference_gate_requires_matching_typed_confirmation(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    with pytest.raises(review.ExternalSkillReviewError, match="confirm_review_id"):
        review.apply_gate_decision(
            registry,
            entry["review_id"],
            decision="approve",
            reviewed_by="director",
            decision_note="reference-only approved",
            confirm_review_id="wrong-id",
            ts=TS,
        )
    assert entry["status"] == "pending_review"


def test_aers_reference_gate_approves_reference_only(tmp_path):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    review.apply_gate_decision(
        registry,
        entry["review_id"],
        decision="approve",
        reviewed_by="director",
        decision_note="reference-only approved",
        confirm_review_id=entry["review_id"],
        ts=TS,
    )
    assert entry["status"] == "approved_reference"
    assert entry["reference_allowed"] is True
    assert entry["execution_allowed"] is False
    assert entry["vault_write"] is False
    assert entry["child_skill_body_read"] is False


def test_operate_aers_reference_approve_cli_records_gate(tmp_path, capsys):
    registry = review.stage_candidates(
        query="review response",
        intended_use="compare reviewer-response workflow",
        rat_stage="VERIFY",
        aers_root=_fake_aers_root(tmp_path),
        ts=TS,
    )
    entry = registry["entries"][0]
    path = tmp_path / "registry.json"
    review.save_registry(registry, path)
    operate_main([
        "aers-reference-approve",
        "--registry",
        str(path),
        "--review-id",
        entry["review_id"],
        "--decision",
        "approve",
        "--reviewed-by",
        "director",
        "--decision-note",
        "reference-only approved",
        "--confirm-review-id",
        entry["review_id"],
        "--ts",
        TS,
    ])
    out = capsys.readouterr().out
    saved = review.load_registry(path)
    approved = saved["entries"][0]
    assert '"gate": "/aers-reference-approve"' in out
    assert approved["status"] == "approved_reference"
    assert approved["execution_allowed"] is False
    assert approved["vault_write"] is False
