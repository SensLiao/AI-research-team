"""Operate recipe for the `new_direction` mode (DISCOVER -> IDEATE -> REPORT).

Audit waves A-B upgrade (2026-06-13; _design/review/ai-capability-audit-2026-06-12.md):
the flagship find-a-direction flow now runs the FULL grounding + anti-drift + ideation chain.

Split of labour (consolidation honesty unchanged — one worker per stage gathers; the gates that
JUDGE are deterministic):
  - LLM workers do the READING / IDEATION over the real vault. DISCOVER worker -> {evidence_table,
    claim_list, claim_evidence_map, signals}; IDEATE worker -> {hypotheses, ideas, tournament
    judgments (pairwise debates), evolved ideas} grounded in the DISCOVER gaps.
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

import json
from pathlib import Path
from typing import Optional

from . import _deep_ideate, _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.citation_checker import build_report
from ...tools.classify_gap import build_classification
from ...tools.elo_tournament import build_elo_tournament
from ...tools.evidence_checker import build_verdict
from ...tools.feasibility_score import build_idea_backlog
from ...tools.idea_dedup import dedupe_ideas
from ...tools.idea_grounding import score_idea_grounding
from ...tools.novelty_aggregate import aggregate_novelty
from ...tools.project_memory import (
    append_gap_inventory,
    load_gap_inventory,
    prior_overlaps,
    workspace_for_run,
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

IDEATE_WORKER_PROMPT = """You are the IDEATE worker of a research machine. The DISCOVER stage already \
classified real gaps from the vault. Read these real artifacts:
  - `{run_dir}/evidence/DISCOVER/gap-classification.artifact.json`  (the classified gaps)
  - `{run_dir}/evidence/DISCOVER/novelty-score.artifact.json`       (novelty per gap, score-only)
Propose falsifiable hypotheses and concrete project ideas that ADDRESS those gaps, judge them in a \
pairwise tournament, and evolve the strongest — for this request:

    REQUEST: {request}

{north_star}

ALSO check the vault's `{vault}/02-wiki/negative-results/` cluster (if present): an idea that repeats a \
recorded negative result must say so in its own summary or be dropped by you — the machine cross-checks.

HONESTY (hard): every hypothesis/idea must reference at least one real GAP-id (from gap-classification) \
and, where relevant, a real `[[slug]]`. A fabricated GAP-/IH- id or invented slug is caught by a \
deterministic referential-integrity gate and BLOCKs the stage. Make ideas genuinely differ in \
feasibility so a ranking is meaningful. Tournament judgments are real comparative reasoning, not \
coin flips — each rationale must name the decisive difference between the two ideas; weigh each \
pair in BOTH orders before deciding (position-bias discipline).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit \
the COMPLETE bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "hypotheses": [{{"hypothesis_id":"IH1","statement":"<falsifiable hypothesis>",
     "falsifiable_prediction":"<concrete measurable prediction>",
     "evidence_needed":["<what would test it>"],"evidence_ref":["GAP-1","[[<slug>]]"]}}],
  "ideas": [{{"idea_id":"IDEA-1","summary":"<concrete project realizing a hypothesis>",
     "evidence_ref":["IH1","GAP-1"],"from_hypothesis_ref":"IH1",
     "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable","time":"short|medium|long"}}}}],
  "tournament": [{{"round":1,"pair_a":"IDEA-1","pair_b":"IDEA-2","winner":"IDEA-1",
     "rationale":"<the decisive difference, 1-2 sentences naming BOTH ideas' content>"}}],
  "evolved": [{{"idea_id":"EV-1","summary":"<mutation/recombination of top ideas>",
     "parent_ids":["IDEA-1"],"mutation_type":"mutate|recombine|strengthen",
     "evidence_ref":["IDEA-1","GAP-1"],
     "feasibility":{{"compute":"...","data":"...","time":"..."}}}}]
}}
Quantities: 3-5 hypotheses; 3-5 ideas (each `from_hypothesis_ref` -> a real IH id; feasibility spanning \
low/short to high/long); tournament = EVERY unordered pair of your ideas exactly once (round always 1, \
`pair_a` = the lexicographically smaller idea_id, winner one of the pair); evolved = 0-2 ideas \
(EV-1, EV-2) whose parent_ids are your own idea ids — emit [] if no evolution genuinely strengthens.

Rigor bar (max-quality): every `falsifiable_prediction` MUST name a concrete metric + a numeric \
threshold + the dataset/condition it is measured on; state what result would FALSIFY the hypothesis. \
Each idea must be a real experiment someone could run next quarter, not a research programme; set its \
feasibility triple honestly (the single biggest cost should dominate the rating).
After writing, verify valid JSON. Return one line: counts + the tournament winner + the most feasible idea."""

COLLISION_WORKER_PROMPT = """You are the NOVELTY-COLLISION CHECKER — an INDEPENDENT prior-art auditor, \
NOT the author of these ideas (you are the prosecutor, not the athlete judging itself). The IDEATE \
worker proposed candidate ideas; your ONLY job is to find out, for EACH idea, whether someone has \
ALREADY ACTUALLY DONE it. Read:
  - `{run_dir}/inbox/IDEATE.bundle.json`  — check EVERY idea in BOTH `ideas` and `evolved`.
  - `{run_dir}/inbox/search-results.json` IF it exists — the sanctioned live-retrieval bundle.

{north_star}

For EACH idea (originals AND evolved):
 1. DECOMPOSE it into (method_combination × application/problem × domain).
 2. Build TARGETED queries around the METHOD + PROBLEM (not the idea's wording); search the real \
literature (use the search bundle + your retrieval tools). Hunt hardest for the exact COMBINATION on \
the same problem.
 3. For each near-hit, judge HONESTLY: does this SPECIFIC paper do the SAME method-combination on the \
SAME problem? did it actually RUN experiments / implement it (not merely propose)?
 4. Assign a verdict:
      "collision" = a SPECIFIC real paper does the same method × same problem AND ran it -> name it.
      "adjacent"  = the combination exists but on a DIFFERENT application/problem, OR was proposed but \
NOT experimentally validated here (this is publishable WHITE SPACE — say so).
      "clear"     = targeted retrieval surfaced no collision ('none found within coverage', NOT \
'proven novel').

HARD HONESTY (a FALSE collision KILLS a good idea — the expensive error):
  - NEVER claim "collision" without a SPECIFIC real paper you can cite (arXiv:/doi:/exact title).
  - NEVER fabricate a paper, DOI, arXiv id, or quote (a downstream existence gate checks every ref; a \
fabricated/unconfirmable colliding paper is discarded and CANNOT cut).
  - If unsure -> "adjacent" or "clear", NEVER "collision".
  - Emit exactly ONE finding per input idea_id; you do NOT drop, rank, or select ideas.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "findings": [
    {{"idea_id": "IDEA-1", "method_combination": "<the combined methods>",
      "application": "<the problem it is applied to>", "domain": "<the field>",
      "queries": ["<targeted query 1>", "<query 2>"], "verdict": "collision|adjacent|clear",
      "colliding_papers": [
        {{"ref": "arXiv:2407.01517", "title": "<paper title>",
          "does_same_method_on_same_problem": true, "experimentally_validated": true,
          "justification": "<1 line: why it is the same>", "quote": "<short supporting quote>"}}
      ],
      "confidence": "high|medium|low", "retrieval_note": "<coverage caveat — what you could not check>"}}
  ],
  "evidence_ref": ["inbox/COLLISION.bundle.json"]
}}
colliding_papers MUST be [] when verdict is "clear". Every finding needs idea_id, method_combination, \
application, domain, queries (>=1), verdict, colliding_papers, confidence. After writing, verify valid \
JSON. Return one line: counts of collision/adjacent/clear + the idea you are most confident is already done."""


# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def _worker_model(stage: str, model_policy: str) -> str:
    """max_quality (the director's default for governed research runs, 2026-06-09) -> all-opus.
    default -> task-appropriate: DISCOVER reading/extraction = sonnet, IDEATE ideation/judgment = opus."""
    if model_policy == "max_quality":
        return "opus"
    return "sonnet" if stage == "DISCOVER" else "opus"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit H5): grounds DISCOVER + novelty in real literature."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def discover_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                    model_policy: str = "max_quality") -> dict:
    """The base DISCOVER grounding worker (evidence_table / claim_list / claim_evidence_map / signals).
    Reused by deep_ideation too (so the two modes share ONE base-worker definition — no drift)."""
    out = f"{run_dir}/inbox/DISCOVER.bundle.json"
    return {"label": "discover-worker", "model": _worker_model("DISCOVER", model_policy), "output": out,
            "prompt": DISCOVER_WORKER_PROMPT.format(request=request, vault=vault, out=out,
                                                    run_dir=run_dir,
                                                    north_star=_shared.north_star_block(run_dir))}


def ideate_worker(run_dir: str, request: str, vault: str = DEFAULT_VAULT,
                  model_policy: str = "max_quality") -> dict:
    """The base IDEATE worker (hypotheses / ideas / tournament / evolved). Reused by deep_ideation too."""
    out = f"{run_dir}/inbox/IDEATE.bundle.json"
    return {"label": "ideate-worker", "model": _worker_model("IDEATE", model_policy), "output": out,
            "prompt": IDEATE_WORKER_PROMPT.format(request=request, run_dir=run_dir, out=out, vault=vault,
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
        return {"workers": [discover_worker(run_dir, request, vault, model_policy), *deep],
                "panel_note": "spawn IN ORDER: discover -> formalize -> mechanism -> contradiction "
                              "(each reads the prior inbox/*.bundle.json). Deep SINGLE-DOMAIN: no "
                              "cross-domain analogy (that breadth layer is deep_ideation)."}
    if stage == "IDEATE":
        return {"workers": [ideate_worker(run_dir, request, vault, model_policy),
                            collision_step(run_dir, vault=vault, model_policy=model_policy),
                            _deep_ideate.experiment_worker(run_dir, request, model_policy)],
                "panel_note": "spawn IN ORDER: ideate -> novelty-collision -> experiment-architect."}
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
            "prompt": COLLISION_WORKER_PROMPT.format(run_dir=run_dir, out=out, north_star=ns_block)}


def _collision_hard_block(run_dir) -> bool:
    """Cut policy for the novelty-collision gate: profile `novelty_collision.hard_block`, default True
    (director lock 2026-06-18 — an evidenced prior-art collision is REMOVED from the menu before
    /idea-bet). A profile may set it False to keep every idea (flag-only) while still labelling DEAD."""
    prof = _shared.domain_profile(run_dir) or {}
    block = prof.get("novelty_collision") or {}
    val = block.get("hard_block")
    return True if val is None else bool(val)


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


def _vault_slug_set():
    root = _shared.resolve_vault_root(DEFAULT_VAULT)
    return _shared.vault_slugs(root), root


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
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts,
                                           _shared.external_refs(et, cem))
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
    matches = []
    for idx, m in enumerate(matches_raw):
        a, bb, w = str(m.get("pair_a") or ""), str(m.get("pair_b") or ""), str(m.get("winner") or "")
        if not ({a, bb} <= idea_ids):
            raise GateBlock(f"tournament match {idx} names unknown idea id(s): {sorted({a, bb} - idea_ids)}")
        if a not in kept_ids or bb not in kept_ids:
            continue                                    # a merged duplicate's matches drop harmlessly
        matches.append({"round": int(m.get("round") or 1), "pair_a": a, "pair_b": bb, "winner": w,
                        "rationale_ref": str(m.get("rationale_ref") or f"{bundle_ref}#tournament[{idx}]")})
    if len(kept_ids) >= 2:
        expected = {tuple(sorted(p)) for p in
                    [(x, y) for x in kept_ids for y in kept_ids if x < y]}
        judged = {tuple(sorted((m["pair_a"], m["pair_b"]))) for m in matches}
        missing = sorted(expected - judged)
        if missing:
            raise GateBlock(
                f"tournament incomplete: unjudged idea pair(s) {missing} — the IDEATE worker must "
                "judge EVERY unordered pair of its (deduplicated) ideas exactly once")
        tournament = build_elo_tournament(matches, evidence_ref=[bundle_ref],
                                          fmt="round_robin", all_ids=sorted(kept_ids))
        paths.append(write_artifact(run_dir, "IDEATE", "idea-tournament.artifact.json",
                                    "elo_tournament", "idea-tournament-ranker", tournament, ts))

    if evolved:
        ev_payload = {"ideas": [{k: v for k, v in e.items() if k in
                                 ("idea_id", "summary", "parent_ids", "evidence_ref", "mutation_type")}
                                for e in evolved]}
        paths.append(write_artifact(run_dir, "IDEATE", "evolved-ideas.artifact.json",
                                    "evolved_ideas", "idea-evolver", ev_payload, ts))

    # The /idea-bet MENU: kept originals + evolved ideas, feasibility-ranked, with negative-result
    # caveats from the vault attached (audit C2) and grounding scored advisory (score-only).
    menu_ideas = [dict(i) for i in dd["kept"]]
    for e in evolved:
        menu_ideas.append({"idea_id": str(e.get("idea_id")), "summary": str(e.get("summary") or ""),
                           "evidence_ref": list(e.get("evidence_ref") or []),
                           "feasibility": dict(e.get("feasibility") or {})})
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
    # An EVIDENCED collision (a real, existence-verified paper that already did this method×problem AND
    # ran it) is CUT here + recorded to the known-prior-art ledger; only SURVIVORS reach the menu. A
    # novelty SCORE still never cuts (design §1). Offline -> nothing cut, all UNVERIFIED, flagged below.
    survivors, cverdict, cpath = _shared.run_collision_gate(
        run_dir, "IDEATE", ts, menu_ideas, hard_block=_collision_hard_block(run_dir))
    paths.append(cpath)

    backlog = build_idea_backlog(survivors, budget=_shared.budget(run_dir))   # ranked MENU (survivors only; no self-bet field)
    paths.append(write_artifact(run_dir, "IDEATE", "idea-backlog.artifact.json",
                                "idea_backlog", "feasibility-reranker", backlog, ts))
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
                   "slug_warnings": ri_warnings}


def _report(run_dir, ts) -> tuple:
    records = _shared.search_records(run_dir)
    note = {"summary": "new-direction menu: evidence-grounded ideas, tournament-judged, "
                       "prior-art-collision screened, and feasibility-ranked; awaiting /idea-bet "
                       "(the director bets — the machine never does)",
            "references": ["evidence/IDEATE/idea-backlog.artifact.json",
                           "evidence/IDEATE/idea-tournament.artifact.json",
                           "evidence/IDEATE/novelty-collision-verdict.artifact.json",
                           "evidence/DISCOVER/novelty-score.artifact.json"],
            "produced_artifacts": [], "open_questions": []}
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
    return (paths, {})


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
        paths, report = _ideate_dets(run_dir, ts, _load_bundle(run_dir, "IDEATE"))
        dpaths, frag = _deep_ideate.deep_ideate_producers(run_dir, ts, required=False)
        report.update(frag)
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
    """The ranked idea_backlog (the /idea-bet menu): feasibility rank + Elo evidence + caveats."""
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
        row = {"rank": i["rank"], "idea_id": i["idea_id"],
               "score": i["feasibility"]["score"], "summary": i["summary"],
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
