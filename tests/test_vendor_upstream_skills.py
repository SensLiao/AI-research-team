"""The vendored upstream text must stay text: reference material that structurally cannot run.

Director decision 2026-08-04 authorised mounting the upstream skills' TEXT and nothing executable.
These tests assert that on the real tree, so the property survives the next person who adds a file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.tools import vendor_upstream_skills as vendor
from research_agent_teams.workbench import indexer

#: Anything that could be executed, auto-loaded as a plugin/skill, or auto-updated.
FORBIDDEN_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bat", ".ps1", ".rb", ".pl",
                      ".exe", ".dll", ".so", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not vendor.MANIFEST_PATH.is_file():
        pytest.skip("vendor tree not fetched on this checkout")
    return json.loads(vendor.MANIFEST_PATH.read_text(encoding="utf-8"))


def test_the_tree_verifies_against_its_own_manifest(manifest):
    result = vendor.verify()
    assert result["ok"], result["violations"]
    assert result["totals"]["files"] == manifest["totals"]["files"]


def test_nothing_in_the_tree_can_execute_or_be_auto_loaded(manifest):
    """"It cannot run" is a property of the allowlist, not a rule someone has to remember."""
    offenders = []
    for path in vendor.VENDOR_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(vendor.VENDOR_ROOT)
        if relative.as_posix() in {"MANIFEST.json", "README.md"}:
            continue          # our own provenance pair
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or not vendor.is_allowed(relative):
            offenders.append(relative.as_posix())
    assert offenders == [], offenders


def test_the_allowlist_admits_text_and_refuses_everything_else():
    for good in ("a/SKILL.md", "b/references/notes.markdown", "LICENSE", "NOTICE.txt",
                 "COPYING", "LICENCE.md"):
        assert vendor.is_allowed(Path(good)), good
    for bad in ("setup.py", "hooks/install.sh", "plugin.json", ".claude-plugin/marketplace.json",
                "mcp.yaml", "scripts/run.js", ".git/config"):
        assert not vendor.is_allowed(Path(bad)), bad


def test_the_source_excluded_on_safety_grounds_is_absent(manifest):
    """§5.3 stays in force: the CDP browser-control source is not here and is still unselectable."""
    assert "drawio_scientific_illustrator" in vendor.EXCLUDED_SOURCE_IDS
    assert not (vendor.VENDOR_ROOT / "drawio-scientific-illustrator").exists()
    assert all(s["source_id"] != "drawio_scientific_illustrator" for s in manifest["sources"])
    lock = {s["source_id"]: s for s in vendor.load_sources()["sources"]}
    assert lock["drawio_scientific_illustrator"]["selectable"] is False
    assert "drawio_scientific_illustrator" not in {s["source_id"] for s in vendor.admitted_sources()}


def test_every_vendored_source_had_all_its_audit_receipts_verified(manifest):
    """A source whose upstream bytes drifted must be BLOCKED, never quietly copied."""
    assert manifest["blocked"] == []
    lock = {s["source_id"]: s for s in vendor.load_sources()["sources"]}
    for entry in manifest["sources"]:
        expected = len(lock[entry["source_id"]]["source_artifacts"])
        assert entry["receipts_verified"] == expected, entry["source_id"]
        assert expected > 0, entry["source_id"]


def test_the_bundle_count_accounts_for_every_admitted_skill(manifest):
    lock = vendor.load_sources()
    excluded = sum(s["skill_count"] for s in lock["sources"]
                   if s["source_id"] in vendor.EXCLUDED_SOURCE_IDS)
    assert manifest["totals"]["skill_bundles"] == lock["skill_count_total"] - excluded
    assert len(manifest["sources"]) == len(vendor.admitted_sources())


def test_what_was_skipped_is_counted_rather_than_hidden(manifest):
    """No silent caps: a bounded copy has to say what it dropped."""
    assert manifest["totals"]["skipped_outside_bundles"] > 0
    for entry in manifest["sources"]:
        skipped = entry["skipped"]
        assert set(skipped) >= {"outside_skill_bundles", "bytes", "examples", "skill_bundles"}
        if skipped["outside_skill_bundles"]:
            assert skipped["examples"], entry["source_id"]


def test_every_license_file_the_lock_declares_is_actually_vendored(manifest):
    """Attribution needs the notice to travel with the text.

    One source (`agent_research_skills`) declares `license_file: null` because upstream ships no
    license at all — `NOASSERTION`, no grant either way. That is an upstream fact, disclosed in the
    vendor README and the manifest, not a missed copy; the test asserts the declared-vs-vendored
    correspondence rather than assuming every repo has a LICENSE.
    """
    lock = {s["source_id"]: s for s in vendor.load_sources()["sources"]}
    notices_missing_upstream = []
    for entry in manifest["sources"]:
        declared = lock[entry["source_id"]].get("license_file")
        vendored = [f["path"] for f in entry["files"]
                    if Path(f["path"]).name.upper().startswith(
                        ("LICENSE", "LICENCE", "NOTICE", "COPYING"))]
        if declared:
            assert declared in [f["path"] for f in entry["files"]], entry["source_id"]
        else:
            assert lock[entry["source_id"]]["license_status"] == "NOASSERTION", entry["source_id"]
            assert vendored == [], entry["source_id"]
            notices_missing_upstream.append(entry["source_id"])
        if entry["attribution_required"] and declared:
            assert vendored, entry["source_id"]
    assert notices_missing_upstream == ["agent_research_skills"], notices_missing_upstream


def test_the_manifest_records_which_safety_decisions_were_reversed(manifest):
    policy = manifest["policy"]
    assert any("§5.1" in line for line in policy["reverses"])
    assert any("§5.5" in line for line in policy["reverses"])
    assert any("§5.2" in line for line in policy["keeps"])
    assert any("§5.3" in line for line in policy["keeps"])


def test_the_source_lock_and_the_vendor_tree_tell_the_same_story(manifest):
    """The audit's self-imposed `copy_policy` says concept-only; the tree now holds text. The lock has
    to SAY so — a governance record that contradicts the tree is worse than no record."""
    vendoring = vendor.load_sources()["text_vendoring"]
    assert vendoring["vendor_root"] == "vendor/upstream-research-skills"
    assert vendoring["excluded_source_ids"] == sorted(vendor.EXCLUDED_SOURCE_IDS)
    assert vendoring["reverses_ledger_items"] == manifest["policy"]["reverses"]
    assert vendoring["keeps_ledger_items"] == manifest["policy"]["keeps"]
    assert "copy_policy still governs CODE" in vendoring["relationship_to_copy_policy"]


def test_the_vendored_text_is_not_indexed_as_the_machines_own_knowledge():
    """It would otherwise inflate the machine artifact count and put third-party prose into the
    director's search results. The indexer sweeps project workspaces and runs — never the package."""
    package_root = Path(indexer.__file__).resolve().parent.parent
    for swept in (package_root / "projects", package_root / "runs"):
        assert swept not in vendor.VENDOR_ROOT.parents
    assert vendor.VENDOR_ROOT.parent == package_root / "vendor"
