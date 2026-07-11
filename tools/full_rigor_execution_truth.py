"""Deterministic execution-truth boundary for ``full_rigor_minimal``.

LLM workers may locate and explain evidence, but they are never a numeric source.
This module reconstructs condition/metric values from attested executor result
files, then cross-checks those rows against the LLM-authored journal and provisional
run records.  A coherent journal/run-record pair is insufficient by construction.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from .execution_receipt_import import (
    ExecutionReceiptError,
    IMPORT_ARTIFACT_REL,
    receipt_bound_raw_rows,
    reverify_execution_import,
    validate_records_against_import,
)


class ExecutionTruthError(ValueError):
    """Execution evidence is absent, incomplete, or internally inconsistent."""


def _payload(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("payload")
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def run_records(run_dir) -> list[dict]:
    execute_dir = Path(run_dir) / "evidence" / "EXECUTE"
    if not execute_dir.is_dir():
        return []
    return [
        row
        for path in sorted(execute_dir.glob("run-record-*.artifact.json"))
        if (row := _payload(path))
    ]


def journal(run_dir) -> dict:
    return _payload(Path(run_dir) / "evidence" / "EXECUTE" / "journal-entry.artifact.json")


def _run_id(run_dir) -> str:
    frame = _payload(Path(run_dir) / "task_frame.artifact.json")
    return str(frame.get("task_id") or Path(run_dir).name)


def verified_execution_import(run_dir, records: list[dict] | None = None) -> dict:
    """Re-verify the external receipt boundary and bind it to run records."""
    manifest = reverify_execution_import(run_dir, expected_run_id=_run_id(run_dir))
    validate_records_against_import(records if records is not None else run_records(run_dir), manifest)
    return manifest


def execution_state(run_dir) -> dict:
    """Classify readiness from records plus a freshly re-verified executor import."""
    records = run_records(run_dir)
    statuses = [str(row.get("status") or "unknown") for row in records]
    journal_exists = bool(journal(run_dir))
    any_provisional = any(status == "provisional" for status in statuses)
    all_planned = bool(records) and all(status == "planned" for status in statuses)
    evidence_error = None
    import_verified = False

    if journal_exists and any_provisional:
        try:
            verified_execution_import(run_dir, records)
            import_verified = True
        except ExecutionReceiptError as exc:
            evidence_error = str(exc)
        if import_verified:
            label = "real-run"
            summary = (
                "Attested non-LLM executor receipts, bound result files, a journal, and "
                "provisional run records are present; claims remain provisional."
            )
        else:
            label = "invalid-execution-evidence"
            summary = (
                "Journal/run-record evidence is not an execution truth source without a freshly "
                f"verified executor import: {evidence_error}"
            )
    elif all_planned:
        label = "scripts-only"
        if journal_exists:
            summary = (
                "A journal object is present, but every run record is still planned; this is an "
                "experiment plan only and no metric claim is valid yet."
            )
        else:
            summary = (
                "Dataset scripts were emitted, but no GPU journal exists and every run record is "
                "planned; this is an experiment plan only and no metric claim is valid yet."
            )
    elif not records and not journal_exists:
        label = "not-started"
        summary = "EXECUTE evidence is not present yet; this is an experiment plan only."
    else:
        label = "ambiguous-execution"
        summary = (
            "Journal and run-record state disagree or are incomplete; no metric claim is valid "
            "until execution evidence is repaired."
        )

    return {
        "label": label,
        "summary": summary,
        "records": records,
        "statuses": statuses,
        "journal_exists": journal_exists,
        "executor_import_verified": import_verified,
        "execution_evidence_error": evidence_error,
        "executed": label == "real-run",
    }


def _finite_number(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecutionTruthError(f"{context} must be numeric, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ExecutionTruthError(f"{context} must be finite, got {value!r}")
    return number


def _seed(value: Any, *, context: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionTruthError(f"{context} seed must be an integer or null, got {value!r}")
    return value


def _metric_key(condition_id: str, seed: int | None, metric: str) -> tuple[str, int | None, str]:
    return condition_id, seed, metric.casefold()


def _run_record_metrics(records: list[dict]) -> tuple[dict[tuple[str, int | None, str], float], dict[str, str]]:
    claims: dict[tuple[str, int | None, str], float] = {}
    names: dict[str, str] = {}
    for index, record in enumerate(records, start=1):
        condition_id = str(record.get("condition_id") or "").strip()
        if not condition_id:
            raise ExecutionTruthError(f"run_record {index} has no condition_id")
        status = str(record.get("status") or "")
        metrics = record.get("metrics") or {}
        if status == "planned" and metrics:
            raise ExecutionTruthError(
                f"planned run_record carries metrics for condition {condition_id!r}"
            )
        if status != "provisional":
            continue
        if not isinstance(metrics, dict) or not metrics:
            raise ExecutionTruthError(
                f"provisional run_record for {condition_id!r} has no metric claims"
            )
        provenance = record.get("provenance") or {}
        seed = _seed(provenance.get("seed"), context=f"run_record {condition_id!r}")
        for metric, value in metrics.items():
            metric_name = str(metric or "").strip()
            if not metric_name:
                raise ExecutionTruthError(f"run_record {condition_id!r} has an empty metric name")
            key = _metric_key(condition_id, seed, metric_name)
            if key in claims:
                raise ExecutionTruthError(
                    f"duplicate provisional run_record metric for {condition_id}/{seed}/{metric_name}"
                )
            claims[key] = _finite_number(
                value, context=f"run_record {condition_id}/{seed}/{metric_name}"
            )
            names.setdefault(metric_name.casefold(), metric_name)
    return claims, names


def _journal_rows(journal_payload: dict) -> list[dict]:
    snapshot = journal_payload.get("metrics_snapshot") or {}
    rows = snapshot.get("raw_result_rows") if isinstance(snapshot, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ExecutionTruthError(
            "real-run analysis requires journal.metrics_snapshot.raw_result_rows; prose or aggregate "
            "model output cannot be reconciled to executor evidence"
        )
    return rows


def _row_signature(row: dict, *, context: str) -> tuple:
    if not isinstance(row, dict):
        raise ExecutionTruthError(f"{context} is not an object")
    condition_id = str(row.get("condition_id") or "").strip()
    metric_name = str(row.get("metric") or "").strip()
    job_id = str(row.get("job_id") or "").strip()
    row_id = str(row.get("row_id") or "").strip()
    if not condition_id or not metric_name or not job_id or not row_id:
        raise ExecutionTruthError(
            f"{context} requires job_id, row_id, condition_id, and metric"
        )
    return (
        job_id,
        row_id,
        condition_id,
        _seed(row.get("seed"), context=context),
        metric_name.casefold(),
        _finite_number(row.get("value"), context=f"{context} value"),
    )


def _require_journal_matches_executor(journal_rows: list[dict], executor_rows: list[dict]) -> None:
    journal_signatures = sorted(
        (_row_signature(row, context=f"journal raw result row {index}")
         for index, row in enumerate(journal_rows, start=1)),
        key=str,
    )
    executor_signatures = sorted(
        (_row_signature(row, context=f"executor raw result row {index}")
         for index, row in enumerate(executor_rows, start=1)),
        key=str,
    )
    if journal_signatures != executor_signatures:
        raise ExecutionTruthError(
            "journal raw result rows do not exactly match attested executor result files"
        )


def _raw_metrics(rows: list[dict]) -> tuple[dict[tuple[str, int | None, str], float], dict[str, str]]:

    grouped: dict[tuple[str, int | None, str], list[float]] = {}
    names: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ExecutionTruthError(f"raw result row {index} is not an object")
        condition_id = str(row.get("condition_id") or "").strip()
        metric_name = str(row.get("metric") or "").strip()
        if not condition_id or not metric_name:
            raise ExecutionTruthError(
                f"raw result row {index} requires condition_id and metric"
            )
        seed = _seed(row.get("seed"), context=f"raw result row {index}")
        key = _metric_key(condition_id, seed, metric_name)
        grouped.setdefault(key, []).append(
            _finite_number(row.get("value"), context=f"raw result row {index} value")
        )
        names.setdefault(metric_name.casefold(), metric_name)
    return {key: fmean(values) for key, values in grouped.items()}, names


def _reconcile(
    claims: dict[tuple[str, int | None, str], float],
    raw: dict[tuple[str, int | None, str], float],
    *,
    tolerance: float,
) -> None:
    for key, claimed in claims.items():
        if key not in raw:
            condition_id, seed, metric = key
            raise ExecutionTruthError(
                "run_record/raw result rows trace BLOCK: "
                f"{condition_id}/{seed}/{metric} is claimed by run_record but has no raw rows"
            )
        if not math.isclose(claimed, raw[key], rel_tol=0.0, abs_tol=tolerance):
            condition_id, seed, metric = key
            raise ExecutionTruthError(
                "raw result rows do not match run_record: "
                f"{condition_id}/{seed}/{metric} claimed={claimed} raw={raw[key]}"
            )
    extra = sorted(set(raw) - set(claims), key=str)
    if extra:
        condition_id, seed, metric = extra[0]
        raise ExecutionTruthError(
            "run_record/raw result rows trace BLOCK: "
            f"{condition_id}/{seed}/{metric} exists in raw rows but no provisional run_record matches"
        )


def derive_numeric_evidence(
    run_dir,
    matrix: dict,
    prereg: dict,
    *,
    tolerance: float = 1e-9,
) -> dict:
    """Rebuild canonical findings and paired seed vectors from EXECUTE evidence."""
    state = execution_state(run_dir)
    if not state["executed"]:
        raise ExecutionTruthError(
            f"{state['label']} execution cannot produce numeric findings or per_seed data"
        )

    try:
        manifest = verified_execution_import(run_dir, state["records"])
        executor_rows = receipt_bound_raw_rows(run_dir, manifest)
    except ExecutionReceiptError as exc:
        raise ExecutionTruthError(f"executor receipt/import verification failed: {exc}") from exc
    journal_payload = journal(run_dir)
    journal_rows = _journal_rows(journal_payload)
    _require_journal_matches_executor(journal_rows, executor_rows)
    claims, claim_names = _run_record_metrics(state["records"])
    raw, raw_names = _raw_metrics(executor_rows)
    if not claims:
        raise ExecutionTruthError("real-run analysis has no provisional run_record metric claims")
    _reconcile(claims, raw, tolerance=tolerance)

    metric_names = {**raw_names, **claim_names}
    primary = str(prereg.get("primary_metric") or "").strip()
    primary_key = primary.casefold()
    declared_conditions = [
        str(row.get("id")) for row in (matrix.get("conditions") or []) if row.get("id")
    ]
    for condition_id in declared_conditions:
        if not any(key[0] == condition_id and key[2] == primary_key for key in raw):
            raise ExecutionTruthError(
                f"declared condition {condition_id!r} has no raw/run_record coverage for primary "
                f"metric {primary!r}"
            )

    by_condition_metric: dict[tuple[str, str], list[tuple[int | None, float]]] = {}
    for (condition_id, seed, metric_key), value in raw.items():
        by_condition_metric.setdefault((condition_id, metric_key), []).append((seed, value))

    baseline_id = str(prereg.get("baseline_condition_id") or "")
    evidence_conditions = sorted({condition_id for condition_id, _metric in by_condition_metric})
    findings: list[dict] = []
    for condition_id in evidence_conditions:
        if condition_id == baseline_id:
            continue
        metric_keys = sorted(
            metric for cid, metric in by_condition_metric if cid == condition_id
        )
        for metric_key in metric_keys:
            values = [value for _seed_value, value in by_condition_metric[(condition_id, metric_key)]]
            finding = {
                "metric": metric_names.get(metric_key, metric_key),
                "value": fmean(values),
                "condition_id": condition_id,
            }
            baseline_rows = by_condition_metric.get((baseline_id, metric_key))
            if baseline_rows:
                finding["baseline_value"] = fmean(value for _seed_value, value in baseline_rows)
                finding["baseline_condition_id"] = baseline_id
            findings.append(finding)
    if not findings:
        raise ExecutionTruthError("execution evidence contains no non-baseline findings")

    per_seed: dict[str, dict[str, list[float]]] = {}
    caveats: list[str] = []
    metric_keys = sorted({metric for _cid, metric in by_condition_metric})
    for metric_key in metric_keys:
        rows_by_condition = {
            condition_id: by_condition_metric.get((condition_id, metric_key), [])
            for condition_id in evidence_conditions
        }
        if not all(rows_by_condition.values()):
            continue
        if any(seed is None for rows in rows_by_condition.values() for seed, _value in rows):
            caveats.append(
                f"no significance computed for {metric_names.get(metric_key, metric_key)}: "
                "one or more execution rows have no seed"
            )
            continue
        seed_sets = [{seed for seed, _value in rows} for rows in rows_by_condition.values()]
        if any(len(seed_set) != len(rows) for seed_set, rows in zip(seed_sets, rows_by_condition.values())):
            raise ExecutionTruthError(
                f"duplicate seeds prevent paired analysis for {metric_names.get(metric_key, metric_key)}"
            )
        if any(seed_set != seed_sets[0] for seed_set in seed_sets[1:]):
            caveats.append(
                f"no significance computed for {metric_names.get(metric_key, metric_key)}: "
                "condition seed sets do not match"
            )
            continue
        metric_name = metric_names.get(metric_key, metric_key)
        for condition_id, rows in rows_by_condition.items():
            per_seed.setdefault(condition_id, {})[metric_name] = [
                value for _seed_value, value in sorted(rows, key=lambda item: item[0])
            ]

    return {
        "findings": findings,
        "per_seed": per_seed or None,
        "caveats": caveats,
        "run_record_count": len(state["records"]),
        "raw_result_row_count": len(
            executor_rows
        ),
        "executor_receipt_count": len(manifest["receipts"]),
        "execution_import_ref": IMPORT_ARTIFACT_REL.as_posix(),
    }


__all__ = [
    "ExecutionTruthError",
    "derive_numeric_evidence",
    "execution_state",
    "journal",
    "run_records",
    "verified_execution_import",
]
