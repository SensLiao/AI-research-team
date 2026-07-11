"""Coverage tests for dormant agents (24 total).

For each agent, we either:
  A) Call the real deterministic tool core, validate the result schema via
     validate_artifact.validate_artifact, and add one edge case.
  B) Where no deterministic tool core exists (pure-LLM producer), build a
     representative payload and assert it validates against its payload schema
     via validate_artifact.validate_payload, AND assert the agent spec file
     exists and has parseable YAML frontmatter.
     These are labelled "spec/schema-only".

Already-covered agents (skipped — coverage exists elsewhere):
  baseline-comparison-auditor  -> test_baseline_audit.py
  claim-strength-calibrator    -> test_claim_calibration.py
  fairness-auditor             -> test_fairness_audit.py
  variance-analyzer            -> test_variance_audit.py
  visualization-auditor        -> test_viz_audit.py
  figure-vlm-critic            -> test_figure_critique_check.py
  repo-code-verifier           -> test_repo_verifier.py
  contribution-ledger-builder  -> test_check_contribution_binding.py
  statistics-power-auditor     -> test_power_audit* / test_stats*

Newly covered here (15 agents):
  code-implementer              - schema-only (pure-LLM implementer)
  failure-case-miner            - schema-only (pure-LLM miner)
  figure-generator              - schema-only (pure-LLM spec writer)
  patch-planner                 - schema-only (pure-LLM planner)
  repro-runner                  - schema-only (pure-LLM lock record)
  review-response-simulator     - schema-only (pure-LLM advisory)
  rq-architect                  - schema-only (pure-LLM chain)
  sandbox-runner                - schema-only (pure-LLM script emitter)
  synthesis-writer              - tool core: check_synthesis_fidelity
  threats-to-validity-writer    - tool core: check_threats_coverage
  unit-test-writer              - schema-only (pure-LLM writer)
  landscape-mapper              - schema-only (pure-LLM mapper)
  venue-review-configurator     - tool core: check_review_independence
  baseline-scout                - schema-only (panel_review lens=baseline-completeness)
  sub-domain-historian          - schema-only (panel_review lens=historical-context)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

from research_agent_teams.tools.validate_artifact import (
    SCHEMA_DIR,
    validate_artifact,
    validate_payload,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
SPEC_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _envelope(artifact_type: str, payload: dict) -> dict:
    """Minimal valid artifact envelope wrapping a payload."""
    return {
        "artifact_id": f"{artifact_type}-test-001",
        "artifact_type": artifact_type,
        "schema_version": "1.0.0",
        "created_by": "test",
        "created_at": "2026-06-16T00:00:00Z",
        "status": "draft",
        "payload": payload,
    }


def _assert_valid_envelope(artifact_type: str, payload: dict) -> None:
    """Assert that an enveloped artifact validates with zero errors."""
    artifact = _envelope(artifact_type, payload)
    errors = validate_artifact(artifact)
    assert errors == [], (
        f"Expected zero schema errors for {artifact_type!r}; got:\n" +
        "\n".join(errors)
    )


def _assert_valid_payload(artifact_type: str, payload: dict) -> None:
    """Assert that a payload-only dict validates against its registered schema."""
    errors = validate_payload(artifact_type, payload)
    assert errors == [], (
        f"Expected zero schema errors for payload type {artifact_type!r}; got:\n" +
        "\n".join(errors)
    )


def _assert_spec_exists(agent_name: str) -> None:
    """Assert that the agent spec file exists and has parseable YAML frontmatter."""
    spec_path = AGENTS_DIR / f"{agent_name}.md"
    assert spec_path.exists(), f"Agent spec file not found: {spec_path}"

    content = spec_path.read_text(encoding="utf-8")
    # Frontmatter is between the first two '---' delimiters
    parts = content.split("---", maxsplit=2)
    assert len(parts) >= 3, (
        f"{agent_name}.md has no parseable YAML frontmatter (expected '---...---' block)"
    )
    fm = yaml.safe_load(parts[1])
    assert isinstance(fm, dict), (
        f"{agent_name}.md frontmatter is not a dict: got {type(fm)}"
    )
    assert "name" in fm, f"{agent_name}.md frontmatter missing 'name' field"
    assert "spec_version" in fm, f"{agent_name}.md frontmatter missing 'spec_version'"
    assert SPEC_VERSION_RE.match(fm["spec_version"]), (
        f"{agent_name}.md spec_version {fm['spec_version']!r} is not semver"
    )


# ===========================================================================
# 1. code-implementer  (spec/schema-only)
# ===========================================================================

class TestCodeImplementer:
    """code-implementer produces implementation_record.
    Tool: pure Write/Edit over approved patch_plan — no deterministic Python core.
    Strategy: validate representative payloads against the registered schema.
    """

    def test_minimal_valid_implementation_record(self) -> None:
        payload = {
            "from_patch_plan_ref": "runs/test-run/evidence/EXECUTE/patch_plan.artifact.json",
            "files_changed": [],
        }
        _assert_valid_payload("implementation_record", payload)

    def test_full_implementation_record(self) -> None:
        payload = {
            "from_patch_plan_ref": "runs/test-run/evidence/EXECUTE/patch_plan.artifact.json",
            "condition_id": "method_sam",
            "summary": "Added LoRA adapter to encoder blocks",
            "files_changed": [
                {
                    "path": "src/model.py",
                    "change_type": "modified",
                    "notes": "Added LoRA attention adapter",  # 'notes' not 'description'
                }
            ],
            "out_of_scope_writes_blocked": False,
        }
        _assert_valid_payload("implementation_record", payload)

    def test_enveloped_implementation_record_validates(self) -> None:
        payload = {
            "from_patch_plan_ref": "patch_plan-2026-01-01.artifact.json",
            "files_changed": [
                {"path": "train.py", "change_type": "modified"}
            ],
        }
        _assert_valid_envelope("implementation_record", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("code-implementer")

    def test_empty_files_changed_is_valid(self) -> None:
        """files_changed may be empty (minItems:0) — no changes is a valid null patch."""
        payload = {
            "from_patch_plan_ref": "ref-001",
            "files_changed": [],
        }
        errors = validate_payload("implementation_record", payload)
        assert errors == []

    def test_missing_from_patch_plan_ref_is_invalid(self) -> None:
        """from_patch_plan_ref is required — omitting it must fail validation."""
        payload = {"files_changed": []}
        errors = validate_payload("implementation_record", payload)
        assert len(errors) >= 1


# ===========================================================================
# 2. failure-case-miner  (spec/schema-only)
# ===========================================================================

class TestFailureCaseMiner:
    """failure-case-miner produces failure_inventory.
    Tool: pure-LLM extraction from result artefacts.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_failure_inventory(self) -> None:
        payload = {
            "condition_id": "method_sam",
            "failures": [
                {
                    "type": "false_positive",
                    "description": "Liver region incorrectly segmented as spleen",
                }
            ],
        }
        _assert_valid_payload("failure_inventory", payload)

    def test_full_failure_inventory(self) -> None:
        payload = {
            "condition_id": "condition_baseline",
            "failures": [
                {
                    "type": "false_negative",
                    "description": "Small lesion missed on slice 47",
                    "case_ref": "result_summary-001.artifact.json",  # schema: case_ref not example_ref
                    "hypothesized_cause": "low contrast at boundary",  # schema field
                },
                {
                    "type": "boundary_error",
                    "description": "Boundary dilation at tissue interface",
                },
            ],
        }
        _assert_valid_payload("failure_inventory", payload)

    def test_enveloped_failure_inventory_validates(self) -> None:
        payload = {
            "condition_id": "test_condition",
            "failures": [{"type": "oom", "description": "GPU OOM on largest cases"}],
        }
        _assert_valid_envelope("failure_inventory", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("failure-case-miner")

    def test_empty_failures_is_invalid(self) -> None:
        """failures[] minItems:1 — empty list must fail schema validation."""
        payload = {"condition_id": "cond", "failures": []}
        errors = validate_payload("failure_inventory", payload)
        assert len(errors) >= 1

    def test_missing_condition_id_is_invalid(self) -> None:
        payload = {"failures": [{"type": "other", "description": "something"}]}
        errors = validate_payload("failure_inventory", payload)
        assert len(errors) >= 1


# ===========================================================================
# 3. figure-generator  (spec/schema-only)
# ===========================================================================

class TestFigureGenerator:
    """figure-generator produces figure_spec_bundle.
    Tool: pure-LLM figure specification writer.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_figure_spec_bundle(self) -> None:
        payload = {
            "figures": [
                {
                    "figure_id": "fig1_dice",
                    "figure_type": "bar",
                    "title": "Dice comparison: baseline vs method",
                    "data_source": "result_summary-001.artifact.json",
                }
            ]
        }
        _assert_valid_payload("figure_spec_bundle", payload)

    def test_multiple_figures_validates(self) -> None:
        payload = {
            "run_ref": "run-abc123",
            "figures": [
                {
                    "figure_id": "fig1_dice",
                    "figure_type": "bar",
                    "title": "Dice by condition",
                    "data_source": "result_summary.artifact.json",
                    # x_axis/y_axis are objects (or null), not plain strings
                    "x_axis": {"label": "condition"},
                    "y_axis": {"label": "Dice", "min": 0.0, "max": 1.0},
                    "conditions": ["baseline", "method_sam"],
                    "metrics": ["Dice"],
                },
                {
                    "figure_id": "fig2_iou_boxplot",
                    "figure_type": "boxplot",
                    "title": "IoU spread across seeds",
                    "data_source": "variance_report.artifact.json",
                    "notes": "3 seeds per condition",
                },
            ],
        }
        _assert_valid_payload("figure_spec_bundle", payload)

    def test_enveloped_figure_spec_bundle_validates(self) -> None:
        payload = {
            "figures": [
                {
                    "figure_id": "fig1",
                    "figure_type": "line",
                    "title": "Training curve",
                    "data_source": "journal_entry.artifact.json",
                }
            ]
        }
        _assert_valid_envelope("figure_spec_bundle", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("figure-generator")

    def test_empty_figures_is_invalid(self) -> None:
        """figures[] minItems:1 — empty list must fail."""
        payload = {"figures": []}
        errors = validate_payload("figure_spec_bundle", payload)
        assert len(errors) >= 1

    def test_invalid_figure_type_is_invalid(self) -> None:
        payload = {
            "figures": [
                {
                    "figure_id": "fig1",
                    "figure_type": "pie",  # not in enum
                    "title": "Pie chart",
                    "data_source": "somewhere",
                }
            ]
        }
        errors = validate_payload("figure_spec_bundle", payload)
        assert len(errors) >= 1


# ===========================================================================
# 4. patch-planner  (spec/schema-only)
# ===========================================================================

class TestPatchPlanner:
    """patch-planner produces patch_plan.
    Tool: pure-LLM planning — no deterministic Python core.
    Strategy: validate representative payloads.
    """

    def _one_change(self) -> dict:
        return {
            "path": "src/model.py",
            "change_type": "modify",
            "description": "Insert LoRA layers after attention projection",
        }

    def test_minimal_valid_patch_plan(self) -> None:
        # changes minItems:1 — need at least one change entry
        payload = {
            "status": "draft",
            "changes": [self._one_change()],
        }
        _assert_valid_payload("patch_plan", payload)

    def test_full_patch_plan(self) -> None:
        payload = {
            "status": "draft",
            "title": "Add LoRA adapter to vision encoder",
            "rationale": "Protocol requires LoRA fine-tuning per experiment_matrix condition",
            "from_protocol_ref": "protocol_spec-001.artifact.json",
            "changes": [
                {
                    "path": "src/model.py",
                    "change_type": "modify",
                    "description": "Insert LoRA layers after attention projection",
                    "snippet": "# lora adapter injected here",
                    "risk_note": "May increase VRAM by ~200MB",
                }
            ],
        }
        _assert_valid_payload("patch_plan", payload)

    def test_enveloped_patch_plan_validates(self) -> None:
        payload = {"status": "draft", "changes": [self._one_change()]}
        _assert_valid_envelope("patch_plan", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("patch-planner")

    def test_invalid_status_is_invalid(self) -> None:
        payload = {"status": "pending", "changes": [self._one_change()]}
        errors = validate_payload("patch_plan", payload)
        assert len(errors) >= 1

    def test_approved_status_is_valid(self) -> None:
        """approved is a valid lifecycle status for patch_plan."""
        payload = {"status": "approved", "changes": [self._one_change()]}
        errors = validate_payload("patch_plan", payload)
        assert errors == []

    def test_empty_changes_is_invalid(self) -> None:
        """changes minItems:1 — empty list must fail."""
        payload = {"status": "draft", "changes": []}
        errors = validate_payload("patch_plan", payload)
        assert len(errors) >= 1


# ===========================================================================
# 5. repro-runner  (spec/schema-only)
# ===========================================================================

class TestReproRunner:
    """repro-runner produces repro_record.
    Tool: pure-LLM provenance-lock record emitter.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_repro_record(self) -> None:
        payload = {
            "condition_id": "method_sam_lora",
            "seed": 42,
            "config_hash": "sha256:abcdef1234567890",
            "data_hash": "sha256:fedcba0987654321",
        }
        _assert_valid_payload("repro_record", payload)

    def test_full_repro_record(self) -> None:
        payload = {
            "condition_id": "baseline_unet",
            "from_run_record_ref": "run_record-001.artifact.json",
            "seed": 2025,
            "config_hash": "sha256:aaa111bbb222ccc333",
            "data_hash": "sha256:ddd444eee555fff666",
            "git_sha": "abc123def456",
            "repro_script": "python train.py --config config.yaml --seed 2025",
            "repro_passed": True,
            "notes": "Exact reproduction of Table 2 Row 3",  # 'notes' not 'environment'
        }
        _assert_valid_payload("repro_record", payload)

    def test_enveloped_repro_record_validates(self) -> None:
        payload = {
            "condition_id": "cond_01",
            "seed": 7,
            "config_hash": "sha256:x1",
            "data_hash": "sha256:y1",
        }
        _assert_valid_envelope("repro_record", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("repro-runner")

    def test_missing_seed_is_invalid(self) -> None:
        payload = {
            "condition_id": "c1",
            "config_hash": "sha256:x",
            "data_hash": "sha256:y",
        }
        errors = validate_payload("repro_record", payload)
        assert len(errors) >= 1

    def test_seed_must_be_integer(self) -> None:
        payload = {
            "condition_id": "c1",
            "seed": "42",  # string, not integer
            "config_hash": "sha256:x",
            "data_hash": "sha256:y",
        }
        errors = validate_payload("repro_record", payload)
        assert len(errors) >= 1


# ===========================================================================
# 6. review-response-simulator  (spec/schema-only)
# ===========================================================================

class TestReviewResponseSimulator:
    """review-response-simulator produces response_simulation.
    Tool: pure-LLM simulated reviewer attacks — advisory only.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_response_simulation(self) -> None:
        payload = {
            "attacks": [
                {
                    "attack_class": "insufficient_power",
                    "attack_text": "Three seeds is too few to claim statistical significance.",
                    "defensible": False,
                }
            ]
        }
        _assert_valid_payload("response_simulation", payload)

    def test_all_attack_classes_valid(self) -> None:
        attack_classes = [
            "insufficient_power",
            "unfair_baseline",
            "dataset_leakage",
            "overclaim",
            "eval_frame_mismatch",
            "out_of_scope",
            "reproducibility",
        ]
        for ac in attack_classes:
            payload = {
                "attacks": [
                    {
                        "attack_class": ac,
                        "attack_text": f"Reviewer says {ac}",
                        "defensible": True,
                    }
                ]
            }
            errors = validate_payload("response_simulation", payload)
            assert errors == [], f"attack_class {ac!r} should be valid; got: {errors}"

    def test_enveloped_response_simulation_validates(self) -> None:
        payload = {
            "attacks": [
                {
                    "attack_class": "reproducibility",
                    "attack_text": "Code is not released.",
                    "defensible": True,
                    "defense_argument": "Code will be released upon acceptance.",  # correct field name
                }
            ]
        }
        _assert_valid_envelope("response_simulation", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("review-response-simulator")

    def test_empty_attacks_is_valid(self) -> None:
        """attacks[] has no minItems — an empty simulation is permitted."""
        payload = {"attacks": []}
        errors = validate_payload("response_simulation", payload)
        assert errors == []

    def test_defensible_must_be_boolean(self) -> None:
        payload = {
            "attacks": [
                {
                    "attack_class": "overclaim",
                    "attack_text": "result is overclaimed",
                    "defensible": "yes",  # string, not boolean
                }
            ]
        }
        errors = validate_payload("response_simulation", payload)
        assert len(errors) >= 1


# ===========================================================================
# 7. rq-architect  (spec/schema-only)
# ===========================================================================

class TestRqArchitect:
    """rq-architect produces rq_hypothesis_chain.
    Tool: pure-LLM hypothesis chain constructor — no deterministic core.
    Strategy: validate representative payloads.
    """

    def _hypothesis(self, hid: str, statement: str, pred: str, evidence: list) -> dict:
        """Helper — evidence_needed is an array of strings (minItems:1)."""
        return {
            "hypothesis_id": hid,
            "statement": statement,
            "falsifiable_prediction": pred,
            "evidence_needed": evidence,
        }

    def test_minimal_valid_rq_hypothesis_chain(self) -> None:
        payload = {
            "research_question": "Does LoRA fine-tuning improve SAM on CBCT data?",
            "hypotheses": [
                self._hypothesis(
                    "H1",
                    "LoRA reduces domain gap between natural and CBCT images",
                    "Dice >= 0.80 on in-distribution CBCT test set",
                    ["Dice score on held-out CBCT test set"],  # must be array
                )
            ],
        }
        _assert_valid_payload("rq_hypothesis_chain", payload)

    def test_multi_hypothesis_chain_validates(self) -> None:
        payload = {
            "research_question": "Can SAM generalize to medical 3D segmentation?",
            "hypotheses": [
                self._hypothesis(
                    "H1",
                    "2D slice-wise SAM can segment 3D volumes",
                    "Dice >= 0.75 per slice",
                    ["per-slice Dice on ToothFairy3 test set"],
                ),
                self._hypothesis(
                    "H2",
                    "Prompt engineering improves 3D coherence",
                    "3D IoU improves by >= 0.05 with centroid prompts",
                    ["volumetric IoU with centroid prompts", "volumetric IoU with random prompts"],
                ),
            ],
        }
        _assert_valid_payload("rq_hypothesis_chain", payload)

    def test_enveloped_rq_hypothesis_chain_validates(self) -> None:
        payload = {
            "research_question": "Can transfer learning reduce annotation cost?",
            "hypotheses": [
                self._hypothesis(
                    "H1",
                    "Pre-trained features reduce labeled data requirements",
                    "Similar Dice with 10x fewer annotations",
                    ["Dice vs annotation budget curve"],
                )
            ],
        }
        _assert_valid_envelope("rq_hypothesis_chain", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("rq-architect")

    def test_empty_hypotheses_is_invalid(self) -> None:
        """hypotheses minItems:1 — empty chain must fail validation."""
        payload = {
            "research_question": "A question",
            "hypotheses": [],
        }
        errors = validate_payload("rq_hypothesis_chain", payload)
        assert len(errors) >= 1

    def test_missing_falsifiable_prediction_is_invalid(self) -> None:
        payload = {
            "research_question": "RQ?",
            "hypotheses": [
                {
                    "hypothesis_id": "H1",
                    "statement": "some statement",
                    # missing falsifiable_prediction (required)
                    "evidence_needed": ["some evidence"],
                }
            ],
        }
        errors = validate_payload("rq_hypothesis_chain", payload)
        assert len(errors) >= 1

    def test_evidence_needed_must_be_array(self) -> None:
        """evidence_needed is an array — a plain string must fail."""
        payload = {
            "research_question": "RQ?",
            "hypotheses": [
                {
                    "hypothesis_id": "H1",
                    "statement": "some statement",
                    "falsifiable_prediction": "pred",
                    "evidence_needed": "a single string",  # wrong type
                }
            ],
        }
        errors = validate_payload("rq_hypothesis_chain", payload)
        assert len(errors) >= 1


# ===========================================================================
# 8. sandbox-runner  (spec/schema-only)
# ===========================================================================

class TestSandboxRunner:
    """sandbox-runner produces sandbox_report.
    Tool: pure-LLM smoke script emitter — fenced, cannot run Bash.
    smoke_passed is nullable until server executes.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_sandbox_report(self) -> None:
        payload = {
            "condition_id": "method_sam_lora",
            "smoke_script": "import torch\nprint('GPU:', torch.cuda.is_available())\n",
        }
        _assert_valid_payload("sandbox_report", payload)

    def test_full_sandbox_report_with_null_passed(self) -> None:
        payload = {
            "condition_id": "baseline_unet",
            "from_implementation_ref": "implementation_record-001.artifact.json",
            "smoke_script": "python -c 'import model; model.sanity_check()'",
            "invoke_command": "bash smoke_test.sh",
            "smoke_passed": None,  # null until server runs it
            "notes": "Pending server execution",
        }
        _assert_valid_payload("sandbox_report", payload)

    def test_sandbox_report_with_passed_true(self) -> None:
        payload = {
            "condition_id": "cond_01",
            "smoke_script": "print('ok')",
            "smoke_passed": True,
        }
        _assert_valid_payload("sandbox_report", payload)

    def test_enveloped_sandbox_report_validates(self) -> None:
        payload = {
            "condition_id": "test_cond",
            "smoke_script": "import os; print(os.getcwd())",
        }
        _assert_valid_envelope("sandbox_report", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("sandbox-runner")

    def test_missing_smoke_script_is_invalid(self) -> None:
        """smoke_script is required — missing it must fail."""
        payload = {"condition_id": "cond_01"}
        errors = validate_payload("sandbox_report", payload)
        assert len(errors) >= 1


# ===========================================================================
# 9. synthesis-writer  — tool core: check_synthesis_fidelity
# ===========================================================================

class TestSynthesisWriter:
    """synthesis-writer produces synthesis_text.
    Tool core: check_synthesis_fidelity (check that prose matches structured verdict).
    Tests: call real tool, validate payload schema, add edge case.
    """

    def _panel_synthesis(self, verdict: str) -> dict:
        return {
            "verdict": verdict,
            "violations": [],
            "addressed_blocks": [],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
        }

    def _synthesis_text(self, structured: str, prose: str, body: str = "detailed body text") -> dict:
        return {
            "structured_verdict": structured,
            "prose_verdict_word": prose,
            "body": body,
        }

    # --- tool core ---

    def test_approve_approve_is_consistent(self) -> None:
        from research_agent_teams.tools.check_synthesis_fidelity import (
            check_synthesis_fidelity,
        )

        ps = self._panel_synthesis("APPROVE")
        st = self._synthesis_text("APPROVE", "approve")
        violations = check_synthesis_fidelity(ps, st)
        assert violations == []

    def test_block_block_is_consistent(self) -> None:
        from research_agent_teams.tools.check_synthesis_fidelity import (
            check_synthesis_fidelity,
        )

        ps = self._panel_synthesis("BLOCK")
        st = self._synthesis_text("BLOCK", "block")
        violations = check_synthesis_fidelity(ps, st)
        assert violations == []

    def test_block_no_concerns_prose_is_a_violation(self) -> None:
        """The classic failure mode: BLOCK structure + 'no concerns' prose → violation."""
        from research_agent_teams.tools.check_synthesis_fidelity import (
            check_synthesis_fidelity,
        )

        ps = self._panel_synthesis("BLOCK")
        st = self._synthesis_text("BLOCK", "no concerns")
        violations = check_synthesis_fidelity(ps, st)
        assert len(violations) >= 1

    def test_approve_reject_prose_is_a_violation(self) -> None:
        """APPROVE structure + 'reject' prose → violation."""
        from research_agent_teams.tools.check_synthesis_fidelity import (
            check_synthesis_fidelity,
            build_report,
        )

        ps = self._panel_synthesis("APPROVE")
        st = self._synthesis_text("APPROVE", "reject")
        violations = check_synthesis_fidelity(ps, st)
        assert len(violations) >= 1
        report = build_report(ps, st)
        assert report["verdict"] == "BLOCK"

    # --- schema validation ---

    def test_valid_synthesis_text_payload(self) -> None:
        payload = self._synthesis_text("APPROVE", "approve")
        _assert_valid_payload("synthesis_text", payload)

    def test_enveloped_synthesis_text_validates(self) -> None:
        payload = self._synthesis_text("BLOCK", "block", body="The panel BLOCKS due to missing power analysis.")
        _assert_valid_envelope("synthesis_text", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("synthesis-writer")

    def test_missing_structured_verdict_is_invalid(self) -> None:
        payload = {"prose_verdict_word": "approve", "body": "body"}
        errors = validate_payload("synthesis_text", payload)
        assert len(errors) >= 1

    def test_invalid_structured_verdict_enum_is_invalid(self) -> None:
        payload = {
            "structured_verdict": "PASS",  # not in enum [APPROVE, BLOCK]
            "prose_verdict_word": "pass",
            "body": "body",
        }
        errors = validate_payload("synthesis_text", payload)
        assert len(errors) >= 1


# ===========================================================================
# 10. threats-to-validity-writer  — tool core: check_threats_coverage
# ===========================================================================

class TestThreatsToValidityWriter:
    """threats-to-validity-writer produces threats_report.
    Tool core: check_threats_coverage (all four validity dimensions required).
    Tests: call real tool, validate payload schema, edge cases.
    """

    def _all_four_threats(self) -> list:
        return [
            {"validity_dimension": "internal", "threat_text": "Instrumentation bias", "mitigation": "Double-blinded annotation"},
            {"validity_dimension": "external", "threat_text": "Single-site dataset", "mitigation": "Multi-site validation planned"},
            {"validity_dimension": "construct", "threat_text": "Dice may not capture topology", "mitigation": "Added HD95 metric"},
            {"validity_dimension": "statistical", "threat_text": "Only 3 seeds", "mitigation": "Wilcoxon test at p<0.05"},
        ]

    # --- tool core ---

    def test_all_four_dimensions_passes(self) -> None:
        from research_agent_teams.tools.check_threats_coverage import check_threats_coverage

        report = {"threats": self._all_four_threats()}
        violations = check_threats_coverage(report)
        assert violations == []

    def test_missing_statistical_dimension_flagged(self) -> None:
        from research_agent_teams.tools.check_threats_coverage import check_threats_coverage

        threats = [t for t in self._all_four_threats() if t["validity_dimension"] != "statistical"]
        report = {"threats": threats}
        violations = check_threats_coverage(report)
        assert len(violations) == 1
        assert "statistical" in violations[0]

    def test_empty_threats_all_four_missing(self) -> None:
        from research_agent_teams.tools.check_threats_coverage import check_threats_coverage, build_report

        report = {"threats": []}
        violations = check_threats_coverage(report)
        assert len(violations) == 4
        result = build_report(report)
        assert result["verdict"] == "BLOCK"

    def test_build_report_pass_with_all_four(self) -> None:
        from research_agent_teams.tools.check_threats_coverage import build_report

        report = {"threats": self._all_four_threats()}
        result = build_report(report)
        assert result["verdict"] == "PASS"
        assert result["missing_dimensions"] == []

    # --- schema validation ---

    def test_valid_threats_report_payload(self) -> None:
        payload = {"threats": self._all_four_threats()}
        _assert_valid_payload("threats_report", payload)

    def test_enveloped_threats_report_validates(self) -> None:
        payload = {"threats": self._all_four_threats()}
        _assert_valid_envelope("threats_report", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("threats-to-validity-writer")

    def test_invalid_validity_dimension_enum_is_invalid(self) -> None:
        payload = {
            "threats": [
                {
                    "validity_dimension": "philosophical",  # not in enum
                    "threat_text": "epistemological doubt",
                    "mitigation": "none",
                }
            ]
        }
        errors = validate_payload("threats_report", payload)
        assert len(errors) >= 1

    def test_empty_threats_array_is_invalid_schema(self) -> None:
        """threats[] minItems:1 — empty must fail schema."""
        payload = {"threats": []}
        errors = validate_payload("threats_report", payload)
        assert len(errors) >= 1


# ===========================================================================
# 11. unit-test-writer  (spec/schema-only)
# ===========================================================================

class TestUnitTestWriter:
    """unit-test-writer produces test_suite_record.
    Tool: pure Write to test files — no deterministic Python core.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_test_suite_record(self) -> None:
        payload = {
            "test_targets": ["loader"],
            "test_files": [],
        }
        _assert_valid_payload("test_suite_record", payload)

    def test_full_test_suite_record(self) -> None:
        payload = {
            "from_implementation_ref": "implementation_record-001.artifact.json",
            "test_targets": ["loader", "metric", "loss"],
            "test_files": [
                {"path": "tests/test_loader.py", "n_tests": 5, "covers": ["loader"]},  # covers is array
                {"path": "tests/test_metric.py", "n_tests": 8, "covers": ["metric"]},
            ],
        }
        _assert_valid_payload("test_suite_record", payload)

    def test_enveloped_test_suite_record_validates(self) -> None:
        payload = {
            "test_targets": ["prompt"],
            "test_files": [{"path": "tests/test_prompt.py"}],
        }
        _assert_valid_envelope("test_suite_record", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("unit-test-writer")

    def test_empty_test_targets_is_invalid(self) -> None:
        """test_targets minItems:1 — empty list must fail."""
        payload = {"test_targets": [], "test_files": []}
        errors = validate_payload("test_suite_record", payload)
        assert len(errors) >= 1

    def test_multiple_test_targets_all_strings(self) -> None:
        payload = {
            "test_targets": ["loader", "metric", "loss", "prompt"],
            "test_files": [],
        }
        errors = validate_payload("test_suite_record", payload)
        assert errors == []


# ===========================================================================
# 12. landscape-mapper  (spec/schema-only)
# ===========================================================================

class TestLandscapeMapper:
    """landscape-mapper produces landscape_map.
    Tool: pure-LLM literature landscape mapping.
    Strategy: validate representative payloads.
    """

    def test_minimal_valid_landscape_map(self) -> None:
        # coverage_gaps items are objects with required gap_id + description
        payload = {
            "domain_query": "medical image segmentation with SAM",
            "methods": [],
            "coverage_gaps": [
                {"gap_id": "G1", "description": "Tooth segmentation from CBCT with SAM not well studied"}
            ],
        }
        _assert_valid_payload("landscape_map", payload)

    def test_full_landscape_map(self) -> None:
        payload = {
            "domain_query": "SAM for 3D medical segmentation",
            "methods": [
                {
                    "method_id": "med_sam",
                    "name": "MedSAM",
                    "covered_by_sources": ["arxiv:2304.12306"],
                    "representative_result": "Dice=0.85 on liver",
                    "notes": "Adapted SAM for medical images",
                },
                {
                    "method_id": "sam_med3d",
                    "name": "SAM-Med3D",
                    "covered_by_sources": ["arxiv:2310.15161"],
                    "notes": "3D volumetric extension of SAM",
                },
            ],
            "datasets_in_landscape": [
                # schema: datasets_in_landscape (not datasets), items: dataset_ref + name
                {"dataset_ref": "zenodo:toothfairy3", "name": "ToothFairy3", "usage_count": 3},
            ],
            "coverage_gaps": [
                # severity enum: critical/major/minor (not high/medium/low)
                {"gap_id": "G1", "description": "No work on LoRA fine-tuning of SAM for tooth anatomy", "gap_kind": "method", "severity": "critical"},
                {"gap_id": "G2", "description": "3D coherence not evaluated in slice-wise SAM papers", "severity": "major"},
            ],
        }
        _assert_valid_payload("landscape_map", payload)

    def test_enveloped_landscape_map_validates(self) -> None:
        payload = {
            "domain_query": "LoRA in vision transformers",
            "methods": [
                {
                    "method_id": "lora",
                    "name": "LoRA",
                    "covered_by_sources": ["arxiv:2106.09685"],
                }
            ],
            "coverage_gaps": [
                {"gap_id": "G1", "description": "LoRA in SAM not fully explored"}
            ],
        }
        _assert_valid_envelope("landscape_map", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("landscape-mapper")

    def test_empty_coverage_gaps_is_valid(self) -> None:
        """coverage_gaps has no minItems constraint — empty list is allowed."""
        payload = {
            "domain_query": "mature field",
            "methods": [],
            "coverage_gaps": [],
        }
        errors = validate_payload("landscape_map", payload)
        assert errors == []

    def test_missing_coverage_gaps_is_invalid(self) -> None:
        """coverage_gaps is required — omitting it must fail."""
        payload = {
            "domain_query": "some domain",
            "methods": [],
        }
        errors = validate_payload("landscape_map", payload)
        assert len(errors) >= 1


# ===========================================================================
# 13. venue-review-configurator  — tool core: check_review_independence
# ===========================================================================

class TestVenueReviewConfigurator:
    """venue-review-configurator produces review_config.
    Tool core: check_review_independence (lenses must be independent and anchored).
    Tests: call real tool, validate payload schema, edge cases.
    """

    def _lens(self, lens: str, anchor: str, agent: str = "some-agent") -> dict:
        return {"lens": lens, "anchor": anchor, "reviewer_agent": agent}

    def _valid_config(self) -> dict:
        return {
            "run_ref": "run-abc",
            "lenses": [
                self._lens("methodology", "statistical design in §3.2", "methodology-reviewer"),
                self._lens("domain", "Dice metric per CV profile", "domain-reviewer"),
            ],
            "synthesis_mandate": "Synthesize all findings into a panel verdict.",
        }

    # --- tool core ---

    def test_clean_independent_config_has_no_violations(self) -> None:
        from research_agent_teams.tools.check_review_independence import check_review_independence

        config = self._valid_config()
        violations = check_review_independence(config)
        assert violations == []

    def test_duplicate_lens_is_a_violation(self) -> None:
        from research_agent_teams.tools.check_review_independence import check_review_independence

        config = {
            "run_ref": "run-001",
            "lenses": [
                self._lens("methodology", "section §3", "agent-a"),
                self._lens("methodology", "section §4", "agent-b"),  # duplicate lens
            ],
            "synthesis_mandate": "mandate",
        }
        violations = check_review_independence(config)
        assert len(violations) >= 1

    def test_empty_anchor_is_a_violation(self) -> None:
        from research_agent_teams.tools.check_review_independence import check_review_independence

        config = {
            "run_ref": "run-002",
            "lenses": [
                self._lens("methodology", "§3.2 statistical design", "agent-a"),
                self._lens("domain", "", "agent-b"),  # empty anchor
            ],
            "synthesis_mandate": "mandate",
        }
        violations = check_review_independence(config)
        assert len(violations) >= 1

    def test_single_lens_is_invalid(self) -> None:
        """Independence requires >= 2 distinct lenses."""
        from research_agent_teams.tools.check_review_independence import build_report

        config = {
            "run_ref": "run-003",
            "lenses": [self._lens("methodology", "anchor text", "agent-a")],
            "synthesis_mandate": "mandate",
        }
        result = build_report(config)
        assert result["valid"] is False

    def test_three_distinct_lenses_is_valid(self) -> None:
        from research_agent_teams.tools.check_review_independence import check_review_independence

        config = {
            "run_ref": "run-004",
            "lenses": [
                self._lens("methodology", "§3 stats", "methodology-reviewer"),
                self._lens("domain", "§4 medical context", "domain-reviewer"),
                self._lens("adversarial", "§5 baseline fairness check", "baseline-scout"),
            ],
            "synthesis_mandate": "Synthesize all.",
        }
        violations = check_review_independence(config)
        assert violations == []

    # --- schema validation ---

    def test_valid_review_config_payload(self) -> None:
        _assert_valid_payload("review_config", self._valid_config())

    def test_enveloped_review_config_validates(self) -> None:
        _assert_valid_envelope("review_config", self._valid_config())

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("venue-review-configurator")

    def test_invalid_lens_enum_is_invalid(self) -> None:
        config = {
            "run_ref": "run-005",
            "lenses": [
                {"lens": "statistical", "anchor": "some anchor", "reviewer_agent": "a"},  # not in enum
                {"lens": "methodology", "anchor": "other anchor", "reviewer_agent": "b"},
            ],
            "synthesis_mandate": "mandate",
        }
        errors = validate_payload("review_config", config)
        assert len(errors) >= 1

    def test_missing_synthesis_mandate_is_invalid(self) -> None:
        config = {
            "run_ref": "run-006",
            "lenses": [
                self._lens("methodology", "anchor-a", "agent-a"),
                self._lens("domain", "anchor-b", "agent-b"),
            ],
            # missing synthesis_mandate (required)
        }
        errors = validate_payload("review_config", config)
        assert len(errors) >= 1


# ===========================================================================
# 14. baseline-scout  (spec/schema-only — panel_review with baseline-completeness lens)
# ===========================================================================

class TestBaselineScout:
    """baseline-scout produces panel_review (lens=baseline-completeness).
    Tool: pure-LLM reviewer role — no deterministic Python core.
    Strategy: validate representative payloads against panel_review schema.
    """

    def test_minimal_valid_baseline_scout_panel_review(self) -> None:
        payload = {
            "lens": "baseline-completeness",
            "findings": [],
        }
        _assert_valid_payload("panel_review", payload)

    def test_panel_review_with_block_finding(self) -> None:
        # When any finding has severity=BLOCK, overall_verdict=BLOCK is required (allOf constraint)
        payload = {
            "lens": "baseline-completeness",
            "overall_verdict": "BLOCK",
            "findings": [
                {
                    "anchor": "Table 2: reported baselines",
                    "evidence": "SAM-Med3D (MICCAI 2023) is missing — it is a direct SOTA on this benchmark",
                    "severity": "BLOCK",
                    "finding_id": "BC-001",
                }
            ],
        }
        _assert_valid_payload("panel_review", payload)

    def test_panel_review_with_warn_finding(self) -> None:
        # WARN (not BLOCK) — overall_verdict not required
        payload = {
            "lens": "baseline-completeness",
            "findings": [
                {
                    "anchor": "§3.1 Related Work",
                    "evidence": "MedSAM is cited but not included as baseline",
                    "severity": "WARN",
                }
            ],
        }
        _assert_valid_payload("panel_review", payload)

    def test_enveloped_baseline_scout_review_validates(self) -> None:
        payload = {
            "lens": "baseline-completeness",
            "findings": [
                {
                    "anchor": "Table 3",
                    "evidence": "All major SOTA baselines are included",
                    "severity": "NOTE",
                }
            ],
        }
        _assert_valid_envelope("panel_review", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("baseline-scout")

    def test_wrong_lens_for_methodology_reviewer_is_valid_schema(self) -> None:
        """The panel_review schema accepts all lens enum values."""
        payload = {"lens": "methodology", "findings": []}
        errors = validate_payload("panel_review", payload)
        assert errors == []

    def test_invalid_severity_enum_is_invalid(self) -> None:
        payload = {
            "lens": "baseline-completeness",
            "findings": [
                {
                    "anchor": "Table 2",
                    "evidence": "missing baseline X",
                    "severity": "CRITICAL",  # not in enum [BLOCK, WARN, NOTE]
                }
            ],
        }
        errors = validate_payload("panel_review", payload)
        assert len(errors) >= 1


# ===========================================================================
# 15. sub-domain-historian  (spec/schema-only — panel_review with historical-context lens)
# ===========================================================================

class TestSubDomainHistorian:
    """sub-domain-historian produces panel_review (lens=historical-context).
    Tool: pure-LLM reviewer role — no deterministic Python core.
    Strategy: validate representative payloads against panel_review schema.
    """

    def test_minimal_valid_historian_panel_review(self) -> None:
        payload = {
            "lens": "historical-context",
            "findings": [],
        }
        _assert_valid_payload("panel_review", payload)

    def test_panel_review_with_block_finding(self) -> None:
        # When any finding has severity=BLOCK, overall_verdict=BLOCK is required
        payload = {
            "lens": "historical-context",
            "overall_verdict": "BLOCK",
            "findings": [
                {
                    "anchor": "§2 Introduction",
                    "evidence": (
                        "The paper claims novelty over 'few works addressing 3D tooth segmentation' "
                        "but ignores the ToothFairy1/2 challenges (2022-2023) and PointSAM3D (2024)"
                    ),
                    "severity": "BLOCK",
                    "finding_id": "HC-001",
                }
            ],
        }
        _assert_valid_payload("panel_review", payload)

    def test_panel_review_all_clear(self) -> None:
        """A panel review with NOTE-level findings (no BLOCK) — overall_verdict not required."""
        payload = {
            "lens": "historical-context",
            "findings": [
                {
                    "anchor": "§2 Related Work trajectory",
                    "evidence": "The paper correctly situates itself relative to the 2020-2024 arc",
                    "severity": "NOTE",
                }
            ],
        }
        _assert_valid_payload("panel_review", payload)

    def test_enveloped_historian_review_validates(self) -> None:
        payload = {
            "lens": "historical-context",
            "findings": [],
        }
        _assert_valid_envelope("panel_review", payload)

    def test_spec_exists_and_is_parseable(self) -> None:
        _assert_spec_exists("sub-domain-historian")

    def test_missing_findings_is_invalid(self) -> None:
        """findings field is required in panel_review schema."""
        payload = {"lens": "historical-context"}
        errors = validate_payload("panel_review", payload)
        assert len(errors) >= 1

    def test_finding_missing_anchor_is_invalid(self) -> None:
        """Each finding requires anchor, evidence, severity."""
        payload = {
            "lens": "historical-context",
            "findings": [
                {
                    # missing anchor (required)
                    "evidence": "some evidence",
                    "severity": "NOTE",
                }
            ],
        }
        errors = validate_payload("panel_review", payload)
        assert len(errors) >= 1
