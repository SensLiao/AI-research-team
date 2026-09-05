"""Read-only views over historical and current manuscript asset records.

The view is integration metadata, never a replacement provenance manifest.
In particular, conceptual assets retain their empty result references.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable, Mapping


def _fail(code: str, message: str, *refs: str) -> None:
    raise ValueError(f"{code}: {message} ({', '.join(refs)})")


def asset_outputs(asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    if "semantic_type" in asset:
        return [dict(row) for row in asset.get("outputs", ())]
    output = asset.get("output")
    return [dict(output)] if isinstance(output, Mapping) else []


def asset_integration_view(
    asset: Mapping[str, Any], *, plan: Mapping[str, Any] | None = None,
    fail: Callable[..., None] = _fail,
) -> dict[str, Any]:
    """Select the planned manuscript output without changing the source record."""
    if "semantic_type" not in asset:
        return {
            "asset_type": asset.get("asset_type"),
            "output": dict(asset.get("output") or {}),
            "source_output": dict(asset.get("output") or {}),
            "result_refs": list(asset.get("result_refs", ())),
            "copies": [
                {"source": row["path"], "destination": row["path"], "sha256": row["sha256"]}
                for row in asset_outputs(asset)
            ],
        }

    outputs = asset_outputs(asset)
    asset_id = str(asset.get("asset_id") or "")
    if not outputs:
        fail("ASSET_OUTPUT_MISSING", "asset has no realized outputs", asset_id)
    kind = "FIGURE" if str(asset.get("label") or "").startswith("fig:") else "TABLE"
    if plan is not None:
        if plan.get("kind") != kind or plan.get("label") != asset.get("label"):
            fail("ASSET_PLAN_MISMATCH", "asset kind or label differs from its frozen plan", asset_id)
        planned = PurePosixPath(str(plan["planned_path"]))
        candidates = [row for row in outputs if PurePosixPath(row["path"]).suffix.lower() == planned.suffix.lower()]
        if len(candidates) > 1:
            candidates = [row for row in candidates if PurePosixPath(row["path"]).stem == planned.stem]
        if len(candidates) != 1:
            fail("ASSET_OUTPUT_SELECTION", "planned format has no unique realized output", asset_id)
        primary = candidates[0]
        canonical = planned.as_posix()
        copies = [
            {"source": row["path"], "destination": planned.with_suffix(PurePosixPath(row["path"]).suffix.lower()).as_posix(), "sha256": row["sha256"]}
            for row in outputs
        ]
    else:
        priority = {"PDF": 0, "PNG": 1, "SVG": 2}
        primary = min(outputs, key=lambda row: (priority.get(row.get("format"), 9), row["path"]))
        canonical = primary["path"]
        copies = [{"source": row["path"], "destination": row["path"], "sha256": row["sha256"]} for row in outputs]
    return {
        "asset_type": kind,
        "output": {**primary, "path": canonical},
        "source_output": dict(primary),
        "result_refs": sorted({str(row["result_ref"]) for row in asset.get("numeric_cells", ())}),
        "copies": copies,
    }
