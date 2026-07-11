"""Deterministic capability catalog for Research Agent Teams.

This is the RAT-native counterpart to the AERS catalog surface. It derives the
director-facing capability map from executable registries instead of prose, so a
mode is only shown as one-button when the operate recipe is actually present.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Optional

from research_agent_teams.orchestrator.agent_connectivity import build_agent_connectivity
from research_agent_teams.orchestrator.graph_spec import (
    load_mode_registry,
    load_roster,
    validate_mode_registry,
)
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools import research_plan

_PKG_ROOT = Path(__file__).resolve().parent.parent
_MODE_REGISTRY_REF = "orchestrator/mode_registry.yaml"
_OPERATE_REGISTRY_REF = "operate/modes/__init__.py::REGISTRY"
_PLAN_CATALOG_REF = "orchestrator/plan_catalog.yaml"

_BAND_LIGHT_MAX = 6
_BAND_MEDIUM_MAX = 16
_SPEC_ONLY_MATURITY_LEVELS = {
    "engine_tested_spec_only",
    "registry_routable_spec_only",
}
_PRODUCT_MATURITY_KEYS = {
    "level",
    "reason",
    "evidence_refs",
    "target_markdown",
    "minimum_worker_pipeline",
    "productization_gaps",
}

_REAL_EXPERIMENT_EXECUTION_AGENTS = {
    "ablation-runner",
    "auto-debugger",
    "experiment-journaler",
    "experiment-tree-explorer",
    "failure-triager",
    "trainset-builder",
    "testset-builder",
}


def operate_recipe_names() -> set[str]:
    """The real one-button operate surface.

    Imported lazily because this catalog is governance/inspection code; callers
    that only need registry parsing should not pay import cost until needed.
    """
    from research_agent_teams.operate.modes import REGISTRY

    return set(REGISTRY)


def _cost_band(max_agent_hops: int) -> str:
    if max_agent_hops <= _BAND_LIGHT_MAX:
        return "light"
    if max_agent_hops <= _BAND_MEDIUM_MAX:
        return "medium"
    return "heavy"


def _mode_intents(plan_catalog: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for intent, spec in (plan_catalog.get("intents") or {}).items():
        for tier in spec.get("tiers") or []:
            tier_id = str(tier.get("id") or "")
            for mode in tier.get("modes") or []:
                out.setdefault(str(mode), []).append({"intent": str(intent), "tier": tier_id})
    return {mode: sorted(rows, key=lambda row: (row["intent"], row["tier"])) for mode, rows in out.items()}


def _mode_status(mode: str, registry_operated: bool, recipe_present: bool) -> str:
    if registry_operated and recipe_present:
        return "operated"
    if registry_operated and not recipe_present:
        return "claimed_operated_without_recipe"
    if recipe_present and not registry_operated:
        return "recipe_without_operated_flag"
    return "spec_only"


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_text_list(value: Any, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(_nonempty_text(item) for item in value)
    )


def _validate_spec_only_product_maturity(
    mode: str,
    spec: dict[str, Any],
    roster: set[str],
) -> list[str]:
    """Validate the target product contract without implying that it is implemented."""
    maturity = spec.get("product_maturity")
    if spec.get("operated"):
        if maturity is not None:
            return [f"{mode}.product_maturity is reserved for modes without operated:true"]
        return []
    if not isinstance(maturity, dict):
        return [f"{mode}.product_maturity missing for spec-only mode"]

    errors: list[str] = []
    missing = sorted(_PRODUCT_MATURITY_KEYS - set(maturity))
    unknown = sorted(set(maturity) - _PRODUCT_MATURITY_KEYS)
    if missing:
        errors.append(f"{mode}.product_maturity missing fields: {missing}")
    if unknown:
        errors.append(f"{mode}.product_maturity unknown fields: {unknown}")

    level = maturity.get("level")
    if level not in _SPEC_ONLY_MATURITY_LEVELS:
        errors.append(f"{mode}.product_maturity.level invalid: {level}")
    if not _nonempty_text(maturity.get("reason")):
        errors.append(f"{mode}.product_maturity.reason must be non-empty")

    evidence_refs = maturity.get("evidence_refs")
    if not _nonempty_text_list(evidence_refs):
        errors.append(f"{mode}.product_maturity.evidence_refs must be a non-empty string list")
    else:
        for ref in evidence_refs:
            evidence_path = (_PKG_ROOT / ref).resolve()
            if not evidence_path.is_relative_to(_PKG_ROOT) or not evidence_path.is_file():
                errors.append(f"{mode}.product_maturity.evidence_ref missing or outside package: {ref}")

    markdown = maturity.get("target_markdown")
    if not isinstance(markdown, dict):
        errors.append(f"{mode}.product_maturity.target_markdown must be an object")
    else:
        expected_keys = {"path", "purpose", "required_sections"}
        if set(markdown) != expected_keys:
            errors.append(
                f"{mode}.product_maturity.target_markdown fields must be {sorted(expected_keys)}"
            )
        path = markdown.get("path")
        if not (
            _nonempty_text(path)
            and path.startswith("director-review/")
            and path.endswith(".md")
            and ".." not in Path(path).parts
        ):
            errors.append(
                f"{mode}.product_maturity.target_markdown.path must be a director-review/*.md path"
            )
        if not _nonempty_text(markdown.get("purpose")):
            errors.append(f"{mode}.product_maturity.target_markdown.purpose must be non-empty")
        if not _nonempty_text_list(markdown.get("required_sections"), minimum=3):
            errors.append(
                f"{mode}.product_maturity.target_markdown.required_sections needs at least 3 entries"
            )

    pipeline = maturity.get("minimum_worker_pipeline")
    if not isinstance(pipeline, dict):
        errors.append(f"{mode}.product_maturity.minimum_worker_pipeline must be an object")
    else:
        expected_keys = {"minimum_distinct_workers", "stages"}
        if set(pipeline) != expected_keys:
            errors.append(
                f"{mode}.product_maturity.minimum_worker_pipeline fields must be {sorted(expected_keys)}"
            )
        minimum_workers = pipeline.get("minimum_distinct_workers")
        if not isinstance(minimum_workers, int) or isinstance(minimum_workers, bool) or minimum_workers < 2:
            errors.append(
                f"{mode}.product_maturity.minimum_worker_pipeline.minimum_distinct_workers must be >= 2"
            )
        stages = pipeline.get("stages")
        worker_names: set[str] = set()
        stage_ids: list[str] = []
        if not isinstance(stages, list) or len(stages) < 2:
            errors.append(
                f"{mode}.product_maturity.minimum_worker_pipeline.stages needs at least 2 stages"
            )
        else:
            for index, stage in enumerate(stages):
                prefix = f"{mode}.product_maturity.minimum_worker_pipeline.stages[{index}]"
                if not isinstance(stage, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if set(stage) != {"id", "workers", "produces"}:
                    errors.append(f"{prefix} fields must be ['id', 'produces', 'workers']")
                if not _nonempty_text(stage.get("id")):
                    errors.append(f"{prefix}.id must be non-empty")
                else:
                    stage_ids.append(stage["id"])
                workers = stage.get("workers")
                if not _nonempty_text_list(workers):
                    errors.append(f"{prefix}.workers must be a non-empty string list")
                else:
                    worker_names.update(workers)
                    for worker in workers:
                        if worker not in roster:
                            errors.append(f"{prefix}.workers unknown agent: {worker}")
                if not _nonempty_text(stage.get("produces")):
                    errors.append(f"{prefix}.produces must be non-empty")
            if len(stage_ids) != len(set(stage_ids)):
                errors.append(f"{mode}.product_maturity pipeline stage ids must be unique")
        if isinstance(minimum_workers, int) and len(worker_names) < minimum_workers:
            errors.append(
                f"{mode}.product_maturity pipeline names {len(worker_names)} distinct workers, "
                f"below declared minimum {minimum_workers}"
            )

    if not _nonempty_text_list(maturity.get("productization_gaps"), minimum=2):
        errors.append(f"{mode}.product_maturity.productization_gaps needs at least 2 entries")
    return errors


def _runnable_surface(status: str) -> str:
    if status == "operated":
        return "one_button_operate"
    if status == "spec_only":
        return "registry_defined_not_one_button"
    return "drift_requires_repair"


def _honesty_notes(
    *,
    status: str,
    gate_level: str,
    execute_stage_present: bool,
    requires_server_for_real_experiment: bool,
) -> list[str]:
    notes: list[str] = []
    if status == "spec_only":
        notes.append("spec_only_not_push_button")
        notes.append("target_product_contract_not_implemented")
    elif status != "operated":
        notes.append("registry_recipe_drift")
    if gate_level == "director_signoff":
        notes.append("human_gate_model_never_self_decides")
    if execute_stage_present:
        notes.append("execute_stage_present_no_execution_claim_without_run_evidence")
    if requires_server_for_real_experiment:
        notes.append("real_experiment_execution_requires_server_evidence")
    return notes


def build_capability_catalog() -> dict[str, Any]:
    """Build a no-secret, no-vault-write capability catalog from live RAT registries."""
    registry = load_mode_registry()
    modes = registry.get("modes") or {}
    recipes = operate_recipe_names()
    plan_catalog = research_plan.load_catalog()
    human_gate_map = plan_catalog.get("mode_gates") or {}
    intent_index = _mode_intents(plan_catalog)
    connectivity = build_agent_connectivity()
    registry_errors = validate_mode_registry(registry)
    roster = load_roster()
    for mode, spec in modes.items():
        registry_errors.extend(_validate_spec_only_product_maturity(mode, spec or {}, roster))

    mode_rows: list[dict[str, Any]] = []
    drift: list[str] = []
    for mode in sorted(modes):
        spec = modes[mode] or {}
        registry_operated = bool(spec.get("operated"))
        recipe_present = mode in recipes
        status = _mode_status(mode, registry_operated, recipe_present)
        if status not in {"operated", "spec_only"}:
            drift.append(f"{mode}:{status}")

        stage_path = list(spec.get("stage_path") or [spec.get("entry_stage"), "REPORT"])
        agents = list(spec.get("agent_subset") or [])
        max_agent_hops = int((spec.get("budget") or {}).get("max_agent_hops") or 0)
        gate_level = str(spec.get("gate_level") or "")
        execute_stage_present = "EXECUTE" in stage_path
        requires_server = bool(
            execute_stage_present and (_REAL_EXPERIMENT_EXECUTION_AGENTS & set(agents))
        )
        mode_rows.append(
            {
                "mode": mode,
                "status": status,
                "runnable_surface": _runnable_surface(status),
                "entry_stage": str(spec.get("entry_stage") or ""),
                "stage_path": stage_path,
                "agent_count": len(agents),
                "agents": agents,
                "gate_level": gate_level,
                "human_gates": list(human_gate_map.get(mode) or []),
                "requires_director_signoff": gate_level == "director_signoff",
                "max_agent_hops": max_agent_hops,
                "cost_band": _cost_band(max_agent_hops),
                "operate_recipe_present": recipe_present,
                "execute_stage_present": execute_stage_present,
                "requires_server_for_real_experiment": requires_server,
                "product_maturity": (
                    deepcopy(spec.get("product_maturity")) if status == "spec_only" else None
                ),
                "intents": intent_index.get(mode, []),
                "honesty_notes": _honesty_notes(
                    status=status,
                    gate_level=gate_level,
                    execute_stage_present=execute_stage_present,
                    requires_server_for_real_experiment=requires_server,
                ),
            }
        )

    summary = {
        "total_modes": len(mode_rows),
        "operated_modes": sum(1 for row in mode_rows if row["status"] == "operated"),
        "spec_only_modes": sum(1 for row in mode_rows if row["status"] == "spec_only"),
        "spec_only_product_contracts": sum(
            1 for row in mode_rows if isinstance(row["product_maturity"], dict)
        ),
        "spec_only_engine_tested_modes": sum(
            1
            for row in mode_rows
            if (row.get("product_maturity") or {}).get("level") == "engine_tested_spec_only"
        ),
        "spec_only_registry_routable_modes": sum(
            1
            for row in mode_rows
            if (row.get("product_maturity") or {}).get("level")
            == "registry_routable_spec_only"
        ),
        "director_signoff_modes": sum(1 for row in mode_rows if row["requires_director_signoff"]),
        "record_only_modes": sum(1 for row in mode_rows if row["gate_level"] == "record_only"),
        "auto_modes": sum(1 for row in mode_rows if row["gate_level"] == "auto"),
        "execute_stage_modes": sum(1 for row in mode_rows if row["execute_stage_present"]),
        "server_gated_modes": sum(1 for row in mode_rows if row["requires_server_for_real_experiment"]),
        "operated_agent_count": connectivity["summary"]["operated_agent_count"],
        "non_control_agent_count": connectivity["summary"]["non_control_agents"],
        "vault_write": False,
        "external_skill_execution": False,
        "aers_import_policy": "reference_only",
    }
    return {
        "schema_version": "1.1.0",
        "generated_from": {
            "mode_registry": _MODE_REGISTRY_REF,
            "operate_registry": _OPERATE_REGISTRY_REF,
            "plan_catalog": _PLAN_CATALOG_REF,
            "agent_connectivity": "orchestrator/agent_connectivity.py",
        },
        "summary": summary,
        "validation": {
            "mode_registry_errors": registry_errors,
            "operate_registry_drift": sorted(drift),
            "agent_connectivity_summary": connectivity["summary"],
        },
        "modes": mode_rows,
    }


def query_modes(
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    intent: Optional[str] = None,
    maturity_level: Optional[str] = None,
    requires_server_for_real_experiment: Optional[bool] = None,
) -> list[dict[str, Any]]:
    """Filter the capability catalog without weakening its honesty fields."""
    rows = list(build_capability_catalog()["modes"])
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    if stage is not None:
        stage_upper = stage.upper()
        rows = [row for row in rows if stage_upper in row["stage_path"]]
    if intent is not None:
        rows = [
            row
            for row in rows
            if any(item["intent"] == intent for item in row.get("intents", []))
        ]
    if maturity_level is not None:
        rows = [
            row
            for row in rows
            if (row.get("product_maturity") or {}).get("level") == maturity_level
        ]
    if requires_server_for_real_experiment is not None:
        rows = [
            row
            for row in rows
            if row["requires_server_for_real_experiment"] is requires_server_for_real_experiment
        ]
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the RAT capability catalog as JSON.")
    parser.add_argument("--out", help="Optional path to write the catalog JSON.")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    catalog = build_capability_catalog()
    payload = json.dumps(catalog, ensure_ascii=False, indent=args.indent)
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write RAT capability catalog")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_capability_catalog",
    "main",
    "operate_recipe_names",
    "query_modes",
]
