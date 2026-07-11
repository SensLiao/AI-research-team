from __future__ import annotations

import json

import pytest

from research_agent_teams.tools import aers_skill_integration_planner as planner
from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.validate_artifact import validate_against


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_aers_root(tmp_path):
    root = tmp_path / "AERS"
    for name in ("lit", "review", "missing"):
        (root / "skills" / name).mkdir(parents=True)
        (root / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    skills = [
        {
            "name": "safe-literature",
            "path": "skills/lit/SKILL.md",
            "collection": "safe",
            "description_effective": "Literature search SOP.",
            "tags": {"stage": ["literature"]},
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/safe",
            "quality_score": 90,
            "quality_flags": [],
            "line_count": 40,
        },
        {
            "name": "review-required",
            "path": "skills/review/SKILL.md",
            "collection": "unknown",
            "description_effective": "Peer review SOP.",
            "tags": {"stage": ["peer-review"]},
            "license": "UNKNOWN - check upstream",
            "commercial_use": "unknown",
            "source_url": "https://example.test/unknown",
            "quality_score": 80,
            "quality_flags": [],
            "line_count": 40,
        },
        {
            "name": "missing",
            "path": "skills/not-there/SKILL.md",
            "collection": "safe",
            "description_effective": "Missing path.",
            "tags": {"stage": ["analysis"]},
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/missing",
            "quality_score": 10,
            "quality_flags": [],
            "line_count": 40,
        },
        {
            "name": "null-stage",
            "path": "skills/lit/SKILL.md",
            "collection": "safe",
            "description_effective": "Null stage tags should fall back safely.",
            "tags": {"stage": None},
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/null",
            "quality_score": 60,
            "quality_flags": [],
            "line_count": 30,
        },
    ]
    _write_json(root / "catalog" / "skills-enriched.json", {"skills": skills})
    _write_json(
        root / "catalog" / "provenance.json",
        {
            "collections": [
                {"id": "safe", "path": "skills/lit", "license": "MIT", "commercial_use": "allowed", "source_confidence": "high", "source_url": "x", "security_review": "SECURITY.md"},
                {"id": "unknown", "path": "skills/review", "license": "UNKNOWN - check upstream", "commercial_use": "unknown", "source_confidence": "medium", "source_url": "x", "security_review": "SECURITY.md"},
            ]
        },
    )
    _write_json(
        root / "catalog" / "skill-audit.json",
        {"records": [{"path": s["path"], "collection": s["collection"], "exact_case": True, "has_description": True, "has_frontmatter": True, "has_name": True, "line_count": s["line_count"]} for s in skills]},
    )
    return root


def test_aers_integration_plan_maps_all_lanes(tmp_path):
    plan = planner.build_plan(aers_root=_fake_aers_root(tmp_path))
    assert validate_against("aers_skill_integration_plan.schema.json", plan) == []
    assert plan["summary"]["total_candidates"] == 4
    assert plan["summary"]["reference_pack_candidates"] == 2
    assert plan["summary"]["human_gate_required"] == 1
    assert plan["summary"]["blocked"] == 1
    rows = {row["name"]: row for row in plan["rows"]}
    assert rows["safe-literature"]["target_stage"] == "DISCOVER"
    assert rows["safe-literature"]["integration_lane"] == "reference_pack"
    assert rows["review-required"]["integration_lane"] == "human_gate_required"
    assert rows["missing"]["integration_lane"] == "blocked"
    assert rows["null-stage"]["target_stage"] == "REPORT"
    assert plan["summary"]["external_skill_execution"] is False
    assert plan["summary"]["child_skill_bodies_read"] is False


def test_aers_integration_plan_cli_rejects_vault_out(tmp_path):
    blocked = default_vault_root() / "_blocked-aers-integration-plan.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        planner.main([
            "--aers-root",
            str(_fake_aers_root(tmp_path)),
            "--out",
            str(blocked),
        ])
    assert not blocked.exists()
