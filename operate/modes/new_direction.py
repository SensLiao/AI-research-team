"""Operate recipe for the `new_direction` mode (DISCOVER -> IDEATE -> REPORT).

Audit waves A-B upgrade (2026-06-13; _design/review/ai-capability-audit-2026-06-12.md):
the flagship find-a-direction flow now runs the FULL grounding + anti-drift + ideation chain.

Split of labour (independent worker ownership; hard gates and final scoring remain deterministic):
  - LLM workers do the READING / IDEATION over the real vault. DISCOVER grounds evidence and gaps;
    IDEA PROPOSER authors hypotheses + mechanism-rich ideas; TOURNAMENT RANKER independently compares
    and evolves them; COLLISION CHECKER prosecutes novelty; EXPERIMENT PLANNER writes falsification plans.
  - Deterministic cores do the GATING / SCORING (never an LLM):
      north-star drift gate (every stage; out-of-scope topic / zero anchor coverage BLOCKs)
      evidence-verifier + citation-integrity (resolvable_refs now enforced — audit W2)
      citation-existence gate over external refs (audit H4 — the live checker, plugged in)
      vault-slug referential integrity (an invented [[slug]] BLOCKs when the vault is reachable)
      gap-classifier + novelty-scorer — novelty now takes the retrieval-grounded
      `no_semantic_neighbor_found` signal from the pre-search bundle (audit H5)
      cross-run project memory: gaps matched against the project's prior gap inventory (audit C1)
      IDEATE referential integrity (a fabricated GAP-/IH- id BLOCKs — audit H3)
      idea dedup -> round-robin Elo tournament over the worker's pairwise judgments (audit B3)
      evolved-ideas validation (parent provenance enforced)
      idea-grounding advisory + negative-result caveats from the vault (audit C2) — score-only
      feasibility rerank -> the /idea-bet MENU (no self-bet field, structurally)

Pre-search (audit H5/M1): run `operate pre-search` after `begin` so DISCOVER reads live
multi-source records and novelty is literature-grounded; skipping it degrades honestly —
the report says `novelty_grounded: false` and the menu is marked vault-only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from . import _deep_ideate, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ..output_versions import resolve_effective_output
from ...tools.citation_checker import build_report
from ...tools.classify_gap import build_classification
from ...tools.elo_tournament import build_elo_tournament
from ...tools.evidence_checker import build_verdict
from ...tools.feasibility_score import build_idea_backlog
from ...tools.idea_bet_markdown import write_idea_bet_menu
from ...tools.idea_dedup import dedupe_ideas
from ...tools.idea_grounding import score_idea_grounding
from ...tools.novelty_aggregate import aggregate_novelty
from ...tools.project_memory import (
    append_gap_inventory,
    load_gap_inventory,
    prior_overlaps,
    workspace_for_run,
)
from ...tools.scientific_investment_score import (
    rank_scientific_investments,
    validate_assessments,
)

STAGES = ["DISCOVER", "IDEATE", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"


# --------------------------------------------------------------------------- worker prompts (LLM WORK)

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of a research machine, mining a real knowledge vault \
for under-explored directions ("gaps") relevant to this request:

    REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/papers/` (glob the .md pages; focus on the clusters most relevant \
to the request — read ~12-20 pages fully). Each page has YAML frontmatter (key-claims, year, venue) + body \
(limitations, future-work). Mine REAL gaps grounded in what the papers actually state.
IF `{run_dir}/inbox/search-results.json` exists: it is the sanctioned live-retrieval bundle — use its \
records to check whether a gap is already closed by recent literature outside the vault, and you may cite \
its rows as extra sources (`doi:`/`arXiv:` refs allowed for those rows only).
If that bundle is empty/off-topic or misses a named method, use agent Web Search to retrieve only paper \
originals, official publisher/project pages, or authors' official repositories; snippets are leads only, \
and every accepted source must still pass the common existence and citation gates.

HONESTY (hard): reference vault papers ONLY by their real `[[slug]]` (page filename without .md); never \
invent a slug — a deterministic gate checks every slug against the vault and BLOCKs fabrications. \
Ground every claim/gap in a real page; in `reported_result` paraphrase the paper's ACTUAL finding. \
Grade `claim_support` honestly (strong = directly+centrally supports; moderate = partial). Set \
`supports_claim:true` only where the locus genuinely supports the claim. Every locus `source_ref` must \
be one of the evidence_table sources (the resolvability gate enforces this).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle.

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
a paper you read OR by a record in the live-retrieval bundle; if a paper partially closes it, narrow the \
gap to the part that remains. Prefer gaps whose evidence_ref cites >=2 independent papers. Mark \
claim_support "strong" ONLY for a paper that centrally and directly supports the claim. Do not pad \
counts with weak or speculative gaps — fewer, sharper, defensible gaps beat a long shallow list.
After writing, verify it is valid JSON. Return one line: pages read + counts + the highest-novelty gap."""

MEMO_CONTRACT_VERSION = "idea-investment-memo/v2"
LEGACY_REPLAY_CONTRACT_VERSION = "idea-legacy-replay/v1"
LEGACY_REPLAY_RECEIPT_NAME = "IDEA-LEGACY-REPLAY.json"
LEGACY_REPLAY_LIMITATIONS = frozenset({
    "no_current_scientific_rank",
    "no_current_scientific_pass",
})
_CONTRACT_STATUS_KEY = "_rat_idea_contract_status"
_CURRENT_CONTRACT = "CURRENT"
_LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


PROPOSER_WORKER_PROMPT = """You are the IDEA PROPOSER of a research machine. The DISCOVER stage already
classified real gaps from the vault. Read these real artifacts:
  - `{run_dir}/evidence/DISCOVER/gap-classification.artifact.json`
  - `{run_dir}/evidence/DISCOVER/novelty-score.artifact.json`

Propose falsifiable hypotheses and concrete project ideas for this request:

    REQUEST: {request}

{north_star}

Do NOT rank, select, or evolve your own proposals. A separate tournament-ranker owns comparative
judgment. Every hypothesis and idea must reference a real upstream GAP-/IH- id and, where relevant, a
real `[[slug]]`. For each idea, write a scientific investment thesis rather than a title: an answerable
question, an explicit mechanism and ordered causal chain, the intended contribution relative to known
work, why the enabling conditions make it worth testing now, and an honest feasibility triple.

Also inspect `{vault}/02-wiki/negative-results/` when present. Do not silently repeat a known failure:
either change the mechanism/control regime or expose the negative result as a named risk in the summary.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit the
COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "memo_contract_version": "idea-investment-memo/v2",
  "hypotheses": [{{"hypothesis_id":"IH1","statement":"<falsifiable hypothesis>",
     "falsifiable_prediction":"<metric + numeric threshold + dataset/condition>",
     "evidence_needed":["<what would test it>"],"evidence_ref":["GAP-1","[[<slug>]]"]}}],
  "ideas": [{{"idea_id":"IDEA-1","summary":"<concrete project realizing a hypothesis>",
     "evidence_ref":["IH1","GAP-1"],"from_hypothesis_ref":"IH1",
     "research_question":"<one answerable question ending in ?>",
     "mechanism_hypothesis":"<why the intervention should change the outcome>",
     "causal_chain":["<intervention -> mediator>","<mediator -> measurable outcome>"],
     "problem_evidence":["<source/result showing the problem is real>"],
     "independent_scientific_value":"<why this matters even outside the current project>",
     "expected_contributions":["<conditional problem/method/mechanism/evaluation contribution>"],
     "intended_contribution":"<specific delta over the closest known approach>",
     "why_now":"<new data/tool/evidence/cost condition that makes this timely>",
     "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable",
        "time":"short|medium|long"}}}}]
}}
Emit 3-5 hypotheses and 3-5 ideas. Every idea must carry the human-first scientific case shown above;
`causal_chain` must contain at least two ordered links. Each prediction must name a metric, numeric
threshold, and evaluation condition. Each idea must be runnable next quarter, not a research programme.
After writing, verify valid JSON. Return only the hypothesis and idea counts; do not self-rank."""


RANKER_WORKER_PROMPT = """You are the IDEA TOURNAMENT RANKER. You did NOT author the proposals. Read:
  - `{run_dir}/inbox/IDEATE.bundle.json`

{north_star}

Compare every unordered pair exactly once. Judge scientific leverage, falsifiability, novelty exposure,
time-to-information, and resource risk. Name the decisive difference between both ideas; do not turn a
feasibility shortcut into a scientific verdict. You may evolve at most two proposals, but every evolved
idea must preserve parent provenance and carry the complete investment-thesis fields of an original.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit the
COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "memo_contract_version": "idea-investment-memo/v2",
  "tournament": [{{"round":1,"pair_a":"IDEA-1","pair_b":"IDEA-2","winner":"IDEA-1",
     "rationale":"<decisive comparison naming both ideas>"}}],
  "evolved": [{{"idea_id":"EV-1","summary":"<stronger mutation or recombination>",
     "parent_ids":["IDEA-1"],"mutation_type":"mutate|recombine|strengthen",
     "evidence_ref":["IDEA-1","GAP-1"],"research_question":"<answerable question>",
     "mechanism_hypothesis":"<mechanism claim>",
     "causal_chain":["<cause -> mediator>","<mediator -> outcome>"],
     "problem_evidence":["<source/result showing the problem is real>"],
     "independent_scientific_value":"<why the problem matters beyond this project>",
     "expected_contributions":["<conditional contribution if evidence succeeds>"],
     "intended_contribution":"<delta over prior work>","why_now":"<timing case>",
     "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable",
        "time":"short|medium|long"}}}}],
  "investment_assessments": [{{"idea_id":"IDEA-1",
     "investment_case":"<why this is or is not worth scarce research capacity>",
     "rank_rationale":"<scientific upside versus cost and failure informativeness>",
     "dimension_scores":{{"importance":1,"mechanism_coherence":1,"novelty_exposure":1,
       "falsifiability":1,"information_gain":1,"downstream_leverage":1}},
     "strongest_rejection_case":"<the strongest reason a skeptical scientist should not fund it>"}}]
}}
Tournament must cover every unordered pair of ORIGINAL ideas exactly once. Emit one assessment for every
original and evolved idea. Every dimension score is an integer 1-5 and must be justified by the prose;
do not reward mere ease. Emit `evolved: []` when no mutation is genuinely stronger. Never emit a bet,
selection, approval, or director decision. After writing, verify valid JSON."""


INVESTMENT_COLLISION_WORKER_PROMPT = """You are the NOVELTY-COLLISION CHECKER, an independent full-paper
novelty auditor. You did not propose or rank the ideas. Read:
  - `{run_dir}/inbox/IDEATE.bundle.json` for original proposals
  - `{run_dir}/inbox/RANKING.bundle.json` for evolved proposals and comparative assessments
  - `{run_dir}/inbox/search-results.json` if it exists

{north_star}

For every original and evolved idea, identify its central falsifiable contribution and the closest
real work. Search results, titles, abstracts, shared keywords, and shared components are discovery
signals only. They can narrow a broad first-claim, but cannot kill an idea.

Before emitting `collision`, obtain and read the full closest paper, including the method and the
experiments bearing on the claim. Compare the problem/target, input state, interaction, output/edit
semantics, mechanism/training, causal controls, primary evaluation target, actual results, and scope.
An exact collision requires the same central claim, a materially equivalent input/output contract,
an equivalent causal assay, and experiments when experiments are required. If full text or decisive
evidence is unavailable, the relationship is `uncertain`, the per-idea verdict is `unverified`, and
it cannot be a fatal collision or a false clearance.

For every exact collision, preserve the full-text file actually read inside the current run and
record its run-local path plus SHA-256. The retrieval route remains your choice; the receipt is
required so a destructive cut is inspectable. Without it, emit `unverified`, never a fatal cut.

Classify each closest paper as `exact_collision`, `partial_component_prior`, `enabling_base`,
`gap_source`, `orthogonal`, or `uncertain`. An idea that improves or closes a gap in prior work is not
covered merely because it inherits a prior component. State what the prior solved, what it did not
solve, the surviving delta, and the strongest reviewer case that the delta is only a rename.

Choose the retrieval, reading, and comparison route that best fits the available environment. Do not
fabricate a paper, identifier, locator, result, figure interpretation, or quote. You do not rank,
select, or drop ideas.

Write ONLY this JSON to `{out}`:
{{
  "memo_contract_version": "idea-investment-memo/v2",
  "findings": [{{
    "idea_id":"IDEA-1","method_combination":"<combined methods>",
    "application":"<problem>","domain":"<field>","queries":["<targeted query>"],
    "verdict":"collision|adjacent|clear|unverified","colliding_papers":[{{
      "ref":"arXiv:2407.01517","title":"<title>",
      "does_same_method_on_same_problem":true,"experimentally_validated":true,
      "full_text_reviewed":true,"relationship":"exact_collision|partial_component_prior|enabling_base|gap_source|orthogonal|uncertain",
      "fulltext_snapshot_ref":"inbox/fulltext-docs/closest-paper.pdf",
      "fulltext_snapshot_sha256":"<64 lowercase hex characters>",
      "same_central_claim":true,"same_input_output_contract":true,
      "same_causal_evaluation":true,"evidence_loci":["p.4 Method","p.7 Table 2"],
      "method_evidence_loci":["p.4 Method"],"result_evidence_loci":["p.7 Table 2"],
      "material_surviving_delta":false,
      "surviving_gap":"<what remains unestablished>",
      "justification":"<what it did, did not do, and why this relation follows>",
      "quote":"<short support actually inspected>"
    }}],
    "closest_prior_art":[{{"ref":"<real ref>","title":"<title>",
      "relationship":"<exact_collision|partial_component_prior|enabling_base|gap_source|orthogonal|uncertain>",
      "difference":"<specific, falsifiable delta>"}}],
    "difference_from_prior_art":"<precise surviving delta or already-done statement>",
    "visual_evidence":[{{"source_ref":"<paper/page/figure or table actually inspected>",
      "asset_ref":"<optional stable relative image path or null>",
      "content":"<axes/table structure and comparison>","key_observation":"<numbers/trend>",
      "supports":"<narrow conclusion>","does_not_support":"<boundary>"}}],
    "confidence":"high|medium|low","retrieval_status":"complete|partial|unavailable",
    "retrieval_note":"<coverage, full-text availability, and unresolved limits>"
  }}],
  "evidence_ref":["inbox/COLLISION.bundle.json"]
}}
`collision` requires at least one existence-verifiable paper with full_text_reviewed=true and a
hash-verified run-local fulltext snapshot,
relationship=exact_collision, all three same_* fields true, experimental validation, separate
method/result evidence loci, and material_surviving_delta=false. Otherwise use adjacent or
unverified and preserve the paper as a partial prior, enabling base, or gap source.
`colliding_papers` must be empty for `clear`; `closest_prior_art` may still name verified adjacent work.
Emit `visual_evidence` only after actual visual inspection; otherwise use an empty list and do not infer
image content from captions or OCR.
Emit exactly one finding per candidate and verify the JSON before returning."""


# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def _worker_model(stage: str, model_policy: str) -> str:
    """max_quality (the director's default for governed research runs, 2026-06-09) -> all-opus.
    default -> task-appropriate: DISCOVER reading/extraction = sonnet, IDEATE ideation/judgment = opus."""
    if model_policy == "max_quality":
        return "opus"
    return "sonnet" if stage == "DISCOVER" else "opus"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None) -> str:
    """Live-retrieval pre-step (audit H5): grounds DISCOVER + novelty in real literature."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries)


def discover_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                    model_policy: str = "max_quality") -> dict:
    """The base DISCOVER grounding worker (evidence_table / claim_list / claim_evidence_map / signals).
    Reused by deep_ideation too (so the two modes share ONE base-worker definition — no drift)."""
    out = f"{run_dir}/inbox/DISCOVER.bundle.json"
    return {"label": "direction-grounding-scout", "model": _worker_model("DISCOVER", model_policy), "output": out,
            "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault, out=out,
                                                    run_dir=run_dir,
                                                    north_star=_shared.north_star_block(run_dir))}


def ideate_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                  model_policy: str = "max_quality") -> dict:
    """Independent proposer: hypotheses and memo-ready ideas, with no comparative judgment."""
    out = f"{run_dir}/inbox/IDEATE.bundle.json"
    return {"label": "hypothesis-generator", "model": _worker_model("IDEATE", model_policy), "output": out,
            "prompt": PROPOSER_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out, vault=vault,
                north_star=_shared.north_star_block(run_dir))}


def ranker_worker(run_dir: str, request: str, model_policy: str = "max_quality") -> dict:
    """Independent comparative judge, dispatched only after the proposal bundle exists."""
    out = f"{run_dir}/inbox/RANKING.bundle.json"
    return {"label": "idea-tournament-ranker", "model": _worker_model("IDEATE", model_policy),
            "output": out, "depends_on": ["hypothesis-generator"],
            "prompt": RANKER_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out,
                north_star=_shared.north_star_block(run_dir))}


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The worker PANEL to dispatch for a stage (or None if deterministic). new_direction is now
    deep-by-default but SINGLE-DOMAIN (it omits the cross-domain analogy-mapper — that breadth layer is
    deep_ideation's signature) and GRACEFUL (run_dets uses required=False, so a skipped deep worker
    degrades to the proven base instead of blocking). Panels are spawned IN ORDER (each deep worker reads
    the prior inbox bundles). NORTH STAR is in every worker prompt (audit A2). REPORT is deterministic."""
    if stage == "DISCOVER":
        deep = _deep_ideate.discover_deep_workers(run_dir, request, vault, model_policy, with_analogy=False)
        workers = [discover_worker(run_dir, request, vault, model_policy), *deep]
        return {"workers": workers,
                "worker_order": [worker["label"] for worker in workers],
                "parallel_groups": [
                    ["direction-grounding-scout"],
                    ["mathematical-formalizer", "contradiction-miner"],
                    ["mathematical-formalizer"],
                ],
                "panel_note": "Wave 1 grounds sources. Wave 2 runs formalization and contradiction "
                              "mining independently. Wave 3 builds the mechanism graph. Deep "
                              "SINGLE-DOMAIN omits cross-domain analogy."}
    if stage == "IDEATE":
        workers = [ideate_worker(run_dir, request, vault, model_policy),
                   ranker_worker(run_dir, request, model_policy),
                   collision_step(run_dir, vault=vault, model_policy=model_policy),
                   _deep_ideate.experiment_worker(run_dir, request, model_policy)]
        return {"workers": workers,
                "worker_order": [worker["label"] for worker in workers],
                "parallel_groups": [[worker["label"]] for worker in workers],
                "panel_note": "spawn IN ORDER: hypothesis-generator (proposer) -> idea-tournament-ranker -> "
                              "novelty-collision-checker -> experiment-planner. Each worker owns a "
                              "distinct bundle and reads only its declared predecessors."}
    return None  # REPORT is deterministic


def collision_step(run_dir: str, vault: str = DEFAULT_VAULT,
                   model_policy: str = "max_quality") -> dict:
    """The INDEPENDENT novelty-collision-checker worker to dispatch in IDEATE, AFTER the ideate worker
    and BEFORE `run_dets("IDEATE")` (the gate consumes its `inbox/COLLISION.bundle.json`). It is a
    SEPARATE worker from the idea proposer (no athlete-judging-self): per director lock 2026-06-18,
    every final idea must be prior-art-checked before reaching /idea-bet. Model: opus (collision
    judgment gates output — a false cut kills a good idea), matching the IDEATE judgment tier."""
    out = f"{run_dir}/inbox/COLLISION.bundle.json"
    ns_block = _shared.north_star_block(run_dir)
    return {"label": "novelty-collision-checker", "model": _worker_model("IDEATE", model_policy),
            "output": out,
            "depends_on": ["hypothesis-generator", "idea-tournament-ranker"],
            "prompt": INVESTMENT_COLLISION_WORKER_PROMPT.format(
                run_dir=run_dir, out=out, north_star=ns_block)}


def _collision_hard_block(run_dir) -> bool:
    """Cut policy for the novelty-collision gate: profile `novelty_collision.hard_block`, default True
    (director lock 2026-06-18 — an evidenced prior-art collision is REMOVED from the menu before
    /idea-bet). A profile may set it False to keep every idea (flag-only) while still labelling DEAD."""
    prof = _shared.domain_profile(run_dir) or {}
    block = prof.get("novelty_collision") or {}
    val = block.get("hard_block")
    return True if val is None else bool(val)


def _load_bundle(run_dir, stage) -> dict:
    logical = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    try:
        p = resolve_effective_output(Path(run_dir), stage, logical)
    except ValueError as exc:
        raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_legacy_replay_receipt(run_dir: str, *, source_run_id: str, reason: str) -> str:
    """Explicitly bind a historical merged IDEATE bundle to replay-only semantics.

    This helper is intentionally never called by the operated current-run path. An operator restoring
    a historical scratch bundle must invoke it deliberately; the receipt binds the exact bytes and
    acknowledges that replay cannot earn the current scientific rank or a current PASS claim.
    """
    ideate_path = Path(run_dir) / "inbox" / "IDEATE.bundle.json"
    if not ideate_path.is_file():
        raise FileNotFoundError(f"legacy replay IDEATE bundle missing at {ideate_path}")
    source = str(source_run_id or "").strip()
    replay_reason = str(reason or "").strip()
    if not source or not replay_reason:
        raise ValueError("legacy replay receipt requires source_run_id and reason")
    receipt = {
        "contract_version": LEGACY_REPLAY_CONTRACT_VERSION,
        "source_run_id": source,
        "reason": replay_reason,
        "ideate_bundle_sha256": _sha256_file(ideate_path),
        "limitations_acknowledged": sorted(LEGACY_REPLAY_LIMITATIONS),
    }
    out = ideate_path.parent / LEGACY_REPLAY_RECEIPT_NAME
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(out)


def _require_legacy_replay_receipt(run_dir: str, ideate_path: Path) -> dict:
    receipt_path = ideate_path.parent / LEGACY_REPLAY_RECEIPT_NAME
    if not receipt_path.is_file():
        raise GateBlock(
            "current idea run BLOCK: IDEATE.bundle.json must declare "
            f"memo_contract_version={MEMO_CONTRACT_VERSION!r}; an old merged bundle is accepted only "
            f"with an explicit hash-bound {LEGACY_REPLAY_RECEIPT_NAME} replay receipt"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"legacy idea replay receipt is unreadable: {exc}") from exc
    if not isinstance(receipt, dict):
        raise GateBlock("legacy idea replay receipt must be a JSON object")
    if receipt.get("contract_version") != LEGACY_REPLAY_CONTRACT_VERSION:
        raise GateBlock(
            "legacy idea replay receipt has unsupported contract_version; expected "
            f"{LEGACY_REPLAY_CONTRACT_VERSION!r}"
        )
    if not str(receipt.get("source_run_id") or "").strip() \
            or not str(receipt.get("reason") or "").strip():
        raise GateBlock("legacy idea replay receipt requires non-blank source_run_id and reason")
    acknowledged = {
        str(value) for value in (receipt.get("limitations_acknowledged") or [])
        if str(value).strip()
    }
    if acknowledged != LEGACY_REPLAY_LIMITATIONS:
        raise GateBlock(
            "legacy idea replay receipt must acknowledge exactly that replay has no current "
            "scientific rank and no current PASS"
        )
    expected_hash = _sha256_file(ideate_path)
    if receipt.get("ideate_bundle_sha256") != expected_hash:
        raise GateBlock(
            "legacy idea replay receipt hash mismatch: the IDEATE bundle changed after replay was "
            "authorized"
        )
    return receipt


_PANEL_OWNER = {
    "IDEATE": "hypothesis-generator",
    "RANKING": "idea-tournament-ranker",
    "COLLISION": "novelty-collision-checker",
    "EXPERIMENT": "experiment-planner",
}

_PANEL_REFRESH = {
    "IDEATE": ["idea-tournament-ranker", "novelty-collision-checker", "experiment-planner"],
    "RANKING": ["novelty-collision-checker", "experiment-planner"],
    "COLLISION": [],
    "EXPERIMENT": [],
}


def _panel_supplement(name: str, defect: str, summary: str) -> TargetedGateBlock:
    owner = _PANEL_OWNER.get(name, name.casefold())
    return TargetedGateBlock(
        summary,
        [{
            "defect_id": f"new-direction-{name.casefold()}-{defect}",
            "category": "worker-output-contract",
            "location": f"IDEATE/{name}.bundle.json",
            "summary": summary,
            "target_agents": [owner],
            "refresh_agents": _PANEL_REFRESH.get(name, []),
        }],
    )


def _load_current_panel_bundle(run_dir: str, name: str, required_keys: tuple[str, ...]) -> dict:
    logical = Path(run_dir) / "inbox" / f"{name}.bundle.json"
    try:
        path = resolve_effective_output(Path(run_dir), "IDEATE", logical)
    except ValueError as exc:
        raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
    if not path.is_file():
        raise _panel_supplement(
            name, "missing-bundle",
            f"current idea panel needs a targeted supplement: {name}.bundle.json missing; proposer, ranker, collision "
            "checker, and experiment planner are all mandatory independent seats"
        )
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _panel_supplement(
            name, "unreadable-json",
            f"current idea panel needs a targeted JSON supplement: {name}.bundle.json is unreadable: {exc}",
        ) from exc
    if not isinstance(bundle, dict):
        raise _panel_supplement(
            name, "json-wrapper",
            f"current idea panel needs one object-valued {name}.bundle.json",
        )
    if bundle.get("memo_contract_version") != MEMO_CONTRACT_VERSION:
        raise _panel_supplement(
            name, "contract-version",
            f"current idea panel needs a contract-field supplement: {name}.bundle.json must declare "
            f"memo_contract_version={MEMO_CONTRACT_VERSION!r}"
        )
    missing = [key for key in required_keys if key not in bundle]
    if missing:
        raise _panel_supplement(
            name, "missing-required-content",
            f"new_direction {name} bundle needs required field(s) {missing}; preserve all existing content",
        )
    return bundle


def _require_worker_boundaries(proposal: dict, ranking: dict, collision: dict,
                               experiment: dict) -> None:
    ownership = {
        "IDEATE": (proposal, {"tournament", "evolved", "investment_assessments", "findings", "sketches"}),
        "RANKING": (ranking, {"hypotheses", "ideas", "findings", "sketches"}),
        "COLLISION": (collision, {"hypotheses", "ideas", "tournament", "evolved",
                                  "investment_assessments", "sketches"}),
        "EXPERIMENT": (experiment, {"hypotheses", "ideas", "tournament", "evolved",
                                     "investment_assessments", "findings"}),
    }
    for name, (bundle, forbidden_fields) in ownership.items():
        crossed = sorted(set(bundle) & forbidden_fields)
        if crossed:
            raise GateBlock(
                f"current idea panel BLOCK: {name}.bundle.json crossed worker ownership boundary: "
                f"{crossed}"
            )


def _load_ideate_bundle(run_dir) -> dict:
    """Load a fail-closed current panel or an explicitly authorized historical replay.

    Current runs must provide four distinct ``idea-investment-memo/v2`` bundles. A historical merged
    bundle is replayable only when a separate receipt binds its exact SHA-256 and acknowledges that it
    cannot earn a current scientific rank/PASS. Merely omitting the version is therefore never a bypass.
    """
    ideate_path = Path(run_dir) / "inbox" / "IDEATE.bundle.json"
    proposal = _load_bundle(run_dir, "IDEATE")
    ranking_path = Path(run_dir) / "inbox" / "RANKING.bundle.json"
    version = proposal.get("memo_contract_version")
    if version is None:
        _require_legacy_replay_receipt(str(run_dir), ideate_path)
        if ranking_path.exists():
            raise GateBlock(
                "legacy idea replay BLOCK: RANKING.bundle.json is present beside a merged historical "
                "IDEATE bundle; replay the frozen legacy bundle only, or migrate all four workers to "
                f"{MEMO_CONTRACT_VERSION}"
            )
        merged = dict(proposal)
        merged[_CONTRACT_STATUS_KEY] = _LEGACY_UNVERIFIED
        return merged
    if version != MEMO_CONTRACT_VERSION:
        raise GateBlock(
            f"current idea run BLOCK: unsupported memo_contract_version={version!r}; expected "
            f"{MEMO_CONTRACT_VERSION!r}"
        )

    ranking = _load_current_panel_bundle(
        str(run_dir), "RANKING", ("tournament", "evolved", "investment_assessments"))
    collision = _load_current_panel_bundle(str(run_dir), "COLLISION", ("findings", "evidence_ref"))
    experiment = _load_current_panel_bundle(str(run_dir), "EXPERIMENT", ("sketches",))
    _require_worker_boundaries(proposal, ranking, collision, experiment)

    merged = dict(proposal)
    for key in ("tournament", "evolved", "investment_assessments"):
        merged[key] = ranking[key]
    merged[_CONTRACT_STATUS_KEY] = _CURRENT_CONTRACT
    return merged


def _vault_slug_set():
    root = _shared.resolve_vault_root(DEFAULT_VAULT)
    return _shared.vault_slugs(root), root


_BACKLOG_IDEA_FIELDS = {
    "idea_id", "summary", "evidence_ref", "from_hypothesis_ref", "novelty_ref",
    "feasibility", "caveats",
}


def _backlog_candidate(idea: dict) -> dict:
    """Project a rich proposal onto the stable typed ``idea_backlog`` contract.

    Investment-memo fields remain in worker bundles and the Markdown review
    layer. This keeps machine artifacts schema-valid and avoids turning the
    human decision surface into a new database contract.
    """
    return {key: value for key, value in idea.items() if key in _BACKLOG_IDEA_FIELDS}


# --------------------------------------------------------------------------- deterministic producers (WORK)

def _discover_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(
        b, ("evidence_table", "claim_list", "claim_evidence_map", "signals"),
        stage="DISCOVER", mode="new_direction")
    paths = []
    et, cl, cem = b["evidence_table"], b["claim_list"], b["claim_evidence_map"]
    signals = [x for x in b["signals"] if isinstance(x, dict)]

    # NORTH-STAR drift gate first (audit H2): direction before content.
    texts = [str(et.get("query") or "")]
    texts += [str(s.get("statement") or "") for s in signals]
    texts += [str(c.get("text") or "") for c in (cl.get("claims") or [])]
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)
    paths.append(dpath)

    ev = build_verdict(et)                                                   # HARD GATE 1
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK":
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")

    cv = build_report(cl, cem, resolvable_refs=_shared.resolvable_refs(et))  # HARD GATE 2 (W2 fix)
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")

    # HARD GATE 3 (audit H4): live existence check over external refs (offline-safe).
    # The focal evidence set is already frozen by upstream reads/pre-search. Re-querying every
    # secondary ref here caused latency and false negatives; strict existence replay remains part
    # of vault promotion rather than ordinary idea delivery.
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts, [])
    paths.append(epath)

    # HARD GATE 4 (audit H3): every [[slug]] anywhere in the bundle must name a real vault page.
    slug_set, _root = _vault_slug_set()
    refs = [str(s.get("ref") or "") for s in (et.get("sources") or [])]
    refs += [str(c.get("source_ref") or "") for c in (cl.get("claims") or [])]
    for m in (cem.get("mappings") or []):
        refs += [str(l.get("source_ref") or "") for l in (m.get("loci") or [])]
    for s in signals:
        refs += [str(s.get("source_ref") or "")] + [str(r) for r in (s.get("evidence_ref") or [])]
    violations, warnings = _shared.check_referential_integrity(
        [r for r in refs if r], known_ids=set(), vault_slug_set=slug_set)
    if violations:
        raise GateBlock(f"vault-slug integrity BLOCK: {violations}")

    fw = {"items": [{"item_id": f"FW-{i + 1}", "statement": s["statement"],
                     "source_ref": s.get("source_ref") or s["evidence_ref"][0]}
                    for i, s in enumerate([x for x in signals if x.get("statement")])]}
    paths.append(write_artifact(run_dir, "DISCOVER", "future-work-items.artifact.json",
                                "future_work_items", "future-work-miner", fw, ts))
    gc = build_classification(signals)
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))

    # Novelty (score-only) — now retrieval-grounded when the pre-search bundle exists (audit H5).
    records = _shared.search_records(run_dir)
    ns_signals = _shared.novelty_signals_from_search(gc["gaps"], records)
    ns = aggregate_novelty(gc["gaps"], signals=ns_signals)
    paths.append(write_artifact(run_dir, "DISCOVER", "novelty-score.artifact.json",
                                "novelty_score", "novelty-scorer", ns, ts))

    # Cross-run project memory (audit C1): 'you already explored this one' becomes visible.
    overlaps = []
    ws = workspace_for_run(run_dir)
    if ws is not None:
        run_id = _shared.task_frame(run_dir)["payload"]["task_id"]
        overlaps = prior_overlaps(gc["gaps"], load_gap_inventory(ws), run_id=run_id)
        append_gap_inventory(ws, run_id, ts, gc["gaps"])

    report = {"evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
              "existence_gate": ex["verdict"], "existence_warnings": len(ex["warnings"]),
              "gaps_classified": len(gc["gaps"]),
              "novelty_grounded": bool(records),
              "prior_gap_overlaps": overlaps,
              "slug_warnings": warnings}
    if not records:
        report["note"] = ("novelty is vault-only (no pre-search bundle) — run "
                          "`operate pre-search` before the DISCOVER worker to ground it in live literature")
    return paths, report


def _ideate_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ("hypotheses", "ideas", "tournament", "evolved"),
                                stage="IDEATE", mode="new_direction")
    contract_status = b.get(_CONTRACT_STATUS_KEY)
    if contract_status not in {_CURRENT_CONTRACT, _LEGACY_UNVERIFIED}:
        raise GateBlock(
            "idea contract gate BLOCK: IDEATE data did not pass the current-panel or explicit-replay "
            "loader"
        )
    paths = []
    hypotheses = [h for h in b["hypotheses"] if isinstance(h, dict)]
    ideas = [i for i in b["ideas"] if isinstance(i, dict)]
    matches_raw = [m for m in b["tournament"] if isinstance(m, dict)]
    evolved = [e for e in b["evolved"] if isinstance(e, dict)]

    # NORTH-STAR drift gate (audit H2).
    texts = [str(h.get("statement") or "") for h in hypotheses]
    texts += [str(i.get("summary") or "") for i in ideas]
    texts += [str(e.get("summary") or "") for e in evolved]
    dpath, _ = _shared.run_drift_gate(run_dir, "IDEATE", ts, texts)
    paths.append(dpath)

    # Referential integrity (audit H3): every ref must resolve to a REAL upstream id / vault page.
    gc_path = Path(run_dir) / "evidence" / "DISCOVER" / "gap-classification.artifact.json"
    gap_ids = set()
    if gc_path.exists():
        gc = json.loads(gc_path.read_text(encoding="utf-8"))["payload"]
        gap_ids = {str(g.get("gap_id")) for g in (gc.get("gaps") or []) if g.get("gap_id")}
    ih_ids = {str(h.get("hypothesis_id")) for h in hypotheses if h.get("hypothesis_id")}
    idea_ids = {str(i.get("idea_id")) for i in ideas if i.get("idea_id")}
    ev_ids = {str(e.get("idea_id")) for e in evolved if e.get("idea_id")}
    known = gap_ids | ih_ids | idea_ids | ev_ids
    slug_set, vault_root = _vault_slug_set()

    refs = []
    for h in hypotheses:
        refs += [str(r) for r in (h.get("evidence_ref") or [])]
    for i in ideas:
        refs += [str(r) for r in (i.get("evidence_ref") or [])]
        if i.get("from_hypothesis_ref"):
            refs.append(str(i["from_hypothesis_ref"]))
    for e in evolved:
        refs += [str(r) for r in (e.get("evidence_ref") or [])]
    violations, ri_warnings = _shared.check_referential_integrity(refs, known, slug_set)
    for e in evolved:                                   # parent provenance is checked directly
        bad_parents = [p for p in (e.get("parent_ids") or []) if str(p) not in idea_ids]
        if bad_parents:
            violations.append(
                f"evolved idea {e.get('idea_id')!r}: parent_ids {bad_parents} are not this run's "
                "idea ids — an evolved idea must descend from real parents")
    if violations:
        raise GateBlock(f"referential-integrity gate BLOCK at IDEATE: {violations}")

    paths.append(write_artifact(run_dir, "IDEATE", "hypothesis-set.artifact.json",
                                "hypothesis_set", "hypothesis-generator", {"hypotheses": hypotheses}, ts))

    # Dedup (AI-Researcher 0.8 pattern) then the round-robin Elo tournament (audit B3).
    dd = dedupe_ideas(ideas)
    kept_ids = {str(i["idea_id"]) for i in dd["kept"]}
    bundle_ref = "inbox/IDEATE.bundle.json"
    ranking_ref = ("inbox/RANKING.bundle.json"
                   if (Path(run_dir) / "inbox" / "RANKING.bundle.json").is_file()
                   else bundle_ref)
    matches = []
    for idx, m in enumerate(matches_raw):
        a, bb, w = str(m.get("pair_a") or ""), str(m.get("pair_b") or ""), str(m.get("winner") or "")
        if not ({a, bb} <= idea_ids):
            raise GateBlock(f"tournament match {idx} names unknown idea id(s): {sorted({a, bb} - idea_ids)}")
        if a not in kept_ids or bb not in kept_ids:
            continue                                    # a merged duplicate's matches drop harmlessly
        matches.append({"round": int(m.get("round") or 1), "pair_a": a, "pair_b": bb, "winner": w,
                        "rationale_ref": str(m.get("rationale_ref") or f"{ranking_ref}#tournament[{idx}]")})
    tournament = {}
    if len(kept_ids) >= 2:
        expected = {tuple(sorted(p)) for p in
                    [(x, y) for x in kept_ids for y in kept_ids if x < y]}
        judged = {tuple(sorted((m["pair_a"], m["pair_b"]))) for m in matches}
        missing = sorted(expected - judged)
        if missing:
            raise _panel_supplement(
                "RANKING", "incomplete-tournament",
                f"tournament incomplete: unjudged idea pair(s) {missing} — the IDEATE worker must "
                "judge EVERY unordered pair of its (deduplicated) ideas exactly once")
        tournament = build_elo_tournament(matches, evidence_ref=[ranking_ref],
                                          fmt="round_robin", all_ids=sorted(kept_ids))
        paths.append(write_artifact(run_dir, "IDEATE", "idea-tournament.artifact.json",
                                    "elo_tournament", "idea-tournament-ranker", tournament, ts))

    if evolved:
        ev_payload = {"ideas": [{k: v for k, v in e.items() if k in
                                 ("idea_id", "summary", "parent_ids", "evidence_ref", "mutation_type")}
                                for e in evolved]}
        paths.append(write_artifact(run_dir, "IDEATE", "evolved-ideas.artifact.json",
                                    "evolved_ideas", "idea-evolver", ev_payload, ts))

    # The /idea-bet MENU: kept originals + evolved ideas, with negative-result caveats from the vault
    # attached (audit C2). Strict memo runs are ranked by a scientific-investment composite; feasibility
    # remains one bounded input and can never become the scientific verdict by itself.
    menu_ideas = [_backlog_candidate(i) for i in dd["kept"]]
    for e in evolved:
        menu_ideas.append(_backlog_candidate({
            "idea_id": str(e.get("idea_id")), "summary": str(e.get("summary") or ""),
            "evidence_ref": list(e.get("evidence_ref") or []),
            "feasibility": dict(e.get("feasibility") or {}),
            "caveats": list(e.get("caveats") or []),
        }))
    if contract_status == _LEGACY_UNVERIFIED:
        replay_caveat = (
            "LEGACY_UNVERIFIED replay: no current scientific-investment rank or current PASS; "
            "rerun the independent proposer/ranker/collision/planner panel before betting."
        )
        for idea in menu_ideas:
            idea["caveats"] = list(idea.get("caveats") or []) + [replay_caveat]
    nr = _shared.negative_result_caveats(vault_root, menu_ideas)
    for i in menu_ideas:
        flags = nr.get(str(i.get("idea_id")), [])
        if flags:
            i["caveats"] = list(i.get("caveats") or []) + flags

    records = _shared.search_records(run_dir)
    grounding = score_idea_grounding(menu_ideas, records, known_internal_ids=known,
                                     evidence_ref=[bundle_ref])
    paths.append(write_artifact(run_dir, "IDEATE", "idea-grounding-report.artifact.json",
                                "idea_grounding_report", "feasibility-reranker", grounding, ts))

    # NOVELTY-COLLISION GATE (director lock 2026-06-18): the mandatory pre-/idea-bet prior-art check.
    # A cut requires an existence-verified, full-text-reviewed exact collision on the central claim,
    # input/output contract, causal assay, and required experiments. The ledger only supplies leads. A
    # novelty SCORE still never cuts (design §1). Offline -> nothing cut, all UNVERIFIED, flagged below.
    survivors, cverdict, cpath = _shared.run_collision_gate(
        run_dir, "IDEATE", ts, menu_ideas, hard_block=_collision_hard_block(run_dir))
    paths.append(cpath)
    collision_bundle = _shared.collision_findings_bundle(run_dir) or {}
    collision_finding_ids = {
        str(row.get("idea_id")) for row in (collision_bundle.get("findings") or [])
        if isinstance(row, dict) and row.get("idea_id")
    }
    survivor_ids = {str(row.get("idea_id")) for row in survivors if row.get("idea_id")}
    missing_collision_findings = sorted(survivor_ids - collision_finding_ids)

    backlog = build_idea_backlog(survivors, budget=_shared.budget(run_dir))
    if contract_status == _CURRENT_CONTRACT:
        assessments = [row for row in (b.get("investment_assessments") or [])
                       if isinstance(row, dict)]
        assessment_errors = validate_assessments(
            assessments, [str(row.get("idea_id")) for row in survivors])
        if assessment_errors:
            raise _panel_supplement(
                "RANKING", "invalid-investment-assessment",
                f"scientific-investment assessment needs a targeted supplement: {assessment_errors}",
            )
        try:
            experiment_path = resolve_effective_output(
                Path(run_dir), "IDEATE", Path(run_dir) / "inbox" / "EXPERIMENT.bundle.json"
            )
        except ValueError as exc:
            raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
        if not experiment_path.is_file():
            raise _panel_supplement(
                "EXPERIMENT", "missing-bundle",
                "scientific-investment rank needs a supplement: EXPERIMENT.bundle.json missing; "
                "dispatch the independent experiment-planner before ranking"
            )
        experiment_bundle = json.loads(experiment_path.read_text(encoding="utf-8"))
        backlog["ranked_ideas"] = rank_scientific_investments(
            backlog["ranked_ideas"],
            assessments=assessments,
            tournament=tournament,
            grounding=grounding,
            sketches=experiment_bundle.get("sketches") or [],
            novelty_retrieval_grounded=(
                bool(cverdict.get("retrieval_grounded")) and not missing_collision_findings
            ),
        )
    paths.append(write_artifact(run_dir, "IDEATE", "idea-backlog.artifact.json",
                                "idea_backlog", "idea-tournament-ranker", backlog, ts))
    return paths, {"ideas_ranked": len(backlog["ranked_ideas"]),
                   "dedup_merged": len(dd["merged"]),
                   "tournament_matches": len(matches),
                   "evolved": len(evolved),
                   "grounding_advisory": bool(records),
                   "negative_result_flags": sum(len(v) for v in nr.values()),
                   "collision_cut": len(cverdict["cut_ids"]),
                   "collision_white_space": sum(1 for e in cverdict["ideas"]
                                                if e["verdict"] == "WHITE_SPACE"),
                    "collision_unverified": sum(1 for e in cverdict["ideas"]
                                                if e["verdict"] == "UNVERIFIED"),
                    "collision_retrieval_grounded": cverdict["retrieval_grounded"],
                    "collision_missing_findings": missing_collision_findings,
                    "idea_contract_status": contract_status,
                    "current_scientific_rank": contract_status == _CURRENT_CONTRACT,
                    "slug_warnings": ri_warnings}


def _report(run_dir, ts) -> tuple:
    records = _shared.search_records(run_dir)
    note = {"summary": "new-direction menu: evidence-grounded ideas, tournament-judged, "
                       "prior-art-collision screened, and scientific-investment ranked; awaiting /idea-bet "
                       "(the director bets — the machine never does)",
            "references": ["director-review/ideas/idea-bet-menu.md",
                           "evidence/IDEATE/idea-backlog.artifact.json",
                           "evidence/IDEATE/idea-tournament.artifact.json",
                           "evidence/IDEATE/novelty-collision-verdict.artifact.json",
                           "evidence/DISCOVER/novelty-score.artifact.json"],
            "produced_artifacts": [], "open_questions": []}
    backlog_path = Path(run_dir) / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
    if backlog_path.is_file():
        backlog = json.loads(backlog_path.read_text(encoding="utf-8")).get("payload") or {}
        ranked = [row for row in (backlog.get("ranked_ideas") or []) if isinstance(row, dict)]
        if ranked and not all(row.get("scientific_investment") for row in ranked):
            note["summary"] = (
                "LEGACY_UNVERIFIED idea replay rendered for historical inspection; it has no current "
                "scientific-investment rank or current PASS and must not be used as an /idea-bet input"
            )
            note["open_questions"].append(
                "legacy replay only: rerun the independent proposer, ranker, collision checker, and "
                "experiment planner under idea-investment-memo/v2 before betting"
            )
    # Honesty (director lock "必须检查"): a run that could not verify novelty, or that cut ideas for
    # prior art, must say so to the director — never present a silently-clean menu.
    cp = Path(run_dir) / "evidence" / "IDEATE" / "novelty-collision-verdict.artifact.json"
    if cp.exists():
        cv = json.loads(cp.read_text(encoding="utf-8"))["payload"]
        if not cv.get("retrieval_grounded"):
            note["open_questions"].append(
                "novelty was NOT verified this run (collision retrieval not grounded) — re-run with "
                "`operate pre-search` + the novelty-collision worker before betting")
        if cv.get("cut_ids"):
            note["open_questions"].append(
                f"{len(cv['cut_ids'])} idea(s) cut for evidenced prior-art collision (already done) — "
                "see novelty-collision-verdict; cut from the bet menu, not hidden — you may override")
    if not records:
        note["open_questions"].append("novelty was vault-only this run (no pre-search bundle) — "
                                      "consider re-running with `operate pre-search` for literature grounding")
    paths = [write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)]
    # RAT-2 Wave-3 deepening (2026-06-19; additive, REPORT-stage ONLY — zero change to the proven
    # DISCOVER/IDEATE contract): a cross-stage quality scorecard (quality-controller) + an advisory
    # integrity recommendation + the blind pairwise quality eval over the menu. deep_ideation adds the
    # upstream deep chain (formalize/mechanism/analogy/contradiction/experiment); new_direction stays the
    # lean flagship but now reports a decomposed, auditable quality read on the same /idea-bet menu.
    paths += _deep_ideate.produce_report_quality(run_dir, ts)
    try:
        md_path = write_idea_bet_menu(run_dir, generated_at=ts)
    except ValueError as exc:
        raise GateBlock(str(exc))
    return (paths, {"director_idea_bet_menu": md_path})


def run_dets(run_dir, stage, ts) -> tuple:
    """Run the deterministic producers/gates for a stage. Returns (artifact_paths, report). Raises
    GateBlock if a hard gate refuses (the run halts; the stage is NOT committed). new_direction is
    deep-by-default + GRACEFUL: after the proven base, the deep producers run with required=False — a
    skipped deep worker degrades to the base instead of blocking (deep_ideation runs them STRICT)."""
    if stage == "DISCOVER":
        paths, report = _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
        dpaths, frag = _deep_ideate.deep_discover_producers(run_dir, ts, required=False)
        report.update(frag)
        return paths + dpaths, report
    if stage == "IDEATE":
        paths, report = _ideate_dets(run_dir, ts, _load_ideate_bundle(run_dir))
        dpaths, frag = _deep_ideate.deep_ideate_producers(run_dir, ts, required=False)
        report.update(frag)
        try:
            report["director_idea_bet_menu"] = write_idea_bet_menu(run_dir, generated_at=ts)
        except ValueError as exc:
            raise GateBlock(str(exc))
        return paths + dpaths, report
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"new_direction has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop (audit M2 — the flagship mode now has the same repair path as the
    evidence modes): ("ok", (paths, report)) or ("retry", feedback). Re-raises the original
    GateBlock at the cap (director escalation)."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))


def menu(run_dir) -> list:
    """The /idea-bet menu: scientific-investment rank when available, plus component evidence."""
    p = Path(run_dir) / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
    if not p.exists():
        return []
    bl = json.loads(p.read_text(encoding="utf-8"))["payload"]
    elo_by_id = {}
    tp = Path(run_dir) / "evidence" / "IDEATE" / "idea-tournament.artifact.json"
    if tp.exists():
        t = json.loads(tp.read_text(encoding="utf-8"))["payload"]
        elo_by_id = {r["idea_id"]: {"elo": r["elo"], "elo_rank": r["rank"]} for r in t["ratings"]}
    rows = []
    for i in bl["ranked_ideas"]:
        investment = i.get("scientific_investment") or {}
        row = {"rank": i["rank"], "idea_id": i["idea_id"],
               "score": investment.get("score", i["feasibility"]["score"]),
               "score_kind": "scientific_investment" if investment else "legacy_feasibility",
               "trust_status": "CURRENT_SCIENTIFIC_RANK" if investment else _LEGACY_UNVERIFIED,
               "feasibility_score": i["feasibility"]["score"], "summary": i["summary"],
               "caveats": list(i.get("caveats") or [])}
        row.update(elo_by_id.get(i["idea_id"], {}))
        rows.append(row)
    return rows


def cut_for_prior_art(run_dir) -> list:
    """The ideas CUT before the /idea-bet menu for an evidenced prior-art collision (DEAD), each with
    its colliding papers + reason — shown to the director ALONGSIDE the menu (cut, NOT hidden; the
    director may still override). [] when nothing was cut or the gate did not run. The companion to
    menu(): menu() = what you may bet on; this = what was already done so you cannot bet on it."""
    p = Path(run_dir) / "evidence" / "IDEATE" / "novelty-collision-verdict.artifact.json"
    if not p.exists():
        return []
    v = json.loads(p.read_text(encoding="utf-8"))["payload"]
    return [{"idea_id": e["idea_id"], "verdict": e["verdict"], "reason": e.get("reason", ""),
             "colliding_papers": e.get("colliding_papers", []), "source": e.get("source", "")}
            for e in v.get("ideas", []) if e.get("cut")]
