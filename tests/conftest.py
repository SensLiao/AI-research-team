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

from research_agent_teams.operate.modes import _shared
from research_agent_teams.tools.scholar_clients import ScholarLookupError


def _offline_transport(url, headers):  # Transport = Callable[[str, Dict[str, str]], bytes]
    raise ScholarLookupError("offline (deterministic test transport)")


@pytest.fixture(autouse=True)
def hermetic_gates(monkeypatch):
    monkeypatch.setattr(_shared, "EXISTENCE_TRANSPORT", _offline_transport)
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)
    yield
