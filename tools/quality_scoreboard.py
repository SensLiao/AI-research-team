"""Director-facing quality scoreboard for RAT.

The scoreboard is a read-only synthesis over the capability catalog, eval
scorecard, and run manifests. It does not inspect evidence artifacts, vault
pages, secrets, or external skill bodies.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

import yaml

from research_agent_teams.tools.capability_catalog import build_capability_catalog
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.rat_eval_harness import build_scorecard
from research_agent_teams.tools.research_output_quality import audit_completed_runs

_PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = _PKG_ROOT / "runs"


def _current_stage(manifest: dict[str, Any]) -> Optional[str]:
    if manifest.get("status") == "done":
        return "REPORT"
    next_step = manifest.get("next_step") or {}
    if isinstance(next_step, dict) and next_step.get("stage"):
        return str(next_step["stage"])
    completed = manifest.get("completed_work") or []
    if completed and isinstance(completed[-1], dict):
        return str(completed[-1].get("stage") or "")
    return manifest.get("entry_stage")


def _read_manifest(path: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, "manifest is not a mapping"
    return data, None


def scan_run_manifests(runs_dir: str | Path = DEFAULT_RUNS_DIR, *, limit: int = 200) -> dict[str, Any]:
    """Scan run manifest metadata only.

    The returned rows intentionally omit request text, evidence payloads, and
    artifact contents. This is a status surface, not a scratch-data exporter.
    """
    root = Path(runs_dir)
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    if not root.exists():
        return {"runs_dir": str(root), "run_count": 0, "by_status": {}, "invalid_manifests": [], "runs": []}

    for manifest_path in sorted(root.rglob("manifest.yaml")):
        rel = manifest_path.relative_to(root)
        manifest, error = _read_manifest(manifest_path)
        if error:
            invalid.append({"path": str(rel), "error": error})
            continue
        completed = manifest.get("completed_work") or []
        pending_gates = manifest.get("pending_gates") or []
        rows.append(
            {
                "run_id": str(manifest.get("run_id") or manifest_path.parent.name),
                "project": manifest.get("project"),
                "mode": str(manifest.get("mode") or ""),
                "status": str(manifest.get("status") or "unknown"),
                "current_stage": _current_stage(manifest),
                "completed_stage_count": len(completed) if isinstance(completed, list) else 0,
                "pending_gate_count": len(pending_gates) if isinstance(pending_gates, list) else 0,
                "path": str(rel.parent),
            }
        )

    by_status: dict[str, int] = {}
    for row in rows:
        status = row["status"]
        by_status[status] = by_status.get(status, 0) + 1
    rows.sort(key=lambda row: (str(row.get("project") or ""), row["run_id"]))
    return {
        "runs_dir": str(root),
        "run_count": len(rows),
        "by_status": by_status,
        "invalid_manifests": invalid,
        "runs": rows[: max(0, limit)],
    }


def _capability_panel(catalog: dict[str, Any]) -> dict[str, Any]:
    summary = catalog["summary"]
    return {
        "total_modes": summary["total_modes"],
        "operated_modes": summary["operated_modes"],
        "spec_only_modes": summary["spec_only_modes"],
        "execute_stage_modes": summary["execute_stage_modes"],
        "server_gated_modes": summary["server_gated_modes"],
        "operate_registry_drift": catalog["validation"]["operate_registry_drift"],
    }


def _eval_panel(scorecard: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": scorecard["summary"],
        "scenario_statuses": [
            {"id": scenario["id"], "status": scenario["status"], "severity": scenario["severity"]}
            for scenario in scorecard.get("scenarios", [])
        ],
    }


def build_quality_scoreboard(
    *,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    aers_root: Optional[str | Path] = None,
    include_manual: bool = True,
    run_limit: int = 200,
) -> dict[str, Any]:
    capability = build_capability_catalog()
    eval_scorecard = build_scorecard(aers_root=aers_root, include_manual=include_manual)
    runs = scan_run_manifests(runs_dir, limit=run_limit)
    business_outputs = audit_completed_runs(runs_dir)
    required_machine_failures = eval_scorecard["summary"]["required_machine_failures"]
    invalid_manifests = len(runs["invalid_manifests"])
    business_output_failures = int(business_outputs["fail"])
    business_output_advisories = int(business_outputs["advisory"])
    overall = "blocked" if required_machine_failures or invalid_manifests or business_output_failures else (
        "needs_manual" if eval_scorecard["summary"]["manual_open"] else "machine_clean"
    )
    return {
        "schema_version": "1.0.0",
        "scoreboard": "rat_quality_scoreboard",
        "overall_status": overall,
        "summary": {
            "required_machine_failures": required_machine_failures,
            "manual_open": eval_scorecard["summary"]["manual_open"],
            "invalid_manifests": invalid_manifests,
            "business_output_failures": business_output_failures,
            "business_output_advisories": business_output_advisories,
            "run_count": runs["run_count"],
            "vault_write": False,
            "external_skill_execution": False,
        },
        "capability": _capability_panel(capability),
        "eval": _eval_panel(eval_scorecard),
        "business_outputs": business_outputs,
        "runs": runs,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the RAT quality scoreboard as JSON.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument("--aers-root")
    parser.add_argument("--out")
    parser.add_argument("--no-manual", action="store_true")
    parser.add_argument("--run-limit", type=int, default=200)
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    scoreboard = build_quality_scoreboard(
        runs_dir=args.runs_dir,
        aers_root=args.aers_root,
        include_manual=not args.no_manual,
        run_limit=args.run_limit,
    )
    payload = json.dumps(scoreboard, ensure_ascii=False, indent=args.indent)
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write RAT quality scoreboard")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 1 if scoreboard["overall_status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_quality_scoreboard", "main", "scan_run_manifests"]
