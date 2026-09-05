"""Operate recipe for the `gap_scan` mode (DISCOVER -> REPORT) — wave-2 absorption.

The lightweight sibling of `gap_breadth`: TWO mutually-blind hunters instead of five, no
prosecution/closure, no mechanism dossiers, no quality audit, no novelty score. gap_scan answers a
narrower question fast — "what candidate gaps exist and what evidence do they already have" — and
explicitly makes NO novelty claim and NO bet recommendation (that is `deep_ideation`'s job, gated by
the novelty-collision check; a prosecuted, closure-verified version is `gap_breadth`).

Pipeline (registry `minimum_worker_pipeline`, `_panel_recipe` §3):
  1. parallel_gap_hunt      future-work-miner + weakness-spotter, dispatched in the SAME wave with no
                            `depends_on` between them and prompts that never name the other's bundle
                            path — structurally blind, not prompt-discipline-blind (mirrors gap_breadth's
                            audit W4 fix).
  2. classify_and_deduplicate  gap-classifier reads BOTH frozen bundles, merges duplicate findings into
                            one signal each (union of evidence_ref, union of derived_from), and must
                            preserve every raw hunter anchor into the merged set (never silently drop
                            one) — enforced by a DETERMINISTIC evidence-coverage check below, not by
                            trusting the worker's word for it. `classify_gap.build_classification`
                            (already engine-tested; see registry evidence_refs) then TYPES every merged
                            signal by field presence and fails loud on an identified-but-unclassifiable
                            one (a real gap can never silently vanish).
  3. render_markdown        deterministic (`_panel_recipe.render_director_markdown`), never a dispatched
                            `synthesis-writer` — see `_panel_recipe`'s design note #2.

Two mode-specific hard gates close the productization gaps the registry names explicitly:
  - evidence coverage: every source_ref/evidence_ref a hunter actually produced must appear in at
    least one gap-classifier signal's evidence_ref, or the run BLOCKs (no candidate may be dropped
    during merge).
  - deterministic dedup: gap-classifier's signals are run through the AI-Researcher-style lexical
    dedup (`tools.idea_dedup`) — a near-duplicate pair the worker failed to merge BLOCKs.

Plus the three gates every wave-2 mode inherits via `_panel_recipe.common_gates` (north-star drift,
citation existence — NOT_APPLICABLE here, gap_scan cites no evidence_table/claim_evidence_map shape and
explicitly defers citation verification to `evidence_review` — and referential integrity: a
gap-classifier signal cannot cite an anchor no hunter produced and no vault page confirms).
"""
from __future__ import annotations

from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, write_artifact
from ...tools.classify_gap import build_classification
from ...tools.idea_dedup import DEFAULT_THRESHOLD, dedupe_ideas

MODE = "gap_scan"
STAGES = _panel_recipe.stage_path(MODE)          # ["DISCOVER", "REPORT"]
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

# (label, bundle_key, depends_on) — the ONLY roster this recipe dispatches or loads. Bundle loading
# needs label+bundle_key+depends_on only (never `.prompt`); dispatch additionally fills `.prompt`.
_SEAT_TABLE = (
    ("future-work-miner", "future_work_items", ()),
    ("weakness-spotter", "weakness_report", ()),
    ("gap-classifier", "gap_signals", ("future-work-miner", "weakness-spotter")),
)
_ALLOWED_DERIVED_FROM = frozenset({"future_work", "weakness_opportunity"})
_DEDUP_THRESHOLD = DEFAULT_THRESHOLD


FUTURE_WORK_PROMPT = """You are the future-work-miner — ONE of two independent gap hunters in the \
gap_scan panel. You are mutually BLIND to the weakness-spotter: you must not read its bundle, and your \
output must not depend on anything it might find. Your lens ONLY: explicitly stated open problems / \
"future work" / limitations the AUTHORS THEMSELVES name in the literature — never a methodological \
weakness you notice yourself (that is the other hunter's lens; stay out of it, overlap wastes the \
panel's diversity).

    REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/` (glob the pages relevant to the request; read the most \
relevant ones fully). IF `{run_dir}/inbox/search-results.json` exists, also use its live-retrieval \
records as additional candidate sources. You have no weakness-spotter or gap-classifier bundle to \
read — you run first, blind, in parallel with the other hunter.

HONESTY (hard): reference vault pages only by their real `[[slug]]`; never invent a slug (a \
deterministic gate checks every slug against the vault). An external paper may use a resolvable \
`doi:...` or `arXiv:...` id only when that exact record already exists in search-results.json or is \
one you actually read. Quote or closely paraphrase what the source ACTUALLY says is unresolved — never \
fabricate a statement. A clean, exhaustively-covered literature set may legitimately yield ZERO items; \
report that honestly rather than inventing one.

WORDING-SHELL ADVISORY (flag, never block)
Before emitting a gap, read your own sentence back. If it uses a generic research-question shell — \
"exploring the impact of X on Y", "investigating the effect of A on B", "a study of X in the context \
of Y", "improving X for Y" — flag it in `wording_advisory` on that item. This is NOT a judgment that \
the gap is bad or generic; it flags only the wording shell. Then answer one question in the same \
field: what term, mechanism, site, or tension would a specialist in this field use instead? Rewriting \
into domain-native terms is encouraged; keeping the original phrasing is also legitimate if it matches \
how the target literature frames it. Never drop a gap because of its wording.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}` (ends in .bundle.json, NOT .artifact.json):
{{"future_work_items": {{"items": [
  {{"item_id":"FW-1","statement":"<the stated open problem or future-work direction, verbatim or \
closely paraphrased>","source_ref":"[[<slug>]] or doi:<doi> or arXiv:<id>",
   "gap_hint":"<optional: what kind of gap this looks like>","tags":["<optional topic tag>"],
   "wording_advisory":"<the shell you spotted + the domain-native term a specialist would use, or omit>"}}
]}}}}
Quantity is a FLOOR with NO upper bound: emit EVERY defensible future-work statement you find — never \
trim a legitimate one to keep the list short. Every item needs a real, non-blank source_ref (anti-slop \
— a blank pointer is not evidence). After writing, verify valid JSON. Return one line: pages read + \
item count."""

WEAKNESS_PROMPT = """You are the weakness-spotter — ONE of two independent gap hunters in the gap_scan \
panel. You are mutually BLIND to the future-work-miner: you must not read its bundle, and your output \
must not depend on anything it might find. Your lens ONLY: methodological weaknesses YOU identify in \
the surveyed work — a weak evaluation protocol, an unfair baseline, a confound, a missing ablation, \
etc. — never a statement the authors themselves already flagged as future work (that is the other \
hunter's lens; stay out of it, overlap wastes the panel's diversity).

    REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/` (glob the pages relevant to the request; read the most \
relevant ones fully). IF `{run_dir}/inbox/search-results.json` exists, also use its live-retrieval \
records as additional candidate sources. You have no future-work-miner or gap-classifier bundle to \
read — you run first, blind, in parallel with the other hunter.

HONESTY (hard): reference vault pages only by their real `[[slug]]`; never invent a slug. An external \
paper may use a resolvable `doi:...` or `arXiv:...` id only when that exact record already exists in \
search-results.json or is one you actually read. Every weakness needs BOTH a concrete `locus` (WHERE \
the weakness is — protocol, baseline, dataset, metric...) and a concrete `opportunity` (what new work \
it opens up), grounded in what you actually read; never fabricate either. A clean, well-evaluated \
literature set may legitimately yield ZERO weaknesses; report that honestly rather than inventing one.

WORDING-SHELL ADVISORY (flag, never block)
Before emitting a gap, read your own sentence back. If it uses a generic research-question shell — \
"exploring the impact of X on Y", "investigating the effect of A on B", "a study of X in the context \
of Y", "improving X for Y" — flag it in `wording_advisory` on that item. This is NOT a judgment that \
the gap is bad or generic; it flags only the wording shell. Then answer one question in the same \
field: what term, mechanism, site, or tension would a specialist in this field use instead? Rewriting \
into domain-native terms is encouraged; keeping the original phrasing is also legitimate if it matches \
how the target literature frames it. Never drop a gap because of its wording.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}` (ends in .bundle.json, NOT .artifact.json):
{{"weakness_report": {{"weaknesses": [
  {{"gap_id":"WK-1","locus":"<where the weakness is>","opportunity":"<the opening it creates for new \
research>","evidence_ref":["[[<slug>]] or doi:<doi> or arXiv:<id>"],
   "severity":"major|minor","source_ref":"<optional direct source ref>",
   "wording_advisory":"<the shell you spotted + the domain-native term a specialist would use, or omit>"}}
]}}}}
Quantity is a FLOOR with NO upper bound: emit EVERY defensible weakness you find — never trim a \
legitimate one to keep the list short. Every weakness needs >=1 real, non-blank evidence_ref (anti-slop \
— a blank pointer is not evidence). After writing, verify valid JSON. Return one line: pages read + \
weakness count."""

CLASSIFY_PROMPT = """You are the gap-classifier. You did NOT hunt for gaps yourself — future-work-miner \
and weakness-spotter already did, blind to each other, and are now frozen. Your job is to MERGE and \
DEDUPLICATE their two independent candidate sets into one clean signal list — never invent a new \
candidate, never silently drop one of theirs, never judge novelty, never recommend a bet.

    REQUEST: {request}

{north_star}

Read BOTH frozen hunter bundles (their real paths):
  - `{fw_path}`  (future_work_items — each item: item_id, statement, source_ref)
  - `{wk_path}`  (weakness_report — each item: gap_id, locus, opportunity, evidence_ref)

TASK:
1. Walk every item in both bundles. When TWO items from the two different hunters describe the SAME \
underlying gap, MERGE them into ONE signal: keep the classifying fields from BOTH origins (statement + \
source_ref AND locus + opportunity, whichever apply), UNION their evidence_ref pointers, and set \
`derived_from` to list every provenance tag that applies (`future_work` for a future-work-miner origin, \
`weakness_opportunity` for a weakness-spotter origin — these are the ONLY two valid tags in this panel).
2. Every item with NO duplicate carries over as its OWN signal, substance unchanged, `derived_from` \
naming its single origin.
3. NEVER drop an item silently: every source_ref / evidence_ref pointer that appears in EITHER hunter \
bundle must appear in the evidence_ref of AT LEAST ONE signal you emit — a downstream deterministic \
gate checks this exactly and BLOCKs on any dropped anchor.
4. Assign each signal a fresh, unique `gap_id` (GAP-1, GAP-2, ...). Never reuse a hunter's own \
item_id/gap_id verbatim as your signal's gap_id — they are different id spaces.
5. You do NOT decide gap_type or reason_code — a deterministic classifier derives those from the \
fields you set.

HONESTY (hard): never invent an evidence_ref that is not already present in one of the two frozen \
bundles; a thin candidate set is reported thin, never padded with a merge that is not real.

COVERAGE-DISTRIBUTION ADVISORY (signal, never a defect)
Report the distribution of the evidence the panel actually used across three dimensions — publication \
year, method family, and venue/community — as `distribution_advisory` at the top level of your bundle. \
Where one bucket holds >=80% of the sources, name the concentration with its fraction and state the \
SEARCH RESPONSE that would balance it (e.g. backward citation chaining to the foundational work, adding \
a qualitative/mechanistic query, querying a different community's vocabulary). This is a \
coverage-distribution signal, not a defect: the evidence base stays valid and nothing is blocked. The \
question it asks is only whether the corpus distribution matches the question being asked.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names (e.g. a named \
dropped anchor, or a named near-duplicate pair), change nothing else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json, NOT .artifact.json):
{{"gap_signals": {{"signals": [
  {{"gap_id":"GAP-1","statement":"<carried from a future-work item, or omit if none>",
   "source_ref":"<carried from a future-work item, or omit if none>",
   "locus":"<carried from a weakness item, or omit if none>",
   "opportunity":"<carried from a weakness item, or omit if none>",
   "evidence_ref":["<every anchor from every item this signal represents>"],
   "derived_from":["future_work","weakness_opportunity"],
   "notes":"<optional: one line on why these were merged, omit for a standalone signal>"}}
]}}}}
Quantity is driven ONLY by the two hunters' real output: merge duplicates down, but never truncate a \
distinct signal to keep the list short. After writing, verify valid JSON. Return one line: signals \
emitted + how many were merges."""


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, **funnel_kwargs) -> str:
    """Live-retrieval pre-step (DISCOVER entry mode; audit H5/M1)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries,
                              **funnel_kwargs)


#: Per-seat model tier (2026-08-07). The two hunters DECIDE what counts as an open gap and everything
#: downstream inherits that judgment, so they are `audit` (-> opus). The classifier only merges and
#: deduplicates two frozen sets under an explicit rule — that is scoped execution, so `tool` (-> sonnet).
#: The tier must be identical in both seat builders or the loading roster and the dispatch roster
#: disagree about the same seat.
_SEAT_TIERS = {
    "future-work-miner": "audit",
    "weakness-spotter": "audit",
    "gap-classifier": "tool",
}


def _seats_for_load() -> list:
    """Roster for BUNDLE LOADING — prompt text is dispatch-only and irrelevant here."""
    return [_panel_recipe.Seat(label=label, prompt="", bundle_key=key,
                               tier=_SEAT_TIERS[label], depends_on=deps)
            for label, key, deps in _SEAT_TABLE]


def _seats_for_dispatch(run_dir: str, request: str, vault: str) -> list:
    """The same roster, with real hand-written prompts filled in for llm_step."""
    north_star = _shared.north_star_block(run_dir)
    outputs = {label: _panel_recipe.bundle_path(run_dir, "DISCOVER", label)
               for label, _key, _deps in _SEAT_TABLE}
    prompts = {
        "future-work-miner": FUTURE_WORK_PROMPT.format(
            request=request, north_star=north_star, vault=vault, run_dir=run_dir,
            out=outputs["future-work-miner"]),
        "weakness-spotter": WEAKNESS_PROMPT.format(
            request=request, north_star=north_star, vault=vault, run_dir=run_dir,
            out=outputs["weakness-spotter"]),
        "gap-classifier": CLASSIFY_PROMPT.format(
            request=request, north_star=north_star, run_dir=run_dir,
            out=outputs["gap-classifier"], fw_path=outputs["future-work-miner"],
            wk_path=outputs["weakness-spotter"]),
    }
    return [_panel_recipe.Seat(label=label, prompt=prompts[label], bundle_key=key,
                               tier=_SEAT_TIERS[label], depends_on=deps)
            for label, key, deps in _SEAT_TABLE]


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """DISCOVER: two blind hunters (wave 1) then gap-classifier (wave 2). REPORT is deterministic."""
    if stage == "DISCOVER":
        seats = _seats_for_dispatch(run_dir, request, vault)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats,
            panel_note="Wave 1: future-work-miner and weakness-spotter run blind to each other — "
                       "spawn both before either sees the other's bundle. Wave 2: gap-classifier "
                       "reads BOTH frozen bundles, merges duplicates, and binds evidence anchors "
                       "before deterministic classify_gap typing. No novelty or bet claim.",
            model_policy=model_policy)
    return None  # REPORT is deterministic


# --------------------------------------------------------------------------- deterministic checks

def _validate_future_work_items(items: list) -> None:
    for index, item in enumerate(items):
        for field in ("item_id", "statement", "source_ref"):
            if not str(item.get(field) or "").strip():
                raise GateBlock(
                    f"{MODE} DISCOVER: future-work-miner item[{index}] is missing a non-blank {field!r}")


def _validate_weaknesses(weaknesses: list) -> None:
    for index, weakness in enumerate(weaknesses):
        for field in ("gap_id", "locus", "opportunity"):
            if not str(weakness.get(field) or "").strip():
                raise GateBlock(
                    f"{MODE} DISCOVER: weakness-spotter weakness[{index}] is missing a non-blank {field!r}")
        if not [r for r in (weakness.get("evidence_ref") or []) if str(r).strip()]:
            raise GateBlock(
                f"{MODE} DISCOVER: weakness-spotter weakness[{index}] has no evidence_ref anchor")


def _validate_signals(signals: list) -> None:
    for index, signal in enumerate(signals):
        gap_id = str(signal.get("gap_id") or "").strip()
        if not gap_id:
            raise GateBlock(
                f"{MODE} DISCOVER: gap-classifier signal[{index}] is missing a non-blank gap_id")
        if not [r for r in (signal.get("evidence_ref") or []) if str(r).strip()]:
            raise GateBlock(
                f"{MODE} DISCOVER: gap-classifier signal {gap_id!r} has no evidence_ref anchor — "
                "every candidate gap needs at least one source anchor")
        bad_provenance = sorted(set(signal.get("derived_from") or []) - _ALLOWED_DERIVED_FROM)
        if bad_provenance:
            raise GateBlock(
                f"{MODE} DISCOVER: gap-classifier signal {gap_id!r} claims derived_from "
                f"{bad_provenance}, but gap_scan only runs future-work-miner and weakness-spotter")


def _raw_anchor_set(items: list, weaknesses: list) -> set:
    """Every source anchor the two blind hunters actually produced — the evidence-coverage floor."""
    anchors: set = set()
    for item in items:
        ref = str(item.get("source_ref") or "").strip()
        if ref:
            anchors.add(ref)
    for weakness in weaknesses:
        for ref in (weakness.get("evidence_ref") or []):
            ref = str(ref).strip()
            if ref:
                anchors.add(ref)
        src = str(weakness.get("source_ref") or "").strip()
        if src:
            anchors.add(src)
    return anchors


def _signal_anchor_set(signals: list) -> set:
    anchors: set = set()
    for signal in signals:
        for ref in (signal.get("evidence_ref") or []):
            ref = str(ref).strip()
            if ref:
                anchors.add(ref)
    return anchors


def _classifying_text(signal: dict) -> str:
    parts = [str(signal.get("statement") or ""), str(signal.get("locus") or ""),
             str(signal.get("opportunity") or "")]
    return " ".join(p for p in parts if p.strip())


def _check_no_duplicate_signals(signals: list) -> None:
    """Deterministic dedup gate (AI-Researcher lexical dedup, reused from tools.idea_dedup).

    gap-classifier must MERGE the two blind hunters' overlapping candidates, not just concatenate
    them. Two signals whose classifying text is near-identical is exactly what an unmerged
    duplicate looks like — this is the "define deterministic deduplication" productization gap.
    """
    if len(signals) < 2:
        return
    pseudo = [{"idea_id": str(signal.get("gap_id")), "summary": _classifying_text(signal)}
              for signal in signals]
    try:
        result = dedupe_ideas(pseudo, threshold=_DEDUP_THRESHOLD, text_key="summary")
    except ValueError as exc:
        raise GateBlock(f"{MODE} DISCOVER dedup precheck BLOCK: {exc}") from exc
    if result["merged"]:
        raise GateBlock(
            f"{MODE} DISCOVER dedup BLOCK: gap-classifier's signal set still has near-duplicate "
            f"candidate(s) it failed to merge (lexical similarity >= {_DEDUP_THRESHOLD}): "
            f"{result['merged']} — merge duplicate hunter findings into ONE signal before "
            "classification, do not list the same gap twice")


def _gap_summary(gap: dict, signal_by_id: dict) -> str:
    signal = signal_by_id.get(str(gap.get("gap_id") or "")) or {}
    statement = str(signal.get("statement") or "").strip()
    if statement:
        return statement
    locus = str(signal.get("locus") or "").strip()
    opportunity = str(signal.get("opportunity") or "").strip()
    if locus and opportunity:
        return f"{locus} — {opportunity}"
    notes = str(gap.get("notes") or "").strip()
    return notes or f"(no summary text; reason_code={gap.get('reason_code')})"


def _render_sections(run_dir, items: list, weaknesses: list, gc: dict,
                     signal_by_id: dict, frag: dict) -> dict:
    ns = _shared.north_star(run_dir)
    records = _shared.search_records(run_dir)
    in_scope = ", ".join(ns["in_scope"]) if ns["in_scope"] else "(none declared)"
    out_scope = ", ".join(ns["out_of_scope"]) if ns["out_of_scope"] else "(none declared)"
    search_scope = "\n".join([
        f"Direction: {ns['statement']}",
        f"In scope: {in_scope}",
        f"Out of scope: {out_scope}",
        f"future-work-miner mined {len(items)} item(s); weakness-spotter found {len(weaknesses)} "
        "weakness(es) — the two hunters ran blind to each other.",
        ("A live-retrieval bundle (search-results.json) was available to both hunters this run."
         if records else "No live-retrieval bundle for this run — scope is vault-only."),
    ])

    gaps = gc.get("gaps") or []
    if not gaps:
        candidate_gaps = (
            f"None — {len(items)} future-work item(s) and {len(weaknesses)} weakness(es) were "
            "surveyed and gap-classifier merged them into zero classified candidates.")
        evidence_section = "None — no candidate gaps were classified, so no source anchors apply."
        classification_section = "None — zero classified gaps; no taxonomy breakdown to report."
    else:
        gap_rows, evidence_rows = [], []
        by_type: dict = {}
        for gap in gaps:
            gid = str(gap["gap_id"])
            gap_rows.append(f"- **{gid}** (`{gap['gap_type']}`): {_gap_summary(gap, signal_by_id)}")
            refs = ", ".join(str(r) for r in (gap.get("evidence_ref") or [])) or "(none)"
            evidence_rows.append(f"- **{gid}**: {refs}")
            by_type.setdefault(gap["gap_type"], []).append(gid)
        candidate_gaps = "\n".join(gap_rows)
        evidence_section = "\n".join(evidence_rows)
        classification_section = "\n".join(
            f"- `{gap_type}` — {len(ids)}: {', '.join(sorted(ids))}"
            for gap_type, ids in sorted(by_type.items()))

    unknowns = []
    if not records:
        unknowns.append(
            "No live-retrieval pre-search ran this run — recent literature outside the vault is "
            "unchecked; run `pre-search` before this scan to widen coverage.")
    unknowns.append(
        "External references (DOI/arXiv ids, if any) were NOT existence-verified in this "
        "lightweight scan — route surviving candidates to evidence_review for per-claim citation "
        "verification.")
    if frag.get("referential_warnings"):
        unknowns.append(
            f"{frag['referential_warnings']} vault-slug reference(s) could not be checked this "
            "run (vault unreachable) — re-verify against the live vault before citing them.")
    unknowns.append(
        "This is a lightweight candidate scan only: it makes NO novelty claim and NO bet "
        "recommendation. Route surviving candidates to deep_ideation (collision-gated novelty + "
        "betting menu) or gap_breadth (prosecuted closure + mechanism dossiers) before committing "
        "research effort.")
    unknowns_section = "\n".join(f"- {line}" for line in unknowns)

    return {
        "Search scope": search_scope,
        "Candidate gaps": candidate_gaps,
        "Evidence and source anchors": evidence_section,
        "Gap classification": classification_section,
        "Unknowns and next searches": unknowns_section,
    }


def _discover_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "DISCOVER", MODE, _seats_for_load())
    fw, wk, gs = bundles["future_work_items"], bundles["weakness_report"], bundles["gap_signals"]

    _shared.require_bundle_keys(fw, ("items",), stage="DISCOVER", mode=f"{MODE}[future-work-miner]")
    _shared.require_bundle_keys(wk, ("weaknesses",), stage="DISCOVER", mode=f"{MODE}[weakness-spotter]")
    _shared.require_bundle_keys(gs, ("signals",), stage="DISCOVER", mode=f"{MODE}[gap-classifier]")

    items = [i for i in (fw.get("items") or []) if isinstance(i, dict)]
    weaknesses = [w for w in (wk.get("weaknesses") or []) if isinstance(w, dict)]
    signals = [s for s in (gs.get("signals") or []) if isinstance(s, dict)]

    _validate_future_work_items(items)
    _validate_weaknesses(weaknesses)
    _validate_signals(signals)

    # productization gap 1: preserve independent hunter outputs before classification.
    raw_anchors = _raw_anchor_set(items, weaknesses)
    signal_anchors = _signal_anchor_set(signals)
    dropped = sorted(raw_anchors - signal_anchors)
    if dropped:
        raise GateBlock(
            f"{MODE} DISCOVER evidence-coverage BLOCK: gap-classifier dropped hunter anchor(s) "
            f"{dropped} — every independent hunter finding must be carried into a classified "
            "signal (merged or standalone), never silently discarded")

    # productization gap 2: deterministic deduplication.
    _check_no_duplicate_signals(signals)

    # the REAL, already engine-tested deterministic core — fails loud on an identified-but-
    # unclassifiable signal (a real gap can never silently vanish).
    try:
        gc = build_classification(signals)
    except ValueError as exc:
        raise GateBlock(f"{MODE} DISCOVER classification BLOCK: {exc}") from exc
    if signals and not gc["gaps"]:
        raise GateBlock(f"{MODE} DISCOVER: {len(signals)} signal(s) submitted but zero classified")

    downstream_refs = sorted({str(r).strip() for gap in gc["gaps"]
                              for r in (gap.get("evidence_ref") or []) if str(r).strip()})

    # the three shared wave-2 gates: north-star drift, citation existence (NOT_APPLICABLE — gap_scan
    # defers citation verification to evidence_review), referential integrity (a classifier signal
    # cannot cite an anchor no hunter produced and no vault page confirms).
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "DISCOVER", ts, mode=MODE,
        bundles={"future_work_items": fw, "weakness_report": wk, "gap_signals": gs},
        downstream_refs=downstream_refs, known_ids=raw_anchors)

    paths = list(gate_paths)
    paths.append(write_artifact(run_dir, "DISCOVER", "future-work-items.artifact.json",
                                "future_work_items", "future-work-miner", fw, ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "weakness-report.artifact.json",
                                "weakness_report", "weakness-spotter", wk, ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))

    signal_by_id = {str(s.get("gap_id")): s for s in signals}
    sections = _render_sections(run_dir, items, weaknesses, gc, signal_by_id, frag)
    director_md = _panel_recipe.render_director_markdown(run_dir, MODE, sections, ts=ts)

    report = {
        "future_work_items": len(items), "weaknesses": len(weaknesses),
        "signals_classified": len(signals), "gaps_classified": len(gc["gaps"]),
        "gap_types": sorted({g["gap_type"] for g in gc["gaps"]}),
        "existence_gate": frag.get("existence_gate"),
        "referential_integrity": frag.get("referential_integrity"),
        "referential_warnings": frag.get("referential_warnings"),
        "director_gap_scan": director_md,
    }
    return paths, report


def _report(run_dir, ts) -> tuple:
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary="gap_scan: two mutually-blind hunters (future-work-miner, weakness-spotter) mined "
                "independent candidates; gap-classifier merged duplicates and bound evidence "
                "anchors; classify_gap deterministically typed every survivor into the director "
                "gap-scan brief. record_only — no novelty claim, no bet.",
        references=["director-review/gaps/gap-scan.md",
                    "evidence/DISCOVER/future-work-items.artifact.json",
                    "evidence/DISCOVER/weakness-report.artifact.json",
                    "evidence/DISCOVER/gap-classification.artifact.json"])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
