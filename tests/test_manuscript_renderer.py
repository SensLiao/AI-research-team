"""TDD contract for the human-first manuscript delivery renderer."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.tests.test_manuscript_predraft_schemas import (
    valid_manuscript_contract,
)
from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_renderer import (
    REQUIRED_REPORT_FILES,
    ManuscriptRenderError,
    write_manuscript_report_set,
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal(payload: dict, field: str) -> dict:
    payload[field] = _hash({key: value for key, value in payload.items() if key != field})
    return payload


def _coverage(snapshot_sha: str) -> dict:
    axes = {}
    for axis in (
        "related_comparison",
        "technical_method",
        "implementation_detail",
        "dataset",
        "metric_evaluation",
        "industry_prior_art",
    ):
        axes[axis] = {
            "criterion": f"Local evidence covers {axis.replace('_', ' ')}.",
            "status": "SUFFICIENT",
            "local_source_refs": [f"evidence/local-{axis}"],
            "rationale": "A bounded local reference was inspected before drafting.",
        }
    return {
        "contract_version": "1.0",
        "coverage_id": "coverage/renderer-fixture",
        "manuscript_snapshot_sha256": snapshot_sha,
        "assessed_at": "2026-07-22T00:00:00Z",
        "local_corpus_refs": [
            {
                "ref": "vault:renderer-fixture#evidence",
                "sha256": "a" * 64,
                "source_kind": "PAPER",
            }
        ],
        "axes": axes,
    }


def _source_tree(run_root: Path) -> tuple[list[dict], str]:
    source = run_root / "source"
    (source / "sections").mkdir(parents=True)
    files = {
        "main.tex": (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\input{sections/introduction}\n"
            "\\bibliography{refs}\n"
            "\\end{document}\n"
        ).encode("utf-8"),
        "refs.bib": b"@article{LocalPaper2026,title={Local Evidence},year={2026}}\n",
        "sections/introduction.tex": b"\\section{Introduction}\\label{sec:introduction}\n",
    }
    kinds = {
        "main.tex": "MAIN_TEX",
        "refs.bib": "BIBLIOGRAPHY",
        "sections/introduction.tex": "SECTION",
    }
    inventory = []
    for relative, data in sorted(files.items()):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        inventory.append({"path": relative, "sha256": _file_hash(path), "kind": kinds[relative]})
    return inventory, _hash(inventory)


def _integration(snapshot_sha: str, inventory: list[dict], source_sha: str) -> dict:
    payload = {
        "contract_version": "1.0",
        "integration_id": "integration/renderer-fixture",
        "integrator_role": "manuscript-integrator",
        "manuscript_snapshot_sha256": snapshot_sha,
        "section_bundle_refs": [
            {
                "section_id": "introduction",
                "bundle_ref": "inbox/WRITE.introduction.bundle.json",
                "bundle_sha256": "b" * 64,
                "content_hash": "c" * 64,
            }
        ],
        "canonical_file_inventory": inventory,
        "source_tree_sha256": source_sha,
        "reconciliation_findings": [],
        "unresolved_interfaces": [],
    }
    return _seal(payload, "integration_hash")


def _toolchain_missing_build(run_id: str, snapshot_sha: str, source_sha: str) -> dict:
    payload = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "manuscript_snapshot_sha256": snapshot_sha,
        "source_tree_ref": "source",
        "source_tree_sha256": source_sha,
        "requires_pdf": True,
        "build_state": "TOOLCHAIN_MISSING",
        "failure": {
            "kind": "TOOLCHAIN_MISSING",
            "code": "LATEXMK_NOT_FOUND",
            "safe_message": "The bounded LaTeX toolchain is unavailable.",
            "observed_at": "2026-07-22T00:01:00Z",
        },
    }
    return _seal(payload, "build_receipt_sha256")


def _compiled_build(run_root: Path, run_id: str, snapshot_sha: str, source_sha: str) -> dict:
    build_dir = run_root / "build"
    build_dir.mkdir()
    (build_dir / "main.pdf").write_bytes(b"%PDF-1.4 renderer fixture\n")
    (build_dir / "main.log").write_text("fixture log\n", encoding="utf-8")
    (build_dir / "main.fls").write_text("INPUT main.tex\n", encoding="utf-8")
    payload = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "manuscript_snapshot_sha256": snapshot_sha,
        "source_tree_ref": "source",
        "source_tree_sha256": source_sha,
        "requires_pdf": True,
        "build_state": "COMPILED",
        "process_receipt": {
            "executable": "latexmk",
            "executable_version": "fixture 1.0",
            "argv": [
                "latexmk",
                "-norc",
                "-pdf",
                "-halt-on-error",
                "-recorder",
                "main.tex",
            ],
            "operating_system": "fixture",
            "tex_engine": "pdflatex",
            "return_code": 0,
            "duration_ms": 1,
            "timed_out": False,
            "shell": False,
            "shell_escape": False,
            "started_at": "2026-07-22T00:01:00Z",
            "finished_at": "2026-07-22T00:01:01Z",
            "receipt_sha256": "d" * 64,
        },
        "log_ref": "build/main.log",
        "log_sha256": _file_hash(build_dir / "main.log"),
        "recorder_ref": "build/main.fls",
        "recorder_sha256": _file_hash(build_dir / "main.fls"),
        "pdf": {
            "path": "build/main.pdf",
            "sha256": _file_hash(build_dir / "main.pdf"),
            "byte_size": (build_dir / "main.pdf").stat().st_size,
        },
    }
    return _seal(payload, "build_receipt_sha256")


def _quality(run_id: str, source_sha: str, build: dict, *, block: bool = False) -> dict:
    findings = [
        {
            "finding_id": "finding-build",
            "finding_class": "HARD",
            "scope": "SUBMISSION",
            "status": "OPEN",
            "daily_effect": "NONE",
            "submission_effect": "BLOCK",
            "code": "BUILD_REQUIRED_UNAVAILABLE",
            "message": "The venue requires a compiled PDF, but the toolchain is unavailable.",
            "evidence_refs": ["build/build-receipt.json"],
            "repair": "Build with a verified bounded LaTeX toolchain.",
        },
        {
            "finding_id": "finding-prose",
            "finding_class": "ADVISORY",
            "scope": "DAILY_USE",
            "status": "OPEN",
            "daily_effect": "CAVEAT",
            "submission_effect": "NONE",
            "code": "PROSE_POLISH",
            "message": "A non-blocking prose polish remains.",
            "evidence_refs": ["evidence/VERIFY/prose-audit.json"],
            "repair": "Apply the advisory prose repair.",
        },
    ]
    daily_state = "USABLE_WITH_CAVEATS"
    rationale = "The canonical source is readable while an advisory caveat remains."
    if block:
        findings.append(
            {
                "finding_id": "finding-secret",
                "finding_class": "HARD",
                "scope": "BOTH",
                "status": "OPEN",
                "daily_effect": "BLOCK",
                "submission_effect": "BLOCK",
                "code": "SECRET_LEAKAGE",
                "message": "A hard truth or permission finding must remain visible.",
                "evidence_refs": ["evidence/VERIFY/secret-audit.json"],
                "repair": "Remove the unsafe material and rerun the audit.",
            }
        )
        daily_state = "BLOCK"
        rationale = "A hard daily-use finding blocks delivery until repaired."
    payload = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "manuscript_sha256": "e" * 64,
        "requires_pdf": True,
        "build": {
            "receipt_ref": "build/build-receipt.json",
            "receipt_sha256": build["build_receipt_sha256"],
            "state": build["build_state"],
            "source_sha256": source_sha,
            "pdf_sha256": (build.get("pdf") or {}).get("sha256"),
        },
        "findings": findings,
        "daily_state": daily_state,
        "daily_rationale": rationale,
        "submission_ready": False,
        "submission_blockers": [
            {
                "blocker_id": "blocker-build",
                "code": "BUILD_REQUIRED_UNAVAILABLE",
                "source_ref": "finding-build",
                "rationale": "The frozen venue policy requires a real compiled PDF.",
            }
        ],
    }
    return _seal(payload, "quality_report_sha256")


def _review(contract: dict, quality: dict, build: dict) -> dict:
    receipt_sha = "f" * 64
    payload = {
        "schema_version": "1.0.0",
        "review_id": "review/scientific-fixture",
        "review_run_id": "review-run-002",
        "reviewer_identity": {
            "reviewer_id": "reviewer-scientific-01",
            "role": "SCIENTIFIC",
            "independent_from_authoring": True,
        },
        "blind_read_receipt": {
            "scheduler_authorization_ref": "receipts/blind-review.json",
            "scheduler_authorization_sha256": receipt_sha,
            "blind_scope_sha256": "1" * 64,
            "issued_at": "2026-07-22T00:02:00Z",
            "other_reviewer_conclusions_visible": False,
            "generation_artifacts_counted_as_independent_evidence": False,
        },
        "frozen_inputs": {
            "contract_ref": "contracts/manuscript-contract.json",
            "contract_sha256": contract["manuscript_snapshot_sha256"],
            "manuscript_ref": "source/main.tex",
            "manuscript_sha256": quality["manuscript_sha256"],
            "pdf_ref": "build/main.pdf",
            "pdf_sha256": build["pdf"]["sha256"],
        },
        "scoped_inputs": [
            {
                "kind": kind,
                "ref": ref,
                "sha256": sha,
                "authorization_receipt_sha256": receipt_sha,
            }
            for kind, ref, sha in (
                ("CONTRACT", "contracts/manuscript-contract.json", contract["manuscript_snapshot_sha256"]),
                ("MANUSCRIPT", "source/main.tex", quality["manuscript_sha256"]),
                ("PDF", "build/main.pdf", build["pdf"]["sha256"]),
            )
        ],
        "findings": [],
        "disposition": "PASS",
    }
    return _seal(payload, "verdict_sha256")


def _fixture(tmp_path: Path, *, compiled: bool = False, block: bool = False) -> dict:
    run_root = tmp_path / "authoring-run-001"
    run_root.mkdir()
    contract = valid_manuscript_contract()
    contract["run_id"] = run_root.name
    contract["contract_id"] = f"manuscript-contract/{run_root.name}"
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    inventory, source_sha = _source_tree(run_root)
    integration = _integration(contract["manuscript_snapshot_sha256"], inventory, source_sha)
    build = (
        _compiled_build(run_root, run_root.name, contract["manuscript_snapshot_sha256"], source_sha)
        if compiled
        else _toolchain_missing_build(run_root.name, contract["manuscript_snapshot_sha256"], source_sha)
    )
    (run_root / "build").mkdir(exist_ok=True)
    (run_root / "build" / "build-receipt.json").write_bytes(_canonical_bytes(build))
    quality = _quality(run_root.name, source_sha, build, block=block)
    return {
        "run_root": run_root,
        "contract": contract,
        "coverage": _coverage(contract["manuscript_snapshot_sha256"]),
        "integration": integration,
        "build": build,
        "quality": quality,
    }


def _render(fixture: dict, **kwargs) -> dict[str, Path]:
    return write_manuscript_report_set(
        fixture["run_root"],
        manuscript_contract=fixture["contract"],
        literature_coverage=fixture["coverage"],
        integration=fixture["integration"],
        quality_report=fixture["quality"],
        build_receipt=fixture["build"],
        **kwargs,
    )


def test_report_set_is_complete_and_honest_without_a_local_toolchain(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    outputs = _render(fixture)

    report_dir = fixture["run_root"] / "director-review" / "manuscript"
    assert set(REQUIRED_REPORT_FILES).issubset({path.name for path in report_dir.iterdir()})
    assert all(path.is_file() for path in outputs.values())
    overview = (report_dir / "00-OVERVIEW.md").read_text(encoding="utf-8")
    assert "`USABLE_WITH_CAVEATS`" in overview
    assert "submission_ready: `false`" in overview
    assert "`TOOLCHAIN_MISSING`" in overview
    assert "No compiled PDF is available" in overview
    assert "BUILD_REQUIRED_UNAVAILABLE" in overview
    assert "PROSE_POLISH" in overview
    assert "../../source/main.tex" in overview
    assert str(fixture["run_root"]) not in overview
    assert "## Independent Review" in (report_dir / "reviewer-report.md").read_text(encoding="utf-8")
    assert "No verified independent manuscript review was supplied." in (
        report_dir / "reviewer-report.md"
    ).read_text(encoding="utf-8")
    assert "related comparison" in (report_dir / "local-literature-coverage.md").read_text(
        encoding="utf-8"
    )


def test_projection_is_byte_equivalent_and_rerender_is_deterministic(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    outputs = _render(fixture)
    before = {path: path.read_bytes() for path in outputs.values()}
    rerendered = _render(fixture)

    assert {path: path.read_bytes() for path in rerendered.values()} == before
    manifest = json.loads(outputs["projection_manifest"].read_text(encoding="utf-8"))
    assert manifest["canonical_source_tree_sha256"] == fixture["integration"]["source_tree_sha256"]
    assert manifest["canonical_mutable_state"] is False
    for row in manifest["files"]:
        source = fixture["run_root"] / row["source_ref"]
        projection = fixture["run_root"] / row["projection_ref"]
        assert _file_hash(source) == row["sha256"] == _file_hash(projection)
        assert source.read_bytes() == projection.read_bytes()


def test_hard_findings_remain_visible_and_daily_block_is_never_downgraded(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, block=True)

    _render(fixture)

    report = (fixture["run_root"] / "director-review" / "manuscript" / "quality-report.md").read_text(
        encoding="utf-8"
    )
    overview = (fixture["run_root"] / "director-review" / "manuscript" / "00-OVERVIEW.md").read_text(
        encoding="utf-8"
    )
    assert "daily_state: `BLOCK`" in overview
    assert "SECRET_LEAKAGE" in overview
    assert "SECRET_LEAKAGE" in report
    assert "Remove the unsafe material and rerun the audit." in report


def test_internal_authoring_audit_never_masquerades_as_independent_review(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    _render(fixture)

    report = (fixture["run_root"] / "director-review" / "manuscript" / "reviewer-report.md").read_text(
        encoding="utf-8"
    )
    assert "## Internal Authoring Audit (Not Independent Review)" in report
    assert fixture["quality"]["quality_report_sha256"] in report
    assert "No verified independent manuscript review was supplied." in report
    assert "Independent review disposition: `PASS`" not in report


def test_distinct_hash_verified_independent_review_is_rendered(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, compiled=True)
    review = _review(fixture["contract"], fixture["quality"], fixture["build"])

    _render(
        fixture,
        independent_review=review,
        independent_review_run_id=review["review_run_id"],
        verified_review_verdict_sha256=review["verdict_sha256"],
        verified_review_receipt_sha256=review["blind_read_receipt"]["scheduler_authorization_sha256"],
    )

    report = (fixture["run_root"] / "director-review" / "manuscript" / "reviewer-report.md").read_text(
        encoding="utf-8"
    )
    assert f"Independent review run: `{review['review_run_id']}`" in report
    assert f"Verdict hash: `{review['verdict_sha256']}`" in report
    assert f"Receipt hash: `{review['blind_read_receipt']['scheduler_authorization_sha256']}`" in report
    assert "Independent review disposition: `PASS`" in report


def test_same_run_or_unverified_review_cannot_be_rendered_as_independent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, compiled=True)
    review = _review(fixture["contract"], fixture["quality"], fixture["build"])
    review["review_run_id"] = fixture["run_root"].name
    review = _seal(review, "verdict_sha256")

    with pytest.raises(ManuscriptRenderError, match="INDEPENDENT_REVIEW_RUN"):
        _render(
            fixture,
            independent_review=review,
            independent_review_run_id=review["review_run_id"],
            verified_review_verdict_sha256=review["verdict_sha256"],
            verified_review_receipt_sha256=review["blind_read_receipt"]["scheduler_authorization_sha256"],
        )


def test_secret_material_is_redacted_from_director_facing_markdown(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    secret = "fixture-secret-do-not-persist"
    fixture["quality"] = copy.deepcopy(fixture["quality"])
    fixture["quality"]["findings"][1]["message"] = f"Advisory text contained {secret}."
    fixture["quality"] = _seal(fixture["quality"], "quality_report_sha256")

    _render(fixture, secret_sentinels={"fixture": secret})

    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (fixture["run_root"] / "director-review" / "manuscript").glob("*.md")
    )
    assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_binary_source_asset_with_secret_is_not_projected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    secret = "binary-asset-secret-001"
    asset = fixture["run_root"] / "source" / "figures" / "plot.bin"
    asset.parent.mkdir()
    asset.write_bytes(b"\x89BIN\x00" + secret.encode("utf-8"))
    inventory = sorted(
        [
            *fixture["integration"]["canonical_file_inventory"],
            {"path": "figures/plot.bin", "sha256": _file_hash(asset), "kind": "FIGURE"},
        ],
        key=lambda row: row["path"],
    )
    source_sha = _hash(inventory)
    fixture["integration"] = _seal(
        {
            **fixture["integration"],
            "canonical_file_inventory": inventory,
            "source_tree_sha256": source_sha,
        },
        "integration_hash",
    )
    fixture["build"] = _seal(
        {**fixture["build"], "source_tree_sha256": source_sha},
        "build_receipt_sha256",
    )
    receipt_path = fixture["run_root"] / "build" / "build-receipt.json"
    receipt_path.write_bytes(_canonical_bytes(fixture["build"]))
    quality = copy.deepcopy(fixture["quality"])
    quality["build"]["source_sha256"] = source_sha
    quality["build"]["receipt_sha256"] = fixture["build"]["build_receipt_sha256"]
    fixture["quality"] = _seal(quality, "quality_report_sha256")

    with pytest.raises(ManuscriptRenderError, match="SECRET_LEAKAGE"):
        _render(fixture, secret_sentinels={"binary_asset": secret})

    assert not (fixture["run_root"] / "director-review" / "manuscript").exists()


def test_mutated_canonical_source_fails_hash_verified_projection(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture["run_root"] / "source" / "main.tex").write_text("mutated", encoding="utf-8")

    with pytest.raises(ManuscriptRenderError, match="CANONICAL_HASH_MISMATCH"):
        _render(fixture)
