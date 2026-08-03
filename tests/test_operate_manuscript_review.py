"""Operated contracts for the independent manuscript-review recipe.

These tests use frozen local authoring fixtures rather than live model calls.  They
exercise the boundary that matters for an operated review: a separate run must
bind the exact authoring bytes, issue one blind authorization per required
capability, preserve every reviewer finding in reconciliation, and leave every
proposed repair as review-only advice.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock, write_artifact
from research_agent_teams.operate.modes import manuscript_review as review
from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.research_output_quality import audit_run_output
from research_agent_teams.tools.validate_artifact import validate_artifact
from tests.test_manuscript_delivery_schemas import _compiled_build, _compiled_quality
from tests.test_manuscript_predraft_schemas import valid_integration, valid_manuscript_contract


TS = "2026-07-22T00:00:00Z"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return _file_sha(path)


def _source_and_review(tmp_path: Path, *, source_only: bool = False, false_execution: bool = False) -> tuple[Path, Path]:
    """Create two real run-store directories joined solely through a review input manifest."""
    runs = tmp_path / "runs"
    authoring = Path(
        spine.begin(str(runs), "authoring-001", "author a frozen AI paper", "manuscript_authoring", TS)["run_dir"]
    )
    contract = authoring / "inbox" / "manuscript-authoring" / "manuscript-contract.json"
    integration = authoring / "evidence" / "ANALYZE" / "manuscript-integration.artifact.json"
    source = authoring / "source" / "main.tex"
    quality = authoring / "evidence" / "ANALYZE" / "manuscript-quality-report.artifact.json"
    build = authoring / "evidence" / "ANALYZE" / "manuscript-build-receipt.artifact.json"
    _write_json(contract, {"run_id": "authoring-001", "paper_type": "EMPIRICAL"})
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("\\documentclass{article}\\begin{document}Frozen manuscript.\\end{document}\n", encoding="utf-8")
    source_sha = _file_sha(source)
    _write_json(integration, {"source_tree_sha256": source_sha, "integration_sha256": "a" * 64})
    findings = []
    if false_execution:
        findings.append(
            {
                "finding_id": "AUDIT-FALSE-EXECUTION",
                "finding_class": "HARD",
                "status": "OPEN",
                "code": "FALSE_EXECUTION_CLAIM",
                "message": "Claimed execution lacks an executor receipt.",
                "evidence_refs": ["source/main.tex"],
                "repair": "Bind a real executor receipt.",
                "submission_effect": "BLOCK",
            }
        )
    _write_json(
        quality,
        {
            "quality_report_sha256": "b" * 64,
            "daily_state": "USABLE_WITH_CAVEATS" if source_only else "USABLE",
            "submission_ready": not source_only and not false_execution,
            "findings": findings,
            "submission_blockers": [],
        },
    )
    pdf_ref: dict[str, str] | None = None
    if source_only:
        _write_json(build, {"build_state": "TOOLCHAIN_MISSING", "pdf": None})
    else:
        pdf = authoring / "build" / "main.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4\nfixture\n")
        pdf_ref = {"ref": "build/main.pdf", "sha256": _file_sha(pdf)}
        _write_json(build, {"build_state": "COMPILED", "pdf": pdf_ref})

    review_run = Path(
        spine.begin(str(runs), "review-001", "independently review the manuscript", "manuscript_review", TS)["run_dir"]
    )
    payload = {
        "schema_version": "manuscript-review-input/v1",
        "authoring_run_id": "authoring-001",
        "authoring_run_dir": str(authoring),
        "contract": {"ref": "inbox/manuscript-authoring/manuscript-contract.json", "sha256": _file_sha(contract)},
        "integration": {"ref": "evidence/ANALYZE/manuscript-integration.artifact.json", "sha256": _file_sha(integration)},
        "manuscript": {"ref": "source/main.tex", "sha256": source_sha},
        "quality_report": {"ref": "evidence/ANALYZE/manuscript-quality-report.artifact.json", "sha256": _file_sha(quality)},
        "build_receipt": {"ref": "evidence/ANALYZE/manuscript-build-receipt.artifact.json", "sha256": _file_sha(build)},
        "pdf": pdf_ref,
    }
    _write_json(review_run / review.INPUT_REL, payload)
    return authoring, review_run


def _stamp(payload: dict, field: str) -> dict:
    stamped = copy.deepcopy(payload)
    stamped[field] = _sha({key: value for key, value in stamped.items() if key != field})
    return stamped


def _schema_bound_source_and_review(tmp_path: Path) -> tuple[Path, Path]:
    """Make a real cross-run authoring evidence set for REPORT lifecycle tests."""
    runs = tmp_path / "runs"
    authoring = Path(
        spine.begin(str(runs), "authoring-001", "author a frozen AI paper", "manuscript_authoring", TS)["run_dir"]
    )
    source_dir = authoring / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    main = source_dir / "main.tex"
    bibliography = source_dir / "refs.bib"
    main.write_text("\\documentclass{article}\\begin{document}Frozen manuscript.\\end{document}\n", encoding="utf-8")
    bibliography.write_text("@article{fixture,title={Fixture}}\n", encoding="utf-8")
    source_tree_sha = _sha({"main.tex": _file_sha(main), "refs.bib": _file_sha(bibliography)})
    pdf = authoring / "build" / "main.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\ntrusted fixture bytes\n")

    contract = valid_manuscript_contract()
    contract["run_id"] = authoring.name
    contract["contract_id"] = f"manuscript-contract/{authoring.name}"
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    integration = valid_integration()
    integration["integration_id"] = f"manuscript-integration/{authoring.name}"
    integration["manuscript_snapshot_sha256"] = contract["manuscript_snapshot_sha256"]
    integration["canonical_file_inventory"] = [
        {"path": "main.tex", "sha256": _file_sha(main), "kind": "MAIN_TEX"},
        {"path": "refs.bib", "sha256": _file_sha(bibliography), "kind": "BIBLIOGRAPHY"},
    ]
    integration["source_tree_sha256"] = source_tree_sha
    integration = _stamp(integration, "integration_hash")
    build = _compiled_build()
    build["run_id"] = authoring.name
    build["manuscript_snapshot_sha256"] = contract["manuscript_snapshot_sha256"]
    build["source_tree_ref"] = "source"
    build["source_tree_sha256"] = source_tree_sha
    build["pdf"] = {"path": "build/main.pdf", "sha256": _file_sha(pdf), "byte_size": pdf.stat().st_size}
    build = _stamp(build, "build_receipt_sha256")
    quality = _compiled_quality()
    quality["run_id"] = authoring.name
    quality["manuscript_sha256"] = source_tree_sha
    quality["build"] = {
        "receipt_ref": "evidence/ANALYZE/manuscript-build-receipt.artifact.json",
        "receipt_sha256": "b" * 64,
        "state": "COMPILED",
        "source_sha256": source_tree_sha,
        "pdf_sha256": _file_sha(pdf),
    }
    quality = _stamp(quality, "quality_report_sha256")
    contract_path = Path(
        write_artifact(
            authoring, "DESIGN", "manuscript-contract.artifact.json", "manuscript_contract", "manuscript-architect", contract, TS
        )
    )
    integration_path = Path(
        write_artifact(
            authoring, "ANALYZE", "manuscript-integration.artifact.json", "manuscript_integration", "manuscript-integrator", integration, TS
        )
    )
    build_path = Path(
        write_artifact(
            authoring, "ANALYZE", "manuscript-build-receipt.artifact.json", "manuscript_build_receipt", "safe-latex-build", build, TS
        )
    )
    quality_path = Path(
        write_artifact(
            authoring, "ANALYZE", "manuscript-quality-report.artifact.json", "manuscript_quality_report", "manuscript-truth-auditor", quality, TS
        )
    )
    for relative in (
        "director-review/manuscript/00-OVERVIEW.md",
        "director-review/manuscript/local-literature-coverage.md",
        "director-review/manuscript/authoring-plan.md",
    ):
        path = authoring / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {Path(relative).stem}\n", encoding="utf-8")
    review_run = Path(
        spine.begin(str(runs), "review-001", "independently review the manuscript", "manuscript_review", TS)["run_dir"]
    )
    _write_json(
        review_run / review.INPUT_REL,
        {
            "schema_version": "manuscript-review-input/v1",
            "authoring_run_id": authoring.name,
            "authoring_run_dir": str(authoring),
            "contract": {"ref": contract_path.relative_to(authoring).as_posix(), "sha256": _file_sha(contract_path)},
            "integration": {"ref": integration_path.relative_to(authoring).as_posix(), "sha256": _file_sha(integration_path)},
            "manuscript": {"ref": "source/main.tex", "sha256": _file_sha(main)},
            "quality_report": {"ref": quality_path.relative_to(authoring).as_posix(), "sha256": _file_sha(quality_path)},
            "build_receipt": {"ref": build_path.relative_to(authoring).as_posix(), "sha256": _file_sha(build_path)},
            "pdf": {"ref": "build/main.pdf", "sha256": _file_sha(pdf)},
        },
    )
    return authoring, review_run


def _finding(capability: str, *, scientific: bool = False, advisory: bool = False) -> dict:
    return {
        "finding_id": f"{capability}-finding",
        "severity": "ADVISORY" if advisory else "BLOCKING",
        "status": "OPEN",
        "dimension": "SCIENTIFIC" if scientific else "CITATION",
        "locus": "source/main.tex:1",
        "description": f"{capability} evidence requires repair.",
        "evidence_refs": ["source/main.tex"],
        "required_fix": "Repair the frozen source and request a new review run.",
    }


def _bundle(run_dir: Path, capability: str, precommit: dict, *, findings: list[dict] | None = None,
            suffix: str = "primary") -> Path:
    auth = precommit["authorization_receipts"][capability]
    frozen = precommit["frozen_inputs"]
    payload = {
        "schema_version": "1.0.0",
        "review_id": f"{capability}-{suffix}",
        "review_run_id": run_dir.name,
        "reviewer_identity": {
            "reviewer_id": f"blind-{capability}-{suffix}",
            "role": review.CAPABILITY_ROLES[capability],
            "independent_from_authoring": True,
        },
        "blind_read_receipt": {
            "scheduler_authorization_ref": auth["ref"],
            "scheduler_authorization_sha256": auth["sha256"],
            "blind_scope_sha256": precommit["blind_scope_sha256"],
            "issued_at": TS,
            "other_reviewer_conclusions_visible": False,
            "generation_artifacts_counted_as_independent_evidence": False,
        },
        "frozen_inputs": dict(frozen),
        "scoped_inputs": [
            {"kind": "CONTRACT", "ref": frozen["contract_ref"], "sha256": frozen["contract_sha256"], "authorization_receipt_sha256": auth["sha256"]},
            {"kind": "MANUSCRIPT", "ref": frozen["manuscript_ref"], "sha256": frozen["manuscript_sha256"], "authorization_receipt_sha256": auth["sha256"]},
            {"kind": "PDF", "ref": frozen["pdf_ref"], "sha256": frozen["pdf_sha256"], "authorization_receipt_sha256": auth["sha256"]},
        ],
        "findings": list(findings or []),
        "disposition": "BLOCK" if any(row["severity"] == "BLOCKING" for row in (findings or [])) else ("NEEDS_REPAIR" if findings else "PASS"),
    }
    payload["verdict_sha256"] = _sha(payload)
    path = run_dir / review.capability_bundle_rel(capability, suffix=suffix)
    _write_json(path, payload)
    return path


def _all_bundles(run_dir: Path, precommit: dict, *, findings_by_capability: dict[str, list[dict]] | None = None) -> None:
    for capability in review.REQUIRED_CAPABILITY_IDS:
        _bundle(run_dir, capability, precommit, findings=(findings_by_capability or {}).get(capability))


def test_review_precommit_freezes_inputs_and_dispatches_exact_blind_capabilities(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)

    assert precommit["review_run_id"] == "review-001"
    assert precommit["authoring_run_id"] == "authoring-001"
    assert set(precommit["authorization_receipts"]) == set(review.REQUIRED_CAPABILITY_IDS)
    assert len({row["sha256"] for row in precommit["authorization_receipts"].values()}) == 6

    panel = review.llm_step(str(review_run), "VERIFY", "review")
    assert panel["group_barriers"] is False
    assert {worker["capability_id"] for worker in panel["workers"]} == set(review.REQUIRED_CAPABILITY_IDS)
    assert len({worker["output"] for worker in panel["workers"]}) == 6
    for worker in panel["workers"]:
        assert worker["input_contract"]["blind"] is True
        assert "authoring-self-audit" in " ".join(worker["input_contract"]["forbidden_inputs"])
        assert "sibling reviewer" in worker["prompt"].lower()


def test_review_reconciles_all_findings_and_renders_advisory_status_only(tmp_path):
    authoring, review_run = _source_and_review(tmp_path)
    original_source = (authoring / "source" / "main.tex").read_bytes()
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(
        review_run,
        precommit,
        findings_by_capability={
            "domain_contribution": [_finding("domain_contribution", scientific=True)],
            "citation": [_finding("citation", advisory=True)],
        },
    )

    paths, result = review.run_dets(str(review_run), "VERIFY", TS)
    status_path = Path(next(path for path in paths if path.endswith(review.ADVISORY_STATUS_ARTIFACT)))
    artifact = json.loads(status_path.read_text(encoding="utf-8"))
    assert validate_artifact(artifact) == []
    assert artifact["artifact_type"] == "report_note"
    assert artifact["payload"]["delivery_status"] == "BLOCK"
    assert result["independence_verified"] is False
    assert result["submission_ready"] is False
    reconciliation = json.loads((review_run / review.RECONCILIATION_REL).read_text(encoding="utf-8"))
    assert len(reconciliation["rows"]) == 2
    assert {row["origin_capability"] for row in reconciliation["rows"]} == {"domain_contribution", "citation"}
    assert all({"origin_receipt_sha256", "disposition", "evidence", "rationale"} <= set(row) for row in reconciliation["rows"])
    assert reconciliation["rebuttal_candidates"]
    assert all(row["applied"] is False for row in reconciliation["rebuttal_candidates"])
    report = (review_run / "director-review" / "manuscript" / "reviewer-report.md").read_text(encoding="utf-8")
    assert "domain_contribution-finding" in report
    assert "citation-finding" in report
    assert (authoring / "source" / "main.tex").read_bytes() == original_source


def test_review_rejects_missing_required_capability_before_join(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    (review_run / review.capability_bundle_rel("citation")).unlink()

    with pytest.raises(GateBlock, match="missing required capability"):
        review.run_dets(str(review_run), "VERIFY", TS)


def test_review_rejects_reused_or_forged_receipts(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    path = review_run / review.capability_bundle_rel("citation")
    payload = json.loads(path.read_text(encoding="utf-8"))
    reused = precommit["authorization_receipts"]["domain_contribution"]
    payload["blind_read_receipt"]["scheduler_authorization_ref"] = reused["ref"]
    payload["blind_read_receipt"]["scheduler_authorization_sha256"] = reused["sha256"]
    for scoped in payload["scoped_inputs"]:
        scoped["authorization_receipt_sha256"] = reused["sha256"]
    payload["verdict_sha256"] = _sha({key: value for key, value in payload.items() if key != "verdict_sha256"})
    _write_json(path, payload)

    with pytest.raises(GateBlock, match="authorization"):
        review.run_dets(str(review_run), "VERIFY", TS)


@pytest.mark.parametrize("mutation", ["protected_leak", "cross_run", "source_tamper"])
def test_review_rejects_leakage_cross_run_and_source_mutation(tmp_path, mutation):
    authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    if mutation == "protected_leak":
        path = review_run / review.capability_bundle_rel("factual")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["scoped_inputs"].append(
            {"kind": "EVIDENCE_SLICE", "ref": "authoring-self-audit/conclusions.json", "sha256": "d" * 64,
             "authorization_receipt_sha256": payload["blind_read_receipt"]["scheduler_authorization_sha256"]}
        )
        payload["verdict_sha256"] = _sha({key: value for key, value in payload.items() if key != "verdict_sha256"})
        _write_json(path, payload)
    elif mutation == "cross_run":
        path = review_run / review.capability_bundle_rel("factual")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["review_run_id"] = "authoring-001"
        payload["verdict_sha256"] = _sha({key: value for key, value in payload.items() if key != "verdict_sha256"})
        _write_json(path, payload)
    else:
        (authoring / "source" / "main.tex").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(GateBlock):
        review.run_dets(str(review_run), "VERIFY", TS)


def test_source_only_review_is_caveated_without_false_pdf_claim(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path, source_only=True)
    precommit = review.prepare_review_precommit(review_run, TS)
    assert precommit["source_only"] is True
    assert precommit["frozen_inputs"]["pdf_ref"] == "audit/no-build-receipt"
    _all_bundles(review_run, precommit)

    _paths, result = review.run_dets(str(review_run), "VERIFY", TS)
    reconciliation = json.loads((review_run / review.RECONCILIATION_REL).read_text(encoding="utf-8"))
    assert result["submission_ready"] is False
    assert result["daily_state"] == "USABLE_WITH_CAVEATS"
    assert reconciliation["source_only"] is True
    assert reconciliation["compiled_pdf_claimed"] is False


def test_false_execution_and_false_compiled_pdf_surface_at_hard_gate(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path, false_execution=True)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    _paths, result = review.run_dets(str(review_run), "VERIFY", TS)
    reconciliation = json.loads((review_run / review.RECONCILIATION_REL).read_text(encoding="utf-8"))
    assert result["daily_state"] == "BLOCK"
    assert any(row["finding_id"].startswith("AUDIT-") for row in reconciliation["rows"])

    _authoring2, review_run2 = _source_and_review(tmp_path / "bad", source_only=False)
    build_path = Path(json.loads((review_run2 / review.INPUT_REL).read_text())["authoring_run_dir"]) / "evidence" / "ANALYZE" / "manuscript-build-receipt.artifact.json"
    _write_json(build_path, {"build_state": "COMPILED", "pdf": None})
    input_path = review_run2 / review.INPUT_REL
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    input_payload["build_receipt"]["sha256"] = _file_sha(build_path)
    input_payload["pdf"] = None
    _write_json(input_path, input_payload)
    with pytest.raises(GateBlock, match="compiled PDF"):
        review.prepare_review_precommit(review_run2, TS)


def test_review_resume_is_idempotent_and_never_mutates_authoring(tmp_path):
    authoring, review_run = _source_and_review(tmp_path)
    source_before = _file_sha(authoring / "source" / "main.tex")
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    first_paths, first = review.run_dets(str(review_run), "VERIFY", TS)
    second_paths, second = review.run_dets(str(review_run), "VERIFY", TS)

    assert first == second
    assert {Path(path).name for path in first_paths} == {Path(path).name for path in second_paths}
    assert _file_sha(authoring / "source" / "main.tex") == source_before


def test_review_rejects_authoring_run_that_is_the_review_run(tmp_path):
    authoring, review_run = _source_and_review(tmp_path)
    input_path = review_run / review.INPUT_REL
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    for key in ("contract", "integration", "manuscript", "quality_report", "build_receipt"):
        source = authoring / payload[key]["ref"]
        target = review_run / payload[key]["ref"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        payload[key]["sha256"] = _file_sha(target)
    assert payload["pdf"] is not None
    pdf_source = authoring / payload["pdf"]["ref"]
    pdf_target = review_run / payload["pdf"]["ref"]
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    pdf_target.write_bytes(pdf_source.read_bytes())
    payload["pdf"]["sha256"] = _file_sha(pdf_target)
    payload["authoring_run_id"] = review_run.name
    payload["authoring_run_dir"] = str(review_run)
    _write_json(input_path, payload)

    with pytest.raises(GateBlock, match="distinct"):
        review.prepare_review_precommit(review_run, TS)


def test_review_rejects_symlinked_authoring_input_before_hashing(tmp_path):
    authoring, review_run = _source_and_review(tmp_path)
    outside = tmp_path / "director-owned-source.tex"
    outside.write_text("outside fixture", encoding="utf-8")
    manuscript = authoring / "source" / "main.tex"
    manuscript.unlink()
    try:
        manuscript.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable on this filesystem: {exc}")
    input_path = review_run / review.INPUT_REL
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["manuscript"]["sha256"] = _file_sha(outside)
    _write_json(input_path, payload)

    with pytest.raises(GateBlock, match="unsafe"):
        review.prepare_review_precommit(review_run, TS)


def test_self_reported_compiled_and_ready_claims_are_caveated_not_trusted(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)

    _paths, result = review.run_dets(str(review_run), "VERIFY", TS)

    assert result["independence_verified"] is False
    assert result["submission_ready"] is False
    assert result["daily_state"] == "USABLE_WITH_CAVEATS"
    report = (review_run / review.REVIEWER_REPORT_REL).read_text(encoding="utf-8")
    assert "independence is not externally verified" in report.lower()
    assert audit_run_output(review_run, "manuscript_review")["status"] == "pass"


def test_secret_in_reviewer_finding_is_blocked_before_director_review_write(tmp_path):
    _authoring, review_run = _source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    sentinel = "sentinel-secret-value-001"
    finding = _finding("domain_contribution")
    finding["description"] = f"api_key={sentinel}"
    _all_bundles(
        review_run,
        precommit,
        findings_by_capability={"domain_contribution": [finding]},
    )

    with pytest.raises(GateBlock, match="secret"):
        review.run_dets(str(review_run), "VERIFY", TS)

    report_path = review_run / review.REVIEWER_REPORT_REL
    assert not report_path.exists() or sentinel not in report_path.read_text(encoding="utf-8")


def test_review_report_writes_schema_valid_advisory_submission_checklist(tmp_path):
    authoring, review_run = _schema_bound_source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    review.run_dets(str(review_run), "VERIFY", TS)

    paths, result = review.run_dets(str(review_run), "REPORT", TS)

    checklist_path = Path(next(path for path in paths if path.endswith(review.SUBMISSION_CHECKLIST_ARTIFACT)))
    artifact = json.loads(checklist_path.read_text(encoding="utf-8"))
    assert validate_artifact(artifact) == []
    checklist = artifact["payload"]
    assert result["submission_ready"] is False
    assert checklist["submission_ready"] is False
    assert checklist["submission_authorization"] is False
    assert checklist["build_truth"]["build_state"] == "COMPILED"
    assert checklist["checks"]["source_build_pdf_truth"]["state"] == "UNVERIFIED"
    assert any(
        finding["finding_id"] == "external-scheduler-independence-unverified"
        and finding["submission_effect"] == "BLOCK"
        for finding in checklist["findings"]
    )
    assert any(
        blocker["blocker_id"] == "external-scheduler-independence"
        for blocker in checklist["submission_blockers"]
    )
    assert checklist["outstanding_director_decisions"][0]["authority"] == "DIRECTOR_HUMAN"
    assert checklist["evidence_links"]["manuscript"]["sha256"] == _file_sha(authoring / "source" / "main.tex")
    assert checklist["evidence_links"]["review"]["sha256"] == _file_sha(
        review_run / review.REVIEWER_REPORT_REL
    )
    assert checklist["submission_checklist_sha256"] == _sha(
        {key: value for key, value in checklist.items() if key != "submission_checklist_sha256"}
    )


def test_review_submission_checklist_preserves_blocking_capability_finding(tmp_path):
    _authoring, review_run = _schema_bound_source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(
        review_run,
        precommit,
        findings_by_capability={"domain_contribution": [_finding("domain_contribution", scientific=True)]},
    )
    review.run_dets(str(review_run), "VERIFY", TS)

    _paths, result = review.run_dets(str(review_run), "REPORT", TS)
    checklist = json.loads(
        (review_run / "evidence" / "REPORT" / review.SUBMISSION_CHECKLIST_ARTIFACT).read_text(encoding="utf-8")
    )["payload"]

    assert result["daily_state"] == "BLOCK"
    assert checklist["daily_state"] == "BLOCK"
    assert checklist["submission_ready"] is False
    assert checklist["capability_coverage"]["domain_contribution"]["state"] == "BLOCK"
    assert any(finding["finding_id"] == "domain_contribution-finding" for finding in checklist["findings"])
    assert any(
        blocker["finding_id"] == "domain_contribution-finding"
        for blocker in checklist["submission_blockers"]
    )


@pytest.mark.parametrize("mutation", ("missing_overview", "tampered_quality"))
def test_submission_checklist_fails_closed_on_missing_or_tampered_evidence(tmp_path, mutation):
    authoring, review_run = _schema_bound_source_and_review(tmp_path)
    precommit = review.prepare_review_precommit(review_run, TS)
    _all_bundles(review_run, precommit)
    review.run_dets(str(review_run), "VERIFY", TS)
    if mutation == "missing_overview":
        (authoring / "director-review/manuscript/00-OVERVIEW.md").unlink()
        match = "authoring overview"
    else:
        quality = authoring / "evidence/ANALYZE/manuscript-quality-report.artifact.json"
        quality.write_text("{}", encoding="utf-8")
        match = "quality_report hash"

    with pytest.raises(GateBlock, match=match):
        review.run_dets(str(review_run), "REPORT", TS)
