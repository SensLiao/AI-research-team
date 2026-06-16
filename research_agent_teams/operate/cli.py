"""Operate CLI — the interface the research-orchestrator skill calls to drive a one-button run.

The skill's loop for `new_direction` (run from the project root):
    begin --mode new_direction --project <slug> --request "..."   -> run_id (+ DISCOVER worker spec)
                                                         (--project = a registered research project;
                                                          the run lives in runs/<project>/<run_id>/)
    [spawn the printed LLM worker -> it writes inbox/<STAGE>.bundle.json]
    run-dets --run-id <id> --stage DISCOVER           -> runs the 2 hard gates + classify + novelty
                                                         (exit 3 + "gate":"BLOCK" if a gate refuses)
    commit  --run-id <id> --stage DISCOVER            -> checkpoint; prints next stage
    worker  --run-id <id> --stage IDEATE --request .. -> the IDEATE worker spec to spawn
    run-dets / commit --stage IDEATE                  -> at the director gate, "paused_for_director": true
    menu    --run-id <id>                             -> the ranked menu to show the director
    [director decides; only then] run-dets / commit --stage REPORT -> done

Every call prints one JSON object so the skill can parse it. The mode is fixed at `begin` and read back
from the run's task_frame by later commands (no --mode needed after begin).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import spine
from .artifacts import GateBlock
from .modes import REGISTRY
from ..tools import execution_registry as exreg
from ..tools import lifecycle as lifecycle_tool
from ..tools import projects as projects_tool
from ..tools import resources as rp
from ..tools import runstore
from ..tools import workspace as ws_tool
from ..tools.budget_tracker import BudgetExceeded
from ..tools.runstore import find_run_dir
from ..tools.scope_guard import discover_vault_root

DEFAULT_RUNS_DIR = "research_agent_teams/runs"
DEFAULT_PROJECTS_DIR = "research_agent_teams/projects"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_dir(runs_dir: str, run_id: str) -> str:
    """Locate the run in either layout (runs/<project>/<run_id>/ or legacy flat). Clean exit if absent."""
    try:
        return str(find_run_dir(runs_dir, run_id))
    except (FileNotFoundError, RuntimeError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _mode_module(mode: str):
    mod = REGISTRY.get(mode)
    if mod is None:
        _emit({"error": f"mode {mode!r} is not wired in the operate layer yet",
               "wired_modes": sorted(REGISTRY)})
        sys.exit(2)
    return mod


def _mode_from_run(runs_dir: str, run_id: str) -> str:
    tf = json.loads((Path(_run_dir(runs_dir, run_id)) / "task_frame.artifact.json").read_text(encoding="utf-8"))
    return tf["payload"]["mode"]


def _policy_from_run(runs_dir: str, run_id: str) -> str:
    tf = json.loads((Path(_run_dir(runs_dir, run_id)) / "task_frame.artifact.json").read_text(encoding="utf-8"))
    return tf["payload"].get("model_policy", "max_quality")


def _north_star_from_args(a) -> dict:
    """The run's direction contract from the CLI flags (statement defaults to the request)."""
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip()]  # noqa: E731
    return {"statement": (a.north_star or "").strip() or a.request,
            "in_scope": split(a.in_scope), "out_of_scope": split(a.out_of_scope)}


def cmd_begin(a) -> None:
    mode = a.mode
    run_id = a.run_id or f"{mode}-{_ts().replace(':', '').replace('-', '')}"
    ts = a.ts or _ts()
    mod = _mode_module(mode)
    # Every run belongs to a registered research project (no more unowned experiments). The vault's
    # project-registry is the single source of truth; the run-store groups by runs/<project>/<run_id>/.
    # Validation vault = the SAME chain the worker prompts use (explicit --vault, else the discovered
    # two-repo layout, else the mode's DEFAULT_VAULT) — so the registry check can never be skipped
    # just because layout discovery failed while a default vault is still in play.
    vault_for_check = a.vault or discover_vault_root() or getattr(mod, "DEFAULT_VAULT", None)
    try:
        check = projects_tool.require_project(a.project, vault_for_check)
    except ValueError as exc:
        _emit({"error": str(exc),
               "note": "begin requires a registered --project (see 05-registry/project-registry.md in "
                       "the vault; the director adds the row — the machine never writes the registry)"})
        sys.exit(2)
    projects_tool.ensure_workspace(a.projects_dir, a.project)   # the project's durable resource room
    plan = spine.begin(a.runs_dir, run_id, a.request, mode, ts,
                       domain_profile_ref=a.profile, model_policy=a.model_policy, project=a.project,
                       north_star=_north_star_from_args(a))
    first = plan["stages"][0]
    vault = a.vault or getattr(mod, "DEFAULT_VAULT", None)
    worker = (mod.llm_step(plan["run_dir"], first, a.request, vault=vault, model_policy=a.model_policy)
              if hasattr(mod, "llm_step") else None)
    out = {"run_id": run_id, "run_dir": plan["run_dir"], "mode": mode, "project": a.project,
           "project_check": check, "stages": plan["stages"], "north_star": plan.get("north_star"),
           "gate_level": plan["gate_level"], "first_stage": first, "next_worker": worker}
    if hasattr(mod, "pre_search"):
        out["pre_search_note"] = ("RECOMMENDED next: `pre-search --run-id " + run_id + "` — grounds "
                                  "novelty/evidence in live literature BEFORE spawning the worker "
                                  "(skipping it degrades honestly to vault-only)")
    _emit(out)


def _pinned_request(runs_dir: str, run_id: str, override: Optional[str]) -> str:
    """The run's request comes from the PINNED task_frame (audit A1 — no CLI side-channel).

    A caller-supplied --request must MATCH the pinned one; a mismatch is refused so a later
    command can never quietly re-aim a run (only the director re-scopes, via a new run)."""
    tf = json.loads((Path(_run_dir(runs_dir, run_id)) / "task_frame.artifact.json").read_text(encoding="utf-8"))
    pinned = tf["payload"].get("request_text") or ""
    if override is not None and override.strip() and override.strip() != pinned.strip():
        _emit({"error": "request mismatch with the pinned task_frame — a run's direction is "
                        "immutable after begin (start a new run to pivot)",
               "pinned_request": pinned, "supplied_request": override})
        sys.exit(2)
    return pinned


def cmd_worker(a) -> None:
    mode = _mode_from_run(a.runs_dir, a.run_id)
    mod = _mode_module(mode)
    vault = a.vault or getattr(mod, "DEFAULT_VAULT", None)
    request = _pinned_request(a.runs_dir, a.run_id, a.request)
    worker = mod.llm_step(_run_dir(a.runs_dir, a.run_id), a.stage, request, vault=vault,
                          model_policy=_policy_from_run(a.runs_dir, a.run_id))
    multi = bool(worker) and "workers" in worker
    _emit({"run_id": a.run_id, "stage": a.stage, "worker": worker,
           "note": ("no LLM worker for this stage (deterministic-only) — go straight to run-dets"
                    if not worker else
                    ("spawn EVERY sub-agent in 'workers' (see the panel note for ordering); each "
                     "writes its own bundle; then run-dets" if multi else
                     "spawn this sub-agent (model + prompt); it writes the bundle to 'output'; then run-dets"))})


def cmd_pre_search(a) -> None:
    """The sanctioned live-retrieval pre-step (audit H5/M1 — now a first-class CLI step).

    Loads the gitignored .env first so the optional RAT_S2_API_KEY quota applies; a dead network
    degrades honestly to an empty bundle with source_errors recorded."""
    from ..execute.config import _load_dotenv
    _load_dotenv("research_agent_teams/.env")
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    request = _pinned_request(a.runs_dir, a.run_id, a.request)
    fn = getattr(mod, "pre_search", None)
    if fn is None:
        _emit({"run_id": a.run_id, "error": f"mode {_mode_from_run(a.runs_dir, a.run_id)!r} has no pre_search step"})
        sys.exit(2)
    bundle_path = fn(rd, request, ts)
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    _emit({"run_id": a.run_id, "bundle": bundle_path,
           "n_records": len(bundle.get("records") or []),
           "source_errors": bundle.get("source_errors") or {},
           "note": "live-retrieval bundle written; the DISCOVER worker reads it by reference. "
                   "Zero records + source_errors = offline degrade (honest, vault-only run)."})


def cmd_run_dets(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    # Absorption wave 1: a mode that exposes `run_dets_with_repair` carries the OpenScholar bounded
    # revise loop — use it so a recoverable gate BLOCK feeds back to the worker instead of halting on
    # the first failure. `--no-repair` forces the bare single-pass path (debugging / legacy parity).
    repair = getattr(mod, "run_dets_with_repair", None)
    try:
        if repair is not None and not a.no_repair:
            outcome = repair(rd, a.stage, ts)
            if outcome[0] == "retry":
                _emit({"run_id": a.run_id, "stage": a.stage, "retry": True, "repair_feedback": outcome[1],
                       "note": "HARD GATE refused, but the bounded-repair budget allows another in-stage "
                               "attempt. Re-dispatch THIS stage's worker with 'repair_feedback' appended to "
                               "its prompt, then run-dets again. Stage NOT committed; do NOT escalate yet."})
                return
            paths, report = outcome[1]
        else:
            paths, report = mod.run_dets(rd, a.stage, ts)
    except GateBlock as gb:
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": True, "gate": "BLOCK", "reason": str(gb),
               "note": "HARD GATE refused (repair budget exhausted if a repair loop ran) — run halts here, "
                       "stage NOT committed. Report the BLOCK to the director honestly."})
        sys.exit(3)
    except BudgetExceeded as be:
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": True, "budget_stop": True, "reason": str(be),
               "note": "BUDGET cap reached (a budget stop is never 'repaired'). Run halts; report to the director."})
        sys.exit(4)
    except FileNotFoundError as fe:
        _emit({"run_id": a.run_id, "stage": a.stage, "error": str(fe)})
        sys.exit(2)
    _emit({"run_id": a.run_id, "stage": a.stage, "artifacts": paths, "report": report,
           "note": "deterministic producers done; now: commit --stage " + a.stage})


def cmd_commit(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    stage_dir = Path(rd) / "evidence" / a.stage
    paths = sorted(str(p) for p in stage_dir.glob("*.artifact.json")) if stage_dir.exists() else []
    # Defense-in-depth: never checkpoint a stage that contains a blocked hard-gate verdict. run-dets
    # already halts (exit 3) on a BLOCK, but a stage's earlier approved artifacts are on disk by then;
    # this stops a stray `commit` from glob-ing a half-done blocked stage into the tamper-evident ledger.
    blocked = []
    for p in paths:
        try:
            if json.loads(Path(p).read_text(encoding="utf-8")).get("status") == "blocked":
                blocked.append(p)
        except (OSError, ValueError):
            continue
    if blocked:
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": True, "gate": "BLOCK",
               "reason": f"stage has blocked hard-gate verdict artifact(s): {blocked}",
               "note": "a stage with a blocked verdict cannot be committed — run-dets refused it. "
                       "Do NOT commit; report the BLOCK to the director or re-run via the repair loop."})
        sys.exit(3)
    res = spine.commit_stage(rd, a.stage, paths, ts)
    res["paused_for_director"] = res["gate"] == "director_signoff"
    if res["paused_for_director"]:
        res["pause_note"] = ("DIRECTOR GATE — do NOT proceed without the director. At the IDEATE boundary this "
                             "IS the /idea-bet review: show `menu` and let the director bet or pivot.")
    _emit(res)


def cmd_reject(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    m = spine.reject_stage(rd, a.stage, ts, reason=a.reason)
    _emit({"run_id": a.run_id, "stage": a.stage, "rejected": True, "status": m["status"],
           "note": ("DIRECTOR VETO recorded as a tamper-evident gate_resolved event; the run is now TERMINAL "
                    "(status=rejected) and cannot be resumed. A plain 'continue' can no longer walk past it — "
                    "start a new run to pivot.")})


def cmd_status(a) -> None:
    _emit(spine.status(_run_dir(a.runs_dir, a.run_id)))


def cmd_project_init(a) -> None:
    try:
        check = projects_tool.require_project(a.project, a.vault or discover_vault_root())
    except ValueError as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    ws = projects_tool.ensure_workspace(a.projects_dir, a.project)
    _emit({"project": a.project, "project_check": check, **ws})


def cmd_project_list(a) -> None:
    rows = projects_tool.list_projects(a.projects_dir, a.runs_dir,
                                       a.vault if a.vault is not None else discover_vault_root())
    _emit({"projects": rows})


def cmd_project_delete(a) -> None:
    """Director-facing deletion: one command removes a project's whole machine-side footprint
    (workspace + all its runs). Typed --confirm <slug> required; the vault is never touched."""
    try:
        res = projects_tool.delete_project(a.projects_dir, a.runs_dir, a.project,
                                           confirm=a.confirm, vault_root=a.vault)
    except (ValueError, PermissionError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    _emit(res)


def cmd_menu(a) -> None:
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    rows = mod.menu(_run_dir(a.runs_dir, a.run_id)) if hasattr(mod, "menu") else []
    _emit({"run_id": a.run_id, "menu": rows})
    if rows:
        print("\n=== /idea-bet MENU (the director chooses; the machine never self-bets) ===", file=sys.stderr)
        for r in rows:
            elo = f"  elo#{r['elo_rank']}({r['elo']})" if r.get("elo_rank") else ""
            print(f"  #{r['rank']}  {r['idea_id']}  (feasibility {r['score']}){elo}  {r['summary']}",
                  file=sys.stderr)
            for cv in (r.get("caveats") or []):
                print(f"        ⚠ {cv}", file=sys.stderr)
        print("  PIVOT: bet on none of these — re-scope the direction", file=sys.stderr)


# --------------------------------------------------------------------------- execution granularity (W4)
# Run ONE stage / skill / bridge mid-flight. These LAYER ON the begin/worker/run-dets/commit loop: they
# never bypass a gate — they resolve the registry entry, locate the project's run, dependency-check
# against the tamper-evident manifest, and either emit the worker/skill/bridge plan (ready) or the
# repair menu (not ready, exit 3). The machine NEVER fabricates a missing input.

def _resolve_run_id(a) -> str:
    """The run to act on: explicit --run-id / --from-run, else the project's most recent run."""
    rid = getattr(a, "run_id", None) or getattr(a, "from_run", None)
    if rid:
        return rid
    runs = ws_tool.project_runs(a.project, a.runs_dir)
    if not runs:
        _emit({"error": f"no run found for project {a.project!r}", "ready": False,
               "repair_actions": [f"operate begin --mode <mode> --project {a.project} --request \"...\""]})
        sys.exit(3)
    return runs[0]["run_id"]


def cmd_run_stage(a) -> None:
    rid = _resolve_run_id(a)
    rd = _run_dir(a.runs_dir, rid)
    try:
        info = exreg.stage_readiness(rd, a.stage)
        definition = exreg.load_stages().get(a.stage, {})
    except (ValueError, FileNotFoundError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    out = {"unit": "stage", "run_id": rid, "project": a.project, "stage": a.stage,
           "definition": definition, **info}
    if info["ready"]:
        out["next"] = f"operate worker --run-id {rid} --stage {a.stage}   (then run-dets, then commit)"
        out["note"] = ("READY — this stage is the run's pending next step; drive it through the normal "
                       "worker -> run-dets -> commit loop (the gates still run)")
        _emit(out)
        return
    out["note"] = "NOT READY — do repair_actions first; the machine will NOT fabricate a missing input"
    _emit(out)
    sys.exit(3)


def cmd_run_skill(a) -> None:
    rid = _resolve_run_id(a)
    rd = _run_dir(a.runs_dir, rid)
    try:
        info = exreg.skill_readiness(rd, a.skill)
        definition = exreg.load_skills().get(a.skill, {})
    except (ValueError, FileNotFoundError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    out = {"unit": "skill", "run_id": rid, "project": a.project, "skill": a.skill,
           "definition": definition, **info}
    if info["ready"]:
        hint = ("delegates to the project-local `server-query` skill (read-only) — it needs a "
                "primary_gpu binding + RAT_SERVER_QUERY_AUTHORIZED" if a.skill == "server_query" else
                f"consumes {definition.get('consumes', [])} -> produces {definition.get('produces', [])}")
        out["note"] = f"READY — run this skill within stage {info.get('stage', '?')}; {hint}"
        _emit(out)
        return
    out["note"] = "NOT READY — do repair_actions first; nothing is fabricated"
    _emit(out)
    sys.exit(3)


def cmd_run_bridge(a) -> None:
    rid = _resolve_run_id(a)
    rd = _run_dir(a.runs_dir, rid)
    try:
        info = exreg.bridge_readiness(rd, a.bridge)
        definition = exreg.load_bridges().get(a.bridge, {})
    except (ValueError, FileNotFoundError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    out = {"unit": "bridge", "run_id": rid, "project": a.project, "bridge": a.bridge,
           "definition": definition, **info}
    if info["ready"]:
        out["note"] = (f"READY — bridge {info['from_stage']} -> {info['to_stage']}; "
                       f"required_skills={definition.get('required_skills', [])}; commit {info['to_stage']} "
                       "via the normal loop")
        _emit(out)
        return
    out["note"] = "NOT READY — do repair_actions first; nothing is fabricated"
    _emit(out)
    sys.exit(3)


# --------------------------------------------------------------------------- workspace + lifecycle + resources (W5)
# Director-facing palette surface. Lifecycle wraps tools/lifecycle.py (the GUARDED archive/soft_delete/
# hard_purge — never the raw projects.delete_project), resources wraps tools/resources.py (capability
# view + scoping binds, NEVER a secret). The vault is never touched by any of these.

def cmd_dashboard(a) -> None:
    _emit(ws_tool.dashboard(a.project, projects_root=a.projects_dir, runs_dir=a.runs_dir, vault_root=a.vault))


def cmd_index(a) -> None:
    rows = ws_tool.project_index(projects_root=a.projects_dir, runs_dir=a.runs_dir, vault_root=a.vault,
                                 include_hidden=a.include_hidden)
    _emit({"projects": rows})


def cmd_set_active(a) -> None:
    st = ws_tool.set_active_project(a.project, a.ts or _ts(), ws_root=a.workspace_root)
    _emit({"active_project": st.get("active_project"), "last_touched": st.get("last_touched")})


def cmd_project_archive(a) -> None:
    data = lifecycle_tool.archive(a.project, a.ts or _ts(), projects_root=a.projects_dir,
                                  reason=a.reason or "")
    _emit({"project": a.project, "lifecycle_status": data["status"],
           "note": "hidden from the active picker; nothing deleted — fully reversible via project-restore"})


def cmd_project_restore(a) -> None:
    try:
        data = lifecycle_tool.restore(a.project, a.ts or _ts(), projects_root=a.projects_dir,
                                      workspace_root_path=a.workspace_root)
    except ValueError as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    _emit({"project": a.project, "lifecycle_status": data["status"], "note": "back to active"})


def cmd_project_soft_delete(a) -> None:
    res = lifecycle_tool.soft_delete(a.project, a.ts or _ts(), projects_root=a.projects_dir,
                                     workspace_root_path=a.workspace_root, reason=a.reason or "")
    _emit({"project": a.project, **res})


def cmd_project_purge(a) -> None:
    """GUARDED physical removal of a project's machine-side scratch. Refuses unless hidden first + no
    active run / no active lease / no promoted vault claims. The vault + shared pool are never touched."""
    try:
        res = lifecycle_tool.hard_purge(a.project, a.ts or _ts(), confirm=a.confirm,
                                        projects_root=a.projects_dir, runs_dir=a.runs_dir,
                                        vault_root=a.vault, workspace_root_path=a.workspace_root,
                                        allow_promoted=a.allow_promoted)
    except (ValueError, PermissionError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    _emit(res)


def cmd_resources(a) -> None:
    try:
        pool = rp.pool_overview(scope=a.scope)
    except (ValueError, FileNotFoundError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    out = {"resources": pool}
    if a.project:
        binds = rp.load_bindings(a.projects_dir, a.project)
        bound = {b.get("resource_ref"): b.get("alias") for b in binds.get("bindings", []) if b.get("alias")}
        for r in pool:
            r["bound_as"] = bound.get(r["resource_id"])     # this project's alias, or None if unbound
        out["project"] = a.project
    _emit(out)


def cmd_resource_bind(a) -> None:
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip()]   # noqa: E731
    try:
        binding = rp.add_binding(a.projects_dir, a.project, alias=a.alias, resource_ref=a.resource,
                                 capabilities=split(a.capabilities), stages=split(a.stages),
                                 skills=split(a.skills), requires_human_approval=a.requires_approval)
    except (ValueError, FileNotFoundError) as exc:
        _emit({"error": str(exc)})
        sys.exit(2)
    _emit({"project": a.project, "binding": binding,
           "note": "binding scopes WHICH pool resource + capabilities a run may LEASE; the global "
                   "default-deny policy still applies on top, and no secret is stored in the binding "
                   "(the credential stays a .env reference on the resource)"})


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)         # shared opts available AFTER the subcommand
    common.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    common.add_argument("--ts", default=None, help="ISO ts (default: now UTC)")

    p = argparse.ArgumentParser(prog="python -m research_agent_teams.operate", allow_abbrev=False,
                                description="One-button operate layer for the research machine.")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("begin", parents=[common], help="PARSE + create a run; print the first worker to spawn")
    b.add_argument("--mode", default="new_direction")
    b.add_argument("--request", required=True)
    b.add_argument("--project", required=True,
                   help="the registered research project this run belongs to (lowercase-kebab slug from "
                        "the vault's 05-registry/project-registry.md); groups the run under "
                        "runs/<project>/<run_id>/ and creates projects/<project>/ on first use")
    b.add_argument("--run-id", default=None)
    b.add_argument("--profile", default=None, help="domain_profile_ref (pointer, recorded for provenance)")
    b.add_argument("--model-policy", default="max_quality", choices=["default", "max_quality"],
                   help="governed research runs default to max_quality (all-opus) per director lock "
                        "2026-06-09 ('优化到最好'); pass --model-policy default for a cheaper run")
    b.add_argument("--north-star", default=None,
                   help="the run's ONE-sentence direction contract (defaults to the request verbatim); "
                        "pinned immutably + hash-chained; every stage is drift-gated against it")
    b.add_argument("--in-scope", default=None,
                   help="comma-separated topics explicitly INSIDE the direction (extra drift anchors)")
    b.add_argument("--out-of-scope", default=None,
                   help="comma-separated topics explicitly EXCLUDED — their appearance in any stage "
                        "output is a hard drift BLOCK")
    b.add_argument("--vault", default=None, help="vault root (defaults to the mode's DEFAULT_VAULT)")
    b.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    b.set_defaults(func=cmd_begin)

    w = sub.add_parser("worker", parents=[common], help="print the LLM worker spec to spawn for a stage")
    w.add_argument("--run-id", required=True)
    w.add_argument("--stage", required=True)
    w.add_argument("--request", default=None,
                   help="optional — the request is read from the PINNED task_frame; a supplied value "
                        "must match it (a mismatch is refused: runs cannot be re-aimed mid-flight)")
    w.add_argument("--vault", default=None)
    w.set_defaults(func=cmd_worker)

    ps = sub.add_parser("pre-search", parents=[common],
                        help="run the sanctioned live-retrieval pre-step (drops inbox/search-results.json; "
                             "grounds novelty/evidence in real literature — recommended after begin)")
    ps.add_argument("--run-id", required=True)
    ps.add_argument("--request", default=None, help="optional; must match the pinned task_frame request")
    ps.set_defaults(func=cmd_pre_search)

    r = sub.add_parser("run-dets", parents=[common], help="run the deterministic producers/gates for a stage")
    r.add_argument("--run-id", required=True)
    r.add_argument("--stage", required=True)
    r.add_argument("--no-repair", action="store_true",
                   help="force the bare single-pass path (skip the bounded-repair revise loop)")
    r.set_defaults(func=cmd_run_dets)

    c = sub.add_parser("commit", parents=[common], help="scope-check + validate + checkpoint a stage")
    c.add_argument("--run-id", required=True)
    c.add_argument("--stage", required=True)
    c.set_defaults(func=cmd_commit)

    rj = sub.add_parser("reject", parents=[common],
                        help="record the director's veto at a director_signoff gate (terminal; not resumable)")
    rj.add_argument("--run-id", required=True)
    rj.add_argument("--stage", required=True)
    rj.add_argument("--reason", default=None)
    rj.set_defaults(func=cmd_reject)

    s = sub.add_parser("status", parents=[common], help="run progress snapshot")
    s.add_argument("--run-id", required=True)
    s.set_defaults(func=cmd_status)

    m = sub.add_parser("menu", parents=[common], help="print the ranked idea_backlog (the /idea-bet menu)")
    m.add_argument("--run-id", required=True)
    m.set_defaults(func=cmd_menu)

    pi = sub.add_parser("project-init", parents=[common],
                        help="validate a registered project + create its projects/<slug>/ workspace")
    pi.add_argument("--project", required=True)
    pi.add_argument("--vault", default=None, help="vault root for registry validation (default: discovered)")
    pi.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pi.set_defaults(func=cmd_project_init)

    pls = sub.add_parser("project-list", parents=[common],
                         help="overview of all projects the machine knows (registry + workspaces + runs)")
    pls.add_argument("--vault", default=None)
    pls.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pls.set_defaults(func=cmd_project_list)

    pd = sub.add_parser("project-delete", parents=[common],
                        help="DELETE a project's machine-side footprint (workspace + all its runs); "
                             "typed --confirm <slug> required; the vault is never touched")
    pd.add_argument("--project", required=True)
    pd.add_argument("--confirm", required=True, help="must equal the project slug (typed confirmation)")
    pd.add_argument("--vault", default=None)
    pd.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pd.set_defaults(func=cmd_project_delete)

    rs = sub.add_parser("run-stage", parents=[common],
                        help="run ONE FSM stage mid-flight (dependency-checked against the run manifest)")
    rs.add_argument("--project", required=True, help="the project whose run to act on")
    rs.add_argument("--stage", required=True, choices=runstore.STAGES)
    rs.add_argument("--run-id", default=None, help="explicit run (default: the project's most recent run)")
    rs.add_argument("--from-run", default=None, help="alias for --run-id (which run to operate on)")
    rs.set_defaults(func=cmd_run_stage)

    rk = sub.add_parser("run-skill", parents=[common],
                        help="run ONE mid-stage skill (ready when its stage is current or committed)")
    rk.add_argument("--project", required=True)
    rk.add_argument("--skill", required=True, help="skill_id from workspace/registries/skill_registry.yaml")
    rk.add_argument("--run-id", default=None)
    rk.add_argument("--from-run", default=None)
    rk.set_defaults(func=cmd_run_skill)

    rbr = sub.add_parser("run-bridge", parents=[common],
                         help="run ONE stage-transition bridge (ready when 'from' is committed + 'to' pending)")
    rbr.add_argument("--project", required=True)
    rbr.add_argument("--bridge", required=True, help="bridge_id from workspace/registries/bridge_registry.yaml")
    rbr.add_argument("--run-id", default=None)
    rbr.add_argument("--from-run", default=None)
    rbr.set_defaults(func=cmd_run_bridge)

    dsh = sub.add_parser("dashboard", parents=[common],
                         help="per-project snapshot (current stage / blockers / recent runs / bound resources)")
    dsh.add_argument("--project", required=True)
    dsh.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    dsh.add_argument("--vault", default=None)
    dsh.set_defaults(func=cmd_dashboard)

    idx = sub.add_parser("index", parents=[common],
                         help="all projects with lifecycle status + current stage (richer than project-list)")
    idx.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    idx.add_argument("--vault", default=None)
    idx.add_argument("--include-hidden", action="store_true", help="also show archived / soft-deleted")
    idx.set_defaults(func=cmd_index)

    sa = sub.add_parser("set-active", parents=[common], help="point the workspace at a project (pointer only)")
    sa.add_argument("--project", required=True)
    sa.add_argument("--workspace-root", default=None)
    sa.set_defaults(func=cmd_set_active)

    pa = sub.add_parser("project-archive", parents=[common],
                        help="hide a project from the active picker (reversible; deletes nothing)")
    pa.add_argument("--project", required=True)
    pa.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pa.add_argument("--reason", default=None)
    pa.set_defaults(func=cmd_project_archive)

    pr = sub.add_parser("project-restore", parents=[common],
                        help="bring an archived / soft-deleted project back to active")
    pr.add_argument("--project", required=True)
    pr.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pr.add_argument("--workspace-root", default=None)
    pr.set_defaults(func=cmd_project_restore)

    psd = sub.add_parser("project-soft-delete", parents=[common],
                         help="reversible removal: hide + revoke the project's active leases; deletes nothing")
    psd.add_argument("--project", required=True)
    psd.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    psd.add_argument("--workspace-root", default=None)
    psd.add_argument("--reason", default=None)
    psd.set_defaults(func=cmd_project_soft_delete)

    pp = sub.add_parser("project-purge", parents=[common],
                        help="GUARDED physical removal of machine-side scratch (must be hidden first; "
                             "refuses while active-run / active-lease / promoted; vault never touched)")
    pp.add_argument("--project", required=True)
    pp.add_argument("--confirm", required=True, help="must equal the project slug (typed confirmation)")
    pp.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    pp.add_argument("--vault", default=None)
    pp.add_argument("--workspace-root", default=None)
    pp.add_argument("--allow-promoted", action="store_true",
                    help="override the promoted-claims guard (machine scratch goes; vault pages stay)")
    pp.set_defaults(func=cmd_project_purge)

    rsc = sub.add_parser("resources", parents=[common],
                         help="list the shared resource pool (capabilities only — no secrets) + project binds")
    rsc.add_argument("--project", default=None, help="also show which resources this project binds")
    rsc.add_argument("--scope", default=None, choices=["shared", "personal"])
    rsc.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    rsc.set_defaults(func=cmd_resources)

    rb = sub.add_parser("resource-bind", parents=[common],
                        help="bind a pool resource (caps/stages/skills) to a project under default-deny")
    rb.add_argument("--project", required=True)
    rb.add_argument("--alias", required=True, help="the project-local name for this binding")
    rb.add_argument("--resource", required=True, help="resource_id from the pool (e.g. api.semantic_scholar)")
    rb.add_argument("--capabilities", required=True, help="comma-separated; must be a subset of the resource's")
    rb.add_argument("--stages", default=None, help="comma-separated FSM stages this binding is allowed in")
    rb.add_argument("--skills", default=None, help="comma-separated skills this binding is allowed for")
    rb.add_argument("--requires-approval", action="store_true",
                    help="mark the binding as needing human approval at lease time")
    rb.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR)
    rb.set_defaults(func=cmd_resource_bind)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
