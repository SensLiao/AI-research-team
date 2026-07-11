"""Deterministic source→vault migration tool — conforms a typed Obsidian source vault to the
DB's universal schema, dedups against the live vault, and reconciles every page into exactly
one bucket (MIGRATE / DEDUP / FLAG).

Single source of truth for the schema is the DATABASE's own `05-registry/type-registry.md`,
parsed via the EXISTING `tools/vault_page_contract.py` — this module keeps NO parallel hardcoded
copy of the type contract. It only adds: (a) source-frontmatter conforming (inject `project`,
coerce `status`/`confidence` where a clear mapping exists), (b) dedup against the target vault,
(c) a verbatim body-hash losslessness proof.

Design discipline (mirrors `tools/promote.py`):
  - PURE where it can be: `parse_page`, `conform_frontmatter`, `normalize_title`,
    `body_sha256`, `classify_page`, `reconcile`. No I/O, no global state.
  - I/O ISOLATED: `scan_source_vault`, `scan_target_slugs`, `run_migration` do the reads;
    writes are confined to an explicit out-dir in dry-run, and the real-vault write path is
    fail-closed behind `--commit --confirm` (NOT invoked by the migration task).
  - FAIL-CLOSED: a page that cannot fully conform is FLAGged, never written; a `--commit` with
    no confirm token raises `CommitNotConfirmed` BEFORE any filesystem mutation.

The DB is the crown jewels: this module never writes `02-wiki/` unless commit+confirm are both
set AND `--i-understand-this-writes-the-real-vault` is passed at the CLI. The migration task uses
dry-run only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

# Reuse the DB-page conformance contract — the authoritative schema, parsed from the live registry.
from research_agent_teams.tools import vault_page_contract as vpc

# Knowledge directories under a source wiki/ that hold migratable typed pages. Underscore dirs
# (_templates / _registry / _routing / _indexes / _bases) and nested `_data` are scaffolding/meta.
_META_DIR_PREFIX = "_"
# README.md (any case) is a meta orientation doc (type: readme) — excluded from migration scope.
_META_FILENAMES = frozenset({"readme.md", "index.md"})

# Status coercion: clear, lossless mappings from common source values to the universal enum
# (schema-contract §4). Anything NOT here is LEFT AS-IS so the contract validator FLAGs it.
_STATUS_COERCE = {
    "superseded": "deprecated",   # superseded-by-another-page == deprecated in the universal enum
    "archived": "deprecated",
    "in-progress": "active",
    "in_progress": "active",
    "wip": "draft",
    "done": "completed",
    "blocked": "parked",
    "paused": "parked",
}

# Confidence coercion: clear synonyms only; unknowns LEFT for FLAG.
_CONFIDENCE_COERCE = {
    "hi": "high",
    "h": "high",
    "med": "medium",
    "mid": "medium",
    "m": "medium",
    "lo": "low",
    "l": "low",
    "unknown": "unverified",
    "tbd": "unverified",
    "none": "unverified",
}

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_TITLE_NORM_STRIP = re.compile(r"[^a-z0-9]+")


class CommitNotConfirmed(RuntimeError):
    """Raised when a real-vault write is requested without the explicit confirm token."""


# --------------------------------------------------------------------------- #
# PURE — parsing / conforming / hashing / dedup keys
# --------------------------------------------------------------------------- #

def parse_page(text: str) -> Tuple[dict, str]:
    """Split a markdown page into (frontmatter dict, body str). Pure.

    Body is everything AFTER the closing `---` delimiter, returned VERBATIM (this is the string
    whose sha256 proves losslessness). A page with no frontmatter → ({}, whole text)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_fm = match.group(1)
    body = text[match.end():]
    # Some source pages embed markdown blockquote callouts (`> **⚠️ REFRESHED…**`,
    # `> **SUPERSEDED…**`) INSIDE their frontmatter. A bare `>` line is NOT valid YAML — it
    # opens a block scalar with no key, so yaml.safe_load raises "while scanning a block scalar"
    # and a fully-typed page would be silently lost (empty fm → wrongly FLAGged). Strip those
    # decorator lines before parsing, but PRESERVE their text in an added `provenance-note`
    # field so the migration stays lossless (frontmatter rule: only-add-never-delete). `#`
    # comment lines are valid YAML and are left untouched.
    callout_lines = [ln for ln in raw_fm.splitlines() if ln.lstrip().startswith(">")]
    cleaned = "\n".join(ln for ln in raw_fm.splitlines() if not ln.lstrip().startswith(">"))
    try:
        fm = yaml.safe_load(cleaned) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    if callout_lines and fm and "provenance-note" not in fm:
        notes = [ln.lstrip().lstrip(">").strip() for ln in callout_lines]
        fm["provenance-note"] = [n for n in notes if n]
    return fm, body


def body_sha256(body: str) -> str:
    """Stable losslessness fingerprint of a page body."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def normalize_title(title: object) -> str:
    """Normalize a title for dedup matching: lowercase, strip non-alphanumerics. Pure."""
    if title is None:
        return ""
    return _TITLE_NORM_STRIP.sub("", str(title).lower())


def conform_frontmatter(frontmatter: dict, *, project: str) -> dict:
    """Return a NEW conformed frontmatter dict (immutability — never mutate the input).

    - inject `project` if absent/empty (never overwrite an existing project)
    - coerce `status` / `confidence` ONLY where a clear lossless mapping exists; otherwise leave
      the value untouched so `validate_page` flags it (no silent normalization of unknowns).
    Pure: deterministic, no I/O.
    """
    out = dict(frontmatter or {})

    if vpc._empty(out.get("project")):
        out["project"] = project

    status = out.get("status")
    if isinstance(status, str) and status not in vpc.STATUS_VALUES:
        coerced = _STATUS_COERCE.get(status.strip().lower())
        if coerced:
            out["status"] = coerced

    conf = out.get("confidence")
    if isinstance(conf, str) and conf not in vpc.CONFIDENCE_VALUES:
        coerced = _CONFIDENCE_COERCE.get(conf.strip().lower())
        if coerced:
            out["confidence"] = coerced

    return out


# Director content-status policy (2026-06-16): the migration filters by CONTENT correctness, not
# just schema completeness. A page marked wrong/old never enters the crown jewels.
#   - result-status ∈ DROP → the result is wrong / superseded / unaudited → never migrate.
#   - result-status == frozen → audited + citable tier → full migrate (can-cite kept).
#   - result-status == provisional → ran correct, not human-blessed → migrate as reference
#     (can-cite-thesis forced false; audit fields may legitimately be absent).
#   - any other / missing result-status → unknown validity → FLAG (manual review, never auto-add).
_DROP_RESULT_STATUS = frozenset({"invalid", "superseded", "missing-audit"})
_FROZEN_RESULT_STATUS = frozenset({"frozen"})
_REF_RESULT_STATUS = frozenset({"provisional"})


def _drop_reason(frontmatter: dict) -> Optional[str]:
    """Return a DROP reason if the page is marked wrong/old, else None. Pure.

    Two axes: universal `status: deprecated` (superseded/archived already coerced to it by
    conform_frontmatter), and type-specific `result-status` ∈ {invalid, superseded, missing-audit}.
    """
    if frontmatter.get("status") == "deprecated":
        return "status:deprecated"
    rs = frontmatter.get("result-status")
    if isinstance(rs, str) and rs in _DROP_RESULT_STATUS:
        return f"result-status:{rs}"
    return None


def classify_page(*, slug: str, frontmatter: dict, body: str,
                  contract: Dict[str, List[str]],
                  target_slugs: Set[str], target_titles: Set[str]) -> dict:
    """Bucket a page → MIGRATE / MIGRATE_REF / DEDUP / FLAG / DROP. Pure.

    Priority: DEDUP (already in vault → link, never re-judge) > DROP (marked wrong/old → never add)
    > content classification. See `_drop_reason` and the policy note above. Returns
    {slug, bucket, type, violations, body_hash, dedup_key?, drop_reason?}.
    """
    hashed = body_sha256(body)
    title_key = normalize_title(frontmatter.get("title"))
    is_dup = slug in target_slugs or (title_key and title_key in target_titles)
    if is_dup:
        return {
            "slug": slug, "bucket": "DEDUP", "type": frontmatter.get("type"),
            "violations": [], "body_hash": hashed,
            "dedup_key": slug if slug in target_slugs else f"title:{title_key}",
        }

    reason = _drop_reason(frontmatter)
    if reason:
        return {"slug": slug, "bucket": "DROP", "type": frontmatter.get("type"),
                "violations": [], "body_hash": hashed, "drop_reason": reason}

    t = frontmatter.get("type")

    # result type: gate strictly by result-status (director policy)
    if t == "result":
        rs = frontmatter.get("result-status")
        if rs in _FROZEN_RESULT_STATUS:                 # citable tier — trust it; ref-fallback if incomplete
            res = vpc.validate_page(frontmatter, contract=contract)
            return {"slug": slug, "bucket": "MIGRATE" if res["ok"] else "MIGRATE_REF",
                    "type": t, "violations": res["violations"], "body_hash": hashed}
        if rs in _REF_RESULT_STATUS:                    # provisional → reference (can-cite:false)
            univ = vpc.validate_page(frontmatter, contract=contract, check_type_specific=False)
            if not univ["ok"]:                          # missing core fields → cannot migrate
                return {"slug": slug, "bucket": "FLAG", "type": t,
                        "violations": univ["violations"], "body_hash": hashed}
            return {"slug": slug, "bucket": "MIGRATE_REF", "type": t,
                    "violations": [], "body_hash": hashed}
        # missing / unknown result-status → unknown validity; full-validate to surface gaps, FLAG
        res = vpc.validate_page(frontmatter, contract=contract)
        return {"slug": slug, "bucket": "FLAG", "type": t,
                "violations": res["violations"], "body_hash": hashed}

    # non-result types: universal-valid pages enter (full → MIGRATE, partial → reference)
    univ = vpc.validate_page(frontmatter, contract=contract, check_type_specific=False)
    if not univ["ok"]:
        return {"slug": slug, "bucket": "FLAG", "type": univ["type"],
                "violations": univ["violations"], "body_hash": hashed}
    full = vpc.validate_page(frontmatter, contract=contract)
    if full["ok"]:
        return {"slug": slug, "bucket": "MIGRATE", "type": full["type"],
                "violations": [], "body_hash": hashed}
    return {"slug": slug, "bucket": "MIGRATE_REF", "type": full["type"],
            "violations": full["violations"], "body_hash": hashed}


def reconcile(classified: List[dict]) -> dict:
    """Build the reconciliation report and ASSERT the partition is exact. Pure.

    Every page lands in exactly one of 5 buckets → migrate+migrate_ref+dedup+flag+drop == total.
    """
    total = len(classified)
    migrate = [c for c in classified if c["bucket"] == "MIGRATE"]
    migrate_ref = [c for c in classified if c["bucket"] == "MIGRATE_REF"]
    dedup = [c for c in classified if c["bucket"] == "DEDUP"]
    flag = [c for c in classified if c["bucket"] == "FLAG"]
    drop = [c for c in classified if c["bucket"] == "DROP"]

    counted = len(migrate) + len(migrate_ref) + len(dedup) + len(flag) + len(drop)
    if counted != total:
        raise AssertionError(
            f"reconciliation broken: migrate({len(migrate)})+ref({len(migrate_ref)})+"
            f"dedup({len(dedup)})+flag({len(flag)})+drop({len(drop)}) = {counted} != total {total}")
    # also assert no page silently fell into an unknown bucket
    buckets = {c["bucket"] for c in classified}
    stray = buckets - {"MIGRATE", "MIGRATE_REF", "DEDUP", "FLAG", "DROP"}
    if stray:
        raise AssertionError(f"reconciliation broken: stray buckets {stray}")

    return {
        "total": total,
        "migrate": len(migrate),
        "migrate_ref": len(migrate_ref),
        "dedup": len(dedup),
        "flag": len(flag),
        "drop": len(drop),
        "flagged": [{"slug": c["slug"], "violations": c["violations"]} for c in flag],
        "dropped": [{"slug": c["slug"], "reason": c.get("drop_reason")} for c in drop],
        "ref": [{"slug": c["slug"], "type": c["type"]} for c in migrate_ref],
        # body-hash preserved: every classified page produced a stable body fingerprint
        "body_hash_preserved": all(
            isinstance(c.get("body_hash"), str) and c["body_hash"].startswith("sha256:")
            for c in classified),
    }


# --------------------------------------------------------------------------- #
# I/O ISOLATED — scanning + the dry-run / commit runner
# --------------------------------------------------------------------------- #

def load_contract_for(vault_root) -> Dict[str, List[str]]:
    """Thin wrapper over vault_page_contract.load_contract (single registry read)."""
    return vpc.load_contract(vault_root)


def load_type_folders(vault_root) -> Dict[str, str]:
    """Parse {type: folder} from the registry's knowledge-note table ('Folder' column).

    Folder placement is a registry CONVENTION (not a hard constraint), but using the registry's
    canonical folder avoids naive mis-pluralization (`synthesis`→`synthesiss`, `entity`→`entitys`,
    `process-memory`→`process-memorys`). Unknown types fall back to `<type>s` at the call site.
    Returns {} if the registry is unreadable (caller falls back)."""
    folders: Dict[str, str] = {}
    try:
        text = (Path(vault_root) / "05-registry" / "type-registry.md").read_text(encoding="utf-8")
    except OSError:
        return folders
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = vpc._cells(line)
        if len(cells) != 5 or not cells[0].startswith("`"):
            continue
        t = cells[0].strip("` ").strip()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", t):
            continue
        folder = cells[1].strip(" `").rstrip("/").strip(" `")
        if folder and "/" not in folder:
            folders[t] = folder
    return folders


def _is_meta_path(rel: Path) -> bool:
    """A source-relative path that is scaffolding/meta (skip from migration scope)."""
    if any(part.startswith(_META_DIR_PREFIX) for part in rel.parts):
        return True
    if rel.name.lower() in _META_FILENAMES:
        return True
    return False


def scan_source_vault(source_wiki: Path) -> List[Tuple[str, str]]:
    """Read every migratable source page → list of (slug, raw_text), sorted (deterministic).

    `slug` is the file basename without `.md` (the TARGET vault nests by topic dir, so dedup is
    basename-keyed). Meta/scaffolding files are excluded.
    """
    source_wiki = Path(source_wiki)
    out: List[Tuple[str, str]] = []
    for path in sorted(source_wiki.rglob("*.md")):
        rel = path.relative_to(source_wiki)
        if _is_meta_path(rel):
            continue
        out.append((path.stem, path.read_text(encoding="utf-8")))
    return out


def scan_target_slugs(target_wiki: Path) -> Tuple[Set[str], Set[str]]:
    """Read the existing TARGET vault → (set of basename slugs, set of normalized titles).

    READ-ONLY. Used purely for the dedup check; the target vault is never modified here.
    """
    target_wiki = Path(target_wiki)
    slugs: Set[str] = set()
    titles: Set[str] = set()
    if not target_wiki.exists():
        return slugs, titles
    for path in sorted(target_wiki.rglob("*.md")):
        if path.name.lower() in _META_FILENAMES:
            continue
        slugs.add(path.stem)
        try:
            fm, _ = parse_page(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        tkey = normalize_title(fm.get("title"))
        if tkey:
            titles.add(tkey)
    return slugs, titles


def _render_page(frontmatter: dict, body: str) -> str:
    """Reassemble a page: conformed frontmatter + VERBATIM body (body bytes untouched)."""
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return "---\n" + fm_yaml + "---\n" + body


def _path_within(child, root) -> bool:
    """True iff `child` resolves inside `root` (mirrors promote.py::_path_within — defence-in-depth so
    a resolved page path can never escape 02-wiki/ into a crown-jewel contract even if a check above
    is bypassed)."""
    c = os.path.normcase(os.path.normpath(os.path.abspath(str(child))))
    r = os.path.normcase(os.path.normpath(os.path.abspath(str(root))))
    return c == r or c.startswith(r + os.sep)


def _append_line(path: Path, line: str) -> None:
    """Append one line to a vault index/log file (create parent dir if missing). Mirrors promote.py —
    append-only, never rewrites the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = path.read_text(encoding="utf-8") if path.exists() else ""
    if prev and not prev.endswith("\n"):
        prev += "\n"
    path.write_text(prev + line + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# LINK REBUILD — curated clean import (no broken links). The lint flags BROKEN_LINK only on body
# [[ ]] and the `related:` list, so those are the only two surfaces we rewrite.
# --------------------------------------------------------------------------- #

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _link_target(inner: str) -> str:
    """The resolvable slug token of a wikilink inner `slug|alias` / `slug#anchor`, lowercased."""
    return inner.split("|", 1)[0].split("#", 1)[0].strip().lower()


def rewrite_body_links(body: str, resolvable: Set[str], redirects: Dict[str, str]) -> str:
    """Rewrite body [[ ]]: resolvable → keep; redirected → [[newslug]] (anchor/alias kept); else
    DE-LINK to plain text (alias if present, else the slug display). An unresolvable link can never
    survive as a [[ ]], so the lint's WIKILINK scan sees no broken link."""
    def repl(mt: "re.Match") -> str:
        inner = mt.group(1)
        tgt = _link_target(inner)
        if tgt in resolvable:
            return mt.group(0)
        link, sep, alias = inner.partition("|")
        slug_part, asep, anchor = link.partition("#")
        if tgt in redirects:
            rest = (("#" + anchor) if asep else "") + (("|" + alias) if sep else "")
            return f"[[{redirects[tgt]}{rest}]]"
        return alias.strip() if sep else slug_part.strip()
    return _WIKILINK_RE.sub(repl, body)


def rewrite_related_list(related, resolvable: Set[str], redirects: Dict[str, str]) -> List:
    """Rewrite a `related:` list: resolvable kept; redirected re-pointed; unresolvable DROPPED (the
    lint resolves related entries with or without [[ ]], so de-linking to text is not enough)."""
    out: List = []
    for r in related or []:
        s = str(r).strip()
        inner = s[2:-2] if (s.startswith("[[") and s.endswith("]]")) else s
        tgt = _link_target(inner)
        if tgt in resolvable:
            out.append(r)
        elif tgt in redirects:
            out.append(f"[[{redirects[tgt]}]]")
    return out


def _vault_resolvable(target_wiki, migrated_fms: Dict[str, Tuple[dict, str]]) -> Set[str]:
    """Lowercased link tokens that resolve in the FINAL vault = existing target pages + migrated
    pages, each contributing its slug + any `aliases`. Mirrors the lint's slug/alias resolution."""
    resolvable: Set[str] = set()
    tw = Path(target_wiki)
    if tw.exists():
        for p in tw.rglob("*.md"):
            if p.name.lower() in _META_FILENAMES:
                continue
            resolvable.add(p.stem.lower())
            try:
                fm, _ = parse_page(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            for a in (fm.get("aliases") or []):
                resolvable.add(str(a).strip().lower())
    for slug, (fm, _) in migrated_fms.items():
        resolvable.add(slug.lower())
        for a in (fm.get("aliases") or []):
            resolvable.add(str(a).strip().lower())
    return resolvable


def run_migration(*, source_wiki, target_wiki, contract_vault_root,
                  project: str, out_dir: Optional[object], dry_run: bool = True,
                  commit: bool = False, confirm: bool = False,
                  link_redirects: Optional[dict] = None) -> dict:
    """Run the migration end-to-end and return the reconciliation report.

    dry_run=True (default): MIGRATE pages are written under `out_dir` (a tempdir), and a temp
    `_migration-index.md` / `_migration-log.md` copy is written there too. The real vault is
    NEVER touched.

    commit=True: real-vault write path — fail-closed. Requires `confirm=True`; otherwise raises
    `CommitNotConfirmed` before any I/O. (Not invoked by the migration task.)
    """
    if commit and not dry_run and not confirm:
        raise CommitNotConfirmed(
            "real-vault write requested without confirm token — refusing. "
            "Pass --commit --confirm --i-understand-this-writes-the-real-vault.")

    contract = load_contract_for(contract_vault_root)
    folders = load_type_folders(contract_vault_root)
    target_slugs, target_titles = scan_target_slugs(target_wiki)

    pages = scan_source_vault(source_wiki)
    classified: List[dict] = []
    conformed_by_slug: Dict[str, Tuple[dict, str]] = {}
    dropped_sup: Dict[str, str] = {}   # dropped slug → declared replacement (superseded-by/invalidated-by)

    for slug, raw in pages:
        fm, body = parse_page(raw)
        conformed = conform_frontmatter(fm, project=project)
        res = classify_page(slug=slug, frontmatter=conformed, body=body,
                            contract=contract, target_slugs=target_slugs,
                            target_titles=target_titles)
        classified.append(res)
        if res["bucket"] in ("MIGRATE", "MIGRATE_REF"):
            to_write = dict(conformed)
            if conformed.get("type") == "result":
                # can-cite-thesis is DERIVED, NEVER trusted from the source self-claim (vault rule +
                # lint CITATION_GATE): citable IFF frozen ∧ leakage:pass ∧ fairness:pass. Repairs an
                # under-claim (frozen+audited but source said false) and blocks an over-claim alike.
                to_write["can-cite-thesis"] = (
                    conformed.get("result-status") == "frozen"
                    and conformed.get("leakage-audit") == "pass"
                    and conformed.get("fairness-audit") == "pass"
                )
            else:
                # close the citation-gate bypass hole: result-gate fields must not ride on a
                # non-result page (lint CITATION_GATE) — they are misplaced there. Strip them.
                for _rf in ("result-status", "can-cite-thesis"):
                    to_write.pop(_rf, None)
            conformed_by_slug[slug] = (to_write, body)
        elif res["bucket"] == "DROP":
            for _k in ("superseded-by", "invalidated-by"):
                _mm = re.search(r"\[\[([^\]\|#]+)", str(conformed.get(_k) or ""))
                if _mm:
                    dropped_sup[slug.lower()] = _mm.group(1).strip().lower()
                    break

    report = reconcile(classified)

    # ---- LINK REBUILD (director 2026-06-16: curated clean import — zero broken links) ----
    # Rewrite every migrated page's body [[ ]] + `related:` so each link either resolves, is
    # redirected to a migrated replacement (a dropped page's own superseded-by/invalidated-by, or a
    # smart reconnect injected via `link_redirects`), or is de-linked. Bodies are NO LONGER
    # byte-verbatim — this is the authorized curation ("整理一份干净的"), not a lossless copy.
    resolvable = _vault_resolvable(target_wiki, conformed_by_slug)
    eff_redirects: Dict[str, str] = {}
    for _src, _dst in {**dropped_sup, **(link_redirects or {})}.items():
        _s, _d = str(_src).lower(), str(_dst).lower()
        if _d in resolvable:
            eff_redirects[_s] = _d
    _rebuilt: Dict[str, Tuple[dict, str]] = {}
    for _slug, (_fm, _body) in conformed_by_slug.items():
        _nfm = dict(_fm)
        if _nfm.get("related"):
            _nr = rewrite_related_list(_nfm.get("related"), resolvable, eff_redirects)
            if _nr:
                _nfm["related"] = _nr
            else:
                _nfm.pop("related", None)
        _rebuilt[_slug] = (_nfm, rewrite_body_links(_body, resolvable, eff_redirects))
    conformed_by_slug = _rebuilt

    # source-ref de-dup (lint SOURCE_REF_DUPLICATE): a `url` must not appear on >1 migrated page —
    # keep it on the lexicographically-first slug (the canonical paper), strip it from the rest (a
    # supplementary / duplicate page loses the duplicate claim).
    _by_url: Dict[str, List[str]] = {}
    for _slug, (_fm, _) in conformed_by_slug.items():
        _u = _fm.get("url")
        if _u:
            _by_url.setdefault(str(_u).strip(), []).append(_slug)
    _url_deduped = 0
    for _u, _slugs in _by_url.items():
        if len(_slugs) > 1:
            for _slug in sorted(_slugs)[1:]:
                _fm, _body = conformed_by_slug[_slug]
                _nf = dict(_fm)
                _nf.pop("url", None)
                conformed_by_slug[_slug] = (_nf, _body)
                _url_deduped += 1
    report["_link_rebuild"] = {"resolvable_tokens": len(resolvable),
                               "redirects_applied": len(eff_redirects),
                               "url_deduped": _url_deduped}

    if dry_run:
        if out_dir is None:
            raise ValueError("dry_run requires an out_dir to write MIGRATE pages into")
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for slug, (conformed, body) in sorted(conformed_by_slug.items()):
            vtype = conformed.get("type") or "page"
            fname = folders.get(vtype, vtype + "s")
            folder = out / fname
            folder.mkdir(parents=True, exist_ok=True)
            page_path = folder / f"{slug}.md"
            page_path.write_text(_render_page(conformed, body), encoding="utf-8")
            written.append(f"{fname}/{slug}.md")
        # temp index/log COPIES (never the real 00-system/index.md or 07-logs/log.md)
        (out / "_migration-index.md").write_text(
            "# Migration index (DRY-RUN, temp copy)\n\n" +
            "\n".join(f"- MIGRATE [[{s}]]" for s in sorted(conformed_by_slug)) + "\n",
            encoding="utf-8")
        (out / "_migration-log.md").write_text(
            "# Migration log (DRY-RUN, temp copy)\n\n" + json.dumps(report, indent=2) + "\n",
            encoding="utf-8")
        report["_written"] = written
        report["_out_dir"] = str(out)
    elif commit and confirm:
        # Real-vault write — page→page copy of every MIGRATE / MIGRATE_REF page into 02-wiki/<type>s/.
        # Crown-jewel discipline (mirrors promote.py): every resolved path MUST stay inside 02-wiki/;
        # the schema contracts (00-system except index/hot/README, 05-registry, 04-templates, 01-raw)
        # are NEVER touched. DEDUP/FLAG/DROP pages are never written. Bodies are byte-verbatim (only
        # the conformed frontmatter is re-rendered). index.md + log.md are appended (vault discipline).
        wiki_root = Path(target_wiki)
        written: List[str] = []
        for slug, (conformed, body) in sorted(conformed_by_slug.items()):
            vtype = conformed.get("type") or "page"
            fname = folders.get(vtype, vtype + "s")
            page_path = wiki_root / fname / f"{slug}.md"
            if not _path_within(page_path, wiki_root):
                raise ValueError(f"refusing commit: resolved path {page_path} escapes 02-wiki/")
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(_render_page(conformed, body), encoding="utf-8")
            written.append(f"{fname}/{slug}.md")
        vault_root_p = wiki_root.parent
        _append_line(vault_root_p / "00-system" / "index.md",
                     f"- migration `{project}`: +{len(written)} pages "
                     f"(MIGRATE {report['migrate']} + REF {report['migrate_ref']}; "
                     f"dropped {report['drop']}, dedup {report['dedup']}, flag {report['flag']})")
        for w in sorted(written):
            _append_line(vault_root_p / "00-system" / "index.md", f"  - [[{Path(w).stem}]]")
        _append_line(vault_root_p / "07-logs" / "log.md",
                     f"MIGRATE-BULK `{project}`: +{len(written)} pages "
                     f"(dropped {report['drop']}, dedup {report['dedup']}, flag {report['flag']})")
        report["_written"] = written
        report["_committed"] = True

    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Deterministic source→vault migration (dry-run reconciliation by default).")
    p.add_argument("--source", required=True, help="path to the source wiki/ directory")
    p.add_argument("--target-vault-root", required=True,
                   help="path to the PhD-Research-OS root (contains 02-wiki/ + 05-registry/)")
    p.add_argument("--project", default="iac-cbct-seg", help="project slug to inject")
    p.add_argument("--dry-run", action="store_true", help="dry-run (write MIGRATE pages to --out)")
    p.add_argument("--out", help="temp output directory for dry-run writes")
    # real-vault write path — triple-gated, NOT used by the migration task
    p.add_argument("--commit", action="store_true", help="REAL write (requires --confirm)")
    p.add_argument("--confirm", action="store_true", help="confirm a real-vault write")
    p.add_argument("--i-understand-this-writes-the-real-vault", action="store_true",
                   dest="understood", help="final explicit ack for a real write")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    target_root = Path(args.target_vault_root)
    target_wiki = target_root / "02-wiki"

    if args.commit:
        if not (args.confirm and args.understood):
            raise CommitNotConfirmed(
                "real-vault commit requires --confirm AND "
                "--i-understand-this-writes-the-real-vault")
        report = run_migration(
            source_wiki=args.source, target_wiki=target_wiki,
            contract_vault_root=target_root, project=args.project,
            out_dir=None, dry_run=False, commit=True, confirm=True)
    else:
        report = run_migration(
            source_wiki=args.source, target_wiki=target_wiki,
            contract_vault_root=target_root, project=args.project,
            out_dir=args.out, dry_run=True)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
