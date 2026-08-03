"""The workbench vocabulary: two independent states, and rows the projection carries.

Why two states (director memo §3.5): one status field was being asked to mean both
"how far has the work got" and "how strong is the evidence".  That conflation is how
"the code is written" gets read as "the hypothesis is supported".  They are split here
and never merged again.

  work state      — Backlog → Ready → Active → Blocked / NeedsDecision → Done
  evidence state  — Proposed → DryRun → Simulated → Observed → Frozen  (or Superseded)

The honesty rule this module enforces: **an evidence state above SIMULATED can never be
self-claimed.**  `Observed` requires a real executor receipt bound to raw result bytes;
`Frozen` additionally requires a human freeze record.  A worker that asserts
`evidence_state: observed` without receipts gets `simulated` — silently downgraded on
purpose, because the alternative is a projection that launders a dry-run into a result.

Nothing here is a source of truth.  These rows are a *projection*: rebuilt from the
machine and the vault, never hand-edited, safe to delete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class WorkState(str, Enum):
    """How far the work has got.  Says nothing about whether the science holds."""

    BACKLOG = "backlog"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs_decision"
    DONE = "done"


class EvidenceState(str, Enum):
    """How strong the evidence is.  Says nothing about how much work was done."""

    PROPOSED = "proposed"
    DRY_RUN = "dry_run"
    SIMULATED = "simulated"
    OBSERVED = "observed"
    FROZEN = "frozen"
    SUPERSEDED = "superseded"


# Ranked weakest → strongest.  SUPERSEDED sits outside the ladder: it is terminal.
EVIDENCE_LADDER: tuple[EvidenceState, ...] = (
    EvidenceState.PROPOSED,
    EvidenceState.DRY_RUN,
    EvidenceState.SIMULATED,
    EvidenceState.OBSERVED,
    EvidenceState.FROZEN,
)

# The ceiling a worker may claim for itself.  Anything above needs external proof.
SELF_CLAIMABLE_CEILING = EvidenceState.SIMULATED

# Plain Chinese for the director-facing Markdown views.
WORK_STATE_WORDS: dict[WorkState, str] = {
    WorkState.BACKLOG: "待办",
    WorkState.READY: "可以开始",
    WorkState.ACTIVE: "进行中",
    WorkState.BLOCKED: "卡住了",
    WorkState.NEEDS_DECISION: "等你决定",
    WorkState.DONE: "做完了",
}

EVIDENCE_STATE_WORDS: dict[EvidenceState, str] = {
    EvidenceState.PROPOSED: "只是提议，还没跑",
    EvidenceState.DRY_RUN: "空跑过，不是真结果",
    EvidenceState.SIMULATED: "合成数据跑过，不能当科研证据",
    EvidenceState.OBSERVED: "真跑出来了，有凭据",
    EvidenceState.FROZEN: "已冻结，可以引用",
    EvidenceState.SUPERSEDED: "已作废／被取代",
}


def _rank(state: EvidenceState) -> int:
    return EVIDENCE_LADDER.index(state) if state in EVIDENCE_LADDER else -1


@dataclass(frozen=True)
class EvidenceVerdict:
    """A derived evidence state plus the reason, so a reader never has to trust it blindly."""

    state: EvidenceState
    reason: str
    downgraded_from: Optional[EvidenceState] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_state": self.state.value,
            "evidence_state_label": EVIDENCE_STATE_WORDS[self.state],
            "reason": self.reason,
            "downgraded_from": self.downgraded_from.value if self.downgraded_from else None,
        }


def coerce_evidence_state(value: Any) -> Optional[EvidenceState]:
    """Accept a stored/claimed string; unknown values are dropped, never guessed."""
    if isinstance(value, EvidenceState):
        return value
    try:
        return EvidenceState(str(value).strip().lower())
    except (ValueError, AttributeError):
        return None


def coerce_work_state(value: Any, default: WorkState = WorkState.BACKLOG) -> WorkState:
    """Accept a stored work state; an unknown value falls back rather than inventing progress."""
    if isinstance(value, WorkState):
        return value
    try:
        return WorkState(str(value).strip().lower())
    except (ValueError, AttributeError):
        return default


def derive_evidence_state(
    *,
    claimed: Any = None,
    has_executor_receipt: bool = False,
    has_raw_result: bool = False,
    ran_dry: bool = False,
    simulated: bool = False,
    human_frozen: bool = False,
    superseded: bool = False,
) -> EvidenceVerdict:
    """Derive the evidence state from facts.  A claim alone can never raise it past the ceiling.

    `has_executor_receipt` + `has_raw_result` are the *only* route to OBSERVED, mirroring
    the machine's existing rule that numeric truth comes from receipt-bound raw bytes and
    never from a worker-supplied value.  `human_frozen` on its own is not enough — a freeze
    over unobserved work would make a proposal citable.
    """
    if superseded:
        return EvidenceVerdict(EvidenceState.SUPERSEDED, "被更新的结果取代或已作废")

    proven = has_executor_receipt and has_raw_result
    if human_frozen and proven:
        return EvidenceVerdict(EvidenceState.FROZEN, "有执行凭据 + 原始结果 + 人类冻结记录")
    if proven:
        return EvidenceVerdict(EvidenceState.OBSERVED, "有执行凭据，且凭据绑定了原始结果字节")

    # No proof — establish the honest floor from what actually happened.
    if simulated:
        floor = EvidenceVerdict(EvidenceState.SIMULATED, "只在合成／fixture 数据上跑过")
    elif ran_dry:
        floor = EvidenceVerdict(EvidenceState.DRY_RUN, "只做了空跑，没有真实执行")
    else:
        floor = EvidenceVerdict(EvidenceState.PROPOSED, "还没有任何执行记录")

    asked = coerce_evidence_state(claimed)
    if asked is None or _rank(asked) <= _rank(floor.state):
        return floor

    # A claim above the floor: honour it only up to the self-claimable ceiling.
    if _rank(asked) <= _rank(SELF_CLAIMABLE_CEILING):
        return EvidenceVerdict(asked, "自述等级，仍在可自称的上限内")
    if human_frozen:
        reason = "自称已冻结，但没有执行凭据 + 原始结果 —— 冻结不能架在未观测的工作上"
    else:
        reason = "自称的等级高于可自称上限，且没有执行凭据 —— 已按事实下调"
    return EvidenceVerdict(floor.state, reason, downgraded_from=asked)


@dataclass(frozen=True)
class ArtifactRow:
    """One reachable thing a director might want to open."""

    artifact_id: str
    project: str
    kind: str
    title: str
    path: str
    source: str                      # "machine" | "vault" | "run"
    updated: str = ""
    run_id: str = ""
    evidence_state: str = EvidenceState.PROPOSED.value
    evidence_reason: str = ""
    lifecycle: str = ""             # the source's OWN lifecycle word, kept verbatim
    text: str = ""                   # indexed body; not echoed back in listings

    def as_dict(self, *, with_text: bool = False) -> dict[str, Any]:
        evidence = coerce_evidence_state(self.evidence_state) or EvidenceState.PROPOSED
        row = {
            "artifact_id": self.artifact_id,
            "project": self.project,
            "kind": self.kind,
            "title": self.title,
            "path": self.path,
            "source": self.source,
            "updated": self.updated,
            "run_id": self.run_id,
            "evidence_state": evidence.value,
            "evidence_state_label": EVIDENCE_STATE_WORDS[evidence],
            "evidence_reason": self.evidence_reason,
            "lifecycle": self.lifecycle,
        }
        if with_text:
            row["text"] = self.text
        return row


@dataclass(frozen=True)
class TaskRow:
    """A task carrying both states independently."""

    task_id: str
    project: str
    title: str
    work_state: str = WorkState.BACKLOG.value
    evidence_state: str = EvidenceState.PROPOSED.value
    priority: str = ""
    why_now: str = ""
    next_action: str = ""
    blockers: tuple[str, ...] = field(default_factory=tuple)
    source_path: str = ""
    source_status: str = ""         # the project's OWN status word, never flattened away
    evidence_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        work = coerce_work_state(self.work_state)
        evidence = coerce_evidence_state(self.evidence_state) or EvidenceState.PROPOSED
        return {
            "task_id": self.task_id,
            "project": self.project,
            "title": self.title,
            "priority": self.priority,
            "work_state": work.value,
            "work_state_label": WORK_STATE_WORDS[work],
            "source_status": self.source_status,
            "evidence_state": evidence.value,
            "evidence_state_label": EVIDENCE_STATE_WORDS[evidence],
            "evidence_reason": self.evidence_reason,
            "why_now": self.why_now,
            "next_action": self.next_action,
            "blockers": list(self.blockers),
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class ProjectRow:
    """One project's headline: what it asks, what is settled, what is stuck."""

    slug: str
    title: str = ""
    question: str = ""
    truth_boundary: tuple[str, ...] = field(default_factory=tuple)
    lifecycle: str = "active"
    active: bool = False
    latest_run_id: str = ""
    latest_run_stage: str = ""
    open_decisions: tuple[str, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    counts: dict[str, int] = field(default_factory=dict)
    home_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title or self.slug,
            "question": self.question,
            "truth_boundary": list(self.truth_boundary),
            "lifecycle": self.lifecycle,
            "active": self.active,
            "latest_run_id": self.latest_run_id,
            "latest_run_stage": self.latest_run_stage,
            "open_decisions": list(self.open_decisions),
            "blockers": list(self.blockers),
            "counts": dict(self.counts),
            "home_path": self.home_path,
        }


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
