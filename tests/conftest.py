"""Shared test fixtures — hermetic defaults for the network/vault-facing gates.

Every test runs with:
  - the citation-existence gate OFFLINE (lookups raise ScholarLookupError -> lookup_error
    WARNINGS, the offline-safe PASS state) — no test ever depends on real network answers;
  - the vault-slug / negative-result checks seeing NO vault (slug checks degrade to warnings) —
    no test ever reads the real knowledge vault by accident.

A test that wants the real behaviour overrides the module attributes itself (e.g. point
``_shared.VAULT_ROOT_OVERRIDE`` at a tmp_path fixture vault, or install a fake transport).
"""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.operate.modes import _shared
from research_agent_teams.tools.scholar_clients import ScholarLookupError


def _offline_transport(url, headers):  # Transport = Callable[[str, Dict[str, str]], bytes]
    raise ScholarLookupError("offline (deterministic test transport)")


@pytest.fixture(autouse=True)
def hermetic_gates(monkeypatch):
    monkeypatch.setattr(_shared, "EXISTENCE_TRANSPORT", _offline_transport)
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)
    yield


@pytest.fixture()
def resource_projects_root(tmp_path, monkeypatch):
    """Provide hermetic resource bindings without publishing a private project workspace."""
    projects_root = tmp_path / "projects"
    binding_path = projects_root / "iac-cbct-seg" / "resource_bindings.yaml"
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project": "iac-cbct-seg",
                "bindings": [
                    {
                        "alias": "paper_api",
                        "resource_ref": "api.semantic_scholar",
                        "allowed_capabilities": ["paper_search", "citation_existence"],
                        "allowed_stages": ["DISCOVER", "VERIFY"],
                    },
                    {
                        "alias": "primary_gpu",
                        "resource_ref": "server.honor.gpu",
                        "allowed_capabilities": ["query_status", "pull_logs"],
                        "allowed_stages": ["EXECUTE", "ANALYZE", "VERIFY"],
                        "allowed_skills": ["server-query"],
                        "requires_human_approval": True,
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAT_PROJECTS_ROOT", str(projects_root))
    return projects_root
