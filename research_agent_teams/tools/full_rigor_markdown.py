"""Director-facing Markdown renderer for full_rigor_minimal experiment runs.

Canonical evidence stays under evidence/<STAGE>/*.artifact.json. This module
writes only human review sidecars:

    director-review/experiments/experiment-plan.md
    director-review/experiments/result-readiness.md  (only for evidence-bound real results)

The pages are decision aids for the director. They do not write the vault and
they do not freeze or promote a result.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .full_rigor_execution_truth import execution_state


EXPERIMENT_PLAN_REL = Path("director-review") / "experiments" / "experiment-plan.md"
RESULT_READINESS_REL = Path("director-review") / "experiments" / "result-readiness.md"

PLAN_REQUIRED_HEADINGS = [
    "## Decision Snapshot",
    "## Research Question",
    "## Hypothesis",
    "## Variables",
    "## Baselines And Conditions",
    "## Data And Split",
    "## Metrics And Statistical Plan",
    "## Preregistration Freeze",
    "## Execution Status",
    "## Failure And Kill Criteria",
    "## Next Exact Run Commands",
    "## Evidence Pointers",
]

RESULT_REQUIRED_HEADINGS = [
    "## Result Snapshot",
    "## Effect Size And Uncertainty",
    "## Analysis Checks",
    "## Failure Attribution",
    "## Verification Readiness",
    "## Claim Boundary",
    "## Next Experiment",
    "## Next Actions",
    "## Evidence Pointers",
]


def experiment_plan_path(run_dir) -> Path:
    return Path(run_dir) / EXPERIMENT_PLAN_REL


def result_readiness_path(run_dir) -> Path:
    return Path(run_dir) / RESULT_READINESS_REL


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _payload(path: Path) -> dict:
    payload = _read_json(path).get("payload")
    return payload if isinstance(payload, dict) else {}


def _stage_payload(run_path: Path, stage: str, filename: str) -> dict:
    return _payload(run_path / "evidence" / stage / filename)


def _task_payload(run_path: Path) -> dict:
    return _payload(run_path / "task_frame.artifact.json")


def _one_line(value: object, *, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _csv(values: list | tuple | set | None, *, limit: int = 8) -> str:
    vals = [str(v) for v in (values or []) if str(v).strip()]
    if not vals:
        return "none recorded"
    shown = vals[:limit]
    suffix = f", +{len(vals) - limit} more" if len(vals) > limit else ""
    return ", ".join(f"`{v}`" for v in shown) + suffix


def _dict_inline(values: dict | None, *, limit: int = 8) -> str:
    if not values:
        return "none recorded"
    items = list(values.items())
    shown = items[:limit]
    suffix = f", +{len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(f"`{k}={v}`" for k, v in shown) + suffix


def _condition_ids(matrix: dict) -> list[str]:
    return [str(c.get("id")) for c in (matrix.get("conditions") or []) if c.get("id")]


def _baseline_condition(matrix: dict) -> dict:
    return next((c for c in (matrix.get("conditions") or []) if c.get("baseline") is True), {})


def _run_records(run_path: Path) -> list[dict]:
    execute_dir = run_path / "evidence" / "EXECUTE"
    if not execute_dir.exists():
        return []
    rows = []
    for p in sorted(execute_dir.glob("run-record-*.artifact.json")):
        payload = _payload(p)
        if payload:
            rows.append(payload)
    return rows


def _execution_state(run_path: Path) -> dict:
    return execution_state(run_path)


def _worker_synthesis(run_path: Path, stage: str, seat: str) -> dict:
    data = _read_json(run_path / "inbox" / f"{stage}.{seat}.bundle.json")
    if stage == "ANALYZE":
        value = data.get("synthesized_bundle")
        return value if isinstance(value, dict) else {}
    return data if isinstance(data, dict) else {}


def _request_and_run(run_path: Path) -> tuple[str, str, str]:
    task = _task_payload(run_path)
    run_id = task.get("task_id") or run_path.name
    project = task.get("project") or "unregistered"
    request = task.get("request_text") or ""
    return str(run_id), str(project), str(request)


def _shell_line(command: str) -> str:
    return f"`{command}`"


def build_experiment_plan_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    matrix = _stage_payload(run_path, "DESIGN", "experiment-matrix.artifact.json")
    prereg = _stage_payload(run_path, "DESIGN", "preregistration.artifact.json")
    protocol = _stage_payload(run_path, "DESIGN", "protocol-spec.artifact.json")
    alignment = _stage_payload(run_path, "DESIGN", "alignment-report.artifact.json")
    vc = _stage_payload(run_path, "DESIGN", "variable-control-report.artifact.json")
    metric_gate = _stage_payload(run_path, "DESIGN", "metric-impl-report.artifact.json")
    train_script = _stage_payload(run_path, "EXECUTE", "trainset-script.artifact.json")
    test_script = _stage_payload(run_path, "EXECUTE", "testset-script.artifact.json")
    preflight = _stage_payload(run_path, "EXECUTE", "preflight-report.artifact.json")
    execution = _execution_state(run_path)

    if not matrix:
        raise ValueError("full rigor Markdown BLOCK: experiment-matrix artifact missing")
    if not prereg:
        raise ValueError("full rigor Markdown BLOCK: preregistration artifact missing")
    if not protocol:
        raise ValueError("full rigor Markdown BLOCK: protocol-spec artifact missing")

    run_id, project, request = _request_and_run(run_path)
    rq = matrix.get("research_question") or request
    baseline = _baseline_condition(matrix)
    variables = matrix.get("variables") or {}
    ranked = matrix.get("ranked_batch") or []
    primary_hypothesis = ranked[0].get("hypothesis") if ranked else "none recorded"

    lines: list[str] = [
        "---",
        f"run_id: {run_id}",
        f"project: {project}",
        "mode: full_rigor_minimal",
        f"generated_at: {generated_at or ''}",
        "primary_human_action: decide whether to run, rerun, or promote through a human gate",
        "records_execution_decision: false",
        "records_promotion_decision: false",
        "json_evidence_root: ../../evidence",
        "---",
        "",
        f"# Experiment Plan - {run_id}",
        "",
        "## Decision Snapshot",
        "",
        f"- Research question: {_one_line(rq, limit=520)}",
        f"- Primary hypothesis: {_one_line(primary_hypothesis, limit=420)}",
        f"- Baseline condition: `{baseline.get('id', 'none recorded')}`.",
        f"- Treatment/next-run conditions: {_csv([r.get('condition_id') for r in ranked])}.",
        f"- Primary metric: `{prereg.get('primary_metric', 'none recorded')}`.",
        f"- Planned seeds: `{prereg.get('n_seeds_planned', 'none recorded')}`.",
        f"- Execution status: `{execution['label']}` - {execution['summary']}",
        f"- Deliverable boundary: {'Evidence-bound result review' if execution['label'] == 'real-run' else 'Experiment plan only; no result-readiness brief or numeric claim is generated'}.",
        "- This page is a run plan and execution boundary. It is not a result promotion.",
        "",
        "## Research Question",
        "",
        f"- Director request: {_one_line(request, limit=520)}",
        f"- Frozen research question: {_one_line(rq, limit=520)}",
        f"- Leakage declaration: {_one_line(matrix.get('leakage_declaration'), limit=520)}",
        "",
        "## Hypothesis",
        "",
    ]
    if ranked:
        for row in ranked:
            lines.append(
                f"- Rank `{row.get('rank')}` condition `{row.get('condition_id')}`: "
                f"{_one_line(row.get('hypothesis'), limit=420)}"
            )
    else:
        lines.append("- No ranked hypothesis was recorded.")

    lines.extend([
        "",
        "## Variables",
        "",
        f"- Studied: {_csv(variables.get('studied'))}.",
        f"- Controlled: {_csv(variables.get('controlled'))}.",
        f"- Frozen: {_csv(variables.get('frozen'))}.",
        f"- Variable-control gate: `{vc.get('verdict', 'not recorded')}`.",
        "",
        "## Baselines And Conditions",
        "",
        "| Condition | Role | Factors | Compiled config seed |",
        "|---|---|---|---|",
    ])
    configs = {str(c.get("condition_id")): c for c in (protocol.get("configs") or [])}
    for condition in matrix.get("conditions") or []:
        cid = str(condition.get("id") or "")
        role = "baseline" if condition.get("baseline") is True else "treatment"
        seed = (configs.get(cid) or {}).get("seed", "")
        lines.append(f"| `{cid}` | {role} | {_dict_inline(condition.get('factors'))} | `{seed}` |")

    lines.extend([
        "",
        "## Data And Split",
        "",
        f"- Protocol source: `{protocol.get('from_matrix_ref', 'not recorded')}` with "
        f"`{len(protocol.get('configs') or [])}` compiled condition config(s).",
        f"- Train script: split `{train_script.get('split', 'not emitted')}`, "
        f"data hash `{train_script.get('data_hash_expected', 'not emitted')}`, "
        f"from protocol `{train_script.get('from_protocol_ref', 'not emitted')}`.",
        f"- Test script: split `{test_script.get('split', 'not emitted')}`, "
        f"data hash `{test_script.get('data_hash_expected', 'not emitted')}`, "
        f"frozen `{test_script.get('frozen', 'not emitted')}`, "
        f"augmentation_enabled `{test_script.get('augmentation_enabled', 'not emitted')}`.",
        f"- Alignment gate: `{alignment.get('verdict', 'not recorded')}`; "
        f"preflight gate: `{preflight.get('verdict', 'not recorded')}`.",
        "",
        "## Metrics And Statistical Plan",
        "",
        f"- Primary metric: `{prereg.get('primary_metric', 'none recorded')}`.",
        f"- Secondary metrics: {_csv(prereg.get('secondary_metrics'))}.",
        f"- Metric implementation gate: `{metric_gate.get('verdict', 'not recorded')}`; "
        f"checked metrics: {_csv(metric_gate.get('checked_metrics'), limit=12)}.",
        f"- Statistical plan: {_one_line(prereg.get('analysis_plan'), limit=620)}",
        f"- Stopping rule: {_one_line(prereg.get('stopping_rule'), limit=420)}",
        "",
        "## Preregistration Freeze",
        "",
        f"- Frozen condition ids: {_csv(prereg.get('condition_ids'))}.",
        f"- Frozen baseline condition: `{prereg.get('baseline_condition_id', 'none recorded')}`.",
        f"- Frozen hypotheses: {_csv(prereg.get('hypotheses'), limit=6)}.",
        "- Any metric, condition, or seed count outside this preregistration must be treated as exploratory unless a new preregistration is created before running.",
        "",
        "## Execution Status",
        "",
        f"- Status label: `{execution['label']}`.",
        f"- Status interpretation: {execution['summary']}",
    ])
    records = execution["records"]
    if records:
        lines.append("- Run records:")
        for record in records:
            prov = record.get("provenance") or {}
            lines.append(
                f"  - `{record.get('condition_id')}` status `{record.get('status')}`; "
                f"seed `{prov.get('seed', 'n/a')}`; config hash `{prov.get('config_hash', 'n/a')}`; "
                f"data hash `{prov.get('data_hash', 'n/a')}`."
            )
    else:
        lines.append("- No run records have been emitted yet.")

    lines.extend([
        "",
        "## Failure And Kill Criteria",
        "",
        "- Kill before running if variable-control, metric-implementation, alignment, or preflight gate is `BLOCK`.",
        "- Kill if test data hash is missing, test augmentation is enabled, or test split is not frozen.",
        "- Kill if a non-baseline condition changes any non-studied or frozen factor relative to the baseline.",
        "- Kill if `journal` is null but a run record claims `provisional` metrics.",
        "- Kill or restart with a new preregistration if ANALYZE reports an unregistered metric or condition.",
        "- Treat any adversarial VERIFY `BLOCK` as non-promotable until repaired and rerun.",
        "",
        "## Next Exact Run Commands",
        "",
        "Use these placeholders from the repository root after the correct worker bundle exists.",
        "",
        "```powershell",
        f"python -m research_agent_teams.operate worker --run-id {run_id} --stage EXECUTE",
        f"# Fill inbox/EXECUTE.bundle.json from a real lab/GPU run if you need real-run evidence.",
        f"python -m research_agent_teams.operate run-dets --run-id {run_id} --stage EXECUTE",
        f"python -m research_agent_teams.operate commit --run-id {run_id} --stage EXECUTE",
        f"python -m research_agent_teams.operate worker --run-id {run_id} --stage ANALYZE",
        f"python -m research_agent_teams.operate run-dets --run-id {run_id} --stage ANALYZE",
        f"python -m research_agent_teams.operate commit --run-id {run_id} --stage ANALYZE",
        f"python -m research_agent_teams.operate worker --run-id {run_id} --stage VERIFY",
        f"python -m research_agent_teams.operate run-dets --run-id {run_id} --stage VERIFY",
        f"python -m research_agent_teams.operate commit --run-id {run_id} --stage VERIFY",
        "```",
        "",
        "If this run already committed a scripts-only EXECUTE stage, start a fresh real-run attempt instead of overwriting history:",
        "",
        "```powershell",
        "python -m research_agent_teams.operate begin --mode full_rigor_minimal --project <project-slug> --request \"<same frozen research question>\"",
        "```",
        "",
        "## Evidence Pointers",
        "",
        "- Design matrix: `evidence/DESIGN/experiment-matrix.artifact.json`.",
        "- Protocol spec: `evidence/DESIGN/protocol-spec.artifact.json`.",
        "- Preregistration: `evidence/DESIGN/preregistration.artifact.json`.",
        "- Train/test scripts: `evidence/EXECUTE/trainset-script.artifact.json`, `evidence/EXECUTE/testset-script.artifact.json` when present.",
        "- Preflight report: `evidence/EXECUTE/preflight-report.artifact.json` when present.",
        "- Result/readiness brief: `director-review/experiments/result-readiness.md` only after an evidence-bound real-run result summary exists.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _result_or_review_exists(run_path: Path) -> bool:
    return (
        execution_state(run_path)["executed"]
        and (run_path / "evidence" / "ANALYZE" / "result-summary.artifact.json").is_file()
    )


def build_result_readiness_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    matrix = _stage_payload(run_path, "DESIGN", "experiment-matrix.artifact.json")
    prereg = _stage_payload(run_path, "DESIGN", "preregistration.artifact.json")
    result = _stage_payload(run_path, "ANALYZE", "result-summary.artifact.json")
    sanity = _stage_payload(run_path, "ANALYZE", "sanity-verdict.artifact.json")
    goal = _stage_payload(run_path, "ANALYZE", "goal-alignment-verdict.artifact.json")
    deviation = _stage_payload(run_path, "ANALYZE", "prereg-deviation-verdict.artifact.json")
    failure = _stage_payload(run_path, "ANALYZE", "failure-attribution.artifact.json")
    review = _stage_payload(run_path, "VERIFY", "review-report.artifact.json")
    analysis_synthesis = _worker_synthesis(
        run_path, "ANALYZE", "analysis-synthesizer"
    )
    verify_synthesis = _worker_synthesis(run_path, "VERIFY", "verify-synthesizer")
    execution = _execution_state(run_path)

    if not matrix:
        raise ValueError("full rigor result Markdown BLOCK: experiment-matrix artifact missing")
    if not _result_or_review_exists(run_path):
        raise ValueError(
            "full rigor result Markdown BLOCK: no evidence-bound real-run result summary found"
        )

    run_id, project, request = _request_and_run(run_path)
    findings = result.get("findings") or []
    caveats = result.get("caveats") or []
    stats = result.get("stats") or {}
    review_verdict = review.get("verdict", "not recorded")
    executed_real = execution["label"] == "real-run"
    if not executed_real:
        claim_boundary = "No result claim is valid yet because execution is scripts-only or unresolved."
    elif review_verdict == "APPROVE-FREEZE":
        claim_boundary = "The result is provisional real-run evidence, but it is still non-citable until /promote-to-vault re-derives it."
    elif review:
        claim_boundary = "VERIFY did not approve a freeze; do not promote or cite until the blockers are repaired."
    else:
        claim_boundary = "ANALYZE evidence exists, but VERIFY has not approved readiness yet."

    lines: list[str] = [
        "---",
        f"run_id: {run_id}",
        f"project: {project}",
        "mode: full_rigor_minimal",
        f"generated_at: {generated_at or ''}",
        "records_promotion_decision: false",
        "json_evidence_root: ../../evidence",
        "---",
        "",
        f"# Result And Readiness Brief - {run_id}",
        "",
        "## Result Snapshot",
        "",
        f"- Research question: {_one_line(matrix.get('research_question') or request, limit=520)}",
        f"- Execution status: `{execution['label']}` - {execution['summary']}",
        f"- Result status: `{result.get('status', 'not recorded')}`; can cite thesis: `{result.get('can_cite_thesis', 'not recorded')}`.",
        f"- Preregistered primary metric: `{prereg.get('primary_metric', 'not recorded')}`.",
    ]
    if findings:
        lines.append("- Findings:")
        for finding in findings:
            delta = f", delta `{finding.get('delta')}`" if "delta" in finding else ""
            p_value = f", p `{finding.get('p_value')}`" if "p_value" in finding else ""
            sig = (
                f", significant_after_correction `{finding.get('significant_after_correction')}`"
                if "significant_after_correction" in finding else ""
            )
            lines.append(
                f"  - `{finding.get('condition_id')}` {finding.get('metric')}: "
                f"value `{finding.get('value')}`, baseline `{finding.get('baseline_value', 'n/a')}`"
                f"{delta}{p_value}{sig}."
            )
    else:
        lines.append("- No result findings were recorded.")
    if stats:
        lines.append(f"- Statistical tests: `{stats.get('n_findings_tested', 0)}` finding(s) tested.")
    if caveats:
        lines.append(f"- Caveats: {_csv(caveats, limit=8)}.")

    lines.extend([
        "",
        "## Effect Size And Uncertainty",
        "",
    ])
    if findings:
        for finding in findings:
            metric = finding.get("metric")
            condition_id = finding.get("condition_id")
            if finding.get("delta") is None:
                effect = "absolute effect unavailable because no traceable baseline value was paired"
            else:
                effect = f"absolute effect `{finding.get('delta')}` versus `{finding.get('baseline_condition_id', 'baseline')}`"
            if finding.get("ci_low") is not None and finding.get("ci_high") is not None:
                uncertainty = (
                    f"treatment-estimate uncertainty interval `[{finding.get('ci_low')}, "
                    f"{finding.get('ci_high')}]` across `{finding.get('n_seeds')}` paired seed(s)"
                )
            else:
                uncertainty = "uncertainty interval unavailable; do not infer precision from the point estimate"
            p_value = (
                f"; paired p-value `{finding.get('p_value')}`, Holm-significant "
                f"`{finding.get('significant_after_correction')}`"
                if finding.get("p_value") is not None else
                "; no defensible paired significance test was computed"
            )
            lines.append(
                f"- `{condition_id}` / `{metric}`: {effect}; {uncertainty}{p_value}."
            )
    else:
        lines.append("- No evidence-bound finding exists, so effect size and uncertainty are unavailable.")

    lines.extend([
        "",
        "## Analysis Checks",
        "",
        f"- Sanity gate: `{sanity.get('verdict', 'not recorded')}`; violations: {_csv(sanity.get('violations'))}.",
        f"- Goal-alignment gate: `{'PASS' if goal.get('pass') is True else ('BLOCK' if goal.get('pass') is False else 'not recorded')}`; violations: {_csv(goal.get('violations'))}.",
        f"- Prereg-deviation gate: `{'PASS' if deviation.get('pass') is True else ('BLOCK' if deviation.get('pass') is False else 'not recorded')}`; violations: {_csv(deviation.get('violations'))}.",
        "",
        "## Failure Attribution",
        "",
        f"- Outcome: `{failure.get('outcome', 'not recorded')}`; attributed layer: `{failure.get('attribution', 'not recorded')}`.",
        f"- Attribution state: `{failure.get('attribution_state', 'not recorded')}`; replication: `{failure.get('replication_status', 'not recorded')}`; counterfactual check: `{failure.get('counterfactual_check', 'not recorded')}`.",
        "- Validity before scientific attribution: "
        + "; ".join(
            f"{name}={failure.get(name, 'not recorded')}" for name in (
                "implementation_valid", "data_valid", "evaluation_valid", "protocol_valid",
                "statistics_valid"
            )
        )
        + ".",
        f"- Skeptical attribution: {_one_line(failure.get('summary'), limit=760)}",
        f"- Evidence references: {_csv(failure.get('evidence_ref'), limit=10)}.",
        f"- Advisory routing only: `{failure.get('next_action_hint', 'not recorded')}`; it does not execute a rerun.",
        "",
        "## Verification Readiness",
        "",
        f"- Adversarial review verdict: `{review_verdict}`.",
    ])
    checks = review.get("checks") or {}
    if checks:
        lines.append("- Verify checks:")
        for name in sorted(checks):
            row = checks[name] if isinstance(checks[name], dict) else {}
            lines.append(
                f"  - `{name}` pass `{row.get('pass')}`: {_one_line(row.get('evidence'), limit=360)}"
            )
    blockers = review.get("blocking_reasons") or []
    if blockers:
        lines.append(f"- Blocking reasons: {_csv(blockers, limit=8)}.")

    lines.extend([
        "",
        "## Claim Boundary",
        "",
        f"- Stage synthesis boundary: {_one_line(analysis_synthesis.get('claim_boundary') or verify_synthesis.get('claim_boundary'), limit=620)}",
        f"- {claim_boundary}",
        "- `/promote-to-vault` remains the only gate that can admit a frozen/citable result into the database.",
        "- This brief does not freeze a number, claim citable truth, submit a paper, or write the database.",
        "",
        "## Next Experiment",
        "",
        f"- {_one_line(analysis_synthesis.get('next_experiment') or verify_synthesis.get('next_experiment'), limit=760)}",
        "- Preserve the existing preregistration only for an exact replication; create a new preregistration before changing conditions, outcomes, or stopping rules.",
        "",
        "## Next Actions",
        "",
    ])
    if execution["label"] != "real-run":
        lines.extend([
            "1. Treat the current artifacts as a design package only.",
            "2. Run the scripts on the director-approved lab/GPU server and capture a non-null journal.",
            "3. Start a fresh real-run attempt if this run already committed a scripts-only EXECUTE stage.",
        ])
    elif review_verdict == "APPROVE-FREEZE":
        lines.extend([
            "1. Audit the result against the experiment plan and preregistration.",
            "2. If the director wants the claim admitted to the database, use `/promote-to-vault`; this run cannot self-promote.",
            "3. If a venue decision is needed, follow with `venue_readiness` after the promotion/readiness boundary is clear.",
        ])
    else:
        lines.extend([
            "1. Repair the listed VERIFY or ANALYZE blockers.",
            "2. Rerun from the earliest affected stage with the preregistration boundary preserved.",
            "3. Do not promote or cite the result until VERIFY and the human gate both clear.",
        ])

    lines.extend([
        "",
        "## Evidence Pointers",
        "",
        "- Experiment plan: `director-review/experiments/experiment-plan.md`.",
        "- Result summary: `evidence/ANALYZE/result-summary.artifact.json` when present.",
        "- Sanity verdict: `evidence/ANALYZE/sanity-verdict.artifact.json` when present.",
        "- Goal-alignment verdict: `evidence/ANALYZE/goal-alignment-verdict.artifact.json` when present.",
        "- Prereg-deviation verdict: `evidence/ANALYZE/prereg-deviation-verdict.artifact.json` when present.",
        "- Failure attribution: `evidence/ANALYZE/failure-attribution.artifact.json` when present.",
        "- Adversarial review: `evidence/VERIFY/review-report.artifact.json` when present.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def lint_experiment_plan_markdown(run_dir) -> list[str]:
    run_path = Path(run_dir)
    out = experiment_plan_path(run_path)
    errors: list[str] = []
    if not out.is_file():
        return [f"missing {EXPERIMENT_PLAN_REL.as_posix()}"]
    text = out.read_text(encoding="utf-8")
    for heading in PLAN_REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    matrix = _stage_payload(run_path, "DESIGN", "experiment-matrix.artifact.json")
    if matrix and _one_line(matrix.get("research_question"), limit=120)[:40] not in text:
        errors.append("experiment plan omits research question")
    for token in ("Research Question", "Hypothesis", "Variables", "Baseline", "Data And Split", "Preregistration", "Execution Status"):
        if token not in text:
            errors.append(f"experiment plan omits {token}")
    if len(text.strip()) < 1200:
        errors.append("experiment plan Markdown is too short to be decision-useful")
    return errors


def lint_result_readiness_markdown(run_dir) -> list[str]:
    run_path = Path(run_dir)
    out = result_readiness_path(run_path)
    errors: list[str] = []
    if not out.is_file():
        return [f"missing {RESULT_READINESS_REL.as_posix()}"]
    text = out.read_text(encoding="utf-8")
    for heading in RESULT_REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    if "Claim Boundary" not in text or "/promote-to-vault" not in text:
        errors.append("result/readiness brief must surface the promotion boundary")
    if len(text.strip()) < 700:
        errors.append("result/readiness Markdown is too short to be decision-useful")
    return errors


def write_experiment_plan_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    out = experiment_plan_path(run_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_experiment_plan_markdown(run_path, generated_at=generated_at), encoding="utf-8")
    errors = lint_experiment_plan_markdown(run_path)
    if errors:
        raise ValueError(f"full rigor experiment plan Markdown BLOCK: {errors}")
    return str(out)


def write_result_readiness_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    out = result_readiness_path(run_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_result_readiness_markdown(run_path, generated_at=generated_at), encoding="utf-8")
    errors = lint_result_readiness_markdown(run_path)
    if errors:
        raise ValueError(f"full rigor result/readiness Markdown BLOCK: {errors}")
    return str(out)


def write_full_rigor_markdown(run_dir, generated_at: Optional[str] = None) -> dict:
    run_path = Path(run_dir)
    out = {"experiment_plan": write_experiment_plan_markdown(run_path, generated_at=generated_at)}
    if _result_or_review_exists(run_path):
        out["result_readiness"] = write_result_readiness_markdown(run_path, generated_at=generated_at)
    else:
        stale = result_readiness_path(run_path)
        if stale.is_file():
            stale.unlink()
    return out
