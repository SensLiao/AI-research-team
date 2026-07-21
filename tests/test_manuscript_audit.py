"""Deterministic truth-audit and delivery-state tests for manuscript output."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.tools.manuscript_audit import (
    audit_manuscript,
    derive_daily_status,
    derive_submission_readiness,
)
from research_agent_teams.tools.validate_artifact import validate_payload


HEX = {letter: letter * 64 for letter in "abcdef0123456789"}


def _canonical_hash(value: dict, omitted: str | None = None) -> str:
    payload = {key: item for key, item in value.items() if key != omitted}
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _contract(*, requires_pdf: bool = True) -> dict:
    venue_rule_ref = "venue/fixture-2026-author-instructions"
    evidence_ref = "evidence/local-paper-001"
    result_ref = "results/frozen-result-001"
    return {
        "contract_version": "1.0",
        "contract_id": "manuscript-contract/run-001",
        "project": "example-project",
        "run_id": "run-001",
        "north_star": "Explain only the contribution supported by frozen evidence.",
        "paper_brief": {
            "working_title": "A Traceable Manuscript Fixture",
            "research_question": "Can scoped authoring preserve evidence provenance?",
            "contribution_statement": "A frozen contract for dependency-safe authoring.",
            "done_when": ["Every load-bearing claim is traceable."],
        },
        "paper_type": "METHOD",
        "venue_profile": {
            "venue_id": "fixture-venue",
            "venue_family": "top-ai-conference",
            "year": 2026,
            "track": "main",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "official_rule_refs": [{"ref": venue_rule_ref, "sha256": HEX["a"]}],
            "template_ref": "templates/fixture-2026",
            "template_sha256": HEX["b"],
            "requires_pdf": requires_pdf,
            "hard_field_policy": {
                "requires_pdf": {
                    "classification": "OFFICIAL_HARD",
                    "weakenable": False,
                    "source_ref": venue_rule_ref,
                    "source_sha256": HEX["a"],
                }
            },
        },
        "outline": [
            {
                "section_id": "introduction",
                "title": "Introduction",
                "purpose": "State the bounded contribution.",
                "required": True,
                "depends_on": [],
            }
        ],
        "claim_ledger": [
            {
                "claim_id": "CLM-001",
                "text": "The workflow preserves declared evidence dependencies.",
                "importance": "LOAD_BEARING",
                "evidence_refs": [evidence_ref],
                "result_refs": [],
            }
        ],
        "evidence_refs": [
            {
                "ref": evidence_ref,
                "sha256": HEX["c"],
                "source_kind": "LOCAL_FULL_TEXT",
                "claim_support": "EXACT_SPAN",
            }
        ],
        "result_refs": [
            {
                "ref": result_ref,
                "sha256": HEX["d"],
                "status": "FROZEN",
                "receipt_ref": "executor-receipts/result-001.json",
                "receipt_sha256": HEX["e"],
            }
        ],
        "glossary": {
            "terms": [
                {
                    "term": "frozen contract",
                    "definition": "An immutable, hash-bound authoring snapshot.",
                }
            ],
            "notation": [{"symbol": "H", "meaning": "SHA-256 digest"}],
        },
        "bibliography": {
            "style": "natbib",
            "entries": [
                {
                    "citation_key": "LocalPaper2026",
                    "source_ref": evidence_ref,
                    "source_sha256": HEX["c"],
                    "identity_status": "VERIFIED",
                }
            ],
        },
        "asset_plan": [
            {
                "asset_id": "fig-architecture",
                "kind": "FIGURE",
                "label": "fig:architecture",
                "planned_path": "figures/architecture.pdf",
                "source_refs": [evidence_ref],
                "result_refs": [],
            }
        ],
        "resolved_tokens": {
            "cascade_order": ["base", "paper_type", "venue", "project", "run"],
            "tokens": [
                {
                    "token": "requires_pdf",
                    "value": requires_pdf,
                    "classification": "HARD",
                    "resolved_layer": "venue",
                    "source_ref": venue_rule_ref,
                    "source_sha256": HEX["a"],
                    "weakenable": False,
                }
            ],
            "snapshot_sha256": HEX["b"],
        },
        "dependency_slices": [
            {
                "slice_id": "slice-introduction",
                "worker_role": "manuscript-introduction-author",
                "input_refs": [
                    {
                        "ref": evidence_ref,
                        "sha256": HEX["c"],
                        "slice_kind": "CLAIM_EVIDENCE",
                    }
                ],
                "slice_sha256": HEX["d"],
            }
        ],
        "source_hashes": [
            {"ref": venue_rule_ref, "sha256": HEX["a"], "kind": "VENUE_RULE"},
            {"ref": evidence_ref, "sha256": HEX["c"], "kind": "EVIDENCE"},
            {"ref": result_ref, "sha256": HEX["d"], "kind": "RESULT"},
        ],
        "manuscript_snapshot_sha256": HEX["e"],
    }


def _manuscript() -> dict:
    return {
        "manuscript_sha256": HEX["f"],
        "sections": [
            {
                "section_id": "abstract",
                "claim_ids": ["CLM-001"],
                "citation_keys": ["LocalPaper2026"],
            },
            {
                "section_id": "introduction",
                "claim_ids": ["CLM-001"],
                "citation_keys": ["LocalPaper2026"],
            },
            {
                "section_id": "conclusion",
                "claim_ids": ["CLM-001"],
                "citation_keys": ["LocalPaper2026"],
            },
        ],
        "claim_evidence": [
            {
                "claim_id": "CLM-001",
                "evidence_ref": "evidence/local-paper-001",
                "source_sha256": HEX["c"],
                "citation_key": "LocalPaper2026",
                "observed_citation_key": "LocalPaper2026",
                "exact_span": "The declared dependency graph is preserved.",
                "entailment": "ENTAILED",
                "metadata_only": False,
                "independent_audit": True,
            }
        ],
        "numeric_claims": [],
        "result_facts": [],
        "bibliography_keys": ["LocalPaper2026"],
        "term_usage": {"frozen contract": "CONSISTENT"},
        "notation_usage": {"H": "CONSISTENT"},
        "labels": ["fig:architecture"],
        "cross_references": ["fig:architecture"],
        "assets": [
            {
                "asset_id": "fig-architecture",
                "label": "fig:architecture",
                "path": "figures/architecture.pdf",
                "owner": "run",
                "mutation_requested": False,
                "source_refs": ["evidence/local-paper-001"],
                "result_refs": [],
                "provenance_valid": True,
            }
        ],
        "anonymity_violations": [],
        "official_rule_violations": [],
        "persisted_texts": {"markdown": "A bounded and anonymous manuscript."},
        "tex_sources": {},
        "advisories": [],
    }


def _process_receipt(*, return_code: int = 0) -> dict:
    return {
        "executable": "fixture-latexmk",
        "executable_version": "fixture-latexmk 1.0",
        "argv": [
            "fixture-latexmk",
            "-norc",
            "-pdf",
            "-halt-on-error",
            "-recorder",
            "main.tex",
        ],
        "operating_system": "fixture-os",
        "tex_engine": "fixture-pdflatex",
        "return_code": return_code,
        "duration_ms": 10,
        "timed_out": False,
        "shell": False,
        "shell_escape": False,
        "started_at": "2026-07-21T09:00:00Z",
        "finished_at": "2026-07-21T09:00:01Z",
        "receipt_sha256": HEX["a"],
    }


def _build_receipt(
    state: str,
    *,
    source_sha256: str,
    requires_pdf: bool = True,
    pdf_sha256: str = HEX["b"],
    byte_size: int = 3,
) -> dict:
    payload = {
        "schema_version": "1.0.0",
        "run_id": "run-001",
        "manuscript_snapshot_sha256": HEX["e"],
        "source_tree_ref": "manuscript/source",
        "source_tree_sha256": source_sha256,
        "requires_pdf": requires_pdf,
        "build_state": state,
    }
    if state == "COMPILED":
        payload.update(
            process_receipt=_process_receipt(),
            log_ref="build/paper.log",
            log_sha256=HEX["c"],
            recorder_ref="build/paper.fls",
            recorder_sha256=HEX["d"],
            pdf={"path": "build/paper.pdf", "sha256": pdf_sha256, "byte_size": byte_size},
        )
    elif state == "TOOLCHAIN_MISSING":
        payload["failure"] = {
            "kind": "TOOLCHAIN_MISSING",
            "code": "LATEXMK_NOT_FOUND",
            "safe_message": "latexmk was not found on the bounded build PATH",
            "observed_at": "2026-07-21T09:00:00Z",
        }
    else:
        payload.update(
            process_receipt=_process_receipt(return_code=12),
            log_ref="build/paper.log",
            log_sha256=HEX["c"],
            failure={
                "kind": "COMPILE_FAILED",
                "code": "PROCESS_NONZERO",
                "safe_message": "latexmk returned a non-zero status",
                "observed_at": "2026-07-21T09:00:01Z",
            },
        )
    payload["build_receipt_sha256"] = _canonical_hash(payload)
    return payload


def _write_pdf(run_root: Path, content: bytes = b"pdf") -> str:
    path = run_root / "build" / "paper.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _audit(
    tmp_path: Path,
    *,
    contract: dict | None = None,
    manuscript: dict | None = None,
    build_receipt: dict | None = None,
    current_source_sha256: str = HEX["a"],
    **kwargs,
) -> dict:
    run_root = tmp_path / "run-001"
    run_root.mkdir(exist_ok=True)
    return audit_manuscript(
        contract or _contract(),
        manuscript or _manuscript(),
        run_root=run_root,
        current_source_sha256=current_source_sha256,
        build_receipt=build_receipt,
        **kwargs,
    )


def _codes(report: dict) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def _assert_schema_valid(report: dict) -> None:
    assert validate_payload("manuscript_quality_report", report) == []
    assert report["quality_report_sha256"] == _canonical_hash(
        report, "quality_report_sha256"
    )


def test_pdf_optional_without_build_is_usable_and_submission_ready(tmp_path):
    report = _audit(tmp_path, contract=_contract(requires_pdf=False))

    _assert_schema_valid(report)
    assert report["requires_pdf"] is False
    assert report["build"]["state"] == "TOOLCHAIN_MISSING"
    assert report["build"]["pdf_sha256"] is None
    assert report["daily_state"] == "USABLE"
    assert report["submission_ready"] is True
    assert report["submission_blockers"] == []
    assert "BUILD_REQUIRED_UNAVAILABLE" not in _codes(report)


@pytest.mark.parametrize(
    ("variant", "expected_code"),
    [
        ("none", "BUILD_REQUIRED_UNAVAILABLE"),
        ("toolchain", "BUILD_REQUIRED_UNAVAILABLE"),
        ("failed", "BUILD_REQUIRED_UNAVAILABLE"),
        ("stale", "BUILD_SOURCE_STALE"),
        ("missing-pdf", "BUILD_PDF_MISSING"),
        ("hash-mismatch", "BUILD_PDF_HASH_MISMATCH"),
    ],
)
def test_required_pdf_build_deficits_are_not_ready_but_remain_readable(
    tmp_path, variant, expected_code
):
    run_root = tmp_path / "run-001"
    run_root.mkdir()
    receipt = None
    if variant == "toolchain":
        receipt = _build_receipt("TOOLCHAIN_MISSING", source_sha256=HEX["a"])
    elif variant == "failed":
        receipt = _build_receipt("COMPILE_FAILED", source_sha256=HEX["a"])
    elif variant in {"stale", "missing-pdf", "hash-mismatch"}:
        recorded = HEX["b"]
        if variant in {"stale", "hash-mismatch"}:
            _write_pdf(run_root, b"actual-pdf")
        if variant == "stale":
            recorded = hashlib.sha256(b"actual-pdf").hexdigest()
        receipt = _build_receipt(
            "COMPILED",
            source_sha256=HEX["9"] if variant == "stale" else HEX["a"],
            pdf_sha256=recorded,
        )

    report = audit_manuscript(
        _contract(),
        _manuscript(),
        run_root=run_root,
        current_source_sha256=HEX["a"],
        build_receipt=receipt,
    )

    _assert_schema_valid(report)
    assert report["daily_state"] != "BLOCK"
    assert report["submission_ready"] is False
    assert expected_code in _codes(report)
    assert expected_code in {item["code"] for item in report["submission_blockers"]}


def test_current_compiled_pdf_is_the_only_required_pdf_ready_branch(tmp_path):
    run_root = tmp_path / "run-001"
    run_root.mkdir()
    pdf_sha = _write_pdf(run_root)
    receipt = _build_receipt(
        "COMPILED", source_sha256=HEX["a"], pdf_sha256=pdf_sha
    )

    report = audit_manuscript(
        _contract(),
        _manuscript(),
        run_root=run_root,
        current_source_sha256=HEX["a"],
        build_receipt=receipt,
    )

    _assert_schema_valid(report)
    assert report["daily_state"] == "USABLE"
    assert report["submission_ready"] is True
    assert report["build"]["source_sha256"] == HEX["a"]
    assert report["build"]["pdf_sha256"] == pdf_sha


def test_claim_evidence_and_citation_truth_fail_closed(tmp_path):
    manuscript = _manuscript()
    link = manuscript["claim_evidence"][0]
    link.update(
        metadata_only=True,
        exact_span="",
        observed_citation_key="WrongIdentity2026",
        entailment="CONTRADICTED",
    )

    report = _audit(
        tmp_path,
        contract=_contract(requires_pdf=False),
        manuscript=manuscript,
    )

    _assert_schema_valid(report)
    assert {
        "METADATA_ONLY_EVIDENCE",
        "UNSUPPORTED_LOAD_BEARING_CLAIM",
        "CITATION_IDENTITY_MISMATCH",
        "CITATION_ENTAILMENT_CONTRADICTED",
    } <= _codes(report)
    assert report["daily_state"] == "BLOCK"
    assert report["submission_ready"] is False


def _with_numeric_result(contract: dict, manuscript: dict, *, value: float) -> None:
    contract["claim_ledger"].append(
        {
            "claim_id": "CLM-RESULT",
            "text": "The frozen evaluation achieved accuracy 0.8125.",
            "importance": "LOAD_BEARING",
            "evidence_refs": [],
            "result_refs": ["results/frozen-result-001"],
        }
    )
    for section in manuscript["sections"]:
        section["claim_ids"].append("CLM-RESULT")
    manuscript["result_facts"] = [
        {
            "result_ref": "results/frozen-result-001",
            "sha256": HEX["d"],
            "receipt_ref": "executor-receipts/result-001.json",
            "receipt_sha256": HEX["e"],
            "raw_result_ref": "execution-results/result.json",
            "raw_result_sha256": HEX["d"],
            "metadata_only": False,
            "values": {"accuracy": {"value": 0.8125, "unit": "fraction"}},
        }
    ]
    manuscript["numeric_claims"] = [
        {
            "claim_id": "CLM-RESULT",
            "result_ref": "results/frozen-result-001",
            "metric": "accuracy",
            "value": value,
            "unit": "fraction",
            "execution_language": "real external experiment",
        }
    ]


def _verified_result_receipt(*_args, **_kwargs) -> dict:
    return {
        "receipt_ref": "executor-receipts/result-001.json",
        "receipt_sha256": "sha256:" + HEX["e"],
        "exit_status": 0,
        "attestation_key_id": "lab-executor-01",
        "result_files": [
            {
                "path": "execution-results/result.json",
                "sha256": "sha256:" + HEX["d"],
                "size_bytes": 128,
            }
        ],
    }


def test_numeric_truth_reverifies_external_receipt_and_bound_result(tmp_path):
    contract = _contract(requires_pdf=False)
    manuscript = _manuscript()
    _with_numeric_result(contract, manuscript, value=0.8125)
    calls = []

    def verifier(*args, **kwargs):
        calls.append((args, kwargs))
        return _verified_result_receipt()

    report = _audit(
        tmp_path,
        contract=contract,
        manuscript=manuscript,
        executor_receipt_verifier=verifier,
        executor_key_resolver=lambda _key_id: b"x" * 32,
    )

    _assert_schema_valid(report)
    assert report["submission_ready"] is True
    assert report["daily_state"] == "USABLE"
    assert len(calls) == 1
    assert calls[0][0][1] == "executor-receipts/result-001.json"
    assert calls[0][1]["expected_run_id"] == "run-001"
    assert "key_resolver" in calls[0][1]


def test_numeric_mismatch_and_failed_receipt_reverification_block(tmp_path):
    contract = _contract(requires_pdf=False)
    manuscript = _manuscript()
    _with_numeric_result(contract, manuscript, value=0.91)

    def rejected(*_args, **_kwargs):
        raise ValueError("signature mismatch containing sensitive internal detail")

    report = _audit(
        tmp_path,
        contract=contract,
        manuscript=manuscript,
        executor_receipt_verifier=rejected,
    )

    _assert_schema_valid(report)
    assert {"NUMERIC_RESULT_MISMATCH", "FALSE_EXECUTION_CLAIM"} <= _codes(report)
    assert report["daily_state"] == "BLOCK"
    assert "sensitive internal detail" not in json.dumps(report)


@pytest.mark.parametrize(
    ("mutate", "expected_code", "expected_state", "expected_ready"),
    [
        (
            lambda value: value["sections"].pop(1),
            "MISSING_REQUIRED_SECTION",
            "BLOCK",
            False,
        ),
        (
            lambda value: value["term_usage"].update({"frozen contract": "INCONSISTENT"}),
            "TERMINOLOGY_INCONSISTENT",
            "NEEDS_SUPPLEMENT",
            True,
        ),
        (
            lambda value: value["notation_usage"].update({"H": "MISSING"}),
            "NOTATION_INCONSISTENT",
            "NEEDS_SUPPLEMENT",
            True,
        ),
        (
            lambda value: value["cross_references"].append("fig:missing"),
            "DANGLING_CROSS_REFERENCE",
            "NEEDS_SUPPLEMENT",
            True,
        ),
        (
            lambda value: value["anonymity_violations"].append("author name exposed"),
            "ANONYMITY_VIOLATION",
            "USABLE",
            False,
        ),
        (
            lambda value: value["official_rule_violations"].append("page limit exceeded"),
            "OFFICIAL_RULE_VIOLATION",
            "USABLE",
            False,
        ),
    ],
)
def test_remaining_registry_dimensions_have_stable_policy(
    tmp_path, mutate, expected_code, expected_state, expected_ready
):
    manuscript = _manuscript()
    mutate(manuscript)

    report = _audit(
        tmp_path,
        contract=_contract(requires_pdf=False),
        manuscript=manuscript,
    )

    _assert_schema_valid(report)
    assert expected_code in _codes(report)
    assert report["daily_state"] == expected_state
    assert report["submission_ready"] is expected_ready


def test_path_secret_and_false_pdf_claims_are_daily_hard_blocks(tmp_path):
    manuscript = _manuscript()
    manuscript["assets"][0]["path"] = "../vault/figure.pdf"
    manuscript["persisted_texts"]["markdown"] = "credential=sentinel-value-001"
    manuscript["claimed_pdf"] = {"path": "build/paper.pdf", "sha256": HEX["b"]}

    report = _audit(
        tmp_path,
        contract=_contract(requires_pdf=False),
        manuscript=manuscript,
        secret_sentinels={"test_secret": "sentinel-value-001"},
    )

    _assert_schema_valid(report)
    assert {
        "PATH_ESCAPE_OR_AMBIGUITY",
        "SECRET_LEAKAGE",
        "FALSE_PDF_CLAIM",
    } <= _codes(report)
    assert report["daily_state"] == "BLOCK"
    serialized = json.dumps(report)
    assert "sentinel-value-001" not in serialized
    assert "../vault" not in serialized


def test_advisories_cannot_block_and_reducers_ignore_model_authored_status(tmp_path):
    manuscript = _manuscript()
    manuscript["advisories"] = [
        {
            "code": "RHETORIC_TOO_DENSE",
            "message": "The opening is dense.",
            "effect": "CAVEAT",
            "evidence_ref": "manuscript/abstract",
            "model_suggested_state": "BLOCK",
        }
    ]

    first = _audit(
        tmp_path,
        contract=_contract(requires_pdf=False),
        manuscript=manuscript,
    )
    second = _audit(
        tmp_path,
        contract=_contract(requires_pdf=False),
        manuscript=copy.deepcopy(manuscript),
    )

    _assert_schema_valid(first)
    assert first == second
    assert first["daily_state"] == "USABLE_WITH_CAVEATS"
    assert first["submission_ready"] is True
    assert derive_daily_status(first["findings"]) == "USABLE_WITH_CAVEATS"
    assert derive_submission_readiness(
        first["findings"], requires_pdf=False, build_verified=False
    ) is True


def test_corrupt_contract_and_receipt_fail_closed_with_schema_valid_report(tmp_path):
    contract = _contract(requires_pdf=False)
    contract["venue_profile"]["requires_pdf"] = "model-says-no"
    receipt = _build_receipt(
        "COMPILED", source_sha256=HEX["a"], requires_pdf=False
    )
    receipt["build_receipt_sha256"] = HEX["0"]

    report = _audit(tmp_path, contract=contract, build_receipt=receipt)

    _assert_schema_valid(report)
    assert {"CORRUPT_INPUT", "CORRUPT_BUILD_RECEIPT"} <= _codes(report)
    assert report["daily_state"] == "BLOCK"
    assert report["submission_ready"] is False


def test_explicit_pdf_claim_requires_current_verified_pdf(tmp_path):
    run_root = tmp_path / "run-001"
    run_root.mkdir()
    actual_sha = _write_pdf(run_root, b"actual-pdf")
    receipt = _build_receipt(
        "COMPILED", source_sha256=HEX["a"], pdf_sha256=actual_sha
    )
    manuscript = _manuscript()
    manuscript["claimed_pdf"] = {"path": "build/paper.pdf", "sha256": HEX["b"]}

    report = audit_manuscript(
        _contract(),
        manuscript,
        run_root=run_root,
        current_source_sha256=HEX["a"],
        build_receipt=receipt,
    )

    _assert_schema_valid(report)
    assert "FALSE_PDF_CLAIM" in _codes(report)
    assert report["daily_state"] == "BLOCK"
    assert report["submission_ready"] is False
