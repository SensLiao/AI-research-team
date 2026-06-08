"""Deterministic core of the train-test-alignment-auditor (the '对齐人').

Given a TRAIN pipeline spec and a TEST/EVAL pipeline spec (plain dicts of pipeline facts), plus the
active domain profile, return the parity violations that would invalidate a comparison. The LLM agent
gathers these facts from the code/config and calls this checker; the checker — not the LLM — decides
PASS/BLOCK, so the gate is mechanical, not a vibe.

Domain-general parity rules (the ones that hold for any AI experiment):
  1. preprocessing(train) must equal preprocessing(test)            (same input processing)
  2. test/eval augmentation must be disabled                        (no train-time aug leaking to eval)
  3. train must explicitly declare 'pretrained' (even if 'none')    (foundation-vs-scratch must be explicit)
  4. eval must declare its 'inference' config                       (threshold / sliding-window / tta)
  5. precision(train) must equal precision(test) when both declared (mixed-precision can change results)
  6. label_space(train) must equal label_space(test) when declared
Domain-specific extras (e.g. 'train_spacing == test_spacing') are listed by the profile's
alignment_invariants and recorded for the auditor; structured facts above are enforced mechanically.
"""
from __future__ import annotations

from typing import List, Optional

PARITY_KEYS = ["preprocessing", "precision", "label_space"]


def check_alignment(train: dict, test: dict, profile: Optional[dict] = None) -> List[str]:
    """Return a list of parity violations; empty == aligned."""
    violations: List[str] = []

    for key in PARITY_KEYS:
        if key in train or key in test:
            if train.get(key) != test.get(key):
                violations.append(f"{key} mismatch: train={train.get(key)!r} vs test={test.get(key)!r}")

    if test.get("augmentation", {}).get("enabled", False):
        violations.append("test/eval augmentation must be disabled (train-time aug must not touch eval)")

    if "pretrained" not in train:
        violations.append("train must explicitly declare 'pretrained' (even if 'none')")

    if "inference" not in test:
        violations.append("eval must declare its 'inference' config (threshold / sliding-window / tta)")

    return violations


def build_report(train: dict, test: dict, profile: Optional[dict] = None,
                 train_ref: Optional[str] = None, test_ref: Optional[str] = None) -> dict:
    """Build an alignment_report payload (verdict derived from violations — never set by hand)."""
    violations = check_alignment(train, test, profile)
    invariants = list((profile or {}).get("alignment_invariants", []))
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "checked_invariants": invariants,
        "train_ref": train_ref,
        "test_ref": test_ref,
    }
