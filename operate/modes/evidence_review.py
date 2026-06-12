"""Operate recipe for the `evidence_review` mode (DISCOVER -> REPORT) — absorption wave 1.

Wires the second mode into the one-button operate layer (REGISTRY), with the OpenScholar
absorption: a bounded draft -> gate-critique -> revise loop. Split of labour:

  - The LLM worker (sub-agent) does the READING: it assembles the graded evidence_table +
    claim_list + claim_evidence_map for the request, from the vault BY REFERENCE plus the
    optional live search bundle the pre-step drops at inbox/search-results.json
    (tools/paper_search.py — the sanctioned channel).
  - Deterministic cores do the GATING: evidence-verifier (evidence_checker.build_verdict) and
    citation-integrity-auditor (citation_checker.build_report) — the two DISCOVER hard gates.
  - The self-feedback loop is `run_dets_with_repair`: a gate BLOCK is fed back to the worker
    verbatim (operate/bounded_repair), capped by the mode budget's max_debug_retries_per_run;
    when the cap is reached the ORIGINAL GateBlock escalates to the director. The loop is the
    OpenScholar draft->critique->re-retrieve->revise shape with the machine's own deterministic
    critics as the loop-exit gate — never an LLM judging itself.

Like new_direction, the mode's listed agents are consolidated into ONE worker per stage for
operation (the gathering is consolidated; the gates that JUDGE are the real deterministic ones).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.citation_checker import build_report
from ...tools.evidence_checker import build_verdict
from ...tools.evidence_scout import build_evidence_table

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of the evidence_review mode: assemble the \
VERIFIED evidence picture for this request:

    REQUEST: {request}

{north_star}

Sources you read (by reference, never inlined):
  1. The vault at `{vault}/02-wiki/` — glob the relevant clusters, read the most relevant pages \
fully; reference pages ONLY by their real `[[slug]]`.
  2. IF `{run_dir}/inbox/search-results.json` exists: the live-retrieval bundle from the \
sanctioned connector. Its `evidence_rows` are schema-ready source rows (claim_support arrives \
"none" — grading is YOUR job; upgrade only what the row's title/venue genuinely supports).

HONESTY (hard): never invent a slug, DOI, or paper; grade `claim_support` honestly (strong = \
directly + centrally supports); set `supports_claim` per locus from the ACTUAL reported result; \
a thin evidence picture is reported as thin (saturation_reached: false), never padded.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}` (ends in .bundle.json, NOT .artifact.json):
{{
  "evidence_table": {{"query": "<the request as searched>",
     "sources": [{{"id":"s1","kind":"paper","ref":"[[<slug>]] or doi:<doi> or arXiv:<id>",
                   "title":"<title>","year":2024,"claim_support":"strong"}}, ...],
     "saturation_reached": true}},
  "claim_list": {{"source_scope": "<scope>",
     "claims": [{{"claim_id":"c1","text":"<claim>","source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings": [{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section/table>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true}}]}}]}}
}}
Quantities: sources 4-8 (>=1 "strong"); claims 2-4, each anchored by >=1 locus with an explicit \
supports_claim. After writing, verify valid JSON. Return one line: sources + claims + saturation."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit M1 — now exposed on every evidence mode)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The LLM worker to dispatch for a stage (None = stage is purely deterministic).
    The prompt carries the run's NORTH STAR block (audit A2)."""
    if stage == "DISCOVER":
        out = f"{run_dir}/inbox/DISCOVER.bundle.json"
        return {"label": "evidence-review-worker", "model": _worker_model(model_policy),
                "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault,
                                                        run_dir=run_dir, out=out,
                                                        north_star=_shared.north_star_block(run_dir))}
    return None  # REPORT is deterministic


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
    _shared.require_bundle_keys(b, ("evidence_table", "claim_list", "claim_evidence_map"),
                                stage="DISCOVER", mode="evidence_review")
    paths = []
    et = build_evidence_table(b["evidence_table"]["query"], b["evidence_table"]["sources"],
                              b["evidence_table"].get("saturation_reached", False))
    texts = [str(et.get("query") or "")]
    texts += [str(s.get("title") or "") for s in (et.get("sources") or [])]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)        # NORTH-STAR gate (H2)
    paths.append(dpath)
    ev = build_verdict(et)                                                   # HARD GATE 1
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK":
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")
    cv = build_report(b["claim_list"], b["claim_evidence_map"],              # HARD GATE 2 (W2 fix:
                      resolvable_refs=_shared.resolvable_refs(et))           #  loci must cite table sources)
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts,          # HARD GATE 3 (H4: live
                                           _shared.external_refs(et, b["claim_evidence_map"]))  # existence)
    paths.append(epath)
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts))      # the DISCOVER exit artifact
    return paths, {"evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
                   "existence_gate": ex["verdict"], "existence_warnings": len(ex["warnings"]),
                   "n_sources": et["n_sources"]}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "evidence_review: verified evidence table + anchored claims; both DISCOVER "
                       "hard gates passed", "references": [], "produced_artifacts": [],
            "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"evidence_review has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """The OpenScholar loop entry: ("ok", (paths, report)) or ("retry", feedback-for-the-worker).
    Re-raises the original GateBlock when the budget's repair cap is reached (director escalation)."""
    return attempt_with_repair(run_dir, stage, _budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
