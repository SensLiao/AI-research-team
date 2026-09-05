"""Operated manuscript-authoring recipe contracts.

These tests deliberately exercise the recipe boundary rather than re-testing the
already focused contract, integration, audit, and LaTeX modules.  In particular,
they keep section assignment adaptive and prove that no incomplete candidate set
can reach the single integration transform.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import write_artifact
from research_agent_teams.operate.modes import manuscript_authoring as authoring
from research_agent_teams.tools.validate_artifact import validate_artifact
from .test_manuscript_predraft_schemas import (
    valid_local_literature_coverage,
    valid_manuscript_contract,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _slice(slice_id: str, role: str) -> dict:
    value = {
        "slice_id": slice_id,
        "worker_role": role,
        "input_refs": [
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": "a" * 64,
                "slice_kind": "GLOBAL_CONTRACT",
            }
        ],
    }
    value["slice_sha256"] = _sha(value)
    return value


def _contract(*, sections: list[str]) -> dict:
    specialized = authoring.SPECIALIZED_SECTION_OWNERS
    rows = []
    slices = []
    for section_id in sections:
        role = specialized.get(section_id, "manuscript-section-author")
        slice_id = f"slice-{section_id}"
        rows.append(
            {
                "section_id": section_id,
                "title": section_id.replace("_", " ").title(),
                "purpose": f"Frozen purpose for {section_id}.",
                "required": True,
                "depends_on": [],
            }
        )
        slices.append(_slice(slice_id, role))
    slices.append(_slice("slice-assets", "manuscript-figure-table-engineer"))
    return {
        "run_id": "run-001",
        "paper_type": "EMPIRICAL",
        "manuscript_snapshot_sha256": "a" * 64,
        "outline": rows,
        "dependency_slices": slices,
    }


def _bundle(section_id: str, role: str, snapshot: str) -> dict:
    value = {
        "contract_version": "1.0",
        "bundle_id": f"bundle/{section_id}",
        "worker_role": role,
        "section_id": section_id,
        "manuscript_snapshot_sha256": snapshot,
        "authorization_receipt": {
            "ref": "inbox/authorization.json",
            "sha256": "b" * 64,
            "worker_role": role,
        },
        "input_refs": [
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": snapshot,
                "slice_kind": "GLOBAL_CONTRACT",
            }
        ],
        "claim_support_refs": [
            {"claim_id": "CLM-1", "evidence_refs": ["evidence/local.json"], "result_refs": []}
        ],
        "draft_latex": f"\\section{{{section_id}}}\nEvidence-backed prose.",
        "citation_keys": [],
        "labels": [],
        "cross_references": [],
        "asset_refs": [],
        "notation_uses": [],
        "uncertainties": [],
        "omissions": [],
        "requested_supplements": [],
    }
    value["content_hash"] = _sha(value)
    return value


def _write_contract(run_dir: Path, contract: dict) -> None:
    path = run_dir / authoring.CONTRACT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract), encoding="utf-8")
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps(
            {
                "payload": {
                    "request_text": "Write the frozen AI research manuscript.",
                    "north_star": {"statement": "Produce a truthful manuscript.", "in_scope": [], "out_of_scope": []},
                    "budget": {"max_debug_retries_per_run": 9},
                }
            }
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim_evidence_map() -> dict:
    return {
        "attribution_contract_version": "claim-span/v1",
        "mappings": [
            {
                "claim_id": "CLM-001",
                "loci": [
                    {
                        "locus_id": "LOC-001",
                        "source_ref": "evidence/local-paper-001",
                        "location": "Section 2",
                        "kind": "text",
                        "reported_result": "The local source supports the frozen claim.",
                        "supports_claim": True,
                        "support_relation": "entails",
                        "span_id": "span-001",
                        "snapshot_ref": "evidence/local-paper-001",
                        "document_hash": "c" * 64,
                        "parser_version": "fixture-parser/v1",
                        "char_start": 0,
                        "char_end": 12,
                        "exact_quote": "local source",
                    }
                ],
                "overall_support": "supported",
            }
        ],
    }


def _prepare_design_slice_run(
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    omit_evidence_slice: bool = False,
) -> dict:
    frozen = valid_manuscript_contract()
    frozen["manuscript_snapshot_sha256"] = authoring._hash(
        frozen, omit="manuscript_snapshot_sha256"
    )
    coverage = valid_local_literature_coverage()
    coverage["manuscript_snapshot_sha256"] = frozen["manuscript_snapshot_sha256"]
    write_artifact(
        run_dir,
        "DISCOVER",
        "local-literature-coverage.artifact.json",
        "local_literature_coverage",
        "manuscript-venue-corpus-scout",
        coverage,
        "2026-07-22T00:00:00Z",
    )
    receipts_root = run_dir / authoring.WORKER_ROOT_REL / "receipts"
    venue_receipt_rel = f"{authoring.WORKER_ROOT_REL}/receipts/venue-scout.json"
    evidence_receipt_rel = f"{authoring.WORKER_ROOT_REL}/receipts/evidence-steward.json"
    venue_receipt_sha = _write_json(receipts_root / "venue-scout.json", {"scope": "DISCOVER"})
    evidence_receipt_sha = _write_json(receipts_root / "evidence-steward.json", {"scope": "DESIGN"})
    venue_seed = {
        "authorization_receipt": {
            "ref": venue_receipt_rel,
            "sha256": venue_receipt_sha,
            "worker_role": "manuscript-venue-corpus-scout",
        },
        "venue_profile": copy.deepcopy(frozen["venue_profile"]),
    }
    evidence_seed = {
        "authorization_receipt": {
            "ref": evidence_receipt_rel,
            "sha256": evidence_receipt_sha,
            "worker_role": "manuscript-evidence-steward",
        },
        "evidence_refs": copy.deepcopy(frozen["evidence_refs"]),
        "result_refs": copy.deepcopy(frozen["result_refs"]),
        "bibliography": copy.deepcopy(frozen["bibliography"]),
    }
    _write_json(
        run_dir / authoring.DISCOVERY_REL,
        {"payload": {"manuscript_discovery": {"manuscript_venue_profile_slice": venue_seed}}},
    )
    _write_json(
        run_dir / authoring.ARCHITECT_REL,
        {
            "payload": {
                "manuscript_contract_draft": {
                    key: copy.deepcopy(value)
                    for key, value in frozen.items()
                    if key != "manuscript_snapshot_sha256"
                }
            }
        },
    )
    admission = {
        "claim_evidence_map": _claim_evidence_map(),
        "evidence_refs": copy.deepcopy(frozen["evidence_refs"]),
        "result_refs": copy.deepcopy(frozen["result_refs"]),
        "bibliography": copy.deepcopy(frozen["bibliography"]),
    }
    if not omit_evidence_slice:
        admission["manuscript_evidence_slice"] = evidence_seed
    _write_json(
        run_dir / authoring.EVIDENCE_STEWARD_REL,
        {"payload": {"manuscript_evidence_admission": admission}},
    )
    freeze_input = {}

    def fake_freeze(contract_draft, *_args, **_kwargs):
        freeze_input["contract_draft"] = copy.deepcopy(contract_draft)
        return copy.deepcopy(frozen)

    monkeypatch.setattr(authoring, "freeze_manuscript_contract", fake_freeze)
    return {
        "frozen": frozen,
        "freeze_input": freeze_input,
        "venue_receipt_rel": venue_receipt_rel,
        "evidence_receipt_rel": evidence_receipt_rel,
    }


GOLD_CASE_ASSERTIONS = {
    "local-sufficient": "local-first suppresses search",
    "local-named-deficit": "named deficit only",
    "retrieval-provider-matrix": "provider failure remains distinct",
    "retrieval-exhaustive-no-evidence": "closed trace required",
    "token-official-hard-override": "official hard policy",
    "snapshot-targeted-invalidation": "descendant-only refresh",
    "bundle-section-and-integrator-closure": "exact one bundle closure",
    "dag-bounded-repair-and-authorization": "two repair attempts and scoped DAG",
    "truth-unsupported-load-bearing-claim": "truth audit hard block",
    "truth-citation-identity-entailment": "citation audit hard block",
    "truth-numeric-receipt-false-execution": "receipt-bound execution truth",
    "asset-path-escape-matrix": "run-owned path boundary",
    "asset-director-owned-immutability": "director assets immutable",
    "build-fake-compiler-matrix": "receipt-bound compiled branch",
    "build-toolchain-missing": "truthful source-only branch",
    "review-frozen-input-separation": "review run stays separate",
    "end-to-end-authoring": "human-first report set",
}


def test_all_gold_cases_have_operated_or_focused_traceability():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "manuscript" / "gold_cases.json").read_text(encoding="utf-8")
    )
    observed = {row["case_id"] for row in fixture["cases"]}
    assert observed == set(GOLD_CASE_ASSERTIONS)
    assert len(GOLD_CASE_ASSERTIONS) == 17


def test_adaptive_section_assignments_preserve_specialists_and_parameterize_remaining():
    contract = _contract(
        sections=["abstract", "introduction", "methods", "discussion", "appendix", "venue_checklist"]
    )

    assignments = authoring.assign_section_owners(contract)

    by_section = {row["section_id"]: row["worker_role"] for row in assignments}
    assert by_section == {
        "abstract": "manuscript-section-author",
        "introduction": "manuscript-introduction-author",
        "methods": "manuscript-methods-author",
        "discussion": "manuscript-section-author",
        "appendix": "manuscript-section-author",
        "venue_checklist": "manuscript-section-author",
    }
    assert {row["section_id"] for row in assignments} == {
        "abstract", "introduction", "methods", "discussion", "appendix", "venue_checklist"
    }


@pytest.mark.parametrize("with_asset", [False, True])
@pytest.mark.parametrize("revision", [False, True])
def test_design_reducer_freezes_one_asset_slice_for_all_authoring_shapes(
    with_asset, revision, monkeypatch
):
    draft = _contract(sections=["abstract"])
    draft.update(
        contract_id="manuscript-contract/run-001",
        asset_plan=[],
        result_refs=[],
        source_hashes=[
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": "a" * 64,
                "kind": "VENUE_RULE",
            }
        ],
    )
    if with_asset:
        draft["asset_plan"] = [
            {
                "asset_id": "fig-overview",
                "kind": "FIGURE",
                "label": "fig:overview",
                "planned_path": "figures/overview.pdf",
                "source_refs": ["inputs/overview.svg"],
                "result_refs": [],
            }
        ]
        draft["source_hashes"].append(
            {
                "ref": "inputs/overview.svg",
                "sha256": "b" * 64,
                "kind": "ASSET",
            }
        )
    if revision:
        draft["revision_requirements"] = [
            {
                "issue_id": "R1",
                "review_sha256": "c" * 64,
                "review_quote": "Keep the overview aligned with the revised abstract.",
                "lane": "prose_repair",
                "target_section": "abstract",
                "acceptance_criterion": "The revised abstract and overview agree.",
            }
        ]

    reduced = authoring._with_deterministic_asset_slice(draft)

    asset_slices = [
        row
        for row in reduced["dependency_slices"]
        if row["worker_role"] == "manuscript-figure-table-engineer"
    ]
    assert len(asset_slices) == 1
    asset_slice = asset_slices[0]
    assert asset_slice["slice_id"] == "slice-assets"
    assert asset_slice["slice_sha256"] == authoring._hash(
        asset_slice, omit="slice_sha256"
    )
    assert asset_slice["input_refs"][0]["ref"] == (
        "contracts/manuscript-contract.json"
    )
    assert asset_slice["input_refs"][0]["slice_kind"] == "GLOBAL_CONTRACT"
    visible = asset_slice["input_refs"][1:]
    if with_asset:
        assert visible == [
            {
                "ref": "inputs/overview.svg",
                "sha256": "b" * 64,
                "slice_kind": "ASSET",
            }
        ]
    else:
        assert visible == []

    # Scheduling consumes the same helper through the frozen contract; its
    # asset lookup must now be unambiguous for both ordinary and revision runs.
    assert authoring._slice_for_assignment(
        reduced, "assets", "manuscript-figure-table-engineer"
    ) == asset_slice
    monkeypatch.setattr(authoring, "load_frozen_contract", lambda _run_dir: reduced)
    panel = authoring._author_panel(".", "author or revise")
    asset_workers = [
        row
        for row in panel["workers"]
        if row["label"] == "manuscript-figure-table-engineer"
    ]
    assert len(asset_workers) == 1
    assert (
        "inputs/overview.svg"
        in asset_workers[0]["input_contract"]["allowed_inputs"]
    ) is with_asset
    assert draft["dependency_slices"][-1]["input_refs"][0]["ref"] == (
        "contracts/manuscript-contract.json"
    )


def test_asset_slice_reuses_declared_results_without_minting_receipts():
    draft = _contract(sections=["abstract"])
    result = {
        "ref": "results/frozen.json",
        "sha256": "d" * 64,
        "status": "FROZEN",
        "receipt_ref": "receipts/executor.json",
        "receipt_sha256": "e" * 64,
    }
    draft.update(
        contract_id="manuscript-contract/run-001",
        asset_plan=[
            {
                "asset_id": "tab-result",
                "kind": "TABLE",
                "label": "tab:result",
                "planned_path": "tables/result.tex",
                "source_refs": [],
                "result_refs": [result["ref"]],
            }
        ],
        result_refs=[copy.deepcopy(result)],
        source_hashes=[
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": "a" * 64,
                "kind": "VENUE_RULE",
            },
            {"ref": result["ref"], "sha256": result["sha256"], "kind": "RESULT"},
        ],
    )

    reduced = authoring._with_deterministic_asset_slice(draft)
    asset_slice = next(
        row
        for row in reduced["dependency_slices"]
        if row["worker_role"] == "manuscript-figure-table-engineer"
    )

    assert reduced["result_refs"] == [result]
    assert asset_slice["input_refs"][1:] == [
        {
            "ref": result["ref"],
            "sha256": result["sha256"],
            "slice_kind": "RESULT",
        }
    ]
    assert all("receipt" not in row for row in asset_slice["input_refs"])


def test_asset_slice_refuses_an_unfrozen_planned_source():
    draft = _contract(sections=["abstract"])
    draft.update(
        contract_id="manuscript-contract/run-001",
        asset_plan=[
            {
                "asset_id": "fig-missing",
                "kind": "FIGURE",
                "label": "fig:missing",
                "planned_path": "figures/missing.pdf",
                "source_refs": ["inputs/missing.svg"],
                "result_refs": [],
            }
        ],
        result_refs=[],
        source_hashes=[
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": "a" * 64,
                "kind": "VENUE_RULE",
            }
        ],
    )

    with pytest.raises(
        authoring.ManuscriptAuthoringError, match="ASSET_SOURCE_HASH_MISSING"
    ):
        authoring._with_deterministic_asset_slice(draft)


def test_design_evidence_steward_can_read_hash_bound_upstream_handoff(tmp_path):
    panel = authoring.llm_step(str(tmp_path), "DESIGN", "write the review")
    steward = next(
        worker
        for worker in panel["workers"]
        if worker["label"] == "manuscript-evidence-steward"
    )

    assert "inbox/upstream-grounding.json" in steward["input_contract"]["allowed_inputs"]
    assert (
        "inbox/upstream-citation-handoff/**"
        in steward["input_contract"]["allowed_inputs"]
    )
    assert "inbox/manuscript-inputs/**" in steward["input_contract"]["allowed_inputs"]
    architect = next(
        worker for worker in panel["workers"] if worker["label"] == "manuscript-architect"
    )
    assert "inbox/manuscript-inputs/**" in architect["input_contract"]["allowed_inputs"]


def test_worker_prompt_embeds_the_publication_grade_role_contract():
    methods_prompt = authoring._prompt(
        "manuscript-methods-author", "ANALYZE", "write the full review"
    )
    section_prompt = authoring._prompt(
        "manuscript-section-author", "ANALYZE", "write the full review"
    )
    integrator_contract = (
        Path(__file__).resolve().parents[2]
        / "research_agent_teams" / "agents" / "manuscript-integrator.md"
    ).read_text(encoding="utf-8")

    assert "workflow_execution_manifest" in methods_prompt
    assert "synthesis_question" in section_prompt
    assert "claim_surface_owner" in integrator_contract
    assert "not an LLM seat" in integrator_contract


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_id", "wrong_role"])
def test_exact_bundle_closure_rejects_all_invalid_sets_before_integration(mutation):
    contract = _contract(sections=["abstract", "introduction"])
    assignments = authoring.assign_section_owners(contract)
    rows = {
        f"inbox/{assignment['section_id']}.json": _bundle(
            assignment["section_id"], assignment["worker_role"], contract["manuscript_snapshot_sha256"]
        )
        for assignment in assignments
    }
    if mutation == "missing":
        rows.pop("inbox/abstract.json")
    elif mutation == "duplicate":
        rows["inbox/abstract-copy.json"] = dict(rows["inbox/abstract.json"])
    elif mutation == "wrong_id":
        rows["inbox/abstract.json"]["section_id"] = "not_in_outline"
    else:
        rows["inbox/abstract.json"]["worker_role"] = "manuscript-results-author"

    with pytest.raises(authoring.ManuscriptAuthoringError):
        authoring.validate_section_bundle_closure(contract, rows)


def test_author_panel_is_sparse_adaptive_and_auditors_are_blind(tmp_path, monkeypatch):
    contract = _contract(sections=["abstract", "introduction", "related_work", "venue_checklist"])
    _write_contract(tmp_path, contract)
    monkeypatch.setattr(authoring, "load_frozen_contract", lambda _run_dir: contract)

    panel = authoring.llm_step(str(tmp_path), "ANALYZE", "write")
    labels = [worker["label"] for worker in panel["workers"]]
    generic = [worker for worker in panel["workers"] if worker["label"] == "manuscript-section-author"]

    assert panel["group_barriers"] is False
    assert labels.count("manuscript-section-author") == 2
    assert {worker["assignment"]["section_id"] for worker in generic} == {"abstract", "venue_checklist"}
    assert "manuscript-introduction-author" in labels
    assert "manuscript-related-work-author" in labels
    assert "manuscript-synthesis-editor" in labels
    assert "manuscript-integrator" not in labels
    for worker in panel["workers"]:
        if worker["label"] in authoring.SECTION_AUTHOR_ROLES:
            assert worker["output"].endswith(".tex")
            assert "Do not write JSON" in worker["prompt"]
            assert authoring.CONTRACT_REL in worker["input_contract"]["allowed_inputs"]
            assert "draft/MANUSCRIPT-ONTOLOGY.md" in worker["input_contract"]["allowed_inputs"]
            assert (
                "inbox/manuscript-authoring/admitted-evidence.json"
                not in worker["input_contract"]["allowed_inputs"]
            )

    review = authoring.llm_step(str(tmp_path), "VERIFY", "audit")
    assert review["group_barriers"] is False
    for worker in review["workers"]:
        assert worker["input_contract"]["blind"] is True
        assert "evidence/VERIFY/**" in worker["input_contract"]["forbidden_inputs"]
        assert "source/**" in worker["input_contract"]["allowed_inputs"]


def test_revision_dispatches_only_affected_section_and_preserves_other_latex(tmp_path, monkeypatch):
    contract = _contract(sections=["abstract", "introduction"])
    contract["revision_requirements"] = [{
        "issue_id": "R1",
        "review_sha256": "a" * 64,
        "review_quote": "Fix the abstract terminology.",
        "lane": "prose_repair",
        "target_section": "abstract",
        "acceptance_criterion": "Abstract uses the ontology term.",
    }]
    _write_contract(tmp_path, contract)
    current = tmp_path / "inbox" / "manuscript-inputs" / "current-source" / "sections"
    current.mkdir(parents=True)
    (current / "abstract.tex").write_text("old abstract", encoding="utf-8")
    (current / "introduction.tex").write_text("unchanged introduction", encoding="utf-8")
    monkeypatch.setattr(authoring, "load_frozen_contract", lambda _run_dir: contract)

    panel = authoring.llm_step(str(tmp_path), "ANALYZE", "revise")
    section_workers = [row for row in panel["workers"] if row["label"] in authoring.SECTION_AUTHOR_ROLES]

    assert [row["assignment"]["section_id"] for row in section_workers] == ["abstract"]
    assert (tmp_path / "draft/sections/introduction.tex").read_text(encoding="utf-8") == "unchanged introduction"


def test_integration_wrapper_never_calls_integrator_when_closure_is_invalid():
    contract = _contract(sections=["abstract", "introduction"])
    called = False

    def _integrator(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not be reached")

    with pytest.raises(authoring.ManuscriptAuthoringError):
        authoring.integrate_section_bundles(
            run_root=".",
            contract=contract,
            bundle_payloads={
                "inbox/abstract.json": _bundle(
                    "abstract", "manuscript-section-author", contract["manuscript_snapshot_sha256"]
                )
            },
            bibliography_text="@article{unused, title={Unused}}",
            integrator_fn=_integrator,
        )
    assert called is False


def test_bundle_loader_accepts_direct_schema_object_without_redundant_wrapper(
    tmp_path,
):
    contract = _contract(sections=["abstract"])
    ref = authoring._worker_rel("manuscript-section-author", section_id="abstract")
    payload = _bundle(
        "abstract",
        "manuscript-section-author",
        contract["manuscript_snapshot_sha256"],
    )
    _write_json(tmp_path / ref, payload)

    loaded = authoring._bundle_payloads(tmp_path, contract)

    assert loaded[ref] == payload


def test_run_authorization_verifier_reopens_scheduler_and_contract(tmp_path):
    contract = _contract(sections=["abstract"])
    _write_contract(tmp_path, contract)
    bundle_ref = authoring._worker_rel(
        "manuscript-section-author", section_id="abstract"
    )
    row = {
        "worker_id": f"0:manuscript-section-author:{bundle_ref}",
        "agent": "manuscript-section-author",
        "source_label": "manuscript-section-author",
        "output": bundle_ref,
        "logical_output": bundle_ref,
        "cycle": 0,
        "wave": 1,
        "authorized_at": "2026-07-22T00:00:00Z",
        "authorization_kind": "initial",
        "dispatch_instance_id": "dispatch-test",
    }
    _write_json(
        tmp_path / "inbox/panel-scheduler/ANALYZE.json",
        {
            "contract_version": "panel-dispatch/v1",
            "stage": "ANALYZE",
            "authorizations": [row],
            "waves": [],
        },
    )
    dependency_slice = next(
        item
        for item in contract["dependency_slices"]
        if item["slice_id"] == "slice-abstract"
    )
    facts = {
        "run_id": contract["run_id"],
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "stage": "ANALYZE",
        "section_id": "abstract",
        "worker_role": "manuscript-section-author",
        "dependency_slice_id": "slice-abstract",
        "dependency_slice_sha256": dependency_slice["slice_sha256"],
        "bundle_ref": bundle_ref,
        "authorization_sha256": _sha(row),
    }
    verifier = authoring._run_authorization_verifier(tmp_path)

    assert verifier(facts) == {"verified": True, **facts}
    assert verifier({**facts, "authorization_sha256": "f" * 64})["verified"] is False


def test_audit_facts_are_derived_from_frozen_bundles_not_integrator_summary():
    contract = _contract(sections=["abstract"])
    contract.update(
        claim_ledger=[],
        evidence_refs=[],
        result_refs=[],
        bibliography={
            "style": "plain",
            "entries": [
                {
                    "citation_key": "FrozenKey",
                    "source_ref": "evidence/frozen",
                    "source_sha256": "c" * 64,
                    "identity_status": "VERIFIED",
                }
            ],
        },
        glossary={"terms": [], "notation": []},
    )
    bundle = _bundle(
        "abstract", "manuscript-section-author", contract["manuscript_snapshot_sha256"]
    )
    bundle["citation_keys"] = ["FrozenKey"]

    facts = authoring._derive_manuscript_audit_facts(
        contract=contract,
        bundle_payloads={"inbox/abstract.json": bundle},
        claim_map={"mappings": []},
        integration={"source_tree_sha256": "d" * 64},
        request={"preserved_warnings": []},
    )

    assert facts["manuscript_sha256"] == "d" * 64
    assert facts["sections"] == [
        {"section_id": "abstract", "claim_ids": ["CLM-1"], "citation_keys": ["FrozenKey"]}
    ]
    assert facts["bibliography_keys"] == ["FrozenKey"]
    assert facts["anonymity_violations"] == []
    assert facts["official_rule_violations"] == []


def _aggregate_evidence_fact_inputs():
    """Synthetic unit-test inputs; no research audit was executed for these claims."""
    contract = _contract(sections=["methods"])
    contract.update(
        claim_ledger=[
            {
                "claim_id": "CLM-1",
                "importance": "LOAD_BEARING",
                "claim_text": "A protocol-level claim.",
                "evidence_refs": ["evidence/extraction.json"],
                "result_refs": [],
            }
        ],
        evidence_refs=[
            {
                "ref": "evidence/extraction.json",
                "sha256": "c" * 64,
                "source_kind": "LOCAL_FULL_TEXT",
                "claim_support": "CLAIM_LEVEL",
            }
        ],
        result_refs=[],
        bibliography={
            "style": "author-year",
            "entries": [
                {
                    "citation_key": "Verified2026",
                    "source_ref": "evidence/bibliography.json",
                    "source_sha256": "d" * 64,
                    "identity_status": "VERIFIED",
                }
            ],
        },
        glossary={"terms": [], "notation": []},
    )
    bundle = _bundle(
        "methods", "manuscript-methods-author", contract["manuscript_snapshot_sha256"]
    )
    bundle["citation_keys"] = ["Verified2026"]
    mapping = {
        "mappings": [
            {
                "claim_id": "CLM-1",
                "overall_support": "supported",
                "loci": [
                    {
                        "locus_id": "L-UNIT-1",
                        "source_ref": "arXiv:2601.00001",
                        "snapshot_ref": "evidence/fulltext.txt",
                        "exact_quote": "The directly inspected full text supports the claim.",
                        "supports_claim": True,
                        "support_relation": "entails",
                    }
                ],
            }
        ]
    }

    return {
        "contract": contract,
        "bundle_payloads": {"inbox/methods.json": bundle},
        "claim_map": mapping,
        "integration": {"source_tree_sha256": "e" * 64},
        "request": {
            "citation_closure": {
                "section_citation_keys": ["Verified2026"],
                "verified_identity_count": 1,
                "unverified_identity_count": 0,
            },
            "preserved_warnings": [],
        },
    }


def test_audit_facts_project_verified_aggregate_evidence_chain(tmp_path):
    # Match the citation-coverage-auditor bundle read by the projection. This
    # record simulates that input interface only; it is not execution evidence.
    audit = {
        "citation_audit": {
            "contract_version": "citation-attribution/v1",
            "independent_of_linker": True,
            "claim_results": [
                {
                    "claim_id": "CLM-1",
                    "verdict": "entails",
                    "locator_verified": True,
                    "verified_locus_ids": ["L-UNIT-1"],
                    "unsupported_locus_ids": [],
                    "notes": "Synthetic unit-test audit input; no external audit was executed.",
                }
            ],
        }
    }
    audit_path = (
        tmp_path / "inbox" / "manuscript-inputs" / "evidence"
        / "DISCOVER.citation-coverage-auditor.bundle.json"
    )
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    facts = authoring._derive_manuscript_audit_facts(
        **_aggregate_evidence_fact_inputs(), run_root=tmp_path,
    )

    assert facts["claim_evidence"] == [
        {
            "claim_id": "CLM-1",
            "evidence_ref": "evidence/extraction.json",
            "source_sha256": "c" * 64,
            "citation_key": "Verified2026",
            "observed_citation_key": "Verified2026",
            "exact_span": "The directly inspected full text supports the claim.",
            "entailment": "ENTAILED",
            "metadata_only": False,
            "independent_audit": True,
            "evidence_chain_verified": True,
            "citation_identity_verified": True,
        }
    ]


def test_audit_facts_without_independent_citation_audit_remain_partial(tmp_path):
    # Linker support and verified bibliography identities alone cannot stand in
    # for the independent auditor's locator/entailment record.
    facts = authoring._derive_manuscript_audit_facts(
        **_aggregate_evidence_fact_inputs(), run_root=tmp_path,
    )
    link = facts["claim_evidence"][0]
    assert link["citation_identity_verified"] is True
    assert link["entailment"] == "PARTIAL"
    assert link["independent_audit"] is False
    assert link["evidence_chain_verified"] is False


def test_table_asset_normalization_preserves_realized_csv_bytes(tmp_path):
    csv_ref = "inbox/manuscript-inputs/tables/protocol-matrix.csv"
    csv_path = tmp_path / csv_ref
    csv_path.parent.mkdir(parents=True)
    csv_path.write_bytes(b"id,class\nP1,O0\n")
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source_ref = "inbox/manuscript-inputs/tables/protocol-matrix.json"
    source_path = tmp_path / source_ref
    source_path.write_text('{"rows":[]}', encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest = {
        "assets": [
            {
                "asset_id": "prompt-provenance-matrix",
                "asset_type": "TABLE",
                "source_inputs": [
                    {"ref": source_ref, "sha256": source_sha, "kind": "EXTERNAL_EVIDENCE", "immutable": True}
                ],
                "output": {
                    "path": csv_ref,
                    "sha256": csv_sha,
                    "byte_size": csv_path.stat().st_size,
                },
                "provenance": {"kind": "EXTERNAL", "created_at": "2026-08-17T00:00:00Z"},
            }
        ]
    }

    normalized = authoring._normalize_asset_manifest_for_integration(tmp_path, manifest)
    asset = normalized["assets"][0]

    assert asset["output"]["path"] == "tables/prompt-provenance-matrix.csv"
    assert asset["output"]["sha256"] == csv_sha
    assert asset["output"]["byte_size"] == csv_path.stat().st_size
    assert asset["source_inputs"][0]["ref"] == source_ref
    assert asset["provenance"]["external_source"]["source_ref"] == csv_ref


def test_section_bundle_inventory_note_exposes_every_frozen_section_bundle():
    contract = _contract(sections=["abstract", "introduction"])

    note = authoring._section_bundle_inventory_note(contract)

    assert note["summary"].startswith("Frozen direct-LaTeX section inventory")
    assert note["references"] == [
        "draft/synthesis/sections/abstract.tex",
        "draft/synthesis/sections/introduction.tex",
    ]
    assert note["produced_artifacts"] == note["references"]


def test_recipe_caps_schema_supplements_at_two(tmp_path):
    _write_contract(tmp_path, _contract(sections=["abstract"]))

    budget = authoring.repair_budget(str(tmp_path))

    assert budget["max_debug_retries_per_run"] == 2


def test_design_stage_writes_hash_bound_venue_and_evidence_slices(tmp_path, monkeypatch):
    fixture = _prepare_design_slice_run(tmp_path, monkeypatch)

    paths, details = authoring.run_dets(str(tmp_path), "DESIGN", "2026-07-22T00:00:00Z")

    freeze_input = fixture["freeze_input"]["contract_draft"]
    frozen_asset_slices = [
        row
        for row in freeze_input["dependency_slices"]
        if row["worker_role"] == "manuscript-figure-table-engineer"
    ]
    assert len(frozen_asset_slices) == 1
    assert frozen_asset_slices[0]["slice_id"] == "slice-assets"
    assert frozen_asset_slices[0]["slice_sha256"] == authoring._hash(
        frozen_asset_slices[0], omit="slice_sha256"
    )

    assert details["venue_profile_slice"] == authoring.DESIGN_VENUE_PROFILE_SLICE_ARTIFACT
    assert details["evidence_slice"] == authoring.DESIGN_EVIDENCE_SLICE_ARTIFACT
    assert any(path.endswith("manuscript-venue-profile-slice.artifact.json") for path in paths)
    assert any(path.endswith("manuscript-evidence-slice.artifact.json") for path in paths)
    venue_artifact = json.loads(
        (tmp_path / authoring.DESIGN_VENUE_PROFILE_SLICE_ARTIFACT).read_text(encoding="utf-8")
    )
    evidence_artifact = json.loads(
        (tmp_path / authoring.DESIGN_EVIDENCE_SLICE_ARTIFACT).read_text(encoding="utf-8")
    )
    assert validate_artifact(venue_artifact) == []
    assert validate_artifact(evidence_artifact) == []
    venue = venue_artifact["payload"]
    evidence = evidence_artifact["payload"]
    coverage_path = tmp_path / authoring.DISCOVERY_COVERAGE_ARTIFACT
    claim_map_path = tmp_path / authoring.DESIGN_CLAIM_EVIDENCE_MAP_ARTIFACT
    assert venue["manuscript_snapshot_sha256"] == fixture["frozen"]["manuscript_snapshot_sha256"]
    assert venue["local_literature_coverage_ref"] == authoring.DISCOVERY_COVERAGE_ARTIFACT
    assert venue["local_literature_coverage_sha256"] == hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    assert venue["authorization_receipt"]["ref"] == fixture["venue_receipt_rel"]
    assert venue["authorization_receipt"]["sha256"] == hashlib.sha256(
        (tmp_path / fixture["venue_receipt_rel"]).read_bytes()
    ).hexdigest()
    assert venue["venue_profile_slice_sha256"] == authoring._hash(
        venue, omit="venue_profile_slice_sha256"
    )
    assert evidence["claim_evidence_map_ref"] == authoring.DESIGN_CLAIM_EVIDENCE_MAP_ARTIFACT
    assert evidence["claim_evidence_map_sha256"] == hashlib.sha256(claim_map_path.read_bytes()).hexdigest()
    assert evidence["authorization_receipt"]["ref"] == fixture["evidence_receipt_rel"]
    assert evidence["evidence_slice_sha256"] == authoring._hash(
        evidence, omit="evidence_slice_sha256"
    )


def test_provisional_authoring_skips_false_official_venue_slice(
    tmp_path, monkeypatch
):
    fixture = _prepare_design_slice_run(tmp_path, monkeypatch)
    frozen = fixture["frozen"]
    frozen["venue_profile"]["requires_pdf"] = False
    frozen["venue_profile"]["hard_field_policy"]["requires_pdf"].update(
        classification="ADVISORY",
        weakenable=True,
    )

    paths, details = authoring.run_dets(
        str(tmp_path), "DESIGN", "2026-07-22T00:00:00Z"
    )

    assert not any(
        path.endswith("manuscript-venue-profile-slice.artifact.json")
        for path in paths
    )
    assert any(
        path.endswith("manuscript-evidence-slice.artifact.json")
        for path in paths
    )
    assert details["venue_profile_slice"] is None


def test_design_slices_fail_closed_on_missing_worker_bundle(tmp_path, monkeypatch):
    """R3 §B① (2026-08-07): REFERENCE_HASH_MISMATCH is gone from manuscript_authoring.py — a
    tampered-after-declaration receipt file is no longer independently re-verified against its
    declared sha256, so that half of this test (tamper_receipt=True) no longer raises. Retired
    with it: the tamper_receipt path through _prepare_design_slice_run, now always False.
    WORKER_BUNDLE_MISSING is unaffected (an absent slice, not a content mismatch)."""
    _prepare_design_slice_run(
        tmp_path,
        monkeypatch,
        omit_evidence_slice=True,
    )

    with pytest.raises(authoring.ManuscriptAuthoringError, match="WORKER_BUNDLE_MISSING"):
        authoring.run_dets(str(tmp_path), "DESIGN", "2026-07-22T00:00:00Z")


def test_authoring_report_does_not_schedule_the_review_only_submission_packager(tmp_path):
    assert authoring.llm_step(str(tmp_path), "REPORT", "render") is None
