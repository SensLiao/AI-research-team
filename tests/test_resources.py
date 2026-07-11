"""Resource plane tests — pool loader, default-deny policy, per-project bindings, and the hard rule
that the registry stores secret REFERENCES (env-var names) only, never values."""
from __future__ import annotations

import pytest

from research_agent_teams.tools import resources as rp


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


REG = """
schema_version: 1
resources:
  - resource_id: api.x
    type: api_key
    secret_refs: {api_key: RAT_X_KEY}
    capabilities: [search]
  - resource_id: srv.y
    type: hardware.ssh_server
    endpoint_ref: RAT_Y_HOST
    secret_refs: {host: RAT_Y_HOST, password: RAT_Y_PASS}
    capabilities: [query_status, submit_job]
"""

POLICY = """
schema_version: 1
default: {access: deny, reason: "no implicit access"}
rules:
  - resource_ref: api.x
    project: "*"
    allowed_capabilities: [search]
    max_lease_duration_seconds: 60
    requires_human_approval: false
  - resource_ref: srv.y
    project: proj-a
    allowed_capabilities: [query_status]
    requires_human_approval: true
"""

BIND = """
schema_version: 1
project: proj-a
bindings:
  - alias: x
    resource_ref: api.x
    allowed_capabilities: [search]
    allowed_stages: [DISCOVER]
  - alias: gpu
    resource_ref: srv.y
    allowed_capabilities: [query_status]
    allowed_skills: [server-query]
"""


@pytest.fixture()
def pool(tmp_path):
    _write(tmp_path / "resources" / "resource_registry.yaml", REG)
    _write(tmp_path / "resources" / "resource_policy.yaml", POLICY)
    _write(tmp_path / "projects" / "proj-a" / "resource_bindings.yaml", BIND)
    return tmp_path


# --------------------------------------------------------------------------- registry

def test_load_registry_indexes_by_id(pool):
    reg = rp.load_registry(str(pool / "resources"))
    assert set(reg) == {"api.x", "srv.y"}
    assert reg["api.x"]["scope"] == "shared"            # defaulted


def test_registry_rejects_a_secret_value_in_a_ref(tmp_path):
    _write(tmp_path / "resources" / "resource_registry.yaml",
           "schema_version: 1\nresources:\n  - resource_id: api.bad\n    type: api_key\n"
           "    secret_refs: {api_key: 'sk-REALSECRET123'}\n    capabilities: [x]\n")
    with pytest.raises(ValueError, match="bare env-var NAME"):
        rp.load_registry(str(tmp_path / "resources"))


def test_registry_rejects_resource_without_capabilities(tmp_path):
    _write(tmp_path / "resources" / "resource_registry.yaml",
           "schema_version: 1\nresources:\n  - resource_id: api.bad\n    type: api_key\n")
    with pytest.raises(ValueError, match="no capabilities"):
        rp.load_registry(str(tmp_path / "resources"))


# --------------------------------------------------------------------------- policy

def test_policy_requires_default_deny(tmp_path):
    _write(tmp_path / "resources" / "resource_policy.yaml",
           "schema_version: 1\ndefault: {access: allow}\nrules: []\n")
    with pytest.raises(ValueError, match="default-deny"):
        rp.load_policy(str(tmp_path / "resources"))


def test_policy_allows_known_capability(pool):
    pol = rp.load_policy(str(pool / "resources"))
    ok, _why, rule = rp.policy_allows(pol, "api.x", "search", "proj-a")
    assert ok and rule["max_lease_duration_seconds"] == 60


def test_policy_default_deny_unknown(pool):
    pol = rp.load_policy(str(pool / "resources"))
    ok, why, _ = rp.policy_allows(pol, "api.unknown", "search", "proj-a")
    assert not ok and "default-deny" in why


def test_policy_project_scoping(pool):
    pol = rp.load_policy(str(pool / "resources"))
    ok_a, _, _ = rp.policy_allows(pol, "srv.y", "query_status", "proj-a")
    ok_b, why_b, _ = rp.policy_allows(pol, "srv.y", "query_status", "proj-b")
    assert ok_a is True
    assert ok_b is False and "default-deny" in why_b   # the srv.y rule is project: proj-a only


# --------------------------------------------------------------------------- bindings

def test_binding_lookup_and_scoping(pool):
    binds = rp.load_bindings(str(pool / "projects"), "proj-a")
    b = rp.binding_for(binds, "x")
    assert b["resource_ref"] == "api.x"
    ok, _ = rp.binding_allows(b, "search", stage="DISCOVER")
    assert ok
    ok2, why2 = rp.binding_allows(b, "search", stage="EXECUTE")
    assert not ok2 and "stage" in why2


def test_binding_skill_scoping(pool):
    binds = rp.load_bindings(str(pool / "projects"), "proj-a")
    b = rp.binding_for(binds, "gpu")
    ok, _ = rp.binding_allows(b, "query_status", skill="server-query")
    assert ok
    ok2, why2 = rp.binding_allows(b, "query_status", skill="other-skill")
    assert not ok2 and "skill" in why2


def test_binding_absent_is_empty(tmp_path):
    binds = rp.load_bindings(str(tmp_path / "projects"), "no-proj")
    assert binds["bindings"] == []


# --------------------------------------------------------------------------- the real shipped pool

def test_real_shipped_pool_validates(monkeypatch):
    """The actual shipped registry + policy must load + validate (catches authoring drift)."""
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    reg = rp.load_registry()
    pol = rp.load_policy()
    assert "server.honor.gpu" in reg and "api.semantic_scholar" in reg
    ok, _, rule = rp.policy_allows(pol, "server.honor.gpu", "query_status", "iac-cbct-seg")
    assert ok and rule["requires_human_approval"] is True
    # submit_job (live execute) is NOT policy-allowed — stays gated
    ok2, _, _ = rp.policy_allows(pol, "server.honor.gpu", "submit_job", "iac-cbct-seg")
    assert ok2 is False
