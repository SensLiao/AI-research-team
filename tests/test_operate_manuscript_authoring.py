"""Operated manuscript-authoring recipe contracts.

These tests deliberately exercise the recipe boundary rather than re-testing the
already focused contract, integration, audit, and LaTeX modules.  In particular,
they keep section assignment adaptive and prove that no incomplete candidate set
can reach the single integration transform.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.modes import manuscript_authoring as authoring


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
