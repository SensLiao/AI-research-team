"""Internal semantic validation primitives for frozen manuscript contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_agent_teams.tools.manuscript_security import validate_run_owned_path


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_RE = re.compile(
    r"^(?!/)(?![A-Za-z]:)(?!.*\.\.)(?!.*\\)[A-Za-z0-9][A-Za-z0-9._:/#-]*$"
)
_CREATE_ONCE_STABILIZATION_SECONDS = 0.25
_CREATE_ONCE_POLL_SECONDS = 0.001


class ManuscriptContractError(ValueError):
    """Stable fail-closed error raised by manuscript contract reducers."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def fail(code: str, message: str) -> None:
    raise ManuscriptContractError(code, message)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        fail("NON_CANONICAL_VALUE", f"value is not canonical JSON: {exc}")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_sha256(value: Any, *, code: str, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        fail(code, f"{label} must be a lowercase 64-character SHA-256")
    return value


def require_reference(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _REFERENCE_RE.fullmatch(value) is None:
        fail("UNSAFE_REFERENCE", f"{label} is not a bounded portable reference")
    return value


def _parse_aware_datetime(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        fail("OFFICIAL_SOURCE_DATE", f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("OFFICIAL_SOURCE_DATE", f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail("OFFICIAL_SOURCE_DATE", f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_official_profile(
    payload: Mapping[str, Any],
    *,
    now: datetime,
    max_official_age: timedelta,
) -> None:
    venue = payload.get("venue_profile")
    if not isinstance(venue, Mapping):
        return
    if now.tzinfo is None or now.utcoffset() is None:
        fail("INVALID_FREEZE_TIME", "now must be timezone-aware")
    if max_official_age < timedelta(0):
        fail("INVALID_FRESHNESS_POLICY", "max_official_age cannot be negative")
    retrieved_at = _parse_aware_datetime(
        venue.get("retrieved_at"), label="venue_profile.retrieved_at"
    )
    frozen_at = now.astimezone(timezone.utc)
    if retrieved_at > frozen_at:
        fail("OFFICIAL_SOURCE_FUTURE", "official source retrieval time is in the future")
    if frozen_at - retrieved_at > max_official_age:
        fail(
            "OFFICIAL_SOURCE_STALE",
            "official venue source exceeds the injected freshness policy",
        )

    official = venue.get("official_rule_refs")
    if not isinstance(official, Sequence) or isinstance(official, (str, bytes)) or not official:
        fail("OFFICIAL_SOURCE_MISSING", "at least one official venue source is required")
    official_pairs: set[tuple[str, str]] = set()
    for index, row in enumerate(official):
        if not isinstance(row, Mapping):
            fail("OFFICIAL_SOURCE_MISSING", f"official source {index} is invalid")
        ref = require_reference(row.get("ref"), label=f"official_rule_refs[{index}].ref")
        sha = require_sha256(
            row.get("sha256"),
            code="OFFICIAL_SOURCE_HASH",
            label=f"official_rule_refs[{index}].sha256",
        )
        official_pairs.add((ref, sha))
    template_ref = require_reference(
        venue.get("template_ref"), label="venue_profile.template_ref"
    )
    template_sha = require_sha256(
        venue.get("template_sha256"),
        code="OFFICIAL_SOURCE_HASH",
        label="venue_profile.template_sha256",
    )
    policy = venue.get("hard_field_policy", {}).get("requires_pdf")
    if not isinstance(policy, Mapping):
        fail("REQUIRES_PDF_POLICY", "official requires_pdf policy is missing")
    policy_ref = require_reference(
        policy.get("source_ref"), label="requires_pdf.source_ref"
    )
    policy_sha = require_sha256(
        policy.get("source_sha256"),
        code="OFFICIAL_SOURCE_HASH",
        label="requires_pdf.source_sha256",
    )
    if policy.get("classification") != "OFFICIAL_HARD" or policy.get("weakenable") is not False:
        fail(
            "REQUIRES_PDF_POLICY",
            "requires_pdf must remain OFFICIAL_HARD and non-weakenable",
        )
    if (policy_ref, policy_sha) not in official_pairs | {(template_ref, template_sha)}:
        fail(
            "REQUIRES_PDF_POLICY_SOURCE",
            "requires_pdf policy must cite a frozen official rule or template",
        )


def _unique_index(
    rows: Any,
    key: str,
    *,
    label: str,
    duplicate_code: str,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {}
    index: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identity = row.get(key)
        if isinstance(identity, str):
            if identity in index:
                fail(duplicate_code, f"duplicate {label} {identity!r}")
            index[identity] = row
    return index


def validate_outline(payload: Mapping[str, Any]) -> None:
    sections = _unique_index(
        payload.get("outline"),
        "section_id",
        label="section",
        duplicate_code="DUPLICATE_SECTION",
    )
    for section_id, row in sections.items():
        for dependency in row.get("depends_on", ()):
            if dependency not in sections:
                fail(
                    "UNKNOWN_SECTION_DEPENDENCY",
                    f"section {section_id!r} references unknown section {dependency!r}",
                )
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            fail("SECTION_DEPENDENCY_CYCLE", f"outline cycle reaches {node!r}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for dependency in sections[node].get("depends_on", ()):
            visit(str(dependency))
        state[node] = 2

    for section in sections:
        visit(section)


def validate_dependency_slice_hashes(
    payload: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    slices = _unique_index(
        payload.get("dependency_slices"),
        "slice_id",
        label="dependency slice",
        duplicate_code="DUPLICATE_DEPENDENCY_SLICE",
    )
    for slice_id, dependency_slice in slices.items():
        unsigned = {
            key: copy.deepcopy(value)
            for key, value in dependency_slice.items()
            if key != "slice_sha256"
        }
        if dependency_slice.get("slice_sha256") != canonical_sha256(unsigned):
            fail(
                "DEPENDENCY_SLICE_HASH_MISMATCH",
                f"dependency slice {slice_id!r} was mutated after hashing",
            )
    return slices


def validate_source_closure(payload: Mapping[str, Any]) -> None:
    evidence = _unique_index(
        payload.get("evidence_refs"),
        "ref",
        label="evidence ref",
        duplicate_code="DUPLICATE_EVIDENCE_REF",
    )
    results = _unique_index(
        payload.get("result_refs"),
        "ref",
        label="result ref",
        duplicate_code="DUPLICATE_RESULT_REF",
    )
    sources = _unique_index(
        payload.get("source_hashes"),
        "ref",
        label="source hash ref",
        duplicate_code="DUPLICATE_SOURCE_HASH",
    )

    def require_source(ref: str, sha: str, kind: str) -> None:
        row = sources.get(ref)
        if row is None or row.get("sha256") != sha or row.get("kind") != kind:
            fail(
                "SOURCE_HASH_CLOSURE",
                f"{kind} source {ref!r} is missing or hash-mismatched",
            )

    venue = payload.get("venue_profile", {})
    for row in venue.get("official_rule_refs", ()):
        require_source(str(row.get("ref")), str(row.get("sha256")), "VENUE_RULE")
    if venue.get("template_ref") is not None:
        require_source(
            str(venue.get("template_ref")),
            str(venue.get("template_sha256")),
            "TEMPLATE",
        )
    for ref, row in evidence.items():
        require_source(ref, str(row.get("sha256")), "EVIDENCE")
    for ref, row in results.items():
        require_source(ref, str(row.get("sha256")), "RESULT")

    claims = _unique_index(
        payload.get("claim_ledger"),
        "claim_id",
        label="claim",
        duplicate_code="DUPLICATE_CLAIM",
    )
    for claim_id, claim in claims.items():
        for ref in claim.get("evidence_refs", ()):
            if ref not in evidence:
                fail(
                    "UNKNOWN_EVIDENCE_REF",
                    f"claim {claim_id!r} references unknown evidence {ref!r}",
                )
        for ref in claim.get("result_refs", ()):
            if ref not in results:
                fail(
                    "UNKNOWN_RESULT_REF",
                    f"claim {claim_id!r} references unknown result {ref!r}",
                )

    bibliography = payload.get("bibliography", {})
    for entry in bibliography.get("entries", ()):
        ref = entry.get("source_ref")
        if ref not in evidence:
            fail("UNKNOWN_EVIDENCE_REF", f"bibliography references {ref!r}")
        if entry.get("source_sha256") != evidence[ref].get("sha256"):
            fail("REFERENCE_HASH_MISMATCH", f"bibliography hash differs for {ref!r}")

    for asset in payload.get("asset_plan", ()):
        for ref in asset.get("source_refs", ()):
            source = sources.get(ref)
            if ref not in evidence and (source is None or source.get("kind") != "ASSET"):
                fail("UNKNOWN_EVIDENCE_REF", f"asset references unknown source {ref!r}")
        for ref in asset.get("result_refs", ()):
            if ref not in results:
                fail("UNKNOWN_RESULT_REF", f"asset references unknown result {ref!r}")

    tokens = _unique_index(
        payload.get("resolved_tokens", {}).get("tokens", ()),
        "token",
        label="token",
        duplicate_code="DUPLICATE_TOKEN",
    )
    for token, row in tokens.items():
        source = sources.get(str(row.get("source_ref")))
        if source is None or source.get("sha256") != row.get("source_sha256"):
            fail("TOKEN_SOURCE_CLOSURE", f"token {token!r} source is not frozen")
        if source.get("kind") not in {"TOKEN_OVERLAY", "VENUE_RULE", "TEMPLATE"}:
            fail("TOKEN_SOURCE_CLOSURE", f"token {token!r} has invalid source kind")

    requires_pdf = tokens.get("requires_pdf")
    if requires_pdf is None:
        fail("REQUIRES_PDF_POLICY", "resolved requires_pdf token is missing")
    policy = venue.get("hard_field_policy", {}).get("requires_pdf", {})
    if (
        requires_pdf.get("value") is not venue.get("requires_pdf")
        or requires_pdf.get("classification") != "HARD"
        or requires_pdf.get("weakenable") is not False
        or requires_pdf.get("resolved_layer") != "venue"
        or requires_pdf.get("source_ref") != policy.get("source_ref")
        or requires_pdf.get("source_sha256") != policy.get("source_sha256")
    ):
        fail(
            "REQUIRES_PDF_POLICY_MISMATCH",
            "resolved requires_pdf must exactly preserve official venue policy",
        )

    known_inputs = {**evidence, **results, **sources}
    for slice_id, dependency_slice in validate_dependency_slice_hashes(payload).items():
        for input_ref in dependency_slice.get("input_refs", ()):
            ref = input_ref.get("ref")
            if ref not in known_inputs:
                fail(
                    "UNKNOWN_DEPENDENCY_REF",
                    f"dependency slice {slice_id!r} references unknown input {ref!r}",
                )
            if known_inputs[ref].get("sha256") != input_ref.get("sha256"):
                fail(
                    "REFERENCE_HASH_MISMATCH",
                    f"dependency slice {slice_id!r} hash differs for {ref!r}",
                )


def _existing_contract_or_conflict(
    target: Path,
    candidate: Mapping[str, Any],
    *,
    run_root: str | Path,
) -> dict[str, Any]:
    validate_run_owned_path(target, run_root=run_root, purpose="write")
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(
            "FROZEN_CONTRACT_CONFLICT",
            "existing contract is unreadable and will not be overwritten",
        )
    if existing == candidate:
        return copy.deepcopy(dict(candidate))
    fail(
        "FROZEN_CONTRACT_CONFLICT",
        "a different contract is already frozen at the target path",
    )


def _existing_contract_after_create_once_race(
    target: Path,
    candidate: Mapping[str, Any],
    *,
    run_root: str | Path,
) -> dict[str, Any]:
    """Let a winning publisher remove its temporary hard-link name.

    This bounded wait is exclusive to the ``FileExistsError`` branch after our
    own create-once link attempt.  The normal path validator remains unchanged;
    a target whose link count stays above one is still rejected as
    ``HARDLINK_PATH`` by ``_existing_contract_or_conflict``.
    """

    deadline = time.monotonic() + _CREATE_ONCE_STABILIZATION_SECONDS
    while True:
        try:
            if target.lstat().st_nlink == 1:
                break
        except OSError:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_CREATE_ONCE_POLL_SECONDS, remaining))
    return _existing_contract_or_conflict(target, candidate, run_root=run_root)


def atomic_create_once(
    target: Path,
    text: str,
    candidate: Mapping[str, Any],
    *,
    run_root: str | Path,
) -> dict[str, Any]:
    """Publish complete bytes once using a unique file plus atomic hard-link."""

    target.parent.mkdir(parents=True, exist_ok=True)
    validate_run_owned_path(target, run_root=run_root, purpose="write")
    if target.exists():
        return _existing_contract_or_conflict(target, candidate, run_root=run_root)

    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        validate_run_owned_path(temporary, run_root=run_root, purpose="write")
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        validate_run_owned_path(target, run_root=run_root, purpose="write")
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            return _existing_contract_after_create_once_race(
                target, candidate, run_root=run_root
            )
        except OSError:
            fail(
                "ATOMIC_FREEZE_UNAVAILABLE",
                "filesystem cannot provide create-once atomic contract publication",
            )
        temporary.unlink()
        temporary = None
        validate_run_owned_path(target, run_root=run_root, purpose="write")
        if os.name != "nt":
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return copy.deepcopy(dict(candidate))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "ManuscriptContractError",
    "atomic_create_once",
    "canonical_json",
    "canonical_sha256",
    "fail",
    "require_reference",
    "require_sha256",
    "validate_dependency_slice_hashes",
    "validate_official_profile",
    "validate_outline",
    "validate_source_closure",
]
