"""Deterministic, provenance-closed renderer for review-manuscript assets.

The renderer creates original diagrams from frozen local facts.  It never
downloads or copies a paper figure.  Third-party PDF excerpts use a separate
``EXTERNAL_EXCERPT`` contract and cannot enter a public output unless a
hash-bound permission receipt is present and marked ``CLEARED``.

All rendering happens in-process (``shell=False`` by construction).  SVG and
PNG bytes are prepared and validated before any target is created, source and
output paths are fenced to the active run, and every source/output/parameter
set is SHA-256 bound in the returned manifest.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import platform
import re
from html import escape as xml_escape
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "2.0.0"
RENDERER_REF = "research_agent_teams/tools/review_asset_renderer.py"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "manuscript_asset_manifest.schema.json"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_LABEL_RE = re.compile(r"^(fig|tab):[A-Za-z0-9][A-Za-z0-9:._-]*$")
_TEMPLATE_TYPES = {
    "PRISMA_FLOW": "EVIDENCE_TABLE",
    "HIDDEN_ORACLE_PATHWAY": "CONCEPTUAL_SCHEMATIC",
    "ORACLE_LADDER": "CONCEPTUAL_SCHEMATIC",
    "PROVENANCE_AXES": "CONCEPTUAL_SCHEMATIC",
    "EVIDENCE_HEATMAP": "QUANTITATIVE_PLOT",
    "PDF_EXCERPT": "EXTERNAL_EXCERPT",
}
_MEDIA = {
    ".svg": ("SVG", "image/svg+xml"),
    ".png": ("PNG", "image/png"),
}
_PALETTE = {
    "ink": "#17202a",
    "muted": "#52606d",
    "paper": "#ffffff",
    "panel": "#f5f7fa",
    "line": "#9aa5b1",
    "accent": "#1f6f8b",
    "accent2": "#d1495b",
    "warm": "#edae49",
}


class AssetRenderError(RuntimeError):
    """Typed fail-closed renderer error with a stable machine code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise AssetRenderError(code, message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_VALUE", str(exc))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_value(value: object) -> str:
    return _hash_bytes(_canonical_bytes(value))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty(value: object, *, code: str, field: str) -> str:
    text = str(value) if value is not None else ""
    if not text.strip():
        _fail(code, f"{field} must be non-empty")
    return text


def _safe_path(root: Path, ref: object, *, code: str) -> tuple[str, Path]:
    text = _nonempty(ref, code=code, field="path").replace("\\", "/")
    pure = Path(text)
    if pure.is_absolute() or pure.drive or any(part == ".." for part in pure.parts):
        _fail(code, f"path escapes active run: {text}")
    candidate = (root / pure).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        _fail(code, f"path escapes active run: {text}")
    return pure.as_posix(), candidate


def _unique_strings(value: object, *, code: str, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail(code, f"{field} must be a non-empty list")
    out = [_nonempty(item, code=code, field=field) for item in value]
    if len(set(out)) != len(out):
        _fail(code, f"{field} contains duplicates")
    return out


def _verify_source(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    required = {"ref", "sha256", "kind", "immutable"}
    if not isinstance(row, Mapping) or not required.issubset(row):
        _fail("SOURCE_PROVENANCE", "source input is missing ref/hash/kind/immutable")
    ref, path = _safe_path(root, row.get("ref"), code="SOURCE_PATH_UNSAFE")
    expected = str(row.get("sha256") or "")
    if not _SHA_RE.fullmatch(expected):
        _fail("SOURCE_PROVENANCE", f"source hash is not SHA-256: {ref}")
    if row.get("immutable") is not True:
        _fail("SOURCE_PROVENANCE", f"source is not frozen immutable: {ref}")
    if not path.is_file():
        _fail("SOURCE_MISSING", f"source does not exist: {ref}")
    actual = _file_hash(path)
    if actual != expected:
        _fail("SOURCE_HASH_MISMATCH", f"source hash differs: {ref}")
    return {
        "ref": ref,
        "sha256": actual,
        "kind": _nonempty(row.get("kind"), code="SOURCE_PROVENANCE", field="source kind"),
        "immutable": True,
    }


def _environment() -> dict[str, str]:
    try:
        import PIL

        pillow = str(PIL.__version__)
    except Exception:  # pragma: no cover - Pillow is a declared renderer dependency
        pillow = "UNAVAILABLE"
    try:
        import fitz

        pymupdf = str(getattr(fitz, "VersionBind", "UNKNOWN"))
    except Exception:  # optional until an external excerpt is requested
        pymupdf = "UNAVAILABLE"
    font_facts: list[dict[str, str]] = []
    try:
        from PIL import ImageFont

        for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            font = ImageFont.truetype(name, 16)
            path = Path(font.path)
            font_facts.append({"name": name, "sha256": _file_hash(path)})
    except Exception:  # pragma: no cover - Pillow/font deployment failure
        font_facts.append({"name": "UNAVAILABLE", "sha256": "0" * 64})
    facts = {
        "python": platform.python_version(),
        "pillow": pillow,
        "pymupdf": pymupdf,
        "font_set_sha256": _hash_value(font_facts),
    }
    return {**facts, "environment_sha256": _hash_value(facts)}


def _svg_text(x: float, y: float, text: object, *, size: int = 18, weight: int = 400,
              anchor: str = "middle", fill: str | None = None) -> str:
    safe = xml_escape(str(text), quote=True)
    colour = fill or _PALETTE["ink"]
    return (
        f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{colour}">{safe}</text>'
    )


def _svg_box(x: float, y: float, width: float, height: float, *, fill: str = "#ffffff",
             stroke: str | None = None, radius: int = 10) -> str:
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" '
        f'rx="{radius}" fill="{fill}" stroke="{stroke or _PALETTE["line"]}" stroke-width="2"/>'
    )


def _svg_document(width: int, height: int, body: Sequence[str], alt: str) -> bytes:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Original review figure</title>',
        f'<desc id="desc">{xml_escape(alt, quote=True)}</desc>',
        f'<rect width="{width}" height="{height}" fill="{_PALETTE["paper"]}"/>',
        *body,
        "</svg>",
    ]
    return ("\n".join(parts) + "\n").encode("utf-8")


def _prisma_svg(parameters: Mapping[str, Any], alt: str) -> bytes:
    keys = ("identified", "deduplicated", "screened", "excluded", "included")
    try:
        counts = {key: int(parameters[key]) for key in keys}
    except (KeyError, TypeError, ValueError):
        _fail("PRISMA_PARAMETERS", f"PRISMA requires integer counts: {', '.join(keys)}")
    if any(value < 0 for value in counts.values()):
        _fail("PRISMA_COUNT_INCONSISTENT", "PRISMA counts cannot be negative")
    if counts["deduplicated"] > counts["identified"] or counts["screened"] != counts["deduplicated"]:
        _fail("PRISMA_COUNT_INCONSISTENT", "screened must equal deduplicated and not exceed identified")
    if counts["excluded"] + counts["included"] != counts["screened"]:
        _fail("PRISMA_COUNT_INCONSISTENT", "excluded plus included must equal screened")
    extended_names = (
        "reports_sought",
        "reports_not_retrieved",
        "reports_assessed",
        "fulltext_excluded",
    )
    present = [name in parameters for name in extended_names]
    if any(present) and not all(present):
        _fail("PRISMA_PARAMETERS", "extended PRISMA counts must be supplied together")
    if all(present):
        try:
            extended = {name: int(parameters[name]) for name in extended_names}
        except (TypeError, ValueError):
            _fail("PRISMA_PARAMETERS", "extended PRISMA counts must be integers")
        if any(value < 0 for value in extended.values()):
            _fail("PRISMA_COUNT_INCONSISTENT", "extended PRISMA counts cannot be negative")
        record_excluded = counts["screened"] - extended["reports_sought"]
        if (
            record_excluded < 0
            or extended["reports_sought"] - extended["reports_not_retrieved"]
            != extended["reports_assessed"]
            or extended["reports_assessed"] - extended["fulltext_excluded"]
            != counts["included"]
            or record_excluded
            + extended["reports_not_retrieved"]
            + extended["fulltext_excluded"]
            != counts["excluded"]
        ):
            _fail("PRISMA_COUNT_INCONSISTENT", "extended PRISMA stages do not reconcile")
        labels = [
            ("Records identified", counts["identified"]),
            ("After duplicate/non-report removal", counts["deduplicated"]),
            ("Records screened", counts["screened"]),
            ("Reports sought for retrieval", extended["reports_sought"]),
            ("Full-text reports assessed", extended["reports_assessed"]),
            ("Studies included", counts["included"]),
        ]
        side_labels = [
            (2, "Records excluded", record_excluded),
            (3, "Reports not retrieved", extended["reports_not_retrieved"]),
            (4, "Full-text reports excluded", extended["fulltext_excluded"]),
        ]
        width, height = 980, 850
        body = [_svg_text(width / 2, 42, "PRISMA evidence-assembly flow", size=24, weight=700)]
        for index, (label, count) in enumerate(labels):
            y = 72 + index * 124
            body.append(_svg_box(70, y, 500, 78, fill=_PALETTE["panel"]))
            body.append(_svg_text(320, y + 32, label, size=18, weight=600))
            body.append(_svg_text(320, y + 59, f"n = {count}", size=16, fill=_PALETTE["muted"]))
            if index < len(labels) - 1:
                body.append(f'<path d="M320 {y + 78} V{y + 118}" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
                body.append(f'<path d="M312 {y + 108} L320 {y + 118} L328 {y + 108}" fill="none" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
        for stage_index, label, count in side_labels:
            y = 72 + stage_index * 124
            body.append(_svg_box(640, y, 280, 78, fill="#fff4e5", stroke=_PALETTE["warm"]))
            body.append(_svg_text(780, y + 32, label, size=16, weight=600))
            body.append(_svg_text(780, y + 59, f"n = {count}", size=15))
            body.append(f'<path d="M570 {y + 39} H640" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
        body.append(_svg_text(width / 2, 824, "Counts are derived from the frozen screening manifest", size=14, fill=_PALETTE["muted"]))
        return _svg_document(width, height, body, alt)
    labels = [
        ("Records identified", counts["identified"]),
        ("After deduplication", counts["deduplicated"]),
        ("Records screened", counts["screened"]),
        ("Studies included", counts["included"]),
    ]
    body = [_svg_text(450, 42, "PRISMA flow", size=24, weight=700)]
    for index, (label, count) in enumerate(labels):
        y = 72 + index * 120
        body.append(_svg_box(230, y, 440, 76, fill=_PALETTE["panel"]))
        body.append(_svg_text(450, y + 31, label, size=18, weight=600))
        body.append(_svg_text(450, y + 57, f"n = {count}", size=16, fill=_PALETTE["muted"]))
        if index < len(labels) - 1:
            body.append(f'<path d="M450 {y + 76} V{y + 114}" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
            body.append(f'<path d="M442 {y + 104} L450 {y + 114} L458 {y + 104}" fill="none" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
    body.append(_svg_box(700, 312, 170, 76, fill="#fff4e5", stroke=_PALETTE["warm"]))
    body.append(_svg_text(785, 343, "Excluded", size=17, weight=600))
    body.append(_svg_text(785, 369, f'n = {counts["excluded"]}', size=16))
    body.append(f'<path d="M670 350 H700" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
    return _svg_document(900, 570, body, alt)


def _pathway_svg(parameters: Mapping[str, Any], alt: str) -> bytes:
    stages = parameters.get("stages")
    if not isinstance(stages, list) or len(stages) < 2 or any(not str(stage).strip() for stage in stages):
        _fail("PATHWAY_PARAMETERS", "reference-information pathway requires at least two named stages")
    width, height = 1100, 310
    margin, gap = 40, 24
    box_width = (width - 2 * margin - gap * (len(stages) - 1)) / len(stages)
    body = [_svg_text(width / 2, 44, "Reference-conditioned information pathway", size=24, weight=700)]
    for index, stage in enumerate(stages):
        x = margin + index * (box_width + gap)
        colour = "#e8f1f5" if "Oracle" not in str(stage) else "#fbe9ec"
        stroke = _PALETTE["accent"] if "Oracle" not in str(stage) else _PALETTE["accent2"]
        body.append(_svg_box(x, 105, box_width, 92, fill=colour, stroke=stroke))
        words = str(stage).split()
        split = max(1, len(words) // 2)
        body.append(_svg_text(x + box_width / 2, 144, " ".join(words[:split]), size=15, weight=600))
        if split < len(words):
            body.append(_svg_text(x + box_width / 2, 168, " ".join(words[split:]), size=15, weight=600))
        body.append(_svg_text(x + box_width / 2, 224, f"P{index + 1}", size=13, fill=_PALETTE["muted"]))
        if index < len(stages) - 1:
            start = x + box_width
            end = start + gap
            body.append(f'<path d="M{start:g} 151 H{end:g}" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
            body.append(f'<path d="M{end - 8:g} 143 L{end:g} 151 L{end - 8:g} 159" fill="none" stroke="{_PALETTE["ink"]}" stroke-width="2"/>')
    body.append(_svg_text(width / 2, 280, "Original synthesis — no third-party figure copied", size=14, fill=_PALETTE["muted"]))
    return _svg_document(width, height, body, alt)


def _ladder_svg(parameters: Mapping[str, Any], alt: str) -> bytes:
    rungs = parameters.get("rungs")
    if not isinstance(rungs, list) or len(rungs) < 2 or any(not str(row).strip() for row in rungs):
        _fail("LADDER_PARAMETERS", "oracle ladder requires at least two named rungs")
    width, height = 1300, 520
    body = [_svg_text(width / 2, 42, "Oracle ladder", size=24, weight=700)]
    body.extend([
        f'<path d="M250 455 L365 90" stroke="{_PALETTE["ink"]}" stroke-width="8"/>',
        f'<path d="M650 455 L535 90" stroke="{_PALETTE["ink"]}" stroke-width="8"/>',
    ])
    for index, rung in enumerate(rungs):
        fraction = index / max(1, len(rungs) - 1)
        y = 420 - fraction * 285
        left = 262 + fraction * 90
        right = 638 - fraction * 90
        colour = _PALETTE["accent2"] if index == len(rungs) - 1 else _PALETTE["accent"]
        body.append(f'<path d="M{left:g} {y:g} H{right:g}" stroke="{colour}" stroke-width="12" stroke-linecap="round"/>')
        body.append(_svg_text(690, y + 6, rung, size=15, weight=600, anchor="start"))
    body.append(_svg_text(155, 476, "lower oracle access", size=14, fill=_PALETTE["muted"]))
    body.append(_svg_text(450, 80, "greater evaluation-only information", size=14, fill=_PALETTE["accent2"]))
    return _svg_document(width, height, body, alt)


def _provenance_axes_values(parameters: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    axes = parameters.get("axes")
    if not isinstance(axes, list) or len(axes) < 3:
        _fail("PROVENANCE_AXES_PARAMETERS", "provenance axes require at least three axis rows")
    out: list[tuple[str, list[str]]] = []
    for axis in axes:
        if not isinstance(axis, Mapping):
            _fail("PROVENANCE_AXES_PARAMETERS", "each provenance axis must be an object")
        label = str(axis.get("label") or "").strip()
        values = axis.get("values")
        if not label or not isinstance(values, list) or len(values) < 2:
            _fail("PROVENANCE_AXES_PARAMETERS", "each provenance axis needs a label and values")
        display = [str(value).strip() for value in values]
        if any(not value for value in display) or len(set(display)) != len(display):
            _fail("PROVENANCE_AXES_PARAMETERS", "axis values must be non-empty and unique")
        out.append((label, display))
    return out


def _provenance_axes_svg(parameters: Mapping[str, Any], alt: str) -> bytes:
    axes = _provenance_axes_values(parameters)
    width, row_h, left, top = 1700, 126, 300, 112
    height = top + len(axes) * row_h + 110
    body = [
        _svg_text(width / 2, 42, "Prompt-provenance audit axes", size=26, weight=700),
        _svg_text(
            width / 2,
            76,
            "Separate dimensions; no left-to-right or O0–O5 ordinal ranking is implied",
            size=15,
            fill=_PALETTE["muted"],
        ),
    ]
    fills = [_PALETTE["panel"], "#e9f2f5", "#f9eef0", "#fff5e5"]
    for row_index, (label, values) in enumerate(axes):
        y = top + row_index * row_h
        body.append(_svg_text(left - 24, y + 52, label, size=17, weight=700, anchor="end"))
        gap = 12
        cell_w = (width - left - 50 - gap * (len(values) - 1)) / len(values)
        for value_index, value in enumerate(values):
            x = left + value_index * (cell_w + gap)
            body.append(_svg_box(x, y, cell_w, 82, fill=fills[row_index % len(fills)], stroke=_PALETTE["line"], radius=12))
            body.append(_svg_text(x + cell_w / 2, y + 49, value, size=14, weight=600))
    body.append(
        _svg_text(
            width / 2,
            height - 30,
            "Legacy O0–O5 codes are categorical shorthand projected from these fields",
            size=15,
            weight=600,
            fill=_PALETTE["accent2"],
        )
    )
    return _svg_document(width, height, body, alt)


def _heatmap_values(parameters: Mapping[str, Any]) -> tuple[list[str], list[str], list[list[float]]]:
    rows = parameters.get("row_labels")
    columns = parameters.get("column_labels")
    matrix = parameters.get("matrix")
    if not isinstance(rows, list) or not rows or not isinstance(columns, list) or not columns:
        _fail("HEATMAP_PARAMETERS", "heatmap requires non-empty row and column labels")
    if not isinstance(matrix, list) or len(matrix) != len(rows):
        _fail("HEATMAP_PARAMETERS", "heatmap row count does not match labels")
    values: list[list[float]] = []
    for row in matrix:
        if not isinstance(row, list) or len(row) != len(columns):
            _fail("HEATMAP_PARAMETERS", "heatmap column count does not match labels")
        converted = [float(value) for value in row]
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in converted):
            _fail("HEATMAP_PARAMETERS", "heatmap cells must be finite proportions in [0,1]")
        values.append(converted)
    return [str(row) for row in rows], [str(col) for col in columns], values


def _heatmap_display_rows(parameters: Mapping[str, Any], identities: Sequence[str]) -> list[str]:
    """Return publication-facing row labels while retaining stable source identities.

    ``row_labels`` remain the immutable matrix identities used for provenance.
    ``row_display_labels`` are optional reader-facing method or short-title labels.
    """

    display = parameters.get("row_display_labels")
    if display is None:
        return list(identities)
    if not isinstance(display, list) or len(display) != len(identities):
        _fail("HEATMAP_PARAMETERS", "heatmap display-label count does not match row identities")
    labels = [str(value).strip() for value in display]
    if any(not value for value in labels) or len(set(labels)) != len(labels):
        _fail("HEATMAP_PARAMETERS", "heatmap display labels must be non-empty and unique")
    return labels


def _heat_colour(value: float) -> str:
    low = (236, 242, 245)
    high = (31, 111, 139)
    rgb = tuple(round(low[index] + value * (high[index] - low[index])) for index in range(3))
    return "#" + "".join(f"{channel:02x}" for channel in rgb)


def _heatmap_svg(parameters: Mapping[str, Any], alt: str) -> bytes:
    rows, columns, matrix = _heatmap_values(parameters)
    display_rows = _heatmap_display_rows(parameters, rows)
    binary_symbols = parameters.get("binary_symbols") is True
    cell_w, cell_h = 190, 82
    left, top = 300, 120
    width = left + len(columns) * cell_w + 60
    height = top + len(rows) * cell_h + 80
    title = str(parameters.get("title") or "Evidence coverage map")
    body = [_svg_text(width / 2, 42, title, size=24, weight=700)]
    for column_index, column in enumerate(columns):
        body.append(_svg_text(left + column_index * cell_w + cell_w / 2, 92, column, size=14, weight=600))
    for row_index, row in enumerate(display_rows):
        y = top + row_index * cell_h
        body.append(_svg_text(left - 14, y + 42, row, size=14, weight=600, anchor="end"))
        for column_index, value in enumerate(matrix[row_index]):
            x = left + column_index * cell_w
            body.append(_svg_box(x, y, cell_w, cell_h, fill=_heat_colour(value), stroke="#ffffff", radius=0))
            if binary_symbols:
                if value >= 0.5:
                    body.append(
                        _svg_text(
                            x + cell_w / 2,
                            y + 50,
                            "●",
                            size=24,
                            weight=700,
                            fill="#ffffff",
                        )
                    )
            else:
                body.append(_svg_text(x + cell_w / 2, y + 50, f"{value:.2f}", size=16, weight=700,
                                      fill="#ffffff" if value >= 0.55 else _PALETTE["ink"]))
    return _svg_document(width, height, body, alt)


def _original_svg(template: str, parameters: Mapping[str, Any], alt: str) -> bytes:
    if template == "PRISMA_FLOW":
        return _prisma_svg(parameters, alt)
    if template == "HIDDEN_ORACLE_PATHWAY":
        return _pathway_svg(parameters, alt)
    if template == "ORACLE_LADDER":
        return _ladder_svg(parameters, alt)
    if template == "PROVENANCE_AXES":
        return _provenance_axes_svg(parameters, alt)
    if template == "EVIDENCE_HEATMAP":
        return _heatmap_svg(parameters, alt)
    _fail("UNKNOWN_RENDER_TEMPLATE", f"unsupported original template: {template}")


def _original_png(template: str, parameters: Mapping[str, Any], alt: str) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:  # pragma: no cover - dependency failure
        _fail("PILLOW_UNAVAILABLE", str(exc))
    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
        label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
        body_font = ImageFont.truetype("DejaVuSans.ttf", 15)
        value_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
    except Exception as exc:  # pragma: no cover - deployment-specific font failure
        _fail("RENDER_FONT_UNAVAILABLE", str(exc))

    def center_text(draw, box, text, font, *, fill=_PALETTE["ink"]):
        x1, y1, x2, y2 = box
        bbox = draw.multiline_textbbox((0, 0), str(text), font=font, spacing=4, align="center")
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        draw.multiline_text(
            ((x1 + x2 - width) / 2, (y1 + y2 - height) / 2 - bbox[1]),
            str(text),
            font=font,
            fill=fill,
            spacing=4,
            align="center",
        )

    def arrow(draw, start, end, *, colour=_PALETTE["ink"], width=3):
        draw.line((start, end), fill=colour, width=width)
        x2, y2 = end
        if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
            sign = 1 if end[0] >= start[0] else -1
            points = [(x2, y2), (x2 - sign * 10, y2 - 7), (x2 - sign * 10, y2 + 7)]
        else:
            sign = 1 if end[1] >= start[1] else -1
            points = [(x2, y2), (x2 - 7, y2 - sign * 10), (x2 + 7, y2 - sign * 10)]
        draw.polygon(points, fill=colour)

    if template == "PRISMA_FLOW":
        _prisma_svg(parameters, alt)
        extended_names = {
            "reports_sought",
            "reports_not_retrieved",
            "reports_assessed",
            "fulltext_excluded",
        }
        if extended_names <= set(parameters):
            size = (980, 850)
            image = Image.new("RGB", size, _PALETTE["paper"])
            draw = ImageDraw.Draw(image)
            center_text(draw, (0, 12, size[0], 60), "PRISMA evidence-assembly flow", title_font)
            record_excluded = int(parameters["screened"]) - int(parameters["reports_sought"])
            labels = [
                ("Records identified", int(parameters["identified"])),
                ("After duplicate/non-report removal", int(parameters["deduplicated"])),
                ("Records screened", int(parameters["screened"])),
                ("Reports sought for retrieval", int(parameters["reports_sought"])),
                ("Full-text reports assessed", int(parameters["reports_assessed"])),
                ("Studies included", int(parameters["included"])),
            ]
            side_labels = [
                (2, "Records excluded", record_excluded),
                (3, "Reports not retrieved", int(parameters["reports_not_retrieved"])),
                (4, "Full-text reports excluded", int(parameters["fulltext_excluded"])),
            ]
            for index, (label, count) in enumerate(labels):
                y1, y2 = 72 + index * 124, 150 + index * 124
                draw.rounded_rectangle((70, y1, 570, y2), radius=12, fill=_PALETTE["panel"], outline=_PALETTE["line"], width=2)
                center_text(draw, (70, y1 + 8, 570, y2 - 20), label, label_font)
                center_text(draw, (70, y2 - 34, 570, y2), f"n = {count}", body_font, fill=_PALETTE["muted"])
                if index < len(labels) - 1:
                    arrow(draw, (320, y2 + 2), (320, y2 + 40))
            for stage_index, label, count in side_labels:
                y1, y2 = 72 + stage_index * 124, 150 + stage_index * 124
                draw.rounded_rectangle((640, y1, 920, y2), radius=12, fill="#fff4e5", outline=_PALETTE["warm"], width=2)
                center_text(draw, (640, y1 + 8, 920, y2 - 20), label, label_font)
                center_text(draw, (640, y2 - 34, 920, y2), f"n = {count}", body_font)
                arrow(draw, (570, y1 + 39), (640, y1 + 39))
            center_text(draw, (0, 804, size[0], 842), "Counts are derived from the frozen screening manifest", body_font, fill=_PALETTE["muted"])
        else:
            size = (900, 570)
            image = Image.new("RGB", size, _PALETTE["paper"])
            draw = ImageDraw.Draw(image)
            center_text(draw, (0, 12, size[0], 60), "PRISMA flow", title_font)
            labels = [
                ("Records identified", int(parameters["identified"])),
                ("After deduplication", int(parameters["deduplicated"])),
                ("Records screened", int(parameters["screened"])),
                ("Studies included", int(parameters["included"])),
            ]
            for index, (label, count) in enumerate(labels):
                y1, y2 = 72 + index * 120, 148 + index * 120
                draw.rounded_rectangle((230, y1, 670, y2), radius=12, fill=_PALETTE["panel"], outline=_PALETTE["line"], width=2)
                center_text(draw, (230, y1 + 8, 670, y2 - 20), label, label_font)
                center_text(draw, (230, y2 - 34, 670, y2), f"n = {count}", body_font, fill=_PALETTE["muted"])
                if index < len(labels) - 1:
                    arrow(draw, (450, y2 + 2), (450, y2 + 38))
            draw.rounded_rectangle((700, 312, 870, 388), radius=12, fill="#fff4e5", outline=_PALETTE["warm"], width=2)
            center_text(draw, (700, 318, 870, 365), "Excluded", label_font)
            center_text(draw, (700, 350, 870, 386), f'n = {int(parameters["excluded"])}', body_font)
            arrow(draw, (670, 350), (700, 350))
    elif template == "HIDDEN_ORACLE_PATHWAY":
        stages = parameters.get("stages")
        _pathway_svg(parameters, alt)
        size = (1100, 310)
        image = Image.new("RGB", size, _PALETTE["paper"])
        draw = ImageDraw.Draw(image)
        center_text(draw, (0, 12, size[0], 62), "Reference-conditioned information pathway", title_font)
        gap, margin = 24, 40
        box_width = (size[0] - 2 * margin - gap * (len(stages) - 1)) / len(stages)
        for index, stage in enumerate(stages):
            x1 = margin + index * (box_width + gap)
            x2 = x1 + box_width
            oracle = "oracle" in str(stage).lower()
            draw.rounded_rectangle((x1, 105, x2, 197), radius=12, fill="#fbe9ec" if oracle else "#e8f1f5", outline=_PALETTE["accent2"] if oracle else _PALETTE["accent"], width=2)
            words = str(stage).split()
            split = max(1, len(words) // 2)
            center_text(draw, (x1 + 8, 112, x2 - 8, 190), " ".join(words[:split]) + ("\n" + " ".join(words[split:]) if split < len(words) else ""), label_font)
            center_text(draw, (x1, 205, x2, 240), f"P{index + 1}", body_font, fill=_PALETTE["muted"])
            if index < len(stages) - 1:
                arrow(draw, (x2 + 3, 151), (x2 + gap - 3, 151))
        center_text(draw, (0, 260, size[0], 300), "Original synthesis — no third-party figure copied", body_font, fill=_PALETTE["muted"])
    elif template == "ORACLE_LADDER":
        rungs = parameters.get("rungs")
        _ladder_svg(parameters, alt)
        size = (1300, 520)
        image = Image.new("RGB", size, _PALETTE["paper"])
        draw = ImageDraw.Draw(image)
        center_text(draw, (0, 12, size[0], 60), "Oracle ladder", title_font)
        draw.line((250, 455, 365, 90), fill=_PALETTE["ink"], width=8)
        draw.line((650, 455, 535, 90), fill=_PALETTE["ink"], width=8)
        for index, rung in enumerate(rungs):
            fraction = index / max(1, len(rungs) - 1)
            y = 420 - fraction * 285
            left = 262 + fraction * 90
            right = 638 - fraction * 90
            colour = _PALETTE["accent2"] if index == len(rungs) - 1 else _PALETTE["accent"]
            draw.line((left, y, right, y), fill=colour, width=12)
            draw.text((690, y - 10), str(rung), font=body_font, fill=_PALETTE["ink"])
        draw.text((40, 470), "lower oracle access", font=body_font, fill=_PALETTE["muted"])
        center_text(draw, (220, 60, 680, 92), "greater evaluation-only information", body_font, fill=_PALETTE["accent2"])
    elif template == "PROVENANCE_AXES":
        axes = _provenance_axes_values(parameters)
        row_h, left, top = 126, 300, 112
        size = (1700, top + len(axes) * row_h + 110)
        image = Image.new("RGB", size, _PALETTE["paper"])
        draw = ImageDraw.Draw(image)
        center_text(draw, (0, 12, size[0], 60), "Prompt-provenance audit axes", title_font)
        center_text(
            draw,
            (0, 60, size[0], 98),
            "Separate dimensions; no left-to-right or O0–O5 ordinal ranking is implied",
            body_font,
            fill=_PALETTE["muted"],
        )
        fills = [_PALETTE["panel"], "#e9f2f5", "#f9eef0", "#fff5e5"]
        for row_index, (label, values) in enumerate(axes):
            y = top + row_index * row_h
            center_text(draw, (10, y, left - 24, y + 82), label, label_font)
            gap = 12
            cell_w = (size[0] - left - 50 - gap * (len(values) - 1)) / len(values)
            for value_index, value in enumerate(values):
                x = left + value_index * (cell_w + gap)
                draw.rounded_rectangle(
                    (x, y, x + cell_w, y + 82),
                    radius=12,
                    fill=fills[row_index % len(fills)],
                    outline=_PALETTE["line"],
                    width=2,
                )
                center_text(draw, (x + 5, y, x + cell_w - 5, y + 82), value, body_font)
        center_text(
            draw,
            (0, size[1] - 70, size[0], size[1] - 20),
            "Legacy O0–O5 codes are categorical shorthand projected from these fields",
            label_font,
            fill=_PALETTE["accent2"],
        )
    elif template == "EVIDENCE_HEATMAP":
        rows, columns, matrix = _heatmap_values(parameters)
        display_rows = _heatmap_display_rows(parameters, rows)
        binary_symbols = parameters.get("binary_symbols") is True
        cell_w, cell_h, left = 190, 82, 300
        size = (left + len(columns) * cell_w + 60, 120 + len(rows) * cell_h + 80)
        image = Image.new("RGB", size, _PALETTE["paper"])
        draw = ImageDraw.Draw(image)
        center_text(draw, (0, 12, size[0], 60), str(parameters.get("title") or "Evidence coverage map"), title_font)
        for column_index, column in enumerate(columns):
            center_text(draw, (left + column_index * cell_w, 72, left + (column_index + 1) * cell_w, 112), column, body_font)
        for row_index, row in enumerate(display_rows):
            y = 120 + row_index * cell_h
            center_text(draw, (12, y, left - 12, y + cell_h), row, body_font)
            for column_index, value in enumerate(matrix[row_index]):
                x = left + column_index * cell_w
                draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill=_heat_colour(value), outline="#ffffff", width=2)
                if binary_symbols:
                    if value >= 0.5:
                        center_text(draw, (x, y, x + cell_w, y + cell_h), "●", title_font, fill="#ffffff")
                else:
                    center_text(draw, (x, y, x + cell_w, y + cell_h), f"{value:.2f}", value_font, fill="#ffffff" if value >= 0.55 else _PALETTE["ink"])
    else:
        _fail("UNKNOWN_RENDER_TEMPLATE", f"unsupported original template: {template}")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _pdf_excerpt_png(root: Path, asset: Mapping[str, Any]) -> bytes:
    excerpt = asset.get("excerpt")
    if not isinstance(excerpt, Mapping):
        _fail("EXTERNAL_EXCERPT_PROVENANCE", "external excerpt metadata is missing")
    pdf_ref, pdf_path = _safe_path(root, excerpt.get("pdf_ref"), code="SOURCE_PATH_UNSAFE")
    expected = str(excerpt.get("pdf_sha256") or "")
    if not pdf_path.is_file():
        _fail("SOURCE_MISSING", f"excerpt PDF does not exist: {pdf_ref}")
    if _file_hash(pdf_path) != expected:
        _fail("SOURCE_HASH_MISMATCH", f"excerpt PDF hash differs: {pdf_ref}")
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - optional runtime failure
        _fail("PYMUPDF_UNAVAILABLE", str(exc))
    crop = excerpt.get("crop") or {}
    try:
        page_number = int(excerpt.get("page"))
        x = float(crop["x"])
        y = float(crop["y"])
        width = float(crop["width"])
        height = float(crop["height"])
    except (KeyError, TypeError, ValueError):
        _fail("EXTERNAL_EXCERPT_PROVENANCE", "excerpt page/crop is invalid")
    if page_number < 1 or min(x, y) < 0 or min(width, height) <= 0 or crop.get("coordinate_space") != "PDF_POINTS":
        _fail("EXTERNAL_EXCERPT_PROVENANCE", "excerpt crop must be positive PDF points")
    try:
        with fitz.open(str(pdf_path)) as document:
            if page_number > len(document):
                _fail("EXTERNAL_EXCERPT_PROVENANCE", "excerpt page exceeds PDF page count")
            page = document[page_number - 1]
            clip = fitz.Rect(x, y, x + width, y + height)
            if not page.rect.contains(clip):
                _fail("EXTERNAL_EXCERPT_PROVENANCE", "excerpt crop exceeds the PDF page")
            # Crops are commonly expanded to a full manuscript column.  Ten
            # device pixels per PDF point preserves about 300 effective ppi
            # for the observed crop-to-column expansion while staying bounded
            # for the small, permission-cleared excerpt region.
            pixmap = page.get_pixmap(matrix=fitz.Matrix(10.0, 10.0), clip=clip, alpha=False)
            return pixmap.tobytes("png")
    except AssetRenderError:
        raise
    except Exception as exc:
        _fail("PDF_EXCERPT_RENDER_FAILED", str(exc))


def _validate_category(asset: Mapping[str, Any]) -> tuple[str, str]:
    semantic_type = _nonempty(asset.get("semantic_type"), code="ASSET_SEMANTICS", field="semantic_type")
    template = _nonempty(asset.get("template"), code="ASSET_SEMANTICS", field="template")
    if _TEMPLATE_TYPES.get(template) != semantic_type:
        _fail("ASSET_TEMPLATE_MISMATCH", f"{template} does not implement {semantic_type}")
    if semantic_type == "EVIDENCE_TABLE":
        rows = asset.get("evidence_rows")
        if not isinstance(rows, list) or not rows:
            _fail("EVIDENCE_ROW_PROVENANCE", "evidence table has no provenance rows")
        for row in rows:
            if not isinstance(row, Mapping):
                _fail("EVIDENCE_ROW_PROVENANCE", "evidence row is not an object")
            _unique_strings(row.get("study_refs"), code="EVIDENCE_ROW_PROVENANCE", field="study_refs")
            _unique_strings(row.get("extraction_refs"), code="EVIDENCE_ROW_PROVENANCE", field="extraction_refs")
            _nonempty(row.get("row_id"), code="EVIDENCE_ROW_PROVENANCE", field="row_id")
    elif semantic_type == "QUANTITATIVE_PLOT":
        cells = asset.get("numeric_cells")
        if not isinstance(cells, list) or not cells:
            _fail("NUMERIC_PROVENANCE", "quantitative plot has no numeric cells")
        for cell in cells:
            if not isinstance(cell, Mapping):
                _fail("NUMERIC_PROVENANCE", "numeric cell is not an object")
            for field in ("result_ref", "cell_ref", "units"):
                _nonempty(cell.get(field), code="NUMERIC_PROVENANCE", field=field)
            if not isinstance(cell.get("value"), (int, float)) or not math.isfinite(float(cell["value"])):
                _fail("NUMERIC_PROVENANCE", "numeric cell value must be finite")
            uncertainty = cell.get("uncertainty")
            if not isinstance(uncertainty, Mapping):
                _fail("NUMERIC_PROVENANCE", "numeric cell uncertainty is missing")
            for field in ("kind", "units"):
                _nonempty(uncertainty.get(field), code="NUMERIC_PROVENANCE", field=f"uncertainty.{field}")
            if not isinstance(uncertainty.get("value"), (int, float)) or not math.isfinite(float(uncertainty["value"])):
                _fail("NUMERIC_PROVENANCE", "uncertainty value must be finite")
    elif semantic_type == "EXTERNAL_EXCERPT":
        excerpt = asset.get("excerpt")
        if not isinstance(excerpt, Mapping):
            _fail("EXTERNAL_EXCERPT_PROVENANCE", "external excerpt metadata is missing")
        for field in ("pdf_ref", "pdf_sha256", "license_ref", "permission_status"):
            _nonempty(excerpt.get(field), code="EXTERNAL_EXCERPT_PROVENANCE", field=field)
        status = excerpt.get("permission_status")
        if status not in {"PENDING", "RESTRICTED", "CLEARED"}:
            _fail("EXTERNAL_EXCERPT_PROVENANCE", "invalid external permission status")
        if asset.get("release_scope", "PRIVATE") == "PUBLIC" and status != "CLEARED":
            _fail("EXTERNAL_PERMISSION_NOT_CLEARED", "uncleared excerpt cannot enter public output")
        if status == "CLEARED":
            for field in ("permission_receipt_ref", "permission_receipt_sha256"):
                _nonempty(excerpt.get(field), code="EXTERNAL_EXCERPT_PROVENANCE", field=field)
    return semantic_type, template


def _permission(root: Path, asset: Mapping[str, Any], semantic_type: str) -> dict[str, Any]:
    if semantic_type != "EXTERNAL_EXCERPT":
        return {"status": "OWNED", "license_ref": "original-project-render", "public_release_allowed": True}
    excerpt = asset["excerpt"]
    status = str(excerpt["permission_status"])
    out: dict[str, Any] = {
        "status": status,
        "license_ref": str(excerpt["license_ref"]),
        "public_release_allowed": status == "CLEARED",
    }
    if status == "CLEARED":
        ref, path = _safe_path(root, excerpt["permission_receipt_ref"], code="PERMISSION_RECEIPT_UNSAFE")
        expected = str(excerpt["permission_receipt_sha256"])
        if not path.is_file() or _file_hash(path) != expected:
            _fail("PERMISSION_RECEIPT_MISMATCH", f"permission receipt is missing or changed: {ref}")
        out["permission_receipt_ref"] = ref
        out["permission_receipt_sha256"] = expected
    return out


def _normalise_plan(root: Path, plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(plan, Mapping):
        _fail("ASSET_PLAN_INVALID", "asset plan must be an object")
    _nonempty(plan.get("run_id"), code="ASSET_PLAN_INVALID", field="run_id")
    if not _SHA_RE.fullmatch(str(plan.get("manuscript_sha256") or "")):
        _fail("ASSET_PLAN_INVALID", "manuscript_sha256 is invalid")
    assets = plan.get("assets")
    if not isinstance(assets, list) or not assets:
        _fail("ASSET_PLAN_INVALID", "asset plan must contain at least one asset")
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    seen_outputs: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for raw in assets:
        if not isinstance(raw, Mapping):
            _fail("ASSET_PLAN_INVALID", "asset plan row is not an object")
        asset = copy.deepcopy(dict(raw))
        asset_id = _nonempty(asset.get("asset_id"), code="ASSET_PLAN_INVALID", field="asset_id")
        label = _nonempty(asset.get("label"), code="ASSET_PLAN_INVALID", field="label")
        if asset_id in seen_ids:
            _fail("DUPLICATE_ASSET_ID", asset_id)
        if label in seen_labels:
            _fail("DUPLICATE_LABEL", label)
        if not _LABEL_RE.fullmatch(label):
            _fail("LABEL_INVALID", label)
        seen_ids.add(asset_id)
        seen_labels.add(label)
        semantic_type, template = _validate_category(asset)
        if not label.startswith("fig:"):
            _fail("LABEL_TYPE_MISMATCH", f"rendered visual asset label must start with fig: ({label})")
        caption = _nonempty(asset.get("caption"), code="CAPTION_MISSING", field="caption")
        alt = _nonempty(asset.get("accessibility_text"), code="ALT_TEXT_MISSING", field="accessibility_text")
        claim_refs = _unique_strings(asset.get("claim_refs"), code="CLAIM_REFS_MISSING", field="claim_refs")
        sources = asset.get("source_inputs")
        if not isinstance(sources, list) or not sources:
            _fail("SOURCE_PROVENANCE", f"asset has no source inputs: {asset_id}")
        source_inputs = [_verify_source(root, row) for row in sources]
        if len({row["ref"] for row in source_inputs}) != len(source_inputs):
            _fail("SOURCE_PROVENANCE", f"asset has duplicate source inputs: {asset_id}")
        frozen_refs = {row["ref"] for row in source_inputs}
        if semantic_type == "EVIDENCE_TABLE":
            for evidence_row in asset["evidence_rows"]:
                for extraction_ref in evidence_row["extraction_refs"]:
                    frozen_ref = str(extraction_ref).split("#", 1)[0]
                    if frozen_ref not in frozen_refs:
                        _fail(
                            "EVIDENCE_ROW_PROVENANCE",
                            f"extraction ref is not backed by a hashed source: {extraction_ref}",
                        )
        elif semantic_type == "QUANTITATIVE_PLOT":
            for cell in asset["numeric_cells"]:
                if str(cell["result_ref"]) not in frozen_refs:
                    _fail(
                        "NUMERIC_PROVENANCE",
                        f"numeric result ref is not backed by a hashed source: {cell['result_ref']}",
                    )
        elif semantic_type == "EXTERNAL_EXCERPT":
            excerpt = asset["excerpt"]
            if (
                str(excerpt["pdf_ref"]) not in frozen_refs
                or not any(
                    row["ref"] == str(excerpt["pdf_ref"])
                    and row["sha256"] == str(excerpt["pdf_sha256"])
                    for row in source_inputs
                )
            ):
                _fail(
                    "EXTERNAL_EXCERPT_PROVENANCE",
                    "excerpt PDF ref/hash is not closed by source_inputs",
                )
        output_refs = _unique_strings(asset.get("outputs"), code="ASSET_OUTPUTS_INVALID", field="outputs")
        outputs: list[tuple[str, Path, str, str]] = []
        for output_ref in output_refs:
            ref, path = _safe_path(root, output_ref, code="ASSET_OUTPUT_PATH_UNSAFE")
            media = _MEDIA.get(path.suffix.lower())
            if media is None:
                _fail("ASSET_OUTPUTS_INVALID", f"output must be SVG or PNG: {ref}")
            if semantic_type == "EXTERNAL_EXCERPT" and media[0] != "PNG":
                _fail("ASSET_OUTPUTS_INVALID", "PDF excerpts may be rendered only to PNG")
            if ref in seen_outputs:
                _fail("DUPLICATE_OUTPUT", ref)
            if path.exists():
                _fail("OUTPUT_ALREADY_EXISTS", ref)
            seen_outputs.add(ref)
            outputs.append((ref, path, media[0], media[1]))
        parameters = asset.get("parameters") or {}
        if not isinstance(parameters, Mapping):
            _fail("ASSET_PARAMETERS_INVALID", f"parameters are not an object: {asset_id}")
        permission = _permission(root, asset, semantic_type)
        normalised.append({
            "raw": asset,
            "asset_id": asset_id,
            "label": label,
            "semantic_type": semantic_type,
            "template": template,
            "caption": caption,
            "alt": alt,
            "claim_refs": claim_refs,
            "source_inputs": source_inputs,
            "outputs": outputs,
            "parameters": copy.deepcopy(dict(parameters)),
            "permission": permission,
        })
    return normalised


def _render_bytes(root: Path, asset: Mapping[str, Any]) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    for ref, _path, format_name, _media_type in asset["outputs"]:
        if asset["semantic_type"] == "EXTERNAL_EXCERPT":
            body = _pdf_excerpt_png(root, asset["raw"])
        elif format_name == "SVG":
            body = _original_svg(asset["template"], asset["parameters"], asset["alt"])
        else:
            body = _original_png(asset["template"], asset["parameters"], asset["alt"])
        if not body:
            _fail("EMPTY_RENDER", ref)
        rendered[ref] = body
    return rendered


def _manifest_asset(plan_hash: str, run_id: str, renderer_sha: str, asset: Mapping[str, Any],
                    rendered: Mapping[str, bytes]) -> dict[str, Any]:
    outputs = []
    for ref, _path, format_name, media_type in asset["outputs"]:
        body = rendered[ref]
        outputs.append({
            "path": ref,
            "format": format_name,
            "media_type": media_type,
            "sha256": _hash_bytes(body),
            "byte_size": len(body),
            "owner_run_id": run_id,
            "run_owned": True,
            "overwrite_policy": "CREATE_NEW",
        })
    source_set_sha = _hash_value(asset["source_inputs"])
    output_set_sha = _hash_value(outputs)
    receipt = {
        "renderer_ref": RENDERER_REF,
        "renderer_sha256": renderer_sha,
        "shell": False,
        "argv": [
            "python", "-m", "research_agent_teams.tools.review_asset_renderer", "render",
            "--plan-sha256", plan_hash, "--asset-id", asset["asset_id"],
        ],
        "fixed_parameters": copy.deepcopy(asset["parameters"]),
        "parameters_sha256": _hash_value(asset["parameters"]),
        "source_set_sha256": source_set_sha,
        "output_set_sha256": output_set_sha,
    }
    receipt["receipt_sha256"] = _hash_value(receipt)
    record: dict[str, Any] = {
        "asset_id": asset["asset_id"],
        "label": asset["label"],
        "semantic_type": asset["semantic_type"],
        "render_template": asset["template"],
        "caption": {"text": asset["caption"], "owner_role": "review-asset-renderer"},
        "accessibility_text": asset["alt"],
        "claim_refs": asset["claim_refs"],
        "source_inputs": asset["source_inputs"],
        "outputs": outputs,
        "permission": asset["permission"],
        "render_receipt": receipt,
    }
    raw = asset["raw"]
    if asset["semantic_type"] == "EVIDENCE_TABLE":
        record["evidence_rows"] = copy.deepcopy(raw["evidence_rows"])
    elif asset["semantic_type"] == "QUANTITATIVE_PLOT":
        record["numeric_cells"] = copy.deepcopy(raw["numeric_cells"])
    elif asset["semantic_type"] == "EXTERNAL_EXCERPT":
        record["excerpt"] = copy.deepcopy(raw["excerpt"])
    record["asset_record_sha256"] = _hash_value(record)
    return record


def _schema_validate(manifest: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.absolute_path))
    except AssetRenderError:
        raise
    except Exception as exc:
        _fail("ASSET_SCHEMA_UNAVAILABLE", str(exc))
    if errors:
        first = errors[0]
        locus = "/".join(str(part) for part in first.absolute_path) or "<root>"
        _fail("ASSET_SCHEMA_INVALID", f"{locus}: {first.message}")


def _closure(plan: Mapping[str, Any], assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    planned = plan.get("assets") or []
    return {
        "status": "CLOSED",
        "planned_asset_ids": [str(row["asset_id"]) for row in planned],
        "rendered_asset_ids": [str(row["asset_id"]) for row in assets],
        "planned_labels": [str(row["label"]) for row in planned],
        "rendered_labels": [str(row["label"]) for row in assets],
        "planned_output_refs": [str(ref).replace("\\", "/") for row in planned for ref in row["outputs"]],
        "rendered_output_refs": [str(output["path"]) for row in assets for output in row["outputs"]],
    }


def render_asset_manifest(run_dir: str | os.PathLike[str], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Render a frozen asset plan and return its version-2 manifest.

    The caller decides where to persist the returned manifest.  Visible assets
    are ``CREATE_NEW`` only; reruns use a fresh run directory instead of
    overwriting evidence from an earlier attempt.
    """

    root = Path(run_dir).resolve()
    if not root.is_dir():
        _fail("RUN_ROOT_MISSING", str(root))
    normalised = _normalise_plan(root, plan)
    plan_hash = _hash_value(plan)
    renderer_path = Path(__file__).resolve()
    renderer_sha = _file_hash(renderer_path)

    # Prepare every byte before publishing any target.  Category checks,
    # source hashes, permission receipts, and optional PDF parsing all happen
    # in this phase.
    prepared = [(asset, _render_bytes(root, asset)) for asset in normalised]
    manifest_assets = [
        _manifest_asset(plan_hash, str(plan["run_id"]), renderer_sha, asset, rendered)
        for asset, rendered in prepared
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(plan["run_id"]),
        "manuscript_sha256": str(plan["manuscript_sha256"]),
        "asset_plan_sha256": plan_hash,
        "render_environment": _environment(),
        "assets": manifest_assets,
        "plan_closure": _closure(plan, manifest_assets),
    }
    manifest["manifest_sha256"] = _hash_value(manifest)
    _schema_validate(manifest)

    created: list[Path] = []
    try:
        for asset, rendered in prepared:
            for ref, path, _format, _media in asset["outputs"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as handle:
                    handle.write(rendered[ref])
                created.append(path)
        validate_asset_manifest(root, plan, manifest)
    except Exception:
        # Only this invocation's explicit CREATE_NEW targets are removed.  No
        # pre-existing file can enter ``created`` because writes use ``xb``.
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return manifest


def validate_asset_manifest(run_dir: str | os.PathLike[str], plan: Mapping[str, Any],
                            manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate schema, source/output hashes, receipts, and plan closure."""

    root = Path(run_dir).resolve()
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != SCHEMA_VERSION:
        _fail("ASSET_MANIFEST_VERSION", "renderer validation requires version 2.0.0")
    planned = plan.get("assets") if isinstance(plan, Mapping) else None
    rendered = manifest.get("assets")
    if not isinstance(planned, list) or not isinstance(rendered, list):
        _fail("ASSET_PLAN_NOT_CLOSED", "planned/rendered asset lists are missing")
    planned_ids = [row.get("asset_id") for row in planned]
    rendered_ids = [row.get("asset_id") for row in rendered]
    planned_labels = [row.get("label") for row in planned]
    rendered_labels = [row.get("label") for row in rendered]
    planned_outputs = [str(ref).replace("\\", "/") for row in planned for ref in row.get("outputs", [])]
    rendered_outputs = [row.get("path") for asset in rendered for row in asset.get("outputs", [])]
    if planned_ids != rendered_ids or planned_labels != rendered_labels or planned_outputs != rendered_outputs:
        _fail("ASSET_PLAN_NOT_CLOSED", "planned IDs, labels, or outputs differ from rendered manifest")
    expected_closure = _closure(plan, rendered)
    if manifest.get("plan_closure") != expected_closure:
        _fail("ASSET_PLAN_NOT_CLOSED", "closure receipt differs from plan and rendered inventory")
    if manifest.get("asset_plan_sha256") != _hash_value(plan):
        _fail("ASSET_PLAN_HASH_MISMATCH", "asset plan changed after rendering")
    environment = manifest.get("render_environment")
    if not isinstance(environment, Mapping):
        _fail("RENDER_ENVIRONMENT_INVALID", "render environment receipt is missing")
    expected_environment_sha = _hash_value(
        {key: value for key, value in environment.items() if key != "environment_sha256"}
    )
    if environment.get("environment_sha256") != expected_environment_sha:
        _fail("RENDER_ENVIRONMENT_INVALID", "render environment hash is invalid")
    expected_manifest_sha = _hash_value({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected_manifest_sha:
        _fail("MANIFEST_HASH_MISMATCH", "manifest record hash is invalid")

    for plan_asset, asset in zip(planned, rendered):
        if asset.get("caption", {}).get("text") != plan_asset.get("caption"):
            _fail("CAPTION_MISMATCH", str(asset.get("asset_id")))
        if asset.get("accessibility_text") != plan_asset.get("accessibility_text"):
            _fail("ALT_TEXT_MISMATCH", str(asset.get("asset_id")))
        if (
            asset.get("semantic_type") != plan_asset.get("semantic_type")
            or asset.get("render_template") != plan_asset.get("template")
            or asset.get("claim_refs") != plan_asset.get("claim_refs")
        ):
            _fail("ASSET_SEMANTIC_MISMATCH", str(asset.get("asset_id")))
        category_field = {
            "EVIDENCE_TABLE": "evidence_rows",
            "QUANTITATIVE_PLOT": "numeric_cells",
            "EXTERNAL_EXCERPT": "excerpt",
        }.get(str(asset.get("semantic_type")))
        if category_field and asset.get(category_field) != plan_asset.get(category_field):
            _fail("ASSET_SEMANTIC_MISMATCH", f"{asset.get('asset_id')} {category_field}")
        expected_sources = [_verify_source(root, row) for row in plan_asset.get("source_inputs", [])]
        if asset.get("source_inputs") != expected_sources:
            _fail("SOURCE_SET_MISMATCH", str(asset.get("asset_id")))
        expected_record_sha = _hash_value({key: value for key, value in asset.items() if key != "asset_record_sha256"})
        if asset.get("asset_record_sha256") != expected_record_sha:
            _fail("ASSET_RECORD_HASH_MISMATCH", str(asset.get("asset_id")))
        receipt = asset.get("render_receipt") or {}
        expected_receipt_sha = _hash_value({key: value for key, value in receipt.items() if key != "receipt_sha256"})
        if receipt.get("receipt_sha256") != expected_receipt_sha or receipt.get("shell") is not False:
            _fail("RENDER_RECEIPT_INVALID", str(asset.get("asset_id")))
        if (
            receipt.get("renderer_sha256") != _file_hash(Path(__file__).resolve())
            or receipt.get("parameters_sha256") != _hash_value(plan_asset.get("parameters") or {})
            or receipt.get("fixed_parameters") != (plan_asset.get("parameters") or {})
        ):
            _fail("RENDER_RECEIPT_INVALID", f"renderer/parameter binding differs: {asset.get('asset_id')}")
        for output in asset.get("outputs", []):
            ref, path = _safe_path(root, output.get("path"), code="ASSET_OUTPUT_PATH_UNSAFE")
            if not path.is_file():
                _fail("OUTPUT_MISSING", ref)
            if _file_hash(path) != output.get("sha256") or path.stat().st_size != output.get("byte_size"):
                _fail("OUTPUT_HASH_MISMATCH", ref)
        if receipt.get("source_set_sha256") != _hash_value(asset.get("source_inputs")):
            _fail("RENDER_RECEIPT_INVALID", "source-set hash differs")
        if receipt.get("output_set_sha256") != _hash_value(asset.get("outputs")):
            _fail("RENDER_RECEIPT_INVALID", "output-set hash differs")
    _schema_validate(manifest)
    return dict(manifest)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail("JSON_INPUT_INVALID", str(exc))
    if not isinstance(value, dict):
        _fail("JSON_INPUT_INVALID", "top-level JSON must be an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render", help="render a plan into CREATE_NEW assets")
    render.add_argument("--run-dir", required=True)
    render.add_argument("--plan", required=True)
    render.add_argument("--manifest", required=True)
    validate = subparsers.add_parser("validate", help="validate an existing manifest")
    validate.add_argument("--run-dir", required=True)
    validate.add_argument("--plan", required=True)
    validate.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    plan = _load_json(Path(args.plan))
    manifest_path = Path(args.manifest)
    if args.command == "render":
        manifest = render_asset_manifest(run_dir, plan)
        if manifest_path.exists():
            _fail("OUTPUT_ALREADY_EXISTS", str(manifest_path))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    else:
        validate_asset_manifest(run_dir, plan, _load_json(manifest_path))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI smoke is exercised indirectly
    raise SystemExit(main())


__all__ = [
    "AssetRenderError",
    "SCHEMA_VERSION",
    "render_asset_manifest",
    "validate_asset_manifest",
]
