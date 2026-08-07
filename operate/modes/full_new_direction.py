"""Operate recipe for the `full_new_direction` mode (DISCOVER -> REPORT) — wave 2.

Registry gap being closed (`product_maturity.productization_gaps`):
  - "Add an operated recipe with a frozen shared source set and both grounding gates."
  - "Define the product boundary and handoff relative to new_direction and /idea-bet."
  - "Add deterministic Markdown coverage and operate-level director packet tests."

full_new_direction is deliberately SMALLER than `new_direction`: it stops at DISCOVER and never
proposes, ranks, or bets on an idea. Its product is a grounded LANDSCAPE -- literature evidence,
model/dataset opportunities, and classified gaps -- passed through the same two hard gates
`new_direction` uses, then handed to the director as a Markdown brief. It never runs IDEATE, so it
never produces an `idea_backlog` and never touches `/idea-bet` directly; see `_RECOMMENDED_HANDOFF`
for the exact product-boundary text this recipe is required to render.

Split of labour (five `agent_subset` seats; only TWO are LLM-dispatched):

  - `gather_landscape` (LLM, ONE wave, a genuinely FROZEN shared source set): lit-scout mines the
    real vault + live retrieval for a literature evidence base; model-dataset-scout then reads
    lit-scout's OWN frozen bundle (`depends_on=("lit-scout",)`) before shortlisting model/dataset
    candidates, so both scouts build on ONE shared literature-gathering pass -- nothing downstream
    ever re-queries or re-gathers sources.
  - `independent_grounding_gates` (deterministic, never LLM-dispatched -- exactly like every other
    operated mode in this codebase): evidence-verifier (`evidence_checker.build_verdict`) and
    citation-integrity-auditor (`citation_checker.build_report`) are the registry's two named hard
    gates over lit-scout's frozen evidence_table / claim_list / claim_evidence_map.
  - `classify_directions` (deterministic): gap-classifier (`classify_gap.build_classification`)
    turns lit-scout's raw gap signals into the typed 7-class gap taxonomy -- the "candidate
    direction theses". A deterministic `landscape_map` then fuses the literature base, the
    classified gaps, and the dataset shortlist into one structured artifact backing the "Problem
    landscape" section (no LLM authors it -- landscape-mapper is not in this mode's `agent_subset`).
  - `render_markdown` (deterministic, never a dispatched worker -- the `_panel_recipe` design
    note applies here too): `_panel_recipe.render_director_markdown` renders the registry's six
    required sections; a hallucination-capable `synthesis-writer` is never spawned.

Every stage carries the three wave-2 common hard gates (`_panel_recipe.common_gates`): north-star
drift, live citation existence, and vault/id referential integrity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, write_artifact
from ...tools import project_memory
from ...tools.citation_checker import build_report
from ...tools.classify_gap import build_classification
from ...tools.evidence_checker import build_verdict
from ...tools.evidence_scout import build_evidence_table
from ...tools.model_dataset_scout import build_candidates

MODE = "full_new_direction"
STAGES = _panel_recipe.stage_path(MODE)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

_HONESTY = """HONESTY (hard): never invent a slug, DOI, paper, model, dataset, or number -- ground \
every claim, gap signal, and candidate in something you actually read. Grade `claim_support` and \
`supports_claim` from the ACTUAL evidence, never from what would be convenient to report. A thin \
literature base or a short shortlist is reported as thin -- never padded to look complete.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, re-emit the COMPLETE bundle, and never argue with the gate or relax these requirements."""


# --------------------------------------------------------------------------- worker prompts (hand-written)

LIT_SCOUT_PROMPT = """You are lit-scout of the full_new_direction mode: gather_landscape wave, seat \
1 of 2. This run stops at DISCOVER -- it hands the director a grounded SHORTLIST of directions, \
never an idea menu, and it never bets. Freeze the ONE literature source set the rest of this run \
builds on: model-dataset-scout reads YOUR bundle next, and nothing downstream re-gathers sources.

    REQUEST: {request}

{north_star}

Sources you read (by reference, never inlined):
  1. The real vault at `{vault}/02-wiki/papers/` -- glob the pages most relevant to the request and \
read ~12-20 of them fully. Each page has YAML frontmatter (key-claims, year, venue) + body \
(limitations, future-work).
  2. IF `{run_dir}/inbox/search-results.json` exists: the sanctioned live-retrieval bundle -- use \
its records as extra sources (`doi:`/`arXiv:` refs allowed for those rows) and to check whether a \
gap is already closed outside the vault.
  3. If that bundle is empty/off-topic or misses a named method, use agent Web Search for paper \
originals, official publisher/project pages, or authors' official repositories only; snippets are \
leads, never evidence.

HONESTY (hard, mode-specific on top of the shared rule below): reference vault pages ONLY by their \
real `[[slug]]` (page filename, no `.md`) -- a deterministic gate checks every slug against the \
vault and BLOCKs a fabrication. Ground every claim and gap signal in a real page or a real \
live-retrieval record; in `reported_result` paraphrase the ACTUAL finding, never invent one.
{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "evidence_table": {{"query": "<the landscape query you actually searched>",
     "sources": [{{"id":"s1","kind":"paper","ref":"[[<slug>]]","title":"<title>","year":2024,
                   "claim_support":"strong"}}, ...],
     "saturation_reached": true}},
  "claim_list": {{"source_scope": "<scope>",
     "claims": [{{"claim_id":"c1","text":"<decision-relevant atomic claim>",
                  "source_ref":"[[<slug>]]"}}]}},
  "claim_evidence_map": {{"mappings": [{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true}}]}}]}},
  "signals": [{{"gap_id":"GAP-1","statement":"<stated future-work/limitation, when this is the type>",
     "source_ref":"[[<slug>]]","evidence_ref":["[[<slug>]]"],"derived_from":["future_work"]}}]
}}
Quantities are FLOORS with NO upper bound -- a shortlist product still wants real volume: \
evidence_table.sources >=15 (>=4 rated "strong"); claims >=8, each anchored by a mapping whose every \
locus sets `supports_claim` explicitly; signals >=10 with varied gap types (transfer_gap needs \
source_domain+target_hook; assumption_gap needs challenged_assumption; methodological_gap needs \
locus+opportunity; coverage_gap needs hole or white_space_present; evidence_gap needs \
under_evidenced; empirical_gap needs untested_condition or untested_dataset; stated_open_problem \
needs statement+source_ref). Never drop a defensible signal to keep the list short -- a short list \
is only correct when the corpus genuinely cannot support more, and then say so in your one-line return.

{enablers_and_reframings}
After writing, verify it is valid JSON. Return one line: pages read + counts + the strongest signal."""

MODEL_DATASET_SCOUT_PROMPT = """You are model-dataset-scout of the full_new_direction mode: \
gather_landscape wave, seat 2 of 2. lit-scout has already frozen this run's ONE literature source \
set -- read it at `{run_dir}/inbox/DISCOVER.lit-scout.bundle.json` before you shortlist anything, so \
your candidates build on the SAME frozen evidence rather than a second, independent search pass.

    REQUEST: {request}

{north_star}

1. Read the frozen lit-scout bundle above for the literature context this run already grounded \
(methods/domains it covers) and the run's active domain profile, when one is set.
2. Shortlist models AND datasets plausibly relevant to this request's modality, scale, and label \
requirements -- from the vault, the live-retrieval bundle at `{run_dir}/inbox/search-results.json` \
(when present), or agent Web Search restricted to a model/dataset's own homepage, paper, or repo.
3. For each candidate record: `kind` ("model" or "dataset"), a canonical `name`, a stable `ref` you \
have actually verified exists (arXiv / DOI / homepage / GitHub -- never a guess), and optionally \
`modality`, `license` (null if genuinely unknown), and `fit_notes` explaining the fit. Where a \
candidate connects to a paper already in lit-scout's frozen evidence_table, say so in `fit_notes`.

You are a producer, not a decision-maker: you shortlist candidates, you never pick a winner.
{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{"task": "<this request, restated as the shortlisting task>",
  "candidates": [{{"kind":"model","name":"<name>","ref":"<verified ref>","modality":"<modality>",
                   "license":"<license or null>","fit_notes":"<why it fits>"}}, ...]}}
Quantities are a FLOOR with NO upper bound: candidates >=6, covering BOTH kinds when the domain \
plausibly has both models and datasets to shortlist -- never pad; if genuinely fewer than 6 real \
candidates exist, say so in your one-line return rather than inventing more.

{enablers_and_reframings}
After writing, verify it is valid JSON. Return one line: n_models + n_datasets + the task."""


#: A9 — the two things a direction thesis needs downstream that a landscape sweep is uniquely placed to
#: notice while it is already reading. Appended to BOTH scout packets so neither has to guess which one
#: owns it; the deterministic layer does not consume these, the director-facing shortlist does.
_ENABLERS_AND_REFRAMINGS = """While gathering the landscape, also record two things the direction theses \
will need downstream:
  - ENABLERS: what became newly available in the last 1-3 years that changes what is feasible here --
    a dataset, a released model, a cost drop, a hardware capability, a tool, a regulation, a published
    result. For each, state what it newly permits. An idea that needs technology which does not exist
    yet is too early; an idea that was equally doable five years ago is probably already done.
  - REFRAMINGS: the same real-world problem as different communities define it. State, for 2-4
    communities, how each would DEFINE this problem, which concepts they would use, which method they
    would reach for, and what solution they would propose. Communities that define the problem
    differently are where the untried methods live; a direction that only exists inside one
    community's framing has already been searched by that community.
Put them in your bundle's `notes` field (they are prose findings, not a new contract key)."""


# --------------------------------------------------------------------------- dispatch (gather_landscape)

def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The 2-seat gather_landscape panel for DISCOVER. REPORT is deterministic (dispatches nobody)."""
    if stage != "DISCOVER":
        return None
    north_star = _shared.north_star_block(run_dir)
    lit_out = _panel_recipe.bundle_path(run_dir, stage, "lit-scout")
    mds_out = _panel_recipe.bundle_path(run_dir, stage, "model-dataset-scout")
    seats = [
        _panel_recipe.Seat(
            # `audit` (-> opus): lit-scout freezes the ONE source set the whole run builds on, so a
            # cheap read here caps everything downstream. It is a judgment seat, not a fetch seat.
            label="lit-scout", bundle_key="evidence_table", tier="audit",
            prompt=LIT_SCOUT_PROMPT.format(request=request, north_star=north_star, vault=vault,
                                           run_dir=run_dir, out=lit_out, honesty=_HONESTY,
                                           enablers_and_reframings=_ENABLERS_AND_REFRAMINGS)),
        _panel_recipe.Seat(
            label="model-dataset-scout", bundle_key="candidates", tier="tool",
            depends_on=("lit-scout",),
            prompt=MODEL_DATASET_SCOUT_PROMPT.format(
                request=request, north_star=north_star, run_dir=run_dir, out=mds_out,
                honesty=_HONESTY, enablers_and_reframings=_ENABLERS_AND_REFRAMINGS)),
    ]
    return _panel_recipe.panel(
        run_dir, stage, MODE, seats, model_policy=model_policy,
        panel_note="Wave 1 (lit-scout) freezes the literature source set. Wave 2 "
                  "(model-dataset-scout) reads that SAME frozen bundle before shortlisting "
                  "model/dataset candidates -- one shared gather pass; nothing is re-queried "
                  "downstream.")


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None) -> str:
    """Live-retrieval pre-step: grounds lit-scout's literature base in real records before dispatch."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries)


# --------------------------------------------------------------------------- ingest (frozen bundle read)

def _load_bundles(run_dir, stage: str) -> tuple:
    """Read the frozen gather_landscape pair: lit-scout's 4-key literature bundle and
    model-dataset-scout's shortlist bundle. `_panel_recipe.load_seat_bundles` assumes one seat ==
    one canonical key; lit-scout's bundle carries FOUR (evidence_table/claim_list/
    claim_evidence_map/signals), the same multi-key DISCOVER-worker shape `new_direction.py`
    established, so this recipe reads both bundle files directly instead of forcing that shape
    through the one-key helper. A missing bundle names the exact missing file: the whole point of
    an independent seat is that its absence changes what the report may claim."""
    lit_path = Path(_panel_recipe.bundle_path(run_dir, stage, "lit-scout"))
    mds_path = Path(_panel_recipe.bundle_path(run_dir, stage, "model-dataset-scout"))
    missing = [p.name for p in (lit_path, mds_path) if not p.is_file()]
    if missing:
        raise GateBlock(
            f"{MODE} {stage} gather_landscape panel is incomplete -- missing bundle(s) {missing}. "
            f"Dispatch both lit-scout and model-dataset-scout in llm_step before running run_dets; "
            f"a missing independent seat is not a pass.")
    lit_raw = json.loads(lit_path.read_text(encoding="utf-8"))
    mds_raw = json.loads(mds_path.read_text(encoding="utf-8"))
    lit = {key: _shared.extract_worker_bundle_value(lit_raw, key, stage=stage, mode=MODE,
                                                     agent="lit-scout")
           for key in ("evidence_table", "claim_list", "claim_evidence_map", "signals")}
    mds = {key: _shared.extract_worker_bundle_value(mds_raw, key, stage=stage, mode=MODE,
                                                    agent="model-dataset-scout")
           for key in ("task", "candidates")}
    return lit, mds


# --------------------------------------------------------------------------- landscape_map (deterministic)

#: A documented heuristic (not classify_gap's own taxonomy) projecting the 7-type gap taxonomy onto
#: landscape_map's 6-value gap_kind enum. Presentation-only; the real taxonomy stays in
#: gap_classification/classify_gap.py.
_GAP_KIND_BY_TYPE = {
    "methodological_gap": "method",
    "coverage_gap": "domain",
    "transfer_gap": "domain",
    "evidence_gap": "evaluation",
    "empirical_gap": "evaluation",
    "assumption_gap": "other",
    "stated_open_problem": "other",
}


def _build_landscape_map(et: dict, gc: dict, mdc: dict) -> dict:
    """Deterministic fusion of the frozen literature base + classified gaps + dataset shortlist into
    one landscape_map artifact -- the structured backing for the "Problem landscape" section. No LLM
    authors this (landscape-mapper is not in this mode's agent_subset); every field is a formatting
    transform of data another seat already produced, never a new fact."""
    coverage_gaps = []
    for gap in gc.get("gaps") or []:
        description = str(gap.get("notes") or "").strip() or \
            f"{str(gap['gap_type']).replace('_', ' ')} ({gap['reason_code']})"
        coverage_gaps.append({
            "gap_id": gap["gap_id"], "description": description,
            "gap_kind": _GAP_KIND_BY_TYPE.get(gap["gap_type"], "other"),
            "severity": "minor",
        })
    datasets = [{"dataset_ref": c["ref"], "name": c["name"]}
                for c in (mdc.get("candidates") or []) if c.get("kind") == "dataset"]
    return {
        "domain_query": str(et.get("query") or ""),
        "methods": [],  # this recipe's lit-scout does not extract a per-method breakdown (honest gap)
        "datasets_in_landscape": datasets,
        "coverage_gaps": coverage_gaps,
        "n_methods_found": 0,
        "n_gaps_identified": len(coverage_gaps),
    }


# --------------------------------------------------------------------------- director Markdown sections

def _render_problem_landscape(et: dict, lm: dict) -> str:
    sources = et.get("sources") or []
    n_strong = sum(1 for s in sources if s.get("claim_support") == "strong")
    lines = [
        f"{et.get('n_sources', len(sources))} source(s) ground the query \"{et.get('query', '')}\" "
        f"({n_strong} rated strong support; saturation_reached={et.get('saturation_reached')}).",
    ]
    gaps = lm.get("coverage_gaps") or []
    if gaps:
        by_kind: dict = {}
        for g in gaps:
            by_kind[g["gap_kind"]] = by_kind.get(g["gap_kind"], 0) + 1
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items()))
        lines.append(f"{len(gaps)} coverage gap(s) identified this pass ({breakdown}).")
    else:
        lines.append("No coverage gaps identified this pass -- the corpus read did not surface one.")
    lines.append("A structured per-method breakdown was not attempted this run (landscape_map.methods "
                 "is empty); the landscape is expressed through the literature base and the gap "
                 "classes below instead.")
    return "\n".join(lines)


def _render_model_dataset_opportunities(mdc: dict) -> str:
    candidates = mdc.get("candidates") or []
    if not candidates:
        return "None found -- model-dataset-scout gathered 0 candidates this run."
    lines = [f"{mdc['n_models']} model candidate(s), {mdc['n_datasets']} dataset candidate(s):"]
    for c in candidates:
        modality = f" ({c['modality']})" if c.get("modality") else ""
        license_note = f", license: {c['license']}" if c.get("license") else ""
        fit = f" -- {c['fit_notes']}" if c.get("fit_notes") else ""
        lines.append(f"- [{c['kind']}] {c['name']}{modality}{license_note}: {c['ref']}{fit}")
    return "\n".join(lines)


def _render_evidence_quality(ev: dict, cv: dict) -> str:
    lines = [
        f"evidence-verifier: {ev['verdict']} (n_sources={ev['n_sources']}, n_strong={ev['n_strong']}, "
        f"saturation_reached={ev['saturation_reached']}).",
        f"citation-integrity-auditor: {cv['verdict']} (n_claims_checked={cv['n_claims_checked']}, "
        f"unresolvable_refs={len(cv.get('unresolvable_refs') or [])}, "
        f"contradicted_claims={len(cv.get('contradicted_claims') or [])}).",
    ]
    if ev.get("reasons"):
        lines.append("evidence reasons: " + "; ".join(ev["reasons"]))
    if cv.get("violations"):
        lines.append("citation violations: " + "; ".join(cv["violations"]))
    return "\n".join(lines)


def _render_direction_theses(gc: dict) -> str:
    gaps = gc.get("gaps") or []
    if not gaps:
        return "None found -- the classifier produced 0 candidate direction theses this run."
    lines = [f"{len(gaps)} candidate direction thesis (gap) class(es):"]
    for g in gaps:
        refs = ", ".join(g.get("evidence_ref") or [])
        note = f" -- {g['notes']}" if g.get("notes") else ""
        lines.append(f"- {g['gap_id']} [{g['gap_type']}/{g['reason_code']}] -> {refs}{note}")
    return "\n".join(lines)


def _render_collision_and_uncertainty(weak_or_moderate: list, overlaps: list, frag: dict) -> str:
    lines = []
    if overlaps:
        lines.append(f"{len(overlaps)} gap(s) collide with a PRIOR run's gap inventory for this "
                     f"project (this direction, or something close to it, was already scanned "
                     f"before): {overlaps}")
    else:
        lines.append("No collision with this project's prior gap-inventory runs.")
    if weak_or_moderate:
        lines.append(f"{len(weak_or_moderate)} source(s) carry only moderate/weak claim_support -- "
                     f"treat the gap(s) they anchor as less certain.")
    existence_warnings = frag.get("existence_warnings", 0)
    referential_warnings = frag.get("referential_warnings", 0)
    if existence_warnings:
        lines.append(f"{existence_warnings} citation(s) could not be existence-verified this run "
                     f"(offline or lookup_error -- a warning, not a fabrication finding).")
    if referential_warnings:
        lines.append(f"{referential_warnings} reference(s) point at an unreachable vault (slug "
                     f"existence unverified this run).")
    if not (weak_or_moderate or existence_warnings or referential_warnings):
        lines.append("No unresolved existence or referential-integrity warnings this run.")
    return "\n".join(lines)


_RECOMMENDED_HANDOFF = (
    "This brief stops at DISCOVER: it is a grounded shortlist of direction theses, model/dataset "
    "opportunities, and evidence gaps -- not a ranked idea menu, and not a bet. The machine does not "
    "select a direction here.\n\n"
    "The next step is the director's, via `/idea-bet`-style human sign-off -- the machine never "
    "self-bets. Concretely: pick one thesis above and hand it to a `new_direction` or "
    "`deep_ideation` run (`operate begin --upstream-run <this run>`) to carry it through IDEATE -- "
    "hypothesis generation, tournament ranking, and the novelty-collision check -- until it reaches "
    "an actual `idea_backlog` menu; ONLY THEN does `/idea-bet` apply, and only the director presses it."
)


# --------------------------------------------------------------------------- deterministic DISCOVER stage

def _discover_dets(run_dir, ts, lit: dict, mds: dict) -> tuple:
    _shared.require_bundle_keys(lit, ("evidence_table", "claim_list", "claim_evidence_map", "signals"),
                                stage="DISCOVER", mode=MODE)
    _shared.require_bundle_keys(mds, ("task", "candidates"), stage="DISCOVER", mode=MODE)
    raw_et = lit["evidence_table"]
    cl = lit["claim_list"]
    cem = lit["claim_evidence_map"]
    signals = [s for s in lit["signals"] if isinstance(s, dict)]
    candidates = [c for c in mds["candidates"] if isinstance(c, dict)]

    paths: list = []
    et = build_evidence_table(str(raw_et.get("query") or ""), raw_et.get("sources") or [],
                              bool(raw_et.get("saturation_reached", False)))

    # HARD GATE 1 (registry's independent_grounding_gates, seat 1): evidence sufficiency. Halts
    # BEFORE lit-scout's own evidence-table artifact is written -- an unsaturated/thin base never
    # gets to look like an accepted literature landscape.
    ev = build_verdict(et)
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} evidence gate BLOCK: {ev['reasons']}")
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts))

    # HARD GATE 2 (registry's independent_grounding_gates, seat 2): citation integrity.
    cv = build_report(cl, cem, resolvable_refs=_shared.resolvable_refs(et))
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} citation gate BLOCK: {cv['violations']}")

    # classify_directions: gap-classifier over lit-scout's raw gap signals.
    gc = build_classification(signals)
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))

    # model_dataset_candidates: deterministic assembly of model-dataset-scout's raw shortlist.
    mdc = build_candidates(str(mds.get("task") or ""), candidates)
    paths.append(write_artifact(run_dir, "DISCOVER", "model-dataset-candidates.artifact.json",
                                "model_dataset_candidates", "model-dataset-scout", mdc, ts))

    # landscape_map: deterministic fusion backing the "Problem landscape" section.
    lm = _build_landscape_map(et, gc, mdc)
    paths.append(write_artifact(run_dir, "DISCOVER", "landscape-map.artifact.json",
                                "landscape_map", "landscape-synthesizer", lm, ts))

    # Three wave-2 common hard gates: north-star drift, live citation existence, referential integrity.
    known_ids = {str(s.get("id")) for s in (et.get("sources") or []) if s.get("id")}
    known_ids |= {str(c.get("claim_id")) for c in (cl.get("claims") or []) if c.get("claim_id")}
    downstream_refs = [r for gap in (gc.get("gaps") or []) for r in (gap.get("evidence_ref") or [])]
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "DISCOVER", ts, mode=MODE,
        bundles={"evidence_table": et, "claim_list": cl, "signals": signals, "candidates": candidates},
        evidence_table=et, claim_evidence_map=cem,
        downstream_refs=downstream_refs, known_ids=known_ids)
    paths += gate_paths

    # Cross-run project memory (mirrors new_direction's audit-C1 pattern): "you already scanned this".
    overlaps: list = []
    ws = project_memory.workspace_for_run(run_dir)
    if ws is not None:
        run_id = _shared.task_frame(run_dir)["payload"]["task_id"]
        overlaps = project_memory.prior_overlaps(gc["gaps"], project_memory.load_gap_inventory(ws),
                                                 run_id=run_id)
        project_memory.append_gap_inventory(ws, run_id, ts, gc["gaps"])

    weak_or_moderate = [s for s in (et.get("sources") or [])
                        if s.get("claim_support") in ("moderate", "weak")]

    sections = {
        "Problem landscape": _render_problem_landscape(et, lm),
        "Model and dataset opportunities": _render_model_dataset_opportunities(mdc),
        "Evidence quality": _render_evidence_quality(ev, cv),
        "Candidate direction theses": _render_direction_theses(gc),
        "Collision and uncertainty notes": _render_collision_and_uncertainty(
            weak_or_moderate, overlaps, frag),
        "Recommended handoff": _RECOMMENDED_HANDOFF,
    }
    md_rel = _panel_recipe.render_director_markdown(
        run_dir, MODE, sections, ts=ts, lead="gather_landscape + independent_grounding_gates + "
                                            "classify_directions panel")

    report = {
        "evidence_gate": ev["verdict"], "citation_gate": cv["verdict"],
        "n_sources": et.get("n_sources") or len(et.get("sources") or []),
        "n_strong_sources": ev.get("n_strong"),
        "n_model_candidates": mdc["n_models"], "n_dataset_candidates": mdc["n_datasets"],
        "gaps_classified": len(gc["gaps"]), "prior_gap_overlaps": overlaps,
        "uncertain_sources": len(weak_or_moderate),
        "director_markdown": md_rel,
    }
    report.update(frag)
    return paths, report


def _report(run_dir, ts) -> tuple:
    md_rel = str(_panel_recipe.target_markdown(MODE)["path"])
    md_written = (Path(run_dir) / md_rel).is_file()
    lm_path = Path(run_dir) / "evidence" / "DISCOVER" / "landscape-map.artifact.json"
    n_gaps = 0
    if lm_path.is_file():
        n_gaps = json.loads(lm_path.read_text(encoding="utf-8"))["payload"].get(
            "n_gaps_identified", 0)
    open_questions = [] if md_written else [
        "director brief markdown missing at DISCOVER -- re-run DISCOVER's run_dets before reporting"]
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary=(f"full_new_direction: grounded DISCOVER-only shortlist -- both grounding gates "
                f"passed, {n_gaps} candidate direction thesis(es) classified; stops before any idea "
                f"bet (see the brief's Recommended handoff section)."),
        references=[md_rel] if md_written else [], open_questions=open_questions)


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock on a
    hard-gate refusal, ValueError on an unknown stage."""
    if stage == "DISCOVER":
        lit, mds = _load_bundles(run_dir, stage)
        return _discover_dets(run_dir, ts, lit, mds)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
