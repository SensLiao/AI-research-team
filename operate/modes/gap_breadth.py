"""Operate recipe for the `gap_breadth` mode (DISCOVER -> REPORT) — audit B3 wiring.

The differentiation engine's focused scan, with the 5-hunter taxonomy REALLY parallel for the
first time in the operated path: `llm_step` returns FIVE independent hunter workers (the audit's
W4 finding was that the flagship consolidated them into one mind — here each hunter is its own
dispatch, so the diversity is structural, not prompt-discipline):

    future-work-miner          -> stated_open_problem signals          (gap ids FW-*)
    weakness-spotter           -> methodological_gap signals           (gap ids WK-*)
    white-space-mapper         -> coverage_gap signals                 (gap ids WS-*)
    cross-domain-transfer-scout-> transfer_gap signals                 (gap ids XF-*)
    contrarian-angle-generator -> assumption_gap signals               (gap ids CA-*)

Deterministic dets: merge the five bundles -> north-star drift gate -> vault-slug referential
integrity -> classify (7-type, fail-loud) -> novelty (SCORE-ONLY, retrieval-grounded when the
pre-search bundle exists) -> cross-run project memory. record_only gate (cheap scan, no
commitment) — the director acts on it by starting a `new_direction` run, never auto.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.classify_gap import build_classification
from ...tools.novelty_aggregate import aggregate_novelty
from ...tools.project_memory import (
    append_gap_inventory,
    load_gap_inventory,
    prior_overlaps,
    workspace_for_run,
)

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

# hunter name -> (gap-id prefix, the lens, the signal fields that set its gap type)
HUNTERS = {
    "future-work-miner": ("FW", "stated future work / limitations the authors themselves name",
                          'set `statement` + `source_ref`; derived_from ["future_work"]'),
    "weakness-spotter": ("WK", "methodological weaknesses that are improvement opportunities",
                         'set `locus` + `opportunity`; derived_from ["weakness_opportunity"]'),
    "white-space-mapper": ("WS", "coverage white space — combinations/settings nobody touched",
                           'set `white_space_present:true`; derived_from ["white_space_present"]'),
    "cross-domain-transfer-scout": ("XF", "methods proven elsewhere, untried in this domain",
                                    'set `source_domain` + `target_hook`; derived_from ["transfer_potential"]'),
    "contrarian-angle-generator": ("CA", "assumptions everyone shares that may be wrong",
                                   'set `challenged_assumption`; derived_from ["contrarian_angle"]'),
}

HUNTER_PROMPT = """You are the {hunter} of a research machine — ONE of five independent gap hunters \
scanning a real knowledge vault in parallel. Your lens (hunt ONLY this): {lens}.

    REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/papers/` (glob the .md pages relevant to the request; read \
~8-12 fully). IF `{run_dir}/inbox/search-results.json` exists, use its live-retrieval records to \
avoid proposing gaps recent literature already closed.

HONESTY (hard): reference papers ONLY by their real `[[slug]]`; never invent a slug (a deterministic \
gate checks every slug against the vault). Ground every signal in what a page actually states. Stay \
inside YOUR lens — the other four hunters cover the rest; overlap wastes the panel's diversity.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit \
the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json):
{{
  "signals": [{{"gap_id":"{prefix}-1","statement":"<the gap, one sharp sentence>",
     "source_ref":"[[<slug>]]","evidence_ref":["[[<slug>]]"],
     {type_fields_hint}}}]
}}
Quantities: 2-4 signals, ids {prefix}-1.. ; field discipline: {type_fields}. \
After writing, verify valid JSON. Return one line: pages read + your sharpest gap."""

_TYPE_FIELDS_HINT = '"derived_from":["<your lens tag>"], "...type-setting fields per your lens..."'


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit H5/M1)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def _bundle_path(run_dir, hunter: str) -> Path:
    return Path(run_dir) / "inbox" / f"DISCOVER.{hunter}.bundle.json"


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """DISCOVER returns FIVE independent hunter workers (spawn them in parallel — each is blind
    to the others; the diversity is structural). REPORT is deterministic."""
    if stage != "DISCOVER":
        return None
    ns_block = _shared.north_star_block(run_dir)
    workers = []
    for hunter, (prefix, lens, type_fields) in HUNTERS.items():
        out = str(_bundle_path(run_dir, hunter)).replace("\\", "/")
        workers.append({
            "label": hunter, "model": _worker_model(model_policy), "output": out,
            "prompt": HUNTER_PROMPT.format(hunter=hunter, lens=lens, request=request,
                                           north_star=ns_block, vault=vault, run_dir=run_dir,
                                           out=out, prefix=prefix, type_fields=type_fields,
                                           type_fields_hint=_TYPE_FIELDS_HINT)})
    return {"label": "gap-hunter-panel", "workers": workers,
            "note": "spawn all FIVE hunters in parallel; each writes its own bundle; then run-dets"}


def _load_hunter_bundles(run_dir) -> dict:
    bundles, missing = {}, []
    for hunter in HUNTERS:
        p = _bundle_path(run_dir, hunter)
        if not p.exists():
            missing.append(hunter)
            continue
        bundles[hunter] = json.loads(p.read_text(encoding="utf-8"))
    if missing:
        raise GateBlock(
            f"gap_breadth DISCOVER: hunter bundle(s) missing for {missing} — spawn ALL five "
            "hunters (see llm_step) before run-dets; the panel's diversity is structural")
    return bundles


def _discover_dets(run_dir, ts) -> tuple:
    bundles = _load_hunter_bundles(run_dir)
    paths = []
    signals, per_hunter = [], {}
    for hunter, b in bundles.items():
        _shared.require_bundle_keys(b, ("signals",), stage="DISCOVER", mode=f"gap_breadth[{hunter}]")
        hs = [s for s in b["signals"] if isinstance(s, dict)]
        per_hunter[hunter] = len(hs)
        signals += hs
    if not signals:
        raise GateBlock("gap_breadth DISCOVER: all five hunters returned zero signals — nothing to classify")

    # NORTH-STAR drift gate over the merged panel output (audit H2).
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts,
                                      [str(s.get("statement") or "") for s in signals])
    paths.append(dpath)

    # Vault-slug referential integrity (audit H3): no hunter may invent a page.
    root = _shared.resolve_vault_root(DEFAULT_VAULT)
    refs = []
    for s in signals:
        refs += [str(s.get("source_ref") or "")] + [str(r) for r in (s.get("evidence_ref") or [])]
    violations, warnings = _shared.check_referential_integrity(
        [r for r in refs if r], known_ids=set(), vault_slug_set=_shared.vault_slugs(root))
    if violations:
        raise GateBlock(f"vault-slug integrity BLOCK: {violations}")

    gc = build_classification(signals)                       # fail-loud: a gap never silently vanishes
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))

    records = _shared.search_records(run_dir)
    ns_signals = _shared.novelty_signals_from_search(gc["gaps"], records)
    nv = aggregate_novelty(gc["gaps"], signals=ns_signals)   # SCORE-ONLY, never a cut
    paths.append(write_artifact(run_dir, "DISCOVER", "novelty-score.artifact.json",
                                "novelty_score", "novelty-scorer", nv, ts))

    overlaps = []
    ws = workspace_for_run(run_dir)
    if ws is not None:
        run_id = _shared.task_frame(run_dir)["payload"]["task_id"]
        overlaps = prior_overlaps(gc["gaps"], load_gap_inventory(ws), run_id=run_id)
        append_gap_inventory(ws, run_id, ts, gc["gaps"])

    report = {"signals_per_hunter": per_hunter, "gaps_classified": len(gc["gaps"]),
              "novelty_grounded": bool(records), "prior_gap_overlaps": overlaps,
              "slug_warnings": warnings}
    if not records:
        report["note"] = "novelty is vault-only (no pre-search bundle) — `operate pre-search` grounds it"
    return paths, report


def _report(run_dir, ts) -> tuple:
    note = {"summary": "gap_breadth scan: five independent hunters -> 7-type classification -> "
                       "score-only novelty; act on it by starting a new_direction run (director's call)",
            "references": ["evidence/DISCOVER/gap-classification.artifact.json",
                           "evidence/DISCOVER/novelty-score.artifact.json"],
            "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"gap_breadth has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop — a hunter's gate feedback re-dispatches only what failed."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
