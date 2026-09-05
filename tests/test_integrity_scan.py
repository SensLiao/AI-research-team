"""Tests for the integrity_scan deterministic FLAGGER (integrity-refusal-recommender).

Proves that:
  - a claim with a number + no evidence_ref            -> flagged unsupported_number (high)
  - a result-asserting claim with no evidence at all    -> flagged missing_evidence_refusal (medium)
  - a properly-cited claim (number + evidence_ref)      -> NO flag
  - a non-numeric, non-result claim with no evidence    -> NO flag
  - severity -> recommendation mapping:
        any high -> RECOMMEND_HALT ; only medium/low -> CAUTION ; no flags -> PROCEED
  - determinism (same input -> same output)
  - a sample integrity_recommendation VALIDATES against the schema via jsonschema directly
    (NOT via PAYLOAD_SCHEMAS registration — the schema is loaded straight from disk)
  - the recommendation is RECOMMENDATION-ONLY: decision_authority is always "director-human-gate"

Schema is loaded directly from research_agent_teams/schemas/ with Draft202012Validator — this tool
does not rely on validate_artifact / PAYLOAD_SCHEMAS registration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.integrity_scan import (
    CAUTION,
    DECISION_AUTHORITY,
    PROCEED,
    RECOMMEND_HALT,
    build_recommendation,
    recommend,
    scan_unsupported_numbers,
)

# Load the schema straight from disk (no PAYLOAD_SCHEMAS registration dependency).
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas" / "integrity_recommendation.schema.json"
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _schema_errors(payload: dict) -> list:
    """Return a sorted list of validation error messages for a payload (empty == valid)."""
    return sorted(e.message for e in _VALIDATOR.iter_errors(payload))


# ==============================================================================
# scan_unsupported_numbers — core detection
# ==============================================================================

def test_number_without_evidence_is_flagged_unsupported():
    """A claim that states a number but has no evidence_ref -> unsupported_number / high."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C1", "text": "Our method reaches 0.87 Dice on the test set."},
    ])
    assert len(flags) == 1
    assert flags[0]["kind"] == "unsupported_number"
    assert flags[0]["locus"] == "C1"
    assert flags[0]["severity"] == "high"
    assert flags[0]["detail"].strip()  # anti-slop: detail is non-blank


def test_percentage_number_without_evidence_is_flagged():
    """A percentage counts as a number (87%) -> unsupported_number when uncited."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C-PCT", "text": "Accuracy improved by 12% over the baseline."},
    ])
    assert len(flags) == 1
    assert flags[0]["kind"] == "unsupported_number"


def test_properly_cited_numeric_claim_is_not_flagged():
    """A numeric claim WITH a non-blank evidence_ref -> NO flag (citation gates own ref quality)."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C2", "text": "Our method reaches 0.87 Dice.", "evidence_ref": ["[[ours2024]]"]},
    ])
    assert flags == []


def test_evidence_ref_as_string_is_accepted():
    """evidence_ref given as a single non-blank string also counts as cited -> NO flag."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C2b", "text": "We observe 3.2x speedup.", "evidence_ref": "[[bench]]"},
    ])
    assert flags == []


def test_blank_evidence_ref_does_not_count_as_evidence():
    """A whitespace-only / empty evidence_ref is NOT a citation -> numeric claim still flagged."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C-BLANK", "text": "We get 99.9% accuracy.", "evidence_ref": ["   "]},
    ])
    assert len(flags) == 1
    assert flags[0]["kind"] == "unsupported_number"


def test_result_assertion_without_evidence_is_missing_evidence_refusal():
    """A result-asserting claim (no number) with no evidence -> missing_evidence_refusal / medium."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C3", "text": "Our method outperforms all baselines.", "asserts_result": True},
    ])
    assert len(flags) == 1
    assert flags[0]["kind"] == "missing_evidence_refusal"
    assert flags[0]["severity"] == "medium"


def test_non_numeric_non_result_claim_with_no_evidence_is_not_flagged():
    """A plain descriptive claim (no number, not marked asserts_result) -> NO flag."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C4", "text": "We use a U-Net backbone for segmentation."},
    ])
    assert flags == []


def test_number_beats_result_assertion_when_both_present():
    """A claim that states a number AND is marked asserts_result -> the stronger unsupported_number."""
    flags = scan_unsupported_numbers([
        {"claim_id": "C5", "text": "Our method outperforms baselines by 5 points.", "asserts_result": True},
    ])
    assert len(flags) == 1
    assert flags[0]["kind"] == "unsupported_number"


def test_scan_preserves_input_order():
    """Flags come out in the same order as the input claims (stable)."""
    flags = scan_unsupported_numbers([
        {"claim_id": "A", "text": "We get 0.5 here."},
        {"claim_id": "B", "text": "We get 0.6 here."},
    ])
    assert [f["locus"] for f in flags] == ["A", "B"]


def test_scan_skips_non_dict_entries():
    """Non-dict entries in the claims list are skipped without error."""
    flags = scan_unsupported_numbers(["not a dict", {"claim_id": "C", "text": "0.7 score"}])  # type: ignore[list-item]
    assert len(flags) == 1
    assert flags[0]["locus"] == "C"


def test_scan_empty_input_yields_no_flags():
    """An empty claims list yields no flags."""
    assert scan_unsupported_numbers([]) == []


# ==============================================================================
# recommend — severity -> recommendation thresholds
# ==============================================================================

def test_recommend_no_flags_is_proceed():
    """No flags -> PROCEED."""
    assert recommend([]) == PROCEED


def test_recommend_only_low_is_caution():
    """Only low-severity flag(s) -> CAUTION (any flag warrants a human look)."""
    assert recommend([{"severity": "low"}]) == CAUTION


def test_recommend_any_medium_is_caution():
    """A medium-severity flag (no high) -> CAUTION."""
    assert recommend([{"severity": "low"}, {"severity": "medium"}]) == CAUTION


def test_recommend_any_high_is_recommend_halt():
    """Any high-severity flag -> RECOMMEND_HALT (strongest advisory signal)."""
    assert recommend([{"severity": "low"}, {"severity": "high"}]) == RECOMMEND_HALT


def test_recommend_unknown_severity_does_not_escalate():
    """An unrecognised severity is treated as lowest rank -> never escalates to RECOMMEND_HALT."""
    assert recommend([{"severity": "bogus"}]) == CAUTION
    assert recommend([{"severity": "bogus"}, {"severity": "medium"}]) == CAUTION


# ==============================================================================
# Determinism
# ==============================================================================

def test_scan_deterministic_same_input_same_output():
    """Same claims -> identical flags (no clock/random/network)."""
    claims = [{"claim_id": "C", "text": "0.91 Dice", "asserts_result": True}]
    assert scan_unsupported_numbers(claims) == scan_unsupported_numbers(claims)


def test_build_recommendation_deterministic():
    """build_recommendation is deterministic for the same input."""
    claims = [{"claim_id": "C1", "text": "We reach 0.88."}]
    r1 = build_recommendation("IR-1", claims, scanned_artifacts=["runs/x/claim_list.json"])
    r2 = build_recommendation("IR-1", claims, scanned_artifacts=["runs/x/claim_list.json"])
    assert r1 == r2


# ==============================================================================
# build_recommendation + schema validation (jsonschema directly)
# ==============================================================================

def test_build_recommendation_validates_against_schema():
    """A built recommendation with a real unsupported-number flag validates against the schema."""
    payload = build_recommendation(
        "IR-001",
        [{"claim_id": "C1", "text": "Our method reaches 0.87 Dice."}],
        scanned_artifacts=["runs/run-7/evidence/DISCOVER/claim_list.artifact.json"],
    )
    assert _schema_errors(payload) == [], f"schema validation failed: {_schema_errors(payload)}"
    assert payload["recommendation"] == RECOMMEND_HALT  # high-severity flag
    assert payload["decision_authority"] == DECISION_AUTHORITY


def test_clean_scan_validates_and_recommends_proceed():
    """A clean scan (well-cited claim) -> PROCEED, empty risk_flags, valid against schema."""
    payload = build_recommendation(
        "IR-002",
        [{"claim_id": "C1", "text": "0.87 Dice.", "evidence_ref": ["[[ours]]"]}],
    )
    assert payload["recommendation"] == PROCEED
    assert payload["risk_flags"] == []
    assert _schema_errors(payload) == []


def test_build_recommendation_carries_extra_flags():
    """Caller-supplied fabricated_data_smell / completion_pressure flags are carried through and
    drive the recommendation deterministically alongside claim-derived flags."""
    payload = build_recommendation(
        "IR-003",
        [{"claim_id": "C1", "text": "We use a transformer."}],  # no claim-derived flag
        extra_flags=[{
            "kind": "fabricated_data_smell",
            "locus": "runs/run-7/results/metrics.json",
            "severity": "high",
            "detail": "all 200 rows report identical 0.900 accuracy (too-clean synthetic tell)",
        }],
    )
    assert payload["recommendation"] == RECOMMEND_HALT
    kinds = {f["kind"] for f in payload["risk_flags"]}
    assert kinds == {"fabricated_data_smell"}
    assert _schema_errors(payload) == []


def test_completion_pressure_flag_validates():
    """A completion_pressure flag is a valid schema enum value and is carried through."""
    payload = build_recommendation(
        "IR-004",
        [],
        extra_flags=[{
            "kind": "completion_pressure",
            "locus": "C9",
            "severity": "medium",
            "detail": "claim asserts a finished result while the run_record is still 'planned'",
        }],
    )
    assert payload["recommendation"] == CAUTION
    assert _schema_errors(payload) == []


# ==============================================================================
# Recommendation-only invariant (no gate / authorization semantics)
# ==============================================================================

def test_decision_authority_is_always_director_human_gate():
    """Every built recommendation stamps decision_authority = director-human-gate (advisory-only)."""
    for claims in ([], [{"claim_id": "C", "text": "0.5"}], [{"claim_id": "C", "text": "ok", "asserts_result": True}]):
        payload = build_recommendation("IR-X", claims)
        assert payload["decision_authority"] == "director-human-gate"


def test_schema_rejects_wrong_decision_authority():
    """The schema pins decision_authority to the const — any other value is rejected (the artifact
    can never claim a different deciding authority than the director's human gate)."""
    payload = build_recommendation("IR-005", [{"claim_id": "C1", "text": "0.9"}])
    payload["decision_authority"] = "machine-self-authorized"  # tamper
    errors = _schema_errors(payload)
    assert errors, "schema must reject a decision_authority other than 'director-human-gate'"


def test_schema_rejects_unknown_risk_kind():
    """risk_flags[].kind is a closed enum — an out-of-enum kind (e.g. a 'block' verdict) is rejected,
    so the advisory artifact can never smuggle in gate/authorization semantics."""
    payload = build_recommendation("IR-006", [])
    payload["risk_flags"] = [{"kind": "BLOCK", "locus": "C1", "severity": "high", "detail": "x"}]
    assert _schema_errors(payload), "schema must reject an unknown risk_flags[].kind"


def test_schema_rejects_additional_properties():
    """additionalProperties:false — an injected enforcement field is rejected."""
    payload = build_recommendation("IR-007", [])
    payload["blocks_gate"] = True  # not in schema
    assert _schema_errors(payload), "schema must reject additional properties"
