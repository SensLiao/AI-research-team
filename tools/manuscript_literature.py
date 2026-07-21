"""Read-only local coverage and deficit-authorized metadata search routing."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research_agent_teams.tools.paper_search import search_many as existing_search_many
from research_agent_teams.tools.recall import recall as existing_recall
from research_agent_teams.tools.scholar_clients import sanitize_scholar_error
from research_agent_teams.tools.validate_artifact import validate_payload


COVERAGE_AXES = (
    "related_comparison", "technical_method", "implementation_detail",
    "dataset", "metric_evaluation", "industry_prior_art",
)

_PROVIDER_PORTS = {
    "ARXIV": "arxiv",
    "OPENALEX": "openalex",
    "CROSSREF": "crossref",
    "SEMANTIC_SCHOLAR": "s2",
}
_PORT_PROVIDERS = {port: provider for provider, port in _PROVIDER_PORTS.items()}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_RE = re.compile(
    r"^(?!/)(?![A-Za-z]:)(?!.*\.\.)(?!.*\\)[A-Za-z0-9][A-Za-z0-9._:/#-]*$"
)
_DEFICIT_RE = re.compile(r"^DEF-[A-Za-z0-9._-]+$")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|token|credential|secret|password)\s*="
)
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PLAN_KEYS = {
    "contract_version",
    "plan_id",
    "coverage_id",
    "manuscript_snapshot_sha256",
    "axis",
    "deficit_id",
    "created_at",
    "query",
    "exhaustive",
    "search_port",
    "metadata_only",
    "attempt_order",
    "attempts",
    "plan_sha256",
}
_ATTEMPT_KEYS = {"provider", "source", "query", "query_sha256"}


class LiteratureCoverageError(ValueError):
    """Stable fail-closed error for literature coverage contracts."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str) -> None:
    raise LiteratureCoverageError(code, detail)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_VALUE", str(exc))


def canonical_sha256(value: Any, *, omit: str | None = None) -> str:
    """Hash canonical JSON, optionally excluding one self-hash field."""

    material = value
    if omit is not None:
        material = {key: item for key, item in dict(value).items() if key != omit}
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _require_reference(value: object, *, field: str) -> str:
    text = str(value or "")
    if not _REFERENCE_RE.fullmatch(text):
        _fail("INVALID_REFERENCE", f"{field} is not a safe relative reference")
    return text


def _require_sha256(value: object, *, field: str) -> str:
    text = str(value or "").lower()
    if not _SHA256_RE.fullmatch(text):
        _fail("INVALID_SHA256", f"{field} must be a bare lowercase SHA-256")
    return text


def _require_timestamp(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        _fail("INVALID_TIMESTAMP", f"{field} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        _fail("INVALID_TIMESTAMP", f"{field} must include a timezone")
    return text


def _safe_query(value: object) -> str:
    query = str(value or "").strip()
    if not query:
        _fail("UNSAFE_QUERY", "a targeted query must be non-empty")
    if _URL_RE.search(query) or _SENSITIVE_ASSIGNMENT_RE.search(query):
        _fail("UNSAFE_QUERY", "URLs and credential-like assignments are forbidden in plans")
    if sanitize_scholar_error(query) != query:
        _fail("UNSAFE_QUERY", "the query would require diagnostic redaction")
    if any(ord(character) < 32 for character in query):
        _fail("UNSAFE_QUERY", "control characters are forbidden in plans")
    return query


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _assert_recall_surface_is_unlinked(root: Path) -> None:
    """Reject link/reparse escapes in exactly the directories recall can traverse."""

    for relative in (Path("00-system"), Path("02-wiki")):
        surface = root / relative
        if not surface.exists():
            continue
        if _is_link_or_reparse(surface):
            _fail("LINKED_VAULT_ROOT", f"recall surface {relative.as_posix()} is linked")
        for directory, names, files in os.walk(surface, followlinks=False):
            parent = Path(directory)
            for name in (*names, *files):
                candidate = parent / name
                if _is_link_or_reparse(candidate):
                    _fail(
                        "LINKED_VAULT_ROOT",
                        f"recall surface contains linked entry {candidate.name!r}",
                    )
                resolved = candidate.resolve(strict=False)
                if not _is_relative_to(resolved, root):
                    _fail("VAULT_PATH_ESCAPE", "recall surface resolves outside its root")


def _bounded_vault_root(
    vault_root: str | os.PathLike[str],
    allowed_vault_roots: Sequence[str | os.PathLike[str]],
) -> Path:
    if not allowed_vault_roots:
        _fail("UNAPPROVED_VAULT_ROOT", "at least one declared vault root is required")
    lexical = Path(vault_root).expanduser().absolute()
    if not lexical.exists() or not lexical.is_dir():
        _fail("UNAPPROVED_VAULT_ROOT", "the requested vault root is not a directory")
    resolved = lexical.resolve(strict=True)
    if _is_link_or_reparse(lexical) or os.path.normcase(str(lexical)) != os.path.normcase(
        str(resolved)
    ):
        _fail("LINKED_VAULT_ROOT", "the requested vault root crosses a link or reparse point")
    allowed: list[Path] = []
    for declared in allowed_vault_roots:
        declared_path = Path(declared).expanduser().absolute()
        if not declared_path.exists() or not declared_path.is_dir():
            continue
        allowed.append(declared_path.resolve(strict=True))
    if resolved not in allowed:
        _fail("UNAPPROVED_VAULT_ROOT", "the requested vault root was not declared")
    _assert_recall_surface_is_unlinked(resolved)
    return resolved


def _schema_valid(payload: Mapping[str, Any]) -> None:
    errors = validate_payload("local_literature_coverage", dict(payload))
    if errors:
        _fail("INVALID_COVERAGE", "; ".join(errors[:5]))


def _normalize_recall_citation(citation: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    slug = str(citation.get("slug") or "").strip()
    reference = _require_reference(f"vault:{slug}", field="local source ref")
    raw_sha = str(citation.get("sha256") or "")
    if raw_sha.startswith("sha256:"):
        raw_sha = raw_sha.removeprefix("sha256:")
    sha256 = _require_sha256(raw_sha, field=f"citation {slug!r} sha256")
    return reference, {"ref": reference, "sha256": sha256, "source_kind": "NOTE"}


def assess_local_coverage(
    *,
    coverage_id: str,
    manuscript_snapshot_sha256: str,
    assessed_at: str,
    criteria: Mapping[str, Mapping[str, Any]],
    vault_root: str | os.PathLike[str],
    allowed_vault_roots: Sequence[str | os.PathLike[str]],
    project: str | None = None,
    top_k: int = 6,
    recall_fn: Callable[..., Mapping[str, Any]] = existing_recall,
) -> dict[str, Any]:
    """Assess six axes; empty recall stays UNVERIFIED until named authorization."""

    if set(criteria) != set(COVERAGE_AXES):
        _fail("INCOMPLETE_COVERAGE_AXES", "criteria must name exactly the six D-06 axes")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        _fail("UNBOUNDED_RECALL", "top_k must be an integer from 1 through 20")
    root = _bounded_vault_root(vault_root, allowed_vault_roots)
    coverage_ref = _require_reference(coverage_id, field="coverage_id")
    snapshot_sha = _require_sha256(
        manuscript_snapshot_sha256, field="manuscript_snapshot_sha256"
    )
    timestamp = _require_timestamp(assessed_at, field="assessed_at")

    corpus_by_ref: dict[str, dict[str, str]] = {}
    axes: dict[str, dict[str, Any]] = {}
    for axis in COVERAGE_AXES:
        specification = criteria[axis]
        if not isinstance(specification, Mapping):
            _fail("INVALID_COVERAGE_CRITERION", f"{axis} criterion must be a mapping")
        criterion = str(specification.get("criterion") or "").strip()
        query = str(specification.get("recall_query") or criterion).strip()
        if not criterion or not query:
            _fail("INVALID_COVERAGE_CRITERION", f"{axis} requires criterion and recall_query")
        note = recall_fn(
            query,
            vault_root=root,
            project=project,
            top_k=top_k,
        )
        if not isinstance(note, Mapping):
            _fail("INVALID_RECALL_NOTE", f"recall for {axis} did not return a mapping")
        raw_citations = note.get("citations") or []
        if not isinstance(raw_citations, Sequence) or isinstance(
            raw_citations, (str, bytes)
        ):
            _fail("INVALID_RECALL_NOTE", f"recall citations for {axis} are not a list")
        local_refs: list[str] = []
        for raw in list(raw_citations)[:top_k]:
            if not isinstance(raw, Mapping):
                _fail("INVALID_RECALL_NOTE", f"recall citation for {axis} is not a mapping")
            reference, row = _normalize_recall_citation(raw)
            previous = corpus_by_ref.get(reference)
            if previous is not None and previous != row:
                _fail("LOCAL_REFERENCE_HASH_CONFLICT", f"{reference} has competing hashes")
            corpus_by_ref[reference] = row
            if reference not in local_refs:
                local_refs.append(reference)
        if local_refs:
            status = "SUFFICIENT"
            rationale = (
                f"Bounded read-only recall returned {len(local_refs)} traceable local "
                "reference(s)."
            )
        else:
            status = "UNVERIFIED"
            rationale = (
                "Bounded local recall returned no reference; this is unverified and does "
                "not authorize search or an evidence-absence claim."
            )
        axes[axis] = {
            "criterion": criterion,
            "status": status,
            "local_source_refs": sorted(local_refs),
            "rationale": rationale,
        }

    payload = {
        "contract_version": "1.0",
        "coverage_id": coverage_ref,
        "manuscript_snapshot_sha256": snapshot_sha,
        "assessed_at": timestamp,
        "local_corpus_refs": [corpus_by_ref[key] for key in sorted(corpus_by_ref)],
        "axes": axes,
    }
    _schema_valid(payload)
    return payload


def _validate_plan(plan: Mapping[str, Any], *, require_hash: bool) -> bool:
    if set(plan) != _PLAN_KEYS:
        _fail("INVALID_QUERY_PLAN", "query plan fields do not match the frozen contract")
    if plan.get("contract_version") != "1.0":
        _fail("INVALID_QUERY_PLAN", "unsupported query plan contract version")
    _require_reference(plan.get("plan_id"), field="plan_id")
    _require_reference(plan.get("coverage_id"), field="coverage_id")
    _require_sha256(plan.get("manuscript_snapshot_sha256"), field="snapshot hash")
    axis = str(plan.get("axis") or "")
    if axis not in COVERAGE_AXES:
        _fail("INVALID_QUERY_PLAN", "query plan axis is not a D-06 axis")
    deficit_id = str(plan.get("deficit_id") or "")
    if not _DEFICIT_RE.fullmatch(deficit_id):
        _fail("INVALID_QUERY_PLAN", "deficit_id must use the DEF-* contract")
    _require_timestamp(plan.get("created_at"), field="created_at")
    query = _safe_query(plan.get("query"))
    if plan.get("exhaustive") is not True:
        _fail("INVALID_QUERY_PLAN", "the required attempt set must be exhaustive")
    if plan.get("search_port") != "paper_search.search_many":
        _fail("INVALID_QUERY_PLAN", "only the existing metadata search port is allowed")
    if plan.get("metadata_only") is not True:
        _fail("INVALID_QUERY_PLAN", "query plans must be metadata-only")
    order = plan.get("attempt_order")
    attempts = plan.get("attempts")
    if not isinstance(order, list) or not order or len(order) != len(set(order)):
        _fail("INVALID_QUERY_PLAN", "attempt_order must be nonempty and unique")
    if not isinstance(attempts, Mapping) or set(order) != set(attempts):
        _fail("INVALID_QUERY_PLAN", "attempt_order and attempts must close exactly")
    for attempt_id in order:
        _require_reference(attempt_id, field="attempt_id")
        attempt = attempts[attempt_id]
        if not isinstance(attempt, Mapping) or set(attempt) != _ATTEMPT_KEYS:
            _fail("INVALID_QUERY_PLAN", f"attempt {attempt_id!r} has invalid fields")
        provider = str(attempt.get("provider") or "")
        if provider not in _PROVIDER_PORTS:
            _fail("INVALID_QUERY_PLAN", f"attempt {attempt_id!r} has unknown provider")
        if attempt.get("source") != _PROVIDER_PORTS[provider]:
            _fail("INVALID_QUERY_PLAN", f"attempt {attempt_id!r} source mismatches provider")
        if attempt.get("query") != query:
            _fail("INVALID_QUERY_PLAN", f"attempt {attempt_id!r} query mismatches plan")
        if attempt.get("query_sha256") != canonical_sha256(query):
            _fail("INVALID_QUERY_PLAN", f"attempt {attempt_id!r} query hash mismatches")
    claimed = str(plan.get("plan_sha256") or "")
    hash_valid = _SHA256_RE.fullmatch(claimed) is not None and claimed == canonical_sha256(
        plan, omit="plan_sha256"
    )
    if require_hash and not hash_valid:
        _fail("QUERY_PLAN_HASH_MISMATCH", "the frozen query plan hash does not match")
    return hash_valid


def build_targeted_query_plan(
    coverage: Mapping[str, Any],
    *,
    axis: str,
    deficit_id: str,
    query: str,
    providers: Sequence[str],
    plan_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Freeze one minimal query and its exact required provider-attempt set."""

    _schema_valid(coverage)
    if axis not in COVERAGE_AXES:
        _fail("UNAUTHORIZED_DEFICIT", "the named axis is not part of D-06 coverage")
    axis_record = coverage["axes"][axis]
    if axis_record.get("status") != "UNVERIFIED" or axis_record.get(
        "local_source_refs"
    ):
        _fail("UNAUTHORIZED_DEFICIT", "only an unverified local axis may authorize search")
    if not _DEFICIT_RE.fullmatch(str(deficit_id or "")):
        _fail("UNAUTHORIZED_DEFICIT", "a named DEF-* identifier is required")
    frozen_query = _safe_query(query)
    normalized_providers = [str(provider or "").upper() for provider in providers]
    if not normalized_providers or len(normalized_providers) != len(
        set(normalized_providers)
    ):
        _fail("INVALID_PROVIDER_SET", "providers must be nonempty and unique")
    unknown = [provider for provider in normalized_providers if provider not in _PROVIDER_PORTS]
    if unknown:
        _fail("INVALID_PROVIDER_SET", f"unknown metadata provider(s): {unknown}")

    attempts: dict[str, dict[str, str]] = {}
    order: list[str] = []
    query_sha = canonical_sha256(frozen_query)
    axis_slug = "-".join(axis.split("_"))
    for provider in normalized_providers:
        provider_slug = "-".join(_PROVIDER_PORTS[provider].split("_"))
        attempt_id = f"attempt-{axis_slug}-{provider_slug}"
        order.append(attempt_id)
        attempts[attempt_id] = {
            "provider": provider,
            "source": _PROVIDER_PORTS[provider],
            "query": frozen_query,
            "query_sha256": query_sha,
        }
    plan: dict[str, Any] = {
        "contract_version": "1.0",
        "plan_id": _require_reference(plan_id, field="plan_id"),
        "coverage_id": coverage["coverage_id"],
        "manuscript_snapshot_sha256": coverage["manuscript_snapshot_sha256"],
        "axis": axis,
        "deficit_id": deficit_id,
        "created_at": _require_timestamp(created_at, field="created_at"),
        "query": frozen_query,
        "exhaustive": True,
        "search_port": "paper_search.search_many",
        "metadata_only": True,
        "attempt_order": order,
        "attempts": attempts,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    _validate_plan(plan, require_hash=True)
    return plan


def _metadata_provider(row: Mapping[str, Any]) -> str:
    raw = str(row.get("provider") or row.get("source") or "").strip()
    if raw.upper() in _PROVIDER_PORTS:
        return raw.upper()
    return _PORT_PROVIDERS.get(raw.lower(), "")


def _safe_metadata_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        provider = _metadata_provider(raw)
        if not provider:
            continue
        title = sanitize_scholar_error(raw.get("title") or "[untitled metadata candidate]")
        title = title.strip() or "[untitled metadata candidate]"
        record_id = str(
            raw.get("provider_record_id")
            or raw.get("id")
            or raw.get("doi")
            or raw.get("arxiv_id")
            or ""
        ).strip()
        if not record_id or _URL_RE.search(record_id) or _SENSITIVE_ASSIGNMENT_RE.search(
            record_id
        ):
            record_id = f"metadata-{hashlib.sha256(title.encode('utf-8')).hexdigest()[:16]}"
        record_id = sanitize_scholar_error(record_id)
        item = {
            "provider": provider,
            "provider_record_id": record_id,
            "title": title,
            "claim_support": "NONE",
            "exact_span_support": False,
            "local_full_text_owned": False,
            "admissible_for_manuscript": False,
        }
        normalized[(provider, record_id)] = item
    return [normalized[key] for key in sorted(normalized)]


def _terminal_mapping(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    terminal = raw.get("terminal")
    return terminal if isinstance(terminal, Mapping) else {}


def derive_search_outcome(
    frozen_query_plan: Mapping[str, Any],
    search_trace: Mapping[str, Any],
    metadata_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reduce one frozen attempt set to the three exact retrieval truth states."""

    plan_hash_valid = _validate_plan(frozen_query_plan, require_hash=False)
    if not isinstance(search_trace, Mapping):
        _fail("INVALID_SEARCH_TRACE", "search trace must be a mapping")
    safe_rows = _safe_metadata_rows(metadata_rows)
    reasons: list[str] = []
    provider_diagnostics: list[str] = []
    if not plan_hash_valid:
        reasons.append("QUERY_PLAN_HASH_MISMATCH")

    claimed_trace_sha = str(search_trace.get("trace_sha256") or "")
    actual_trace_sha = canonical_sha256(search_trace, omit="trace_sha256")
    if claimed_trace_sha != actual_trace_sha:
        reasons.append("TRACE_HASH_MISMATCH")
    if search_trace.get("plan_id") != frozen_query_plan.get("plan_id"):
        reasons.append("TRACE_PLAN_ID_MISMATCH")
    if search_trace.get("plan_sha256") != frozen_query_plan.get("plan_sha256"):
        reasons.append("TRACE_PLAN_HASH_MISMATCH")
    if search_trace.get("contract_version") != "1.0":
        reasons.append("TRACE_VERSION_MISMATCH")

    required_order = list(frozen_query_plan["attempt_order"])
    trace_order = search_trace.get("attempt_order")
    trace_attempts = search_trace.get("attempts")
    trace_order_valid = (
        isinstance(trace_order, list)
        and len(trace_order) == len(set(trace_order))
        and trace_order == required_order
    )
    if not trace_order_valid:
        reasons.append("ATTEMPT_ORDER_MISMATCH")
    if not isinstance(trace_attempts, Mapping):
        trace_attempts = {}
        reasons.append("ATTEMPTS_NOT_MAPPED")
    if set(trace_attempts) != set(required_order):
        reasons.append("ATTEMPT_SET_MISMATCH")
    if search_trace.get("budget_exhausted") is True:
        reasons.append("BUDGET_EXHAUSTED")
    if search_trace.get("stopped_early") is True:
        reasons.append("STOPPED_EARLY")

    identity_valid = True
    terminals: dict[str, Mapping[str, Any]] = {}
    for attempt_id in required_order:
        planned = frozen_query_plan["attempts"][attempt_id]
        observed = trace_attempts.get(attempt_id)
        if not isinstance(observed, Mapping):
            identity_valid = False
            reasons.append(f"MISSING_ATTEMPT:{attempt_id}")
            terminals[attempt_id] = {}
            continue
        for field in ("provider", "query", "query_sha256"):
            if observed.get(field) != planned.get(field):
                identity_valid = False
                reasons.append(f"ATTEMPT_{field.upper()}_MISMATCH:{attempt_id}")
        terminals[attempt_id] = _terminal_mapping(observed)
        diagnostic = observed.get("provider_error")
        if diagnostic:
            provider_diagnostics.append(sanitize_scholar_error(diagnostic))

    base_complete = not reasons and identity_valid

    def is_provider_failure(terminal: Mapping[str, Any]) -> bool:
        return (
            terminal.get("closed") is True
            and terminal.get("status") == "PROVIDER_FAILURE"
            and terminal.get("result_count") == 0
            and terminal.get("admissible_rows") == 0
            and terminal.get("response_sha256") is None
        )

    def is_successful_empty(terminal: Mapping[str, Any]) -> bool:
        response_sha = terminal.get("response_sha256")
        return (
            terminal.get("closed") is True
            and terminal.get("status") == "SUCCESS_EMPTY"
            and terminal.get("result_count") == 0
            and terminal.get("admissible_rows") == 0
            and isinstance(response_sha, str)
            and _SHA256_RE.fullmatch(response_sha) is not None
        )

    if base_complete and all(is_provider_failure(terminals[key]) for key in required_order):
        outcome = "PROVIDER_FAILURE"
    elif (
        base_complete
        and frozen_query_plan.get("exhaustive") is True
        and not safe_rows
        and all(is_successful_empty(terminals[key]) for key in required_order)
    ):
        outcome = "NO_EVIDENCE_AFTER_VALID_SEARCH"
    else:
        outcome = "PARTIAL_OR_UNRESOLVED_ZERO_RESULT"
        if safe_rows:
            reasons.append("METADATA_REQUIRES_FOLLOW_UP")

    projected_attempts: dict[str, dict[str, Any]] = {}
    for attempt_id in required_order:
        planned = frozen_query_plan["attempts"][attempt_id]
        terminal = terminals.get(attempt_id, {})
        if outcome == "PROVIDER_FAILURE":
            projected_terminal = {
                "closed": True,
                "status": "PROVIDER_FAILURE",
                "result_count": 0,
                "admissible_rows": 0,
                "response_sha256": None,
            }
        elif outcome == "NO_EVIDENCE_AFTER_VALID_SEARCH":
            projected_terminal = {
                "closed": True,
                "status": "SUCCESS_EMPTY",
                "result_count": 0,
                "admissible_rows": 0,
                "response_sha256": terminal["response_sha256"],
            }
        else:
            response_sha = terminal.get("response_sha256")
            projected_terminal = {
                "closed": True,
                "status": "PARTIAL" if terminal.get("closed") is True else "UNRESOLVED_ZERO_RESULT",
                "result_count": max(0, int(terminal.get("result_count") or 0)),
                "admissible_rows": 0,
                "response_sha256": (
                    response_sha
                    if isinstance(response_sha, str) and _SHA256_RE.fullmatch(response_sha)
                    else None
                ),
            }
        projected_attempts[attempt_id] = {
            "provider": planned["provider"],
            "query": planned["query"],
            "query_sha256": planned["query_sha256"],
            "terminal": projected_terminal,
        }

    return {
        "outcome": outcome,
        "terminal_trace_sha256": actual_trace_sha,
        "attempts": projected_attempts,
        "metadata_rows": safe_rows,
        "trace_complete": base_complete,
        "diagnostics": sorted(
            set(
                sanitize_scholar_error(item)
                for item in [*reasons, *provider_diagnostics]
            )
        ),
    }


def _execute_query_plan(
    plan: Mapping[str, Any],
    *,
    search_many_fn: Callable[..., Mapping[str, Any]],
    transport: object,
    limit_per_source: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: dict[str, dict[str, Any]] = {}
    metadata: list[dict[str, Any]] = []
    for attempt_id in plan["attempt_order"]:
        specification = plan["attempts"][attempt_id]
        provider = specification["provider"]
        error = ""
        records: list[Mapping[str, Any]] = []
        source_errors: dict[str, str] = {}
        try:
            result = search_many_fn(
                [specification["query"]],
                sources=(specification["source"],),
                limit_per_source=limit_per_source,
                transport=transport,
            )
            if not isinstance(result, Mapping):
                raise TypeError("metadata search returned a non-mapping result")
            raw_records = result.get("records") or []
            if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
                raise TypeError("metadata search records are not a sequence")
            records = [row for row in raw_records if isinstance(row, Mapping)]
            source_errors = {
                str(key): sanitize_scholar_error(value)
                for key, value in dict(result.get("source_errors") or {}).items()
            }
        except Exception as exc:
            error = sanitize_scholar_error(exc)

        safe_attempt_rows = _safe_metadata_rows(
            [dict(row, provider=provider) for row in records]
        )
        metadata.extend(safe_attempt_rows)
        if error or (source_errors and not records):
            status = "PROVIDER_FAILURE"
        elif source_errors:
            status = "PARTIAL"
        elif records:
            status = "SUCCESS_WITH_METADATA"
        else:
            status = "SUCCESS_EMPTY"
        diagnostic_parts = [error] if error else []
        diagnostic_parts.extend(source_errors.values())
        safe_response = {
            "provider": provider,
            "query_sha256": specification["query_sha256"],
            "metadata_rows": safe_attempt_rows,
            "source_errors": sorted(set(diagnostic_parts)),
        }
        response_sha = None if status == "PROVIDER_FAILURE" else canonical_sha256(safe_response)
        observed: dict[str, Any] = {
            "provider": provider,
            "query": specification["query"],
            "query_sha256": specification["query_sha256"],
            "terminal": {
                "closed": True,
                "status": status,
                "result_count": len(records),
                "admissible_rows": 0,
                "response_sha256": response_sha,
            },
        }
        if diagnostic_parts:
            observed["provider_error"] = " | ".join(sorted(set(diagnostic_parts)))
        attempts[attempt_id] = observed

    trace: dict[str, Any] = {
        "contract_version": "1.0",
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "attempt_order": list(plan["attempt_order"]),
        "attempts": attempts,
        "budget_exhausted": False,
        "stopped_early": False,
    }
    trace["trace_sha256"] = canonical_sha256(trace)
    return trace, _safe_metadata_rows(metadata)


def route_coverage_deficits(
    coverage: Mapping[str, Any],
    *,
    query_plans: Sequence[Mapping[str, Any]],
    search_many_fn: Callable[..., Mapping[str, Any]] = existing_search_many,
    transport: object = None,
    limit_per_source: int = 10,
) -> dict[str, Any]:
    """Execute only frozen named deficits through the existing metadata port."""

    _schema_valid(coverage)
    if isinstance(limit_per_source, bool) or not isinstance(limit_per_source, int):
        _fail("INVALID_SEARCH_LIMIT", "limit_per_source must be an integer")
    if not 1 <= limit_per_source <= 50:
        _fail("INVALID_SEARCH_LIMIT", "limit_per_source must be from 1 through 50")
    routed_coverage = copy.deepcopy(dict(coverage))
    frozen_plans: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    diagnostics: dict[str, list[str]] = {}
    seen_axes: set[str] = set()
    for raw_plan in query_plans:
        if not isinstance(raw_plan, Mapping):
            _fail("INVALID_QUERY_PLAN", "query plan must be a mapping")
        plan = copy.deepcopy(dict(raw_plan))
        _validate_plan(plan, require_hash=True)
        axis = plan["axis"]
        if axis in seen_axes:
            _fail("DUPLICATE_DEFICIT", f"axis {axis!r} has more than one query plan")
        seen_axes.add(axis)
        if plan["coverage_id"] != coverage["coverage_id"] or plan[
            "manuscript_snapshot_sha256"
        ] != coverage["manuscript_snapshot_sha256"]:
            _fail("QUERY_PLAN_BINDING_MISMATCH", "query plan does not bind this coverage")
        axis_record = routed_coverage["axes"][axis]
        if axis_record.get("status") != "UNVERIFIED" or axis_record.get(
            "local_source_refs"
        ):
            _fail("UNAUTHORIZED_DEFICIT", "search is forbidden for locally sufficient axes")

        trace, metadata = _execute_query_plan(
            plan,
            search_many_fn=search_many_fn,
            transport=transport,
            limit_per_source=limit_per_source,
        )
        derived = derive_search_outcome(plan, trace, metadata)
        authorization_id = _require_reference(
            f"authorization-{plan['deficit_id'].removeprefix('DEF-').lower()}",
            field="authorization_id",
        )
        axis_record.update(
            {
                "status": "DEFICIT",
                "rationale": (
                    f"{axis_record['rationale']} Named deficit {plan['deficit_id']} was "
                    f"routed through a frozen metadata-only plan; outcome={derived['outcome']}."
                ),
                "query_authorization": {
                    "authorization_id": authorization_id,
                    "deficit_id": plan["deficit_id"],
                    "frozen_plan_sha256": plan["plan_sha256"],
                    "created_at": plan["created_at"],
                    "outcome": derived["outcome"],
                    "terminal_trace_sha256": derived["terminal_trace_sha256"],
                    "attempts": derived["attempts"],
                    "metadata_rows": derived["metadata_rows"],
                },
            }
        )
        frozen_plans.append(plan)
        traces.append(trace)
        diagnostics[plan["deficit_id"]] = derived["diagnostics"]

    _schema_valid(routed_coverage)
    return {
        "coverage": routed_coverage,
        "frozen_query_plans": frozen_plans,
        "search_traces": traces,
        "diagnostics": diagnostics,
    }


__all__ = ["COVERAGE_AXES", "LiteratureCoverageError", "assess_local_coverage",
           "build_targeted_query_plan", "canonical_sha256", "derive_search_outcome",
           "route_coverage_deficits"]
