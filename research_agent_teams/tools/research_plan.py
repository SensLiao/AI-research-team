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

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_PKG = Path(__file__).resolve().parents[1]                       # research_agent_teams/
_CATALOG_PATH = _PKG / "orchestrator" / "plan_catalog.yaml"
_REGISTRY_PATH = _PKG / "orchestrator" / "mode_registry.yaml"

UPSTREAM_GROUNDING_FILE = "upstream-grounding.json"              # under <run>/inbox/

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


def upstream_grounding(prev_run_dirs: List[str]) -> dict:
    """Compact handoff extracted from each completed upstream link (mode + request + REPORT summary +
    any ranked idea backlog + the on-disk key artifacts to read by reference). Robust to missing
    files — a link with nothing readable contributes an empty-but-named entry, never an exception."""
    runs: List[dict] = []
    for rd in prev_run_dirs:
        d = Path(rd)
        entry: dict = {"run_id": d.name, "mode": "", "request": "", "summary": "",
                       "top_ideas": [], "key_artifacts": []}
        tf = _read_json(d / "task_frame.artifact.json")
        if tf:
            payload = tf.get("payload") or {}
            entry["mode"] = payload.get("mode") or ""
            entry["request"] = payload.get("request_text") or ""
            entry["run_id"] = payload.get("task_id") or d.name
        report = d / "evidence" / "REPORT" / "report-note.artifact.json"
        rn = _read_json(report)
        if rn:
            entry["summary"] = ((rn.get("payload") or {}).get("summary")) or ""
            entry["key_artifacts"].append(str(report))
        backlog = d / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
        bl = _read_json(backlog)
        if bl:
            ranked = ((bl.get("payload") or {}).get("ranked_ideas")) or []
            entry["top_ideas"] = [{"idea_id": i.get("idea_id"), "summary": i.get("summary")}
                                  for i in ranked[:5] if isinstance(i, dict)]
            entry["key_artifacts"].append(str(backlog))
        runs.append(entry)
    return {"upstream_runs": runs}


def write_upstream_grounding(new_run_dir: str, prev_run_dirs: List[str]) -> str:
    """Write the downstream run's `inbox/upstream-grounding.json` from the upstream links. Returns
    the path. Called by `operate begin --upstream-run <prev>` before the first worker is built."""
    inbox = Path(new_run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    out = inbox / UPSTREAM_GROUNDING_FILE
    out.write_text(json.dumps(upstream_grounding(prev_run_dirs), ensure_ascii=False, indent=2),
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
        ideas = up.get("top_ideas") or []
        if ideas:
            ids = ", ".join(str(i.get("idea_id")) for i in ideas if i.get("idea_id"))
            if ids:
                lines.append(f"      candidate ideas carried in: {ids}")
    lines.append(
        "Build the NEXT step ON this established ground; do not repeat upstream work. If the upstream "
        "output conflicts with your inputs, SAY SO rather than silently diverging — you never re-scope.")
    return "\n".join(lines)


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
    block = _grounding_block(run_dir, grounding)
    if "workers" in worker and isinstance(worker.get("workers"), list):
        for w in worker["workers"]:
            if isinstance(w, dict) and isinstance(w.get("prompt"), str):
                w["prompt"] = w["prompt"] + block
    elif isinstance(worker.get("prompt"), str):
        worker["prompt"] = worker["prompt"] + block
    return worker
