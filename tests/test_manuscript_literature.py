"""TDD contract for local-first manuscript literature routing."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from research_agent_teams.tools import manuscript_literature
from research_agent_teams.tools.manuscript_literature import (
    COVERAGE_AXES,
    LiteratureCoverageError,
    assess_local_coverage,
    build_targeted_query_plan,
    derive_search_outcome,
    route_coverage_deficits,
)
from research_agent_teams.tools.validate_artifact import validate_payload


NOW = "2026-07-21T13:20:00Z"
SNAPSHOT_SHA = hashlib.sha256(b"manuscript-snapshot-01-12").hexdigest()
RESPONSE_A = hashlib.sha256(b"response-a").hexdigest()
RESPONSE_B = hashlib.sha256(b"response-b").hexdigest()
EXPECTED_AXES = (
    "related_comparison",
    "technical_method",
    "implementation_detail",
    "dataset",
    "metric_evaluation",
    "industry_prior_art",
)


def _canonical_sha(value: object, *, omit: str | None = None) -> str:
    if omit is not None:
        value = {key: item for key, item in dict(value).items() if key != omit}
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _criteria() -> dict[str, dict[str, str]]:
    return {
        axis: {
            "criterion": f"Local evidence must cover {axis.replace('_', ' ')}.",
            "recall_query": f"manuscript {axis.replace('_', ' ')}",
        }
        for axis in EXPECTED_AXES
    }


def _coverage(tmp_path: Path, *, empty_axis: str | None = None):
    vault_root = tmp_path / "PhD-Research-OS"
    vault_root.mkdir()
    calls: list[dict] = []

    def recall_spy(query, *, vault_root, project=None, top_k=6):
        calls.append(
            {
                "query": query,
                "vault_root": Path(vault_root),
                "project": project,
                "top_k": top_k,
            }
        )
        axis = query.removeprefix("manuscript ").replace(" ", "_")
        citations = []
        if axis != empty_axis:
            citations = [
                {
                    "slug": f"paper-{axis.replace('_', '-')}",
                    "sha256": "sha256:" + hashlib.sha256(axis.encode()).hexdigest(),
                    "section": "Evidence",
                    "supports": "fixture pointer only",
                }
            ]
        return {
            "query": query,
            "citations": citations,
            "confidence": "high" if citations else "low",
            "vault_silent": not citations,
        }

    coverage = assess_local_coverage(
        coverage_id="coverage-01-12",
        manuscript_snapshot_sha256=SNAPSHOT_SHA,
        assessed_at=NOW,
        criteria=_criteria(),
        vault_root=vault_root,
        allowed_vault_roots=(vault_root,),
        project="fixture-project",
        top_k=3,
        recall_fn=recall_spy,
    )
    return coverage, calls, vault_root


def _plan(coverage: dict, *, providers=("ARXIV", "OPENALEX")) -> dict:
    return build_targeted_query_plan(
        coverage,
        axis="related_comparison",
        deficit_id="DEF-related-comparison",
        query="matched budget graph retrieval comparison",
        providers=providers,
        plan_id="qp-related-comparison",
        created_at=NOW,
    )


def _trace(plan: dict, statuses: tuple[str, ...]) -> dict:
    attempts = {}
    for index, attempt_id in enumerate(plan["attempt_order"]):
        planned = plan["attempts"][attempt_id]
        status = statuses[index]
        attempts[attempt_id] = {
            "provider": planned["provider"],
            "query": planned["query"],
            "query_sha256": planned["query_sha256"],
            "terminal": {
                "closed": True,
                "status": status,
                "result_count": 0,
                "admissible_rows": 0,
                "response_sha256": (
                    None
                    if status == "PROVIDER_FAILURE"
                    else (RESPONSE_A if index == 0 else RESPONSE_B)
                ),
            },
        }
    trace = {
        "contract_version": "1.0",
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "attempt_order": list(plan["attempt_order"]),
        "attempts": attempts,
        "budget_exhausted": False,
        "stopped_early": False,
    }
    trace["trace_sha256"] = _canonical_sha(trace)
    return trace


def _reseal_trace(trace: dict) -> dict:
    trace["trace_sha256"] = _canonical_sha(trace, omit="trace_sha256")
    return trace


def test_coverage_axes_are_the_exact_six_d06_dimensions():
    assert COVERAGE_AXES == EXPECTED_AXES


def test_bounded_local_recall_covers_all_axes_and_returns_references_only(tmp_path: Path):
    coverage, calls, vault_root = _coverage(tmp_path)

    assert len(calls) == 6
    assert {call["query"] for call in calls} == {
        details["recall_query"] for details in _criteria().values()
    }
    assert all(call["vault_root"] == vault_root.resolve() for call in calls)
    assert all(call["project"] == "fixture-project" for call in calls)
    assert all(call["top_k"] == 3 for call in calls)
    assert set(coverage["axes"]) == set(EXPECTED_AXES)
    assert all(axis["status"] == "SUFFICIENT" for axis in coverage["axes"].values())
    assert all(axis["local_source_refs"] for axis in coverage["axes"].values())
    assert all(set(row) == {"ref", "sha256", "source_kind"} for row in coverage["local_corpus_refs"])
    assert all(row["ref"].startswith("vault:") for row in coverage["local_corpus_refs"])
    assert validate_payload("local_literature_coverage", coverage) == []


def test_sufficient_local_coverage_suppresses_every_search_call(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path)
    search_calls = []

    def forbidden_search(*args, **kwargs):
        search_calls.append((args, kwargs))
        raise AssertionError("local sufficiency must suppress search")

    routed = route_coverage_deficits(
        coverage,
        query_plans=(),
        search_many_fn=forbidden_search,
        transport=object(),
    )

    assert routed["coverage"] == coverage
    assert routed["frozen_query_plans"] == []
    assert routed["search_traces"] == []
    assert search_calls == []


def test_only_a_named_unverified_axis_can_create_a_frozen_targeted_plan(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage)

    assert coverage["axes"]["related_comparison"]["status"] == "UNVERIFIED"
    assert plan["axis"] == "related_comparison"
    assert plan["deficit_id"] == "DEF-related-comparison"
    assert plan["exhaustive"] is True
    assert plan["attempt_order"] == [
        "attempt-related-comparison-arxiv",
        "attempt-related-comparison-openalex",
    ]
    assert [plan["attempts"][key]["provider"] for key in plan["attempt_order"]] == [
        "ARXIV",
        "OPENALEX",
    ]
    assert plan["plan_sha256"] == _canonical_sha(plan, omit="plan_sha256")

    with pytest.raises(LiteratureCoverageError, match="UNAUTHORIZED_DEFICIT"):
        build_targeted_query_plan(
            coverage,
            axis="technical_method",
            deficit_id="DEF-method",
            query="a query that local evidence already closes",
            providers=("ARXIV",),
            plan_id="qp-method",
            created_at=NOW,
        )


@pytest.mark.parametrize(
    "query",
    [
        "https://api.openalex.org/works?api_key=fixture-secret",
        "graph retrieval token=fixture-secret",
    ],
)
def test_query_authorization_rejects_secret_bearing_urls_or_assignments(
    tmp_path: Path, query: str
):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")

    with pytest.raises(LiteratureCoverageError, match="UNSAFE_QUERY"):
        build_targeted_query_plan(
            coverage,
            axis="related_comparison",
            deficit_id="DEF-related-comparison",
            query=query,
            providers=("OPENALEX",),
            plan_id="qp-related-comparison",
            created_at=NOW,
        )


def test_named_deficit_calls_only_search_many_and_keeps_openalex_metadata_only(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage, providers=("OPENALEX",))
    transport = object()
    calls = []

    def search_spy(queries, *, sources, limit_per_source, transport):
        calls.append(
            {
                "queries": queries,
                "sources": sources,
                "limit": limit_per_source,
                "transport": transport,
            }
        )
        return {
            "queries": list(queries),
            "records": [
                {
                    "source": "openalex",
                    "id": "W123",
                    "title": "Matched-budget graph retrieval",
                    "url": "https://api.openalex.org/works/W123?token=must-not-return",
                    "abstract": "metadata must not become content",
                    "pdf_url": "https://example.invalid/paper.pdf",
                    "found_in": ["openalex"],
                }
            ],
            "source_errors": {},
        }

    routed = route_coverage_deficits(
        coverage,
        query_plans=(plan,),
        search_many_fn=search_spy,
        transport=transport,
        limit_per_source=4,
    )

    assert calls == [
        {
            "queries": ["matched budget graph retrieval comparison"],
            "sources": ("openalex",),
            "limit": 4,
            "transport": transport,
        }
    ]
    authorization = routed["coverage"]["axes"]["related_comparison"][
        "query_authorization"
    ]
    assert authorization["outcome"] == "PARTIAL_OR_UNRESOLVED_ZERO_RESULT"
    assert authorization["metadata_rows"] == [
        {
            "provider": "OPENALEX",
            "provider_record_id": "W123",
            "title": "Matched-budget graph retrieval",
            "claim_support": "NONE",
            "exact_span_support": False,
            "local_full_text_owned": False,
            "admissible_for_manuscript": False,
        }
    ]
    serialized = json.dumps(routed, sort_keys=True)
    assert "abstract" not in serialized
    assert "pdf_url" not in serialized
    assert "must-not-return" not in serialized
    assert validate_payload("local_literature_coverage", routed["coverage"]) == []


def test_total_required_provider_outage_is_provider_failure(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage)
    trace = _trace(plan, ("PROVIDER_FAILURE", "PROVIDER_FAILURE"))

    derived = derive_search_outcome(plan, trace, metadata_rows=[])

    assert derived["outcome"] == "PROVIDER_FAILURE"
    assert {row["terminal"]["status"] for row in derived["attempts"].values()} == {
        "PROVIDER_FAILURE"
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_failure",
        "budget_exhausted",
        "stopped_early",
        "plan_trace_hash_mismatch",
        "missing_attempt",
        "undeclared_attempt",
        "duplicate_attempt",
    ],
)
def test_any_incomplete_or_unresolved_zero_result_is_never_absence(
    tmp_path: Path, mutation: str
):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage)
    trace = _trace(plan, ("SUCCESS_EMPTY", "SUCCESS_EMPTY"))

    if mutation == "partial_failure":
        second = trace["attempt_order"][1]
        trace["attempts"][second]["terminal"].update(
            status="PROVIDER_FAILURE", response_sha256=None
        )
    elif mutation == "budget_exhausted":
        trace["budget_exhausted"] = True
    elif mutation == "stopped_early":
        trace["stopped_early"] = True
    elif mutation == "plan_trace_hash_mismatch":
        trace["plan_sha256"] = "0" * 64
    elif mutation == "missing_attempt":
        trace["attempts"].pop(trace["attempt_order"][1])
    elif mutation == "undeclared_attempt":
        trace["attempts"]["attempt-undeclared"] = copy.deepcopy(
            next(iter(trace["attempts"].values()))
        )
    elif mutation == "duplicate_attempt":
        trace["attempt_order"].append(trace["attempt_order"][0])
    _reseal_trace(trace)

    derived = derive_search_outcome(plan, trace, metadata_rows=[])

    assert derived["outcome"] == "PARTIAL_OR_UNRESOLVED_ZERO_RESULT"
    assert set(derived["attempts"]) == set(plan["attempt_order"])
    assert all(row["terminal"]["closed"] for row in derived["attempts"].values())


def test_no_evidence_requires_exact_successful_terminal_closure(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage)
    trace = _trace(plan, ("SUCCESS_EMPTY", "SUCCESS_EMPTY"))

    derived = derive_search_outcome(plan, trace, metadata_rows=[])

    assert derived["outcome"] == "NO_EVIDENCE_AFTER_VALID_SEARCH"
    assert derived["trace_complete"] is True
    assert derived["terminal_trace_sha256"] == trace["trace_sha256"]
    assert {row["terminal"]["status"] for row in derived["attempts"].values()} == {
        "SUCCESS_EMPTY"
    }


def test_nonempty_rows_are_forced_to_metadata_only_and_never_prove_absence(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage, providers=("OPENALEX",))
    trace = _trace(plan, ("SUCCESS_WITH_METADATA",))
    attempt_id = trace["attempt_order"][0]
    trace["attempts"][attempt_id]["terminal"].update(result_count=1)
    _reseal_trace(trace)

    derived = derive_search_outcome(
        plan,
        trace,
        metadata_rows=[
            {
                "provider": "OPENALEX",
                "id": "W999",
                "title": "A metadata candidate",
                "claim_support": "ENTAILED",
                "exact_span_support": True,
                "local_full_text_owned": True,
                "admissible_for_manuscript": True,
            }
        ],
    )

    assert derived["outcome"] == "PARTIAL_OR_UNRESOLVED_ZERO_RESULT"
    assert derived["metadata_rows"] == [
        {
            "provider": "OPENALEX",
            "provider_record_id": "W999",
            "title": "A metadata candidate",
            "claim_support": "NONE",
            "exact_span_support": False,
            "local_full_text_owned": False,
            "admissible_for_manuscript": False,
        }
    ]


def test_provider_errors_and_request_urls_are_redacted_before_return(tmp_path: Path):
    coverage, _, _ = _coverage(tmp_path, empty_axis="related_comparison")
    plan = _plan(coverage, providers=("OPENALEX",))

    def failed_search(*args, **kwargs):
        raise RuntimeError(
            "network failure for https://api.openalex.org/works?api_key=super-secret"
        )

    routed = route_coverage_deficits(
        coverage,
        query_plans=(plan,),
        search_many_fn=failed_search,
        transport=object(),
    )

    serialized = json.dumps(routed, sort_keys=True)
    assert routed["coverage"]["axes"]["related_comparison"][
        "query_authorization"
    ]["outcome"] == "PROVIDER_FAILURE"
    assert "super-secret" not in serialized
    assert "?api_key" not in serialized
    assert "https://api.openalex.org/works" in serialized


def test_unapproved_or_linked_vault_roots_fail_before_recall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    allowed = tmp_path / "allowed-vault"
    outside = tmp_path / "outside-vault"
    allowed.mkdir()
    outside.mkdir()
    calls = []

    def recall_spy(*args, **kwargs):
        calls.append((args, kwargs))
        return {"citations": []}

    with pytest.raises(LiteratureCoverageError, match="UNAPPROVED_VAULT_ROOT"):
        assess_local_coverage(
            coverage_id="coverage-unsafe",
            manuscript_snapshot_sha256=SNAPSHOT_SHA,
            assessed_at=NOW,
            criteria=_criteria(),
            vault_root=outside,
            allowed_vault_roots=(allowed,),
            recall_fn=recall_spy,
        )
    assert calls == []

    linked = tmp_path / "linked-vault"
    try:
        os.symlink(allowed, linked, target_is_directory=True)
    except OSError:
        linked.mkdir()
        original_link_check = manuscript_literature._is_link_or_reparse
        monkeypatch.setattr(
            manuscript_literature,
            "_is_link_or_reparse",
            lambda path: path == linked or original_link_check(path),
        )
    with pytest.raises(LiteratureCoverageError, match="LINKED_VAULT_ROOT"):
        assess_local_coverage(
            coverage_id="coverage-linked",
            manuscript_snapshot_sha256=SNAPSHOT_SHA,
            assessed_at=NOW,
            criteria=_criteria(),
            vault_root=linked,
            allowed_vault_roots=(allowed,),
            recall_fn=recall_spy,
        )
    assert calls == []


def test_module_has_no_write_promotion_download_or_direct_provider_surface():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "manuscript_literature.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "research_agent_teams.tools.paper_search" in imported_modules
    assert not ({"urllib", "requests", "subprocess"} & imported_modules)
    assert not ({"open", "promote", "download", "urlopen"} & called_names)
    assert not (
        {
            "write_text",
            "write_bytes",
            "unlink",
            "replace",
            "rename",
            "mkdir",
            "rmdir",
            "download",
        }
        & called_attributes
    )
    assert "search_openalex" not in source
    assert "search_arxiv" not in source
    assert "search_crossref" not in source
    assert "search_s2" not in source
