"""Bounded, receipt-producing LaTeX builds for run-owned manuscript trees."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research_agent_teams.tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    ManuscriptTexViolation,
    scan_persisted_text,
    validate_run_owned_path,
    validate_tex_sources,
)
from research_agent_teams.tools._manuscript_integrator_security import scan_candidate_text
from research_agent_teams.tools._latex_sandbox import (
    LatexSandboxViolation,
    atomic_write_bytes,
    executable_sha256,
    invoke_runner,
    private_workspace,
    stable_file_bytes,
    stage_files,
    text_artifacts,
    validate_recorder_inputs,
)
from research_agent_teams.tools.runstore import atomic_write_text
from research_agent_teams.tools.validate_artifact import validate_payload


_ALLOWED_ENV = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "SOURCE_DATE_EPOCH",
    }
)
_OUTPUT_LIMIT = 512_000
_PROBE_TIMEOUT = 15
_BUILD_TIMEOUT = 180
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_REF_RE = re.compile(r"\\(?:ref|pageref|eqref|autoref|Cref|cref)\s*\{([^{}]+)\}")
_LABEL_RE = re.compile(r"\\label\s*\{([^{}]+)\}")
_ASSET_RE = re.compile(
    r"\\(?P<kind>input|include|includegraphics|addbibresource|bibliography)"
    r"\*?\s*(?:\[[^\[\]]*\]\s*)?\{(?P<value>[^{}]+)\}",
    re.IGNORECASE,
)
_UNRESOLVED_LOG_RE = re.compile(
    r"(?:undefined references?|citation [`'].+?[`'] .* undefined|"
    r"reference [`'].+?[`'] .* undefined)",
    re.IGNORECASE,
)
_EXECUTABLE_SUPPORT_SUFFIXES = frozenset(
    {".sty", ".cls", ".cfg", ".def", ".fd", ".lua", ".bst", ".pl", ".py", ".sh", ".bat", ".cmd", ".ps1", ".exe", ".dll"}
)


class LatexBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_STAMP)


def _miktex_installer_guard(executable: str) -> list[str]:
    """Disable MiKTeX's implicit package downloader for a bounded build."""

    return ["--disable-installer"] if "miktex" in str(executable).casefold() else []


def _scan_durable_bytes(
    label: str,
    files: Mapping[str, bytes],
    *,
    sentinels: Mapping[str, str] | None,
    patterns: Mapping[str, Any] | None,
) -> None:
    """Run the shared byte-aware secret scan without exposing matched values."""

    def fail(code: str, _message: str, *_details: object) -> None:
        raise LatexBuildError(code, f"{label} failed the durable-output safety scan")

    scan_candidate_text(files, fail=fail, sentinels=sentinels, patterns=patterns)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    return _digest_bytes(stable_file_bytes(path))


def _object_digest(value: Mapping[str, Any], omitted: str) -> str:
    return _digest_bytes(_canonical({key: item for key, item in value.items() if key != omitted}))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_root(run_root: str | os.PathLike[str], source_root: str | os.PathLike[str]) -> tuple[Path, Path]:
    run = Path(run_root).absolute().resolve(strict=True)
    source_input = Path(source_root).absolute()
    try:
        validate_run_owned_path(
            source_input / ".source-boundary-probe",
            run_root=run,
            purpose="read",
            owned_output_roots=(source_input,),
        )
    except (ManuscriptPathViolation, OSError) as exc:
        raise LatexBuildError("SOURCE_OUTSIDE_RUN", "source tree crosses an unsafe path boundary") from exc
    try:
        source = source_input.resolve(strict=True)
    except OSError as exc:
        raise LatexBuildError("SOURCE_MISSING", "manuscript source tree is unavailable") from exc
    if not source.is_dir() or not _inside(source, run):
        raise LatexBuildError("SOURCE_OUTSIDE_RUN", "source tree must be an existing run-owned directory")
    cursor = source
    while cursor != run:
        if cursor.is_symlink():
            raise LatexBuildError("SOURCE_OUTSIDE_RUN", "source tree may not traverse a link")
        cursor = cursor.parent
    return run, source


def _kind(relative: str) -> str:
    if relative == "main.tex":
        return "MAIN_TEX"
    if relative == "refs.bib":
        return "BIBLIOGRAPHY"
    if relative.startswith("sections/"):
        return "SECTION"
    if relative == "manifests/asset-manifest.json":
        return "ASSET_MANIFEST"
    if relative.startswith("figures/"):
        return "FIGURE"
    if relative.startswith("tables/"):
        return "TABLE"
    return "OTHER"


def _source_snapshot(run: Path, source: Path) -> tuple[str, dict[str, str], dict[str, bytes]]:
    inventory: list[dict[str, str]] = []
    tex_sources: dict[str, str] = {}
    source_files: dict[str, bytes] = {}
    for path in sorted((item for item in source.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise LatexBuildError("SOURCE_OUTSIDE_RUN", "source files may not be links")
        checked = validate_run_owned_path(
            path, run_root=run, purpose="read", owned_output_roots=(source,)
        )
        try:
            data = stable_file_bytes(path, max_bytes=64 * 1024 * 1024)
        except LatexSandboxViolation as exc:
            raise LatexBuildError("SOURCE_CHANGED", "source identity is not stable") from exc
        relative = checked["relative_path"]
        source_relative = path.relative_to(source).as_posix()
        inventory.append(
            {"path": source_relative, "sha256": _digest_bytes(data), "kind": _kind(source_relative)}
        )
        source_files[source_relative] = data
        if path.suffix.casefold() in {".tex", ".bib"}:
            try:
                tex_sources[source_relative] = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LatexBuildError("SOURCE_ENCODING", f"{relative} is not UTF-8") from exc
    if "main.tex" not in tex_sources:
        raise LatexBuildError("MAIN_TEX_MISSING", "source/main.tex is required")
    physical_hash = _digest_bytes(_canonical(inventory))
    manifest_ref = "manifests/manuscript-integration.json"
    manifest_bytes = source_files.get(manifest_ref)
    if manifest_bytes is None:
        return physical_hash, tex_sources, source_files
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        canonical_inventory = manifest["canonical_file_inventory"]
        canonical_hash = manifest["source_tree_sha256"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LatexBuildError(
            "SOURCE_CHANGED", "integration manifest is malformed"
        ) from exc
    expected = {
        str(row["path"]): str(row["sha256"])
        for row in canonical_inventory
        if isinstance(row, Mapping) and row.get("path") and row.get("sha256")
    }
    if len(expected) != len(canonical_inventory):
        raise LatexBuildError("SOURCE_CHANGED", "integration inventory is malformed")
    actual_paths = set(source_files) - {manifest_ref}
    if actual_paths != set(expected):
        raise LatexBuildError("SOURCE_CHANGED", "source files differ from integration inventory")
    if any(_digest_bytes(source_files[path]) != digest for path, digest in expected.items()):
        raise LatexBuildError("SOURCE_CHANGED", "source file hash differs from integration inventory")
    if _digest_bytes(_canonical(canonical_inventory)) != canonical_hash:
        raise LatexBuildError("SOURCE_CHANGED", "integration source-tree hash does not verify")
    return canonical_hash, tex_sources, source_files


def _asset_exists(source: Path, kind: str, raw: str) -> bool:
    values = raw.split(",") if kind.casefold() == "bibliography" else [raw]
    for value in values:
        value = value.strip()
        candidate = source / value
        suffixes: Sequence[str]
        if candidate.suffix:
            suffixes = ("",)
        elif kind.casefold() in {"input", "include"}:
            suffixes = ("", ".tex")
        elif kind.casefold() in {"bibliography", "addbibresource"}:
            suffixes = ("", ".bib")
        else:
            suffixes = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps")
        if not any((Path(str(candidate) + suffix)).is_file() for suffix in suffixes):
            return False
    return True


def _preflight(
    run: Path,
    source: Path,
    tex_sources: Mapping[str, str],
    source_files: Mapping[str, bytes],
    *,
    sentinels: Mapping[str, str] | None,
    patterns: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    if any(Path(name).suffix.casefold() in _EXECUTABLE_SUPPORT_SUFFIXES for name in source_files):
        return "UNSAFE_TEX_SUPPORT_FILE", "local executable TeX support files are forbidden"
    try:
        _scan_durable_bytes(
            "manuscript source",
            source_files,
            sentinels=sentinels,
            patterns=patterns,
        )
    except LatexBuildError as exc:
        return exc.code, "source tree failed durable-material safety scanning"
    try:
        validate_tex_sources(tex_sources, run_root=run, source_root=source)
    except ManuscriptTexViolation:
        return "UNSAFE_TEX_SOURCE", "TeX source failed the bounded command policy"
    combined = "\n".join(tex_sources.values())
    try:
        scan_persisted_text("latex-source", combined, sentinels=sentinels, patterns=patterns)
    except ManuscriptSecretViolation:
        return "SECRET_LEAKAGE", "TeX source contains caller-identified secret material"
    for match in _ASSET_RE.finditer(combined):
        if not _asset_exists(source, match.group("kind"), match.group("value")):
            return "MISSING_BUILD_ASSET", "a referenced manuscript asset is missing"
    labels = set(_LABEL_RE.findall(combined))
    references = set(_REF_RE.findall(combined))
    if references - labels:
        return "UNRESOLVED_REFERENCE", "a manuscript reference has no matching label"
    return None, None


def _sanitize_environment(environment: Mapping[str, str] | None) -> tuple[dict[str, str], str | None]:
    supplied = dict(os.environ if environment is None else environment)
    raw_candidates = supplied.get("RAT_LATEX_DRIVER_RUNTIME_CANDIDATES")
    clean = {
        key: str(value)
        for key, value in supplied.items()
        if key.upper() in _ALLOWED_ENV and value is not None
    }
    clean.setdefault("PATH", "")
    clean["openin_any"] = "p"
    clean["openout_any"] = "p"
    return clean, raw_candidates


def _prepend_path(environment: dict[str, str], parents: Sequence[Path], platform_name: str) -> None:
    current = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
    combined = [str(parent) for parent in parents] + current
    seen: set[str] = set()
    unique: list[str] = []
    for item in combined:
        key = os.path.normcase(os.path.abspath(item)) if platform_name == "nt" else os.path.abspath(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    environment["PATH"] = os.pathsep.join(unique)


def _which_call(which: Callable[..., str | None], name: str, environment: Mapping[str, str]) -> str | None:
    try:
        found = which(name, path=environment.get("PATH", ""))
    except TypeError:
        found = which(name)
    return str(Path(found).absolute()) if found else None


def _candidate_perl(raw: str | None, platform_name: str) -> Path | None:
    if raw is None:
        return None
    names = ("perl.exe", "perl") if platform_name == "nt" else ("perl", "perl.exe")
    seen: set[str] = set()
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        candidate = Path(item.strip()).absolute()
        candidates = [candidate] if candidate.name.casefold() in names else [candidate / name for name in names]
        for executable in candidates:
            key = os.path.normcase(str(executable)) if platform_name == "nt" else str(executable)
            if key in seen:
                continue
            seen.add(key)
            if executable.is_file():
                return executable
    return None


def _windows_miktex(environment: Mapping[str, str], name: str) -> str | None:
    local = environment.get("LOCALAPPDATA")
    if not local:
        return None
    candidate = Path(local) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / f"{name}.exe"
    return str(candidate.absolute()) if candidate.is_file() else None


def _version(result: Mapping[str, Any], fallback: str) -> str:
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first = next(
        (line for line in lines if re.search(r"(?:latexmk|version|pdftex)", line, re.IGNORECASE)),
        lines[0] if lines else fallback,
    )
    return first[:240] or fallback


def detect_latex_toolchain(
    run_root: str | os.PathLike[str],
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[..., str | None] = shutil.which,
    runner: Callable[..., Mapping[str, Any]] | None = None,
    platform_name: str | None = None,
    runtime_candidates: str | None = None,
    prefer_direct: bool = False,
    timeout: int = _PROBE_TIMEOUT,
    output_limit: int = _OUTPUT_LIMIT,
) -> dict[str, Any]:
    run = Path(run_root).absolute()
    clean, declared = _sanitize_environment(environment)
    if runtime_candidates is not None:
        declared = runtime_candidates
    host = platform_name or os.name
    diagnostics: list[str] = []
    identities: dict[str, str] = {}

    def bind(name: str, path: str | None) -> str | None:
        if not path:
            return None
        try:
            identities[name] = executable_sha256(path, platform_name=host)
            return path
        except (OSError, LatexSandboxViolation):
            diagnostics.append(f"{name.upper()}_IDENTITY_REJECTED")
            return None

    perl = _which_call(which, "perl", clean)
    if not perl:
        candidate = _candidate_perl(declared, host)
        perl = str(candidate) if candidate else None
    perl = bind("perl", perl)
    if perl:
        _prepend_path(clean, (Path(perl).parent,), host)

    def discover(name: str) -> str | None:
        found = _which_call(which, name, clean)
        if not found and host == "nt":
            found = _windows_miktex(clean, name)
        found = bind(name, found)
        if found:
            _prepend_path(clean, (Path(found).parent,), host)
        return found

    latexmk = discover("latexmk")
    if latexmk and perl and not prefer_direct:
        probe = invoke_runner(
            runner, (latexmk, "-v"), cwd=run, environment=clean,
            timeout=timeout, output_limit=output_limit,
        )
        if probe["returncode"] == 0 and not probe["timed_out"]:
            return {
                "state": "READY", "driver": "latexmk",
                "executables": {"latexmk": latexmk, "perl": perl},
                "executable_sha256": {key: identities[key] for key in ("latexmk", "perl")},
                "environment": clean, "version": _version(probe, "latexmk version unavailable"),
                "diagnostics": diagnostics,
            }
        diagnostics.append("LATEXMK_READINESS_FAILED")
    elif latexmk and not prefer_direct:
        diagnostics.append("LATEXMK_RUNTIME_UNAVAILABLE")
    elif latexmk and prefer_direct:
        diagnostics.append("LATEXMK_SKIPPED_DIRECT_PREFERENCE")

    pdflatex = discover("pdflatex")
    if pdflatex:
        engine_probe = invoke_runner(
            runner, (pdflatex, "--version"), cwd=run, environment=clean,
            timeout=timeout, output_limit=output_limit,
        )
        if engine_probe["returncode"] == 0 and not engine_probe["timed_out"]:
            for bibliography in ("bibtex", "biber"):
                bibliography_path = discover(bibliography)
                if not bibliography_path:
                    continue
                bib_probe = invoke_runner(
                    runner, (bibliography_path, "--version"), cwd=run,
                    environment=clean, timeout=timeout, output_limit=output_limit,
                )
                if bib_probe["returncode"] == 0 and not bib_probe["timed_out"]:
                    return {
                        "state": "READY", "driver": "direct", "bibliography": bibliography,
                        "executables": {"pdflatex": pdflatex, bibliography: bibliography_path},
                        "executable_sha256": {
                            "pdflatex": identities["pdflatex"],
                            bibliography: identities[bibliography],
                        },
                        "environment": clean,
                        "version": _version(engine_probe, "pdflatex version unavailable"),
                        "diagnostics": diagnostics,
                    }
        diagnostics.append("DIRECT_READINESS_FAILED")
    return {
        "state": "TOOLCHAIN_MISSING", "driver": None, "executables": {},
        "environment": clean, "diagnostics": diagnostics + ["NO_RUNNABLE_LATEX_DRIVER"],
    }


def _process_receipt(
    *,
    executable: str,
    version: str,
    argv: list[str],
    tex_engine: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    process = {
        "executable": executable,
        "executable_version": version,
        "argv": argv,
        "operating_system": platform.system() or os.name,
        "tex_engine": tex_engine,
        "return_code": int(result["returncode"]),
        "duration_ms": max(0, int(result["duration_ms"])),
        "timed_out": bool(result["timed_out"]),
        "shell": False,
        "shell_escape": False,
        "started_at": str(result["started_at"]),
        "finished_at": str(result["finished_at"]),
    }
    process["receipt_sha256"] = _object_digest(process, "receipt_sha256")
    return process


def _base_receipt(
    run_id: str, snapshot_hash: str, source_ref: str, source_hash: str,
    requires_pdf: bool, state: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0", "run_id": run_id,
        "manuscript_snapshot_sha256": snapshot_hash,
        "source_tree_ref": source_ref, "source_tree_sha256": source_hash,
        "requires_pdf": bool(requires_pdf), "build_state": state,
    }


def _finish_receipt(run: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    receipt["build_receipt_sha256"] = _object_digest(receipt, "build_receipt_sha256")
    errors = validate_payload("manuscript_build_receipt", receipt)
    if errors:
        raise LatexBuildError("INVALID_BUILD_RECEIPT", "; ".join(errors[:3]))
    destination = run / "evidence" / "manuscript-build-receipt.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    validate_run_owned_path(destination, run_root=run, purpose="write")
    atomic_write_text(destination, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def _safe_log_text(
    records: Sequence[tuple[list[str], Mapping[str, Any]]],
    diagnostics: Sequence[str],
    *,
    run: Path,
) -> str:
    rows = list(diagnostics)
    for argv, result in records:
        portable = [Path(argv[0]).name, *[str(arg).replace(str(run), "<RUN>") for arg in argv[1:]]]
        rows.extend(
            [
                f"argv={json.dumps(portable, ensure_ascii=False)}",
                f"return_code={int(result['returncode'])}",
                f"duration_ms={max(0, int(result['duration_ms']))}",
                f"timed_out={str(bool(result['timed_out'])).lower()}",
                f"stdout={str(result.get('stdout', ''))}",
                f"stderr={str(result.get('stderr', ''))}",
            ]
        )
    text = "\n".join(rows) + "\n"
    text = text.replace(str(run), "<RUN>").replace(str(Path.home()), "<HOME>")
    text = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^/\\\r\n]+", "<HOME>", text)
    return text[:_OUTPUT_LIMIT]


def build_latex_project(
    run_root: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    run_id: str,
    manuscript_snapshot_sha256: str,
    requires_pdf: bool,
    environment: Mapping[str, str] | None = None,
    which: Callable[..., str | None] = shutil.which,
    runner: Callable[..., Mapping[str, Any]] | None = None,
    platform_name: str | None = None,
    runtime_candidates: str | None = None,
    prefer_direct: bool = False,
    timeout: int = _BUILD_TIMEOUT,
    output_limit: int = _OUTPUT_LIMIT,
    secret_sentinels: Mapping[str, str] | None = None,
    secret_patterns: Mapping[str, Any] | None = None,
    clock: Callable[[], str] = _now,
) -> dict[str, Any]:
    run, source = _safe_root(run_root, source_root)
    source_hash, tex_sources, source_files = _source_snapshot(run, source)
    source_ref = source.relative_to(run).as_posix()
    preflight_code, preflight_message = _preflight(
        run, source, tex_sources, source_files,
        sentinels=secret_sentinels, patterns=secret_patterns,
    )
    build = run / "build"
    log_path = build / "build.log"
    pdf_path = build / "main.pdf"
    recorder_path = build / "main.fls"
    for stale in (log_path, pdf_path, recorder_path):
        validate_run_owned_path(
            stale, run_root=run, purpose="write", owned_output_roots=(build,)
        )
    build.mkdir(parents=True, exist_ok=True)
    for stale in (log_path, pdf_path, recorder_path):
        if stale.exists() and stale.is_file():
            stale.unlink()

    if preflight_code:
        observed = clock()
        result = {
            "returncode": 2, "duration_ms": 0, "timed_out": False,
            "started_at": observed, "finished_at": observed,
        }
        argv = ["preflight", "-norc", "-recorder", "-halt-on-error", "-no-shell-escape"]
        process = _process_receipt(
            executable="preflight", version="bounded-source-policy/1.0", argv=argv,
            tex_engine="preflight", result=result,
        )
        log_text = f"{preflight_code}: {preflight_message}\n"
        atomic_write_text(log_path, log_text)
        receipt = _base_receipt(
            run_id, manuscript_snapshot_sha256, source_ref, source_hash,
            requires_pdf, "COMPILE_FAILED",
        )
        receipt.update(
            {
                "process_receipt": process,
                "log_ref": log_path.relative_to(run).as_posix(),
                "log_sha256": _digest_file(log_path),
                "failure": {
                    "kind": "COMPILE_FAILED", "code": preflight_code,
                    "safe_message": preflight_message or "manuscript preflight failed",
                    "observed_at": observed,
                },
            }
        )
        return _finish_receipt(run, receipt)

    selected = detect_latex_toolchain(
        run, environment=environment, which=which, runner=runner,
        platform_name=platform_name, runtime_candidates=runtime_candidates,
        prefer_direct=prefer_direct,
        output_limit=output_limit,
    )
    if selected["state"] != "READY":
        receipt = _base_receipt(
            run_id, manuscript_snapshot_sha256, source_ref, source_hash,
            requires_pdf, "TOOLCHAIN_MISSING",
        )
        receipt["failure"] = {
            "kind": "TOOLCHAIN_MISSING", "code": "NO_RUNNABLE_LATEX_DRIVER",
            "safe_message": "no runnable LaTeX driver was found in the sanitized build environment",
            "observed_at": clock(),
        }
        return _finish_receipt(run, receipt)

    env = selected["environment"]
    records: list[tuple[list[str], Mapping[str, Any]]] = []
    host = platform_name or os.name

    def identity_is_current() -> bool:
        try:
            return all(
                executable_sha256(path, platform_name=host)
                == selected["executable_sha256"][name]
                for name, path in selected["executables"].items()
            )
        except (OSError, LatexSandboxViolation):
            return False

    hash_diagnostics = [
        f"TOOL_SHA256 {name}={digest}"
        for name, digest in sorted(selected["executable_sha256"].items())
    ]
    failure_code: str | None = None
    failure_message: str | None = None
    pdf_bytes = b""
    recorder_bytes = b""

    with private_workspace(build, platform_name=host) as (_workspace, staged_source, private_output):
        stage_files(staged_source, source_files)
        deadline = time.monotonic() + max(0.001, float(timeout))
        last_command_timeout = float("inf")

        def run_command(command: list[str], cwd: Path) -> Mapping[str, Any]:
            nonlocal failure_code, failure_message, last_command_timeout
            if not identity_is_current():
                failure_code = "TOOL_IDENTITY_CHANGED"
                failure_message = "selected tool identity changed after readiness probing"
                stamp = clock()
                return {
                    "returncode": 126, "timed_out": False, "duration_ms": 0,
                    "started_at": stamp, "finished_at": stamp,
                }
            # Preserve a strictly shrinking allowance for a multi-process
            # direct pipeline even on coarse monotonic-clock platforms.
            remaining = min(deadline - time.monotonic(), last_command_timeout - 1e-6)
            if remaining <= 0:
                stamp = clock()
                return {
                    "returncode": 124, "timed_out": True, "duration_ms": 0,
                    "started_at": stamp, "finished_at": stamp,
                }
            last_command_timeout = remaining
            outcome = invoke_runner(
                runner, command, cwd=cwd, environment=env, timeout=remaining,
                output_limit=output_limit,
            )
            records.append((command, outcome))
            if not identity_is_current():
                failure_code = "TOOL_IDENTITY_CHANGED"
                failure_message = "selected tool identity changed during compilation"
                outcome = dict(outcome)
                outcome["returncode"] = 126
            return outcome

        if selected["driver"] == "latexmk":
            executable_path = selected["executables"]["latexmk"]
            executable = Path(executable_path).name
            installer_guard = _miktex_installer_guard(executable_path)
            actual = [
                executable_path, *installer_guard, "-norc", "-gg", "-pdf", "-interaction=nonstopmode",
                "-halt-on-error", "-file-line-error", "-recorder", "-no-shell-escape",
                f"-outdir={private_output}", "main.tex",
            ]
            result = run_command(actual, staged_source)
            portable_argv = [
                executable, *installer_guard, "-norc", "-gg", "-pdf", "-interaction=nonstopmode",
                "-halt-on-error", "-file-line-error", "-recorder", "-no-shell-escape",
                "-outdir=private-output", "main.tex",
            ]
            aggregate = dict(result)
        else:
            engine = selected["executables"]["pdflatex"]
            bib_name = selected["bibliography"]
            bib = selected["executables"][bib_name]
            bibliography_source = staged_source / "refs.bib"
            if bibliography_source.is_file():
                shutil.copyfile(bibliography_source, private_output / "refs.bib")
            engine_guard = _miktex_installer_guard(engine)
            bibliography_guard = _miktex_installer_guard(bib)
            engine_args = [
                *engine_guard, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
                "-recorder", "-no-shell-escape", f"-output-directory={private_output}",
                "main.tex",
            ]
            passes = [
                [engine, *engine_args],
                [bib, *bibliography_guard, "main"],
                [engine, *engine_args],
                [engine, *engine_args],
                [engine, *engine_args],
            ]
            for index, command in enumerate(passes):
                result = run_command(command, private_output if index == 1 else staged_source)
                if result["returncode"] != 0 or result["timed_out"] or failure_code:
                    break
            executable = "direct-pipeline"
            portable_argv = [
                executable, "-norc", "-recorder", "-halt-on-error", "-no-shell-escape",
                *engine_guard, "pdflatex", *bibliography_guard, bib_name,
                "pdflatex", "pdflatex", "pdflatex",
            ]
            aggregate = {
                "returncode": int(result["returncode"]),
                "timed_out": any(bool(item[1]["timed_out"]) for item in records),
                "duration_ms": sum(int(item[1]["duration_ms"]) for item in records),
                "started_at": (records[0][1] if records else result)["started_at"],
                "finished_at": (records[-1][1] if records else result)["finished_at"],
            }

        tex_engine = "pdflatex"
        log_text = _safe_log_text(
            records, [*selected.get("diagnostics", ()), *hash_diagnostics], run=run
        )
        generated_text: dict[str, str] = {}
        try:
            generated_text = text_artifacts(private_output, max_bytes=output_limit)
        except (OSError, LatexSandboxViolation):
            failure_code = failure_code or "OUTPUT_IDENTITY_INVALID"
            failure_message = failure_message or "generated artifacts failed stable bounded reads"
        engine_log_text = generated_text.get("main.log", "")
        secret_leak = False
        try:
            scan_persisted_text(
                "latex-build-log", log_text,
                sentinels=secret_sentinels, patterns=secret_patterns,
            )
            scan_persisted_text(
                "latex-tool-version", str(selected["version"]),
                sentinels=secret_sentinels, patterns=secret_patterns,
            )
            for name, text in generated_text.items():
                scan_persisted_text(
                    f"latex-artifact:{name}", text,
                    sentinels=secret_sentinels, patterns=secret_patterns,
                )
        except ManuscriptSecretViolation:
            secret_leak = True
            selected["version"] = "[REDACTED_TOOL_VERSION]"
            log_text = "[REDACTED_SECRET_OUTPUT]\n"

        if secret_leak:
            failure_code, failure_message = (
                "SECRET_LEAKAGE", "generated build artifacts contained secret material"
            )
        elif failure_code:
            pass
        elif aggregate["timed_out"]:
            failure_code, failure_message = "PROCESS_TIMEOUT", "LaTeX build exceeded its total deadline"
        elif aggregate["returncode"] != 0:
            failure_code, failure_message = "PROCESS_NONZERO", "LaTeX build process returned a non-zero status"
        elif engine_log_text and _UNRESOLVED_LOG_RE.search(engine_log_text):
            failure_code, failure_message = "UNRESOLVED_REFERENCE", "LaTeX build left unresolved references or citations"
        else:
            try:
                pdf_bytes = stable_file_bytes(private_output / "main.pdf", max_bytes=512 * 1024 * 1024)
                recorder_bytes = stable_file_bytes(private_output / "main.fls", max_bytes=output_limit)
                _scan_durable_bytes(
                    "compiler output",
                    {"main.pdf": pdf_bytes, "main.fls": recorder_bytes},
                    sentinels=secret_sentinels,
                    patterns=secret_patterns,
                )
                roots = [staged_source, private_output]
                for key in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA"):
                    if env.get(key):
                        roots.extend([Path(env[key]) / "MiKTeX", Path(env[key]) / "Programs" / "MiKTeX"])
                if host != "nt":
                    roots.extend(
                        Path(item) for item in (
                            "/usr/share/texlive", "/usr/share/texmf", "/usr/local/texlive",
                            "/var/lib/texmf", "/etc/texmf", "/usr/share/fonts",
                        )
                    )
                validate_recorder_inputs(recorder_bytes, cwd=staged_source, allowed_roots=roots)
            except FileNotFoundError:
                failure_code, failure_message = "PDF_MISSING", "build did not produce PDF and recorder outputs"
            except LatexSandboxViolation:
                failure_code, failure_message = "OUTPUT_IDENTITY_INVALID", "PDF or recorder identity failed validation"
            except LatexBuildError as exc:
                failure_code, failure_message = exc.code, "compiler output failed durable-material safety scanning"
            if not failure_code and not pdf_bytes:
                failure_code, failure_message = "PDF_MISSING", "build did not produce a non-empty PDF"
            if not failure_code:
                try:
                    current_source_hash, _, _ = _source_snapshot(run, source)
                except LatexBuildError:
                    current_source_hash = ""
                if current_source_hash != source_hash:
                    failure_code, failure_message = "SOURCE_CHANGED", "source tree changed during compilation"

        atomic_write_text(log_path, log_text)
        if not failure_code:
            atomic_write_bytes(pdf_path, pdf_bytes)
            atomic_write_bytes(recorder_path, recorder_bytes)

    if failure_code:
        if pdf_path.is_file():
            pdf_path.unlink()
        failed = dict(aggregate)
        if failed["returncode"] == 0 and not failed["timed_out"]:
            failed["returncode"] = 1
        process = _process_receipt(
            executable=executable, version=selected["version"], argv=portable_argv,
            tex_engine=tex_engine, result=failed,
        )
        receipt = _base_receipt(
            run_id, manuscript_snapshot_sha256, source_ref, source_hash,
            requires_pdf, "COMPILE_FAILED",
        )
        receipt.update(
            {
                "process_receipt": process,
                "log_ref": log_path.relative_to(run).as_posix(),
                "log_sha256": _digest_file(log_path),
                "failure": {
                    "kind": "COMPILE_FAILED", "code": failure_code,
                    "safe_message": failure_message or "LaTeX build failed",
                    "observed_at": clock(),
                },
            }
        )
        return _finish_receipt(run, receipt)

    process = _process_receipt(
        executable=executable, version=selected["version"], argv=portable_argv,
        tex_engine=tex_engine, result=aggregate,
    )
    receipt = _base_receipt(
        run_id, manuscript_snapshot_sha256, source_ref, source_hash,
        requires_pdf, "COMPILED",
    )
    receipt.update(
        {
            "process_receipt": process,
            "log_ref": log_path.relative_to(run).as_posix(),
            "log_sha256": _digest_file(log_path),
            "recorder_ref": recorder_path.relative_to(run).as_posix(),
            "recorder_sha256": _digest_bytes(recorder_bytes),
            "pdf": {
                "path": pdf_path.relative_to(run).as_posix(),
                "sha256": _digest_bytes(pdf_bytes), "byte_size": len(pdf_bytes),
            },
        }
    )
    return _finish_receipt(run, receipt)


__all__ = ["LatexBuildError", "build_latex_project", "detect_latex_toolchain"]
