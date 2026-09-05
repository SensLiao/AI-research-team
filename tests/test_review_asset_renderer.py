"""TDD contract for provenance-closed, publication-safe review assets."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.review_asset_renderer import (
    AssetRenderError,
    render_asset_manifest,
    validate_asset_manifest,
)


SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "research_agent_teams"
    / "schemas"
    / "manuscript_asset_manifest.schema.json"
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_source(root: Path, ref: str, body: bytes) -> dict:
    target = root / ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {
        "ref": ref,
        "sha256": _sha_bytes(body),
        "kind": "EXTRACTION",
        "immutable": True,
    }


def _base_plan(root: Path) -> dict:
    corpus = _write_source(root, "evidence/corpus.json", b'{"included":12}')
    claims = _write_source(root, "evidence/claims.json", b'{"claims":["CLM-1"]}')
    results = _write_source(root, "results/frozen.json", b'{"n":12,"rate":0.75}')
    return {
        "run_id": "hidden-oracle-review-001",
        "manuscript_sha256": "a" * 64,
        "assets": [
            {
                "asset_id": "asset-prisma",
                "label": "fig:prisma-flow",
                "semantic_type": "EVIDENCE_TABLE",
                "template": "PRISMA_FLOW",
                "caption": "PRISMA flow of the frozen retrieval and screening set.",
                "accessibility_text": "Flow diagram from 42 identified records to 12 included studies.",
                "claim_refs": ["CLM-SEARCH-1"],
                "source_inputs": [corpus],
                "outputs": [
                    "manuscript/assets/prisma-flow.svg",
                    "manuscript/assets/prisma-flow.png",
                ],
                "parameters": {
                    "identified": 42,
                    "deduplicated": 35,
                    "screened": 35,
                    "excluded": 23,
                    "reports_sought": 20,
                    "reports_not_retrieved": 2,
                    "reports_assessed": 18,
                    "fulltext_excluded": 6,
                    "included": 12,
                },
                "evidence_rows": [
                    {
                        "row_id": "included-set",
                        "study_refs": ["STUDY-001", "STUDY-012"],
                        "extraction_refs": ["evidence/corpus.json#/included"],
                    }
                ],
            },
            {
                "asset_id": "asset-pathway",
                "label": "fig:hidden-oracle-pathway",
                "semantic_type": "CONCEPTUAL_SCHEMATIC",
                "template": "HIDDEN_ORACLE_PATHWAY",
                "caption": "Where hidden-oracle information enters and contaminates evaluation.",
                "accessibility_text": "Five-stage pathway from task construction to contaminated evaluation.",
                "claim_refs": ["CLM-PROV-1", "CLM-PROV-4"],
                "source_inputs": [claims],
                "outputs": [
                    "manuscript/assets/hidden-oracle-pathway.svg",
                    "manuscript/assets/hidden-oracle-pathway.png",
                ],
                "parameters": {
                    "stages": [
                        "Task construction",
                        "Prompt assembly",
                        "Oracle exposure",
                        "Model response",
                        "Evaluation",
                    ]
                },
            },
            {
                "asset_id": "asset-ladder",
                "label": "fig:oracle-ladder",
                "semantic_type": "CONCEPTUAL_SCHEMATIC",
                "template": "ORACLE_LADDER",
                "caption": "Oracle ladder ordered by increasing access to evaluation-only information.",
                "accessibility_text": "Four-rung ladder from no oracle to direct answer exposure.",
                "claim_refs": ["CLM-TAX-1"],
                "source_inputs": [claims],
                "outputs": [
                    "manuscript/assets/oracle-ladder.svg",
                    "manuscript/assets/oracle-ladder.png",
                ],
                "parameters": {
                    "rungs": [
                        "L0: no oracle",
                        "L1: structural hints",
                        "L2: evaluator feedback",
                        "L3: answer exposure",
                    ]
                },
            },
            {
                "asset_id": "asset-provenance-axes",
                "label": "fig:provenance-axes",
                "semantic_type": "CONCEPTUAL_SCHEMATIC",
                "template": "PROVENANCE_AXES",
                "caption": "Orthogonal prompt-provenance audit axes.",
                "accessibility_text": "Four independent rows for producer, reference access, realism evidence, and phase.",
                "claim_refs": ["CLM-TAX-1"],
                "source_inputs": [claims],
                "outputs": [
                    "manuscript/assets/provenance-axes.svg",
                    "manuscript/assets/provenance-axes.png",
                ],
                "parameters": {
                    "axes": [
                        {"label": "Producer", "values": ["Human", "Automatic", "Simulator"]},
                        {"label": "Reference access", "values": ["None", "Geometry", "Residual"]},
                        {"label": "Realism evidence", "values": ["Observed", "Synthetic", "Unclear"]},
                        {"label": "Phase", "values": ["Training", "Evaluation", "Stopping"]},
                    ]
                },
            },
            {
                "asset_id": "asset-heatmap",
                "label": "fig:evidence-map",
                "semantic_type": "QUANTITATIVE_PLOT",
                "template": "EVIDENCE_HEATMAP",
                "caption": "Claim-by-study evidence coverage in the frozen extraction matrix.",
                "accessibility_text": "Heatmap with two claims and two studies; darker cells indicate stronger support.",
                "claim_refs": ["CLM-PROV-1", "CLM-PROV-4"],
                "source_inputs": [results],
                "outputs": [
                    "manuscript/assets/evidence-map.svg",
                    "manuscript/assets/evidence-map.png",
                ],
                "parameters": {
                    "row_labels": ["STUDY-001", "STUDY-012"],
                    "row_display_labels": ["MedSAM", "Human-Touch"],
                    "column_labels": ["CLM-PROV-1", "CLM-PROV-4"],
                    "matrix": [[1.0, 0.5], [0.0, 0.75]],
                    "binary_symbols": True,
                },
                "numeric_cells": [
                    {
                        "result_ref": "results/frozen.json",
                        "cell_ref": "/rate",
                        "value": 0.75,
                        "units": "proportion",
                        "uncertainty": {
                            "kind": "NOT_APPLICABLE",
                            "value": 0.0,
                            "units": "proportion",
                        },
                    }
                ],
            },
        ],
    }


def _schema_errors(payload: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    def flatten(error):
        yield f"{error.json_path}: {error.message}"
        for child in error.context:
            yield from flatten(child)

    return [
        detail
        for error in Draft202012Validator(schema).iter_errors(payload)
        for detail in flatten(error)
    ]


def test_four_original_templates_render_svg_and_png_with_closed_receipts(tmp_path: Path):
    plan = _base_plan(tmp_path)

    manifest = render_asset_manifest(tmp_path, plan)

    assert _schema_errors(manifest) == []
    assert manifest["schema_version"] == "2.0.0"
    assert len(manifest["render_environment"]["font_set_sha256"]) == 64
    assert manifest["plan_closure"]["status"] == "CLOSED"
    assert manifest["plan_closure"]["planned_asset_ids"] == manifest["plan_closure"]["rendered_asset_ids"]
    assert {row["render_template"] for row in manifest["assets"]} == {
        "PRISMA_FLOW",
        "HIDDEN_ORACLE_PATHWAY",
        "ORACLE_LADDER",
        "PROVENANCE_AXES",
        "EVIDENCE_HEATMAP",
    }
    prisma_svg = (tmp_path / "manuscript/assets/prisma-flow.svg").read_text(
        encoding="utf-8"
    )
    assert "Reports not retrieved" in prisma_svg
    assert "Full-text reports excluded" in prisma_svg
    heatmap_svg = (tmp_path / "manuscript/assets/evidence-map.svg").read_text(
        encoding="utf-8"
    )
    assert "MedSAM" in heatmap_svg and "Human-Touch" in heatmap_svg
    assert "STUDY-001" not in heatmap_svg and "STUDY-012" not in heatmap_svg
    assert "1.00" not in heatmap_svg and "0.00" not in heatmap_svg
    for asset in manifest["assets"]:
        assert asset["render_receipt"]["shell"] is False
        assert asset["caption"]["text"]
        assert asset["accessibility_text"]
        for output in asset["outputs"]:
            path = tmp_path / output["path"]
            assert path.is_file()
            assert _sha_bytes(path.read_bytes()) == output["sha256"]
            if output["format"] == "SVG":
                assert path.read_text(encoding="utf-8").startswith("<svg")
            else:
                assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_rendering_is_byte_deterministic_for_fixed_inputs(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_manifest = render_asset_manifest(first, _base_plan(first))
    second_manifest = render_asset_manifest(second, _base_plan(second))

    first_hashes = [output["sha256"] for asset in first_manifest["assets"] for output in asset["outputs"]]
    second_hashes = [output["sha256"] for asset in second_manifest["assets"] for output in asset["outputs"]]
    assert first_hashes == second_hashes
    assert first_manifest["manifest_sha256"] == second_manifest["manifest_sha256"]


def test_conceptual_schematic_requires_sources_and_claims_but_not_numeric_results(tmp_path: Path):
    plan = _base_plan(tmp_path)
    conceptual = plan["assets"][1]
    assert "numeric_cells" not in conceptual

    manifest = render_asset_manifest(tmp_path, plan)

    rendered = next(row for row in manifest["assets"] if row["asset_id"] == "asset-pathway")
    assert rendered["semantic_type"] == "CONCEPTUAL_SCHEMATIC"
    assert rendered["claim_refs"] == conceptual["claim_refs"]
    assert "numeric_cells" not in rendered


def test_evidence_table_requires_study_and_extraction_refs_per_row(tmp_path: Path):
    plan = _base_plan(tmp_path)
    del plan["assets"][0]["evidence_rows"][0]["extraction_refs"]

    with pytest.raises(AssetRenderError, match="EVIDENCE_ROW_PROVENANCE"):
        render_asset_manifest(tmp_path, plan)


def test_evidence_row_extraction_ref_must_close_to_a_hashed_source(tmp_path: Path):
    plan = _base_plan(tmp_path)
    plan["assets"][0]["evidence_rows"][0]["extraction_refs"] = [
        "evidence/not-frozen.json#/included"
    ]

    with pytest.raises(AssetRenderError, match="EVIDENCE_ROW_PROVENANCE"):
        render_asset_manifest(tmp_path, plan)


def test_quantitative_plot_requires_units_and_uncertainty(tmp_path: Path):
    plan = _base_plan(tmp_path)
    quantitative = next(row for row in plan["assets"] if row["semantic_type"] == "QUANTITATIVE_PLOT")
    del quantitative["numeric_cells"][0]["uncertainty"]

    with pytest.raises(AssetRenderError, match="NUMERIC_PROVENANCE"):
        render_asset_manifest(tmp_path, plan)


def test_numeric_result_ref_must_close_to_a_hashed_source(tmp_path: Path):
    plan = _base_plan(tmp_path)
    quantitative = next(row for row in plan["assets"] if row["semantic_type"] == "QUANTITATIVE_PLOT")
    quantitative["numeric_cells"][0]["result_ref"] = "results/not-frozen.json"

    with pytest.raises(AssetRenderError, match="NUMERIC_PROVENANCE"):
        render_asset_manifest(tmp_path, plan)


def test_source_hash_mismatch_fails_before_any_asset_is_published(tmp_path: Path):
    plan = _base_plan(tmp_path)
    plan["assets"][0]["source_inputs"][0]["sha256"] = "f" * 64

    with pytest.raises(AssetRenderError, match="SOURCE_HASH_MISMATCH"):
        render_asset_manifest(tmp_path, plan)

    assert not (tmp_path / "manuscript" / "assets").exists()


def test_duplicate_label_and_unclosed_asset_plan_are_rejected(tmp_path: Path):
    plan = _base_plan(tmp_path)
    plan["assets"][1]["label"] = plan["assets"][0]["label"]
    with pytest.raises(AssetRenderError, match="DUPLICATE_LABEL"):
        render_asset_manifest(tmp_path, plan)

    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    clean_plan = _base_plan(clean_root)
    manifest = render_asset_manifest(clean_root, clean_plan)
    manifest["assets"].pop()
    with pytest.raises(AssetRenderError, match="ASSET_PLAN_NOT_CLOSED"):
        validate_asset_manifest(clean_root, clean_plan, manifest)


def test_uncleared_external_excerpt_cannot_be_rendered_for_public_release(tmp_path: Path):
    pdf = _write_source(tmp_path, "sources/paper.pdf", b"not-a-real-pdf")
    plan = {
        "run_id": "external-001",
        "manuscript_sha256": "b" * 64,
        "assets": [
            {
                "asset_id": "asset-excerpt",
                "label": "fig:external-excerpt",
                "semantic_type": "EXTERNAL_EXCERPT",
                "template": "PDF_EXCERPT",
                "caption": "Excerpt from a third-party paper.",
                "accessibility_text": "Cropped third-party diagram.",
                "claim_refs": ["CLM-EXT-1"],
                "source_inputs": [pdf],
                "outputs": ["manuscript/assets/external-excerpt.png"],
                "release_scope": "PUBLIC",
                "excerpt": {
                    "pdf_ref": "sources/paper.pdf",
                    "pdf_sha256": pdf["sha256"],
                    "page": 1,
                    "crop": {"x": 0, "y": 0, "width": 100, "height": 100, "coordinate_space": "PDF_POINTS"},
                    "license_ref": "publisher-license-pending",
                    "permission_status": "PENDING",
                },
            }
        ],
    }

    with pytest.raises(AssetRenderError, match="EXTERNAL_PERMISSION_NOT_CLEARED"):
        render_asset_manifest(tmp_path, plan)


def test_cleared_external_excerpt_is_hash_page_crop_and_permission_bound(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "sources" / "paper.pdf"
    pdf_path.parent.mkdir(parents=True)
    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(10, 10, 110, 110), color=(0, 0, 0), fill=(0.8, 0.9, 1.0))
        document.save(str(pdf_path), garbage=4, deflate=True)
    pdf_hash = _sha_bytes(pdf_path.read_bytes())
    receipt = _write_source(tmp_path, "permissions/excerpt.json", b'{"status":"CLEARED"}')
    plan = {
        "run_id": "external-cleared-001",
        "manuscript_sha256": "b" * 64,
        "assets": [
            {
                "asset_id": "asset-excerpt",
                "label": "fig:external-excerpt",
                "semantic_type": "EXTERNAL_EXCERPT",
                "template": "PDF_EXCERPT",
                "caption": "Permission-cleared excerpt from a third-party paper.",
                "accessibility_text": "Cropped blue square from page one of the source PDF.",
                "claim_refs": ["CLM-EXT-1"],
                "source_inputs": [
                    {"ref": "sources/paper.pdf", "sha256": pdf_hash, "kind": "PDF_SOURCE", "immutable": True}
                ],
                "outputs": ["manuscript/assets/external-excerpt.png"],
                "release_scope": "PUBLIC",
                "excerpt": {
                    "pdf_ref": "sources/paper.pdf",
                    "pdf_sha256": pdf_hash,
                    "page": 1,
                    "crop": {"x": 10, "y": 10, "width": 100, "height": 100, "coordinate_space": "PDF_POINTS"},
                    "license_ref": "publisher-license-001",
                    "permission_status": "CLEARED",
                    "permission_receipt_ref": receipt["ref"],
                    "permission_receipt_sha256": receipt["sha256"],
                },
            }
        ],
    }

    manifest = render_asset_manifest(tmp_path, plan)

    excerpt = manifest["assets"][0]
    assert excerpt["permission"]["public_release_allowed"] is True
    assert excerpt["excerpt"]["pdf_sha256"] == pdf_hash
    assert excerpt["excerpt"]["page"] == 1
    assert excerpt["outputs"][0]["format"] == "PNG"
    from PIL import Image

    with Image.open(tmp_path / excerpt["outputs"][0]["path"]) as rendered:
        # Ten device pixels per PDF point preserve roughly 300 effective ppi
        # when a typical figure crop is expanded to manuscript column width.
        assert rendered.width == 1000 and rendered.height == 1000
    assert _schema_errors(manifest) == []


def test_schema_rejects_quantitative_asset_missing_uncertainty(tmp_path: Path):
    manifest = render_asset_manifest(tmp_path, _base_plan(tmp_path))
    broken = copy.deepcopy(manifest)
    quantitative = next(row for row in broken["assets"] if row["semantic_type"] == "QUANTITATIVE_PLOT")
    del quantitative["numeric_cells"][0]["uncertainty"]

    assert any("uncertainty" in path for path in _schema_errors(broken))
