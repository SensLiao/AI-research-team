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
from ._ideation_prompts import (
    DIRECTION_ADVISOR_WORKER_PROMPT,
    INVESTMENT_COLLISION_WORKER_PROMPT,
    DIVERGENCE_OPERATOR_BLOCK,
    DIVERGENCE_RUNNER_WORKER_PROMPT,
    DIVERGENCE_TRACE_JSON,
    PROPOSER_WORKER_PROMPT,
    RANKER_WORKER_PROMPT,
)
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
from ...tools.saturation_meter import measure_saturation
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
     "saturation_reached": false}},
  "saturation_rounds": [{{"round_index":1,"queries_run":0,"new_unique_sources":0,
     "cumulative_unique_sources":0}}],
  "claim_list": {{"source_scope": "<scope>",
     "claims": [{{"claim_id":"c1","text":"<claim>","source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings": [{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true}}]}}]}},
  "signals": [{{"gap_id":"GAP-1","statement":"<stated future-work/limitation>","source_ref":"[[<slug>]]",
     "evidence_ref":["[[<slug>]]"],"derived_from":["future_work"]}}]
}}
Quantities are FLOORS, not ranges — there is NO upper bound, and volume is wanted: \
evidence_table.sources >=20 (>=5 "strong"); claims >=10 (each anchored by a mapping, every locus \
supports_claim:true); signals >=12 with VARIED gap types (include the field(s) that set the type) and an \
honest `derived_from` list (1-3 tags) — more distinct tags = higher novelty:
  stated_open_problem -> statement+source_ref ; methodological_gap -> locus+opportunity ;
  coverage_gap -> white_space_present:true ; transfer_gap -> source_domain+target_hook ;
  assumption_gap -> challenged_assumption ; evidence_gap -> under_evidenced:true ;
  empirical_gap -> untested_condition .
derived_from tags: future_work, white_space_present, weakness_opportunity, transfer_potential, \
contrarian_angle, under_evidenced, empirically_untested.
`saturation_reached` is a compatibility field only — always emit false and never self-declare \
saturation; a deterministic meter derives it from your search rounds. Record those rounds in \
`saturation_rounds`: one entry per retrieval pass with {{round_index, queries_run, \
new_unique_sources, cumulative_unique_sources}}. Run at least TWO passes — one pass can never be \
saturated, and the meter honestly reports INSUFFICIENT_DATA for a single round.

Rigor bar (max-quality): for EACH gap, satisfy yourself it is genuinely OPEN — not already solved by \
a paper you read OR by a record in the live-retrieval bundle; if a paper partially closes it, narrow the \
gap to the part that remains. Prefer gaps whose evidence_ref cites >=2 independent papers. Mark \
claim_support "strong" ONLY for a paper that centrally and directly supports the claim.
Volume discipline (director lock 2026-08-04): the bar is PER ITEM, never a cap on the number of items. \
Every gap you emit must clear the bar above on its own — grounded in a real page or a real record, and \
genuinely still open. Having cleared it, EMIT IT: do not drop a defensible gap to keep the list short, do \
not stop at the floor, and do not summarize several distinct gaps into one. A long list of individually \
defensible gaps is the goal; a short list is only correct when the corpus genuinely cannot support more, \
and then you must say so explicitly in `read_summary`.
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


#: Every IDEATE-panel packet (proposer / ranker / collision checker / divergence runner / direction
#: advisor) lives in `_ideation_prompts.py`, imported above and re-exported here — the invention-first
#: rewrite of 2026-08-07 made them too large to keep inline. deep_ideation reuses this module's
#: builders, so both modes read from ONE prompt source.



# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def _worker_model(stage: str, model_policy: str) -> str:
    """max_quality (the director's default for governed research runs, 2026-06-09) -> all-opus.

    default -> task-appropriate. DISCOVER moved to opus on 2026-08-07: the grounding scout does not
    merely extract, it decides what counts as a still-OPEN gap, and every downstream idea inherits that
    judgment — a cheap read here silently caps the whole run's ceiling. The parameters are kept so a
    future stage can route down again without a signature change.
    """
    return "opus"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, **funnel_kwargs) -> str:
    """Live-retrieval pre-step (audit H5): grounds DISCOVER + novelty in real literature."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries,
                              **funnel_kwargs)


def discover_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                    model_policy: str = "default") -> dict:
    """The base DISCOVER grounding worker (evidence_table / claim_list / claim_evidence_map / signals).
    Reused by deep_ideation too (so the two modes share ONE base-worker definition — no drift)."""
    out = f"{run_dir}/inbox/DISCOVER.bundle.json"
    return {"label": "direction-grounding-scout", "model": _worker_model("DISCOVER", model_policy), "output": out,
            "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault, out=out,
                                                    run_dir=run_dir,
                                                    north_star=_shared.north_star_block(run_dir))}


def divergence_worker(run_dir: str, request: str, model_policy: str = "default") -> dict:
    """The B1 seat: runs the six divergence operators over the frozen DISCOVER material BEFORE the
    proposer, so divergence is an accountable artifact instead of a side effect of whoever wrote the
    ideas. The proposer keeps the same operator block as its own fallback, so a lighter run that does
    NOT dispatch this seat still diverges — it just does not get an independent trace."""
    out = f"{run_dir}/inbox/DIVERGENCE.bundle.json"
    return {"label": "divergence-operator-runner", "model": _worker_model("IDEATE", model_policy),
            "output": out,
            "prompt": DIVERGENCE_RUNNER_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out,
                north_star=_shared.north_star_block(run_dir),
                divergence_operators=DIVERGENCE_OPERATOR_BLOCK,
                divergence_trace=DIVERGENCE_TRACE_JSON)}


def ideate_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                  model_policy: str = "default") -> dict:
    """Independent proposer: hypotheses and memo-ready ideas, with no comparative judgment."""
    out = f"{run_dir}/inbox/IDEATE.bundle.json"
    return {"label": "hypothesis-generator", "model": _worker_model("IDEATE", model_policy), "output": out,
            "prompt": PROPOSER_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out, vault=vault,
                north_star=_shared.north_star_block(run_dir),
                divergence_operators=DIVERGENCE_OPERATOR_BLOCK,
                divergence_trace=DIVERGENCE_TRACE_JSON)}


def ranker_worker(run_dir: str, request: str, model_policy: str = "default") -> dict:
    """Independent comparative judge, dispatched only after the proposal bundle exists."""
    out = f"{run_dir}/inbox/RANKING.bundle.json"
    return {"label": "idea-tournament-ranker", "model": _worker_model("IDEATE", model_policy),
            "output": out, "depends_on": ["hypothesis-generator"],
            "prompt": RANKER_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out,
                north_star=_shared.north_star_block(run_dir))}


def direction_advisor_worker(run_dir: str, request: str, model_policy: str = "default") -> dict:
    """The B5 seat: an ADVISORY outer-loop reading of the finished run (DEEPEN / BROADEN / PIVOT /
    CONCLUDE, each with evidence for and against). It recommends; it never decides, bets, ranks, or
    touches the menu — the director decides at /idea-bet. Absent seat degrades to no recommendation."""
    out = f"{run_dir}/inbox/DIRECTION_ADVICE.bundle.json"
    return {"label": "direction-decision-advisor", "model": _worker_model("REPORT", model_policy),
            "output": out,
            "prompt": DIRECTION_ADVISOR_WORKER_PROMPT.format(
                request=request, run_dir=run_dir, out=out,
                north_star=_shared.north_star_block(run_dir))}


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The worker PANEL to dispatch for a stage (or None if deterministic). new_direction is now
    deep-by-default but SINGLE-DOMAIN (it omits the cross-domain analogy-mapper — that breadth layer is
    deep_ideation's signature) and GRACEFUL (run_dets uses required=False, so a skipped deep worker
    degrades to the proven base instead of blocking). Panels are spawned IN ORDER (each deep worker reads
    the prior inbox bundles). NORTH STAR is in every worker prompt (audit A2). REPORT dispatches ONE
    advisory seat (direction-decision-advisor) and is otherwise deterministic."""
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
        workers = [divergence_worker(run_dir, request, model_policy),
                   ideate_worker(run_dir, request, vault, model_policy),
                   ranker_worker(run_dir, request, model_policy),
                   collision_step(run_dir, vault=vault, model_policy=model_policy),
                   _deep_ideate.experiment_worker(run_dir, request, model_policy)]
        return {"workers": workers,
                "worker_order": [worker["label"] for worker in workers],
                "parallel_groups": [[worker["label"]] for worker in workers],
                "panel_note": "spawn IN ORDER: divergence-operator-runner (six operators over the frozen "
                              "DISCOVER material) -> hypothesis-generator (proposer) -> "
                              "idea-tournament-ranker -> novelty-collision-checker -> experiment-planner. "
                              "Each worker owns a distinct bundle and reads only its declared "
                              "predecessors."}
    if stage == "REPORT":
        worker = direction_advisor_worker(run_dir, request, model_policy)
        return {"workers": [worker],
                "worker_order": [worker["label"]],
                "parallel_groups": [[worker["label"]]],
                "panel_note": "direction-decision-advisor reads the finished run and recommends "
                              "DEEPEN/BROADEN/PIVOT/CONCLUDE with evidence on both sides. Advisory only: "
                              "the REPORT artifacts stay deterministic and the director decides."}
    return None


def collision_step(run_dir: str, vault: str = DEFAULT_VAULT,
                   model_policy: str = "default") -> dict:
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
    # Bundle hash comparison removed 2026-08-07 (director lock: no hash/receipt gating). What the
    # receipt is actually for survives intact: an operator must DELIBERATELY name the source run,
    # give a reason, and acknowledge in writing that a replay earns no current rank and no current
    # PASS. That acknowledgement is what stops a historical bundle being mistaken for a fresh one;
    # the digest never added to it.
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


#: Fields projected from a rich proposal onto the typed ``idea_backlog`` contract. The 2026-08-07
#: invention block (contribution_tier / invention_claim / mechanism_graph_refs / innovation_layers /
#: resource_envelope) is carried through because the deterministic ranker reads contribution_tier for
#: the invention feasibility waiver, and the director's menu renders the rest. Every one of them is
#: OPTIONAL in the schema, so an older bundle that omits them still validates.
_BACKLOG_IDEA_FIELDS = {
    "idea_id", "summary", "evidence_ref", "from_hypothesis_ref", "novelty_ref",
    "feasibility", "caveats",
    "contribution_tier", "invention_claim", "mechanism_graph_refs", "intervention_point",
    "addresses_conflicts", "origin_operator", "innovation_layers", "depth_target",
    "conventional_base", "unusual_connection", "resource_envelope",
}


#: The closed origin_operator vocabulary the idea_backlog schema enforces. The merger may write a
#: longer provenance string (e.g. "negation (...); merged from {...}") — the deterministic producer
#: normalizes to the first legal token instead of BLOCKing a real upstream bundle.
_ORIGIN_OPERATORS = ("gap", "constraint", "negation", "reformulation", "cross_product",
                     "enabler", "tension")


def _normalize_origin_operator(value) -> str:
    if isinstance(value, str):
        for op in _ORIGIN_OPERATORS:
            if value.strip().startswith(op):
                return op
    return "gap"


def _backlog_candidate(idea: dict) -> dict:
    """Project a rich proposal onto the stable typed ``idea_backlog`` contract.

    Investment-memo fields remain in worker bundles and the Markdown review
    layer. This keeps machine artifacts schema-valid and avoids turning the
    human decision surface into a new database contract. `origin_operator` is
    normalized to its closed vocabulary (merger provenance strings accepted).
    """
    out = {key: value for key, value in idea.items() if key in _BACKLOG_IDEA_FIELDS}
    if "origin_operator" in out:
        out["origin_operator"] = _normalize_origin_operator(out["origin_operator"])
    return out


# --------------------------------------------------------------------------- deterministic producers (WORK)

def _measured_saturation(bundle: dict) -> bool:
    """Derive `saturation_reached` from the worker's recorded retrieval rounds.

    False whenever the history cannot support a SATURATED verdict — no rounds, a single round
    (INSUFFICIENT_DATA), or a malformed history. The meter never upgrades a thin search.
    """
    rounds = [r for r in (bundle.get("saturation_rounds") or []) if isinstance(r, dict)]
    if not rounds:
        return False
    try:
        return measure_saturation(rounds, report_id="SAT-DISCOVER")["verdict"] == "SATURATED"
    except (ValueError, TypeError, KeyError):
        return False


_DIVERGENCE_OPERATOR_KEYS = (
    "constraints", "negations", "reformulations", "cross_product", "enablers", "tensions",
)


def _produce_divergence_trace(run_dir, ts, ideate_bundle: dict) -> Optional[str]:
    """Record the six-operator divergence trace as a typed artifact.

    Two sources, in priority order: the independent `divergence-operator-runner` seat's bundle, else
    the proposer's own inline `divergence_trace` (the fallback for lighter runs where that seat is not
    dispatched). Neither present -> no artifact, no block: divergence is measured, never gated.
    """
    trace, source = None, ""
    dpath = Path(run_dir) / "inbox" / "DIVERGENCE.bundle.json"
    if dpath.is_file():
        try:
            bundle = json.loads(dpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            bundle = {}
        if isinstance(bundle, dict) and isinstance(bundle.get("divergence_trace"), dict):
            trace, source = bundle, "divergence-operator-runner"
    if trace is None and isinstance(ideate_bundle.get("divergence_trace"), dict):
        trace, source = ideate_bundle, "hypothesis-generator"
    if trace is None:
        return None

    raw = trace["divergence_trace"]
    payload = {
        "trace_id": str(trace.get("trace_id") or "DT-001"),
        "produced_by": source,
        **{key: [x for x in (raw.get(key) or []) if isinstance(x, dict)]
           for key in _DIVERGENCE_OPERATOR_KEYS},
    }
    anomalies = [a for a in (trace.get("anomalies") or []) if isinstance(a, dict)]
    if anomalies:
        payload["anomalies"] = anomalies
    operators_run = [str(x) for x in (trace.get("operators_run") or []) if str(x).strip()]
    if operators_run:
        payload["operators_run"] = operators_run
    return write_artifact(run_dir, "IDEATE", "divergence-trace.artifact.json",
                          "divergence_trace", source, payload, ts)


def _produce_direction_recommendation(run_dir, ts) -> Optional[str]:
    """Project the advisory direction-decision-advisor bundle onto its typed artifact.

    Absent seat -> None. This is ADVICE: DEEPEN / BROADEN / PIVOT / CONCLUDE with evidence on both
    sides, rendered for the director. It never selects an idea and never gates anything.
    """
    path = Path(run_dir) / "inbox" / "DIRECTION_ADVICE.bundle.json"
    if not path.is_file():
        return None
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(bundle, dict) or not bundle.get("recommended"):
        return None
    payload = {
        "recommendation_id": str(bundle.get("recommendation_id") or "DR-001"),
        "recommended": str(bundle["recommended"]),
        "confidence": str(bundle.get("confidence") or "low"),
        "rationale": str(bundle.get("rationale") or ""),
        "options": [o for o in (bundle.get("options") or []) if isinstance(o, dict)],
        "evidence_ref": [str(r) for r in (bundle.get("evidence_ref") or []) if str(r).strip()]
                        or ["inbox/DIRECTION_ADVICE.bundle.json"],
    }
    unresolved = [str(u) for u in (bundle.get("unresolved") or []) if str(u).strip()]
    if unresolved:
        payload["unresolved"] = unresolved
    return write_artifact(run_dir, "REPORT", "direction-recommendation.artifact.json",
                          "direction_recommendation", "direction-decision-advisor", payload, ts)


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

    # Saturation is MEASURED, never self-declared (2026-08-07). The worker records its retrieval rounds;
    # a deterministic meter derives the verdict and overwrites whatever the bundle claimed. A single
    # round can never be saturated (the meter reports INSUFFICIENT_DATA), and no rounds means False.
    # Previously the worker copied `saturation_reached: true` out of its own prompt skeleton and the
    # evidence gate accepted it, so the check verified nothing.
    et["saturation_reached"] = _measured_saturation(b)

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
              "existence_checked": ex["verdict"] != "UNVERIFIED",
              "saturation_reached": ev["saturation_reached"],
              "saturation_rounds": len([r for r in (b.get("saturation_rounds") or [])
                                        if isinstance(r, dict)]),
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
    # DISCOVER claim ids (c1..cN) are real upstream ids too — the multi-view proposers may cite
    # them directly (director lock 2026-08-09); a claim id produced by the grounding bundle must
    # never be judged a fabrication.
    claim_ids = set()
    disc_path = Path(run_dir) / "inbox" / "DISCOVER.bundle.json"
    if disc_path.exists():
        disc = json.loads(disc_path.read_text(encoding="utf-8"))
        claim_ids = {str(c.get("claim_id")) for c in ((disc.get("claim_list") or {}).get("claims") or [])
                     if c.get("claim_id")}
    ih_ids = {str(h.get("hypothesis_id")) for h in hypotheses if h.get("hypothesis_id")}
    idea_ids = {str(i.get("idea_id")) for i in ideas if i.get("idea_id")}
    ev_ids = {str(e.get("idea_id")) for e in evolved if e.get("idea_id")}
    known = gap_ids | claim_ids | ih_ids | idea_ids | ev_ids
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

    dtrace = _produce_divergence_trace(run_dir, ts, b)
    if dtrace:
        paths.append(dtrace)

    # Dedup (AI-Researcher 0.8 pattern) then the round-robin Elo tournament (audit B3).
    dd = dedupe_ideas(ideas)
    kept_ids = {str(i["idea_id"]) for i in dd["kept"]}
    # Killed ideas (director lock 2026-08-09: the ranker's kill filters) do not participate in the
    # tournament — no pairing is required for an idea that will not be ranked; it still appears on
    # the menu with its kill reason.
    ranking_path = Path(run_dir) / "inbox" / "RANKING.bundle.json"
    if ranking_path.is_file():
        try:
            rk = json.loads(ranking_path.read_text(encoding="utf-8"))
            killed = {str(a.get("idea_id")) for a in (rk.get("investment_assessments") or [])
                      if isinstance(a, dict) and a.get("killed")}
            kept_ids -= killed
        except (OSError, ValueError):
            pass  # unreadable ranking = treat as no kills (the tournament gate still enforces pairs)
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
        # An evolved idea is re-authored here rather than passed through, so the projection stays
        # explicit. It must carry the SAME invention block as an original — an evolved recombination is
        # the highest-value output of the ranker, and dropping contribution_tier here would silently
        # deny it the invention feasibility waiver downstream.
        candidate = {
            "idea_id": str(e.get("idea_id")), "summary": str(e.get("summary") or ""),
            "evidence_ref": list(e.get("evidence_ref") or []),
            "feasibility": dict(e.get("feasibility") or {}),
            "caveats": list(e.get("caveats") or []),
        }
        for field in ("contribution_tier", "invention_claim", "mechanism_graph_refs",
                      "intervention_point", "innovation_layers", "depth_target",
                      "conventional_base", "unusual_connection", "resource_envelope"):
            if e.get(field) is not None:
                candidate[field] = e[field]
        menu_ideas.append(_backlog_candidate(candidate))
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
                    "divergence_trace": bool(dtrace),
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
    ep = Path(run_dir) / "evidence" / "DISCOVER" / "citation-existence-verdict.artifact.json"
    if ep.exists():
        exv = json.loads(ep.read_text(encoding="utf-8"))["payload"]
        if str(exv.get("verdict") or "") == "UNVERIFIED":
            note["open_questions"].append(
                "本次没有做任何外部存在性核对：citation existence gate = UNVERIFIED（没有可查的外部"
                "引用，或每一次查询都失败）。不要把它读成'查过了、没问题'——它是'没查'。"
            )
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
    # Advisory outer-loop read (DEEPEN / BROADEN / PIVOT / CONCLUDE). Produced BEFORE the report note so
    # the note can point the director at it; absent seat -> no artifact and no mention.
    rec = _produce_direction_recommendation(run_dir, ts)
    if rec:
        note["references"].append("evidence/REPORT/direction-recommendation.artifact.json")
    paths = [write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)]
    if rec:
        paths.append(rec)
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
    return (paths, {"director_idea_bet_menu": md_path,
                    "direction_recommendation": bool(rec)})


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
