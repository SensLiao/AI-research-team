"""Tests for validate_split.py — deterministic validator for split_manifest artifacts.

Verifies:
- Valid manifests with allowed split units pass without raising.
- Forbidden split_unit (slice, patch per cv-medical profile) raises ValueError.
- Structural violations (missing leakage_declaration, too few splits, etc.) raise ValueError.
- Proven against the REAL cv-medical-segmentation.profile.yaml (no dead-gate risk).
"""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.tools.validate_artifact import PROFILE_DIR
from research_agent_teams.tools.validate_split import check_split_unit, validate_split


# ---- helpers ------------------------------------------------------------------

def _manifest(split_unit: str = "patient", leakage: str = "patient_id_disjoint") -> dict:
    return {
        "split_unit": split_unit,
        "splits": [
            {"name": "train", "fraction": 0.7},
            {"name": "val", "fraction": 0.1},
            {"name": "test", "fraction": 0.2},
        ],
        "leakage_declaration": leakage,
    }


_CV_PROFILE = {
    "profile_id": "cv-medical-segmentation",
    "split_policy": {
        "default_split_unit": "patient",
        "allowed_split_units": ["patient", "case"],
        "forbidden_split_units": ["slice", "patch", "image"],
    },
    "metrics": [{"name": "Dice", "higher_is_better": True}],
    "hard_invariants": ["all splits must be patient-level or case-level"],
    "display_name": "Test",
}


# ---- happy-path tests ---------------------------------------------------------

def test_allowed_split_unit_passes():
    """patient is an allowed split_unit — should not raise."""
    validate_split(_manifest("patient"), _CV_PROFILE)


def test_case_split_unit_passes():
    """case is also an allowed split_unit — should not raise."""
    validate_split(_manifest("case"), _CV_PROFILE)


def test_no_profile_passes_any_unit():
    """Without a profile, any split_unit is accepted (no policy to enforce)."""
    validate_split(_manifest("token"))  # no profile argument


def test_two_splits_is_minimum():
    """Exactly 2 splits (train + test) is the minimum; should not raise."""
    m = _manifest()
    m["splits"] = [
        {"name": "train", "fraction": 0.8},
        {"name": "test", "fraction": 0.2},
    ]
    validate_split(m, _CV_PROFILE)


# ---- forbidden split_unit tests -----------------------------------------------

def test_slice_split_unit_raises():
    """slice is in forbidden_split_units — must raise ValueError."""
    with pytest.raises(ValueError, match="forbidden"):
        validate_split(_manifest("slice"), _CV_PROFILE)


def test_patch_split_unit_raises():
    """patch is in forbidden_split_units — must raise ValueError."""
    with pytest.raises(ValueError, match="forbidden"):
        validate_split(_manifest("patch"), _CV_PROFILE)


def test_image_split_unit_raises():
    """image is in forbidden_split_units — must raise ValueError."""
    with pytest.raises(ValueError, match="forbidden"):
        validate_split(_manifest("image"), _CV_PROFILE)


def test_check_split_unit_alone_raises_for_forbidden():
    """check_split_unit (lower-level) also raises for forbidden units."""
    with pytest.raises(ValueError, match="forbidden"):
        check_split_unit({"split_unit": "slice"}, _CV_PROFILE)


# ---- structural violation tests -----------------------------------------------

def test_missing_split_unit_raises():
    """A manifest without split_unit must raise ValueError."""
    m = _manifest()
    del m["split_unit"]
    with pytest.raises(ValueError, match="split_unit"):
        validate_split(m, _CV_PROFILE)


def test_empty_split_unit_raises():
    """An empty string split_unit must raise ValueError."""
    m = _manifest()
    m["split_unit"] = ""
    with pytest.raises(ValueError, match="split_unit"):
        validate_split(m, _CV_PROFILE)


def test_missing_leakage_declaration_raises():
    """A manifest without leakage_declaration must raise ValueError."""
    m = _manifest()
    del m["leakage_declaration"]
    with pytest.raises(ValueError, match="leakage_declaration"):
        validate_split(m, _CV_PROFILE)


def test_empty_leakage_declaration_raises():
    """An empty leakage_declaration must raise ValueError."""
    m = _manifest()
    m["leakage_declaration"] = "   "
    with pytest.raises(ValueError, match="leakage_declaration"):
        validate_split(m, _CV_PROFILE)


def test_fewer_than_two_splits_raises():
    """Only 1 split is below the minimum of 2 — must raise ValueError."""
    m = _manifest()
    m["splits"] = [{"name": "train", "fraction": 1.0}]
    with pytest.raises(ValueError, match="splits"):
        validate_split(m, _CV_PROFILE)


def test_split_fraction_out_of_range_raises():
    """A fraction > 1.0 is invalid — must raise ValueError."""
    m = _manifest()
    m["splits"][0]["fraction"] = 1.5
    with pytest.raises(ValueError, match="fraction"):
        validate_split(m, _CV_PROFILE)


def test_zero_fraction_raises():
    """fraction = 0 is not valid (exclusive of 0) — must raise ValueError."""
    m = _manifest()
    m["splits"][0]["fraction"] = 0.0
    with pytest.raises(ValueError, match="fraction"):
        validate_split(m, _CV_PROFILE)


# ---- real-profile proof (no dead gate) ----------------------------------------

def test_real_shipped_profile_blocks_slice():
    """CRITICAL: load the real cv-medical-segmentation.profile.yaml and prove that
    a slice-based split raises ValueError. This confirms the gate actually fires on
    the production profile shape, not just on a toy inline dict."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # slice is in the profile's forbidden_split_units
    with pytest.raises(ValueError, match="forbidden"):
        validate_split(_manifest("slice"), profile)


def test_real_shipped_profile_blocks_patch():
    """patch is also in the real profile's forbidden_split_units."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    with pytest.raises(ValueError, match="forbidden"):
        validate_split(_manifest("patch"), profile)


def test_real_shipped_profile_allows_patient():
    """patient is in the real profile's allowed_split_units — must NOT raise."""
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    validate_split(_manifest("patient"), profile)  # should not raise
