"""Operate recipe for the `check_run` mode (EXECUTE -> REPORT) — wave-2 wiring (2026-08-04).

check_run gives the director a read-only run-health snapshot, split into two independent seats
exactly as the registry's own productization_gaps demanded: "the observer must not also be the one
deciding what its alerts mean" (mode_registry.yaml, check_run.product_maturity.productization_gaps).

  - monitor        OBSERVES the run-store and reports raw run status; it never computes
                    alert_type/severity itself — the deterministic `monitor_scan.build_alerts` core
                    (already engine-tested, see tests/test_monitor_scan.py) does that, so an LLM can
                    never hand-set an alert's classification.
  - failure-triager INDEPENDENTLY judges what monitor's evidence means: likely cause, urgency, and a
                    BOUNDED menu of intervention options. It never re-observes the run-store itself,
                    and every `condition_id` it triages must be a run monitor actually reported —
                    triaging an unobserved run is a fabricated target and BLOCKs (this mode's own
                    hard gate, alongside the three shared `_panel_recipe` gates).

Both are advisory: monitor's alert never blocks, and an intervention_option is a MENU CHOICE, never
a claim that anything ran — the registry's own target_markdown purpose says so directly ("...without
claiming an intervention was executed"). Every observed run's status is paired with its OWN execution
truth (`_panel_recipe.execution_truth`) so "monitored" never reads as "the experiment succeeded";
that boundary is named directly in `_panel_recipe.execution_truth`'s docstring as applying here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ...tools import monitor_scan
from ...tools.failure_triage import classify_trace

STAGES = _panel_recipe.stage_path("check_run")
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

# A guaranteed-absent path: `execution_truth` on this honestly resolves to "not-started" (no
# evidence/EXECUTE, no task_frame) instead of the recipe hand-rolling an equivalent verdict through
# a second code path when an observed run carries no resolvable directory of its own.
_UNRESOLVED_RUN_DIR = "inbox/__unresolved_run_dir__"

# Seat identities for LOADING already-written bundles (`load_seat_bundles` never reads `.prompt`).
# `llm_step` builds a second, fully-prompted tuple per call, since prompts need `request`/`run_dir`.
_SEATS = (
    _panel_recipe.Seat(label="monitor", prompt="", bundle_key="observed_runs", tier="tool"),
    _panel_recipe.Seat(label="failure-triager", prompt="", bundle_key="triage_assessments",
                       tier="audit", depends_on=("monitor",)),
)

MONITOR_PROMPT = """You are the monitor — the OBSERVE worker of check_run. Your ONE job is to \
find every run relevant to this request in the run-store and report its RAW status; you do NOT \
decide what it means (failure-triager does that, independently, after you) and you never compute \
alert_type or severity yourself — only the deterministic tool downstream may set those.

REQUEST: {request}

{north_star}

Read (by reference, never inlined):
  1. Every run_manifest under the run-store root reachable from `{run_dir}` (its parent directory \
is the runs root; sibling run directories are what you scan) — glob for manifest files there.
  2. Every run_record artifact under each candidate run's own `evidence/EXECUTE/*.artifact.json`.
  3. `{run_dir}/task_frame.artifact.json` only to understand THIS request's scope — never treat \
this run itself as one being monitored.

For EACH run relevant to the request, record: its run_id (or condition_id), its raw status string \
exactly as stored, any declared cost figure you find (cost, metrics.cost, metrics.total_cost, \
resources.cost, or resources.gpu_cost — whichever the run actually carries), and the real relative \
path to that run's own directory so a downstream check can verify whether it ever really executed. \
Never infer or guess a status the run's own record does not state.

HONESTY (hard): if the run-store has nothing to watch yet (no runs, or only planned/provisional \
records with no issue), that is a legitimate result — report an empty or all-healthy list. Never \
fabricate a stalled/failed run to have something to report.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}`:
{{"observed_runs": [{{"run_id": "<real id>", "status": "<raw status string>", \
"cost": <number or null>, "run_dir": "<real relative path to that run's directory, or null>"}}]}}
Quantities are a FLOOR with NO upper bound: report every run relevant to this request, never a \
capped top-N subset — an empty run-store is reported as "observed_runs": [], never padded. After \
writing, verify valid JSON. Return one line: how many runs you found and how many looked healthy."""

TRIAGE_PROMPT = """You are failure-triager — the INDEPENDENT TRIAGE worker of check_run. You did \
NOT observe the run-store yourself; monitor already did (read its complete bundle at \
`{run_dir}/inbox/EXECUTE.monitor.bundle.json`). Your ONE job is to independently judge what \
monitor's raw observations mean: likely cause, urgency, and a BOUNDED menu of intervention options \
— for every run monitor's data shows is not plainly healthy.

REQUEST: {request}

{north_star}

You MAY reopen a flagged run's own evidence (that run's own `evidence/EXECUTE/*.artifact.json`, at \
the run_dir monitor recorded for it) to look for more detail than monitor's summary carries — but \
never invent detail no such file supports. If you find nothing richer than monitor's own record, \
use that record's own status/detail text as your raw_evidence_excerpt — never fabricate a trace.

HONESTY (hard): every intervention_options entry is a MENU CHOICE the director has not yet acted on \
— never phrase one as already done or in progress. Ground every condition_id you triage in a run \
monitor actually reported; triaging a run nobody observed is a fabricated target and will be \
rejected. Grade urgency honestly against the run's OWN evidence, not against how interesting the \
run seems.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}`:
{{"triage_assessments": [{{"condition_id": "<a run_id monitor actually reported>", \
"raw_evidence_excerpt": "<real text you read - monitor's record or a reopened trace>", \
"likely_cause": "<your independent judgment>", "urgency": "critical|warn|info", \
"intervention_options": ["<bounded option 1>", "<bounded option 2>"], \
"open_question": "<anything you could not resolve independently, or null>"}}]}}
Quantities are a FLOOR with NO upper bound: assess every non-healthy run monitor reported — never a \
capped top-N subset — and list every defensible intervention option, never truncated for brevity. \
If every observed run is healthy, emit "triage_assessments": [] — that is a legitimate result, not \
a gap. After writing, verify valid JSON. Return one line: how many runs you assessed and their \
urgencies."""


def llm_step(run_dir, stage, request, vault=DEFAULT_VAULT, model_policy="max_quality") -> Optional[dict]:
    """monitor observes first; failure-triager independently triages only after reading its bundle."""
    if stage == "EXECUTE":
        north_star = _shared.north_star_block(run_dir)
        monitor_out = _panel_recipe.bundle_path(run_dir, "EXECUTE", "monitor")
        triage_out = _panel_recipe.bundle_path(run_dir, "EXECUTE", "failure-triager")
        seats = (
            _panel_recipe.Seat(
                label="monitor", bundle_key="observed_runs", tier="tool",
                prompt=MONITOR_PROMPT.format(request=request, north_star=north_star,
                                             run_dir=run_dir, out=monitor_out)),
            _panel_recipe.Seat(
                label="failure-triager", bundle_key="triage_assessments", tier="audit",
                depends_on=("monitor",),
                prompt=TRIAGE_PROMPT.format(request=request, north_star=north_star,
                                            run_dir=run_dir, out=triage_out)),
        )
        return _panel_recipe.panel(
            run_dir, "EXECUTE", "check_run", seats, model_policy=model_policy,
            panel_note="monitor observes the run-store first; failure-triager independently judges "
                      "urgency and bounded intervention options only after reading monitor's "
                      "bundle — it never re-observes the run-store itself.")
    return None  # REPORT is deterministic


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _run_ident(run: dict) -> str:
    return str(run.get("run_id") or run.get("condition_id") or "unknown_run")


def _slug(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return safe or "run"


def _execution_states(observed_runs, run_dir) -> dict:
    """{run_ident: execution_truth state} for every observed run — an OBSERVED run's own evidence,
    never this check_run session's, so "monitored" never reads as "the experiment succeeded".

    `path_reported` distinguishes "monitor gave us a real path and it genuinely has no execution
    evidence" from "monitor gave us no path at all" — both honestly resolve to the same
    `execution_truth` label, but only the first is a real claim about that run; the second is
    just an unresolved unknown, and the two must not read the same to the director.
    """
    states = {}
    for run in observed_runs:
        given = run.get("run_dir")
        candidate = given or str(Path(run_dir) / _UNRESOLVED_RUN_DIR)
        state = dict(_panel_recipe.execution_truth(candidate))
        state["path_reported"] = bool(given)
        states[_run_ident(run)] = state
    return states


def _status_boundary(state: dict) -> str:
    boundary = _panel_recipe.execution_boundary_section(state)
    if not state.get("path_reported"):
        return ("(monitor reported no run directory for this run, so execution could not be "
               f"independently checked.) {boundary}")
    return boundary


def _execute_dets(run_dir, ts) -> tuple:
    bundles = _panel_recipe.load_seat_bundles(run_dir, "EXECUTE", "check_run", _SEATS)
    observed_runs = bundles["observed_runs"]
    assessments = bundles["triage_assessments"]
    if not isinstance(observed_runs, list):
        raise GateBlock(
            f"check_run EXECUTE: monitor's observed_runs must be a list, got "
            f"{type(observed_runs).__name__}")
    if not isinstance(assessments, list):
        raise GateBlock(
            f"check_run EXECUTE: failure-triager's triage_assessments must be a list, got "
            f"{type(assessments).__name__}")

    # This mode's own hard gate: an independent triage target must be a run monitor actually
    # reported — a condition_id nobody observed is a fabricated triage target, not a thin result.
    known_ids = {_run_ident(run) for run in observed_runs}
    seen_ids = [str(a.get("condition_id") or "").strip() for a in assessments]
    unknown = sorted(set(seen_ids) - known_ids)
    if unknown:
        raise TargetedGateBlock(
            f"check_run EXECUTE: failure-triager assessed condition_id(s) {unknown} that monitor "
            f"never reported observing (known runs: {sorted(known_ids)}) — an independent triage "
            f"must be grounded in an actual observation",
            [{"defect_id": "check-run-ungrounded-triage-target",
              "location": "EXECUTE/triage_assessments",
              "summary": f"condition_id(s) {unknown} do not appear in monitor's observed_runs; "
                        "re-triage only runs monitor actually reported.",
              "target_agents": ["failure-triager"], "refresh_agents": []}])
    dupes = sorted({cid for cid in seen_ids if seen_ids.count(cid) > 1})
    if dupes:
        raise TargetedGateBlock(
            f"check_run EXECUTE: duplicate triage assessment(s) for {dupes} — one independent "
            f"judgment per run",
            [{"defect_id": "check-run-duplicate-triage-assessment",
              "location": "EXECUTE/triage_assessments",
              "summary": f"condition_id(s) {dupes} appear more than once; emit exactly one "
                        "assessment per run.",
              "target_agents": ["failure-triager"], "refresh_agents": []}])

    paths, frag = _panel_recipe.common_gates(
        run_dir, "EXECUTE", ts, mode="check_run",
        bundles={"observed_runs": observed_runs, "triage_assessments": assessments})

    budget = _shared.budget(run_dir)
    alert_bundle = monitor_scan.build_alerts(observed_runs, budget)  # deterministic; never hand-set
    paths.append(write_artifact(run_dir, "EXECUTE", "monitor-alert.artifact.json", "monitor_alert",
                                "monitor", alert_bundle, ts, "approved"))  # advisory only

    triage_reports = []
    for assessment in assessments:
        cid = str(assessment.get("condition_id") or "").strip()
        excerpt = (str(assessment.get("raw_evidence_excerpt") or "").strip()
                  or f"no detail reported for {cid}")
        options = [str(o).strip() for o in _as_list(assessment.get("intervention_options"))
                  if str(o).strip()]
        payload = {
            "condition_id": cid,
            "error_class": classify_trace(excerpt),        # machine-derived, never hand-set
            "stack_trace_excerpt": excerpt,
            "remediation_hint": "; ".join(options) or None,
            "notes": (f"likely cause: {assessment.get('likely_cause') or 'unstated'}; "
                     f"urgency: {assessment.get('urgency') or 'unstated'}"
                     + (f"; open question: {assessment['open_question']}"
                        if str(assessment.get("open_question") or "").strip() else "")),
        }
        paths.append(write_artifact(run_dir, "EXECUTE", f"triage-report-{_slug(cid)}.artifact.json",
                                    "triage_report", "failure-triager", payload, ts, "approved"))
        triage_reports.append({**assessment, "condition_id": cid, "intervention_options": options,
                               "error_class": payload["error_class"]})

    sections = _render_sections(run_dir, observed_runs, alert_bundle["alerts"], triage_reports)
    md_path = _panel_recipe.render_director_markdown(run_dir, "check_run", sections, ts=ts)

    report = {"n_runs_observed": len(observed_runs), "n_alerts": len(alert_bundle["alerts"]),
              "n_triage_assessments": len(triage_reports), "director_markdown_brief": md_path}
    report.update(frag)
    return paths, report


def _render_sections(run_dir, observed_runs, alert_rows, triage_reports) -> dict:
    n = len(observed_runs)
    flagged_ids = {str(a.get("run_ref")) for a in alert_rows}
    states = _execution_states(observed_runs, run_dir)

    if observed_runs:
        lines = []
        for run in observed_runs:
            rid = _run_ident(run)
            status = str(run.get("status") or "unknown")
            flag = " (flagged below)" if rid in flagged_ids else ""
            lines.append(f"- `{rid}`: status={status}{flag}. "
                        f"{_panel_recipe.execution_boundary_section(states[rid])}")
        current_status = (f"{n} run(s) observed; {len(flagged_ids)} flagged, "
                          f"{n - len(flagged_ids)} healthy.\n\n" + "\n".join(lines))
    else:
        current_status = ("No runs found in the run-store for this request yet. That is the "
                          "honest, expected result before any real GPU run exists — not an error.")

    if alert_rows:
        evidence_alerts = "\n".join(
            f"- **{a.get('alert_type')}** ({a.get('severity')}) on `{a.get('run_ref')}`: "
            f"{a.get('detail') or 'no detail reported'} "
            f"(evidence: {', '.join(a.get('evidence_ref') or [])})"
            for a in alert_rows)
    else:
        evidence_alerts = (f"None — all {n} observed run(s) are healthy (no stalled/failed/"
                          f"over_budget/cost_spike condition detected).")

    triaged_ids = {t.get("condition_id") for t in triage_reports}
    if triage_reports:
        lines = ["The options below are a MENU only — none of them has been carried out; "
                "whether to act on any is the director's call:"]
        for t in triage_reports:
            options_text = "; ".join(t.get("intervention_options") or []) or "none proposed"
            lines.append(f"- `{t.get('condition_id')}` (urgency: {t.get('urgency') or 'unstated'}) "
                        f"— likely cause: {t.get('likely_cause') or 'unstated'}. "
                        f"Options: {options_text}.")
        intervention_options = "\n".join(lines)
    else:
        intervention_options = "None — no run required an intervention menu this pass."

    unresolved = [str(t["open_question"]).strip() for t in triage_reports
                 if str(t.get("open_question") or "").strip()]
    for rid in sorted(flagged_ids - triaged_ids):
        unresolved.append(f"`{rid}` has an alert but no independent triage assessment was produced "
                          f"this pass — treat it as unreviewed.")
    for rid, state in states.items():
        if state.get("label") in {"ambiguous-execution", "invalid-execution-evidence"}:
            unresolved.append(f"`{rid}`: execution evidence is {state['label']} — {state['summary']}")
    if unresolved:
        unresolved_decisions = "\n".join(f"- {item}" for item in unresolved)
    else:
        unresolved_decisions = f"None — {n + len(triage_reports)} item(s) checked, nothing ambiguous."

    return {"Current run status": current_status, "Evidence-backed alerts": evidence_alerts,
            "Intervention options": intervention_options, "Unresolved decisions": unresolved_decisions}


def _report(run_dir, ts) -> tuple:
    md_path = _panel_recipe.target_markdown("check_run")["path"]
    return _panel_recipe.report_note(
        run_dir, ts, mode="check_run",
        summary="check_run: monitor observed the run-store, failure-triager independently judged "
               "urgency and bounded intervention options for every non-healthy run it was given, "
               f"and a deterministic run-health brief was rendered to {md_path}. monitor's alert "
               "stays advisory only; no intervention was executed.",
        references=[md_path])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"check_run has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair("check_run", run_dets)
