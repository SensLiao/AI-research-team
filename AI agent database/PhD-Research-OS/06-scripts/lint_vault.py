"""
lint_vault.py — Programmatic LINT for the PhD Research OS vault.

Runs 15 checks. Exits non-zero on errors so CI / pre-commit can block.

NOTE (paper-reading-upgrade, 2026-06-26): the READING_DEPTH section-graduation check
(#15) is intentionally emitted as a WARNING during the legacy-page migration window so
the ~60 pre-upgrade paper pages do NOT fail-all. It is designed to HARDEN to ERROR at
`reading-status >= read` once the legacy pages have been re-deepened (P6 Codex
work-orders). The graduation mapping mirrors the project's reading-depth LEDGER table
and 04-templates/paper.md.

Checks:
  1. UNIVERSAL_FRONTMATTER  — every knowledge-note page has all required fields
  2. UNKNOWN_TYPE           — `type:` value exists in 05-registry/type-registry.md
  3. UNKNOWN_STATUS         — `status:` value exists in 05-registry/status-registry.md
  4. BROKEN_LINK            — every [[slug]] resolves to a file or alias
  5. ORPHAN_PAGE            — knowledge-note page has at least one inbound [[link]]
  6. STUB_PAGE              — body length < 100 chars
  7. STALE_LOW_CONF         — confidence: low|unverified and updated > 30 days ago
  8. CITATION_GATE          — for type:result, can-cite-thesis matches the derived formula
  9. DUPLICATE_SLUG         — no two pages share a filename (case-insensitive)
 10. VOCAB                  — domain/tags values are in the controlled registries
                             (advisory: warning for domain, info for tags — never blocks)
 11. OVER_READ / DEEP_READ_CAP — granularity controller: flags over-read (background at
                             deep-read) + per-thread deep-read soft cap (advisory only)
 12. SOURCE_REF_DUPLICATE   — (M12) same doi/url source identifier on ≥2 paper pages
                             → error; same normalized title across ≥2 slugs → warning
 13. REVIEW_CYCLE_OVERDUE   — (L4) page with review-cycle:<N> not reviewed within N days
                             → warning (advisory, never blocks)
 14. READING_STATUS_ENUM    — (paper-reading-upgrade) type:paper `reading-status` is in the
                             registry enum {to-read, skimmed, read, deep-read, cited,
                             deprecated} → warning (catches enum drift)
 15. READING_DEPTH          — (paper-reading-upgrade) type:paper body carries the sections
                             its reading-status earns (skimmed→Stage 0+Pass 1;
                             read→+Pass 2; deep-read/cited→+Figure+Pass 3+Stage 4)
                             → warning during migration; hardens to ERROR at
                             reading-status >= read after legacy pages are migrated

Usage:
  python 06-scripts/lint_vault.py                  # full lint, exit non-zero on errors
  python 06-scripts/lint_vault.py --json           # machine-readable output
  python 06-scripts/lint_vault.py --warnings-only  # don't exit non-zero
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import frontmatter  # type: ignore
except ImportError:
    print("ERROR: install python-frontmatter: pip install python-frontmatter", file=sys.stderr)
    sys.exit(2)

VAULT_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = VAULT_ROOT / "02-wiki"
REGISTRY_DIR = VAULT_ROOT / "05-registry"
SYSTEM_DIR = VAULT_ROOT / "00-system"

UNIVERSAL_REQUIRED = ["title", "type", "status", "confidence", "created", "updated", "project"]
META_TYPES = {"schema", "registry", "readme", "index", "log", "hot", "routing", "manifest", "plan", "view"}
WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]")
TYPE_ROW_RE = re.compile(r"^\|\s*`(?P<type>[a-z\-]+)`\s*\|", re.MULTILINE)


def _gate_requires_reproducibility() -> bool:
    """Reproducibility folds into the citation gate only when the project declared
    reproducibility_level: full at bootstrap (see 00-system/AGENTS.md §2). Read without
    a yaml dependency so the lint never breaks on a missing optional package."""
    intake = VAULT_ROOT / "bootstrap-intake.yml"
    if not intake.exists():
        return False
    try:
        for line in intake.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("reproducibility_level:"):
                return s.split(":", 1)[1].strip().strip('"').strip("'") == "full"
    except OSError:
        return False
    return False


REQUIRE_REPRO = _gate_requires_reproducibility()


@dataclass
class LintError:
    severity: str  # "error" | "warning" | "info"
    code: str
    page: str
    detail: str


@dataclass
class LintReport:
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintError] = field(default_factory=list)
    infos: list[LintError] = field(default_factory=list)

    def add(self, severity: str, code: str, page: str, detail: str) -> None:
        bucket = {"error": self.errors, "warning": self.warnings, "info": self.infos}[severity]
        bucket.append(LintError(severity, code, page, detail))

    def summary(self) -> str:
        return f"{len(self.errors)} errors, {len(self.warnings)} warnings, {len(self.infos)} info"


def load_registered_types() -> set[str]:
    """Parse 05-registry/type-registry.md and extract registered type names."""
    path = REGISTRY_DIR / "type-registry.md"
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(TYPE_ROW_RE.findall(text)) | META_TYPES


def load_registered_statuses() -> set[str]:
    path = REGISTRY_DIR / "status-registry.md"
    if not path.exists():
        return {"draft", "active", "completed", "deprecated", "parked"}
    text = path.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*`([a-z\-]+)`\s*\|", text, re.MULTILINE)
    return set(rows) | {"draft", "active", "completed", "deprecated", "parked"}


def load_registered_domains() -> set[str]:
    """Parse the controlled-domains table in 05-registry/domains.md (first column)."""
    path = REGISTRY_DIR / "domains.md"
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*`([a-z0-9\-]+)`\s*\|", text, re.MULTILINE))


def load_registered_tags() -> set[str]:
    """Parse the controlled tag sections of 05-registry/tags.md (discipline / content /
    thread). Only backticked tokens inside those sections count, so prose field names
    like `result-status:` don't leak in."""
    path = REGISTRY_DIR / "tags.md"
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    tags: set[str] = set()
    for header in ("workflow tags", "Controlled content tags", "Thread labels"):
        m = re.search(rf"##[^\n]*{re.escape(header)}.*?(?=\n## |\Z)", text, re.DOTALL)
        if m:
            tags |= set(re.findall(r"`([a-z0-9\-]+)`", m.group(0)))
    tags.discard("result-status")
    return tags


def collect_pages() -> list[Path]:
    """All .md files under wiki/, excluding _bases (which are .base) and templates."""
    pages = []
    for p in WIKI_DIR.rglob("*.md"):
        if "_templates" in p.parts or "_bases" in p.parts:
            continue
        pages.append(p)
    return sorted(pages)


def page_slug(page: Path) -> str:
    return page.stem.lower()


def is_meta_type(meta: dict) -> bool:
    t = meta.get("type", "")
    return t in META_TYPES


def parse_page(path: Path) -> tuple[dict[str, Any], str]:
    try:
        # utf-8-sig tolerates a UTF-8 BOM (Windows editors / PowerShell), which would otherwise
        # make YAML frontmatter unparseable and the page silently look untyped.
        text = path.read_text(encoding="utf-8-sig")
        post = frontmatter.loads(text)
        return dict(post.metadata), post.content
    except Exception as e:
        return {}, f"<<parse error: {e}>>"


def check_universal_frontmatter(report: LintReport, path: Path, meta: dict) -> None:
    if is_meta_type(meta):
        return
    page = page_slug(path)
    for field_name in UNIVERSAL_REQUIRED:
        if field_name not in meta or meta[field_name] in (None, "", []):
            report.add("error", "UNIVERSAL_FRONTMATTER", page, f"missing required field: {field_name}")


def check_type(report: LintReport, path: Path, meta: dict, registered: set[str]) -> None:
    page = page_slug(path)
    t = meta.get("type")
    if not t:
        return  # caught by UNIVERSAL_FRONTMATTER
    if t not in registered:
        report.add("error", "UNKNOWN_TYPE", page, f"type '{t}' not in registry")


def check_status(report: LintReport, path: Path, meta: dict, registered: set[str]) -> None:
    if is_meta_type(meta):
        return
    page = page_slug(path)
    s = meta.get("status")
    if not s:
        return
    if s not in registered:
        report.add("error", "UNKNOWN_STATUS", page, f"status '{s}' not in registry")


def check_links_and_orphans(report: LintReport, pages: list[Path]) -> None:
    slugs = {page_slug(p): p for p in pages}
    aliases: dict[str, str] = {}
    for p in pages:
        meta, _ = parse_page(p)
        for a in meta.get("aliases", []) or []:
            aliases[str(a).lower()] = page_slug(p)

    inbound: dict[str, set[str]] = {s: set() for s in slugs}

    for p in pages:
        meta, body = parse_page(p)
        page = page_slug(p)
        for match in WIKILINK_RE.finditer(body):
            target = match.group(1).lower().strip()
            target_no_anchor = target.split("#", 1)[0].strip()
            resolved = target_no_anchor if target_no_anchor in slugs else aliases.get(target_no_anchor)
            if resolved:
                inbound[resolved].add(page)
            else:
                report.add("error", "BROKEN_LINK", page, f"[[{target}]] resolves to nothing")

        for r in meta.get("related", []) or []:
            r_str = str(r).strip()
            if r_str.startswith("[[") and r_str.endswith("]]"):
                r_str = r_str[2:-2]
            target = r_str.split("|", 1)[0].split("#", 1)[0].strip().lower()
            resolved = target if target in slugs else aliases.get(target)
            if resolved:
                inbound[resolved].add(page)
            elif target:
                report.add("error", "BROKEN_LINK", page, f"related: [[{target}]] resolves to nothing")

    for slug, sources in inbound.items():
        if not sources:
            meta, _ = parse_page(slugs[slug])
            if is_meta_type(meta):
                continue
            report.add("warning", "ORPHAN_PAGE", slug, "no inbound [[link]] from any other knowledge-note page")


def check_stub(report: LintReport, path: Path, meta: dict, body: str) -> None:
    if is_meta_type(meta):
        return
    page = page_slug(path)
    body_text = re.sub(r"#.*$", "", body, flags=re.MULTILINE).strip()
    if len(body_text) < 100 or body_text.upper().startswith("TODO"):
        report.add("warning", "STUB_PAGE", page, f"body < 100 chars (got {len(body_text)})")


def check_stale_low_confidence(report: LintReport, path: Path, meta: dict) -> None:
    if is_meta_type(meta):
        return
    page = page_slug(path)
    conf = meta.get("confidence")
    if conf not in ("low", "unverified"):
        return
    updated = meta.get("updated")
    if not updated:
        return
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated).date()
        except ValueError:
            return
    elif isinstance(updated, datetime):
        updated = updated.date()
    if not isinstance(updated, date):
        return
    age_days = (date.today() - updated).days
    if age_days > 30:
        report.add("warning", "STALE_LOW_CONF", page,
                   f"confidence={conf}, updated {age_days}d ago — re-verify or mark parked")


def check_citation_gate(report: LintReport, path: Path, meta: dict) -> None:
    if is_meta_type(meta):
        return
    page = page_slug(path)
    is_result_type = meta.get("type") == "result"
    in_results_folder = path.parent.name == "results"
    declares_result_fields = ("can-cite-thesis" in meta) or ("result-status" in meta)
    if not (is_result_type or in_results_folder or declares_result_fields):
        return
    # Close the gate-bypass hole: a page in results/ (or carrying result fields) whose
    # `type` is malformed would otherwise skip the gate entirely. Flag it instead.
    if not is_result_type:
        report.add("error", "CITATION_GATE", page,
                   f"page is in results/ or declares result fields but type='{meta.get('type')}' "
                   f"!= 'result' — the citation gate only governs type==result; fix the type so the "
                   f"gate applies (closes the gate-bypass hole).")
        return
    rs = meta.get("result-status")
    leak = meta.get("leakage-audit")
    fair = meta.get("fairness-audit")
    repro = meta.get("reproducibility-audit")
    declared = meta.get("can-cite-thesis")
    derived = (rs == "frozen") and (leak == "pass") and (fair == "pass")
    if REQUIRE_REPRO:
        derived = derived and (repro == "pass")
    if declared is None:
        report.add("error", "CITATION_GATE", page, "result page missing `can-cite-thesis`")
        return
    if bool(declared) != bool(derived):
        repro_note = f", reproducibility={repro}" if REQUIRE_REPRO else ""
        report.add("error", "CITATION_GATE", page,
                   f"can-cite-thesis={declared} but derived={derived} "
                   f"(result-status={rs}, leakage={leak}, fairness={fair}{repro_note}). "
                   f"Manual override forbidden — fix the underlying audits.")


def check_duplicate_slugs(report: LintReport, pages: list[Path]) -> None:
    seen: dict[str, list[Path]] = {}
    for p in pages:
        seen.setdefault(p.stem.lower(), []).append(p)
    for slug, paths in seen.items():
        if len(paths) > 1:
            locs = ", ".join(str(x.relative_to(VAULT_ROOT)) for x in paths)
            report.add("error", "DUPLICATE_SLUG", slug, f"slug appears in: {locs}")


def check_vocab(report: LintReport, path: Path, meta: dict, domains: set[str], tags: set[str]) -> None:
    """Advisory (§9 anti-rot): flag domain/tag values outside the controlled registries.
    Warnings / infos only — never blocks a write; only errors set a non-zero exit."""
    if is_meta_type(meta):
        return
    page = page_slug(path)
    if domains:
        for d in meta.get("domain", []) or []:
            if str(d) not in domains:
                report.add("warning", "VOCAB_DOMAIN", page,
                           f"domain '{d}' not in 05-registry/domains.md (advisory — converge or register)")
    if tags:
        for t in meta.get("tags", []) or []:
            if str(t) not in tags:
                report.add("info", "VOCAB_TAG", page,
                           f"tag '{t}' not in 05-registry/tags.md (advisory)")


# Thread labels — project-specific; keep in sync with 05-registry/tags.md "Thread labels" section.
# These are EXAMPLE thread labels — replace them with your own project's threads.
THREAD_LABELS = {
    "example-thread-a", "example-thread-b", "example-thread-c",
}


def check_reading_depth(report: LintReport, path: Path, meta: dict) -> None:
    """Advisory (granularity controller — see status-registry reading-status drive rules):
    a `background` paper should cap at `skimmed`; deep-reading it is over-zoom."""
    if is_meta_type(meta) or meta.get("type") != "paper":
        return
    page = page_slug(path)
    rel = meta.get("relevance")
    rs = meta.get("reading-status")
    if rel == "background" and rs in ("deep-read", "cited"):
        report.add("warning", "OVER_READ", page,
                   f"`background` paper at reading-status={rs} — the granularity rule caps "
                   f"`background` at `skimmed` (likely over-zoom; demote relevance or the read).")


# ── Section-graduation (paper-reading-upgrade, 2026-06-26) ───────────────────────
# A type:paper page must carry the body sections its `reading-status` earns. Tokens are
# distinctive words matched case-insensitively against the page's headings, so renaming a
# heading ("Pass 1 — Contract" → "Pass 1: Setup") does NOT false-fail. WARN-ONLY during the
# legacy-page migration window (see module docstring): it is designed to HARDEN to ERROR at
# `reading-status >= read` once the legacy pages are re-deepened. The mapping mirrors the
# LEDGER graduation table (the project's reading-depth design ledger) and the
# section markers in 04-templates/paper.md.
READING_STATUS_ENUM = {"to-read", "skimmed", "read", "deep-read", "cited", "deprecated"}

_GRAD_SKIMMED = [
    ("Stage 0 positioning", ("stage 0", "stage-0", "positioning")),
    ("TL;DR", ("tl;dr", "tldr", "tl dr")),
    ("Pass 1 contract", ("pass 1", "pass-1", "contract")),
]
_GRAD_READ = [
    ("Pass 2 teardown", ("pass 2", "pass-2")),
    ("claim→evidence table", ("claim",)),
    ("method breakdown", ("method",)),
    ("results table", ("result",)),
]
_GRAD_DEEP = [
    ("figure reading", ("figure",)),
    ("Pass 3 appraisal", ("pass 3", "pass-3", "appraisal")),
    ("Stage 4 relations & trend", ("stage 4", "stage-4", "concept network", "trend")),
]
# Cumulative: each rung inherits the rungs below it.
READING_GRADUATION = {
    "skimmed": _GRAD_SKIMMED,
    "read": _GRAD_SKIMMED + _GRAD_READ,
    "deep-read": _GRAD_SKIMMED + _GRAD_READ + _GRAD_DEEP,
    "cited": _GRAD_SKIMMED + _GRAD_READ + _GRAD_DEEP,
}

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def _page_headings(body: str) -> list[str]:
    return [m.group(1).strip().lower() for m in _HEADING_RE.finditer(body)]


def check_reading_status_enum(report: LintReport, path: Path, meta: dict) -> None:
    """READING_STATUS_ENUM (paper-reading-upgrade): a type:paper page's `reading-status`
    must be one of the registry enum values (status-registry §paper.reading-status).
    WARN-only — catches enum drift (e.g. `web-verified-...`, `shallow-read`)."""
    if is_meta_type(meta) or meta.get("type") != "paper":
        return
    rs = meta.get("reading-status")
    if rs in (None, "", []):
        return  # absence is not drift; the template seeds a default
    if str(rs) not in READING_STATUS_ENUM:
        report.add("warning", "READING_STATUS_ENUM", page_slug(path),
                   f"reading-status '{rs}' not in the registry enum "
                   f"{{to-read, skimmed, read, deep-read, cited, deprecated}} "
                   f"(05-registry/status-registry.md §paper.reading-status — fix the drift).")


def check_reading_section_graduation(report: LintReport, path: Path, meta: dict, body: str) -> None:
    """READING_DEPTH (paper-reading-upgrade): a type:paper page must carry the body sections
    its `reading-status` earns. Tolerant heading match (distinctive words, case-insensitive)
    so a heading rename does not false-fail. WARN during the migration window; HARDENS to
    ERROR at reading-status >= read once legacy pages are migrated (see module docstring +
    the LEDGER graduation table)."""
    if is_meta_type(meta) or meta.get("type") != "paper":
        return
    rs = meta.get("reading-status")
    required = READING_GRADUATION.get(str(rs))
    if not required:
        return  # to-read / deprecated / unknown — no graduation floor (enum drift caught separately)
    headings = _page_headings(body)
    missing = [label for label, tokens in required
               if not any(tok in h for h in headings for tok in tokens)]
    if missing:
        report.add("warning", "READING_DEPTH", page_slug(path),
                   f"reading-status={rs} requires sections (cumulative): "
                   f"{', '.join(label for label, _ in required)}; missing: {', '.join(missing)}. "
                   f"WARN during the paper-reading-upgrade migration window — hardens to ERROR at "
                   f"reading-status>=read after legacy pages are migrated.")


def check_bitemporal(report: LintReport, path: Path, meta: dict) -> None:
    """Bi-temporal validity rule (absorption wave 1 — Graphiti invalidate-don't-delete):
    ANY page that sets `invalid-at` MUST set `invalidated-by` — an invalidated page always
    references its invalidator (the refuting / superseding page) and is never deleted.
    Registered as OPTIONAL fields on claim/comparison in the type registry; the rule is
    type-agnostic on purpose (a future type adopting the fields inherits the rule)."""
    if is_meta_type(meta):
        return
    page = page_slug(path)
    invalid_at = meta.get("invalid-at")
    invalidated_by = meta.get("invalidated-by")
    if invalid_at not in (None, "", []) and invalidated_by in (None, "", []):
        report.add("error", "BITEMPORAL", page,
                   "invalid-at is set but invalidated-by is empty — an invalidated page must "
                   "reference its invalidator ([[slug]]); invalidate-don't-delete.")


def check_thread_depth_caps(report: LintReport, pages: list[Path]) -> None:
    """Advisory: per-thread deep-read soft cap ≈ ceil(sqrt(thread_size)) — 'deliberately
    ignore most, deep-read a sqrt-small core'. Never blocks (info only)."""
    total: dict[str, int] = {}
    deep: dict[str, int] = {}
    for p in pages:
        meta, _ = parse_page(p)
        if meta.get("type") != "paper":
            continue
        thread = next((t for t in (meta.get("tags", []) or []) if t in THREAD_LABELS), None)
        if not thread:
            continue
        total[thread] = total.get(thread, 0) + 1
        if meta.get("reading-status") in ("deep-read", "cited"):
            deep[thread] = deep.get(thread, 0) + 1
    for thread, n in total.items():
        cap = math.ceil(n ** 0.5)
        d = deep.get(thread, 0)
        if d > cap:
            report.add("info", "DEEP_READ_CAP", thread,
                       f"{d} deep-reads > soft cap ceil(sqrt({n}))={cap} — granularity rule: "
                       f"deep-read a sqrt-small core, ignore most (advisory).")


def check_source_ref_duplicate(report: LintReport, pages: list[Path]) -> None:
    """M12 — SOURCE_REF_DUPLICATE: detect paper pages that share the same external
    source identifier (doi or url), which indicates the same paper was ingested twice
    under different slugs.

    Severity rules:
    - doi or url values that are non-empty and appear in ≥2 different slugs → ERROR
      (two pages definitely reference the same external resource)
    - title values (normalised: lowercase, strip punct/whitespace) that appear in
      ≥2 different slugs but share no common doi/url → WARNING
      (likely duplicates, but not certain — e.g. a paper and its arXiv preprint may
      carry the same title with legitimately different slugs)

    Scope: only `type: paper` pages are checked. Other types use `source:` for local
    paths, not for globally-unique external identifiers.
    """
    # Collect doi, url, and normalised title per slug for paper pages only.
    doi_map: dict[str, list[str]] = {}   # doi_value → [slug, ...]
    url_map: dict[str, list[str]] = {}   # url_value → [slug, ...]
    title_map: dict[str, list[str]] = {} # normalised_title → [slug, ...]

    _strip_punct = re.compile(r"[^\w\s]")

    def _norm_title(raw: str) -> str:
        return _strip_punct.sub("", raw.lower()).split()
    def _norm_title_key(raw: str) -> str:
        return " ".join(_norm_title(raw))

    for p in pages:
        meta, _ = parse_page(p)
        if meta.get("type") != "paper":
            continue
        slug = page_slug(p)

        doi_val = str(meta.get("doi") or "").strip()
        url_val = str(meta.get("url") or "").strip()
        title_val = str(meta.get("title") or "").strip()

        if doi_val:
            doi_map.setdefault(doi_val, []).append(slug)
        if url_val:
            url_map.setdefault(url_val, []).append(slug)
        if title_val:
            norm = _norm_title_key(title_val)
            if norm:
                title_map.setdefault(norm, []).append(slug)

    # ERROR: shared doi
    for doi_val, slugs in doi_map.items():
        if len(slugs) >= 2:
            report.add(
                "error", "SOURCE_REF_DUPLICATE",
                slugs[0],
                f"doi '{doi_val}' appears in {len(slugs)} pages: {', '.join(slugs)} — "
                f"likely the same paper ingested twice. Merge or remove one.",
            )

    # ERROR: shared url (that is not a doi-already-reported duplicate)
    for url_val, slugs in url_map.items():
        if len(slugs) >= 2:
            report.add(
                "error", "SOURCE_REF_DUPLICATE",
                slugs[0],
                f"url '{url_val}' appears in {len(slugs)} pages: {', '.join(slugs)} — "
                f"likely the same paper ingested twice. Merge or remove one.",
            )

    # WARNING: shared normalised title (only if not already flagged by doi/url above)
    # Build a set of slug-pairs already covered by doi/url errors so we avoid double-reporting.
    already_flagged: set[frozenset[str]] = set()
    for slugs in list(doi_map.values()) + list(url_map.values()):
        if len(slugs) >= 2:
            for i in range(len(slugs)):
                for j in range(i + 1, len(slugs)):
                    already_flagged.add(frozenset({slugs[i], slugs[j]}))

    for norm, slugs in title_map.items():
        if len(slugs) >= 2:
            pairs = [frozenset({slugs[i], slugs[j]})
                     for i in range(len(slugs)) for j in range(i + 1, len(slugs))]
            new_pairs = [p for p in pairs if p not in already_flagged]
            if new_pairs:
                report.add(
                    "warning", "SOURCE_REF_DUPLICATE",
                    slugs[0],
                    f"title '{norm[:80]}' appears in {len(slugs)} pages: {', '.join(slugs)} — "
                    f"possibly the same paper under different slugs. Verify and merge if so.",
                )


def check_review_cycle_overdue(report: LintReport, pages: list[Path]) -> None:
    """L4 — REVIEW_CYCLE_OVERDUE: flag pages that declare a numeric review-cycle but have
    not been reviewed within that many days.

    Behaviour:
    - Only fires when ALL of these are present: `review-cycle:` is a positive integer (or
      a string that parses to one) AND `reviewed:` is a parseable date.
    - `review-cycle: none` (or missing / 0 / negative) → skipped.
    - Advisory warning only — never sets exit code 1 by itself, but contributes to the
      warnings count that the caller may act on.
    - Works independently of `confidence:` level — high-confidence pages with a tight
      review cycle are checked equally.
    """
    today = date.today()

    for p in pages:
        meta, _ = parse_page(p)
        if is_meta_type(meta):
            continue
        page = page_slug(p)

        rc_raw = meta.get("review-cycle")
        if rc_raw is None or str(rc_raw).strip().lower() in ("none", "", "0"):
            continue

        # Parse review-cycle as a positive integer (days).
        try:
            cycle_days = int(str(rc_raw).strip())
        except (ValueError, TypeError):
            continue
        if cycle_days <= 0:
            continue

        # Parse reviewed date.
        reviewed_raw = meta.get("reviewed")
        if not reviewed_raw:
            continue  # no review date recorded — can't determine overdue
        if isinstance(reviewed_raw, datetime):
            reviewed_date = reviewed_raw.date()
        elif isinstance(reviewed_raw, date):
            reviewed_date = reviewed_raw
        elif isinstance(reviewed_raw, str):
            s = str(reviewed_raw).strip()
            if not s:
                continue
            try:
                reviewed_date = datetime.fromisoformat(s).date()
            except ValueError:
                continue
        else:
            continue

        age_days = (today - reviewed_date).days
        if age_days > cycle_days:
            report.add(
                "warning", "REVIEW_CYCLE_OVERDUE", page,
                f"review-cycle={cycle_days}d but last reviewed {age_days}d ago "
                f"(reviewed={reviewed_date}) — schedule a review pass.",
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint the vault.")
    ap.add_argument("--json", action="store_true", help="output JSON instead of text")
    ap.add_argument("--warnings-only", action="store_true",
                    help="don't exit non-zero on errors (treat all as warnings)")
    ap.add_argument("--file", metavar="PATH",
                    help="lint a single file (per-file checks only; skips cross-file checks "
                         "like orphans/broken-links/duplicate-slugs). Used by the write-time hook.")
    args = ap.parse_args(argv)

    report = LintReport()
    types = load_registered_types()
    statuses = load_registered_statuses()
    domains = load_registered_domains()
    tags_vocab = load_registered_tags()

    if args.file:
        fp = Path(args.file)
        if not fp.is_absolute():
            fp = Path.cwd() / fp
        if not fp.exists():
            print(f"file not found: {fp}", file=sys.stderr)
            return 2
        meta, body = parse_page(fp)
        check_universal_frontmatter(report, fp, meta)
        check_type(report, fp, meta, types)
        check_status(report, fp, meta, statuses)
        check_stub(report, fp, meta, body)
        check_stale_low_confidence(report, fp, meta)
        check_citation_gate(report, fp, meta)
        check_vocab(report, fp, meta, domains, tags_vocab)
        check_reading_depth(report, fp, meta)
        check_reading_status_enum(report, fp, meta)
        check_reading_section_graduation(report, fp, meta, body)
        check_bitemporal(report, fp, meta)
        check_review_cycle_overdue(report, [fp])
        # Cross-file checks (orphans / broken links / duplicate slugs / source-ref-duplicate)
        # need the whole vault and are intentionally skipped in single-file mode (used by the
        # write-time hook).
    else:
        pages = collect_pages()
        for p in pages:
            meta, body = parse_page(p)
            check_universal_frontmatter(report, p, meta)
            check_type(report, p, meta, types)
            check_status(report, p, meta, statuses)
            check_stub(report, p, meta, body)
            check_stale_low_confidence(report, p, meta)
            check_citation_gate(report, p, meta)
            check_vocab(report, p, meta, domains, tags_vocab)
            check_reading_depth(report, p, meta)
            check_reading_status_enum(report, p, meta)
            check_reading_section_graduation(report, p, meta, body)
            check_bitemporal(report, p, meta)
            check_review_cycle_overdue(report, [p])
        check_links_and_orphans(report, pages)
        check_duplicate_slugs(report, pages)
        check_thread_depth_caps(report, pages)
        check_source_ref_duplicate(report, pages)

    if args.json:
        out = {
            "errors": [vars(e) for e in report.errors],
            "warnings": [vars(e) for e in report.warnings],
            "infos": [vars(e) for e in report.infos],
            "summary": report.summary(),
        }
        print(json.dumps(out, indent=2))
    else:
        scope = f"file {args.file}" if args.file else "vault"
        print(f"\n=== Lint Report ({scope}) — {date.today()} ===\n")
        for bucket_name, bucket in (("ERRORS", report.errors), ("WARNINGS", report.warnings), ("INFO", report.infos)):
            if not bucket:
                continue
            print(f"\n{bucket_name} ({len(bucket)}):\n")
            for e in bucket:
                print(f"  [{e.code}] {e.page}: {e.detail}")
        print(f"\n{report.summary()}\n")

    if report.errors and not args.warnings_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
