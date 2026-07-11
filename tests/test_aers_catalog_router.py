from __future__ import annotations

import json

from research_agent_teams.tools import aers_catalog_router as router
from research_agent_teams.tools.validate_artifact import validate_against


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_aers_root(tmp_path):
    root = tmp_path / "AERS"
    (root / "skills" / "safe").mkdir(parents=True)
    (root / "skills" / "safe" / "SKILL.md").write_text("---\nname: safe\n---\n", encoding="utf-8")
    (root / "skills" / "share").mkdir(parents=True)
    (root / "skills" / "share" / "SKILL.md").write_text("---\nname: share\n---\n", encoding="utf-8")

    skills = [
        {
            "name": "safe-did-skill",
            "path": "skills/safe/SKILL.md",
            "collection": "safe",
            "line_count": 120,
            "description_effective": "Difference in differences and evidence workflow.",
            "has_references": True,
            "tags": {
                "method": ["staggered-did"],
                "stage": ["analysis", "robustness"],
                "topic": ["causal-inference"],
                "language": ["python"],
            },
            "quality_score": 95,
            "quality_flags": [],
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/safe",
            "sync": "manual",
        },
        {
            "name": "share-alike-skill",
            "path": "skills/share/SKILL.md",
            "collection": "share",
            "line_count": 50,
            "description_effective": "Useful but share alike.",
            "has_references": True,
            "tags": {"stage": ["writing"]},
            "quality_score": 90,
            "quality_flags": [],
            "license": "CC-BY-SA-4.0",
            "commercial_use": "share-alike",
            "source_url": "https://example.test/share",
            "sync": "manual",
        },
        {
            "name": "missing-paper-workflow",
            "path": "skills/missing/SKILL.md",
            "collection": "missing",
            "line_count": 259,
            "description_effective": "Catalog says it exists, disk disagrees.",
            "has_references": False,
            "tags": {"stage": ["workflow"]},
            "quality_score": 70,
            "quality_flags": [],
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/missing",
            "sync": "manual",
        },
        {
            "name": "escaping-skill",
            "path": "../.env",
            "collection": "escape",
            "line_count": 1,
            "description_effective": "Bad path.",
            "has_references": False,
            "tags": {},
            "quality_score": 1,
            "quality_flags": [],
            "license": "MIT",
            "commercial_use": "allowed",
            "source_url": "https://example.test/escape",
            "sync": "manual",
        },
    ]
    collections = [
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
            "id": "share",
            "path": "skills/share",
            "license": "CC-BY-SA-4.0",
            "commercial_use": "share-alike",
            "source_confidence": "high",
            "source_url": "https://example.test/share",
            "security_review": "SECURITY.md",
        },
        {
            "id": "missing",
            "path": "skills/missing",
            "license": "MIT",
            "commercial_use": "allowed",
            "source_confidence": "high",
            "source_url": "https://example.test/missing",
            "security_review": "SECURITY.md",
        },
        {
            "id": "escape",
            "path": "skills/escape",
            "license": "MIT",
            "commercial_use": "allowed",
            "source_confidence": "high",
            "source_url": "https://example.test/escape",
            "security_review": "SECURITY.md",
        },
    ]
    audits = [
        {
            "collection": s["collection"],
            "exact_case": True,
            "has_description": True,
            "has_frontmatter": True,
            "has_name": True,
            "line_count": s["line_count"],
            "name": s["name"],
            "path": s["path"],
        }
        for s in skills
    ]
    _write_json(root / "catalog" / "skills-enriched.json", {"skills": skills})
    _write_json(root / "catalog" / "provenance.json", {"collections": collections})
    _write_json(root / "catalog" / "skill-audit.json", {"records": audits})
    return root


def test_load_candidates_is_catalog_only_and_schema_valid(tmp_path):
    root = _fake_aers_root(tmp_path)
    candidates = router.load_candidates(root)
    assert len(candidates) == 4
    safe = next(c for c in candidates if c["name"] == "safe-did-skill")
    assert safe["catalog_only"] is True
    assert safe["skill_path_exists"] is True
    assert safe["recommendation"] == "safe_reference"
    assert validate_against("aers_skill_candidate.schema.json", safe) == []


def test_default_query_returns_only_safe_references(tmp_path):
    root = _fake_aers_root(tmp_path)
    out = router.query_candidates(query="DID evidence", root=root)
    assert [c["name"] for c in out] == ["safe-did-skill"]
    assert all(c["recommendation"] == "safe_reference" for c in out)


def test_review_required_items_are_visible_only_when_requested(tmp_path):
    root = _fake_aers_root(tmp_path)
    default = router.query_candidates(query="share", root=root)
    assert default == []
    reviewed = router.query_candidates(query="share", root=root, include_review_required=True)
    assert [c["name"] for c in reviewed] == ["share-alike-skill"]
    assert reviewed[0]["recommendation"] == "review_required"
    assert any("share_or_restricted_license" in r for r in reviewed[0]["risk_reasons"])


def test_missing_and_escaping_paths_are_do_not_use(tmp_path):
    root = _fake_aers_root(tmp_path)
    candidates = {c["name"]: c for c in router.load_candidates(root)}
    assert candidates["missing-paper-workflow"]["recommendation"] == "do_not_use"
    assert "catalog_path_missing" in candidates["missing-paper-workflow"]["risk_reasons"]
    assert candidates["escaping-skill"]["recommendation"] == "do_not_use"
    assert "catalog_path_escapes_root" in candidates["escaping-skill"]["risk_reasons"]


def test_summary_never_claims_vault_write_or_child_body_read(tmp_path):
    root = _fake_aers_root(tmp_path)
    summary = router.summarize_catalog(root)
    assert summary["total_candidates"] == 4
    assert summary["catalog_only"] is True
    assert summary["vault_write"] is False
    assert summary["child_skill_bodies_read"] is False
    assert summary["by_recommendation"]["safe_reference"] == 1
    assert summary["by_recommendation"]["review_required"] == 1
    assert summary["by_recommendation"]["do_not_use"] == 2


def test_default_catalog_is_internal_metadata_snapshot():
    summary = router.summarize_catalog()
    assert router.default_aers_root().name == "aers-catalog"
    assert summary["metadata_snapshot"] is True
    assert summary["catalog_only"] is True
    assert summary["child_skill_bodies_read"] is False
    assert summary["vault_write"] is False
    assert summary["total_candidates"] == 1150
    assert summary["by_recommendation"] == {
        "review_required": 507,
        "safe_reference": 642,
        "do_not_use": 1,
    }
