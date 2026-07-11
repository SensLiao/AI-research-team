"""Schema validation tests for all 8 VERIFY panel schemas.

Each schema: one well-formed payload that validates (errors == []) and one crafted-bad
payload that is rejected (errors != []). Covers the golden structural assertions pushed
into each schema per the contract.

Uses validate_against(filename, instance) — no PAYLOAD_SCHEMAS registration needed.
"""
from __future__ import annotations

from research_agent_teams.tools.validate_artifact import validate_against


# =============================================================================
# 1. review_config
# =============================================================================

class TestReviewConfigSchema:
    _SCHEMA = "review_config.schema.json"

    def test_well_formed_validates(self) -> None:
        good = {
            "run_ref": "run-001",
            "lenses": [
                {
                    "lens": "methodology",
                    "anchor": "statistical design and variable control",
                    "reviewer_agent": "methodology-reviewer",
                },
                {
                    "lens": "domain",
                    "anchor": "metric validity per cv-medical-segmentation",
                    "reviewer_agent": "domain-reviewer",
                },
            ],
            "synthesis_mandate": "Synthesize all findings into a structured verdict.",
            "inputs_to_review": ["evidence/ANALYZE/result-summary.artifact.json"],
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_run_ref_rejected(self) -> None:
        bad = {
            "lenses": [{"lens": "methodology", "anchor": "stats", "reviewer_agent": "r"}],
            "synthesis_mandate": "synth",
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_missing_synthesis_mandate_rejected(self) -> None:
        bad = {
            "run_ref": "run-001",
            "lenses": [{"lens": "methodology", "anchor": "stats", "reviewer_agent": "r"}],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_lens_with_empty_anchor_rejected(self) -> None:
        """Schema enforces minLength:1 on anchor."""
        bad = {
            "run_ref": "run-001",
            "lenses": [{"lens": "methodology", "anchor": "", "reviewer_agent": "r"}],
            "synthesis_mandate": "synth",
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_invalid_lens_value_rejected(self) -> None:
        """lens must be enum methodology|domain."""
        bad = {
            "run_ref": "run-001",
            "lenses": [{"lens": "statistical", "anchor": "stats", "reviewer_agent": "r"}],
            "synthesis_mandate": "synth",
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_additional_properties_rejected(self) -> None:
        bad = {
            "run_ref": "run-001",
            "lenses": [{"lens": "methodology", "anchor": "stats", "reviewer_agent": "r"}],
            "synthesis_mandate": "synth",
            "extra_field": "not allowed",
        }
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 2. panel_review  (shared by methodology + domain, discriminated by lens)
# =============================================================================

class TestPanelReviewSchema:
    _SCHEMA = "panel_review.schema.json"

    def test_methodology_review_with_block_finding_validates(self) -> None:
        good = {
            "lens": "methodology",
            "findings": [
                {
                    "anchor": "section 3.2, table 1: only 1 seed reported",
                    "evidence": "experiment_matrix.n_seeds=1; profile requires min 3",
                    "severity": "BLOCK",
                    "finding_id": "meth-01",
                    "rebuttal_required": True,
                }
            ],
            "overall_verdict": "BLOCK",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_domain_review_with_warn_finding_validates(self) -> None:
        good = {
            "lens": "domain",
            "findings": [
                {
                    "anchor": "figure 2 caption",
                    "evidence": "HD95 not reported; only Dice shown",
                    "severity": "WARN",
                }
            ],
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_empty_findings_validates(self) -> None:
        """Reviewer with no findings is valid."""
        good = {"lens": "methodology", "findings": []}
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_lens_rejected(self) -> None:
        bad = {"findings": [{"anchor": "sec 3", "evidence": "text", "severity": "WARN"}]}
        assert validate_against(self._SCHEMA, bad) != []

    def test_finding_with_empty_anchor_rejected(self) -> None:
        """anchor requires minLength:1 — a key golden assertion."""
        bad = {
            "lens": "methodology",
            "findings": [{"anchor": "", "evidence": "some evidence", "severity": "WARN"}],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_finding_with_empty_evidence_rejected(self) -> None:
        """evidence requires minLength:1."""
        bad = {
            "lens": "methodology",
            "findings": [{"anchor": "section 3", "evidence": "", "severity": "WARN"}],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_finding_with_invalid_severity_rejected(self) -> None:
        bad = {
            "lens": "domain",
            "findings": [{"anchor": "sec 2", "evidence": "text", "severity": "CRITICAL"}],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_invalid_lens_value_rejected(self) -> None:
        bad = {"lens": "statistical", "findings": []}
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 3. critic_memo
# =============================================================================

class TestCriticMemoSchema:
    _SCHEMA = "critic_memo.schema.json"

    def test_well_formed_with_block_flag_validates(self) -> None:
        good = {
            "cross_findings": [
                {
                    "description": "Methodology reviewer PASSes on eval frame; domain reviewer BLOCKs same issue",
                    "involved_lenses": ["methodology", "domain"],
                    "resolution_path": "Escalate to BLOCK in methodology review",
                }
            ],
            "block_flags": [
                {
                    "flag_text": "eval frame inconsistency not resolved",
                    "source": "meth-01 vs dom-01",
                    "defensible_path": "Add metric implementation check",
                }
            ],
            "gaps": ["missing ablation on postprocessing"],
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_empty_memo_validates(self) -> None:
        """No findings and no flags is valid (panel reviews are consistent)."""
        good = {"cross_findings": [], "block_flags": []}
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_cross_findings_rejected(self) -> None:
        bad = {"block_flags": []}
        assert validate_against(self._SCHEMA, bad) != []

    def test_missing_block_flags_rejected(self) -> None:
        bad = {"cross_findings": []}
        assert validate_against(self._SCHEMA, bad) != []

    def test_block_flag_with_empty_flag_text_rejected(self) -> None:
        bad = {
            "cross_findings": [],
            "block_flags": [{"flag_text": "", "source": "critic"}],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_cross_finding_with_empty_description_rejected(self) -> None:
        bad = {
            "cross_findings": [{"description": "", "involved_lenses": ["methodology"]}],
            "block_flags": [],
        }
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 4. panel_synthesis
# =============================================================================

class TestPanelSynthesisSchema:
    _SCHEMA = "panel_synthesis.schema.json"

    def test_approve_with_no_violations_validates(self) -> None:
        good = {
            "verdict": "APPROVE",
            "violations": [],
            "addressed_blocks": [
                {"block_source": "meth-01", "rebuttal": "n_seeds=5 in the corrected run"}
            ],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
            "overall_summary": "All blocks addressed.",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_block_with_violations_validates(self) -> None:
        good = {
            "verdict": "BLOCK",
            "violations": ["reviewer BLOCK finding 'dom-01' not addressed"],
            "addressed_blocks": [],
            "unaddressed_blocks": ["dom-01"],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_approve_with_violations_schema_rejected(self) -> None:
        """The allOf if/then: violations non-empty → verdict MUST be BLOCK. APPROVE+violations rejected."""
        bad = {
            "verdict": "APPROVE",
            "violations": ["unaddressed block"],
            "addressed_blocks": [],
            "unaddressed_blocks": ["dom-01"],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_missing_violations_rejected(self) -> None:
        bad = {
            "verdict": "APPROVE",
            "addressed_blocks": [],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_addressed_block_with_empty_rebuttal_rejected(self) -> None:
        bad = {
            "verdict": "APPROVE",
            "violations": [],
            "addressed_blocks": [{"block_source": "meth-01", "rebuttal": ""}],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, bad) != []

    # M3 regression tests -------------------------------------------------------

    def test_m3_approve_with_nonempty_unaddressed_blocks_rejected(self) -> None:
        """M3 regression: APPROVE + non-empty unaddressed_blocks MUST be schema-rejected.

        Previously this validated successfully because the schema had no allOf clause
        enforcing that APPROVE requires unaddressed_blocks maxItems:0.
        """
        bad = {
            "verdict": "APPROVE",
            "violations": [],
            "addressed_blocks": [],
            "unaddressed_blocks": ["dom-01"],  # non-empty while verdict=APPROVE
            "open_critic_flags": [],
        }
        errors = validate_against(self._SCHEMA, bad)
        assert errors != [], (
            "M3 regression FAILED: APPROVE+non-empty unaddressed_blocks validated; "
            "schema must reject this with an allOf APPROVE→maxItems:0 rule"
        )

    def test_m3_approve_with_nonempty_open_critic_flags_rejected(self) -> None:
        """M3 regression: APPROVE + non-empty open_critic_flags MUST be schema-rejected."""
        bad = {
            "verdict": "APPROVE",
            "violations": [],
            "addressed_blocks": [],
            "unaddressed_blocks": [],
            "open_critic_flags": ["some unresolved critic flag"],  # non-empty while verdict=APPROVE
        }
        errors = validate_against(self._SCHEMA, bad)
        assert errors != [], (
            "M3 regression FAILED: APPROVE+non-empty open_critic_flags validated; "
            "schema must reject this with an allOf APPROVE→maxItems:0 rule"
        )

    def test_m3_block_with_nonempty_unaddressed_blocks_validates(self) -> None:
        """M3 regression (happy): BLOCK + non-empty unaddressed_blocks is valid."""
        good = {
            "verdict": "BLOCK",
            "violations": ["reviewer BLOCK finding 'dom-01' not addressed"],
            "addressed_blocks": [],
            "unaddressed_blocks": ["dom-01"],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_m3_approve_with_both_lists_empty_validates(self) -> None:
        """M3 regression (happy): APPROVE + both lists empty is valid (normal APPROVE)."""
        good = {
            "verdict": "APPROVE",
            "violations": [],
            "addressed_blocks": [{"block_source": "meth-01", "rebuttal": "n_seeds=5 confirmed"}],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
        }
        assert validate_against(self._SCHEMA, good) == []


# =============================================================================
# 5. synthesis_text
# =============================================================================

class TestSynthesisTextSchema:
    _SCHEMA = "synthesis_text.schema.json"

    def test_well_formed_validates(self) -> None:
        good = {
            "structured_verdict": "APPROVE",
            "prose_verdict_word": "approve",
            "body": "The review panel found the work ready for submission after addressing all BLOCKs.",
            "addressed_blocks_summary": ["Block meth-01 was addressed by increasing n_seeds to 5."],
            "remaining_concerns": [],
            "from_synthesis_ref": "evidence/VERIFY/panel-synthesis.artifact.json",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_block_verdict_validates(self) -> None:
        good = {
            "structured_verdict": "BLOCK",
            "prose_verdict_word": "block",
            "body": "The panel blocks until the eval frame mismatch is resolved.",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_structured_verdict_rejected(self) -> None:
        bad = {"prose_verdict_word": "approve", "body": "text"}
        assert validate_against(self._SCHEMA, bad) != []

    def test_missing_prose_verdict_word_rejected(self) -> None:
        bad = {"structured_verdict": "APPROVE", "body": "text"}
        assert validate_against(self._SCHEMA, bad) != []

    def test_empty_body_rejected(self) -> None:
        bad = {"structured_verdict": "APPROVE", "prose_verdict_word": "approve", "body": ""}
        assert validate_against(self._SCHEMA, bad) != []

    def test_invalid_structured_verdict_rejected(self) -> None:
        bad = {
            "structured_verdict": "PASS",  # must be APPROVE or BLOCK
            "prose_verdict_word": "pass",
            "body": "text",
        }
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 6. contribution_ledger
# =============================================================================

class TestContributionLedgerSchema:
    _SCHEMA = "contribution_ledger.schema.json"

    def test_well_formed_validates(self) -> None:
        good = {
            "contributions": [
                {
                    "claim_text": "Our LoRA fine-tuning achieves +3% Dice over the baseline",
                    "evidence_refs": ["evidence/ANALYZE/result-summary.artifact.json"],
                    "condition_id": "treatment-lora",
                    "contribution_type": "method",
                    "scope_note": "Tested on cv-medical-segmentation profile only",
                }
            ],
            "run_ref": "run-001",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_contributions_rejected(self) -> None:
        bad = {"run_ref": "run-001"}
        assert validate_against(self._SCHEMA, bad) != []

    def test_empty_evidence_refs_schema_rejected(self) -> None:
        """Schema enforces minItems:1 on evidence_refs — golden assertion."""
        bad = {
            "contributions": [
                {
                    "claim_text": "some claim",
                    "evidence_refs": [],  # empty → rejected
                    "condition_id": "cond-1",
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_empty_condition_id_schema_rejected(self) -> None:
        """Schema enforces minLength:1 on condition_id — golden assertion."""
        bad = {
            "contributions": [
                {
                    "claim_text": "some claim",
                    "evidence_refs": ["evidence/r.json"],
                    "condition_id": "",  # empty → rejected
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_invalid_contribution_type_rejected(self) -> None:
        bad = {
            "contributions": [
                {
                    "claim_text": "claim",
                    "evidence_refs": ["e.json"],
                    "condition_id": "cond-1",
                    "contribution_type": "result",  # not in enum
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 7. threats_report
# =============================================================================

class TestThreatsReportSchema:
    _SCHEMA = "threats_report.schema.json"

    def test_well_formed_validates(self) -> None:
        good = {
            "threats": [
                {
                    "validity_dimension": "internal",
                    "threat_text": "selection bias: all patients from single site",
                    "mitigation": "external test set added",
                    "severity": "medium",
                },
                {
                    "validity_dimension": "external",
                    "threat_text": "dataset from single institution",
                    "mitigation": "acknowledged as limitation",
                    "severity": "high",
                },
                {
                    "validity_dimension": "construct",
                    "threat_text": "Dice may not capture topology",
                    "mitigation": "clDice added as secondary metric",
                    "severity": "low",
                },
                {
                    "validity_dimension": "statistical",
                    "threat_text": "only 3 seeds",
                    "mitigation": "none identified — future work",
                    "severity": "medium",
                },
            ]
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_threats_rejected(self) -> None:
        bad = {"coverage_confirmed": True}
        assert validate_against(self._SCHEMA, bad) != []

    def test_threat_with_invalid_dimension_rejected(self) -> None:
        bad = {
            "threats": [
                {
                    "validity_dimension": "ecological",  # not in enum
                    "threat_text": "text",
                    "mitigation": "none",
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_threat_with_empty_threat_text_rejected(self) -> None:
        bad = {
            "threats": [
                {"validity_dimension": "internal", "threat_text": "", "mitigation": "none"}
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_threat_with_empty_mitigation_rejected(self) -> None:
        bad = {
            "threats": [
                {"validity_dimension": "internal", "threat_text": "bias", "mitigation": ""}
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []


# =============================================================================
# 8. response_simulation
# =============================================================================

class TestResponseSimulationSchema:
    _SCHEMA = "response_simulation.schema.json"

    def test_well_formed_with_indefensible_attack_validates(self) -> None:
        """The contract requirement: attacks each have attack_class + defensible boolean."""
        good = {
            "attacks": [
                {
                    "attack_class": "insufficient_power",
                    "attack_text": "The reported +2% improvement is within variance for n=3 seeds.",
                    "defensible": False,
                    "defense_argument": "",
                    "severity_if_indefensible": "major",
                },
                {
                    "attack_class": "unfair_baseline",
                    "attack_text": "Baseline was not given LoRA adaptation budget.",
                    "defensible": True,
                    "defense_argument": "Baseline given equivalent wall-time as documented in run-record.",
                    "severity_if_indefensible": "fatal",
                },
            ],
            "indefensible_count": 1,
            "run_ref": "run-001",
        }
        assert validate_against(self._SCHEMA, good) == []

    def test_empty_attacks_validates(self) -> None:
        """Empty attacks list is valid (advisory artifact)."""
        good = {"attacks": []}
        assert validate_against(self._SCHEMA, good) == []

    def test_missing_attacks_rejected(self) -> None:
        bad = {"indefensible_count": 0, "run_ref": "run-001"}
        assert validate_against(self._SCHEMA, bad) != []

    def test_attack_missing_defensible_rejected(self) -> None:
        """defensible is required on each attack."""
        bad = {
            "attacks": [
                {
                    "attack_class": "overclaim",
                    "attack_text": "Abstract overclaims.",
                    # defensible missing
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_attack_missing_attack_class_rejected(self) -> None:
        """attack_class is required."""
        bad = {
            "attacks": [
                {
                    "attack_text": "Some attack.",
                    "defensible": True,
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_attack_with_empty_attack_class_rejected(self) -> None:
        """attack_class must be minLength:1."""
        bad = {
            "attacks": [
                {"attack_class": "", "attack_text": "Some attack.", "defensible": True}
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []

    def test_attack_invalid_severity_rejected(self) -> None:
        bad = {
            "attacks": [
                {
                    "attack_class": "overclaim",
                    "attack_text": "text",
                    "defensible": False,
                    "severity_if_indefensible": "catastrophic",  # not in enum
                }
            ]
        }
        assert validate_against(self._SCHEMA, bad) != []
