"""Resource plane — shared resource pool loader + policy/binding evaluation.

Holds WHAT resources exist and WHERE their secrets live (a gitignored-.env variable NAME), plus a
default-deny policy and per-project bindings. NEVER holds a credential value — every ``secret_ref`` /
``endpoint_ref`` is an env-var NAME (CLAUDE.md §6), resolved to a value only at connect time by the
execute layer, never by this module, never echoed.

Mirrors tools/projects.py: explicit Python validation with actionable errors, read-only over the data
files. Companions: lease_manager.py (TTL leases + redacted audit), resource_resolver.py
(capability -> lease).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/

# An env-var NAME (NOT a value): UPPER_SNAKE. Any *_ref that is not a bare name is REJECTED, so a real
# credential pasted into the registry by mistake fails loudly instead of leaking into the repo.
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def resources_root(root: Optional[str] = None) -> Path:
    """Resource-pool data root. ``RAT_RESOURCES_ROOT`` wins (tests); else research_agent_teams/resources."""
    if root:
        return Path(root)
    return Path(os.environ.get("RAT_RESOURCES_ROOT") or (_PKG_ROOT / "resources"))


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"resource file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must parse to a mapping, got {type(data).__name__}")
    return data


def _assert_env_name(value: object, where: str) -> None:
    if not isinstance(value, str) or not _ENV_NAME_RE.match(value):
        raise ValueError(
            f"{where}: {value!r} is not a bare env-var NAME (UPPER_SNAKE). The resource pool stores "
            "secret REFERENCES only — never a value. Put the secret in research_agent_teams/.env and "
            "reference its variable name here.")


# --------------------------------------------------------------------------- loaders (read-only)

def load_registry(resources_root_path: Optional[str] = None) -> Dict[str, dict]:
    """``{resource_id: resource}``. Validates required keys + that every ``secret_ref`` / ``*_ref`` is
    an env-var NAME (no values). Raises ValueError on any malformed resource."""
    root = resources_root(resources_root_path)
    data = _load_yaml(root / "resource_registry.yaml")
    out: Dict[str, dict] = {}
    for r in data.get("resources", []) or []:
        rid = r.get("resource_id")
        if not rid or not isinstance(rid, str):
            raise ValueError(f"resource missing a string resource_id: {r!r}")
        if rid in out:
            raise ValueError(f"duplicate resource_id {rid!r}")
        if not r.get("capabilities"):
            raise ValueError(f"resource {rid!r} declares no capabilities")
        for role, ref in (r.get("secret_refs") or {}).items():
            _assert_env_name(ref, f"resource {rid!r} secret_refs.{role}")
        for key in (
            "endpoint_ref", "port_ref", "remote_workdir_ref", "python_ref", "conda_env_ref",
            "conda_sh_ref", "scheduler_ref", "results_pull_dir_ref", "known_hosts_ref",
            "connect_host_ref", "ssh_key_ref",
        ):
            if r.get(key) is not None:
                _assert_env_name(r[key], f"resource {rid!r} {key}")
        r.setdefault("scope", "shared")
        out[rid] = r
    if not out:
        raise ValueError(f"{root / 'resource_registry.yaml'} declares no resources")
    return out


def connection_env_refs(resource: dict) -> Dict[str, str]:
    """Build semantic connection role -> env-var NAME for one resource.

    Values are never resolved here. Keeping this translation in the resource plane lets every SSH
    consumer select a server without hardcoding a second RAT_SERVER_* implementation.
    """
    refs = dict(resource.get("secret_refs") or {})
    field_roles = {
        "endpoint_ref": "endpoint",
        "port_ref": "port",
        "remote_workdir_ref": "remote_workdir",
        "python_ref": "python",
        "conda_env_ref": "conda_env",
        "conda_sh_ref": "conda_sh",
        "scheduler_ref": "scheduler",
        "results_pull_dir_ref": "results_pull_dir",
        "known_hosts_ref": "known_hosts",
        "connect_host_ref": "connect_host",
        "ssh_key_ref": "ssh_key",
    }
    for field, role in field_roles.items():
        if resource.get(field):
            refs.setdefault(role, resource[field])
    if "host" not in refs and "endpoint" in refs:
        refs["host"] = refs["endpoint"]
    return refs


def load_policy(resources_root_path: Optional[str] = None) -> dict:
    """The access policy. Enforces the structural invariant ``default.access == 'deny'``."""
    root = resources_root(resources_root_path)
    data = _load_yaml(root / "resource_policy.yaml")
    if (data.get("default") or {}).get("access") != "deny":
        raise ValueError(
            "resource_policy.yaml MUST set default.access: deny — default-deny is required (no "
            "implicit access to shared resources).")
    data.setdefault("rules", [])
    return data


def load_bindings(projects_root, slug: str) -> dict:
    """Per-project resource_bindings.yaml (``{project, bindings: []}`` if absent)."""
    p = Path(projects_root) / slug / "resource_bindings.yaml"
    if not p.exists():
        return {"project": slug, "bindings": []}
    data = _load_yaml(p)
    data.setdefault("bindings", [])
    if not isinstance(data["bindings"], list):
        raise ValueError(f"{p}: 'bindings' must be a list")
    return data


# --------------------------------------------------------------------------- decisions

def binding_for(bindings: dict, alias_or_resource: str) -> Optional[dict]:
    """Find a binding by its alias OR its resource_ref."""
    for b in bindings.get("bindings", []) or []:
        if b.get("alias") == alias_or_resource or b.get("resource_ref") == alias_or_resource:
            return b
    return None


def binding_allows(binding: dict, capability: str, *, stage: Optional[str] = None,
                   skill: Optional[str] = None) -> Tuple[bool, str]:
    """Whether a binding permits this capability (and, if given, stage/skill)."""
    if capability not in (binding.get("allowed_capabilities") or []):
        return False, (f"binding {binding.get('alias')!r} does not allow capability {capability!r} "
                       f"(allowed: {binding.get('allowed_capabilities')})")
    if stage is not None and binding.get("allowed_stages") and stage not in binding["allowed_stages"]:
        return False, (f"binding {binding.get('alias')!r} not allowed in stage {stage!r} "
                       f"(allowed: {binding.get('allowed_stages')})")
    if skill is not None and binding.get("allowed_skills") and skill not in binding["allowed_skills"]:
        return False, (f"binding {binding.get('alias')!r} not allowed for skill {skill!r} "
                       f"(allowed: {binding.get('allowed_skills')})")
    return True, "binding allows"


def policy_rule(policy: dict, resource_ref: str, project: str) -> Optional[dict]:
    """The first policy rule matching (resource_ref, project) where project is '*' or an exact slug."""
    for rule in policy.get("rules", []) or []:
        if rule.get("resource_ref") != resource_ref:
            continue
        proj = rule.get("project", "*")
        if proj == "*" or proj == project:
            return rule
    return None


def policy_allows(policy: dict, resource_ref: str, capability: str,
                  project: str) -> Tuple[bool, str, dict]:
    """Default-deny: returns (allowed, reason, rule). No matching rule => denied."""
    rule = policy_rule(policy, resource_ref, project)
    if rule is None:
        return False, (f"default-deny: no policy rule for resource {resource_ref!r} / project "
                       f"{project!r}"), {}
    if capability not in (rule.get("allowed_capabilities") or []):
        return False, (f"policy denies capability {capability!r} on {resource_ref!r} "
                       f"(allowed: {rule.get('allowed_capabilities')})"), rule
    return True, "policy allows", rule


# --------------------------------------------------------------------------- director-facing views / writes

def pool_overview(*, scope: Optional[str] = None,
                  resources_root_path: Optional[str] = None) -> list:
    """The 'what can I use' listing for the director: resource_id / type / scope / capabilities / status
    / display_name. DELIBERATELY omits every secret_ref / endpoint_ref (even the env-var NAMES) — the
    director picks by capability, never needs the ref, and the pool view must never become a place a
    credential name leaks from."""
    out = []
    for rid, r in sorted(load_registry(resources_root_path).items()):
        if scope and r.get("scope") != scope:
            continue
        out.append({"resource_id": rid, "type": r.get("type"), "scope": r.get("scope", "shared"),
                    "capabilities": list(r.get("capabilities") or []), "status": r.get("status"),
                    "display_name": r.get("display_name")})
    return out


def add_binding(projects_root, slug: str, *, alias: str, resource_ref: str, capabilities: list,
                stages: Optional[list] = None, skills: Optional[list] = None,
                requires_human_approval: bool = False,
                resources_root_path: Optional[str] = None) -> dict:
    """Append a per-project binding (alias -> pool resource + allowed caps/stages/skills) to
    projects/<slug>/resource_bindings.yaml. Validates the resource exists in the pool and the requested
    capabilities are a SUBSET of what it declares. A binding is a SCOPING record, never a secret — the
    credential stays a .env ref on the resource and the default-deny policy still applies on top at lease
    time. Refuses a duplicate alias (bindings are append-only; edit the file by hand to change one).
    Immutable write: builds a new bindings list, never mutates the loaded one."""
    if not alias or not resource_ref:
        raise ValueError("a binding needs both an alias and a resource_ref")
    if not capabilities:
        raise ValueError("a binding must allow at least one capability")
    registry = load_registry(resources_root_path)
    res = registry.get(resource_ref)
    if res is None:
        raise ValueError(f"unknown resource_ref {resource_ref!r} (pool: {sorted(registry)})")
    declared = set(res.get("capabilities") or [])
    bad = [c for c in capabilities if c not in declared]
    if bad:
        raise ValueError(f"resource {resource_ref!r} does not provide capabilities {bad} "
                         f"(it provides {sorted(declared)})")
    existing = load_bindings(projects_root, slug)
    if binding_for(existing, alias) is not None:
        raise ValueError(f"alias {alias!r} is already bound for project {slug!r} "
                         "(bindings are append-only; edit resource_bindings.yaml to change one)")
    binding: dict = {"alias": alias, "resource_ref": resource_ref,
                     "allowed_capabilities": list(capabilities)}
    if stages:
        binding["allowed_stages"] = list(stages)
    if skills:
        binding["allowed_skills"] = list(skills)
    binding["requires_human_approval"] = bool(requires_human_approval)
    new = {"schema_version": existing.get("schema_version", 1), "project": slug,
           "bindings": list(existing.get("bindings", [])) + [binding]}
    out_path = Path(projects_root) / slug / "resource_bindings.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(new, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return binding
