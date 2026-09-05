"""Outcome recipes — the logic behind the director-facing "你想得到什么" menu (v4 P2.1).

`plan_catalog.yaml` answers "the director said X, which modes run?". It is reactive: a director who
does not know `deep_ideation` exists cannot ask for it. This module answers the other question —
"what can I end up holding, and what does each of those cost me?" — over the six outcomes declared in
`orchestrator/outcome_recipes.yaml`.

Division of labour, deliberately:
  - this module      DATA + DERIVATION (no rendering, so it never imports `reporting` → no cycle)
  - reporting/outcomes.py   the plain-Chinese menu and compiled-recipe cards
  - workbench/cli.py        the two navigation verbs (they print commands; they cannot start a run)

Nothing here is declared that can be derived. Team size, hop budget, cost band, human gates and the
deliverable file path are read from `mode_registry.yaml` + `plan_catalog.yaml` at call time, and
:func:`validate_all` REJECTS a recipe that tries to state any of them itself — a hardcoded number in
the menu is a number that goes stale and then misleads the director.

Read-only. No model call. Never starts a run.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

from . import research_plan, worker_census

_PKG = Path(__file__).resolve().parents[1]                        # research_agent_teams/
_RECIPES_PATH = _PKG / "orchestrator" / "outcome_recipes.yaml"
_GATES_DIR = _PKG / "gates"

#: The main-thread role (director rule D7). A recipe's seats are worker SUB-agents; this name must
#: never appear among them, or the menu would be promising that the conductor plays an instrument.
MAIN_THREAD_AGENT = "research-orchestrator"

#: Keys a recipe may NOT declare, because they are derived from the registry. Guarding the data shape
#: is what keeps invariant "derived, never declared" true for recipes nobody has written yet.
_FORBIDDEN_KEYS = frozenset({
    "seats", "team", "team_size", "agents", "agent_subset", "gates", "budget", "hops",
    "agent_hops", "cost", "band", "deliverable_path", "deliverable_file", "executor", "main_thread",
})

#: A seat count written into prose is the "declared, not derived" defect wearing a sentence: the
#: number is right the day it is typed and wrong the day the registry changes. Structural counts that
#: are NOT derivable from the registry (e.g. "3 个互相独立的审稿人", owned by the mode's own recipe) are fine.
_SEAT_COUNT_IN_PROSE = re.compile(r"\d+\s*(?:席|个\s*agent)")

#: A mode whose presence FORCES an honesty statement in the recipe's `ceiling`, and the substring
#: that statement must contain. The point is not the wording — it is that a future recipe cannot
#: quietly inherit a limit without telling the director about it.
_REQUIRED_CEILINGS: dict[str, tuple[str, ...]] = {
    # No GPU receipt => scripts + preregistration only, metrics structurally empty.
    "full_rigor_minimal": ("GPU",),
    # Reading a paper produces DRAFT knowledge; only the human gate admits it to the vault.
    "ingest_paper": ("/promote-to-vault",),
    "read_paper_deep": ("/promote-to-vault",),
}


# --------------------------------------------------------------------------------- loading

def load_recipes(path: Optional[str | Path] = None) -> dict[str, Any]:
    """The raw recipe catalog (the human-authored SSOT)."""
    p = Path(path) if path else _RECIPES_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def recipe_ids(path: Optional[str | Path] = None) -> list[str]:
    """Menu order — the order the director sees, i.e. file order."""
    return list((load_recipes(path).get("recipes") or {}).keys())


def known_gate_names() -> set[str]:
    """The gates that actually have a spec file in `gates/` (`/idea-bet` ← `idea-bet.md`)."""
    return {f"/{p.stem}" for p in sorted(_GATES_DIR.glob("*.md"))}


# --------------------------------------------------------------------------------- derivation

def mode_facts(mode: str) -> dict[str, Any]:
    """Everything the menu needs about ONE mode, read from the registry — never hardcoded."""
    spec = (research_plan.load_mode_registry().get("modes") or {}).get(mode) or {}
    seats = list(spec.get("agent_subset") or [])
    handoff = spec.get("handoff") or {}
    entry = str(spec.get("entry_stage") or "")
    # Of the declared roster, how many seats the mode's own recipe never names — they fire only on
    # the mechanism-council path. Measured 2026-08-04: 15 seats across 3 modes. Showing a ceiling
    # without this split would read as a dispatch promise (see worker_census).
    council_only = [s for s in seats if not worker_census.dispatched_by_recipe(s)]
    ceiling = (spec.get("budget") or {}).get("max_agent_hops")
    return {
        "mode": mode,
        "operated": bool(spec.get("operated")),
        "seats": len(seats),
        "recipe_seats": len(seats) - len(council_only),
        "council_only": len(council_only),
        "seat_names": seats,
        "hops": research_plan.UNBOUNDED_HOP_COST if ceiling is None else int(ceiling),
        "entry_stage": entry,
        "stage_path": list(spec.get("stage_path") or []),
        "gate_stages": list(spec.get("director_gate_stages") or []),
        "deliverable": handoff.get("primary_markdown") or "",
        # Every mode that starts in DISCOVER takes the standard grounding step; the others enter
        # downstream of it and would have nothing to search for.
        "needs_pre_search": entry == "DISCOVER",
    }


def _variants(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return list(recipe.get("variants") or [])


def _pick_variant(recipe: dict[str, Any], variant: Optional[str]) -> dict[str, Any]:
    variants = _variants(recipe)
    if not variants:
        raise ValueError("recipe declares no variants")
    if variant:
        for v in variants:
            if str(v.get("id")) == variant:
                return v
        raise KeyError(f"unknown variant {variant!r}; known: {[v.get('id') for v in variants]}")
    for v in variants:
        if v.get("recommended"):
            return v
    return variants[0]


def resolve(recipe_id: str, *, variant: Optional[str] = None,
            path: Optional[str | Path] = None) -> dict[str, Any]:
    """One outcome + one variant, fully annotated with DERIVED facts."""
    recipes = load_recipes(path).get("recipes") or {}
    if recipe_id not in recipes:
        raise KeyError(f"unknown outcome {recipe_id!r}; known: {sorted(recipes)}")
    recipe = recipes[recipe_id] or {}
    picked = _pick_variant(recipe, variant)
    modes = list(picked.get("modes") or [])
    facts = [mode_facts(m) for m in modes]
    return {
        "contract": "outcome-recipe/v1",
        "id": recipe_id,
        "want": recipe.get("want", ""),
        "deliverable": recipe.get("deliverable", ""),
        "for_you_when": recipe.get("for_you_when", ""),
        "covers_intents": list(recipe.get("covers_intents") or []),
        "ceiling": list(recipe.get("ceiling") or []),
        "variant": {
            "id": picked.get("id"),
            "label": picked.get("label", ""),
            "recommended": bool(picked.get("recommended")),
            "why": picked.get("why", ""),
        },
        "variants": [{"id": v.get("id"), "label": v.get("label", ""),
                      "recommended": bool(v.get("recommended")),
                      "modes": list(v.get("modes") or []), "why": v.get("why", "")}
                     for v in _variants(recipe)],
        "modes": modes,
        "mode_facts": facts,
        # ---- derived, every one of them ----
        "seats": sum(f["seats"] for f in facts),
        "recipe_seats": sum(f["recipe_seats"] for f in facts),
        "council_only": sum(f["council_only"] for f in facts),
        "cost": research_plan.estimate_cost(modes),
        "gates": research_plan.gates_in_chain(modes),
        "deliverables": [{"mode": f["mode"], "path": f["deliverable"]} for f in facts],
        "validation": research_plan.validate_chain(modes),
        "questions": {m: research_plan.mode_questions(m) for m in modes if research_plan.mode_questions(m)},
    }


def resolve_all(*, path: Optional[str | Path] = None) -> list[dict[str, Any]]:
    """Every outcome at its recommended variant — the six-choice menu, annotated."""
    return [resolve(rid, path=path) for rid in recipe_ids(path)]


#: The director's own sentence is what gets pinned as the run's north star, so the compiled command
#: must NOT quietly default to the recipe's generic want ("我想要一个能下注的研究方向" is a wish, not a
#: direction — it bounds nothing, and every drift check downstream would be vacuous).
REQUEST_PLACEHOLDER = "<把你的原话写在这里 —— 这句会被钉成这次运行的北极星>"


def command_chain(recipe_id: str, *, variant: Optional[str] = None,
                  project: Optional[str] = None, request: Optional[str] = None,
                  path: Optional[str | Path] = None) -> list[dict[str, Any]]:
    """The exact commands to run this outcome, link by link.

    Link N>1 is threaded with `--upstream-run <link N-1's run id>` so it reads what came before. A
    gated link is followed by a STOP: the director decides there, never the machine.
    """
    view = resolve(recipe_id, variant=variant, path=path)
    slug = project or "<project-slug>"
    ask = request or REQUEST_PLACEHOLDER
    steps: list[dict[str, Any]] = []
    for index, facts in enumerate(view["mode_facts"]):
        mode = facts["mode"]
        begin = (f'python -m research_agent_teams.operate begin --mode {mode} '
                 f'--project {slug} --request "{ask}"')
        if index:
            begin += f' --upstream-run <{view["mode_facts"][index - 1]["mode"]} 的 run_id>'
        cmds = [begin]
        if facts["needs_pre_search"]:
            cmds.append("python -m research_agent_teams.operate pre-search --run-id <run_id>")
        cmds.append("# 然后按打印出来的 worker 规格逐个派 sub-agent；每个阶段 run-dets → commit")
        steps.append({"link": index + 1, "mode": mode, "seats": facts["seats"],
                      "commands": cmds,
                      "stops_at": [g["gate"] for g in view["gates"] if g["after"] == mode]})
    return steps


# --------------------------------------------------------------------------------- matching

def match_recipe(request: str, *, path: Optional[str | Path] = None) -> Optional[dict[str, Any]]:
    """Which outcome a free-text request lands on, via the plan catalog's intent matching.

    Returns ``None`` when the request matches no intent — the caller then SHOWS the menu instead of
    guessing, which is the whole point of having a menu.
    """
    intents, matched = research_plan.best_intents(request or "")
    if not matched:
        return None
    catalog = load_recipes(path).get("recipes") or {}
    by_intent: dict[str, str] = {}
    for rid, recipe in catalog.items():
        for iid in (recipe or {}).get("covers_intents") or []:
            by_intent.setdefault(str(iid), rid)
    for iid in intents:
        if iid in by_intent:
            rid = by_intent[iid]
            return {"id": rid, "via_intent": iid, "want": (catalog[rid] or {}).get("want", "")}
    return None


# --------------------------------------------------------------------------------- validation

def coverage(*, path: Optional[str | Path] = None) -> dict[str, Any]:
    """Which operated modes the menu can reach. A mode reachable from no outcome is invisible."""
    operated = research_plan.wired_modes()
    reached: set[str] = set()
    for recipe in (load_recipes(path).get("recipes") or {}).values():
        for v in _variants(recipe or {}):
            reached.update(str(m) for m in (v.get("modes") or []))
    return {"operated": sorted(operated), "covered": sorted(reached & operated),
            "missing": sorted(operated - reached), "extra": sorted(reached - operated)}


def _check_forbidden(where: str, block: Any, violations: list[str]) -> None:
    if not isinstance(block, dict):
        return
    for key in sorted(set(block) & _FORBIDDEN_KEYS):
        violations.append(
            f"{where}: declares {key!r} — that fact is DERIVED from mode_registry.yaml / "
            "plan_catalog.yaml and must not be restated here (it would go stale)")


def validate_all(*, path: Optional[str | Path] = None) -> dict[str, Any]:
    """Every invariant the menu must satisfy, as a data verdict.

    Used by `tests/test_outcome_recipes.py` AND by the CLI, so a bad hand-edit of the yaml surfaces
    the moment the director asks for the menu, not silently at run time.
    """
    catalog = load_recipes(path)
    recipes = catalog.get("recipes") or {}
    violations: list[str] = []
    warnings: list[str] = []

    if not recipes:
        violations.append("no recipes declared")

    known_intents = set(research_plan.all_intents())
    gate_specs = known_gate_names()

    for rid, recipe in recipes.items():
        recipe = recipe or {}
        where = f"outcome {rid!r}"
        _check_forbidden(where, recipe, violations)
        for field in ("want", "deliverable", "ceiling"):
            if not recipe.get(field):
                violations.append(f"{where}: missing required field {field!r}")
        for field in ("want", "deliverable", "for_you_when"):
            if _SEAT_COUNT_IN_PROSE.search(str(recipe.get(field) or "")):
                violations.append(
                    f"{where}: {field!r} states a seat count in prose — seats are DERIVED from "
                    "mode_registry.yaml and the sentence goes stale the day the registry changes")
        for iid in recipe.get("covers_intents") or []:
            if str(iid) not in known_intents:
                violations.append(f"{where}: covers unknown intent {iid!r} "
                                  f"(not in plan_catalog.yaml)")
        variants = _variants(recipe)
        if not variants:
            violations.append(f"{where}: declares no variants")
        recommended = [v for v in variants if v.get("recommended")]
        if len(recommended) != 1:
            violations.append(f"{where}: needs exactly ONE recommended variant, found "
                              f"{len(recommended)}")

        chain_modes: set[str] = set()
        for v in variants:
            vid = v.get("id")
            vwhere = f"{where} variant {vid!r}"
            _check_forbidden(vwhere, v, violations)
            modes = [str(m) for m in (v.get("modes") or [])]
            if not modes:
                violations.append(f"{vwhere}: declares no modes")
            chain_modes.update(modes)
            verdict = research_plan.validate_chain(modes)
            violations.extend(f"{vwhere}: {msg}" for msg in verdict["violations"])
            for mode in verdict["spec_only"]:
                violations.append(
                    f"{vwhere}: {mode!r} is spec-only — an outcome menu may only offer one-button "
                    "modes, otherwise it promises push-button work that is hand-driven")
            for facts in (mode_facts(m) for m in modes):
                if not facts["seats"]:
                    violations.append(f"{vwhere}: mode {facts['mode']!r} declares no agent_subset — "
                                      "an outcome with no seats has nobody to do the work")
                if MAIN_THREAD_AGENT in facts["seat_names"]:
                    violations.append(
                        f"{vwhere}: mode {facts['mode']!r} lists {MAIN_THREAD_AGENT!r} as a seat — "
                        "every seat is a worker SUB-agent; the main thread never takes a seat (D7)")
                if not facts["deliverable"]:
                    violations.append(
                        f"{vwhere}: mode {facts['mode']!r} has no handoff.primary_markdown — then "
                        "\"你最后拿到什么\" would be prose, not a file the director can open")
            for gate in (g["gate"] for g in research_plan.gates_in_chain(modes)):
                if gate not in gate_specs:
                    violations.append(f"{vwhere}: routes through {gate} but there is no spec file "
                                      f"in gates/ for it")

        ceiling_text = "\n".join(str(c) for c in recipe.get("ceiling") or [])
        for mode, required in _REQUIRED_CEILINGS.items():
            if mode in chain_modes:
                for needle in required:
                    if needle not in ceiling_text:
                        violations.append(
                            f"{where}: contains {mode!r} but its ceiling never mentions {needle!r} "
                            "— the director would not be told the limit of what they get")

    cov = coverage(path=path)
    for mode in cov["missing"]:
        violations.append(
            f"coverage: operated mode {mode!r} is reachable from NO outcome — a capability the "
            "director cannot reach is a capability that does not exist to them")
    for mode in cov["extra"]:
        violations.append(f"coverage: {mode!r} appears in an outcome but is not an operated mode")

    return {"ok": not violations, "violations": violations, "warnings": warnings,
            "n_recipes": len(recipes), "coverage": cov}


def assert_valid(*, path: Optional[str | Path] = None) -> dict[str, Any]:
    """:func:`validate_all`, raising on violation — for callers that must not render a broken menu."""
    verdict = validate_all(path=path)
    if not verdict["ok"]:
        raise ValueError("outcome_recipes.yaml is invalid:\n  - "
                         + "\n  - ".join(verdict["violations"]))
    return verdict


__all__ = ["MAIN_THREAD_AGENT", "REQUEST_PLACEHOLDER", "assert_valid", "command_chain", "coverage",
           "known_gate_names", "load_recipes", "match_recipe", "mode_facts", "recipe_ids", "resolve",
           "resolve_all", "validate_all"]
