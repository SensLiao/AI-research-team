"""CLUSTER C wiring test — gap-hunting breadth producers → classify_gap → novelty_aggregate.

This is the core guarantee for Cluster C: the four producer payloads feed directly into
the existing classify_gap.build_classification() + novelty_aggregate.aggregate_novelty()
pipeline with NO edits to those tools.

For EACH of the 4 producers we prove:
  1. A well-formed payload validates against its schema (validate_against == []).
  2. Its items feed into build_classification() and produce the CORRECT (gap_type, reason_code).
  3. Those classified gaps feed into aggregate_novelty() and:
       - EVERY gap gets a score (none dropped — novelty-paradox guard).
       - Each score entry validates against novelty_score.schema.json.
  4. A crafted item with empty evidence_ref is schema-REJECTED (anti-slop).

Producer → expected classify_gap output:
  weakness item  (locus + opportunity)         → methodological_gap / WEAK_LOCUS   (rule 3)
  white_space region (hole=True)               → coverage_gap       / WHITESPACE    (rule 4)
  transfer candidate (source_domain+target_hook)→ transfer_gap      / XFER_BIND     (rule 1)
  contrarian angle (challenged_assumption)     → assumption_gap     / ASSUMPTION    (rule 2)

Note: build_classification is called here as an importer (allowed; importing ≠ editing).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.classify_gap import build_classification
from research_agent_teams.tools.novelty_aggregate import aggregate_novelty
from research_agent_teams.tools.validate_artifact import validate_against


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_novelty_all_scored(gaps: list, scored: dict) -> None:
    """Assert every gap in the classification has a score and that score validates."""
    scores = scored["scores"]
    assert len(scores) == len(gaps), (
        f"Expected {len(gaps)} score(s) from aggregate_novelty, got {len(scores)}. "
        f"Novelty-paradox guard: NONE may be dropped."
    )
    errors = validate_against("novelty_score.schema.json", scored)
    assert errors == [], f"novelty_score payload failed validation: {errors}"


# ==============================================================================
# Producer 1: weakness-spotter  →  weakness_report
# ==============================================================================

class TestWeaknessSpotterWiring:
    SCHEMA = "weakness_report.schema.json"

    def _good_payload(self) -> dict:
        return {
            "weaknesses": [
                {
                    "gap_id": "WK-001",
                    "locus": "loss function design in UNet-family models",
                    "opportunity": "topology-aware loss for tubular structure segmentation",
                    "evidence_ref": ["[[chen2023]]"],
                },
                {
                    "gap_id": "WK-002",
                    "locus": "data augmentation strategy for class-imbalanced datasets",
                    "opportunity": "class-conditional augmentation pipeline",
                    "evidence_ref": ["[[doe2024]]"],
                },
            ]
        }

    def test_schema_validates(self):
        """A well-formed weakness_report validates."""
        errors = validate_against(self.SCHEMA, self._good_payload())
        assert errors == [], f"weakness_report validation failed: {errors}"

    def test_classify_gap_gives_methodological(self):
        """weakness items (locus + opportunity) → methodological_gap / WEAK_LOCUS."""
        payload = self._good_payload()
        gaps_out = build_classification(payload["weaknesses"])["gaps"]
        assert len(gaps_out) == 2
        for gap in gaps_out:
            assert gap["gap_type"] == "methodological_gap", (
                f"Expected methodological_gap, got {gap['gap_type']!r} for gap_id={gap['gap_id']!r}"
            )
            assert gap["reason_code"] == "WEAK_LOCUS"

    def test_novelty_aggregate_scores_all(self):
        """Every classified weakness gap receives a novelty score (none dropped)."""
        payload = self._good_payload()
        classified = build_classification(payload["weaknesses"])
        scored = aggregate_novelty(classified["gaps"])
        _check_novelty_all_scored(classified["gaps"], scored)

    def test_novelty_score_validates_against_schema(self):
        """The novelty payload from weakness gaps validates against novelty_score.schema.json."""
        payload = self._good_payload()
        classified = build_classification(payload["weaknesses"])
        scored = aggregate_novelty(classified["gaps"])
        errors = validate_against("novelty_score.schema.json", scored)
        assert errors == [], f"novelty_score schema errors: {errors}"

    def test_empty_evidence_ref_schema_rejected(self):
        """Anti-slop: a weakness item with empty evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["weaknesses"][0]["evidence_ref"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for empty evidence_ref but got none"

    def test_whitespace_evidence_ref_schema_rejected(self):
        """Anti-slop: a weakness item with whitespace-only evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["weaknesses"][0]["evidence_ref"] = ["   "]
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for whitespace evidence_ref but got none"


# ==============================================================================
# Producer 2: white-space-mapper  →  white_space_map
# ==============================================================================

class TestWhiteSpaceMapperWiring:
    SCHEMA = "white_space_map.schema.json"

    def _good_payload(self) -> dict:
        return {
            "regions": [
                {
                    "gap_id": "WS-001",
                    "region": "3D-aware multi-scale feature fusion for small tubular structures in CT",
                    "hole": True,
                    "evidence_ref": ["[[landscape-map-001]]"],
                },
                {
                    "gap_id": "WS-002",
                    "region": "few-shot organ segmentation under extreme label scarcity (<10 samples)",
                    "hole": True,
                    "evidence_ref": ["[[landscape-map-001]]", "[[chen2023]]"],
                },
            ]
        }

    def test_schema_validates(self):
        """A well-formed white_space_map validates."""
        errors = validate_against(self.SCHEMA, self._good_payload())
        assert errors == [], f"white_space_map validation failed: {errors}"

    def test_classify_gap_gives_coverage(self):
        """white_space regions (hole=True) → coverage_gap / WHITESPACE."""
        payload = self._good_payload()
        gaps_out = build_classification(payload["regions"])["gaps"]
        assert len(gaps_out) == 2
        for gap in gaps_out:
            assert gap["gap_type"] == "coverage_gap", (
                f"Expected coverage_gap, got {gap['gap_type']!r} for gap_id={gap['gap_id']!r}"
            )
            assert gap["reason_code"] == "WHITESPACE"

    def test_novelty_aggregate_scores_all(self):
        """Every classified coverage gap receives a novelty score (none dropped)."""
        payload = self._good_payload()
        classified = build_classification(payload["regions"])
        scored = aggregate_novelty(classified["gaps"])
        _check_novelty_all_scored(classified["gaps"], scored)

    def test_novelty_score_validates_against_schema(self):
        """The novelty payload from white-space gaps validates against novelty_score.schema.json."""
        payload = self._good_payload()
        classified = build_classification(payload["regions"])
        scored = aggregate_novelty(classified["gaps"])
        errors = validate_against("novelty_score.schema.json", scored)
        assert errors == [], f"novelty_score schema errors: {errors}"

    def test_empty_evidence_ref_schema_rejected(self):
        """Anti-slop: a region item with empty evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["regions"][0]["evidence_ref"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for empty evidence_ref but got none"

    def test_whitespace_evidence_ref_schema_rejected(self):
        """Anti-slop: a region item with whitespace-only evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["regions"][0]["evidence_ref"] = [" "]
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for whitespace evidence_ref but got none"

    def test_hole_false_does_not_trigger_coverage_gap(self):
        """A region with hole=False does NOT match coverage_gap rule 4
        (confirms the producer-contract: only emit hole:True regions)."""
        item = {
            "gap_id": "WS-COVERED",
            "hole": False,
            "evidence_ref": ["[[ref]]"],
        }
        # hole=False means no coverage_gap rule fires; no other rule fires either → ValueError
        with pytest.raises(ValueError):
            build_classification([item])


# ==============================================================================
# Producer 3: cross-domain-transfer-scout  →  transfer_candidates
# ==============================================================================

class TestTransferScoutWiring:
    SCHEMA = "transfer_candidates.schema.json"

    def _good_payload(self) -> dict:
        return {
            "candidates": [
                {
                    "gap_id": "XF-001",
                    "source_domain": "natural language processing",
                    "target_hook": "attention-based feature selection for radiology reports",
                    "evidence_ref": ["[[vaswani2017]]"],
                },
                {
                    "gap_id": "XF-002",
                    "source_domain": "graph neural networks",
                    "target_hook": "anatomical topology constraints for organ segmentation",
                    "evidence_ref": ["[[xu2022]]"],
                },
            ]
        }

    def test_schema_validates(self):
        """A well-formed transfer_candidates validates."""
        errors = validate_against(self.SCHEMA, self._good_payload())
        assert errors == [], f"transfer_candidates validation failed: {errors}"

    def test_classify_gap_gives_transfer(self):
        """transfer candidates (source_domain + target_hook) → transfer_gap / XFER_BIND (rule 1)."""
        payload = self._good_payload()
        gaps_out = build_classification(payload["candidates"])["gaps"]
        assert len(gaps_out) == 2
        for gap in gaps_out:
            assert gap["gap_type"] == "transfer_gap", (
                f"Expected transfer_gap, got {gap['gap_type']!r} for gap_id={gap['gap_id']!r}"
            )
            assert gap["reason_code"] == "XFER_BIND"

    def test_novelty_aggregate_scores_all(self):
        """Every classified transfer gap receives a novelty score (none dropped)."""
        payload = self._good_payload()
        classified = build_classification(payload["candidates"])
        scored = aggregate_novelty(classified["gaps"])
        _check_novelty_all_scored(classified["gaps"], scored)

    def test_novelty_score_validates_against_schema(self):
        """The novelty payload from transfer gaps validates against novelty_score.schema.json."""
        payload = self._good_payload()
        classified = build_classification(payload["candidates"])
        scored = aggregate_novelty(classified["gaps"])
        errors = validate_against("novelty_score.schema.json", scored)
        assert errors == [], f"novelty_score schema errors: {errors}"

    def test_empty_evidence_ref_schema_rejected(self):
        """Anti-slop: a candidate item with empty evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["candidates"][0]["evidence_ref"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for empty evidence_ref but got none"

    def test_whitespace_evidence_ref_schema_rejected(self):
        """Anti-slop: a candidate item with whitespace-only evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["candidates"][0]["evidence_ref"] = ["  "]
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for whitespace evidence_ref but got none"

    def test_transfer_rule_takes_priority_over_assumption(self):
        """Rule 1 (transfer) beats rule 2 (assumption) when both source_domain+target_hook
        and challenged_assumption are present — confirms priority ordering."""
        item = {
            "gap_id": "XF-PRIO",
            "source_domain": "signal processing",
            "target_hook": "frequency-domain MRI features",
            "challenged_assumption": "spatial convolutions are sufficient for MRI",
            "evidence_ref": ["[[ref]]"],
        }
        gaps_out = build_classification([item])["gaps"]
        assert gaps_out[0]["gap_type"] == "transfer_gap"
        assert gaps_out[0]["reason_code"] == "XFER_BIND"


# ==============================================================================
# Producer 4: contrarian-angle-generator  →  contrarian_angles
# ==============================================================================

class TestContrarianAngleWiring:
    SCHEMA = "contrarian_angles.schema.json"

    def _good_payload(self) -> dict:
        return {
            "angles": [
                {
                    "gap_id": "CA-001",
                    "challenged_assumption": (
                        "Pre-training on ImageNet always improves performance "
                        "on medical imaging tasks."
                    ),
                    "evidence_ref": ["[[raghu2019]]"],
                },
                {
                    "gap_id": "CA-002",
                    "challenged_assumption": (
                        "Larger model capacity monotonically improves "
                        "segmentation on small datasets."
                    ),
                    "evidence_ref": ["[[chen2023]]"],
                },
            ]
        }

    def test_schema_validates(self):
        """A well-formed contrarian_angles validates."""
        errors = validate_against(self.SCHEMA, self._good_payload())
        assert errors == [], f"contrarian_angles validation failed: {errors}"

    def test_classify_gap_gives_assumption(self):
        """contrarian angles (challenged_assumption) → assumption_gap / ASSUMPTION (rule 2)."""
        payload = self._good_payload()
        gaps_out = build_classification(payload["angles"])["gaps"]
        assert len(gaps_out) == 2
        for gap in gaps_out:
            assert gap["gap_type"] == "assumption_gap", (
                f"Expected assumption_gap, got {gap['gap_type']!r} for gap_id={gap['gap_id']!r}"
            )
            assert gap["reason_code"] == "ASSUMPTION"

    def test_novelty_aggregate_scores_all(self):
        """Every classified assumption gap receives a novelty score (none dropped)."""
        payload = self._good_payload()
        classified = build_classification(payload["angles"])
        scored = aggregate_novelty(classified["gaps"])
        _check_novelty_all_scored(classified["gaps"], scored)

    def test_novelty_score_validates_against_schema(self):
        """The novelty payload from contrarian gaps validates against novelty_score.schema.json."""
        payload = self._good_payload()
        classified = build_classification(payload["angles"])
        scored = aggregate_novelty(classified["gaps"])
        errors = validate_against("novelty_score.schema.json", scored)
        assert errors == [], f"novelty_score schema errors: {errors}"

    def test_empty_evidence_ref_schema_rejected(self):
        """Anti-slop: an angle item with empty evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["angles"][0]["evidence_ref"] = []
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for empty evidence_ref but got none"

    def test_whitespace_evidence_ref_schema_rejected(self):
        """Anti-slop: an angle item with whitespace-only evidence_ref is schema-REJECTED."""
        bad = self._good_payload()
        bad["angles"][0]["evidence_ref"] = ["\t"]
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], "Expected schema rejection for whitespace evidence_ref but got none"

    def test_assumption_rule_beats_coverage(self):
        """Rule 2 (assumption) beats rule 4 (coverage) when both challenged_assumption
        and hole=True are present — confirms priority ordering."""
        item = {
            "gap_id": "CA-PRIO",
            "challenged_assumption": "attention is all you need for medical segmentation",
            "hole": True,
            "evidence_ref": ["[[ref]]"],
        }
        gaps_out = build_classification([item])["gaps"]
        assert gaps_out[0]["gap_type"] == "assumption_gap"
        assert gaps_out[0]["reason_code"] == "ASSUMPTION"


# ==============================================================================
# Cross-producer: all four producers together in a single pipeline call
# ==============================================================================

class TestAllFourProducersTogether:
    """Validates the full breadth pipeline: collect items from all 4 producers,
    feed them into build_classification, then into aggregate_novelty, and assert
    that EVERY gap is scored (none dropped) and the schema validates."""

    def test_all_four_producers_pipeline(self):
        """All four producer item types flow through build_classification → aggregate_novelty
        without any drops. This is the breadth guarantee."""
        weakness_item = {
            "gap_id": "WK-ALL",
            "locus": "evaluation protocol",
            "opportunity": "blind hold-out test set",
            "evidence_ref": ["[[ref-wk]]"],
        }
        whitespace_item = {
            "gap_id": "WS-ALL",
            "hole": True,
            "evidence_ref": ["[[ref-ws]]"],
        }
        transfer_item = {
            "gap_id": "XF-ALL",
            "source_domain": "signal processing",
            "target_hook": "frequency-domain features for MRI",
            "evidence_ref": ["[[ref-xf]]"],
        }
        contrarian_item = {
            "gap_id": "CA-ALL",
            "challenged_assumption": "dice loss is always sufficient",
            "evidence_ref": ["[[ref-ca]]"],
        }

        all_items = [weakness_item, whitespace_item, transfer_item, contrarian_item]
        classified = build_classification(all_items)
        gaps = classified["gaps"]

        # All 4 must survive (none dropped)
        assert len(gaps) == 4, f"Expected 4 classified gaps, got {len(gaps)}"

        # Check correct types in order
        assert gaps[0]["gap_type"] == "methodological_gap"
        assert gaps[0]["reason_code"] == "WEAK_LOCUS"
        # whitespace: hole=True → coverage_gap, but contrarian_item lacks hole so check order
        # note: transfer beats assumption, and assumption beats coverage → whitespace is rule 4
        assert gaps[1]["gap_type"] == "coverage_gap"
        assert gaps[1]["reason_code"] == "WHITESPACE"
        assert gaps[2]["gap_type"] == "transfer_gap"
        assert gaps[2]["reason_code"] == "XFER_BIND"
        assert gaps[3]["gap_type"] == "assumption_gap"
        assert gaps[3]["reason_code"] == "ASSUMPTION"

        # Novelty aggregate: all 4 scored
        scored = aggregate_novelty(gaps)
        assert len(scored["scores"]) == 4, (
            "aggregate_novelty must score EVERY gap (none dropped — novelty-paradox guard)"
        )

        # Schema validates
        errors = validate_against("novelty_score.schema.json", scored)
        assert errors == [], f"Combined novelty_score validation failed: {errors}"
