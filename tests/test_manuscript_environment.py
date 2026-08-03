"""Portable environment checks and opt-in Phase 01 release-evidence verification.

The normal test suite verifies the parsers with temporary evidence only.  Reading
release JUnit files during a Docker targeted run would be self-referential because
``linux/targeted.xml`` is produced only after that run exits.  A separate explicit
``RAT_VERIFY_PHASE_EVIDENCE=1`` invocation verifies persisted release evidence.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

import pytest

from research_agent_teams.tools.latex_build import detect_latex_toolchain


ROOT = Path(__file__).resolve().parents[1]
PHASE_EVIDENCE_ROOT = ROOT / ".planning" / "evidence" / "phase-01"
WINDOWS_EVIDENCE_DIR = PHASE_EVIDENCE_ROOT / "windows"
LINUX_EVIDENCE_DIR = PHASE_EVIDENCE_ROOT / "linux"
WINDOWS_TARGETED_JUNIT = PHASE_EVIDENCE_ROOT / "windows-targeted.xml"
SECURITY_JUNIT = PHASE_EVIDENCE_ROOT / "security-junit.xml"
DIRECTOR_ROUTE_JUNIT = PHASE_EVIDENCE_ROOT / "director-route-junit.xml"
COMPLETION_JUNIT = PHASE_EVIDENCE_ROOT / "completion-junit.xml"
FULL_SUITE_JUNIT = PHASE_EVIDENCE_ROOT / "full-suite-junit.xml"
PRE_FULL_SUITE_SOURCE_SNAPSHOT = PHASE_EVIDENCE_ROOT / "source-snapshot-pre-full-suite.json"
POST_FULL_SUITE_SOURCE_SNAPSHOT = PHASE_EVIDENCE_ROOT / "source-snapshot-post-full-suite.json"
LINUX_TARGETED_JUNIT = LINUX_EVIDENCE_DIR / "targeted.xml"
WINDOWS_REAL_BUILD_RECEIPT = WINDOWS_EVIDENCE_DIR / "real-build-receipt.json"
WINDOWS_REAL_BUILD_BUNDLE = WINDOWS_EVIDENCE_DIR / "real-build-bundle.json"
AI_EVAL_SCORECARD = PHASE_EVIDENCE_ROOT / "ai-eval-scorecard.json"
DOCKER_PLATFORM_EVIDENCE = LINUX_EVIDENCE_DIR / "docker-platform.txt"
DOCKER_IMAGE_EVIDENCE = LINUX_EVIDENCE_DIR / "docker-image.txt"
EXPECTED_DOCKER_PLATFORM = "linux/amd64"
EXPECTED_DOCKER_IMAGE = (
    "python@sha256:cb1503943096ba7e3713bab3a59c4fa493c1799949c1f16dedfc2a7ff80754da"
)
WINDOWS_REQUIRED_CASES = frozenset(
    {
        "test_driver_readiness_uses_build_sanitized_environment",
        "test_latexmk_present_without_perl_falls_back_to_direct_pipeline",
        "test_real_latex_build_emits_sanitized_receipt",
        "test_toolchain_missing_is_truthful",
    }
)
LINUX_REQUIRED_CASES = frozenset(
    {
        "test_driver_readiness_uses_build_sanitized_environment",
        "test_latexmk_present_without_perl_falls_back_to_direct_pipeline",
        "test_toolchain_missing_is_truthful",
    }
)
FULL_SUITE_REQUIRED_CASES = frozenset(
    {
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[domain_contribution]",
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[methods_reproducibility]",
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[figure_table]",
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[factual]",
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[citation]",
        "test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker[venue_style_latex]",
        "test_design_stage_writes_hash_bound_venue_and_evidence_slices",
        "test_design_slices_fail_closed_on_missing_or_tampered_provenance[True-False-REFERENCE_HASH_MISMATCH]",
        "test_design_slices_fail_closed_on_missing_or_tampered_provenance[False-True-WORKER_BUNDLE_MISSING]",
        "test_review_report_writes_schema_valid_advisory_submission_checklist",
        "test_submission_checklist_fails_closed_on_missing_or_tampered_evidence[missing_overview]",
        "test_submission_checklist_fails_closed_on_missing_or_tampered_evidence[tampered_quality]",
        "test_scheduler_receipt_write_rejects_linked_parent_before_touching_outside",
        "test_repair_plan_write_rejects_linked_parent_before_touching_outside",
    }
)
RUNTIME_PINS = {
    "PyYAML": "6.0.2",
    "jsonschema": "4.25.1",
    "cryptography": "47.0.0",
    "PyMuPDF": "1.26.5",
    "paramiko": "2.8.1",
}
DEV_PINS = {**RUNTIME_PINS, "pytest": "8.4.2"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RAW_USER_OR_RUNTIME_PATH = re.compile(
    r"(?:^[A-Za-z]:[\\/]|^\\\\|^/|(?:^|[\\/])(?:users|home)[\\/])",
    re.IGNORECASE,
)
SOURCE_SNAPSHOT_EXCLUDED_PREFIXES = (
    ".planning/",
    "runs/",
    "workspace/audit_log.jsonl",
    "workspace/lease_registry.jsonl",
)


def _pinned_requirements(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        assert "==" in line, f"{path.name} contains an unpinned requirement: {line!r}"
        name, version = line.split("==", 1)
        assert name and version and name not in rows, f"{path.name} duplicates {name!r}"
        rows[name] = version
    return rows


def _local_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _count_attribute(element: ElementTree.Element, attribute: str) -> int:
    raw = element.get(attribute, "0")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"JUnit {attribute} is not an integer") from exc
    assert value >= 0, f"JUnit {attribute} is negative"
    return value


def parse_junit(path: Path) -> dict[str, Any]:
    """Parse JUnit defensively; malformed or underspecified evidence is rejected."""
    assert path.is_file(), "required JUnit evidence is missing"
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise AssertionError("JUnit evidence cannot be parsed") from exc
    assert _local_tag(root) in {"testsuites", "testsuite"}, "unexpected JUnit root"

    suites = [element for element in root.iter() if _local_tag(element) in {"testsuites", "testsuite"}]
    cases = [element for element in root.iter() if _local_tag(element) == "testcase"]
    assert cases, "JUnit evidence contains no test cases"
    for case in cases:
        assert case.get("name"), "JUnit testcase has no name"

    failures = max(
        [sum(_count_attribute(suite, "failures") for suite in suites)]
        + [sum(1 for element in root.iter() if _local_tag(element) == "failure")]
    )
    errors = max(
        [sum(_count_attribute(suite, "errors") for suite in suites)]
        + [sum(1 for element in root.iter() if _local_tag(element) == "error")]
    )
    skipped = max(
        [sum(_count_attribute(suite, "skipped") for suite in suites)]
        + [sum(1 for element in root.iter() if _local_tag(element) == "skipped")]
    )
    return {
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "cases": cases,
        "case_names": {str(case.get("name")) for case in cases},
    }


def assert_passing_junit(path: Path, required_cases: Iterable[str] = ()) -> dict[str, Any]:
    """Require a readable, zero-failure/error JUnit report and passing named cases."""
    parsed = parse_junit(path)
    assert parsed["failures"] == 0, "JUnit evidence reports failures"
    assert parsed["errors"] == 0, "JUnit evidence reports errors"
    for expected in required_cases:
        matching = [case for case in parsed["cases"] if case.get("name") == expected]
        assert matching, f"JUnit evidence is missing required testcase {expected!r}"
        for case in matching:
            outcomes = {_local_tag(child) for child in case}
            assert not outcomes & {"failure", "error", "skipped"}, (
                f"required testcase {expected!r} did not pass"
            )
    return parsed


def _assert_sha256(value: object, field: str) -> None:
    assert isinstance(value, str) and _SHA256.fullmatch(value), f"{field} is not a SHA-256"


def _object_digest(value: dict[str, Any], omitted: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != omitted}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_kind(relative: str) -> str:
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


def _source_tree_digest(source: Path) -> str:
    """Independently reproduce the stable source-tree inventory digest."""
    assert source.is_dir(), "staged source tree is missing"
    inventory: list[dict[str, str]] = []
    for path in sorted((item for item in source.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        assert not path.is_symlink(), "release source witness may not contain links"
        relative = path.relative_to(source).as_posix()
        inventory.append(
            {"path": relative, "sha256": _file_digest(path), "kind": _source_kind(relative)}
        )
    encoded = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_material(entries: list[dict[str, str]]) -> bytes:
    return "\n".join(
        f"{entry['path']}\0{entry['sha256']}" for entry in entries
    ).encode("utf-8")


def _current_snapshot_paths() -> list[str]:
    """Enumerate the complete non-generated git source set for a snapshot."""
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "cannot enumerate repository source files"
    rows = [row.replace("\\", "/") for row in result.stdout.splitlines() if row]
    paths = [
        row for row in rows
        if not any(row.startswith(prefix) for prefix in SOURCE_SNAPSHOT_EXCLUDED_PREFIXES)
        and (ROOT / Path(row)).is_file()
    ]
    assert len(paths) == len(set(paths)), "git source enumeration repeats a path"
    return sorted(paths)


def _assert_snapshot_timestamp(value: object, field: str) -> datetime:
    assert isinstance(value, str) and value.strip(), f"{field} is missing"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(f"{field} is not an ISO timestamp") from exc
    assert parsed.tzinfo is not None, f"{field} must carry a timezone"
    return parsed.astimezone(timezone.utc)


def assert_source_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Verify a complete repository-source snapshot without trusting its prose."""
    required = {
        "schema_version", "kind", "captured_at", "repository_head", "entries",
        "inventory_sha256", "excluded_prefixes",
    }
    assert required <= set(snapshot), "source snapshot is missing required fields"
    assert snapshot["schema_version"] == "1.0.0"
    assert snapshot["excluded_prefixes"] == list(SOURCE_SNAPSHOT_EXCLUDED_PREFIXES), (
        "source snapshot exclusions differ from the release contract"
    )
    _assert_snapshot_timestamp(snapshot["captured_at"], "source snapshot captured_at")
    head = snapshot["repository_head"]
    assert isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head), (
        "source snapshot repository_head is not a commit SHA"
    )
    entries = snapshot["entries"]
    assert isinstance(entries, list) and entries, "source snapshot contains no files"
    normalized: list[dict[str, str]] = []
    for entry in entries:
        assert isinstance(entry, dict), "source snapshot entry is not an object"
        assert set(entry) == {"path", "sha256"}, "source snapshot entry has unknown fields"
        relative = entry["path"]
        _assert_safe_relative_ref(relative, "source snapshot path")
        assert isinstance(relative, str)
        path = ROOT / Path(relative)
        try:
            path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise AssertionError("source snapshot path escapes repository root") from exc
        assert path.is_file() and not path.is_symlink(), "source snapshot file is unsafe or missing"
        _assert_sha256(entry["sha256"], "source snapshot entry sha256")
        assert _file_digest(path) == entry["sha256"], "source snapshot file changed"
        normalized.append({"path": relative, "sha256": entry["sha256"]})
    assert normalized == sorted(normalized, key=lambda entry: entry["path"]), (
        "source snapshot entries are not sorted"
    )
    assert len({entry["path"] for entry in normalized}) == len(normalized), (
        "source snapshot repeats a path"
    )
    assert [entry["path"] for entry in normalized] == _current_snapshot_paths(), (
        "source snapshot does not cover the complete current repository source set"
    )
    assert snapshot["inventory_sha256"] == hashlib.sha256(
        _snapshot_material(normalized)
    ).hexdigest(), "source snapshot inventory digest is invalid"
    return snapshot


def _junit_timestamp(path: Path) -> datetime:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise AssertionError("JUnit timestamp cannot be read") from exc
    raw = root.get("timestamp")
    if not raw:
        values = [
            element.get("timestamp")
            for element in root.iter()
            if _local_tag(element) == "testsuite" and element.get("timestamp")
        ]
        assert values, "JUnit timestamp is missing"
        assert len(set(values)) == 1, "JUnit suites disagree on timestamp"
        raw = values[0]
    return _assert_snapshot_timestamp(raw, "JUnit timestamp")


def _assert_safe_relative_ref(value: object, field: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{field} is empty"
    assert not _RAW_USER_OR_RUNTIME_PATH.search(value), f"{field} exposes a raw runtime/user path"
    parts = value.replace("\\", "/").split("/")
    assert ".." not in parts, f"{field} escapes the receipt boundary"


def _all_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _all_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_strings(nested)


def assert_windows_real_build_receipt(
    receipt: dict[str, Any], *, bundle_root: Path | None = None
) -> None:
    """Validate the release-only Windows receipt without trusting prose claims."""
    required = {
        "schema_version", "run_id", "manuscript_snapshot_sha256", "source_tree_ref",
        "source_tree_sha256", "requires_pdf", "build_state", "process_receipt", "log_ref",
        "log_sha256", "recorder_ref", "recorder_sha256", "pdf", "build_receipt_sha256",
    }
    assert required <= set(receipt), "Windows receipt is missing required build facts"
    assert receipt["build_state"] == "COMPILED"
    assert receipt["requires_pdf"] is True
    assert isinstance(receipt["run_id"], str) and receipt["run_id"].strip()
    _assert_sha256(receipt["manuscript_snapshot_sha256"], "manuscript_snapshot_sha256")
    _assert_sha256(receipt["source_tree_sha256"], "source_tree_sha256")
    _assert_sha256(receipt["log_sha256"], "log_sha256")
    _assert_sha256(receipt["recorder_sha256"], "recorder_sha256")
    _assert_sha256(receipt["build_receipt_sha256"], "build_receipt_sha256")
    for field in ("source_tree_ref", "log_ref", "recorder_ref"):
        _assert_safe_relative_ref(receipt[field], field)

    process = receipt["process_receipt"]
    assert isinstance(process, dict), "process_receipt must be an object"
    for field in ("executable", "executable_version", "argv", "operating_system", "return_code", "timed_out", "shell", "shell_escape", "receipt_sha256"):
        assert field in process, f"process_receipt is missing {field}"
    executable = process["executable"]
    assert isinstance(executable, str) and executable.strip()
    assert executable.casefold() in {
        "latexmk", "latexmk.exe", "direct-pipeline", "pdflatex", "pdflatex.exe",
    }
    assert isinstance(process["argv"], list) and process["argv"]
    assert process["argv"][0] == executable
    assert all(isinstance(argument, str) and argument for argument in process["argv"])
    assert "-norc" in process["argv"]
    assert "-recorder" in process["argv"]
    assert "-halt-on-error" in process["argv"]
    assert "-no-shell-escape" in process["argv"]
    assert str(process["operating_system"]).casefold().startswith("windows")
    assert process["return_code"] == 0
    assert process["timed_out"] is False
    assert process["shell"] is False
    assert process["shell_escape"] is False
    _assert_sha256(process["receipt_sha256"], "process_receipt.receipt_sha256")
    assert process["receipt_sha256"] == _object_digest(process, "receipt_sha256")

    pdf = receipt["pdf"]
    assert isinstance(pdf, dict), "PDF truth must be an object"
    assert set(("path", "sha256", "byte_size")) <= set(pdf), "PDF truth is incomplete"
    _assert_safe_relative_ref(pdf["path"], "pdf.path")
    assert str(pdf["path"]).casefold().endswith(".pdf")
    _assert_sha256(pdf["sha256"], "pdf.sha256")
    assert isinstance(pdf["byte_size"], int) and pdf["byte_size"] > 0
    assert receipt["build_receipt_sha256"] == _object_digest(receipt, "build_receipt_sha256")

    if bundle_root is not None:
        assert bundle_root.is_dir(), "Windows real-build witness bundle is missing"
        assert not bundle_root.is_symlink(), "Windows real-build witness bundle may not be a link"
        source = bundle_root / str(receipt["source_tree_ref"])
        log = bundle_root / str(receipt["log_ref"])
        recorder = bundle_root / str(receipt["recorder_ref"])
        pdf_file = bundle_root / str(pdf["path"])
        for label, path in (("source", source), ("log", log), ("recorder", recorder), ("pdf", pdf_file)):
            assert path.exists(), f"Windows witness {label} is missing"
            assert not path.is_symlink(), f"Windows witness {label} may not be a link"
        assert _source_tree_digest(source) == receipt["source_tree_sha256"]
        assert _file_digest(log) == receipt["log_sha256"]
        assert _file_digest(recorder) == receipt["recorder_sha256"]
        assert _file_digest(pdf_file) == pdf["sha256"]
        assert pdf_file.stat().st_size == pdf["byte_size"]

    for text in _all_strings(receipt):
        assert not _RAW_USER_OR_RUNTIME_PATH.search(text), "receipt exposes a raw runtime/user path"


def _sample_windows_real_build_receipt() -> dict[str, Any]:
    digest = "a" * 64
    receipt = {
        "schema_version": "1.0.0",
        "run_id": "real-latex-build-001",
        "manuscript_snapshot_sha256": digest,
        "source_tree_ref": "source",
        "source_tree_sha256": digest,
        "requires_pdf": True,
        "build_state": "COMPILED",
        "process_receipt": {
            "executable": "latexmk.EXE",
            "executable_version": "Latexmk 4.88",
            "argv": ["latexmk.EXE", "-norc", "-recorder", "-halt-on-error", "-no-shell-escape", "main.tex"],
            "operating_system": "Windows",
            "return_code": 0,
            "timed_out": False,
            "shell": False,
            "shell_escape": False,
            "receipt_sha256": "",
        },
        "log_ref": "build/build.log",
        "log_sha256": digest,
        "recorder_ref": "build/main.fls",
        "recorder_sha256": digest,
        "pdf": {"path": "build/main.pdf", "sha256": digest, "byte_size": 1},
        "build_receipt_sha256": "",
    }
    receipt["process_receipt"]["receipt_sha256"] = _object_digest(
        receipt["process_receipt"], "receipt_sha256"
    )
    receipt["build_receipt_sha256"] = _object_digest(receipt, "build_receipt_sha256")
    return receipt


def verify_phase_release_evidence(evidence_root: Path = PHASE_EVIDENCE_ROOT) -> None:
    """Verify pre-existing phase evidence after producer commands have completed.

    This function must be called in a follow-up evidence-verification process,
    not inside the Docker command that is writing ``linux/targeted.xml``.
    """
    windows_dir = evidence_root / "windows"
    linux_dir = evidence_root / "linux"
    required_paths = (
        windows_dir / "real-build-receipt.json",
        windows_dir / "real-build-bundle.json",
        evidence_root / "windows-targeted.xml",
        evidence_root / "ai-eval-scorecard.json",
        evidence_root / "security-junit.xml",
        evidence_root / "director-route-junit.xml",
        evidence_root / "completion-junit.xml",
        evidence_root / "full-suite-junit.xml",
        evidence_root / "source-snapshot-pre-full-suite.json",
        evidence_root / "source-snapshot-post-full-suite.json",
        linux_dir / "docker-platform.txt",
        linux_dir / "docker-image.txt",
        linux_dir / "targeted.xml",
    )
    for path in required_paths:
        assert path.is_file(), f"required phase evidence is missing: {path.name}"

    receipt = json.loads((windows_dir / "real-build-receipt.json").read_text(encoding="utf-8"))
    bundle = json.loads((windows_dir / "real-build-bundle.json").read_text(encoding="utf-8"))
    assert isinstance(bundle, dict), "Windows real-build witness index is not an object"
    assert bundle.get("schema_version") == "1.0.0"
    assert bundle.get("build_receipt_sha256") == receipt.get("build_receipt_sha256")
    bundle_name = bundle.get("bundle_root")
    _assert_safe_relative_ref(bundle_name, "real-build bundle_root")
    assert isinstance(bundle_name, str) and bundle_name.startswith("real-build-")
    bundle_root = windows_dir / bundle_name
    assert bundle_root.parent == windows_dir and bundle_root.resolve().parent == windows_dir.resolve()
    assert_windows_real_build_receipt(receipt, bundle_root=bundle_root)
    assert_passing_junit(evidence_root / "windows-targeted.xml", WINDOWS_REQUIRED_CASES)
    security = assert_passing_junit(evidence_root / "security-junit.xml")
    assert security["cases"], "security JUnit contains no test cases"
    assert_passing_junit(
        evidence_root / "director-route-junit.xml",
        {"test_d07_calls_no_search_before_local_coverage_names_a_deficit"},
    )
    assert_passing_junit(
        evidence_root / "completion-junit.xml",
        {
            "test_exactly_twelve_real_operated_modes_and_no_phantom_review_pack",
            "test_all_seventeen_gold_cases_remain_the_single_completion_matrix",
        },
    )
    full_suite = assert_passing_junit(
        evidence_root / "full-suite-junit.xml", FULL_SUITE_REQUIRED_CASES
    )
    assert full_suite["cases"], "full-suite JUnit contains no test cases"
    pre_snapshot = assert_source_snapshot(json.loads(
        (evidence_root / "source-snapshot-pre-full-suite.json").read_text(encoding="utf-8")
    ))
    post_snapshot = assert_source_snapshot(json.loads(
        (evidence_root / "source-snapshot-post-full-suite.json").read_text(encoding="utf-8")
    ))
    assert pre_snapshot["kind"] == "pre-full-suite"
    assert post_snapshot["kind"] == "post-full-suite"
    assert pre_snapshot["repository_head"] == post_snapshot["repository_head"]
    assert pre_snapshot["inventory_sha256"] == post_snapshot["inventory_sha256"], (
        "source tree changed while the full suite was running"
    )
    assert post_snapshot.get("pre_snapshot_sha256") == _file_digest(
        evidence_root / "source-snapshot-pre-full-suite.json"
    )
    assert post_snapshot.get("full_suite_junit_sha256") == _file_digest(
        evidence_root / "full-suite-junit.xml"
    )
    pre_time = _assert_snapshot_timestamp(pre_snapshot["captured_at"], "pre source snapshot")
    post_time = _assert_snapshot_timestamp(post_snapshot["captured_at"], "post source snapshot")
    junit_time = _junit_timestamp(evidence_root / "full-suite-junit.xml")
    assert pre_time <= junit_time <= post_time, "full-suite JUnit is outside the source snapshot interval"

    scorecard = json.loads((evidence_root / "ai-eval-scorecard.json").read_text(encoding="utf-8"))
    summary = scorecard.get("summary")
    assert isinstance(summary, dict), "AI-eval scorecard has no summary"
    assert summary.get("required_machine_failures") == 0
    assert summary.get("fail") == 0
    # PowerShell's ``-Encoding utf8`` may include a BOM; it is not evidence
    # content and must not make an otherwise exact platform/digest fail.
    assert (linux_dir / "docker-platform.txt").read_text(encoding="utf-8-sig").strip() == EXPECTED_DOCKER_PLATFORM
    assert (linux_dir / "docker-image.txt").read_text(encoding="utf-8-sig").strip() == EXPECTED_DOCKER_IMAGE
    assert_passing_junit(linux_dir / "targeted.xml", LINUX_REQUIRED_CASES)


def test_manifests_pin_only_the_existing_observed_runtime_and_test_runner():
    assert _pinned_requirements(ROOT / "requirements.txt") == RUNTIME_PINS
    assert _pinned_requirements(ROOT / "requirements-dev.txt") == {"pytest": "8.4.2"}
    assert (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()[0] == "-r requirements.txt"


def test_supported_python_and_installed_distribution_versions_match_the_pins():
    assert sys.version_info >= (3, 9)
    for distribution, expected in DEV_PINS.items():
        assert importlib.metadata.version(distribution) == expected


def test_latex_readiness_uses_a_sanitized_environment_and_parent_only_runtime_candidates(tmp_path):
    raw_candidates = os.environ.get("RAT_LATEX_DRIVER_RUNTIME_CANDIDATES", "")
    for raw in filter(None, raw_candidates.split(os.pathsep)):
        candidate = Path(raw)
        assert candidate.is_absolute()
        assert candidate.name.casefold() not in {"perl", "perl.exe"}

    toolchain = detect_latex_toolchain(
        tmp_path,
        environment=dict(os.environ),
        runtime_candidates=raw_candidates or None,
    )
    clean = toolchain["environment"]
    assert "RAT_LATEX_DRIVER_RUNTIME_CANDIDATES" not in clean
    assert clean["openin_any"] == "p"
    assert clean["openout_any"] == "p"
    assert set(clean) <= {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
        "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "HOME", "USERPROFILE", "HOMEDRIVE",
        "HOMEPATH", "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "openin_any", "openout_any",
    }
    assert toolchain["state"] in {"READY", "TOOLCHAIN_MISSING"}
    if os.environ.get("RAT_REQUIRE_REAL_LATEX") == "1":
        assert toolchain["state"] == "READY"
        assert toolchain["driver"] in {"latexmk", "direct"}
        assert toolchain["executables"]


def test_junit_gate_parser_fails_closed_for_counts_and_required_cases(tmp_path):
    valid = tmp_path / "valid.xml"
    valid.write_text(
        "<testsuites failures='0' errors='0'><testsuite failures='0' errors='0'>"
        "<testcase name='fallback'/></testsuite></testsuites>",
        encoding="utf-8",
    )
    parsed = assert_passing_junit(valid, {"fallback"})
    assert parsed["failures"] == parsed["errors"] == 0

    failing = tmp_path / "failing.xml"
    failing.write_text(
        "<testsuite failures='1' errors='0'><testcase name='fallback'><failure/></testcase></testsuite>",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        assert_passing_junit(failing, {"fallback"})

    skipped = tmp_path / "skipped.xml"
    skipped.write_text(
        "<testsuite failures='0' errors='0'><testcase name='fallback'><skipped/></testcase></testsuite>",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        assert_passing_junit(skipped, {"fallback"})

    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<testsuite>", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_passing_junit(malformed)


def test_windows_real_receipt_contract_fails_closed_for_hashes_driver_and_paths():
    receipt = _sample_windows_real_build_receipt()
    assert_windows_real_build_receipt(receipt)

    direct = copy.deepcopy(receipt)
    direct["process_receipt"]["executable"] = "pdflatex.exe"
    direct["process_receipt"]["argv"][0] = "pdflatex.exe"
    direct["process_receipt"]["receipt_sha256"] = _object_digest(
        direct["process_receipt"], "receipt_sha256"
    )
    direct["build_receipt_sha256"] = _object_digest(direct, "build_receipt_sha256")
    assert_windows_real_build_receipt(direct)

    invalid_hash = copy.deepcopy(receipt)
    invalid_hash["pdf"]["sha256"] = "not-a-hash"
    with pytest.raises(AssertionError):
        assert_windows_real_build_receipt(invalid_hash)

    unselected_driver = copy.deepcopy(receipt)
    unselected_driver["process_receipt"]["argv"][0] = "C:/Users/example/latexmk.exe"
    with pytest.raises(AssertionError):
        assert_windows_real_build_receipt(unselected_driver)


def test_phase_release_evidence_layout_is_pinned_without_reading_live_outputs():
    assert WINDOWS_REAL_BUILD_RECEIPT == WINDOWS_EVIDENCE_DIR / "real-build-receipt.json"
    assert WINDOWS_REAL_BUILD_BUNDLE == WINDOWS_EVIDENCE_DIR / "real-build-bundle.json"
    assert LINUX_TARGETED_JUNIT == LINUX_EVIDENCE_DIR / "targeted.xml"
    assert EXPECTED_DOCKER_PLATFORM == "linux/amd64"
    assert EXPECTED_DOCKER_IMAGE.startswith("python@sha256:")
    assert len(EXPECTED_DOCKER_IMAGE.rsplit(":", 1)[1]) == 64


def test_release_evidence_verifier_fails_closed_when_a_required_file_is_absent(tmp_path):
    with pytest.raises(AssertionError):
        verify_phase_release_evidence(tmp_path)


def test_phase_release_evidence_is_verified_only_with_explicit_opt_in():
    if os.environ.get("RAT_VERIFY_PHASE_EVIDENCE") != "1":
        return
    verify_phase_release_evidence()
