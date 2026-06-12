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
from ..tools import projects as projects_tool
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
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
