"""Behavioral contracts for manuscript build, asset, quality, and review payloads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_FILES = {
    "build": "manuscript_build_receipt.schema.json",
    "assets": "manuscript_asset_manifest.schema.json",
    "quality": "manuscript_quality_report.schema.json",
    "review": "manuscript_review_verdict.schema.json",
}
HEX = {
    key: char * 64
    for key, char in zip(
        "abcdefghijklmno",
        "0123456789abcde",
    )
}


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def _errors(name: str, payload: dict) -> list:
    return sorted(
        Draft202012Validator(_schema(name)).iter_errors(payload),
        key=lambda error: [str(part) for part in error.absolute_path],
    )


def _assert_valid(name: str, payload: dict) -> None:
    assert _errors(name, payload) == []


def _assert_invalid(name: str, payload: dict) -> None:
    assert _errors(name, payload), f"{name} unexpectedly accepted {payload!r}"


def _compiled_build() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "paper-20260721",
        "manuscript_snapshot_sha256": HEX["a"],
        "source_tree_ref": "runs/paper-20260721/manuscript/source",
        "source_tree_sha256": HEX["b"],
        "requires_pdf": True,
        "build_state": "COMPILED",
        "process_receipt": {
            "executable": "latexmk",
            "executable_version": "Latexmk 4.85",
            "argv": [
                "latexmk",
                "-norc",
                "-pdf",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-recorder",
                "-outdir=runs/paper-20260721/build",
                "main.tex",
            ],
            "operating_system": "windows-11",
            "tex_engine": "pdflatex",
            "return_code": 0,
            "duration_ms": 1240,
            "timed_out": False,
            "shell": False,
            "shell_escape": False,
            "started_at": "2026-07-21T09:00:00Z",
            "finished_at": "2026-07-21T09:00:02Z",
            "receipt_sha256": HEX["c"],
        },
        "log_ref": "runs/paper-20260721/build/main.log",
        "log_sha256": HEX["d"],
        "recorder_ref": "runs/paper-20260721/build/main.fls",
        "recorder_sha256": HEX["e"],
        "pdf": {
            "path": "runs/paper-20260721/build/main.pdf",
            "sha256": HEX["f"],
            "byte_size": 4096,
        },
        "build_receipt_sha256": HEX["g"],
    }


def _toolchain_missing_build() -> dict:
    payload = _compiled_build()
    payload["build_state"] = "TOOLCHAIN_MISSING"
    for key in ("process_receipt", "log_ref", "log_sha256", "recorder_ref", "recorder_sha256", "pdf"):
        payload.pop(key)
    payload["failure"] = {
        "kind": "TOOLCHAIN_MISSING",
        "code": "LATEXMK_NOT_FOUND",
        "safe_message": "latexmk was not found on the bounded build PATH",
        "observed_at": "2026-07-21T09:00:00Z",
    }
    return payload


def _compile_failed_build() -> dict:
    payload = _compiled_build()
    payload["build_state"] = "COMPILE_FAILED"
    payload["process_receipt"]["return_code"] = 12
    for key in ("recorder_ref", "recorder_sha256", "pdf"):
        payload.pop(key)
    payload["failure"] = {
        "kind": "COMPILE_FAILED",
        "code": "PROCESS_NONZERO",
        "safe_message": "latexmk returned a non-zero status",
        "observed_at": "2026-07-21T09:00:02Z",
    }
    return payload


def _generated_asset() -> dict:
    return {
        "asset_id": "asset-overview-v1",
        "label": "fig:overview",
        "asset_type": "FIGURE",
        "source_inputs": [
            {
                "ref": "runs/paper-20260721/results/frozen-result.json",
                "sha256": HEX["a"],
                "kind": "FROZEN_RESULT",
                "immutable": True,
            }
        ],
        "output": {
            "path": "runs/paper-20260721/manuscript/assets/overview.pdf",
            "sha256": HEX["b"],
            "byte_size": 2048,
            "owner_run_id": "paper-20260721",
            "run_owned": True,
            "overwrite_policy": "CREATE_NEW",
            "preexisting_target": False,
        },
        "caption": {
            "text": "System overview derived from the frozen result.",
            "owner_role": "figure-table-author",
        },
        "claim_refs": ["claim-001"],
        "result_refs": ["result-001"],
        "numeric_source_cells": [
            {
                "result_ref": "result-001",
                "cell_ref": "overview.nodes",
                "sha256": HEX["c"],
            }
        ],
        "provenance": {
            "kind": "GENERATED",
            "creator": "figure-table-author",
            "created_at": "2026-07-21T09:01:00Z",
            "render_command": {
                "script_ref": "runs/paper-20260721/scripts/render_overview.py",
                "script_sha256": HEX["d"],
                "argv": ["python", "render_overview.py", "--frozen-input"],
                "environment_sha256": HEX["e"],
                "parameters_sha256": HEX["f"],
                "command_receipt_sha256": HEX["g"],
            },
        },
        "permission": {
            "status": "OWNED",
            "license_ref": "project-owned-output",
        },
        "accessibility_text": "A directed graph showing the manuscript workflow stages.",
        "asset_record_sha256": HEX["h"],
    }


def _external_asset() -> dict:
    asset = _generated_asset()
    asset["asset_id"] = "asset-director-table-v1"
    asset["label"] = "tab:director-results"
    asset["asset_type"] = "TABLE"
    asset["provenance"] = {
        "kind": "EXTERNAL",
        "creator": "director",
        "created_at": "2026-07-20T10:00:00Z",
        "external_source": {
            "source_ref": "director-assets/results-table.csv",
            "original_sha256": HEX["i"],
            "acquired_at": "2026-07-21T08:00:00Z",
        },
    }
    asset["permission"] = {
        "status": "DIRECTOR_APPROVED",
        "license_ref": "director-approval-20260721",
    }
    return asset


def _asset_manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "paper-20260721",
        "manuscript_sha256": HEX["j"],
        "assets": [_generated_asset(), _external_asset()],
        "manifest_sha256": HEX["k"],
    }


def _compiled_quality() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "paper-20260721",
        "manuscript_sha256": HEX["a"],
        "requires_pdf": True,
        "build": {
            "receipt_ref": "runs/paper-20260721/build/build-receipt.json",
            "receipt_sha256": HEX["b"],
            "state": "COMPILED",
            "source_sha256": HEX["c"],
            "pdf_sha256": HEX["d"],
        },
        "findings": [],
        "daily_state": "USABLE",
        "daily_rationale": "No open daily-use findings.",
        "submission_ready": True,
        "submission_blockers": [],
        "quality_report_sha256": HEX["e"],
    }


def _finding(
    *,
    finding_id: str,
    finding_class: str,
    scope: str,
    daily_effect: str,
    submission_effect: str,
    code: str,
) -> dict:
    return {
        "finding_id": finding_id,
        "finding_class": finding_class,
        "scope": scope,
        "status": "OPEN",
        "daily_effect": daily_effect,
        "submission_effect": submission_effect,
        "code": code,
        "message": f"Observed {code}",
        "evidence_refs": ["runs/paper-20260721/evidence/check.json"],
        "repair": "Resolve the cited deterministic finding.",
    }


def _pdf_required_readable_deficit() -> dict:
    payload = _compiled_quality()
    payload["build"] = {
        "receipt_ref": "runs/paper-20260721/build/build-receipt.json",
        "receipt_sha256": HEX["b"],
        "state": "TOOLCHAIN_MISSING",
        "source_sha256": HEX["c"],
        "pdf_sha256": None,
    }
    payload["findings"] = [
        _finding(
            finding_id="finding-build",
            finding_class="HARD",
            scope="SUBMISSION",
            daily_effect="NONE",
            submission_effect="BLOCK",
            code="BUILD_REQUIRED_UNAVAILABLE",
        ),
        _finding(
            finding_id="finding-prose",
            finding_class="ADVISORY",
            scope="DAILY_USE",
            daily_effect="CAVEAT",
            submission_effect="NONE",
            code="PROSE_POLISH",
        ),
    ]
    payload["daily_state"] = "USABLE_WITH_CAVEATS"
    payload["daily_rationale"] = "The source is readable; prose polish remains advisory."
    payload["submission_ready"] = False
    payload["submission_blockers"] = [
        {
            "blocker_id": "blocker-build",
            "code": "BUILD_REQUIRED_UNAVAILABLE",
            "source_ref": "finding-build",
            "rationale": "The frozen venue contract requires a real compiled PDF.",
        }
    ]
    return payload


def _review_verdict() -> dict:
    authorization_hash = HEX["a"]
    return {
        "schema_version": "1.0.0",
        "review_id": "review-scientific-001",
        "review_run_id": "review-20260721",
        "reviewer_identity": {
            "reviewer_id": "scientific-reviewer-01",
            "role": "SCIENTIFIC",
            "independent_from_authoring": True,
        },
        "blind_read_receipt": {
            "scheduler_authorization_ref": "runs/review-20260721/receipts/blind-scope.json",
            "scheduler_authorization_sha256": authorization_hash,
            "blind_scope_sha256": HEX["b"],
            "issued_at": "2026-07-21T09:02:00Z",
            "other_reviewer_conclusions_visible": False,
            "generation_artifacts_counted_as_independent_evidence": False,
        },
        "frozen_inputs": {
            "contract_ref": "runs/paper-20260721/manuscript-contract.json",
            "contract_sha256": HEX["c"],
            "manuscript_ref": "runs/paper-20260721/manuscript/main.tex",
            "manuscript_sha256": HEX["d"],
            "pdf_ref": "runs/paper-20260721/build/main.pdf",
            "pdf_sha256": HEX["e"],
        },
        "scoped_inputs": [
            {
                "kind": kind,
                "ref": ref,
                "sha256": hash_value,
                "authorization_receipt_sha256": authorization_hash,
            }
            for kind, ref, hash_value in (
                ("CONTRACT", "runs/paper-20260721/manuscript-contract.json", HEX["c"]),
                ("MANUSCRIPT", "runs/paper-20260721/manuscript/main.tex", HEX["d"]),
                ("PDF", "runs/paper-20260721/build/main.pdf", HEX["e"]),
            )
        ],
        "findings": [],
        "disposition": "PASS",
        "verdict_sha256": HEX["f"],
    }


def _review_finding(severity: str) -> dict:
    return {
        "finding_id": f"finding-{severity.lower()}",
        "severity": severity,
        "status": "OPEN",
        "dimension": "CLAIM_EVIDENCE",
        "locus": "sec:results",
        "description": "The claim needs a narrower evidence boundary.",
        "evidence_refs": ["runs/review-20260721/evidence/exact-span.json"],
        "required_fix": "Narrow the claim to the supported exact span.",
    }


@pytest.mark.parametrize("name", sorted(SCHEMA_FILES))
def test_delivery_schemas_are_draft_2020_12_closed_documents(name: str) -> None:
    schema = _schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"https://research-os/schemas/{SCHEMA_FILES[name]}"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"]
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("build", _compiled_build),
        ("assets", _asset_manifest),
        ("quality", _compiled_quality),
        ("review", _review_verdict),
    ],
)
def test_complete_delivery_payloads_validate(name: str, factory) -> None:
    _assert_valid(name, factory())


@pytest.mark.parametrize(
    "field",
    [
        "process_receipt",
        "log_ref",
        "log_sha256",
        "recorder_ref",
        "recorder_sha256",
        "pdf",
    ],
)
def test_compiled_build_requires_every_observed_build_fact(field: str) -> None:
    payload = _compiled_build()
    del payload[field]
    _assert_invalid("build", payload)


@pytest.mark.parametrize(
    "field",
    ["executable", "executable_version", "argv", "operating_system", "return_code", "receipt_sha256"],
)
def test_compiled_build_requires_complete_process_receipt(field: str) -> None:
    payload = _compiled_build()
    del payload["process_receipt"][field]
    _assert_invalid("build", payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("process_receipt", "return_code"), 1),
        (("process_receipt", "timed_out"), True),
        (("process_receipt", "shell"), True),
        (("process_receipt", "shell_escape"), True),
        (("pdf", "byte_size"), 0),
        (("pdf", "sha256"), "stale"),
    ],
)
def test_compiled_build_rejects_fabricated_or_unsafe_facts(path: tuple[str, str], value) -> None:
    payload = _compiled_build()
    payload[path[0]][path[1]] = value
    _assert_invalid("build", payload)


def test_toolchain_missing_is_valid_without_a_pdf_claim() -> None:
    _assert_valid("build", _toolchain_missing_build())


@pytest.mark.parametrize("forbidden", ["pdf", "process_receipt", "log_ref", "log_sha256"])
def test_toolchain_missing_forbids_compile_and_pdf_claims(forbidden: str) -> None:
    payload = _toolchain_missing_build()
    payload[forbidden] = _compiled_build()[forbidden]
    _assert_invalid("build", payload)


def test_compile_failed_requires_an_observed_process_and_log() -> None:
    payload = _compile_failed_build()
    _assert_valid("build", payload)
    del payload["process_receipt"]
    _assert_invalid("build", payload)


def test_compile_failed_cannot_expose_a_pdf() -> None:
    payload = _compile_failed_build()
    payload["pdf"] = _compiled_build()["pdf"]
    _assert_invalid("build", payload)


@pytest.mark.parametrize("unsafe_ref", ["../main.tex", "/tmp/main.tex", "C:/outside/main.tex"])
def test_build_rejects_paths_outside_the_run(unsafe_ref: str) -> None:
    payload = _compiled_build()
    payload["source_tree_ref"] = unsafe_ref
    _assert_invalid("build", payload)


def test_build_receipt_is_closed() -> None:
    payload = _compiled_build()
    payload["claimed_pdf_without_evidence"] = True
    _assert_invalid("build", payload)


def test_generated_and_external_assets_validate() -> None:
    _assert_valid("assets", _asset_manifest())


@pytest.mark.parametrize(
    "field",
    [
        "label",
        "source_inputs",
        "output",
        "caption",
        "claim_refs",
        "result_refs",
        "numeric_source_cells",
        "provenance",
        "permission",
        "accessibility_text",
    ],
)
def test_each_asset_requires_complete_ownership_and_provenance(field: str) -> None:
    payload = _asset_manifest()
    del payload["assets"][0][field]
    _assert_invalid("assets", payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_owned", False),
        ("overwrite_policy", "OVERWRITE"),
        ("preexisting_target", True),
        ("owner_run_id", ""),
        ("sha256", "mutable"),
    ],
)
def test_asset_output_cannot_encode_overwrite_ambiguity(field: str, value) -> None:
    payload = _asset_manifest()
    payload["assets"][0]["output"][field] = value
    _assert_invalid("assets", payload)


def test_asset_sources_must_be_explicitly_immutable() -> None:
    payload = _asset_manifest()
    payload["assets"][0]["source_inputs"][0]["immutable"] = False
    _assert_invalid("assets", payload)


def test_generated_asset_requires_reproducible_render_command() -> None:
    payload = _asset_manifest()
    del payload["assets"][0]["provenance"]["render_command"]
    _assert_invalid("assets", payload)


def test_external_asset_requires_original_hash_and_permission() -> None:
    payload = _asset_manifest()
    del payload["assets"][1]["provenance"]["external_source"]["original_sha256"]
    _assert_invalid("assets", payload)


def test_asset_manifest_rejects_unsafe_output_path() -> None:
    payload = _asset_manifest()
    payload["assets"][0]["output"]["path"] = "../vault/figure.pdf"
    _assert_invalid("assets", payload)


def test_asset_records_are_closed() -> None:
    payload = _asset_manifest()
    payload["assets"][0]["overwrite_director_asset"] = True
    _assert_invalid("assets", payload)


def test_advisory_caveat_derives_usable_with_caveats() -> None:
    payload = _compiled_quality()
    payload["findings"] = [
        _finding(
            finding_id="finding-prose",
            finding_class="ADVISORY",
            scope="DAILY_USE",
            daily_effect="CAVEAT",
            submission_effect="NONE",
            code="PROSE_POLISH",
        )
    ]
    payload["daily_state"] = "USABLE_WITH_CAVEATS"
    _assert_valid("quality", payload)


def test_advisory_findings_cannot_escalate_to_block() -> None:
    payload = _compiled_quality()
    payload["findings"] = [
        _finding(
            finding_id="finding-prose",
            finding_class="ADVISORY",
            scope="DAILY_USE",
            daily_effect="CAVEAT",
            submission_effect="NONE",
            code="PROSE_POLISH",
        )
    ]
    payload["daily_state"] = "BLOCK"
    _assert_invalid("quality", payload)


def test_advisory_finding_cannot_claim_a_hard_effect() -> None:
    payload = _compiled_quality()
    payload["findings"] = [
        _finding(
            finding_id="finding-style",
            finding_class="ADVISORY",
            scope="BOTH",
            daily_effect="BLOCK",
            submission_effect="BLOCK",
            code="STYLE",
        )
    ]
    payload["daily_state"] = "BLOCK"
    payload["submission_ready"] = False
    payload["submission_blockers"] = [
        {"blocker_id": "b-style", "code": "STYLE", "source_ref": "finding-style", "rationale": "style"}
    ]
    _assert_invalid("quality", payload)


def test_open_daily_hard_finding_forces_block_and_not_ready() -> None:
    payload = _compiled_quality()
    payload["findings"] = [
        _finding(
            finding_id="finding-truth",
            finding_class="HARD",
            scope="BOTH",
            daily_effect="BLOCK",
            submission_effect="BLOCK",
            code="FALSE_RESULT_CLAIM",
        )
    ]
    _assert_invalid("quality", payload)


def test_block_requires_an_open_daily_hard_finding() -> None:
    payload = _compiled_quality()
    payload["daily_state"] = "BLOCK"
    payload["submission_ready"] = False
    payload["submission_blockers"] = [
        {"blocker_id": "b-none", "code": "UNKNOWN", "source_ref": "none", "rationale": "none"}
    ]
    _assert_invalid("quality", payload)


def test_needs_supplement_is_a_distinct_daily_state() -> None:
    payload = _compiled_quality()
    payload["findings"] = [
        _finding(
            finding_id="finding-coverage",
            finding_class="ADVISORY",
            scope="DAILY_USE",
            daily_effect="SUPPLEMENT",
            submission_effect="NONE",
            code="OPTIONAL_COVERAGE_GAP",
        )
    ]
    payload["daily_state"] = "NEEDS_SUPPLEMENT"
    _assert_valid("quality", payload)


def test_pdf_required_build_deficit_can_remain_readable_but_not_ready() -> None:
    _assert_valid("quality", _pdf_required_readable_deficit())


@pytest.mark.parametrize("missing", ["findings", "submission_blockers"])
def test_pdf_required_build_deficit_requires_explicit_build_blocker(missing: str) -> None:
    payload = _pdf_required_readable_deficit()
    if missing == "findings":
        payload["findings"] = payload["findings"][1:]
    else:
        payload["submission_blockers"] = []
    _assert_invalid("quality", payload)


def test_pdf_required_build_deficit_cannot_be_submission_ready() -> None:
    payload = _pdf_required_readable_deficit()
    payload["submission_ready"] = True
    payload["submission_blockers"] = []
    _assert_invalid("quality", payload)


def test_false_submission_state_requires_blocker_rationale() -> None:
    payload = _compiled_quality()
    payload["submission_ready"] = False
    _assert_invalid("quality", payload)


def test_submission_ready_forbids_blocker_entries() -> None:
    payload = _compiled_quality()
    payload["submission_blockers"] = [
        {"blocker_id": "b-stale", "code": "STALE", "source_ref": "old", "rationale": "stale"}
    ]
    _assert_invalid("quality", payload)


def test_noncompiled_build_forbids_pdf_hash() -> None:
    payload = _pdf_required_readable_deficit()
    payload["build"]["pdf_sha256"] = HEX["d"]
    _assert_invalid("quality", payload)


def test_quality_report_is_closed() -> None:
    payload = _compiled_quality()
    payload["quality_score_override"] = "PASS"
    _assert_invalid("quality", payload)


def test_independent_frozen_review_verdict_validates() -> None:
    _assert_valid("review", _review_verdict())


@pytest.mark.parametrize(
    "field",
    [
        "contract_ref",
        "contract_sha256",
        "manuscript_ref",
        "manuscript_sha256",
        "pdf_ref",
        "pdf_sha256",
    ],
)
def test_review_requires_every_frozen_input_fact(field: str) -> None:
    payload = _review_verdict()
    del payload["frozen_inputs"][field]
    _assert_invalid("review", payload)


@pytest.mark.parametrize(
    ("container", "field"),
    [
        ("reviewer_identity", "reviewer_id"),
        ("reviewer_identity", "independent_from_authoring"),
        ("blind_read_receipt", "scheduler_authorization_ref"),
        ("blind_read_receipt", "scheduler_authorization_sha256"),
        ("blind_read_receipt", "blind_scope_sha256"),
        ("blind_read_receipt", "other_reviewer_conclusions_visible"),
    ],
)
def test_review_requires_identity_and_blind_read_receipt(container: str, field: str) -> None:
    payload = _review_verdict()
    del payload[container][field]
    _assert_invalid("review", payload)


def test_reviewer_must_be_independent_from_authoring() -> None:
    payload = _review_verdict()
    payload["reviewer_identity"]["independent_from_authoring"] = False
    _assert_invalid("review", payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("other_reviewer_conclusions_visible", True),
        ("generation_artifacts_counted_as_independent_evidence", True),
    ],
)
def test_blind_review_cannot_see_peer_conclusions_or_launder_generation_evidence(field: str, value) -> None:
    payload = _review_verdict()
    payload["blind_read_receipt"][field] = value
    _assert_invalid("review", payload)


@pytest.mark.parametrize("kind", ["CONTRACT", "MANUSCRIPT", "PDF"])
def test_review_scope_must_include_each_frozen_input_kind(kind: str) -> None:
    payload = _review_verdict()
    payload["scoped_inputs"] = [entry for entry in payload["scoped_inputs"] if entry["kind"] != kind]
    _assert_invalid("review", payload)


def test_open_blocking_review_finding_forces_block() -> None:
    payload = _review_verdict()
    payload["findings"] = [_review_finding("BLOCKING")]
    _assert_invalid("review", payload)
    payload["disposition"] = "BLOCK"
    _assert_valid("review", payload)


def test_block_disposition_requires_an_open_blocking_finding() -> None:
    payload = _review_verdict()
    payload["disposition"] = "BLOCK"
    _assert_invalid("review", payload)


def test_open_advisory_review_finding_derives_needs_repair() -> None:
    payload = _review_verdict()
    payload["findings"] = [_review_finding("ADVISORY")]
    payload["disposition"] = "NEEDS_REPAIR"
    _assert_valid("review", payload)
    payload["disposition"] = "PASS"
    _assert_invalid("review", payload)


def test_review_verdict_is_closed() -> None:
    payload = _review_verdict()
    payload["authoring_mutation"] = "rewrite"
    _assert_invalid("review", payload)
