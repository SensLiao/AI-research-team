"""Lease manager tests — TTL grant/expiry/revoke, audit redaction, and the hard refusal to write any
record carrying a secret-like key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from research_agent_teams.tools.lease_manager import LeaseManager


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t = self.t + timedelta(seconds=secs)


def _mgr(tmp_path):
    clock = _Clock(datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc))
    return LeaseManager(str(tmp_path / "workspace"), now=clock), clock


def test_acquire_writes_lease_and_audit(tmp_path):
    mgr, _ = _mgr(tmp_path)
    lease = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1",
                        ttl_seconds=60)
    assert lease["lease_id"] == "lease-r1-001"
    assert lease["status"] == "active" and lease["secrets_logged"] is False
    assert mgr.lease_path.is_file() and mgr.audit_path.is_file()
    audit = mgr.audit_path.read_text(encoding="utf-8")
    assert '"secret_material_logged": false' in audit
    assert '"decision": "granted"' in audit


def test_lease_seq_increments_per_run(tmp_path):
    mgr, _ = _mgr(tmp_path)
    a = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1")
    b = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1")
    c = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r2")
    assert a["lease_id"] == "lease-r1-001"
    assert b["lease_id"] == "lease-r1-002"
    assert c["lease_id"] == "lease-r2-001"


def test_lease_expires_with_ttl(tmp_path):
    mgr, clock = _mgr(tmp_path)
    lease = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1",
                        ttl_seconds=60)
    assert mgr.is_active(lease) is True
    clock.advance(61)
    assert mgr.is_active(lease) is False
    assert mgr.active_leases("r1") == []


def test_revoke_marks_inactive(tmp_path):
    mgr, _ = _mgr(tmp_path)
    lease = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1",
                        ttl_seconds=3600)
    assert len(mgr.active_leases()) == 1
    mgr.revoke(lease["lease_id"], reason="done")
    assert mgr.active_leases() == []


def test_revoke_unknown_raises(tmp_path):
    mgr, _ = _mgr(tmp_path)
    with pytest.raises(ValueError, match="no such lease"):
        mgr.revoke("lease-nope-001")


def test_append_refuses_secret_like_keys(tmp_path):
    mgr, _ = _mgr(tmp_path)
    with pytest.raises(ValueError, match="secret-like keys"):
        mgr._append(mgr.audit_path, {"password": "x", "ok": 1})
    with pytest.raises(ValueError, match="secret-like keys"):
        mgr._append(mgr.lease_path, {"api_key": "x"})


def test_legit_records_pass_the_secret_key_guard(tmp_path):
    """The real lease/audit keys (incl. 'secrets_logged' / 'secret_material_logged') are NOT rejected."""
    mgr, _ = _mgr(tmp_path)
    lease = mgr.acquire(resource_ref="api.x", capability="search", project="p", run_id="r1")
    assert "secrets_logged" in lease                    # legit key survived the guard
