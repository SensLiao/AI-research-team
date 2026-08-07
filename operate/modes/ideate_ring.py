"""Operate recipe for the `ideate_ring` mode (IDEATE -> REPORT) — wave-2 (2026-08-04).

The M3-f "IDEATE-ring completion" mode: a FOCUSED, standalone five-seat ideation ring —
hypothesis-generator -> idea-tournament-ranker -> idea-evolver -> {feasibility-reranker,
novelty-collision-checker} -> a deterministic /idea-bet menu. Unlike `new_direction` /
`deep_ideation`, this mode's `entry_stage` is IDEATE, not DISCOVER: there is no gap-hunting
stage in THIS run, so the "grounded input" is not a `gap_classification`/`novelty_score`
artifact — it is the director's own opportunity-set text (`task_frame.payload.request_text`),
read verbatim by hypothesis-generator. That contract is one of the registry's own
`productization_gaps` ("define the required grounded input contract") and this module's
first design decision: hypothesis-generator's `evidence_ref` cites fragments of that text (or a
real `[[slug]]`/DOI it names), and is therefore NOT checked against this run's internal id
registry — only the RING-INTERNAL references (idea -> hypothesis, evolved -> idea) are, because
only those can be fabricated against ids this run actually minted.

Split of labour (five independent seats; deterministic cores never let a seat hand-set a
score, a rank, or a bet):
  - hypothesis-generator turns the opportunity set into falsifiable hypotheses (hypothesis_set).
  - idea-tournament-ranker turns each hypothesis into one candidate idea with a comparative
    score; the deterministic `tools.tournament_bracket.build_bracket` (round-robin, NOT a score
    mean — the registry's own gate_level comment) runs the real pairwise bracket. Pre-tournament
    dedup (`tools.idea_dedup`, AI-Researcher 0.8-similarity) runs first so near-duplicate
    phrasings do not flood the bracket; a duplicate's evolved-idea parent references are remapped
    to its surviving representative, never silently orphaned.
  - idea-evolver reads the ranker's own bundle (there is no committed tournament artifact yet at
    dispatch time — the whole panel runs before ANY deterministic producer) and evolves the
    strongest candidates; every evolved idea carries non-empty `parent_ids` (anti-slop).
  - feasibility-reranker and novelty-collision-checker run in the SAME wave, over the SAME
    candidate set (originals + evolved), and are structurally independent of each other and of
    the idea producers (director red line: the checker never audits its own output). The checker
    writes to the FIXED path `inbox/COLLISION.bundle.json` (not this mode's usual per-seat bundle
    naming) so it can reuse `_shared.run_collision_gate` byte-for-byte — the same
    evidence-not-score collision machinery `new_direction`/`deep_ideation` already carry, with the
    same four honest verdicts (DEAD/WHITE_SPACE/CLEAR/UNVERIFIED) and the same anti-false-cut
    safety (a cut requires an existence-verified, hash-bound, full-text-reviewed paper).
  - `idea_backlog` (the ranked, no-self-bet MENU) and `idea_lineage` (the mechanical
    candidate/evolved/cut/merged-duplicate provenance ledger) are assembled deterministically.

The director Markdown is rendered with `_panel_recipe.render_director_markdown` against this
mode's OWN registry-declared sections (`Input opportunity set` / `Falsifiable hypotheses` /
`Tournament results` / `Evolved ideas and lineage` / `Prior-art collisions` / `Director bet menu`).
`tools.idea_bet_markdown.write_idea_bet_menu` (the renderer `new_direction`/`deep_ideation` share)
was checked first and NOT reused: its fixed heading set (Decision Snapshot, Portfolio Execution
Map, ...) and its idea-investment-memo/v2 field contract belong to a heavier, experiment-planner-
bearing pipeline this mode does not run, and reusing it would violate the registry's own required
section names. Using the shared deterministic renderer with THIS mode's sections is the generalized
"deterministic Markdown compiler" the registry's gap asks for — not a second bespoke compiler.

No `pre_search`: `entry_stage` is IDEATE, so there is no DISCOVER-entry literature grounding step in
this mode. The novelty-collision-checker still reads `inbox/search-results.json` when a director (or
an earlier run in the same workspace) happened to leave one, but never requires it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ...tools.feasibility_score import build_idea_backlog
from ...tools.idea_dedup import dedupe_ideas
from ...tools.tournament_bracket import build_bracket

MODE = "ideate_ring"
STAGES = _panel_recipe.stage_path(MODE)          # ["IDEATE", "REPORT"] (registry-declared)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

# The novelty-collision-checker's bundle lives at this FIXED path (not the usual per-seat naming)
# so `_shared.run_collision_gate` / `_shared.collision_findings_bundle` — already battle-tested by
# new_direction/deep_ideation — can be reused verbatim instead of re-implementing existence
# verification, fulltext-snapshot verification, and prior-art-ledger cross-referencing here.
COLLISION_BUNDLE_REL = "inbox/COLLISION.bundle.json"

# label -> the bundle_key its worker bundle carries. Single source for both llm_step (dispatch,
# real prompts) and run_dets (loading via _panel_recipe.load_seat_bundles). The collision checker
# is deliberately excluded — it is loaded through `_shared.collision_findings_bundle` instead.
_PRODUCER_BUNDLE_KEYS = (
    ("hypothesis-generator", "hypothesis_set"),
    ("idea-tournament-ranker", "tournament_ideas"),
    ("idea-evolver", "evolved_ideas"),
    ("feasibility-reranker", "feasibility_ratings"),
)

# --------------------------------------------------------------------------- worker prompts (LLM WORK)

HYPOTHESIS_GENERATOR_PROMPT = """You are the hypothesis-generator seat of the ideate_ring mode: turn the \
director's own opportunity-set input into a set of falsifiable, evidence-linked research hypotheses.

    DIRECTOR'S OPPORTUNITY SET (the ONLY input this run has — read it as the gaps, observations, or \
open questions to hypothesize about):
    {request}

{north_star}

This run has NO upstream DISCOVER stage — there is no gap_classification or novelty_score artifact to \
read, and none exists to invent. Ground every hypothesis in a specific fragment of the opportunity-set \
text above; cite that fragment (or a real [[slug]] / DOI / arXiv id it names) in evidence_ref.

HONESTY (hard): never invent a gap, a citation, or a source not actually present in the opportunity-set \
text; if the text is too thin to support many hypotheses, say so in a hypothesis's notes rather than \
padding the list. Each falsifiable_prediction must name a metric, a numeric threshold, and the condition \
under which it would be observed — a vague aspiration is not falsifiable and the schema rejects it.

You do NOT rank, select, or flag a preferred hypothesis, and you do NOT evolve, mutate, or judge novelty \
— those are separate independent seats, dispatched after you.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "hypothesis_set": {{
    "hypotheses": [
      {{"hypothesis_id": "IH1", "statement": "<declarative claim>",
        "falsifiable_prediction": "<metric + numeric threshold + the condition it is measured under>",
        "evidence_needed": ["<experiment, dataset, or measurement needed to test it>"],
        "evidence_ref": ["<opportunity-set fragment, or a real [[slug]]/doi/arXiv id it names>"],
        "source_gap_ref": "<optional: an id you assigned the opportunity-set fragment, if you numbered them>",
        "notes": "<optional: uncertainty, or an honest note that the input was too thin for more>"}}
    ]
  }}
}}
Quantities are FLOORS with NO upper bound: emit every distinct, falsifiable hypothesis the opportunity \
set actually supports (>=6 when the input is rich enough) — never merge two distinct mechanisms into one \
hypothesis to keep the list short, and never invent filler past what the text honestly supports. After \
writing, verify valid JSON. Return one line: how many hypotheses you produced and from how many distinct \
opportunity-set fragments."""

RANKER_PROMPT = """You are the idea-tournament-ranker seat. You did NOT author the hypotheses. Read:
  - `{run_dir}/inbox/IDEATE.hypothesis-generator.bundle.json` (the frozen hypothesis_set)

{north_star}

Turn each hypothesis (or a small coherent cluster of related hypotheses) into ONE candidate idea, and \
give it a comparative "score" in [0,1] reflecting your own judgment of scientific leverage, \
falsifiability, and grounding RELATIVE TO the other candidates here. The deterministic tournament tool \
then runs a REAL round-robin bracket from your scores (every distinct pair plays exactly once; the \
higher score wins each pairing) — you never hand-set a winner, a rank, or a win count.

You do NOT evolve, mutate, or recombine ideas here (idea-evolver is a separate seat, dispatched after \
you), and you do NOT judge novelty or prior art (the novelty-collision-checker is independent of you).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "tournament_ideas": [
    {{"idea_id": "IDEA-1", "from_hypothesis_ref": "IH1",
      "summary": "<one-sentence concrete research idea realizing the hypothesis>",
      "score": 0.8, "score_rationale": "<why this score relative to the OTHER candidates>",
      "evidence_ref": ["IH1"]}}
  ]
}}
Emit one idea per hypothesis, or per coherent cluster (name every hypothesis_id it absorbs in \
evidence_ref) — a FLOOR, not a cap; do not drop a defensible hypothesis to keep the list short. Every \
idea_id must be unique and every from_hypothesis_ref/evidence_ref must name a real hypothesis_id from \
the bundle above. After writing, verify valid JSON. Return one line: how many ideas you produced and \
their score range."""

EVOLVER_PROMPT = """You are the idea-evolver seat. You did NOT author or rank the candidate ideas. Read:
  - `{run_dir}/inbox/IDEATE.idea-tournament-ranker.bundle.json` (every candidate idea and your \
comparative score signal — treat a higher score as stronger; there is no separate ranking file yet, the \
deterministic round-robin tournament runs only after this whole panel finishes)

{north_star}

Run an ISLAND generation instead of a shortlist. Partition the candidates into 3-4 islands by their \
dominant mechanism family (not by score), then evolve WITHIN each island — mutating (varying one design \
choice), recombining (merging the strongest aspects of two or more), or strengthening (adding a \
complementary mechanism, or removing a known weakness). Every island must contribute at least one \
evolved idea, including the currently weakest island: a low-scoring island is exactly where an \
unexplored mechanism family survives, and collapsing onto the top-2 is how a search converges early. \
When two ideas differ only in wording, keep the SHORTER one (Occam) and evolve the other into a \
genuinely different mechanism. The number of evolved ideas is a floor, never a cap.

Every evolved idea MUST carry a non-empty parent_ids naming the real idea_id(s) it was derived from — an \
evolved idea with no parents is schema-rejected (anti-slop: "where did this come from"). You do NOT add \
a selected/chosen/winner field, and you do NOT judge novelty or feasibility — separate independent seats \
own those.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "evolved_ideas": {{
    "ideas": [
      {{"idea_id": "EV-1", "summary": "<the evolved idea, one sentence>",
        "parent_ids": ["IDEA-1"], "mutation_type": "mutate",
        "evidence_ref": ["IDEA-1"]}}
    ]
  }}
}}
The schema requires at least one evolved idea — if truly nothing improves on the originals, still \
evolve the single strongest candidate with a "strengthen" pass that tightens its falsifiable prediction, \
rather than leaving the list empty. Beyond that floor there is no upper bound: emit every idea that is \
genuinely stronger than its parent(s). After writing, verify valid JSON. Return one line: how many \
evolved ideas you produced and which mutation types."""

FEASIBILITY_PROMPT = """You are the feasibility-reranker seat. You did NOT author, rank, or evolve these \
ideas. Read:
  - `{run_dir}/inbox/IDEATE.idea-tournament-ranker.bundle.json` (the original candidate ideas)
  - `{run_dir}/inbox/IDEATE.idea-evolver.bundle.json` (the evolved generation)

{north_star}

For EVERY idea_id in BOTH files — originals and evolved, none skipped — declare its feasibility \
signals: compute ("low"/"medium"/"high", or a numeric GPU-run estimate), data \
("available"/"restricted"/"unavailable"), time ("short"/"medium"/"long"). These are your evidence-backed \
judgment signals; a deterministic tool maps them to a numeric score and ranks every idea — you do NOT \
hand-set a score or a rank, and you do NOT add a selected/chosen/winner field (the director picks via \
/idea-bet, downstream of this whole ring).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "feasibility_ratings": [
    {{"idea_id": "IDEA-1",
      "feasibility": {{"compute": "medium", "data": "available", "time": "medium"}},
      "caveats": ["<optional known limitation or risk>"]}}
  ]
}}
Cover EVERY idea_id from both upstream files — a floor (every idea gets a rating), never a cap. After \
writing, verify valid JSON. Return one line: how many ideas you rated."""

COLLISION_PROMPT = """You are the novelty-collision-checker seat — a fully INDEPENDENT auditor. You did \
NOT propose, rank, or evolve any of these ideas; your only job is deciding what the closest real prior \
work actually established. Read:
  - `{run_dir}/inbox/IDEATE.idea-tournament-ranker.bundle.json` (original candidate ideas)
  - `{run_dir}/inbox/IDEATE.idea-evolver.bundle.json` (evolved ideas)
  - `{run_dir}/inbox/search-results.json` if it exists (optional; this mode runs no pre-search step)

{north_star}

For EVERY idea_id above — originals AND evolved, one finding each, none skipped — identify its central \
falsifiable contribution and the closest real prior work. Search results, titles, abstracts, shared \
keywords, and shared components are discovery leads only; they can narrow an overclaimed "first" but can \
never by themselves justify a collision.

Before emitting `collision`, obtain and read the full closest paper, including its method and the \
experiments bearing on the claim. Compare problem/target, input state, interaction, output/edit \
semantics, mechanism/training, causal controls, primary evaluation target, actual results, and scope. An \
`exact_collision` requires the same central claim, a materially equivalent input/output contract, and an \
equivalent causal assay, WITH experiments when the run requires experimental evidence.

Classify each closest paper as exact_collision / partial_component_prior / enabling_base / gap_source / \
orthogonal / uncertain. If only an abstract or snippet is available, set full_text_reviewed=false, \
relationship=uncertain, and the per-idea verdict=unverified — never a fatal collision, never a false \
clearance. For every exact_collision, preserve the exact full-text file you read INSIDE this run and \
record its run-local path plus SHA-256 — without a hash-verified snapshot the deterministic gate keeps \
the idea UNVERIFIED regardless of your verdict.

Do not fabricate a paper, identifier, locator, result, or quote. You do not rank, select, or drop ideas \
— that is the deterministic gate's job, and ultimately the director's via /idea-bet.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle. Never argue with the gate and never relax the honesty rules above.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "findings": [{{
    "idea_id": "IDEA-1", "method_combination": "<candidate mechanism, not its marketing label>",
    "application": "<concrete problem/target>", "domain": "<field>",
    "queries": ["<targeted query actually used>"],
    "verdict": "collision|adjacent|clear|unverified",
    "colliding_papers": [{{
      "ref": "<real resolvable reference: arXiv:... | doi:... | a near-exact title>", "title": "<title>",
      "does_same_method_on_same_problem": true, "experimentally_validated": true,
      "full_text_reviewed": true, "fulltext_snapshot_ref": "inbox/fulltext-docs/closest-paper.pdf",
      "fulltext_snapshot_sha256": "<64 lowercase hex characters>",
      "relationship": "exact_collision|partial_component_prior|enabling_base|gap_source|orthogonal|uncertain",
      "same_central_claim": true, "same_input_output_contract": true, "same_causal_evaluation": true,
      "evidence_loci": ["p.4 Method"], "method_evidence_loci": ["p.4 Method"],
      "result_evidence_loci": ["p.7 Table 2"], "material_surviving_delta": false,
      "surviving_gap": "<what remains unestablished>",
      "justification": "<what it did, did not do, and why this relation follows>"}}],
    "confidence": "high|medium|low", "retrieval_status": "complete|partial|unavailable",
    "retrieval_note": "<coverage, full-text availability, and unresolved limits>"
  }}],
  "evidence_ref": ["inbox/COLLISION.bundle.json"]
}}
One finding per idea_id, covering every original and evolved idea — a floor, not a cap. \
`colliding_papers` MUST be empty when verdict is 'clear'. After writing, verify valid JSON. Return one \
line: how many ideas you checked and the verdict breakdown."""


def _worker_model(model_policy: str, tier: str) -> str:
    return _panel_recipe.worker_model(model_policy, tier)


def _loading_seats() -> list:
    """label + bundle_key pairs (no real prompt needed) for `_panel_recipe.load_seat_bundles`."""
    return [_panel_recipe.Seat(label=label, prompt="", bundle_key=key)
            for label, key in _PRODUCER_BUNDLE_KEYS]


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The five-seat IDEATE panel (four waves) — or None; REPORT is deterministic."""
    if stage != "IDEATE":
        return None
    ns = _shared.north_star_block(run_dir)

    def out(label: str) -> str:
        return _panel_recipe.bundle_path(run_dir, "IDEATE", label)

    collision_out = f"{run_dir}/{COLLISION_BUNDLE_REL}"
    seats = [
        _panel_recipe.Seat(
            label="hypothesis-generator", bundle_key="hypothesis_set", tier="audit",
            prompt=HYPOTHESIS_GENERATOR_PROMPT.format(
                request=request, north_star=ns, out=out("hypothesis-generator"))),
        _panel_recipe.Seat(
            # Ranking ideas IS ideation, not bookkeeping — the order it emits decides which idea
            # the director sees first, so it stays on the frontier tier with its siblings.
            label="idea-tournament-ranker", bundle_key="tournament_ideas", tier="design",
            depends_on=("hypothesis-generator",),
            prompt=RANKER_PROMPT.format(run_dir=run_dir, north_star=ns,
                                        out=out("idea-tournament-ranker"))),
        _panel_recipe.Seat(
            label="idea-evolver", bundle_key="evolved_ideas", tier="audit",
            depends_on=("idea-tournament-ranker",),
            prompt=EVOLVER_PROMPT.format(run_dir=run_dir, north_star=ns,
                                         out=out("idea-evolver"))),
        _panel_recipe.Seat(
            label="feasibility-reranker", bundle_key="feasibility_ratings", tier="audit",
            depends_on=("idea-evolver",),
            prompt=FEASIBILITY_PROMPT.format(run_dir=run_dir, north_star=ns,
                                             out=out("feasibility-reranker"))),
        _panel_recipe.Seat(
            label="novelty-collision-checker", bundle_key="collision_findings", tier="audit",
            depends_on=("idea-evolver",),
            prompt=COLLISION_PROMPT.format(run_dir=run_dir, north_star=ns, out=collision_out)),
    ]
    result = _panel_recipe.panel(
        run_dir, "IDEATE", MODE, seats, model_policy=model_policy,
        panel_note="Wave 1 hypothesis-generator. Wave 2 idea-tournament-ranker (dedup + real "
                   "pairwise bracket happen deterministically after the whole panel returns). "
                   "Wave 3 idea-evolver. Wave 4 (parallel, independent of each other): "
                   "feasibility-reranker + novelty-collision-checker.")
    # The checker writes to the FIXED inbox/COLLISION.bundle.json path (see module docstring) so
    # _shared.run_collision_gate can be reused verbatim; every other seat keeps the standard
    # per-seat bundle_path the rest of this recipe (and load_seat_bundles) expects.
    for worker in result["workers"]:
        if worker["label"] == "novelty-collision-checker":
            worker["output"] = collision_out
    return result


# --------------------------------------------------------------------------- small local helpers

def _write_or_block(run_dir, stage: str, filename: str, artifact_type: str, created_by: str,
                    payload: dict, ts: str) -> str:
    """write_artifact, with a schema failure turned into a repairable, targeted gate."""
    try:
        return write_artifact(run_dir, stage, filename, artifact_type, created_by, payload, ts)
    except ValueError as exc:
        raise TargetedGateBlock(
            f"{artifact_type} needs a local supplement: {exc}",
            [{"defect_id": f"ideate-ring-{artifact_type.replace('_', '-')}", "location": filename,
              "summary": str(exc), "target_agents": [created_by], "refresh_agents": []},
             ]) from exc


def _collision_hard_block(run_dir) -> bool:
    """Director default True (an evidenced DEAD collision is cut); profile-tunable to flag-only."""
    prof = _shared.domain_profile(run_dir) or {}
    block = prof.get("novelty_collision") or {}
    val = block.get("hard_block")
    return True if val is None else bool(val)


# --------------------------------------------------------------------------- deterministic producers

def _ideate_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "IDEATE", MODE, _loading_seats())

    hyps = [h for h in (bundles["hypothesis_set"].get("hypotheses") or []) if isinstance(h, dict)]
    if not hyps:
        raise TargetedGateBlock(
            "hypothesis_set has no hypotheses",
            [{"defect_id": "ideate-ring-hypothesis-set-empty", "location": "IDEATE.hypothesis-generator",
              "summary": "hypothesis-generator must emit at least one hypothesis",
              "target_agents": ["hypothesis-generator"], "refresh_agents": []}])
    hyp_ids_list = [str(h.get("hypothesis_id")) for h in hyps if h.get("hypothesis_id")]
    if len(set(hyp_ids_list)) != len(hyp_ids_list):
        dupes = sorted({x for x in hyp_ids_list if hyp_ids_list.count(x) > 1})
        raise TargetedGateBlock(
            f"duplicate hypothesis_id: {dupes}",
            [{"defect_id": "ideate-ring-hypothesis-id-dup", "location": "IDEATE.hypothesis-generator",
              "summary": f"duplicate hypothesis_id(s) {dupes} — every id must be unique",
              "target_agents": ["hypothesis-generator"], "refresh_agents": []}])
    hyp_ids = set(hyp_ids_list)

    tournament_ideas_raw = [i for i in (bundles["tournament_ideas"] or []) if isinstance(i, dict)]
    if not tournament_ideas_raw:
        raise TargetedGateBlock(
            "idea-tournament-ranker produced no candidate ideas",
            [{"defect_id": "ideate-ring-tournament-ideas-empty",
              "location": "IDEATE.idea-tournament-ranker",
              "summary": "idea-tournament-ranker must turn every hypothesis into >=1 candidate idea",
              "target_agents": ["idea-tournament-ranker"], "refresh_agents": []}])

    evolved = [e for e in (bundles["evolved_ideas"].get("ideas") or []) if isinstance(e, dict)]
    if not evolved:
        raise TargetedGateBlock(
            "idea-evolver produced no evolved ideas",
            [{"defect_id": "ideate-ring-evolved-ideas-empty", "location": "IDEATE.idea-evolver",
              "summary": "idea-evolver must emit at least one evolved idea (schema minItems:1)",
              "target_agents": ["idea-evolver"], "refresh_agents": []}])

    feasibility_rows = [r for r in (bundles["feasibility_ratings"] or []) if isinstance(r, dict)]

    idea_ids_raw = {str(i.get("idea_id")) for i in tournament_ideas_raw if i.get("idea_id")}
    evolved_ids = {str(e.get("idea_id")) for e in evolved if e.get("idea_id")}
    known_ids = hyp_ids | idea_ids_raw | evolved_ids

    # RING-INTERNAL references only (idea -> hypothesis, evolved -> idea). hypothesis-generator's
    # OWN evidence_ref intentionally points OUTSIDE the ring, at the director's freeform opportunity
    # set — see module docstring — so it is validated only by the hypothesis_set schema itself.
    downstream_refs = []
    for idea in tournament_ideas_raw:
        downstream_refs += [str(r) for r in (idea.get("evidence_ref") or [])]
        if idea.get("from_hypothesis_ref"):
            downstream_refs.append(str(idea["from_hypothesis_ref"]))
    for e in evolved:
        downstream_refs += [str(r) for r in (e.get("evidence_ref") or [])]
        downstream_refs += [str(r) for r in (e.get("parent_ids") or [])]

    collision_raw = _shared.collision_findings_bundle(run_dir) or {}
    gate_bundles = {**bundles, "collision_findings": collision_raw}
    paths, frag = _panel_recipe.common_gates(
        run_dir, "IDEATE", ts, mode=MODE, bundles=gate_bundles,
        downstream_refs=downstream_refs, known_ids=known_ids, vault=DEFAULT_VAULT)

    # 1. hypothesis-generator -> hypothesis_set (frozen artifact #1)
    paths.append(_write_or_block(run_dir, "IDEATE", "hypothesis-set.artifact.json", "hypothesis_set",
                                 "hypothesis-generator", {"hypotheses": hyps}, ts))
    hyp_ref = "evidence/IDEATE/hypothesis-set.artifact.json"

    # 2. idea-tournament-ranker -> dedup (AI-Researcher 0.8-similarity) then the REAL round-robin
    #    bracket (idea_tournament, frozen artifact #2; pairwise, never a score mean).
    try:
        deduped = dedupe_ideas(tournament_ideas_raw)
    except ValueError as exc:
        raise TargetedGateBlock(
            f"idea dedup needs a supplement: {exc}",
            [{"defect_id": "ideate-ring-dedup", "location": "IDEATE.idea-tournament-ranker",
              "summary": str(exc), "target_agents": ["idea-tournament-ranker"], "refresh_agents": []}]
        ) from exc
    kept = deduped["kept"]
    try:
        tournament_payload = build_bracket(kept, score_key="score", evidence_ref=[hyp_ref])
    except ValueError as exc:
        raise TargetedGateBlock(
            f"idea_tournament needs a supplement: {exc}",
            [{"defect_id": "ideate-ring-tournament", "location": "IDEATE.idea-tournament-ranker",
              "summary": str(exc), "target_agents": ["idea-tournament-ranker"], "refresh_agents": []}]
        ) from exc
    paths.append(_write_or_block(run_dir, "IDEATE", "idea-tournament.artifact.json", "idea_tournament",
                                 "idea-tournament-ranker", tournament_payload, ts))
    tournament_ref = "evidence/IDEATE/idea-tournament.artifact.json"

    # Remap any evolved parent_id that dedup folded away to its surviving representative — "no idea
    # silently vanishes" (idea_dedup's own guarantee) extends to the evolved generation's lineage.
    remap = {mid: row["kept_id"] for row in deduped["merged"] for mid in row["merged_ids"]}
    kept_ids = {str(i["idea_id"]) for i in kept}
    for e in evolved:
        e["parent_ids"] = [remap.get(str(p), str(p)) for p in (e.get("parent_ids") or [])]
        bad_parents = [p for p in e["parent_ids"] if p not in kept_ids]
        if bad_parents:
            raise TargetedGateBlock(
                f"evolved idea {e.get('idea_id')!r} has parent_ids {bad_parents} outside this run's "
                "surviving ideas",
                [{"defect_id": "ideate-ring-evolved-parent-ids", "location": "IDEATE.idea-evolver",
                  "summary": f"parent_ids must name real, surviving idea_id(s): {bad_parents}",
                  "target_agents": ["idea-evolver"], "refresh_agents": []}])

    # 3. idea-evolver -> evolved_ideas (frozen artifact #3)
    paths.append(_write_or_block(run_dir, "IDEATE", "evolved-ideas.artifact.json", "evolved_ideas",
                                 "idea-evolver", {"ideas": evolved}, ts))

    # 4. feasibility-reranker merges its ratings onto the FULL candidate set (originals + evolved,
    #    one shared idea_id namespace) -> idea_backlog (the ranked MENU; frozen artifact #4).
    feas_by_id = {str(r.get("idea_id")): r.get("feasibility") or {}
                  for r in feasibility_rows if r.get("idea_id")}
    menu_ideas = []
    for idea in kept:
        iid = str(idea["idea_id"])
        refs = [str(r) for r in (idea.get("evidence_ref") or []) if str(r).strip()]
        menu_ideas.append({
            "idea_id": iid, "summary": str(idea.get("summary") or ""),
            "evidence_ref": refs or [str(idea.get("from_hypothesis_ref") or hyp_ref)],
            "feasibility": feas_by_id.get(iid) or {},
        })
    for e in evolved:
        iid = str(e["idea_id"])
        refs = [str(r) for r in (e.get("evidence_ref") or []) if str(r).strip()]
        menu_ideas.append({
            "idea_id": iid, "summary": str(e.get("summary") or ""),
            "evidence_ref": refs or [str(p) for p in (e.get("parent_ids") or [])],
            "feasibility": feas_by_id.get(iid) or {},
        })
    missing_feas = sorted(m["idea_id"] for m in menu_ideas if not m["feasibility"])
    if missing_feas:
        raise TargetedGateBlock(
            f"feasibility-reranker did not rate idea(s) {missing_feas}",
            [{"defect_id": "ideate-ring-feasibility-coverage", "location": "IDEATE.feasibility-reranker",
              "summary": f"every original and evolved idea needs a feasibility rating; missing "
                         f"{missing_feas}",
              "target_agents": ["feasibility-reranker"], "refresh_agents": []}])

    backlog = build_idea_backlog(menu_ideas, budget=_shared.budget(run_dir))
    paths.append(_write_or_block(run_dir, "IDEATE", "idea-backlog.artifact.json", "idea_backlog",
                                 "feasibility-reranker", backlog, ts))

    # 5. novelty-collision-checker -> novelty_collision_report (frozen artifact #5). Shared machinery:
    #    an EVIDENCED collision cuts; a novelty score never does; offline/unconfirmable -> UNVERIFIED,
    #    never a silent cut, never hidden from the director.
    survivors, cverdict, cpath = _shared.run_collision_gate(
        run_dir, "IDEATE", ts, menu_ideas, hard_block=_collision_hard_block(run_dir))
    paths.append(cpath)

    # 6. idea_lineage (frozen artifact #6) — the mechanical provenance ledger; disposition is never a bet.
    cut_ids = set(cverdict.get("cut_ids") or [])
    hyp_by_idea = {str(i["idea_id"]): str(i.get("from_hypothesis_ref") or "") for i in kept}
    lineage_rows = []
    for idea in kept:
        iid = str(idea["idea_id"])
        refs = [str(r) for r in (idea.get("evidence_ref") or []) if str(r).strip()] or [tournament_ref]
        row = {"idea_id": iid, "evidence_ref": refs,
               "disposition": "cut_prior_art" if iid in cut_ids else "candidate"}
        if hyp_by_idea.get(iid):
            row["hypothesis_ref"] = hyp_by_idea[iid]
        lineage_rows.append(row)
    for e in evolved:
        iid = str(e["idea_id"])
        parent_ids = [str(p) for p in (e.get("parent_ids") or [])]
        refs = [str(r) for r in (e.get("evidence_ref") or []) if str(r).strip()] or parent_ids
        lineage_rows.append({
            "idea_id": iid, "evidence_ref": refs, "parent_ids": parent_ids,
            "disposition": "cut_prior_art" if iid in cut_ids else "evolved",
        })
    for merged_row in deduped["merged"]:
        for mid in merged_row["merged_ids"]:
            lineage_rows.append({
                "idea_id": str(mid), "evidence_ref": [tournament_ref], "disposition": "merged_duplicate",
                "notes": f"merged into {merged_row['kept_id']} (similarity "
                         f"{merged_row['max_similarity']})",
            })
    paths.append(_write_or_block(run_dir, "IDEATE", "idea-lineage.artifact.json", "idea_lineage",
                                 "idea-evolver", {"lineages": lineage_rows}, ts))

    report = {
        "hypotheses": len(hyps), "tournament_ideas": len(tournament_ideas_raw),
        "dedup_merged": len(deduped["merged"]), "tournament_matchups": len(tournament_payload["matchups"]),
        "evolved": len(evolved), "ranked_ideas": len(backlog["ranked_ideas"]),
        "collision_retrieval_grounded": cverdict["retrieval_grounded"],
        "collision_cut": len(cverdict["cut_ids"]), "collision_survivors": len(survivors),
    }
    report.update(frag)
    return paths, report


def _read_payload(run_dir, stage: str, filename: str) -> dict:
    p = Path(run_dir) / "evidence" / stage / filename
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("payload") or {}
    except (OSError, ValueError):
        return {}


def _fmt_list(values, empty: str) -> str:
    vals = [str(v).strip() for v in (values or []) if str(v).strip()]
    return ", ".join(f"`{v}`" for v in vals) if vals else empty


def _opportunity_set_section(run_dir) -> str:
    tf = _shared.task_frame(run_dir)["payload"]
    ns = _shared.north_star(run_dir)
    request = str(tf.get("request_text") or "").strip() or "(no request text recorded)"
    return (f"{request}\n\n> North star: {ns['statement']}\n"
            "> This run has no upstream DISCOVER stage — the text above, verbatim, is the only "
            "grounded input hypothesis-generator read.")


def _hypotheses_section(run_dir) -> str:
    hs = _read_payload(run_dir, "IDEATE", "hypothesis-set.artifact.json")
    hyps = hs.get("hypotheses") or []
    if not hyps:
        return "None — hypothesis-generator produced no hypotheses this run."
    lines = []
    for h in hyps:
        lines.append(
            f"- **{h.get('hypothesis_id')}**: {h.get('statement')}\n"
            f"  - Falsifiable prediction: {h.get('falsifiable_prediction')}\n"
            f"  - Evidence needed: {_fmt_list(h.get('evidence_needed'), 'none recorded')}\n"
            f"  - Evidence ref: {_fmt_list(h.get('evidence_ref'), 'none recorded')}")
    return "\n".join(lines)


def _tournament_section(run_dir) -> str:
    t = _read_payload(run_dir, "IDEATE", "idea-tournament.artifact.json")
    matchups = t.get("matchups") or []
    ranking = t.get("ranking") or []
    if not ranking:
        return "None — the tournament produced no ranking this run."
    lines = [f"Round-robin pairwise bracket: {len(matchups)} matchup(s) over {len(ranking)} idea(s) "
             "(never a score mean — every distinct pair played exactly once)."]
    for row in sorted(ranking, key=lambda r: r.get("rank", 0)):
        lines.append(f"- rank {row.get('rank')}: `{row.get('idea_id')}` ({row.get('wins')} win(s))")
    return "\n".join(lines)


def _evolved_and_lineage_section(run_dir) -> str:
    ev = _read_payload(run_dir, "IDEATE", "evolved-ideas.artifact.json")
    ideas = ev.get("ideas") or []
    lin = _read_payload(run_dir, "IDEATE", "idea-lineage.artifact.json")
    lin_by_id = {str(row.get("idea_id")): row for row in (lin.get("lineages") or [])
                if isinstance(row, dict)}
    if not ideas:
        return "None — idea-evolver produced no evolved ideas this run."
    lines = []
    for idea in ideas:
        iid = str(idea.get("idea_id"))
        disp = (lin_by_id.get(iid) or {}).get("disposition", "evolved")
        lines.append(
            f"- **{iid}** ({idea.get('mutation_type', 'evolved')}, disposition: `{disp}`): "
            f"{idea.get('summary')}\n"
            f"  - Parents: {_fmt_list(idea.get('parent_ids'), 'none recorded')}")
    merged = [row for row in (lin.get("lineages") or [])
             if isinstance(row, dict) and row.get("disposition") == "merged_duplicate"]
    if merged:
        lines.append("")
        lines.append("Pre-tournament dedup folded these near-duplicates (no idea silently vanished):")
        for row in merged:
            lines.append(f"- `{row.get('idea_id')}`: {row.get('notes')}")
    return "\n".join(lines)


def _collisions_section(run_dir) -> str:
    cv = _read_payload(run_dir, "IDEATE", "novelty-collision-verdict.artifact.json")
    ideas = cv.get("ideas") or []
    if not ideas:
        return "None — the novelty-collision gate produced no verdicts this run."
    lines = [f"Retrieval grounded this run: `{cv.get('retrieval_grounded')}`" +
             ("" if cv.get("retrieval_grounded") else
              " — novelty was NOT verified; treat every CLEAR/WHITE_SPACE below as provisional.")]
    for row in ideas:
        cut_flag = " — CUT from the menu" if row.get("cut") else ""
        lines.append(f"- `{row.get('idea_id')}`: **{row.get('verdict')}**{cut_flag}. {row.get('reason')}")
    return "\n".join(lines)


def _director_menu_section(run_dir) -> str:
    bl = _read_payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    ranked = bl.get("ranked_ideas") or []
    if not ranked:
        return "None — the ranked menu is empty this run."
    lines = ["The model never self-bets: pick exactly one `idea_id` via `/idea-bet`, or choose PIVOT "
             "(none of these — re-scope). This ranking is a feasibility ordering, not a recommendation."]
    for idea in ranked:
        feas = idea.get("feasibility") or {}
        lines.append(
            f"- rank {idea.get('rank')}: **{idea.get('idea_id')}** (feasibility {feas.get('score')}): "
            f"{idea.get('summary')}\n"
            f"  - Caveats: {_fmt_list(idea.get('caveats'), 'none recorded')}")
    return "\n".join(lines)


def _report(run_dir, ts) -> tuple:
    backlog = _read_payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    collision = _read_payload(run_dir, "IDEATE", "novelty-collision-verdict.artifact.json")
    note = {
        "summary": "ideate_ring: the 5-seat IDEATE ring (hypothesis-generator -> idea-tournament-ranker "
                   "-> idea-evolver -> feasibility-reranker + independent novelty-collision-checker) "
                   "rendered a ranked, no-self-bet director menu; /idea-bet is the next human action",
        "references": ["director-review/ideas/idea-bet-menu.md",
                       "evidence/IDEATE/idea-backlog.artifact.json",
                       "evidence/IDEATE/idea-tournament.artifact.json",
                       "evidence/IDEATE/novelty-collision-verdict.artifact.json",
                       "evidence/IDEATE/idea-lineage.artifact.json"],
        "produced_artifacts": [], "open_questions": [],
    }
    if not backlog.get("ranked_ideas"):
        note["open_questions"].append("idea-backlog has no ranked ideas — inspect the IDEATE stage "
                                      "before proceeding to /idea-bet")
    if collision and not collision.get("retrieval_grounded"):
        note["open_questions"].append(
            "novelty was NOT verified this run (collision retrieval not grounded) — every idea's "
            "novelty status is UNVERIFIED; re-run the collision worker with real retrieval before "
            "betting")
    if collision and collision.get("cut_ids"):
        note["open_questions"].append(
            f"{len(collision['cut_ids'])} idea(s) cut for evidenced prior-art collision — see the "
            "Markdown menu's Prior-art collisions section; the director may still override")
    paths = [write_artifact(run_dir, "REPORT", "report-note.artifact.json", "report_note",
                            "research-orchestrator", note, ts)]

    sections = {
        "Input opportunity set": _opportunity_set_section(run_dir),
        "Falsifiable hypotheses": _hypotheses_section(run_dir),
        "Tournament results": _tournament_section(run_dir),
        "Evolved ideas and lineage": _evolved_and_lineage_section(run_dir),
        "Prior-art collisions": _collisions_section(run_dir),
        "Director bet menu": _director_menu_section(run_dir),
    }
    rel = _panel_recipe.render_director_markdown(run_dir, MODE, sections, ts=ts,
                                                 lead="hypothesis-generator")
    return paths, {"director_idea_bet_menu": rel}


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "IDEATE":
        return _ideate_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"ideate_ring has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
