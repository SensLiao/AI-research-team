"""Director-reviewed final Markdown admission for the System-M -> System-D seam.

This is deliberately a sibling of the frozen-result promoter, not a relaxation of it.
Result promotion still requires leakage/fairness/reviewer audits and derives
``result-status: frozen`` / ``can-cite-thesis: true``.  This module admits a
human-approved readable document (paper card, synthesis, or idea card) with a
SHA-verified source copy, explicit epistemic labels, and no result-shaped
frontmatter whatsoever.

The director authorizes the exact admission either by explicitly invoking the
top-level ``/promote-to-vault`` source command, or (for unattended/local CLI
workflows) with ``RAT_DOCUMENT_ADMISSION_AUTHORIZED=<admission-id>``.  Worker
agents, scheduled jobs, and ordinary research modes never receive the
director-command capability.  The source Markdown is copied in full into the
vault so the scratch run can later be deleted without breaking the research
record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from research_agent_teams.tools.ledger import append_event
from research_agent_teams.tools.projects import REGISTRY_REL, has_registry, load_registered_projects
from research_agent_teams.tools.validate_artifact import validate_payload
from research_agent_teams.tools import vault_page_contract as vpc


_SAFE_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_TYPES = {
    "paper": "papers",
    "synthesis": "syntheses",
    "idea": "ideas",
    "source": "sources",
    "method": "methods",
    "model": "models",
    "dataset": "datasets",
    "protocol": "protocols",
    "experiment": "experiments",
}
_ALLOWED_STATUSES = {"draft", "active", "parked", "deprecated"}
_ALLOWED_CONFIDENCE = {"high", "medium", "low", "unverified"}
_ALLOWED_EVIDENCE = {
    "PAPER-CITE", "VAULT-CITE", "ASSUMPTION", "DECISION-CITE", "MEETING-CITE", "DATA-CITE",
    "EXP-RESULT",
}
_TYPE_METADATA = {
    "paper": {
        "required": {"authors", "year", "venue", "reading-status", "relevance"},
        "allowed": {
            "authors", "year", "venue", "doi", "url", "reading-status", "relevance", "paper-type",
            "read-purpose", "reading-objective", "key-claims", "serves-claim",
        },
    },
    "synthesis": {
        "required": {"covers"},
        "allowed": {"covers", "for-chapter", "claim-chain", "required-evidence-status"},
    },
    "idea": {
        "required": {"idea-status", "rationale"},
        "allowed": {"idea-status", "rationale", "evidence-for", "evidence-against", "blockers", "decided-by"},
    },
    "source": {
        "required": {"source-type", "maintained-by"},
        "allowed": {"source-type", "maintained-by", "canonical"},
    },
    "method": {
        "required": {"category"},
        "allowed": {"category", "first-seen", "applied-in", "mathematical-form"},
    },
    "model": {
        "required": {"family", "native-dim"},
        "allowed": {
            "family", "native-dim", "params", "prompt-modes", "training-data", "license",
            "official-repo", "paper",
        },
    },
    "dataset": {
        "required": {"size", "modality"},
        "allowed": {
            "size", "modality", "classes", "split-policy", "preprocessing", "source-url",
            "license", "local-path", "version", "data-hash",
        },
    },
    "protocol": {
        # A current protocol has no successor yet.  ``superseded-by`` becomes
        # meaningful only when the page is later deprecated, so requiring it
        # at first admission makes every active protocol invalid by design.
        "required": {"protocol-type", "protocol-version", "applies-to"},
        "allowed": {"protocol-type", "protocol-version", "applies-to", "superseded-by", "rationale-doc"},
    },
    "experiment": {
        "required": {"experiment-id", "model", "dataset", "protocol", "serves-rq", "serves-contrib"},
        "allowed": {
            "experiment-id", "model", "dataset", "protocol", "serves-rq", "serves-contrib",
            "expected-outputs", "stop-conditions", "runs", "result-pages",
        },
    },
}


@dataclass(frozen=True)
class PreparedDocument:
    candidate: dict
    candidate_path: Path
    candidate_sha: str
    source_path: Path
    source_sha: str
    page_path: Path
    page: str


@dataclass(frozen=True)
class PreparedCanonicalRedirect:
    """An existing canonical source page rendered into a historical pointer."""

    replacement_slug: str
    target_slug: str
    target_path: Path
    page: str


@dataclass(frozen=True)
class PreparedSupersession:
    """An existing same-project page retained as a deprecated historical pointer."""

    replacement_slug: str
    target_type: str
    target_slug: str
    target_path: Path
    page: str


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _within(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def document_admission_is_authorized(admission_id: str, *, explicit_director_command: bool = False) -> bool:
    """Accept an explicit director command or the legacy exact environment authorization.

    ``explicit_director_command`` is passed only by the primary source-command
    handler after a top-level user explicitly invokes `/promote-to-vault`.
    It is intentionally unavailable to research workers and mode recipes.  A
    document admission still cannot create a frozen result or thesis-citable
    metric page.
    """
    return bool(admission_id) and (
        bool(explicit_director_command)
        or os.environ.get("RAT_DOCUMENT_ADMISSION_AUTHORIZED", "") == admission_id
    )


def _yaml_value(value) -> str:
    """Render a small JSON subset which is also valid YAML, preventing FM injection."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _strip_frontmatter(source: str) -> str:
    """Remove a top-level YAML block and normalize line endings for stable rendering.

    Source Markdown can come from Windows workers (CRLF) while the admission page is
    assembled with ``"\n".join``.  Normalize before assembly so TextIO on Windows
    cannot turn an embedded CRLF into ``CRCRLF`` (visually a blank line after every
    source line).  This changes no Markdown content; it gives the Vault one canonical
    newline representation.
    """
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    if not source.startswith("---"):
        return source.strip()
    lines = source.splitlines()
    if not lines or lines[0].strip() != "---":
        return source.strip()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return source.strip()


def _candidate_ref(candidate: dict, candidate_path: Path, candidate_sha: str) -> dict:
    return {"path": str(candidate_path).replace("\\", "/"), "sha256": candidate_sha}


def _record(candidate: dict, *, candidate_path: Path, candidate_sha: str, source_ref: dict,
            admissible: bool, reasons: Sequence[str], decided_by: str, decided_at: str,
            vault_path: Optional[Path] = None, vault_slug: Optional[str] = None,
            canonical_redirects: Sequence[str] = (), superseded_pages: Sequence[str] = (),
            authorization_basis: Optional[str] = None) -> dict:
    record = {
        "admission_id": candidate.get("admission_id", "missing-admission-id"),
        "candidate_ref": _candidate_ref(candidate, candidate_path, candidate_sha),
        "source_ref": source_ref,
        "document_type": candidate.get("vault_type", "synthesis"),
        "admissible": admissible,
        "reasons": list(reasons) or ["rejected: missing decision trace"],
        "vault_path": str(vault_path) if vault_path else None,
        "vault_slug": vault_slug,
        "canonical_redirects": list(canonical_redirects),
        "superseded_pages": list(superseded_pages),
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    if authorization_basis:
        record["authorization_basis"] = authorization_basis
    return record


def _source_path(candidate: dict, workspace_root: Path) -> Tuple[Optional[Path], List[str]]:
    """Resolve and SHA-check the source, fenced to this project's durable/run areas."""
    errors: List[str] = []
    ref = candidate.get("source_ref") or {}
    raw_path = ref.get("path", "")
    if not isinstance(raw_path, str) or not raw_path:
        return None, ["source_ref.path missing"]
    rel = Path(raw_path)
    if rel.is_absolute():
        return None, ["source_ref.path must be workspace-relative, never absolute"]
    path = (workspace_root / rel).resolve()
    if not _within(path, workspace_root):
        return None, ["source_ref.path escapes workspace"]
    try:
        relative = path.relative_to(workspace_root.resolve())
    except ValueError:  # defence in depth for exotic Windows path handling
        return None, ["source_ref.path escapes workspace"]
    parts = relative.parts
    project = candidate.get("project", "")
    permitted = (
        len(parts) >= 4 and parts[0:3] == ("research_agent_teams", "runs", project)
    ) or (
        len(parts) >= 4 and parts[0:3] == ("research_agent_teams", "projects", project)
    )
    if not permitted:
        return None, ["source_ref.path is outside this project's runs/workspace"]
    if "inbox" in parts:
        return None, ["source_ref.path points at an inbox artifact, not a director-readable final Markdown"]
    if path.suffix.lower() != ".md":
        return None, ["source_ref.path is not a Markdown file"]
    if not path.exists() or not path.is_file():
        return None, ["source_ref.path not found"]
    raw = path.read_bytes()
    want = ref.get("sha256", "")
    got = _sha256_bytes(raw)
    if got != want:
        errors.append("source_ref.sha256 mismatch (stale or forged source)")
    return path, errors


def _metadata_errors(vault_type: str, metadata: object) -> List[str]:
    if vault_type not in _TYPE_METADATA:
        return [f"unsupported document vault_type {vault_type!r}"]
    if not isinstance(metadata, dict):
        return ["metadata must be an object"]
    spec = _TYPE_METADATA[vault_type]
    errors: List[str] = []
    unknown = sorted(set(metadata) - spec["allowed"])
    missing = sorted(k for k in spec["required"] if metadata.get(k) in (None, "", []))
    if unknown:
        errors.append(f"metadata contains unsupported {vault_type} fields: {unknown}")
    if missing:
        errors.append(f"metadata missing required {vault_type} fields: {missing}")
    if vault_type == "paper":
        if not isinstance(metadata.get("authors"), list) or not metadata.get("authors"):
            errors.append("paper metadata.authors must be a non-empty list")
        if not isinstance(metadata.get("year"), int) or metadata.get("year", 0) < 1900:
            errors.append("paper metadata.year must be a plausible integer")
        if metadata.get("reading-status") not in {"to-read", "skimmed", "read", "deep-read", "cited", "deprecated"}:
            errors.append("paper metadata.reading-status is invalid")
        if metadata.get("relevance") not in {"direct", "adjacent", "background"}:
            errors.append("paper metadata.relevance is invalid")
    if vault_type == "synthesis":
        covers = metadata.get("covers")
        if not isinstance(covers, list) or not covers or not all(
            isinstance(x, str) and x.startswith("[[") and x.endswith("]]" ) for x in covers
        ):
            errors.append("synthesis metadata.covers must be a non-empty list of [[wikilinks]]")
    if vault_type == "idea":
        if metadata.get("idea-status") not in {"preset", "in-consideration", "greenlit", "shipped", "parked"}:
            errors.append("idea metadata.idea-status is invalid")
    return errors


def _candidate_errors(candidate: dict, *, vault_root: Path) -> List[str]:
    errors = list(validate_payload("document_promotion_candidate", candidate))
    vault_type = candidate.get("vault_type")
    if vault_type not in _ALLOWED_TYPES:
        errors.append(f"unsupported vault_type {vault_type!r}")
    for field in ("admission_id", "slug", "project"):
        if not _SAFE_SLUG.fullmatch(str(candidate.get(field, ""))):
            errors.append(f"{field} must be a safe lowercase-kebab identifier")
    if candidate.get("status") not in _ALLOWED_STATUSES:
        errors.append("unregistered document status")
    if candidate.get("confidence") not in _ALLOWED_CONFIDENCE:
        errors.append("invalid confidence")
    if candidate.get("evidence_class") not in _ALLOWED_EVIDENCE:
        errors.append("invalid evidence class")
    errors.extend(_metadata_errors(str(vault_type), candidate.get("metadata")))
    redirects = candidate.get("canonical_redirects", [])
    if redirects:
        if vault_type != "synthesis":
            errors.append("canonical_redirects are allowed only on a synthesis current-route page")
        if candidate.get("status") != "active":
            errors.append("a synthesis with canonical_redirects must have active status")
        if not isinstance(redirects, list) or any(not _SAFE_SLUG.fullmatch(str(slug)) for slug in redirects):
            errors.append("canonical_redirects must be a list of safe existing page slugs")
    supersessions = candidate.get("supersede_pages", [])
    if supersessions:
        if vault_type != "synthesis":
            errors.append("supersede_pages are allowed only on an active current-route synthesis")
        if candidate.get("status") != "active":
            errors.append("a synthesis with supersede_pages must have active status")
        if not isinstance(supersessions, list):
            errors.append("supersede_pages must be a list")
        else:
            seen_targets: set[tuple[str, str]] = set()
            for row in supersessions:
                if not isinstance(row, dict):
                    errors.append("every supersede_pages entry must be an object")
                    continue
                target_type = str(row.get("vault_type", ""))
                target_slug = str(row.get("slug", ""))
                if target_type not in _ALLOWED_TYPES or not _SAFE_SLUG.fullmatch(target_slug):
                    errors.append("supersede_pages entries require a supported vault_type and safe slug")
                    continue
                key = (target_type, target_slug)
                if key in seen_targets:
                    errors.append(f"duplicate supersede_pages target: {target_type}/{target_slug}")
                seen_targets.add(key)
                if target_type == vault_type and target_slug == candidate.get("slug"):
                    errors.append("a document cannot supersede itself")
    if has_registry(vault_root):
        projects = load_registered_projects(vault_root)
        if candidate.get("project") not in projects:
            errors.append(
                f"project {candidate.get('project')!r} is not registered in {REGISTRY_REL}"
            )
    return errors


def _render_page(candidate: dict, *, source_text: str, source_sha: str, created: str) -> str:
    """Produce a conformant, non-result vault page with a complete readable source copy."""
    metadata = candidate["metadata"]
    title = str(candidate["title"]).replace("\r", " ").replace("\n", " ").strip()
    provenance_source = f"director-reviewed-document:{candidate['admission_id']}:{source_sha}"
    fields: List[Tuple[str, object]] = [
        ("title", title),
        ("type", candidate["vault_type"]),
        ("status", candidate["status"]),
        ("confidence", candidate["confidence"]),
        ("created", created),
        ("updated", created),
        ("project", candidate["project"]),
        ("rq", candidate.get("rq", [])),
        ("contrib", candidate.get("contrib", [])),
        ("domain", candidate.get("domain", ["medical-imaging"])),
        ("tags", candidate.get("tags", [])),
        ("related", candidate.get("related", [])),
        ("source", provenance_source),
        ("aliases", candidate.get("aliases", [])),
        ("evidence-class", candidate["evidence_class"]),
        ("owner", "promote-to-vault-document-gate"),
        ("reviewed", created),
        ("review-cycle", 30),
        ("admission-kind", "director-reviewed-document"),
        ("admission-id", candidate["admission_id"]),
        ("source-markdown-origin", candidate["source_ref"]["path"]),
        ("source-markdown-sha256", source_sha),
    ]
    for key in sorted(metadata):
        fields.append((key, metadata[key]))
    frontmatter = "\n".join(f"{key}: {_yaml_value(value)}" for key, value in fields)
    body = _strip_frontmatter(source_text)
    return "\n".join([
        "---",
        frontmatter,
        "---",
        "",
        f"# {title}",
        "",
        "## Admission provenance",
        "",
        "> This is a full, director-reviewed Markdown copy from the Agent Teams workshop. It is a research document, not a frozen experimental result; it does not establish a thesis-citable metric, global novelty certification, or clinical validity by itself.",
        "",
        f"- Admission batch: `{candidate['admission_id']}`",
        f"- Original workshop path at admission: `{candidate['source_ref']['path']}`",
        f"- Source Markdown SHA-256: `{source_sha}`",
        "- The full document body is retained below so the workshop run may later be cleaned up without losing human-readable research knowledge.",
        "",
        "## Promoted final Markdown",
        "",
        body or "_The source Markdown was empty at admission._",
        "",
    ])


def prepare_document(candidate: dict, *, candidate_path: Path, candidate_sha: str,
                     workspace_root: Path, vault_root: Path, created: str) -> Tuple[Optional[PreparedDocument], List[str]]:
    """Fully validate one candidate before any vault write. Pure except for local reads."""
    errors = _candidate_errors(candidate, vault_root=vault_root)
    source_path, source_errors = _source_path(candidate, workspace_root)
    errors.extend(source_errors)
    source_ref = candidate.get("source_ref") or {"path": "missing", "sha256": "sha256:" + "0" * 64}
    if errors or source_path is None:
        return None, errors
    source_raw = source_path.read_bytes()
    source_sha = _sha256_bytes(source_raw)
    page_path = vault_root / "02-wiki" / _ALLOWED_TYPES[candidate["vault_type"]] / f"{candidate['slug']}.md"
    if not _within(page_path, vault_root / "02-wiki"):
        return None, ["resolved vault target escapes 02-wiki"]
    if page_path.exists():
        return None, [f"vault target already exists: {page_path.name}; document admission never overwrites"]
    page = _render_page(candidate, source_text=source_raw.decode("utf-8-sig"), source_sha=source_sha, created=created)
    # Use System D's live registry as the schema oracle. Full type-specific conformance is required.
    try:
        post_frontmatter = _frontmatter_dict(page)
        verdict = vpc.validate_page(post_frontmatter, contract=vpc.load_contract(vault_root), check_type_specific=True)
        if not verdict["ok"]:
            errors.append(f"vault page contract failed: {verdict['violations']}")
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"could not validate against live vault page contract: {exc}")
    if errors:
        return None, errors
    return PreparedDocument(candidate, candidate_path, candidate_sha, source_path, source_sha, page_path, page), []


def _frontmatter_dict(page: str) -> dict:
    """Small parser for our JSON-safe YAML subset; sufficient before the vault's full linter runs."""
    lines = page.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing frontmatter")
    out: Dict[str, object] = {}
    for line in lines[1:]:
        if line == "---":
            return out
        key, sep, value = line.partition(":")
        if not sep:
            continue
        raw = value.strip()
        try:
            out[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            if raw == "true":
                out[key.strip()] = True
            elif raw == "false":
                out[key.strip()] = False
            elif raw == "null":
                out[key.strip()] = None
            else:
                out[key.strip()] = raw
    raise ValueError("unterminated frontmatter")


def _frontmatter_region(text: str) -> Tuple[int, int]:
    """Return the byte-like character bounds of a top-level YAML frontmatter block."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    return 4, end


def _frontmatter_scalar(text: str, key: str) -> Optional[str]:
    start, end = _frontmatter_region(text)
    match = re.search(rf"(?m)^{re.escape(key)}:\s*([^\n#]+)", text[start:end])
    if not match:
        return None
    return match.group(1).strip().strip("'\"")


def _replace_frontmatter_scalar(text: str, key: str, value: str) -> str:
    """Replace one simple YAML scalar while preserving the remainder of a legacy page."""
    start, end = _frontmatter_region(text)
    front = text[start:end]
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*[^\n]*$")
    replacement = f"{key}: {value}"
    if pattern.search(front):
        front = pattern.sub(replacement, front, count=1)
    else:
        if not front.endswith("\n"):
            front += "\n"
        front += replacement + "\n"
    return text[:start] + front + text[end:]


def prepare_canonical_redirects(candidate: dict, *, vault_root: Path, created: str) -> Tuple[List[PreparedCanonicalRedirect], List[str]]:
    """Prepare narrow same-project canonical redirections before any vault write.

    The admitted synthesis is added as the current route; the old canonical page is not deleted or
    rewritten wholesale.  It becomes a historical pointer, which prevents a recall from silently
    treating two incompatible RQ/idea versions as simultaneous current truth.
    """
    slugs = candidate.get("canonical_redirects") or []
    if not slugs:
        return [], []
    redirects: List[PreparedCanonicalRedirect] = []
    errors: List[str] = []
    marker = f"<!-- current-route-supersession: {candidate['slug']} -->"
    for target_slug in slugs:
        target_path = vault_root / "02-wiki" / "sources" / f"{target_slug}.md"
        if not target_path.exists() or not target_path.is_file():
            errors.append(f"canonical redirect target not found: {target_slug}")
            continue
        try:
            original = target_path.read_text(encoding="utf-8")
            if _frontmatter_scalar(original, "canonical") != "true":
                errors.append(f"canonical redirect target is not canonical: {target_slug}")
                continue
            if _frontmatter_scalar(original, "project") != candidate["project"]:
                errors.append(f"canonical redirect target belongs to another project: {target_slug}")
                continue
            if marker in original:
                errors.append(f"canonical redirect target already points to this current route: {target_slug}")
                continue
            rendered = _replace_frontmatter_scalar(original, "status", "deprecated")
            rendered = _replace_frontmatter_scalar(rendered, "updated", created)
            rendered = _replace_frontmatter_scalar(rendered, "canonical", "false")
            if not rendered.endswith("\n"):
                rendered += "\n"
            rendered += "\n".join([
                "",
                marker,
                "## Current-route pointer",
                "",
                "> [!warning] This page is retained as historical project context, not the current RAC-PET definition.",
                f"> Use [[{candidate['slug']}]] for the current RQs, contributions, method gates and kill criteria.",
                "> Do not combine the legacy RQ/idea/method wording below with the newer route unless a later director decision explicitly reopens it.",
                "",
            ])
            redirects.append(PreparedCanonicalRedirect(candidate["slug"], target_slug, target_path, rendered))
        except (OSError, ValueError) as exc:
            errors.append(f"could not prepare canonical redirect {target_slug}: {exc}")
    return redirects, errors


def prepare_supersessions(candidate: dict, *, vault_root: Path,
                          created: str) -> Tuple[List[PreparedSupersession], List[str]]:
    """Prepare narrow, same-project lifecycle supersessions without deleting history."""
    rows = candidate.get("supersede_pages") or []
    if not rows:
        return [], []
    prepared: List[PreparedSupersession] = []
    errors: List[str] = []
    marker = f"<!-- current-route-supersession: {candidate['slug']} -->"
    for row in rows:
        target_type = str(row.get("vault_type") or "")
        target_slug = str(row.get("slug") or "")
        target_path = vault_root / "02-wiki" / _ALLOWED_TYPES[target_type] / f"{target_slug}.md"
        if not target_path.is_file() or not _within(target_path, vault_root / "02-wiki"):
            errors.append(f"supersession target not found: {target_type}/{target_slug}")
            continue
        try:
            original = target_path.read_text(encoding="utf-8")
            if _frontmatter_scalar(original, "project") != candidate["project"]:
                errors.append(f"supersession target belongs to another project: {target_type}/{target_slug}")
                continue
            if _frontmatter_scalar(original, "type") != target_type:
                errors.append(f"supersession target type mismatch: {target_type}/{target_slug}")
                continue
            if marker in original:
                errors.append(f"supersession target already points to this route: {target_type}/{target_slug}")
                continue
            rendered = _replace_frontmatter_scalar(original, "status", "deprecated")
            rendered = _replace_frontmatter_scalar(rendered, "updated", created)
            if target_type == "source" and _frontmatter_scalar(rendered, "canonical") is not None:
                rendered = _replace_frontmatter_scalar(rendered, "canonical", "false")
            if target_type == "idea" and _frontmatter_scalar(rendered, "idea-status") == "greenlit":
                rendered = _replace_frontmatter_scalar(rendered, "idea-status", "parked")
            if not rendered.endswith("\n"):
                rendered += "\n"
            rendered += "\n".join([
                "",
                marker,
                "## 当前版本指针",
                "",
                "> [!warning] 本页保留为历史证据，不再定义 RAC-PET 的当前研究问题、Ideas、方法或实验顺序。",
                f"> 当前版本请阅读 [[{candidate['slug']}]]；不要把下方旧定义与当前路线并列使用。",
                "",
            ])
            prepared.append(PreparedSupersession(
                candidate["slug"], target_type, target_slug, target_path, rendered,
            ))
        except (OSError, ValueError) as exc:
            errors.append(f"could not prepare supersession {target_type}/{target_slug}: {exc}")
    return prepared, errors


def _write_record(admission_root: Path, record: dict, slug: str) -> Path:
    admission_root.mkdir(parents=True, exist_ok=True)
    clean_slug = slug
    for suffix in (".document-promotion-candidate.json", ".json"):
        if clean_slug.endswith(suffix):
            clean_slug = clean_slug[:-len(suffix)]
    if not _SAFE_SLUG.fullmatch(clean_slug):
        clean_slug = "invalid-candidate"
    path = admission_root / f"document-promotion-record-{clean_slug}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _upsert_section(path: Path, heading: str, lines: Iterable[str]) -> None:
    """Replace a generated H2 section rather than endlessly appending it."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    rendered = heading + "\n\n" + "\n".join(lines).rstrip() + "\n"
    pattern = re.compile(rf"(?ms)^{re.escape(heading)}\n.*?(?=^## |\Z)")
    if pattern.search(text):
        text = pattern.sub(rendered.rstrip("\n"), text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n" + rendered
    path.write_text(text, encoding="utf-8")


def _touch_vault_navigation(vault_root: Path, prepared: Sequence[PreparedDocument], *,
                            canonical_redirects: Sequence[PreparedCanonicalRedirect],
                            supersessions: Sequence[PreparedSupersession], decided_by: str,
                            decided_at: str) -> None:
    slugs = [p.candidate["slug"] for p in prepared]
    date = decided_at[:10]
    index = vault_root / "00-system" / "index.md"
    hot = vault_root / "00-system" / "hot.md"
    log = vault_root / "07-logs" / "log.md"
    _upsert_section(
        index,
        "## Recently admitted director-reviewed documents",
        [f"- [[{slug}]] — final Agent Teams Markdown copied into the vault on {date}." for slug in slugs],
    )
    _upsert_section(
        hot,
        "## Recent director-reviewed document admission",
        [
            f"- {date}: admitted {len(slugs)} RAC-PET final Markdown documents: "
            + ", ".join(f"[[{slug}]]" for slug in slugs) + ".",
            "- Boundary: these are document admissions, not frozen experimental results; no PET/CT GPU metric or global novelty certification is implied.",
        ],
    )
    hot_text = hot.read_text(encoding="utf-8")
    hot_text = re.sub(r"(?m)^updated:\s*[^\n]+$", f"updated: {date}", hot_text, count=1)
    hot.write_text(hot_text, encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        if log.stat().st_size and not log.read_text(encoding="utf-8").endswith("\n"):
            fh.write("\n")
        fh.write(
            f"DOCUMENT-ADMISSION {', '.join(f'[[{slug}]]' for slug in slugs)}: "
            f"director-reviewed Markdown copies admitted by {decided_by} {decided_at}; "
            "non-result boundary retained.\n"
        )
        fh.write(
            "CONTRACT-EDIT [[index]], [[hot]] - change-summary: added the current director-reviewed document "
            "admission entry and explicit non-result boundary; rationale: make vault copies discoverable before scratch cleanup.\n"
        )
        if canonical_redirects:
            targets = ", ".join(f"[[{item.target_slug}]]" for item in canonical_redirects)
            replacement = canonical_redirects[0].replacement_slug
            fh.write(
                f"CONTRACT-EDIT {targets} - change-summary: marked legacy RAC-PET canonical pages as historical "
                f"pointers to [[{replacement}]]; rationale: prevent current retrieval from mixing incompatible "
                "RQ/idea/method versions after document admission.\n"
            )
        if supersessions:
            targets = ", ".join(f"[[{item.target_slug}]]" for item in supersessions)
            replacement = supersessions[0].replacement_slug
            fh.write(
                f"CONTRACT-EDIT {targets} - change-summary: retained old same-project pages as deprecated "
                f"historical pointers to [[{replacement}]]; rationale: remove obsolete composite/current "
                "definitions from the active reading path without deleting provenance.\n"
            )


def run_document_admission_batch(candidates: Sequence[Tuple[dict, Path, str]], *, admission_id: str,
                                 admission_root: Path, workspace_root: Path, vault_root: Path,
                                 human_authorized: bool, decided_by: str, decided_at: str,
                                 authorization_basis: Optional[str] = None) -> List[dict]:
    """Validate all candidates first, then either write all of the batch or none of it.

    The all-or-nothing preflight prevents a half-migrated run from being deleted. A record is written
    for each candidate regardless of outcome; only an admitted batch touches System D.
    """
    prepared: List[PreparedDocument] = []
    canonical_redirects: List[PreparedCanonicalRedirect] = []
    supersessions: List[PreparedSupersession] = []
    records: List[dict] = []
    seen_slugs: set[str] = set()
    rejection = []
    for candidate, candidate_path, candidate_sha in candidates:
        source_ref = candidate.get("source_ref") or {"path": "missing", "sha256": "sha256:" + "0" * 64}
        if candidate.get("admission_id") != admission_id:
            reason = "candidate admission_id does not match requested batch"
            rejection.append(reason)
            records.append(_record(candidate, candidate_path=candidate_path, candidate_sha=candidate_sha,
                                   source_ref=source_ref, admissible=False, reasons=[reason],
                                   decided_by=decided_by, decided_at=decided_at))
            continue
        if candidate.get("slug") in seen_slugs:
            reason = "duplicate target slug within document-admission batch"
            rejection.append(reason)
            records.append(_record(candidate, candidate_path=candidate_path, candidate_sha=candidate_sha,
                                   source_ref=source_ref, admissible=False, reasons=[reason],
                                   decided_by=decided_by, decided_at=decided_at))
            continue
        seen_slugs.add(candidate.get("slug"))
        prepared_one, errors = prepare_document(
            candidate, candidate_path=candidate_path, candidate_sha=candidate_sha,
            workspace_root=workspace_root, vault_root=vault_root, created=decided_at[:10],
        )
        if errors or prepared_one is None:
            rejection.extend(errors or ["candidate preparation failed"])
            records.append(_record(candidate, candidate_path=candidate_path, candidate_sha=candidate_sha,
                                   source_ref=source_ref, admissible=False, reasons=errors or ["candidate preparation failed"],
                                   decided_by=decided_by, decided_at=decided_at))
        else:
            redirects, redirect_errors = prepare_canonical_redirects(
                candidate, vault_root=vault_root, created=decided_at[:10]
            )
            superseded, supersession_errors = prepare_supersessions(
                candidate, vault_root=vault_root, created=decided_at[:10]
            )
            lifecycle_errors = redirect_errors + supersession_errors
            if lifecycle_errors:
                rejection.extend(lifecycle_errors)
                records.append(_record(
                    candidate, candidate_path=candidate_path, candidate_sha=candidate_sha,
                    source_ref=source_ref, admissible=False, reasons=lifecycle_errors,
                    decided_by=decided_by, decided_at=decided_at,
                ))
            else:
                prepared.append(prepared_one)
                canonical_redirects.extend(redirects)
                supersessions.extend(superseded)

    if not human_authorized:
        rejection.append("no director document authorization (requires an explicit director command or exact environment authorization)")
    if rejection:
        # Preflight intentionally fails the whole batch, including otherwise-valid documents.
        invalid_slugs = {r["candidate_ref"]["path"] for r in records}
        for item in prepared:
            if str(item.candidate_path).replace("\\", "/") not in invalid_slugs:
                records.append(_record(
                    item.candidate, candidate_path=item.candidate_path, candidate_sha=item.candidate_sha,
                    source_ref=item.candidate["source_ref"], admissible=False,
                    reasons=["batch not admitted: " + "; ".join(sorted(set(rejection)))],
                    decided_by=decided_by, decided_at=decided_at,
                ))
        if authorization_basis:
            for record in records:
                record["authorization_basis"] = authorization_basis
        for rec in records:
            _write_record(admission_root, rec, Path(rec["candidate_ref"]["path"]).name)
        append_event(admission_root / "admission-ledger.jsonl", "promote", {
            "admission_id": admission_id,
            "admissible": False,
            "vault_slugs": [],
            "reason_count": len(set(rejection)),
            "decided_by": decided_by,
            "authorization_basis": authorization_basis,
        }, decided_at)
        return records

    # The entire batch is prepared first. New documents and narrowly scoped lifecycle pointers
    # are then written together; no unvalidated candidate can half-migrate a run.
    for item in prepared:
        item.page_path.parent.mkdir(parents=True, exist_ok=True)
        item.page_path.write_text(item.page, encoding="utf-8")
    for redirect in canonical_redirects:
        redirect.target_path.write_text(redirect.page, encoding="utf-8")
    for supersession in supersessions:
        supersession.target_path.write_text(supersession.page, encoding="utf-8")
    _touch_vault_navigation(
        vault_root, prepared, canonical_redirects=canonical_redirects, supersessions=supersessions,
        decided_by=decided_by, decided_at=decided_at,
    )
    redirects_by_replacement: Dict[str, List[str]] = {}
    for redirect in canonical_redirects:
        redirects_by_replacement.setdefault(redirect.replacement_slug, []).append(redirect.target_slug)
    supersessions_by_replacement: Dict[str, List[str]] = {}
    for supersession in supersessions:
        label = f"{supersession.target_type}/{supersession.target_slug}"
        supersessions_by_replacement.setdefault(supersession.replacement_slug, []).append(label)
    for item in prepared:
        redirected = redirects_by_replacement.get(item.candidate["slug"], [])
        superseded = supersessions_by_replacement.get(item.candidate["slug"], [])
        basis = authorization_basis or "director authorization"
        reasons = [f"admitted: {basis}, SHA-verified final Markdown, and full vault-page contract pass"]
        if redirected:
            reasons.append("canonical historical pointers updated: " + ", ".join(redirected))
        if superseded:
            reasons.append("same-project pages deprecated with history retained: " + ", ".join(superseded))
        record = _record(
            item.candidate, candidate_path=item.candidate_path, candidate_sha=item.candidate_sha,
            source_ref=item.candidate["source_ref"], admissible=True, reasons=reasons,
            decided_by=decided_by, decided_at=decided_at, vault_path=item.page_path,
            vault_slug=item.candidate["slug"], canonical_redirects=redirected,
            superseded_pages=superseded,
            authorization_basis=authorization_basis,
        )
        _write_record(admission_root, record, item.candidate["slug"])
        records.append(record)
    append_event(admission_root / "admission-ledger.jsonl", "promote", {
        "admission_id": admission_id,
        "admissible": True,
        "vault_slugs": [item.candidate["slug"] for item in prepared],
        "decided_by": decided_by,
        "authorization_basis": authorization_basis,
    }, decided_at)
    return records
