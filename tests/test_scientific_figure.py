"""Real-byte regression tests for the offline scientific figure adapter."""
from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import fitz
import pytest
from PIL import Image

from research_agent_teams.tools.scientific_figure import (
    ScientificFigureError,
    bundle_manifest,
    render_figure,
)
from research_agent_teams.tools.validate_artifact import validate_payload


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 80">
  <rect x="0" y="0" width="160" height="80" fill="white"/>
  <g id="art-icon"><rect x="8" y="12" width="55" height="35"
       fill="#DDEEFF" stroke="#222222" stroke-width="0.5"/></g>
  <rect x="97" y="12" width="55" height="35" fill="#F8E6CA"
       stroke="#222222" stroke-width="0.5"/>
  <line id="rel-ab" x1="65" y1="30" x2="95" y2="30"
        stroke="#222222" stroke-width="0.5"/>
  <text x="14" y="34" font-family="Helvetica" font-size="9">Alpha</text>
  <text x="105" y="34" font-family="Helvetica" font-size="9">Beta</text>
</svg>"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value: object) -> str:
    body = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha(body)


def _write_input(root: Path, ref: str, body: bytes) -> dict:
    target = root / ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {"ref": ref, "sha256": _sha(body)}


@pytest.fixture()
def figure_case(tmp_path):
    root = tmp_path / "figure-test-run"
    root.mkdir()
    svg = _write_input(root, "inputs/source.svg", SVG.encode("utf-8"))
    evidence = _write_input(
        root, "inputs/evidence.json",
        b'{"claim_id":"CLM-1","statement":"Alpha is associated with Beta."}',
    )
    evidence.update(kind="EXTERNAL_EVIDENCE", immutable=True)
    spec = {
        "run_id": root.name,
        "asset_id": "figure-association",
        "label": "fig:association",
        "purpose": "Illustrate a reported association without an effect-size claim.",
        "caption": {
            "text": "Alpha is associated with Beta; the line does not imply causation.",
            "owner_role": "manuscript-figure-table-engineer",
        },
        "accessibility_text": "Two labeled boxes joined by an association line.",
        "svg_source": svg,
        "source_inputs": [evidence],
        "claim_refs": ["CLM-1"],
        "relations": [{
            "id": "rel-ab", "type": "association", "support": "reported",
            "claim_refs": ["CLM-1"],
        }],
        "output_stem": "outputs/figure-association",
        "width_mm": 80,
        "dpi": 300,
        "min_font_pt": 8,
    }
    return root, spec


def _plan(spec: dict) -> dict:
    return {"assets": [{
        name: spec[name] for name in ("asset_id", "label", "output_stem")
    }]}


def _replace_svg(root: Path, spec: dict, text: str) -> None:
    spec["svg_source"] = _write_input(
        root, spec["svg_source"]["ref"], text.encode("utf-8"),
    )


def test_real_render_exports_editable_assets_and_valid_v2_manifest(figure_case):
    root, spec = figure_case
    original_spec = copy.deepcopy(spec)
    original_svg = (root / spec["svg_source"]["ref"]).read_bytes()

    rendered = render_figure(root, spec)
    asset = rendered["asset"]
    assert [row["format"] for row in asset["outputs"]] == ["SVG", "PDF", "PNG"]
    assert asset["render_template"] == "SCIENTIFIC_ILLUSTRATION"
    assert asset["semantic_type"] == "CONCEPTUAL_SCHEMATIC"
    assert "numeric_cells" not in asset
    for output in asset["outputs"]:
        body = (root / output["path"]).read_bytes()
        assert len(body) == output["byte_size"] > 0
        assert _sha(body) == output["sha256"]
        assert output["overwrite_policy"] == "CREATE_NEW"
        assert output["owner_run_id"] == root.name

    svg_path = root / (spec["output_stem"] + ".svg")
    texts = ET.parse(svg_path).findall(".//{http://www.w3.org/2000/svg}text")
    assert [element.text for element in texts] == ["Alpha", "Beta"]
    with fitz.open(root / (spec["output_stem"] + ".pdf")) as pdf:
        assert len(pdf) == 1
        assert "Alpha" in pdf[0].get_text()
        assert "Beta" in pdf[0].get_text()
    with Image.open(root / (spec["output_stem"] + ".png")) as png:
        assert png.format == "PNG"
        assert png.mode == "RGB"
        assert png.getpixel((0, 0)) == (255, 255, 255)

    plan = _plan(spec)
    manifest = bundle_manifest(root.name, "a" * 64, plan, [rendered])
    assert validate_payload("manuscript_asset_manifest", manifest) == []
    assert manifest["schema_version"] == "2.0.0"
    assert manifest["asset_plan_sha256"] == _canonical_sha(plan)
    assert manifest["plan_closure"]["status"] == "CLOSED"
    assert manifest["plan_closure"]["planned_output_refs"] == [
        spec["output_stem"] + ext for ext in (".svg", ".pdf", ".png")
    ]
    assert rendered["checks"]["scientific_review"] == "REQUIRED"
    assert rendered["checks"]["visual_review"] == "REQUIRED"
    assert spec == original_spec
    assert (root / spec["svg_source"]["ref"]).read_bytes() == original_svg


@pytest.mark.parametrize("width_mm,dpi", [(80, 300), (120, 600)])
def test_final_physical_size_and_raster_dpi_are_real(figure_case, width_mm, dpi):
    root, spec = figure_case
    spec.update(width_mm=width_mm, dpi=dpi)
    rendered = render_figure(root, spec)
    with fitz.open(root / (spec["output_stem"] + ".pdf")) as pdf:
        assert pdf[0].rect.width * 25.4 / 72 == pytest.approx(width_mm, abs=0.1)
        assert pdf[0].rect.height * 25.4 / 72 == pytest.approx(width_mm / 2, abs=0.1)
    with Image.open(root / (spec["output_stem"] + ".png")) as png:
        assert png.width == pytest.approx(width_mm / 25.4 * dpi, abs=1.1)
        assert png.height == pytest.approx(width_mm / 2 / 25.4 * dpi, abs=1.1)
        assert png.info["dpi"] == pytest.approx((dpi, dpi), abs=0.02)
        assert rendered["checks"]["pixels"] == [png.width, png.height]
        assert rendered["checks"]["effective_dpi"] == pytest.approx(
            png.width / (width_mm / 25.4), abs=0.01,
        )


@pytest.mark.parametrize("input_name", ["svg_source", "source_inputs"])
def test_changed_input_bytes_are_rejected_before_export(figure_case, input_name):
    root, spec = figure_case
    row = spec["svg_source"] if input_name == "svg_source" else spec["source_inputs"][0]
    target = root / row["ref"]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ScientificFigureError, match="INPUT_HASH_MISMATCH"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("claims", [[], ["CLM-NO-SOURCE"]])
def test_relations_require_nonempty_known_claim_support(figure_case, claims):
    root, spec = figure_case
    spec["relations"][0]["claim_refs"] = claims
    with pytest.raises(ScientificFigureError, match="UNSUPPORTED_RELATION"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("missing", ["license", "license_evidence", "credit_text"])
def test_external_artwork_requires_licence_evidence_and_credit(figure_case, missing):
    root, spec = figure_case
    artwork = _write_input(root, "inputs/icon.svg", SVG.encode("utf-8"))
    artwork.update(
        svg_id="art-icon", license="CC-BY-4.0", creator="Fixture author",
        source_url="https://example.invalid/icon",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_evidence="Fixture item-level licence statement.",
        credit_text="Icon: Fixture author, CC BY 4.0.",
    )
    del artwork[missing]
    spec["artwork"] = [artwork]
    with pytest.raises(ScientificFigureError, match="ARTWORK_PERMISSION|ARTWORK_CREDIT"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("unsafe", [
    '<script>alert(1)</script>',
    '<use href="https://example.invalid/external.svg#icon"/>',
    '<rect x="1" y="1" width="2" height="2" onload="alert(1)"/>',
])
def test_svg_active_content_and_external_references_are_rejected(figure_case, unsafe):
    root, spec = figure_case
    _replace_svg(root, spec, SVG.replace("</svg>", unsafe + "</svg>"))
    with pytest.raises(ScientificFigureError, match="UNSAFE_ASSET_CONTENT"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("font_style", ["italic", "expression(alert(1))"])
def test_svg_font_style_accepts_static_italic_and_rejects_expressions(figure_case, font_style):
    root, spec = figure_case
    _replace_svg(
        root, spec,
        SVG.replace('font-size="9"', f'font-size="9" font-style="{font_style}"'),
    )
    if font_style != "italic":
        with pytest.raises(ScientificFigureError, match="UNSAFE_ASSET_CONTENT"):
            render_figure(root, spec)
        assert not (root / "outputs").exists()
        return
    render_figure(root, spec)
    with fitz.open(root / (spec["output_stem"] + ".pdf")) as pdf:
        spans = [
            span for block in pdf[0].get_text("dict")["blocks"]
            if block["type"] == 0 for line in block["lines"] for span in line["spans"]
        ]
    assert {span["text"] for span in spans} == {"Alpha", "Beta"}
    assert all("Oblique" in span["font"] or "Italic" in span["font"] for span in spans)


def test_straight_dashes_remain_gaps_in_actual_pdf_and_png(figure_case):
    root, spec = figure_case
    probe = (
        '<path id="dash-probe" d="M 10 65 L 150 65" fill="none" '
        'stroke="#000000" stroke-width="1" stroke-linecap="butt" '
        'stroke-dasharray="10 10"/>'
    )
    _replace_svg(root, spec, SVG.replace("</svg>", probe + "</svg>"))
    render_figure(root, spec)
    with fitz.open(root / (spec["output_stem"] + ".pdf")) as pdf:
        scale = pdf[0].rect.width / 160
        segments = []
        for drawing in pdf[0].get_drawings():
            # MuPDF may encode a horizontal stroke as a zero-height PDF rectangle.
            # Check the rendered geometric extents, not its internal path opcode.
            rect = drawing["rect"]
            if (drawing["type"] == "s" and abs(rect.y0 / scale - 65) < 0.1
                    and abs(rect.y1 / scale - 65) < 0.1):
                segments.append((rect.x0 / scale, rect.x1 / scale))
        segments.sort()
        assert len(segments) == 7
        for (start, end), expected_start in zip(segments, range(10, 150, 20)):
            assert start == pytest.approx(expected_start, abs=0.1)
            assert end == pytest.approx(expected_start + 10, abs=0.1)
    with Image.open(root / (spec["output_stem"] + ".png")) as png:
        pixels_per_unit = spec["width_mm"] / 25.4 * spec["dpi"] / 160
        y = round(65 * pixels_per_unit)
        for x in range(15, 150, 20):
            assert max(png.getpixel((round(x * pixels_per_unit), y))) < 50
        for x in range(25, 150, 20):
            assert min(png.getpixel((round(x * pixels_per_unit), y))) > 240


def test_curved_dashes_are_rejected_instead_of_becoming_solid(figure_case):
    root, spec = figure_case
    curve = (
        '<path d="M 10 65 Q 80 45 150 65" fill="none" stroke="#000000" '
        'stroke-width="1" stroke-dasharray="10 10"/>'
    )
    _replace_svg(root, spec, SVG.replace("</svg>", curve + "</svg>"))
    with pytest.raises(ScientificFigureError, match="UNSUPPORTED_DASH_PATH"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("location", ["output", "svg_absolute", "evidence_parent"])
def test_paths_cannot_escape_the_run_directory(figure_case, location):
    root, spec = figure_case
    outside = root.parent / "outside.svg"
    sentinel = SVG.encode("utf-8")
    outside.write_bytes(sentinel)
    if location == "output":
        spec["output_stem"] = "../outside-output"
    elif location == "svg_absolute":
        spec["svg_source"] = {"ref": str(outside.resolve()), "sha256": _sha(sentinel)}
    else:
        spec["source_inputs"][0].update(ref="../outside.svg", sha256=_sha(sentinel))
    with pytest.raises(ScientificFigureError, match="UNSAFE_PATH"):
        render_figure(root, spec)
    assert outside.read_bytes() == sentinel
    assert not (root / "outputs").exists()
    assert not (root.parent / "outside-output.svg").exists()


def test_font_size_is_checked_after_actual_render_scaling(figure_case):
    root, spec = figure_case
    _replace_svg(root, spec, SVG.replace('font-size="9"', 'font-size="2"'))
    with pytest.raises(ScientificFigureError, match="SMALL_TEXT"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


def test_fully_clipped_svg_label_cannot_disappear_into_a_passing_render(figure_case):
    root, spec = figure_case
    outside = (
        '<text x="170" y="68" font-family="Helvetica" font-size="9">'
        'Required label outside canvas</text>'
    )
    _replace_svg(root, spec, SVG.replace("</svg>", outside + "</svg>"))
    with pytest.raises(ScientificFigureError, match="TEXT_OUTSIDE_CANVAS"):
        render_figure(root, spec)
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("extension", [".svg", ".pdf", ".png"])
def test_existing_output_blocks_the_whole_export_without_overwrite(figure_case, extension):
    root, spec = figure_case
    existing = root / (spec["output_stem"] + extension)
    existing.parent.mkdir()
    sentinel = b"User-owned existing output must survive byte-for-byte."
    existing.write_bytes(sentinel)
    with pytest.raises(ScientificFigureError, match="OUTPUT_EXISTS"):
        render_figure(root, spec)
    assert existing.read_bytes() == sentinel
    assert list(existing.parent.iterdir()) == [existing]


@pytest.mark.parametrize("mismatch", ["missing_figure", "wrong_label", "wrong_output_stem"])
def test_bundle_closure_compares_the_actual_plan_with_rendered_assets(figure_case, mismatch):
    root, spec = figure_case
    rendered = render_figure(root, spec)
    plan = _plan(spec)
    if mismatch == "missing_figure":
        plan["assets"].append({
            "asset_id": "figure-required-but-missing",
            "label": "fig:missing",
            "output_stem": "outputs/required-but-missing",
        })
    elif mismatch == "wrong_label":
        plan["assets"][0]["label"] = "fig:requested-label"
    else:
        plan["assets"][0]["output_stem"] = "outputs/requested-stem"
    original_plan = copy.deepcopy(plan)
    original_rendered = copy.deepcopy(rendered)
    with pytest.raises(ScientificFigureError, match="INCOMPLETE_PLAN"):
        bundle_manifest(root.name, "a" * 64, plan, [rendered])
    assert plan == original_plan
    assert rendered == original_rendered
