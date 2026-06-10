"""Operate recipe for the `new_direction` mode (DISCOVER -> IDEATE -> REPORT).

Split of labour (the honest demo structure, productized):
  - LLM workers (sub-agents) do the READING / IDEATION over the real vault — the only part a deterministic
    tool cannot do. DISCOVER worker -> {evidence_table, claim_list, claim_evidence_map, signals}; IDEATE
    worker -> {hypotheses, ideas} grounded in the DISCOVER gaps.
  - Deterministic cores do the GATING / SCORING (never an LLM): evidence-verifier + citation-integrity-auditor
    (the two DISCOVER hard gates), gap-classifier, novelty-scorer (score-only), feasibility-reranker.

Cold-start-over-an-existing-vault note: the strict `full_new_direction` flow has separate scouts
(lit-scout / claim-extractor / claim-evidence-linker) gather the evidence the gates verify. `new_direction`
has no scout in its subset, so this recipe's DISCOVER worker gathers that evidence by reference as it
mines gaps — the consolidation called out in the first-run demo. The gates that JUDGE the evidence are
the real deterministic ones; only the gathering is consolidated into one worker.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..artifacts import GateBlock, write_artifact
from ...tools.citation_checker import build_report
from ...tools.classify_gap import build_classification
from ...tools.evidence_checker import build_verdict
from ...tools.feasibility_score import build_idea_backlog
from ...tools.novelty_aggregate import aggregate_novelty

STAGES = ["DISCOVER", "IDEATE", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"


# --------------------------------------------------------------------------- worker prompts (LLM WORK)

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of a research machine, mining a real knowledge vault \
for under-explored directions ("gaps") relevant to this request:

    REQUEST: {request}

Read the real vault at `{vault}/02-wiki/papers/` (glob the .md pages; focus on the clusters most relevant \
to the request — read ~12-20 pages fully). Each page has YAML frontmatter (key-claims, year, venue) + body \
(limitations, future-work). Mine REAL gaps grounded in what the papers actually state.

HONESTY (hard): reference papers ONLY by their real `[[slug]]` (page filename without .md); never invent a \
slug. Ground every claim/gap in a real page; in `reported_result` paraphrase the paper's ACTUAL finding. \
Grade `claim_support` honestly (strong = directly+centrally supports; moderate = partial). Set \
`supports_claim:true` only where the locus genuinely supports the claim.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "read_summary": "<2-3 sentences>",
  "evidence_table": {{"query": "<the gap-scan query>",
     "sources": [{{"id":"s1","kind":"paper","ref":"[[<slug>]]","claim_support":"strong"}}, ...],
     "saturation_reached": true}},
  "claim_list": {{"source_scope": "<scope>",
     "claims": [{{"claim_id":"c1","text":"<claim>","source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings": [{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true}}]}}]}},
  "signals": [{{"gap_id":"GAP-1","statement":"<stated future-work/limitation>","source_ref":"[[<slug>]]",
     "evidence_ref":["[[<slug>]]"],"derived_from":["future_work"]}}]
}}
Quantities: evidence_table.sources 4-6 (>=1 "strong"); claims 2-3 (each anchored by a mapping, every locus \
supports_claim:true); signals 4-6 with VARIED gap types (include the field(s) that set the type) and an \
honest `derived_from` list (1-3 tags) — more distinct tags = higher novelty:
  stated_open_problem -> statement+source_ref ; methodological_gap -> locus+opportunity ;
  coverage_gap -> white_space_present:true ; transfer_gap -> source_domain+target_hook ;
  assumption_gap -> challenged_assumption ; evidence_gap -> under_evidenced:true ;
  empirical_gap -> untested_condition .
derived_from tags: future_work, white_space_present, weakness_opportunity, transfer_potential, \
contrarian_angle, under_evidenced, empirically_untested.

Rigor bar (max-quality): for EACH gap, satisfy yourself it is genuinely OPEN — not already solved by \
a paper you read; if a paper partially closes it, narrow the gap to the part that remains. Prefer gaps \
whose evidence_ref cites >=2 independent papers. Mark claim_support "strong" ONLY for a paper that \
centrally and directly supports the claim (a paper that merely mentions it is "moderate"). Do not pad \
counts with weak or speculative gaps — fewer, sharper, defensible gaps beat a long shallow list.
After writing, verify it is valid JSON. Return one line: pages read + counts + the highest-novelty gap."""

IDEATE_WORKER_PROMPT = """You are the IDEATE worker of a research machine. The DISCOVER stage already \
classified real gaps from the vault. Read these real artifacts:
  - `{run_dir}/evidence/DISCOVER/gap-classification.artifact.json`  (the classified gaps)
  - `{run_dir}/evidence/DISCOVER/novelty-score.artifact.json`       (novelty per gap, score-only)
Propose falsifiable hypotheses and concrete project ideas that ADDRESS those gaps, for this request:

    REQUEST: {request}

HONESTY: every hypothesis/idea must reference at least one real GAP-id (from gap-classification) and, where \
relevant, a real `[[slug]]`. Make ideas genuinely differ in feasibility so a ranking is meaningful.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "hypotheses": [{{"hypothesis_id":"IH1","statement":"<falsifiable hypothesis>",
     "falsifiable_prediction":"<concrete measurable prediction>",
     "evidence_needed":["<what would test it>"],"evidence_ref":["GAP-1","[[<slug>]]"]}}],
  "ideas": [{{"idea_id":"IDEA-1","summary":"<concrete project realizing a hypothesis>",
     "evidence_ref":["IH1","GAP-1"],"from_hypothesis_ref":"IH1",
     "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable","time":"short|medium|long"}}}}]
}}
Quantities: 3-5 hypotheses, 3-5 ideas (each `from_hypothesis_ref` -> a real IH id; feasibility spanning \
low/short to high/long).

Rigor bar (max-quality): every `falsifiable_prediction` MUST name a concrete metric + a numeric \
threshold + the dataset/condition it is measured on (reject vague predictions like "improves accuracy"); \
state what result would FALSIFY the hypothesis. Each idea must be a real experiment someone could run \
next quarter, not a research programme; set its feasibility triple honestly (the single biggest cost — \
compute / data access / time — should dominate the rating).
After writing, verify valid JSON. Return one line: counts + the most feasible idea."""


# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def _worker_model(stage: str, model_policy: str) -> str:
    """max_quality (the director's default for governed research runs, 2026-06-09) -> all-opus.
    default -> task-appropriate: DISCOVER reading/extraction = sonnet, IDEATE ideation/judgment = opus."""
    if model_policy == "max_quality":
        return "opus"
    return "sonnet" if stage == "DISCOVER" else "opus"


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The LLM worker to dispatch for a stage (or None if the stage is purely deterministic).

    `run_dir` is the run's path FROM the cwd the skill runs in (e.g. research_agent_teams/runs/<id>),
    so the worker's `output` and the prompt's read-paths resolve correctly. The skill spawns a sub-agent
    with `prompt` + `model`; the worker writes its bundle to `output`; then `run_dets(stage)` consumes it.
    `model_policy` selects the worker tier (max_quality -> opus; default -> task-appropriate).
    """
    out = f"{run_dir}/inbox/{stage}.bundle.json"
    if stage == "DISCOVER":
        return {"label": "discover-worker", "model": _worker_model(stage, model_policy), "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault, out=out)}
    if stage == "IDEATE":
        return {"label": "ideate-worker", "model": _worker_model(stage, model_policy), "output": out,
                "prompt": IDEATE_WORKER_PROMPT.format(request=request, run_dir=run_dir, out=out)}
    return None  # REPORT is deterministic


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- deterministic producers (WORK)

def _discover_dets(run_dir, ts, b) -> tuple:
    paths = []
    ev = build_verdict(b["evidence_table"])                                  # HARD GATE 1
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
    fw = {"items": [{"item_id": f"FW-{i + 1}", "statement": s["statement"],
                     "source_ref": s.get("source_ref") or s["evidence_ref"][0]}
                    for i, s in enumerate([x for x in b["signals"] if x.get("statement")])]}
    paths.append(write_artifact(run_dir, "DISCOVER", "future-work-items.artifact.json",
                                "future_work_items", "future-work-miner", fw, ts))
    gc = build_classification(b["signals"])
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))
    ns = aggregate_novelty(gc["gaps"])                                       # score-only, never a cut
    paths.append(write_artifact(run_dir, "DISCOVER", "novelty-score.artifact.json",
                                "novelty_score", "novelty-scorer", ns, ts))
    return paths, {"evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
                   "gaps_classified": len(gc["gaps"])}


def _ideate_dets(run_dir, ts, b) -> tuple:
    paths = []
    paths.append(write_artifact(run_dir, "IDEATE", "hypothesis-set.artifact.json",
                                "hypothesis_set", "hypothesis-generator", {"hypotheses": b["hypotheses"]}, ts))
    backlog = build_idea_backlog(b["ideas"])                                 # ranked MENU (no self-bet field)
    paths.append(write_artifact(run_dir, "IDEATE", "idea-backlog.artifact.json",
                                "idea_backlog", "feasibility-reranker", backlog, ts))
    return paths, {"ideas_ranked": len(backlog["ranked_ideas"])}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "new-direction menu: evidence-grounded ideas ranked by feasibility; awaiting /idea-bet",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    """Run the deterministic producers/gates for a stage. Returns (artifact_paths, report).
    Raises GateBlock if a hard gate refuses (the run halts; the stage is NOT committed)."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "IDEATE":
        return _ideate_dets(run_dir, ts, _load_bundle(run_dir, "IDEATE"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"new_direction has no stage {stage!r}")


def menu(run_dir) -> list:
    """The ranked idea_backlog (the /idea-bet menu) as a list of {rank, idea_id, score, summary}."""
    p = Path(run_dir) / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
    if not p.exists():
        return []
    bl = json.loads(p.read_text(encoding="utf-8"))["payload"]
    return [{"rank": i["rank"], "idea_id": i["idea_id"],
             "score": i["feasibility"]["score"], "summary": i["summary"]} for i in bl["ranked_ideas"]]
