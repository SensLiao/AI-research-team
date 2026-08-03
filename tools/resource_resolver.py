"""Resource resolver — the ONLY bridge from a capability request to a usable (leased) resource.

``resolve(project, run_id, alias_or_resource, capability, ...)``:
  load registry + policy + project bindings
  -> binding allows this resource + capability (+ stage / skill)?     (else ResourceDenied)
  -> policy allows (default-deny, least-privilege, capability)?       (else ResourceDenied)
  -> LeaseManager.acquire(...)  ->  ResolvedResource

Returns REFERENCES + a redacted summary, NEVER a secret value. For the SSH server it attaches the
execute layer's already-redacted connection summary (host / user / auth-MODE only); the password/key
are read from os.environ ONLY at connect time inside execute/runner.py — never here. This module never
sets ``RAT_EXECUTE_AUTHORIZED`` (the legacy exact-run CLI capability), cannot assert the primary
assistant's library-only explicit-director-command confirmation, and never opens a connection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from research_agent_teams.tools import resources as rp
from research_agent_teams.tools.lease_manager import LeaseManager

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/


class ResourceDenied(ValueError):
    """A capability request is not permitted by the binding or the policy (default-deny)."""


@dataclass(frozen=True)
class ResolvedResource:
    """A granted capability. Holds REFERENCES + a redacted summary — never a secret value."""
    resource_id: str
    capability: str
    lease_id: str
    injection_mode: str
    env_refs: Dict[str, str]                 # role -> .env var NAME (never a value)
    redacted_summary: Dict[str, object]
    requires_human_approval: bool
    expires_at: str

    def secret_values(self) -> dict:         # explicit: this object holds none
        return {}


def _projects_root(projects_root: Optional[str]) -> Path:
    if projects_root:
        return Path(projects_root)
    return Path(os.environ.get("RAT_PROJECTS_ROOT") or (_PKG_ROOT / "projects"))


class ResourceResolver:
    def __init__(self, *, workspace_root: Optional[str] = None, resources_root: Optional[str] = None,
                 projects_root: Optional[str] = None, now=None):
        self._projects_root = _projects_root(projects_root)
        self._leases = LeaseManager(workspace_root, now=now)
        self._registry = rp.load_registry(resources_root)
        self._policy = rp.load_policy(resources_root)

    def candidates(self, *, project: str, resource_type: Optional[str] = None,
                   capability: Optional[str] = None,
                   require_execution_ready: bool = False) -> list[dict]:
        """Return redacted, non-leasing candidates bound to ``project``.

        This is discovery only: it never resolves environment values, opens a connection, acquires a
        lease, or grants ``submit_job``.  When ``capability`` is supplied, both the project binding and
        the default-deny policy must allow it. ``require_execution_ready`` filters on independently
        recorded hardware/runtime readiness, while the later ``resolve`` + human gate still controls
        the actual operation. This keeps "the GPU exists" separate from "a job may be submitted".
        """
        bindings = rp.load_bindings(self._projects_root, project)
        out: list[dict] = []
        for binding in bindings.get("bindings", []) or []:
            resource_ref = binding.get("resource_ref")
            resource = self._registry.get(resource_ref)
            if resource is None:
                continue
            if resource_type and resource.get("type") != resource_type:
                continue
            if require_execution_ready and not bool(resource.get("execution_ready")):
                continue
            if capability:
                binding_ok, _ = rp.binding_allows(binding, capability)
                policy_ok, _, _ = rp.policy_allows(
                    self._policy, resource_ref, capability, project)
                if not (binding_ok and policy_ok):
                    continue
            submit_binding_ok, _ = rp.binding_allows(binding, "submit_job")
            submit_policy_ok, _, _ = rp.policy_allows(
                self._policy, resource_ref, "submit_job", project)
            out.append({
                "alias": binding.get("alias"),
                "resource_id": resource_ref,
                "type": resource.get("type"),
                "status": resource.get("status"),
                "execution_ready": bool(resource.get("execution_ready")),
                "execution_status": resource.get("execution_status", "unspecified"),
                "query_capabilities": list(binding.get("allowed_capabilities") or []),
                "submit_job_allowed": bool(submit_binding_ok and submit_policy_ok),
            })
        return sorted(out, key=lambda item: (str(item["alias"]), str(item["resource_id"])))

    def resolve(self, *, project: str, run_id: str, alias_or_resource: str, capability: str,
                stage: Optional[str] = None, skill: Optional[str] = None,
                ttl_seconds: Optional[int] = None) -> ResolvedResource:
        bindings = rp.load_bindings(self._projects_root, project)
        binding = rp.binding_for(bindings, alias_or_resource)
        if binding is None:
            self._deny_audit(project, run_id, alias_or_resource, capability, skill)
            raise ResourceDenied(
                f"project {project!r} has no binding for {alias_or_resource!r} — bind it in "
                f"projects/{project}/resource_bindings.yaml first")

        resource_ref = binding["resource_ref"]
        ok, why = rp.binding_allows(binding, capability, stage=stage, skill=skill)
        if not ok:
            self._deny_audit(project, run_id, resource_ref, capability, skill)
            raise ResourceDenied(why)

        ok, why, rule = rp.policy_allows(self._policy, resource_ref, capability, project)
        if not ok:
            self._deny_audit(project, run_id, resource_ref, capability, skill)
            raise ResourceDenied(why)

        resource = self._registry.get(resource_ref)
        if resource is None:
            self._deny_audit(project, run_id, resource_ref, capability, skill)
            raise ResourceDenied(f"binding references unknown resource {resource_ref!r} (not in pool)")

        requires_approval = bool(rule.get("requires_human_approval")
                                 or binding.get("requires_human_approval"))
        max_ttl = int(rule.get("max_lease_duration_seconds", 3600))
        ttl = min(int(ttl_seconds), max_ttl) if ttl_seconds else max_ttl
        injection_mode = "manual_copy_required" if requires_approval else "runtime_env"

        lease = self._leases.acquire(
            resource_ref=resource_ref, capability=capability, project=project, run_id=run_id,
            alias=binding.get("alias"), ttl_seconds=ttl, injection_mode=injection_mode,
            requires_human_approval=requires_approval)

        env_refs = rp.connection_env_refs(resource)

        return ResolvedResource(
            resource_id=resource_ref,
            capability=capability,
            lease_id=lease["lease_id"],
            injection_mode=injection_mode,
            env_refs=env_refs,
            redacted_summary=self._redacted_summary(resource),
            requires_human_approval=requires_approval,
            expires_at=lease["expires_at"])

    # ----------------------------------------------------------------- internals
    def _deny_audit(self, project, run_id, resource_ref, capability, skill) -> None:
        self._leases.audit(project=project, run_id=run_id, resource_ref=resource_ref,
                           capability=capability, lease_id=None, decision="denied", skill=skill)

    @staticmethod
    def _redacted_summary(resource: dict) -> Dict[str, object]:
        """A display summary with NO secret values — only ids, the auth MODE, and env-var NAMES."""
        summ: Dict[str, object] = {
            "resource_id": resource.get("resource_id"),
            "type": resource.get("type"),
            "display_name": resource.get("display_name"),
            "scope": resource.get("scope", "shared"),
            "auth": resource.get("auth", "none"),
            "capabilities": resource.get("capabilities", []),
            "secret_ref_names": sorted((resource.get("secret_refs") or {}).values()),
        }
        # For the SSH server attach the execute layer's already-redacted connection summary when the
        # .env is wired — host/user/auth-MODE only, never the password (read at connect time elsewhere).
        if resource.get("type") == "hardware.ssh_server":
            try:
                from research_agent_teams.execute import config as ec
                summ["connection"] = ec.redacted_summary(
                    ec.load_config(env_refs=rp.connection_env_refs(resource)))
            except Exception as e:                       # .env not wired / no host -> stay informative
                summ["connection"] = {"status": f"offline-plan ({type(e).__name__})"}
        return summ
