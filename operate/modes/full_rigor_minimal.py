"""Operated full-rigor experiment recipe.

Every substantive stage is a real panel.  First-round seats are blind to their
siblings; only the stage synthesizer may read their bundles.  Deterministic code
owns all gates and all result numbers.  In particular, ANALYZE reconstructs
findings from persisted raw result rows and provisional run records rather than
accepting values authored by a model.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import List

from .. import bounded_repair
from ..artifacts import GateBlock, write_artifact
from . import _shared
from ._full_rigor_workers import (
    PANEL_SPECS,
    bundle_path as _bundle_path,
    llm_step as _panel_llm_step,
    load_panel as _load_panel,
)
from ...tools import prereg as prereg_tool
from ...tools.alignment_checker import build_report as alignment_build
from ...tools.compare_metric_impls import build_report as metric_build
from ...tools.experiment_feedback import build_experiment_feedback
from ...tools.execution_receipt_import import (
    ExecutionReceiptError,
    IMPORT_ARTIFACT_REL,
    build_execution_import,
    import_note_payload,
    validate_records_against_import,
    verified_binding_index,
)
from ...tools.experiment_planner import build_matrix
from ...tools.full_rigor_execution_truth import (
    ExecutionTruthError,
    derive_numeric_evidence,
    execution_state,
    verified_execution_import,
)
from ...tools.full_rigor_markdown import (
    EXPERIMENT_PLAN_REL,
    RESULT_READINESS_REL,
    write_full_rigor_markdown,
)
from ...tools.goal_alignment_audit import build_verdict as goal_alignment_build
from ...tools.preflight_checker import build_report as preflight_build
from ...tools.protocol_compiler import compile_protocol
from ...tools.result_analyzer import build_result_summary, build_result_summary_with_stats
from ...tools.review_checker import build_report as review_build
from ...tools.sanity_checker import build_report as sanity_build
from ...tools.variable_control_checker import build_report as vc_build


STAGES = ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

MATRIX_REF = "evidence/DESIGN/experiment-matrix.artifact.json"
PROTOCOL_REF = "evidence/DESIGN/protocol-spec.artifact.json"
ALIGNMENT_REF = "evidence/DESIGN/alignment-report.artifact.json"
PREREG_REF = "evidence/DESIGN/preregistration.artifact.json"

REVIEW_CHECKS = ("leakage", "fairness", "eval_frame", "provenance", "overclaim")


def _panel_has_started(run_dir, stage: str) -> bool:
    spec = PANEL_SPECS[stage]
    return any(
        _bundle_path(run_dir, stage, seat).is_file()
        for seat in (*spec["first"], spec["synth"])
    )


def _write_json_once(path: Path, payload: dict) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_scripts_only_analysis_panel(run_dir) -> None:
    """Materialize the scientifically empty ANALYZE panel without model calls."""
    failure = {
        "hypothesis_ref": f"{MATRIX_REF}#ranked_batch/0",
        "outcome": "inconclusive",
        "attribution": "unknown",
        "attribution_state": "symptom_only",
        "implementation_valid": False,
        "data_valid": False,
        "evaluation_valid": False,
        "protocol_valid": False,
        "statistics_valid": False,
        "counterfactual_check": "not_tested",
        "replication_status": "not_attempted",
        "diagnostic_intervention": None,
        "replication_artifacts": [],
        "summary": "No execution result exists, so no failure or success can be attributed.",
        "next_action_hint": "stop",
    }
    narrative = {
        "caveats": ["Scripts-only: no signed execution result exists to analyze."],
        "failure_attribution": failure,
        "claim_boundary": "Experiment design and scripts exist; no empirical result claim is admissible.",
        "next_experiment": "Run the frozen protocol through the attested external executor.",
    }
    rows = {
        "result-extractor": {"candidate_findings": [], "evidence_refs": []},
        "statistician": {
            "candidate_per_seed": None,
            "assessment": {
                "method": "not-applicable",
                "uncertainty_limit": "No result rows exist in scripts-only state.",
            },
        },
        "failure-attribution-skeptic": {
            "failure_attribution": failure,
            "alternative_explanations": [],
            "claim_boundary": narrative["claim_boundary"],
            "next_experiment": narrative["next_experiment"],
        },
        "analysis-synthesizer": {
            "source_seats": list(PANEL_SPECS["ANALYZE"]["first"]),
            "resolution_log": ["Deterministic scripts-only branch: no result evidence to reconcile."],
            "synthesized_bundle": narrative,
        },
    }
    for seat, payload in rows.items():
        _write_json_once(_bundle_path(run_dir, "ANALYZE", seat), payload)


def _write_scripts_only_verify_panel(run_dir) -> None:
    """Record that result review is inapplicable until attested results exist."""
    checks = {
        name: {"pass": False, "evidence": "Not applicable: scripts-only, no result claim exists."}
        for name in REVIEW_CHECKS
    }
    next_experiment = "Execute the frozen protocol before requesting result verification."
    for seat in PANEL_SPECS["VERIFY"]["first"]:
        _write_json_once(_bundle_path(run_dir, "VERIFY", seat), {
            "checks": checks,
            "seat_summary": "No empirical result is available for independent review.",
            "next_experiment": next_experiment,
        })
    _write_json_once(_bundle_path(run_dir, "VERIFY", PANEL_SPECS["VERIFY"]["synth"]), {
        "source_seats": list(PANEL_SPECS["VERIFY"]["first"]),
        "checks": checks,
        "result_ready": False,
        "claim_boundary": "Scripts-only: no result claim may be reviewed or frozen.",
        "next_experiment": next_experiment,
    })


def llm_step(run_dir: str, stage: str, request: str, vault=None,
             model_policy: str = "max_quality"):
    """Skip result-only panels when the external executor produced no result."""
    if stage in {"ANALYZE", "VERIFY"} and not _panel_has_started(run_dir, stage):
        state = execution_state(run_dir)
        if state["label"] == "scripts-only":
            if stage == "ANALYZE":
                _write_scripts_only_analysis_panel(run_dir)
            else:
                _write_scripts_only_verify_panel(run_dir)
            return None
    return _panel_llm_step(
        run_dir, stage, request, vault=vault, model_policy=model_policy,
    )

def _require_source_seats(stage: str, synth: dict) -> None:
    expected = list(PANEL_SPECS[stage]["first"])
    if synth.get("source_seats") != expected:
        raise GateBlock(
            f"{stage} synthesis source_seats must be exactly {expected}; got "
            f"{synth.get('source_seats')!r}"
        )


def _require_synthesized_bundle(stage: str, panel: dict[str, dict]) -> dict:
    synth = panel[str(PANEL_SPECS[stage]["synth"])]
    _require_source_seats(stage, synth)
    bundle = synth.get("synthesized_bundle")
    if not isinstance(bundle, dict):
        raise GateBlock(f"{stage} synthesizer missing object synthesized_bundle")
    return bundle


def _validate_design_panel(panel: dict[str, dict]) -> dict:
    if not isinstance(panel["experiment-planner"].get("candidate_bundle"), dict):
        raise GateBlock("DESIGN experiment-planner missing candidate_bundle")
    concerns: list[tuple[str, str]] = []
    for seat in PANEL_SPECS["DESIGN"]["first"][1:]:
        assessment = panel[seat].get("assessment")
        if not isinstance(assessment, dict):
            raise GateBlock(f"DESIGN {seat} missing assessment")
        verdict = assessment.get("verdict")
        blocking = assessment.get("blocking_concerns")
        if verdict not in {"PASS", "REVISE"} or not isinstance(blocking, list):
            raise GateBlock(f"DESIGN {seat} assessment is malformed")
        if verdict == "REVISE" and not blocking:
            raise GateBlock(f"DESIGN {seat} says REVISE without a blocking concern")
        concerns.extend((seat, str(item)) for item in blocking if str(item).strip())
    synth = panel["design-synthesizer"]
    bundle = _require_synthesized_bundle("DESIGN", panel)
    resolutions = synth.get("resolution_log") or []
    for seat, concern in concerns:
        resolved = any(
            isinstance(row, dict)
            and row.get("seat") == seat
            and row.get("concern") == concern
            and str(row.get("resolution") or "").strip()
            for row in resolutions
        )
        if not resolved:
            raise GateBlock(f"DESIGN synthesis left {seat} concern unresolved: {concern}")
    return bundle


def _validate_execute_panel(panel: dict[str, dict]) -> dict:
    scripts = panel["script-author"].get("script_bundle")
    auditor = panel["execution-evidence-auditor"]
    evidence = auditor.get("execution_evidence")
    assessment = auditor.get("assessment")
    if not isinstance(scripts, dict) or not isinstance(evidence, dict):
        raise GateBlock("EXECUTE first-round seats must emit script_bundle and execution_evidence")
    if not isinstance(assessment, dict) or assessment.get("verdict") != "PASS":
        raise GateBlock("EXECUTE execution-evidence-auditor did not PASS the evidence handoff")
    if assessment.get("blocking_concerns"):
        raise GateBlock(
            f"EXECUTE evidence auditor BLOCK: {assessment.get('blocking_concerns')}"
        )
    bundle = _require_synthesized_bundle("EXECUTE", panel)
    expected = {**scripts, **evidence}
    if bundle != expected:
        raise GateBlock(
            "EXECUTE synthesizer changed first-round scripts or execution evidence; synthesis may "
            "combine but never author journal/run_record content"
        )
    return bundle


def _validate_analysis_panel(panel: dict[str, dict]) -> dict:
    extractor = panel["result-extractor"]
    statistician = panel["statistician"]
    skeptic = panel["failure-attribution-skeptic"]
    if not isinstance(extractor.get("candidate_findings"), list):
        raise GateBlock("ANALYZE result-extractor missing candidate_findings list")
    if "candidate_per_seed" not in statistician or not isinstance(
        statistician.get("assessment"), dict
    ):
        raise GateBlock("ANALYZE statistician missing candidate_per_seed or assessment")
    for key in ("failure_attribution", "alternative_explanations", "claim_boundary", "next_experiment"):
        if key not in skeptic:
            raise GateBlock(f"ANALYZE failure-attribution-skeptic missing {key}")
    failure = skeptic.get("failure_attribution")
    if not isinstance(failure, dict):
        raise GateBlock("ANALYZE failure-attribution-skeptic failure_attribution must be an object")
    for key in (
        "hypothesis_ref", "attribution_state", "implementation_valid", "data_valid",
        "evaluation_valid", "protocol_valid", "statistics_valid", "counterfactual_check",
        "replication_status", "diagnostic_intervention", "replication_artifacts",
    ):
        if key not in failure:
            raise GateBlock(f"ANALYZE failure-attribution-skeptic missing failure_attribution.{key}")
    bundle = _require_synthesized_bundle("ANALYZE", panel)
    forbidden = sorted(set(bundle) & {"findings", "per_seed", "p_value", "effect_size"})
    if forbidden:
        raise GateBlock(
            f"ANALYZE synthesizer may not author numeric result fields: {forbidden}"
        )
    for key in ("caveats", "failure_attribution", "claim_boundary", "next_experiment"):
        if key not in bundle:
            raise GateBlock(f"ANALYZE synthesized_bundle missing {key}")
    if bundle["failure_attribution"] != failure:
        raise GateBlock(
            "ANALYZE synthesizer changed the skeptic's failure attribution; causal state may not "
            "be upgraded during synthesis"
        )
    return bundle


def _merge_verify_checks(panel: dict[str, dict]) -> tuple[dict, dict]:
    synth = panel["verify-synthesizer"]
    _require_source_seats("VERIFY", synth)
    merged = {}
    for check_name in REVIEW_CHECKS:
        rows = []
        for seat in PANEL_SPECS["VERIFY"]["first"]:
            checks = panel[seat].get("checks")
            if not isinstance(checks, dict) or not isinstance(checks.get(check_name), dict):
                raise GateBlock(f"VERIFY {seat} did not investigate {check_name}")
            row = checks[check_name]
            if not isinstance(row.get("pass"), bool):
                raise GateBlock(f"VERIFY {seat}/{check_name} pass must be boolean")
            rows.append((seat, row))
        passed = all(row["pass"] for _seat, row in rows)
        evidence = " | ".join(
            f"{seat}: {str(row.get('evidence') or 'no evidence').strip()}" for seat, row in rows
        )
        merged[check_name] = {"pass": passed, "evidence": evidence}

        synth_row = (synth.get("checks") or {}).get(check_name)
        if not isinstance(synth_row, dict) or synth_row.get("pass") is not passed:
            raise GateBlock(
                f"VERIFY synthesis overrode independent verdict for {check_name}; expected pass={passed}"
            )
    if not isinstance(synth.get("result_ready"), bool):
        raise GateBlock("VERIFY synthesis result_ready must be boolean")
    return synth, merged


def _run_id(run_dir) -> str:
    return str(_shared.task_frame(run_dir)["payload"].get("task_id") or Path(run_dir).name)


def _seed(run_dir) -> int:
    return int(hashlib.sha256(_run_id(run_dir).encode("utf-8")).hexdigest()[:8], 16)


def _read_payload(run_dir, ref: str) -> dict:
    path = Path(run_dir) / ref
    if not path.is_file():
        raise GateBlock(
            f"full_rigor required upstream artifact {ref} is missing; complete its producing stage first"
        )
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def _direction_anchor(run_dir) -> List[str]:
    try:
        matrix = _read_payload(run_dir, MATRIX_REF)
    except GateBlock:
        return []
    texts = [str(matrix.get("research_question") or "")]
    texts.extend(str(row.get("hypothesis") or "") for row in matrix.get("ranked_batch") or [])
    return [text for text in texts if text]


def _design_dets(run_dir, ts, panel) -> tuple:
    bundle = _validate_design_panel(panel)
    _shared.require_bundle_keys(
        bundle,
        ["design", "train", "test", "shared_config", "metric_impls", "prereg"],
        stage="DESIGN",
        mode="full_rigor_minimal",
    )
    profile = _shared.domain_profile(run_dir)
    paths: List[str] = []
    design = bundle["design"]
    try:
        matrix = build_matrix(
            design["rq"],
            design["variables"],
            design["conditions"],
            design["ranked_batch"],
            design["leakage"],
        )
    except ValueError as exc:
        raise GateBlock(f"experiment-matrix design-hygiene BLOCK: {exc}") from exc

    variable_control = vc_build(matrix, profile=profile)
    paths.append(write_artifact(
        run_dir,
        "DESIGN",
        "variable-control-report.artifact.json",
        "variable_control_report",
        "variable-control-auditor",
        variable_control,
        ts,
        "blocked" if variable_control["verdict"] == "BLOCK" else "approved",
    ))
    if variable_control["verdict"] == "BLOCK":
        raise GateBlock(f"variable-control BLOCK: {variable_control['violations']}")

    metric_report = metric_build(bundle["metric_impls"], profile=profile)
    paths.append(write_artifact(
        run_dir,
        "DESIGN",
        "metric-impl-report.artifact.json",
        "metric_impl_report",
        "metric-implementation-auditor",
        metric_report,
        ts,
        "blocked" if metric_report["verdict"] == "BLOCK" else "approved",
    ))
    if metric_report["verdict"] == "BLOCK":
        raise GateBlock(f"metric-impl BLOCK: {metric_report['violations']}")

    protocol = compile_protocol(
        matrix, from_matrix_ref=MATRIX_REF, shared=bundle["shared_config"], seed=_seed(run_dir)
    )
    paths.append(write_artifact(
        run_dir, "DESIGN", "protocol-spec.artifact.json", "protocol_spec",
        "protocol-compiler", protocol, ts
    ))

    alignment = alignment_build(
        bundle["train"], bundle["test"], profile=profile,
        train_ref="train-pipeline", test_ref="test-pipeline"
    )
    paths.append(write_artifact(
        run_dir,
        "DESIGN",
        "alignment-report.artifact.json",
        "alignment_report",
        "train-test-alignment-auditor",
        alignment,
        ts,
        "blocked" if alignment["verdict"] == "BLOCK" else "approved",
    ))
    if alignment["verdict"] == "BLOCK":
        raise GateBlock(f"alignment BLOCK: {alignment['violations']}")

    try:
        prereg = prereg_tool.build_prereg(matrix, **bundle["prereg"])
    except ValueError as exc:
        raise GateBlock(f"preregistration BLOCK (analysis contract not frozen): {exc}") from exc
    paths.append(write_artifact(
        run_dir, "DESIGN", "preregistration.artifact.json", "preregistration",
        "experiment-planner", prereg, ts
    ))

    drift_texts = [design["rq"]]
    drift_texts.extend(str(row.get("hypothesis") or "") for row in matrix["ranked_batch"])
    drift_texts.extend(str(row.get("id") or "") for row in matrix["conditions"])
    drift_path, _ = _shared.run_drift_gate(run_dir, "DESIGN", ts, drift_texts)
    paths.append(drift_path)
    paths.append(write_artifact(
        run_dir, "DESIGN", "experiment-matrix.artifact.json", "experiment_matrix",
        "experiment-planner", matrix, ts
    ))
    write_full_rigor_markdown(run_dir, generated_at=ts)
    return paths, {
        "vc_gate": variable_control["verdict"],
        "metric_gate": metric_report["verdict"],
        "alignment_gate": alignment["verdict"],
        "prereg_frozen": True,
        "n_conditions": len(matrix["conditions"]),
    }


def _execute_dets(run_dir, ts, panel) -> tuple:
    bundle = _validate_execute_panel(panel)
    _shared.require_bundle_keys(
        bundle,
        [
            "train_script",
            "test_script",
            "journal",
            "run_records",
            "executor_receipt_refs",
        ],
        stage="EXECUTE", mode="full_rigor_minimal"
    )
    profile = _shared.domain_profile(run_dir)
    paths: List[str] = []
    paths.append(write_artifact(
        run_dir, "EXECUTE", "trainset-script.artifact.json", "dataset_script_record",
        "trainset-builder", bundle["train_script"], ts
    ))
    paths.append(write_artifact(
        run_dir, "EXECUTE", "testset-script.artifact.json", "dataset_script_record",
        "testset-builder", bundle["test_script"], ts
    ))

    protocol = _read_payload(run_dir, PROTOCOL_REF)
    alignment = _read_payload(run_dir, ALIGNMENT_REF)
    preflight = preflight_build(
        bundle["train_script"],
        bundle["test_script"],
        protocol,
        alignment,
        profile=profile,
        protocol_ref=PROTOCOL_REF,
        alignment_ref=ALIGNMENT_REF,
        file_identity_manifests=bundle.get("file_identity_manifests"),
    )
    paths.append(write_artifact(
        run_dir,
        "EXECUTE",
        "preflight-report.artifact.json",
        "preflight_report",
        "preflight-checker",
        preflight,
        ts,
        "blocked" if preflight["verdict"] == "BLOCK" else "approved",
    ))
    if preflight["verdict"] == "BLOCK":
        raise GateBlock(f"preflight BLOCK: {preflight['violations']}")

    journal = bundle["journal"]
    records = bundle["run_records"] or []
    receipt_refs = bundle["executor_receipt_refs"]
    if not isinstance(receipt_refs, list) or not all(
        isinstance(ref, str) and ref.strip() for ref in receipt_refs
    ):
        raise GateBlock("executor_receipt_refs must be a list of non-empty relative paths")
    for record in records:
        status = record.get("status")
        metrics = record.get("metrics") or {}
        if status == "planned" and metrics:
            raise GateBlock(
                f"planned run_record carries metrics for {record.get('condition_id')!r}; "
                "planned is not numeric execution evidence"
            )
        if journal is None and status != "planned":
            raise GateBlock(
                "no journal = no real run: every run_record must be planned and metric-free"
            )

    provisional = any(record.get("status") == "provisional" for record in records)
    if provisional:
        try:
            execution_import = build_execution_import(
                run_dir,
                receipt_refs,
                run_id=_run_id(run_dir),
                created_at=ts,
            )
            validate_records_against_import(records, execution_import)
        except ExecutionReceiptError as exc:
            raise GateBlock(f"executor receipt/import BLOCK: {exc}") from exc
        paths.append(write_artifact(
            run_dir,
            "EXECUTE",
            IMPORT_ARTIFACT_REL.name,
            "note",
            "execution-receipt-importer",
            import_note_payload(execution_import),
            ts,
        ))
    elif receipt_refs:
        raise GateBlock(
            "executor receipts were supplied without provisional run_records; execution state is ambiguous"
        )

    if journal is None:
        parity_label = "SKIPPED(no real run)"
        executed = False
    else:
        paths.append(write_artifact(
            run_dir, "EXECUTE", "journal-entry.artifact.json", "journal_entry",
            "experiment-journaler", journal, ts
        ))
        from ...tools.parity_checker import build_report as parity_build

        parity = parity_build(
            journal, alignment, profile=profile,
            journal_ref="journal_entry", alignment_ref=ALIGNMENT_REF
        )
        paths.append(write_artifact(
            run_dir,
            "EXECUTE",
            "parity-verdict.artifact.json",
            "parity_verdict",
            "train-test-parity-verifier",
            parity,
            ts,
            "blocked" if parity["verdict"] == "BLOCK" else "approved",
        ))
        if parity["verdict"] == "BLOCK":
            raise GateBlock(f"parity BLOCK: {parity['violations']}")
        executed = provisional
        parity_label = "PASS" if executed else "PASS(no completed run_records)"

    drift_texts = list(_direction_anchor(run_dir))
    for index, record in enumerate(records, start=1):
        paths.append(write_artifact(
            run_dir, "EXECUTE", f"run-record-{index}.artifact.json", "run_record",
            "ablation-runner", record, ts
        ))
        drift_texts.append(str(record.get("condition_id") or ""))
        if record.get("notes"):
            drift_texts.append(str(record["notes"]))
    drift_path, _ = _shared.run_drift_gate(run_dir, "EXECUTE", ts, drift_texts)
    paths.append(drift_path)
    write_full_rigor_markdown(run_dir, generated_at=ts)
    return paths, {
        "preflight_gate": preflight["verdict"],
        "parity_gate": parity_label,
        "scripts_emitted": True,
        "executed": executed,
        "executor_receipts_verified": len(receipt_refs) if executed else 0,
    }


def _candidate_findings_match(candidate: list[dict], canonical: list[dict]) -> None:
    def index(rows):
        out = {}
        for row in rows:
            key = (str(row.get("condition_id") or ""), str(row.get("metric") or "").casefold())
            if key in out:
                raise GateBlock(f"duplicate candidate finding for {key}")
            out[key] = row
        return out

    proposed = index(candidate)
    expected = index(canonical)
    if set(proposed) != set(expected):
        raise GateBlock(
            "candidate finding set does not match traceable execution evidence: "
            f"candidate={sorted(proposed)} evidence={sorted(expected)}"
        )
    for key, truth in expected.items():
        row = proposed[key]
        for field in ("value", "baseline_value"):
            truth_value = truth.get(field)
            candidate_value = row.get(field)
            if truth_value is None and candidate_value is None:
                continue
            if (
                isinstance(candidate_value, bool)
                or not isinstance(candidate_value, (int, float))
                or not math.isclose(float(candidate_value), float(truth_value), rel_tol=0.0, abs_tol=1e-9)
            ):
                raise GateBlock(
                    "candidate finding does not match traceable execution evidence: "
                    f"{key} {field} candidate={candidate_value!r} evidence={truth_value!r}"
                )
        if row.get("baseline_condition_id") != truth.get("baseline_condition_id"):
            raise GateBlock(
                f"candidate finding baseline trace mismatch for {key}: "
                f"{row.get('baseline_condition_id')!r} != {truth.get('baseline_condition_id')!r}"
            )


def _candidate_per_seed_match(candidate, canonical) -> None:
    if not canonical:
        if candidate not in (None, {}):
            raise GateBlock("candidate per_seed has no traceable execution evidence")
        return
    if not isinstance(candidate, dict):
        raise GateBlock("candidate per_seed omitted traceable seeded execution evidence")
    if set(candidate) != set(canonical):
        raise GateBlock(
            f"candidate per_seed condition set does not match execution evidence: "
            f"{sorted(candidate)} != {sorted(canonical)}"
        )
    for condition_id, metrics in canonical.items():
        proposed_metrics = candidate.get(condition_id)
        if not isinstance(proposed_metrics, dict) or set(proposed_metrics) != set(metrics):
            raise GateBlock(
                f"candidate per_seed metrics do not match execution evidence for {condition_id}"
            )
        for metric, values in metrics.items():
            proposed_values = proposed_metrics[metric]
            if not isinstance(proposed_values, list) or len(proposed_values) != len(values):
                raise GateBlock(
                    f"candidate per_seed vector length does not match evidence for {condition_id}/{metric}"
                )
            for proposed, truth in zip(proposed_values, values):
                if (
                    isinstance(proposed, bool)
                    or not isinstance(proposed, (int, float))
                    or not math.isclose(float(proposed), float(truth), rel_tol=0.0, abs_tol=1e-9)
                ):
                    raise GateBlock(
                        "candidate per_seed value does not match execution evidence for "
                        f"{condition_id}/{metric}: {proposed!r} != {truth!r}"
                    )


def _analysis_drift(run_dir, ts, matrix: dict, texts: list[str]) -> str:
    drift_texts = [str(matrix.get("research_question") or "")]
    drift_texts.extend(str(row.get("hypothesis") or "") for row in matrix.get("ranked_batch") or [])
    drift_texts.extend(str(text) for text in texts if str(text).strip())
    path, _ = _shared.run_drift_gate(run_dir, "ANALYZE", ts, drift_texts)
    return path


def _primary_hypothesis_ref(matrix: dict, result: dict) -> str:
    tested_conditions = {
        str(row.get("condition_id") or "") for row in result.get("findings") or []
        if str(row.get("condition_id") or "")
    }
    for index, row in enumerate(matrix.get("ranked_batch") or []):
        condition_id = str(row.get("condition_id") or "")
        if condition_id in tested_conditions and str(row.get("hypothesis") or "").strip():
            return f"{MATRIX_REF}#ranked_batch/{index}"
    raise GateBlock(
        "failure-attribution BLOCK: no tested result condition maps to a concrete ranked hypothesis"
    )


def _analyze_dets(run_dir, ts, panel) -> tuple:
    narrative = _validate_analysis_panel(panel)
    extractor = panel["result-extractor"]
    statistician = panel["statistician"]
    skeptic = panel["failure-attribution-skeptic"]
    matrix = _read_payload(run_dir, MATRIX_REF)
    prereg = _read_payload(run_dir, PREREG_REF)
    state = execution_state(run_dir)
    paths: List[str] = []

    if not state["executed"]:
        if state["label"] != "scripts-only":
            raise GateBlock(f"ANALYZE execution state is {state['label']}: {state['summary']}")
        if extractor["candidate_findings"] or statistician["candidate_per_seed"] not in (None, {}):
            raise GateBlock(
                "scripts-only numeric analysis BLOCK: findings/per_seed are forbidden when journal "
                "is null or every run_record is planned"
            )
        paths.append(_analysis_drift(
            run_dir,
            ts,
            matrix,
            [
                *list(narrative.get("caveats") or []),
                str(narrative.get("claim_boundary") or ""),
                str(narrative.get("next_experiment") or ""),
            ],
        ))
        write_full_rigor_markdown(run_dir, generated_at=ts)
        return paths, {
            "analysis_status": "SKIPPED(scripts-only)",
            "stats_computed": False,
            "result_summary_emitted": False,
        }

    try:
        truth = derive_numeric_evidence(run_dir, matrix, prereg)
    except ExecutionTruthError as exc:
        raise GateBlock(f"ANALYZE execution-evidence BLOCK: {exc}") from exc
    _candidate_findings_match(extractor["candidate_findings"], truth["findings"])
    _candidate_per_seed_match(statistician["candidate_per_seed"], truth["per_seed"])

    caveats = list(narrative.get("caveats") or []) + list(truth["caveats"])
    if truth["per_seed"]:
        result = build_result_summary_with_stats(
            truth["findings"], truth["per_seed"], seed=_seed(run_dir), caveats=caveats
        )
        stats_computed = bool(result.get("stats", {}).get("n_findings_tested"))
    else:
        if not any("no significance computed" in caveat for caveat in caveats):
            caveats.append("no significance computed - no paired per-seed execution evidence")
        result = build_result_summary(truth["findings"], caveats=caveats)
        stats_computed = False

    profile = _shared.domain_profile(run_dir)
    sanity = sanity_build(result, profile=profile)
    paths.append(write_artifact(
        run_dir,
        "ANALYZE",
        "sanity-verdict.artifact.json",
        "sanity_verdict",
        "result-sanity-checker",
        sanity,
        ts,
        "blocked" if sanity["verdict"] == "BLOCK" else "approved",
    ))
    if sanity["verdict"] == "BLOCK":
        raise GateBlock(f"sanity BLOCK: {sanity['violations']}")

    goal = goal_alignment_build(matrix, result, profile=profile)
    paths.append(write_artifact(
        run_dir,
        "ANALYZE",
        "goal-alignment-verdict.artifact.json",
        "analysis_check_verdict",
        "goal-alignment-checker",
        goal,
        ts,
        "blocked" if not goal["pass"] else "approved",
    ))
    if not goal["pass"]:
        raise GateBlock(f"goal-alignment BLOCK: {goal['violations']}")

    deviation = prereg_tool.build_deviation_verdict(prereg, result)
    paths.append(write_artifact(
        run_dir,
        "ANALYZE",
        "prereg-deviation-verdict.artifact.json",
        "analysis_check_verdict",
        "compliance-auditor",
        deviation,
        ts,
        "blocked" if not deviation["pass"] else "approved",
    ))
    if not deviation["pass"]:
        raise GateBlock(f"prereg-deviation BLOCK: {deviation['violations']}")

    drift_texts = []
    for finding in result["findings"]:
        drift_texts.extend([str(finding["metric"]), str(finding["condition_id"])])
    drift_texts.extend(str(caveat) for caveat in caveats)
    drift_texts.extend([
        str(narrative.get("claim_boundary") or ""),
        str(narrative.get("next_experiment") or ""),
    ])
    paths.append(_analysis_drift(run_dir, ts, matrix, drift_texts))
    result_ref = "evidence/ANALYZE/result-summary.artifact.json"
    paths.append(write_artifact(
        run_dir, "ANALYZE", "result-summary.artifact.json", "result_summary",
        "result-analyzer", result, ts
    ))

    attribution = narrative.get("failure_attribution")
    if not isinstance(attribution, dict):
        raise GateBlock("ANALYZE synthesis failure_attribution must be an object")
    alternatives = [
        str(item).strip() for item in (skeptic.get("alternative_explanations") or [])
        if str(item).strip()
    ]
    summary = str(attribution.get("summary") or "").strip()
    if alternatives:
        summary += " Alternative explanations: " + "; ".join(alternatives) + "."
    summary += " Next experiment: " + str(narrative.get("next_experiment") or "").strip()
    metric_deltas = [
        {
            "name": f"{finding['metric']}@{finding['condition_id']}",
            "before": finding.get("baseline_value"),
            "after": finding.get("value"),
        }
        for finding in result["findings"]
        if finding.get("baseline_value") is not None
    ]
    evidence_refs = [
        f"evidence/EXECUTE/run-record-{index}.artifact.json"
        for index in range(1, len(state["records"]) + 1)
    ] + [truth["execution_import_ref"], result_ref]
    expected_hypothesis_ref = _primary_hypothesis_ref(matrix, result)
    if attribution.get("hypothesis_ref") != expected_hypothesis_ref:
        raise GateBlock(
            "failure-attribution BLOCK: hypothesis_ref does not match the tested ranked hypothesis; "
            f"expected {expected_hypothesis_ref!r}"
        )
    try:
        execution_import = verified_execution_import(run_dir, state["records"])
    except ExecutionReceiptError as exc:
        raise GateBlock(f"failure-attribution execution binding BLOCK: {exc}") from exc
    try:
        feedback = build_experiment_feedback(
            result_ref,
            str(attribution.get("outcome") or ""),
            str(attribution.get("attribution") or ""),
            summary,
            evidence_refs,
            hypothesis_ref=expected_hypothesis_ref,
            next_action_hint=attribution.get("next_action_hint"),
            metrics_delta=metric_deltas,
            attribution_state=attribution.get("attribution_state"),
            validity={key: attribution.get(key) for key in (
                "implementation_valid", "data_valid", "evaluation_valid", "protocol_valid",
                "statistics_valid",
            )},
            counterfactual_check=attribution.get("counterfactual_check"),
            replication_status=attribution.get("replication_status"),
            diagnostic_intervention=attribution.get("diagnostic_intervention"),
            replication_artifacts=attribution.get("replication_artifacts"),
            verified_execution_bindings=verified_binding_index(execution_import),
        )
    except ValueError as exc:
        raise GateBlock(f"failure-attribution BLOCK: {exc}") from exc
    paths.append(write_artifact(
        run_dir, "ANALYZE", "failure-attribution.artifact.json", "experiment_feedback",
        "analysis-synthesizer", feedback, ts
    ))
    write_full_rigor_markdown(run_dir, generated_at=ts)
    return paths, {
        "sanity_gate": sanity["verdict"],
        "goal_alignment_gate": "PASS" if goal["pass"] else "BLOCK",
        "prereg_deviation_gate": "PASS" if deviation["pass"] else "BLOCK",
        "stats_computed": stats_computed,
        "evidence_bound": True,
        "raw_result_rows": truth["raw_result_row_count"],
        "executor_receipts": truth["executor_receipt_count"],
    }


def _verify_dets(run_dir, ts, panel) -> tuple:
    synth, checks = _merge_verify_checks(panel)
    state = execution_state(run_dir)
    paths: List[str] = []

    if not state["executed"]:
        if synth.get("result_ready") is True:
            raise GateBlock(
                "VERIFY scripts-only BLOCK: a result cannot be ready when every run_record is planned"
            )
        drift_texts = list(_direction_anchor(run_dir))
        drift_texts.extend([
            str(synth.get("claim_boundary") or ""),
            str(synth.get("next_experiment") or ""),
        ])
        path, _ = _shared.run_drift_gate(run_dir, "VERIFY", ts, drift_texts)
        paths.append(path)
        write_full_rigor_markdown(run_dir, generated_at=ts)
        return paths, {"review_gate": "SKIPPED(scripts-only)"}

    _read_payload(run_dir, "evidence/ANALYZE/result-summary.artifact.json")
    expected_ready = all(row["pass"] for row in checks.values())
    if synth.get("result_ready") is not expected_ready:
        raise GateBlock(
            f"VERIFY result_ready must be derived from all independent checks "
            f"({expected_ready}), not self-declared"
        )
    review = review_build(checks)
    paths.append(write_artifact(
        run_dir,
        "VERIFY",
        "review-report.artifact.json",
        "review_report",
        "verify-synthesizer",
        review,
        ts,
        "blocked" if review["verdict"] == "BLOCK" else "approved",
    ))
    if review["verdict"] == "BLOCK":
        raise GateBlock(f"adversarial-review BLOCK: {review['blocking_reasons']}")

    drift_texts = list(_direction_anchor(run_dir))
    drift_texts.extend([
        str(review["verdict"]),
        str(synth.get("claim_boundary") or ""),
        str(synth.get("next_experiment") or ""),
    ])
    for name, row in checks.items():
        drift_texts.extend([name, str(row.get("evidence") or "")])
    path, _ = _shared.run_drift_gate(run_dir, "VERIFY", ts, drift_texts)
    paths.append(path)
    write_full_rigor_markdown(run_dir, generated_at=ts)
    return paths, {"review_gate": review["verdict"]}


def _report(run_dir, ts) -> tuple:
    state = execution_state(run_dir)
    sidecars = write_full_rigor_markdown(run_dir, generated_at=ts)
    references = [EXPERIMENT_PLAN_REL.as_posix()]
    if "result_readiness" in sidecars:
        references.append(RESULT_READINESS_REL.as_posix())

    if state["executed"]:
        summary = (
            "full_rigor_minimal real-run review completed. Numeric findings were reconstructed from "
            "matching raw result rows and provisional run records, all deterministic gates passed, "
            "and the result remains provisional/non-citable until /promote-to-vault re-derives it."
        )
    else:
        summary = (
            "full_rigor_minimal experiment plan only: scripts were emitted but no completed execution "
            "records exist. ANALYZE produced no result summary, VERIFY issued no freeze review, and "
            "the director-facing output contains no result readiness claim."
        )
    note = {
        "summary": summary,
        "references": references,
        "produced_artifacts": [],
        "open_questions": [],
    }
    paths = [write_artifact(
        run_dir, "REPORT", "report-note.artifact.json", "report_note",
        "research-orchestrator", note, ts
    )]
    report = {"director_experiment_plan": sidecars["experiment_plan"]}
    if "result_readiness" in sidecars:
        report["director_result_readiness"] = sidecars["result_readiness"]
    return paths, report


def _was_executed(run_dir) -> bool:
    return bool(execution_state(run_dir)["executed"])


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DESIGN":
        return _design_dets(run_dir, ts, _load_panel(run_dir, "DESIGN"))
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts, _load_panel(run_dir, "EXECUTE"))
    if stage == "ANALYZE":
        return _analyze_dets(run_dir, ts, _load_panel(run_dir, "ANALYZE"))
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts, _load_panel(run_dir, "VERIFY"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"full_rigor_minimal has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts)
    )
