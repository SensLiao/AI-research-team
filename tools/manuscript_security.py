"""Fail-closed safety checks shared by manuscript authoring stages.

The helpers in this module validate caller-supplied values only.  They do not
create files, invoke a shell, inspect secret stores, or promote anything into
the research vault.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Pattern, Sequence
from urllib.parse import quote

from research_agent_teams.tools.path_boundaries import (
    PathBoundaryError,
    assert_not_vault_path,
)
from research_agent_teams.tools.scope_guard import _within, decide


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_TEX_DIRECTIVE_START_RE = re.compile(
    r"\\(?P<command>includegraphics|addbibresource|bibliography|input|include)\b",
    re.IGNORECASE,
)
_TEX_DIRECTIVE_RE = re.compile(
    r"\\(?P<command>includegraphics|addbibresource|bibliography|input|include)\b"
    r"\*?\s*(?:\[[^\[\]]*\]\s*)?\{(?P<argument>[^{}]*)\}",
    re.IGNORECASE,
)
_EXECUTION_DIRECTIVE_RE = re.compile(
    r"(?:"
    r"\\(?:immediate\s*\\)?write18\b|"
    r"\\(?:directlua|latelua|luaexec|ShellEscape|pdfshellescape)\b|"
    r"\\usepackage(?:\[[^\]]*\])?\{(?:shellesc|minted|pythontex)\}|"
    r"\\begin\{(?:pycode|python|minted)\}|"
    r"\b(?:subprocess|os\.system|powershell|cmd\.exe|/bin/sh|curl|wget)\b"
    r")",
    re.IGNORECASE,
)
_WRITE_DIRECTIVE_RE = re.compile(
    r"\\(?:openout|closeout|newwrite|openin|read|write)(?=\d|\b)", re.IGNORECASE
)
_DYNAMIC_DIRECTIVE_RE = re.compile(
    r"\\(?:def|edef|gdef|xdef|catcode|csname|endcsname)\b", re.IGNORECASE
)
_NEGATED_EXECUTION_RE = re.compile(
    r"(?:scripts?\s+only|no\s+experiment\s+was\s+run|"
    r"no\s+result\s+is\s+claimed|did\s+not\s+(?:run|execute)|not\s+executed)",
    re.IGNORECASE,
)
_POSITIVE_EXECUTION_RE = re.compile(
    r"(?:\bwe\s+)?\b(?:ran|executed|trained|evaluated|observed|achieved)\b|"
    r"\b(?:real\s+)?gpu\s+(?:experiment|run)\b",
    re.IGNORECASE,
)
_REAL_EXECUTION_RE = re.compile(r"\b(?:real\s+)?gpu\b|\breal\s+experiment\b", re.IGNORECASE)


class _ManuscriptViolation(Exception):
    """Base implementation for stable, JSON-compatible policy failures."""

    policy = "manuscript"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.findings = (
            [dict(finding) for finding in findings]
            if findings is not None
            else [{"code": code, "policy": self.policy, "message": message}]
        )
        super().__init__(f"{code}: {message}")


class ManuscriptPathViolation(PermissionError, _ManuscriptViolation):
    """Raised when a manuscript path crosses an ownership boundary."""

    policy = "manuscript_path"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        _ManuscriptViolation.__init__(self, code, message, findings=findings)


class ManuscriptTexViolation(ValueError, _ManuscriptViolation):
    """Raised when TeX input contains an unsafe or ambiguous directive."""

    policy = "tex_source"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        _ManuscriptViolation.__init__(self, code, message, findings=findings)


class ManuscriptSecretViolation(ValueError, _ManuscriptViolation):
    """Raised when caller-supplied secret evidence appears in durable text."""

    policy = "persisted_text"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        _ManuscriptViolation.__init__(self, code, message, findings=findings)


class ManuscriptExecutionViolation(ValueError, _ManuscriptViolation):
    """Raised when prose claims execution without admissible evidence."""

    policy = "execution_truth"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        _ManuscriptViolation.__init__(self, code, message, findings=findings)


def _raise_path(code: str, message: str) -> None:
    raise ManuscriptPathViolation(code, message)


def _lexical_path_parts(raw: str) -> tuple[str, ...]:
    portable = raw.replace("\\", "/")
    return tuple(portable.split("/"))


def _check_portable_spelling(raw: str) -> None:
    if not raw or "\x00" in raw:
        _raise_path("AMBIGUOUS_PATH", "path is empty or contains a NUL character")
    if unicodedata.normalize("NFC", raw) != raw:
        _raise_path("AMBIGUOUS_PATH", "path is not in canonical NFC form")
    if any(character.isspace() and character != " " for character in raw):
        _raise_path("AMBIGUOUS_PATH", "path contains non-portable whitespace")

    parts = _lexical_path_parts(raw)
    if any(part == ".." for part in parts):
        _raise_path("PATH_TRAVERSAL", "parent traversal is not allowed")
    if any(part.endswith((" ", ".")) for part in parts if part not in {"", "."}):
        _raise_path("AMBIGUOUS_PATH", "path has a platform-ambiguous component")


def _is_cross_platform_absolute(raw: str) -> bool:
    windows_path = PureWindowsPath(raw)
    return bool(windows_path.drive) or windows_path.is_absolute() or raw.startswith(("//", "\\\\"))


def _is_reparse_point(path: Path, stat_result: os.stat_result) -> bool:
    """Return whether ``path`` is a Windows reparse point without following it."""

    del path  # Kept in the signature so tests/platform adapters can identify the component.
    attributes = int(getattr(stat_result, "st_file_attributes", 0) or 0)
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _existing_components(path: Path) -> list[Path]:
    components: list[Path] = []
    current = path
    while True:
        if os.path.lexists(current):
            components.append(current)
        if current == current.parent:
            break
        current = current.parent
    components.reverse()
    return components


def _reject_links(path: Path) -> None:
    for component in _existing_components(path):
        component_stat = component.lstat()
        if stat.S_ISLNK(component_stat.st_mode):
            _raise_path("SYMLINK_PATH", "symbolic links are not accepted at manuscript boundaries")
        if _is_reparse_point(component, component_stat):
            _raise_path("REPARSE_PATH", "reparse points are not accepted at manuscript boundaries")


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    """Use the existing scope primitive for a platform-normalized containment test."""

    return _within(path, root)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_kind(path: Path) -> str:
    if not os.path.lexists(path):
        return "missing"
    mode = path.lstat().st_mode
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    return "other"


def validate_run_owned_path(
    target: str | os.PathLike[str],
    *,
    run_root: str | os.PathLike[str],
    purpose: str = "write",
    vault_root: str | os.PathLike[str] | None = None,
    director_asset_roots: Sequence[str | os.PathLike[str]] = (),
    owned_output_roots: Sequence[str | os.PathLike[str]] | None = None,
    expected_sha256: str | None = None,
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a path without creating, opening for write, or mutating it.

    Relative targets are interpreted against ``run_root``.  Existing director
    assets may be read and hash-checked only when their roots are explicitly
    supplied.  Missing paths are permitted so later stages can validate future
    outputs before creating them.
    """

    if purpose not in {"read", "write"}:
        raise ValueError("purpose must be 'read' or 'write'")

    raw = os.fspath(target)
    if not isinstance(raw, str):
        raise TypeError("target must be a text path")
    _check_portable_spelling(raw)

    run_path = Path(run_root).absolute()
    native_target = Path(raw)
    cross_platform_absolute = _is_cross_platform_absolute(raw)
    if cross_platform_absolute and not native_target.is_absolute():
        _raise_path("PATH_OUTSIDE_RUN", "cross-platform absolute paths are not run-owned")
    candidate = native_target.absolute() if native_target.is_absolute() else run_path / native_target

    # Classify symlinks/junctions before resolving so the policy error remains
    # precise even when a link points outside the run.
    _reject_links(candidate)

    director_roots = tuple(Path(root).absolute() for root in director_asset_roots)
    director_root = next((root for root in director_roots if _inside(candidate, root)), None)
    if director_root is not None:
        if purpose == "write":
            _raise_path("DIRECTOR_ASSET_IMMUTABLE", "director assets are immutable inputs")
        resolved_candidate = _resolved(candidate)
        resolved_director_root = _resolved(director_root)
        if not _inside(resolved_candidate, resolved_director_root):
            _raise_path("PATH_OUTSIDE_RUN", "director asset path resolves outside its declared root")
        kind = _path_kind(candidate)
        if kind != "file":
            _raise_path("DIRECTOR_ASSET_NOT_FILE", "director asset must be an existing regular file")
        actual_sha = _sha256_file(candidate)
        if expected_sha256 is not None and actual_sha.lower() != expected_sha256.lower():
            _raise_path("DIRECTOR_ASSET_HASH_MISMATCH", "director asset hash does not match")
        return {
            "ok": True,
            "policy": "run_owned_path",
            "path": str(resolved_candidate),
            "relative_path": candidate.relative_to(director_root).as_posix(),
            "owner": "director",
            "purpose": purpose,
            "existing_kind": kind,
            "scope_checked": False,
            "sha256": actual_sha,
            "findings": [],
        }

    if vault_root is not None:
        try:
            assert_not_vault_path(candidate, purpose=purpose, vault_root=vault_root)
        except PathBoundaryError:
            _raise_path("VAULT_WRITE", "direct vault access is forbidden")

    if not _inside(candidate, run_path):
        _raise_path("PATH_OUTSIDE_RUN", "path is outside the active run")

    allowed_roots = (
        tuple(Path(root).absolute() for root in owned_output_roots)
        if owned_output_roots is not None
        else (run_path,)
    )
    if not any(_inside(candidate, root) for root in allowed_roots):
        _raise_path("UNOWNED_OUTPUT_ROOT", "path is outside declared output roots")

    resolved_candidate = _resolved(candidate)
    resolved_run = _resolved(run_path)
    if not _inside(resolved_candidate, resolved_run):
        _raise_path("PATH_OUTSIDE_RUN", "path resolves outside the active run")
    if not any(_inside(resolved_candidate, _resolved(root)) for root in allowed_roots):
        _raise_path("UNOWNED_OUTPUT_ROOT", "path resolves outside declared output roots")

    scope_checked = scope is not None
    if scope is not None:
        guarded_scope = dict(scope)
        # Supplying explicit non-empty values prevents scope_guard from consulting
        # environment overrides.  The validator consumes caller-owned facts only.
        guarded_scope.setdefault(
            "vault_root", str(Path(vault_root).absolute() if vault_root else run_path.parent / ".no-vault")
        )
        guarded_scope.setdefault("projects_root", str(run_path.parent / ".no-projects"))
        allowed, _reason = decide("Write", candidate, guarded_scope)
        if not allowed:
            _raise_path("SCOPE_DENIED", "permission scope rejected the manuscript path")

    kind = _path_kind(candidate)
    if kind in {"directory", "other"}:
        _raise_path("PATH_NOT_REGULAR_FILE", "manuscript target is not a regular file")
    result: dict[str, Any] = {
        "ok": True,
        "policy": "run_owned_path",
        "path": str(resolved_candidate),
        "relative_path": candidate.relative_to(run_path).as_posix(),
        "owner": "run",
        "purpose": purpose,
        "existing_kind": kind,
        "scope_checked": scope_checked,
        "findings": [],
    }
    if expected_sha256 is not None:
        if kind != "file":
            _raise_path("HASH_SOURCE_NOT_FILE", "hash verification requires an existing regular file")
        actual_sha = _sha256_file(candidate)
        if actual_sha.lower() != expected_sha256.lower():
            _raise_path("HASH_MISMATCH", "file hash does not match")
        result["sha256"] = actual_sha
    return result


def _strip_tex_comments(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        cut = len(line)
        for index, character in enumerate(line):
            if character != "%":
                continue
            preceding_slashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                preceding_slashes += 1
                cursor -= 1
            if preceding_slashes % 2 == 0:
                cut = index
                break
        output.append(line[:cut] + ("\n" if line.endswith("\n") and cut < len(line) else ""))
    return "".join(output)


def _raise_tex(code: str, message: str) -> None:
    raise ManuscriptTexViolation(code, message)


def _validate_tex_reference(reference: str, *, source_root: Path, run_root: Path) -> None:
    reference = reference.strip()
    if not reference:
        _raise_tex("TEX_DYNAMIC_COMMAND", "TeX path argument is empty or malformed")
    windows = PureWindowsPath(reference)
    if (
        _URL_SCHEME_RE.match(reference)
        or reference.startswith(("/", "~", "//", "\\\\"))
        or bool(windows.drive)
        or windows.is_absolute()
        or "|" in reference
    ):
        _raise_tex("TEX_EXTERNAL_PATH", "TeX directive references an external path")
    if "\\" in reference or any(token in reference for token in ("#", "$", "{" , "}")):
        _raise_tex("TEX_DYNAMIC_COMMAND", "TeX directive uses a dynamic path")
    try:
        validate_run_owned_path(
            source_root / reference,
            run_root=run_root,
            purpose="read",
            owned_output_roots=(source_root,),
        )
    except ManuscriptPathViolation as exc:
        raise ManuscriptTexViolation(
            "TEX_EXTERNAL_PATH",
            "TeX directive path is outside the manuscript source root",
        ) from exc


def validate_tex_sources(
    sources: Mapping[str, str],
    *,
    run_root: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    vault_root: str | os.PathLike[str] | None = None,
    max_source_chars: int = 1_000_000,
) -> dict[str, Any]:
    """Validate in-memory TeX sources using a bounded, literal-path policy."""

    if not isinstance(sources, Mapping) or not sources:
        _raise_tex("TEX_SOURCE_REQUIRED", "at least one TeX source is required")
    run_path = Path(run_root).absolute()
    source_path = Path(source_root).absolute()
    if not _inside(source_path, run_path):
        _raise_tex("TEX_EXTERNAL_PATH", "source root must be owned by the active run")

    directives_checked = 0
    for source_name, raw_text in sources.items():
        if not isinstance(source_name, str) or not isinstance(raw_text, str):
            _raise_tex("TEX_SOURCE_INVALID", "TeX source names and bodies must be text")
        if len(raw_text) > max_source_chars:
            _raise_tex("TEX_SOURCE_TOO_LARGE", "TeX source exceeds the validation bound")
        try:
            validate_run_owned_path(
                source_path / source_name,
                run_root=run_path,
                purpose="read",
                vault_root=vault_root,
                owned_output_roots=(source_path,),
            )
        except ManuscriptPathViolation as exc:
            raise ManuscriptTexViolation(
                "TEX_EXTERNAL_PATH", "TeX source name is outside the source root"
            ) from exc

        text = _strip_tex_comments(raw_text)
        if _EXECUTION_DIRECTIVE_RE.search(text):
            _raise_tex("TEX_EXECUTION_DIRECTIVE", "executable TeX content is forbidden")
        if _WRITE_DIRECTIVE_RE.search(text):
            _raise_tex("TEX_WRITE_DIRECTIVE", "TeX file-write directives are forbidden")
        if _DYNAMIC_DIRECTIVE_RE.search(text):
            _raise_tex("TEX_DYNAMIC_COMMAND", "dynamic TeX command construction is forbidden")

        starts = list(_TEX_DIRECTIVE_START_RE.finditer(text))
        parsed = list(_TEX_DIRECTIVE_RE.finditer(text))
        if len(starts) != len(parsed) or any(
            start.start() != directive.start() for start, directive in zip(starts, parsed)
        ):
            _raise_tex("TEX_DYNAMIC_COMMAND", "TeX include directive is not a bounded literal")

        for directive in parsed:
            command = directive.group("command").lower()
            argument = directive.group("argument")
            references = argument.split(",") if command == "bibliography" else [argument]
            for reference in references:
                _validate_tex_reference(reference, source_root=source_path, run_root=run_path)
            directives_checked += 1

    return {
        "ok": True,
        "policy": "tex_source",
        "files_checked": len(sources),
        "directives_checked": directives_checked,
        "findings": [],
    }


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_persisted_text(
    channel: str,
    text: str,
    *,
    sentinels: Mapping[str, str] | None = None,
    patterns: Mapping[str, str | Pattern[str]] | None = None,
) -> dict[str, Any]:
    """Scan caller-supplied durable text without consulting files or environment."""

    if not isinstance(channel, str) or not isinstance(text, str):
        raise TypeError("channel and text must be strings")
    findings: list[dict[str, Any]] = []
    for name, sentinel in (sentinels or {}).items():
        if not isinstance(name, str) or not isinstance(sentinel, str) or not sentinel:
            continue
        representations = {sentinel, quote(sentinel, safe=""), quote(sentinel, safe="-._~")}
        offsets = [text.find(value) for value in representations if value and text.find(value) >= 0]
        if offsets:
            findings.append(
                {
                    "code": "SECRET_SENTINEL",
                    "channel": channel,
                    "sentinel": name,
                    "line": _line_number(text, min(offsets)),
                }
            )
    for name, expression in (patterns or {}).items():
        compiled = re.compile(expression) if isinstance(expression, str) else expression
        match = compiled.search(text)
        if match:
            findings.append(
                {
                    "code": "SECRET_PATTERN",
                    "channel": channel,
                    "pattern": str(name),
                    "line": _line_number(text, match.start()),
                }
            )
    if findings:
        raise ManuscriptSecretViolation(
            "SECRET_LEAKAGE",
            "durable text contains caller-identified secret material",
            findings=findings,
        )
    return {
        "ok": True,
        "policy": "persisted_text",
        "channel": channel,
        "findings": [],
    }


def _raise_execution(code: str, message: str) -> None:
    raise ManuscriptExecutionViolation(code, message)


def validate_execution_claim(prose: str, result_facts: Mapping[str, Any]) -> dict[str, Any]:
    """Require a frozen non-LLM receipt before admitting execution prose."""

    if not isinstance(prose, str) or not isinstance(result_facts, Mapping):
        raise TypeError("prose must be text and result_facts must be a mapping")
    explicitly_negative = bool(_NEGATED_EXECUTION_RE.search(prose))
    claims_execution = bool(_POSITIVE_EXECUTION_RE.search(prose)) and not explicitly_negative
    if not claims_execution:
        return {
            "ok": True,
            "policy": "execution_truth",
            "execution_claim": False,
            "findings": [],
        }

    admissibility = result_facts.get("admissibility")
    if not isinstance(admissibility, Mapping):
        _raise_execution("UNSUPPORTED_EXECUTION_CLAIM", "execution evidence is missing")
    if bool(admissibility.get("script_only")):
        _raise_execution("SCRIPTS_ONLY", "scripts-only evidence cannot support execution prose")
    if bool(admissibility.get("plan_only")):
        _raise_execution("PLAN_ONLY", "plan-only evidence cannot support execution prose")
    if bool(admissibility.get("metadata_only")):
        _raise_execution("METADATA_ONLY", "metadata-only evidence cannot support execution prose")
    if result_facts.get("status") != "FROZEN":
        _raise_execution("RESULT_NOT_FROZEN", "only frozen results can support execution prose")

    receipt = result_facts.get("executor_receipt")
    raw_source = result_facts.get("raw_source")
    if not isinstance(receipt, Mapping) or not isinstance(raw_source, Mapping):
        _raise_execution("MISSING_EXECUTOR_RECEIPT", "an auditable executor receipt is required")
    executor_kind = str(receipt.get("executor_kind") or "")
    if re.search(r"(?:LLM|MODEL|REASONING)", executor_kind, re.IGNORECASE):
        _raise_execution("MODEL_AUTHORED_RECEIPT", "model-authored receipts are inadmissible")
    if executor_kind != "SIGNED_EXTERNAL_EXECUTOR":
        _raise_execution("UNSUPPORTED_EXECUTOR_RECEIPT", "receipt is not from an approved executor")

    raw_sha = str(raw_source.get("sha256") or "")
    receipt_raw_sha = str(receipt.get("raw_source_sha256") or "")
    receipt_sha = str(receipt.get("receipt_sha256") or "")
    if not _SHA256_RE.fullmatch(raw_sha) or receipt_raw_sha.lower() != raw_sha.lower():
        _raise_execution("RECEIPT_SOURCE_MISMATCH", "receipt is not bound to the raw result")
    if not _SHA256_RE.fullmatch(receipt_sha) or receipt.get("exit_code") != 0:
        _raise_execution("INVALID_EXECUTOR_RECEIPT", "executor receipt is incomplete or unsuccessful")
    if not bool(admissibility.get("observed_evidence")):
        _raise_execution("UNOBSERVED_EXECUTION", "execution prose requires observed evidence")

    requires_real_execution = bool(_REAL_EXECUTION_RE.search(prose))
    if (
        bool(receipt.get("fixture_only"))
        or not bool(admissibility.get("real_research_execution"))
    ):
        code = "NOT_REAL_EXECUTION" if requires_real_execution else "UNSUPPORTED_EXECUTION_CLAIM"
        _raise_execution(code, "evidence does not establish real research execution")

    return {
        "ok": True,
        "policy": "execution_truth",
        "execution_claim": True,
        "receipt_sha256": receipt_sha.lower(),
        "findings": [],
    }


__all__ = [
    "ManuscriptExecutionViolation",
    "ManuscriptPathViolation",
    "ManuscriptSecretViolation",
    "ManuscriptTexViolation",
    "scan_persisted_text",
    "validate_execution_claim",
    "validate_run_owned_path",
    "validate_tex_sources",
]
