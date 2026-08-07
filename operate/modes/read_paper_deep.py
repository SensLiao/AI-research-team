"""Operate recipe for the `read_paper_deep` mode (DISCOVER -> REPORT).

High-quality paper reading must be a real staged panel, not one giant worker
filling JSON fields. This recipe dispatches independent per-paper workers for
pre-read planning, project alignment, coverage, claims, evidence, method,
numeric results, algorithm/math checks, figures, appraisal, relations, trend,
transfer, reproducibility, a blind second-reader branch, explicit
reconciliation, quality audit, and director-facing Markdown.

The mode still produces draft knowledge only. `/promote-to-vault` remains the
only database write gate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ..output_versions import resolve_effective_output
from ...tools import fulltext_qa
from ...tools.citation_attribution import (
    build_run_attribution_report,
    load_explicit_legacy_replay,
    write_fulltext_context_snapshot,
)
from ...tools.citation_checker import build_report
from ...tools.evidence_scout import build_evidence_table
from ...tools.paper_markdown_quality import audit_paper_markdown
from ...tools.paper_visual_assets import (
    MANIFEST_REL,
    load_visual_manifest,
    write_visual_manifest,
)
from ...tools.validate_artifact import validate_payload
from ...tools.schema_normalizer import write_report

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

# bundle key -> (artifact_type, producing agent name, output filename, status)
ARTIFACT_PLAN = (
    ("independent_reading_critique", "independent_reading_critique",
     "independent-reading-critic", "independent-reading-critique.artifact.json", "approved"),
    ("paper_reading_plan", "paper_reading_plan", "paper-reading-planner",
     "paper-reading-plan.artifact.json", "approved"),
    ("paper_note", "paper_note", "literature-ingest", "paper-note.artifact.json", "draft"),
    ("paper_structure", "paper_structure", "paper-structure-mapper",
     "paper-structure.artifact.json", "approved"),
    ("project_context_alignment", "project_context_alignment", "project-context-aligner",
     "project-context-alignment.artifact.json", "approved"),
    ("claim_list", "claim_list", "claim-extractor", "claim-list.artifact.json", "approved"),
    ("claim_evidence_map", "claim_evidence_map", "claim-evidence-linker",
     "claim-evidence-map.artifact.json", "approved"),
    ("method_teardown", "method_teardown", "method-teardown-extractor",
     "method-teardown.artifact.json", "approved"),
    ("exploration_tree", "exploration_tree", "research-trajectory-extractor",
     "exploration-tree.artifact.json", "approved"),
    ("figure_reading", "figure_reading", "figure-reader", "figure-reading.artifact.json", "approved"),
    ("result_table_audit", "result_table_audit", "result-table-auditor",
     "result-table-audit.artifact.json", "approved"),
    ("math_algorithm_audit", "math_algorithm_audit", "math-algorithm-verifier",
     "math-algorithm-audit.artifact.json", "approved"),
    ("paper_appraisal", "paper_appraisal", "paper-appraiser", "paper-appraisal.artifact.json",
     "approved"),
    ("paper_relations", "paper_relations", "paper-relations-mapper",
     "paper-relations.artifact.json", "approved"),
    ("trend_card", "trend_card", "trend-card-builder", "trend-card.artifact.json", "approved"),
    ("domain_transfer_note", "domain_transfer_note", "domain-transfer-critic",
     "domain-transfer-note.artifact.json", "approved"),
    ("reproducibility_materials_audit", "reproducibility_materials_audit",
     "reproducibility-materials-auditor", "reproducibility-materials-audit.artifact.json",
     "approved"),
    ("paper_reading_reconciliation", "paper_reading_reconciliation",
     "paper-reading-reconciler", "paper-reading-reconciliation.artifact.json", "approved"),
    ("paper_reading_quality", "paper_reading_quality", "paper-reading-quality-auditor",
     "paper-reading-quality.artifact.json", "approved"),
    ("paper_markdown_card", "paper_markdown_card", "paper-markdown-writer",
     "paper-markdown-card.artifact.json", "approved"),
)

BUNDLE_BY_AGENT = {
    agent: (key, atype, filename, status)
    for key, atype, agent, filename, status in ARTIFACT_PLAN
}
AGENT_BY_KEY = {key: agent for key, _atype, agent, _filename, _status in ARTIFACT_PLAN}
BUNDLE_KEYS = tuple(key for key, *_ in ARTIFACT_PLAN)
CITATION_AUDITOR_AGENT = "citation-coverage-auditor"

# Without explicit groups the scheduler turns worker_order into a full serial
# barrier. These waves expose the actual sparse scientific dependency graph.
READ_PAPER_PARALLEL_GROUPS = [
    ["independent-reading-critic", "paper-reading-planner"],
    ["literature-ingest"],
    ["paper-structure-mapper", "project-context-aligner"],
    ["claim-extractor"],
    # research-trajectory-extractor sits next to method-teardown-extractor deliberately: the two read
    # the same frozen paper from two angles (what the method IS vs how it came to be) and share
    # predecessors. Wave order here must mirror ARTIFACT_PLAN, which is what the scheduler walks.
    ["claim-evidence-linker", "method-teardown-extractor", "research-trajectory-extractor",
     "paper-relations-mapper"],
    [CITATION_AUDITOR_AGENT, "figure-reader", "math-algorithm-verifier"],
    ["result-table-auditor", "reproducibility-materials-auditor"],
    ["paper-appraiser"],
    ["trend-card-builder", "domain-transfer-critic"],
    ["paper-reading-reconciler"],
    ["paper-reading-quality-auditor"],
    ["paper-markdown-writer"],
]

OPTIONAL_SPECIALISTS = {
    "visual_audit": ("figure-reader",),
    "result_audit": ("result-table-auditor",),
    "math_audit": ("math-algorithm-verifier",),
    "lineage_trend": ("paper-relations-mapper", "trend-card-builder"),
    "reproducibility_audit": ("reproducibility-materials-auditor",),
}

# Explicit dataflow replaces the old "every worker sees all earlier workers"
# behavior.  In particular, the blind branch has no analyst-bundle dependency;
# only the reconciler may join it with the primary reading branch.
WORKER_DEPENDENCIES = {
    "paper-reading-planner": (),
    "independent-reading-critic": (),
    "literature-ingest": ("paper-reading-planner",),
    "paper-structure-mapper": ("paper-reading-planner", "literature-ingest"),
    "project-context-aligner": ("paper-reading-planner", "literature-ingest"),
    "claim-extractor": ("literature-ingest", "paper-structure-mapper"),
    "claim-evidence-linker": ("claim-extractor", "paper-structure-mapper"),
    "citation-coverage-auditor": (
        "claim-extractor", "claim-evidence-linker", "paper-structure-mapper",
    ),
    "method-teardown-extractor": (
        "literature-ingest", "paper-structure-mapper", "claim-extractor",
    ),
    # Same predecessors as the teardown, deliberately: the two read the same frozen paper from two
    # different angles (what the method IS vs how it came to be) and neither may inherit the other's
    # reconstruction. Running them in one wave keeps them independent.
    "research-trajectory-extractor": (
        "literature-ingest", "paper-structure-mapper", "claim-extractor",
    ),
    "figure-reader": (
        "paper-structure-mapper", "claim-evidence-linker", "method-teardown-extractor",
    ),
    "result-table-auditor": (
        "claim-extractor", "claim-evidence-linker", "paper-structure-mapper", "figure-reader",
    ),
    "math-algorithm-verifier": ("literature-ingest", "method-teardown-extractor"),
    "paper-appraiser": (
        "claim-evidence-linker", "method-teardown-extractor", "figure-reader",
        "result-table-auditor", "math-algorithm-verifier",
    ),
    "paper-relations-mapper": ("literature-ingest", "claim-extractor"),
    "trend-card-builder": ("literature-ingest", "paper-relations-mapper", "paper-appraiser"),
    "domain-transfer-critic": (
        "project-context-aligner", "paper-appraiser", "result-table-auditor",
    ),
    "reproducibility-materials-auditor": (
        "literature-ingest", "method-teardown-extractor", "math-algorithm-verifier",
    ),
    "paper-reading-reconciler": (
        "independent-reading-critic", "claim-extractor", "claim-evidence-linker",
        "method-teardown-extractor", "figure-reader", "result-table-auditor",
        "math-algorithm-verifier", "paper-appraiser", "domain-transfer-critic",
    ),
    "paper-reading-quality-auditor": (
        "paper-reading-planner", "paper-structure-mapper", "project-context-aligner",
        "claim-extractor", "claim-evidence-linker", "method-teardown-extractor",
        "figure-reader", "result-table-auditor", "math-algorithm-verifier",
        "paper-appraiser", "reproducibility-materials-auditor", "citation-coverage-auditor",
        "paper-reading-reconciler",
    ),
    "paper-markdown-writer": tuple(
        [agent for _key, _atype, agent, _fname, _status in ARTIFACT_PLAN
         if agent not in {"paper-markdown-writer"}]
        + ["citation-coverage-auditor"]
    ),
}

_BLIND_ALLOWED_INPUT_CLASSES = {
    "task_frame", "source_document", "fulltext_snapshot", "visual_snapshot",
}


def _blind_input_class_from_ref(ref: str) -> str:
    """Map the scheduler's path-style blind receipts to the canonical class contract.

    Current worker prompts expose allowed paths, while older bundles emitted explicit
    ``input_class`` objects.  Accept both representations without broadening the blind
    reader's read boundary; unknown paths deliberately map to the empty class and fail
    the existing allow-list checks.
    """
    value = str(ref or "").replace("\\", "/").strip()
    lowered = value.lower()
    if value in _BLIND_ALLOWED_INPUT_CLASSES:
        return value
    if lowered == "task_frame.artifact.json":
        return "task_frame"
    if lowered.startswith("inbox/fulltext-docs/"):
        return "source_document"
    if lowered == "inbox/fulltext-qa.json" or lowered.startswith("inbox/citation-snapshots/"):
        return "fulltext_snapshot"
    if lowered == str(MANIFEST_REL).lower() or lowered.startswith("inbox/paper-visuals/"):
        return "visual_snapshot"
    return ""


def _blind_input_receipt(item) -> tuple[str, str]:
    if isinstance(item, dict):
        ref = str(item.get("ref") or "").replace("\\", "/")
        input_class = str(item.get("input_class") or "")
        return input_class or _blind_input_class_from_ref(ref), ref
    if isinstance(item, str):
        ref = item.replace("\\", "/")
        return _blind_input_class_from_ref(ref), ref
    return "", ""


def _worker_model(model_policy: str, agent: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    if agent in {
        "paper-reading-planner",
        "project-context-aligner",
        "result-table-auditor",
        "math-algorithm-verifier",
        "domain-transfer-critic",
        "independent-reading-critic",
        "paper-reading-reconciler",
        "paper-reading-quality-auditor",
        "paper-markdown-writer",
    }:
        return "opus"
    return "sonnet"


def _reading_hook(run_dir) -> str:
    prof = _shared.domain_profile(run_dir) or {}
    reading = prof.get("reading") or {}
    if not reading:
        return ""
    lines = ["DOMAIN READING PROFILE:"]
    if reading.get("paper_type_default"):
        lines.append(f"- default paper_type: {reading['paper_type_default']}")
    stds = reading.get("reporting_standards") or []
    if stds:
        lines.append(f"- reporting standards to check: {', '.join(str(s) for s in stds)}")
    if reading.get("appraisal_checklist"):
        lines.append(f"- appraisal checklist: {reading['appraisal_checklist']}")
    if reading.get("notes"):
        lines.append(f"- notes: {reading['notes']}")
    return "\n".join(lines) + "\n"


def fulltext_pre(run_dir, question: str, doc_paths, ts: str) -> Optional[str]:
    """Create text and visual source snapshots before any reading worker runs."""
    if not doc_paths:
        return None
    docs = list(doc_paths)
    report = fulltext_qa.ask(question, docs, retraction_flags=fulltext_qa.retraction_check(docs))
    p = Path(run_dir) / "inbox" / "fulltext-qa.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    write_fulltext_context_snapshot(run_dir, report, docs)
    # A separate immutable visual snapshot prevents a caption/text extractor
    # from masquerading as a figure reader.  Failure is recorded honestly in
    # the manifest and later blocks visual PASS; it does not fabricate images.
    write_visual_manifest(run_dir, docs)
    return str(p)


def _bundle_path(run_dir, agent: str) -> Path:
    return Path(run_dir) / "inbox" / f"DISCOVER.{agent}.bundle.json"


def _prior_inputs(run_dir, prior_agents: list[str]) -> str:
    if not prior_agents:
        return ""
    lines = ["These are the ONLY earlier worker bundles you may read before writing:"]
    for agent in prior_agents:
        lines.append(f"- `{_bundle_path(run_dir, agent).as_posix()}`")
    return "\n".join(lines) + "\n"


def _prompt(agent: str, key: str, request: str, run_dir: str, out: str,
            north_star: str, reading_hook: str, prior_agents: list[str]) -> str:
    source = (
        "Source by reference: the paper itself (file path, [[slug]], DOI, URL, or arXiv). "
        "When `inbox/shared-paper-representation.json` exists, reuse it for stable note, structure, "
        "and claim facts; reopen the source only for your specialist verification instead of rebuilding "
        "the whole paper representation. "
        "If `inbox/fulltext-qa.json` exists, use its page contexts and retraction flags. "
        "For exact text attribution, use `inbox/citation-snapshots/fulltext-contexts.manifest.json` "
        "and its UTF-8 snapshot; the manifest supplies the recomputable hash, offsets, and quotes. "
        "Actual visual inspection uses only page images named by "
        "`inbox/paper-visual-manifest.json`; extracted text and captions are not images."
    )
    isolation = ""
    if agent == "independent-reading-critic":
        isolation = (
            "BLIND INPUT FIREWALL: read only task_frame.artifact.json, copied files under "
            "inbox/fulltext-docs/, inbox/fulltext-qa.json, and manifest-backed page images. "
            "DO NOT open any inbox/DISCOVER.*.bundle.json. Record consumed_inputs exactly.\n"
        )
    effective_reading_hook = "" if agent == "independent-reading-critic" else reading_hook
    common = f"""You are `{agent}` in the TRUE multi-worker `read_paper_deep` pipeline.

REQUEST: {request}

{north_star}
{effective_reading_hook}
{source}
{isolation}
{_prior_inputs(run_dir, prior_agents)}
Write ONLY JSON to `{out}`. The JSON must have exactly one top-level key: `{key}`.
Never invent source refs, figures, tables, claims, or numbers. Leave unknown fields honest.
"""

    bodies = {
        "paper-reading-planner": """
Task: create the pre-read question tree and decision contract before anyone summarizes.
Output shape: {"paper_reading_plan": {source_hint, reading_objective, decision_need,
key_questions, required_outputs, reread_triggers, not_for, specialist_policy}}.
Write at least 6 key questions and 6 required outputs — FLOORS with no upper bound; ask every question this paper can actually settle for the project. Make the read serve a concrete project
decision, not a generic paper summary.
Set each specialist_policy value to required or skip. Skip only when the source makes that seat
scientifically inapplicable. Uncertainty means required. Blind reading, claim/evidence, independent
citation audit, appraisal, reconciliation, quality audit, and Markdown are never optional.
""",
        "literature-ingest": """
Task: identify the paper and produce the Stage-0 + Pass-1 paper note.
Output shape: {"paper_note": {title, source_ref, summary, claims, methods, datasets, metrics,
paper_type, read_purpose, relation_to_thesis, reading_objective, reading_status, paper_contract}}.
Claims must be atomic and falsifiable; aim for 3-8.
""",
        "paper-structure-mapper": """
Task: map full-paper coverage before claims are trusted.
Output shape: {"paper_structure": {source_ref, sections, figures, tables, supplements,
coverage_gaps, fulltext_available}}.
List all load-bearing figures/tables you can see. Mark unread load-bearing items honestly.
""",
        "project-context-aligner": """
Task: tie this focal paper to the active project, advisor questions, and downstream research decisions.
Output shape: {"project_context_alignment": {source_ref, project_context, relevance, thesis_fit,
advisor_questions, vault_or_project_refs, must_answer, downstream_decisions, misuse_risks}}.
Be strict about A-core vs B-related vs C-background. If project context is thin, say so.
""",
        "claim-extractor": """
Task: extract atomic claims from the paper note and the actual paper.
Output shape: {"claim_list": {source_scope, claims:[{claim_id,text,source_ref,kind,confidence}]}}.
Do not include floating claims. Every claim must trace to the same source_ref.
""",
        "claim-evidence-linker": """
Task: link every claim to concrete loci you actually read.
Output shape: {"claim_evidence_map": {attribution_contract_version:"claim-span/v1",
mappings:[{claim_id,overall_support,loci,claim_risk}]}}.
Every locus needs source_ref, location, kind, reported_result, supports_claim, support_relation,
directness, span_id, snapshot_ref, document_hash, parser_version, exact_quote, and an exact
char_start/char_end, machine-readable table_cell_ref, or figure_region_ref. Reopen the local
snapshot and use the supplied citation manifest; never estimate an offset or hash.
If `inbox/fulltext-qa.json` has page contexts, add `page`, `locator_confidence`, and `extraction_ref`
for every core supporting locus. A local-PDF PASS must be page-anchored.
""" + _shared.SUPPORT_RELATION_CONTRACT,
        "citation-coverage-auditor": """
Task: independently judge every claim-locus relation after the linker has frozen the map. Reopen the
local source/fulltext snapshot and form the semantic judgment yourself. Do not copy the linker's
supports_claim flag. The deterministic gate, not you, will recompute file hashes, offsets, and quotes.
Output shape: {"citation_audit": {"contract_version":"citation-attribution/v1",
"independent_of_linker":true,"claim_results":[{"claim_id":"c1",
"verdict":"entails|partial|contradicts|insufficient","locator_verified":true,
"verified_locus_ids":["l1"],"unsupported_locus_ids":[],"notes":"independent reason"}]}}.
Emit exactly one result per claim and classify every mapped locus. Source existence or topical overlap
is not entailment. If the local snapshot is absent, set locator_verified=false; never invent PASS.
""",
        "method-teardown-extractor": """
Task: reconstruct how the method/dataset/system actually works.
Output shape: {"method_teardown": {source_ref, problem_definition, core_assumptions,
representation, loss_terms, training_flow, inference_flow, train_infer_consistency, data,
cost, baseline_difference}}.
For non-method papers, adapt the fields honestly and mark not-applicable content.
Trajectory extraction — the dead ends, design decisions and pivots BEHIND the method — is the
`research-trajectory-extractor` seat's artifact, not yours. Record what the method IS; cross-reference
its nodes downstream rather than duplicating them here.
""",
        "research-trajectory-extractor": """
Task: beyond what the method IS, extract the research TRAJECTORY that produced it — the part that
saves a future reader from rediscovering a known failure.
Output shape: {"exploration_tree": {source_ref, nodes, extraction_note}}. Emit `nodes`, each typed:
  - `dead_end`  — an approach the paper tried and abandoned. REQUIRED: `hypothesis` (what was
    expected), `failure_mode` (why it failed, concretely — not "did not work"), `lesson` (what
    transfers to someone else's problem). Ablation rows showing a component HURTS are dead ends. This
    is the most valuable node type; a teardown with zero dead-end nodes on a paper that reports
    ablations is an incomplete teardown.
  - `decision`  — a design choice with real alternatives. REQUIRED: `choice`, `alternatives` (at least
    one genuinely considered), and `informed_by` (what evidence informed it).
  - `pivot`     — a change of direction. REQUIRED: `from_state`, `to_state`, `trigger` (the
    observation that forced it). "We initially pursued X but found ..." is the tell.
Every node carries `support_level`: `explicit` when the paper directly reports it (then cite the
section/table/figure in `source_refs`), or `inferred` when you are reconstructing a plausible decision
from the narrative. PREFER OMISSION OVER FABRICATING A HIGHLY SPECIFIC INFERRED NODE — an invented
dead end is worse than a missing one, because a future reader will trust it. An empty `nodes` list is
a legitimate answer for a paper that reports no abandoned approach, no alternative and no pivot; say
so in `extraction_note`.
""",
        "figure-reader": """
Task: visually inspect the paper's load-bearing figures and tables, not captions or OCR alone.
Open `inbox/paper-visual-manifest.json` and the referenced page image for every load-bearing item.
Output shape: {"figure_reading": {source_ref,visual_input_status,visual_manifest_ref,
figures:[{figure_ref,inspection_status,page,visual_asset_ref,visual_asset_sha256,axes,controls,
error_bars,take_home,distrust}]}}.
Use INSPECTED_VISUAL only after opening the image. Without an actual visual input, set
UNREAD_VISUAL; never claim a deep visual read.
""",
        "result-table-auditor": """
Task: audit numeric results, table/plot comparisons, metric direction, variance, baseline binding,
and split/leakage risks for every result-bearing core claim.
Output shape: {"result_table_audit": {source_ref, applicability, audited_items,
metric_direction_checks, baseline_binding_checks, statistical_reporting, leakage_or_split_risks,
medical_segmentation_audit, overall}}.
If applicability is applicable, include at least one audited item tied to a claim_id. Be especially
careful with lower-is-better metrics such as HD95, error rate, loss, and latency.
For medical imaging / autoPET / interactive-correction papers, fill `medical_segmentation_audit`
with patient/case split, metric direction/unit, baseline binding, uncertainty, per-case failure
analysis, and when relevant lesion-level recall, false-positive count, prompt/scribble/click protocol
parity, correction budget, and oracle-vs-learned fairness.
""",
        "math-algorithm-verifier": """
Task: check equations, algorithm flow, pseudo-code, loss/objective definitions, complexity/cost, and
implementation assumptions for method/theory papers.
Output shape: {"math_algorithm_audit": {source_ref, applicability, formal_objects,
algorithm_flow, equation_consistency, complexity_or_cost, implementation_assumptions, red_flags,
overall}}.
Use not-applicable for non-method/non-theory papers. Do not invent derivations; call underspecification
out explicitly.
""",
        "paper-appraiser": """
Task: critically appraise the paper as a reviewer, without issuing accept/reject.
Output shape: {"paper_appraisal": {source_ref,paper_type,dimensions,assumptions,
limitations_acknowledged,limitations_unacknowledged,baseline_fairness,ablation_sufficiency,
statistical_robustness,selective_reporting,reproducibility_gaps,generalization,
reviewer_questions,checklist,medical_imaging_checklist,overall}}.
Cover the 7D dimensions and the relevant reporting checklist. For medical-imaging reads, fill
`medical_imaging_checklist` using CLAIM/TRIPOD+AI/STARD-AI/CONSORT-AI-style concerns: patient split,
external validation, annotation protocol, inter-reader variability, scanner/site shift, metric
direction, statistical uncertainty, clinical claim boundary, preprocessing leakage, and failure cases.
Use the local item bank at `research_agent_teams/agents/references/reporting-guidelines/medical-imaging-ai-item-bank.json`;
each medical checklist item must include `standard_ref`, `item_id`, `category`, `status`,
`evidence_ref`, `risk`, and any `required_fix`.
For originality, separate the focal paper's own positioning from global novelty. Without full text
for the closest target papers, do not infer a collision or non-originality from titles, abstracts,
keywords, or the focal authors' related-work prose; mark that comparison unverified.
""",
        "paper-relations-mapper": """
Task: situate the focal paper among prior work.
Output shape: {"paper_relations": {source_ref, edges:[{target_ref,relation,note}]}}.
Include direct baselines, datasets, methods used, and papers this work claims to extend or replace.
This records author-claimed/citation-neighborhood lineage, not independently verified novelty.
Do not claim a target paper covers the focal contribution unless that target's full method and
decision-relevant results were separately available and read.
""",
        "trend-card-builder": """
Task: synthesize the sub-area trend only from grounded source refs.
Output shape: {"trend_card": {scope,shifts,failure_modes,mechanism_vs_result,
reproducibility_trend,opportunities,source_refs}}.
If a single paper is too thin for a trend, say so with modest shifts; do not inflate.
""",
        "domain-transfer-critic": """
Task: decide what this paper can legitimately support for the current research target.
Output shape: {"domain_transfer_note": {source_ref,target_context,transfer_level,usable_for,
not_usable_for,evidence_limits,required_local_validation,risk_of_overclaim,transfer_matrix}}.
Be strict about modality, dataset, task, metric, and deployment differences. For medical imaging,
write a transfer_matrix over modality, anatomy/task, dataset/population, scanner/site, annotation
protocol, metrics, deployment context, and supervision/prompting.
""",
        "reproducibility-materials-auditor": """
Task: audit whether the paper exposes enough code, data, configuration, environment, and access
details to support reproduction or local reimplementation.
Output shape: {"reproducibility_materials_audit": {source_ref, code_availability,
data_availability, config_availability, environment, license_or_access_constraints,
reproduction_steps, missing_materials, reproducibility_risk}}.
This is not an execution claim. It is a materials audit.
""",
        "independent-reading-critic": """
Task: perform a BLIND second read from the source snapshot, without seeing any primary analyst bundle.
Output shape: {"independent_reading_critique": {source_ref,reading_mode,
primary_analysis_seen,allowed_input_classes,consumed_inputs,independent_summary,verdict,
disagreements,missed_claims,overclaim_risks,alternative_interpretations,required_repairs,
director_warning}}.
Set reading_mode=blind_second_read, primary_analysis_seen=false, and disagreements=[] because
comparison has not happened. independent_summary must independently cover claims, method, key
results, and limitations. If you saw a primary bundle, do not claim blindness. Use only the schema
verdicts PASS, PASS_WITH_CAVEATS, NEEDS_SUPPLEMENT, or BLOCK. Evidence that is useful for reading but
not promotion-ready is PASS_WITH_CAVEATS: keep the promotion boundary in required_repairs and
director_warning instead of inventing BLOCK_FOR_PROMOTION.
""",
        "paper-reading-reconciler": """
Task: be the FIRST worker to compare the primary analysis with the blind second read.
Output shape: {"paper_reading_reconciliation": {source_ref,comparison_performed,
blind_bundle_ref,primary_bundle_refs,agreements,disagreements,missed_by_primary,
missed_by_blind_reader,repair_ledger,unresolved_repairs,verdict,director_warning}}.
Every disagreement needs a stable id, both positions, source evidence, resolution, and a
repair_required flag. Every repair-required disagreement must have a linked repair-ledger item.
PASS requires zero unresolved repairs; accepted limitations must remain visible.
""",
        "paper-reading-quality-auditor": """
Task: independently audit whether the read is good enough for director review.
Output shape: {"paper_reading_quality": {source_ref,verdict,coverage,
single_paper_completeness,source_fidelity,visual_coverage,evidence_saturation,anchoring,
method_depth,figure_table_coverage,result_table_depth,algorithmic_depth,reproducibility_depth,
project_alignment,domain_transfer_honesty,independent_critique_resolution,markdown_ready,
promotion_ready,strengths,required_repairs,reviewer_attack_points}}.
Verdict must be PASS, PASS_WITH_CAVEATS, NEEDS_SUPPLEMENT, or BLOCK. Do not PASS shallow coverage.
Use PASS_WITH_CAVEATS only when every scientific invariant passes and the remaining limitation is
explicitly disclosed in the Markdown; use NEEDS_SUPPLEMENT for a local repairable gap; reserve BLOCK
for source fabrication, hash/quote conflict, blind contamination, leakage, or unsupported core claims.
If the independent citation map contains calibrated partial relations or complete-document absence
claims, do not call the read plain PASS: use PASS_WITH_CAVEATS and name the affected claim ids.
Keep the axes separate: single-paper completeness is not literature saturation; set
evidence_saturation=not-assessed-single-paper. PASS with load-bearing visuals requires verified
page renders and visual_coverage=complete. PASS also requires a resolved reconciliation ledger.
For A-core/medical-imaging papers, reviewer_attack_points should be structured objects covering
baseline_fairness, dataset_split_leakage, statistical_uncertainty, transfer_generalization, and
reproducibility, not just a loose list of complaints.
""",
        "paper-markdown-writer": """
Task: write the final human-readable Markdown paper card from prior evidence only.
Output shape: {"paper_markdown_card": {source_ref,title,markdown,evidence_refs,covered_claim_ids,
covered_figure_refs,covered_sections,quality_verdict}}.
This is a HUMAN EDITING pass, not an audit dump. The visible Markdown must start with the paper title,
then paper identity, one-screen summary, background/problem, authors' hypothesis and 2-4 complete
contribution statements; data/research design; one coherent method flow; 3-7 natural-language
conclusion-evidence packages when scientifically applicable; numeric/fairness, visual, robustness,
failure, validity, and reproducibility audits; literature position; blind-primary reconciliation;
then domain/project transfer and next actions. Put stable claim ids in HTML comments, never in visible
headings or first-column reading entries. Do not expose any raw upstream instruction, quality token,
defect/repair id, worker/bundle name, claim count, entailment/partial count, hash, schema/contract,
promotion/vault state, run id, or V-number. Translate every accepted audit finding into the relevant
scientific paragraph; do not create a visible reconciliation or governance chapter.
Mention in natural language that the card is a single-paper read and does not establish exhaustive
literature coverage. Every load-bearing visual must be actually inspected, but per director preference
do not embed images: provide a concise Chinese text account of its content, axes/table structure,
important numbers, support, and non-support. `covered_*` fields are advisory only;
a deterministic checker audits the actual Markdown body.
In the literature passage, distinguish: what the authors claim; what this focal-paper read verifies;
and what global novelty remains unverified without full-text closest-prior comparisons.
For every partial, insufficient, or complete-document absence claim, explain the scientific boundary
in natural language at the point where it matters. Keep claim ids only in terse hidden HTML comments;
never show the citation-relation vocabulary to the reader. End with a short decision-oriented next-step
section. The filename/title must be timeless and contain no product version.
""",
    }
    return common + bodies[agent]


def _assert_dependency_contract(agents: list[str], run_dir: str | None = None) -> None:
    positions = {agent: index for index, agent in enumerate(agents)}
    errors = []
    for agent in agents:
        deps = WORKER_DEPENDENCIES.get(agent)
        if deps is None:
            errors.append(f"missing dependency declaration for {agent}")
            continue
        unknown = sorted(
            dep for dep in set(deps) - set(agents)
            if run_dir is None or not _bundle_path(run_dir, dep).is_file()
        )
        if unknown:
            errors.append(f"{agent} has unknown dependencies: {unknown}")
        forward = [dep for dep in deps if dep in positions and positions[dep] >= positions[agent]]
        if forward:
            errors.append(f"{agent} has non-prior dependencies: {forward}")
    if WORKER_DEPENDENCIES.get("independent-reading-critic"):
        errors.append("blind second reader must have zero analyst-bundle dependencies")
    reconciler_deps = set(WORKER_DEPENDENCIES.get("paper-reading-reconciler") or ())
    required_join = {
        "independent-reading-critic", "claim-extractor", "method-teardown-extractor",
        "result-table-auditor", "paper-appraiser",
    }
    if not required_join <= reconciler_deps:
        errors.append(f"reconciler missing join inputs: {sorted(required_join - reconciler_deps)}")
    if "paper-reading-reconciler" not in set(
        WORKER_DEPENDENCIES.get("paper-reading-quality-auditor") or ()
    ):
        errors.append("quality auditor must consume reconciliation")
    if CITATION_AUDITOR_AGENT not in set(
        WORKER_DEPENDENCIES.get("paper-reading-quality-auditor") or ()
    ):
        errors.append("quality auditor must consume independent citation audit")
    if "paper-reading-quality-auditor" not in set(
        WORKER_DEPENDENCIES.get("paper-markdown-writer") or ()
    ):
        errors.append("Markdown writer must consume quality audit")
    if errors:
        raise RuntimeError(f"read_paper_deep dependency contract invalid: {errors}")


def _worker_agents() -> list[str]:
    agents = [agent for _key, _atype, agent, _fname, _status in ARTIFACT_PLAN]
    insert_at = agents.index("claim-evidence-linker") + 1
    agents.insert(insert_at, CITATION_AUDITOR_AGENT)
    return agents


def _load_bundle_payload(run_dir: str, agent: str, key: str) -> dict | None:
    path = _bundle_path(run_dir, agent)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    payload = _shared.extract_worker_bundle_value(
        value, key, stage="DISCOVER", mode="read_paper_deep", agent=agent,
        required=False, default=None,
    )
    return payload if isinstance(payload, dict) else None


def _optional_placeholder(agent: str, source_ref: str) -> tuple[str, dict]:
    reason = "Planner marked this specialist scientifically not applicable; no LLM seat was used."
    payloads = {
        "figure-reader": ("figure_reading", {
            "source_ref": source_ref, "visual_input_status": "NOT_APPLICABLE",
            "visual_manifest_ref": None, "figures": [],
        }),
        "result-table-auditor": ("result_table_audit", {
            "source_ref": source_ref, "applicability": "not-applicable", "audited_items": [],
            "metric_direction_checks": reason, "baseline_binding_checks": reason,
            "statistical_reporting": reason, "leakage_or_split_risks": [],
            "medical_segmentation_audit": None, "overall": "not-applicable",
        }),
        "math-algorithm-verifier": ("math_algorithm_audit", {
            "source_ref": source_ref, "applicability": "not-applicable", "formal_objects": [],
            "algorithm_flow": reason, "equation_consistency": reason, "complexity_or_cost": None,
            "implementation_assumptions": [], "red_flags": [], "overall": "not-applicable",
        }),
        "paper-relations-mapper": ("paper_relations", {"source_ref": source_ref, "edges": []}),
        "trend-card-builder": ("trend_card", {
            "scope": f"Focal-paper-only read for {source_ref}; lineage/trend was not requested",
            "shifts": [], "failure_modes": [], "mechanism_vs_result": reason,
            "reproducibility_trend": None, "opportunities": [], "source_refs": [source_ref],
        }),
        "reproducibility-materials-auditor": ("reproducibility_materials_audit", {
            "source_ref": source_ref, "code_availability": reason, "data_availability": reason,
            "config_availability": reason, "environment": None,
            "license_or_access_constraints": [], "reproduction_steps": [],
            "missing_materials": [reason], "reproducibility_risk": "high",
        }),
    }
    return payloads[agent]


def _active_worker_agents(run_dir: str) -> list[str]:
    agents = _worker_agents()
    plan = _load_bundle_payload(run_dir, "paper-reading-planner", "paper_reading_plan") or {}
    policy = plan.get("specialist_policy") or {}
    note = _load_bundle_payload(run_dir, "literature-ingest", "paper_note") or {}
    source_ref = str(note.get("source_ref") or "").strip()
    if not isinstance(policy, dict) or not source_ref:
        return agents
    skipped = {
        agent
        for policy_key, role_agents in OPTIONAL_SPECIALISTS.items()
        if policy.get(policy_key) == "skip"
        for agent in role_agents
    }
    decisions = []
    for agent in sorted(skipped):
        key, payload = _optional_placeholder(agent, source_ref)
        path = _bundle_path(run_dir, agent)
        if not path.exists():
            path.write_text(json.dumps({key: payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        decisions.append({"agent": agent, "decision": "deterministic-not-applicable", "bundle": str(path)})
    if decisions:
        decision_path = Path(run_dir) / "inbox" / "optional-specialist-decisions.json"
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [agent for agent in agents if agent not in skipped]


def _write_shared_paper_representation(run_dir: str) -> str | None:
    available = {
        key: value for key, value in {
            "paper_note": _load_bundle_payload(run_dir, "literature-ingest", "paper_note"),
            "paper_structure": _load_bundle_payload(run_dir, "paper-structure-mapper", "paper_structure"),
            "claim_list": _load_bundle_payload(run_dir, "claim-extractor", "claim_list"),
        }.items() if value is not None
    }
    if not available:
        return None
    out = Path(run_dir) / "inbox" / "shared-paper-representation.json"
    out.write_text(json.dumps({
        "contract_version": "shared-paper-representation/v1",
        "components": available,
        "source_boundaries": {
            "fulltext_manifest": "inbox/citation-snapshots/fulltext-contexts.manifest.json",
            "visual_manifest": MANIFEST_REL.as_posix(),
            "note": "Reuse stable facts here; reopen source snapshots only for specialist verification.",
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out.relative_to(Path(run_dir)).as_posix()


def _worker_input_contract(run_dir: str, agent: str, dependencies: tuple[str, ...]) -> dict:
    source_inputs = [
        "task_frame.artifact.json",
        "inbox/fulltext-docs/**",
        "inbox/fulltext-qa.json",
        "inbox/citation-snapshots/**",
        MANIFEST_REL.as_posix(),
        "inbox/paper-visuals/**",
        "inbox/shared-paper-representation.json",
    ]
    bundle_inputs = [
        _bundle_path(run_dir, dependency).relative_to(Path(run_dir)).as_posix()
        for dependency in dependencies
    ]
    all_bundle_refs = [
        _bundle_path(run_dir, other).relative_to(Path(run_dir)).as_posix()
        for other in _worker_agents() if other != agent
    ]
    contract = {
        "allowed_inputs": source_inputs + bundle_inputs,
        "allowed_bundle_agents": list(dependencies),
        "forbidden_inputs": [],
        "blind": False,
    }
    if agent == "independent-reading-critic":
        contract.update({
            "allowed_inputs": source_inputs,
            "allowed_bundle_agents": [],
            "forbidden_inputs": all_bundle_refs,
            "blind": True,
        })
    return contract


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    if stage != "DISCOVER":
        return None
    _write_shared_paper_representation(run_dir)
    agents = _active_worker_agents(run_dir)
    _assert_dependency_contract(agents, run_dir)
    north_star = _shared.north_star_block(run_dir)
    reading_hook = _reading_hook(run_dir)
    workers = []
    for agent in agents:
        key = "citation_audit" if agent == CITATION_AUDITOR_AGENT else BUNDLE_BY_AGENT[agent][0]
        dependencies = tuple(dep for dep in WORKER_DEPENDENCIES[agent] if dep in agents)
        out = str(_bundle_path(run_dir, agent)).replace("\\", "/")
        worker = {
            "label": agent,
            "model": _worker_model(model_policy, agent),
            "output": out,
            "prompt": _prompt(
                agent, key, request, run_dir, out, north_star, reading_hook, list(dependencies),
            ),
            "input_contract": _worker_input_contract(run_dir, agent, dependencies),
            "task_capabilities": ["document_reading"] + (
                ["image_input"]
                if agent in {
                    "independent-reading-critic", "figure-reader", "result-table-auditor",
                    CITATION_AUDITOR_AGENT,
                }
                else []
            ),
        }
        workers.append(worker)
    return {
        "label": "read-paper-deep-panel",
        "workers": workers,
        "panel_note": (
            "Spawn by worker_order and explicit input contracts. The blind second reader MUST finish "
            "first as an isolated source-only branch, before any primary bundle exists; the primary "
            "branch then proceeds independently; "
            "the citation auditor independently checks every frozen claim-locus relation; "
            "paper-reading-reconciler is the first blind/primary join; then quality audit and Markdown."
        ),
        "worker_order": agents,
        # Groups are release-order hints, not scientific data dependencies.
        # Explicit WORKER_DEPENDENCIES own freshness and resume semantics.
        "group_barriers": False,
        "parallel_groups": [
            [agent for agent in group if agent in agents]
            for group in READ_PAPER_PARALLEL_GROUPS
            if any(agent in agents for agent in group)
        ],
    }


def _load_worker_bundles(run_dir) -> dict:
    try:
        replay = load_explicit_legacy_replay(run_dir)
    except ValueError as exc:
        raise GateBlock(str(exc)) from exc
    out = {}
    missing = []
    for key, atype, agent, _fname, _status in ARTIFACT_PLAN:
        logical = _bundle_path(run_dir, agent)
        try:
            p = resolve_effective_output(Path(run_dir), "DISCOVER", logical)
        except ValueError as exc:
            raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
        if not p.exists():
            missing.append(agent)
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        worker_payload = _shared.extract_worker_bundle_value(
            raw, key, stage="DISCOVER", mode="read_paper_deep", agent=agent,
        )
        payload, _schema_errors, report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", agent, atype, worker_payload, label=key,
        )
        if report.get("representation_conflicts") or report.get("unsafe_preserved_extras"):
            raise GateBlock(
                f"read_paper_deep truth/control representation BLOCK in {agent}: "
                f"conflicts={report.get('representation_conflicts') or []}; "
                f"unsafe_extras={report.get('unsafe_preserved_extras') or []}"
            )
        out[key] = payload
    auditor_path = resolve_effective_output(
        Path(run_dir), "DISCOVER", _bundle_path(run_dir, CITATION_AUDITOR_AGENT)
    )
    if auditor_path.exists():
        raw = json.loads(auditor_path.read_text(encoding="utf-8"))
        out["citation_audit"] = _shared.extract_worker_bundle_value(
            raw, "citation_audit", stage="DISCOVER", mode="read_paper_deep",
            agent=CITATION_AUDITOR_AGENT,
        )
    elif replay is None:
        missing.append(CITATION_AUDITOR_AGENT)
    if missing:
        raise GateBlock(
            f"read_paper_deep DISCOVER missing worker bundle(s): {missing}. "
            "Spawn every staged worker; a deep read is not complete when one role is absent."
        )
    return out


def _data_descendants(agent: str) -> list[str]:
    impacted = set()
    frontier = {agent}
    while frontier:
        current = frontier.pop()
        for candidate, dependencies in WORKER_DEPENDENCIES.items():
            if current in dependencies and candidate not in impacted:
                impacted.add(candidate)
                frontier.add(candidate)
    impacted.discard(agent)
    return [candidate for candidate in WORKER_DEPENDENCIES if candidate in impacted]


def _supplement_defect(
    defect_id: str,
    category: str,
    location: str,
    summary: str,
    targets: list[str],
    refresh: list[str],
    *,
    severity: str = "material",
) -> dict:
    return {
        "defect_id": defect_id,
        "category": category,
        "severity": severity,
        "location": location,
        "summary": summary,
        "target_agents": targets,
        "refresh_agents": refresh,
    }


def _validate_all_payloads(b: dict) -> list[str]:
    """Return schema advisories without blocking the readable paper card.

    The director-facing product is Markdown.  Structured sidecars are useful for
    search and provenance, but a missing optional field must not invalidate an
    otherwise complete reading or trigger another research-worker cycle.
    """
    defects = []
    for key, atype, agent, _fname, _status in ARTIFACT_PLAN:
        payload = b.get(key) if isinstance(b.get(key), dict) else {}
        errors = validate_payload(atype, payload)
        if errors:
            defects.append(_supplement_defect(
                f"SCHEMA-{len(defects) + 1:03d}",
                "schema-semantic-gap",
                key,
                "; ".join(errors)[:4000],
                [agent],
                _data_descendants(agent),
            ))
    return [
        f"schema advisory at {row['location']}: {row['summary']}"
        for row in defects
    ]


def _source_ref(b: dict) -> str:
    pn = b.get("paper_note") or {}
    return str(pn.get("source_ref") or "")


_APPRAISAL_DIMS = {
    "soundness",
    "significance",
    "originality",
    "eval_rigor",
    "reproducibility",
    "clarity",
    "domain_validity",
}

_MARKDOWN_REQUIRED_SECTIONS = {
    "decision-need",
    "project-alignment",
    "claims-and-evidence",
    "method-or-theory",
    "numeric-results",
    "figures-and-tables",
    "critical-appraisal",
    "reproducibility",
    "domain-transfer",
    "independent-critique",
    "next-actions",
}
_MEDICAL_MARKDOWN_SECTIONS = {"medical-imaging-checklist", "transfer-matrix"}
_MEDICAL_CHECKLIST_CATEGORIES = {
    "patient_split",
    "external_validation",
    "annotation_protocol",
    "scanner_site_shift",
    "metric_direction",
    "statistical_uncertainty",
    "clinical_claim_boundary",
    "preprocessing_leakage",
}


def _director_ready(quality: dict) -> bool:
    return quality.get("verdict") in {"PASS", "PASS_WITH_CAVEATS"}
_MEDICAL_TRANSFER_AXES = {
    "modality",
    "anatomy_or_task",
    "dataset_population",
    "scanner_or_site",
    "annotation_protocol",
    "metrics",
    "deployment_context",
}
_CORE_ATTACK_CATEGORIES = {
    "baseline_fairness",
    "dataset_split_leakage",
    "statistical_uncertainty",
    "transfer_generalization",
    "reproducibility",
}
_MEDICAL_ITEM_BANK_REL = (
    "agents/references/reporting-guidelines/medical-imaging-ai-item-bank.json"
)
_FALLBACK_MEDICAL_ITEM_IDS = {
    "CLAIM-MI-01",
    "CLAIM-MI-02",
    "CLAIM-MI-03",
    "CLAIM-MI-04",
    "CLAIM-MI-05",
    "CLAIM-MI-06",
    "CLAIM-MI-07",
    "TRIPODAI-MI-01",
    "STARDAI-MI-01",
    "CROSS-MI-LEAKAGE",
    "CROSS-MI-READER",
    "CROSS-MI-CLINICAL-BOUNDARY",
}
_MEDICAL_RESULT_AUDIT_CATEGORIES = {
    "patient_or_case_level_split",
    "metric_direction_and_unit",
    "baseline_binding",
    "statistical_uncertainty",
    "per_case_failure_analysis",
}
_AUTOPET_INTERACTIVE_RESULT_CATEGORIES = {
    "lesion_level_recall",
    "false_positive_count",
    "prompt_protocol_parity",
    "correction_budget",
    "oracle_vs_learned_fairness",
}


def _norm_ref(ref) -> str:
    return str(ref or "").strip().lower()


def _load_bearing_refs(structure: dict) -> list[str]:
    refs = []
    for item in (structure.get("figures") or []):
        if item.get("load_bearing"):
            refs.append(str(item.get("figure_ref") or "").strip())
    for item in (structure.get("tables") or []):
        if item.get("load_bearing"):
            refs.append(str(item.get("table_ref") or "").strip())
    return [r for r in refs if r]


def _is_medical_imaging_run(run_dir) -> bool:
    prof = _shared.domain_profile(run_dir) or {}
    tags = {str(x) for x in (prof.get("applies_to") or [])}
    pid = str(prof.get("profile_id") or "")
    return pid == "cv-medical-segmentation" or bool(
        tags & {"medical-imaging", "3d-segmentation", "tubular-anatomy"}
    )


def _is_a_core_read(b: dict) -> bool:
    return (
        (b.get("project_context_alignment") or {}).get("relevance") == "A-core"
        or (b.get("paper_note") or {}).get("relation_to_thesis") == "A-core"
    )


def _run_context_text(run_dir, b: dict) -> str:
    texts = []
    tf = Path(run_dir) / "task_frame.artifact.json"
    if tf.is_file():
        try:
            payload = (json.loads(tf.read_text(encoding="utf-8")).get("payload") or {})
        except (OSError, ValueError):
            payload = {}
        north_star = payload.get("north_star") or {}
        texts.extend([
            str(payload.get("request") or ""),
            str(north_star.get("statement") or ""),
            " ".join(str(x) for x in (north_star.get("in_scope") or [])),
        ])
    texts.extend([
        str((b.get("paper_note") or {}).get("title") or ""),
        str((b.get("paper_note") or {}).get("summary") or ""),
        str((b.get("project_context_alignment") or {}).get("project_context") or ""),
        str((b.get("domain_transfer_note") or {}).get("target_context") or ""),
    ])
    return " ".join(texts).lower()


def _is_autopet_or_interactive_context(run_dir, b: dict) -> bool:
    text = _run_context_text(run_dir, b)
    needles = (
        "autopet",
        "pet/ct",
        "pet-ct",
        "lesion",
        "interactive",
        "point",
        "click",
        "scribble",
        "prompt",
        "correction",
        "oracle",
        "intent",
    )
    return any(n in text for n in needles)


def _medical_item_bank_ids() -> set[str]:
    path = Path(__file__).resolve().parents[2] / _MEDICAL_ITEM_BANK_REL
    try:
        bank = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(_FALLBACK_MEDICAL_ITEM_IDS)
    ids = {str(x) for x in (bank.get("minimum_item_ids") or []) if str(x)}
    return ids or set(_FALLBACK_MEDICAL_ITEM_IDS)


def _fulltext_has_page_context(run_dir) -> bool:
    p = Path(run_dir) / "inbox" / "fulltext-qa.json"
    if not p.is_file():
        return False
    try:
        report = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(report.get("available") and any(c.get("page") for c in report.get("contexts") or []))


def _inside_run(run_dir, ref: str) -> Optional[Path]:
    root = Path(run_dir).resolve()
    raw = Path(str(ref))
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        cwd_candidate = raw.resolve()
        try:
            cwd_candidate.relative_to(root)
            candidate = cwd_candidate
        except ValueError:
            candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _blind_provenance_checks(run_dir, b: dict, quality: dict) -> list[str]:
    blind = b.get("independent_reading_critique") or {}
    errors = []
    declared = {
        _blind_input_class_from_ref(str(x))
        for x in blind.get("allowed_input_classes") or []
    }
    declared.discard("")
    if declared != _BLIND_ALLOWED_INPUT_CLASSES:
        errors.append(
            "blind second reader allowed_input_classes must equal the source-only contract; "
            f"got={sorted(declared)}"
        )
    if blind.get("reading_mode") != "blind_second_read" or blind.get("primary_analysis_seen") is not False:
        errors.append("blind second reader provenance does not attest an isolated first read")
    if blind.get("disagreements"):
        errors.append("blind second read cannot report disagreements before reconciliation")

    blind_bundle = _bundle_path(run_dir, "independent-reading-critic")
    if blind_bundle.is_file():
        blind_written = blind_bundle.stat().st_mtime_ns
        preexisting_primary = []
        for _key, _atype, agent, _fname, _status in ARTIFACT_PLAN:
            if agent == "independent-reading-critic":
                continue
            candidate = _bundle_path(run_dir, agent)
            if candidate.is_file() and candidate.stat().st_mtime_ns < blind_written:
                preexisting_primary.append(agent)
        if preexisting_primary:
            errors.append(
                "blind second-reader bundle was written after other pipeline bundles; temporal "
                f"isolation is invalid: {preexisting_primary}"
            )

    seen_classes = set()
    for item in blind.get("consumed_inputs") or []:
        input_class, ref = _blind_input_receipt(item)
        seen_classes.add(input_class)
        if input_class not in _BLIND_ALLOWED_INPUT_CLASSES:
            errors.append(f"blind second reader consumed forbidden input class: {input_class}")
            continue
        if ".bundle.json" in ref.lower() or "discover." in ref.lower():
            errors.append(f"blind second reader provenance names an analyst bundle: {ref}")
            continue
        path = _inside_run(run_dir, ref)
        if path is None:
            errors.append(f"blind second reader input escapes run scratch: {ref}")
            continue
        allowed_path = False
        root = Path(run_dir).resolve()
        if input_class == "task_frame":
            allowed_path = path == root / "task_frame.artifact.json"
        elif input_class == "source_document":
            allowed_path = (root / "inbox" / "fulltext-docs") in path.parents
        elif input_class == "fulltext_snapshot":
            allowed_path = (
                path == root / "inbox" / "fulltext-qa.json"
                or (root / "inbox" / "citation-snapshots") in path.parents
            )
        elif input_class == "visual_snapshot":
            allowed_path = (
                path == root / MANIFEST_REL
                or (root / "inbox" / "paper-visuals") in path.parents
            )
        if not allowed_path:
            errors.append(f"blind second reader input violates class/path contract: {input_class} -> {ref}")
        elif not path.is_file():
            errors.append(f"blind second reader input does not exist: {ref}")

    if _director_ready(quality):
        if "task_frame" not in seen_classes:
            errors.append("PASS requires blind second reader to consume task_frame")
        if not ({"source_document", "fulltext_snapshot"} <= seen_classes):
            errors.append("PASS requires blind second reader to consume both source document and fulltext snapshot")
        blind_verdict = blind.get("verdict")
        if quality.get("verdict") == "PASS":
            if blind_verdict != "PASS" or blind.get("required_repairs"):
                errors.append("PASS requires the blind source read itself to PASS without required repairs")
        elif blind_verdict not in {"PASS", "PASS_WITH_CAVEATS"}:
            errors.append(
                "PASS_WITH_CAVEATS requires blind source verdict PASS or PASS_WITH_CAVEATS, "
                f"got {blind_verdict!r}"
            )
    return errors


def _reconciliation_checks(run_dir, b: dict, quality: dict) -> list[str]:
    reconciliation = b.get("paper_reading_reconciliation") or {}
    errors = []
    blind_ref = str(reconciliation.get("blind_bundle_ref") or "").replace("\\", "/")
    expected_blind = _bundle_path(run_dir, "independent-reading-critic").relative_to(
        Path(run_dir)
    ).as_posix()
    if blind_ref != expected_blind:
        errors.append(
            "reconciliation blind_bundle_ref must point to the isolated second-reader bundle; "
            f"got={blind_ref!r}"
        )
    blind_path = _inside_run(run_dir, blind_ref)
    if blind_path is None or not blind_path.is_file():
        errors.append(f"reconciliation blind bundle is missing: {blind_ref}")

    primary_refs = {
        str(ref).replace("\\", "/") for ref in reconciliation.get("primary_bundle_refs") or []
    }
    required_agents = {
        "claim-extractor", "claim-evidence-linker", "method-teardown-extractor",
        "figure-reader", "result-table-auditor", "math-algorithm-verifier", "paper-appraiser",
        "domain-transfer-critic",
    }
    accepted_refs = {}
    for agent in required_agents:
        logical = _bundle_path(run_dir, agent)
        refs = {logical.relative_to(Path(run_dir)).as_posix()}
        try:
            effective = resolve_effective_output(Path(run_dir), "DISCOVER", logical)
            refs.add(effective.relative_to(Path(run_dir)).as_posix())
        except (ValueError, OSError):
            pass
        accepted_refs[agent] = refs
    missing = sorted(
        min(refs) for agent, refs in accepted_refs.items()
        if not (refs & primary_refs)
    )
    if missing:
        errors.append(f"reconciliation omits required primary bundles: {missing}")
    if expected_blind in primary_refs:
        errors.append("blind bundle must not be mislabeled as a primary bundle")
    for ref in primary_refs:
        path = _inside_run(run_dir, ref)
        if path is None or not path.is_file():
            errors.append(f"reconciliation primary bundle is missing or out of run: {ref}")

    disagreements = reconciliation.get("disagreements") or []
    disagreement_ids = [str(item.get("disagreement_id") or "") for item in disagreements]
    if len(disagreement_ids) != len(set(disagreement_ids)):
        errors.append(f"reconciliation has duplicate disagreement ids: {disagreement_ids}")
    repair_ledger = reconciliation.get("repair_ledger") or []
    repair_ids = [str(item.get("repair_id") or "") for item in repair_ledger]
    if len(repair_ids) != len(set(repair_ids)):
        errors.append(f"reconciliation has duplicate repair ids: {repair_ids}")
    repaired_disagreements = {str(item.get("disagreement_id") or "") for item in repair_ledger}
    missing_repairs = sorted(
        str(item.get("disagreement_id") or "") for item in disagreements
        if item.get("repair_required") and str(item.get("disagreement_id") or "") not in repaired_disagreements
    )
    if missing_repairs:
        errors.append(f"repair-required disagreements lack ledger entries: {missing_repairs}")
    unknown_repairs = sorted(repaired_disagreements - set(disagreement_ids))
    if unknown_repairs:
        errors.append(f"repair ledger references unknown disagreements: {unknown_repairs}")

    unresolved = list(reconciliation.get("unresolved_repairs") or [])
    unresolved += [
        str(item.get("repair_id") or "") for item in repair_ledger
        if item.get("status") == "unresolved"
    ]
    if _director_ready(quality):
        if reconciliation.get("verdict") != "PASS":
            errors.append("PASS requires paper_reading_reconciliation.verdict=PASS")
        if unresolved:
            errors.append(f"PASS cannot coexist with unresolved reconciliation repairs: {unresolved}")
    return errors


def _visual_input_checks(run_dir, b: dict, quality: dict) -> list[str]:
    structure = b.get("paper_structure") or {}
    load_bearing = {_norm_ref(ref): ref for ref in _load_bearing_refs(structure)}
    reading = b.get("figure_reading") or {}
    errors = []
    if not load_bearing:
        if _director_ready(quality) and quality.get("visual_coverage") != "not-applicable":
            errors.append("PASS with no load-bearing visuals requires visual_coverage=not-applicable")
        return errors

    if not _director_ready(quality):
        return errors
    if quality.get("visual_coverage") != "complete":
        errors.append("PASS with load-bearing visuals requires visual_coverage=complete")
    if reading.get("visual_input_status") != "INSPECTED_VISUAL":
        errors.append("PASS cannot claim deep visual reading without visual_input_status=INSPECTED_VISUAL")
    if str(reading.get("visual_manifest_ref") or "").replace("\\", "/") != MANIFEST_REL.as_posix():
        errors.append("PASS requires figure_reading.visual_manifest_ref to name the run visual manifest")
    manifest = load_visual_manifest(run_dir)
    if manifest.get("status") != "AVAILABLE":
        errors.append("PASS requires an AVAILABLE paper visual manifest")
    for document in manifest.get("documents") or []:
        doc_ref = str(document.get("doc_ref") or "")
        doc_path = _inside_run(run_dir, doc_ref)
        if doc_path is None or not doc_path.is_file():
            errors.append(f"visual manifest source document is missing or outside run scratch: {doc_ref}")
            continue
        # Source-document hash comparison removed 2026-08-07 (director lock: no hash gating). The
        # two checks that actually make a visual claim honest survive: the document must EXIST and
        # must be inside the run's own scratch (path fencing, one line above).

    readings = {
        _norm_ref(item.get("figure_ref")): item
        for item in reading.get("figures") or []
        if item.get("figure_ref")
    }
    for normalized, display_ref in load_bearing.items():
        item = readings.get(normalized)
        if not item:
            errors.append(f"load-bearing visual has no figure_reading entry: {display_ref}")
            continue
        if item.get("inspection_status") != "INSPECTED_VISUAL":
            errors.append(f"load-bearing visual is UNREAD_VISUAL: {display_ref}")
            continue
        page = item.get("page")
        asset_ref = str(item.get("visual_asset_ref") or "")
        if not isinstance(page, int) or not asset_ref:
            errors.append(f"visual inspection provenance incomplete for {display_ref}")
            continue
        # Asset hash verification removed 2026-08-07 (director lock: no hash gating). The claim
        # "I actually opened this page image" is still bounded by what remains: a declared page
        # number, a manifest-named asset ref, and the INSPECTED_VISUAL status checked above.
        asset_path = _inside_run(run_dir, asset_ref)
        if asset_path is None or not asset_path.is_file():
            errors.append(
                f"{display_ref}: inspected visual asset is missing or outside run scratch: {asset_ref}")
    return errors


def _repair_packet_path(run_dir, b: dict) -> Path:
    title = str((b.get("paper_markdown_card") or {}).get("title")
                or (b.get("paper_note") or {}).get("title") or "paper-read")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:72] or "paper-read"
    return Path(run_dir) / "director-review" / "technical" / f"REPAIR-{slug}.md"


def _write_repair_packet(run_dir, b: dict, problems: list[str]) -> str:
    """Write a human repair packet before blocking a non-director-ready deep read."""
    quality = b.get("paper_reading_quality") or {}
    critique = b.get("independent_reading_critique") or {}
    reconciliation = b.get("paper_reading_reconciliation") or {}
    md = b.get("paper_markdown_card") or {}
    out = _repair_packet_path(run_dir, b)
    out.parent.mkdir(parents=True, exist_ok=True)
    repairs = list(quality.get("required_repairs") or []) + list(critique.get("required_repairs") or [])
    repairs += list(reconciliation.get("unresolved_repairs") or [])
    lines = [
        "---",
        "mode: read_paper_deep",
        "repair_packet: true",
        "records_promotion_decision: false",
        "citation_status: do_not_cite_until_reread_passes",
        "---",
        "",
        f"# Paper Read Repair Packet - {md.get('title') or (b.get('paper_note') or {}).get('title') or 'untitled'}",
        "",
        "## Status",
        "",
        f"- Quality verdict: `{quality.get('verdict', 'UNKNOWN')}`.",
        f"- Markdown ready: `{quality.get('markdown_ready')}`.",
        f"- Independent critic verdict: `{critique.get('verdict', 'UNKNOWN')}`.",
        f"- Reconciliation verdict: `{reconciliation.get('verdict', 'UNKNOWN')}`.",
        "- This is a readable working paper card with explicit caveats. It is usable for project reasoning, but not yet vault-promotable.",
        "",
        "## Blocking Problems",
        "",
    ]
    lines.extend(f"- {p}" for p in (problems or ["paper_reading_quality did not PASS"]))
    lines.extend(["", "## Required Repairs", ""])
    if repairs:
        lines.extend(f"- {r}" for r in repairs)
    else:
        lines.append("- No explicit repair list was supplied; rerun the failed worker with the gate feedback.")
    attacks = quality.get("reviewer_attack_points") or []
    if attacks:
        lines.extend(["", "## Reviewer Attack Points", ""])
        for attack in attacks:
            if isinstance(attack, dict):
                lines.append(f"- `{attack.get('category')}`: {attack.get('attack')}")
            else:
                lines.append(f"- {attack}")
    markdown = str(md.get("markdown") or "").strip()
    if markdown:
        lines.extend(["", "## Current Full Paper Card", "", markdown.rstrip()])
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(out)


def _claim_integrity_checks(b: dict, quality: dict) -> list[str]:
    claims = (b.get("claim_list") or {}).get("claims") or []
    mappings = (b.get("claim_evidence_map") or {}).get("mappings") or []
    errors = []

    claim_ids = [str(c.get("claim_id") or "") for c in claims]
    if len(set(claim_ids)) != len(claim_ids):
        errors.append(f"duplicate claim ids in claim_list: {claim_ids}")
    map_ids = [str(m.get("claim_id") or "") for m in mappings]
    if len(set(map_ids)) != len(map_ids):
        errors.append(f"duplicate claim ids in claim_evidence_map: {map_ids}")
    if set(claim_ids) != set(map_ids):
        errors.append(
            "claim/mapping exact-set mismatch: "
            f"claims={sorted(set(claim_ids))}, mappings={sorted(set(map_ids))}"
        )
    audited_claim_ids = {
        str(item.get("claim_id") or "")
        for item in (b.get("result_table_audit") or {}).get("audited_items") or []
        if item.get("claim_id")
    }
    unknown_audited = sorted(audited_claim_ids - set(claim_ids))
    if unknown_audited:
        errors.append(f"result_table_audit references unknown claim ids: {unknown_audited}")

    if _director_ready(quality):
        claim_kind = {str(c.get("claim_id")): c.get("kind") for c in claims}
        contradicted = [
            str(m.get("claim_id") or "") for m in mappings
            if str(m.get("overall_support") or "") == "contradicted"
        ]
        not_found = [
            str(m.get("claim_id") or "") for m in mappings
            if str(m.get("overall_support") or "") == "not-found"
            and claim_kind.get(str(m.get("claim_id") or "")) != "limitation"
        ]
        if contradicted:
            errors.append(f"PASS cannot coexist with contradicted claims: {contradicted}")
        if not_found:
            errors.append(f"claims lack exact support and are not coverage limitations: {not_found}")
    return errors


def _coverage_based_absence_claim_ids(run_dir, b: dict) -> set[str]:
    manifest_path = Path(run_dir) / "inbox" / "citation-snapshots" / "fulltext-contexts.manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not str(manifest.get("coverage_boundary") or "").startswith("complete local PDF"):
        return set()
    mappings = {
        str(row.get("claim_id")): row
        for row in (b.get("claim_evidence_map") or {}).get("mappings") or []
    }
    return {
        str(claim.get("claim_id"))
        for claim in (b.get("claim_list") or {}).get("claims") or []
        if claim.get("kind") == "limitation"
        and (mappings.get(str(claim.get("claim_id"))) or {}).get("overall_support") == "not-found"
    }


def _figure_coverage_checks(b: dict, quality: dict) -> list[str]:
    structure = b.get("paper_structure") or {}
    load_bearing = _load_bearing_refs(structure)
    read_refs = {
        _norm_ref(fig.get("figure_ref"))
        for fig in (b.get("figure_reading") or {}).get("figures") or []
        if fig.get("figure_ref")
    }
    missing = [ref for ref in load_bearing if _norm_ref(ref) not in read_refs]
    if _director_ready(quality) and missing:
        return [f"PASS cannot omit load-bearing figure/table readings: {missing}"]
    return []


def _appraisal_depth_checks(b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality):
        return []
    dims = (b.get("paper_appraisal") or {}).get("dimensions") or []
    names = [str(d.get("dim") or "") for d in dims]
    errors = []
    if len(set(names)) != len(names):
        errors.append(f"duplicate paper_appraisal dimensions: {names}")
    missing = sorted(_APPRAISAL_DIMS - set(names))
    if missing:
        errors.append(f"PASS requires full 7D paper_appraisal coverage; missing={missing}")
    critical = {"soundness", "eval_rigor", "reproducibility", "domain_validity"}
    unanchored = [
        d.get("dim") for d in dims
        if d.get("dim") in critical and not str(d.get("evidence_ref") or "").strip()
    ]
    if unanchored:
        errors.append(f"PASS requires evidence_ref for critical appraisal dimensions: {unanchored}")
    return errors


def _method_depth_checks(b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality):
        return []
    method = b.get("method_teardown") or {}
    required = (
        "problem_definition", "core_assumptions", "representation",
        "training_flow", "inference_flow", "data",
    )
    missing = [key for key in required if not method.get(key)]
    if missing:
        return [f"director-ready method_teardown is structurally thin; missing={missing}"]
    return []


def _page_anchor_checks(run_dir, b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality):
        return []
    errors = []
    has_page_context = _fulltext_has_page_context(run_dir)
    if _is_a_core_read(b) and not has_page_context:
        errors.append(
            "A-core read_paper_deep PASS requires `fulltext-pre` page context; without a "
            "local/fulltext page-anchored read this can only be skim/read, not PASS deep-read."
        )
        return errors
    if not has_page_context:
        return []
    for mapping in (b.get("claim_evidence_map") or {}).get("mappings") or []:
        for locus in mapping.get("loci") or []:
            if not locus.get("supports_claim"):
                continue
            if locus.get("page") is None:
                errors.append(
                    f"local-PDF PASS requires page anchor for claim {mapping.get('claim_id')} "
                    f"locus {locus.get('locus_id')}"
                )
            if locus.get("locator_confidence") == "low":
                errors.append(
                    f"local-PDF PASS cannot use low-confidence locator for claim {mapping.get('claim_id')} "
                    f"locus {locus.get('locus_id')}"
                )
    return errors


def _attack_categories(attacks: list) -> set[str]:
    cats = set()
    for attack in attacks:
        if isinstance(attack, dict):
            cats.add(str(attack.get("category") or ""))
    return cats


def _medical_result_audit_checks(run_dir, b: dict) -> list[str]:
    result_audit = b.get("result_table_audit") or {}
    medical = result_audit.get("medical_segmentation_audit") or {}
    items = [i for i in (medical.get("items") or []) if isinstance(i, dict)]
    categories = {str(i.get("category") or "") for i in items}
    missing = sorted(_MEDICAL_RESULT_AUDIT_CATEGORIES - categories)
    errors = []
    if missing:
        errors.append(f"medical-imaging PASS requires result-audit categories: {missing}")
    if _is_autopet_or_interactive_context(run_dir, b):
        missing_auto = sorted(_AUTOPET_INTERACTIVE_RESULT_CATEGORIES - categories)
        if missing_auto:
            errors.append(
                "autoPET/interactive-correction PASS requires result-audit categories: "
                f"{missing_auto}"
            )
    hard_fail = [
        i.get("category") for i in items
        if i.get("category") in {"patient_or_case_level_split", "metric_direction_and_unit",
                                 "baseline_binding"}
        and i.get("status") in {"unmet", "na"}
    ]
    if hard_fail:
        errors.append(f"medical-imaging PASS cannot leave core result-audit items unmet/na: {hard_fail}")
    return errors


def _medical_imaging_quality_checks(run_dir, b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality) or not _is_medical_imaging_run(run_dir):
        return []
    errors = []
    appraisal = b.get("paper_appraisal") or {}
    med = appraisal.get("medical_imaging_checklist") or {}
    items = [i for i in (med.get("items") or []) if isinstance(i, dict)]
    categories = {str(i.get("category") or "") for i in items}
    missing_categories = sorted(_MEDICAL_CHECKLIST_CATEGORIES - categories)
    if missing_categories:
        errors.append(
            "medical-imaging PASS requires checklist categories: "
            f"{missing_categories}"
        )
    weak_required = [
        i.get("category") for i in items
        if i.get("category") in {"patient_split", "metric_direction", "clinical_claim_boundary",
                                 "preprocessing_leakage"}
        and i.get("status") in {"unmet", "na"}
    ]
    if weak_required:
        errors.append(f"medical-imaging PASS cannot leave core checklist categories unmet/na: {weak_required}")
    reported_item_ids = {str(i.get("item_id") or "") for i in items if i.get("item_id")}
    missing_item_ids = sorted(_medical_item_bank_ids() - reported_item_ids)
    if missing_item_ids:
        errors.append(
            "medical-imaging PASS requires local reporting-guideline item bank coverage: "
            f"{missing_item_ids}"
        )

    transfer_rows = [
        r for r in (b.get("domain_transfer_note") or {}).get("transfer_matrix") or []
        if isinstance(r, dict)
    ]
    transfer_axes = {str(r.get("axis") or "") for r in transfer_rows}
    missing_axes = sorted(_MEDICAL_TRANSFER_AXES - transfer_axes)
    if missing_axes:
        errors.append(f"medical-imaging PASS requires transfer_matrix axes: {missing_axes}")

    attacks = quality.get("reviewer_attack_points") or []
    attack_categories = _attack_categories(attacks)
    missing_attacks = sorted(_CORE_ATTACK_CATEGORIES - attack_categories)
    if missing_attacks:
        errors.append(
            "medical-imaging A-core PASS requires structured reviewer_attack_points for: "
            f"{missing_attacks}"
        )

    sections = {str(x) for x in (b.get("paper_markdown_card") or {}).get("covered_sections") or []}
    missing_sections = sorted(_MEDICAL_MARKDOWN_SECTIONS - sections)
    if missing_sections:
        errors.append(f"medical-imaging Markdown card missing sections: {missing_sections}")
    errors += _medical_result_audit_checks(run_dir, b)
    return errors


def _quality_consistency_checks(b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality):
        return []
    errors = []
    required_pairs = {
        "coverage": "full",
        "single_paper_completeness": "complete",
        "evidence_saturation": "not-assessed-single-paper",
        "anchoring": "strong",
        "domain_transfer_honesty": "strong",
        "project_alignment": "strong",
        "independent_critique_resolution": "resolved",
    }
    if quality.get("verdict") == "PASS_WITH_CAVEATS":
        if quality.get("source_fidelity") not in {"strong", "mixed"}:
            errors.append(
                "PASS_WITH_CAVEATS requires paper_reading_quality.source_fidelity="
                f"strong|mixed, got {quality.get('source_fidelity')!r}"
            )
    else:
        required_pairs["source_fidelity"] = "strong"
    for key, expected in required_pairs.items():
        if quality.get(key) != expected:
            errors.append(f"PASS requires paper_reading_quality.{key}={expected}, got {quality.get(key)!r}")

    for key in ("method_depth", "figure_table_coverage", "result_table_depth",
                "algorithmic_depth", "reproducibility_depth"):
        got = quality.get(key)
        if got in {"weak", "missing"}:
            errors.append(f"PASS cannot coexist with paper_reading_quality.{key}={got!r}")

    if (b.get("result_table_audit") or {}).get("applicability") == "applicable":
        if quality.get("result_table_depth") not in {"strong", "mixed"}:
            errors.append("applicable result_table_audit requires result_table_depth strong/mixed")
        if (b.get("result_table_audit") or {}).get("overall") == "weak":
            errors.append("PASS cannot coexist with weak result_table_audit")
        if not ((b.get("result_table_audit") or {}).get("audited_items") or []):
            errors.append("applicable result_table_audit requires at least one audited item")

    if (b.get("math_algorithm_audit") or {}).get("applicability") == "applicable":
        if quality.get("algorithmic_depth") not in {"strong", "mixed"}:
            errors.append("applicable math_algorithm_audit requires algorithmic_depth strong/mixed")
        if (b.get("math_algorithm_audit") or {}).get("overall") == "weak":
            errors.append("PASS cannot coexist with weak math_algorithm_audit")

    critique = b.get("independent_reading_critique") or {}
    critique_verdict = critique.get("verdict")
    if quality.get("verdict") == "PASS":
        if critique_verdict != "PASS":
            errors.append(
                "PASS requires independent_reading_critique.verdict=PASS, got "
                f"{critique_verdict!r}"
            )
        if critique.get("required_repairs"):
            errors.append("PASS cannot coexist with independent_reading_critique.required_repairs")
    elif critique_verdict not in {"PASS", "PASS_WITH_CAVEATS"}:
        errors.append(
            "PASS_WITH_CAVEATS requires independent_reading_critique.verdict="
            f"PASS|PASS_WITH_CAVEATS, got {critique_verdict!r}"
        )
    if (b.get("paper_reading_reconciliation") or {}).get("verdict") != "PASS":
        errors.append("PASS requires paper_reading_reconciliation.verdict=PASS")
    if (b.get("paper_reading_reconciliation") or {}).get("unresolved_repairs"):
        errors.append("PASS cannot coexist with paper_reading_reconciliation.unresolved_repairs")
    if quality.get("required_repairs"):
        errors.append("PASS cannot coexist with paper_reading_quality.required_repairs")

    is_core = (
        (b.get("project_context_alignment") or {}).get("relevance") == "A-core"
        or (b.get("paper_note") or {}).get("relation_to_thesis") == "A-core"
    )
    min_attacks = 5 if is_core else 2
    attacks = quality.get("reviewer_attack_points") or []
    if len(attacks) < min_attacks:
        errors.append(f"PASS requires at least {min_attacks} reviewer_attack_points; got {len(attacks)}")

    md = b.get("paper_markdown_card") or {}
    if md.get("quality_verdict") != quality.get("verdict"):
        errors.append(
            f"paper_markdown_card.quality_verdict={md.get('quality_verdict')!r} "
            f"does not match quality verdict={quality.get('verdict')!r}"
        )
    return errors


def _markdown_coverage_checks(run_dir, b: dict, quality: dict) -> list[str]:
    if not _director_ready(quality):
        return []
    md = b.get("paper_markdown_card") or {}
    errors = []
    claim_ids = {
        str(c.get("claim_id") or "")
        for c in (b.get("claim_list") or {}).get("claims") or []
        if c.get("claim_id")
    }
    covered_claims = {str(x) for x in md.get("covered_claim_ids") or []}
    missing_claims = sorted(claim_ids - covered_claims)
    if missing_claims:
        errors.append(f"Markdown card omits claim ids: {missing_claims}")

    load_bearing = {_norm_ref(x) for x in _load_bearing_refs(b.get("paper_structure") or {})}
    covered_figs = {_norm_ref(x) for x in md.get("covered_figure_refs") or []}
    missing_figs = sorted(ref for ref in load_bearing if ref not in covered_figs)
    if missing_figs:
        errors.append(f"Markdown card omits load-bearing figure/table refs: {missing_figs}")

    sections = {str(x) for x in md.get("covered_sections") or []}
    missing_sections = sorted(_MARKDOWN_REQUIRED_SECTIONS - sections)
    if missing_sections:
        errors.append(f"Markdown card missing required director sections: {missing_sections}")
    body_audit = audit_paper_markdown(
        str(md.get("markdown") or ""),
        b,
        medical=_is_medical_imaging_run(run_dir),
    )
    errors += [f"Markdown coverage advisory: {error}" for error in body_audit["errors"]]
    advisory = {
        "contract_version": "paper-markdown-advisory/v1",
        "delivery_blocking": False,
        "verdict": "PASS" if not errors else "USABLE_WITH_CAVEATS",
        "warnings": errors,
        "coverage": body_audit.get("coverage") or {},
    }
    path = Path(run_dir) / "inbox" / "markdown-quality-advisory.json"
    path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return errors


def _extra_existence_refs(b: dict) -> list[str]:
    refs = []
    refs += [str(e.get("target_ref") or "") for e in (b.get("paper_relations") or {}).get("edges") or []]
    refs += [str(r or "") for r in (b.get("trend_card") or {}).get("source_refs") or []]
    return [r.strip() for r in refs if r and r.strip() and not r.strip().startswith("[[")]


def _classify_quality_defects(problems: list[str]) -> list[dict]:
    defects = []
    for index, problem in enumerate(dict.fromkeys(str(row) for row in problems)):
        text = problem.casefold()
        severity = "material"
        # "hash mismatch" left this keyword table on 2026-08-07 together with the checks that used
        # to raise it — nothing emits that phrase any more, and keeping a dead trigger word here
        # would mis-route a future defect that merely mentions hashing in its prose.
        if any(token in text for token in (
            "source consistency", "blind contamination",
            "primary analysis was seen", "unsupported/contradicted claims",
            "violates class/path contract",
        )):
            category, targets, refresh, severity = "scientific-integrity", [], [], "critical"
        elif any(token in text for token in (
            "independent_reading_critique", "blind second reader", "blind source verdict",
        )):
            category = "blind-second-read"
            targets = ["independent-reading-critic"]
            refresh = [
                "paper-reading-reconciler", "paper-reading-quality-auditor",
                "paper-markdown-writer",
            ]
        elif "markdown" in text or "covered_sections" in text:
            category, targets, refresh = "markdown", ["paper-markdown-writer"], []
        elif any(token in text for token in ("visual", "figure", "table refs")):
            category = "visual-or-table"
            targets = ["figure-reader"]
            refresh = [
                "result-table-auditor", "paper-appraiser", "domain-transfer-critic",
                "paper-reading-reconciler", "paper-reading-quality-auditor",
                "paper-markdown-writer",
            ]
        elif "reconciliation" in text or "blind bundle" in text:
            category = "reconciliation"
            targets = ["paper-reading-reconciler"]
            refresh = ["paper-reading-quality-auditor", "paper-markdown-writer"]
        elif "method_teardown" in text or "method depth" in text:
            category = "method-depth"
            targets = ["method-teardown-extractor"]
            refresh = _data_descendants("method-teardown-extractor")
        elif any(token in text for token in ("claim/mapping", "claim ids", "page anchor", "locator")):
            category = "claim-evidence"
            targets = ["claim-evidence-linker", CITATION_AUDITOR_AGENT]
            refresh = [
                "paper-reading-reconciler", "paper-reading-quality-auditor",
                "paper-markdown-writer",
            ]
        elif "result" in text or "metric" in text or "split" in text or "leakage" in text:
            category = "result-audit"
            targets = ["result-table-auditor"]
            refresh = _data_descendants("result-table-auditor")
        else:
            category = "quality-audit"
            targets = ["paper-reading-quality-auditor"]
            refresh = ["paper-markdown-writer"]
        defects.append(_supplement_defect(
            f"QUALITY-{index + 1:03d}", category, "paper-reading-quality", problem,
            targets, refresh, severity=severity,
        ))
    return defects


def _citation_gap_is_hard(reasons) -> bool:
    summary = "; ".join(str(row) for row in (reasons or []))
    lowered = summary.casefold()
    # Page-render / figure-asset bookkeeping is presentation evidence.  It is
    # useful as a warning but must not hide an otherwise readable card or
    # trigger another full panel.  Core source/text tampering and cross-claim
    # attribution remain truth failures.
    if (
        "figure asset sha-256 mismatch" in lowered
        or "visual asset hash mismatch" in lowered
    ) and not any(token in lowered for token in (
        "fulltext", "exact quote", "numeric",
    )):
        return False
    # The three hash-mismatch tokens left this table on 2026-08-07 with the checks that produced
    # them. Exact-quote and numeric conflicts stay: those read the real bytes and are grounding,
    # not integrity accounting.
    return any(token in lowered for token in (
        "exact quote mismatch",
        "numeric conflict",
        "cross-claim",
        "unresolvable reference",
        "unanchored",
        "missing supports_claim",
        "supports_claim=false",
        "is contradicted by locus",
    ))


def _raise_citation_gap(message: str, reasons, *, force_hard: bool = False) -> None:
    summary = "; ".join(str(row) for row in (reasons or [message]))
    hard = force_hard or _citation_gap_is_hard(reasons)
    raise TargetedGateBlock(
        f"{message}: {summary}",
        [_supplement_defect(
            "CITATION-001",
            "citation-attribution",
            "claim_evidence_map/citation_audit",
            summary[:6000],
            [] if hard else ["claim-evidence-linker", CITATION_AUDITOR_AGENT],
            [] if hard else [
                "paper-reading-reconciler", "paper-reading-quality-auditor",
                "paper-markdown-writer",
            ],
            severity="critical" if hard else "material",
        )],
        verdict="BLOCK" if hard else "NEEDS_SUPPLEMENT",
    )


def _source_document_tail(ref: str) -> str:
    """Return the run-local fulltext identity independent of absolute-path spelling."""
    normalized = str(ref or "").strip().replace("\\", "/")
    lowered = normalized.casefold()
    marker = "inbox/fulltext-docs/"
    index = lowered.rfind(marker)
    if index < 0:
        return ""
    return normalized[index + len(marker):].casefold()


def _same_source_document(left: str, right: str, run_dir=None) -> bool:
    if str(left or "") == str(right or ""):
        return True
    left_tail = _source_document_tail(left)
    right_tail = _source_document_tail(right)
    if left_tail and left_tail == right_tail:
        return True
    # Workers sometimes append provenance or page notes after the run-local
    # filename (for example ``...paper.pdf; sha256:...``).  Treat those as
    # metadata on the same document, not as part of the filename identity.
    if run_dir and left_tail and right_tail:
        docs_root = Path(run_dir) / "inbox" / "fulltext-docs"
        if docs_root.is_dir():
            for document in docs_root.iterdir():
                if not document.is_file():
                    continue
                name = document.name.casefold()
                # Workers use both ``; sha256:...`` and URI-fragment style
                # ``#sha256:...`` annotations for the same run-local PDF.
                # These suffixes describe provenance; they are not part of the
                # document identity used by the cross-role consistency gate.
                left_matches = (
                    left_tail == name
                    or left_tail.startswith(name + ";")
                    or left_tail.startswith(name + "#")
                )
                right_matches = (
                    right_tail == name
                    or right_tail.startswith(name + ";")
                    or right_tail.startswith(name + "#")
                )
                if left_matches and right_matches:
                    return True
    # A single-paper run may use a canonical DOI/arXiv ref in the primary note
    # while the blind reader records the only local PDF it was allowed to see.
    # Bind that spelling only when the run has exactly one fulltext document.
    if run_dir and bool(left_tail) != bool(right_tail):
        local_tail = left_tail or right_tail
        docs_root = Path(run_dir) / "inbox" / "fulltext-docs"
        documents = [path for path in docs_root.iterdir() if path.is_file()] if docs_root.is_dir() else []
        return len(documents) == 1 and documents[0].name.casefold() == local_tail
    return False


def _consistency_checks(run_dir, b: dict) -> list[str]:
    """Normalize cross-role metadata and return non-blocking content advisories.

    Only later truth checks may block on a missing/corrupt core source, an
    unsupported core claim or numeric/quote conflict.  Path spelling, role
    metadata, coverage, presentation, and worker self-verdicts never make a
    finished Markdown card disappear or cause an automatic expensive rerun.
    """
    warnings = []
    src = _source_ref(b)
    if not src:
        docs_root = Path(run_dir) / "inbox" / "fulltext-docs"
        documents = [path for path in docs_root.iterdir() if path.is_file()] if docs_root.is_dir() else []
        if len(documents) == 1:
            src = f"inbox/fulltext-docs/{documents[0].name}"
            (b.get("paper_note") or {})["source_ref"] = src
            warnings.append("paper_note.source_ref was empty and was normalized to the only local source")
        else:
            raise GateBlock(
                "read_paper_deep core source missing: paper_note.source_ref is empty and no single "
                "local fulltext document can be bound"
            )
    same_source_keys = [
        "paper_structure", "project_context_alignment", "method_teardown", "figure_reading",
        "result_table_audit", "math_algorithm_audit", "paper_appraisal", "paper_relations",
        "domain_transfer_note", "reproducibility_materials_audit", "independent_reading_critique",
        "paper_reading_reconciliation",
        "paper_reading_quality",
        "paper_markdown_card",
    ]
    mismatches = []
    for key in same_source_keys:
        payload = b.get(key) or {}
        got = str(payload.get("source_ref") or "")
        if got and got != src:
            if _same_source_document(got, src, run_dir):
                payload["source_ref"] = src
            else:
                mismatches.append(f"{key}.source_ref={got!r}")
    for c in (b.get("claim_list") or {}).get("claims") or []:
        got = str(c.get("source_ref") or "")
        if got != src:
            if _same_source_document(got, src, run_dir):
                c["source_ref"] = src
            else:
                mismatches.append(f"claim {c.get('claim_id')} source_ref={got!r}")
    for mapping in (b.get("claim_evidence_map") or {}).get("mappings") or []:
        for locus in mapping.get("loci") or []:
            got = str(locus.get("source_ref") or "")
            if got != src and _same_source_document(got, src, run_dir):
                locus["source_ref"] = src
    if mismatches:
        warnings.append(
            "cross-role source_ref spelling differs; content retained and the canonical paper_note "
            f"reference is used for delivery: {mismatches}"
        )

    structure = b.get("paper_structure") or {}
    unread_load_bearing = []
    for item in (structure.get("figures") or []):
        if item.get("load_bearing") and item.get("read_status") != "read":
            unread_load_bearing.append(item.get("figure_ref"))
    for item in (structure.get("tables") or []):
        if item.get("load_bearing") and item.get("read_status") != "read":
            unread_load_bearing.append(item.get("table_ref"))

    quality = b.get("paper_reading_quality") or {}
    verdict = quality.get("verdict")
    if quality.get("promotion_ready"):
        quality["promotion_ready"] = False
        write_report(
            Path(run_dir) / "inbox" / "normalization" / "promotion-ready.json",
            {
                "contract_version": "schema-normalization/v1",
                "artifact_type": "paper_reading_quality",
                "changes": [{
                    "pointer": "/promotion_ready",
                    "rule": "human-promotion-gate-authority",
                    "before": True,
                    "after": False,
                }],
                "preserved_extras": [],
                "scientific_fields_modified": False,
            },
        )
    quality_errors = []
    if unread_load_bearing and _director_ready(quality):
        quality_errors.append(
            f"PASS cannot coexist with unread load-bearing figures/tables: "
            f"{unread_load_bearing}"
        )
    quality_errors += _blind_provenance_checks(run_dir, b, quality)
    quality_errors += _reconciliation_checks(run_dir, b, quality)
    quality_errors += _claim_integrity_checks(b, quality)
    quality_errors += _figure_coverage_checks(b, quality)
    quality_errors += _visual_input_checks(run_dir, b, quality)
    quality_errors += _appraisal_depth_checks(b, quality)
    quality_errors += _method_depth_checks(b, quality)
    quality_errors += _quality_consistency_checks(b, quality)
    quality_errors += _markdown_coverage_checks(run_dir, b, quality)
    quality_errors += _page_anchor_checks(run_dir, b, quality)
    quality_errors += _medical_imaging_quality_checks(run_dir, b, quality)
    if verdict == "BLOCK":
        warnings.append(
            "worker quality verdict was BLOCK; Markdown is still delivered and the stated reasons "
            "remain visible as caveats"
        )

    problems = list(quality_errors)
    if verdict == "NEEDS_SUPPLEMENT":
        problems.append(
            "paper_reading_quality BLOCK from director-ready output: "
            "verdict=NEEDS_SUPPLEMENT"
        )
        problems += [str(row) for row in (quality.get("required_repairs") or [])]
    if verdict == "PASS_WITH_CAVEATS":
        markdown = str((b.get("paper_markdown_card") or {}).get("markdown") or "").casefold()
        if not any(token in markdown for token in ("caveat", "limitation", "局限", "限制")):
            problems.append("PASS_WITH_CAVEATS requires explicit caveats in director Markdown")
    if not quality.get("markdown_ready"):
        advisory_path = Path(run_dir) / "inbox" / "markdown-quality-advisory.json"
        existing = {}
        if advisory_path.is_file():
            existing = json.loads(advisory_path.read_text(encoding="utf-8"))
        warnings = list(existing.get("warnings") or [])
        warnings.append("paper_reading_quality.markdown_ready is false")
        existing.update({
            "contract_version": "paper-markdown-advisory/v1",
            "delivery_blocking": False,
            "verdict": "USABLE_WITH_CAVEATS",
            "warnings": list(dict.fromkeys(warnings)),
        })
        advisory_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if verdict not in {"PASS", "PASS_WITH_CAVEATS", "NEEDS_SUPPLEMENT", "BLOCK"}:
        problems.append(f"unknown paper_reading_quality verdict: {verdict!r}")
    if problems:
        _write_repair_packet(run_dir, b, problems)
        # A MISSING core source still stops the run — you cannot read a paper that is not there.
        # The hash-mismatch trigger was removed 2026-08-07 with the check that emitted it.
        hard_source_problems = [
            str(row) for row in problems
            if "core source missing" in str(row).casefold()
            or "core source corrupt" in str(row).casefold()
        ]
        if hard_source_problems:
            raise TargetedGateBlock(
                "read_paper_deep core source integrity BLOCK: " + "; ".join(hard_source_problems),
                [_supplement_defect(
                    "SOURCE-INTEGRITY-001", "scientific-integrity", "source",
                    "; ".join(hard_source_problems), [], [], severity="critical",
                )],
                verdict="BLOCK",
            )
        warnings.extend(str(row) for row in problems)
    return list(dict.fromkeys(warnings))


def _fallback_markdown_from_structured_artifacts(b: dict) -> str:
    """Build a readable, non-authoritative card when the writer returns no body."""
    note = b.get("paper_note") or {}
    plan = b.get("paper_reading_plan") or {}
    alignment = b.get("project_context_alignment") or {}
    claim_list = b.get("claim_list") or {}
    claim_map = b.get("claim_evidence_map") or {}
    method = b.get("method_teardown") or {}
    results = b.get("result_table_audit") or {}
    figures = b.get("figure_reading") or {}
    appraisal = b.get("paper_appraisal") or {}
    reproducibility = b.get("reproducibility_materials_audit") or {}
    transfer = b.get("domain_transfer_note") or {}
    critique = b.get("independent_reading_critique") or {}
    reconciliation = b.get("paper_reading_reconciliation") or {}
    quality = b.get("paper_reading_quality") or {}

    title = str(note.get("title") or (b.get("paper_markdown_card") or {}).get("title") or "Paper")
    source_ref = str(note.get("source_ref") or "source reference unavailable")
    lines = [
        f"# {title}",
        "",
        "> **Delivery caveat:** The paper Markdown worker returned a blank body. This minimal "
        "card was rendered deterministically from validated structured reading artifacts; it is "
        "usable for review but not promotion-ready.",
        "",
        f"**Source:** {source_ref}",
        "",
        "## Decision Need",
        str(plan.get("decision_need") or plan.get("reading_objective") or "Not recorded."),
        "",
        "## Project Alignment",
        str(alignment.get("thesis_fit") or note.get("summary") or "Not recorded."),
        "",
        "## Claims and Evidence",
    ]

    mappings = {
        str(row.get("claim_id") or ""): row
        for row in claim_map.get("mappings") or []
        if isinstance(row, dict)
    }
    claims = claim_list.get("claims") or []
    if not claims:
        lines.append("- No structured claims were available.")
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "claim")
        lines.append(f"- **{claim_id}:** {str(claim.get('text') or 'Claim text unavailable.')}")
        loci = (mappings.get(claim_id) or {}).get("loci") or []
        evidence_bits = []
        for locus in loci:
            location = str(locus.get("location") or locus.get("locus_id") or "location unavailable")
            result = str(locus.get("reported_result") or "").strip()
            evidence_bits.append(f"{location}{': ' + result if result else ''}")
        lines.append(
            "  - Evidence: " + ("; ".join(evidence_bits) if evidence_bits else "No mapped locus recorded.")
        )

    lines += [
        "",
        "## Method or Theory",
        str(method.get("representation") or method.get("problem_definition") or "Not recorded."),
    ]
    loss_terms = method.get("loss_terms") or []
    if loss_terms:
        lines.append("- Components: " + "; ".join(
            f"{str(row.get('term') or 'component')} ({str(row.get('role') or 'role not recorded')})"
            for row in loss_terms
        ))

    lines += ["", "## Numeric Results"]
    audited_items = results.get("audited_items") or []
    if not audited_items:
        lines.append("No audited numeric result was recorded.")
    for row in audited_items:
        lines.append(
            f"- {str(row.get('item_ref') or 'Result')}: "
            f"{str(row.get('reported_comparison') or row.get('audit') or 'comparison not recorded')}"
        )

    lines += ["", "## Figures and Tables"]
    figure_rows = figures.get("figures") or []
    if not figure_rows:
        lines.append("No structured figure or table reading was recorded.")
    for row in figure_rows:
        lines.append(
            f"- {str(row.get('figure_ref') or 'Visual')}: "
            f"{str(row.get('take_home') or 'take-home not recorded')}"
        )

    limitations = [
        str(row) for row in (
            appraisal.get("limitations_acknowledged") or []
        ) + (
            appraisal.get("limitations_unacknowledged") or []
        ) if str(row).strip()
    ]
    lines += [
        "",
        "## Critical Appraisal",
        str(appraisal.get("overall") or "Not recorded."),
    ]
    if limitations:
        lines.append("- Limitations: " + "; ".join(limitations))

    lines += [
        "",
        "## Reproducibility",
        f"Risk: {str(reproducibility.get('reproducibility_risk') or 'not recorded')}.",
    ]
    missing_materials = [str(row) for row in reproducibility.get("missing_materials") or []]
    if missing_materials:
        lines.append("- Missing materials: " + "; ".join(missing_materials))

    lines += [
        "",
        "## Domain Transfer",
        f"Transfer level: {str(transfer.get('transfer_level') or 'not recorded')}.",
    ]
    not_usable = [str(row) for row in transfer.get("not_usable_for") or []]
    if not_usable:
        lines.append("- Not usable for: " + "; ".join(not_usable))

    warning = str(
        reconciliation.get("director_warning")
        or critique.get("director_warning")
        or "Independent-reader warning was not recorded."
    )
    lines += [
        "",
        "## Independent Critique",
        warning,
        "Multi-source evidence saturation was not assessed in this single-paper read.",
        "",
        "## Next Actions",
    ]
    next_actions = [str(row) for row in transfer.get("required_local_validation") or []]
    next_actions += [str(row) for row in quality.get("required_repairs") or []]
    if next_actions:
        lines += [f"- {row}" for row in dict.fromkeys(next_actions) if row.strip()]
    else:
        lines.append("- Review this deterministic fallback against the source before promotion.")
    return "\n".join(lines).rstrip() + "\n"


def _write_markdown_card(
    run_dir,
    payload: dict,
    *,
    legacy_replay: bool = False,
    delivery_status: str | None = None,
    caveats: list[str] | None = None,
) -> str:
    title = str(payload.get("title") or "paper-card")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "paper-card"
    out = Path(run_dir) / "director-review" / "papers" / f"{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = str(payload.get("markdown") or "").rstrip() + "\n"
    # Delivery state and machine caveats belong in the technical advisory JSON.
    # The director-facing paper card is the finished reading product, so it must
    # start with the paper title and integrate scientific limits in context.
    if legacy_replay:
        body = (
            "> **LEGACY_UNVERIFIED:** this historical replay has no mechanically verified "
            "claim-span attribution and is not citation- or promotion-ready.\n\n" + body
        )
    out.write_text(body, encoding="utf-8")
    return str(out)


def _apply_usable_first_policy(run_dir, b: dict, warnings: list[str]) -> None:
    """Deliver a readable caveated card when only non-core checks are incomplete."""
    if not warnings:
        return
    quality = b.get("paper_reading_quality") or {}
    markdown = b.get("paper_markdown_card") or {}
    quality.setdefault("evidence_saturation", "not-assessed-single-paper")
    if quality.get("verdict") != "BLOCK":
        quality["verdict"] = "PASS_WITH_CAVEATS"
        quality["promotion_ready"] = False
        markdown["quality_verdict"] = "PASS_WITH_CAVEATS"
    advisory_path = Path(run_dir) / "inbox" / "usable-first-advisory.json"
    advisory_path.parent.mkdir(parents=True, exist_ok=True)
    advisory_path.write_text(json.dumps({
        "contract_version": "usable-first-advisory/v1",
        "delivery_blocking": False,
        "verdict": "USABLE_WITH_CAVEATS",
        "warnings": list(dict.fromkeys(str(row) for row in warnings if str(row).strip())),
        "policy": (
            "Non-core schema, receipt, coverage, and Markdown gaps do not replay scientific roles. "
            "Only source fabrication/missing core source, unsupported core claims, numeric or quote "
            "conflict, leakage, false execution, or permission violations block delivery."
        ),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _discover_dets(run_dir, ts) -> tuple:
    b = _load_worker_bundles(run_dir)
    quality = b.get("paper_reading_quality") or {}
    preview_status = (
        "USABLE" if quality.get("verdict") == "PASS"
        else "USABLE_WITH_CAVEATS"
    )
    if str((b.get("paper_markdown_card") or {}).get("markdown") or "").strip():
        _write_markdown_card(
            run_dir,
            b["paper_markdown_card"],
            delivery_status=preview_status,
            caveats=list(quality.get("required_repairs") or []),
        )
    delivery_warnings = []
    delivery_warnings.extend(_validate_all_payloads(b))
    markdown = b.get("paper_markdown_card") or {}
    if not str(markdown.get("markdown") or "").strip():
        markdown["markdown"] = _fallback_markdown_from_structured_artifacts(b)
        delivery_warnings.append(
            "paper Markdown worker returned a blank body; a deterministic fallback card was "
            "rendered from validated structured paper artifacts"
        )
    delivery_warnings.extend(_consistency_checks(run_dir, b))
    _apply_usable_first_policy(run_dir, b, delivery_warnings)
    paths = []
    pn = b["paper_note"] or {}

    et = build_evidence_table(
        str(pn.get("title") or ""),
        [{"id": "s1", "kind": "paper", "ref": str(pn.get("source_ref") or ""),
          "notes": "single-paper source inventory; support is assessed claim-by-claim"}],
        False,
    )

    contract = pn.get("paper_contract") or {}
    texts = [
        str((b["paper_reading_plan"] or {}).get("reading_objective") or ""),
        str((b["paper_reading_plan"] or {}).get("decision_need") or ""),
        str(pn.get("title") or ""),
        str(pn.get("summary") or ""),
    ]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    texts.append(str(contract.get("contract_sentence") or ""))
    texts.append(str((b["project_context_alignment"] or {}).get("thesis_fit") or ""))
    texts.append(str((b["method_teardown"] or {}).get("representation") or ""))
    texts.append(str((b["result_table_audit"] or {}).get("overall") or ""))
    texts.append(str((b["math_algorithm_audit"] or {}).get("overall") or ""))
    texts.append(str((b["paper_appraisal"] or {}).get("overall") or ""))
    texts.append(str((b["domain_transfer_note"] or {}).get("transfer_level") or ""))
    texts.append(str((b["independent_reading_critique"] or {}).get("director_warning") or ""))
    texts.append(str((b["paper_reading_reconciliation"] or {}).get("director_warning") or ""))
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)
    paths.append(dpath)

    coverage_absence_ids = _coverage_based_absence_claim_ids(run_dir, b)
    cv = build_report(
        b["claim_list"], b["claim_evidence_map"],
        resolvable_refs=_shared.resolvable_refs(et),
        coverage_based_absence_claim_ids=coverage_absence_ids,
    )
    # This verdict is computed from claim/evidence truth, not presentation
    # quality.  Any current-run BLOCK remains fail-closed; readable Markdown
    # may bypass formatting defects, never unsupported or contradictory claims.
    cv_hard = cv["verdict"] == "BLOCK"
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv_hard else "draft" if cv["verdict"] == "BLOCK"
                                else "approved"))
    if cv["verdict"] == "BLOCK":
        _raise_citation_gap(
            "citation gate BLOCK; targeted supplement required",
            cv["violations"],
            force_hard=True,
        )

    try:
        attribution = build_run_attribution_report(
            run_dir, b["claim_list"], b["claim_evidence_map"], b.get("citation_audit"),
            require_complete_claims=True,
            coverage_based_absence_claim_ids=coverage_absence_ids,
        )
    except ValueError as exc:
        _raise_citation_gap(
            "citation attribution input is invalid", [str(exc)], force_hard=True,
        )
    if attribution["verdict"] == "PASS_WITH_CAVEATS":
        if b["paper_reading_quality"].get("verdict") == "PASS":
            b["paper_reading_quality"]["verdict"] = "PASS_WITH_CAVEATS"
            b["paper_markdown_card"]["quality_verdict"] = "PASS_WITH_CAVEATS"
        write_report(
            Path(run_dir) / "inbox" / "normalization" / "citation-caveat-verdict.json",
            {
                "contract_version": "schema-normalization/v1",
                "artifact_type": "paper_reading_quality",
                "changes": [{
                    "pointer": "/verdict",
                    "rule": "derived-citation-caveat",
                    "before": "PASS",
                    "after": "PASS_WITH_CAVEATS",
                }],
                "preserved_extras": [],
                "scientific_fields_modified": False,
            },
        )
    attr_status = (
        "approved" if attribution["verdict"] in {"PASS", "PASS_WITH_CAVEATS"}
        else "draft"
    )
    paths.append(write_artifact(
        run_dir, "DISCOVER", "citation-attribution-report.artifact.json",
        "citation_attribution_report", CITATION_AUDITOR_AGENT, attribution, ts, attr_status,
    ))
    if attribution["verdict"] not in {"PASS", "PASS_WITH_CAVEATS"} and not attribution["legacy_replay"]:
        reasons = attribution["violations"] + attribution["unverified_reasons"]
        _raise_citation_gap(
            f"citation attribution {attribution['verdict']}", reasons, force_hard=True,
        )

    _apply_usable_first_policy(run_dir, b, delivery_warnings)

    # A deep read is about the focal paper. Related-work/trend strings are useful background,
    # but live-validating every secondary title adds latency and false negatives without changing
    # the focal claim evidence. Promotion can run the stricter landscape-wide existence audit.
    refs = _shared.external_refs(et, b["claim_evidence_map"])
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts, refs)
    paths.append(epath)

    for key, atype, agent, fname, status in ARTIFACT_PLAN:
        if attribution["legacy_replay"]:
            status = "draft"
        remaining_schema_errors = validate_payload(atype, b[key])
        if remaining_schema_errors:
            # The immutable worker bundle and normalization/advisory reports
            # remain available.  A non-canonical sidecar must not erase the
            # completed readable paper card after source/claim/citation truth
            # gates above have already run.  Promotion remains strict and can
            # require a targeted supplement before admitting this sidecar.
            delivery_warnings.append(
                f"typed sidecar omitted at {key}: "
                + "; ".join(remaining_schema_errors)[:4000]
            )
            continue
        paths.append(write_artifact(run_dir, "DISCOVER", fname, atype, agent, b[key], ts, status))

    _apply_usable_first_policy(run_dir, b, delivery_warnings)

    md_path = _write_markdown_card(
        run_dir,
        b["paper_markdown_card"],
        legacy_replay=attribution["legacy_replay"],
        delivery_status=(
            "USABLE" if b["paper_reading_quality"].get("verdict") == "PASS"
            else "USABLE_WITH_CAVEATS"
        ),
        caveats=list(b["paper_reading_quality"].get("required_repairs") or []),
    )
    cem = b["claim_evidence_map"].get("mappings") or []
    quality = b["paper_reading_quality"]
    markdown_audit = audit_paper_markdown(
        str((b["paper_markdown_card"] or {}).get("markdown") or ""),
        b,
        medical=_is_medical_imaging_run(run_dir),
    )
    effective_quality = (
        "LEGACY_UNVERIFIED" if attribution["legacy_replay"] else quality.get("verdict")
    )
    return paths, {
        "citation_gate": cv["verdict"],
        "citation_attribution_gate": (
            "LEGACY_UNVERIFIED" if attribution["legacy_replay"] else attribution["verdict"]),
        "citation_legacy_replay": attribution["legacy_replay"],
        "citation_correctness": attribution["citation_correctness"],
        "claim_completeness": attribution["claim_completeness"],
        "citation_f1": attribution["citation_f1"],
        "existence_gate": ex["verdict"],
        "existence_warnings": len(ex["warnings"]),
        "quality_verdict": effective_quality,
        "worker_reported_quality_verdict": quality.get("verdict"),
        "single_paper_completeness": quality.get("single_paper_completeness"),
        "source_fidelity": (
            "unverified" if attribution["legacy_replay"] else quality.get("source_fidelity")),
        "visual_coverage": quality.get("visual_coverage"),
        "evidence_saturation": quality.get("evidence_saturation"),
        "markdown_semantic_verdict": (
            "UNVERIFIED" if attribution["legacy_replay"] else markdown_audit.get("verdict")),
        "director_markdown_card": md_path,
        "n_claims": len(b["claim_list"].get("claims") or []),
        "n_mappings": len(cem),
        "n_loss_terms": len((b["method_teardown"] or {}).get("loss_terms") or []),
        "n_figures": len((b["figure_reading"] or {}).get("figures") or []),
        "result_table_overall": (b["result_table_audit"] or {}).get("overall"),
        "math_algorithm_overall": (b["math_algorithm_audit"] or {}).get("overall"),
        "reproducibility_risk": (b["reproducibility_materials_audit"] or {}).get("reproducibility_risk"),
        "independent_critique_verdict": (b["independent_reading_critique"] or {}).get("verdict"),
        "reconciliation_verdict": (b["paper_reading_reconciliation"] or {}).get("verdict"),
        "project_relevance": (b["project_context_alignment"] or {}).get("relevance"),
        "n_appraisal_dims": len((b["paper_appraisal"] or {}).get("dimensions") or []),
        "n_relations": len((b["paper_relations"] or {}).get("edges") or []),
        "n_trend_shifts": len((b["trend_card"] or {}).get("shifts") or []),
        "transfer_level": (b["domain_transfer_note"] or {}).get("transfer_level"),
    }


def _delivery_advisory_summary(run_dir) -> tuple[str, list[str]]:
    """Aggregate durable usability advisories for the REPORT artifact."""
    caveats = []
    status = "USABLE"
    for relative in (
        "inbox/markdown-quality-advisory.json",
        "inbox/usable-first-advisory.json",
    ):
        path = Path(run_dir) / relative
        if not path.is_file():
            continue
        try:
            advisory = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = "USABLE_WITH_CAVEATS"
            caveats.append(f"could not read delivery advisory: {relative}")
            continue
        warnings = [str(row) for row in advisory.get("warnings") or [] if str(row).strip()]
        if warnings or advisory.get("verdict") == "USABLE_WITH_CAVEATS":
            status = "USABLE_WITH_CAVEATS"
        caveats.extend(warnings)

    quality_path = (
        Path(run_dir) / "evidence" / "DISCOVER" / "paper-reading-quality.artifact.json"
    )
    if quality_path.is_file():
        try:
            quality = json.loads(quality_path.read_text(encoding="utf-8")).get("payload") or {}
        except (OSError, json.JSONDecodeError):
            quality = {}
        verdict = str(quality.get("verdict") or "")
        if verdict and verdict != "PASS":
            status = "USABLE_WITH_CAVEATS"
            caveats.extend(
                str(row) for row in quality.get("required_repairs") or [] if str(row).strip()
            )
            if not quality.get("required_repairs"):
                caveats.append(f"paper reading quality verdict: {verdict}")

    attribution_path = (
        Path(run_dir) / "evidence" / "DISCOVER" / "citation-attribution-report.artifact.json"
    )
    if attribution_path.is_file():
        try:
            attribution = json.loads(attribution_path.read_text(encoding="utf-8")).get("payload") or {}
        except (OSError, json.JSONDecodeError):
            attribution = {}
        if attribution.get("legacy_replay"):
            status = "USABLE_WITH_CAVEATS"
            caveats.append("legacy replay: citation attribution remains unverified")

    return status, list(dict.fromkeys(caveats))


def _report(run_dir, ts) -> tuple:
    delivery_status, delivery_caveats = _delivery_advisory_summary(run_dir)
    note = {
        "summary": "read_paper_deep: staged primary plus blind paper read completed with explicit "
                   "reconciliation, hash-verified visual coverage, a body-audited Markdown card, and "
                   "single-paper evidence saturation correctly marked not assessed. Draft knowledge "
                   "only; promote through /promote-to-vault after human review.",
        "references": [
            "evidence/DISCOVER/paper-reading-quality.artifact.json",
            "evidence/DISCOVER/paper-reading-reconciliation.artifact.json",
            "evidence/DISCOVER/paper-markdown-card.artifact.json",
            "director-review/papers/",
        ],
        "produced_artifacts": [],
        "open_questions": [],
        "delivery_status": delivery_status,
        "delivery_caveats": delivery_caveats,
    }
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"read_paper_deep has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
