"""Operate read_paper_deep + ingest_paper paper-reading wiring tests.

read_paper_deep is a real staged paper-reading panel: a primary branch plus a
blind second reader, explicit reconciliation, nineteen typed artifacts,
hash-verified page visuals, and body-audited director Markdown.
ingest_paper intentionally remains the light Tier-S single-note path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import ingest_paper, read_paper_deep
from research_agent_teams.operate.panel_scheduler import schedule_next_wave
from research_agent_teams.tools import fulltext_qa
from research_agent_teams.tools.paper_markdown_quality import audit_paper_markdown
from research_agent_teams.tools.validate_artifact import validate_artifact, validate_payload

TS = "2026-06-26T12:00:00Z"
SOURCE = "doi:10.1109/TMI.2024.7654321"
NORTH_STAR = {
    "statement": "inferior alveolar canal segmentation in CBCT",
    "in_scope": ["canal", "segmentation", "CBCT", "foundation model"],
    "out_of_scope": [],
}
VISUAL_REF = "inbox/paper-visuals/doc-01/page-0001.png"
VISUAL_BYTES = b"unit-test-rendered-page-image"
VISUAL_SHA256 = hashlib.sha256(VISUAL_BYTES).hexdigest()
SOURCE_DOC_REF = "inbox/fulltext-docs/01-paper.pdf"

EXPECTED_DEEP_FILES = [
    "paper-reading-plan",
    "paper-note",
    "paper-structure",
    "project-context-alignment",
    "claim-list",
    "claim-evidence-map",
    "method-teardown",
    "figure-reading",
    "result-table-audit",
    "math-algorithm-audit",
    "paper-appraisal",
    "paper-relations",
    "trend-card",
    "domain-transfer-note",
    "reproducibility-materials-audit",
    "independent-reading-critique",
    "paper-reading-reconciliation",
    "paper-reading-quality",
    "paper-markdown-card",
]

# The citation-existence gate is forced OFFLINE + the vault unreachable by conftest's autouse
# `hermetic_gates` fixture, so every existence lookup degrades to a WARNING (the offline-safe PASS).


def _mk_run(tmp_path, name="run-1", mode="read_paper_deep", north_star=NORTH_STAR, budget=None,
            domain_profile_ref=None):
    run_dir = tmp_path / name
    (run_dir / "inbox").mkdir(parents=True)
    tf = {
        "payload": {
            "task_id": name,
            "mode": mode,
            "north_star": north_star,
            "budget": budget or {"max_agent_hops": 24, "max_debug_retries_per_run": 3},
        }
    }
    if domain_profile_ref:
        tf["payload"]["domain_profile_ref"] = domain_profile_ref
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_ingest_bundle(run_dir, payload):
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _with_citation_truth(run_dir, payload):
    payload = copy.deepcopy(payload)
    payload["claim_evidence_map"]["attribution_contract_version"] = "claim-span/v1"
    audit_rows = []
    for mapping in payload["claim_evidence_map"]["mappings"]:
        verified = []
        unsupported = []
        for locus in mapping["loci"]:
            quote = str(locus.get("reported_result") or "")
            snapshot_ref = f"inbox/citation-snapshots/{locus['locus_id']}.txt"
            snapshot = Path(run_dir) / snapshot_ref
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(quote, encoding="utf-8")
            supports = locus.get("supports_claim") is True
            relation = (
                "entails" if supports and mapping.get("overall_support") == "supported"
                else "partial" if supports
                else "contradicts"
            )
            locus.update({
                "support_relation": relation,
                "span_id": f"SPAN-{locus['locus_id']}",
                "snapshot_ref": snapshot_ref,
                "document_hash": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                "parser_version": "utf-8-char/v1",
                "char_start": 0,
                "char_end": len(quote),
                "exact_quote": quote,
            })
            if locus.get("kind") == "figure":
                locus["figure_region_ref"] = VISUAL_REF
            (verified if supports else unsupported).append(locus["locus_id"])
        verdict = (
            "entails" if mapping.get("overall_support") == "supported"
            else "partial" if mapping.get("overall_support") == "partial"
            else "contradicts"
        )
        audit_rows.append({
            "claim_id": mapping["claim_id"],
            "verdict": verdict,
            "locator_verified": True,
            "verified_locus_ids": verified,
            "unsupported_locus_ids": unsupported,
            "notes": "independent source reread confirmed the frozen claim-locus relation",
        })
    payload["citation_audit"] = {
        "contract_version": "citation-attribution/v1",
        "independent_of_linker": True,
        "claim_results": audit_rows,
    }
    return payload


def _write_deep_worker_bundles(run_dir, payload, skip_agents=(), *, strict=True):
    if strict:
        payload = _with_citation_truth(run_dir, payload)
    skip = set(skip_agents)
    for key, _atype, agent, _fname, _status in read_paper_deep.ARTIFACT_PLAN:
        if agent in skip:
            continue
        p = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        p.write_text(json.dumps({key: payload[key]}, ensure_ascii=False), encoding="utf-8")
    if strict and read_paper_deep.CITATION_AUDITOR_AGENT not in skip:
        p = run_dir / "inbox" / "DISCOVER.citation-coverage-auditor.bundle.json"
        p.write_text(json.dumps({"citation_audit": payload["citation_audit"]}), encoding="utf-8")


def _write_fulltext_context(run_dir):
    source_doc = run_dir / SOURCE_DOC_REF
    source_doc.parent.mkdir(parents=True, exist_ok=True)
    source_doc.write_bytes(b"%PDF-1.4 unit-test source snapshot")
    visual = run_dir / VISUAL_REF
    visual.parent.mkdir(parents=True, exist_ok=True)
    visual.write_bytes(VISUAL_BYTES)
    (run_dir / "inbox" / "fulltext-qa.json").write_text(
        json.dumps({
            "available": True,
            "contexts": [
                {"doc_ref": SOURCE_DOC_REF, "page": 5, "excerpt": "Table 2 reports Dice."},
                {"doc_ref": SOURCE_DOC_REF, "page": 6, "excerpt": "Figure 4 reports continuity."},
            ],
        }),
        encoding="utf-8",
    )
    (run_dir / "inbox" / "paper-visual-manifest.json").write_text(
        json.dumps({
            "manifest_version": "1.0.0",
            "status": "AVAILABLE",
            "render_engine": "unit-test",
            "render_scale": 1.0,
            "documents": [{
                "doc_ref": SOURCE_DOC_REF,
                "document_sha256": hashlib.sha256(source_doc.read_bytes()).hexdigest(),
                "pages": [{
                    "page": 1,
                    "image_ref": VISUAL_REF,
                    "image_sha256": VISUAL_SHA256,
                    "width": 100,
                    "height": 100,
                }],
            }],
            "errors": [],
        }),
        encoding="utf-8",
    )


def _with_page_anchors(bundle):
    b = copy.deepcopy(bundle)
    for mapping in b["claim_evidence_map"]["mappings"]:
        for idx, locus in enumerate(mapping["loci"], start=1):
            locus["page"] = idx + 4
            locus["locator_confidence"] = "high"
            locus["extraction_ref"] = f"fulltext-qa.context.{idx}"
    return b


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


def _load(paths, needle):
    return json.loads(Path(next(p for p in paths if needle in p)).read_text(encoding="utf-8"))


def _markdown(source_ref=SOURCE):
    return "\n".join([
        "# A foundation model for inferior alveolar canal segmentation in CBCT",
        "",
        "## Decision Need",
        "Use this paper to decide whether a foundation-model adapter plus topology-aware loss is a "
        "credible first-wave method branch for inferior alveolar canal segmentation in CBCT.",
        "",
        "## Project Alignment",
        "The paper claims that adapting a segmentation foundation model with a low-rank adapter "
        "and a boundary-aware loss improves canal segmentation in CBCT, especially continuity.",
        "",
        "## Claims and evidence",
        f"- Claim c1 is anchored to {source_ref}, Table 2: the adapted model improves Dice over nnU-Net.",
        f"- Claim c2 is anchored to {source_ref}, Figure 4: the boundary term reduces broken canals.",
        "",
        "## Method reconstruction",
        "The method freezes a foundation-model encoder, trains a small adapter and decoder, and uses "
        "Dice plus a boundary term. The useful causal hypothesis is not just 'FM is better'; it is "
        "that the boundary term plus frozen representation changes the topology error profile.",
        "",
        "## Numeric Results",
        "Table 2 supports c1: Dice is higher-is-better and the reported comparison is 0.91 vs 0.85 "
        "against nnU-Net. Figure 4 supports c2: continuity errors are lower, with fewer breaks. Missing fold-level variance "
        "means this is a useful prior, not a final generalization claim.",
        "",
        "## Algorithm And Math",
        "The algorithmic mechanism is internally clear enough for a local reimplementation: frozen "
        "encoder, adapter/decoder training, Dice plus boundary objective, then a single forward pass "
        "plus connected-component cleanup at inference.",
        "",
        "## Figure/table reading",
        "Table 2 carries the headline metric comparison. Figure 4 carries the topological continuity "
        "argument, but it lacks fold-level variance, so the continuity claim should be treated as "
        "plausible rather than settled.",
        "",
        "## Appraisal and transfer",
        "The paper is useful as a method prior for thin-structure segmentation. It is not enough to "
        "claim clinical generalization or multi-center robustness because it is single-center, has no "
        "cross-scanner test, and has no scanner transfer evidence. Required local validation is held-out "
        "CBCT, a topology metric, a scanner split, Dice, HD95, centerline continuity, and failure cases.",
        "",
        "## Reproducibility",
        "The paper gives enough method detail to sketch a local branch, but missing public code and "
        "seed variance keep reproduction risk medium.",
        "",
        "## Independent Critique",
        "The blind second reader and primary reader were reconciled. Both support the method-design "
        "use, while the director warning is: use as an A-core design prior, not as clinical robustness "
        "evidence. Scanner transfer and topology variance remain accepted limitations.",
        "Multi-source evidence saturation was not assessed in this single-paper read.",
        "",
        "## Next Actions",
        "Use it to define an ablation template, not to claim clinical robustness. The local validation "
        "must include held-out CBCT, scanner split, Dice, HD95, centerline continuity, and failure cases.",
        "",
        "## Reviewer attack points",
        "- Where is the cross-scanner validation?",
        "- Are topology metrics reported with variance?",
        "- Does the adapter still help when the boundary loss is tuned for nnU-Net?",
        "- Was the patient-level split preserved after preprocessing?",
        "- Does HD95 improve as clearly as Dice?",
    ])


def _good_bundle(source_ref=SOURCE):
    """A clean staged deep read: every worker payload is valid and anchored to the paper."""
    return {
        "paper_reading_plan": {
            "source_hint": source_ref,
            "reading_objective": "establish whether foundation-model adaptation helps canal segmentation",
            "decision_need": "choose whether to include an FM-adapter plus topology-loss branch",
            "key_questions": [
                "does the method improve canal Dice over nnU-Net?",
                "does it improve topological continuity?",
                "what local validation is required before using it in our project?",
            ],
            "required_outputs": [
                "claim evidence map",
                "method teardown",
                "numeric result audit",
                "domain transfer boundary",
            ],
            "reread_triggers": ["unread load-bearing Table 2", "missing Figure 4 continuity evidence"],
            "not_for": ["clinical robustness claim without cross-scanner validation"],
        },
        "paper_note": {
            "title": "A foundation model for inferior alveolar canal segmentation in CBCT",
            "source_ref": source_ref,
            "summary": "Adapts a segmentation foundation model to thin tubular canal structures in CBCT "
                       "volumes, improving topological continuity over supervised baselines.",
            "claims": [
                "the adapted foundation model beats nnU-Net on canal segmentation Dice",
                "topological continuity improves with the boundary loss",
            ],
            "methods": ["low-rank adapter", "boundary loss"],
            "datasets": ["CBCT"],
            "metrics": ["Dice"],
            "paper_type": "method",
            "read_purpose": "method",
            "relation_to_thesis": "A-core",
            "reading_objective": "establish whether foundation-model adaptation helps canal segmentation",
            "reading_status": "deep-read",
            "paper_contract": {
                "category": "method",
                "context": "CBCT canal segmentation",
                "correctness_prior": "plausible",
                "contributions": ["adapter", "loss"],
                "clarity": "clear",
                "contract_sentence": "thin canal segmentation -> FM adapter + boundary loss -> "
                                     "vs supervised -> Dice/HD95 -> CBCT only",
            },
        },
        "paper_structure": {
            "source_ref": source_ref,
            "sections": [
                {"section_ref": "Abstract", "role": "claim preview", "read_status": "read",
                 "key_points": ["foundation-model adaptation for CBCT canal segmentation"]},
                {"section_ref": "Methods", "role": "method definition", "read_status": "read",
                 "key_points": ["adapter", "boundary loss"]},
                {"section_ref": "Results", "role": "main evidence", "read_status": "read",
                 "key_points": ["Dice and continuity comparison"]},
            ],
            "figures": [
                {"figure_ref": "Figure 4", "read_status": "read", "load_bearing": True,
                 "reason": "continuity evidence"},
            ],
            "tables": [
                {"table_ref": "Table 2", "read_status": "read", "load_bearing": True,
                 "reason": "headline metric comparison"},
            ],
            "supplements": [],
            "coverage_gaps": [],
            "fulltext_available": True,
        },
        "project_context_alignment": {
            "source_ref": source_ref,
            "project_context": "IAC CBCT segmentation with foundation-model adaptation",
            "relevance": "A-core",
            "thesis_fit": "directly informs whether an FM adapter plus boundary loss should be tested",
            "advisor_questions": ["is the intent/metric signal measurable locally?"],
            "vault_or_project_refs": ["iac-cbct-seg"],
            "must_answer": ["whether the method is a baseline or a candidate branch"],
            "downstream_decisions": ["first-wave experiment branch", "metric set", "ablation template"],
            "misuse_risks": ["overclaiming scanner generalization"],
        },
        "claim_list": {
            "source_scope": "this paper",
            "claims": [
                {"claim_id": "c1", "text": "the adapted foundation model beats nnU-Net on canal Dice",
                 "source_ref": source_ref},
                {"claim_id": "c2", "text": "topological continuity improves with the boundary loss",
                 "source_ref": source_ref},
            ],
        },
        "claim_evidence_map": {
            "mappings": [
                {"claim_id": "c1", "overall_support": "supported",
                 "loci": [{"locus_id": "l1", "source_ref": source_ref, "location": "Table 2",
                           "kind": "table", "reported_result": "0.91 vs 0.85 Dice",
                           "supports_claim": True, "directness": "direct"}],
                 "claim_risk": {"level": "low", "note": "direct Dice comparison"}},
                {"claim_id": "c2", "overall_support": "supported",
                 "loci": [{"locus_id": "l2", "source_ref": source_ref, "location": "Figure 4",
                           "kind": "figure", "reported_result": "fewer canal breaks with boundary loss",
                           "supports_claim": True}]},
            ],
        },
        "method_teardown": {
            "source_ref": source_ref,
            "problem_definition": "input CBCT volume -> binary canal segmentation mask",
            "core_assumptions": ["the canal is a single connected tube"],
            "representation": "adds a low-rank adapter plus boundary-aware loss to a frozen "
                              "foundation-model encoder for canal segmentation",
            "loss_terms": [
                {"term": "Dice", "role": "region overlap", "ablate_effect": "recall drops"},
                {"term": "boundary", "role": "continuity", "ablate_effect": "more breaks"},
            ],
            "training_flow": "freeze encoder, train adapter and decoder with Dice plus boundary loss",
            "inference_flow": "single forward pass plus connected-component cleanup",
            "train_infer_consistency": "matched",
            "data": "480 CBCT volumes, patient-level split",
            "cost": "4.2M trainable params",
            "baseline_difference": "the boundary loss on a frozen FM",
        },
        "figure_reading": {
            "source_ref": source_ref,
            "visual_input_status": "INSPECTED_VISUAL",
            "visual_manifest_ref": "inbox/paper-visual-manifest.json",
            "figures": [
                {"figure_ref": "Figure 4", "axes": "method vs continuity-error count",
                 "inspection_status": "INSPECTED_VISUAL", "page": 1,
                 "visual_asset_ref": VISUAL_REF, "visual_asset_sha256": VISUAL_SHA256,
                 "controls": "nnU-Net, supervised FM", "error_bars": None,
                 "take_home": "the boundary loss reduces canal breaks",
                 "distrust": "no variance shown across folds"},
                {"figure_ref": "Table 2", "axes": "methods by Dice and HD95",
                 "inspection_status": "INSPECTED_VISUAL", "page": 1,
                 "visual_asset_ref": VISUAL_REF, "visual_asset_sha256": VISUAL_SHA256,
                 "controls": "nnU-Net", "error_bars": "not shown",
                 "take_home": "adapted FM has the best Dice",
                 "distrust": "single split may inflate ranking"},
            ],
        },
        "result_table_audit": {
            "source_ref": source_ref,
            "applicability": "applicable",
            "audited_items": [
                {"item_ref": "Table 2", "claim_id": "c1", "metric": "Dice",
                 "direction": "higher-is-better", "reported_comparison": "0.91 vs 0.85",
                 "audit": "adapted FM row is correctly bound against nnU-Net", "risk": "low"},
                {"item_ref": "Figure 4", "claim_id": "c2", "metric": "continuity errors",
                 "direction": "lower-is-better", "reported_comparison": "fewer breaks",
                 "audit": "supports topology direction but lacks fold variance", "risk": "medium"},
            ],
            "metric_direction_checks": "Dice higher is better; continuity error lower is better",
            "baseline_binding_checks": "adapted FM is compared to nnU-Net and supervised FM rows",
            "statistical_reporting": "no fold-level variance, so numeric certainty is limited",
            "leakage_or_split_risks": ["single-center split only"],
            "medical_segmentation_audit": None,
            "overall": "supports-headline",
        },
        "math_algorithm_audit": {
            "source_ref": source_ref,
            "applicability": "applicable",
            "formal_objects": ["frozen encoder", "low-rank adapter", "boundary loss"],
            "algorithm_flow": "freeze encoder, train adapter/decoder, apply single-pass inference",
            "equation_consistency": "loss terms align with the method teardown and ablation story",
            "complexity_or_cost": "4.2M trainable params reported",
            "implementation_assumptions": ["connected tube prior", "patient-level split"],
            "red_flags": ["boundary loss hyperparameter sensitivity is under-specified"],
            "overall": "strong",
        },
        "paper_appraisal": {
            "source_ref": source_ref,
            "paper_type": "method",
            "dimensions": [
                {"dim": "soundness", "score": 3, "evidence_ref": "Section 4", "note": "solid"},
                {"dim": "significance", "score": 3, "evidence_ref": "Abstract",
                 "note": "thin-structure continuity matters"},
                {"dim": "originality", "score": 3, "evidence_ref": "Methods",
                 "note": "adapter plus boundary loss is a plausible method delta"},
                {"dim": "eval_rigor", "score": 2, "evidence_ref": "Table 2",
                 "note": "single split, no variance"},
                {"dim": "reproducibility", "score": 2, "evidence_ref": "Supplement",
                 "note": "no code released"},
                {"dim": "clarity", "score": 3, "evidence_ref": "Methods",
                 "note": "training flow is clear enough"},
                {"dim": "domain_validity", "score": 2, "evidence_ref": "Dataset section",
                 "note": "single-center CBCT only"},
            ],
            "assumptions": ["canal connectivity"],
            "limitations_acknowledged": ["single center"],
            "limitations_unacknowledged": ["no cross-scanner test"],
            "baseline_fairness": "nnU-Net tuned, fair",
            "ablation_sufficiency": "loss terms ablated",
            "statistical_robustness": "no variance reported",
            "selective_reporting": "none evident",
            "reproducibility_gaps": ["no code"],
            "generalization": "single-center only",
            "reviewer_questions": ["how does it transfer across scanners?"],
            "checklist": {
                "standard": "tripod_ai",
                "items": [{"item": "reports calibration", "status": "unmet", "note": "absent"}],
            },
            "overall": "a solid single-center method paper; eval rigor is the weakness",
        },
        "paper_relations": {
            "source_ref": source_ref,
            "edges": [
                {"target_ref": "[[nnunet]]", "relation": "extends",
                 "note": "uses nnU-Net as the baseline"},
                {"target_ref": "doi:10.1000/sam", "relation": "uses",
                 "note": "adapts the SAM family"},
            ],
        },
        "trend_card": {
            "scope": "foundation-model adaptation for thin-structure CBCT segmentation",
            "shifts": [{"dimension": "method", "from": "fully supervised nnU-Net",
                        "to": "adapter-tuned foundation models"}],
            "failure_modes": ["broken tubular continuity"],
            "mechanism_vs_result": "mostly reports THAT, rarely explains WHY",
            "reproducibility_trend": "stagnant",
            "opportunities": ["topology-aware losses"],
            "source_refs": [source_ref],
        },
        "domain_transfer_note": {
            "source_ref": source_ref,
            "target_context": "our IAC CBCT segmentation and foundation-model adaptation project",
            "transfer_level": "direct",
            "usable_for": ["method prior", "metric list", "ablation template"],
            "not_usable_for": ["clinical generalization claim", "multi-center robustness claim"],
            "evidence_limits": ["single center", "no scanner transfer"],
            "required_local_validation": ["held-out CBCT", "topology metric", "scanner split"],
            "risk_of_overclaim": "medium",
        },
        "reproducibility_materials_audit": {
            "source_ref": source_ref,
            "code_availability": "no public code found in the read",
            "data_availability": "CBCT data described but not openly downloadable",
            "config_availability": "main training setup described, exact seeds absent",
            "environment": "GPU training environment not fully specified",
            "license_or_access_constraints": ["clinical CBCT access restrictions"],
            "reproduction_steps": ["implement adapter", "train with Dice plus boundary loss"],
            "missing_materials": ["public code", "seed list", "scanner split details"],
            "reproducibility_risk": "medium",
        },
        "independent_reading_critique": {
            "source_ref": source_ref,
            "reading_mode": "blind_second_read",
            "primary_analysis_seen": False,
            "allowed_input_classes": [
                "task_frame", "source_document", "fulltext_snapshot", "visual_snapshot",
            ],
            "consumed_inputs": [
                {"input_class": "task_frame", "ref": "task_frame.artifact.json"},
                {"input_class": "source_document", "ref": SOURCE_DOC_REF},
                {"input_class": "fulltext_snapshot", "ref": "inbox/fulltext-qa.json"},
                {"input_class": "visual_snapshot", "ref": "inbox/paper-visual-manifest.json"},
                {"input_class": "visual_snapshot", "ref": VISUAL_REF},
            ],
            "independent_summary": {
                "claims": [
                    "the adapted foundation model improves Dice over nnU-Net",
                    "the boundary term reduces canal breaks",
                ],
                "method": "frozen encoder with low-rank adapter and boundary-aware loss",
                "key_results": ["Table 2 reports 0.91 vs 0.85 Dice", "Figure 4 shows fewer breaks"],
                "limitations": ["single-center data", "no cross-scanner validation"],
            },
            "verdict": "PASS",
            "disagreements": [],
            "missed_claims": [],
            "overclaim_risks": ["single-center scanner generalization"],
            "alternative_interpretations": ["boundary loss may drive most of the gain, not FM adaptation"],
            "required_repairs": [],
            "director_warning": "use as A-core design prior, not as clinical robustness evidence",
        },
        "paper_reading_reconciliation": {
            "source_ref": source_ref,
            "comparison_performed": True,
            "blind_bundle_ref": "inbox/DISCOVER.independent-reading-critic.bundle.json",
            "primary_bundle_refs": [
                "inbox/DISCOVER.claim-extractor.bundle.json",
                "inbox/DISCOVER.claim-evidence-linker.bundle.json",
                "inbox/DISCOVER.method-teardown-extractor.bundle.json",
                "inbox/DISCOVER.figure-reader.bundle.json",
                "inbox/DISCOVER.result-table-auditor.bundle.json",
                "inbox/DISCOVER.math-algorithm-verifier.bundle.json",
                "inbox/DISCOVER.paper-appraiser.bundle.json",
                "inbox/DISCOVER.domain-transfer-critic.bundle.json",
            ],
            "agreements": ["both readers identify the adapter/loss branch and single-center limit"],
            "disagreements": [{
                "disagreement_id": "d1",
                "topic": "source of improvement",
                "primary_position": "adapter plus boundary loss is the method delta",
                "blind_position": "boundary loss may explain most of the gain",
                "resolution": "retain both as an unresolved mechanism alternative for local ablation",
                "evidence_ref": "Table 2 and Figure 4",
                "repair_required": False,
            }],
            "missed_by_primary": [],
            "missed_by_blind_reader": [],
            "repair_ledger": [],
            "unresolved_repairs": [],
            "verdict": "PASS",
            "director_warning": "use as A-core design prior, not as clinical robustness evidence",
        },
        "paper_reading_quality": {
            "source_ref": source_ref,
            "verdict": "PASS",
            "coverage": "full",
            "single_paper_completeness": "complete",
            "source_fidelity": "strong",
            "visual_coverage": "complete",
            "evidence_saturation": "not-assessed-single-paper",
            "anchoring": "strong",
            "method_depth": "strong",
            "figure_table_coverage": "complete",
            "result_table_depth": "strong",
            "algorithmic_depth": "strong",
            "reproducibility_depth": "mixed",
            "project_alignment": "strong",
            "domain_transfer_honesty": "strong",
            "independent_critique_resolution": "resolved",
            "markdown_ready": True,
            "promotion_ready": False,
            "strengths": ["claims linked to loci", "method reconstructed", "transfer boundary explicit"],
            "required_repairs": [],
            "reviewer_attack_points": [
                "single-center validation",
                "variance missing",
                "cross-scanner split absent",
                "HD95 direction and topology metrics need local confirmation",
                "adapter versus boundary-loss contribution may be confounded",
            ],
        },
        "paper_markdown_card": {
            "source_ref": source_ref,
            "title": "A foundation model for inferior alveolar canal segmentation in CBCT",
            "markdown": _markdown(source_ref),
            "evidence_refs": ["Table 2", "Figure 4", "Section 4"],
            "covered_claim_ids": ["c1", "c2"],
            "covered_figure_refs": ["Table 2", "Figure 4"],
            "covered_sections": [
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
            ],
            "quality_verdict": "PASS",
        },
    }


def _medical_enriched_bundle():
    b = _with_page_anchors(_good_bundle())
    b["paper_appraisal"]["medical_imaging_checklist"] = {
        "standard_refs": ["claim", "tripod_ai", "stard_ai", "strobe"],
        "items": [
            {"item_id": "CLAIM-MI-01", "standard_ref": "claim", "category": "patient_split",
             "status": "met", "evidence_ref": "Dataset section",
             "risk": "low"},
            {"item_id": "CLAIM-MI-07", "standard_ref": "claim", "category": "external_validation",
             "status": "unmet", "evidence_ref": "Limitations",
             "risk": "medium", "required_fix": "run an external scanner/site split locally"},
            {"item_id": "CLAIM-MI-03", "standard_ref": "claim", "category": "annotation_protocol",
             "status": "partial", "evidence_ref": "Methods",
             "risk": "medium"},
            {"item_id": "CROSS-MI-READER", "standard_ref": "cross_standard",
             "category": "inter_reader_variability", "status": "unmet", "evidence_ref": "Methods",
             "risk": "medium"},
            {"item_id": "CLAIM-MI-02", "standard_ref": "claim", "category": "scanner_site_shift",
             "status": "unmet", "evidence_ref": "Dataset section",
             "risk": "medium"},
            {"item_id": "CLAIM-MI-04", "standard_ref": "claim", "category": "metric_direction",
             "status": "met", "evidence_ref": "Table 2",
             "risk": "low"},
            {"item_id": "CLAIM-MI-05", "standard_ref": "claim",
             "category": "statistical_uncertainty", "status": "partial", "evidence_ref": "Table 2",
             "risk": "medium"},
            {"item_id": "TRIPODAI-MI-01", "standard_ref": "tripod_ai",
             "category": "clinical_claim_boundary", "status": "met", "evidence_ref": "Discussion",
             "risk": "low"},
            {"item_id": "CROSS-MI-LEAKAGE", "standard_ref": "cross_standard",
             "category": "preprocessing_leakage", "status": "met", "evidence_ref": "Methods",
             "risk": "low"},
            {"item_id": "CLAIM-MI-06", "standard_ref": "claim", "category": "failure_case_analysis",
             "status": "partial", "evidence_ref": "Figure 4",
             "risk": "medium"},
            {"item_id": "STARDAI-MI-01", "standard_ref": "stard_ai",
             "category": "annotation_protocol", "status": "partial", "evidence_ref": "Methods",
             "risk": "medium"},
            {"item_id": "CROSS-MI-CLINICAL-BOUNDARY", "standard_ref": "cross_standard",
             "category": "clinical_claim_boundary", "status": "met", "evidence_ref": "Discussion",
             "risk": "low"},
        ],
    }
    b["result_table_audit"]["medical_segmentation_audit"] = {
        "task_context": "tubular_structure",
        "items": [
            {"category": "patient_or_case_level_split", "status": "met",
             "evidence_ref": "Dataset section", "risk": "low"},
            {"category": "metric_direction_and_unit", "status": "met",
             "evidence_ref": "Table 2", "risk": "low"},
            {"category": "baseline_binding", "status": "met",
             "evidence_ref": "Table 2", "risk": "low"},
            {"category": "statistical_uncertainty", "status": "partial",
             "evidence_ref": "Table 2", "risk": "medium"},
            {"category": "per_case_failure_analysis", "status": "partial",
             "evidence_ref": "Figure 4", "risk": "medium"},
        ],
    }
    b["domain_transfer_note"]["transfer_matrix"] = [
        {"axis": "modality", "source_setting": "CBCT", "target_setting": "CBCT",
         "match_level": "same", "implication": "modality evidence transfers directly"},
        {"axis": "anatomy_or_task", "source_setting": "canal segmentation",
         "target_setting": "inferior alveolar canal segmentation", "match_level": "close",
         "implication": "task is close enough for method-prior use"},
        {"axis": "dataset_population", "source_setting": "single-center CBCT",
         "target_setting": "local held-out CBCT", "match_level": "close",
         "implication": "needs local held-out validation"},
        {"axis": "scanner_or_site", "source_setting": "single site",
         "target_setting": "scanner/site-shift possible", "match_level": "unknown",
         "implication": "do not claim cross-site robustness"},
        {"axis": "annotation_protocol", "source_setting": "expert canal labels",
         "target_setting": "project canal labels", "match_level": "close",
         "implication": "compare annotation protocol before citing"},
        {"axis": "metrics", "source_setting": "Dice and continuity",
         "target_setting": "Dice, HD95, topology continuity", "match_level": "close",
         "implication": "add HD95/topology local checks"},
        {"axis": "deployment_context", "source_setting": "retrospective evaluation",
         "target_setting": "research prototype", "match_level": "close",
         "implication": "no clinical deployment claim"},
    ]
    b["paper_reading_quality"]["reviewer_attack_points"] = [
        {"category": "baseline_fairness", "attack": "Was nnU-Net tuned to the same budget?",
         "evidence_ref": "Table 2", "severity": "medium"},
        {"category": "dataset_split_leakage", "attack": "Is the patient-level split preserved?",
         "evidence_ref": "Dataset section", "severity": "high"},
        {"category": "statistical_uncertainty", "attack": "Where are fold variance and CIs?",
         "evidence_ref": "Table 2", "severity": "medium"},
        {"category": "transfer_generalization", "attack": "No scanner/site transfer is shown.",
         "evidence_ref": "Limitations", "severity": "medium"},
        {"category": "reproducibility", "attack": "No code or seeds are released.",
         "evidence_ref": "Supplement", "severity": "medium"},
    ]
    b["paper_markdown_card"]["covered_sections"] += [
        "medical-imaging-checklist",
        "transfer-matrix",
    ]
    b["paper_markdown_card"]["markdown"] += (
        "\n\n## Medical Imaging Checklist\nPatient split, metric direction, clinical claim boundary, "
        "and preprocessing leakage are explicitly checked; external validation remains a local repair.\n"
        "\n## Transfer Matrix\nCBCT modality matches, scanner/site transfer is unknown, and no clinical "
        "deployment claim is supported.\n"
    )
    return b


# ---------------- read_paper_deep happy path ----------------


def test_read_paper_deep_writes_all_nineteen_artifacts_and_gates_approve(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)

    for needle in EXPECTED_DEEP_FILES:
        assert any(needle in p for p in paths), f"missing artifact {needle}"
    assert report["citation_gate"] == "PASS" and report["existence_gate"] == "PASS"
    assert report["quality_verdict"] == "PASS"
    assert report["single_paper_completeness"] == "complete"
    assert report["source_fidelity"] == "strong"
    assert report["visual_coverage"] == "complete"
    assert report["evidence_saturation"] == "not-assessed-single-paper"
    assert report["markdown_semantic_verdict"] == "PASS"
    assert not any("evidence-verdict" in p for p in paths), "saturation gate must be skipped for 1 source"
    drift = _load(paths, "drift-verdict")
    assert drift["status"] == "approved" and drift["payload"]["pass"] is True
    assert report["n_claims"] == 2 and report["n_figures"] == 2 and report["n_relations"] == 2
    assert report["n_loss_terms"] == 2 and report["n_appraisal_dims"] == 7 and report["n_trend_shifts"] == 1
    assert report["result_table_overall"] == "supports-headline"
    assert report["math_algorithm_overall"] == "strong"
    assert report["reproducibility_risk"] == "medium"
    assert report["independent_critique_verdict"] == "PASS"
    assert report["reconciliation_verdict"] == "PASS"
    assert report["project_relevance"] == "A-core"
    assert report["transfer_level"] == "direct"
    assert Path(report["director_markdown_card"]).is_file()
    rendered_markdown = Path(report["director_markdown_card"]).read_text(encoding="utf-8")
    assert "Reviewer attack points" in rendered_markdown
    assert "![" not in rendered_markdown, (
        "a complete text equivalent must remain PASS-capable when no stable copied image is embedded"
    )
    attribution = _load(paths, "citation-attribution-report")
    assert attribution["payload"]["mechanical_verification"]["n_verified"] == 2
    assert attribution["payload"]["verdict"] == "PASS"
    _validate_written(paths)

    rpaths, _ = read_paper_deep.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)


def test_read_paper_deep_medical_profile_requires_business_rigor(tmp_path):
    run_dir = _mk_run(tmp_path, domain_profile_ref="cv-medical-segmentation")
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _medical_enriched_bundle())
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["quality_verdict"] == "PASS"
    _validate_written(paths)

    bad_run = _mk_run(tmp_path, name="medical-bad", domain_profile_ref="cv-medical-segmentation")
    _write_fulltext_context(bad_run)
    bad = _medical_enriched_bundle()
    bad["domain_transfer_note"]["transfer_matrix"] = []
    _write_deep_worker_bundles(bad_run, bad)
    _paths, report = read_paper_deep.run_dets(bad_run, "DISCOVER", TS)
    advisory = json.loads((bad_run / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("transfer_matrix axes" in row for row in advisory["warnings"])


def test_read_paper_deep_local_pdf_pass_requires_page_anchors(tmp_path):
    run_dir = _mk_run(tmp_path)
    (run_dir / "inbox" / "fulltext-qa.json").write_text(
        json.dumps({"available": True, "contexts": [{"doc_ref": "paper.pdf", "page": 3}]}),
        encoding="utf-8",
    )
    _write_deep_worker_bundles(run_dir, _good_bundle())
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("page anchor" in row for row in advisory["warnings"])


def test_read_paper_deep_a_core_pass_requires_fulltext_pre(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("fulltext-pre" in row for row in advisory["warnings"])


def test_read_paper_deep_medical_profile_requires_item_bank_coverage(tmp_path):
    run_dir = _mk_run(tmp_path, domain_profile_ref="cv-medical-segmentation")
    _write_fulltext_context(run_dir)
    bad = _medical_enriched_bundle()
    bad["paper_appraisal"]["medical_imaging_checklist"]["items"] = [
        item for item in bad["paper_appraisal"]["medical_imaging_checklist"]["items"]
        if item.get("item_id") != "STARDAI-MI-01"
    ]
    _write_deep_worker_bundles(run_dir, bad)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("STARDAI-MI-01" in row for row in advisory["warnings"])


def test_read_paper_deep_autopet_context_requires_interactive_result_lens(tmp_path):
    north_star = {
        "statement": "autoPET-V PET/CT interactive lesion correction with oracle intent",
        "in_scope": ["autoPET", "PET/CT", "lesion", "interactive", "oracle intent"],
        "out_of_scope": [],
    }
    run_dir = _mk_run(tmp_path, domain_profile_ref="cv-medical-segmentation",
                      north_star=north_star)
    _write_fulltext_context(run_dir)
    bad = _medical_enriched_bundle()
    _write_deep_worker_bundles(run_dir, bad)
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "north-star drift gate BLOCK" in str(ei.value)


def test_read_paper_deep_paper_note_written_as_draft(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    paths, _ = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    note = _load(paths, "paper-note")
    assert note["status"] == "draft" and note["artifact_type"] == "paper_note"


# ---------------- read_paper_deep appraisal stays advisory ----------------


def test_read_paper_deep_appraisal_is_advisory_never_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["paper_appraisal"]["dimensions"] = [
        {"dim": d, "score": 1, "evidence_ref": "Section 4", "note": "poor"}
        for d in (
            "soundness",
            "significance",
            "originality",
            "eval_rigor",
            "reproducibility",
            "clarity",
            "domain_validity",
        )
    ]
    b["paper_appraisal"]["overall"] = "weak paper on every axis"
    _write_deep_worker_bundles(run_dir, b)
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_gate"] == "PASS"
    appraisal = _load(paths, "paper-appraisal")["payload"]
    for forbidden in ("verdict", "decision", "accept", "reject", "meets_bar", "status", "cut"):
        assert forbidden not in appraisal


# ---------------- read_paper_deep hard-gate BLOCKs ----------------


def test_read_paper_deep_missing_worker_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_worker_bundles(run_dir, _good_bundle(), skip_agents={"trend-card-builder"})
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "trend-card-builder" in str(ei.value) and "missing worker bundle" in str(ei.value)


def test_read_paper_deep_current_run_cannot_omit_citation_auditor(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_worker_bundles(
        run_dir, _good_bundle(), skip_agents={"citation-coverage-auditor"})
    with pytest.raises(GateBlock, match="citation-coverage-auditor"):
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)


def test_read_paper_deep_recomputes_snapshot_hash_and_blocks_tampering(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    (run_dir / "inbox" / "citation-snapshots" / "l1.txt").write_text(
        "tampered after linker output", encoding="utf-8")
    with pytest.raises(GateBlock) as exc:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "SHA-256 mismatch" in str(exc.value)


def test_read_paper_deep_quote_locator_mismatch_is_visible_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    linker = run_dir / "inbox" / "DISCOVER.claim-evidence-linker.bundle.json"
    payload = json.loads(linker.read_text(encoding="utf-8"))
    payload["claim_evidence_map"]["mappings"][0]["loci"][0]["exact_quote"] = "fabricated quote"
    linker.write_text(json.dumps(payload), encoding="utf-8")
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("exact_quote mismatch" in row for row in advisory["warnings"])


def test_source_document_identity_accepts_relative_or_mojibaked_parent_path():
    canonical = (
        "C:/Users/user/Desktop/project/run/inbox/fulltext-docs/01-paper.pdf"
    )
    relative = "inbox/fulltext-docs/01-paper.pdf"
    mojibaked_parent = (
        "C:/Users/garbled-name/Desktop/project/run/inbox/fulltext-docs/01-paper.pdf"
    )
    assert read_paper_deep._same_source_document(canonical, relative)
    assert read_paper_deep._same_source_document(canonical, mojibaked_parent)
    assert not read_paper_deep._same_source_document(
        canonical, "inbox/fulltext-docs/02-different-paper.pdf"
    )


def test_single_local_pdf_can_bind_to_canonical_external_source(tmp_path):
    docs = tmp_path / "inbox" / "fulltext-docs"
    docs.mkdir(parents=True)
    (docs / "01-paper.pdf").write_bytes(b"paper")
    assert read_paper_deep._same_source_document(
        "arXiv:2102.06583", "inbox/fulltext-docs/01-paper.pdf", tmp_path,
    )
    (docs / "02-other.pdf").write_bytes(b"other")
    assert not read_paper_deep._same_source_document(
        "arXiv:2102.06583", "inbox/fulltext-docs/01-paper.pdf", tmp_path,
    )


def test_inside_run_accepts_cwd_relative_path_that_already_contains_run_root(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    run_dir = workspace / "research_agent_teams" / "runs" / "proj" / "run-1"
    target = run_dir / "inbox" / "fulltext-qa.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(workspace)
    ref = target.relative_to(workspace).as_posix()
    assert read_paper_deep._inside_run(run_dir, ref) == target.resolve()


def test_read_paper_deep_explicit_legacy_replay_is_draft_and_never_passes(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    (run_dir / "inbox" / "citation-legacy-replay.json").write_text(json.dumps({
        "contract_version": "citation-legacy-replay/v1",
        "legacy_replay": True,
        "reason": "historical read fixture predates exact claim-span attribution",
        "source_run_ref": "historical-paper-read",
    }), encoding="utf-8")
    _write_deep_worker_bundles(
        run_dir, _with_page_anchors(_good_bundle()), strict=False)
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["citation_attribution_gate"] == "LEGACY_UNVERIFIED"
    assert report["quality_verdict"] == "LEGACY_UNVERIFIED"
    assert report["source_fidelity"] == "unverified"
    assert report["markdown_semantic_verdict"] == "UNVERIFIED"
    attribution = _load(paths, "citation-attribution-report")
    assert attribution["status"] == "draft"
    assert attribution["payload"]["verdict"] == "UNVERIFIED"
    quality_artifact = _load(paths, "paper-reading-quality")
    assert quality_artifact["status"] == "draft"
    markdown = Path(report["director_markdown_card"]).read_text(encoding="utf-8")
    assert "LEGACY_UNVERIFIED" in markdown


def test_read_paper_deep_empty_source_ref_blocks_on_schema(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_deep_worker_bundles(run_dir, _good_bundle(source_ref=""))
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "source_ref BLOCK" in str(ei.value)


def test_read_paper_deep_unresolvable_locus_blocks_citation(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["claim_evidence_map"]["mappings"][0]["loci"][0]["source_ref"] = "doi:10.9999/not-this-paper"
    _write_deep_worker_bundles(run_dir, b)
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "citation gate BLOCK" in str(ei.value)


def test_read_paper_deep_quality_auditor_delivers_reread_as_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    b["paper_reading_quality"].update({
        "verdict": "NEEDS_REREAD",
        "coverage": "partial",
        "markdown_ready": False,
        "required_repairs": ["read missing ablation details before director review"],
    })
    b["paper_markdown_card"]["quality_verdict"] = "NEEDS_REREAD"
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("missing ablation" in row for row in advisory["warnings"])


def test_read_paper_deep_quality_must_separate_single_paper_axes(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    del b["paper_reading_quality"]["evidence_saturation"]
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    quality = json.loads(
        (run_dir / "evidence" / "DISCOVER" / "paper-reading-quality.artifact.json").read_text()
    )["payload"]
    assert quality["evidence_saturation"] == "not-assessed-single-paper"


def test_read_paper_deep_unread_load_bearing_figure_is_visible_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    b["paper_structure"]["figures"][0]["read_status"] = "not-read"
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("unread load-bearing" in row for row in advisory["warnings"])


def test_read_paper_deep_markdown_claim_declaration_gap_is_advisory(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["paper_markdown_card"]["covered_claim_ids"] = ["c1"]
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "markdown-quality-advisory.json").read_text())
    assert report["director_markdown_card"]
    assert advisory["delivery_blocking"] is False
    assert any("Markdown card omits claim ids" in row for row in advisory["warnings"])


def test_read_paper_deep_markdown_ready_false_is_advisory(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["paper_reading_quality"]["markdown_ready"] = False
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "markdown-quality-advisory.json").read_text())
    assert Path(report["director_markdown_card"]).is_file()
    assert advisory["delivery_blocking"] is False
    assert "paper_reading_quality.markdown_ready is false" in advisory["warnings"]


def test_read_paper_deep_independent_critic_repairs_become_caveats(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    b["independent_reading_critique"]["verdict"] = "NEEDS_REREAD"
    b["independent_reading_critique"]["required_repairs"] = ["re-read the numeric table"]
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("independent_reading_critique" in row for row in advisory["warnings"])


def test_read_paper_deep_independent_critic_caveats_do_not_block_caveated_delivery(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["independent_reading_critique"]["verdict"] = "PASS_WITH_CAVEATS"
    b["independent_reading_critique"]["required_repairs"] = [
        "obtain the post-challenge result before promotion"
    ]
    b["paper_reading_quality"]["verdict"] = "PASS_WITH_CAVEATS"
    b["paper_reading_quality"]["source_fidelity"] = "mixed"
    b["paper_markdown_card"]["quality_verdict"] = "PASS_WITH_CAVEATS"
    b["paper_markdown_card"]["markdown"] += "\n## Caveats\nNo efficacy claim is promotion-ready.\n"
    _write_deep_worker_bundles(run_dir, b)

    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)

    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"


def test_read_paper_deep_blind_provenance_defect_targets_blind_reader(tmp_path):
    problems = ["PASS requires blind second reader to consume both source document and fulltext snapshot"]

    defects = read_paper_deep._classify_quality_defects(problems)

    assert defects[0]["target_agents"] == ["independent-reading-critic"]
    assert defects[0]["refresh_agents"] == [
        "paper-reading-reconciler", "paper-reading-quality-auditor", "paper-markdown-writer"
    ]


def test_read_paper_deep_blind_receipt_instruction_is_not_false_integrity_block(tmp_path):
    problems = [
        "局部补充 blind second reader：保持 primary_analysis_seen=false，登记 source_document；"
        "完成后只刷新 reconciliation、quality 和 Markdown。"
    ]

    defects = read_paper_deep._classify_quality_defects(problems)

    assert defects[0]["severity"] == "material"
    assert defects[0]["category"] == "blind-second-read"
    assert defects[0]["target_agents"] == ["independent-reading-critic"]


def test_read_paper_deep_blind_reader_bundle_provenance_is_delivery_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["independent_reading_critique"]["consumed_inputs"].append({
        "input_class": "source_document",
        "ref": "inbox/DISCOVER.claim-extractor.bundle.json",
    })
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("provenance names an analyst bundle" in row for row in advisory["warnings"])


def test_read_paper_deep_blind_bundle_timing_is_delivery_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    blind = run_dir / "inbox" / "DISCOVER.independent-reading-critic.bundle.json"
    primary = run_dir / "inbox" / "DISCOVER.claim-extractor.bundle.json"
    older = max(1, blind.stat().st_mtime_ns - 10_000_000)
    os.utime(primary, ns=(older, older))
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("temporal isolation is invalid" in row for row in advisory["warnings"])


def test_read_paper_deep_reconciliation_gaps_are_delivery_caveats(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["paper_reading_reconciliation"]["primary_bundle_refs"].remove(
        "inbox/DISCOVER.result-table-auditor.bundle.json"
    )
    b["paper_reading_reconciliation"]["disagreements"].append({
        "disagreement_id": "d2",
        "topic": "numeric interpretation",
        "primary_position": "headline result is stable",
        "blind_position": "variance is not reported",
        "resolution": "requires a repaired uncertainty statement",
        "evidence_ref": "Table 2",
        "repair_required": True,
    })
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("reconciliation omits required primary bundles" in row for row in advisory["warnings"])
    assert any("repair-required disagreements lack ledger entries" in row for row in advisory["warnings"])


def test_read_paper_deep_missing_visual_manifest_is_delivery_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    (run_dir / "inbox" / "paper-visual-manifest.json").unlink()
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("visual manifest" in row.casefold() for row in advisory["warnings"])


def test_read_paper_deep_tampered_visual_asset_hash_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    (run_dir / VISUAL_REF).write_bytes(b"tampered-after-manifest")
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "visual asset hash mismatch" in str(ei.value)


def test_read_paper_deep_tampered_source_snapshot_blocks_visual_provenance(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    (run_dir / SOURCE_DOC_REF).write_bytes(b"changed source after rendering")
    _write_deep_worker_bundles(run_dir, _with_page_anchors(_good_bundle()))
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "source-document hash mismatch" in str(ei.value)


def test_read_paper_deep_unread_visual_is_delivery_caveat(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["figure_reading"]["visual_input_status"] = "UNREAD_VISUAL"
    b["figure_reading"]["figures"][0]["inspection_status"] = "UNREAD_VISUAL"
    b["paper_reading_quality"]["visual_coverage"] = "unread"
    _write_deep_worker_bundles(run_dir, b)
    _paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "usable-first-advisory.json").read_text())
    assert report["quality_verdict"] == "PASS_WITH_CAVEATS"
    assert any("UNREAD_VISUAL" in row or "visual_coverage" in row for row in advisory["warnings"])


def test_markdown_body_claim_gap_is_advisory_despite_writer_self_report(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    assert "c2" in b["paper_markdown_card"]["covered_claim_ids"]
    b["paper_markdown_card"]["markdown"] = b["paper_markdown_card"]["markdown"].replace(
        f"- Claim c2 is anchored to {SOURCE}, Figure 4: the boundary term reduces broken canals.\n",
        "",
    ).replace("Figure 4 supports c2: ", "Figure 4 shows that ")
    _write_deep_worker_bundles(run_dir, b)
    read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "markdown-quality-advisory.json").read_text())
    assert any("substantively cover load-bearing claim c2" in row for row in advisory["warnings"])


def test_markdown_body_numeric_method_caveat_and_heading_gaps_are_advisory(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["method_teardown"]["loss_terms"].append({
        "term": "persistent homology auxiliary penalty",
        "role": "topology regularization",
        "ablate_effect": "unknown",
    })
    b["domain_transfer_note"]["not_usable_for"].append(
        "deployment on pediatric cone-beam CT without calibration"
    )
    b["paper_markdown_card"]["markdown"] = b["paper_markdown_card"]["markdown"].replace(
        "0.91 vs 0.85", "a higher score"
    ).replace("## Numeric Results", "Numeric Results")
    _write_deep_worker_bundles(run_dir, b)
    read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "markdown-quality-advisory.json").read_text())
    message = "\n".join(advisory["warnings"])
    assert "missing semantic section: numeric-results" in message
    assert "omits method component: persistent homology auxiliary penalty" in message
    assert "omits key audited result: Table 2" in message
    assert "pediatric cone-beam CT without calibration" in message


def test_markdown_visual_ref_without_visual_content_explanation_is_advisory(tmp_path):
    b = _with_page_anchors(_good_bundle())
    audit = audit_paper_markdown(
        "# Paper\n\nFigure 4 and Table 2 were inspected; see the source visuals.\n",
        b,
    )
    assert any(
        "does not explain its visual content" in row for row in audit["errors"]
    )


def test_markdown_body_missing_saturation_disclaimer_is_advisory(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_fulltext_context(run_dir)
    b = _with_page_anchors(_good_bundle())
    b["paper_markdown_card"]["markdown"] = b["paper_markdown_card"]["markdown"].replace(
        "Multi-source evidence saturation was not assessed in this single-paper read.\n", ""
    )
    _write_deep_worker_bundles(run_dir, b)
    read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    advisory = json.loads((run_dir / "inbox" / "markdown-quality-advisory.json").read_text())
    assert any("multi-source evidence saturation was not assessed" in row for row in advisory["warnings"])


def test_read_paper_deep_unknown_stage_raises_valueerror(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError):
        read_paper_deep.run_dets(run_dir, "NO_SUCH_STAGE", TS)


def test_read_paper_deep_llm_step_shape_carries_north_star(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = read_paper_deep.llm_step(run_dir, "DISCOVER", "read this canal paper", model_policy="default")
    assert spec["label"] == "read-paper-deep-panel"
    assert len(spec["workers"]) == 20
    assert spec["worker_order"][0] == "independent-reading-critic"
    assert spec["worker_order"][1] == "paper-reading-planner"
    assert spec["worker_order"][-1] == "paper-markdown-writer"
    assert spec["parallel_groups"] == read_paper_deep.READ_PAPER_PARALLEL_GROUPS
    assert len(spec["parallel_groups"]) == 12
    assert "blind second reader" in spec["panel_note"]
    assert all(w["output"].endswith(f"inbox/DISCOVER.{w['label']}.bundle.json") for w in spec["workers"])
    assert all("NORTH STAR" in w["prompt"] for w in spec["workers"])
    assert "read this canal paper" in spec["workers"][0]["prompt"]
    assert spec["workers"][0]["model"] == "opus"
    assert next(w for w in spec["workers"] if w["label"] == "literature-ingest")["model"] == "sonnet"
    assert spec["workers"][-1]["model"] == "opus"
    blind = next(w for w in spec["workers"] if w["label"] == "independent-reading-critic")
    assert blind["input_contract"]["blind"] is True
    assert blind["input_contract"]["allowed_bundle_agents"] == []
    assert "DO NOT open any inbox/DISCOVER.*.bundle.json" in blind["prompt"]
    assert not any(".bundle.json`" in line for line in blind["prompt"].splitlines()
                   if line.strip().startswith("- `"))
    reconciler = next(w for w in spec["workers"] if w["label"] == "paper-reading-reconciler")
    assert "independent-reading-critic" in reconciler["input_contract"]["allowed_bundle_agents"]
    citation = next(w for w in spec["workers"] if w["label"] == "citation-coverage-auditor")
    assert spec["worker_order"].index("citation-coverage-auditor") > spec["worker_order"].index(
        "claim-evidence-linker")
    assert "claim-evidence-linker" in citation["input_contract"]["allowed_bundle_agents"]
    assert "deterministic gate" in citation["prompt"]
    assert "image_input" in next(w for w in spec["workers"] if w["label"] == "figure-reader")["task_capabilities"]
    assert read_paper_deep.llm_step(run_dir, "REPORT", "q") is None


def test_read_paper_scheduler_executes_sparse_graph_in_twelve_waves(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = read_paper_deep.llm_step(run_dir, "DISCOVER", "read this paper")
    task_path = Path(run_dir) / "task_frame.artifact.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["payload"]["agent_subset"] = list(spec["worker_order"])
    task_path.write_text(json.dumps(task), encoding="utf-8")
    observed = []
    while True:
        decision = schedule_next_wave(run_dir, "DISCOVER", spec, ts=TS)
        if decision["status"] == "complete":
            break
        assert decision["status"] == "wave_ready"
        labels = [worker["label"] for worker in decision["workers"]]
        observed.append(labels)
        for worker in decision["workers"]:
            path = Path(worker["output"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
    assert observed == read_paper_deep.READ_PAPER_PARALLEL_GROUPS


def test_planner_can_skip_only_optional_specialists_with_valid_placeholders(tmp_path):
    run_dir = Path(_mk_run(tmp_path))
    policy = {key: "skip" for key in read_paper_deep.OPTIONAL_SPECIALISTS}
    (run_dir / "inbox" / "DISCOVER.paper-reading-planner.bundle.json").write_text(
        json.dumps({"paper_reading_plan": {
            "reading_objective": "read protocol", "decision_need": "choose experiment",
            "key_questions": ["q1", "q2", "q3"],
            "required_outputs": ["o1", "o2", "o3"], "specialist_policy": policy,
        }}), encoding="utf-8")
    (run_dir / "inbox" / "DISCOVER.literature-ingest.bundle.json").write_text(
        json.dumps({"paper_note": {"source_ref": "doi:10.1/protocol"}}), encoding="utf-8")
    spec = read_paper_deep.llm_step(str(run_dir), "DISCOVER", "read protocol")
    labels = set(spec["worker_order"])
    skipped = {agent for agents in read_paper_deep.OPTIONAL_SPECIALISTS.values() for agent in agents}
    assert not labels & skipped
    assert {"independent-reading-critic", "citation-coverage-auditor",
            "paper-reading-reconciler", "paper-reading-quality-auditor",
            "paper-markdown-writer"} <= labels
    for agent in skipped:
        path = run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json"
        bundle = json.loads(path.read_text(encoding="utf-8"))
        key = next(iter(bundle))
        assert validate_payload(key, bundle[key]) == []


def test_shared_paper_representation_is_reused_across_specialists(tmp_path):
    run_dir = Path(_mk_run(tmp_path))
    samples = {
        "literature-ingest": ("paper_note", {"source_ref": "paper", "summary": "summary"}),
        "paper-structure-mapper": ("paper_structure", {"source_ref": "paper", "sections": []}),
        "claim-extractor": ("claim_list", {"source_scope": "paper", "claims": []}),
    }
    for agent, (key, payload) in samples.items():
        (run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json").write_text(
            json.dumps({key: payload}), encoding="utf-8")
    spec = read_paper_deep.llm_step(str(run_dir), "DISCOVER", "read")
    shared = json.loads((run_dir / "inbox" / "shared-paper-representation.json").read_text())
    assert set(shared["components"]) == {"paper_note", "paper_structure", "claim_list"}
    nonblind = next(w for w in spec["workers"] if w["label"] == "method-teardown-extractor")
    assert "inbox/shared-paper-representation.json" in nonblind["input_contract"]["allowed_inputs"]
    assert "reuse it for stable note" in nonblind["prompt"]


def test_blind_second_reader_does_not_receive_domain_profile_or_primary_context(tmp_path):
    run_dir = str(_mk_run(tmp_path, domain_profile_ref="cv-medical-segmentation"))
    spec = read_paper_deep.llm_step(run_dir, "DISCOVER", "read the source")
    blind = next(worker for worker in spec["workers"]
                 if worker["label"] == "independent-reading-critic")
    primary = next(worker for worker in spec["workers"] if worker["label"] == "paper-appraiser")
    assert "DOMAIN READING PROFILE" not in blind["prompt"]
    assert "DOMAIN READING PROFILE" in primary["prompt"]
    assert blind["input_contract"]["allowed_bundle_agents"] == []


# ---------------- read_paper_deep optional fulltext pre-step ----------------


def test_fulltext_pre_no_docs_writes_nothing(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert read_paper_deep.fulltext_pre(str(run_dir), "what is the method?", [], TS) is None
    assert not (run_dir / "inbox" / "fulltext-qa.json").exists()


def test_fulltext_pre_degrades_honestly_when_paperqa_absent(tmp_path, monkeypatch):
    run_dir = _mk_run(tmp_path)
    monkeypatch.setattr(fulltext_qa, "paperqa_available", lambda: False)
    doc = str(tmp_path / "scratch" / "paper.pdf")
    p = read_paper_deep.fulltext_pre(str(run_dir), "what is the method?", [doc], TS)
    assert p is not None
    report = json.loads(Path(p).read_text(encoding="utf-8"))
    assert report["available"] is False and "paper-qa" in report["reason"]
    assert (run_dir / "inbox" / "fulltext-qa.json").exists()
    manifest = json.loads((run_dir / "inbox" / "paper-visual-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "UNAVAILABLE"


def test_fulltext_pre_extracts_existing_local_pdf_with_pymupdf(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    run_dir = _mk_run(tmp_path)
    pdf = tmp_path / "scratch" / "skeleton-recall.pdf"
    pdf.parent.mkdir()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Skeleton Recall Loss preserves canal connectivity in CBCT volumes.")
    doc.save(str(pdf))
    doc.close()

    monkeypatch.setattr(fulltext_qa, "paperqa_available", lambda: False)
    p = read_paper_deep.fulltext_pre(str(run_dir), "skeleton recall canal connectivity", [str(pdf)], TS)
    report = json.loads(Path(p).read_text(encoding="utf-8"))
    assert report["available"] is True
    assert report["contexts"] and report["contexts"][0]["page"] == 1
    assert "Skeleton Recall Loss" in report["contexts"][0]["excerpt"]
    assert (run_dir / "inbox" / "fulltext-qa.json").exists()
    citation_manifest = json.loads(
        (run_dir / "inbox" / "citation-snapshots" / "fulltext-contexts.manifest.json")
        .read_text(encoding="utf-8")
    )
    citation_snapshot = run_dir / citation_manifest["snapshot_ref"]
    assert citation_snapshot.is_file()
    assert hashlib.sha256(citation_snapshot.read_bytes()).hexdigest() == citation_manifest["document_hash"]
    assert citation_manifest["contexts"][0]["exact_quote"] in citation_snapshot.read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "inbox" / "paper-visual-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "AVAILABLE"
    image_ref = manifest["documents"][0]["pages"][0]["image_ref"]
    assert (run_dir / image_ref).is_file()


# ---------------- ingest_paper Tier-S happy path + BLOCK ----------------


def test_ingest_paper_happy_path_writes_draft_note(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    pn = _good_bundle()["paper_note"]
    pn["reading_status"] = "skimmed"
    _write_ingest_bundle(run_dir, {"paper_note": pn})
    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_claims"] == 2 and report["reading_status"] == "skimmed"
    note = _load(paths, "paper-note")
    assert note["status"] == "draft" and note["artifact_type"] == "paper_note"
    _validate_written(paths)
    rpaths, _ = ingest_paper.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)


def test_ingest_paper_malformed_note_blocks(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    pn = _good_bundle()["paper_note"]
    pn["reading_status"] = "not-a-real-status"
    _write_ingest_bundle(run_dir, {"paper_note": pn})
    with pytest.raises(GateBlock) as ei:
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert "schema BLOCK" in str(ei.value)


def test_ingest_paper_missing_key_blocks(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    _write_ingest_bundle(run_dir, {"not_a_note": {}})
    with pytest.raises(GateBlock) as ei:
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert "paper_note" in str(ei.value) and "missing required key" in str(ei.value)
