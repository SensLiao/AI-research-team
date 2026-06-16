"""Resource resolver tests — binding+policy gating (default-deny), TTL lease creation, and the hard
invariant that a resolved resource NEVER carries a secret value (sentinel check)."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.resource_resolver import ResourceDenied, ResourceResolver


@pytest.fixture()
def resolver(tmp_path, monkeypatch):
    # REAL shipped registry/policy + REAL project bindings; isolate the lease store to tmp.
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    return ResourceResolver(workspace_root=str(tmp_path / "ws"))


def test_resolve_paper_api_grants_lease(resolver):
    r = resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="paper_api",
                         capability="paper_search", stage="DISCOVER")
    assert r.resource_id == "api.semantic_scholar"
    assert r.lease_id == "lease-r1-001"
    assert r.requires_human_approval is False
    assert r.injection_mode == "runtime_env"
    assert r.env_refs == {"api_key": "RAT_S2_API_KEY"}   # the NAME, not a value


def test_resolve_denies_unbound_resource(resolver):
    with pytest.raises(ResourceDenied, match="no binding"):
        resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="connector.notion",
                         capability="notion_read")


def test_resolve_denies_capability_outside_binding(resolver):
    with pytest.raises(ResourceDenied, match="capability"):
        resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="paper_api",
                         capability="submit_job")


def test_resolve_denies_wrong_stage(resolver):
    with pytest.raises(ResourceDenied, match="stage"):
        resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="paper_api",
                         capability="paper_search", stage="EXECUTE")


def test_server_resolve_flags_approval_and_leaks_no_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    # sentinel secret in the environment — must NEVER surface in the resolved object / lease / audit
    monkeypatch.setenv("RAT_SERVER_HOST", "lab.example.edu")
    monkeypatch.setenv("RAT_SERVER_USER", "user01")
    monkeypatch.setenv("RAT_SERVER_PASSWORD", "SENTINEL-SECRET-DO-NOT-LEAK")
    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    r = resolver.resolve(project="iac-cbct-seg", run_id="r9", alias_or_resource="primary_gpu",
                         capability="query_status", stage="EXECUTE", skill="server-query")
    assert r.resource_id == "server.honor.gpu"
    assert r.requires_human_approval is True             # live SSH -> approval flagged
    assert r.injection_mode == "manual_copy_required"
    blob = repr(r) + str(r.redacted_summary) + str(r.env_refs)
    assert "SENTINEL-SECRET-DO-NOT-LEAK" not in blob
    assert "RAT_SERVER_PASSWORD" in r.env_refs.values()  # the NAME may appear; the VALUE must not
    leases = (tmp_path / "ws" / "lease_registry.jsonl").read_text(encoding="utf-8")
    audit = (tmp_path / "ws" / "audit_log.jsonl").read_text(encoding="utf-8")
    assert "SENTINEL-SECRET-DO-NOT-LEAK" not in leases + audit


def test_denied_request_is_audited(tmp_path, monkeypatch):
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    with pytest.raises(ResourceDenied):
        resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="connector.notion",
                         capability="notion_read")
    audit = (tmp_path / "ws" / "audit_log.jsonl").read_text(encoding="utf-8")
    assert '"decision": "denied"' in audit


def test_ttl_capped_by_policy(tmp_path, monkeypatch):
    """A caller asking for a longer TTL than the policy max gets capped at the policy ceiling."""
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    # api.semantic_scholar policy max is 3600s; ask for 999999 -> lease window must be <= 3600s
    r = resolver.resolve(project="iac-cbct-seg", run_id="r1", alias_or_resource="paper_api",
                         capability="paper_search", stage="DISCOVER", ttl_seconds=999999)
    # parse granted/expires from the lease file
    import json
    rec = json.loads((tmp_path / "ws" / "lease_registry.jsonl").read_text(encoding="utf-8").splitlines()[0])
    from datetime import datetime, timezone
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    span = (datetime.strptime(rec["expires_at"], fmt) - datetime.strptime(rec["granted_at"], fmt)).total_seconds()
    assert span <= 3600
    assert r.lease_id == "lease-r1-001"
