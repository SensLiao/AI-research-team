"""Tests for the classify_gap deterministic gap classifier (DISCOVER-stage).

Proves that:
  - a signal with source_domain + target_hook → ("transfer_gap", "XFER_BIND")
  - a signal with challenged_assumption → ("assumption_gap", "ASSUMPTION")
  - a signal with locus + opportunity → ("methodological_gap", "WEAK_LOCUS")
  - a signal with hole=True → ("coverage_gap", "WHITESPACE")
  - a signal with white_space_present=True → ("coverage_gap", "WHITESPACE")
  - a signal with under_evidenced=True → ("evidence_gap", "UNDER_EVIDENCED")
  - a signal with untested_condition → ("empirical_gap", "UNTESTED_SETTING")
  - a signal with untested_dataset → ("empirical_gap", "UNTESTED_SETTING")
  - a signal with statement + source_ref → ("stated_open_problem", "FW_STATED")
  - an ambiguous signal matching multiple rules → first-match (priority) wins
  - a signal with no matching rule → raises ValueError
  - build_classification produces a valid gap_classification payload
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.classify_gap import build_classification, classify_gap
from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# One crafted signal per gap_type → correct enum + non-empty reason_code
# ==============================================================================

def test_transfer_gap():
    """Signal with source_domain + target_hook → transfer_gap / XFER_BIND."""
    gap_type, reason_code = classify_gap({
        "source_domain": "computer vision",
        "target_hook": "medical image segmentation",
    })
    assert gap_type == "transfer_gap"
    assert reason_code == "XFER_BIND"
    assert len(reason_code) > 0


def test_assumption_gap():
    """Signal with challenged_assumption → assumption_gap / ASSUMPTION."""
    gap_type, reason_code = classify_gap({
        "challenged_assumption": "Large-scale pre-training is always beneficial for small datasets.",
    })
    assert gap_type == "assumption_gap"
    assert reason_code == "ASSUMPTION"
    assert len(reason_code) > 0


def test_methodological_gap():
    """Signal with locus + opportunity → methodological_gap / WEAK_LOCUS."""
    gap_type, reason_code = classify_gap({
        "locus": "loss function design",
        "opportunity": "topology-aware loss for tubular structures",
    })
    assert gap_type == "methodological_gap"
    assert reason_code == "WEAK_LOCUS"
    assert len(reason_code) > 0


def test_coverage_gap_via_hole():
    """Signal with hole=True → coverage_gap / WHITESPACE."""
    gap_type, reason_code = classify_gap({
        "hole": True,
    })
    assert gap_type == "coverage_gap"
    assert reason_code == "WHITESPACE"
    assert len(reason_code) > 0


def test_coverage_gap_via_white_space_present():
    """Signal with white_space_present=True → coverage_gap / WHITESPACE."""
    gap_type, reason_code = classify_gap({
        "white_space_present": True,
    })
    assert gap_type == "coverage_gap"
    assert reason_code == "WHITESPACE"
    assert len(reason_code) > 0


def test_evidence_gap():
    """Signal with under_evidenced=True → evidence_gap / UNDER_EVIDENCED."""
    gap_type, reason_code = classify_gap({
        "under_evidenced": True,
    })
    assert gap_type == "evidence_gap"
    assert reason_code == "UNDER_EVIDENCED"
    assert len(reason_code) > 0


def test_empirical_gap_via_untested_condition():
    """Signal with untested_condition → empirical_gap / UNTESTED_SETTING."""
    gap_type, reason_code = classify_gap({
        "untested_condition": "low-data regime with fewer than 50 training samples",
    })
    assert gap_type == "empirical_gap"
    assert reason_code == "UNTESTED_SETTING"
    assert len(reason_code) > 0


def test_empirical_gap_via_untested_dataset():
    """Signal with untested_dataset → empirical_gap / UNTESTED_SETTING."""
    gap_type, reason_code = classify_gap({
        "untested_dataset": "MSD Task04_Hippocampus",
    })
    assert gap_type == "empirical_gap"
    assert reason_code == "UNTESTED_SETTING"
    assert len(reason_code) > 0


def test_stated_open_problem():
    """Signal with statement + source_ref → stated_open_problem / FW_STATED."""
    gap_type, reason_code = classify_gap({
        "statement": "Future work should explore few-shot learning for organ segmentation.",
        "source_ref": "[[wang2024]]",
    })
    assert gap_type == "stated_open_problem"
    assert reason_code == "FW_STATED"
    assert len(reason_code) > 0


# ==============================================================================
# Priority / precedence tests
# ==============================================================================

def test_transfer_beats_stated_open_problem():
    """Priority rule 1 beats rule 7: transfer_gap wins when both source_domain+target_hook
    and statement+source_ref are present."""
    gap_type, reason_code = classify_gap({
        "source_domain": "nlp",
        "target_hook": "biomedical text mining",
        "statement": "Future work should transfer NLP methods to bio.",
        "source_ref": "[[doe2023]]",
    })
    assert gap_type == "transfer_gap", "transfer_gap (rule 1) must beat stated_open_problem (rule 7)"


def test_assumption_beats_coverage():
    """Priority rule 2 beats rule 4: assumption_gap wins when both challenged_assumption
    and hole are present."""
    gap_type, _ = classify_gap({
        "challenged_assumption": "attention is all you need for medical seg",
        "hole": True,
    })
    assert gap_type == "assumption_gap", "assumption_gap (rule 2) must beat coverage_gap (rule 4)"


def test_methodological_beats_evidence():
    """Priority rule 3 beats rule 5: methodological_gap wins when locus+opportunity
    and under_evidenced are both present."""
    gap_type, _ = classify_gap({
        "locus": "data augmentation",
        "opportunity": "class-conditional augmentation",
        "under_evidenced": True,
    })
    assert gap_type == "methodological_gap", "methodological_gap (rule 3) must beat evidence_gap (rule 5)"


def test_transfer_beats_assumption():
    """Rule 1 beats rule 2: transfer wins over assumption when both signals present."""
    gap_type, _ = classify_gap({
        "source_domain": "cv",
        "target_hook": "nlp",
        "challenged_assumption": "vision features are not useful for text",
    })
    assert gap_type == "transfer_gap"


# ==============================================================================
# Default / edge cases
# ==============================================================================

def test_signal_with_no_matching_rule_raises_value_error():
    """A signal with no recognisable field raises ValueError (no silent default)."""
    with pytest.raises(ValueError):
        classify_gap({"irrelevant_field": "nothing useful"})


def test_empty_signal_raises_value_error():
    """An empty signal dict matches no rule."""
    with pytest.raises(ValueError):
        classify_gap({})


def test_statement_only_no_source_ref_raises_value_error():
    """statement without source_ref is not enough for stated_open_problem (rule 7 requires both)."""
    with pytest.raises(ValueError):
        classify_gap({"statement": "Future work needed."})


def test_source_ref_only_no_statement_raises_value_error():
    """source_ref without statement is not enough for stated_open_problem."""
    with pytest.raises(ValueError):
        classify_gap({"source_ref": "[[ref]]"})


def test_non_dict_input_raises_value_error():
    """Non-dict input raises ValueError."""
    with pytest.raises(ValueError):
        classify_gap("not a dict")  # type: ignore[arg-type]


# ==============================================================================
# build_classification: payload-level tests
# ==============================================================================

def _make_signals() -> list:
    return [
        {
            "gap_id": "GAP-001",
            "statement": "Explore few-shot segmentation.",
            "source_ref": "[[ref1]]",
            "evidence_ref": ["[[ref1]]"],
        },
        {
            "gap_id": "GAP-002",
            "source_domain": "nlp",
            "target_hook": "radiology reports",
            "evidence_ref": ["[[ref2]]"],
        },
        {
            "gap_id": "GAP-003",
            "locus": "evaluation protocol",
            "opportunity": "blind hold-out test",
            "evidence_ref": ["[[ref3]]"],
        },
    ]


def test_build_classification_returns_correct_types():
    signals = _make_signals()
    result = build_classification(signals)
    gaps = result["gaps"]
    assert len(gaps) == 3
    assert gaps[0]["gap_type"] == "stated_open_problem"
    assert gaps[0]["reason_code"] == "FW_STATED"
    assert gaps[1]["gap_type"] == "transfer_gap"
    assert gaps[1]["reason_code"] == "XFER_BIND"
    assert gaps[2]["gap_type"] == "methodological_gap"
    assert gaps[2]["reason_code"] == "WEAK_LOCUS"


def test_build_classification_preserves_order():
    """Output order must match input order (stable ordering)."""
    signals = _make_signals()
    result = build_classification(signals)
    gap_ids = [g["gap_id"] for g in result["gaps"]]
    assert gap_ids == ["GAP-001", "GAP-002", "GAP-003"]


def test_build_classification_skips_unidentified_noise():
    """A signal with NO gap_id that matches no rule is un-identified noise — skipped silently."""
    signals = [
        {"gap_id": "GAP-GOOD", "statement": "Open problem.", "source_ref": "[[r]]", "evidence_ref": ["[[r]]"]},
        {"irrelevant": "nothing"},  # no gap_id -> noise -> skipped
    ]
    result = build_classification(signals)
    gap_ids = [g["gap_id"] for g in result["gaps"]]
    assert gap_ids == ["GAP-GOOD"]


def test_build_classification_raises_on_identified_unclassifiable():
    """ROUND-2 FIX (silent-drop finding): an IDENTIFIED gap (one carrying a gap_id) that matches no
    rule must RAISE — a real, identified gap must NEVER silently vanish (the dual of slop in the M3
    risk model). Only un-identified noise (no gap_id) is skipped."""
    signals = [
        {"gap_id": "GAP-GOOD", "statement": "Open problem.", "source_ref": "[[r]]", "evidence_ref": ["[[r]]"]},
        {"gap_id": "GAP-BAD", "irrelevant": "nothing"},  # has gap_id but no rule -> must raise
    ]
    with pytest.raises(ValueError, match="GAP-BAD"):
        build_classification(signals)


def test_build_classification_carries_derived_from():
    """build_classification carries the signal's derived_from onto the gap so the novelty-scorer can
    aggregate provenance from gap_classification ALONE (no runtime re-injection)."""
    signals = [{
        "gap_id": "GAP-1", "statement": "Open problem.", "source_ref": "[[r]]",
        "evidence_ref": ["[[r]]"], "derived_from": ["future_work", "white_space_present"],
    }]
    result = build_classification(signals)
    assert result["gaps"][0]["derived_from"] == ["future_work", "white_space_present"]


def test_build_classification_validates_against_schema():
    """The payload from build_classification must validate against gap_classification.schema.json."""
    signals = _make_signals()
    result = build_classification(signals)
    errors = validate_against("gap_classification.schema.json", result)
    assert errors == [], f"build_classification output failed schema validation: {errors}"


def test_build_classification_empty_input():
    """An empty signal list produces an empty gaps array (valid schema)."""
    result = build_classification([])
    assert result == {"gaps": []}
    errors = validate_against("gap_classification.schema.json", result)
    assert errors == []


def test_classify_gap_deterministic_same_input_same_output():
    """Same signal dict always produces the same result (determinism)."""
    signal = {"locus": "loss", "opportunity": "dice-topology", "evidence_ref": ["ref"]}
    r1 = classify_gap(signal)
    r2 = classify_gap(signal)
    assert r1 == r2


def test_build_classification_deterministic_stable_order():
    """build_classification with the same signals list always produces the same gap order."""
    signals = _make_signals()
    r1 = build_classification(signals)
    r2 = build_classification(signals)
    assert r1 == r2
