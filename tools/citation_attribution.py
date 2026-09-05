"""Deterministic source-truth gate for claim-level citation attribution.

The semantic auditor may decide whether a quoted locus entails a claim. It may
not attest that a snapshot, hash, offset, or quote is real. Those facts are
recomputed here from a local immutable snapshot inside the run directory.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "citation-attribution/v1"
CLAIM_SPAN_VERSION = "claim-span/v1"
LEGACY_REPLAY_VERSION = "citation-legacy-replay/v1"
LEGACY_REPLAY_REL = Path("inbox/citation-legacy-replay.json")
CITATION_SNAPSHOT_REL = Path("inbox/citation-snapshots/fulltext-contexts.txt")
CITATION_MANIFEST_REL = Path("inbox/citation-snapshots/fulltext-contexts.manifest.json")

_POSITIVE_RELATIONS = {"entails", "partial"}
_NEGATIVE_RELATIONS = {"contradicts", "insufficient"}
_ALL_RELATIONS = _POSITIVE_RELATIONS | _NEGATIVE_RELATIONS
# R3 A1 (2026-08-07): only 'entails' strictly requires supports_claim=true. 'partial' is a
# boundary/qualification, not a refutation — it may legitimately carry supports_claim=false
# (the locus narrows the claim's scope) without that being a locator-gate inconsistency.
_REQUIRES_SUPPORTS_TRUE = {"entails"}
_TEXT_SOURCE_SUFFIXES = {".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml", ".csv"}
_HTML_SOURCE_SUFFIXES = {".html", ".htm"}
_MAX_LOCAL_TEXT_BYTES = 16 * 1024 * 1024


def _rows(value: object) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _claim_ids(claim_list: dict) -> list[str]:
    return [str(row.get("claim_id")) for row in _rows(claim_list.get("claims"))
            if row.get("claim_id")]


def load_explicit_legacy_replay(run_dir: str | Path) -> dict | None:
    """Return a validated legacy-replay declaration, or ``None`` for a current run.

    A historical payload is never inferred from its old shape. Replaying it
    requires a deliberate marker under the run's inbox, and the resulting
    attribution can only be UNVERIFIED.
    """
    path = Path(run_dir) / LEGACY_REPLAY_REL
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid explicit citation legacy replay marker: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("citation legacy replay marker must be a JSON object")
    if payload.get("contract_version") != LEGACY_REPLAY_VERSION:
        raise ValueError(f"citation legacy replay marker must declare {LEGACY_REPLAY_VERSION}")
    if payload.get("legacy_replay") is not True:
        raise ValueError("citation legacy replay marker must set legacy_replay=true")
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 10:
        raise ValueError("citation legacy replay marker requires a specific reason")
    return {
        "contract_version": LEGACY_REPLAY_VERSION,
        "legacy_replay": True,
        "reason": reason,
        "source_run_ref": str(payload.get("source_run_ref") or "").strip(),
        "marker_ref": LEGACY_REPLAY_REL.as_posix(),
    }


class _HTMLBodyText(HTMLParser):
    """Small, deterministic HTML text extractor; scripts and styles never enter evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401 - HTMLParser callback
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:  # noqa: D401 - HTMLParser callback
        if tag.casefold() in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:  # noqa: D401 - HTMLParser callback
        if not self._hidden_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._parts)


def _complete_local_contexts(doc_paths: list[str] | None) -> list[dict]:
    """Extract immutable text from supported local primary-source files.

    PDFs retain page-level PyMuPDF extraction.  Official challenge protocols,
    repositories, and evaluation rules are often primary HTML/Markdown/Python/
    JSON rather than PDFs, so a bounded UTF-8 / HTML-body path is accepted too.
    It never executes source code or JavaScript and records a parser version per
    context for downstream attribution.
    """
    contexts = []
    for raw in doc_paths or []:
        path = Path(raw)
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        if suffix == ".pdf":
            try:
                import fitz
                with fitz.open(str(path)) as document:
                    for page_index, page in enumerate(document, start=1):
                        text = page.get_text("text")
                        if text.strip():
                            contexts.append({
                                "doc_ref": str(path.resolve()),
                                "page": page_index,
                                "excerpt": text,
                                "parser_version": "pymupdf-page-text/v1",
                            })
            except Exception:
                continue
            continue
        if suffix not in _TEXT_SOURCE_SUFFIXES | _HTML_SOURCE_SUFFIXES:
            continue
        try:
            raw_bytes = path.read_bytes()
            if len(raw_bytes) > _MAX_LOCAL_TEXT_BYTES:
                continue
            source_text = raw_bytes.decode("utf-8-sig")
            if suffix in _HTML_SOURCE_SUFFIXES:
                parser = _HTMLBodyText()
                parser.feed(source_text)
                parser.close()
                text = parser.text()
                parser_version = "html-body-text/v1"
            else:
                text = source_text
                parser_version = "utf8-source-text/v1"
            if text.strip():
                contexts.append({
                    "doc_ref": str(path.resolve()),
                    "page": None,
                    "excerpt": text,
                    "parser_version": parser_version,
                })
        except (OSError, UnicodeError):
            continue
    return contexts


def write_fulltext_context_snapshot(
    run_dir: str | Path,
    fulltext_report: dict,
    doc_paths: list[str] | None = None,
) -> dict | None:
    """Materialize a stable UTF-8 char-offset snapshot for exact attribution.

    Local PDFs, official HTML pages, and raw UTF-8 repository/protocol files
    use controlled complete-source extraction. When no readable local source
    exists, the function falls back honestly to retrieval excerpts and marks
    that narrower coverage boundary in the manifest.
    """
    complete_contexts = _complete_local_contexts(doc_paths)
    contexts = complete_contexts or [
        row for row in _rows(fulltext_report.get("contexts"))
        if str(row.get("excerpt") or "")
    ]
    if not contexts:
        return None
    root = Path(run_dir)
    snapshot_path = root / CITATION_SNAPSHOT_REL
    manifest_path = root / CITATION_MANIFEST_REL
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    text = ""
    manifest_rows = []
    for index, context in enumerate(contexts, start=1):
        if text:
            text += "\n\n"
        excerpt = str(context["excerpt"])
        start = len(text)
        text += excerpt
        end = len(text)
        manifest_rows.append({
            "context_ref": f"CTX-{index:04d}",
            "doc_ref": str(context.get("doc_ref") or ""),
            "page": context.get("page"),
            "parser_version": str(context.get("parser_version") or "utf-8-char/v1"),
            "char_start": start,
            "char_end": end,
            "exact_quote": excerpt,
        })
    raw = text.encode("utf-8")
    snapshot_path.write_bytes(raw)
    local_parsers = {str(row.get("parser_version") or "") for row in complete_contexts}
    manifest = {
        "contract_version": "citation-context-snapshot/v1",
        "snapshot_ref": CITATION_SNAPSHOT_REL.as_posix(),
        "document_hash": hashlib.sha256(raw).hexdigest(),
        "parser_version": (
            next(iter(local_parsers)) if len(local_parsers) == 1 else
            "mixed-local-source/v1" if complete_contexts else "utf-8-char/v1"
        ),
        "coverage_boundary": (
            "complete local PDF page-text extraction; visual content remains separately audited"
            if local_parsers == {"pymupdf-page-text/v1"} else
            "complete local source extraction (PDF page text / HTML body / UTF-8 source); visual content remains separately audited"
            if complete_contexts else
            "fulltext-qa excerpts only; not the complete source document"
        ),
        "contexts": manifest_rows,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _fulltext_report_contexts(complete_contexts: list[dict]) -> list[dict]:
    """Make compact QA contexts from the same frozen extract used for attribution.

    ``fulltext_qa`` is intentionally PDF-oriented.  Do not pass Markdown, HTML,
    or source code to its PyMuPDF fallback merely because a mixed source set also
    contains a PDF.  Instead, use the controlled local extractor as the unified
    mixed-source engine and expose short, non-inline contexts for worker QA.
    """
    contexts: list[dict] = []
    for row in complete_contexts:
        excerpt = str(row.get("excerpt") or "").strip()
        doc_ref = str(row.get("doc_ref") or "").strip()
        if not excerpt or not doc_ref:
            continue
        contexts.append({
            "doc_ref": doc_ref,
            "page": row.get("page"),
            "excerpt": excerpt[:500],
            "relevance": None,
        })
    return contexts


def prepare_fulltext_citation_inputs(run_dir: str | Path, question: str,
                                     doc_paths: list[str]) -> str | None:
    """Create the shared report and immutable snapshot using a mixed-source-safe engine.

    A source set may contain PDFs plus official protocol Markdown, task HTML, or
    repository Python.  The old path selected PyMuPDF when *any* PDF was present,
    then passed every source to it; that made an otherwise valid mixed set report
    ``available=false``.  One controlled extractor now produces both the compact
    fulltext-QA contexts and the complete attribution snapshot for every supported
    local source.  It never executes code or scripts.
    """
    if not doc_paths:
        return None
    from . import fulltext_qa

    docs = list(doc_paths)
    complete_contexts = _complete_local_contexts(docs)
    qa_contexts = _fulltext_report_contexts(complete_contexts)
    report = {
        "question": question,
        "available": bool(qa_contexts),
        "reason": "" if qa_contexts else (
            "no supported readable local PDF, HTML, or UTF-8 source yielded a frozen context"
        ),
        "answer_summary": (
            f"Extracted {len(qa_contexts)} compact context(s) from {len(docs)} local source document(s) "
            "using the controlled mixed-source extractor."
            if qa_contexts else ""
        ),
        "contexts": qa_contexts,
        "retraction_flags": fulltext_qa.retraction_check(docs),
    }
    path = Path(run_dir) / "inbox" / "fulltext-qa.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    write_fulltext_context_snapshot(run_dir, report, docs)
    return str(path)


def build_legacy_attribution_report(claim_list: dict, claim_evidence_map: dict,
                                    replay: dict) -> dict:
    """Build a visible, non-passing report for an explicitly requested replay."""
    claim_ids = _claim_ids(claim_list)
    loci = [locus for mapping in _rows(claim_evidence_map.get("mappings"))
            for locus in _rows(mapping.get("loci"))]
    reason = f"explicit legacy replay has no mechanically verified claim-span evidence: {replay['reason']}"
    return {
        "contract_version": CONTRACT_VERSION,
        "verdict": "UNVERIFIED",
        "legacy_replay": True,
        "violations": [],
        "unverified_reasons": [reason],
        "citation_correctness": 0.0,
        "claim_completeness": 0.0,
        "citation_f1": 0.0,
        "n_claims": len(claim_ids),
        "n_loci": len(loci),
        "claim_results": [],
        "mechanical_verification": {
            "n_verified": 0,
            "n_unverified": len(loci),
            "n_blocked": 0,
            "locus_results": [],
        },
        "evidence_ref": [replay["marker_ref"]],
    }


def build_run_attribution_report(run_dir: str | Path, claim_list: dict,
                                 claim_evidence_map: dict,
                                 independent_audit: dict | None, *,
                                 require_complete_claims: bool = False,
                                 coverage_based_absence_claim_ids: set[str] | None = None) -> dict:
    """Apply the explicit replay boundary, then build the appropriate report."""
    replay = load_explicit_legacy_replay(run_dir)
    if replay is not None:
        return build_legacy_attribution_report(claim_list, claim_evidence_map, replay)
    return build_attribution_report(
        claim_list,
        claim_evidence_map,
        independent_audit or {},
        run_dir=run_dir,
        require_complete_claims=require_complete_claims,
        coverage_based_absence_claim_ids=coverage_based_absence_claim_ids,
    )


def _locus_index(claim_evidence_map: dict) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    by_id: dict[str, dict] = {}
    owner: dict[str, str] = {}
    errors: list[str] = []
    for mapping in _rows(claim_evidence_map.get("mappings")):
        claim_id = str(mapping.get("claim_id") or "")
        for locus in _rows(mapping.get("loci")):
            locus_id = str(locus.get("locus_id") or "")
            if not locus_id:
                continue
            if locus_id in by_id:
                errors.append(f"duplicate locus_id {locus_id!r}")
            by_id[locus_id] = locus
            owner[locus_id] = claim_id
    return by_id, owner, errors


def _precise_locator_errors(claim_id: str, locus: dict) -> list[str]:
    locus_id = str(locus.get("locus_id") or "?")
    errors: list[str] = []
    for field in ("span_id", "snapshot_ref", "parser_version", "exact_quote"):
        if not str(locus.get(field) or "").strip():
            errors.append(f"{claim_id}/{locus_id}: strict locus missing {field}")

    relation = str(locus.get("support_relation") or "")
    if relation not in _ALL_RELATIONS:
        errors.append(f"{claim_id}/{locus_id}: support_relation is required")
    elif relation in _REQUIRES_SUPPORTS_TRUE and locus.get("supports_claim") is not True:
        errors.append(f"{claim_id}/{locus_id}: positive support_relation conflicts with supports_claim")
    elif relation in _NEGATIVE_RELATIONS and locus.get("supports_claim") is not False:
        errors.append(f"{claim_id}/{locus_id}: negative support_relation conflicts with supports_claim")

    kind = str(locus.get("kind") or "text")
    char_start, char_end = locus.get("char_start"), locus.get("char_end")
    text_locator = (
        isinstance(char_start, int) and not isinstance(char_start, bool)
        and isinstance(char_end, int) and not isinstance(char_end, bool)
        and 0 <= char_start < char_end
    )
    visual_locator = kind == "figure" and bool(str(locus.get("figure_region_ref") or "").strip())
    table_locator = kind == "table" and bool(str(locus.get("table_cell_ref") or "").strip())
    if not (text_locator or visual_locator or table_locator):
        errors.append(f"{claim_id}/{locus_id}: no exact char span, table cell, or figure region locator")
    if kind == "figure" and not visual_locator:
        errors.append(f"{claim_id}/{locus_id}: figure evidence requires figure_region_ref")
    return errors


def _resolve_snapshot(run_dir: str | Path | None, snapshot_ref: str) -> tuple[Path | None, str | None, bool]:
    """Resolve a snapshot inside the run. Third return value marks a hard policy violation."""
    if run_dir is None:
        return None, "run_dir was not supplied, so the local snapshot cannot be reopened", False
    root = Path(run_dir).resolve()
    raw = Path(snapshot_ref)
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None, f"snapshot_ref escapes the run directory: {snapshot_ref}", True
    if candidate.is_symlink():
        return None, f"snapshot_ref must not be a symlink: {snapshot_ref}", True
    if not resolved.is_file():
        return None, f"local snapshot is unavailable: {snapshot_ref}", False
    return resolved, None, False


def _json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError(f"cannot descend through {type(value).__name__}")
    return value


def _table_cell_value(text: str, locator: str) -> str:
    """Resolve the two machine-readable table locator forms supported by the gate."""
    if locator.startswith("json-pointer:"):
        value = _json_pointer(json.loads(text), locator.removeprefix("json-pointer:"))
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return str(value)
    if locator.startswith("csv:"):
        parts = dict(
            item.split("=", 1) for item in locator.removeprefix("csv:").split(",") if "=" in item
        )
        row = int(parts["r"])
        column = int(parts["c"])
        delimiter = "\t" if parts.get("delimiter") == "tab" else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if row < 1 or column < 1:
            raise ValueError("CSV row and column are 1-based")
        return rows[row - 1][column - 1]
    raise ValueError("table_cell_ref is not machine-readable (use json-pointer: or csv:r=,c=)")


def _verify_figure_region(run_dir: str | Path | None, locator: str) -> tuple[str, str]:
    """Verify that a figure locator names a rendered page the visual manifest actually lists.

    B1 (2026-08-07): the SHA-256 comparison against the manifest's declared image hash was
    torn down (it was a completeness check, not grounding); the asset still has to exist
    inside the run (path safety enforced by _resolve_snapshot) and be listed in the manifest.
    """
    asset_ref, _, fragment = locator.removeprefix("path:").partition("#")
    _asset_path, problem, policy_block = _resolve_snapshot(run_dir, asset_ref)
    if problem:
        return ("BLOCK" if policy_block else "UNVERIFIED"), problem
    manifest_path = Path(run_dir) / "inbox" / "paper-visual-manifest.json"
    if not manifest_path.is_file():
        return "UNVERIFIED", "figure locator has no local paper-visual-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "UNVERIFIED", f"figure manifest cannot be read: {exc}"
    wanted = Path(asset_ref).as_posix().lower()
    matched = None
    for document in _rows(manifest.get("documents")):
        for page in _rows(document.get("pages")):
            if Path(str(page.get("image_ref") or "")).as_posix().lower() == wanted:
                matched = page
                break
        if matched is not None:
            break
    if matched is None:
        return "UNVERIFIED", f"figure asset {asset_ref!r} is absent from the visual manifest"
    if fragment.startswith("xywh="):
        try:
            x, y, width, height = [int(value) for value in fragment.removeprefix("xywh=").split(",")]
            page_width = int(matched.get("width") or 0)
            page_height = int(matched.get("height") or 0)
        except (TypeError, ValueError):
            return "BLOCK", "figure xywh region is malformed"
        if min(x, y, width, height) < 0 or width == 0 or height == 0:
            return "BLOCK", "figure xywh region must have non-negative origin and positive size"
        if page_width and page_height and (x + width > page_width or y + height > page_height):
            return "BLOCK", "figure xywh region exceeds the rendered page bounds"
    return "PASS", "figure asset is listed in the visual manifest and the optional region is well-formed"


def _mechanically_verify_locus(claim_id: str, locus: dict,
                               run_dir: str | Path | None,
                               snapshot_cache: dict[str, tuple[Path | None, bytes | None, str | None, str | None, bool]] | None = None) -> dict:
    locus_id = str(locus.get("locus_id") or "?")
    snapshot_ref = str(locus.get("snapshot_ref") or "")
    result = {
        "claim_id": claim_id,
        "locus_id": locus_id,
        "verdict": "UNVERIFIED",
        "snapshot_ref": snapshot_ref,
        "hash_verified": False,
        "locator_verified": False,
        "quote_verified": False,
        "details": [],
    }
    cache = snapshot_cache if snapshot_cache is not None else {}
    cached = cache.get(snapshot_ref)
    if cached is None:
        path, problem, policy_block = _resolve_snapshot(run_dir, snapshot_ref)
        raw: bytes | None = None
        actual_hash: str | None = None
        if not problem:
            try:
                raw = path.read_bytes()
                actual_hash = hashlib.sha256(raw).hexdigest()
            except OSError as exc:
                problem = f"snapshot could not be read: {exc}"
        cached = (path, raw, actual_hash, problem, policy_block)
        cache[snapshot_ref] = cached
    path, raw, actual_hash, problem, policy_block = cached
    if problem:
        result["verdict"] = "BLOCK" if policy_block else "UNVERIFIED"
        result["details"].append(problem)
        return result

    declared_hash = str(locus.get("document_hash") or "").lower()
    if declared_hash != actual_hash:
        result["verdict"] = "BLOCK"
        result["details"].append("document_hash does not match the frozen source snapshot bytes")
        return result
    result["hash_verified"] = True

    try:
        text = (raw or b"").decode("utf-8")
    except UnicodeDecodeError:
        result["details"].append(
            "snapshot is not UTF-8 text; exact_quote cannot be mechanically checked from this snapshot"
        )
        return result

    exact_quote = str(locus.get("exact_quote") or "")
    start, end = locus.get("char_start"), locus.get("char_end")
    has_char_span = (
        isinstance(start, int) and not isinstance(start, bool)
        and isinstance(end, int) and not isinstance(end, bool)
        and 0 <= start < end
    )
    if has_char_span:
        if end > len(text):
            result["verdict"] = "BLOCK"
            result["details"].append(
                f"char span [{start}, {end}) exceeds snapshot length {len(text)}"
            )
            return result
        observed = text[start:end]
        result["locator_verified"] = True
    elif str(locus.get("kind") or "text") == "table" and locus.get("table_cell_ref"):
        try:
            observed = _table_cell_value(text, str(locus["table_cell_ref"]))
            result["locator_verified"] = True
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result["details"].append(f"table cell locator could not be mechanically resolved: {exc}")
            return result
    else:
        result["details"].append(
            "locator has no mechanically sliceable char span or supported table-cell reference"
        )
        return result

    if observed != exact_quote:
        result["verdict"] = "BLOCK"
        result["details"].append(
            f"exact_quote mismatch at the declared locator: observed {observed!r}, declared {exact_quote!r}"
        )
        return result
    result["quote_verified"] = True
    if str(locus.get("kind") or "text") == "figure":
        figure_status, figure_detail = _verify_figure_region(
            run_dir, str(locus.get("figure_region_ref") or ""))
        result["details"].append(figure_detail)
        if figure_status != "PASS":
            result["verdict"] = figure_status
            return result
    result["verdict"] = "PASS"
    result["details"].append("snapshot was reopened and the locator plus exact quote were recomputed")
    return result


def build_attribution_report(claim_list: dict, claim_evidence_map: dict,
                             independent_audit: dict, *,
                             run_dir: str | Path | None = None,
                             require_complete_claims: bool = False,
                             coverage_based_absence_claim_ids: set[str] | None = None) -> dict:
    """Recompute source identity, locators, quotes, coverage, and the aggregate verdict."""
    errors: list[str] = []
    unverified: list[str] = []
    coverage_absence_ids = set(coverage_based_absence_claim_ids or set())
    coverage_absence_seen: set[str] = set()
    claim_ids = _claim_ids(claim_list)
    claim_id_set = set(claim_ids)
    if not claim_ids:
        errors.append("strict citation attribution requires at least one claim")
    if len(claim_ids) != len(claim_id_set):
        errors.append("claim_list contains duplicate claim_id values")
    if claim_evidence_map.get("attribution_contract_version") != CLAIM_SPAN_VERSION:
        errors.append(f"claim_evidence_map must declare {CLAIM_SPAN_VERSION}")
    if independent_audit.get("contract_version") != CONTRACT_VERSION:
        errors.append(f"independent audit must declare {CONTRACT_VERSION}")
    if independent_audit.get("independent_of_linker") is not True:
        errors.append("citation auditor must attest independent_of_linker=true")

    locus_by_id, locus_owner, locus_index_errors = _locus_index(claim_evidence_map)
    errors.extend(locus_index_errors)
    mapped_claims: set[str] = set()
    mechanical_results: list[dict] = []
    mechanical_by_id: dict[str, dict] = {}
    snapshot_cache: dict[str, tuple[Path | None, bytes | None, str | None, str | None, bool]] = {}
    for mapping in _rows(claim_evidence_map.get("mappings")):
        claim_id = str(mapping.get("claim_id") or "")
        if claim_id not in claim_id_set:
            errors.append(f"claim map names unknown claim {claim_id!r}")
            continue
        if claim_id in mapped_claims:
            errors.append(f"claim map contains duplicate mapping for {claim_id}")
        mapped_claims.add(claim_id)
        loci = _rows(mapping.get("loci"))
        if not loci:
            errors.append(f"{claim_id}: strict claim mapping has no loci")
        for locus in loci:
            errors.extend(_precise_locator_errors(claim_id, locus))
            mechanical = _mechanically_verify_locus(claim_id, locus, run_dir, snapshot_cache)
            mechanical_results.append(mechanical)
            locus_id = str(locus.get("locus_id") or "")
            if locus_id:
                mechanical_by_id[locus_id] = mechanical
            if mechanical["verdict"] == "BLOCK":
                errors.extend(f"{claim_id}/{locus_id}: {row}" for row in mechanical["details"])
            elif mechanical["verdict"] == "UNVERIFIED":
                unverified.extend(f"{claim_id}/{locus_id}: {row}" for row in mechanical["details"])
    for claim_id in sorted(claim_id_set - mapped_claims):
        errors.append(f"{claim_id}: missing from strict claim-evidence map")

    audit_rows = _rows(independent_audit.get("claim_results"))
    audit_by_claim: dict[str, dict] = {}
    for row in audit_rows:
        claim_id = str(row.get("claim_id") or "")
        if claim_id in audit_by_claim:
            errors.append(f"{claim_id}: duplicate independent audit result")
        audit_by_claim[claim_id] = row
        if claim_id not in claim_id_set:
            errors.append(f"independent audit names unknown claim {claim_id!r}")

    verified_edges = 0
    audited_edges = 0
    fully_supported_claims = 0
    results: list[dict] = []
    for claim_id in claim_ids:
        row = audit_by_claim.get(claim_id)
        if row is None:
            errors.append(f"{claim_id}: independent citation audit missing")
            continue
        verdict = str(row.get("verdict") or "")
        if verdict not in _ALL_RELATIONS:
            errors.append(f"{claim_id}: invalid independent verdict {verdict!r}")
        if row.get("locator_verified") is not True:
            errors.append(f"{claim_id}: independent auditor did not verify the locator")

        verified_ids = [str(x) for x in (row.get("verified_locus_ids") or []) if str(x)]
        unsupported_ids = [str(x) for x in (row.get("unsupported_locus_ids") or []) if str(x)]
        if len(verified_ids) != len(set(verified_ids)) or len(unsupported_ids) != len(set(unsupported_ids)):
            errors.append(f"{claim_id}: duplicate locus id in independent audit")
        for locus_id in verified_ids + unsupported_ids:
            if locus_id not in locus_by_id:
                errors.append(f"{claim_id}: audit references unknown locus {locus_id!r}")
            elif locus_owner.get(locus_id) != claim_id:
                errors.append(f"{claim_id}: audit locus {locus_id!r} belongs to another claim")
            mechanical = mechanical_by_id.get(locus_id)
            if mechanical and mechanical["verdict"] != "PASS":
                message = f"{claim_id}: auditor classified locus {locus_id!r} without mechanical verification"
                if mechanical["verdict"] == "BLOCK":
                    errors.append(message)
                else:
                    unverified.append(message)
        if set(verified_ids) & set(unsupported_ids):
            errors.append(f"{claim_id}: locus cannot be both verified and unsupported")
        mapped_ids = {lid for lid, owner in locus_owner.items() if owner == claim_id}
        omitted = mapped_ids - set(verified_ids) - set(unsupported_ids)
        if omitted:
            errors.append(f"{claim_id}: independent audit omitted loci {sorted(omitted)}")
        audited_edges += len(verified_ids) + len(unsupported_ids)
        verified_edges += sum(
            mechanical_by_id.get(locus_id, {}).get("verdict") == "PASS"
            for locus_id in verified_ids
        )

        mechanical_claim_ok = bool(mapped_ids) and all(
            mechanical_by_id.get(lid, {}).get("verdict") == "PASS" for lid in mapped_ids
        )

        mapping = next(
            (m for m in _rows(claim_evidence_map.get("mappings"))
             if str(m.get("claim_id") or "") == claim_id),
            {},
        )
        if verdict == "entails":
            if not verified_ids:
                errors.append(f"{claim_id}: entails verdict has no verified locus")
            if mechanical_claim_ok:
                fully_supported_claims += 1
        elif verdict == "partial" and mapping.get("overall_support") == "supported":
            errors.append(
                f"{claim_id}: independent auditor found partial support only; "
                "a core paper claim requires complete entailment"
            )
        elif verdict in _NEGATIVE_RELATIONS:
            if (verdict == "insufficient" and claim_id in coverage_absence_ids
                    and mapping.get("overall_support") == "not-found"):
                coverage_absence_seen.add(claim_id)
            else:
                errors.append(f"{claim_id}: independent auditor verdict is {verdict}")
        results.append({
            "claim_id": claim_id,
            "verdict": verdict,
            "locator_verified": mechanical_claim_ok,
            "verified_locus_ids": verified_ids,
            "unsupported_locus_ids": unsupported_ids,
            "notes": str(row.get("notes") or ""),
        })

    precision = verified_edges / audited_edges if audited_edges else 0.0
    completeness = fully_supported_claims / len(claim_ids) if claim_ids else 0.0
    f1 = 2 * precision * completeness / (precision + completeness) if precision + completeness else 0.0
    verdict = "BLOCK" if errors else ("UNVERIFIED" if unverified else (
        "PASS_WITH_CAVEATS"
        if require_complete_claims and claim_ids and (
            fully_supported_claims != len(claim_ids) or coverage_absence_seen
        )
        else "PASS"
    ))
    return {
        "contract_version": CONTRACT_VERSION,
        "verdict": verdict,
        "legacy_replay": False,
        "violations": errors,
        "unverified_reasons": sorted(set(unverified)),
        "citation_correctness": round(precision, 4),
        "claim_completeness": round(completeness, 4),
        "citation_f1": round(f1, 4),
        "n_claims": len(claim_ids),
        "n_loci": len(locus_by_id),
        "claim_results": results,
        "mechanical_verification": {
            "n_verified": sum(row["verdict"] == "PASS" for row in mechanical_results),
            "n_unverified": sum(row["verdict"] == "UNVERIFIED" for row in mechanical_results),
            "n_blocked": sum(row["verdict"] == "BLOCK" for row in mechanical_results),
            "locus_results": mechanical_results,
        },
        "evidence_ref": [
            "evidence/DISCOVER/claim-list.artifact.json",
            "evidence/DISCOVER/claim-evidence-map.artifact.json",
            "inbox/DISCOVER.citation-coverage-auditor.bundle.json",
        ],
    }
