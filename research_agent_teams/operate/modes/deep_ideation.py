"""Operate recipe for the `deep_ideation` mode (DISCOVER -> IDEATE -> REPORT) — the FULL deep chain.

The deepest find-a-direction flow: it runs new_direction's proven grounding + ideation + novelty-collision
base AND the RAT-2 deep-ideation chain wired in `_deep_ideate` (problem formalization -> mechanism graph ->
cross-domain analogy -> evidence saturation -> contradiction mining -> experiment sketches -> idea lineage
-> quality scorecard + integrity + blind pairwise eval). It is the report's IDEATE-v2 made push-button.

Zero-drift design: this module COMPOSES — it reuses new_direction's `_discover_dets` / `_ideate_dets` /
`_report` (the proven, tested base) and ADDS the `_deep_ideate` producers. There is no second copy of the
base logic. The lighter, flagship variant is `new_direction` (same base + the REPORT-stage deep enrichment
only); the director picks between them via the research-orchestrator skill (AskUserQuestion).

Stages are the SAME macro path as new_direction ([DISCOVER, IDEATE, REPORT]) — the deep chain is a
micro-subgraph INSIDE the macro stages, so the runstore stage enum is untouched (report's hard constraint).
The IDEATE boundary IS the /idea-bet review; downstream experiment rigor fires only AFTER a human bet.
"""
from __future__ import annotations

from typing import Optional

from . import _deep_ideate, _shared, new_direction
from ..artifacts import GateBlock  # noqa: F401  (re-exported for parity with new_direction's surface)
from ..bounded_repair import attempt_with_repair

STAGES = ["DISCOVER", "IDEATE", "REPORT"]
DEFAULT_VAULT = new_direction.DEFAULT_VAULT


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Same live-retrieval pre-step as new_direction (grounds DISCOVER + novelty + analogy in literature)."""
    return new_direction.pre_search(run_dir, request, ts, transport=transport,
                                    sources=sources, limit_per_source=limit_per_source)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The worker(s) to dispatch for a stage. DISCOVER and IDEATE return a PANEL ('workers') the skill
    spawns IN ORDER (each deep worker reads the prior workers' inbox bundles). REPORT is deterministic."""
    if stage == "DISCOVER":
        deep = _deep_ideate.discover_deep_workers(run_dir, request, vault, model_policy, with_analogy=True)
        return {"workers": [new_direction.discover_worker(run_dir, request, vault, model_policy), *deep],
                "panel_note": "spawn IN ORDER: discover -> formalize -> mechanism -> analogy -> "
                              "contradiction (each reads the prior inbox/*.bundle.json). deep_ideation "
                              "adds the cross-domain analogy-mapper that new_direction omits."}
    if stage == "IDEATE":
        return {"workers": [new_direction.ideate_worker(run_dir, request, vault, model_policy),
                            new_direction.collision_step(run_dir, vault=vault, model_policy=model_policy),
                            _deep_ideate.experiment_worker(run_dir, request, model_policy)],
                "panel_note": "spawn IN ORDER: ideate -> novelty-collision -> experiment-architect "
                              "(collision + experiment read inbox/IDEATE.bundle.json)."}
    return None  # REPORT is deterministic


def _discover_dets(run_dir, ts) -> tuple:
    """new_direction's proven DISCOVER base + the deep producers STRICT (required=True — deep_ideation
    guarantees the full artifact set; a missing deep worker bundle BLOCKs rather than degrades)."""
    paths, report = new_direction._discover_dets(run_dir, ts, new_direction._load_bundle(run_dir, "DISCOVER"))
    dpaths, frag = _deep_ideate.deep_discover_producers(run_dir, ts, required=True)
    report.update(frag)
    return paths + dpaths, report


def _ideate_dets(run_dir, ts) -> tuple:
    """new_direction's proven IDEATE base (dedup -> tournament -> collision gate -> /idea-bet menu) +
    experiment sketches + idea lineage, STRICT (required=True)."""
    paths, report = new_direction._ideate_dets(run_dir, ts, new_direction._load_bundle(run_dir, "IDEATE"))
    dpaths, frag = _deep_ideate.deep_ideate_producers(run_dir, ts, required=True)
    report.update(frag)
    return paths + dpaths, report


def _report(run_dir, ts) -> tuple:
    """new_direction's honest report-note + the REPORT-stage aggregation (scorecard + integrity + eval)."""
    paths, report = new_direction._report(run_dir, ts)
    paths += _deep_ideate.produce_report_quality(run_dir, ts)
    return paths, report


def run_dets(run_dir, stage, ts) -> tuple:
    """Run the deterministic producers/gates for a stage. Raises GateBlock on a hard-gate refusal,
    ValueError on an unknown stage (the wiring test asserts this)."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "IDEATE":
        return _ideate_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"deep_ideation has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop (same path as new_direction): ('ok', (paths, report)) or ('retry', feedback)."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))


def menu(run_dir) -> list:
    """The ranked idea_backlog (the /idea-bet menu) — produced by the shared IDEATE base."""
    return new_direction.menu(run_dir)


def cut_for_prior_art(run_dir) -> list:
    """Ideas cut before the menu for an evidenced prior-art collision (shown alongside menu())."""
    return new_direction.cut_for_prior_art(run_dir)
