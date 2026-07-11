"""Numeric benchmark adapter that verifies metrics from execution evidence.

This adapter recomputes aggregate metrics from result rows and compares them
against provisional run_records. It treats prose summaries as non-evidence:
a PASS requires result rows, a run journal object, and a live hash manifest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Optional

from research_agent_teams.tools.hash_manifest_validator import validate_manifest
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "numeric_benchmark_report.schema.json"


class NumericBenchmarkError(ValueError):
    """Raised for malformed benchmark inputs."""


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extract_run_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if data.get("artifact_type") == "run_record" and isinstance(data.get("payload"), dict):
            return [data["payload"]]
        for key in ("run_records", "records", "payload"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict) and isinstance(value.get("run_records"), list):
                return [row for row in value["run_records"] if isinstance(row, dict)]
    raise NumericBenchmarkError("run_records input must be a list or object containing run_records")


def _extract_result_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("rows") or data.get("results") or data.get("metrics") or []
    else:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        condition = row.get("condition_id")
        metric = row.get("metric")
        value = row.get("value")
        if isinstance(condition, str) and condition and isinstance(metric, str) and metric:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            out.append({**row, "condition_id": condition, "metric": metric, "value": float(value)})
    return out


def _group_means(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (row["condition_id"], row["metric"])
        grouped.setdefault(key, []).append(float(row["value"]))
    return {
        key: {"value": mean(values), "row_count": len(values)}
        for key, values in grouped.items()
    }


def _journal_verdict(journal: Any, journal_ref: Optional[str]) -> dict[str, Any]:
    violations: list[str] = []
    if not isinstance(journal, dict) or not journal:
        violations.append("run journal is missing or not an object")
    if isinstance(journal, dict) and str(journal.get("status") or "").lower() == "planned":
        violations.append("run journal status is planned, not executed evidence")
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "journal_ref": journal_ref,
    }


def _metric_checks(
    run_records: list[dict[str, Any]],
    recomputed: dict[tuple[str, str], dict[str, Any]],
    *,
    tolerance: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    violations: list[str] = []
    for record in run_records:
        condition = str(record.get("condition_id") or "")
        metrics = record.get("metrics") or {}
        if record.get("status") == "planned" and metrics:
            violations.append(f"{condition}: planned run_record carries metrics")
        if not isinstance(metrics, dict):
            violations.append(f"{condition}: metrics is not an object")
            continue
        for metric, claimed in sorted(metrics.items()):
            status = "match"
            violation = ""
            if isinstance(claimed, bool) or not isinstance(claimed, (int, float)):
                status = "invalid_claim"
                violation = f"{condition}/{metric}: claimed metric is not numeric"
            else:
                row = recomputed.get((condition, str(metric)))
                if row is None:
                    status = "missing_result_rows"
                    violation = f"{condition}/{metric}: no result rows to recompute claim"
                else:
                    delta = abs(float(claimed) - float(row["value"]))
                    if delta > tolerance:
                        status = "mismatch"
                        violation = (
                            f"{condition}/{metric}: claimed={claimed} "
                            f"recomputed={row['value']} delta={delta}"
                        )
            if violation:
                violations.append(violation)
            checks.append(
                {
                    "condition_id": condition,
                    "metric": str(metric),
                    "claimed_value": claimed,
                    "recomputed_value": (
                        recomputed.get((condition, str(metric))) or {}
                    ).get("value"),
                    "source_row_count": (
                        recomputed.get((condition, str(metric))) or {}
                    ).get("row_count", 0),
                    "tolerance": tolerance,
                    "status": status,
                }
            )
    return checks, violations


def build_report(
    *,
    run_records: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    hash_manifest: dict[str, Any],
    journal: Any,
    required_paths: Iterable[str],
    run_records_ref: Optional[str] = None,
    result_artifact_refs: Optional[list[str]] = None,
    hash_manifest_ref: Optional[str] = None,
    journal_ref: Optional[str] = None,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    recomputed = _group_means(result_rows)
    metric_checks, metric_violations = _metric_checks(run_records, recomputed, tolerance=tolerance)
    hash_check = validate_manifest(
        hash_manifest,
        required_paths,
        manifest_ref=hash_manifest_ref,
    )
    journal_check = _journal_verdict(journal, journal_ref)
    violations = []
    if not result_rows:
        violations.append("no result rows available for recomputation")
    violations.extend(metric_violations)
    violations.extend(f"hash: {v}" for v in hash_check.get("violations") or [])
    violations.extend(f"journal: {v}" for v in journal_check.get("violations") or [])
    payload = {
        "schema_version": "1.0.0",
        "adapter": "numeric_benchmark_adapter",
        "verdict": "BLOCK" if violations else "PASS",
        "input_refs": {
            "run_records_ref": run_records_ref,
            "result_artifact_refs": result_artifact_refs or [],
            "hash_manifest_ref": hash_manifest_ref,
            "journal_ref": journal_ref,
        },
        "summary": {
            "run_record_count": len(run_records),
            "result_row_count": len(result_rows),
            "claimed_metric_count": len(metric_checks),
            "recomputed_metric_count": len(recomputed),
            "matched_metric_count": sum(1 for row in metric_checks if row["status"] == "match"),
            "mismatch_count": sum(1 for row in metric_checks if row["status"] == "mismatch"),
            "required_machine_failures": len(violations),
        },
        "hash_check": hash_check,
        "journal_check": journal_check,
        "metric_checks": metric_checks,
        "violations": violations,
        "trust_boundary": {
            "prose_summaries_trusted": False,
            "requires_result_rows": True,
            "requires_live_hash_manifest": True,
            "requires_run_journal": True,
            "vault_write": False,
        },
    }
    errors = validate_against(SCHEMA, payload)
    if errors:
        raise NumericBenchmarkError(f"{SCHEMA} validation failed: {errors}")
    return payload


def build_report_from_files(
    *,
    run_records_path: str | Path,
    result_artifact_paths: list[str | Path],
    hash_manifest_path: str | Path,
    journal_path: str | Path,
    required_paths: Optional[list[str]] = None,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    result_rows: list[dict[str, Any]] = []
    for path in result_artifact_paths:
        result_rows.extend(_extract_result_rows(_load_json(path)))
    required = required_paths or [str(Path(path).name) for path in result_artifact_paths]
    return build_report(
        run_records=_extract_run_records(_load_json(run_records_path)),
        result_rows=result_rows,
        hash_manifest=_load_json(hash_manifest_path),
        journal=_load_json(journal_path),
        required_paths=required,
        run_records_ref=str(run_records_path),
        result_artifact_refs=[str(path) for path in result_artifact_paths],
        hash_manifest_ref=str(hash_manifest_path),
        journal_ref=str(journal_path),
        tolerance=tolerance,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute numeric benchmark claims from result rows, journal, and hash evidence."
    )
    parser.add_argument("--run-records", required=True)
    parser.add_argument("--result-artifact", action="append", required=True)
    parser.add_argument("--hash-manifest", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--required-path", action="append", default=None)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--out")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    report = build_report_from_files(
        run_records_path=args.run_records,
        result_artifact_paths=args.result_artifact,
        hash_manifest_path=args.hash_manifest,
        journal_path=args.journal,
        required_paths=args.required_path,
        tolerance=args.tolerance,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=args.indent)
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write numeric benchmark report")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "NumericBenchmarkError",
    "build_report",
    "build_report_from_files",
    "main",
]
