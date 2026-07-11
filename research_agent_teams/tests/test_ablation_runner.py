"""Tests for the ablation-runner deterministic core."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.ablation_runner import build_run_record
from research_agent_teams.tools.validate_artifact import validate_against


# ---------------------------------------------------------------------------
# Fixtures / shared helpers
# ---------------------------------------------------------------------------

def _base(status: str = "planned", condition_id: str = "cond-baseline",
          config_hash: str = "abc123", **kwargs) -> dict:
    """Return a minimal valid run_record payload."""
    return build_run_record(
        condition_id=condition_id,
        config_hash=config_hash,
        status=status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# (a) "planned" record — schema-valid, status == "planned"
# ---------------------------------------------------------------------------

def test_planned_record_is_schema_valid():
    payload = _base(status="planned")
    errors = validate_against("run_record.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"
    assert payload["status"] == "planned"


# ---------------------------------------------------------------------------
# (b) "provisional" record carrying metrics — schema-valid
# ---------------------------------------------------------------------------

def test_provisional_record_with_metrics_is_schema_valid():
    payload = build_run_record(
        condition_id="cond-lora-r16",
        config_hash="deadbeef",
        status="provisional",
        metrics={"dice": 0.87, "hd95": 4.2},
        data_hash="data-sha-99",
        git_sha="f00bar",
        seed=42,
    )
    errors = validate_against("run_record.schema.json", payload)
    assert errors == [], f"Schema violations: {errors}"
    assert payload["status"] == "provisional"
    assert payload["metrics"]["dice"] == pytest.approx(0.87)


# ---------------------------------------------------------------------------
# (c) Ceiling enforcement — "frozen" (and other forbidden statuses) raise
# ---------------------------------------------------------------------------

def test_frozen_status_raises_value_error():
    with pytest.raises(ValueError, match="ceiling violated"):
        build_run_record(
            condition_id="cond-x",
            config_hash="aaa",
            status="frozen",
        )


def test_approved_status_raises_value_error():
    with pytest.raises(ValueError, match="ceiling violated"):
        build_run_record(
            condition_id="cond-x",
            config_hash="aaa",
            status="approved",
        )


# ---------------------------------------------------------------------------
# (d) Provenance carries config_hash; metrics default to {}
# ---------------------------------------------------------------------------

def test_provenance_carries_config_hash():
    payload = _base(config_hash="sha256-test-hash")
    assert payload["provenance"]["config_hash"] == "sha256-test-hash"


def test_metrics_default_to_empty_dict():
    payload = _base()
    assert payload["metrics"] == {}


def test_notes_omitted_when_none():
    payload = _base()
    assert "notes" not in payload


def test_notes_present_when_given():
    payload = _base(notes="ran on 4×A100, wall-time 3h")
    assert payload["notes"] == "ran on 4×A100, wall-time 3h"
    errors = validate_against("run_record.schema.json", payload)
    assert errors == []


def test_optional_provenance_fields_are_none_by_default():
    payload = _base()
    prov = payload["provenance"]
    assert prov["data_hash"] is None
    assert prov["git_sha"] is None
    assert prov["seed"] is None
