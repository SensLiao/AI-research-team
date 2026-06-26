"""Shared deep-ideation chain (RAT-2 Wave-3 wiring, 2026-06-19).

The deep IDEATE micro-subgraph the deep-research report asks for, wired ONTO the fixed macro spine
WITHOUT changing the stage enum. Both `deep_ideation` (full chain) and `new_direction` (the
REPORT-stage enrichment subset) import from here, so there is ONE source of the deep logic — no drift.

Design (the report's three principles):
  - object-first: every deep step emits a TYPED artifact validated by validate_artifact, so 'depth'
    is a recorded object, not a longer paragraph.
  - criticism-before-ranking: contradiction + novelty-collision run before the /idea-bet menu.
  - deterministic cores SCORE / derive; LLM workers READ / IDEATE (consolidation honesty, matching
    new_direction). A worker bundle is `inbox/<STEM>.bundle.json`; a deterministic producer turns it
    into `evidence/<stage>/<...>.artifact.json`.

Maps the already-built RAT-2 capability tools into the operate recipe (closes audit gap A1):
  formal_problem_schema.build_problem_abstraction  -> problem_abstraction       (mathematical-formalizer)
  <LLM-authored bundle>                            -> mechanism_graph           (mechanism-graph-builder)
  analogy_graph_match.match_mechanisms            -> mechanism_mapping          (analogy-mapper)
  saturation_meter.measure_saturation             -> evidence_saturation_report (evidence-saturation-judge)
  <LLM-authored bundle>                            -> contradiction_report      (contradiction-miner)
  <LLM-authored bundle>                            -> experiment_sketch         (experiment-architect)
  <assembled from artifacts>                       -> idea_lineage              (idea-lineage-tracker)
  stage_scorecard.build_stage_scorecard/global    -> global_quality_scorecard  (quality-controller; A2 -> REPORT)
  integrity_scan.build_recommendation             -> integrity_recommendation  (integrity-refusal-recommender; A3 -> REPORT)
  idea_quality_eval.build_quality_eval            -> idea_quality_eval         (blind pairwise harness)

This module is a LEAF: it imports only _shared / artifacts / tools (never new_direction / deep_ideation),
so new_direction may import it for its REPORT enrichment without a circular import. deep_ideation composes
new_direction's proven base with these producers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ...tools.analogy_graph_match import match_mechanisms
from ...tools.formal_problem_schema import build_problem_abstraction
from ...tools.integrity_scan import build_recommendation
from ...tools.saturation_meter import measure_saturation
from ...tools.stage_scorecard import build_global_scorecard, build_stage_scorecard

# The closed mechanism-primitive vocabulary (mirrors problem_abstraction.schema.json — the worker MUST
# pick from these; build_problem_abstraction raises on an unknown primitive).
MECHANISM_PRIMITIVES = (
    "thin_structure", "topology_preservation", "boundary_uncertainty", "anisotropic_geometry",
    "long_range_dependency", "class_imbalance", "partial_observability", "noise_robustness",
    "constraint_satisfaction", "multi_scale_structure", "graph_connectivity", "energy_minimization",
    "dynamical_stability",
)


def _deep_model(model_policy: str) -> str:
    """Deep-chain workers are judgment-dense (formalize / mechanism / analogy / contradiction /
    experiment) — opus regardless of policy (report §所需资源: judgment-heavy steps go to the high
    model). max_quality is opus anyway; default keeps these on opus because they ARE the depth."""
    return "opus"


# --------------------------------------------------------------------------- worker prompts (LLM WORK)

FORMALIZE_WORKER_PROMPT = """You are the PROBLEM-FORMALIZER worker (the mathematical-formalizer). Turn \
the request into a TYPED, domain-NEUTRAL problem abstraction so the rest of the deep chain reasons about \
mechanisms, not surface wording — for this request:

    REQUEST: {request}

{north_star}

Read `{run_dir}/inbox/DISCOVER.bundle.json` (the grounding evidence/claims already mined from the vault) \
to ground your abstraction in what the literature actually says.

Pick `mechanism_primitives` ONLY from this closed vocabulary (an unknown primitive is rejected by a \
deterministic gate): {primitives}. Choose the few that genuinely name the underlying mechanism; an empty \
list is legitimate if none fit (formal_form will then be 'none').

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names; re-emit the FULL bundle.

Write ONLY this JSON to `{out}` (filename ends in .bundle.json):
{{
  "problem_id": "PA-001",
  "problem": "<the problem in one precise sentence (the surface form is fine here)>",
  "mechanism_primitives": ["<from the closed vocabulary>"],
  "failure_modes": ["<how this problem class is known to fail, mechanism-level>"],
  "constraints": ["<hard constraints: label scarcity / compute / real-time / ...>"],
  "success_metrics": ["<how success is measured at the mechanism level>"],
  "abstraction_confidence": 0.6
}}
abstraction_confidence in [0,1] is advisory (low is legitimate). After writing, verify valid JSON. \
Return one line: the chosen primitives + your confidence."""

MECHANISM_WORKER_PROMPT = """You are the MECHANISM-GRAPH-BUILDER worker. Build the EXPLICIT internal causal \
graph of the problem itself (NOT a cross-domain analogy) — this is where depth becomes a measurable object. \
Read:
  - `{run_dir}/inbox/FORMALIZE.bundle.json`  (the problem abstraction; REUSE its problem_id as problem_ref)
  - `{run_dir}/inbox/DISCOVER.bundle.json`   (evidence/claims to ground each node + edge)

{north_star}

Decompose the problem into mechanism / variable / mediator / outcome nodes and the DIRECTED causal edges \
between them; mark where one could intervene and the known failure modes. Every node and every edge MUST \
carry a non-empty evidence_ref (a real [[slug]] / gap_id / claim_id) — a deterministic gate checks that \
every edge's from_node/to_node names a real node, and rejects an invented graph.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names; re-emit the FULL bundle.

Write ONLY this JSON to `{out}`:
{{
  "graph_id": "MG-001",
  "problem_ref": "<the FORMALIZE problem_id, e.g. PA-001>",
  "nodes": [{{"node_id":"N1","label":"<mechanism/variable>","kind":"mechanism|variable|mediator|intervention_point|outcome","evidence_ref":["[[<slug>]]"]}}],
  "edges": [{{"edge_id":"E1","from_node":"N1","to_node":"N2","relation":"causes|enables|inhibits|mediates|depends_on|correlates","evidence_ref":["[[<slug>]]"],"rationale":"<why>"}}],
  "intervention_points": [{{"node_ref":"N1","rationale":"<why acting here changes the outcome>"}}],
  "failure_modes": ["<how this mechanism breaks>"]
}}
Quantities: >=3 nodes and >=2 edges that form at least one chain of length >=2 (real depth, not a star). \
After writing, verify valid JSON. Return one line: node/edge counts + the longest causal chain."""

ANALOGY_WORKER_PROMPT = """You are the ANALOGY-MAPPER worker. From the problem's MECHANISMS, find STRUCTURAL \
(not surface) analogs in OTHER domains and lay them next to this problem. Read:
  - `{run_dir}/inbox/FORMALIZE.bundle.json`  (problem_id -> use as target_problem_id)
  - `{run_dir}/inbox/MECHANISM.bundle.json`  (the problem's mechanism nodes -> the target mechanisms)
  - `{run_dir}/inbox/DISCOVER.bundle.json`   (+ inbox/search-results.json if present) for real source-domain papers

{north_star}

For each analogy: strip domain nouns to mechanism phrases, list the SHARED mechanisms (each grounded by a \
real source paper ref), the source-domain assumptions that would BLOCK the transfer, and the required \
adaptations. ONLY emit a mapping that has >=1 genuinely shared mechanism (a zero-overlap 'analogy' is not \
one — drop it). Provide source_mechanisms + target_mechanisms as plain phrase lists; a deterministic tool \
computes overlap_score and the verdict from them (you do NOT set the score).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names; re-emit the FULL bundle.

Write ONLY this JSON to `{out}`:
{{
  "mappings": [{{
    "mapping_id": "AM-001", "source_domain": "<the other field>",
    "target_problem_id": "<the FORMALIZE problem_id>",
    "source_mechanisms": ["<mechanism phrase in the source domain>"],
    "target_mechanisms": ["<mechanism phrase in THIS problem>"],
    "shared_mechanisms": [{{"mechanism":"<shared phrase>","source_evidence_ref":["arXiv:... or [[slug]]"]}}],
    "blocking_assumptions": [{{"assumption":"<source assumption at risk>","why_blocking":"<why it breaks here>"}}],
    "required_adaptations": [{{"adaptation":"<how to port it>","addresses":"<which assumption/mechanism>"}}]
  }}]
}}
Emit 1-3 mappings (the strongest structural analogs). After writing, verify valid JSON. Return one line: \
count + the strongest analog's source domain."""

CONTRADICTION_WORKER_PROMPT = """You are the CONTRADICTION-MINER worker. Find where the grounded evidence \
CONFLICTS with itself — the conflicts an idea must survive. Read:
  - `{run_dir}/inbox/DISCOVER.bundle.json`  (its claim_list + claim_evidence_map are the claims to compare)

{north_star}

Compare claims pairwise; record genuine conflicts only (do NOT manufacture disagreement). Each conflict \
names two real claim ids (from claim_list) and its kind.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names; re-emit the FULL bundle.

Write ONLY this JSON to `{out}`:
{{
  "conflicts": [{{"conflict_id":"CF-1","claim_ref_a":"c1","claim_ref_b":"c2",
     "kind":"numerical-disagreement|directional-flip|scope-mismatch|method-conflict|other",
     "detail":"<what disagrees>"}}],
  "n_claims_checked": 3
}}
n_claims_checked = how many claims you actually compared (>=0). conflicts MAY be empty (a clean evidence \
base is a real finding). After writing, verify valid JSON. Return one line: conflicts found / claims checked."""

EXPERIMENT_WORKER_PROMPT = """You are the EXPERIMENT-ARCHITECT worker. Make each candidate idea TESTABLE: \
reduce it to a MINIMAL experiment with a concrete falsifier (the designability gate — an idea you cannot \
sketch an experiment for is not yet a direction). This is a sketch, NOT the full DESIGN protocol. Read:
  - `{run_dir}/inbox/IDEATE.bundle.json`  (its `ideas` and `evolved` are the candidates to sketch)

{north_star}

For EACH candidate idea_id (originals + evolved), emit one minimal experiment sketch.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names; re-emit the FULL bundle.

Write ONLY this JSON to `{out}`:
{{
  "sketches": [{{
    "sketch_id":"ES-1","idea_ref":"<idea_id, e.g. IDEA-1>",
    "experiment":"<the minimal experiment to run next quarter>",
    "controls":["<what is held fixed / the baseline>"],
    "metrics":["<observable metric>"],
    "observable_signals":["<what you'd see if it works vs fails>"],
    "falsifier":"<the result that would FALSIFY the idea>",
    "next_branch":"<what to try if it fails>",
    "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable","time":"short|medium|long"}}
  }}]
}}
One sketch per candidate idea. After writing, verify valid JSON. Return one line: sketches written + the \
idea with the cleanest falsifier."""


# --------------------------------------------------------------------------- worker-spec builders

def discover_deep_workers(run_dir: str, request: str, vault: str, model_policy: str,
                          *, with_analogy: bool) -> List[dict]:
    """The deep DISCOVER panel, in dependency order (each reads prior bundles). The mode PREPENDS its base
    discover worker. `with_analogy` adds the cross-domain analogy-mapper (deep_ideation only)."""
    ns = _shared.north_star_block(run_dir)
    model = _deep_model(model_policy)

    def w(label: str, stem: str, prompt: str) -> dict:
        out = f"{run_dir}/inbox/{stem}.bundle.json"
        return {"label": label, "model": model, "output": out,
                "prompt": prompt.format(request=request, run_dir=run_dir, out=out, north_star=ns,
                                        primitives=", ".join(MECHANISM_PRIMITIVES))}

    workers = [w("problem-formalizer", "FORMALIZE", FORMALIZE_WORKER_PROMPT),
               w("mechanism-graph-builder", "MECHANISM", MECHANISM_WORKER_PROMPT)]
    if with_analogy:
        workers.append(w("analogy-mapper", "ANALOGY", ANALOGY_WORKER_PROMPT))
    workers.append(w("contradiction-miner", "CONTRADICTION", CONTRADICTION_WORKER_PROMPT))
    return workers


def experiment_worker(run_dir: str, request: str, model_policy: str) -> dict:
    """The IDEATE experiment-architect worker (deep_ideation only), dispatched AFTER ideate + collision."""
    ns = _shared.north_star_block(run_dir)
    out = f"{run_dir}/inbox/EXPERIMENT.bundle.json"
    return {"label": "experiment-architect", "model": _deep_model(model_policy), "output": out,
            "prompt": EXPERIMENT_WORKER_PROMPT.format(run_dir=run_dir, out=out, north_star=ns)}


# --------------------------------------------------------------------------- helpers

def _inbox(run_dir, stem: str, *, required: bool) -> Optional[dict]:
    p = Path(run_dir) / "inbox" / f"{stem}.bundle.json"
    if not p.exists():
        if required:
            raise FileNotFoundError(
                f"{stem} worker bundle missing at {p} — dispatch the {stem} deep worker first")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _artifact(run_dir, stage: str, filename: str) -> Optional[dict]:
    p = Path(run_dir) / "evidence" / stage / filename
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("payload")


def _write_or_block(run_dir, stage, filename, atype, created_by, payload, ts) -> str:
    """write_artifact validates the schema and raises ValueError on a malformed payload; convert that to a
    GateBlock so the bounded-repair loop can re-dispatch the worker instead of crashing the run."""
    try:
        return write_artifact(run_dir, stage, filename, atype, created_by, payload, ts)
    except ValueError as exc:
        raise GateBlock(f"{atype} BLOCK (malformed deep bundle): {exc}")


# --------------------------------------------------------------------------- DISCOVER deep producers

def produce_problem_abstraction(run_dir, ts, *, required: bool = True) -> Optional[str]:
    b = _inbox(run_dir, "FORMALIZE", required=required)
    if b is None:
        return None
    _shared.require_bundle_keys(b, ("problem_id", "problem", "mechanism_primitives"),
                               stage="DISCOVER", mode="deep_ideation")
    try:
        pa = build_problem_abstraction(
            b["problem"], b.get("mechanism_primitives") or [], problem_id=b["problem_id"],
            failure_modes=b.get("failure_modes"), constraints=b.get("constraints"),
            success_metrics=b.get("success_metrics"),
            abstraction_confidence=float(b.get("abstraction_confidence", 0.5)), notes=b.get("notes"))
    except (ValueError, TypeError) as exc:
        raise GateBlock(f"problem-abstraction BLOCK: {exc}")
    return _write_or_block(run_dir, "DISCOVER", "problem-abstraction.artifact.json",
                           "problem_abstraction", "mathematical-formalizer", pa, ts)


def produce_mechanism_graph(run_dir, ts, *, required: bool = True) -> Optional[str]:
    b = _inbox(run_dir, "MECHANISM", required=required)
    if b is None:
        return None
    _shared.require_bundle_keys(b, ("graph_id", "problem_ref", "nodes", "edges"),
                               stage="DISCOVER", mode="deep_ideation")
    node_ids = {str(n.get("node_id")) for n in b["nodes"] if isinstance(n, dict)}
    bad = []
    for e in b["edges"]:
        for k in ("from_node", "to_node"):
            if str(e.get(k)) not in node_ids:
                bad.append(f"edge {e.get('edge_id')!r} {k}={e.get(k)!r}")
    for ip in (b.get("intervention_points") or []):
        if str(ip.get("node_ref")) not in node_ids:
            bad.append(f"intervention node_ref={ip.get('node_ref')!r}")
    if bad:
        raise GateBlock(f"mechanism-graph integrity BLOCK: {bad} not in node_ids")
    pa = _artifact(run_dir, "DISCOVER", "problem-abstraction.artifact.json")
    if pa and str(b["problem_ref"]) != str(pa.get("problem_id")):
        raise GateBlock(f"mechanism-graph problem_ref {b['problem_ref']!r} != problem_abstraction "
                        f"{pa.get('problem_id')!r}")
    payload = {k: b[k] for k in ("graph_id", "problem_ref", "nodes", "edges")}
    for opt in ("intervention_points", "failure_modes", "notes"):
        if b.get(opt):
            payload[opt] = b[opt]
    return _write_or_block(run_dir, "DISCOVER", "mechanism-graph.artifact.json",
                           "mechanism_graph", "mechanism-graph-builder", payload, ts)


def produce_mechanism_mappings(run_dir, ts, *, required: bool = True) -> List[str]:
    b = _inbox(run_dir, "ANALOGY", required=required)
    if b is None:
        return []
    pa = _artifact(run_dir, "DISCOVER", "problem-abstraction.artifact.json")
    target_pid = str(pa.get("problem_id")) if pa else "PA-001"
    paths = []
    for i, m in enumerate(b.get("mappings") or []):
        shared = [s for s in (m.get("shared_mechanisms") or []) if isinstance(s, dict)]
        if not shared:
            continue                                    # a zero-overlap 'analogy' is not one — drop it
        src = [str(s) for s in (m.get("source_mechanisms") or []) if str(s).strip()]
        tgt = [str(t) for t in (m.get("target_mechanisms") or []) if str(t).strip()]
        overlap = float(match_mechanisms(src, tgt)["overlap_score"]) if (src and tgt) else 0.0
        blockers = [x for x in (m.get("blocking_assumptions") or []) if isinstance(x, dict)]
        verdict = "REPAIR" if blockers else "PASS"      # allOf: PASS requires no blockers
        payload = {"mapping_id": m.get("mapping_id") or f"AM-{i + 1}",
                   "source_domain": m.get("source_domain") or "unknown",
                   "target_problem_id": m.get("target_problem_id") or target_pid,
                   "shared_mechanisms": shared, "blocking_assumptions": blockers,
                   "required_adaptations": [x for x in (m.get("required_adaptations") or [])
                                            if isinstance(x, dict)],
                   "overlap_score": overlap, "verdict": verdict}
        if m.get("notes"):
            payload["notes"] = m["notes"]
        paths.append(_write_or_block(run_dir, "DISCOVER",
                                     f"mechanism-mapping-{payload['mapping_id']}.artifact.json",
                                     "mechanism_mapping", "analogy-mapper", payload, ts))
    return paths


def produce_evidence_saturation(run_dir, ts) -> Optional[str]:
    """Advisory measured-saturation report. Uses the DISCOVER bundle's optional `saturation_rounds`; with
    only one retrieval pass it honestly reports INSUFFICIENT_DATA (real saturation needs iterative rounds)."""
    b = _inbox(run_dir, "DISCOVER", required=False)
    if b is None:
        return None
    rounds = b.get("saturation_rounds")
    if not rounds:
        et = b.get("evidence_table") or {}
        n = len(et.get("sources") or [])
        rounds = [{"round_index": 1, "queries_run": 1 if et.get("query") else 0,
                   "new_unique_sources": n, "cumulative_unique_sources": n}]
    rep = measure_saturation(rounds, report_id="SAT-001")
    return _write_or_block(run_dir, "DISCOVER", "evidence-saturation-report.artifact.json",
                           "evidence_saturation_report", "evidence-saturation-judge", rep, ts)


def produce_contradiction(run_dir, ts, *, required: bool = True) -> Optional[str]:
    b = _inbox(run_dir, "CONTRADICTION", required=required)
    if b is None:
        return None
    _shared.require_bundle_keys(b, ("conflicts", "n_claims_checked"),
                               stage="DISCOVER", mode="deep_ideation")
    payload = {"conflicts": [c for c in b["conflicts"] if isinstance(c, dict)],
               "n_claims_checked": int(b["n_claims_checked"])}
    if b.get("notes"):
        payload["notes"] = b["notes"]
    return _write_or_block(run_dir, "DISCOVER", "contradiction-report.artifact.json",
                           "contradiction_report", "contradiction-miner", payload, ts)


def deep_discover_producers(run_dir, ts, *, required: bool) -> Tuple[List[str], dict]:
    """The deep DISCOVER producer sequence, shared by deep_ideation (required=True, STRICT) and
    new_direction (required=False, GRACEFUL). Returns (paths, report_fragment). A producer whose worker
    bundle is absent is skipped when required=False — so a mode that does NOT dispatch a given deep worker
    (e.g. new_direction omits the cross-domain analogy-mapper) simply omits that artifact, no crash."""
    paths: List[str] = []
    pa = produce_problem_abstraction(run_dir, ts, required=required)
    if pa:
        paths.append(pa)
    mg = produce_mechanism_graph(run_dir, ts, required=required)
    if mg:
        paths.append(mg)
    maps = produce_mechanism_mappings(run_dir, ts, required=required)
    paths += maps
    sat = produce_evidence_saturation(run_dir, ts)
    if sat:
        paths.append(sat)
    con = produce_contradiction(run_dir, ts, required=required)
    if con:
        paths.append(con)
    frag = {"deep_discover": {"problem_abstraction": bool(pa), "mechanism_graph": bool(mg),
                             "mechanism_mappings": len(maps), "evidence_saturation": bool(sat),
                             "contradiction": bool(con)}}
    return paths, frag


# --------------------------------------------------------------------------- IDEATE deep producers

def produce_experiment_sketches(run_dir, ts, *, required: bool = True) -> List[str]:
    b = _inbox(run_dir, "EXPERIMENT", required=required)
    if b is None:
        return []
    paths = []
    for i, s in enumerate(b.get("sketches") or []):
        if not isinstance(s, dict):
            continue
        sid = s.get("sketch_id") or f"ES-{i + 1}"
        payload = {"sketch_id": sid}
        for k in ("idea_ref", "experiment", "controls", "metrics", "observable_signals", "falsifier"):
            if k in s:
                payload[k] = s[k]
        for opt in ("next_branch", "feasibility", "notes"):
            if s.get(opt) is not None:
                payload[opt] = s[opt]
        paths.append(_write_or_block(run_dir, "IDEATE", f"experiment-sketch-{sid}.artifact.json",
                                     "experiment_sketch", "experiment-architect", payload, ts))
    return paths


def produce_idea_lineage(run_dir, ts) -> Optional[str]:
    """Assemble the per-idea provenance ledger from the artifacts the IDEATE/DISCOVER stages already wrote.
    disposition is MECHANICAL (candidate / cut_prior_art / evolved) — never a bet."""
    backlog = _artifact(run_dir, "IDEATE", "idea-backlog.artifact.json") or {}
    coll = _artifact(run_dir, "IDEATE", "novelty-collision-verdict.artifact.json") or {}
    evolved = _artifact(run_dir, "IDEATE", "evolved-ideas.artifact.json") or {}
    pa = _artifact(run_dir, "DISCOVER", "problem-abstraction.artifact.json") or {}
    mg = _artifact(run_dir, "DISCOVER", "mechanism-graph.artifact.json") or {}
    ideate_b = _inbox(run_dir, "IDEATE", required=False) or {}

    ranked_ids = [str(i.get("idea_id")) for i in backlog.get("ranked_ideas") or []]
    cut_ids = {str(x) for x in (coll.get("cut_ids") or [])}
    evolved_ids = {str(e.get("idea_id")) for e in evolved.get("ideas") or []}
    parents_by = {str(e.get("idea_id")): [str(p) for p in (e.get("parent_ids") or [])]
                  for e in evolved.get("ideas") or []}
    hyp_by, gaps_by = {}, {}
    for i in ideate_b.get("ideas") or []:
        iid = str(i.get("idea_id"))
        if i.get("from_hypothesis_ref"):
            hyp_by[iid] = str(i["from_hypothesis_ref"])
        gaps_by[iid] = [str(r) for r in (i.get("evidence_ref") or []) if str(r).startswith("GAP")]

    problem_ref = pa.get("problem_id")
    mg_ref = mg.get("graph_id")
    sketch_dir = Path(run_dir) / "evidence" / "IDEATE"
    sketch_by = {}
    if sketch_dir.exists():
        for sp in sketch_dir.glob("experiment-sketch-*.artifact.json"):
            pl = json.loads(sp.read_text(encoding="utf-8")).get("payload") or {}
            if pl.get("idea_ref"):
                sketch_by[str(pl["idea_ref"])] = str(pl.get("sketch_id"))

    all_ids = list(dict.fromkeys(ranked_ids + sorted(cut_ids) + sorted(evolved_ids)))
    lineages = []
    for iid in all_ids:
        disp = "cut_prior_art" if iid in cut_ids else ("evolved" if iid in evolved_ids else "candidate")
        ev = [hyp_by[iid]] if iid in hyp_by else ([str(problem_ref)] if problem_ref else [iid])
        lin = {"idea_id": iid, "disposition": disp, "evidence_ref": ev}
        if problem_ref:
            lin["problem_ref"] = str(problem_ref)
        if mg_ref:
            lin["mechanism_graph_ref"] = str(mg_ref)
        if iid in hyp_by:
            lin["hypothesis_ref"] = hyp_by[iid]
        if gaps_by.get(iid):
            lin["gap_refs"] = gaps_by[iid]
        if parents_by.get(iid):
            lin["parent_ids"] = parents_by[iid]
        if sketch_by.get(iid):
            lin["experiment_sketch_ref"] = sketch_by[iid]
        lineages.append(lin)
    if not lineages:
        return None
    return _write_or_block(run_dir, "IDEATE", "idea-lineage.artifact.json",
                           "idea_lineage", "idea-lineage-tracker", {"lineages": lineages}, ts)


def deep_ideate_producers(run_dir, ts, *, required: bool) -> Tuple[List[str], dict]:
    """The deep IDEATE producer sequence (experiment sketches + idea lineage), shared by deep_ideation
    (required=True) and new_direction (required=False). idea_lineage is always assembled from whatever
    artifacts exist (it degrades to a backlog-only lineage when no upstream deep artifacts are present)."""
    sketches = produce_experiment_sketches(run_dir, ts, required=required)
    lin = produce_idea_lineage(run_dir, ts)
    paths = list(sketches) + ([lin] if lin else [])
    frag = {"deep_ideate": {"experiment_sketches": len(sketches), "idea_lineage": bool(lin)}}
    return paths, frag


# --------------------------------------------------------------------------- REPORT deep producers

def _gate_verdicts(run_dir, stage: str) -> List[dict]:
    """Every committed gate/producer artifact in a stage, mapped to a {panel_role, pass, violations,
    evidence_ref} verdict (pass = status != blocked). A run reaching REPORT passed its hard gates, so this
    is an honest record, not a re-judgement."""
    d = Path(run_dir) / "evidence" / stage
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.artifact.json")):
        try:
            art = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"panel_role": art.get("artifact_type") or p.stem,
                    "pass": art.get("status") != "blocked", "violations": [],
                    "evidence_ref": str(p)})
    return out


def produce_report_quality(run_dir, ts) -> List[str]:
    """REPORT-stage aggregation: global quality scorecard (quality-controller; closes A2 -> REPORT),
    integrity recommendation (advisory; closes A3 -> REPORT), and the blind pairwise quality eval."""
    paths = []
    cards = []
    for stage in ("DISCOVER", "IDEATE"):
        v = _gate_verdicts(run_dir, stage)
        if v:
            cards.append(build_stage_scorecard(stage, v))
    run_id = _shared.task_frame(run_dir)["payload"]["task_id"]
    gsc = build_global_scorecard(run_id, cards)
    paths.append(_write_or_block(run_dir, "REPORT", "global-quality-scorecard.artifact.json",
                                 "global_quality_scorecard", "quality-controller", gsc, ts))

    disc = _inbox(run_dir, "DISCOVER", required=False) or {}
    claims = [{"claim_id": str(c.get("claim_id")), "text": str(c.get("text") or ""),
               "evidence_ref": c.get("source_ref")}
              for c in ((disc.get("claim_list") or {}).get("claims") or []) if isinstance(c, dict)]
    rec = build_recommendation("IR-1", claims,
                               scanned_artifacts=["evidence/DISCOVER/contradiction-report.artifact.json"])
    paths.append(_write_or_block(run_dir, "REPORT", "integrity-recommendation.artifact.json",
                                 "integrity_recommendation", "integrity-refusal-recommender", rec, ts))

    qe = produce_quality_eval(run_dir, ts)
    if qe:
        paths.append(qe)
    return paths


def produce_quality_eval(run_dir, ts) -> Optional[str]:
    """The blind pairwise quality harness over the candidate ideas (decomposed, advisory, no collapsed
    total). Imported lazily so this module loads even before the tool is present."""
    from ...tools.idea_quality_eval import build_quality_eval

    backlog = _artifact(run_dir, "IDEATE", "idea-backlog.artifact.json") or {}
    ideas = [{"idea_id": str(i.get("idea_id")), "evidence_ref": i.get("evidence_ref") or []}
             for i in (backlog.get("ranked_ideas") or []) if i.get("idea_id")]
    if not ideas:
        return None
    mg = _artifact(run_dir, "DISCOVER", "mechanism-graph.artifact.json")
    contr = _artifact(run_dir, "DISCOVER", "contradiction-report.artifact.json")
    coll = _artifact(run_dir, "IDEATE", "novelty-collision-verdict.artifact.json")
    grounding = None
    gr = _artifact(run_dir, "IDEATE", "idea-grounding-report.artifact.json")
    if isinstance(gr, dict) and isinstance(gr.get("scores"), list):
        grounding = {str(s.get("idea_id")): float(s.get("score"))
                     for s in gr["scores"] if s.get("idea_id") is not None and s.get("score") is not None}
    disc_dir = Path(run_dir) / "evidence" / "DISCOVER"
    mappings = [json.loads(p.read_text(encoding="utf-8")).get("payload")
                for p in sorted(disc_dir.glob("mechanism-mapping-*.artifact.json"))] if disc_dir.exists() else []
    ide_dir = Path(run_dir) / "evidence" / "IDEATE"
    sketches = [json.loads(p.read_text(encoding="utf-8")).get("payload")
                for p in sorted(ide_dir.glob("experiment-sketch-*.artifact.json"))] if ide_dir.exists() else []
    qe = build_quality_eval("QE-001", ideas, mechanism_graph=mg, mechanism_mappings=mappings or None,
                            contradiction=contr, experiment_sketches=sketches or None,
                            collision_verdict=coll, grounding_by_id=grounding)
    return _write_or_block(run_dir, "REPORT", "idea-quality-eval.artifact.json",
                           "idea_quality_eval", "idea_quality_eval", qe, ts)
