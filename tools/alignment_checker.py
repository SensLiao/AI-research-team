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

zero_training escape hatch (R3 A2, 2026-08-07): rules 1, 3, 5, and 6 above all assume training
happens. A frozen, no-training pipeline (e.g. a foundation model run zero-shot) legitimately has
no 'pretrained' declaration to make and no train-side preprocessing/precision/label_space to match
against — see check_alignment(..., zero_training=True) and detect_zero_training() for the dual-lock
condition that must hold before those checks may be skipped. Rules 2 and 4 never relax.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

PARITY_KEYS = ["preprocessing", "precision", "label_space"]


def detect_zero_training(declared: bool, frozen_variables: Iterable[str] = ()) -> bool:
    """Dual-lock detection for the zero_training escape hatch (R3 A2, 2026-08-07).

    True only when the caller's own declared fact says zero_training AND the experiment
    design's frozen-variable list carries an explicit zero_training entry — a single
    unchecked flag from either side is not enough to skip a parity invariant. A frozen
    entry may carry a ' -- <reason>' explanatory suffix; only the text before it is
    matched, case-insensitively. Pure and caller-agnostic: each call site supplies its
    own declared flag and frozen-variable list from wherever its bundle shape keeps them.
    """
    if not declared:
        return False
    for entry in frozen_variables or ():
        name = str(entry or "").split(" -- ", 1)[0].strip().casefold()
        if name.startswith("zero_training"):
            return True
    return False


def check_alignment(train: dict, test: dict, profile: Optional[dict] = None,
                    *, zero_training: bool = False) -> List[str]:
    """Return a list of parity violations; empty == aligned.

    zero_training (R3 A2, 2026-08-07): once the caller confirms the dual-lock escape
    hatch (see detect_zero_training), a frozen no-training pipeline is exempt from
    PARITY_KEYS and the 'pretrained' declaration — both invariants assume training
    happens at all. augmentation-must-be-disabled and inference-must-be-declared stay
    in force (a zero_training pipeline still runs inference over a test set), and the
    test side must still declare a non-empty 'preprocessing' — the one check that
    would otherwise let a zero_training pipeline train and test on differently
    processed inputs pass unnoticed once the PARITY_KEYS match is skipped.
    """
    violations: List[str] = []

    if not zero_training:
        for key in PARITY_KEYS:
            if key in train or key in test:
                if train.get(key) != test.get(key):
                    violations.append(f"{key} mismatch: train={train.get(key)!r} vs test={test.get(key)!r}")

    if test.get("augmentation", {}).get("enabled", False):
        violations.append("test/eval augmentation must be disabled (train-time aug must not touch eval)")

    if not zero_training and "pretrained" not in train:
        violations.append("train must explicitly declare 'pretrained' (even if 'none')")

    if "inference" not in test:
        violations.append("eval must declare its 'inference' config (threshold / sliding-window / tta)")

    if zero_training and not test.get("preprocessing"):
        violations.append(
            "zero_training pipeline must still declare a non-empty test 'preprocessing' "
            "(the train/test preprocessing match is skipped, so this is the only remaining check)"
        )

    return violations


def build_report(train: dict, test: dict, profile: Optional[dict] = None,
                 train_ref: Optional[str] = None, test_ref: Optional[str] = None,
                 *, zero_training: bool = False) -> dict:
    """Build an alignment_report payload (verdict derived from violations — never set by hand)."""
    violations = check_alignment(train, test, profile, zero_training=zero_training)
    invariants = list((profile or {}).get("alignment_invariants", []))
    skipped_invariants = list(PARITY_KEYS) + ["pretrained"] if zero_training else []
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "checked_invariants": invariants,
        "train_ref": train_ref,
        "test_ref": test_ref,
        "zero_training": zero_training,
        "skipped_invariants": skipped_invariants,
    }
