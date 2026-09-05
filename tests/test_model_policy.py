"""Director's two-knob model routing: default (task-appropriate) vs max_quality (all-opus),
plus the hard 'no haiku, floor at sonnet' lock. Pure-function tests over the resolver and the
spec-frontmatter source of truth (agents/*.md)."""
from __future__ import annotations

import pytest

from research_agent_teams.orchestrator.model_policy import (
    NO_MODEL,
    RUNTIME_MODEL_ENV,
    RUNTIME_REASONING_ENV,
    RUNTIME_SERVICE_ENV,
    VALID_POLICIES,
    capability_requirements,
    codex_runtime_fields,
    decorate_worker_runtime,
    effective_models,
    haiku_offenders,
    load_agent_models,
    resolve_model,
    runtime_observability_contract,
    runtime_observability_fields,
    safe_resolve_model,
)


# ---------------------------------------------------------------- the director lock: no haiku, ever

def test_no_built_agent_declares_haiku():
    # state-tracker was promoted haiku -> sonnet; nothing in the system declares haiku anymore.
    assert haiku_offenders() == []


def test_default_mode_floors_haiku_to_sonnet():
    # even if a spec regressed to haiku, default mode still refuses to run below sonnet.
    assert resolve_model("haiku", "default") == "sonnet"


def test_max_quality_floors_haiku_to_opus():
    assert resolve_model("haiku", "max_quality") == "opus"


# ---------------------------------------------------------------- default mode = honor the spec

def test_default_honors_declared_llm_tiers():
    assert resolve_model("sonnet", "default") == "sonnet"
    assert resolve_model("opus", "default") == "opus"


def test_default_leaves_deterministic_agents_modelless():
    assert resolve_model(NO_MODEL, "default") == NO_MODEL


# ---------------------------------------------------------------- max_quality = every reasoner -> opus

def test_max_quality_forces_every_llm_agent_to_opus():
    assert resolve_model("sonnet", "max_quality") == "opus"
    assert resolve_model("opus", "max_quality") == "opus"


def test_max_quality_never_puts_a_model_on_a_deterministic_hook():
    # a Python hook (model:none) is not "upgraded" to opus — it has no model to run.
    assert resolve_model(NO_MODEL, "max_quality") == NO_MODEL


# ---------------------------------------------------------------- Codex runtime mapping

def test_runtime_is_model_agnostic_until_deployment_binds_it():
    assert codex_runtime_fields("sonnet", environ={}) == {}
    assert codex_runtime_fields("opus", environ={}) == {}
    assert codex_runtime_fields(NO_MODEL) == {}


def test_runtime_binding_comes_from_environment_not_agent_specs():
    env = {
        RUNTIME_MODEL_ENV: "provider/frontier-model",
        RUNTIME_REASONING_ENV: "maximum",
        RUNTIME_SERVICE_ENV: "preferred",
    }
    assert codex_runtime_fields("opus", environ=env) == {
        "runtime_model": "provider/frontier-model",
        "reasoning_effort": "maximum",
        "service_tier": "preferred",
    }


def test_runtime_binding_is_explicitly_not_provider_observation():
    env = {
        RUNTIME_MODEL_ENV: "provider/frontier-model",
        RUNTIME_REASONING_ENV: "maximum",
        RUNTIME_SERVICE_ENV: "preferred",
    }
    assert runtime_observability_fields("opus", environ=env) == {
        "runtime_observation_status": "unobserved",
        "runtime_binding_source": "deployment_environment",
        "runtime_observation_reason": "operate_process_has_no_provider_response_metadata",
    }
    assert runtime_observability_fields("opus", environ={}) == {
        "runtime_observation_status": "unobserved",
        "runtime_binding_source": "none",
        "runtime_observation_reason": "operate_process_has_no_provider_response_metadata",
    }
    assert runtime_observability_fields(NO_MODEL) == {
        "runtime_observation_status": "not_applicable",
        "runtime_binding_source": "none",
        "runtime_observation_reason": "deterministic_or_unresolved_no_model_seat",
    }


def test_runtime_observability_contract_forbids_estimated_usage():
    contract = runtime_observability_contract("opus")
    assert contract["status"] == "unobserved"
    assert contract["provider_receipt_available"] is False
    assert contract["estimated_usage_allowed"] is False
    assert contract["required_observed_fields"] == [
        "resolved_model",
        "service_tier",
        "reasoning_effort",
        "input_tokens",
        "output_tokens",
        "elapsed_ms",
    ]


def test_capability_requirements_are_provider_neutral():
    assert capability_requirements("sonnet")["reasoning_quality"] == "strong"
    assert capability_requirements("opus")["reasoning_quality"] == "frontier"
    assert capability_requirements("opus")["provider"] == "any"


def test_worker_runtime_decoration_preserves_logical_tier_and_adds_capabilities(monkeypatch):
    monkeypatch.delenv(RUNTIME_MODEL_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_REASONING_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_SERVICE_ENV, raising=False)
    worker = {"label": "read-paper-deep-worker", "model": "opus", "prompt": "...",
              "output": "x.bundle.json"}
    decorated = decorate_worker_runtime(worker)
    assert decorated["model"] == "opus"
    assert decorated["model_tier"] == "opus"
    assert decorated["capability_requirements"]["reasoning_quality"] == "frontier"
    assert decorated["capability_requirements"]["provider"] == "any"
    assert decorated["runtime_observability"]["status"] == "unobserved"
    assert decorated["runtime_observability"]["estimated_usage_allowed"] is False
    assert "runtime_model" not in decorated


def test_worker_runtime_decoration_handles_panels(monkeypatch):
    monkeypatch.delenv(RUNTIME_MODEL_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_REASONING_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_SERVICE_ENV, raising=False)
    panel = {"workers": [{"label": "a", "model": "sonnet"}, {"label": "b", "model": "opus"}]}
    decorated = decorate_worker_runtime(panel)
    for worker in decorated["workers"]:
        assert worker["model_tier"] == worker["model"]
        assert worker["capability_requirements"]["provider"] == "any"
        assert worker["runtime_observability"]["provider_receipt_available"] is False
        assert "runtime_model" not in worker


# ---------------------------------------------------------------- guards (fail loud)

def test_unknown_policy_raises():
    with pytest.raises(ValueError, match="unknown model_policy"):
        resolve_model("sonnet", "ultra")


def test_unknown_declared_model_raises():
    with pytest.raises(ValueError, match="unknown declared model"):
        resolve_model("gpt", "default")


def test_valid_policies_are_exactly_two():
    assert set(VALID_POLICIES) == {"default", "max_quality"}


def test_safe_resolve_never_raises_and_degrades_to_none():
    # the observability-safe variant used by the engine: a bad spec/policy must degrade, not crash
    assert safe_resolve_model(None, "default") is None          # unbuilt agent (absent from the map)
    assert safe_resolve_model("gpt-5", "default") is None       # malformed declared model
    assert safe_resolve_model("sonnet", "ultra") is None        # malformed policy
    # a valid pair still resolves normally (and still honors the locks)
    assert safe_resolve_model("sonnet", "default") == "sonnet"
    assert safe_resolve_model("haiku", "default") == "sonnet"   # floor still applies
    assert safe_resolve_model("sonnet", "max_quality") == "opus"


# ---------------------------------------------------------------- spec frontmatter = single source of truth

def test_load_agent_models_reads_built_specs():
    models = load_agent_models()
    # judgment / hard-gate / sign-off agents are opus
    for a in ("research-orchestrator", "experiment-planner", "evidence-verifier",
              "variable-control-auditor", "train-test-alignment-auditor",
              "adversarial-reviewer", "conflict-resolver"):
        assert models[a] == "opus", a
    # scoped execution / verification agents are sonnet
    for a in ("lit-scout", "model-dataset-scout", "literature-ingest", "protocol-compiler",
              "repo-code-verifier", "ablation-runner", "result-analyzer"):
        assert models[a] == "sonnet", a
    # the promoted recorder is sonnet (no longer haiku)
    assert models["state-tracker"] == "sonnet"
    # deterministic Python hooks declare no model
    for a in ("permission-scope-guard", "artifact-contract-enforcer", "budget-and-stop-controller"):
        assert models[a] == NO_MODEL, a


def test_effective_models_default_has_no_haiku_and_keeps_gates_opus():
    eff = effective_models("default")
    assert "haiku" not in eff.values()
    assert eff["evidence-verifier"] == "opus"          # a hard gate stays opus in default mode
    assert eff["lit-scout"] == "sonnet"                # execution stays sonnet


def test_effective_models_max_quality_upgrades_every_reasoner_to_opus():
    eff = effective_models("max_quality")
    deterministic = {"permission-scope-guard", "artifact-contract-enforcer", "budget-and-stop-controller", "manuscript-integrator"}
    for name, model in eff.items():
        if name in deterministic:
            assert model == NO_MODEL, name
        else:
            assert model == "opus", name


def test_every_built_spec_declares_a_known_non_haiku_model():
    # Roster-drift guard: as the team grows (M2/M3 add agents), EVERY spec must declare a known
    # model and never haiku. A typo'd or haiku spec fails loud HERE (the right place) instead of
    # silently degrading an obslog line at runtime. Stays correct as the roster grows.
    allowed = {NO_MODEL, "sonnet", "opus"}
    models = load_agent_models()
    assert models, "no agent specs found — loader is broken"
    for name, model in models.items():
        assert model in allowed, f"{name} declares unexpected model '{model}' (haiku is banned)"
