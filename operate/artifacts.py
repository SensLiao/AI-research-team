"""Artifact plumbing for the operate layer.

Envelope-wrap a payload, contract-validate it, and write it into a run's `evidence/<stage>/` dir —
byte-compatible with the artifacts the engine's test producers write (same `_env` envelope, same
`validate_artifact` contract check). `GateBlock` is raised by a deterministic hard gate (evidence /
citation / variable-control / ...) to HALT the run at its stage — the operated mirror of the engine
producer raising mid-stage so the next stage is never reached on unverified evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from ..tools.validate_artifact import validate_artifact


class GateBlock(RuntimeError):
    """A deterministic hard gate refused — the run halts at this stage (no forward progress)."""


class TargetedGateBlock(GateBlock):
    """A local gap that can be repaired without replaying a whole stage."""

    def __init__(
        self,
        message: str,
        defects: Iterable[Mapping[str, object]],
        *,
        verdict: str = "NEEDS_SUPPLEMENT",
    ) -> None:
        if verdict not in {"NEEDS_SUPPLEMENT", "BLOCK"}:
            raise ValueError(f"unsupported targeted gate verdict: {verdict!r}")
        super().__init__(message)
        self.verdict = verdict
        self.defects = [dict(row) for row in defects]


def envelope(artifact_type: str, created_by: str, payload: dict, ts: str,
             status: str = "approved") -> dict:
    """The standard artifact envelope (matches the engine test producers' `_env`)."""
    return {
        "artifact_id": artifact_type,
        "artifact_type": artifact_type,
        "schema_version": "1.0.0",
        "created_by": created_by,
        "created_at": ts,
        "status": status,
        "payload": payload,
    }


def write_artifact(run_dir, stage: str, filename: str, artifact_type: str, created_by: str,
                   payload: dict, ts: str, status: str = "approved") -> str:
    """Envelope-wrap, contract-validate, and write one artifact into evidence/<stage>/. Returns its path.

    Validation happens HERE (before the file is trusted) — a producer can never write an artifact that
    fails its schema. `spine.commit_stage` re-validates every path again before checkpointing, so the
    contract is enforced twice (producer + boundary), exactly as the engine does at the boundary.
    """
    art = envelope(artifact_type, created_by, payload, ts, status)
    errs = validate_artifact(art)
    if errs:
        raise ValueError(f"operate produced an invalid {artifact_type}: {errs}")
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(json.dumps(art, ensure_ascii=False), encoding="utf-8")
    return str(p)
