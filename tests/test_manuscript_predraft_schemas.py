"""Behavior tests for the manuscript pre-draft schema family.

These tests intentionally validate payloads directly with Draft 2020-12.  Central
artifact registration is deferred to Plan 01-09; this plan owns only the payload
contracts that later reducers and operated recipes consume.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _errors(schema_name: str, payload: dict) -> list[str]:
    return [
        error.message
        for error in _validator(schema_name).iter_errors(payload)
    ]


def _assert_valid(schema_name: str, payload: dict) -> None:
    assert _errors(schema_name, payload) == []


def _assert_invalid(schema_name: str, payload: dict) -> None:
    assert _errors(schema_name, payload), f"expected {schema_name} to reject payload"


def valid_manuscript_contract() -> dict:
    venue_rule_ref = "venue/icml-2026-author-instructions"
    evidence_ref = "evidence/local-paper-001"
    result_ref = "results/frozen-result-001"
    return {
        "contract_version": "1.0",
        "contract_id": "manuscript-contract/run-001",
        "project": "example-project",
        "run_id": "run-001",
        "north_star": "Explain the supported contribution without exceeding frozen evidence.",
        "paper_brief": {
            "working_title": "A Traceable Manuscript Fixture",
            "research_question": "Can scoped authoring preserve evidence provenance?",
            "contribution_statement": "A frozen contract for dependency-safe authoring.",
            "done_when": ["Every load-bearing claim is traceable."],
        },
        "paper_type": "METHOD",
        "venue_profile": {
            "venue_id": "icml",
            "venue_family": "top-ai-conference",
            "year": 2026,
            "track": "main",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "official_rule_refs": [
                {"ref": venue_rule_ref, "sha256": SHA_A},
            ],
            "template_ref": "templates/icml-2026",
            "template_sha256": SHA_B,
            "requires_pdf": True,
            "hard_field_policy": {
                "requires_pdf": {
                    "classification": "OFFICIAL_HARD",
                    "weakenable": False,
                    "source_ref": venue_rule_ref,
                    "source_sha256": SHA_A,
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
                "sha256": SHA_C,
                "source_kind": "LOCAL_FULL_TEXT",
                "claim_support": "EXACT_SPAN",
            }
        ],
        "result_refs": [
            {
                "ref": result_ref,
                "sha256": SHA_D,
                "status": "FROZEN",
                "receipt_ref": "receipts/result-001",
                "receipt_sha256": SHA_E,
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
                    "source_sha256": SHA_C,
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
                    "value": True,
                    "classification": "HARD",
                    "resolved_layer": "venue",
                    "source_ref": venue_rule_ref,
                    "source_sha256": SHA_A,
                    "weakenable": False,
                }
            ],
            "snapshot_sha256": SHA_B,
        },
        "dependency_slices": [
            {
                "slice_id": "slice-introduction",
                "worker_role": "manuscript-introduction-author",
                "input_refs": [
                    {
                        "ref": evidence_ref,
                        "sha256": SHA_C,
                        "slice_kind": "CLAIM_EVIDENCE",
                    }
                ],
                "slice_sha256": SHA_D,
            }
        ],
        "source_hashes": [
            {"ref": venue_rule_ref, "sha256": SHA_A, "kind": "VENUE_RULE"},
            {"ref": evidence_ref, "sha256": SHA_C, "kind": "EVIDENCE"},
            {"ref": result_ref, "sha256": SHA_D, "kind": "RESULT"},
        ],
        "manuscript_snapshot_sha256": SHA_E,
    }


AXES = (
    "related_comparison",
    "technical_method",
    "implementation_detail",
    "dataset",
    "metric_evaluation",
    "industry_prior_art",
)


def valid_local_literature_coverage() -> dict:
    return {
        "contract_version": "1.0",
        "coverage_id": "local-literature-coverage/run-001",
        "manuscript_snapshot_sha256": SHA_E,
        "assessed_at": "2026-07-21T00:00:00Z",
        "local_corpus_refs": [
            {
                "ref": "evidence/local-paper-001",
                "sha256": SHA_C,
                "source_kind": "PAPER",
            }
        ],
        "axes": {
            axis: {
                "criterion": f"Coverage criterion for {axis}.",
                "status": "SUFFICIENT",
                "local_source_refs": ["evidence/local-paper-001"],
                "rationale": "The frozen local source satisfies this criterion.",
            }
            for axis in AXES
        },
    }


def _deficit_with_outcome(outcome: str) -> dict:
    payload = valid_local_literature_coverage()
    terminal_status = {
        "PROVIDER_FAILURE": "PROVIDER_FAILURE",
        "PARTIAL_OR_UNRESOLVED_ZERO_RESULT": "UNRESOLVED_ZERO_RESULT",
        "NO_EVIDENCE_AFTER_VALID_SEARCH": "SUCCESS_EMPTY",
    }[outcome]
    response_sha256 = None if outcome == "PROVIDER_FAILURE" else SHA_D
    payload["axes"]["related_comparison"] = {
        "criterion": "A same-contract comparison is required.",
        "status": "DEFICIT",
        "local_source_refs": [],
        "rationale": "No local source closes the comparison axis.",
        "query_authorization": {
            "authorization_id": "search-authorization/DEF-001",
            "deficit_id": "DEF-001",
            "frozen_plan_sha256": SHA_A,
            "created_at": "2026-07-21T00:01:00Z",
            "outcome": outcome,
            "terminal_trace_sha256": SHA_B,
            "attempts": {
                "attempt-001": {
                    "provider": "SEMANTIC_SCHOLAR",
                    "query": "same input output contract comparison",
                    "query_sha256": SHA_C,
                    "terminal": {
                        "closed": True,
                        "status": terminal_status,
                        "result_count": 0,
                        "admissible_rows": 0,
                        "response_sha256": response_sha256,
                    },
                }
            },
            "metadata_rows": [],
        },
    }
    return payload


def valid_section_bundle() -> dict:
    return {
        "contract_version": "1.0",
        "bundle_id": "section-bundle/introduction",
        "worker_role": "manuscript-introduction-author",
        "section_id": "introduction",
        "manuscript_snapshot_sha256": SHA_E,
        "authorization_receipt": {
            "ref": "receipts/authorization-introduction",
            "sha256": SHA_A,
            "worker_role": "manuscript-introduction-author",
        },
        "input_refs": [
            {
                "ref": "contracts/manuscript-contract",
                "sha256": SHA_E,
                "slice_kind": "GLOBAL_CONTRACT",
            },
            {
                "ref": "evidence/local-paper-001",
                "sha256": SHA_C,
                "slice_kind": "CLAIM_EVIDENCE",
            },
        ],
        "claim_support_refs": [
            {
                "claim_id": "CLM-001",
                "evidence_refs": ["evidence/local-paper-001"],
                "result_refs": [],
            }
        ],
        "draft_latex": "\\section{Introduction} Traceable evidence supports the claim.",
        "citation_keys": ["LocalPaper2026"],
        "labels": ["sec:introduction"],
        "cross_references": [],
        "asset_refs": [],
        "notation_uses": [{"symbol": "H", "meaning_ref": "glossary/H"}],
        "uncertainties": [],
        "omissions": [],
        "requested_supplements": [],
        "content_hash": SHA_D,
    }


def valid_integration() -> dict:
    return {
        "contract_version": "1.0",
        "integration_id": "manuscript-integration/run-001",
        "integrator_role": "manuscript-integrator",
        "manuscript_snapshot_sha256": SHA_E,
        "section_bundle_refs": [
            {
                "section_id": "introduction",
                "bundle_ref": "inbox/section-introduction.bundle.json",
                "bundle_sha256": SHA_A,
                "content_hash": SHA_D,
            }
        ],
        "canonical_file_inventory": [
            {"path": "main.tex", "sha256": SHA_A, "kind": "MAIN_TEX"},
            {"path": "refs.bib", "sha256": SHA_B, "kind": "BIBLIOGRAPHY"},
            {
                "path": "sections/introduction.tex",
                "sha256": SHA_C,
                "kind": "SECTION",
            },
        ],
        "source_tree_sha256": SHA_E,
        "reconciliation_findings": [
            {
                "finding_id": "REC-001",
                "category": "TERMINOLOGY",
                "disposition": "RESOLVED",
                "details": "Canonical terminology applied.",
                "affected_refs": ["section-bundle/introduction"],
            }
        ],
        "unresolved_interfaces": [],
        "integration_hash": SHA_D,
    }


@pytest.mark.parametrize(
    "schema_name",
    [
        "manuscript_contract.schema.json",
        "local_literature_coverage.schema.json",
        "manuscript_section_bundle.schema.json",
        "manuscript_integration.schema.json",
    ],
)
def test_schemas_are_valid_draft_2020_12(schema_name):
    validator = _validator(schema_name)
    assert validator.schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert validator.schema["$id"].startswith("https://research-os/schemas/")


def test_complete_frozen_manuscript_contract_validates():
    _assert_valid("manuscript_contract.schema.json", valid_manuscript_contract())


@pytest.mark.parametrize(
    "field",
    [
        "paper_brief",
        "paper_type",
        "venue_profile",
        "outline",
        "claim_ledger",
        "evidence_refs",
        "result_refs",
        "glossary",
        "bibliography",
        "asset_plan",
        "resolved_tokens",
        "dependency_slices",
        "source_hashes",
        "manuscript_snapshot_sha256",
    ],
)
def test_contract_rejects_missing_frozen_snapshot_fields(field):
    payload = valid_manuscript_contract()
    del payload[field]
    _assert_invalid("manuscript_contract.schema.json", payload)


def test_contract_requires_non_weakenable_official_requires_pdf_policy():
    payload = valid_manuscript_contract()
    payload["venue_profile"]["hard_field_policy"]["requires_pdf"]["weakenable"] = True
    _assert_invalid("manuscript_contract.schema.json", payload)


def test_contract_rejects_unknown_fields_and_malformed_hashes():
    payload = valid_manuscript_contract()
    payload["promotion_authorized"] = True
    _assert_invalid("manuscript_contract.schema.json", payload)

    payload = valid_manuscript_contract()
    payload["source_hashes"][0]["sha256"] = "not-a-sha256"
    _assert_invalid("manuscript_contract.schema.json", payload)


def test_all_six_local_coverage_axes_are_required_and_closed():
    payload = valid_local_literature_coverage()
    _assert_valid("local_literature_coverage.schema.json", payload)

    del payload["axes"]["dataset"]
    _assert_invalid("local_literature_coverage.schema.json", payload)

    payload = valid_local_literature_coverage()
    payload["axes"]["seventh_axis"] = payload["axes"]["dataset"]
    _assert_invalid("local_literature_coverage.schema.json", payload)


@pytest.mark.parametrize("status", ["SUFFICIENT", "DEFICIT", "UNVERIFIED"])
def test_coverage_axes_accept_only_declared_states(status):
    payload = valid_local_literature_coverage()
    axis = payload["axes"]["dataset"]
    axis["status"] = status
    if status == "DEFICIT":
        axis.update(_deficit_with_outcome("PROVIDER_FAILURE")["axes"]["related_comparison"])
    _assert_valid("local_literature_coverage.schema.json", payload)

    axis["status"] = "PROVIDER_FAILURE"
    _assert_invalid("local_literature_coverage.schema.json", payload)


def test_only_a_deficit_can_carry_query_authorization():
    payload = _deficit_with_outcome("PROVIDER_FAILURE")
    authorization = payload["axes"]["related_comparison"].pop("query_authorization")
    _assert_invalid("local_literature_coverage.schema.json", payload)

    payload = valid_local_literature_coverage()
    payload["axes"]["dataset"]["query_authorization"] = authorization
    _assert_invalid("local_literature_coverage.schema.json", payload)


@pytest.mark.parametrize(
    "outcome",
    [
        "PROVIDER_FAILURE",
        "PARTIAL_OR_UNRESOLVED_ZERO_RESULT",
        "NO_EVIDENCE_AFTER_VALID_SEARCH",
    ],
)
def test_search_authorization_accepts_exact_routed_outcomes(outcome):
    _assert_valid(
        "local_literature_coverage.schema.json",
        _deficit_with_outcome(outcome),
    )


def test_no_evidence_requires_complete_successful_zero_row_terminal_trace():
    payload = _deficit_with_outcome("NO_EVIDENCE_AFTER_VALID_SEARCH")
    terminal = payload["axes"]["related_comparison"]["query_authorization"]["attempts"]["attempt-001"]["terminal"]

    terminal["closed"] = False
    _assert_invalid("local_literature_coverage.schema.json", payload)

    payload = _deficit_with_outcome("NO_EVIDENCE_AFTER_VALID_SEARCH")
    payload["axes"]["related_comparison"]["query_authorization"]["attempts"]["attempt-001"]["terminal"]["status"] = "PROVIDER_FAILURE"
    _assert_invalid("local_literature_coverage.schema.json", payload)

    payload = _deficit_with_outcome("NO_EVIDENCE_AFTER_VALID_SEARCH")
    payload["axes"]["related_comparison"]["query_authorization"]["attempts"]["attempt-001"]["terminal"]["admissible_rows"] = 1
    _assert_invalid("local_literature_coverage.schema.json", payload)


def test_search_trace_has_one_closed_plan_binding_and_rejects_competing_hash():
    payload = _deficit_with_outcome("NO_EVIDENCE_AFTER_VALID_SEARCH")
    authorization = payload["axes"]["related_comparison"]["query_authorization"]
    authorization["trace_bound_to_plan_sha256"] = SHA_D
    _assert_invalid("local_literature_coverage.schema.json", payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claim_support", "EXACT_SPAN"),
        ("exact_span_support", True),
        ("local_full_text_owned", True),
        ("admissible_for_manuscript", True),
    ],
)
def test_search_metadata_cannot_claim_manuscript_evidence(field, value):
    payload = _deficit_with_outcome("PARTIAL_OR_UNRESOLVED_ZERO_RESULT")
    authorization = payload["axes"]["related_comparison"]["query_authorization"]
    authorization["metadata_rows"] = [
        {
            "provider": "SEMANTIC_SCHOLAR",
            "provider_record_id": "paper-001",
            "title": "Candidate metadata only",
            "claim_support": "NONE",
            "exact_span_support": False,
            "local_full_text_owned": False,
            "admissible_for_manuscript": False,
        }
    ]
    authorization["metadata_rows"][0][field] = value
    _assert_invalid("local_literature_coverage.schema.json", payload)


def test_complete_dependency_scoped_section_bundle_validates():
    _assert_valid("manuscript_section_bundle.schema.json", valid_section_bundle())


@pytest.mark.parametrize(
    "field",
    [
        "manuscript_snapshot_sha256",
        "authorization_receipt",
        "input_refs",
        "claim_support_refs",
        "draft_latex",
        "citation_keys",
        "labels",
        "asset_refs",
        "uncertainties",
        "content_hash",
    ],
)
def test_section_bundle_rejects_missing_required_fields(field):
    payload = valid_section_bundle()
    del payload[field]
    _assert_invalid("manuscript_section_bundle.schema.json", payload)


def test_section_bundle_requires_declared_hashes_and_claim_support():
    payload = valid_section_bundle()
    payload["input_refs"][0]["sha256"] = "bad"
    _assert_invalid("manuscript_section_bundle.schema.json", payload)

    payload = valid_section_bundle()
    payload["claim_support_refs"][0]["evidence_refs"] = []
    _assert_invalid("manuscript_section_bundle.schema.json", payload)


def test_section_bundle_requires_the_frozen_global_contract_slice():
    payload = valid_section_bundle()
    payload["input_refs"][0]["slice_kind"] = "CLAIM_EVIDENCE"
    _assert_invalid("manuscript_section_bundle.schema.json", payload)


def test_single_integrator_canonical_inventory_validates():
    _assert_valid("manuscript_integration.schema.json", valid_integration())


@pytest.mark.parametrize(
    "field",
    [
        "integrator_role",
        "manuscript_snapshot_sha256",
        "section_bundle_refs",
        "canonical_file_inventory",
        "source_tree_sha256",
        "reconciliation_findings",
        "unresolved_interfaces",
    ],
)
def test_integration_rejects_missing_canonical_fields(field):
    payload = valid_integration()
    del payload[field]
    _assert_invalid("manuscript_integration.schema.json", payload)


def test_integration_rejects_non_integrator_and_unbound_bundle_hashes():
    payload = valid_integration()
    payload["integrator_role"] = "manuscript-section-author"
    _assert_invalid("manuscript_integration.schema.json", payload)

    payload = valid_integration()
    del payload["section_bundle_refs"][0]["content_hash"]
    _assert_invalid("manuscript_integration.schema.json", payload)


def test_integration_requires_main_and_bibliography_inventory_entries():
    payload = valid_integration()
    payload["canonical_file_inventory"] = payload["canonical_file_inventory"][2:]
    _assert_invalid("manuscript_integration.schema.json", payload)


@pytest.mark.parametrize(
    ("schema_name", "factory"),
    [
        ("manuscript_section_bundle.schema.json", valid_section_bundle),
        ("manuscript_integration.schema.json", valid_integration),
    ],
)
def test_candidate_and_integration_contracts_are_closed(schema_name, factory):
    payload = copy.deepcopy(factory())
    payload["write_to_vault"] = True
    _assert_invalid(schema_name, payload)
