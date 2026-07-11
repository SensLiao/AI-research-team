"""RAT-native eval harness for research-product quality and honesty.

The highest-value checks target what the director reads: ideas must be
falsifiable, evidence briefs must change a decision, experiment plans must be
runnable, and every operated mode must have a mode-specific Markdown contract.
Boundary checks remain as a small supporting layer; they are not a proxy for
scientific quality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from research_agent_teams.tools import aers_catalog_router
from research_agent_teams.tools.capability_catalog import build_capability_catalog
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.research_output_quality import MODE_OUTPUT_CONTRACTS


def _machine_check(check_id: str, required: bool, passed: bool, message: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "kind": "machine",
        "required": required,
        "passed": bool(passed),
        "message": message,
    }


def _manual_check(check_id: str, required: bool, guidance: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "kind": "manual",
        "required": required,
        "passed": None,
        "message": guidance,
    }


def _scenario(
    scenario_id: str,
    *,
    category: str,
    severity: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    required_failures = [
        check for check in checks
        if check["kind"] == "machine" and check["required"] and check["passed"] is False
    ]
    manual_open = [check for check in checks if check["kind"] == "manual" and check["passed"] is None]
    if required_failures:
        status = "fail"
    elif manual_open:
        status = "needs_manual"
    else:
        status = "pass"
    return {
        "id": scenario_id,
        "category": category,
        "severity": severity,
        "status": status,
        "checks": checks,
    }


def _mode_by_name(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["mode"]: row for row in catalog.get("modes", [])}


def _research_product_scenario(catalog: dict[str, Any]) -> dict[str, Any]:
    operated = {
        row["mode"] for row in catalog.get("modes", [])
        if row.get("status") == "operated"
    }
    contracts = set(MODE_OUTPUT_CONTRACTS)
    shallow = sorted(
        mode for mode, contract in MODE_OUTPUT_CONTRACTS.items()
        if len(contract.concepts) < 6 or contract.min_chars < 600 or not contract.primary_globs
    )
    checks = [
        _machine_check(
            "every-operated-mode-has-director-markdown-contract",
            True,
            operated == contracts,
            f"missing={sorted(operated - contracts)} extra={sorted(contracts - operated)}",
        ),
        _machine_check(
            "contracts-test-business-depth-not-json-shape",
            True,
            not shallow,
            f"shallow_contracts={shallow}",
        ),
    ]
    return _scenario(
        "rat-research-product-quality",
        category="research-output-quality",
        severity="critical",
        checks=checks,
    )


def _capability_surface_scenario(catalog: dict[str, Any]) -> dict[str, Any]:
    modes = catalog.get("modes", [])
    operated = [row for row in modes if row.get("status") == "operated"]
    spec_only = [row for row in modes if row.get("status") == "spec_only"]
    drift = catalog.get("validation", {}).get("operate_registry_drift") or []
    default_spec_only = []
    for row in modes:
        if row.get("status") == "spec_only" and row.get("intents"):
            default_spec_only.append(row.get("mode"))
    checks = [
        _machine_check(
            "no-operate-registry-drift",
            True,
            not drift,
            f"operate_registry_drift={drift}",
        ),
        _machine_check(
            "operated-count-matches-summary",
            True,
            len(operated) == catalog.get("summary", {}).get("operated_modes"),
            f"operated={len(operated)} summary={catalog.get('summary', {}).get('operated_modes')}",
        ),
        _machine_check(
            "spec-only-not-in-default-tier-catalog",
            True,
            not default_spec_only,
            f"spec_only_modes_with_intent_tiers={sorted(default_spec_only)}",
        ),
        _machine_check(
            "spec-only-has-honesty-note",
            True,
            all("spec_only_not_push_button" in row.get("honesty_notes", []) for row in spec_only),
            "every spec-only mode must say it is not push-button",
        ),
    ]
    return _scenario(
        "rat-capability-surface-honesty",
        category="capability-governance",
        severity="critical",
        checks=checks,
    )


def _execution_boundary_scenario(catalog: dict[str, Any]) -> dict[str, Any]:
    modes = _mode_by_name(catalog)
    server_gated = [
        row for row in catalog.get("modes", [])
        if row.get("requires_server_for_real_experiment")
    ]
    execute_modes = [
        row for row in catalog.get("modes", [])
        if row.get("execute_stage_present")
    ]
    checks = [
        _machine_check(
            "full-rigor-server-gated",
            True,
            bool(modes.get("full_rigor_minimal", {}).get("requires_server_for_real_experiment")),
            "full_rigor_minimal must not imply real GPU execution without server evidence",
        ),
        _machine_check(
            "server-gated-modes-have-note",
            True,
            all(
                "real_experiment_execution_requires_server_evidence" in row.get("honesty_notes", [])
                for row in server_gated
            ),
            f"server_gated={[row.get('mode') for row in server_gated]}",
        ),
        _machine_check(
            "execute-modes-have-no-execution-claim-note",
            True,
            all(
                "execute_stage_present_no_execution_claim_without_run_evidence" in row.get("honesty_notes", [])
                for row in execute_modes
            ),
            f"execute_modes={[row.get('mode') for row in execute_modes]}",
        ),
    ]
    return _scenario(
        "rat-execution-boundary-honesty",
        category="execution-honesty",
        severity="critical",
        checks=checks,
    )


def _vault_and_aers_boundary_scenario(catalog: dict[str, Any], *, aers_root: Optional[str | Path]) -> dict[str, Any]:
    summary = catalog.get("summary", {})
    checks = [
        _machine_check(
            "capability-catalog-never-writes-vault",
            True,
            summary.get("vault_write") is False,
            f"vault_write={summary.get('vault_write')}",
        ),
        _machine_check(
            "capability-catalog-never-executes-external-skills",
            True,
            summary.get("external_skill_execution") is False,
            f"external_skill_execution={summary.get('external_skill_execution')}",
        ),
    ]
    try:
        aers_summary = aers_catalog_router.summarize_catalog(aers_root)
        aers_candidates = aers_catalog_router.load_candidates(aers_root)
        missing_or_escape = [
            row for row in aers_candidates
            if (not row.get("skill_path_exists")) or "catalog_path_escapes_root" in row.get("risk_reasons", [])
        ]
        checks.extend(
            [
                _machine_check(
                    "aers-router-is-catalog-only",
                    True,
                    aers_summary.get("catalog_only") is True
                    and aers_summary.get("vault_write") is False
                    and aers_summary.get("child_skill_bodies_read") is False,
                    f"aers_summary={aers_summary}",
                ),
                _machine_check(
                    "aers-missing-or-escaping-paths-are-do-not-use",
                    True,
                    all(row.get("recommendation") == "do_not_use" for row in missing_or_escape),
                    f"flagged={[row.get('path') for row in missing_or_escape]}",
                ),
            ]
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI when AERS is absent.
        checks.append(
            _machine_check(
                "aers-catalog-readable",
                True,
                False,
                f"AERS catalog could not be read: {exc}",
            )
        )
    return _scenario(
        "rat-vault-and-aers-boundary",
        category="boundary-safety",
        severity="critical",
        checks=checks,
    )


def _manual_final_audit_scenario(include_manual: bool) -> Optional[dict[str, Any]]:
    if not include_manual:
        return None
    checks = [
        _manual_check(
            "final-full-compatibility-audit",
            True,
            "Before a final ship claim, a human or release owner must confirm the full RAT test suite "
            "and any relevant DB/vault lint were run against the current dirty worktrees.",
        )
    ]
    return _scenario(
        "rat-final-compatibility-manual-gate",
        category="release-readiness",
        severity="high",
        checks=checks,
    )


def _summary(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [check for scenario in scenarios for check in scenario.get("checks", [])]
    required_machine_failures = [
        check for check in checks
        if check["kind"] == "machine" and check["required"] and check["passed"] is False
    ]
    manual_open = [check for check in checks if check["kind"] == "manual" and check["passed"] is None]
    return {
        "scenario_count": len(scenarios),
        "pass": sum(1 for scenario in scenarios if scenario["status"] == "pass"),
        "needs_manual": sum(1 for scenario in scenarios if scenario["status"] == "needs_manual"),
        "fail": sum(1 for scenario in scenarios if scenario["status"] == "fail"),
        "machine_checks": sum(1 for check in checks if check["kind"] == "machine"),
        "manual_open": len(manual_open),
        "required_machine_failures": len(required_machine_failures),
    }


def build_scorecard(
    *,
    capability_catalog: Optional[dict[str, Any]] = None,
    aers_root: Optional[str | Path] = None,
    include_manual: bool = True,
) -> dict[str, Any]:
    """Run the RAT eval scenarios and return a deterministic scorecard."""
    catalog = capability_catalog if capability_catalog is not None else build_capability_catalog()
    scenarios = [
        _research_product_scenario(catalog),
        _capability_surface_scenario(catalog),
        _execution_boundary_scenario(catalog),
        _vault_and_aers_boundary_scenario(catalog, aers_root=aers_root),
    ]
    manual = _manual_final_audit_scenario(include_manual)
    if manual:
        scenarios.append(manual)
    return {
        "schema_version": "1.0.0",
        "harness": "rat_eval_harness",
        "summary": _summary(scenarios),
        "scenarios": scenarios,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAT governance eval scenarios.")
    parser.add_argument(
        "--aers-root",
        help="Optional full AERS root or catalog snapshot path; defaults to RAT's internal metadata snapshot.",
    )
    parser.add_argument("--out", help="Optional path to write scorecard JSON.")
    parser.add_argument("--no-manual", action="store_true", help="Omit manual release-readiness items.")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    scorecard = build_scorecard(
        aers_root=args.aers_root,
        include_manual=not args.no_manual,
    )
    payload = json.dumps(scorecard, ensure_ascii=False, indent=args.indent)
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write RAT eval scorecard")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if scorecard["summary"]["required_machine_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_scorecard", "main"]
