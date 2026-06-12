"""Spine engine — ties the whole control plane together and drives a task through the stages.

This is the testable core of the orchestrator (the SKILL.md is a thin Claude-Code wrapper around it).
For each stage from entry -> REPORT it runs the per-stage micro-protocol:
  WORK (agent_fn writes an artifact) -> scope-check -> VERIFY (contract-validate) -> RECORD
  (obslog + checkpoint to the hash-chained run-store) -> REVIEW (director gate) ; budget enforced.
Crash-safe: each stage ends at a ledger boundary, so resume_task() can pick up exactly where it died.

agent_fn(stage, task_frame, run_dir, ts) -> path to the artifact it wrote (into evidence/<stage>/).
gate_fn(stage, task_frame) -> "approved" | "modify" | "reject".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from research_agent_teams.orchestrator.model_policy import load_agent_models, safe_resolve_model
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools.budget_tracker import assert_within
from research_agent_teams.tools.obslog import append_log
from research_agent_teams.tools.runstore import (
    STAGES,
    checkpoint_stage,
    create_run,
    find_run_dir,
    pin_task_frame,
    prepare_resume,
    read_manifest,
    record_gate,
    run_dir_for,
    start_stage,
)
from research_agent_teams.tools.scope_guard import decide
from research_agent_teams.tools.validate_artifact import validate_artifact


def _stages_from(entry: str):
    return STAGES[STAGES.index(entry):]


def _resolve_path(task_frame) -> list:
    """The ordered list of stages this run drives. A mode may declare a forward-only `stage_path`
    (e.g. evidence_review = [DISCOVER, REPORT], skipping the experiment stages); otherwise the run
    drives the full tail from entry_stage to REPORT. The path is authoritative for both first-run and
    resume, so a forward-skip survives a crash."""
    p = task_frame["payload"]
    entry = p["entry_stage"]
    sp = p.get("stage_path")
    if not sp:
        return _stages_from(entry)
    idxs = [STAGES.index(s) for s in sp]                 # raises ValueError on an unknown stage
    if idxs != sorted(idxs) or len(set(sp)) != len(sp):
        raise ValueError(f"stage_path must be forward-only and unique: {sp}")
    if sp[0] != entry:
        raise ValueError(f"stage_path must start at entry_stage {entry}: {sp}")
    if sp[-1] != STAGES[-1]:
        raise ValueError(f"stage_path must end at {STAGES[-1]} (the reply segment is mandatory): {sp}")
    return list(sp)


def _validate_artifact_file(path) -> dict:
    art = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_artifact(art)
    if errs:
        raise ValueError(f"stage artifact failed contract: {errs}")
    return art


def _drive(run_dir, task_frame, start_stage_name, agent_fn, gate_fn, ts, vault_root):
    p = task_frame["payload"]
    budget, subset, gate_level = p["budget"], p["agent_subset"], p["gate_level"]
    policy = p.get("model_policy", "default")            # backward-compatible: old frames -> default
    agent_models = load_agent_models()                   # spec frontmatter = single source of truth
    # The run's LEAD agent (subset[0]) labels the whole run's model in obslog — the same lead-proxy
    # convention the agent_name field already uses. It is a RUN-WIDE label, not a per-stage one
    # (the engine dispatches stages through an opaque agent_fn and does not know each stage's agent).
    # safe_resolve_model keeps this observability label from ever crashing a resumable run on a bad
    # spec; real misconfiguration fails loud in tests / at PARSE instead.
    lead = subset[0] if subset else None
    declared = agent_models.get(lead) if lead else None
    lead_model = safe_resolve_model(declared, policy)
    run_root = str(Path(run_dir).parent)
    manifest = read_manifest(run_dir)
    done = {c["stage"] for c in manifest["completed_work"]}
    # The mode's path is authoritative (a forward-skip like evidence_review=[DISCOVER,REPORT] must
    # survive a crash). Remaining = path stages not yet checkpointed; a crashed mid-stage is not in
    # completed_work, so it re-runs. start_stage_name is kept for signature stability only.
    remaining = [s for s in _resolve_path(task_frame) if s not in done]
    usage = {"agent_hops": len(manifest["completed_work"])}
    obs = Path(run_dir) / "obs.jsonl"

    for stage in remaining:
        usage["agent_hops"] += 1
        assert_within(budget, usage)                       # budget/stop controller
        start_stage(run_dir, stage, ts, subset)            # ledger: stage_started
        art_path = agent_fn(stage, task_frame, run_dir, ts)  # WORK
        ok, reason = decide("Write", str(art_path),         # permission scope (fence)
                            {"run_root": run_root, "run_id": p["task_id"], "stage": stage, "vault_root": vault_root})
        if not ok:
            raise PermissionError(f"scope violation at {stage}: {reason}")
        _validate_artifact_file(art_path)                   # VERIFY (contract)
        append_log(obs, {"agent_name": lead or "stub", "task_id": p["task_id"], "stage": stage,
                         "started_at": ts, "tool_calls": 1, "model": lead_model})  # observability
        if gate_level == "director_signoff":                # REVIEW (director gate) — BEFORE the checkpoint
            decision = gate_fn(stage, task_frame) or "approved"
            record_gate(run_dir, stage, decision, ts)       # durable, tamper-evident signoff (the veto fix)
            if str(decision).strip().lower() == "reject":
                # vetoed: do NOT checkpoint — a rejected stage never becomes a clean boundary, and the run
                # is now terminal (status=rejected), so a plain resume can no longer walk past the veto.
                raise RuntimeError(f"director rejected at {stage}")
        checkpoint_stage(run_dir, stage, [art_path], f"idem-{stage}", ts)     # RECORD (boundary; only if not rejected)
    return read_manifest(run_dir)


def run_task(runs_dir, run_id, request, mode, ts, agent_fn, gate_fn,
             domain_profile_ref: Optional[str] = None, vault_root: Optional[str] = None,
             budget_override: Optional[dict] = None, model_policy: str = "default",
             project: Optional[str] = None, north_star: Optional[dict] = None) -> dict:
    tf = resolve_task(request, mode, run_id, ts, domain_profile_ref=domain_profile_ref,
                      model_policy=model_policy, project=project, north_star=north_star)  # PARSE
    if budget_override is not None:
        tf["payload"]["budget"] = budget_override
    rerrs = validate_routing(tf)
    if rerrs:
        raise ValueError(f"routing rejected: {rerrs}")
    entry = tf["payload"]["entry_stage"]
    create_run(runs_dir, run_id, mode, entry, ts, domain_profile_ref, tf["payload"]["agent_subset"],
               project=project)
    run_dir = run_dir_for(runs_dir, run_id, project)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")  # orchestrator-written
    pin_task_frame(run_dir, ts)  # the direction contract enters the hash chain (audit H2.3)
    return _drive(run_dir, tf, entry, agent_fn, gate_fn, ts, vault_root)


def resume_task(runs_dir, run_id, ts, agent_fn, gate_fn, vault_root: Optional[str] = None) -> dict:
    run_dir = find_run_dir(runs_dir, run_id)                # either layout: flat or runs/<project>/<id>
    tf = json.loads((run_dir / "task_frame.artifact.json").read_text(encoding="utf-8"))
    res = prepare_resume(run_dir, ts)                       # detect + guard + log resume
    return _drive(run_dir, tf, res["resume_stage"], agent_fn, gate_fn, ts, vault_root)
