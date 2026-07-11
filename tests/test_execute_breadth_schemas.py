"""Schema tests for SUB-TEAM 2.2 — EXECUTE breadth (6 schemas).

Each schema gets:
  - a well-formed sample that MUST validate (errors == [])
  - one or more crafted-bad samples that MUST be rejected (errors != [])

All tests use validate_against(schema_filename, instance) directly — they work
before PAYLOAD_SCHEMAS registration (the main-thread integration step).

Schemas tested:
  patch_plan, implementation_record, test_suite_record,
  sandbox_report, triage_report, repro_record
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against


# ===========================================================================
# 1. patch_plan
# ===========================================================================

_GOOD_PATCH_PLAN = {
    "status": "draft",
    "title": "Add LoRA adapter to encoder",
    "rationale": "Experiment condition c1 requires a low-rank adapter layer.",
    "from_protocol_ref": "runs/r01/evidence/EXECUTE/protocol-spec.artifact.json",
    "changes": [
        {
            "path": "src/model/encoder.py",
            "change_type": "modify",
            "description": "Insert LoRA adapter after the last attention layer.",
            "snippet": "encoder.add_module('lora', LoRALayer(rank=8))",
            "risk_note": "shared by all conditions — change carefully",
        }
    ],
    "review_notes": None,
}


def test_patch_plan_wellformed_validates():
    assert validate_against("patch_plan.schema.json", _GOOD_PATCH_PLAN) == []


def test_patch_plan_empty_changes_rejected():
    bad = {**_GOOD_PATCH_PLAN, "changes": []}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_missing_changes_rejected():
    bad = {k: v for k, v in _GOOD_PATCH_PLAN.items() if k != "changes"}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_missing_status_rejected():
    bad = {k: v for k, v in _GOOD_PATCH_PLAN.items() if k != "status"}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_invalid_status_rejected():
    bad = {**_GOOD_PATCH_PLAN, "status": "pending"}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_change_missing_path_rejected():
    bad_change = {"change_type": "modify", "description": "no path here"}
    bad = {**_GOOD_PATCH_PLAN, "changes": [bad_change]}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_change_empty_path_rejected():
    bad_change = {"path": "", "change_type": "create", "description": "empty path"}
    bad = {**_GOOD_PATCH_PLAN, "changes": [bad_change]}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_change_invalid_type_rejected():
    bad_change = {
        "path": "src/foo.py",
        "change_type": "rewrite",  # not in enum
        "description": "full rewrite",
    }
    bad = {**_GOOD_PATCH_PLAN, "changes": [bad_change]}
    assert validate_against("patch_plan.schema.json", bad) != []


def test_patch_plan_approved_status_validates():
    ok = {**_GOOD_PATCH_PLAN, "status": "approved"}
    assert validate_against("patch_plan.schema.json", ok) == []


def test_patch_plan_additional_property_rejected():
    bad = {**_GOOD_PATCH_PLAN, "unexpected_field": "oops"}
    assert validate_against("patch_plan.schema.json", bad) != []


# ===========================================================================
# 2. implementation_record
# ===========================================================================

_GOOD_IMPL_RECORD = {
    "from_patch_plan_ref": "runs/r01/evidence/EXECUTE/patch-plan.artifact.json",
    "condition_id": "c1",
    "summary": "Inserted LoRA adapter into encoder; 12 lines added.",
    "files_changed": [
        {
            "path": "src/model/encoder.py",
            "change_type": "modified",
            "lines_added": 12,
            "lines_removed": 0,
            "notes": "Adapter inserted after existing attention block.",
        }
    ],
    "out_of_scope_writes_blocked": False,
    "git_sha": None,
    "caveats": [],
}


def test_implementation_record_wellformed_validates():
    assert validate_against("implementation_record.schema.json", _GOOD_IMPL_RECORD) == []


def test_implementation_record_missing_patch_plan_ref_rejected():
    bad = {k: v for k, v in _GOOD_IMPL_RECORD.items() if k != "from_patch_plan_ref"}
    assert validate_against("implementation_record.schema.json", bad) != []


def test_implementation_record_empty_patch_plan_ref_rejected():
    bad = {**_GOOD_IMPL_RECORD, "from_patch_plan_ref": ""}
    assert validate_against("implementation_record.schema.json", bad) != []


def test_implementation_record_missing_files_changed_rejected():
    bad = {k: v for k, v in _GOOD_IMPL_RECORD.items() if k != "files_changed"}
    assert validate_against("implementation_record.schema.json", bad) != []


def test_implementation_record_bad_change_type_rejected():
    bad_file = {"path": "src/foo.py", "change_type": "touched"}  # not in enum
    bad = {**_GOOD_IMPL_RECORD, "files_changed": [bad_file]}
    assert validate_against("implementation_record.schema.json", bad) != []


def test_implementation_record_additional_property_rejected():
    bad = {**_GOOD_IMPL_RECORD, "surprise": True}
    assert validate_against("implementation_record.schema.json", bad) != []


# ===========================================================================
# 3. test_suite_record
# ===========================================================================

_GOOD_TEST_SUITE = {
    "from_implementation_ref": "runs/r01/evidence/EXECUTE/impl-record.artifact.json",
    "test_targets": ["loader", "metric"],
    "test_files": [
        {
            "path": "runs/r01/evidence/EXECUTE/tests/test_loader.py",
            "n_tests": 4,
            "covers": ["loader"],
        },
        {
            "path": "runs/r01/evidence/EXECUTE/tests/test_metric.py",
            "n_tests": 3,
            "covers": ["metric"],
        },
    ],
    "coverage_pct": None,
    "notes": "coverage_pct null until externally run",
}


def test_test_suite_record_wellformed_validates():
    assert validate_against("test_suite_record.schema.json", _GOOD_TEST_SUITE) == []


def test_test_suite_record_missing_test_targets_rejected():
    bad = {k: v for k, v in _GOOD_TEST_SUITE.items() if k != "test_targets"}
    assert validate_against("test_suite_record.schema.json", bad) != []


def test_test_suite_record_empty_test_targets_rejected():
    bad = {**_GOOD_TEST_SUITE, "test_targets": []}
    assert validate_against("test_suite_record.schema.json", bad) != []


def test_test_suite_record_missing_test_files_rejected():
    bad = {k: v for k, v in _GOOD_TEST_SUITE.items() if k != "test_files"}
    assert validate_against("test_suite_record.schema.json", bad) != []


def test_test_suite_record_coverage_out_of_range_rejected():
    bad = {**_GOOD_TEST_SUITE, "coverage_pct": 101.0}
    assert validate_against("test_suite_record.schema.json", bad) != []


def test_test_suite_record_file_missing_path_rejected():
    bad_file = {"n_tests": 2, "covers": ["loader"]}  # no path
    bad = {**_GOOD_TEST_SUITE, "test_files": [bad_file]}
    assert validate_against("test_suite_record.schema.json", bad) != []


def test_test_suite_record_additional_property_rejected():
    bad = {**_GOOD_TEST_SUITE, "extra": "oops"}
    assert validate_against("test_suite_record.schema.json", bad) != []


# ===========================================================================
# 4. sandbox_report
# ===========================================================================

_GOOD_SANDBOX_REPORT = {
    "condition_id": "c1",
    "from_implementation_ref": "runs/r01/evidence/EXECUTE/impl-record.artifact.json",
    "smoke_script": (
        "import torch\n"
        "from src.model import build_model\n"
        "model = build_model(rank=8)\n"
        "x = torch.randn(2, 3, 224, 224)\n"
        "out = model(x)\n"
        "assert out.shape[0] == 2\n"
        "print('smoke PASS')\n"
    ),
    "invoke_command": "python smoke_test_c1.py",
    "smoke_passed": None,
    "exit_code": None,
    "stdout_tail": None,
    "stderr_tail": None,
    "notes": "Requires no GPU; runs on CPU in <30s.",
}


def test_sandbox_report_wellformed_validates():
    assert validate_against("sandbox_report.schema.json", _GOOD_SANDBOX_REPORT) == []


def test_sandbox_report_null_smoke_passed_validates():
    """smoke_passed=null is the canonical pre-run state — must be valid."""
    ok = {**_GOOD_SANDBOX_REPORT, "smoke_passed": None}
    assert validate_against("sandbox_report.schema.json", ok) == []


def test_sandbox_report_boolean_smoke_passed_validates():
    """After out-of-band execution, smoke_passed may be true or false."""
    ok_true = {**_GOOD_SANDBOX_REPORT, "smoke_passed": True}
    ok_false = {**_GOOD_SANDBOX_REPORT, "smoke_passed": False}
    assert validate_against("sandbox_report.schema.json", ok_true) == []
    assert validate_against("sandbox_report.schema.json", ok_false) == []


def test_sandbox_report_missing_condition_id_rejected():
    bad = {k: v for k, v in _GOOD_SANDBOX_REPORT.items() if k != "condition_id"}
    assert validate_against("sandbox_report.schema.json", bad) != []


def test_sandbox_report_missing_smoke_script_rejected():
    bad = {k: v for k, v in _GOOD_SANDBOX_REPORT.items() if k != "smoke_script"}
    assert validate_against("sandbox_report.schema.json", bad) != []


def test_sandbox_report_empty_smoke_script_rejected():
    bad = {**_GOOD_SANDBOX_REPORT, "smoke_script": ""}
    assert validate_against("sandbox_report.schema.json", bad) != []


def test_sandbox_report_string_smoke_passed_rejected():
    """smoke_passed must be boolean or null — never a string."""
    bad = {**_GOOD_SANDBOX_REPORT, "smoke_passed": "yes"}
    assert validate_against("sandbox_report.schema.json", bad) != []


def test_sandbox_report_additional_property_rejected():
    bad = {**_GOOD_SANDBOX_REPORT, "extra_field": 42}
    assert validate_against("sandbox_report.schema.json", bad) != []


# ===========================================================================
# 5. triage_report
# ===========================================================================

_GOOD_TRIAGE = {
    "condition_id": "c1",
    "from_sandbox_ref": "runs/r01/evidence/EXECUTE/sandbox-report.artifact.json",
    "error_class": "shape",
    "stack_trace_excerpt": (
        "RuntimeError: mat1 and mat2 shapes cannot be multiplied (32x512 and 256x10)"
    ),
    "remediation_hint": (
        "Check tensor shapes at the point of mismatch; log shapes before the failing op."
    ),
    "notes": None,
}


def test_triage_report_wellformed_validates():
    assert validate_against("triage_report.schema.json", _GOOD_TRIAGE) == []


def test_triage_report_all_valid_error_classes():
    valid_classes = [
        "shape", "oom", "device_assert", "nan_loss",
        "import_error", "file_not_found", "timeout", "permission", "unknown",
    ]
    for ec in valid_classes:
        ok = {**_GOOD_TRIAGE, "error_class": ec}
        errors = validate_against("triage_report.schema.json", ok)
        assert errors == [], f"error_class={ec!r} should be valid but got: {errors}"


def test_triage_report_missing_error_class_rejected():
    bad = {k: v for k, v in _GOOD_TRIAGE.items() if k != "error_class"}
    assert validate_against("triage_report.schema.json", bad) != []


def test_triage_report_invalid_error_class_rejected():
    bad = {**_GOOD_TRIAGE, "error_class": "segfault"}  # not in enum
    assert validate_against("triage_report.schema.json", bad) != []


def test_triage_report_missing_condition_id_rejected():
    bad = {k: v for k, v in _GOOD_TRIAGE.items() if k != "condition_id"}
    assert validate_against("triage_report.schema.json", bad) != []


def test_triage_report_missing_stack_trace_rejected():
    bad = {k: v for k, v in _GOOD_TRIAGE.items() if k != "stack_trace_excerpt"}
    assert validate_against("triage_report.schema.json", bad) != []


def test_triage_report_empty_stack_trace_rejected():
    bad = {**_GOOD_TRIAGE, "stack_trace_excerpt": ""}
    assert validate_against("triage_report.schema.json", bad) != []


def test_triage_report_additional_property_rejected():
    bad = {**_GOOD_TRIAGE, "bogus": True}
    assert validate_against("triage_report.schema.json", bad) != []


# ===========================================================================
# 6. repro_record
# ===========================================================================

_GOOD_REPRO = {
    "condition_id": "c1",
    "from_run_record_ref": "runs/r01/evidence/EXECUTE/run-record.artifact.json",
    "seed": 42,
    "config_hash": "sha256:abcdef1234567890",
    "data_hash": "sha256:fedcba0987654321",
    "git_sha": "a1b2c3d4e5f6",
    "repro_script": (
        "import random, torch\n"
        "random.seed(42)\n"
        "torch.manual_seed(42)\n"
        "# load config by hash and run\n"
        "print('repro complete')\n"
    ),
    "repro_passed": None,
    "result_delta": None,
    "notes": "CUDA version and cuDNN version must match for bit-exact repro.",
}


def test_repro_record_wellformed_validates():
    assert validate_against("repro_record.schema.json", _GOOD_REPRO) == []


def test_repro_record_missing_seed_rejected():
    bad = {k: v for k, v in _GOOD_REPRO.items() if k != "seed"}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_missing_config_hash_rejected():
    bad = {k: v for k, v in _GOOD_REPRO.items() if k != "config_hash"}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_missing_data_hash_rejected():
    bad = {k: v for k, v in _GOOD_REPRO.items() if k != "data_hash"}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_empty_config_hash_rejected():
    bad = {**_GOOD_REPRO, "config_hash": ""}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_empty_data_hash_rejected():
    bad = {**_GOOD_REPRO, "data_hash": ""}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_missing_condition_id_rejected():
    bad = {k: v for k, v in _GOOD_REPRO.items() if k != "condition_id"}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_null_repro_passed_validates():
    """repro_passed=null is the canonical pre-run state — must be valid."""
    ok = {**_GOOD_REPRO, "repro_passed": None}
    assert validate_against("repro_record.schema.json", ok) == []


def test_repro_record_boolean_repro_passed_validates():
    ok_true = {**_GOOD_REPRO, "repro_passed": True}
    ok_false = {**_GOOD_REPRO, "repro_passed": False}
    assert validate_against("repro_record.schema.json", ok_true) == []
    assert validate_against("repro_record.schema.json", ok_false) == []


def test_repro_record_string_seed_rejected():
    """seed must be integer, not a string."""
    bad = {**_GOOD_REPRO, "seed": "42"}
    assert validate_against("repro_record.schema.json", bad) != []


def test_repro_record_additional_property_rejected():
    bad = {**_GOOD_REPRO, "unexpected": "no"}
    assert validate_against("repro_record.schema.json", bad) != []
