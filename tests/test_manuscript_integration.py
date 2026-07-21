"""TDD contract for deterministic, single-writer manuscript integration."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import research_agent_teams.tools.manuscript_integrator as integrator_module
from research_agent_teams.tests.test_manuscript_predraft_schemas import (
    valid_manuscript_contract,
)
from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_integrator import (
    ManuscriptIntegrationError,
    integrate_manuscript,
    materialize_source_tree,
    validate_section_bundle,
)
from research_agent_teams.tools.validate_artifact import validate_payload


STAGE = "WRITE"
RECEIPT_REF = "inbox/panel-scheduler/WRITE.json"
EVIDENCE_REF = "evidence/local-paper-001"
RESULT_REF = "results/frozen-result.json"
BIBLIOGRAPHY = (
    "@article{LocalPaper2026,\n"
    "  title = {A Frozen Local Source},\n"
    "  author = {Fixture, Research},\n"
    "  year = {2026}\n"
    "}\n"
)
SECTIONS = (
    {
        "section_id": "introduction",
        "worker_role": "manuscript-introduction-author",
        "dependency_slice_id": "slice-introduction",
    },
    {
        "section_id": "methods",
        "worker_role": "manuscript-methods-author",
        "dependency_slice_id": "slice-methods",
    },
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stamp(value: dict, field: str) -> dict:
    value[field] = _canonical_hash({key: item for key, item in value.items() if key != field})
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _contract(run_root: Path) -> dict:
    result_path = run_root / RESULT_REF
    _write_json(result_path, {"fixture_only": True, "metrics": {"score": 0.8125}})
    result_sha = _file_hash(result_path)
    receipt_path = run_root / "receipts/result-001"
    _write_json(receipt_path, {"fixture": True, "result_sha256": result_sha})

    contract = valid_manuscript_contract()
    contract["run_id"] = run_root.name
    contract["outline"] = [
        {
            "section_id": row["section_id"],
            "title": row["section_id"].title(),
            "purpose": f"Provide the frozen {row['section_id']} account.",
            "required": True,
            "depends_on": [] if index == 0 else [SECTIONS[index - 1]["section_id"]],
        }
        for index, row in enumerate(SECTIONS)
    ]
    contract["claim_ledger"] = [
        {
            "claim_id": "CLM-INTRO",
            "text": "The contribution is evidence-bound.",
            "importance": "LOAD_BEARING",
            "evidence_refs": [EVIDENCE_REF],
            "result_refs": [],
        },
        {
            "claim_id": "CLM-METHOD",
            "text": "The method consumes declared inputs.",
            "importance": "SUPPORTING",
            "evidence_refs": [EVIDENCE_REF],
            "result_refs": [],
        },
    ]
    contract["result_refs"] = [
        {
            "ref": RESULT_REF,
            "sha256": result_sha,
            "status": "FROZEN",
            "receipt_ref": "receipts/result-001",
            "receipt_sha256": _file_hash(receipt_path),
        }
    ]
    contract["bibliography"]["entries"] = [
        {
            "citation_key": "LocalPaper2026",
            "source_ref": EVIDENCE_REF,
            "source_sha256": "c" * 64,
            "identity_status": "VERIFIED",
        }
    ]
    contract["asset_plan"] = []
    contract["dependency_slices"] = []
    for row in SECTIONS:
        dependency_slice = {
            "slice_id": row["dependency_slice_id"],
            "worker_role": row["worker_role"],
            "input_refs": [
                {
                    "ref": EVIDENCE_REF,
                    "sha256": "c" * 64,
                    "slice_kind": "CLAIM_EVIDENCE",
                }
            ],
        }
        _stamp(dependency_slice, "slice_sha256")
        contract["dependency_slices"].append(dependency_slice)
    contract["source_hashes"] = [
        {"ref": EVIDENCE_REF, "sha256": "c" * 64, "kind": "EVIDENCE"},
        {"ref": RESULT_REF, "sha256": result_sha, "kind": "RESULT"},
    ]
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    assert validate_payload("manuscript_contract", contract) == []
    return contract


def _authorization_row(role: str, output_ref: str) -> dict:
    return {
        "worker_id": f"0:{role}:{output_ref}",
        "agent": role,
        "source_label": role,
        "output": output_ref,
        "logical_output": output_ref,
        "cycle": 0,
        "wave": 1,
        "authorized_at": "2026-07-21T00:00:00Z",
        "authorization_kind": "initial",
    }


def _bundle(contract: dict, row: dict, authorization_sha: str) -> dict:
    section_id = row["section_id"]
    claim_id = "CLM-INTRO" if section_id == "introduction" else "CLM-METHOD"
    citation = "Supported by frozen evidence \\cite{LocalPaper2026}."
    reference = "" if section_id == "introduction" else " See \\ref{sec:introduction}."
    value = {
        "contract_version": "1.0",
        "bundle_id": f"section-bundle/{section_id}",
        "worker_role": row["worker_role"],
        "section_id": section_id,
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "authorization_receipt": {
            "ref": RECEIPT_REF,
            "sha256": authorization_sha,
            "worker_role": row["worker_role"],
        },
        "input_refs": [
            {
                "ref": "contracts/manuscript-contract.json",
                "sha256": contract["manuscript_snapshot_sha256"],
                "slice_kind": "GLOBAL_CONTRACT",
            },
            {
                "ref": EVIDENCE_REF,
                "sha256": "c" * 64,
                "slice_kind": "CLAIM_EVIDENCE",
            },
        ],
        "claim_support_refs": [
            {"claim_id": claim_id, "evidence_refs": [EVIDENCE_REF], "result_refs": []}
        ],
        "draft_latex": (
            f"\\section{{{section_id.title()}}}\n"
            f"\\label{{sec:{section_id}}}\n{citation}{reference}\n"
        ),
        "citation_keys": ["LocalPaper2026"],
        "labels": [f"sec:{section_id}"],
        "cross_references": [] if section_id == "introduction" else ["sec:introduction"],
        "asset_refs": [],
        "notation_uses": [{"symbol": "H", "meaning_ref": "glossary/H"}],
        "uncertainties": [],
        "omissions": [],
        "requested_supplements": [],
    }
    return _stamp(value, "content_hash")


def _setup_run(tmp_path: Path) -> tuple[Path, dict, list[str]]:
    run_root = tmp_path / "run-001"
    run_root.mkdir(parents=True)
    contract = _contract(run_root)
    refs = [f"inbox/{STAGE}.{row['section_id']}.bundle.json" for row in SECTIONS]
    rows = [_authorization_row(row["worker_role"], ref) for row, ref in zip(SECTIONS, refs)]
    receipt = {
        "contract_version": "panel-dispatch/v1",
        "stage": STAGE,
        "authorizations": rows,
        "waves": [
            {
                "wave": 1,
                "cycle": 0,
                "authorized_at": "2026-07-21T00:00:00Z",
                "worker_ids": [row["worker_id"] for row in rows],
                "agents": [row["agent"] for row in rows],
            }
        ],
    }
    _write_json(run_root / RECEIPT_REF, receipt)
    for section, ref, authorization in zip(SECTIONS, refs, rows):
        _write_json(run_root / ref, _bundle(contract, section, _canonical_hash(authorization)))
    return run_root, contract, refs


def _rewrite_bundle(run_root: Path, ref: str, change) -> dict:
    path = run_root / ref
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    _stamp(payload, "content_hash")
    _write_json(path, payload)
    return payload


def _integrate(run_root: Path, contract: dict, refs: list[str], **kwargs) -> dict:
    return integrate_manuscript(
        run_root=run_root,
        manuscript_contract=contract,
        section_bundle_refs=refs,
        required_sections=SECTIONS,
        bibliography_text=kwargs.pop("bibliography_text", BIBLIOGRAPHY),
        stage=STAGE,
        **kwargs,
    )


def _assert_code(expected: str, action) -> ManuscriptIntegrationError:
    with pytest.raises(ManuscriptIntegrationError) as exc:
        action()
    assert exc.value.code == expected
    assert exc.value.findings and exc.value.findings[0]["code"] == expected
    return exc.value


def test_deterministic_integration_materializes_one_native_source_tree(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)

    first = _integrate(run_root, contract, list(reversed(refs)))
    second = _integrate(run_root, contract, refs)

    assert _canonical_bytes(first["integration"]) == _canonical_bytes(second["integration"])
    assert first["files"] == second["files"]
    assert [row["section_id"] for row in first["integration"]["section_bundle_refs"]] == [
        "introduction",
        "methods",
    ]
    assert validate_payload("manuscript_integration", first["integration"]) == []
    assert validate_payload("manuscript_asset_manifest", first["asset_manifest"]) == []

    source = materialize_source_tree(first, run_root=run_root)
    expected_files = {
        "main.tex",
        "refs.bib",
        "sections/introduction.tex",
        "sections/methods.tex",
        "manifests/manuscript-integration.json",
        "manifests/asset-manifest.json",
        "build/integration-metadata.json",
    }
    assert {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()} == expected_files
    for directory in ("sections", "figures", "tables", "manifests", "build"):
        assert (source / directory).is_dir()
    assert (source / "main.tex").read_text(encoding="utf-8").index("introduction") < (
        source / "main.tex"
    ).read_text(encoding="utf-8").index("methods")
    for item in first["integration"]["canonical_file_inventory"]:
        assert _file_hash(source / item["path"]) == item["sha256"]

    _assert_code("SOURCE_ALREADY_EXISTS", lambda: materialize_source_tree(first, run_root=run_root))


@pytest.mark.parametrize(
    ("variant", "expected"),
    [("missing", "MISSING_REQUIRED_SECTION"), ("duplicate", "DUPLICATE_REQUIRED_SECTION")],
)
def test_required_sections_are_exactly_one_and_never_synthesized(tmp_path, variant, expected):
    run_root, contract, refs = _setup_run(tmp_path)
    selected = refs[:1] if variant == "missing" else [refs[0], refs[0], refs[1]]
    repair_calls = []

    _assert_code(
        expected,
        lambda: _integrate(
            run_root,
            contract,
            selected,
            format_repair=lambda *args: repair_calls.append(args),
        ),
    )
    assert repair_calls == []
    assert not (run_root / "source").exists()


def test_bundle_contract_authorization_and_declared_slice_fail_closed(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)

    stale_contract = copy.deepcopy(contract)
    stale_contract["north_star"] = "Mutable context must not be consumed."
    _assert_code(
        "CONTRACT_HASH_MISMATCH",
        lambda: _integrate(run_root, stale_contract, refs),
    )

    _rewrite_bundle(
        run_root,
        refs[0],
        lambda payload: payload["input_refs"].append(
            {"ref": "evidence/undeclared", "sha256": "f" * 64, "slice_kind": "CLAIM_EVIDENCE"}
        ),
    )
    _assert_code("UNAUTHORIZED_DEPENDENCY", lambda: _integrate(run_root, contract, refs))

    run_root, contract, refs = _setup_run(tmp_path / "receipt-case")
    receipt_path = run_root / RECEIPT_REF
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["authorizations"][0]["agent"] = "different-author"
    _write_json(receipt_path, receipt)
    _assert_code("AUTHORIZATION_MISMATCH", lambda: _integrate(run_root, contract, refs))


def test_validate_section_bundle_allows_only_two_format_repairs(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    path = run_root / refs[0]
    valid_text = path.read_text(encoding="utf-8")
    malformed = valid_text.replace(',"bundle_id"', '"bundle_id"', 1)
    path.write_text(malformed, encoding="utf-8")
    calls = []

    def repaired(raw: str, _errors: list[str], attempt: int) -> str:
        calls.append(attempt)
        return raw if attempt == 1 else valid_text

    validated = validate_section_bundle(
        refs[0],
        run_root=run_root,
        manuscript_contract=contract,
        required_section=SECTIONS[0],
        stage=STAGE,
        format_repair=repaired,
    )
    assert validated["repair_attempts"] == 2
    assert calls == [1, 2]
    assert path.read_text(encoding="utf-8") == malformed

    calls.clear()
    _assert_code(
        "REPAIR_LIMIT_EXCEEDED",
        lambda: validate_section_bundle(
            refs[0],
            run_root=run_root,
            manuscript_contract=contract,
            required_section=SECTIONS[0],
            stage=STAGE,
            format_repair=lambda raw, _errors, attempt: calls.append(attempt) or raw,
        ),
    )
    assert calls == [1, 2]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda payload: payload["labels"].append("sec:methods"),
            "DUPLICATE_LABEL",
        ),
        (
            lambda payload: payload["cross_references"].append("sec:missing"),
            "UNRESOLVED_REFERENCE",
        ),
        (
            lambda payload: payload["citation_keys"].append("Invented2026"),
            "UNKNOWN_CITATION",
        ),
        (
            lambda payload: payload["claim_support_refs"].append(
                {"claim_id": "CLM-METHOD", "evidence_refs": [EVIDENCE_REF], "result_refs": []}
            ),
            "DUPLICATE_CLAIM",
        ),
    ],
)
def test_cross_bundle_coherence_failures_are_typed_before_publish(tmp_path, mutation, expected):
    run_root, contract, refs = _setup_run(tmp_path)
    _rewrite_bundle(run_root, refs[0], mutation)

    _assert_code(expected, lambda: _integrate(run_root, contract, refs))
    assert not (run_root / "source").exists()


def test_frozen_result_hash_and_declared_tex_metadata_are_verified(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    _rewrite_bundle(
        run_root,
        refs[1],
        lambda payload: payload["claim_support_refs"][0]["result_refs"].append(RESULT_REF),
    )
    (run_root / RESULT_REF).write_text('{"metrics":{"score":0.99}}', encoding="utf-8")

    _assert_code("STALE_RESULT", lambda: _integrate(run_root, contract, refs))

    run_root, contract, refs = _setup_run(tmp_path / "metadata-case")
    _rewrite_bundle(
        run_root,
        refs[0],
        lambda payload: payload.update(citation_keys=[]),
    )
    _assert_code("CITATION_METADATA_MISMATCH", lambda: _integrate(run_root, contract, refs))


@pytest.mark.parametrize(
    ("latex", "kwargs", "expected"),
    [
        ("\\write18{touch escaped}", {}, "UNSAFE_TEX"),
        ("The sentinel is TOPSECRET.", {"secret_sentinels": {"fixture": "TOPSECRET"}}, "SECRET_LEAKAGE"),
    ],
)
def test_unsafe_tex_and_secret_text_never_reach_source(tmp_path, latex, kwargs, expected):
    run_root, contract, refs = _setup_run(tmp_path)

    def mutate(payload: dict) -> None:
        payload["draft_latex"] += latex

    _rewrite_bundle(run_root, refs[0], mutate)
    _assert_code(expected, lambda: _integrate(run_root, contract, refs, **kwargs))
    assert not (run_root / "source").exists()


def _external_asset(run_root: Path, contract: dict, director_file: Path) -> dict:
    source_sha = _file_hash(director_file)
    asset = {
        "asset_id": "asset-director-figure",
        "label": "fig:director",
        "asset_type": "FIGURE",
        "source_inputs": [
            {"ref": director_file.name, "sha256": source_sha, "kind": "DIRECTOR_ASSET", "immutable": True}
        ],
        "output": {
            "path": "figures/director.svg",
            "sha256": source_sha,
            "byte_size": len(director_file.read_bytes()),
            "owner_run_id": run_root.name,
            "run_owned": True,
            "overwrite_policy": "CREATE_NEW",
            "preexisting_target": False,
        },
        "caption": {"text": "Director-provided architecture.", "owner_role": "director"},
        "claim_refs": ["CLM-INTRO"],
        "result_refs": [RESULT_REF],
        "numeric_source_cells": [
            {"result_ref": RESULT_REF, "cell_ref": "metrics.score", "sha256": contract["result_refs"][0]["sha256"]}
        ],
        "provenance": {
            "kind": "EXTERNAL",
            "creator": "director",
            "created_at": "2026-07-21T00:00:00Z",
            "external_source": {
                "source_ref": director_file.name,
                "original_sha256": source_sha,
                "acquired_at": "2026-07-21T00:00:00Z",
            },
        },
        "permission": {"status": "DIRECTOR_APPROVED", "license_ref": "director-approval"},
        "accessibility_text": "A compact architecture diagram.",
    }
    _stamp(asset, "asset_record_sha256")
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_root.name,
        "manuscript_sha256": contract["manuscript_snapshot_sha256"],
        "assets": [asset],
    }
    return _stamp(manifest, "manifest_sha256")


def _prepare_external_asset_case(tmp_path: Path, content: bytes = b"<svg><title>director source</title></svg>"):
    run_root, contract, refs = _setup_run(tmp_path)
    director_root = tmp_path / "director-assets"
    director_root.mkdir()
    director_file = director_root / "director.svg"
    director_file.write_bytes(content)
    manifest = _external_asset(run_root, contract, director_file)
    contract["asset_plan"] = [{
        "asset_id": "asset-director-figure", "kind": "FIGURE", "label": "fig:director",
        "planned_path": "figures/director.svg", "source_refs": [director_file.name],
        "result_refs": [RESULT_REF],
    }]
    contract["source_hashes"].append(
        {"ref": director_file.name, "sha256": _file_hash(director_file), "kind": "ASSET"}
    )
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    manifest["manuscript_sha256"] = contract["manuscript_snapshot_sha256"]
    _stamp(manifest, "manifest_sha256")
    receipt = json.loads((run_root / RECEIPT_REF).read_text(encoding="utf-8"))
    for row, ref, authorization in zip(SECTIONS, refs, receipt["authorizations"]):
        _write_json(run_root / ref, _bundle(contract, row, _canonical_hash(authorization)))

    def add_figure(payload: dict) -> None:
        payload["draft_latex"] += (
            "\\begin{figure}\\centering\\includegraphics{figures/director.svg}"
            "\\caption{Director-provided architecture.}\\label{fig:director}\\end{figure}\n"
        )
        payload["labels"].append("fig:director")
        payload["asset_refs"].append("asset-director-figure")

    _rewrite_bundle(run_root, refs[0], add_figure)
    return run_root, contract, refs, director_root, director_file, manifest


def test_director_asset_is_copied_byte_for_byte_with_canonical_provenance(tmp_path):
    run_root, contract, refs, director_root, director_file, manifest = (
        _prepare_external_asset_case(tmp_path)
    )
    before = director_file.read_bytes()
    candidate = _integrate(
        run_root,
        contract,
        refs,
        asset_manifest=manifest,
        asset_sources={"asset-director-figure": director_file},
        director_asset_roots=[director_root],
    )
    source = materialize_source_tree(candidate, run_root=run_root)

    assert director_file.read_bytes() == before
    assert (source / "figures/director.svg").read_bytes() == before
    record = candidate["asset_manifest"]["assets"][0]
    assert record["source_inputs"][0]["sha256"] == record["output"]["sha256"]
    assert record["provenance"]["external_source"]["original_sha256"] == _file_hash(director_file)


def test_bibliography_is_part_of_the_fail_closed_tex_boundary(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    unsafe = BIBLIOGRAPHY.replace("A Frozen Local Source", "\\write18{touch escaped}")
    _assert_code(
        "UNSAFE_TEX",
        lambda: _integrate(run_root, contract, refs, bibliography_text=unsafe),
    )


def test_result_use_requires_a_real_frozen_receipt_binding(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    contract["claim_ledger"][1]["result_refs"] = [RESULT_REF]
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    receipt = json.loads((run_root / RECEIPT_REF).read_text(encoding="utf-8"))
    for row, ref, authorization in zip(SECTIONS, refs, receipt["authorizations"]):
        _write_json(run_root / ref, _bundle(contract, row, _canonical_hash(authorization)))
    _rewrite_bundle(
        run_root, refs[1],
        lambda payload: payload["claim_support_refs"][0]["result_refs"].append(RESULT_REF),
    )
    _assert_code("RESULT_RECEIPT_UNVERIFIED", lambda: _integrate(run_root, contract, refs))


def test_materialization_rejects_cross_run_replay_and_preserves_foreign_lock(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    candidate = _integrate(run_root, contract, refs)
    other_run = tmp_path / "run-002"
    other_run.mkdir()
    _assert_code(
        "CANDIDATE_RUN_MISMATCH",
        lambda: materialize_source_tree(candidate, run_root=other_run),
    )
    lock = run_root / ".source-integration.lock"
    lock.write_bytes(b"incumbent-writer")
    _assert_code("SOURCE_WRITER_BUSY", lambda: materialize_source_tree(candidate, run_root=run_root))
    assert lock.read_bytes() == b"incumbent-writer"


def test_scheduler_receipt_requires_an_external_authority(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    _assert_code(
        "AUTHORIZATION_VERIFIER_REQUIRED",
        lambda: integrate_manuscript(
            run_root=run_root, manuscript_contract=contract, section_bundle_refs=refs,
            required_sections=SECTIONS, bibliography_text=BIBLIOGRAPHY, stage=STAGE,
        ),
    )


def test_format_repair_cannot_change_json_structure(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    path = run_root / refs[0]
    valid_text = path.read_text(encoding="utf-8")
    path.write_text(valid_text.replace('"asset_refs":[]', '"asset_refs":{', 1), encoding="utf-8")
    _assert_code(
        "FORMAT_REPAIR_CHANGED_CONTENT",
        lambda: validate_section_bundle(
            refs[0], run_root=run_root, manuscript_contract=contract,
            required_section=SECTIONS[0], stage=STAGE,
            format_repair=lambda *_args: valid_text,
        ),
    )


def test_asset_source_refs_and_textual_asset_secrets_are_verified(tmp_path):
    run_root, contract, refs, director_root, director_file, manifest = (
        _prepare_external_asset_case(tmp_path)
    )
    manifest["assets"][0]["source_inputs"][0]["ref"] = "forged.svg"
    _stamp(manifest["assets"][0], "asset_record_sha256")
    _stamp(manifest, "manifest_sha256")
    _assert_code(
        "ASSET_SOURCE_INPUT_MISMATCH",
        lambda: _integrate(
            run_root, contract, refs, asset_manifest=manifest,
            asset_sources={"asset-director-figure": director_file},
            director_asset_roots=[director_root],
        ),
    )

    run_root, contract, refs, director_root, director_file, manifest = (
        _prepare_external_asset_case(tmp_path / "secret", b"<svg>TOPSECRET</svg>")
    )
    _assert_code(
        "SECRET_LEAKAGE",
        lambda: _integrate(
            run_root, contract, refs, asset_manifest=manifest,
            asset_sources={"asset-director-figure": director_file},
            director_asset_roots=[director_root], secret_sentinels={"fixture": "TOPSECRET"},
        ),
    )


def test_asset_copy_uses_hash_checked_bytes_not_a_later_path_read(tmp_path, monkeypatch):
    run_root, contract, refs, director_root, director_file, manifest = (
        _prepare_external_asset_case(tmp_path)
    )
    expected = director_file.read_bytes()
    injected = b"X" * len(expected)
    original_read = Path.read_bytes

    def raced_read(path: Path) -> bytes:
        return injected if path == director_file else original_read(path)

    monkeypatch.setattr(Path, "read_bytes", raced_read)
    candidate = _integrate(
        run_root, contract, refs, asset_manifest=manifest,
        asset_sources={"asset-director-figure": director_file}, director_asset_roots=[director_root],
    )
    assert candidate["files"]["figures/director.svg"] == expected


def test_generated_assets_require_argv_receipts_and_all_assets_must_exist(tmp_path):
    run_root, contract, refs = _setup_run(tmp_path)
    director_root = tmp_path / "director-assets"
    director_root.mkdir()
    director_file = director_root / "director.svg"
    director_file.write_bytes(b"<svg/>")
    manifest = _external_asset(run_root, contract, director_file)
    manifest["assets"][0]["provenance"] = {
        "kind": "GENERATED",
        "creator": "figure-table-author",
        "created_at": "2026-07-21T00:00:00Z",
    }
    _stamp(manifest["assets"][0], "asset_record_sha256")
    _stamp(manifest, "manifest_sha256")
    _assert_code(
        "GENERATED_COMMAND_REQUIRED",
        lambda: _integrate(
            run_root,
            contract,
            refs,
            asset_manifest=manifest,
            asset_sources={"asset-director-figure": director_file},
            director_asset_roots=[director_root],
        ),
    )

    manifest = _external_asset(run_root, contract, director_file)
    _assert_code(
        "ASSET_SOURCE_MISSING",
        lambda: _integrate(
            run_root,
            contract,
            refs,
            asset_manifest=manifest,
            asset_sources={},
            director_asset_roots=[director_root],
        ),
    )


@pytest.mark.parametrize("target_name", ["director-review", "other-run/source", "vault/source"])
def test_only_current_run_canonical_source_is_a_valid_target(tmp_path, target_name):
    run_root, contract, refs = _setup_run(tmp_path)
    candidate = _integrate(run_root, contract, refs)

    _assert_code(
        "CANONICAL_TARGET_REQUIRED",
        lambda: materialize_source_tree(candidate, run_root=run_root, target=run_root / target_name),
    )
    assert not (run_root / "source").exists()


def test_symlink_escape_and_partial_write_both_roll_back(tmp_path, monkeypatch):
    run_root, contract, refs = _setup_run(tmp_path)
    candidate = _integrate(run_root, contract, refs)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (run_root / "source").symlink_to(outside, target_is_directory=True)
    except OSError:
        pass  # The shared security suite exercises link policy on restricted Windows hosts.
    else:
        _assert_code("UNSAFE_OUTPUT_PATH", lambda: materialize_source_tree(candidate, run_root=run_root))
        assert list(outside.iterdir()) == []
        (run_root / "source").unlink()

    original = integrator_module._write_candidate_file
    calls = 0

    def fail_mid_publish(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected write failure")
        original(path, data)

    monkeypatch.setattr(integrator_module, "_write_candidate_file", fail_mid_publish)
    _assert_code("PUBLISH_FAILED", lambda: materialize_source_tree(candidate, run_root=run_root))
    assert not (run_root / "source").exists()
    assert not list(run_root.glob(".source-integration-*"))
