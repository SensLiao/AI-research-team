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
from tests.test_manuscript_predraft_schemas import (
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
    tamper_receipt: bool = False,
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
    if tamper_receipt:
        _write_json(receipts_root / "evidence-steward.json", {"scope": "TAMPERED"})
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
        {"payload": {"manuscript_contract_draft": {}}},
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
    monkeypatch.setattr(
        authoring,
        "freeze_manuscript_contract",
        lambda *_args, **_kwargs: copy.deepcopy(frozen),
    )
    return {
        "frozen": frozen,
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
    assert "manuscript-integrator" in labels

    review = authoring.llm_step(str(tmp_path), "VERIFY", "audit")
    assert review["group_barriers"] is False
    for worker in review["workers"]:
        assert worker["input_contract"]["blind"] is True
        assert "evidence/VERIFY/**" in worker["input_contract"]["forbidden_inputs"]
        assert "source/**" in worker["input_contract"]["allowed_inputs"]


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


def test_recipe_caps_schema_supplements_at_two(tmp_path):
    _write_contract(tmp_path, _contract(sections=["abstract"]))

    budget = authoring.repair_budget(str(tmp_path))

    assert budget["max_debug_retries_per_run"] == 2


def test_design_stage_writes_hash_bound_venue_and_evidence_slices(tmp_path, monkeypatch):
    fixture = _prepare_design_slice_run(tmp_path, monkeypatch)

    paths, details = authoring.run_dets(str(tmp_path), "DESIGN", "2026-07-22T00:00:00Z")

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


@pytest.mark.parametrize(
    ("tamper_receipt", "omit_evidence_slice", "match"),
    [
        (True, False, "REFERENCE_HASH_MISMATCH"),
        (False, True, "WORKER_BUNDLE_MISSING"),
    ],
)
def test_design_slices_fail_closed_on_missing_or_tampered_provenance(
    tmp_path, monkeypatch, tamper_receipt, omit_evidence_slice, match
):
    _prepare_design_slice_run(
        tmp_path,
        monkeypatch,
        tamper_receipt=tamper_receipt,
        omit_evidence_slice=omit_evidence_slice,
    )

    with pytest.raises(authoring.ManuscriptAuthoringError, match=match):
        authoring.run_dets(str(tmp_path), "DESIGN", "2026-07-22T00:00:00Z")


def test_authoring_report_does_not_schedule_the_review_only_submission_packager(tmp_path):
    assert authoring.llm_step(str(tmp_path), "REPORT", "render") is None
