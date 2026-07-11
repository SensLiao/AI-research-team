"""Read-only router for the Auto-Empirical Research Skills catalog snapshot.

This module treats AERS as reference metadata, not as executable instructions.
By default it reads the RAT-internal metadata snapshot under
``agents/references/aers-catalog``. Explicit ``--aers-root`` callers can still
point it at a full upstream AERS checkout for refresh/audit runs. In both modes
it reads only machine-readable catalog metadata and never opens child
``SKILL.md`` bodies, runs hooks, or writes to the vault.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
INTERNAL_AERS_CATALOG_DIR = _PKG_ROOT / "agents" / "references" / "aers-catalog"

_SAFE_LICENSE_PREFIXES = ("MIT", "Apache-2.0", "BSD", "ISC")
_RISKY_LICENSE_MARKERS = (
    "UNKNOWN",
    "GPL",
    "AGPL",
    "CC-BY-NC",
    "Non-Commercial",
    "Mixed",
    "CC-BY-SA",
)

_RAT_STAGE_TAGS = {
    "DISCOVER": {
        "literature",
        "research-design",
        "citation-hygiene",
        "reproducibility",
        "data",
        "systematic-review",
        "paper-reading",
    },
    "IDEATE": {"research-design", "hypothesis", "topic", "causal-inference"},
    "DESIGN": {"research-design", "power", "data", "causal-inference", "econometrics"},
    "EXECUTE": {"analysis", "data", "reproduction", "runtime-safety"},
    "ANALYZE": {"analysis", "robustness", "tables-figures", "causal-inference"},
    "VERIFY": {"reproduction", "robustness", "citation-hygiene", "peer-review"},
    "REPORT": {"writing", "tables-figures", "submission", "rebuttal"},
}


class AERSCatalogError(ValueError):
    """Raised when the AERS catalog is missing or malformed."""


def default_aers_root() -> Path:
    return INTERNAL_AERS_CATALOG_DIR


def _root(root: Optional[str | Path] = None) -> Path:
    return Path(root) if root is not None else default_aers_root()


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise AERSCatalogError(f"AERS catalog file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _catalog_dir(root: Path) -> Path:
    external_catalog_dir = root / "catalog"
    if (external_catalog_dir / "skills-enriched.json").exists():
        return external_catalog_dir
    if (root / "skills-enriched.json").exists():
        return root
    return external_catalog_dir


def _load_optional_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _catalog_files(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    catalog_dir = _catalog_dir(root)
    enriched = _load_json(catalog_dir / "skills-enriched.json")
    provenance = _load_json(catalog_dir / "provenance.json")
    audit = _load_json(catalog_dir / "skill-audit.json")
    if not isinstance(enriched.get("skills"), list):
        raise AERSCatalogError("skills-enriched.json must contain a skills list")
    if not isinstance(provenance.get("collections"), list):
        raise AERSCatalogError("provenance.json must contain a collections list")
    if not isinstance(audit.get("records"), list):
        raise AERSCatalogError("skill-audit.json must contain a records list")
    return enriched, provenance, audit, catalog_dir


def _metadata_only_snapshot(root: Path, catalog_dir: Path) -> bool:
    return catalog_dir == root and not (root / "skills").exists()


def _missing_paths_from_snapshot(catalog_dir: Path) -> set[str]:
    data = _load_optional_json(catalog_dir / "path-existence-overrides.json")
    if not isinstance(data, dict):
        return set()
    paths = data.get("missing_skill_paths")
    if not isinstance(paths, list):
        return set()
    return {p for p in paths if isinstance(p, str)}


def _safe_catalog_path(root: Path, rel_path: str) -> tuple[Optional[Path], Optional[str]]:
    try:
        pure = PurePosixPath(rel_path)
    except TypeError:
        return None, "catalog_path_not_string"
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        return None, "catalog_path_escapes_root"
    return root.joinpath(*pure.parts), None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _tag_values(tags: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(tags, dict):
        for values in tags.values():
            for value in _as_list(values):
                if isinstance(value, str):
                    out.add(value.lower())
    return out


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9_.+-]+", text.lower()) if t}


def _description_snippet(text: Any, limit: int = 280) -> str:
    if not isinstance(text, str):
        return ""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."


def _license_allowed(license_name: str, commercial_use: str) -> bool:
    if commercial_use != "allowed":
        return False
    if not license_name:
        return False
    return license_name.startswith(_SAFE_LICENSE_PREFIXES)


def _risk_profile(
    skill: dict[str, Any],
    provenance: dict[str, Any],
    audit: dict[str, Any],
    *,
    skill_path_exists: bool,
    path_error: Optional[str],
) -> tuple[str, list[str], str]:
    reasons: list[str] = []

    license_name = str(skill.get("license") or provenance.get("license") or "")
    commercial_use = str(skill.get("commercial_use") or provenance.get("commercial_use") or "")

    if path_error:
        reasons.append(path_error)
    elif not skill_path_exists:
        reasons.append("catalog_path_missing")

    if not _license_allowed(license_name, commercial_use):
        reasons.append(f"license_review_required:{license_name or 'missing'}")
    if commercial_use != "allowed":
        reasons.append(f"commercial_use_review_required:{commercial_use or 'missing'}")
    if any(marker in license_name for marker in _RISKY_LICENSE_MARKERS):
        reasons.append(f"share_or_restricted_license:{license_name}")

    source_confidence = str(provenance.get("source_confidence") or "")
    if source_confidence in {"low", "unresolved"}:
        reasons.append(f"low_source_confidence:{source_confidence}")
    if not provenance.get("security_review"):
        reasons.append("missing_security_review_pointer")

    for flag in _as_list(skill.get("quality_flags")):
        if isinstance(flag, str) and flag:
            reasons.append(f"quality_flag:{flag}")

    line_count = skill.get("line_count") or audit.get("line_count")
    if isinstance(line_count, int) and line_count > 500:
        reasons.append("oversized_skill_requires_progressive_disclosure")

    for key in ("exact_case", "has_description", "has_frontmatter", "has_name"):
        if key in audit and audit[key] is False:
            reasons.append(f"audit_{key}_false")

    blockers = {
        "catalog_path_escapes_root",
        "catalog_path_missing",
    }
    if any(r in blockers for r in reasons):
        return "high", reasons, "do_not_use"
    if reasons:
        return "medium", reasons, "review_required"
    return "low", [], "safe_reference"


def load_candidates(root: Optional[str | Path] = None) -> list[dict[str, Any]]:
    """Load AERS catalog candidates with provenance and risk metadata.

    The function reads only ``catalog/*.json``. It checks whether catalog paths
    physically exist but does not read the referenced child skill files.
    """
    aers_root = _root(root)
    enriched, provenance_doc, audit_doc, catalog_dir = _catalog_files(aers_root)
    provenance_by_id = {
        c.get("id"): c for c in provenance_doc.get("collections", []) if isinstance(c, dict)
    }
    audit_by_path = {
        r.get("path"): r for r in audit_doc.get("records", []) if isinstance(r, dict)
    }
    metadata_only = _metadata_only_snapshot(aers_root, catalog_dir)
    snapshot_missing_paths = _missing_paths_from_snapshot(catalog_dir)

    candidates: list[dict[str, Any]] = []
    for skill in enriched["skills"]:
        if not isinstance(skill, dict):
            continue
        rel_path = str(skill.get("path") or "")
        collection = str(skill.get("collection") or "")
        provenance = provenance_by_id.get(collection) or {}
        audit = audit_by_path.get(rel_path) or {}
        physical_path, path_error = _safe_catalog_path(aers_root, rel_path)
        if metadata_only and not path_error:
            skill_path_exists = bool(audit) and rel_path not in snapshot_missing_paths
        else:
            skill_path_exists = bool(physical_path and physical_path.is_file())
        risk_level, risk_reasons, recommendation = _risk_profile(
            skill,
            provenance,
            audit,
            skill_path_exists=skill_path_exists,
            path_error=path_error,
        )
        tags = skill.get("tags") if isinstance(skill.get("tags"), dict) else {}
        candidates.append(
            {
                "name": str(skill.get("name") or ""),
                "path": rel_path,
                "collection": collection,
                "description_snippet": _description_snippet(skill.get("description_effective")),
                "tags": tags,
                "license": str(skill.get("license") or provenance.get("license") or ""),
                "commercial_use": str(skill.get("commercial_use") or provenance.get("commercial_use") or ""),
                "source_url": str(skill.get("source_url") or provenance.get("source_url") or ""),
                "source_confidence": str(provenance.get("source_confidence") or ""),
                "security_review": str(provenance.get("security_review") or ""),
                "quality_score": skill.get("quality_score"),
                "quality_flags": _as_list(skill.get("quality_flags")),
                "line_count": skill.get("line_count") or audit.get("line_count"),
                "has_references": bool(skill.get("has_references")),
                "skill_path_exists": skill_path_exists,
                "metadata_snapshot": metadata_only,
                "risk_level": risk_level,
                "risk_reasons": risk_reasons,
                "recommendation": recommendation,
                "catalog_only": True,
            }
        )
    return candidates


def _match_score(candidate: dict[str, Any], query_tokens: set[str], filters: set[str]) -> int:
    haystack = set()
    haystack |= _tokens(str(candidate.get("name") or ""))
    haystack |= _tokens(str(candidate.get("path") or ""))
    haystack |= _tokens(str(candidate.get("collection") or ""))
    haystack |= _tokens(str(candidate.get("description_snippet") or ""))
    haystack |= _tag_values(candidate.get("tags"))
    return 4 * len(query_tokens & haystack) + 2 * len(filters & haystack)


def query_candidates(
    *,
    query: str = "",
    rat_stage: Optional[str] = None,
    method: Optional[str] = None,
    topic: Optional[str] = None,
    language: Optional[str] = None,
    include_review_required: bool = False,
    root: Optional[str | Path] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return ranked AERS candidates by metadata only.

    By default, only ``safe_reference`` candidates are returned. Pass
    ``include_review_required=True`` to show candidates that need manual license,
    path, or security review.
    """
    query_tokens = _tokens(query)
    filters = {v.lower() for v in (method, topic, language) if v}
    if rat_stage:
        filters |= _RAT_STAGE_TAGS.get(rat_stage.upper(), set())

    ranked: list[tuple[int, dict[str, Any]]] = []
    for candidate in load_candidates(root):
        if not include_review_required and candidate["recommendation"] != "safe_reference":
            continue
        match_score = _match_score(candidate, query_tokens, filters)
        if query_tokens or filters:
            if match_score <= 0:
                continue
        score = match_score
        if candidate.get("recommendation") == "safe_reference":
            score += 2
        if candidate.get("skill_path_exists"):
            score += 1
        ranked.append((score, candidate))
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].get("quality_score") if isinstance(item[1].get("quality_score"), int) else -1,
            item[1].get("name") or "",
        ),
        reverse=True,
    )
    return [candidate for _, candidate in ranked[: max(0, limit)]]


def summarize_catalog(root: Optional[str | Path] = None) -> dict[str, Any]:
    """Return a no-secret summary of the AERS metadata surface."""
    candidates = load_candidates(root)
    by_recommendation: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    missing_paths = []
    for candidate in candidates:
        rec = str(candidate["recommendation"])
        risk = str(candidate["risk_level"])
        by_recommendation[rec] = by_recommendation.get(rec, 0) + 1
        by_risk[risk] = by_risk.get(risk, 0) + 1
        if not candidate["skill_path_exists"]:
            missing_paths.append(candidate["path"])
    return {
        "total_candidates": len(candidates),
        "by_recommendation": by_recommendation,
        "by_risk_level": by_risk,
        "missing_catalog_paths": sorted(missing_paths),
        "catalog_only": True,
        "vault_write": False,
        "child_skill_bodies_read": False,
        "metadata_snapshot": bool(candidates and candidates[0].get("metadata_snapshot")),
        "catalog_root": str(_catalog_dir(_root(root))),
    }


__all__ = [
    "AERSCatalogError",
    "default_aers_root",
    "load_candidates",
    "query_candidates",
    "summarize_catalog",
]
