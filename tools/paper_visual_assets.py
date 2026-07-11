"""Render and verify page images used by the deep paper-reading panel.

The text extractor and the visual reader have different evidence contracts.  A
page number in extracted text does not prove that a worker inspected a plot or
table.  This module therefore creates immutable page renders under run scratch
and records hashes that ``read_paper_deep`` can verify before accepting a
visual-reading claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


MANIFEST_REL = Path("inbox") / "paper-visual-manifest.json"
VISUALS_REL = Path("inbox") / "paper-visuals"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_to_run(path: Path, run_dir: Path) -> str:
    return path.resolve().relative_to(run_dir.resolve()).as_posix()


def render_pdf_pages(run_dir: str | Path, doc_paths: Iterable[str], *, scale: float = 1.5) -> dict:
    """Render every local PDF page and return a hash-addressed visual manifest.

    Rendering every page is deliberate: the structure mapper has not yet
    identified load-bearing figures when ``fulltext-pre`` runs.  The later
    workers may select relevant pages, but they cannot manufacture a render.
    """
    run_root = Path(run_dir)
    pdfs = [Path(raw) for raw in doc_paths if Path(raw).is_file() and Path(raw).suffix.lower() == ".pdf"]
    base = {
        "manifest_version": "1.0.0",
        "status": "UNAVAILABLE",
        "render_engine": "PyMuPDF",
        "render_scale": scale,
        "documents": [],
        "errors": [],
    }
    if not pdfs:
        base["errors"].append("no local PDF was supplied; visual inspection is unavailable")
        return base

    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover - depends on optional local runtime
        base["errors"].append(f"PyMuPDF unavailable: {exc}")
        return base

    visuals_root = run_root / VISUALS_REL
    visuals_root.mkdir(parents=True, exist_ok=True)
    for doc_index, pdf in enumerate(pdfs, start=1):
        doc_record = {
            "doc_ref": str(pdf.resolve()),
            "document_sha256": file_sha256(pdf),
            "pages": [],
        }
        doc_dir = visuals_root / f"doc-{doc_index:02d}"
        doc_dir.mkdir(parents=True, exist_ok=True)
        try:
            with fitz.open(str(pdf)) as document:
                for page_index, page in enumerate(document, start=1):
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    image_path = doc_dir / f"page-{page_index:04d}.png"
                    pixmap.save(str(image_path))
                    doc_record["pages"].append({
                        "page": page_index,
                        "image_ref": _relative_to_run(image_path, run_root),
                        "image_sha256": file_sha256(image_path),
                        "width": int(pixmap.width),
                        "height": int(pixmap.height),
                    })
        except Exception as exc:  # honest degradation, including malformed PDFs
            base["errors"].append(f"render failed for {pdf}: {exc}")
        base["documents"].append(doc_record)

    if any(doc.get("pages") for doc in base["documents"]):
        base["status"] = "AVAILABLE"
    elif not base["errors"]:
        base["errors"].append("PDFs contained no renderable pages")
    return base


def write_visual_manifest(run_dir: str | Path, doc_paths: Iterable[str]) -> str:
    run_root = Path(run_dir)
    manifest = render_pdf_pages(run_root, doc_paths)
    out = run_root / MANIFEST_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)


def load_visual_manifest(run_dir: str | Path) -> dict:
    path = Path(run_dir) / MANIFEST_REL
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def manifest_page_index(manifest: dict) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    for document in manifest.get("documents") or []:
        for page in document.get("pages") or []:
            ref = str(page.get("image_ref") or "").replace("\\", "/")
            number = page.get("page")
            if ref and isinstance(number, int):
                out[(ref, number)] = page
    return out


def verify_visual_asset(run_dir: str | Path, image_ref: str, page: int, expected_sha256: str) -> list[str]:
    """Verify path fencing, existence, manifest membership, page, and content hash."""
    run_root = Path(run_dir).resolve()
    candidate = (run_root / str(image_ref)).resolve()
    errors: list[str] = []
    try:
        candidate.relative_to(run_root)
    except ValueError:
        return [f"visual asset escapes run scratch: {image_ref}"]
    if not candidate.is_file():
        return [f"visual asset does not exist: {image_ref}"]

    manifest = load_visual_manifest(run_root)
    record = manifest_page_index(manifest).get((str(image_ref).replace("\\", "/"), page))
    if record is None:
        errors.append(f"visual asset/page is absent from manifest: {image_ref} page={page}")
        return errors
    actual = file_sha256(candidate)
    manifest_hash = str(record.get("image_sha256") or "")
    if not expected_sha256 or actual != expected_sha256:
        errors.append(f"visual asset hash mismatch for {image_ref}")
    if actual != manifest_hash:
        errors.append(f"visual manifest hash mismatch for {image_ref}")
    return errors
