"""Operate recipe for the `evidence_deep` mode (DISCOVER -> REPORT) — absorption wave 1.

The evidence-DEPTH sub-team, operated: claim extraction, claim-evidence linking, and
contradiction mining over the verified evidence picture, with both DISCOVER hard gates live and
the OpenScholar bounded revise loop (run_dets_with_repair) around them.

Consolidation honesty (same structure new_direction documents): the mode's registry subset lists
10 agents; operated v1 consolidates the GATHERING into one DISCOVER worker whose bundle carries
the inputs for the deterministic cores. v1 emits: the two hard-gate verdicts, the evidence_table
exit artifact, the contradiction_report, and — when the miner finds a vault-claim-level
contradiction — invalidation_record proposals (Graphiti invalidate-don't-delete absorption; they
reach the vault ONLY via /promote-to-vault). source_quality / staleness / dataset_card artifacts
remain prompt-driven (not yet deterministic in the operate path) and are listed as open in the
build record — never silently claimed.
"""
from __future__ import annotations

import json
import re
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
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of the evidence_deep mode: build the \
DEEP evidence picture — claims, anchored loci, and CONTRADICTIONS — for this request:

    REQUEST: {request}

{north_star}

Sources (by reference, never inlined): the vault at `{vault}/02-wiki/` (real `[[slug]]` only); \
plus `{run_dir}/inbox/search-results.json` if present (sanctioned live-retrieval bundle); plus \
`{run_dir}/inbox/fulltext-qa.json` if present (page-anchored contexts + retraction flags — cite \
pages in loci; a locus from a retracted source gets supports_claim:false).

HONESTY (hard): never invent slugs/DOIs; explicit `supports_claim` per locus from the ACTUAL \
reported result; contradictions must be traceable to claim texts you actually compared \
(normalize pairs so claim_ref_a < claim_ref_b; no duplicates; never resolve who is right).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and \
re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json):
{{
  "evidence_table": {{"query":"<scope>","sources":[{{"id":"s1","kind":"paper",
     "ref":"[[<slug>]]","claim_support":"strong"}}, ...],"saturation_reached":true}},
  "claim_list": {{"source_scope":"<scope>","claims":[{{"claim_id":"c1","text":"<claim>",
     "source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings":[{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section/table/p.N>",
       "kind":"text","reported_result":"<actual finding>","supports_claim":true}}]}}]}},
  "contradictions": {{"n_claims_checked": <int>, "summary": "<1-2 sentences>",
     "conflicts":[{{"conflict_id":"conf1","claim_ref_a":"c1","claim_ref_b":"c2",
       "kind":"numerical-disagreement","description":"<why they conflict>",
       "resolution_status":"unresolved"}}]}},
  "invalidation_proposals": [{{"claim_slug":"<existing-vault-claim-slug>",
     "invalidated_by_slug":"<existing-vault-page-slug>","edge_type":"refutes",
     "invalid_at":"YYYY-MM-DD","basis":"<what the newer source reports vs the claim>",
     "evidence_ref":["conf1","[[<slug>]]"]}}]
}}
Quantities: sources 5-10 (>=1 strong); claims 3-6 anchored; check EVERY claim pair about the \
same method/metric/dataset; invalidation_proposals ONLY for contradictions that invalidate a \
REAL existing vault claim page (else leave the list empty — empty is the normal case). \
After writing, verify valid JSON. Return one line: claims + conflicts + proposals counts."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit M1 — now exposed on every evidence mode)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage == "DISCOVER":
        out = f"{run_dir}/inbox/DISCOVER.bundle.json"
        return {"label": "evidence-deep-worker", "model": _worker_model(model_policy),
                "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault,
                                                        run_dir=run_dir, out=out,
                                                        north_star=_shared.north_star_block(run_dir))}
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
    _shared.require_bundle_keys(b, ("evidence_table", "claim_list", "claim_evidence_map"),
                                stage="DISCOVER", mode="evidence_deep")
    paths = []
    et = build_evidence_table(b["evidence_table"]["query"], b["evidence_table"]["sources"],
                              b["evidence_table"].get("saturation_reached", False))
    texts = [str(et.get("query") or "")]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    texts += [str((b.get("contradictions") or {}).get("summary") or "")]
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)        # NORTH-STAR gate (H2)
    paths.append(dpath)
    ev = build_verdict(et)                                                   # HARD GATE 1
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK":
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")
    cv = build_report(b["claim_list"], b["claim_evidence_map"],              # HARD GATE 2 (W2 fix)
                      resolvable_refs=_shared.resolvable_refs(et))
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts,          # HARD GATE 3 (H4)
                                           _shared.external_refs(et, b["claim_evidence_map"]))
    paths.append(epath)
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts))
    contradictions = b.get("contradictions") or {"n_claims_checked": 0, "conflicts": [], "summary": ""}
    paths.append(write_artifact(run_dir, "DISCOVER", "contradiction-report.artifact.json",
                                "contradiction_report", "contradiction-miner", contradictions, ts))
    n_props = 0
    for i, prop in enumerate(b.get("invalidation_proposals") or [], start=1):
        # fail-closed slug shape check BEFORE schema validation: a malformed proposal must not
        # crash the stage with an opaque schema error — name the violation.
        for f in ("claim_slug", "invalidated_by_slug"):
            if not _SLUG.match(str(prop.get(f, ""))):
                raise GateBlock(f"invalidation proposal {i}: {f} is not a real slug shape "
                                f"({prop.get(f)!r}) — never invent a slug")
        paths.append(write_artifact(run_dir, "DISCOVER", f"invalidation-{i}.artifact.json",
                                    "invalidation_record", "contradiction-miner", prop, ts,
                                    status="draft"))  # a PROPOSAL: only /promote-to-vault lands it
        n_props += 1
    return paths, {"evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
                   "existence_gate": ex["verdict"], "existence_warnings": len(ex["warnings"]),
                   "n_conflicts": len(contradictions.get("conflicts") or []),
                   "n_invalidation_proposals": n_props}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "evidence_deep: anchored claims + contradiction mining complete; "
                       "invalidation proposals (if any) await /promote-to-vault",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"evidence_deep has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop (OpenScholar shape): ok / retry-with-feedback / escalate at the cap."""
    return attempt_with_repair(run_dir, stage, _budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
