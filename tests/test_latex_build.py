"""TDD contract for the bounded LaTeX detector and build state machine."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from research_agent_teams.tools.latex_build import (
    LatexBuildError,
    build_latex_project,
    detect_latex_toolchain,
)
from research_agent_teams.tools.validate_artifact import validate_payload


HEX = {letter: letter * 64 for letter in "abcdef0123456789"}


def _source_tree(run_root: Path, main: str | None = None) -> Path:
    source = run_root / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.tex").write_text(
        main
        or (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\section{Fixture}\\label{sec:fixture}\n"
            "A bounded build; see Section~\\ref{sec:fixture}.\n"
            "\\end{document}\n"
        ),
        encoding="utf-8",
    )
    return source


def _fake_tools(root: Path, *names: str) -> dict[str, str]:
    tool_dir = root / "tool chain"
    tool_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    suffix = ".exe" if os.name == "nt" else ""
    for name in names:
        path = tool_dir / f"{name}{suffix}"
        path.write_bytes(b"fixture executable")
        path.chmod(0o755)
        paths[name] = str(path.resolve())
    return paths


def _which(paths: dict[str, str]):
    def resolve(name: str, *, path: str | None = None):
        del path
        return paths.get(name)

    return resolve


def _basename(value: str) -> str:
    return Path(value).stem.casefold()


class FakeRunner:
    def __init__(
        self,
        run_root: Path,
        *,
        mode: str = "success",
        unhealthy: set[str] | None = None,
        secret: str | None = None,
    ) -> None:
        self.run_root = run_root
        self.mode = mode
        self.unhealthy = unhealthy or set()
        self.secret = secret
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        call = {"argv": list(argv), **kwargs}
        self.calls.append(call)
        name = _basename(str(argv[0]))
        probe = any(arg in {"-v", "--version"} for arg in argv[1:])
        if probe:
            failed = name in self.unhealthy
            return self._result(returncode=1 if failed else 0, stdout=f"{name} fixture 1.0")
        if self.mode == "timeout":
            return self._result(returncode=124, stdout="timed out", timed_out=True)
        if self.mode == "failure":
            return self._result(returncode=12, stdout="compiler failed")
        output = self.secret or "fixture compiler output"
        if self.mode == "success" and name in {"latexmk", "pdflatex"}:
            build = self._output_dir(argv)
            build.mkdir(exist_ok=True)
            (build / "main.pdf").write_bytes(b"%PDF-1.4 fixture\n")
            (build / "main.fls").write_text("INPUT main.tex\nOUTPUT main.pdf\n", encoding="utf-8")
        return self._result(returncode=0, stdout=output)

    def _output_dir(self, argv) -> Path:
        for argument in argv:
            for prefix in ("-outdir=", "-output-directory="):
                if str(argument).startswith(prefix):
                    return Path(str(argument)[len(prefix) :])
        return self.run_root / "build"

    @staticmethod
    def _result(*, returncode: int, stdout: str, timed_out: bool = False) -> dict:
        return {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": "",
            "timed_out": timed_out,
            "duration_ms": 7,
            "started_at": "2026-07-21T10:00:00Z",
            "finished_at": "2026-07-21T10:00:01Z",
        }


def _build(
    run_root: Path,
    tools: dict[str, str],
    runner: FakeRunner,
    *,
    environment: dict[str, str] | None = None,
    runtime_candidates: str | None = None,
    platform_name: str | None = None,
    **kwargs,
) -> dict:
    source = _source_tree(run_root)
    env = {"PATH": "", "LOCALAPPDATA": str(run_root / "local app")}
    env.update(environment or {})
    if runtime_candidates is not None:
        env["RAT_LATEX_DRIVER_RUNTIME_CANDIDATES"] = runtime_candidates
    return build_latex_project(
        run_root,
        source,
        run_id="build-run-001",
        manuscript_snapshot_sha256=HEX["a"],
        requires_pdf=True,
        environment=env,
        which=_which(tools),
        runner=runner,
        platform_name=platform_name or ("nt" if os.name == "nt" else "posix"),
        **kwargs,
    )


def _assert_valid(receipt: dict) -> None:
    assert validate_payload("manuscript_build_receipt", receipt) == []
    unsigned = {key: value for key, value in receipt.items() if key != "build_receipt_sha256"}
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert receipt["build_receipt_sha256"] == hashlib.sha256(raw).hexdigest()


def test_driver_readiness_uses_build_sanitized_environment(tmp_path):
    run_root = tmp_path / "run with spaces"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "perl", "pdflatex", "bibtex")
    runner = FakeRunner(run_root)
    perl_parent = str(Path(tools["perl"]).parent)
    candidates = os.pathsep.join([perl_parent, perl_parent, tools["perl"]])
    original = {
        "PATH": "fixture-base-path",
        "LOCALAPPDATA": str(tmp_path / "Local App Data"),
        "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES": candidates,
        "UNSAFE_SECRET": "must-not-reach-child",
    }

    receipt = _build(
        run_root,
        tools,
        runner,
        environment=original,
        runtime_candidates=candidates,
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILED"
    assert len(runner.calls) >= 2
    first_env = runner.calls[0]["env"]
    assert all(call["env"] == first_env for call in runner.calls)
    assert all(call["shell"] is False for call in runner.calls)
    assert first_env["PATH"].split(os.pathsep).count(perl_parent) == 1
    assert "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES" not in first_env
    assert "UNSAFE_SECRET" not in first_env
    assert original["PATH"] == "fixture-base-path"
    durable = json.dumps(receipt, ensure_ascii=False)
    assert Path.home().name not in durable
    assert "-no-shell-escape" in receipt["process_receipt"]["argv"]
    assert not {"-shell-escape", "--shell-escape", "--enable-write18"}.intersection(
        receipt["process_receipt"]["argv"]
    )


def test_latexmk_present_without_perl_falls_back_to_direct_pipeline(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "pdflatex", "bibtex")
    runner = FakeRunner(run_root)

    receipt = _build(run_root, tools, runner, runtime_candidates="")

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILED"
    assert receipt["process_receipt"]["executable"] == "direct-pipeline"
    assert "pdflatex" in " ".join(receipt["process_receipt"]["argv"]).casefold()
    assert "bibtex" in " ".join(receipt["process_receipt"]["argv"]).casefold()
    actual = [
        _basename(call["argv"][0])
        for call in runner.calls
        if not any(arg in {"-v", "--version"} for arg in call["argv"][1:])
    ]
    assert actual == ["pdflatex", "bibtex", "pdflatex", "pdflatex"]
    log = (run_root / receipt["log_ref"]).read_text(encoding="utf-8")
    assert "LATEXMK_RUNTIME_UNAVAILABLE" in log


def test_fake_latexmk_success_binds_fresh_pdf_source_and_receipts(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "perl")
    runner = FakeRunner(run_root)

    first = _build(
        run_root,
        tools,
        runner,
        runtime_candidates=str(Path(tools["perl"]).parent),
    )
    second = _build(
        run_root,
        tools,
        runner,
        runtime_candidates=str(Path(tools["perl"]).parent),
    )

    _assert_valid(first)
    _assert_valid(second)
    assert first["build_state"] == "COMPILED"
    assert first["source_tree_sha256"] == second["source_tree_sha256"]
    assert first["pdf"]["sha256"] == hashlib.sha256(b"%PDF-1.4 fixture\n").hexdigest()
    assert first["pdf"]["byte_size"] > 0
    assert first["process_receipt"]["receipt_sha256"]
    assert first["log_sha256"] and first["recorder_sha256"]


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("failure", "PROCESS_NONZERO"),
        ("timeout", "PROCESS_TIMEOUT"),
        ("no-output", "PDF_MISSING"),
    ],
)
def test_failed_timeout_and_missing_output_never_claim_pdf(tmp_path, mode, expected_code):
    run_root = tmp_path / mode
    run_root.mkdir()
    tools = _fake_tools(tmp_path / mode, "latexmk", "perl")
    runner = FakeRunner(run_root, mode=mode)
    if mode == "no-output":
        stale = run_root / "build" / "main.pdf"
        stale.parent.mkdir()
        stale.write_bytes(b"stale pdf must be removed")

    receipt = _build(
        run_root,
        tools,
        runner,
        runtime_candidates=str(Path(tools["perl"]).parent),
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == expected_code
    assert "pdf" not in receipt
    assert not (run_root / "build" / "main.pdf").exists()


def test_toolchain_missing_is_truthful(tmp_path):
    run_root = tmp_path / "missing"
    run_root.mkdir()
    runner = FakeRunner(run_root)

    receipt = _build(
        run_root,
        {},
        runner,
        environment={"PATH": "", "LOCALAPPDATA": str(tmp_path / "absent")},
        runtime_candidates="",
        platform_name="posix",
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "TOOLCHAIN_MISSING"
    assert receipt["failure"]["code"] == "NO_RUNNABLE_LATEX_DRIVER"
    assert "pdf" not in receipt
    assert "process_receipt" not in receipt
    assert runner.calls == []


def test_windows_environment_derived_miktex_and_runtime_candidates(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    local = tmp_path / "LocalAppData"
    bin_dir = local / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    for name in ("latexmk.exe", "pdflatex.exe", "bibtex.exe"):
        (bin_dir / name).write_bytes(b"fixture")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "perl.exe").write_bytes(b"fixture")
    runner = FakeRunner(run_root)

    detected = detect_latex_toolchain(
        run_root,
        environment={
            "PATH": "",
            "LOCALAPPDATA": str(local),
            "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES": str(runtime),
        },
        which=lambda *_args, **_kwargs: None,
        runner=runner,
        platform_name="nt",
    )

    assert detected["state"] == "READY"
    assert detected["driver"] == "latexmk"
    assert Path(detected["executables"]["latexmk"]).parent == bin_dir.resolve()
    assert str(runtime.resolve()) in detected["environment"]["PATH"].split(os.pathsep)


def test_linux_discovery_uses_injected_which_without_windows_candidates(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "pdflatex", "biber")
    runner = FakeRunner(run_root)

    detected = detect_latex_toolchain(
        run_root,
        environment={"PATH": "/fixture/bin", "LOCALAPPDATA": str(tmp_path / "ignored")},
        which=_which(tools),
        runner=runner,
        platform_name="posix",
    )

    assert detected["state"] == "READY"
    assert detected["driver"] == "direct"
    assert detected["bibliography"] == "biber"


@pytest.mark.parametrize(
    ("main", "code"),
    [
        (r"\documentclass{article}\immediate\write18{whoami}", "UNSAFE_TEX_SOURCE"),
        (
            r"\documentclass{article}\begin{document}See \ref{missing}.\end{document}",
            "UNRESOLVED_REFERENCE",
        ),
        (
            r"\documentclass{article}\usepackage{graphicx}\begin{document}"
            r"\includegraphics{figures/missing.pdf}\end{document}",
            "MISSING_BUILD_ASSET",
        ),
    ],
)
def test_unsafe_tex_unresolved_reference_and_missing_asset_fail_preflight(
    tmp_path, main, code
):
    run_root = tmp_path / code
    run_root.mkdir()
    source = _source_tree(run_root, main)
    tools = _fake_tools(tmp_path / code, "latexmk", "perl")
    runner = FakeRunner(run_root)

    receipt = build_latex_project(
        run_root,
        source,
        run_id="build-run-001",
        manuscript_snapshot_sha256=HEX["a"],
        requires_pdf=True,
        environment={
            "PATH": "",
            "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES": str(Path(tools["perl"]).parent),
        },
        which=_which(tools),
        runner=runner,
        platform_name="nt" if os.name == "nt" else "posix",
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == code
    assert "pdf" not in receipt
    assert runner.calls == []


def test_source_path_escape_is_rejected_before_any_process(tmp_path):
    run_root = tmp_path / "run"
    outside = tmp_path / "outside"
    run_root.mkdir()
    source = _source_tree(outside)
    runner = FakeRunner(run_root)

    with pytest.raises(LatexBuildError, match="SOURCE_OUTSIDE_RUN"):
        build_latex_project(
            run_root,
            source,
            run_id="build-run-001",
            manuscript_snapshot_sha256=HEX["a"],
            requires_pdf=True,
            environment={"PATH": ""},
            which=lambda *_args, **_kwargs: None,
            runner=runner,
        )

    assert runner.calls == []


def test_secret_bearing_log_hard_fails_and_persists_only_redaction(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "perl")
    secret = "sentinel-build-secret-001"
    runner = FakeRunner(run_root, secret=f"compiler leaked {secret}")

    receipt = _build(
        run_root,
        tools,
        runner,
        runtime_candidates=str(Path(tools["perl"]).parent),
        secret_sentinels={"fixture_secret": secret},
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == "SECRET_LEAKAGE"
    durable = (run_root / receipt["log_ref"]).read_text(encoding="utf-8")
    assert secret not in durable
    assert "[REDACTED_SECRET_OUTPUT]" in durable
    assert secret not in json.dumps(receipt)


def test_build_compiles_private_snapshot_and_detects_source_mutation(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    source = _source_tree(run_root)
    tools = _fake_tools(tmp_path, "latexmk", "perl")

    class MutatingRunner(FakeRunner):
        def __call__(self, argv, **kwargs):
            probe = any(arg in {"-v", "--version"} for arg in argv[1:])
            if not probe:
                compiled = Path(kwargs["cwd"]) / "main.tex"
                assert compiled.parent != source
                assert "write18" not in compiled.read_text(encoding="utf-8")
                (source / "main.tex").write_text(
                    r"\documentclass{article}\immediate\write18{whoami}",
                    encoding="utf-8",
                )
            return super().__call__(argv, **kwargs)

    receipt = _build(
        run_root,
        tools,
        MutatingRunner(run_root),
        runtime_candidates=str(Path(tools["perl"]).parent),
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == "SOURCE_CHANGED"
    assert "-no-shell-escape" in receipt["process_receipt"]["argv"]
    assert "pdf" not in receipt


def test_executable_tex_support_files_are_rejected_before_process(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    _source_tree(run_root)
    (run_root / "source" / "attacker.cfg").write_text(
        r"\immediate\write18{whoami}", encoding="utf-8"
    )
    tools = _fake_tools(tmp_path, "latexmk", "perl")
    runner = FakeRunner(run_root)

    receipt = build_latex_project(
        run_root,
        run_root / "source",
        run_id="build-run-001",
        manuscript_snapshot_sha256=HEX["a"],
        requires_pdf=True,
        environment={
            "PATH": "",
            "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES": str(Path(tools["perl"]).parent),
        },
        which=_which(tools),
        runner=runner,
    )

    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == "UNSAFE_TEX_SUPPORT_FILE"
    assert runner.calls == []


def test_tool_identity_change_after_probe_fails_before_compile(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "perl")

    class ReplacingRunner(FakeRunner):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if any(arg in {"-v", "--version"} for arg in argv[1:]):
                Path(tools["latexmk"]).write_bytes(b"replaced executable")
            return result

    receipt = _build(
        run_root,
        tools,
        ReplacingRunner(run_root),
        runtime_candidates=str(Path(tools["perl"]).parent),
    )

    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == "TOOL_IDENTITY_CHANGED"
    assert "pdf" not in receipt


def test_secret_generated_artifacts_are_removed_not_only_log_redacted(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "latexmk", "perl")
    secret = "artifact-secret-001"

    class ArtifactSecretRunner(FakeRunner):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if not any(arg in {"-v", "--version"} for arg in argv[1:]):
                output = self._output_dir(argv)
                (output / "main.aux").write_text(secret, encoding="utf-8")
                (output / "main.log").write_text(secret, encoding="utf-8")
            return result

    receipt = _build(
        run_root,
        tools,
        ArtifactSecretRunner(run_root),
        runtime_candidates=str(Path(tools["perl"]).parent),
        secret_sentinels={"artifact": secret},
    )

    assert receipt["build_state"] == "COMPILE_FAILED"
    assert receipt["failure"]["code"] == "SECRET_LEAKAGE"
    assert not any(secret in path.read_text(encoding="utf-8", errors="ignore")
                   for path in run_root.rglob("*") if path.is_file())


def test_direct_pipeline_uses_one_decreasing_build_deadline(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    tools = _fake_tools(tmp_path, "pdflatex", "bibtex")

    class DelayedRunner(FakeRunner):
        def __call__(self, argv, **kwargs):
            if not any(arg in {"-v", "--version"} for arg in argv[1:]):
                time.sleep(0.01)
            return super().__call__(argv, **kwargs)

    runner = DelayedRunner(run_root)
    receipt = _build(run_root, tools, runner, runtime_candidates="", timeout=5)

    assert receipt["build_state"] == "COMPILED"
    compile_timeouts = [
        call["timeout"] for call in runner.calls
        if not any(arg in {"-v", "--version"} for arg in call["argv"][1:])
    ]
    assert len(compile_timeouts) == 4
    assert all(later < earlier for earlier, later in zip(compile_timeouts, compile_timeouts[1:]))


@pytest.mark.skipif(
    os.environ.get("RAT_REQUIRE_REAL_LATEX") != "1",
    reason="real host LaTeX is required only by the explicit verification gate",
)
def test_real_latex_build_emits_sanitized_receipt(tmp_path):
    run_root = tmp_path / "real-latex-run"
    run_root.mkdir()
    source = _source_tree(run_root)

    receipt = build_latex_project(
        run_root,
        source,
        run_id="real-latex-build-001",
        manuscript_snapshot_sha256=HEX["a"],
        requires_pdf=True,
        environment=dict(os.environ),
    )

    _assert_valid(receipt)
    assert receipt["build_state"] == "COMPILED"
    assert receipt["process_receipt"]["executable"] in {
        "latexmk.exe",
        "latexmk",
        "direct-pipeline",
    }
    assert receipt["pdf"]["byte_size"] > 0
    assert (run_root / receipt["pdf"]["path"]).is_file()
    evidence_dir = Path(os.environ["RAT_MANUSCRIPT_EVIDENCE_DIR"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = evidence_dir / "real-build-receipt.json"
    evidence.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    persisted = evidence.read_text(encoding="utf-8")
    assert Path.home().name not in persisted
    assert "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES" not in persisted
