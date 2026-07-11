"""Tests for all 8 new DESIGN-depth schemas + the existing adr schema (for decision-surfacer).

Uses validate_against() which validates directly against schema files — NO PAYLOAD_SCHEMAS
registration required. All tests are GREEN before main-thread integration.

Schemas tested:
  rq_hypothesis_chain, split_manifest, data_protocol, unified_config,
  integration_plan, baseline_fairness_plan, metric_impl_report, power_audit_report.
  Plus: adr (existing — for decision-surfacer's build-and-validate test).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ==============================================================================
# 1. rq_hypothesis_chain
# ==============================================================================

class TestRqHypothesisChain:
    SCHEMA = "rq_hypothesis_chain.schema.json"

    def _good(self) -> dict:
        return {
            "research_question": "Does LoRA beat full fine-tune at equal budget?",
            "hypotheses": [
                {
                    "hypothesis_id": "H1",
                    "statement": "LoRA achieves comparable Dice to full fine-tune.",
                    "falsifiable_prediction": (
                        "Mean Dice of LoRA condition >= mean Dice of full-ft condition "
                        "within 1% at the same compute budget."
                    ),
                    "evidence_needed": ["ablation experiment with equal GPU hours"],
                }
            ],
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_empty_hypotheses_rejected(self):
        """hypotheses minItems:1 — empty list is schema-rejected."""
        bad = self._good()
        bad["hypotheses"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_falsifiable_prediction_rejected(self):
        """Each hypothesis requires falsifiable_prediction (minLength:1)."""
        bad = self._good()
        del bad["hypotheses"][0]["falsifiable_prediction"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_falsifiable_prediction_rejected(self):
        """Empty falsifiable_prediction violates minLength:1."""
        bad = self._good()
        bad["hypotheses"][0]["falsifiable_prediction"] = ""
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_evidence_needed_rejected(self):
        """Each hypothesis requires evidence_needed."""
        bad = self._good()
        del bad["hypotheses"][0]["evidence_needed"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_evidence_needed_rejected(self):
        """evidence_needed minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["hypotheses"][0]["evidence_needed"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_research_question_rejected(self):
        bad = self._good()
        del bad["research_question"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        """additionalProperties:false — unknown top-level key is rejected."""
        bad = self._good()
        bad["unexpected_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_multiple_hypotheses_with_depends_on_validates(self):
        """Two hypotheses with depends_on should validate fine."""
        good = self._good()
        good["hypotheses"].append({
            "hypothesis_id": "H2",
            "statement": "LoRA converges faster.",
            "falsifiable_prediction": "Training loss of LoRA decreases 2x faster in first 10 epochs.",
            "evidence_needed": ["training curves from ablation"],
            "depends_on": ["H1"],
        })
        assert validate_against(self.SCHEMA, good) == []


# ==============================================================================
# 2. split_manifest
# ==============================================================================

class TestSplitManifest:
    SCHEMA = "split_manifest.schema.json"

    def _good(self) -> dict:
        return {
            "split_unit": "patient",
            "splits": [
                {"name": "train", "fraction": 0.7},
                {"name": "val", "fraction": 0.1},
                {"name": "test", "fraction": 0.2},
            ],
            "leakage_declaration": "patient_id_disjoint verified across all splits",
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_missing_split_unit_rejected(self):
        bad = self._good()
        del bad["split_unit"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_leakage_declaration_rejected(self):
        bad = self._good()
        del bad["leakage_declaration"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_only_one_split_rejected(self):
        """splits minItems:2 — single split is schema-rejected."""
        bad = self._good()
        bad["splits"] = [{"name": "train", "fraction": 1.0}]
        assert validate_against(self.SCHEMA, bad) != []

    def test_fraction_above_one_rejected(self):
        """fraction maximum:1 — fraction > 1 is rejected."""
        bad = self._good()
        bad["splits"][0]["fraction"] = 1.5
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        bad = self._good()
        bad["unknown"] = "x"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 3. data_protocol
# ==============================================================================

class TestDataProtocol:
    SCHEMA = "data_protocol.schema.json"

    def _good(self) -> dict:
        return {
            "steps": [
                {
                    "step_id": "s1",
                    "kind": "resampling",
                    "description": "Resample all volumes to 1mm isotropic spacing.",
                    "train_only": False,
                },
                {
                    "step_id": "s2",
                    "kind": "augmentation",
                    "description": "Random horizontal flips.",
                    "train_only": True,
                },
            ],
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_missing_steps_rejected(self):
        bad = self._good()
        del bad["steps"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_steps_rejected(self):
        """steps minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["steps"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_step_missing_train_only_rejected(self):
        bad = self._good()
        del bad["steps"][0]["train_only"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_step_missing_kind_rejected(self):
        bad = self._good()
        del bad["steps"][0]["kind"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_step_invalid_kind_rejected(self):
        """kind is an enum — invalid value is rejected."""
        bad = self._good()
        bad["steps"][0]["kind"] = "magic_step"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_step_property_rejected(self):
        bad = self._good()
        bad["steps"][0]["unknown_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_top_level_property_rejected(self):
        bad = self._good()
        bad["extra"] = "not_allowed"
        assert validate_against(self.SCHEMA, bad) != []

    # ------ H3 anti-leakage regression tests (fails-before/passes-after) ------

    def test_augmentation_train_only_false_rejected(self):
        """H3 regression: augmentation step with train_only:false must be REJECTED.
        This was the hole — before the allOf fix, this validated silently."""
        bad = self._good()
        # Make the augmentation step leak into test by setting train_only=False
        bad["steps"][1]["train_only"] = False
        assert validate_against(self.SCHEMA, bad) != [], (
            "Schema must reject an augmentation step with train_only:false (anti-leakage allOf)"
        )

    def test_no_augmentation_steps_validates(self):
        """H3 choice: per-item rule only (not ≥1-augmentation requirement).
        A protocol with only preprocessing steps and no augmentation is VALID.
        Rationale: pure preprocessing pipelines (e.g. resampling-only) are legitimate
        and should not be forced to invent an augmentation step they don't need."""
        good = {
            "steps": [
                {
                    "step_id": "s1",
                    "kind": "resampling",
                    "description": "Resample to 1mm isotropic.",
                    "train_only": False,
                },
                {
                    "step_id": "s2",
                    "kind": "normalization",
                    "description": "Z-score normalize intensities.",
                    "train_only": False,
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == [], (
            "A protocol with no augmentation steps should be VALID (per-item rule only)"
        )

    def test_augmentation_train_only_true_with_preprocessing_validates(self):
        """H3 regression: valid protocol — augmentation step train_only:true plus
        preprocessing steps that correctly have train_only:false — must PASS."""
        good = {
            "steps": [
                {
                    "step_id": "s1",
                    "kind": "preprocessing",
                    "description": "Clip HU values.",
                    "train_only": False,
                },
                {
                    "step_id": "s2",
                    "kind": "augmentation",
                    "description": "Random rotation ±15°.",
                    "train_only": True,
                },
                {
                    "step_id": "s3",
                    "kind": "normalization",
                    "description": "Z-score normalize.",
                    "train_only": False,
                },
            ]
        }
        assert validate_against(self.SCHEMA, good) == [], (
            "A protocol with augmentation train_only:true and preprocessing train_only:false must PASS"
        )


# ==============================================================================
# 4. unified_config
# ==============================================================================

class TestUnifiedConfig:
    SCHEMA = "unified_config.schema.json"

    def _good(self) -> dict:
        return {
            "shared_config": {"lr": 1e-4, "epochs": 50},
            "conditions": [
                {"condition_id": "c0", "divergences": []},
                {
                    "condition_id": "c1",
                    "divergences": [
                        {
                            "key": "adapter",
                            "value": "lora",
                            "justification": "studying LoRA adapter effect",
                        }
                    ],
                },
            ],
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_missing_conditions_rejected(self):
        bad = self._good()
        del bad["conditions"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_shared_config_rejected(self):
        bad = self._good()
        del bad["shared_config"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_divergence_missing_justification_rejected(self):
        """Divergence with no justification key is rejected by schema (required field)."""
        bad = self._good()
        bad["conditions"][1]["divergences"][0] = {
            "key": "adapter",
            "value": "lora",
            # justification deliberately omitted
        }
        assert validate_against(self.SCHEMA, bad) != []

    def test_divergence_missing_key_field_rejected(self):
        bad = self._good()
        bad["conditions"][1]["divergences"][0] = {
            "value": "lora",
            "justification": "reason",
        }
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_divergence_property_rejected(self):
        bad = self._good()
        bad["conditions"][1]["divergences"][0]["unexpected"] = "field"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_top_level_rejected(self):
        bad = self._good()
        bad["unexpected"] = "not allowed"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 5. integration_plan
# ==============================================================================

class TestIntegrationPlan:
    SCHEMA = "integration_plan.schema.json"

    def _good(self) -> dict:
        return {
            "research_question": "Does LoRA beat full fine-tune?",
            "conditions": [
                {
                    "condition_id": "c0",
                    "module": None,
                    "entry_point": "train.py",
                },
                {
                    "condition_id": "c1",
                    "module": "methods.lora_adapter",
                    "entry_point": "train.py --adapter lora",
                },
            ],
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_missing_conditions_rejected(self):
        bad = self._good()
        del bad["conditions"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_only_one_condition_rejected(self):
        """conditions minItems:2 — single condition is rejected."""
        bad = self._good()
        bad["conditions"] = [bad["conditions"][0]]
        assert validate_against(self.SCHEMA, bad) != []

    def test_no_null_module_baseline_rejected(self):
        """The allOf.contains rule requires at least one condition with module:null."""
        bad = self._good()
        bad["conditions"][0]["module"] = "methods.full_finetune"  # no null-module baseline
        assert validate_against(self.SCHEMA, bad) != []

    def test_condition_missing_entry_point_rejected(self):
        bad = self._good()
        del bad["conditions"][0]["entry_point"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_condition_property_rejected(self):
        bad = self._good()
        bad["conditions"][0]["unknown_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_top_level_rejected(self):
        bad = self._good()
        bad["extra"] = "not allowed"
        assert validate_against(self.SCHEMA, bad) != []

    # ------ M1 regression tests -----------------------------------------------

    def test_two_baselines_zero_treatments_rejected(self):
        """M1 regression: two baseline conditions (module:null) and zero treatments.
        Before the fix, this validated because the old allOf only required ≥1 baseline.
        After the fix: maxContains:1 on the baseline clause rejects 2 baselines,
        AND the treatment clause rejects zero treatments."""
        bad = {
            "research_question": "Does X beat Y?",
            "conditions": [
                {"condition_id": "c0", "module": None, "entry_point": "train.py"},
                {"condition_id": "c1", "module": None, "entry_point": "train.py"},
            ],
        }
        assert validate_against(self.SCHEMA, bad) != [], (
            "Two baselines + zero treatments must be REJECTED (exactly-one baseline + ≥1 treatment)"
        )

    def test_one_baseline_one_treatment_validates(self):
        """M1 regression: exactly one baseline + one treatment — the canonical valid case."""
        good = self._good()
        assert validate_against(self.SCHEMA, good) == [], (
            "One baseline + one treatment must VALIDATE"
        )

    def test_zero_baselines_rejected(self):
        """M1 existing test: no null-module condition is still rejected."""
        bad = self._good()
        bad["conditions"][0]["module"] = "methods.full_finetune"  # replace the null-module
        assert validate_against(self.SCHEMA, bad) != [], (
            "Zero baselines must be REJECTED"
        )

    def test_one_baseline_multiple_treatments_validates(self):
        """M1: one baseline plus two treatment conditions is valid."""
        good = {
            "research_question": "Multi-treatment experiment?",
            "conditions": [
                {"condition_id": "c0", "module": None, "entry_point": "train.py"},
                {"condition_id": "c1", "module": "methods.lora", "entry_point": "train.py --lora"},
                {"condition_id": "c2", "module": "methods.adapter", "entry_point": "train.py --adapter"},
            ],
        }
        assert validate_against(self.SCHEMA, good) == [], (
            "One baseline + two treatments must VALIDATE"
        )


# ==============================================================================
# 6. baseline_fairness_plan
# ==============================================================================

class TestBaselineFairnessPlan:
    SCHEMA = "baseline_fairness_plan.schema.json"

    def _good(self) -> dict:
        return {
            "baseline_ref": "c0",
            "treatment_refs": ["c1"],
            "fairness_checks": [
                {
                    "check_name": "data_hash",
                    "baseline_value": "sha256:abc123",
                    "treatment_values": {"c1": "sha256:abc123"},
                    "mismatch_detected": False,
                }
            ],
            "fairness_violations": [],
        }

    def test_wellformed_validates(self):
        assert validate_against(self.SCHEMA, self._good()) == []

    def test_with_violations_validates(self):
        """A plan with violations is still schema-valid (violations field is present)."""
        good = self._good()
        good["fairness_violations"] = ["compute_budget mismatch: c0=100 GPU-h, c1=50 GPU-h"]
        assert validate_against(self.SCHEMA, good) == []

    def test_missing_baseline_ref_rejected(self):
        bad = self._good()
        del bad["baseline_ref"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_treatment_refs_rejected(self):
        bad = self._good()
        del bad["treatment_refs"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_treatment_refs_rejected(self):
        """treatment_refs minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["treatment_refs"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_fairness_checks_rejected(self):
        bad = self._good()
        del bad["fairness_checks"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_empty_fairness_checks_rejected(self):
        """fairness_checks minItems:1 — empty list is rejected."""
        bad = self._good()
        bad["fairness_checks"] = []
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_fairness_violations_rejected(self):
        bad = self._good()
        del bad["fairness_violations"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_check_missing_check_name_rejected(self):
        bad = self._good()
        del bad["fairness_checks"][0]["check_name"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        bad = self._good()
        bad["unknown_field"] = "x"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 7. metric_impl_report (gate schema — must enforce verdict-integrity allOf)
# ==============================================================================

class TestMetricImplReport:
    SCHEMA = "metric_impl_report.schema.json"

    def _good_pass(self) -> dict:
        return {
            "verdict": "PASS",
            "violations": [],
            "checked_metrics": ["dice", "hd95"],
        }

    def _good_block(self) -> dict:
        return {
            "verdict": "BLOCK",
            "violations": ["metric='dice' has inconsistent impl_ref: c0='monai.DiceMetric' c1='custom.dice'"],
            "checked_metrics": ["dice"],
        }

    def test_pass_no_violations_validates(self):
        assert validate_against(self.SCHEMA, self._good_pass()) == []

    def test_block_with_violations_validates(self):
        assert validate_against(self.SCHEMA, self._good_block()) == []

    def test_verdict_integrity_pass_with_violations_rejected(self):
        """CRITICAL: verdict=PASS but violations non-empty — must be schema-rejected (allOf).
        A hand-set PASS with violations is a lie that bypasses the gate."""
        bad = {
            "verdict": "PASS",  # hand-set pass — WRONG
            "violations": ["metric='dice' inconsistent impl_ref"],
        }
        errors = validate_against(self.SCHEMA, bad)
        assert errors != [], (
            "Schema must reject verdict=PASS when violations is non-empty (allOf verdict-integrity rule)"
        )

    def test_missing_verdict_rejected(self):
        bad = self._good_pass()
        del bad["verdict"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_violations_rejected(self):
        bad = self._good_pass()
        del bad["violations"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_verdict_value_rejected(self):
        bad = self._good_pass()
        bad["verdict"] = "WARN"
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        bad = self._good_pass()
        bad["unknown"] = "x"
        assert validate_against(self.SCHEMA, bad) != []


# ==============================================================================
# 8. power_audit_report (advisory — sufficient bool, not PASS/BLOCK)
# ==============================================================================

class TestPowerAuditReport:
    SCHEMA = "power_audit_report.schema.json"

    def _good_sufficient(self) -> dict:
        return {
            "sufficient": True,
            "n_seeds_declared": 5,
            "min_seeds_required": 3,
        }

    def _good_insufficient(self) -> dict:
        return {
            "sufficient": False,
            "n_seeds_declared": 1,
            "min_seeds_required": 3,
            "power_concerns": [
                "n=1 provides no variance estimate; results are a single data point"
            ],
        }

    def test_sufficient_true_validates(self):
        assert validate_against(self.SCHEMA, self._good_sufficient()) == []

    def test_sufficient_false_with_concerns_validates(self):
        assert validate_against(self.SCHEMA, self._good_insufficient()) == []

    def test_no_profile_min_validates(self):
        """When profile doesn't declare min, min_seeds_required can be null."""
        good = {
            "sufficient": True,
            "n_seeds_declared": 3,
            "min_seeds_required": None,
            "power_concerns": ["No minimum declared in profile; 3 seeds used as domain default"],
        }
        assert validate_against(self.SCHEMA, good) == []

    def test_missing_sufficient_rejected(self):
        bad = self._good_sufficient()
        del bad["sufficient"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_n_seeds_declared_rejected(self):
        bad = self._good_sufficient()
        del bad["n_seeds_declared"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_n_seeds_negative_rejected(self):
        """n_seeds_declared minimum:0."""
        bad = self._good_sufficient()
        bad["n_seeds_declared"] = -1
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        bad = self._good_sufficient()
        bad["bogus_field"] = "x"
        assert validate_against(self.SCHEMA, bad) != []

    def test_with_adr_override_ref_validates(self):
        """Including an optional adr_override_ref should still validate."""
        good = self._good_insufficient()
        good["adr_override_ref"] = "ADR-0001"
        assert validate_against(self.SCHEMA, good) == []


# ==============================================================================
# 9. adr (EXISTING schema) — decision-surfacer build-and-validate test
# ==============================================================================

class TestAdrDecisionSurfacer:
    SCHEMA = "adr.schema.json"

    def _good_adr(self) -> dict:
        return {
            "decision_id": "ADR-0001",
            "question": "Which split unit to use for cv-medical experiments?",
            "options": [
                "patient-level split (prevents patient leakage)",
                "slice-level split (more samples but causes patient leakage)",
            ],
            "chosen_option": "patient-level split (prevents patient leakage)",
            "reason": "Patient-level is required by domain profile; slice-level causes leakage.",
            "status": "proposed",
        }

    def test_wellformed_adr_validates(self):
        """decision-surfacer builds an ADR and it validates against the existing schema."""
        assert validate_against(self.SCHEMA, self._good_adr()) == []

    def test_approved_adr_validates(self):
        """An approved ADR with approved_by and approved_at is valid."""
        good = self._good_adr()
        good["status"] = "approved"
        good["approved_by"] = "director"
        good["approved_at"] = "2026-06-08T12:00:00Z"
        assert validate_against(self.SCHEMA, good) == []

    def test_missing_decision_id_rejected(self):
        bad = self._good_adr()
        del bad["decision_id"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_wrong_decision_id_format_rejected(self):
        """decision_id must match ^ADR-[0-9]{4,}$."""
        bad = self._good_adr()
        bad["decision_id"] = "DEC-001"
        assert validate_against(self.SCHEMA, bad) != []

    def test_only_one_option_rejected(self):
        """options minItems:2 — a single option is rejected."""
        bad = self._good_adr()
        bad["options"] = ["only one option"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_invalid_status_rejected(self):
        """status enum only allows proposed/approved/rejected."""
        bad = self._good_adr()
        bad["status"] = "pending"
        assert validate_against(self.SCHEMA, bad) != []

    def test_missing_question_rejected(self):
        bad = self._good_adr()
        del bad["question"]
        assert validate_against(self.SCHEMA, bad) != []

    def test_extra_property_rejected(self):
        bad = self._good_adr()
        bad["extra_field"] = "oops"
        assert validate_against(self.SCHEMA, bad) != []
