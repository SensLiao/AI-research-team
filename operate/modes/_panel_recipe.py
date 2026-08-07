"""Spec-driven machinery shared by the wave-2 operated recipes (2026-08-04).

Wave 2 wires the 14 modes that were registry-routable but had no operate recipe, taking the
one-button surface to every mode in the registry. Each of those modes already carried its own
build spec IN THE REGISTRY: `minimum_worker_pipeline` (which seats run in which order and what
each one produces) plus `target_markdown` (the director-facing path and its required sections).
This module turns that declared spec into the four things the operate spine asks a recipe for —
a dispatch panel, validated worker bundles, the common hard gates, and a linted director
Markdown — so a new mode module only supplies what a spec cannot: the hand-written seat prompts
and its own mode-specific deterministic checks.

Three deliberate choices, all load-bearing:

  * **Prompts stay hand-written.** The 2026-08-03 measurement showed a worker's output volume is
    set by the wording of its dispatch order — an "at most N" phrasing held a 122-paper panel to a
    handful of rows. Generating prompts from a spec would quietly re-introduce that ceiling, so the
    spec owns STRUCTURE and a human owns the ASK. `Seat.prompt` is never templated from the registry.

  * **`render_markdown` is deterministic, not a seat.** Every wave-2 mode's
    `minimum_worker_pipeline` names `synthesis-writer` for its final render step, but no operated
    mode dispatches it: all 12 wave-1 modes render their director Markdown in plain Python, and the
    registry's own `productization_gaps` ask for exactly that ("deterministic Markdown rendering",
    "a deterministic Markdown compiler with cross-reference validation"). A renderer that cannot
    hallucinate a section is strictly stronger than a worker that can, so a wave-2 mode dispatches
    `minimum_distinct_workers` minus that one render seat. The gap is intentional, not a missing worker.

  * **Structure blocks; prose only warns.** A required section the RECIPE forgot to render is a
    recipe bug and hard-BLOCKs (`render_director_markdown`). Content-quality lint stays advisory,
    matching wave 1. "None found" is a legitimate non-empty section value — thin worker output must
    be reported as thin, never blocked into padding.

Every recipe built on this module inherits the same three hard gates wave 1 carries (north-star
drift, citation existence, referential integrity) and the same bounded repair loop, so a wave-2
mode is never a weaker citizen than a wave-1 mode.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ..output_versions import resolve_effective_output
from ...orchestrator.graph_spec import load_mode_registry
from ...tools.full_rigor_execution_truth import execution_state

DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

#: Seat tiers -> model routing. `max_quality` puts every reasoning seat on opus (director's
#: "全 OPUS"); the default policy keeps judgment on opus and scoped execution on sonnet, per
#: the project's §9 model-routing rule. There is no haiku tier in this system.
#:
#: Four tiers, not three (director's refinement, 2026-08-05). `reason` used to carry both
#: "design the experiment" and "write the code that runs an already-frozen design", and those
#: two do NOT deserve the same model: the director's rule is 质量 / 想法 / 实验设计 -> opus,
#: 书写 · 固定死了的 · 写代码 -> sonnet. Designing is not sonnet-able merely because it is
#: called planning, so `design` exists to keep protocol/experiment/ideation-ranking seats on
#: opus while `reason` keeps its cheap half.
_TIER_DEFAULT = {"design": "opus", "reason": "sonnet", "audit": "opus", "tool": "sonnet"}


# --------------------------------------------------------------------------- registry spec access

@lru_cache(maxsize=1)
def _registry() -> dict:
    return load_mode_registry()["modes"]


def mode_spec(mode: str) -> dict:
    """The registry entry for `mode` — the single source of truth for its shape.

    A recipe reads its stage path, seat roster, pipeline and Markdown contract from here rather
    than restating them, so a registry edit can never silently disagree with the wired recipe.
    """
    spec = _registry().get(mode)
    if spec is None:
        raise ValueError(f"{mode!r} is not in mode_registry.yaml — a recipe cannot outrun the registry")
    return spec


def stage_path(mode: str) -> list:
    return list(mode_spec(mode)["stage_path"])


def declared_seats(mode: str) -> tuple:
    """The mode's `agent_subset` — the ONLY seats this mode may dispatch."""
    return tuple(mode_spec(mode).get("agent_subset") or ())


def pipeline(mode: str) -> tuple:
    """The registry's declared `minimum_worker_pipeline.stages` (empty tuple when absent)."""
    maturity = mode_spec(mode).get("product_maturity") or {}
    return tuple((maturity.get("minimum_worker_pipeline") or {}).get("stages") or ())


def target_markdown(mode: str) -> dict:
    """The declared director-facing Markdown contract: `path`, `purpose`, `required_sections`.

    Read from `handoff` once a mode is wired, and from `product_maturity.target_markdown` while it
    is still spec-only. The two are the same contract at different lifecycle stages: `product_maturity`
    is a TARGET a spec-only mode promises, and the capability catalog forbids an operated mode from
    keeping one ("reserved for modes without operated:true") — so wiring a mode MOVES the contract
    into `handoff` rather than deleting it. Both paths are supported because wave 2 wires the modes
    in batches and the unwired remainder must keep working.
    """
    handoff = mode_spec(mode).get("handoff") or {}
    if handoff.get("primary_markdown") and handoff.get("required_sections"):
        return {"path": handoff["primary_markdown"],
                "purpose": handoff.get("purpose") or "",
                "required_sections": list(handoff["required_sections"])}
    maturity = mode_spec(mode).get("product_maturity") or {}
    spec = maturity.get("target_markdown")
    if not spec or not spec.get("path") or not spec.get("required_sections"):
        raise ValueError(
            f"{mode!r} declares no director-Markdown contract in either handoff.required_sections "
            f"or product_maturity.target_markdown — a wave-2 recipe renders the registry's declared "
            f"sections and cannot invent its own")
    return spec


def mode_budget(mode: str) -> dict:
    return dict(mode_spec(mode).get("budget") or {})


# --------------------------------------------------------------------------- dispatch

@dataclass(frozen=True)
class Seat:
    """One dispatched worker in a wave-2 panel.

    label       roster agent name; MUST appear in the mode's `agent_subset` (validated).
    prompt      the hand-written dispatch order, already formatted. Never spec-generated.
    bundle_key  the canonical top-level key the worker's bundle must carry.
    tier        reason | audit | tool -> model routing (see `_TIER_DEFAULT`).
    depends_on  labels whose bundles this seat must read first; drives the parallel waves.
    """
    label: str
    prompt: str
    bundle_key: str
    tier: str = "reason"
    depends_on: tuple = field(default=())


def worker_model(model_policy: str, tier: str = "reason") -> str:
    """Explicit per-seat model. `max_quality` == the director's 全 OPUS switch."""
    if model_policy == "max_quality":
        return "opus"
    return _TIER_DEFAULT.get(tier, "sonnet")


def bundle_path(run_dir, stage: str, label: str) -> str:
    """Where a seat writes its bundle. One accountable writer per file, by construction."""
    return f"{run_dir}/inbox/{stage}.{label}.bundle.json"


def _waves(seats: Sequence[Seat]) -> list:
    """Group seats into dependency waves — seats inside one wave are genuinely parallel."""
    remaining = list(seats)
    done: set = set()
    waves: list = []
    while remaining:
        ready = [s for s in remaining if all(d in done for d in s.depends_on)]
        if not ready:
            unresolved = {s.label: [d for d in s.depends_on if d not in done] for s in remaining}
            raise ValueError(f"seat dependency cycle or unknown upstream: {unresolved}")
        waves.append([s.label for s in ready])
        done.update(s.label for s in ready)
        remaining = [s for s in remaining if s.label not in done]
    return waves


def panel(run_dir, stage: str, mode: str, seats: Sequence[Seat], *, panel_note: str,
          model_policy: str = "default") -> dict:
    """Build the `llm_step` payload for one stage: every declared seat, in dependency waves.

    Validates each label against the mode's `agent_subset` here, so a typo fails at dispatch
    time with a readable message instead of surfacing later as a panel-scheduler rejection.
    """
    allowed = set(declared_seats(mode))
    unknown = [s.label for s in seats if s.label not in allowed]
    if unknown:
        raise ValueError(
            f"{mode} {stage} would dispatch seat(s) {unknown} that its agent_subset does not "
            f"declare — add them to mode_registry.yaml or fix the label (allowed: {sorted(allowed)})")
    duplicates = sorted({s.label for s in seats if [x.label for x in seats].count(s.label) > 1})
    if duplicates:
        raise ValueError(f"{mode} {stage} dispatches {duplicates} twice — one writer per bundle")

    workers = []
    for seat in seats:
        worker = {"label": seat.label, "model": worker_model(model_policy, seat.tier),
                  "output": bundle_path(run_dir, stage, seat.label), "prompt": seat.prompt}
        if seat.depends_on:
            worker["depends_on"] = list(seat.depends_on)
        workers.append(worker)
    return {"label": f"{mode.replace('_', '-')}-panel", "workers": workers,
            "worker_order": [s.label for s in seats], "parallel_groups": _waves(seats),
            "panel_note": panel_note}


# --------------------------------------------------------------------------- ingest

def load_seat_bundles(run_dir, stage: str, mode: str, seats: Sequence[Seat]) -> dict:
    """Read every declared seat bundle -> {bundle_key: value}. Reports ALL gaps at once.

    A partially dispatched panel is a BLOCK, never a silent degrade: the whole point of an
    independent seat is that its absence changes what the report may claim.

    Each seat is read at its EFFECTIVE version, not at its first-written bytes. When a gate issues a
    targeted repair the corrected bundle lands under `inbox/supplements/<stage>/repair-NNN/corrected/`
    and the repair plan hash-links it to what it supersedes; `resolve_effective_output` walks that
    chain. Reading the logical path directly instead — which this function used to do — meant a gate
    re-read the ORIGINAL bytes after every repair, re-raised the same defect, and burned the repair
    budget on a loop that could never converge. The lineage-aware modes (`gap_breadth`,
    `deep_research`, `new_direction`, `read_paper_deep`, `evidence_deep`, the deep-ideate shared
    core) already resolved it this way; every mode built on this recipe did not.
    """
    run_root = Path(run_dir)
    root = run_root / "inbox"
    missing = [f"{stage}.{s.label}.bundle.json" for s in seats
               if not (root / f"{stage}.{s.label}.bundle.json").is_file()]
    if missing:
        raise GateBlock(
            f"{mode} {stage} panel is incomplete — missing bundle(s) {missing}. Dispatch every "
            f"seat in llm_step before running the deterministic stage; a missing independent seat "
            f"is not a pass.")
    out: dict = {}
    for seat in seats:
        logical = root / f"{stage}.{seat.label}.bundle.json"
        try:
            effective = resolve_effective_output(run_root, stage, logical)
        except ValueError as exc:
            # A broken supplement chain is tampering-shaped, so it stops the stage rather than
            # silently falling back to the superseded bytes.
            raise GateBlock(
                f"{mode} {stage} cannot resolve the repair lineage for {seat.label}: {exc}") from exc
        raw = json.loads(effective.read_text(encoding="utf-8"))
        out[seat.bundle_key] = _shared.extract_worker_bundle_value(
            raw, seat.bundle_key, stage=stage, mode=mode, agent=seat.label)
    return out


def collect_texts(value, _depth: int = 0) -> list:
    """Every string inside a nested bundle — the north-star drift gate's input."""
    if _depth > 12:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [t for v in value.values() for t in collect_texts(v, _depth + 1)]
    if isinstance(value, (list, tuple)):
        return [t for v in value for t in collect_texts(v, _depth + 1)]
    return []


# --------------------------------------------------------------------------- the common hard gates

def common_gates(run_dir, stage: str, ts: str, *, mode: str, bundles: dict,
                 evidence_table: Optional[dict] = None,
                 claim_evidence_map: Optional[dict] = None,
                 downstream_refs: Iterable[str] = (), known_ids: Iterable[str] = (),
                 vault: Optional[str] = None) -> tuple:
    """The three gates every operated mode carries. Returns (artifact_paths, report_fragment).

    1. north-star drift  — a provably out-of-scope topic BLOCKs (semantic drift still needs a human).
    2. citation existence — a ref CONFIRMED not to exist BLOCKs; offline degrades to a warning.
    3. referential integrity — an internal-shaped id nobody upstream produced BLOCKs.

    Modes with no bibliography (design / execute / monitor panels) simply pass no evidence table;
    gates 2-3 then have nothing to check and say so rather than pretending to have run.
    """
    paths: list = []
    frag: dict = {}

    drift_path, drift_facts = _shared.run_drift_gate(
        run_dir, stage, ts, collect_texts(bundles))
    paths.append(drift_path)
    frag["drift_gate"] = "PASS"
    frag.update({f"drift_{k}": v for k, v in (drift_facts or {}).items()})

    external = list(_shared.external_refs(evidence_table or {}, claim_evidence_map)) \
        if evidence_table is not None else []
    if external:
        ex_path, verdict = _shared.run_existence_gate(run_dir, stage, ts, external)
        paths.append(ex_path)
        frag["existence_gate"] = verdict["verdict"]
        frag["existence_warnings"] = len(verdict.get("warnings") or [])
    else:
        frag["existence_gate"] = "NOT_APPLICABLE"
        frag["existence_warnings"] = 0

    refs = [r for r in downstream_refs if str(r).strip()]
    if refs:
        vault_root = _shared.resolve_vault_root(vault or DEFAULT_VAULT)
        violations, warnings = _shared.check_referential_integrity(
            refs, set(known_ids), _shared.vault_slugs(vault_root))
        if violations:
            raise GateBlock(
                f"{mode} {stage} referential integrity BLOCK: {violations}")
        frag["referential_integrity"] = "PASS"
        frag["referential_warnings"] = len(warnings)
    else:
        frag["referential_integrity"] = "NOT_APPLICABLE"
        frag["referential_warnings"] = 0

    return paths, frag


# --------------------------------------------------------------------------- director Markdown

def _heading(section: str) -> str:
    return f"## {section}"


def render_director_markdown(run_dir, mode: str, sections: dict, *, ts: str,
                             lead: Optional[str] = None, extra: Optional[dict] = None) -> str:
    """Write the registry-declared director Markdown. Returns the RUN-RELATIVE path.

    Every `required_sections` entry must be supplied non-empty — the recipe owns those strings,
    so a gap is a recipe bug and BLOCKs. Honest emptiness is expressed IN the text
    ("none found — 3 sources checked"), never by omitting the section.
    """
    spec = target_markdown(mode)
    required = [str(s) for s in spec["required_sections"]]
    missing = [s for s in required if not str(sections.get(s) or "").strip()]
    if missing:
        raise GateBlock(
            f"{mode} director Markdown is missing required section(s) {missing} — the registry's "
            f"target_markdown contract declares them. Render 'none found' with its evidence "
            f"rather than dropping the section.")

    title = spec.get("purpose") or mode
    lines = [f"# {mode.replace('_', ' ')} — director brief", "",
             f"> {title}", f"> generated {ts}" + (f" · lead: {lead}" if lead else ""), ""]
    for section in required:
        lines += [_heading(section), "", str(sections[section]).strip(), ""]
    for name, body in (extra or {}).items():
        if str(body or "").strip():
            lines += [_heading(str(name)), "", str(body).strip(), ""]

    text = "\n".join(lines).rstrip() + "\n"
    rel = str(spec["path"])
    out = Path(run_dir) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    warnings = lint_director_markdown(text, required)
    advisory = {"contract_version": "research-markdown-advisory/v1", "delivery_blocking": False,
                "delivery_status": "USABLE" if not warnings else "USABLE_WITH_CAVEATS",
                "warnings": warnings}
    advisory_path = Path(run_dir) / "inbox" / f"{mode}-markdown-quality-advisory.json"
    advisory_path.parent.mkdir(parents=True, exist_ok=True)
    advisory_path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return rel


def lint_director_markdown(text: str, required_sections: Sequence[str]) -> list:
    """Advisory content lint (never blocking). Structure was already enforced upstream."""
    warnings: list = []
    for section in required_sections:
        head = _heading(str(section))
        if head not in text:
            warnings.append(f"heading absent from rendered text: {section!r}")
            continue
        body = text.split(head, 1)[1].split("\n## ", 1)[0].strip()
        if len(body) < 40:
            warnings.append(f"section {section!r} is very thin ({len(body)} chars) — is it really this thin?")
    for banned in ("TODO", "TBD", "lorem ipsum", "<placeholder>"):
        if banned.lower() in text.lower():
            warnings.append(f"placeholder text {banned!r} reached the director brief")
    return warnings


# --------------------------------------------------------------------------- REPORT stage

def report_note(run_dir, ts: str, *, mode: str, summary: str, references: Iterable[str] = (),
                open_questions: Iterable[str] = (), produced: Iterable[str] = ()) -> tuple:
    """The standard REPORT-stage artifact. Deterministic — REPORT dispatches no worker."""
    note = {"summary": summary, "references": [str(r) for r in references],
            "produced_artifacts": [str(p) for p in produced],
            "open_questions": [str(q) for q in open_questions]}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json", "report_note",
                            "research-orchestrator", note, ts)], {})


# --------------------------------------------------------------------------- bounded repair loop

def make_repair(mode: str, run_dets: Callable) -> Callable:
    """Wrap a recipe's `run_dets` in the shared bounded revise loop.

    Returns the standard ("ok", (paths, report)) / ("retry", feedback) contract; the ORIGINAL
    GateBlock escalates to the director once the budget's repair cap is reached.
    """

    def run_dets_with_repair(run_dir, stage, ts):
        return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                                   lambda: run_dets(run_dir, stage, ts))

    run_dets_with_repair.__doc__ = (
        f"{mode}: bounded worker-revise loop around run_dets "
        f"(('ok', (paths, report)) | ('retry', feedback)).")
    return run_dets_with_repair


# --------------------------------------------------------------------------- honesty boundary

def execution_truth(run_dir) -> dict:
    """Planned vs really-ran, decided by the ONE canonical classifier the system already has.

    Wave-2 modes that touch experiment execution (`m2_accept`, `tree_explore`,
    `debug_failed_run`, `check_run`, `repo_code_audit`) must gate every numeric claim on
    `executed`. Re-deciding this locally is how a design run starts reading like a result, so
    this is a thin re-export of `tools.full_rigor_execution_truth.execution_state` and nothing more.

    Returns the classifier's dict; `executed` is True only for label == "real-run".
    """
    return execution_state(run_dir)


def refuse_metrics_without_receipt(state: dict, metrics, *, mode: str, what: str) -> None:
    """BLOCK when a mode would report numbers it did not actually measure."""
    if metrics and not state.get("executed"):
        raise GateBlock(
            f"{mode} would report {what} while execution state is {state.get('label')!r} "
            f"({state.get('summary')}) — a planned or unverified run has no metrics. Emit the "
            f"runnable scripts and an empty metric set instead of a number.")


def execution_boundary_section(state: dict) -> str:
    """The director-facing sentence for a group-B mode's honesty boundary."""
    if state.get("executed"):
        return ("**Really ran.** Attested executor receipts, bound result files and a journal are "
                f"present; claims stay provisional until review. ({state.get('summary')})")
    return (f"**Did NOT run — this is a plan, not a result.** Execution state: "
            f"`{state.get('label')}`. {state.get('summary')} Every number below is a target or a "
            f"script parameter, never a measurement.")
