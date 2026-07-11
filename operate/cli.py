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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import spine
from .artifacts import GateBlock, TargetedGateBlock
from .modes import REGISTRY
from .panel_scheduler import PanelContractError, schedule_next_wave
from ..orchestrator.model_policy import decorate_worker_runtime
from ..tools import execution_registry as exreg
from ..tools import lifecycle as lifecycle_tool
from ..tools import projects as projects_tool
from ..tools import research_plan
from ..tools import resources as rp
from ..tools import runstore
from ..tools import workspace as ws_tool
from ..tools.budget_tracker import BudgetExceeded
from ..tools.director_packet import lint_packet, write_packet
from ..tools.idea_bet_markdown import write_idea_bet_menu
from ..tools.research_business_standard import decorate_worker_quality
from ..tools.runstore import find_run_dir
from ..tools.scope_guard import discover_vault_root

DEFAULT_RUNS_DIR = str(Path(__file__).resolve().parents[1] / "runs")
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


def _resolve_upstream_dirs(runs_dir: str, upstream_run_ids) -> list:
    """Resolve --upstream-run ids (prior chain links) to their run dirs. A bad id exits cleanly (the
    chain must not silently drop a link the orchestrator believed it threaded)."""
    dirs = []
    for rid in (upstream_run_ids or []):
        try:
            dirs.append(str(find_run_dir(runs_dir, rid)))
        except (FileNotFoundError, RuntimeError) as exc:
            _emit({"error": f"--upstream-run {rid!r}: {exc}"})
            sys.exit(2)
    return dirs


def _schedule_stage_worker(run_dir: str, stage: str, request: str, mod, *, vault,
                           model_policy: str, ts: str, authorize: bool = True) -> tuple:
    """Open the current stage and expose only its next scheduler-authorized wave."""
    spine.open_stage(run_dir, stage, ts)
    raw = mod.llm_step(run_dir, stage, request, vault=vault, model_policy=model_policy)
    raw = research_plan.augment_worker_with_upstream(raw, run_dir)
    decision = schedule_next_wave(run_dir, stage, raw, ts=ts, authorize=authorize)
    dispatch = decision.get("dispatch")
    if dispatch is not None and authorize:
        dispatch = decorate_worker_quality(dispatch, stage)
        dispatch = decorate_worker_runtime(dispatch)
    return dispatch, decision


def _schedule_or_exit(run_dir: str, stage: str, request: str, mod, *, vault,
                      model_policy: str, ts: str, authorize: bool = True) -> tuple:
    try:
        return _schedule_stage_worker(
            run_dir, stage, request, mod, vault=vault, model_policy=model_policy,
            ts=ts, authorize=authorize,
        )
    except BudgetExceeded as exc:
        _emit({"stage": stage, "halted": True, "budget_stop": True, "reason": str(exc),
               "note": "Actual worker dispatch reached max_agent_hops; no partial wave was authorized."})
        sys.exit(4)
    except (PanelContractError, ValueError) as exc:
        _emit({"stage": stage, "halted": True, "scheduler_block": True, "reason": str(exc),
               "note": "Panel scheduling refused an invalid order, label, predecessor, or read scope."})
        sys.exit(2)


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
    # Combination layer (2026-06-19): when this run is a LINK in a director-approved chain, thread the
    # prior link(s)' output in — write inbox/upstream-grounding.json and fold a PRIOR CHAIN CONTEXT
    # block into the first worker's prompt so it builds ON the upstream result instead of restarting.
    upstream = _resolve_upstream_dirs(a.runs_dir, a.upstream_run)
    if upstream:
        grounding_path = research_plan.write_upstream_grounding(
            plan["run_dir"], upstream, downstream_mode=mode
        )
        runstore.pin_upstream_grounding(plan["run_dir"], grounding_path, ts)
    worker, schedule = _schedule_or_exit(
        plan["run_dir"], first, a.request, mod, vault=vault,
        model_policy=a.model_policy, ts=ts,
    )
    out = {"run_id": run_id, "run_dir": plan["run_dir"], "mode": mode, "project": a.project,
           "project_check": check, "stages": plan["stages"], "north_star": plan.get("north_star"),
           "gate_level": plan["gate_level"], "first_stage": first, "next_worker": worker,
           "schedule": schedule}
    if worker:
        out["runtime_note"] = ("Spawn on any provider/model that satisfies capability_requirements; "
                               "concrete runtime fields are optional deployment bindings.")
    if upstream:
        out["upstream_runs"] = upstream
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
    rd = _run_dir(a.runs_dir, a.run_id)
    worker, schedule = _schedule_or_exit(
        rd, a.stage, request, mod, vault=vault,
        model_policy=_policy_from_run(a.runs_dir, a.run_id), ts=a.ts or _ts(),
    )
    if schedule.get("status") == "blocked_missing_predecessor":
        _emit({"run_id": a.run_id, "stage": a.stage, "worker": None, "schedule": schedule,
               "note": "No legal worker wave: predecessor evidence is missing."})
        sys.exit(3)
    multi = bool(worker) and "workers" in worker
    _emit({"run_id": a.run_id, "stage": a.stage, "worker": worker, "schedule": schedule,
           "note": ("no LLM worker for this stage (deterministic-only) — go straight to run-dets"
                    if not worker else
                    ("spawn EVERY sub-agent in this scheduler-authorized wave concurrently; "
                     "then call worker again for the next legal wave" if multi else
                    "spawn this sub-agent using capability_requirements + prompt; "
                     "it writes the bundle to 'output'; then call worker again"))})


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


def _copy_docs_to_run_scratch(run_dir: str, doc_paths) -> list:
    dest_dir = Path(run_dir) / "inbox" / "fulltext-docs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for i, raw in enumerate(doc_paths or [], start=1):
        src = Path(raw).expanduser().resolve()
        if not src.is_file():
            _emit({"error": f"document does not exist or is not a file: {raw}"})
            sys.exit(2)
        stem = src.stem or f"doc-{i}"
        suffix = src.suffix or ".pdf"
        dst = dest_dir / f"{i:02d}-{stem}{suffix}"
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def cmd_fulltext_pre(a) -> None:
    """Copy local docs/PDFs into run scratch, then write inbox/fulltext-qa.json."""
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    fn = getattr(mod, "fulltext_pre", None)
    if fn is None:
        _emit({"run_id": a.run_id,
               "error": f"mode {_mode_from_run(a.runs_dir, a.run_id)!r} has no fulltext_pre step"})
        sys.exit(2)
    question = (a.question or _pinned_request(a.runs_dir, a.run_id, a.request)).strip()
    docs = _copy_docs_to_run_scratch(rd, a.doc)
    report_path = fn(rd, question, docs, ts)
    if report_path is None:
        _emit({"run_id": a.run_id, "error": "fulltext_pre wrote nothing; no documents supplied"})
        sys.exit(2)
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    _emit({"run_id": a.run_id, "bundle": report_path, "copied_docs": docs,
           "available": report.get("available"), "n_contexts": len(report.get("contexts") or []),
           "reason": report.get("reason") or "",
           "note": "page-anchored full-text bundle written; the DISCOVER worker reads it by reference."})


def cmd_run_dets(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    mod = _mode_module(_mode_from_run(a.runs_dir, a.run_id))
    request = _pinned_request(a.runs_dir, a.run_id, None)
    _unused, schedule = _schedule_or_exit(
        rd, a.stage, request, mod, vault=getattr(mod, "DEFAULT_VAULT", None),
        model_policy=_policy_from_run(a.runs_dir, a.run_id), ts=ts, authorize=False,
    )
    if schedule.get("status") != "complete":
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": True,
               "workers_incomplete": True, "schedule": schedule,
               "note": "run-dets cannot bypass the panel scheduler; finish the next legal wave first."})
        sys.exit(2)
    # Absorption wave 1: a mode that exposes `run_dets_with_repair` carries the OpenScholar bounded
    # revise loop — use it so a recoverable gate BLOCK feeds back to the worker instead of halting on
    # the first failure. `--no-repair` forces the bare single-pass path (debugging / legacy parity).
    repair = getattr(mod, "run_dets_with_repair", None)
    try:
        if repair is not None and not a.no_repair:
            outcome = repair(rd, a.stage, ts)
            if outcome[0] == "retry":
                packet = write_packet(rd, generated_at=ts)
                _emit({"run_id": a.run_id, "stage": a.stage, "retry": True, "repair_feedback": outcome[1],
                       "delivery_status": "NEEDS_SUPPLEMENT",
                       "director_review_packet": str(packet),
                       "note": "A readable working packet is available now. The scheduler will dispatch only "
                               "the targeted supplement; completed analysis remains preserved."})
                return
            paths, report = outcome[1]
        else:
            paths, report = mod.run_dets(rd, a.stage, ts)
    except GateBlock as gb:
        packet = write_packet(rd, generated_at=ts)
        hard = isinstance(gb, TargetedGateBlock) and gb.verdict == "BLOCK"
        _emit({"run_id": a.run_id, "stage": a.stage, "halted": hard,
               "gate": "BLOCK" if hard else "NEEDS_SUPPLEMENT", "reason": str(gb),
               "delivery_status": "BLOCK" if hard else "USABLE_WITH_CAVEATS",
               "director_review_packet": str(packet),
               "note": "The current readable result remains available. Only truth, safety, execution, or "
                       "permission failures are hard blocks; other gaps remain explicit supplements."})
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


def cmd_packet(a) -> None:
    rd = _run_dir(a.runs_dir, a.run_id)
    ts = a.ts or _ts()
    try:
        path = write_packet(rd, generated_at=ts)
        errors = lint_packet(rd)
    except Exception as exc:
        _emit({"run_id": a.run_id, "packet": "BLOCKED", "error": str(exc),
               "note": "director-review packet was not generated; do not treat REPORT as human-ready"})
        sys.exit(3)
    _emit({"run_id": a.run_id, "director_review_packet": str(path),
           "lint_errors": errors, "note": "Markdown packet is the director-facing entry; JSON remains evidence"})


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
    rd = _run_dir(a.runs_dir, a.run_id)
    rows = mod.menu(rd) if hasattr(mod, "menu") else []
    cuts = mod.cut_for_prior_art(rd) if hasattr(mod, "cut_for_prior_art") else []
    md_path = None
    md_error = None
    if rows:
        try:
            md_path = write_idea_bet_menu(rd, generated_at=a.ts or _ts())
        except ValueError as exc:
            md_error = str(exc)
    payload = {"run_id": a.run_id, "menu": rows, "cut_for_prior_art": cuts}
    if md_path:
        payload["director_idea_bet_menu"] = md_path
    if md_error:
        payload["director_idea_bet_menu_error"] = md_error
    _emit(payload)
    if rows:
        print("\n=== /idea-bet MENU (the director chooses; the machine never self-bets) ===", file=sys.stderr)
        if md_path:
            print(f"  Markdown decision page: {md_path}", file=sys.stderr)
        if cuts:
            print("  Cut before menu for evidenced prior art:", file=sys.stderr)
            for c in cuts:
                print(f"    {c['idea_id']}  {c['verdict']}  {c.get('reason', '')}", file=sys.stderr)
        for r in rows:
            elo = f"  elo#{r['elo_rank']}({r['elo']})" if r.get("elo_rank") else ""
            print(f"  #{r['rank']}  {r['idea_id']}  (feasibility {r['score']}){elo}  {r['summary']}",
                  file=sys.stderr)
            for cv in (r.get("caveats") or []):
                print(f"        ⚠ {cv}", file=sys.stderr)
        print("  PIVOT: bet on none of these — re-scope the direction", file=sys.stderr)


# --------------------------------------------------------------------------- combination layer (tiers)
# The director-lock 2026-06-19 entry: a request maps to an INTENT and PROPOSES tiered mode-COMBINATIONS
# (core 1-mode -> mainline -> full), NOT a single mode. Advisory — it starts no run and picks nothing;
# the orchestrator renders the tiers as the director's AskUserQuestion, then runs the chosen chain
# link-by-link via `begin --upstream-run`.

def cmd_plan_propose(a) -> None:
    _emit(research_plan.propose_for_request(a.request, intent=a.intent))


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


def cmd_scoreboard(a) -> None:
    """Director-facing one-button health panel over capability, eval, and runs."""
    from ..tools.quality_scoreboard import build_quality_scoreboard

    board = build_quality_scoreboard(
        runs_dir=a.runs_dir,
        aers_root=a.aers_root,
        include_manual=not a.no_manual,
        run_limit=a.run_limit,
    )
    _emit(board)


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


def cmd_aers_reference_approve(a) -> None:
    """Human gate for approving/rejecting an AERS reference candidate.

    It can only approve reference use; it never enables external execution or
    vault writes. The palette entry is disable-model-invocation.
    """
    from ..tools import external_skill_review as review

    registry = review.load_registry(a.registry)
    entry = review.apply_gate_decision(
        registry,
        a.review_id,
        decision=a.decision,
        reviewed_by=a.reviewed_by,
        decision_note=a.decision_note,
        confirm_review_id=a.confirm_review_id,
        ts=a.ts or _ts(),
        allow_review_required=a.allow_review_required,
    )
    exported = None
    if a.export_run_dir and entry.get("reference_allowed"):
        exported = review.export_run_inbox_reference(entry, a.export_run_dir)
    review.save_registry(registry, a.out or a.registry)
    _emit({
        **review.summarize_registry(registry),
        "gate": "/aers-reference-approve",
        "decision": a.decision,
        "review_id": a.review_id,
        "exported_reference": exported,
        "note": "human gate recorded; reference approval never grants execution or vault write",
    })


def cmd_numeric_benchmark(a) -> None:
    """Recompute claimed metrics from result rows + journal/hash evidence."""
    from ..tools.numeric_benchmark_adapter import build_report_from_files
    from ..tools.path_boundaries import assert_not_vault_path

    report = build_report_from_files(
        run_records_path=a.run_records,
        result_artifact_paths=a.result_artifact,
        hash_manifest_path=a.hash_manifest,
        journal_path=a.journal,
        required_paths=a.required_path,
        tolerance=a.tolerance,
    )
    if a.out:
        out = assert_not_vault_path(a.out, purpose="write numeric benchmark report")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit(report)
    if report["verdict"] != "PASS":
        sys.exit(1)


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
                   help="research runs default to max_quality: all reasoning seats request frontier "
                        "capability from whichever runtime is available; pass --model-policy default "
                        "for a mixed strong/frontier workload profile")
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
    b.add_argument("--upstream-run", action="append", default=None,
                   help="run_id of a PRIOR chain link whose output grounds this run (repeatable). The "
                        "combination layer threads its REPORT/idea-backlog into this run's first worker "
                        "(inbox/upstream-grounding.json) so the link builds ON it instead of restarting")
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

    fp = sub.add_parser("fulltext-pre", parents=[common],
                        help="copy local PDFs/docs into run scratch and write inbox/fulltext-qa.json")
    fp.add_argument("--run-id", required=True)
    fp.add_argument("--doc", action="append", required=True,
                    help="local PDF/doc path to copy into run scratch before extraction (repeatable)")
    fp.add_argument("--question", default=None,
                    help="optional extraction question; defaults to the pinned task_frame request")
    fp.add_argument("--request", default=None, help="optional; must match the pinned task_frame request")
    fp.set_defaults(func=cmd_fulltext_pre)

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

    pkt = sub.add_parser("packet", parents=[common],
                         help="generate/regenerate the director-facing Markdown packet for a run")
    pkt.add_argument("--run-id", required=True)
    pkt.set_defaults(func=cmd_packet)

    m = sub.add_parser("menu", parents=[common], help="print the ranked idea_backlog (the /idea-bet menu)")
    m.add_argument("--run-id", required=True)
    m.set_defaults(func=cmd_menu)

    plp = sub.add_parser("plan-propose", parents=[common],
                         help="propose tiered mode-COMBINATIONS for a request (intents + tiers + cost + "
                              "gates + per-mode drill-down questions) — the combination layer's entry; "
                              "advisory, starts no run")
    plp.add_argument("--request", required=True)
    plp.add_argument("--intent", default=None,
                     help="force an intent id (else the request is matched; no match -> all intents)")
    plp.set_defaults(func=cmd_plan_propose)

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

    scb = sub.add_parser("scoreboard", parents=[common],
                         help="director one-button health panel: capability catalog + evals + run manifests")
    scb.add_argument("--aers-root", default=None)
    scb.add_argument("--run-limit", type=int, default=200)
    scb.add_argument("--no-manual", action="store_true",
                     help="omit manual release-readiness rows (for machine-only CI checks)")
    scb.set_defaults(func=cmd_scoreboard)

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

    ara = sub.add_parser("aers-reference-approve", parents=[common],
                         help="HUMAN GATE: approve/reject one AERS reference candidate; never execution/vault")
    ara.add_argument("--registry", required=True)
    ara.add_argument("--out", default=None, help="optional output registry path (defaults to --registry)")
    ara.add_argument("--review-id", required=True)
    ara.add_argument("--decision", required=True, choices=["approve", "reject"])
    ara.add_argument("--reviewed-by", required=True)
    ara.add_argument("--decision-note", required=True)
    ara.add_argument("--confirm-review-id", required=True,
                     help="must exactly equal --review-id; typed human confirmation")
    ara.add_argument("--allow-review-required", action="store_true")
    ara.add_argument("--export-run-dir", default=None,
                     help="optional run dir to receive inbox/external-skill-references/<id>.json")
    ara.set_defaults(func=cmd_aers_reference_approve)

    nb = sub.add_parser("numeric-benchmark", parents=[common],
                        help="verify claimed metrics by recomputing from result rows + journal/hash evidence")
    nb.add_argument("--run-records", required=True)
    nb.add_argument("--result-artifact", action="append", required=True)
    nb.add_argument("--hash-manifest", required=True)
    nb.add_argument("--journal", required=True)
    nb.add_argument("--required-path", action="append", default=None)
    nb.add_argument("--tolerance", type=float, default=1e-9)
    nb.add_argument("--out", default=None)
    nb.set_defaults(func=cmd_numeric_benchmark)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
