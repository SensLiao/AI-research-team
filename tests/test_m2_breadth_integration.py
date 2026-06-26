"""M2 breadth integration — the cross-cutting invariants the per-sub-team builders could NOT check
because they only saw their own files. Proves the 5 sub-teams are actually WIRED into the control plane:

  1. Every registered artifact_type resolves to a schema file that is a valid JSON Schema AND actually
     enforces required fields (validate_payload({}) is non-empty) — catches a registration typo or an
     accidentally-permissive schema (a schema that validates {} would let a malformed artifact through).
  2. Every built agent spec is well-formed (frontmatter parses; name == filename; model is a real tier;
     a declared `produces` is a registered artifact_type) — catches a spec whose output type was never
     registered (it could never be contract-validated at runtime).
  3. All 41 M2-breadth agents + 37 new schemas are present (the breadth is complete, not partial).
  4. The graph + mode registry are still internally valid after the gate/mode edits.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from research_agent_teams.orchestrator.graph_spec import (
    load_roster,
    validate_graph,
    validate_mode_registry,
)
from research_agent_teams.tools.validate_artifact import (
    PAYLOAD_SCHEMAS,
    SCHEMA_DIR,
    validate_payload,
)

PKG = Path(__file__).resolve().parent.parent
AGENTS_DIR = PKG / "agents"
VALID_MODELS = {"opus", "sonnet", "haiku"}
# control / hook agents (artifact-contract-enforcer, permission-scope-guard, ...) are not LLM agents;
# their frontmatter declares `model: none`. Real LLM agents must use a real tier.
NON_LLM_MODEL = "none"

# The 37 schemas + 41 agents the breadth must deliver (decision-surfacer reuses existing `adr`).
BREADTH_ARTIFACT_TYPES = [
    # 2.1 DESIGN depth (8)
    "rq_hypothesis_chain", "split_manifest", "data_protocol", "unified_config", "integration_plan",
    "baseline_fairness_plan", "metric_impl_report", "power_audit_report",
    # 2.2 EXECUTE breadth (6)
    "patch_plan", "implementation_record", "test_suite_record", "sandbox_report", "triage_report", "repro_record",
    # 2.3 EVIDENCE depth (8)
    "source_quality_report", "claim_list", "claim_evidence_map", "contradiction_report", "dataset_card",
    "staleness_report", "citation_integrity_verdict", "landscape_map",
    # 2.4 ANALYZE panel (7)
    "baseline_audit_report", "variance_report", "analysis_check_verdict", "failure_inventory",
    "figure_spec_bundle", "viz_audit_report", "calibrated_claims",
    # 2.5 VERIFY panel (8)
    "review_config", "panel_review", "critic_memo", "panel_synthesis", "synthesis_text",
    "contribution_ledger", "threats_report", "response_simulation",
]

BREADTH_AGENTS = [
    # 2.1 (9)
    "rq-architect", "dataset-split-planner", "data-protocol-designer", "config-unifier",
    "method-integration-planner", "baseline-fairness-planner", "metric-implementation-auditor",
    "statistics-power-auditor", "decision-surfacer",
    # 2.2 (6)
    "patch-planner", "code-implementer", "unit-test-writer", "sandbox-runner", "failure-triager", "repro-runner",
    # 2.3 (8)
    "source-quality-ranker", "claim-extractor", "claim-evidence-linker", "contradiction-miner",
    "dataset-card-builder", "staleness-auditor", "citation-integrity-auditor", "landscape-mapper",
    # 2.4 (9)
    "baseline-comparison-auditor", "variance-analyzer", "fairness-auditor", "compliance-auditor",
    "goal-alignment-checker", "failure-case-miner", "figure-generator", "visualization-auditor",
    "claim-strength-calibrator",
    # 2.5 (9)
    "review-configurator", "methodology-reviewer", "domain-reviewer", "scientific-critic", "review-synthesizer",
    "synthesis-writer", "contribution-ledger-builder", "threats-to-validity-writer", "review-response-simulator",
]


def _frontmatter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{md_path.name}: no frontmatter block"
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


# --------------------------------------------------------------------------- 1. registration round-trip

def test_every_registered_type_has_a_valid_enforcing_schema():
    for atype, fname in PAYLOAD_SCHEMAS.items():
        path = SCHEMA_DIR / fname
        assert path.exists(), f"{atype}: registered schema file {fname} is missing"
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)  # raises if the schema itself is malformed
        # an empty payload must FAIL — proves the schema enforces required fields (not permissive)
        assert validate_payload(atype, {}) != [], f"{atype}: schema accepts empty {{}} (too permissive)"


def test_all_37_breadth_types_are_registered():
    for atype in BREADTH_ARTIFACT_TYPES:
        assert atype in PAYLOAD_SCHEMAS, f"breadth artifact_type {atype!r} is not registered in PAYLOAD_SCHEMAS"
    # decision-surfacer reuses the existing adr type (no new schema) — it must still be registered
    assert "adr" in PAYLOAD_SCHEMAS


def test_no_duplicate_schema_filenames():
    fnames = list(PAYLOAD_SCHEMAS.values())
    assert len(fnames) == len(set(fnames)), "two artifact_types map to the same schema file"


# --------------------------------------------------------------------------- 2 + 3. agent-spec consistency

def test_all_41_breadth_agents_have_specs():
    for name in BREADTH_AGENTS:
        assert (AGENTS_DIR / f"{name}.md").exists(), f"missing agent spec: {name}.md"
    assert len(BREADTH_AGENTS) == 41


def test_every_agent_spec_is_wellformed():
    # Global invariant over ALL specs (control/hook + worker): frontmatter parses, name matches the
    # filename and is in the roster, and the model tier is a real tier (or `none` for hook/control).
    roster = load_roster()
    for md in AGENTS_DIR.glob("*.md"):
        fm = _frontmatter(md)
        assert fm.get("name") == md.stem, f"{md.name}: frontmatter name {fm.get('name')!r} != filename"
        assert fm.get("name") in roster, f"{md.name}: agent {fm.get('name')!r} not in roster"
        assert fm.get("model") in VALID_MODELS | {NON_LLM_MODEL}, f"{md.name}: invalid model tier {fm.get('model')!r}"


def test_every_breadth_agent_produces_a_registered_type():
    # The 41 breadth worker agents each emit ONE typed artifact — its `produces` must be a registered
    # artifact_type, or the engine could never contract-validate that agent's output at runtime.
    for name in BREADTH_AGENTS:
        fm = _frontmatter(AGENTS_DIR / f"{name}.md")
        produces = fm.get("produces")
        assert produces in PAYLOAD_SCHEMAS, f"{name}: produces {produces!r} is not a registered artifact_type"


# Control / run-infra agents whose `produces:` frontmatter is free-text prose describing run-store
# plumbing (manifests, ledger entries, the orchestrator's own bookkeeping), NOT a payload artifact_type.
# They CANNOT be detected by `model: none` alone — these two declare a real LLM tier (opus / sonnet)
# yet emit no typed artifact, so the glob guard below must skip them explicitly. Keep this set as small
# as the truth requires (exactly these two — adding more would mask a real unregistered worker type).
PROSE_PRODUCES_CONTROL_AGENTS = {"research-orchestrator", "state-tracker"}


def _produces_types(produces) -> list[str]:
    # `produces:` is parsed by yaml.safe_load, so it is either a single string (most agents) or a list
    # (e.g. venue-selector: `produces: [venue_candidates, venue_profile]` — BOTH must be registered).
    if produces is None:
        return []
    if isinstance(produces, list):
        return [str(p) for p in produces]
    return [str(produces)]


def test_all_noncontrol_agents_produce_registered_types():
    # GLOB-based completeness guard: the hardcoded BREADTH_AGENTS list above only covers ~41 of the ~83
    # non-control producers, leaving the rest unchecked — so a NEW agent declaring a typo or an
    # unregistered `produces:` type would slip through. This iterates EVERY agents/*.md, skips only the
    # control/infra agents (model: none + the two prose-producing control agents above), and asserts each
    # declared produces-type (single OR array form) is a registered key in PAYLOAD_SCHEMAS — so the engine
    # can always contract-validate that agent's output at runtime.
    checked = 0
    for md in sorted(AGENTS_DIR.glob("*.md")):
        fm = _frontmatter(md)
        model = fm.get("model")
        if model == NON_LLM_MODEL or md.stem in PROSE_PRODUCES_CONTROL_AGENTS:
            continue  # control / run-infra agent — its `produces:` is plumbing prose, not a payload type
        checked += 1
        for atype in _produces_types(fm.get("produces")):
            assert atype in PAYLOAD_SCHEMAS, (
                f"{md.name}: produces type {atype!r} is not a registered artifact_type in "
                f"validate_artifact.PAYLOAD_SCHEMAS"
            )
    # Guard the guard: the glob must actually cover the broad worker roster, not silently match nothing.
    # (~83 non-control producers today; assert a healthy floor so a glob/skip regression is caught.)
    assert checked >= 80, f"completeness guard only checked {checked} agents — expected the full non-control roster (~83)"


def test_breadth_runtime_model_tiers_match_the_plan():
    # §9 default-mode tiers: the depth layer is judgment-heavy (auditors/gates/reviewers = opus).
    # synthesis-writer joined the opus tier 2026-06-13 (audit M7): it renders the director-facing
    # final verdict prose — a softened BLOCK narrative is a high-cost failure, so judgment tier.
    expected_opus = {
        "rq-architect", "baseline-fairness-planner", "metric-implementation-auditor", "statistics-power-auditor",
        "source-quality-ranker", "contradiction-miner", "staleness-auditor", "citation-integrity-auditor",
        "baseline-comparison-auditor", "variance-analyzer", "fairness-auditor", "compliance-auditor",
        "goal-alignment-checker", "visualization-auditor", "claim-strength-calibrator",
        "review-configurator", "methodology-reviewer", "domain-reviewer", "scientific-critic",
        "review-synthesizer", "synthesis-writer", "threats-to-validity-writer", "review-response-simulator",
    }
    for name in BREADTH_AGENTS:
        fm = _frontmatter(AGENTS_DIR / f"{name}.md")
        if name in expected_opus:
            assert fm["model"] == "opus", f"{name}: expected opus (judgment-heavy), got {fm['model']}"
        else:
            assert fm["model"] == "sonnet", f"{name}: expected sonnet (builder/extractor), got {fm['model']}"


# --------------------------------------------------------------------------- 4. registries still valid

def test_graph_and_modes_valid_after_gate_and_mode_edits():
    assert validate_graph() == []
    assert validate_mode_registry() == []


def test_new_hard_gates_are_wired_into_graph():
    from research_agent_teams.orchestrator.graph_spec import load_graph
    g = load_graph()["stages"]
    assert "metric-implementation-auditor" in g["DESIGN"]["blocking_gates"]
    assert "citation-integrity-auditor" in g["DISCOVER"]["blocking_gates"]
