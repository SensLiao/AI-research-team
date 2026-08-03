"""Model-allocation policy — the director's two-knob model routing.

Every run uses exactly ONE of two modes:

  * "default"      — task-appropriate. Each agent runs on the model its spec declares:
                     opus for judgment / hard gates / final sign-off, sonnet for scoped
                     execution & verification. Balances quality, cost, and speed.
  * "max_quality"  — every *reasoning* agent is forced to opus (director opt-in for a
                     high-stakes run). Deterministic agents are untouched.

Two director locks, enforced structurally here (not just by convention):

  1. haiku is NEVER used. The minimum tier for an agent that actually reasons is sonnet.
     `resolve_model` floors haiku -> sonnet in BOTH modes, so even a stale spec that still
     says `model: haiku` can never put a real agent on haiku.
  2. `model: none` agents (permission-scope-guard / artifact-contract-enforcer /
     budget-and-stop-controller / ...) are pure deterministic Python — they run NO model.
     Neither mode ever assigns them one (max_quality does not "upgrade" a hook to opus).

This module is the SINGLE source of truth: it reads each agent's declared model from its
spec frontmatter (agents/*.md), so the mapping is never duplicated and cannot drift.
Pure functions over files/dicts; no LLM, no network.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

NO_MODEL = "none"
# LLM tiers, ascending capability/cost. haiku is listed so a stale spec still parses, but the
# FLOOR below guarantees haiku is never the *resolved* tier for a reasoning agent.
LLM_TIERS = ("haiku", "sonnet", "opus")
FLOOR = "sonnet"            # director lock: nothing that reasons runs below sonnet (no haiku)
TOP = "opus"
VALID_POLICIES = ("default", "max_quality")
KNOWN_MODELS = (NO_MODEL,) + LLM_TIERS

# Runtime selection is deliberately model-agnostic. Historical `sonnet`/`opus`
# strings remain compatibility aliases for workload classes, not vendor model
# requests. By default the harness omits a concrete model id, so the caller
# inherits the strongest available runtime. A deployment may bind an id through
# environment/config without changing any agent or mode definition.
RUNTIME_MODEL_ENV = "RAT_RUNTIME_MODEL"
RUNTIME_REASONING_ENV = "RAT_RUNTIME_REASONING_EFFORT"
RUNTIME_SERVICE_ENV = "RAT_RUNTIME_SERVICE_TIER"

RUNTIME_OBSERVED_FIELDS = (
    "resolved_model",
    "service_tier",
    "reasoning_effort",
    "input_tokens",
    "output_tokens",
    "elapsed_ms",
)

_CAPABILITY_BY_TIER = {
    "sonnet": {
        "reasoning_quality": "strong",
        "context_requirement": "long",
        "tool_use": True,
        "provider": "any",
    },
    "opus": {
        "reasoning_quality": "frontier",
        "context_requirement": "long",
        "tool_use": True,
        "provider": "any",
    },
}


def _rank(tier: str) -> int:
    return LLM_TIERS.index(tier)


def resolve_model(declared: str, policy: str) -> str:
    """Resolve the model an agent actually runs on, from its declared model + the run policy.

    none        -> none    (deterministic agent; never gets a model in either mode)
    max_quality -> opus    (every reasoning agent forced to the top tier)
    default     -> declared, floored at sonnet (haiku -> sonnet)
    """
    if policy not in VALID_POLICIES:
        raise ValueError(f"unknown model_policy '{policy}' (valid: {list(VALID_POLICIES)})")
    if declared not in KNOWN_MODELS:
        raise ValueError(f"unknown declared model '{declared}' (known: {list(KNOWN_MODELS)})")
    if declared == NO_MODEL:
        return NO_MODEL
    if policy == "max_quality":
        return TOP
    # default mode: honor the spec, but never below the floor (no haiku, ever)
    return declared if _rank(declared) >= _rank(FLOOR) else FLOOR


def safe_resolve_model(declared: Optional[str], policy: str) -> Optional[str]:
    """Observability-safe resolve: the resolved model, or None when there is no declared model OR
    the declared model / policy is unknown or malformed. Use this where a bad spec must NOT crash a
    crash-safe, resumable run (e.g. the obslog model label). Dispatch / PARSE paths should use
    resolve_model directly so a real misconfiguration fails loud where it belongs."""
    if declared is None:
        return None
    try:
        return resolve_model(declared, policy)
    except ValueError:
        return None


def capability_requirements(resolved_model: Optional[str]) -> Dict[str, object]:
    """Provider-neutral capabilities required by a logical workload class."""
    if resolved_model is None or resolved_model == NO_MODEL:
        return {}
    if resolved_model not in LLM_TIERS:
        raise ValueError(f"unknown resolved model '{resolved_model}' (known: {list(LLM_TIERS)})")
    tier = "sonnet" if resolved_model == "haiku" else resolved_model
    return dict(_CAPABILITY_BY_TIER[tier])


def codex_runtime_fields(
    resolved_model: Optional[str],
    *,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Return concrete runtime fields only when deployment config supplies them.

    The historical function name is retained for API compatibility. No model id,
    reasoning setting, or service tier is hardcoded in the research architecture.
    """
    if resolved_model is None or resolved_model == NO_MODEL:
        return {}
    if resolved_model not in LLM_TIERS:
        raise ValueError(f"unknown resolved model '{resolved_model}' (known: {list(LLM_TIERS)})")
    env = os.environ if environ is None else environ
    mapping = (
        ("runtime_model", RUNTIME_MODEL_ENV),
        ("reasoning_effort", RUNTIME_REASONING_ENV),
        ("service_tier", RUNTIME_SERVICE_ENV),
    )
    return {
        field: str(env.get(env_name) or "").strip()
        for field, env_name in mapping
        if str(env.get(env_name) or "").strip()
    }


def runtime_observability_fields(
    resolved_model: Optional[str],
    *,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Describe what the operate process actually observes about a worker call.

    The operate CLI emits a worker specification and exits; the Codex host runs
    that worker outside this Python process.  Consequently deployment env values
    are request-time bindings, never provider-response evidence.  This function
    deliberately has no path that returns ``provider_attested``: adding such a
    state requires a host callback carrying a cryptographically verifiable
    provider receipt.
    """
    if resolved_model is None or resolved_model == NO_MODEL:
        return {
            "runtime_observation_status": "not_applicable",
            "runtime_binding_source": "none",
            "runtime_observation_reason": "deterministic_or_unresolved_no_model_seat",
        }
    bindings = codex_runtime_fields(resolved_model, environ=environ)
    return {
        "runtime_observation_status": "unobserved",
        "runtime_binding_source": "deployment_environment" if bindings else "none",
        "runtime_observation_reason": "operate_process_has_no_provider_response_metadata",
    }


def runtime_observability_contract(resolved_model: Optional[str]) -> Dict[str, object]:
    """Fail-closed runner contract attached to every reasoning worker spec."""
    if resolved_model is None or resolved_model == NO_MODEL:
        return {
            "status": "not_applicable",
            "provider_receipt_available": False,
            "estimated_usage_allowed": False,
            "required_observed_fields": [],
        }
    return {
        "status": "unobserved",
        "provider_receipt_available": False,
        "estimated_usage_allowed": False,
        "required_observed_fields": list(RUNTIME_OBSERVED_FIELDS),
        "adapter_requirement": "signed_host_provider_usage_callback",
    }


def decorate_worker_runtime(worker: Optional[dict]) -> Optional[dict]:
    """Add concrete Codex runtime fields to an operate worker spec.

    The existing `model` field remains the logical tier for backward-compatible
    tests and historical audit prose. `capability_requirements` is the actual
    provider-neutral dispatch contract. Concrete runtime fields appear only when
    deployment configuration explicitly binds them.
    """
    if not worker:
        return worker
    if "workers" in worker:
        for child in worker.get("workers") or []:
            decorate_worker_runtime(child)
        return worker
    tier = worker.get("model")
    if not tier:
        return worker
    tier = str(tier)
    worker.setdefault("model_tier", tier)
    worker.setdefault("capability_requirements", capability_requirements(tier))
    worker.update(codex_runtime_fields(tier))
    worker.setdefault("runtime_observability", runtime_observability_contract(tier))
    return worker


def _frontmatter(md_text: str) -> dict:
    """Parse the leading `---` YAML frontmatter block of a markdown file ({} if none)."""
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    block: List[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    else:
        return {}  # no closing fence -> treat as no frontmatter
    return yaml.safe_load("\n".join(block)) or {}


def load_agent_models(agents_dir: Optional[str] = None) -> Dict[str, str]:
    """Map agent name -> declared model, read from each spec's frontmatter.

    A spec with no `model:` key at all is skipped (it declares nothing dispatchable).
    A `model: none` (or explicit null) is kept as NO_MODEL — a deterministic agent that
    declares it runs no model is a real, recorded fact, not an omission."""
    d = Path(agents_dir) if agents_dir else AGENTS_DIR
    out: Dict[str, str] = {}
    for p in sorted(d.glob("*.md")):
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        if "model" not in fm:
            continue
        raw = fm["model"]
        # YAML may parse a bare `none` as the string "none"; an explicit null means the same.
        model = NO_MODEL if raw is None else str(raw)
        name = fm.get("name") or p.stem
        out[str(name)] = model
    return out


def haiku_offenders(agents_dir: Optional[str] = None) -> List[str]:
    """Specs that still declare `model: haiku` — MUST be empty (director lock)."""
    return sorted(n for n, m in load_agent_models(agents_dir).items() if m == "haiku")


def effective_models(policy: str, agents_dir: Optional[str] = None) -> Dict[str, str]:
    """Name -> resolved model for a policy (applies the floor + max_quality upgrade)."""
    return {n: resolve_model(m, policy) for n, m in load_agent_models(agents_dir).items()}
