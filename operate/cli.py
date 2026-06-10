"""Operate CLI — the interface the research-orchestrator skill calls to drive a one-button run.

The skill's loop for `new_direction` (run from the project root):
    begin --mode new_direction --request "..."        -> run_id (+ DISCOVER worker spec)
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

from . import spine
from .artifacts import GateBlock
from .modes import REGISTRY

DEFAULT_RUNS_DIR = "research_agent_teams/runs"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_dir(runs_dir: str, run_id: str) -> str:
    return str(Path(runs_dir) / run_id)


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


def cmd_begin(a) -> None:
    mode = a.mode
    run_id = a.run_id or f"{mode}-{_ts().replace(':', '').replace('-', '')}"
    ts = a.ts or _ts()
    plan = spine.begin(a.runs_dir, run_id, a.request, mode, ts,
                       domain_profile_ref=a.profile, model_policy=a.model_policy)
    mod = _mode_module(mode)
    first = plan["stages"][0]
    vault = a.vault or getattr(mod, "DEFAULT_VAULT", None)
    worker = (mod.llm_step(plan["run_dir"], first, a.request, vault=vault, model_policy=a.model_policy)
              if hasattr(mod, "llm_step") else None)
    _emit({"run_id": run_id, "run_dir": plan["run_dir"], "mode": mode, "stages": plan["stages"],
           "gate_level": plan["gate_level"], "first_stage": first, "next_worker": worker})


def cmd_worker(a) -> None:
    mode = _mode_from_run(a.runs_dir, a.run_id)
    mod = _mode_module(mode)
    vault = a.vault or getattr(mod, "DEFAULT_VAULT", None)
    worker = mod.llm_step(_run_dir(a.runs_dir, a.run_id), a.stage, a.request, vault=vault,
                          model_policy=_policy_from_run(a.runs_dir, a.run_id))
    _emit({"run_id": a.run_id, "stage": a.stage, "worker": worker,
           "note": ("no LLM worker for this stage (deterministic-only) — go straight to run-dets"
                    if not worker else
                    "spawn this sub-agent (model + prompt); it writes the bundle to 'output'; then run-dets")})


def cmd_run_dets(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    try:
        paths, report = mod.run_dets(rd, a.stage, ts)
    except GateBlock as gb:
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": True, "gate": "BLOCK", "reason": str(gb),
               "note": "HARD GATE refused — run halts here, stage NOT committed. Report the BLOCK to the director honestly."})
        sys.exit(3)
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


def cmd_menu(a) -> None:
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    rows = mod.menu(_run_dir(a.runs_dir, a.run_id)) if hasattr(mod, "menu") else []
    _emit({"run_id": a.run_id, "menu": rows})
    if rows:
        print("\n=== /idea-bet MENU (the director chooses; the machine never self-bets) ===", file=sys.stderr)
        for r in rows:
            print(f"  #{r['rank']}  {r['idea_id']}  (feasibility {r['score']})  {r['summary']}", file=sys.stderr)
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
    b.add_argument("--run-id", default=None)
    b.add_argument("--profile", default=None, help="domain_profile_ref (pointer, recorded for provenance)")
    b.add_argument("--model-policy", default="max_quality", choices=["default", "max_quality"],
                   help="governed research runs default to max_quality (all-opus) per director lock "
                        "2026-06-09 ('优化到最好'); pass --model-policy default for a cheaper run")
    b.add_argument("--vault", default=None, help="vault root (defaults to the mode's DEFAULT_VAULT)")
    b.set_defaults(func=cmd_begin)

    w = sub.add_parser("worker", parents=[common], help="print the LLM worker spec to spawn for a stage")
    w.add_argument("--run-id", required=True)
    w.add_argument("--stage", required=True)
    w.add_argument("--request", required=True)
    w.add_argument("--vault", default=None)
    w.set_defaults(func=cmd_worker)

    r = sub.add_parser("run-dets", parents=[common], help="run the deterministic producers/gates for a stage")
    r.add_argument("--run-id", required=True)
    r.add_argument("--stage", required=True)
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
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
