"""Operate recipe for the NEW `deep_research` mode (DISCOVER -> REPORT) — absorption wave 1.

The open_deep_research recipe, ported as a PATTERN (no LangGraph): supervisor decomposes the
topic into perspective-split research angles (the STORM-style principled split of the
consolidated hunters), researchers gather per angle with PER-RESEARCHER COMPRESSION before the
merge, and the run emits a `research_brief` exit artifact alongside the verified evidence chain.

What this mode wires LIVE (previously dead):
  - budget counter `max_iterations_without_new_evidence` — the worker reports its
    iterations-without-new-evidence honestly; the deterministic dets enforce the cap;
  - budget counter `max_fulltext_reads` — ditto for full-text reads;
  - the live-retrieval pre-step (`pre_search`) — tools/paper_search.py fans the topic across
    the free-first scholarly APIs and drops inbox/search-results.json for the worker; a dead
    network degrades to a recorded source_errors bundle, never a fabricated one;
  - the OpenScholar bounded revise loop around BOTH DISCOVER hard gates
    (`run_dets_with_repair`, capped by max_debug_retries_per_run).

Consolidation honesty: operated v1 dispatches ONE supervisor worker whose prompt structures the
parallel researchers as sections with their own compression budgets (the same consolidation
new_direction documents); true multi-subagent fan-out is the orchestrator skill's dispatch
choice, not this recipe's requirement.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.budget_tracker import assert_within
from ...tools.citation_checker import build_report
from ...tools.evidence_checker import build_verdict
from ...tools.evidence_scout import build_evidence_table
from ...tools.paper_search import search, write_search_bundle

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

DISCOVER_WORKER_PROMPT = """You are the SUPERVISOR of a deep_research run (open_deep_research \
recipe: scope -> perspective-split researchers -> per-researcher compression -> merge) for:

    TOPIC: {request}

PROTOCOL:
  1. SCOPE: decompose the topic into 3-4 PERSPECTIVES (research angles that genuinely differ — \
the principled split: e.g. methods-state, benchmark/evidence-state, open-problems, adjacent-field \
transfer). For each: perspective_id (P1..), angle, 2-3 concrete questions.
  2. RESEARCH each perspective AS ITS OWN RESEARCHER: read the vault `{vault}/02-wiki/` clusters \
relevant to that angle (real `[[slug]]` only) and the live bundle \
`{run_dir}/inbox/search-results.json` if present (rows from the sanctioned connector; grade what \
you actually judge relevant). Track honestly: how many search-refine iterations produced NO new \
evidence, and how many full texts you read.
  3. COMPRESS per researcher BEFORE merging: each perspective's findings become ONE summary \
(<=2000 chars) + its source_refs (DOI / arXiv / [[slug]]). Never dump raw notes into the brief.
  4. MERGE into the bundle below. saturation_reached=true ONLY when another iteration would \
likely add nothing.

HONESTY (hard): never invent slugs/DOIs; thin coverage is reported thin; the usage counters are \
REAL counts, not aspirations — the deterministic budget gate reads them.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and \
re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json):
{{
  "research_brief": {{"topic":"{request}",
     "perspectives":[{{"perspective_id":"P1","angle":"<angle>","questions":["<q1>","<q2>"]}}],
     "findings":[{{"perspective_id":"P1","summary":"<compressed, <=2000 chars>",
        "source_refs":["[[<slug>]]","doi:<doi>"]}}],
     "iterations_used": <int>, "saturation_reached": true,
     "evidence_ref": ["inbox/search-results.json", "[[<slug>]]"]}},
  "usage": {{"iterations_without_new_evidence": <int>, "fulltext_reads": <int>}},
  "evidence_table": {{"query":"{request}","sources":[{{"id":"s1","kind":"paper",
     "ref":"[[<slug>]] or doi:<doi>","claim_support":"strong"}}],"saturation_reached":true}},
  "claim_list": {{"source_scope":"<scope>","claims":[{{"claim_id":"c1","text":"<claim>",
     "source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings":[{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true}}]}}]}}
}}
Quantities: 3-4 perspectives; one finding per perspective (source_refs >=2 where coverage \
allows); evidence_table sources 5-10 (>=1 strong); claims 2-4 anchored. \
After writing, verify valid JSON. Return one line: perspectives + sources + iterations."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Deterministic live-retrieval pre-step: drop inbox/search-results.json for the worker.
    A dead network degrades to an empty-records bundle with source_errors recorded — the run
    proceeds vault-only and the brief's coverage is honestly thinner; nothing is fabricated."""
    try:
        res = search(request, sources=sources, limit_per_source=limit_per_source, transport=transport)
    except Exception as e:  # total failure (e.g. bad query) -> recorded, never invented
        res = {"query": request, "records": [], "source_errors": {"all": str(e)}}
    return write_search_bundle(run_dir, request, res, ts)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage == "DISCOVER":
        out = f"{run_dir}/inbox/DISCOVER.bundle.json"
        return {"label": "deep-research-supervisor", "model": _worker_model(model_policy),
                "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault,
                                                        run_dir=run_dir, out=out)}
    return None


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


def _budget(run_dir) -> dict:
    tf = json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))
    return dict(tf["payload"].get("budget") or {})


def _discover_dets(run_dir, ts, b) -> tuple:
    # Budget gate FIRST (the previously-dead counters, now live): the worker's honest usage
    # counts are enforced deterministically; exceeding them halts the stage as BudgetExceeded
    # (a budget stop is NOT a quality gate — the repair loop deliberately does not catch it).
    usage = b.get("usage")
    if not isinstance(usage, dict):
        raise GateBlock("deep_research worker did not report 'usage' counts — the budget gate needs "
                        "honest iterations_without_new_evidence + fulltext_reads (omitting them must "
                        "not silently pass the gate)")
    try:
        iters = int(usage["iterations_without_new_evidence"])
        reads = int(usage["fulltext_reads"])
    except (KeyError, TypeError, ValueError):
        raise GateBlock("deep_research 'usage' must report INTEGER iterations_without_new_evidence + "
                        "fulltext_reads (the worker declares real counts; null / missing is rejected)")
    assert_within(_budget(run_dir),
                  {"iterations_without_new_evidence": iters, "fulltext_reads": reads})

    paths = []
    et = build_evidence_table(b["evidence_table"]["query"], b["evidence_table"]["sources"],
                              b["evidence_table"].get("saturation_reached", False))
    ev = build_verdict(et)                                                   # HARD GATE 1
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK":
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")
    cv = build_report(b["claim_list"], b["claim_evidence_map"])              # HARD GATE 2
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")
    paths.append(write_artifact(run_dir, "DISCOVER", "research-brief.artifact.json",
                                "research_brief", "lit-scout", b["research_brief"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts))
    brief = b["research_brief"]
    return paths, {"evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
                   "n_perspectives": len(brief.get("perspectives") or []),
                   "iterations_used": brief.get("iterations_used", 0),
                   "saturation_reached": brief.get("saturation_reached", False)}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "deep_research: perspective-split brief + verified evidence chain; "
                       "budget counters live (iterations / fulltext reads)",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"deep_research has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop around the gates (BudgetExceeded passes through uncaught — a budget
    stop must surface, never be 'repaired')."""
    return attempt_with_repair(run_dir, stage, _budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
