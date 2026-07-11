"""DB-page conformance contract — binds the machine's write paths to System D's authoritative schema.

Single source of truth (schema-contract §9.1): the page schema lives in the DATABASE's own markdown
(`05-registry/type-registry.md` + `00-system/schema-contract.md` §1). The machine must NEVER keep a
parallel hardcoded copy. This module PARSES the live registry and validates any page the machine is
about to write — the migration ingest path AND the promote seam (`tools/promote.py`) — against it, so
write-side and read-side can never drift from the DB's own definition.

Pure + I/O-isolated: `load_contract()` does the single read; `validate_page()` is pure over a parsed
contract. Fail-closed: an unknown type or any missing required field is a violation, so a
non-conformant page is never written.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

# Universal required frontmatter — schema-contract §1 "Required fields".
UNIVERSAL_REQUIRED = ("title", "type", "status", "confidence", "created", "updated", "project")

# Page-lifecycle status enum — schema-contract §4 (the universal `status:`, distinct from type-specific
# status fields like reading-status / result-status / claim-status which carry their own vocab).
STATUS_VALUES = frozenset({"draft", "active", "completed", "deprecated", "parked"})
CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unverified"})

_ROW_SPLIT = re.compile(r"(?<!\\)\|")          # split table rows on UNescaped pipes only
_PARENS = re.compile(r"\([^()]*\)")            # one innermost (...) group
_BACKTICK_NAME = re.compile(r"`([a-z][a-z0-9-]*)`")


def _registry_path(vault_root) -> Path:
    return Path(vault_root) / "05-registry" / "type-registry.md"


def _cells(line: str) -> List[str]:
    """Split a markdown table row into trimmed cells, honouring escaped pipes (`\\|`) inside enums."""
    parts = [c.replace("\\|", "|").strip() for c in _ROW_SPLIT.split(line.strip())]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _extract_field_names(cell: str) -> List[str]:
    """Backticked top-level field names in a 'required fields' cell. The `(type/enum)` hints — and any
    backticks nested INSIDE those hints (e.g. `[[model-slug]]`, or `audit`'s sub-keys) — are removed
    first, so only genuine top-level required fields survive."""
    s = cell
    prev = None
    while prev != s:                            # strip nested (...) hints iteratively
        prev = s
        s = _PARENS.sub("", s)
    out: List[str] = []
    seen = set()
    for name in _BACKTICK_NAME.findall(s):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def load_contract(vault_root) -> Dict[str, List[str]]:
    """Parse the knowledge-note table of `type-registry.md` → {type: [required type-specific fields]}.

    Only the 5-column knowledge-note table is parsed (the 3-column meta-doc table is ignored), so meta
    types (schema/registry/index/...) never enter the contract. Header + separator rows are skipped
    (their first cell is not a `backticked` type name)."""
    text = _registry_path(vault_root).read_text(encoding="utf-8")
    contract: Dict[str, List[str]] = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) != 5 or not cells[0].startswith("`"):
            continue
        type_name = cells[0].strip("` ").strip()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", type_name):
            continue
        contract[type_name] = _extract_field_names(cells[3])
    return contract


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def validate_page(frontmatter: dict, *, contract: Dict[str, List[str]],
                  check_type_specific: bool = True) -> dict:
    """Validate a page's frontmatter against the DB contract. Pure.

    `check_type_specific=False` validates the UNIVERSAL layer only (universal-required + type-in-registry
    + status/confidence enums + bitemporal) and skips the per-type required-field check — used by the
    promote seam, whose result DATA fields (model/dataset/metric/...) come from a real run and are
    server-gated. The migration path uses the default (full conformance).

    Returns {ok: bool, type, violations: [{code, ...}]}. Codes:
      MISSING_UNIVERSAL · MISSING_TYPE · UNKNOWN_TYPE · MISSING_TYPE_SPECIFIC ·
      UNREGISTERED_STATUS · BAD_CONFIDENCE · BITEMPORAL.
    """
    fm = frontmatter or {}
    violations: List[dict] = []

    for f in UNIVERSAL_REQUIRED:
        if f not in fm or _empty(fm.get(f)):
            violations.append({"code": "MISSING_UNIVERSAL", "field": f})

    t = fm.get("type")
    if not t:
        violations.append({"code": "MISSING_TYPE"})
    elif t not in contract:
        violations.append({"code": "UNKNOWN_TYPE", "field": "type", "value": t})
    elif check_type_specific:
        for f in contract[t]:
            if f not in fm or _empty(fm.get(f)):
                violations.append({"code": "MISSING_TYPE_SPECIFIC", "field": f, "type": t})

    status = fm.get("status")
    if status and status not in STATUS_VALUES:
        violations.append({"code": "UNREGISTERED_STATUS", "field": "status", "value": status})
    conf = fm.get("confidence")
    if conf and conf not in CONFIDENCE_VALUES:
        violations.append({"code": "BAD_CONFIDENCE", "field": "confidence", "value": conf})

    # Bitemporal hard rule (registry field-extension log 2026-06-10 / lint BITEMPORAL): setting
    # `invalid-at` REQUIRES `invalidated-by` (invalidate-don't-delete).
    if not _empty(fm.get("invalid-at")) and _empty(fm.get("invalidated-by")):
        violations.append({"code": "BITEMPORAL", "detail": "invalid-at requires invalidated-by"})

    return {"ok": not violations, "type": t, "violations": violations}
