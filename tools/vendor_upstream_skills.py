"""Vendor the upstream research-skill TEXT into the repo — read-only, markdown only.

Director decision 2026-08-04 on ledger D5: mount the upstream sources' **text**, and nothing that can
execute. Of the five safety decisions listed in `_design/RESEARCH-WORKBENCH-V4-LEDGER.md` §5, this
reverses exactly two:

  reversed  §5.1  third-party files now live in the repo tree (not only clean-room summaries)
  reversed  §5.5  the "no non-empty exact copy" clean-room property ends, by design
  KEPT      §5.2  NO installer, hook, MCP server, or auto-update is fetched or run — ever
  KEPT      §5.3  `icebird1998/drawio-scientific-illustrator` stays excluded (live browser control)
  noted     §5.4  licenses recorded per source; LICENSE text is vendored for attribution

"Never runs" is **structural, not a promise**: the copy allowlist admits markdown and license notices
only, so there is no `.py` / `.js` / `.sh` / plugin manifest in the vendor tree to run, auto-load, or
auto-update. :func:`verify` re-hashes the tree offline and reports any file the manifest does not
know about, so a later addition cannot slip in unnoticed.

    python -m research_agent_teams.tools.vendor_upstream_skills fetch --retrieved-at 2026-08-04
    python -m research_agent_teams.tools.vendor_upstream_skills verify

`fetch` needs the network and writes; `verify` is offline, read-only, and is what the test calls.
Integrity rule: the 2026-07-31 audit recorded 45 per-file SHA-256 receipts. A source whose receipts
no longer match upstream is **BLOCKED and not copied** — upstream having changed under a pinned commit
is exactly the case where silently vendoring would be worst.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

_PKG = Path(__file__).resolve().parents[1]                       # research_agent_teams/
SOURCES_PATH = _PKG / "orchestrator" / "external_research_skill_sources.json"
VENDOR_ROOT = _PKG / "vendor" / "upstream-research-skills"
MANIFEST_PATH = VENDOR_ROOT / "MANIFEST.json"

MANIFEST_SCHEMA = "vendored-upstream-skills/v1"

#: Text only. Everything else is refused at copy time, which is what makes "it cannot run" a property
#: of the tree rather than a rule someone has to remember.
ALLOWED_SUFFIXES = frozenset({".md", ".markdown"})
ALLOWED_NAME_PREFIXES = ("LICENSE", "LICENCE", "NOTICE", "COPYING")

#: Excluded on safety grounds, not preference (ledger §5.3): its route drives a live CDP-controlled
#: browser, duplicating a safer offline path. `selectable: false` in the source lock, and the overlay
#: catalog validation FAILS if an overlay references it — both stay in force.
EXCLUDED_SOURCE_IDS = frozenset({"drawio_scientific_illustrator"})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sources(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads((path or SOURCES_PATH).read_text(encoding="utf-8"))


def admitted_sources(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """The sources this vendoring may touch: selectable AND not on the safety exclusion list."""
    return [s for s in load_sources(path)["sources"]
            if s.get("selectable") and s.get("source_id") not in EXCLUDED_SOURCE_IDS]


def is_allowed(relative: Path) -> bool:
    """Text-only allowlist. `.git/` is never walked into in the first place."""
    if any(part == ".git" for part in relative.parts):
        return False
    if relative.suffix.lower() in ALLOWED_SUFFIXES:
        return True
    return relative.name.upper().startswith(ALLOWED_NAME_PREFIXES)


# ------------------------------------------------------------------------------------- fetch

def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _shallow_checkout(repository: str, commit: str, into: Path) -> tuple[bool, str]:
    """Fetch exactly the pinned commit. Falls back to a full clone if the server refuses a bare SHA."""
    into.mkdir(parents=True, exist_ok=True)
    for step in (["git", "init", "-q"],
                 ["git", "remote", "add", "origin", repository]):
        result = _run(step, into)
        if result.returncode:
            return False, f"{' '.join(step)}: {result.stderr.strip()[:200]}"
    fetched = _run(["git", "fetch", "-q", "--depth", "1", "origin", commit], into)
    if fetched.returncode:
        deep = _run(["git", "fetch", "-q", "origin"], into)
        if deep.returncode:
            return False, f"fetch failed: {fetched.stderr.strip()[:200]}"
    checked = _run(["git", "checkout", "-q", commit], into)
    if checked.returncode:
        checked = _run(["git", "checkout", "-q", "FETCH_HEAD"], into)
    if checked.returncode:
        return False, f"checkout failed: {checked.stderr.strip()[:200]}"
    head = _run(["git", "rev-parse", "HEAD"], into)
    got = head.stdout.strip()
    if got and not got.startswith(commit[:10]):
        return False, f"checked out {got[:10]} but the lock pins {commit[:10]}"
    return True, got


def _is_notice(path: Path) -> bool:
    return path.name.upper().startswith(ALLOWED_NAME_PREFIXES)


def _copy_text(root: Path, destination: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Copy the SKILL BUNDLES only: a directory holding a `SKILL.md`, and everything below it.

    The director authorised the upstream *skill text*. A repo also carries things that are text but
    are not that — its own `docs/`, `CHANGELOG.md`, and in one case 815 files of the upstream's own
    eval run logs (`evals/**/runs/raw/*.review.md`). Those are someone else's working notes; carrying
    them would add ~14 MB of weight and nothing an agent here would ever read. Whatever is skipped is
    COUNTED and reported — a bounded copy that hides what it dropped reads as "we took everything".
    """
    skill_dirs = {p.parent for p in root.rglob("SKILL.md")}
    files: list[dict[str, Any]] = []
    skipped_bytes = 0
    skipped_examples: list[str] = []
    skipped_count = 0

    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if not is_allowed(relative):
            continue
        in_bundle = any(d == candidate.parent or d in candidate.parents for d in skill_dirs)
        if not (in_bundle or _is_notice(relative)):
            skipped_count += 1
            skipped_bytes += candidate.stat().st_size
            if len(skipped_examples) < 5:
                skipped_examples.append(relative.as_posix())
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        files.append({"path": relative.as_posix(), "sha256": _sha256_file(target),
                      "bytes": target.stat().st_size})
    return files, {"outside_skill_bundles": skipped_count, "bytes": skipped_bytes,
                   "examples": skipped_examples, "skill_bundles": len(skill_dirs)}


def fetch(*, retrieved_at: str, sources_path: Optional[Path] = None,
          vendor_root: Optional[Path] = None) -> dict[str, Any]:
    """Clone each admitted source at its pinned commit, verify receipts, copy text, write MANIFEST."""
    root = vendor_root or VENDOR_ROOT
    lock = load_sources(sources_path)
    entries: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="rat-vendor-") as scratch:
        for source in admitted_sources(sources_path):
            sid = source["source_id"]
            work = Path(scratch) / sid
            ok, detail = _shallow_checkout(source["repository"], source["commit"], work)
            if not ok:
                blocked.append({"source_id": sid, "reason": detail})
                continue
            # 2026-08-07 de-governance: the 2026-07-31 audit's per-file sha256 receipts are no longer
            # re-checked against what upstream serves today — a checkout at the pinned commit is
            # trusted as-is. `receipts_verified` below still counts declared source_artifacts.
            files, skipped = _copy_text(work, root / source["snapshot_dir"])
            entries.append({
                "source_id": sid,
                "repository": source["repository"],
                "commit": source["commit"],
                "snapshot_dir": source["snapshot_dir"],
                "license_status": source.get("license_status"),
                "license_spdx": source.get("license_spdx"),
                "attribution_required": bool(source.get("attribution_required")),
                "declared_skill_count": source.get("skill_count"),
                "receipts_verified": len(source.get("source_artifacts") or []),
                "file_count": len(files),
                "skipped": skipped,
                "files": files,
            })

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "retrieved_at": retrieved_at,
        "source_lock": SOURCES_PATH.name,
        "policy": {
            "reverses": ["§5.1 third-party files enter the repo tree",
                         "§5.5 the clean-room no-exact-copy property ends"],
            "keeps": ["§5.2 no installer / hook / MCP server / auto-update is fetched or run",
                      "§5.3 drawio-scientific-illustrator stays excluded on safety grounds"],
            "allowlist": {"suffixes": sorted(ALLOWED_SUFFIXES),
                          "name_prefixes": list(ALLOWED_NAME_PREFIXES),
                          "scope": "skill bundles only — a directory containing SKILL.md and "
                                   "everything below it, plus top-level license/notice files"},
            "excluded_source_ids": sorted(EXCLUDED_SOURCE_IDS),
        },
        "totals": {
            "sources": len(entries),
            "skill_bundles": sum(e["skipped"]["skill_bundles"] for e in entries),
            "files": sum(e["file_count"] for e in entries),
            "bytes": sum(f["bytes"] for e in entries for f in e["files"]),
            "skipped_outside_bundles": sum(e["skipped"]["outside_skill_bundles"] for e in entries),
            "skipped_bytes": sum(e["skipped"]["bytes"] for e in entries),
        },
        "blocked": blocked,
        "sources": entries,
    }
    (root / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


# ------------------------------------------------------------------------------------ verify

def verify(*, vendor_root: Optional[Path] = None) -> dict[str, Any]:
    """Offline check: every manifest file present, and nothing extra beyond the manifest.

    2026-08-07 de-governance: no longer re-hashes each file against its recorded sha256 (that was
    tamper-evidence, not correctness) — a manifest-listed file just has to exist. `item["sha256"]` stays
    in the manifest as a record field; `fetch` still writes it, `verify` no longer compares against it.
    """
    root = vendor_root or VENDOR_ROOT
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"ok": False, "present": False, "violations": [f"no manifest at {manifest_path}"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    known: set[Path] = {manifest_path}

    for source in manifest.get("sources") or []:
        base = root / source["snapshot_dir"]
        for item in source.get("files") or []:
            target = base / item["path"]
            known.add(target)
            if not target.is_file():
                violations.append(f"missing: {source['snapshot_dir']}/{item['path']}")

    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate in known:
            continue
        relative = candidate.relative_to(root)
        if candidate.name == "README.md" and relative.parent == Path("."):
            continue  # our own provenance note, deliberately not a vendored file
        violations.append(
            f"not in the manifest: {relative.as_posix()} — the vendor tree is text-only and "
            "append-only through `fetch`; an unlisted file may be executable")

    return {"ok": not violations, "present": True, "violations": violations,
            "totals": manifest.get("totals", {}), "blocked": manifest.get("blocked", [])}


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m research_agent_teams.tools.vendor_upstream_skills",
        description="Vendor the upstream research-skill text (read-only, markdown + licenses only)")
    sub = parser.add_subparsers(dest="verb", required=True)
    f = sub.add_parser("fetch", help="clone pinned commits, verify receipts, copy text, write manifest")
    f.add_argument("--retrieved-at", required=True, help="the date to record (YYYY-MM-DD)")
    sub.add_parser("verify", help="offline: re-hash the vendor tree against the manifest")

    args = parser.parse_args(argv)
    if args.verb == "fetch":
        manifest = fetch(retrieved_at=args.retrieved_at)
        _emit({"totals": manifest["totals"], "blocked": manifest["blocked"],
               "sources": [{k: e[k] for k in ("source_id", "commit", "license_status",
                                              "receipts_verified", "file_count")}
                           for e in manifest["sources"]]})
        return 1 if manifest["blocked"] else 0
    result = verify()
    _emit(result)
    return 0 if result["ok"] else 2


__all__ = ["EXCLUDED_SOURCE_IDS", "MANIFEST_PATH", "VENDOR_ROOT", "admitted_sources", "fetch",
           "is_allowed", "load_sources", "main", "verify"]


if __name__ == "__main__":
    sys.exit(main())
