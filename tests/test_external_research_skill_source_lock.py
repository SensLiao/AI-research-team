from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from research_agent_teams.tools import research_capability_router as router


EXPECTED_SKILL_COUNTS = {
    "orchestra_research_skills": 98,
    "claude_scholar": 45,
    "academic_research_skills": 4,
    "agent_research_skills": 31,
    "scientific_agent_skills": 158,
    "scipilot_figure_skill": 1,
    "drawio_skills": 2,
    "drawio_scientific_illustrator": 1,
    "nature_skills": 19,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head_without_git(repo: Path) -> str:
    git_dir = repo / ".git"
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref = head.removeprefix("ref: ")
    loose_ref = git_dir / Path(*ref.split("/"))
    if loose_ref.is_file():
        return loose_ref.read_text(encoding="utf-8").strip()
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        suffix = f" {ref}"
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            if line.endswith(suffix):
                return line.split(" ", 1)[0]
    raise AssertionError(f"cannot resolve {ref} without invoking git: {repo}")


def test_source_lock_is_complete_and_catalog_is_an_exact_projection() -> None:
    source_lock = router.load_external_source_lock()
    catalog = router.load_overlay_catalog()

    assert source_lock["source_count"] == 9
    assert source_lock["skill_count_total"] == 359
    by_id = {source["source_id"]: source for source in source_lock["sources"]}
    assert {source_id: source["skill_count"] for source_id, source in by_id.items()} == (
        EXPECTED_SKILL_COUNTS
    )
    assert catalog["sources"] == source_lock["sources"]

    rejected = by_id["drawio_scientific_illustrator"]
    assert rejected["selectable"] is False
    assert rejected["implementation_status"] == "rejected"

    selectable = {source_id for source_id, source in by_id.items() if source["selectable"]}
    referenced = {
        source_id
        for overlay in catalog["overlays"]
        for source_id in overlay["provenance_refs"]
    }
    assert referenced == selectable
    assert "drawio_scientific_illustrator" not in referenced

    scientific_paths = {
        artifact["path"] for artifact in by_id["scientific_agent_skills"]["source_artifacts"]
    }
    assert "skills/hypothesis-generation/scripts/validate_hypothesis_schema.py" in scientific_paths
    assert "skills/hypothesis-generation/scripts/validate_prediction_matrix.py" in scientific_paths
    assert "scripts/validate_hypothesis_schema.py" not in scientific_paths
    assert "scripts/validate_prediction_matrix.py" not in scientific_paths


def test_materialized_snapshot_matches_locked_commits_counts_and_hashes() -> None:
    source_lock = router.load_external_source_lock()
    review_root = Path(
        os.environ.get("RAT_EXTERNAL_RESEARCH_SKILLS_REVIEW_ROOT", source_lock["review_root"])
    )
    if not review_root.is_dir():
        pytest.skip(f"out-of-repository review snapshot is not present: {review_root}")

    observed_total = 0
    for source in source_lock["sources"]:
        repo = review_root / source["snapshot_dir"]
        assert repo.is_dir(), source["source_id"]
        assert _head_without_git(repo) == source["commit"]
        skill_count = sum(1 for _ in repo.rglob("SKILL.md"))
        assert skill_count == source["skill_count"], source["source_id"]
        observed_total += skill_count
        for artifact in source["source_artifacts"]:
            source_file = repo.joinpath(*artifact["path"].split("/"))
            assert source_file.is_file(), f"{source['source_id']}:{artifact['path']}"
            assert _sha256(source_file) == artifact["sha256"]
    assert observed_total == 359


def test_overlay_cannot_reference_rejected_source(tmp_path: Path) -> None:
    catalog = deepcopy(router.load_overlay_catalog())
    catalog["overlays"][0]["provenance_refs"].append("drawio_scientific_illustrator")
    candidate = tmp_path / "rejected-source-overlay.json"
    candidate.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(router.ResearchCapabilityRouterError, match="non-selectable"):
        router.load_overlay_catalog(candidate)


def test_selected_provenance_carries_file_license_and_implementation_lock() -> None:
    route = router.route_research_capabilities(
        "Review the manuscript figures and claims.",
        publication_kind="manuscript_review",
    )
    required = {
        "source_id",
        "repository",
        "commit",
        "snapshot_dir",
        "skill_count",
        "license_status",
        "license_spdx",
        "license_file",
        "copy_policy",
        "commercial_use_policy",
        "attribution_required",
        "admission",
        "selectable",
        "implementation_status",
        "source_artifacts",
    }
    for overlay in route["capability_overlays"]:
        for source in overlay["provenance"]:
            assert set(source) == required
            assert source["selectable"] is True
            assert source["implementation_status"] != "rejected"
            assert source["source_artifacts"]
            assert all(len(artifact["sha256"]) == 64 for artifact in source["source_artifacts"])
