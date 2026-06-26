"""Operate recipe for the `read_paper_deep` mode (DISCOVER -> REPORT) — paper-reading upgrade P4.

The Tier-D single-paper deep-read, operated: one DISCOVER worker reads ONE paper to the full
0+3+1 card and emits a bundle with EIGHT artifacts — the Tier-S spine (`paper_note`), the
structured claim ledger (`claim_list` + `claim_evidence_map`, loci optionally carrying
directness/claim_risk), the Pass-2 depth (`method_teardown` + `figure_reading`), the Pass-3 outward
appraisal (`paper_appraisal`, ADVISORY), and the Stage-4 situating layer (`paper_relations` +
`trend_card`).

Consolidation honesty (same structure evidence_deep / new_direction document): the mode's registry
subset lists the routed worker labels (record_only — the live hard gates fire as deterministic cores in-recipe, not as subset-listed gates); operated v1 consolidates the READING
into ONE DISCOVER worker whose bundle carries the inputs for the deterministic cores. The 5 per-paper
producers (method-teardown-extractor / figure-reader / paper-appraiser / paper-relations-mapper /
trend-card-builder) are operate sub-workers — rostered, dispatched by this recipe (created_by names the
producing agent), intentionally not FSM-routed (same pattern as novelty-collision-checker).

Gate posture (record_only; design D5/D7): the mode is record_only because a single-paper read produces
DRAFT knowledge, not a sign-off commitment — the human gate for knowledge is /promote-to-vault, so a
director PAUSE at the DISCOVER boundary would be redundant. The genuinely-applicable HARD gates STILL
fire as deterministic cores regardless of gate_level: the north-star drift gate, the citation-integrity
gate (every claim anchored + resolvable against the paper), and the live citation-existence gate (a
fabricated source ref BLOCKs). The evidence-verifier SATURATION gate does NOT apply to a single paper
(only one source — nothing to saturate), so it is honestly OMITTED (never listed-then-skipped).
`paper_appraisal` is ADVISORY — it is written but NEVER a gate and never blocks (additionalProperties:false
makes a self-decision field structurally impossible).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools import fulltext_qa
from ...tools.citation_checker import build_report
from ...tools.evidence_scout import build_evidence_table
from ...tools.validate_artifact import validate_payload

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

# bundle key -> (artifact_type, producing agent name, output filename, status)
ARTIFACT_PLAN = (
    ("paper_note", "paper_note", "literature-ingest", "paper-note.artifact.json", "draft"),
    ("claim_list", "claim_list", "claim-extractor", "claim-list.artifact.json", "approved"),
    ("claim_evidence_map", "claim_evidence_map", "claim-evidence-linker",
     "claim-evidence-map.artifact.json", "approved"),
    ("method_teardown", "method_teardown", "method-teardown-extractor",
     "method-teardown.artifact.json", "approved"),
    ("figure_reading", "figure_reading", "figure-reader", "figure-reading.artifact.json", "approved"),
    ("paper_appraisal", "paper_appraisal", "paper-appraiser", "paper-appraisal.artifact.json", "approved"),
    ("paper_relations", "paper_relations", "paper-relations-mapper",
     "paper-relations.artifact.json", "approved"),
    ("trend_card", "trend_card", "trend-card-builder", "trend-card.artifact.json", "approved"),
)
BUNDLE_KEYS = tuple(k for (k, *_rest) in ARTIFACT_PLAN)

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of the read_paper_deep mode: read ONE paper \
to the FULL 0+3+1 research card and emit every layer as a typed artifact, for this request:

    REQUEST: {request}

{north_star}
{reading_hook}
Source (by reference, never inlined): the paper itself (its source_ref — a file path, [[slug]], DOI, \
or arXiv id). If `{run_dir}/inbox/fulltext-qa.json` is present, use it (page-anchored full-text \
contexts + retraction flags — anchor loci to its pages; a locus from a retracted source gets \
supports_claim:false). If it is absent, read from the paper's own text/figures.

HONESTY (hard): never invent a source_ref/DOI/slug; every claim is ANCHORED to a locus you actually \
read with an explicit supports_claim (true = the locus supports the claim, false = it reports the \
opposite); the appraisal is a reading aid — score what the paper actually shows, never decide accept/\
reject (there is no verdict field). Leave a field null/empty rather than fabricate it.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit \
the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json) — EIGHT keys, each matching its schema:
{{
  "paper_note": {{"title":"<title>","source_ref":"<file/[[slug]]/DOI/arXiv>","summary":"<3-5 lines>",
     "claims":["<atomic claim>", ...], "paper_type":"method|theory|empirical|dataset-benchmark|tool|review|position",
     "read_purpose":"idea|method|baseline|related-work|reproduce|review",
     "relation_to_thesis":"A-core|B-related|C-background","reading_objective":"<one line>",
     "reading_status":"deep-read",
     "paper_contract":{{"category":"<...>","context":"<...>","correctness_prior":"<...>",
        "contributions":["<...>"],"clarity":"<...>",
        "contract_sentence":"problem -> method -> vs prior -> evidence -> applicability"}}}},
  "claim_list": {{"source_scope":"<paper>","claims":[{{"claim_id":"c1","text":"<claim>",
     "source_ref":"<same source_ref>"}}]}},
  "claim_evidence_map": {{"mappings":[{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"<same source_ref>","location":"<Table/Fig/Section>",
       "kind":"table","reported_result":"<actual finding>","supports_claim":true,
       "directness":"direct"}}], "claim_risk":{{"level":"low","note":"<why>"}}}}]}},
  "method_teardown": {{"source_ref":"<same source_ref>","problem_definition":"<in/out/target>",
     "core_assumptions":["<...>"],"representation":"<what it changes vs prior>",
     "loss_terms":[{{"term":"<name>","role":"<...>","ablate_effect":"<deleting it does ...>"}}],
     "training_flow":"<...>","inference_flow":"<...>","train_infer_consistency":"<...|null>",
     "data":"<source/scale/splits/leakage>","cost":"<...|null>","baseline_difference":"<one delta|null>"}},
  "figure_reading": {{"source_ref":"<same source_ref>","figures":[{{"figure_ref":"Figure 3",
     "axes":"<what x/y measure>","controls":"<...|null>","error_bars":"<...|null>",
     "take_home":"<the one thing it argues>","distrust":"<what to be skeptical of|null>"}}]}},
  "paper_appraisal": {{"source_ref":"<same source_ref>","paper_type":"<as above>",
     "dimensions":[{{"dim":"soundness","score":3,"evidence_ref":"<Section/Fig|null>","note":"<...>"}}, ...],
     "assumptions":["<...>"],"limitations_acknowledged":["<...>"],"limitations_unacknowledged":["<...>"],
     "baseline_fairness":"<...>","ablation_sufficiency":"<...>","statistical_robustness":"<...>",
     "selective_reporting":"<...>","reproducibility_gaps":["<...>"],"generalization":"<...>",
     "reviewer_questions":["<...>"],
     "checklist":{{"standard":"neurips|tripod_ai|strobe|consort|prisma|cochrane_rob2|casp|none",
        "items":[{{"item":"<requirement>","status":"met|partial|unmet|na","note":"<...>"}}]}},
     "overall":"<one-paragraph reviewer-mode standing — ADVISORY, never a verdict>"}},
  "paper_relations": {{"source_ref":"<same source_ref>","edges":[{{"target_ref":"<other paper>",
     "relation":"inherits|refutes|unifies|replaces|opens|extends|uses","note":"<what exactly>"}}]}},
  "trend_card": {{"scope":"<the sub-area this paper sits in>",
     "shifts":[{{"dimension":"method","from":"<was>","to":"<moving to>"}}],
     "failure_modes":["<...>"],"mechanism_vs_result":"<does the field explain WHY or only THAT>",
     "reproducibility_trend":"<...|null>","opportunities":["<your white space>"],
     "source_refs":["<same source_ref>", ...]}}
}}
Dimensions: score the 7 venue dims you can judge (soundness/significance/originality/eval_rigor/\
reproducibility/clarity/domain_validity), 1-4 each. Claims 3-8 anchored. EVERY locus's source_ref must \
be the paper's own source_ref. After writing, verify valid JSON. Return one line: claims + figures + \
relations + loss_terms counts."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def _reading_hook(run_dir) -> str:
    """Inject the domain profile's optional `reading` block (paper-type default + reporting standards
    + appraisal checklist) so reading rigor is domain-tunable (design D6). Silent when absent."""
    prof = _shared.domain_profile(run_dir) or {}
    reading = prof.get("reading") or {}
    if not reading:
        return ""
    lines = ["DOMAIN READING PROFILE (use it for the appraisal lens + reporting standard):"]
    if reading.get("paper_type_default"):
        lines.append(f"  default paper_type when unclear: {reading['paper_type_default']}")
    stds = reading.get("reporting_standards") or []
    if stds:
        lines.append(f"  reporting standards to check: {', '.join(str(s) for s in stds)}")
    if reading.get("appraisal_checklist"):
        lines.append(f"  appraisal checklist standard: {reading['appraisal_checklist']}")
    if reading.get("notes"):
        lines.append(f"  notes: {reading['notes']}")
    return "\n".join(lines) + "\n"


def fulltext_pre(run_dir, question: str, doc_paths, ts: str) -> Optional[str]:
    """OPTIONAL page-anchored full-text QA + retraction pre-step (design D7; PaperQA2 pattern).

    Writes `inbox/fulltext-qa.json` ONLY when doc_paths are supplied, so the DISCOVER worker can
    anchor its loci to real page contexts. When the optional `paper-qa` dependency is absent (or no
    docs / the engine errors), `ask()` returns an honest available:false report and we STILL write it —
    this pre-step must NEVER crash the run. Retraction flags (deterministic Crossref) ride along.
    Returns the report path, or None when no docs were supplied (the worker then reads the paper itself)."""
    if not doc_paths:
        return None
    docs = list(doc_paths)
    report = fulltext_qa.ask(question, docs, retraction_flags=fulltext_qa.retraction_check(docs))
    p = Path(run_dir) / "inbox" / "fulltext-qa.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return str(p)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage == "DISCOVER":
        out = f"{run_dir}/inbox/DISCOVER.bundle.json"
        return {"label": "read-paper-deep-worker", "model": _worker_model(model_policy),
                "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, run_dir=run_dir, out=out,
                                                        north_star=_shared.north_star_block(run_dir),
                                                        reading_hook=_reading_hook(run_dir))}
    return None


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


def _discover_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, BUNDLE_KEYS, stage="DISCOVER", mode="read_paper_deep")
    paths = []
    pn = b["paper_note"] or {}
    # (2) MINIMAL single-source evidence_table from the paper_note — the citation/existence gates' input
    # (the SATURATION gate, evidence-verifier/build_verdict, is intentionally SKIPPED: one source has
    # nothing to saturate — design D5/D7).
    et = build_evidence_table(
        str(pn.get("title") or ""),
        [{"id": "s1", "kind": "paper", "ref": str(pn.get("source_ref") or ""), "claim_support": "strong"}],
        True)
    # (3) NORTH-STAR drift gate (H2): title + summary + each claim + contract sentence + method
    # representation + appraisal overall.
    contract = pn.get("paper_contract") or {}
    texts = [str(pn.get("title") or ""), str(pn.get("summary") or "")]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    texts.append(str(contract.get("contract_sentence") or ""))
    texts.append(str((b["method_teardown"] or {}).get("representation") or ""))
    texts.append(str((b["paper_appraisal"] or {}).get("overall") or ""))
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)
    paths.append(dpath)
    # (5) Citation-integrity HARD gate — every claim anchored, supported, and resolvable to the paper.
    cv = build_report(b["claim_list"], b["claim_evidence_map"],
                      resolvable_refs=_shared.resolvable_refs(et))
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")
    # (6) Live citation-existence HARD gate — a fabricated source ref BLOCKs (offline -> warnings).
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts,
                                           _shared.external_refs(et, b["claim_evidence_map"]))
    paths.append(epath)
    # (7) Contract-validate ALL eight artifacts BEFORE writing any — a single readable GateBlock
    # naming every schema failure (instead of an opaque mid-write ValueError on the first bad one).
    errors = []
    for key, atype, _agent, _fname, _status in ARTIFACT_PLAN:
        for e in validate_payload(atype, b[key] if isinstance(b.get(key), dict) else {}):
            errors.append(f"{key}: {e}")
    if errors:
        raise GateBlock(f"read_paper_deep artifact schema BLOCK: {errors}")
    # (8) Write each artifact (created_by = the producing agent). paper_appraisal is ADVISORY — written,
    # never a gate, never blocks.
    for key, atype, agent, fname, status in ARTIFACT_PLAN:
        paths.append(write_artifact(run_dir, "DISCOVER", fname, atype, agent, b[key], ts, status))
    cem = b["claim_evidence_map"].get("mappings") or []
    return paths, {"citation_gate": cv["verdict"], "existence_gate": ex["verdict"],
                   "existence_warnings": len(ex["warnings"]),
                   "n_claims": len(b["claim_list"].get("claims") or []),
                   "n_mappings": len(cem),
                   "n_loss_terms": len((b["method_teardown"] or {}).get("loss_terms") or []),
                   "n_figures": len((b["figure_reading"] or {}).get("figures") or []),
                   "n_appraisal_dims": len((b["paper_appraisal"] or {}).get("dimensions") or []),
                   "n_relations": len((b["paper_relations"] or {}).get("edges") or []),
                   "n_trend_shifts": len((b["trend_card"] or {}).get("shifts") or [])}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "read_paper_deep: one paper read to the full 0+3+1 card — spine + claim ledger + "
                       "method teardown + figure reading + ADVISORY appraisal + relations + trend card; "
                       "citation + existence gates passed. Draft knowledge — promote via /promote-to-vault.",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"read_paper_deep has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop (OpenScholar shape): ok / retry-with-feedback / escalate at the cap."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
