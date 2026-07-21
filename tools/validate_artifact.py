"""Artifact contract enforcer (deterministic core).

Validates an enveloped artifact in two layers:
  1. envelope structure (artifact_envelope.schema.json)
  2. payload, against the schema registered for its artifact_type

Returns a list of human-readable error strings; empty list == valid.
This is a pure function over dicts: no I/O beyond reading the local schema files,
no network, no LLM. The PreToolUse hook and agents call this; it never "fixes" data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"

# Registry: artifact_type -> payload schema filename. Grows as the system grows.
PAYLOAD_SCHEMAS = {
    "task_frame": "task_frame.schema.json",
    "domain_profile": "domain_profile.schema.json",
    "note": "note.schema.json",
    "alignment_report": "alignment_report.schema.json",
    "adr": "adr.schema.json",                                  # governance ADR (conflict-resolver / decision-surfacer)
    # --- Phase 01 operated manuscript authoring contracts ---
    "manuscript_contract": "manuscript_contract.schema.json",
    "local_literature_coverage": "local_literature_coverage.schema.json",
    "manuscript_section_bundle": "manuscript_section_bundle.schema.json",
    "manuscript_integration": "manuscript_integration.schema.json",
    "manuscript_build_receipt": "manuscript_build_receipt.schema.json",
    "manuscript_asset_manifest": "manuscript_asset_manifest.schema.json",
    "manuscript_quality_report": "manuscript_quality_report.schema.json",
    "manuscript_review_verdict": "manuscript_review_verdict.schema.json",
    # --- Phase 1 (V1 agents) artifact types ---
    "evidence_table": "evidence_table.schema.json",            # lit-scout / DISCOVER exit
    "evidence_verdict": "evidence_verdict.schema.json",        # evidence-verifier (hard gate)
    "repo_verification": "repo_verification.schema.json",      # repo-code-verifier
    "model_dataset_candidates": "model_dataset_candidates.schema.json",  # model-dataset-scout
    "paper_note": "paper_note.schema.json",                    # literature-ingest
    "experiment_matrix": "experiment_matrix.schema.json",      # experiment-planner / DESIGN exit
    "protocol_spec": "protocol_spec.schema.json",              # protocol-compiler
    "variable_control_report": "variable_control_report.schema.json",   # variable-control-auditor (hard gate)
    "run_record": "run_record.schema.json",                    # ablation-runner / EXECUTE exit
    "result_summary": "result_summary.schema.json",            # result-analyzer / ANALYZE exit
    "review_report": "review_report.schema.json",              # adversarial-reviewer (hard gate) / VERIFY exit
    "report_note": "report_note.schema.json",                  # REPORT exit (the reply)
    # --- M2-a (spine slice) artifact types ---
    "dataset_script_record": "dataset_script_record.schema.json",  # trainset-builder / testset-builder
    "preflight_report": "preflight_report.schema.json",        # preflight-checker (hard gate, EXECUTE)
    "journal_entry": "journal_entry.schema.json",              # experiment-journaler
    "parity_verdict": "parity_verdict.schema.json",            # train-test-parity-verifier (hard gate, EXECUTE)
    "sanity_verdict": "sanity_verdict.schema.json",            # result-sanity-checker (hard gate, ANALYZE)
    # --- M2 breadth 2.1 DESIGN depth ---
    "rq_hypothesis_chain": "rq_hypothesis_chain.schema.json",   # rq-architect
    "split_manifest": "split_manifest.schema.json",            # dataset-split-planner
    "data_protocol": "data_protocol.schema.json",              # data-protocol-designer
    "unified_config": "unified_config.schema.json",            # config-unifier
    "integration_plan": "integration_plan.schema.json",        # method-integration-planner
    "baseline_fairness_plan": "baseline_fairness_plan.schema.json",  # baseline-fairness-planner
    "metric_impl_report": "metric_impl_report.schema.json",    # metric-implementation-auditor (hard gate, DESIGN)
    "power_audit_report": "power_audit_report.schema.json",     # statistics-power-auditor (advisory)
    # (decision-surfacer reuses existing `adr`)
    # --- M2 breadth 2.2 EXECUTE breadth ---
    "patch_plan": "patch_plan.schema.json",                    # patch-planner
    "implementation_record": "implementation_record.schema.json",  # code-implementer
    "test_suite_record": "test_suite_record.schema.json",      # unit-test-writer
    "sandbox_report": "sandbox_report.schema.json",            # sandbox-runner
    "triage_report": "triage_report.schema.json",              # failure-triager
    "repro_record": "repro_record.schema.json",                # repro-runner
    # --- M2 breadth 2.3 EVIDENCE depth ---
    "source_quality_report": "source_quality_report.schema.json",  # source-quality-ranker
    "evidence_search_trace": "evidence_search_trace.schema.json",  # evidence-search-moderator
    "claim_list": "claim_list.schema.json",                    # claim-extractor
    "claim_evidence_map": "claim_evidence_map.schema.json",    # claim-evidence-linker
    "contradiction_report": "contradiction_report.schema.json",  # contradiction-miner
    "dataset_card": "dataset_card.schema.json",                # dataset-card-builder
    "staleness_report": "staleness_report.schema.json",        # staleness-auditor
    "citation_integrity_verdict": "citation_integrity_verdict.schema.json",  # citation-integrity-auditor (hard gate, DISCOVER)
    "citation_attribution_report": "citation_attribution_report.schema.json",  # independent span/semantic attribution gate
    "landscape_map": "landscape_map.schema.json",              # landscape-mapper
    "paper_note_verification": "paper_note_verification.schema.json",  # source-claim-verifier
    # --- M2 breadth 2.4 ANALYZE panel ---
    "baseline_audit_report": "baseline_audit_report.schema.json",  # baseline-comparison-auditor
    "variance_report": "variance_report.schema.json",          # variance-analyzer
    "analysis_check_verdict": "analysis_check_verdict.schema.json",  # fairness/compliance/goal-alignment check-panel (shared, panel_role)
    "failure_inventory": "failure_inventory.schema.json",      # failure-case-miner
    "figure_spec_bundle": "figure_spec_bundle.schema.json",    # figure-generator
    "viz_audit_report": "viz_audit_report.schema.json",        # visualization-auditor (advisory)
    "calibrated_claims": "calibrated_claims.schema.json",      # claim-strength-calibrator
    # --- M2 breadth 2.5 VERIFY panel ---
    "review_config": "review_config.schema.json",              # review-configurator
    "panel_review": "panel_review.schema.json",                # methodology/domain reviewers (shared, lens)
    "critic_memo": "critic_memo.schema.json",                  # scientific-critic
    "panel_synthesis": "panel_synthesis.schema.json",          # review-synthesizer
    "synthesis_text": "synthesis_text.schema.json",            # synthesis-writer
    "contribution_ledger": "contribution_ledger.schema.json",  # contribution-ledger-builder
    "threats_report": "threats_report.schema.json",            # threats-to-validity-writer
    "response_simulation": "response_simulation.schema.json",  # review-response-simulator (advisory)
    # --- M3-a (new-direction spine) artifact types ---
    "future_work_items": "future_work_items.schema.json",      # future-work-miner (DISCOVER gap)
    "gap_classification": "gap_classification.schema.json",    # gap-classifier (shared DISCOVER/IDEATE; 7-type)
    "gap_prosecution": "gap_prosecution.schema.json",          # independent closure/open-status prosecution
    "gap_dossier_set": "gap_dossier_set.schema.json",          # mechanism-grounded Known/Unknown dossiers
    "gap_quality_audit": "gap_quality_audit.schema.json",      # independent scientific opportunity audit
    "novelty_score": "novelty_score.schema.json",              # novelty-scorer (SCORE-ONLY, advisory; never a cut)
    "hypothesis_set": "hypothesis_set.schema.json",            # hypothesis-generator (IDEATE)
    "idea_backlog": "idea_backlog.schema.json",                # feasibility-reranker / IDEATE exit (no self-bet field)
    # --- M3-b (EXECUTE menus + variable-touch ⛔ gate) ---
    "debug_session": "debug_session.schema.json",              # auto-debugger (EXECUTE menu, proposal)
    "experiment_tree": "experiment_tree.schema.json",          # experiment-tree-explorer (EXECUTE menu, bounded)
    "variable_touch_verdict": "variable_touch_verdict.schema.json",  # variable-touch-guard (EXECUTE hard gate ⛔)
    # --- M3-c (gap-hunting breadth; items are classify_gap signals) ---
    "weakness_report": "weakness_report.schema.json",          # weakness-spotter -> methodological_gap
    "white_space_map": "white_space_map.schema.json",          # white-space-mapper -> coverage_gap
    "transfer_candidates": "transfer_candidates.schema.json",  # cross-domain-transfer-scout -> transfer_gap
    "contrarian_angles": "contrarian_angles.schema.json",      # contrarian-angle-generator -> assumption_gap
    # --- M3-d (VR-1 venue-targeted peer-review) ---
    "venue_candidates": "venue_candidates.schema.json",        # venue-selector B-path (no auto-pick field)
    "venue_profile": "venue_profile.schema.json",              # venue-selector C-path (instantiated rubric scorecard)
    "venue_review": "venue_review.schema.json",                # venue-reviewer-persona (NO self-decide field)
    "venue_meta_review": "venue_meta_review.schema.json",      # area-chair advisory synthesis (NO verdict/accept)
    "venue_readiness_verdict": "venue_readiness_verdict.schema.json",  # deterministic advisory readiness derivation
    # --- M3-e (figure critic + monitor; both advisory) ---
    "figure_critique": "figure_critique.schema.json",          # figure-vlm-critic (advisory)
    "monitor_alert": "monitor_alert.schema.json",              # monitor (advisory)
    # --- M3-f (IDEATE-ring completion) ---
    "idea_tournament": "idea_tournament.schema.json",          # idea-tournament-ranker (pairwise bracket)
    "evolved_ideas": "evolved_ideas.schema.json",              # idea-evolver (parent-provenance)
    # --- M3.5 (the M⇄D seam — recall read side + promote write side) ---
    "recall_note": "recall_note.schema.json",                  # recall.py / RECALL exit (by-reference, never inlines D)
    "promotion_candidate": "promotion_candidate.schema.json",  # UNTRUSTED gate input (trust boundary; no path chars)
    "promotion_record": "promotion_record.schema.json",        # promote.py / promote-to-vault gate (re-derived, never self-claim)
    # --- Absorption wave 1 (2026-06-10; see _design/research-agent-teams-absorption-wave1-build-contract.md) ---
    "citation_existence_verdict": "citation_existence_verdict.schema.json",  # citation_existence.py (ARS three-state; live-existence gate helper)
    "fulltext_qa_report": "fulltext_qa_report.schema.json",    # fulltext_qa.py (PaperQA2 wrapper; page-anchored, available:false-honest)
    "experiment_feedback": "experiment_feedback.schema.json",  # experiment_feedback.py (RD-Agent failure attribution)
    "solution_tree": "solution_tree.schema.json",              # solution_tree.py (AIDE journal: draft/debug/improve tree)
    "elo_tournament": "elo_tournament.schema.json",            # elo_tournament.py (co-scientist Elo + Swiss; EVIDENCE, no chosen field)
    "calibration_report": "calibration_report.schema.json",    # review_calibration.py (SPECS-lite planted-error recall)
    "idea_grounding_report": "idea_grounding_report.schema.json",  # idea_grounding.py (ScholarEval-style; SCORE-ONLY)
    "research_brief": "research_brief.schema.json",            # operate/modes/deep_research.py (open_deep_research recipe)
    "research_perspective_note": "research_perspective_note.schema.json",  # deep_research perspective worker
    "research_markdown_brief": "research_markdown_brief.schema.json",      # deep_research director-facing Markdown brief
    "invalidation_record": "invalidation_record.schema.json",  # contradiction-mining structured landing (Graphiti bi-temporal; via promote only)
    # --- Audit waves A-D (2026-06-13; see _design/review/ai-capability-audit-2026-06-12.md §6) ---
    "preregistration": "preregistration.schema.json",          # tools/prereg.py (C3: analysis contract frozen at DESIGN, deviation-checked at ANALYZE)
    # --- Novelty-collision upgrade (2026-06-18; see _design/novelty-collision-upgrade-LEDGER.md) ---
    "collision_findings": "collision_findings.schema.json",    # novelty-collision-checker worker bundle (semantic judgment; never decides a cut)
    "novelty_collision_report": "novelty_collision_report.schema.json",  # tools/novelty_collision.py (EVIDENCE-not-score; cuts only on an existence-verified paper)
    # --- RAT-2 Wave-1/2 genuinely-new core (2026-06-18; see _design/rat2/01-roadmap-waves1-3.md) ---
    "problem_abstraction": "problem_abstraction.schema.json",  # mathematical-formalizer (IDEATE; typed mechanism abstraction + formal_form)
    "mechanism_mapping": "mechanism_mapping.schema.json",      # analogy-mapper (IDEATE; source↔target mechanism map; PASS⇒no blockers)
    "evidence_saturation_report": "evidence_saturation_report.schema.json",  # evidence-saturation-judge (DISCOVER; measured saturation, informs gate not decides)
    "stage_scorecard": "stage_scorecard.schema.json",          # quality-controller intermediate (per-stage rollup of existing analysis_check_verdict)
    "global_quality_scorecard": "global_quality_scorecard.schema.json",  # quality-controller (cross-stage aggregate; can_finish⇒all required dims pass)
    "integrity_recommendation": "integrity_recommendation.schema.json",  # integrity-refusal-recommender (REPORT; ADVISORY-only, decision_authority=director-human-gate)
    # --- RAT-2 Wave-3 deep-ideation chain (2026-06-19; see _design/idea-engine/IDEA-ENGINE-LEDGER.md) ---
    "mechanism_graph": "mechanism_graph.schema.json",          # mathematical-formalizer (DISCOVER; explicit internal causal graph of the problem; depth as a measurable object)
    "experiment_sketch": "experiment_sketch.schema.json",      # experiment-planner (IDEATE; minimal testable experiment per surviving idea; lighter than DESIGN protocol)
    "idea_lineage": "idea_lineage.schema.json",                # idea-evolver (IDEATE; per-idea provenance ledger; disposition is mechanical, never a bet)
    "idea_quality_eval": "idea_quality_eval.schema.json",      # idea_quality_eval.py (REPORT; blind pairwise quality harness; decomposed scores, no collapsed total / no bet)
    # --- Paper-reading upgrade (2026-06-26; see _design/paper-reading-upgrade/paper-reading-upgrade-LEDGER.md) ---
    "method_teardown": "method_teardown.schema.json",          # Pass-2 method teardown of a read paper (problem / assumptions / per-term loss / flows / data / cost / baseline diff)
    "figure_reading": "figure_reading.schema.json",            # Pass-2 structured figure reading (axes / controls / error-bars / take-home / distrust)
    "paper_appraisal": "paper_appraisal.schema.json",          # Pass-3 outward per-paper appraisal (venue-7D re-pointed OUTWARD; ADVISORY, never a gate / never self-decides)
    "paper_relations": "paper_relations.schema.json",          # Stage-4 typed paper->paper edges (inherits / refutes / unifies / replaces / opens / extends / uses)
    "trend_card": "trend_card.schema.json",                    # Stage-4 concept-centric trend extraction (shifts / failure-modes / mechanism-vs-result / opportunities)
    "paper_structure": "paper_structure.schema.json",          # full-paper section/figure/table inventory; prevents shallow read masquerading as deep
    "paper_reading_plan": "paper_reading_plan.schema.json",    # pre-read question tree + decision contract for deep paper reads
    "project_context_alignment": "project_context_alignment.schema.json",  # paper-to-project fit and downstream decision alignment
    "result_table_audit": "result_table_audit.schema.json",    # numeric results, metric direction, baseline binding, variance, split/leakage audit
    "math_algorithm_audit": "math_algorithm_audit.schema.json",  # equations / algorithm flow / pseudo-code consistency audit
    "reproducibility_materials_audit": "reproducibility_materials_audit.schema.json",  # code/data/config/environment availability audit
    "independent_reading_critique": "independent_reading_critique.schema.json",  # second-reader challenge memo
    "paper_reading_reconciliation": "paper_reading_reconciliation.schema.json",  # blind-vs-primary comparison + repair ledger
    "domain_transfer_note": "domain_transfer_note.schema.json",  # direct/indirect/proxy transfer boundary for the current research target
    "paper_reading_quality": "paper_reading_quality.schema.json",  # independent business-quality audit of a paper read
    "paper_markdown_card": "paper_markdown_card.schema.json",  # human-readable Markdown card evidence; actual .md is in director-review/papers/
    # --- AERS-informed governance layer (2026-07-05+) ---
    "numeric_benchmark_report": "numeric_benchmark_report.schema.json",  # numeric_benchmark_adapter.py (recompute metrics from result rows + journal/hash evidence)
    "aers_skill_integration_plan": "aers_skill_integration_plan.schema.json",  # aers_skill_integration_planner.py (metadata-only AERS -> RAT stage/SOP map)
}

_ENVELOPE_SCHEMA = "artifact_envelope.schema.json"


def _load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def _errors(schema: dict, instance, prefix: str) -> List[str]:
    validator = Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(instance), key=str):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{prefix}: {err.message} (at {loc})")
    return out


def validate_envelope(artifact: dict) -> List[str]:
    """Validate the envelope structure only."""
    return _errors(_load_schema(_ENVELOPE_SCHEMA), artifact, "envelope")


def validate_payload(artifact_type: str, payload: dict) -> List[str]:
    """Validate a payload against the schema registered for artifact_type."""
    fname = PAYLOAD_SCHEMAS.get(artifact_type)
    if fname is None:
        return [f"payload: unknown artifact_type '{artifact_type}' (no registered schema)"]
    return _errors(_load_schema(fname), payload, "payload")


def validate_against(schema_filename: str, instance) -> List[str]:
    """Validate any instance against a named schema file in schemas/. Reusable for
    infra objects that are not enveloped artifacts (run_manifest, ledger_event, ...)."""
    return _errors(_load_schema(schema_filename), instance, schema_filename)


def validate_artifact(artifact: dict) -> List[str]:
    """Full validation: envelope + payload-for-its-type. Empty list == valid."""
    errors = validate_envelope(artifact)
    atype = artifact.get("artifact_type")
    payload = artifact.get("payload")
    if isinstance(atype, str) and isinstance(payload, dict):
        errors += validate_payload(atype, payload)
    return errors


def is_valid(artifact: dict) -> bool:
    return not validate_artifact(artifact)


def validate_profile_dict(profile: dict) -> List[str]:
    """Validate a domain-profile body (the payload of a domain_profile artifact)."""
    return validate_payload("domain_profile", profile)
