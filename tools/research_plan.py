"""Research-plan composer — the COMBINATION layer (director lock 2026-06-19).

Before this, the operate layer ran exactly ONE mode per run. The director's requirement: a request
must be able to invoke a COMBINATION of modes (a "tier"), the orchestrator must RECOMMEND tiers
(fastest/cheapest 1-mode core -> mainline -> deepest/widest full), the director picks one, then
answers each mode's drill-down questions (one round per mode), and the chain runs link-by-link.

This module is the deterministic brain behind that:
  - load the human-authored catalog (orchestrator/plan_catalog.yaml — the SSOT for intents/tiers).
  - match a request to an INTENT and PROPOSE its tiers, each annotated with cost (from
    mode_registry.yaml budgets), the human gates it passes through, and a validation verdict.
  - validate a chain: an unknown mode is a violation; a spec-only (not one-button) mode is FLAGGED
    honestly (never pretended push-button); a chain that runs backwards through the research phases
    (venue before ideate, design before evidence) is a violation.
  - thread one link's output into the next: write `inbox/upstream-grounding.json` into the downstream
    run and append a "PRIOR CHAIN CONTEXT" block to its worker prompt(s) so link N builds ON link N-1.

It is pure (no import of the operate layer — the CLI calls IN to here, never the reverse, so there is
no circular import). The model proposes; the DIRECTOR picks the tier and every human gate. The chain
is a bounded composition over a frozen, human-authored menu — not a free-form dynamic workflow.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from research_agent_teams.tools.ledger import last_of_type, read_events

_PKG = Path(__file__).resolve().parents[1]                       # research_agent_teams/
_CATALOG_PATH = _PKG / "orchestrator" / "plan_catalog.yaml"
_REGISTRY_PATH = _PKG / "orchestrator" / "mode_registry.yaml"

UPSTREAM_GROUNDING_FILE = "upstream-grounding.json"              # under <run>/inbox/
HANDOFF_CONTRACT_VERSION = "mode-handoff/v2"

# Cost bands (sum of the chain's modes' max_agent_hops) — drives the "fastest/cheapest" labelling.
_BAND_LIGHT_MAX = 6
_BAND_MEDIUM_MAX = 16


# --------------------------------------------------------------------------- catalog / registry I/O

def load_catalog(path: Optional[str] = None) -> dict:
    """The plan catalog (re-read each call so an edit takes effect with no restart)."""
    p = Path(path) if path else _CATALOG_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_mode_registry(path: Optional[str] = None) -> dict:
    p = Path(path) if path else _REGISTRY_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def all_modes() -> set:
    """Every mode the registry knows (wired + spec-only)."""
    return set((load_mode_registry().get("modes") or {}).keys())


def wired_modes() -> set:
    """The one-button modes (operated:true in mode_registry.yaml — the wiring test enforces the mirror).

    Only these belong in a default tier; validate_chain flags anything else."""
    modes = load_mode_registry().get("modes") or {}
    return {m for m, spec in modes.items() if isinstance(spec, dict) and spec.get("operated")}


def all_intents() -> List[str]:
    return list((load_catalog().get("intents") or {}).keys())


# --------------------------------------------------------------------------- intent matching

def match_intents(request: str) -> List[Tuple[str, int]]:
    """(intent_id, score) for every intent, ranked by how many of its aliases appear in the request.

    Ties keep catalog order. A request that matches nothing returns every intent with score 0 (the
    caller then asks the director which arc — never a silent guess)."""
    cat = load_catalog()
    intents = cat.get("intents") or {}
    req = (request or "").lower()
    order = list(intents)
    scored: List[Tuple[str, int]] = []
    for iid in order:
        spec = intents[iid] or {}
        # aliases (full phrases) + keywords (short high-signal tokens, robust to natural phrasing
        # where a full alias is broken up, e.g. 找/个/研究/方向).
        terms = list(spec.get("aliases") or []) + list(spec.get("keywords") or [])
        score = sum(1 for t in terms if str(t).strip() and str(t).strip().lower() in req)
        scored.append((iid, score))
    scored.sort(key=lambda x: (-x[1], order.index(x[0])))
    return scored


def best_intents(request: str) -> Tuple[List[str], bool]:
    """(intent_ids, matched). Matched intents (score>0) if any, else ALL intents (ask the director)."""
    ranked = match_intents(request)
    hits = [iid for iid, s in ranked if s > 0]
    if hits:
        return hits, True
    return [iid for iid, _ in ranked], False


# --------------------------------------------------------------------------- cost / gates / validation

def estimate_cost(modes: List[str]) -> dict:
    """A chain's rough cost = sum of its modes' max_agent_hops (from mode_registry budgets)."""
    reg = load_mode_registry().get("modes") or {}
    hops = 0
    for m in modes:
        budget = (reg.get(m) or {}).get("budget") or {}
        hops += int(budget.get("max_agent_hops") or 0)
    if hops <= _BAND_LIGHT_MAX:
        band = "light"
    elif hops <= _BAND_MEDIUM_MAX:
        band = "medium"
    else:
        band = "heavy"
    return {"n_modes": len(modes), "agent_hops": hops, "band": band}


def gates_in_chain(modes: List[str]) -> List[dict]:
    """The human gates a chain PAUSES at, in order ({after: mode, gate: '/idea-bet'} ...)."""
    mg = load_catalog().get("mode_gates") or {}
    out: List[dict] = []
    for m in modes:
        for g in (mg.get(m) or []):
            out.append({"after": m, "gate": g})
    return out


def validate_chain(modes: List[str]) -> dict:
    """Verdict for an ordered mode chain.

    - unknown mode (not in the registry) -> violation.
    - spec-only mode (in the registry but not operated) -> FLAGGED (warning + spec_only list); honest
      that this link is hand-driven, not push-button — never silently treated as one-button.
    - phase order: a chain must be NON-DECREASING in phase_rank (discovery -> ideate -> design ->
      venue); a strictly-decreasing step is a violation. Within a rank the order is free."""
    cat = load_catalog()
    rank = cat.get("phase_rank") or {}
    known = all_modes()
    wired = wired_modes()
    violations: List[str] = []
    warnings: List[str] = []
    spec_only: List[str] = []

    for m in modes:
        if m not in known:
            violations.append(f"unknown mode {m!r} — not in mode_registry.yaml")
    for m in modes:
        if m in known and m not in wired:
            spec_only.append(m)
            warnings.append(
                f"{m!r} is spec-only (not one-button yet) — this link must be hand-driven per §3, "
                "not presented as push-button")

    ranked = [(m, rank.get(m)) for m in modes if rank.get(m) is not None]
    for (a_m, a_r), (b_m, b_r) in zip(ranked, ranked[1:]):
        if b_r < a_r:
            violations.append(
                f"phase order: {b_m!r} (rank {b_r}) cannot run after {a_m!r} (rank {a_r}) — a chain "
                "runs discovery -> ideate -> design -> venue")

    return {"ok": not violations, "violations": violations, "warnings": warnings,
            "spec_only": spec_only}


def mode_questions(mode: str) -> List[dict]:
    """The per-mode drill-down questions to ask AFTER this mode is included in the picked tier."""
    return list((load_catalog().get("mode_questions") or {}).get(mode) or [])


# --------------------------------------------------------------------------- propose tiers

def _tier_view(tier: dict) -> dict:
    modes = list(tier.get("modes") or [])
    return {"id": tier.get("id"), "label": tier.get("label", ""),
            "recommended": bool(tier.get("recommended")),
            "modes": modes, "why": tier.get("why", ""),
            "cost": estimate_cost(modes), "gates": gates_in_chain(modes),
            "validation": validate_chain(modes)}


def propose(intent_id: str) -> dict:
    """An intent's full tier menu (each tier annotated with cost / gates / validation)."""
    intents = load_catalog().get("intents") or {}
    if intent_id not in intents:
        raise KeyError(f"unknown intent {intent_id!r}; known: {sorted(intents)}")
    spec = intents[intent_id] or {}
    return {"intent": intent_id, "description": spec.get("description", ""),
            "tiers": [_tier_view(t) for t in (spec.get("tiers") or [])]}


def recommended_tier(tiers: List[dict]) -> Optional[dict]:
    """The tier marked recommended (else the middle one, else None)."""
    for t in tiers:
        if t.get("recommended"):
            return t
    return tiers[len(tiers) // 2] if tiers else None


def propose_for_request(request: str, intent: Optional[str] = None) -> dict:
    """The full proposal the CLI/orchestrator needs to render the tier AskUserQuestion + the
    per-mode drill-down rounds. When `intent` is given it is used verbatim; otherwise the request is
    matched (and if nothing matches, EVERY intent is returned so the director chooses the arc)."""
    if intent:
        intent_ids, matched = [intent], True
    else:
        intent_ids, matched = best_intents(request)
    return {"request": request, "matched": matched,
            "intents": [propose(i) for i in intent_ids],
            "mode_questions": load_catalog().get("mode_questions") or {},
            "note": "Render the recommended intent's tiers as the FIRST AskUserQuestion (tier pick, "
                    "with cost + the gates it pauses at). THEN ask each chosen mode's drill-down "
                    "(mode_questions) — one round per mode. THEN run the chain link-by-link with "
                    "`operate begin --mode <m> --upstream-run <prev>`, pausing at each gate."}


# --------------------------------------------------------------------------- chain threading

def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_yaml(path: Path) -> Optional[dict]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return value if isinstance(value, dict) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _mode_handoff(mode: str) -> dict:
    spec = ((load_mode_registry().get("modes") or {}).get(mode) or {}).get("handoff") or {}
    return dict(spec) if isinstance(spec, dict) else {}


def _normalise_contract(raw: dict, *, pinned: bool) -> dict:
    return {
        "contract_version": str(raw.get("contract_version") or HANDOFF_CONTRACT_VERSION),
        "product_version": str(raw.get("product_version") or "unversioned"),
        "primary_markdown": str(raw.get("primary_markdown") or ""),
        "reusable_artifacts": [str(x) for x in (raw.get("reusable_artifacts") or [])],
        "accepts": [str(x) for x in (raw.get("accepts") or [])],
        "contract_pinned": pinned,
        "contract_source": "task_frame" if pinned else "registry_fallback_for_legacy_run",
    }


def _contract_for_run(payload: dict, mode: str) -> dict:
    pinned = payload.get("product_contract") or {}
    if isinstance(pinned, dict) and pinned.get("product_version"):
        return _normalise_contract(pinned, pinned=True)
    return _normalise_contract(_mode_handoff(mode), pinned=False)


def _declared_files(run_dir: Path, contract: dict) -> tuple[list[Path], list[str]]:
    """Resolve the product contract to actual files without guessing a stage path."""
    found: list[Path] = []
    missing: list[str] = []
    primary = str(contract.get("primary_markdown") or "")
    if primary:
        matches = sorted(p for p in run_dir.glob(primary.replace("<paper>", "*")) if p.is_file())
        if matches:
            found.extend(matches)
        else:
            missing.append(primary)
    for name in contract.get("reusable_artifacts") or []:
        matches = sorted(p for p in (run_dir / "evidence").glob(f"**/{name}") if p.is_file())
        if matches:
            found.extend(matches)
        else:
            missing.append(name)
    return found, missing


def _manifest_item(path: Path, run_dir: Path) -> dict:
    raw = _read_json(path) or {}
    try:
        relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return {
        "path": str(path.resolve()),
        "run_relative_path": relative,
        "sha256": _sha256_file(path),
        "artifact_type": str(raw.get("artifact_type") or "retrieval_bundle"),
        "schema_version": str(raw.get("schema_version") or "unversioned"),
        "status": str(raw.get("status") or "available"),
    }


def validate_upstream_grounding(grounding: dict) -> list[str]:
    """Verify only transport integrity and declared contract compatibility.

    This deliberately does not re-review upstream science. It prevents a
    downstream mode from silently consuming a replaced or missing file.
    """
    errors: list[str] = []
    if grounding.get("handoff_contract_version") != HANDOFF_CONTRACT_VERSION:
        errors.append(
            f"unsupported handoff contract {grounding.get('handoff_contract_version')!r}; "
            f"expected {HANDOFF_CONTRACT_VERSION!r}"
        )
    for run in grounding.get("upstream_runs") or []:
        for item in run.get("artifact_manifest") or []:
            path = Path(str(item.get("path") or ""))
            if not path.is_file():
                errors.append(f"{run.get('run_id')}: missing handoff file {path}")
                continue
            expected = str(item.get("sha256") or "")
            actual = _sha256_file(path)
            if expected != actual:
                errors.append(
                    f"{run.get('run_id')}: handoff hash mismatch for "
                    f"{item.get('run_relative_path') or path.name}"
                )
    downstream = grounding.get("downstream_contract") or {}
    accepted = {str(value) for value in downstream.get("accepts") or []}
    if grounding.get("downstream_mode") and downstream and not downstream.get("contract_pinned"):
        errors.append("downstream product contract is not pinned in the task frame")
    for run in grounding.get("upstream_runs") or []:
        product = str((run.get("product_contract") or {}).get("product_version") or "")
        if accepted and product and product not in accepted:
            errors.append(
                f"mode handoff mismatch: downstream accepts {sorted(accepted)}, "
                f"but upstream {run.get('run_id')!r} provides {product!r}"
            )
    return errors


def _validate_downstream_compatibility(runs: list[dict], downstream_mode: Optional[str],
                                       downstream_contract: Optional[dict] = None) -> None:
    if not downstream_mode:
        return
    downstream = downstream_contract or _normalise_contract(_mode_handoff(downstream_mode), pinned=False)
    accepted = {str(value) for value in downstream.get("accepts") or []}
    for run in runs:
        product = str((run.get("product_contract") or {}).get("product_version") or "")
        if product and product not in accepted:
            raise ValueError(
                f"mode handoff mismatch: {downstream_mode!r} accepts {sorted(accepted)}, "
                f"but upstream {run.get('run_id')!r} provides {product!r}"
            )


def upstream_grounding(prev_run_dirs: List[str], downstream_mode: Optional[str] = None,
                       downstream_contract: Optional[dict] = None) -> dict:
    """Compact handoff extracted from each completed upstream link (mode + request + REPORT summary +
    any ranked idea backlog + the on-disk key artifacts to read by reference). Robust to missing
    files — a link with nothing readable contributes an empty-but-named entry, never an exception."""
    runs: List[dict] = []
    for rd in prev_run_dirs:
        d = Path(rd)
        entry: dict = {"run_id": d.name, "run_dir": str(d.resolve()), "mode": "",
                       "request": "", "summary": "", "top_ideas": [],
                       "key_artifacts": [], "reusable_inputs": [],
                       "artifact_manifest": [], "run_status": "unknown",
                       "delivery_status": "UNKNOWN", "project": "",
                       "product_contract": {}, "missing_declared_artifacts": []}
        payload: dict = {}
        tf = _read_json(d / "task_frame.artifact.json")
        if tf:
            payload = tf.get("payload") or {}
            entry["mode"] = payload.get("mode") or ""
            entry["request"] = payload.get("request_text") or ""
            entry["run_id"] = payload.get("task_id") or d.name
            entry["project"] = payload.get("project") or ""
        manifest = _read_yaml(d / "manifest.yaml") or {}
        entry["run_status"] = str(manifest.get("status") or "unknown")
        entry["product_contract"] = _contract_for_run(payload, str(entry["mode"]))
        report = d / "evidence" / "REPORT" / "report-note.artifact.json"
        rn = _read_json(report)
        if rn:
            report_payload = rn.get("payload") or {}
            entry["summary"] = report_payload.get("summary") or ""
            entry["delivery_status"] = str(
                report_payload.get("markdown_delivery_status")
                or report_payload.get("delivery_status")
                or ("USABLE" if entry["run_status"] == "done" else "UNKNOWN")
            )
            entry["key_artifacts"].append(str(report))
        backlog = d / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
        bl = _read_json(backlog)
        if bl:
            ranked = ((bl.get("payload") or {}).get("ranked_ideas")) or []
            entry["top_ideas"] = [{"idea_id": i.get("idea_id"), "summary": i.get("summary")}
                                  for i in ranked[:5] if isinstance(i, dict)]
            entry["key_artifacts"].append(str(backlog))
        fallback_candidates = (
            d / "inbox" / "search-results.json",
            d / "evidence" / "DISCOVER" / "evidence-table.artifact.json",
            d / "evidence" / "DISCOVER" / "source-quality-report.artifact.json",
            d / "evidence" / "DISCOVER" / "claim-list.artifact.json",
            d / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json",
            d / "evidence" / "DISCOVER" / "citation-attribution-report.artifact.json",
            d / "evidence" / "DISCOVER" / "contradiction-report.artifact.json",
            d / "evidence" / "DISCOVER" / "landscape-map.artifact.json",
            d / "evidence" / "DISCOVER" / "gap-dossier.artifact.json",
        )
        declared, missing = _declared_files(d, entry["product_contract"])
        entry["missing_declared_artifacts"] = missing
        primary = str(entry["product_contract"].get("primary_markdown") or "")
        for path in declared:
            if primary and path.match(primary.replace("<paper>", "*")):
                entry["key_artifacts"].append(str(path.resolve()))
        entry["reusable_inputs"] = [
            str(path.resolve()) for path in declared + list(fallback_candidates) if path.is_file()
        ]
        manifested_paths = []
        for raw_path in entry["key_artifacts"] + entry["reusable_inputs"]:
            path = Path(raw_path)
            if path.is_file() and path.resolve() not in manifested_paths:
                manifested_paths.append(path.resolve())
                entry["artifact_manifest"].append(_manifest_item(path, d))
        runs.append(entry)
    if downstream_mode and downstream_contract is None:
        downstream_contract = _normalise_contract(_mode_handoff(downstream_mode), pinned=False)
    _validate_downstream_compatibility(runs, downstream_mode, downstream_contract)
    return {
        "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "downstream_mode": downstream_mode or "",
        "downstream_contract": downstream_contract or {},
        "upstream_runs": runs,
    }


def write_upstream_grounding(new_run_dir: str, prev_run_dirs: List[str],
                             downstream_mode: Optional[str] = None) -> str:
    """Write the downstream run's `inbox/upstream-grounding.json` from the upstream links. Returns
    the path. Called by `operate begin --upstream-run <prev>` before the first worker is built."""
    inbox = Path(new_run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    out = inbox / UPSTREAM_GROUNDING_FILE
    task_frame = _read_json(Path(new_run_dir) / "task_frame.artifact.json") or {}
    payload = task_frame.get("payload") or {}
    pinned_downstream = _contract_for_run(payload, str(payload.get("mode") or downstream_mode or ""))
    out.write_text(json.dumps(upstream_grounding(prev_run_dirs, downstream_mode, pinned_downstream),
                              ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return str(out)


def _grounding_block(run_dir: str, grounding: dict) -> str:
    lines = [
        "",
        "",
        "--- PRIOR CHAIN CONTEXT (this run CONTINUES a director-approved research chain) ---",
        "This is NOT a fresh start: earlier links already produced grounded, gated results. The full "
        f"handoff is `{run_dir}/inbox/{UPSTREAM_GROUNDING_FILE}` — read it by reference. In brief:",
    ]
    for up in grounding.get("upstream_runs") or []:
        mode = up.get("mode") or "?"
        rid = up.get("run_id") or "?"
        summ = (up.get("summary") or "").strip() or "(no REPORT summary on disk)"
        lines.append(f"  • [{mode} · {rid}] {summ}")
        arts = up.get("key_artifacts") or []
        if arts:
            lines.append(f"      key artifacts (read by reference, do NOT redo): {', '.join(arts)}")
        reusable = up.get("reusable_inputs") or []
        if reusable:
            lines.append(
                "      frozen reusable evidence (reuse before new retrieval): "
                + ", ".join(reusable)
            )
        ideas = up.get("top_ideas") or []
        if ideas:
            ids = ", ".join(str(i.get("idea_id")) for i in ideas if i.get("idea_id"))
            if ids:
                lines.append(f"      candidate ideas carried in: {ids}")
    lines.append(
        "Build the NEXT step ON this established ground; do not repeat upstream work. If the upstream "
        "output conflicts with your inputs, SAY SO rather than silently diverging — you never re-scope.")
    return "\n".join(lines)


def _grounding_pointer_block(run_dir: str) -> str:
    return (
        "\n\n--- PRIOR CHAIN CONTEXT (pointer only) ---\n"
        f"The root worker already receives the full upstream handoff. Read `{run_dir}/inbox/"
        f"{UPSTREAM_GROUNDING_FILE}` only if a direct scientific dependency is absent from your "
        "predecessor bundle; do not repeat upstream retrieval or synthesis."
    )


def augment_worker_with_upstream(worker: Optional[dict], run_dir: str) -> Optional[dict]:
    """Append the PRIOR CHAIN CONTEXT block to a worker spec's prompt(s) when this run has upstream
    grounding (a no-op otherwise, so single-mode runs are untouched). Handles both worker shapes: a
    single `{prompt: ...}` and a panel `{workers: [{prompt: ...}, ...]}`."""
    if not worker:
        return worker
    p = Path(run_dir) / "inbox" / UPSTREAM_GROUNDING_FILE
    grounding = _read_json(p)
    if not grounding or not (grounding.get("upstream_runs")):
        return worker
    integrity_errors = validate_upstream_grounding(grounding)
    ledger_path = Path(run_dir) / "ledger.jsonl"
    if ledger_path.is_file():
        pin = last_of_type(read_events(ledger_path), "upstream_handoff_pinned")
        if pin is None:
            integrity_errors.append("upstream handoff manifest is not pinned in the run ledger")
        elif str((pin.get("payload") or {}).get("grounding_sha256") or "") != _sha256_file(p):
            integrity_errors.append("upstream handoff manifest hash does not match its ledger pin")
    if integrity_errors:
        raise ValueError("upstream handoff integrity failed: " + "; ".join(integrity_errors))
    block = _grounding_block(run_dir, grounding)
    pointer = _grounding_pointer_block(run_dir)
    if "workers" in worker and isinstance(worker.get("workers"), list):
        for w in worker["workers"]:
            if isinstance(w, dict) and isinstance(w.get("prompt"), str):
                dependencies = list(w.get("depends_on") or [])
                w["prompt"] = w["prompt"] + (pointer if dependencies else block)
    elif isinstance(worker.get("prompt"), str):
        worker["prompt"] = worker["prompt"] + block
    return worker
