"""Deterministic validator for read-only remote sha256 manifests.

The server-side helper produces either an offline plan or a live read-only manifest. A plan is useful
operator guidance, but only a live manifest can be execution evidence.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional


_SHA256_LINE = re.compile(r"^[0-9a-fA-F]{64}\s+(.+)$")


def _clean_required(paths: Iterable[str]) -> List[str]:
    return [str(p).strip().rstrip("/") for p in paths if str(p).strip()]


def validate_manifest(manifest: dict, required_paths: Iterable[str],
                      *, manifest_ref: Optional[str] = None) -> dict:
    """Validate a hash-manifest payload against required directory/file prefixes."""
    required = _clean_required(required_paths)
    violations: List[str] = []

    if not isinstance(manifest, dict):
        return {
            "verdict": "BLOCK",
            "violations": ["hash manifest is not an object"],
            "manifest_ref": manifest_ref,
            "required_paths": required,
            "covered_paths": [],
            "line_count": 0,
            "stdout_sha256": None,
        }

    if manifest.get("mode") != "live":
        violations.append("hash manifest is not live evidence (offline plan is not executable proof)")

    stdout_sha = manifest.get("stdout_sha256")
    if not (isinstance(stdout_sha, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", stdout_sha)):
        violations.append("hash manifest missing valid stdout_sha256")

    missing = manifest.get("missing") or []
    if missing:
        violations.append(f"hash manifest reports missing paths: {missing}")

    lines = manifest.get("lines") or []
    if not isinstance(lines, list):
        violations.append("hash manifest lines is not a list")
        lines = []
    if not lines:
        violations.append("hash manifest contains no sha256 lines")

    covered_paths: List[str] = []
    malformed = []
    for line in lines:
        if not isinstance(line, str):
            malformed.append(str(line))
            continue
        if line.startswith("__MISSING__ "):
            continue
        match = _SHA256_LINE.match(line.strip())
        if not match:
            malformed.append(line)
            continue
        covered_paths.append(match.group(1).strip())
    if malformed:
        violations.append(f"hash manifest has malformed sha256 lines: {malformed[:3]}")

    for req in required:
        if not any(p == req or p.startswith(req + "/") for p in covered_paths):
            violations.append(f"required path not covered by sha256 lines: {req}")

    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "manifest_ref": manifest_ref,
        "required_paths": required,
        "covered_paths": covered_paths,
        "line_count": len(lines),
        "stdout_sha256": stdout_sha,
    }
