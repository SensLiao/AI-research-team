"""Resource plane tests — pool loader, default-deny policy, per-project bindings, and the hard rule
that the registry stores secret REFERENCES (env-var names) only, never values."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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
    port_ref: RAT_Y_PORT
    remote_workdir_ref: RAT_Y_WORKDIR
    known_hosts_ref: RAT_Y_KNOWN_HOSTS
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


def test_connection_env_refs_are_resource_specific(pool):
    reg = rp.load_registry(str(pool / "resources"))
    refs = rp.connection_env_refs(reg["srv.y"])
    assert refs == {
        "host": "RAT_Y_HOST",
        "password": "RAT_Y_PASS",
        "endpoint": "RAT_Y_HOST",
        "port": "RAT_Y_PORT",
        "remote_workdir": "RAT_Y_WORKDIR",
        "known_hosts": "RAT_Y_KNOWN_HOSTS",
    }


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


def test_real_bdav_3090_director_resolution_still_requires_live_execution_admission(monkeypatch):
    """A director-reported fix cannot expose values or silently grant execute access."""
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    reg = rp.load_registry()
    pol = rp.load_policy()
    resource = reg["server.usyd.bdav_z390_3090"]

    assert resource["status"] == "director_reported_resolved_reverification_pending"
    assert resource["execution_ready"] is False
    assert resource["execution_status"] == (
        "director_reported_resolved_live_reverification_pending"
    )
    assert resource["execution_blockers"] == ["live_execution_admission_not_reverified"]
    assert resource["known_hosts_ref"] == "RAT_BDAV_Z390_KNOWN_HOSTS"
    assert resource["connect_host_ref"] == "RAT_BDAV_Z390_CONNECT_HOST"
    refs = rp.connection_env_refs(resource)
    assert refs["host"] == "RAT_BDAV_Z390_HOST"
    assert refs["user"] == "RAT_BDAV_Z390_USER"
    assert refs["password"] == "RAT_BDAV_Z390_PASSWORD"
    assert refs["known_hosts"] == "RAT_BDAV_Z390_KNOWN_HOSTS"
    assert refs["connect_host"] == "RAT_BDAV_Z390_CONNECT_HOST"

    for capability in ("query_status", "pull_logs"):
        allowed, _, rule = rp.policy_allows(
            pol, resource["resource_id"], capability, "petct-residual-correction"
        )
        assert allowed is True
        assert rule["requires_human_approval"] is True
    denied, _, _ = rp.policy_allows(
        pol, resource["resource_id"], "submit_job", "petct-residual-correction"
    )
    assert denied is False

    pkg_root = Path(rp.__file__).resolve().parents[1]
    bindings = rp.load_bindings(pkg_root / "projects", "petct-residual-correction")
    primary = rp.binding_for(bindings, "primary_gpu")
    assert primary["resource_ref"] == "server.honor.gpu"
    binding = rp.binding_for(bindings, "secondary_gpu")
    assert binding["resource_ref"] == resource["resource_id"]
    assert binding["allowed_capabilities"] == ["query_status", "pull_logs"]
    assert binding["allowed_skills"] == ["server-query"]
    assert binding["requires_human_approval"] is True


def test_bdav_3090_preflight_keeps_transport_separate_from_readiness():
    """A DNS/TCP check must not be promoted into authenticated, GPU, or execute readiness."""
    pkg_root = Path(rp.__file__).resolve().parents[1]
    path = (
        pkg_root
        / "resources"
        / "verification"
        / "server.usyd.bdav_z390_3090-preflight-2026-07-31.yaml"
    )
    evidence = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert evidence["verification_state"] == "read_only_verified_execution_blocked"
    assert evidence["secret_material_recorded"] is False
    assert evidence["trust_gate"]["expected_fingerprint_from_trusted_out_of_band_channel"] is None
    offline = evidence["historical_offline_verification"]
    assert offline["secret_store_inspected"] is False
    assert offline["ssh_authentication_attempted"] is False
    assert offline["ssh_session_opened"] is False
    assert offline["server_write_attempted"] is False
    assert offline["direct_tcp_22_observed_reachable"] is True
    assert offline["decision"] == "remain_credential_recovery_required"

    live = evidence["fresh_authenticated_read_only_inventory"]
    assert live["credential_value_observed_or_recorded"] is False
    assert live["strict_host_key_verification"] is True
    assert live["gpu_inventory"][0]["model"] == "NVIDIA GeForce RTX 3090"
    assert live["gpu_inventory"][1]["model"] == "NVIDIA GeForce GTX 1080 Ti"
    assert live["disk"]["reported_use_percent"] == 100
    assert live["conda"]["project_environment_verified"] is False
    assert live["scheduler"]["slurm_usable"] is False
    assert live["decision"] == "READ_ONLY_VERIFIED_EXECUTION_BLOCKED"

    plan = evidence["recovery_and_first_inventory_plan"]
    assert plan["state"] == "COMPLETED_THROUGH_INV1_READ_ONLY_VERIFIED_EXECUTION_BLOCKED"
    assert "submit_job_remains_default_denied" in plan["hard_invariants"]
    steps = {step["id"]: step for step in plan["steps"]}
    assert list(steps) == ["CR-1", "TRUST-1", "LOCAL-1", "INV-1", "POST-1"]
    assert steps["LOCAL-1"]["prerequisites"] == ["CR-1", "TRUST-1"]
    assert "explicit_live_query_authorization" in steps["INV-1"]["prerequisites"]
    assert "job_submission" in steps["INV-1"]["prohibited_actions"]
    assert steps["INV-1"]["status"] == "PASS_READ_ONLY"
    assert evidence["governance"]["submit_job"] == "default_denied"
    admission = evidence["execution_admission_plan"]
    assert admission["state"] == "BLOCKED"
    assert admission["current_transition"] == "retain_query_status_and_pull_logs_only"
