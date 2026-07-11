"""Build a RAT integration map over the AERS skill catalog.

The planner does not import or execute AERS skill bodies. It maps catalog
metadata into RAT stages and integration lanes so every safe candidate has a
place in the research machine as a reviewed reference/SOP pack.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from research_agent_teams.tools import aers_catalog_router
from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "aers_skill_integration_plan.schema.json"

_STAGE_BY_AERS_STAGE = {
    "literature": "DISCOVER",
    "citation": "DISCOVER",
    "data": "DESIGN",
    "ideation": "IDEATE",
    "analysis": "ANALYZE",
    "robustness": "ANALYZE",
    "reproduction": "EXECUTE",
    "peer-review": "VERIFY",
    "submission": "VERIFY",
    "writing": "REPORT",
    "tables-figures": "REPORT",
    "presentation": "REPORT",
    "de-aigc": "REPORT",
}

_SOP_PACK_BY_STAGE = {
    "DISCOVER": "aers-literature-citation-pack",
    "IDEATE": "aers-ideation-pack",
    "DESIGN": "aers-data-design-pack",
    "EXECUTE": "aers-reproducibility-pack",
    "ANALYZE": "aers-analysis-robustness-pack",
    "VERIFY": "aers-peer-review-submission-pack",
    "REPORT": "aers-writing-communication-pack",
}

_AGENT_HINT_BY_STAGE = {
    "DISCOVER": "literature-search-strategist",
    "IDEATE": "hypothesis-generator",
    "DESIGN": "data-wrangling-auditor",
    "EXECUTE": "reproducibility-packager",
    "ANALYZE": "benchmark-evidence-auditor",
    "VERIFY": "submission-guideline-scout",
    "REPORT": "manuscript-polish-editor",
}


class AERSIntegrationPlanError(ValueError):
    """Raised when the generated integration plan is malformed."""


def _stage_tags(candidate: dict[str, Any]) -> list[str]:
    tags = candidate.get("tags") or {}
    vals = tags.get("stage") if isinstance(tags, dict) else []
    if vals is None:
        vals = []
    if isinstance(vals, str):
        vals = [vals]
    return [str(v) for v in vals if str(v)]


def _target_stage(candidate: dict[str, Any]) -> str:
    for tag in _stage_tags(candidate):
        stage = _STAGE_BY_AERS_STAGE.get(tag)
        if stage:
            return stage
    path = str(candidate.get("path") or "").lower()
    name = str(candidate.get("name") or "").lower()
    text = f"{path} {name}"
    if any(token in text for token in ("citation", "zotero", "literature", "search", "pdf")):
        return "DISCOVER"
    if any(token in text for token in ("repro", "replication", "run", "code")):
        return "EXECUTE"
    if any(token in text for token in ("review", "referee", "submission", "journal")):
        return "VERIFY"
    if any(token in text for token in ("write", "latex", "paper", "polish")):
        return "REPORT"
    return "REPORT"


def _lane(candidate: dict[str, Any]) -> str:
    rec = candidate["recommendation"]
    if rec == "safe_reference":
        return "reference_pack"
    if rec == "review_required":
        return "human_gate_required"
    return "blocked"


def _integration_row(candidate: dict[str, Any]) -> dict[str, Any]:
    stage = _target_stage(candidate)
    lane = _lane(candidate)
    return {
        "name": candidate["name"],
        "path": candidate["path"],
        "collection": candidate["collection"],
        "recommendation": candidate["recommendation"],
        "risk_level": candidate["risk_level"],
        "risk_reasons": candidate["risk_reasons"],
        "target_stage": stage,
        "target_agent_hint": _AGENT_HINT_BY_STAGE[stage],
        "sop_pack": _SOP_PACK_BY_STAGE[stage],
        "integration_lane": lane,
        "license": candidate["license"],
        "commercial_use": candidate["commercial_use"],
        "source_url": candidate["source_url"],
        "catalog_only": True,
    }


def build_plan(*, aers_root: Optional[str | Path] = None) -> dict[str, Any]:
    rows = [_integration_row(candidate) for candidate in aers_catalog_router.load_candidates(aers_root)]
    by_lane: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    by_pack: dict[str, int] = {}
    for row in rows:
        by_lane[row["integration_lane"]] = by_lane.get(row["integration_lane"], 0) + 1
        by_stage[row["target_stage"]] = by_stage.get(row["target_stage"], 0) + 1
        by_pack[row["sop_pack"]] = by_pack.get(row["sop_pack"], 0) + 1
    payload = {
        "schema_version": "1.0.0",
        "planner": "aers_skill_integration_planner",
        "summary": {
            "total_candidates": len(rows),
            "reference_pack_candidates": by_lane.get("reference_pack", 0),
            "human_gate_required": by_lane.get("human_gate_required", 0),
            "blocked": by_lane.get("blocked", 0),
            "vault_write": False,
            "external_skill_execution": False,
            "child_skill_bodies_read": False,
        },
        "by_stage": dict(sorted(by_stage.items())),
        "by_sop_pack": dict(sorted(by_pack.items())),
        "rows": sorted(rows, key=lambda r: (r["integration_lane"], r["target_stage"], r["collection"], r["name"])),
    }
    errors = validate_against(SCHEMA, payload)
    if errors:
        raise AERSIntegrationPlanError(f"{SCHEMA} validation failed: {errors}")
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a RAT integration plan over the AERS catalog.")
    parser.add_argument("--aers-root")
    parser.add_argument("--out")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    plan = build_plan(aers_root=args.aers_root)
    payload = json.dumps(plan, ensure_ascii=False, indent=args.indent)
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write AERS integration plan")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AERSIntegrationPlanError", "build_plan", "main"]
