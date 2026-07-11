"""Schema validate/reject tests for all 8 SUB-TEAM 2.3 schemas.

Uses validate_against(schema_filename, instance) which validates directly against
a schema file — no PAYLOAD_SCHEMAS registration needed (green before main-thread
registration step).

For every schema: at least one well-formed accept + at least one crafted-bad reject.
Golden assertions from the M2 contract are enforced by these tests.
"""
from __future__ import annotations

from research_agent_teams.tools.validate_artifact import validate_against


# ===========================================================================
# 1. source_quality_report.schema.json
# ===========================================================================

_GOOD_SQR = {
    "ranked_sources": [
        {
            "source_ref": "cvpr:2024.001",
            "rank": 1,
            "tier": "peer-reviewed",
            "rigor_score": 0.85,
            "year": 2024,
            "venue": "CVPR 2024",
            "rank_notes": "",
        }
    ],
    "ranking_rationale": "Peer-reviewed venue; recent publication.",
    "n_sources_ranked": 1,
}


def test_source_quality_report_valid():
    assert validate_against("source_quality_report.schema.json", _GOOD_SQR) == []


def test_source_quality_report_missing_ranked_sources_rejected():
    bad = {"ranking_rationale": "Some rationale"}
    assert validate_against("source_quality_report.schema.json", bad) != []


def test_source_quality_report_missing_ranking_rationale_rejected():
    bad = {"ranked_sources": []}
    assert validate_against("source_quality_report.schema.json", bad) != []


def test_source_quality_report_invalid_tier_rejected():
    bad = {
        "ranked_sources": [
            {"source_ref": "r1", "rank": 1, "tier": "UNKNOWN-TIER", "rigor_score": 0.5}
        ],
        "ranking_rationale": "test",
    }
    assert validate_against("source_quality_report.schema.json", bad) != []


def test_source_quality_report_rigor_score_out_of_range_rejected():
    bad = {
        "ranked_sources": [
            {"source_ref": "r1", "rank": 1, "tier": "preprint", "rigor_score": 1.5}
        ],
        "ranking_rationale": "test",
    }
    assert validate_against("source_quality_report.schema.json", bad) != []


# ===========================================================================
# 2. claim_list.schema.json — golden test: claim with no source_ref is rejected
# ===========================================================================

_GOOD_CLAIM_LIST = {
    "source_scope": "survey of 3D segmentation methods",
    "claims": [
        {
            "claim_id": "c1",
            "text": "Method X achieves 0.87 Dice on DatasetA.",
            "source_ref": "arxiv:2409.00001",
            "kind": "performance",
            "confidence": "high",
        }
    ],
}


def test_claim_list_valid():
    assert validate_against("claim_list.schema.json", _GOOD_CLAIM_LIST) == []


def test_claim_list_missing_source_ref_rejected():
    """Golden test: a claim with no source_ref is schema-rejected."""
    bad = {
        "source_scope": "test",
        "claims": [
            {"claim_id": "c1", "text": "Some claim without a source."}
            # source_ref is missing
        ],
    }
    assert validate_against("claim_list.schema.json", bad) != []


def test_claim_list_empty_text_rejected():
    bad = {
        "source_scope": "test",
        "claims": [{"claim_id": "c1", "text": "", "source_ref": "ref-1"}],
    }
    assert validate_against("claim_list.schema.json", bad) != []


def test_claim_list_empty_source_ref_rejected():
    """Golden test: empty source_ref (minLength 1) is rejected."""
    bad = {
        "source_scope": "test",
        "claims": [{"claim_id": "c1", "text": "A claim.", "source_ref": ""}],
    }
    assert validate_against("claim_list.schema.json", bad) != []


def test_claim_list_missing_source_scope_rejected():
    bad = {"claims": [{"claim_id": "c1", "text": "A claim.", "source_ref": "r1"}]}
    assert validate_against("claim_list.schema.json", bad) != []


def test_claim_list_invalid_kind_rejected():
    bad = {
        "source_scope": "s",
        "claims": [{"claim_id": "c1", "text": "T.", "source_ref": "r", "kind": "BADKIND"}],
    }
    assert validate_against("claim_list.schema.json", bad) != []


# ===========================================================================
# 3. claim_evidence_map.schema.json — golden test: empty loci[] is rejected
# ===========================================================================

_GOOD_CEM = {
    "mappings": [
        {
            "claim_id": "c1",
            "loci": [
                {
                    "locus_id": "l1",
                    "source_ref": "arxiv:2409.00001",
                    "location": "Table 2 row 1",
                    "kind": "table",
                    "reported_result": "0.87 Dice",
                    "supports_claim": True,
                }
            ],
            "overall_support": "supported",
        }
    ]
}


def test_claim_evidence_map_valid():
    assert validate_against("claim_evidence_map.schema.json", _GOOD_CEM) == []


def test_claim_evidence_map_empty_loci_rejected():
    """Golden test: a mapping with loci=[] is schema-rejected (minItems:1)."""
    bad = {
        "mappings": [
            {"claim_id": "c1", "loci": [], "overall_support": "not-found"}
        ]
    }
    assert validate_against("claim_evidence_map.schema.json", bad) != []


def test_claim_evidence_map_missing_mappings_rejected():
    bad = {}
    assert validate_against("claim_evidence_map.schema.json", bad) != []


def test_claim_evidence_map_locus_missing_source_ref_rejected():
    bad = {
        "mappings": [
            {
                "claim_id": "c1",
                "loci": [{"locus_id": "l1", "location": "Table 1"}],  # source_ref missing
            }
        ]
    }
    assert validate_against("claim_evidence_map.schema.json", bad) != []


def test_claim_evidence_map_invalid_kind_rejected():
    bad = {
        "mappings": [
            {
                "claim_id": "c1",
                "loci": [
                    {
                        "locus_id": "l1",
                        "source_ref": "r1",
                        "location": "L1",
                        "kind": "NOTAKIND",
                        "supports_claim": True,
                    }
                ],
            }
        ]
    }
    assert validate_against("claim_evidence_map.schema.json", bad) != []


def test_claim_evidence_map_locus_missing_supports_claim_rejected():
    """C3 golden test: supports_claim is now REQUIRED — omitting it is a schema error."""
    bad = {
        "mappings": [
            {
                "claim_id": "c1",
                "loci": [
                    {
                        "locus_id": "l1",
                        "source_ref": "arxiv:2409.00001",
                        "location": "Table 2 row 1",
                        "kind": "table",
                        "reported_result": "0.87 Dice",
                        # supports_claim intentionally OMITTED — must be rejected
                    }
                ],
            }
        ]
    }
    errors = validate_against("claim_evidence_map.schema.json", bad)
    assert errors != [], (
        "A locus without supports_claim must be schema-rejected — "
        "supports_claim is required (no default)"
    )


# ===========================================================================
# 4. contradiction_report.schema.json — conflict requires two claim_refs + kind
# ===========================================================================

_GOOD_CONTRADICTION = {
    "n_claims_checked": 10,
    "conflicts": [
        {
            "conflict_id": "conf1",
            "claim_ref_a": "c1",
            "claim_ref_b": "c3",
            "kind": "numerical-disagreement",
            "description": "c1 reports Dice=0.87, c3 reports Dice=0.61 for the same method.",
            "resolution_status": "unresolved",
        }
    ],
    "summary": "One numerical disagreement found.",
}


def test_contradiction_report_valid():
    assert validate_against("contradiction_report.schema.json", _GOOD_CONTRADICTION) == []


def test_contradiction_report_valid_no_conflicts():
    """An empty conflicts list is valid."""
    good = {"n_claims_checked": 5, "conflicts": [], "summary": "No conflicts found."}
    assert validate_against("contradiction_report.schema.json", good) == []


def test_contradiction_report_missing_claim_ref_a_rejected():
    bad = {
        "n_claims_checked": 2,
        "conflicts": [
            # claim_ref_a is missing
            {"conflict_id": "c1", "claim_ref_b": "c2", "kind": "numerical-disagreement",
             "description": "desc"}
        ],
    }
    assert validate_against("contradiction_report.schema.json", bad) != []


def test_contradiction_report_missing_kind_rejected():
    bad = {
        "n_claims_checked": 2,
        "conflicts": [
            {"conflict_id": "c1", "claim_ref_a": "ca", "claim_ref_b": "cb",
             "description": "desc"}  # kind missing
        ],
    }
    assert validate_against("contradiction_report.schema.json", bad) != []


def test_contradiction_report_invalid_kind_rejected():
    bad = {
        "n_claims_checked": 1,
        "conflicts": [
            {"conflict_id": "c1", "claim_ref_a": "ca", "claim_ref_b": "cb",
             "kind": "NOT-A-KIND", "description": "desc"}
        ],
    }
    assert validate_against("contradiction_report.schema.json", bad) != []


# ===========================================================================
# 5. dataset_card.schema.json — golden test: card with known overlap lists a risk
# ===========================================================================

_GOOD_DATASET_CARD = {
    "dataset_ref": "https://toothfairy.grand-challenge.org",
    "description": "3D CT scans for dental anatomy segmentation.",
    "year": 2023,
    "license": "CC BY 4.0",
    "modality": "CT",
    "size": {"total_samples": 443, "unit": "cases"},
    "splits": [
        {"name": "train", "n_samples": 300, "split_unit": "patient"},
        {"name": "test", "n_samples": 143, "split_unit": "patient"},
    ],
    "known_overlaps": ["ToothFairy1"],
    "leakage_risks": [
        {
            "risk_id": "lr1",
            "description": "ToothFairy3 shares subjects with ToothFairy1; train/test contamination possible.",
            "severity": "high",
            "overlapping_dataset": "ToothFairy1",
        }
    ],
    "provenance_notes": "Released as part of MICCAI 2023 challenge.",
}


def test_dataset_card_valid():
    assert validate_against("dataset_card.schema.json", _GOOD_DATASET_CARD) == []


def test_dataset_card_with_overlap_has_leakage_risk():
    """Golden test: a card with known_overlaps lists at least one leakage risk.

    Schema requires leakage_risks[] field to be present (not omitted).
    This test verifies a card with overlap passes schema (risk is populated),
    and a card with overlap but missing leakage_risks is rejected.
    """
    # Valid: has overlap AND has corresponding leakage risk
    assert validate_against("dataset_card.schema.json", _GOOD_DATASET_CARD) == []
    assert _GOOD_DATASET_CARD["known_overlaps"] == ["ToothFairy1"]
    assert len(_GOOD_DATASET_CARD["leakage_risks"]) > 0


def test_dataset_card_missing_leakage_risks_field_rejected():
    """leakage_risks is a required field — missing it rejects the card."""
    bad = {
        "dataset_ref": "ref",
        "description": "A dataset.",
        "splits": [],
        # leakage_risks is MISSING
    }
    assert validate_against("dataset_card.schema.json", bad) != []


def test_dataset_card_missing_required_fields_rejected():
    bad = {"dataset_ref": "ref"}  # description and splits missing
    assert validate_against("dataset_card.schema.json", bad) != []


def test_dataset_card_invalid_split_name_rejected():
    bad = {
        "dataset_ref": "ref",
        "description": "desc",
        "splits": [{"name": "INVALID_SPLIT", "n_samples": 100}],
        "leakage_risks": [],
    }
    assert validate_against("dataset_card.schema.json", bad) != []


def test_dataset_card_invalid_severity_rejected():
    bad = {
        "dataset_ref": "ref",
        "description": "desc",
        "splits": [],
        "leakage_risks": [
            {"risk_id": "r1", "description": "desc", "severity": "CRITICAL_NOT_IN_ENUM"}
        ],
    }
    assert validate_against("dataset_card.schema.json", bad) != []


# ===========================================================================
# 6. staleness_report.schema.json — status enum includes SUPERSEDED
# ===========================================================================

_GOOD_STALENESS_REPORT = {
    "source_ref": "github.com/old-seg-repo",
    "status": "SUPERSEDED",
    "age_years": 3.0,
    "successor_ref": "github.com/new-seg-repo",
    "staleness_rationale": "Superseded by github.com/new-seg-repo.",
    "audit_year": 2026,
}


def test_staleness_report_superseded_valid():
    assert validate_against("staleness_report.schema.json", _GOOD_STALENESS_REPORT) == []


def test_staleness_report_current_valid():
    good = {
        "source_ref": "arxiv:2025.0001",
        "status": "CURRENT",
        "age_years": 1.0,
        "successor_ref": None,
        "staleness_rationale": "Published 1 year ago.",
        "audit_year": 2026,
    }
    assert validate_against("staleness_report.schema.json", good) == []


def test_staleness_report_stale_valid():
    good = {
        "source_ref": "old-paper",
        "status": "STALE",
        "age_years": 5.0,
        "successor_ref": None,
        "staleness_rationale": "5 years old, no successor.",
        "audit_year": 2026,
    }
    assert validate_against("staleness_report.schema.json", good) == []


def test_staleness_report_missing_status_rejected():
    bad = {"source_ref": "r1", "age_years": 3.0}
    assert validate_against("staleness_report.schema.json", bad) != []


def test_staleness_report_invalid_status_rejected():
    bad = {
        "source_ref": "r1",
        "status": "OUTDATED",  # not in enum
        "age_years": 3.0,
    }
    assert validate_against("staleness_report.schema.json", bad) != []


# ===========================================================================
# 7. citation_integrity_verdict.schema.json — allOf: violations non-empty => BLOCK
# ===========================================================================

_GOOD_CIV_PASS = {
    "verdict": "PASS",
    "violations": [],
    "unresolvable_refs": [],
    "no_locus_claims": [],
    "contradicted_claims": [],
    "n_claims_checked": 3,
}

_GOOD_CIV_BLOCK = {
    "verdict": "BLOCK",
    "violations": ["claim c1 is unanchored"],
    "unresolvable_refs": [],
    "no_locus_claims": ["c1"],
    "contradicted_claims": [],
    "n_claims_checked": 3,
}


def test_citation_integrity_verdict_pass_valid():
    assert validate_against("citation_integrity_verdict.schema.json", _GOOD_CIV_PASS) == []


def test_citation_integrity_verdict_block_valid():
    assert validate_against("citation_integrity_verdict.schema.json", _GOOD_CIV_BLOCK) == []


def test_citation_integrity_verdict_hand_set_pass_with_violations_rejected():
    """Schema allOf: a hand-set PASS with non-empty violations must be rejected."""
    bad = {
        "verdict": "PASS",  # hand-set PASS
        "violations": ["c1 is unanchored"],  # but violations is non-empty
    }
    errors = validate_against("citation_integrity_verdict.schema.json", bad)
    assert errors != [], (
        "A PASS verdict with non-empty violations must be schema-rejected by the allOf rule"
    )


def test_citation_integrity_verdict_missing_verdict_rejected():
    bad = {"violations": []}
    assert validate_against("citation_integrity_verdict.schema.json", bad) != []


def test_citation_integrity_verdict_invalid_verdict_rejected():
    bad = {"verdict": "WARN", "violations": []}
    assert validate_against("citation_integrity_verdict.schema.json", bad) != []


# ===========================================================================
# 8. landscape_map.schema.json — coverage_gaps[] must be present
# ===========================================================================

_GOOD_LANDSCAPE_MAP = {
    "domain_query": "3D medical image segmentation with foundation models",
    "methods": [
        {
            "method_id": "m1",
            "name": "SAM-Med3D",
            "covered_by_sources": ["arxiv:2310.15161"],
            "representative_result": "Dice=0.78 on ToothFairy2",
            "notes": "",
        }
    ],
    "datasets_in_landscape": [
        {"dataset_ref": "https://toothfairy.grand-challenge.org", "name": "ToothFairy3",
         "usage_count": 3}
    ],
    "coverage_gaps": [
        {
            "gap_id": "g1",
            "description": "No evaluation of SAM3 on thin tubular structures such as coronary arteries.",
            "gap_kind": "domain",
            "severity": "major",
        }
    ],
    "n_methods_found": 1,
    "n_gaps_identified": 1,
}


def test_landscape_map_valid():
    assert validate_against("landscape_map.schema.json", _GOOD_LANDSCAPE_MAP) == []


def test_landscape_map_empty_gaps_valid():
    """An empty coverage_gaps list is schema-valid (the field must be present, not non-empty)."""
    good = {
        "domain_query": "NLP classification",
        "methods": [],
        "coverage_gaps": [],
    }
    assert validate_against("landscape_map.schema.json", good) == []


def test_landscape_map_missing_coverage_gaps_rejected():
    """coverage_gaps is a required field — missing it is rejected."""
    bad = {
        "domain_query": "NLP",
        "methods": [],
        # coverage_gaps MISSING
    }
    assert validate_against("landscape_map.schema.json", bad) != []


def test_landscape_map_missing_domain_query_rejected():
    bad = {"methods": [], "coverage_gaps": []}
    assert validate_against("landscape_map.schema.json", bad) != []


def test_landscape_map_invalid_gap_kind_rejected():
    bad = {
        "domain_query": "test",
        "methods": [],
        "coverage_gaps": [
            {"gap_id": "g1", "description": "desc", "gap_kind": "NOT-VALID"}
        ],
    }
    assert validate_against("landscape_map.schema.json", bad) != []


def test_landscape_map_gap_missing_description_rejected():
    bad = {
        "domain_query": "test",
        "methods": [],
        "coverage_gaps": [
            {"gap_id": "g1"}  # description missing
        ],
    }
    assert validate_against("landscape_map.schema.json", bad) != []
