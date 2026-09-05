"""Operate recipe for the `aers_enhanced_research_pack` mode (DISCOVER -> DESIGN -> EXECUTE ->
ANALYZE -> VERIFY -> REPORT) — wave-2 panel recipe built on `_panel_recipe`.

Assembles a REFERENCE-ONLY AERS-enhanced research package: which cataloged AERS reference packs
apply, a grounded literature-search strategy, a data-wrangling protocol, a reproducibility-materials
audit, the literature's benchmark-evidence landscape, a submission checklist, an independent
bibliography verification, and traceable manuscript-polish recommendations.

Registry stage grouping vs. this recipe's FSM mapping (`minimum_worker_pipeline` names 5 internal
groups; the FSM has 6 stages after REPORT is excluded — this recipe distributes the 8 declared seats
across the 5 dispatching stages so every stage carries real, well-scoped work):

  DISCOVER curate_references_and_search : aers-sop-curator, literature-search-strategist
  DESIGN   (data half of) audit_data_and_reproducibility : data-wrangling-auditor
  EXECUTE  (packaging/audit half) : reproducibility-packager, benchmark-evidence-auditor
  ANALYZE  (submission/bibliography half of) audit_benchmarks_and_submission :
           submission-guideline-scout, bibliography-validator
  VERIFY   polish_manuscript (+ deterministic render_markdown) : manuscript-polish-editor

Two honesty boundaries the registry calls out explicitly are load-bearing here:

  * EXECUTE is packaging/audit work, never evidence an experiment ran. `_panel_recipe.execution_truth`
    classifies this run's EXECUTE evidence (always "not-started" in this reference-only mode, since no
    seat ever writes a run-record/journal); `numeric_benchmark_adapter.build_report` is called with
    EMPTY execution inputs so the "no local recomputation happened" fact is a machine-checked artifact
    (verdict=BLOCK, not a recipe failure), never a prose-only claim. Any worker-reported
    `own_measured_metrics` is hard-refused via `refuse_metrics_without_receipt`.
  * The AERS integration plan is a pure function of the (catalog-only, no-child-body-read) AERS
    snapshot, so it is computed DETERMINISTICALLY by `aers_skill_integration_planner.build_plan()` —
    never re-derived or invented by a worker. aers-sop-curator's job is the one thing the tool cannot
    do: judge which mapped packs are actually *applicable* to this project's direction.

Every non-REPORT stage carries the three shared hard gates (`_panel_recipe.common_gates`): north-star
drift always; citation existence + referential integrity whenever a stage's own seats cite a ref
(DESIGN's data protocol cites none, so its evidence_table is honestly NOT_APPLICABLE). The Markdown is
rendered once, in VERIFY (the last content stage), from every stage's already-committed artifacts —
never re-derived from worker prose that a later stage cannot see.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ._panel_recipe import Seat
from . import _panel_recipe
from ..artifacts import GateBlock, write_artifact
from ...tools import aers_skill_integration_planner
from ...tools import numeric_benchmark_adapter

MODE = "aers_enhanced_research_pack"
STAGES = ["DISCOVER", "DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

_DISCOVER_SEAT_KEYS = (
    ("aers-sop-curator", "aers_applicability_note"),
    ("literature-search-strategist", "evidence_search_trace"),
)
_DESIGN_SEAT_KEYS = (
    ("data-wrangling-auditor", "data_protocol"),
)
_EXECUTE_SEAT_KEYS = (
    ("reproducibility-packager", "reproducibility_materials_audit"),
    ("benchmark-evidence-auditor", "benchmark_evidence_note"),
)
_ANALYZE_SEAT_KEYS = (
    ("submission-guideline-scout", "submission_checklist_note"),
    ("bibliography-validator", "bibliography_verification_note"),
)
_VERIFY_SEAT_KEYS = (
    ("manuscript-polish-editor", "manuscript_polish_note"),
)


# --------------------------------------------------------------------------- worker prompts (hand-written)

AERS_CURATOR_PROMPT = """You are aers-sop-curator, a DISCOVER seat of the aers_enhanced_research_pack \
mode: judge which cataloged AERS reference packs actually apply to THIS project.

    REQUEST: {request}

{north_star}

A deterministic, catalog-metadata-only scan has ALREADY mapped every safe AERS reference candidate to \
a RAT stage and a risk lane (reference_pack / human_gate_required / blocked). Read that scan at \
`{snapshot_path}` — it is `by_stage` / `by_sop_pack` counts plus per-candidate `rows`. Never re-derive, \
invent, or override its lane/stage/risk labels; your ONLY job is to judge, for THIS request, which \
mapped sop_packs are actually relevant, and which are not, and why.

Also read the vault at `{vault}/02-wiki/` for this project's real direction so your judgement is \
grounded in the actual research question, not a generic guess.

HONESTY (hard): every sop_pack you call relevant must be a real `sop_pack` value that appears in the \
snapshot's `by_sop_pack` keys; never invent one. If nothing in the snapshot is relevant to this request, \
say so plainly in `body` — that is a legitimate answer, never padded to look thorough.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}`:
{{
  "aers_applicability_note": {{
    "title": "AERS reference applicability for <this request, in your own words>",
    "body": "<which sop_pack(s) from the snapshot are relevant and why; which are not and why; any \
license/risk-lane caveat the director should know>",
    "refs": []
  }}
}}
Quantity is a FLOOR, not a ceiling: judge every sop_pack the snapshot's `by_sop_pack` names as relevant \
or not, and say why; never drop a defensible judgement to stay short. `refs` stays empty — sop_pack \
names belong in `body`, never in a citation list. After writing, verify valid JSON. Return one line: \
how many packs judged relevant + not relevant."""


LITERATURE_STRATEGIST_PROMPT = """You are literature-search-strategist, the other DISCOVER seat: design \
AND run a real (if lightweight) literature-search strategy for this project — a reference-only search \
STRATEGY grounded in at least one real round of reading, not the full saturation review that \
evidence_review performs.

    REQUEST: {request}

{north_star}

Sources you read (by reference, never inlined):
  1. The vault at `{vault}/02-wiki/` — glob the relevant clusters, read the most relevant pages.
  2. IF `{run_dir}/inbox/search-results.json` exists: the live-retrieval bundle from the sanctioned \
connector — read its `evidence_rows` and cite only the ones actually relevant.
  3. If both are thin or off-topic, say so honestly via `stop_reason` — never invent a source or a hit \
to look complete.

HONESTY (hard): every `source_ref` must be a real vault `[[slug]]`, a real DOI/arXiv id, or a real title \
from the live-retrieval bundle — never invented. A thin round is reported as thin (`budget_exhausted` or \
`inconclusive`), never padded with fabricated hits.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "evidence_search_trace": {{
    "search_contract_version": "evidence-search-trace/v1",
    "research_question": "<this request, restated as a search question>",
    "critical_claims": [{{"claim_id": "C1", "question": "<what this pack must get right>",
      "importance": "critical|major|supporting"}}],
    "representativeness_dimensions": ["<dimension you actually checked coverage across, e.g. method, \
dataset, venue>"],
    "rounds": [{{"round_index": 0, "questions": ["<query you actually ran or read for>"],
      "source_hits": [{{"source_ref": "<real ref>"}}], "claim_ids_addressed": ["C1"],
      "contradiction_claim_ids_queried": [], "representativeness_dimensions_queried": [],
      "findings": [{{"finding_id": "F1", "source_refs": ["<real ref>"], "claim_ids": ["C1"],
        "finding_kind": "supportive|contradictory|boundary|null"}}]}}],
    "stop_reason": "semantic_complete|budget_exhausted|source_access_blocked|human_stop|inconclusive",
    "budget_exhausted": false
  }}
}}
Quantity is a FLOOR: cover every critical claim you name with at least one round; never invent a round \
you did not actually run. After writing, verify valid JSON. Return one line: rounds run + sources cited \
+ stop_reason."""


DATA_WRANGLING_PROMPT = """You are data-wrangling-auditor, the DESIGN seat: audit and RECONSTRUCT the \
data-handling protocol this project's direction actually needs (or that the relevant vault notes \
describe) — preprocessing, augmentation, postprocessing, normalization, resampling steps.

    REQUEST: {request}

{north_star}

Read the vault at `{vault}/02-wiki/` for this direction's data contracts/splits where they exist; \
otherwise reconstruct the minimum honest protocol implied by the request itself and say so in `notes`.

HARD ANTI-LEAKAGE RULE (mechanically enforced downstream — get this right): any step you mark \
`"kind": "augmentation"` MUST carry `"train_only": true`. Augmentation reaching validation/test data is \
a leakage bug and WILL be BLOCKED. Steps that are not augmentation may be train_only true or false \
depending on whether they apply to every split.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names — most often a \
`train_only` violation — change nothing else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "data_protocol": {{
    "from_split_manifest_ref": null,
    "steps": [{{"step_id": "s1",
      "kind": "preprocessing|augmentation|postprocessing|normalization|resampling",
      "description": "<real step description>", "train_only": true, "params": {{}},
      "applies_to_splits": []}}],
    "notes": "<caveat about what is reconstructed vs. confirmed from a real source>"
  }}
}}
Quantity is a FLOOR: include every step the direction genuinely needs; never drop a defensible one to \
stay short, and never mark an augmentation step train_only:false. After writing, verify valid JSON. \
Return one line: step count + whether any augmentation step exists."""


REPRODUCIBILITY_PACKAGER_PROMPT = """You are reproducibility-packager, an EXECUTE seat: audit whether \
this direction's target paper(s)/vault materials expose enough code, data, config, and environment \
detail to reproduce or reimplement locally. This is a PACKAGING/AUDIT judgment — you run nothing.

    REQUEST: {request}

{north_star}

Read the vault at `{vault}/02-wiki/` for the relevant paper(s)/notes.

HONESTY (hard): grade availability from what is ACTUALLY documented, never assumed; missing materials \
are listed, never silently skipped.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "reproducibility_materials_audit": {{
    "source_ref": "<real vault slug or paper ref this audit covers>",
    "code_availability": "<what code is actually available, or 'not available'>",
    "data_availability": "<what data is actually available, or 'not available'>",
    "config_availability": "<what config/hyperparameters are documented, or 'not documented'>",
    "environment": "<documented environment/deps, or null>",
    "license_or_access_constraints": ["<real constraint, if any>"],
    "reproduction_steps": ["<step you could actually follow from what is documented>"],
    "missing_materials": ["<what is missing>"],
    "reproducibility_risk": "low|medium|high"
  }}
}}
After writing, verify valid JSON. Return one line: risk level + missing-materials count."""


BENCHMARK_EVIDENCE_PROMPT = """You are benchmark-evidence-auditor, the other EXECUTE seat: catalog the \
benchmark/metric evidence the LITERATURE reports for this direction. This is an audit of what OTHERS \
measured — this pack runs no experiment, so you have nothing of your own to report.

    REQUEST: {request}

{north_star}

Read the vault at `{vault}/02-wiki/` (and `{run_dir}/inbox/search-results.json` if present) for the \
benchmarks/datasets/metrics/SOTA numbers the relevant sources actually report.

HARD RULE: `own_measured_metrics` MUST stay an empty list — you have no attested execution receipt, so \
you report ZERO metrics as your own. Cite literature-reported numbers only in `body`, always naming \
their source.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "benchmark_evidence_note": {{
    "title": "Benchmark evidence landscape for <this request>",
    "body": "<which benchmarks/datasets/metrics the literature reports, with a source per number, and \
where the evidence is thin or absent>",
    "refs": ["<real source ref per number you cited>"],
    "own_measured_metrics": []
  }}
}}
Quantity is a FLOOR: cover every benchmark the relevant sources report; never drop a defensible one to \
stay short. After writing, verify valid JSON. Return one line: benchmarks covered + own_measured_metrics \
count (must be 0)."""


SUBMISSION_SCOUT_PROMPT = """You are submission-guideline-scout, an ANALYZE seat: assemble a \
reference-only submission checklist (page limits, anonymization, formatting, required sections, \
supplementary rules) for a candidate venue/SOP relevant to this direction. This is REFERENCE \
information for the director, never a submission decision or a claim the work is ready.

    REQUEST: {request}

{north_star}

Read the vault at `{vault}/02-wiki/` for any venue/SOP notes already recorded for this direction. If \
none exist, name a plausible venue TYPE (e.g. "a mid-tier CV conference") explicitly as unconfirmed \
rather than inventing a specific venue's real rules.

HONESTY (hard): never state a specific venue's real formatting/anonymity rule unless you actually read \
it from a real source; mark anything you cannot confirm as unconfirmed rather than guessing a number.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "submission_checklist_note": {{
    "title": "Submission checklist (reference only) for <this request>",
    "body": "<checklist items: page limit / anonymization / required sections / supplementary rules / \
deadline pattern, each marked confirmed-from-source or unconfirmed>",
    "refs": ["<real source ref per confirmed item>"]
  }}
}}
After writing, verify valid JSON. Return one line: confirmed items + unconfirmed items."""


BIBLIOGRAPHY_VALIDATOR_PROMPT = """You are bibliography-validator, an INDEPENDENT ANALYZE seat. You did \
NOT scout literature, curate AERS references, or write the search strategy — your ONLY job is to \
REOPEN and independently re-check every ref the earlier seats cited. You produce no new references.

    REQUEST: {request}

{north_star}

Reopen and re-check the refs recorded in:
- `{run_dir}/evidence/DISCOVER/*.artifact.json` (the literature search trace)

For each ref, form your OWN judgment of whether it is real and correctly used; do not defer to the \
citing seat's framing.

HONESTY (hard): never invent a ref to check; if a cited ref looks fabricated or you cannot confirm it, \
flag it explicitly in `body` and leave it OUT of `refs` (only list the ones you actually re-verified).

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "bibliography_verification_note": {{
    "title": "Independent bibliography verification for <this request>",
    "body": "<how many refs re-checked, how many confirmed, how many flagged and why — you produce no \
new references, only verification>",
    "refs": ["<only the refs you actually independently re-verified>"]
  }}
}}
Quantity is a FLOOR: re-check every ref the earlier seats cited; never skip one to stay short. After \
writing, verify valid JSON. Return one line: refs re-checked + refs flagged."""


MANUSCRIPT_POLISH_PROMPT = """You are manuscript-polish-editor, the VERIFY seat: propose TRACEABLE \
manuscript edit recommendations for this direction's write-up. You never silently change a scientific \
claim — every suggestion that touches a claim, number, or comparison must be flagged for author \
confirmation, never applied.

    REQUEST: {request}

{north_star}

Read the vault at `{vault}/02-wiki/` for this direction's existing write-up/notes, if any.

HONESTY (hard): a style/clarity/formatting suggestion may be listed as routine; ANY suggestion that \
would change a claim, number, or comparison must be marked `requires_author_confirmation: true` inside \
your own wording of `body` — never silently resolved.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change nothing \
else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{
  "manuscript_polish_note": {{
    "title": "Manuscript polish recommendations for <this request>",
    "body": "<numbered list of edit suggestions, each with location + rationale + whether it is routine \
or requires_author_confirmation>",
    "refs": ["<real locus/section you actually read, if a write-up exists>"]
  }}
}}
Quantity is a FLOOR: list every defensible suggestion; never drop one to stay short. After writing, \
verify valid JSON. Return one line: routine suggestions + author-confirmation-required suggestions."""


# --------------------------------------------------------------------------- seat builders

def _bare_seats(pairs) -> list:
    """label+bundle_key only, for `load_seat_bundles` — no prompt text needs recomputing."""
    return [Seat(label=label, bundle_key=key, prompt="") for label, key in pairs]


def _write_aers_snapshot(run_dir) -> str:
    """The deterministic, catalog-metadata-only integration plan, dropped for the curator to read.

    Pure function of the internal AERS catalog snapshot — safe to recompute on every DISCOVER
    `llm_step` call (idempotent, no network, no child-skill-body read, no vault write)."""
    plan = aers_skill_integration_planner.build_plan()
    out = Path(run_dir) / "inbox" / "aers-integration-plan-snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out).replace("\\", "/")


def _discover_seats(run_dir, request, vault, model_policy) -> list:
    north_star = _shared.north_star_block(run_dir)
    snapshot_path = _write_aers_snapshot(run_dir)
    curator_out = _panel_recipe.bundle_path(run_dir, "DISCOVER", "aers-sop-curator")
    strategist_out = _panel_recipe.bundle_path(run_dir, "DISCOVER", "literature-search-strategist")
    prompts = {
        "aers-sop-curator": AERS_CURATOR_PROMPT.format(
            request=request, north_star=north_star, snapshot_path=snapshot_path, vault=vault,
            out=curator_out),
        "literature-search-strategist": LITERATURE_STRATEGIST_PROMPT.format(
            request=request, north_star=north_star, vault=vault, run_dir=run_dir, out=strategist_out),
    }
    return [Seat(label=label, bundle_key=key, prompt=prompts[label]) for label, key in _DISCOVER_SEAT_KEYS]


def _design_seats(run_dir, request, vault, model_policy) -> list:
    north_star = _shared.north_star_block(run_dir)
    out = _panel_recipe.bundle_path(run_dir, "DESIGN", "data-wrangling-auditor")
    prompts = {
        "data-wrangling-auditor": DATA_WRANGLING_PROMPT.format(
            request=request, north_star=north_star, vault=vault, out=out),
    }
    return [Seat(label=label, bundle_key=key, prompt=prompts[label]) for label, key in _DESIGN_SEAT_KEYS]


def _execute_seats(run_dir, request, vault, model_policy) -> list:
    north_star = _shared.north_star_block(run_dir)
    packager_out = _panel_recipe.bundle_path(run_dir, "EXECUTE", "reproducibility-packager")
    benchmark_out = _panel_recipe.bundle_path(run_dir, "EXECUTE", "benchmark-evidence-auditor")
    prompts = {
        "reproducibility-packager": REPRODUCIBILITY_PACKAGER_PROMPT.format(
            request=request, north_star=north_star, vault=vault, out=packager_out),
        "benchmark-evidence-auditor": BENCHMARK_EVIDENCE_PROMPT.format(
            request=request, north_star=north_star, vault=vault, run_dir=run_dir, out=benchmark_out),
    }
    return [Seat(label=label, bundle_key=key, prompt=prompts[label], tier="audit" if label ==
                 "benchmark-evidence-auditor" else "reason") for label, key in _EXECUTE_SEAT_KEYS]


def _analyze_seats(run_dir, request, vault, model_policy) -> list:
    north_star = _shared.north_star_block(run_dir)
    scout_out = _panel_recipe.bundle_path(run_dir, "ANALYZE", "submission-guideline-scout")
    biblio_out = _panel_recipe.bundle_path(run_dir, "ANALYZE", "bibliography-validator")
    prompts = {
        "submission-guideline-scout": SUBMISSION_SCOUT_PROMPT.format(
            request=request, north_star=north_star, vault=vault, out=scout_out),
        "bibliography-validator": BIBLIOGRAPHY_VALIDATOR_PROMPT.format(
            request=request, north_star=north_star, run_dir=run_dir, out=biblio_out),
    }
    return [Seat(label=label, bundle_key=key, prompt=prompts[label], tier="audit" if label ==
                 "bibliography-validator" else "reason") for label, key in _ANALYZE_SEAT_KEYS]


def _verify_seats(run_dir, request, vault, model_policy) -> list:
    north_star = _shared.north_star_block(run_dir)
    out = _panel_recipe.bundle_path(run_dir, "VERIFY", "manuscript-polish-editor")
    prompts = {
        "manuscript-polish-editor": MANUSCRIPT_POLISH_PROMPT.format(
            request=request, north_star=north_star, vault=vault, out=out),
    }
    return [Seat(label=label, bundle_key=key, prompt=prompts[label]) for label, key in _VERIFY_SEAT_KEYS]


# --------------------------------------------------------------------------- llm_step

def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, **funnel_kwargs) -> str:
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries,
                              **funnel_kwargs)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    if stage == "DISCOVER":
        seats = _discover_seats(run_dir, request, vault, model_policy)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats, model_policy=model_policy,
            panel_note="Curate applicable AERS reference packs and design+run a grounded lightweight "
                       "literature-search strategy, independently of each other.")
    if stage == "DESIGN":
        seats = _design_seats(run_dir, request, vault, model_policy)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats, model_policy=model_policy,
            panel_note="Audit/reconstruct the data-wrangling protocol this direction needs; the "
                       "anti-leakage rule (augmentation implies train_only) is a hard gate.")
    if stage == "EXECUTE":
        seats = _execute_seats(run_dir, request, vault, model_policy)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats, model_policy=model_policy,
            panel_note="PACKAGING/AUDIT work only, never a real run: audit reproduction materials and "
                       "catalog the literature's reported benchmark evidence, independently.")
    if stage == "ANALYZE":
        seats = _analyze_seats(run_dir, request, vault, model_policy)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats, model_policy=model_policy,
            panel_note="Scout submission guidelines and independently re-verify the bibliography — "
                       "two independent judgments, neither reads the other's output.")
    if stage == "VERIFY":
        seats = _verify_seats(run_dir, request, vault, model_policy)
        return _panel_recipe.panel(
            run_dir, stage, MODE, seats, model_policy=model_policy,
            panel_note="Propose traceable manuscript-polish recommendations; nothing here silently "
                       "changes a scientific claim.")
    return None  # REPORT is deterministic


# --------------------------------------------------------------------------- deterministic helpers

def _clean_note(raw: dict) -> dict:
    """A schema-conformant {title, body, refs} — defensive against a worker adding stray fields."""
    return {"title": str((raw or {}).get("title") or "").strip() or "untitled",
            "body": str((raw or {}).get("body") or ""),
            "refs": [str(r) for r in ((raw or {}).get("refs") or [])]}


def _refs_from_search_trace(trace: dict) -> list:
    out = []
    for round_ in trace.get("rounds") or []:
        for hit in round_.get("source_hits") or []:
            ref = str(hit.get("source_ref") or "").strip()
            if ref:
                out.append(ref)
    return list(dict.fromkeys(out))


def _evidence_table_for_gates(refs: list, prefix: str) -> Optional[dict]:
    """An ad-hoc evidence_table shape purely for `common_gates`' existence/referential checks —
    never persisted as its own artifact (this mode has no bibliography artifact type of its own)."""
    if not refs:
        return None
    return {"sources": [{"id": f"{prefix}{i}", "kind": "reference", "ref": r}
                        for i, r in enumerate(refs, 1)]}


def _check_data_protocol_leakage(protocol: dict, *, mode: str) -> None:
    """Mode-specific hard gate: an augmentation step reaching non-train splits is a leakage bug."""
    violations = [
        f"step {step.get('step_id')!r} is kind=augmentation but train_only is not true"
        for step in (protocol.get("steps") or [])
        if step.get("kind") == "augmentation" and not step.get("train_only")
    ]
    if violations:
        raise GateBlock(
            f"{mode} DESIGN anti-leakage BLOCK: {violations} — augmentation reaching non-train splits "
            f"is a leakage bug; every augmentation step must declare train_only=true")


def _read_stage_payloads(run_dir, stage: str) -> dict:
    """filename -> payload for every artifact already committed in `stage` (read-only, for VERIFY's
    render step to assemble the full pack from stages that have already run)."""
    d = Path(run_dir) / "evidence" / stage
    out: dict = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.artifact.json")):
        try:
            art = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[p.name] = art.get("payload") or {}
    return out


def _fmt_list(items) -> str:
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    return "; ".join(cleaned) if cleaned else "(none)"


# --------------------------------------------------------------------------- stage producers

def _discover_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "DISCOVER", MODE, _bare_seats(_DISCOVER_SEAT_KEYS))
    note = bundles["aers_applicability_note"]
    trace = bundles["evidence_search_trace"]

    plan = aers_skill_integration_planner.build_plan()   # deterministic — independent of the worker bundle

    paths = [
        write_artifact(run_dir, "DISCOVER", "aers-integration-plan.artifact.json",
                       "aers_skill_integration_plan", "aers-sop-curator", plan, ts),
        write_artifact(run_dir, "DISCOVER", "aers-applicability-note.artifact.json",
                       "note", "aers-sop-curator", _clean_note(note), ts),
        write_artifact(run_dir, "DISCOVER", "literature-search-trace.artifact.json",
                       "evidence_search_trace", "literature-search-strategist", trace, ts),
    ]

    refs = _refs_from_search_trace(trace)
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "DISCOVER", ts, mode=MODE, bundles=bundles,
        evidence_table=_evidence_table_for_gates(refs, "s"), downstream_refs=refs, known_ids=set())
    paths += gate_paths

    report = {
        "aers_reference_pack_candidates": plan["summary"]["reference_pack_candidates"],
        "aers_human_gate_required": plan["summary"]["human_gate_required"],
        "aers_blocked": plan["summary"]["blocked"],
        "search_rounds": len(trace.get("rounds") or []),
        "search_stop_reason": trace.get("stop_reason"),
        **frag,
    }
    return paths, report


def _design_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "DESIGN", MODE, _bare_seats(_DESIGN_SEAT_KEYS))
    protocol = bundles["data_protocol"]

    _check_data_protocol_leakage(protocol, mode=MODE)   # mode-specific hard gate — before any write

    paths = [write_artifact(run_dir, "DESIGN", "data-protocol.artifact.json",
                            "data_protocol", "data-wrangling-auditor", protocol, ts)]

    gate_paths, frag = _panel_recipe.common_gates(run_dir, "DESIGN", ts, mode=MODE, bundles=bundles)
    paths += gate_paths

    steps = protocol.get("steps") or []
    report = {"n_data_protocol_steps": len(steps),
              "n_augmentation_steps": sum(1 for s in steps if s.get("kind") == "augmentation"), **frag}
    return paths, report


def _execute_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "EXECUTE", MODE, _bare_seats(_EXECUTE_SEAT_KEYS))
    audit = bundles["reproducibility_materials_audit"]
    bench_note = bundles["benchmark_evidence_note"]

    # Mode-specific hard gate: this pack never ran anything, so a worker-reported "own" metric with no
    # attested execution receipt is a fabrication, not a finding — refuse it before writing anything.
    state = _panel_recipe.execution_truth(run_dir)
    _panel_recipe.refuse_metrics_without_receipt(
        state, bench_note.get("own_measured_metrics") or [], mode=MODE,
        what="own-measured benchmark metrics")

    # The honesty-boundary proof: recomputed from EMPTY execution inputs (there is nothing to
    # recompute in this reference-only mode), so the BLOCK verdict is a machine-checked fact, not prose.
    bench_report = numeric_benchmark_adapter.build_report(
        run_records=[], result_rows=[], hash_manifest={}, journal={}, required_paths=[])

    paths = [
        write_artifact(run_dir, "EXECUTE", "reproducibility-materials-audit.artifact.json",
                       "reproducibility_materials_audit", "reproducibility-packager", audit, ts),
        write_artifact(run_dir, "EXECUTE", "benchmark-evidence-note.artifact.json",
                       "note", "benchmark-evidence-auditor", _clean_note(bench_note), ts),
        write_artifact(run_dir, "EXECUTE", "numeric-benchmark-report.artifact.json",
                       "numeric_benchmark_report", "benchmark-evidence-auditor", bench_report, ts,
                       "blocked" if bench_report["verdict"] == "BLOCK" else "approved"),
    ]

    refs = [str(r) for r in (bench_note.get("refs") or []) if str(r).strip()]
    refs = list(dict.fromkeys(refs))
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "EXECUTE", ts, mode=MODE, bundles=bundles,
        evidence_table=_evidence_table_for_gates(refs, "e"), downstream_refs=refs, known_ids=set())
    paths += gate_paths

    report = {"reproducibility_risk": audit.get("reproducibility_risk"),
              "execution_state": state["label"], "executed": state["executed"],
              "numeric_benchmark_verdict": bench_report["verdict"], **frag}
    return paths, report


def _analyze_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "ANALYZE", MODE, _bare_seats(_ANALYZE_SEAT_KEYS))
    scout_note = bundles["submission_checklist_note"]
    biblio_note = bundles["bibliography_verification_note"]

    paths = [
        write_artifact(run_dir, "ANALYZE", "submission-checklist-note.artifact.json",
                       "note", "submission-guideline-scout", _clean_note(scout_note), ts),
        write_artifact(run_dir, "ANALYZE", "bibliography-verification-note.artifact.json",
                       "note", "bibliography-validator", _clean_note(biblio_note), ts),
    ]

    refs = [str(r) for r in (biblio_note.get("refs") or []) if str(r).strip()]
    refs = list(dict.fromkeys(refs))
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "ANALYZE", ts, mode=MODE, bundles=bundles,
        evidence_table=_evidence_table_for_gates(refs, "b"), downstream_refs=refs, known_ids=set())
    paths += gate_paths

    report = {"submission_checklist_refs": len(scout_note.get("refs") or []),
              "bibliography_refs_reverified": len(refs), **frag}
    return paths, report


def _verify_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "VERIFY", MODE, _bare_seats(_VERIFY_SEAT_KEYS))
    polish = bundles["manuscript_polish_note"]

    paths = [write_artifact(run_dir, "VERIFY", "manuscript-polish-note.artifact.json",
                            "note", "manuscript-polish-editor", _clean_note(polish), ts)]

    refs = [str(r) for r in (polish.get("refs") or []) if str(r).strip()]
    refs = list(dict.fromkeys(refs))
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "VERIFY", ts, mode=MODE, bundles=bundles,
        evidence_table=_evidence_table_for_gates(refs, "m"), downstream_refs=refs, known_ids=set())
    paths += gate_paths

    discover = _read_stage_payloads(run_dir, "DISCOVER")
    design = _read_stage_payloads(run_dir, "DESIGN")
    execute = _read_stage_payloads(run_dir, "EXECUTE")
    analyze = _read_stage_payloads(run_dir, "ANALYZE")

    plan = discover.get("aers-integration-plan.artifact.json") or {}
    plan_summary = plan.get("summary") or {}
    aers_note = discover.get("aers-applicability-note.artifact.json") or {}
    trace = discover.get("literature-search-trace.artifact.json") or {}
    protocol = design.get("data-protocol.artifact.json") or {}
    repro_audit = execute.get("reproducibility-materials-audit.artifact.json") or {}
    bench_note = execute.get("benchmark-evidence-note.artifact.json") or {}
    bench_report = execute.get("numeric-benchmark-report.artifact.json") or {}
    scout_note = analyze.get("submission-checklist-note.artifact.json") or {}
    biblio_note = analyze.get("bibliography-verification-note.artifact.json") or {}

    exec_state = _panel_recipe.execution_truth(run_dir)
    steps = protocol.get("steps") or []

    sections = {
        "AERS references and applicability": (
            f"Deterministic catalog scan (metadata-only, no child skill body read, nothing executed): "
            f"{plan_summary.get('reference_pack_candidates', 0)} reference-pack candidate(s), "
            f"{plan_summary.get('human_gate_required', 0)} needing a human license/security gate, "
            f"{plan_summary.get('blocked', 0)} blocked.\n\n"
            f"{aers_note.get('title', '')}\n{aers_note.get('body') or '(none)'}"
        ),
        "Literature search strategy": (
            f"{len(trace.get('rounds') or [])} round(s) run; stop reason: "
            f"{trace.get('stop_reason', 'unknown')}.\n"
            f"Research question: {trace.get('research_question') or '(none)'}"
        ),
        "Data-wrangling protocol": (
            f"{len(steps)} step(s) audited/reconstructed "
            f"({sum(1 for s in steps if s.get('kind') == 'augmentation')} augmentation step(s), all "
            f"checked train_only — anti-leakage gate passed).\n"
            f"{protocol.get('notes') or '(no additional notes)'}"
        ),
        "Reproducibility package": (
            f"Reproducibility risk: {repro_audit.get('reproducibility_risk', 'unknown')}. "
            f"Code: {repro_audit.get('code_availability', '(unaudited)')}. "
            f"Data: {repro_audit.get('data_availability', '(unaudited)')}. "
            f"Config: {repro_audit.get('config_availability', '(unaudited)')}. "
            f"Missing: {_fmt_list(repro_audit.get('missing_materials'))}."
        ),
        "Benchmark evidence": (
            f"{_panel_recipe.execution_boundary_section(exec_state)}\n\n"
            f"This pack contains no experiment execution; the EXECUTE stage performed reproduction "
            f"packaging and benchmark-evidence auditing only. The deterministic numeric-benchmark "
            f"recomputation confirms this mechanically: verdict={bench_report.get('verdict', 'BLOCK')} "
            f"({_fmt_list(bench_report.get('violations'))}).\n\n"
            f"Literature-reported benchmark landscape: {bench_note.get('body') or '(none)'}"
        ),
        "Submission checklist": (
            f"{scout_note.get('body') or '(none)'}\n(reference only — never a submission decision)"
        ),
        "Bibliography audit": (
            f"Independent existence check at ANALYZE: "
            f"{(analyze.get('citation-existence-verdict.artifact.json') or {}).get('verdict', 'NOT_APPLICABLE (no external refs to check)')}. "
            f"Reaching VERIFY confirms no fabricated/broken reference was found at ANALYZE (a violation "
            f"would have halted the run there).\n\n{biblio_note.get('body') or '(none)'}"
        ),
        "Manuscript revisions": (
            f"{polish.get('body') or '(none)'}"
        ),
    }

    rel = _panel_recipe.render_director_markdown(run_dir, MODE, sections, ts=ts)

    report = {
        "director_research_pack": rel,
        "pack_coverage": {"seats_covered": len(_panel_recipe.declared_seats(MODE)),
                          "sections_rendered": len(sections)},
        **frag,
    }
    return paths, report


def _report(run_dir, ts) -> tuple:
    rel = _panel_recipe.target_markdown(MODE)["path"]
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary="aers_enhanced_research_pack: 8-seat reference-only AERS-enhanced research pack "
               "(curate+search -> data/reproducibility audit -> packaging/benchmark audit -> "
               "submission+bibliography audit -> manuscript polish) with a deterministically rendered "
               "director brief; EXECUTE performed packaging/audit only, never a real experiment run.",
        references=[rel])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "DESIGN":
        return _design_dets(run_dir, ts)
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts)
    if stage == "ANALYZE":
        return _analyze_dets(run_dir, ts)
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
