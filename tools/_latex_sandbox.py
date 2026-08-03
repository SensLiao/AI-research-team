"""Private filesystem and process primitives for :mod:`latex_build`.

This module has no manuscript policy.  It supplies descriptor-stable reads,
private staging, atomic byte publication, and bounded subprocess capture so the
public adapter can stay small and auditable.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence


class LatexSandboxViolation(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reparse(metadata: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and getattr(metadata, "st_file_attributes", 0) & marker)


def stable_file_bytes(
    path: str | os.PathLike[str],
    *,
    max_bytes: int | None = None,
    single_link: bool = True,
) -> bytes:
    """Read one regular file through a stable descriptor without following links."""

    target = Path(path)
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or _reparse(before):
        raise LatexSandboxViolation("UNSAFE_FILE_IDENTITY", "file is not a plain regular file")
    if single_link and before.st_nlink != 1:
        raise LatexSandboxViolation("UNSAFE_FILE_IDENTITY", "hard-linked files are not accepted")
    if max_bytes is not None and before.st_size > max_bytes:
        raise LatexSandboxViolation("OUTPUT_LIMIT_EXCEEDED", "file exceeds the bounded read limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    try:
        opened = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino, before.st_size)
        if identity != (opened.st_dev, opened.st_ino, opened.st_size):
            raise LatexSandboxViolation("FILE_IDENTITY_CHANGED", "file changed before descriptor binding")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise LatexSandboxViolation("OUTPUT_LIMIT_EXCEEDED", "file exceeds the bounded read limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise LatexSandboxViolation("FILE_IDENTITY_CHANGED", "file changed during descriptor read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def executable_sha256(path: str | os.PathLike[str], *, platform_name: str) -> str:
    target = Path(path).absolute()
    if platform_name == "nt" and target.suffix.casefold() != ".exe":
        raise LatexSandboxViolation("UNSAFE_EXECUTABLE", "Windows drivers must be .exe files")
    return hashlib.sha256(
        stable_file_bytes(target, max_bytes=256 * 1024 * 1024, single_link=False)
    ).hexdigest()


def _assert_plain_parent_chain(parent: Path) -> None:
    """Reject an existing link/reparse component without creating below it."""

    for directory in (parent, *parent.parents):
        if not os.path.lexists(directory):
            continue
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _reparse(metadata)
        ):
            raise LatexSandboxViolation(
                "UNSAFE_OUTPUT_PARENT",
                "atomic output parent must be a plain directory",
            )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Publish bytes without a predictable temporary name or link traversal.

    Callers still own authorization of ``path``.  This primitive additionally
    refuses a linked/reparse parent, so a pre-created ``*.tmp`` link cannot
    redirect a receipt, log, or director-facing projection outside its run.
    """

    target = path.absolute()
    _assert_plain_parent_chain(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_plain_parent_chain(target.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        published = target.lstat()
        if (
            not stat.S_ISREG(published.st_mode)
            or stat.S_ISLNK(published.st_mode)
            or _reparse(published)
        ):
            raise LatexSandboxViolation(
                "UNSAFE_OUTPUT_IDENTITY",
                "atomic output was not published as a plain regular file",
            )
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def stage_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in files.items():
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise LatexSandboxViolation("UNSAFE_STAGE_PATH", "source inventory contains an unsafe path")
        destination = root.joinpath(*pure.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            destination.chmod(0o400)


def text_artifacts(root: Path, *, max_bytes: int) -> dict[str, str]:
    """Read generated textual evidence with stable identities and a shared cap."""

    suffixes = {".log", ".aux", ".fls", ".bbl", ".blg", ".toc", ".out", ".lof", ".lot"}
    remaining = max_bytes
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.suffix.casefold() not in suffixes:
            continue
        data = stable_file_bytes(path, max_bytes=remaining)
        remaining -= len(data)
        result[path.relative_to(root).as_posix()] = data.decode("utf-8", errors="replace")
    return result


def validate_recorder_inputs(data: bytes, *, cwd: Path, allowed_roots: Sequence[Path]) -> None:
    roots = [root.resolve(strict=False) for root in allowed_roots]
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        raw = line[6:].strip().strip('"')
        if not raw:
            raise LatexSandboxViolation("RECORDER_INPUT_INVALID", "recorder contains an empty input")
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        resolved = candidate.resolve(strict=False)
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise LatexSandboxViolation(
                "RECORDER_INPUT_OUTSIDE_POLICY", "recorder input is outside approved TeX roots"
            )


@contextmanager
def private_workspace(build_root: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Yield a random private source/output pair and remove all scratch artifacts."""

    workspace = Path(tempfile.mkdtemp(prefix=".latex-private-", dir=build_root))
    source = workspace / "source"
    output = workspace / "output"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    try:
        workspace.chmod(0o700)
    except OSError:
        pass
    try:
        yield workspace, source, output
    finally:
        shutil.rmtree(workspace, ignore_errors=False)


def _capture(pipe: Any, sink: bytearray, limit: int) -> None:
    try:
        while True:
            chunk = pipe.read(65536)
            if not chunk:
                break
            room = max(0, limit - len(sink))
            if room:
                sink.extend(chunk[:room])
    finally:
        pipe.close()


def _kill_tree(process: subprocess.Popen[bytes], environment: Mapping[str, str]) -> None:
    if os.name == "nt":
        system_root = environment.get("SYSTEMROOT") or environment.get("WINDIR")
        taskkill = Path(system_root) / "System32" / "taskkill.exe" if system_root else None
        if taskkill and taskkill.is_file():
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=5,
                check=False,
            )
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def bounded_subprocess(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    env: Mapping[str, str],
    timeout: float,
    output_limit: int,
    shell: bool,
) -> dict[str, Any]:
    """Run one process with streaming output caps and descendant termination."""

    if shell is not False:
        raise LatexSandboxViolation("SHELL_FORBIDDEN", "subprocess shells are forbidden")
    started_at = _now()
    started = time.monotonic()
    options: dict[str, Any] = {"start_new_session": True}
    if os.name == "nt":
        options = {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        }
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        **options,
    )
    stdout = bytearray()
    stderr = bytearray()
    readers = [
        threading.Thread(target=_capture, args=(process.stdout, stdout, output_limit), daemon=True),
        threading.Thread(target=_capture, args=(process.stderr, stderr, output_limit), daemon=True),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        return_code = process.wait(timeout=max(0.001, float(timeout)))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process, env)
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait(timeout=5)
    for reader in readers:
        reader.join(timeout=5)
    return {
        "returncode": int(return_code if not timed_out else 124),
        "stdout": bytes(stdout).decode("utf-8", errors="replace"),
        "stderr": bytes(stderr).decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "started_at": started_at,
        "finished_at": _now(),
    }


def invoke_runner(
    runner: Callable[..., Mapping[str, Any]] | None,
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
    output_limit: int,
) -> dict[str, Any]:
    invoke = runner or bounded_subprocess
    result = dict(
        invoke(
            list(argv), cwd=str(cwd), env=environment, timeout=timeout,
            output_limit=output_limit, shell=False,
        )
    )
    result.setdefault("returncode", 1)
    result.setdefault("stdout", "")
    result.setdefault("stderr", "")
    result.setdefault("timed_out", False)
    result.setdefault("duration_ms", 0)
    result.setdefault("started_at", _now())
    result.setdefault("finished_at", _now())
    result["stdout"] = str(result["stdout"])[:output_limit]
    result["stderr"] = str(result["stderr"])[:output_limit]
    return result


__all__ = [
    "LatexSandboxViolation",
    "atomic_write_bytes",
    "bounded_subprocess",
    "executable_sha256",
    "invoke_runner",
    "private_workspace",
    "stable_file_bytes",
    "stage_files",
    "text_artifacts",
    "validate_recorder_inputs",
]
