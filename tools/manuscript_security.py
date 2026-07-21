"""Fail-closed safety checks shared by manuscript authoring stages.

The helpers in this module validate caller-supplied values only.  They do not
create files, invoke a shell, inspect secret stores, or promote anything into
the research vault.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Pattern, Sequence
from urllib.parse import quote, unquote_plus

from research_agent_teams.tools.path_boundaries import (
    PathBoundaryError,
    assert_not_vault_path,
    default_vault_root,
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
    r"\\(?:directlua|latelua|luaexec|special|ShellEscape|pdfshellescape|inputminted)\b|"
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?"
    r"\s*\{(?:shellesc|shellescape|minted|pythontex)\}|"
    r"\\begin\{(?:pycode|python|minted)\}|"
    r"\b(?:subprocess|os\.system|powershell|cmd\.exe|/bin/sh|curl|wget)\b"
    r")",
    re.IGNORECASE,
)
_WRITE_DIRECTIVE_RE = re.compile(
    r"\\(?:openout|closeout|newwrite|newread|openin|read|write)(?=\d|\b)|"
    r"\\begin\s*\{filecontents\*?\}",
    re.IGNORECASE,
)
_DYNAMIC_DIRECTIVE_RE = re.compile(
    r"\\(?:def|edef|gdef|xdef|catcode|csname|endcsname|expandafter|futurelet|"
    r"scantokens|afterassignment|everyjob|everypar|everyeof|graphicspath)\b",
    re.IGNORECASE,
)
_CONDITIONAL_INPUT_RE = re.compile(
    r"\\(?:InputIfFileExists|IfFileExists)\b", re.IGNORECASE
)
_CONTROL_SEQUENCE_RE = re.compile(r"\\(?P<name>[A-Za-z@]+)")
_ENVIRONMENT_RE = re.compile(r"\\(?:begin|end)\s*\{(?P<name>[A-Za-z*]+)\}")
_PACKAGE_RE = re.compile(
    r"\\usepackage\s*(?:\[[^\[\]]*\]\s*)?\{(?P<names>[^{}]+)\}",
    re.IGNORECASE,
)
_DOCUMENT_CLASS_RE = re.compile(
    r"\\documentclass\s*(?:\[[^\[\]]*\]\s*)?\{(?P<name>[^{}]+)\}",
    re.IGNORECASE,
)
_SAFE_TEX_COMMANDS = frozenset(
    """
    documentclass usepackage begin end input include includegraphics bibliography
    addbibresource bibliographystyle title author date maketitle thanks section
    subsection subsubsection paragraph subparagraph label ref pageref eqref autoref
    cite citep citet Cref cref caption centering footnote emph textbf textit texttt
    textrm textsf textsc underline url href item hline cline topmidrule toprule
    midrule bottomrule multicolumn multirow resizebox rotatebox color textcolor
    newline linebreak pagebreak newpage clearpage appendix tableofcontents
    listoffigures listoftables vspace hspace smallskip medskip bigskip noindent
    quad qquad left right frac sqrt sum prod int lim min max argmin argmax log exp
    sin cos tan softmax mathbb mathbf mathcal mathrm mathit operatorname text
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa
    lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi
    chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    infty partial nabla ell cdot times pm mp leq geq neq approx sim equiv propto
    in subset subseteq supset supseteq cup cap setminus forall exists neg land lor
    to mapsto leftarrow rightarrow Leftrightarrow Rightarrow ldots cdots vdots ddots
    linewidth textwidth columnwidth baselineskip
    """.split()
)
_SAFE_TEX_ENVIRONMENTS = frozenset(
    """
    document abstract figure figure* table table* tabular tabular* tabularx
    itemize enumerate description equation equation* align align* aligned gather
    gather* multline multline* split cases matrix pmatrix bmatrix vmatrix Vmatrix
    theorem lemma proposition corollary definition assumption remark example proof
    minipage center flushleft flushright quote quotation
    """.split()
)
_SAFE_TEX_PACKAGES = frozenset(
    """
    amsmath amssymb amsfonts amsthm array balance booktabs caption cleveref enumitem
    fontenc geometry graphicx hyperref inputenc mathtools microtype multirow natbib
    newtxmath newtxtext subcaption tabularx times url verbatim xcolor
    """.split()
)
_NO_EXECUTION_TEMPLATE_RE = re.compile(
    r"\s*scripts?\s+only:\s*no\s+experiment\s+was\s+run\s+and\s+"
    r"no\s+result\s+is\s+claimed\.\s*",
    re.IGNORECASE,
)
_REAL_EXECUTION_RE = re.compile(r"\b(?:real\s+)?gpu\b|\breal\s+experiment\b", re.IGNORECASE)
_FIXTURE_DISCLOSURE_RE = re.compile(
    r"\b(?:synthetic\s+fixture|test-only|fixture-only)\b", re.IGNORECASE
)


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

    director_roots = tuple(Path(root).absolute() for root in director_asset_roots)
    director_root = next((root for root in director_roots if _inside(candidate, root)), None)
    effective_vault_root = Path(vault_root).absolute() if vault_root else default_vault_root()
    if (
        not _inside(candidate, run_path)
        and director_root is None
        and not _inside(candidate, effective_vault_root)
    ):
        _raise_path("PATH_OUTSIDE_RUN", "path is outside the active run")

    # Classify symlinks/junctions before resolving so the policy error remains
    # precise even when a link points outside the run.
    _reject_links(candidate)

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
        if not guarded_scope.get("vault_root"):
            guarded_scope["vault_root"] = str(
                Path(vault_root).absolute() if vault_root else run_path.parent / ".no-vault"
            )
        if not guarded_scope.get("projects_root"):
            guarded_scope["projects_root"] = str(run_path.parent / ".no-projects")
        allowed, _reason = decide("Write", candidate, guarded_scope)
        if not allowed:
            _raise_path("SCOPE_DENIED", "permission scope rejected the manuscript path")

    kind = _path_kind(candidate)
    if kind in {"directory", "other"}:
        _raise_path("PATH_NOT_REGULAR_FILE", "manuscript target is not a regular file")
    if purpose == "write" and kind == "file" and candidate.lstat().st_nlink != 1:
        _raise_path("HARDLINK_PATH", "hard-linked files are not accepted as output targets")
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


def _validate_tex_allowlist(text: str) -> None:
    for match in _CONTROL_SEQUENCE_RE.finditer(text):
        if match.group("name") not in _SAFE_TEX_COMMANDS:
            _raise_tex("TEX_UNSUPPORTED_COMMAND", "TeX control sequence is not allowlisted")

    for match in _ENVIRONMENT_RE.finditer(text):
        if match.group("name") not in _SAFE_TEX_ENVIRONMENTS:
            _raise_tex("TEX_UNSUPPORTED_COMMAND", "TeX environment is not allowlisted")

    package_starts = list(re.finditer(r"\\usepackage\b", text, re.IGNORECASE))
    packages = list(_PACKAGE_RE.finditer(text))
    if len(package_starts) != len(packages):
        _raise_tex("TEX_DYNAMIC_COMMAND", "package declaration is not a bounded literal")
    for declaration in packages:
        for package in declaration.group("names").split(","):
            if package.strip() not in _SAFE_TEX_PACKAGES:
                _raise_tex("TEX_UNSUPPORTED_COMMAND", "TeX package is not allowlisted")

    class_starts = list(re.finditer(r"\\documentclass\b", text, re.IGNORECASE))
    classes = list(_DOCUMENT_CLASS_RE.finditer(text))
    if len(class_starts) != len(classes):
        _raise_tex("TEX_DYNAMIC_COMMAND", "document class declaration is not a bounded literal")
    for declaration in classes:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", declaration.group("name").strip()):
            _raise_tex("TEX_EXTERNAL_PATH", "document class path is not a bounded identifier")


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
        if "^^" in text:
            _raise_tex("TEX_OBFUSCATED_COMMAND", "TeX character-code rewriting is forbidden")
        if _EXECUTION_DIRECTIVE_RE.search(text):
            _raise_tex("TEX_EXECUTION_DIRECTIVE", "executable TeX content is forbidden")
        if _WRITE_DIRECTIVE_RE.search(text):
            _raise_tex("TEX_WRITE_DIRECTIVE", "TeX file-write directives are forbidden")
        if _CONDITIONAL_INPUT_RE.search(text):
            _raise_tex("TEX_EXTERNAL_PATH", "conditional TeX file discovery is forbidden")
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
        _validate_tex_allowlist(text)

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
        matched_line = None
        for line_number, line in enumerate(text.splitlines() or [text], start=1):
            decoded_line = unquote_plus(line)
            if any(value and value in line for value in representations) or sentinel in decoded_line:
                matched_line = line_number
                break
        if matched_line is not None:
            findings.append(
                {
                    "code": "SECRET_SENTINEL",
                    "channel": channel,
                    "sentinel": name,
                    "line": matched_line,
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
    if not prose.strip() or _NO_EXECUTION_TEMPLATE_RE.fullmatch(prose):
        return {
            "ok": True,
            "policy": "execution_truth",
            "execution_claim": False,
            "findings": [],
        }

    admissibility = result_facts.get("admissibility")
    if not isinstance(admissibility, Mapping):
        _raise_execution("UNSUPPORTED_EXECUTION_CLAIM", "execution evidence is missing")
    if admissibility.get("script_only") is True:
        _raise_execution("SCRIPTS_ONLY", "scripts-only evidence cannot support execution prose")
    if admissibility.get("plan_only") is True:
        _raise_execution("PLAN_ONLY", "plan-only evidence cannot support execution prose")
    if admissibility.get("metadata_only") is True:
        _raise_execution("METADATA_ONLY", "metadata-only evidence cannot support execution prose")
    if result_facts.get("status") != "FROZEN":
        _raise_execution("RESULT_NOT_FROZEN", "only frozen results can support execution prose")

    receipt = result_facts.get("executor_receipt")
    raw_source = result_facts.get("raw_source")
    if not isinstance(receipt, Mapping) or not isinstance(raw_source, Mapping):
        _raise_execution("MISSING_EXECUTOR_RECEIPT", "an auditable executor receipt is required")
    executor_kind = str(receipt.get("executor_kind") or "")
    fixture_executor = executor_kind == "DETERMINISTIC_FIXTURE_NON_LLM"
    if not fixture_executor and re.search(r"(?:LLM|MODEL|REASONING)", executor_kind, re.IGNORECASE):
        _raise_execution("MODEL_AUTHORED_RECEIPT", "model-authored receipts are inadmissible")
    if executor_kind == "SIGNED_EXTERNAL_EXECUTOR":
        _raise_execution(
            "EXECUTION_REVERIFY_REQUIRED",
            "real executor receipts require independent signature and file reverification",
        )
    if not fixture_executor:
        _raise_execution("UNSUPPORTED_EXECUTOR_RECEIPT", "receipt is not from an approved executor")

    raw_sha = str(raw_source.get("sha256") or "")
    receipt_raw_sha = str(receipt.get("raw_source_sha256") or "")
    receipt_sha = str(receipt.get("receipt_sha256") or "")
    raw_bytes = raw_source.get("canonical_bytes")
    if (
        not isinstance(raw_bytes, str)
        or not _SHA256_RE.fullmatch(raw_sha)
        or not hmac.compare_digest(hashlib.sha256(raw_bytes.encode("utf-8")).hexdigest(), raw_sha.lower())
        or not hmac.compare_digest(receipt_raw_sha.lower(), raw_sha.lower())
    ):
        _raise_execution("RECEIPT_SOURCE_MISMATCH", "receipt is not bound to the raw result")
    receipt_bytes = receipt.get("receipt_canonical_bytes")
    if (
        not isinstance(receipt_bytes, str)
        or not _SHA256_RE.fullmatch(receipt_sha)
        or not hmac.compare_digest(
            hashlib.sha256(receipt_bytes.encode("utf-8")).hexdigest(), receipt_sha.lower()
        )
        or receipt.get("exit_code") != 0
    ):
        _raise_execution("INVALID_EXECUTOR_RECEIPT", "executor receipt is incomplete or unsuccessful")
    if admissibility.get("observed_evidence") is not True:
        _raise_execution("UNOBSERVED_EXECUTION", "execution prose requires observed evidence")

    requires_real_execution = bool(_REAL_EXECUTION_RE.search(prose))
    is_bounded_fixture = (
        result_facts.get("synthetic_fixture") is True
        and receipt.get("fixture_only") is True
        and admissibility.get("real_research_execution") is False
    )
    if requires_real_execution:
        _raise_execution("NOT_REAL_EXECUTION", "fixture evidence cannot establish real execution")
    if not is_bounded_fixture:
        _raise_execution(
            "EXECUTION_REVERIFY_REQUIRED",
            "non-fixture execution requires independent signature and file reverification",
        )
    if not _FIXTURE_DISCLOSURE_RE.search(prose):
        _raise_execution(
            "FIXTURE_DISCLOSURE_REQUIRED",
            "synthetic execution evidence must be disclosed in manuscript prose",
        )

    return {
        "ok": True,
        "policy": "execution_truth",
        "execution_claim": True,
        "evidence_class": "synthetic_fixture",
        "publishable": False,
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
