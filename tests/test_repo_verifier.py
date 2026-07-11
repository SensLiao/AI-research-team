"""Tests for the repo-code-verifier deterministic core."""
from __future__ import annotations

from research_agent_teams.tools.repo_verifier import verify_repo
from research_agent_teams.tools.validate_artifact import validate_against

FULL_FACTS = {
    "has_code": True,
    "has_license": True,
    "has_pinned_commit": True,
    "has_weights": True,
    "pretrained_loads_grepped": True,
    "license_id": "MIT",
    "commit": "abc1234",
}


def test_full_facts_yields_verified():
    """Code + license + pinned_commit all present -> VERIFIED, no missing items."""
    payload = verify_repo("github.com/example/repo", FULL_FACTS)
    assert payload["verdict"] == "VERIFIED"
    assert payload["missing"] == []
    assert payload["repo_ref"] == "github.com/example/repo"


def test_no_code_yields_block():
    """has_code False -> BLOCK regardless of other facts, and 'code' in missing."""
    facts = {**FULL_FACTS, "has_code": False}
    payload = verify_repo("github.com/example/no-code", facts)
    assert payload["verdict"] == "BLOCK"
    assert "code" in payload["missing"]


def test_code_present_but_no_pinned_commit_yields_unverified():
    """has_code True but has_pinned_commit False -> UNVERIFIED, 'pinned_commit' in missing."""
    facts = {**FULL_FACTS, "has_pinned_commit": False, "commit": None}
    payload = verify_repo("github.com/example/no-commit", facts)
    assert payload["verdict"] == "UNVERIFIED"
    assert "pinned_commit" in payload["missing"]
    assert "code" not in payload["missing"]


def test_code_present_but_no_license_yields_unverified():
    """has_code True but has_license False -> UNVERIFIED, 'license' in missing."""
    facts = {**FULL_FACTS, "has_license": False, "license_id": None}
    payload = verify_repo("github.com/example/no-license", facts)
    assert payload["verdict"] == "UNVERIFIED"
    assert "license" in payload["missing"]


def test_weights_not_required_for_verified():
    """has_weights False should not prevent VERIFIED when code/license/commit are present."""
    facts = {**FULL_FACTS, "has_weights": False}
    payload = verify_repo("github.com/example/no-weights", facts)
    assert payload["verdict"] == "VERIFIED"
    assert "weights" not in payload["missing"]


def test_all_results_are_schema_valid():
    """Every verify_repo result must validate cleanly against repo_verification.schema.json."""
    cases = [
        ("github.com/example/full", FULL_FACTS),
        ("github.com/example/no-code", {**FULL_FACTS, "has_code": False}),
        ("github.com/example/no-commit", {**FULL_FACTS, "has_pinned_commit": False}),
        ("github.com/example/empty", {}),
    ]
    for repo_ref, facts in cases:
        payload = verify_repo(repo_ref, facts)
        errors = validate_against("repo_verification.schema.json", payload)
        assert errors == [], f"Schema errors for {repo_ref}: {errors}"


def test_empty_facts_yields_block_and_schema_valid():
    """No facts at all -> BLOCK (no code), all three missing, schema-valid."""
    payload = verify_repo("github.com/example/unknown", {})
    assert payload["verdict"] == "BLOCK"
    assert set(payload["missing"]) == {"code", "license", "pinned_commit"}
    assert validate_against("repo_verification.schema.json", payload) == []
