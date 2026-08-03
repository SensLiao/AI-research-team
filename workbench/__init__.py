"""The research workbench: a rebuildable projection over the machine and the vault.

Front page for the director, structured query surface for an agent.  It holds **no**
source of truth — every row is derived from `research_agent_teams/` (the machine) and
`PhD-Research-OS/` (the vault), so `.workbench/` can be deleted and rebuilt at any time.
Nothing here writes the vault, starts a run, or resolves a credential.
"""
from __future__ import annotations

from .model import (
    EVIDENCE_LADDER,
    EVIDENCE_STATE_WORDS,
    SELF_CLAIMABLE_CEILING,
    WORK_STATE_WORDS,
    ArtifactRow,
    EvidenceState,
    EvidenceVerdict,
    ProjectRow,
    TaskRow,
    WorkState,
    coerce_evidence_state,
    coerce_work_state,
    derive_evidence_state,
)

__all__ = [
    "ArtifactRow",
    "EVIDENCE_LADDER",
    "EVIDENCE_STATE_WORDS",
    "EvidenceState",
    "EvidenceVerdict",
    "ProjectRow",
    "SELF_CLAIMABLE_CEILING",
    "TaskRow",
    "WORK_STATE_WORDS",
    "WorkState",
    "coerce_evidence_state",
    "coerce_work_state",
    "derive_evidence_state",
]
