from __future__ import annotations

import json

import pytest

from research_agent_teams.tools.capability_catalog import build_capability_catalog
from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.rat_eval_harness import build_scorecard, main
from research_agent_teams.tools.validate_artifact import validate_against


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _fake_aers_root(tmp_path):
    root = tmp_path / "AERS"
    (root / "skills" / "safe").mkdir(parents=True)
    (root / "skills" / "safe" / "SKILL.md").write_text("---\nname: safe\n---\n", encoding="utf-8")
    skills = [
        {
            "name": "safe-skill",
            "path": "skills/safe/SKILL.md",
            "collection": "safe",
            "description_effective": "Safe metadata-only skill.",
            "tags": {"stage": ["writing"]},
            "license": "MIT",
            "commercial_use": "allowed",
            "quality_score": 95,
            "quality_flags": [],
            "line_count": 50,
            "has_references": True,
        },
        {
            "name": "missing-skill",
            "path": "skills/missing/SKILL.md",
            "collection": "safe",
            "description_effective": "Missing path must be blocked.",
            "tags": {},
            "license": "MIT",
            "commercial_use": "allowed",
            "quality_score": 10,
            "quality_flags": [],
            "line_count": 20,
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
                }
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


def test_rat_eval_scorecard_schema_and_machine_checks_pass(tmp_path):
    scorecard = build_scorecard(aers_root=_fake_aers_root(tmp_path), include_manual=True)
    assert validate_against("rat_eval_scorecard.schema.json", scorecard) == []
    assert scorecard["summary"]["required_machine_failures"] == 0
    assert scorecard["summary"]["fail"] == 0
    assert scorecard["summary"]["needs_manual"] == 1
    assert scorecard["summary"]["manual_open"] == 1


def test_manual_items_never_auto_pass(tmp_path):
    scorecard = build_scorecard(aers_root=_fake_aers_root(tmp_path), include_manual=True)
    manual_scenario = next(s for s in scorecard["scenarios"] if s["id"] == "rat-final-compatibility-manual-gate")
    assert manual_scenario["status"] == "needs_manual"
    assert manual_scenario["checks"][0]["kind"] == "manual"
    assert manual_scenario["checks"][0]["passed"] is None


def test_research_product_quality_is_a_first_class_eval_scenario(tmp_path):
    scorecard = build_scorecard(aers_root=_fake_aers_root(tmp_path), include_manual=False)
    scenario = next(s for s in scorecard["scenarios"] if s["id"] == "rat-research-product-quality")
    assert scenario["category"] == "research-output-quality"
    assert scenario["status"] == "pass"
    assert scenario["checks"][0]["id"] == "every-operated-mode-has-director-markdown-contract"
    assert scenario["checks"][0]["passed"] is True


def test_tampered_vault_write_fails_required_machine_check(tmp_path):
    catalog = build_capability_catalog()
    catalog["summary"]["vault_write"] = True
    scorecard = build_scorecard(
        capability_catalog=catalog,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scorecard["summary"]["required_machine_failures"] == 1
    boundary = next(s for s in scorecard["scenarios"] if s["id"] == "rat-vault-and-aers-boundary")
    assert boundary["status"] == "fail"


def test_tampered_spec_only_intent_membership_fails(tmp_path):
    catalog = build_capability_catalog()
    # exemplar swapped 2026-08-04: design_experiment is operated now, and this check is
    # about a SPEC-ONLY mode being smuggled into a default tier.
    mode = next(row for row in catalog["modes"] if row["mode"] == "tree_explore")
    mode["intents"] = [{"intent": "fake_default", "tier": "core"}]
    scorecard = build_scorecard(
        capability_catalog=catalog,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scorecard["summary"]["required_machine_failures"] == 1
    surface = next(s for s in scorecard["scenarios"] if s["id"] == "rat-capability-surface-honesty")
    assert surface["status"] == "fail"


def test_rat_eval_cli_rejects_default_vault_out():
    blocked = default_vault_root() / "_blocked-rat-eval-scorecard.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        main(["--out", str(blocked), "--no-manual"])
    assert not blocked.exists()
