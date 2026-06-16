"""Lease manager — time-bounded grants of a resource CAPABILITY to a run, with a redacted audit trail.

A lease records WHAT capability on WHICH resource was granted to WHICH run until WHEN — NEVER a
credential value (secrets stay in .env, read only at connect time by the execute layer). Leases are
appended to ``workspace/lease_registry.jsonl``; every access decision is appended to
``workspace/audit_log.jsonl`` with ``secret_material_logged: false``. The writer REFUSES any record
carrying a secret-like key (defence-in-depth), so the audit trail is provably value-free.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/

# Keys that must NEVER appear in a lease/audit record (a caller passing a value is a bug we hard-stop).
_FORBIDDEN_KEYS = {"password", "secret", "token", "api_key", "apikey", "key", "credential", "passwd"}

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def workspace_root(root: Optional[str] = None) -> Path:
    """Workspace control-plane root. ``RAT_WORKSPACE_ROOT`` wins (tests); else research_agent_teams/workspace."""
    if root:
        return Path(root)
    return Path(os.environ.get("RAT_WORKSPACE_ROOT") or (_PKG_ROOT / "workspace"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS_FMT)


class LeaseManager:
    """Append-only lease + audit store. Inject ``now`` for deterministic tests."""

    def __init__(self, ws_root: Optional[str] = None, now: Optional[Callable[[], datetime]] = None):
        self._root = workspace_root(ws_root)
        self._now = now or _utcnow

    @property
    def lease_path(self) -> Path:
        return self._root / "lease_registry.jsonl"

    @property
    def audit_path(self) -> Path:
        return self._root / "audit_log.jsonl"

    # ----------------------------------------------------------------- internals
    def _append(self, path: Path, record: dict) -> None:
        bad = _FORBIDDEN_KEYS & {str(k).lower() for k in record}
        if bad:
            raise ValueError(
                f"refused to write a record carrying secret-like keys {sorted(bad)} — leases/audit "
                "hold references only, never values")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _read(self, path: Path) -> List[dict]:
        if not path.exists():
            return []
        out: List[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _next_seq(self, run_id: str) -> int:
        seen = {r["lease_id"] for r in self._read(self.lease_path)
                if r.get("run_id") == run_id and "lease_id" in r}
        return len(seen) + 1

    # ----------------------------------------------------------------- API
    def acquire(self, *, resource_ref: str, capability: str, project: str, run_id: str,
                alias: Optional[str] = None, ttl_seconds: int = 3600,
                injection_mode: str = "runtime_env",
                requires_human_approval: bool = False) -> dict:
        """Grant a TTL lease for a capability and record it + an audit line. No secret is involved."""
        now = self._now()
        lease = {
            "lease_id": f"lease-{run_id}-{self._next_seq(run_id):03d}",
            "resource_ref": resource_ref,
            "capability": capability,
            "alias": alias,
            "project": project,
            "run_id": run_id,
            "granted_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=int(ttl_seconds))),
            "injection_mode": injection_mode,
            "requires_human_approval": bool(requires_human_approval),
            "secrets_logged": False,
            "status": "active",
        }
        self._append(self.lease_path, lease)
        self.audit(project=project, run_id=run_id, resource_ref=resource_ref, capability=capability,
                   lease_id=lease["lease_id"], decision="granted")
        return lease

    def audit(self, *, project: Optional[str], run_id: Optional[str], resource_ref: str,
              capability: str, lease_id: Optional[str], decision: str,
              skill: Optional[str] = None) -> dict:
        rec = {
            "ts": _iso(self._now()),
            "project": project,
            "run_id": run_id,
            "skill": skill,
            "resource_ref": resource_ref,
            "capability": capability,
            "lease_id": lease_id,
            "decision": decision,
            "secret_material_logged": False,
        }
        self._append(self.audit_path, rec)
        return rec

    def is_active(self, lease: dict, at: Optional[datetime] = None) -> bool:
        if lease.get("status") != "active":
            return False
        at = at or self._now()
        try:
            exp = datetime.strptime(lease["expires_at"], _TS_FMT).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return False
        return at <= exp

    def active_leases(self, run_id: Optional[str] = None) -> List[dict]:
        """Currently-active leases (latest record per lease_id; a revoke appends a tombstone)."""
        latest: Dict[str, dict] = {}
        for r in self._read(self.lease_path):
            lid = r.get("lease_id")
            if lid:
                latest[lid] = {**latest.get(lid, {}), **r}
        return [l for l in latest.values()
                if self.is_active(l) and (run_id is None or l.get("run_id") == run_id)]

    def revoke(self, lease_id: str, *, reason: str = "revoked") -> dict:
        records = [r for r in self._read(self.lease_path) if r.get("lease_id") == lease_id]
        if not records:
            raise ValueError(f"no such lease {lease_id!r}")
        base = records[-1]
        tombstone = {**base, "status": "revoked", "revoked_at": _iso(self._now()), "reason": reason}
        self._append(self.lease_path, tombstone)
        self.audit(project=base.get("project"), run_id=base.get("run_id"),
                   resource_ref=base.get("resource_ref"), capability=base.get("capability"),
                   lease_id=lease_id, decision="revoked")
        return tombstone
