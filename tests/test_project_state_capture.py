from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_agent_teams.operate.modes import deep_research
from research_agent_teams.tools.project_state_capture import (
    FactSpec,
    ProjectStateCaptureError,
    ProjectStateConflictError,
    SourceSpec,
    capture_project_state,
)
from research_agent_teams.tools.validate_artifact import validate_artifact


TS = "2026-08-13T10:00:00Z"
VALID_UNTIL = "2026-08-14T10:00:00Z"
PROJECT = "honours-project"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _make_run(tmp_path: Path, *, project: str = PROJECT) -> tuple[Path, Path]:
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    task_frame = {
        "artifact_id": "task-frame-run-1",
        "artifact_type": "task_frame",
        "schema_version": "1.0.0",
        "created_by": "orchestrator",
        "created_at": TS,
        "status": "draft",
        "payload": {
            "task_id": "run-1",
            "project": project,
            "mode": "deep_research",
            "entry_stage": "DISCOVER",
            "agent_subset": ["lit-scout"],
            "gate_level": "director_signoff",
            "budget": {"max_agent_hops": 1},
        },
    }
    assert validate_artifact(task_frame) == []
    task_path = run_dir / "task_frame.artifact.json"
    task_path.write_text(json.dumps(task_frame), encoding="utf-8")
    return run_dir, task_path


def _make_sources(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "explicit-inputs"
    source_root.mkdir(exist_ok=True)
    canonical = source_root / "CANONICAL-PROJECT.md"
    manifest = source_root / "live-manifest.json"
    canonical.write_bytes(b"# Frozen project contract\nintent + P2T\n")
    manifest.write_bytes(b'{"phase":"honours","status":"current"}\n')
    return canonical, manifest


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"host cannot create test symlinks: {exc}")


def _capture(run_dir: Path, canonical: Path, manifest: Path, **overrides) -> Path:
    kwargs = {
        "run_dir": run_dir,
        "project": PROJECT,
        "source_of_truth_id": "honours-live-state",
        "captured_at": TS,
        "valid_until": VALID_UNTIL,
        "sources": [
            SourceSpec("CANONICAL_STATE", canonical, "canonical"),
            SourceSpec("LIVE_MANIFEST", manifest, "manifest"),
        ],
        "facts": [
            FactSpec(
                "direction",
                "Structured intent and P2T are the frozen core direction.",
                ("canonical",),
            ),
            FactSpec(
                "live-phase",
                "The project is in the current honours implementation phase.",
                ("manifest",),
            ),
        ],
    }
    kwargs.update(overrides)
    return capture_project_state(**kwargs)


def test_capture_copies_exact_bytes_and_writes_consumable_bound_artifact(tmp_path):
    run_dir, task_path = _make_run(tmp_path)
    canonical, manifest = _make_sources(tmp_path)

    artifact_path = _capture(run_dir, canonical, manifest)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact_path.parent == run_dir / "inbox" / "project-state"
    assert artifact["created_by"] == "project-state-capture"
    assert artifact["status"] == "approved"
    assert artifact["payload"]["project_id"] == PROJECT
    assert artifact["payload"]["captured_at"] == TS
    assert artifact["payload"]["valid_until"] == VALID_UNTIL
    assert artifact["input_artifact_hashes"] == [_sha256(task_path.read_bytes())]
    assert validate_artifact(artifact) == []

    sources = {row["role"]: row for row in artifact["payload"]["sources"]}
    canonical_copy = run_dir / sources["CANONICAL_STATE"]["source_ref"]
    manifest_copy = run_dir / sources["LIVE_MANIFEST"]["source_ref"]
    assert canonical_copy.read_bytes() == canonical.read_bytes()
    assert manifest_copy.read_bytes() == manifest.read_bytes()
    assert sources["CANONICAL_STATE"]["source_sha256"] == _sha256(canonical.read_bytes())
    assert sources["LIVE_MANIFEST"]["source_sha256"] == _sha256(manifest.read_bytes())
    assert canonical_copy.name != manifest_copy.name
    assert all(
        set(fact["source_refs"]).issubset({row["source_ref"] for row in sources.values()})
        for fact in artifact["payload"]["facts"]
    )

    defects: list[tuple[str, str]] = []
    accepted = deep_research._validate_current_project_snapshot(
        run_dir,
        artifact_path.relative_to(run_dir).as_posix(),
        _sha256(artifact_path.read_bytes()),
        "2026-08-13T12:00:00Z",
        lambda defect_id, summary: defects.append((defect_id, summary)),
    )
    assert accepted is True
    assert defects == []


def test_identical_capture_is_noop_but_changed_capture_conflicts(tmp_path):
    run_dir, _ = _make_run(tmp_path)
    canonical, manifest = _make_sources(tmp_path)
    first = _capture(run_dir, canonical, manifest, output="current.artifact.json")
    artifact_bytes = first.read_bytes()
    artifact_mtime = first.stat().st_mtime_ns
    source_mtimes = {
        path.name: path.stat().st_mtime_ns
        for path in (run_dir / "inbox" / "project-state" / "sources").iterdir()
    }

    second = _capture(run_dir, canonical, manifest, output="current.artifact.json")

    assert second == first
    assert first.read_bytes() == artifact_bytes
    assert first.stat().st_mtime_ns == artifact_mtime
    assert {
        path.name: path.stat().st_mtime_ns
        for path in (run_dir / "inbox" / "project-state" / "sources").iterdir()
    } == source_mtimes

    with pytest.raises(ProjectStateConflictError, match="artifact conflict"):
        _capture(
            run_dir,
            canonical,
            manifest,
            output="current.artifact.json",
            facts=[FactSpec("direction", "A materially changed claim.", ("canonical",))],
        )
    assert first.read_bytes() == artifact_bytes


@pytest.mark.parametrize(
    "sensitive_name",
    [".env", ".env.local", "server.pem", "private.key", "credentials.json", "access_token.txt", "id_rsa"],
)
def test_secret_shaped_sources_are_rejected_before_copy(tmp_path, sensitive_name):
    run_dir, _ = _make_run(tmp_path)
    path = tmp_path / sensitive_name
    path.write_bytes(b"must-not-be-copied")

    with pytest.raises(ProjectStateCaptureError, match="refusing"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("CANONICAL_STATE", path)],
            facts=[FactSpec("state", "Current state")],
        )
    assert not (run_dir / "inbox" / "project-state" / "sources").exists()


def test_directory_and_out_of_lane_output_are_rejected(tmp_path):
    run_dir, _ = _make_run(tmp_path)
    canonical, _manifest = _make_sources(tmp_path)
    directory = tmp_path / "ordinary-directory"
    directory.mkdir()

    with pytest.raises(ProjectStateCaptureError, match="not a directory"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("CANONICAL_STATE", directory)],
            facts=[FactSpec("state", "Current state")],
        )

    with pytest.raises(ProjectStateCaptureError, match="direct child"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("CANONICAL_STATE", canonical)],
            facts=[FactSpec("state", "Current state")],
            output=tmp_path / "escaped.artifact.json",
        )
    assert not (tmp_path / "escaped.artifact.json").exists()


def test_source_and_output_symlinks_fail_closed_including_source_parent(tmp_path):
    run_dir, _ = _make_run(tmp_path)
    canonical, _manifest = _make_sources(tmp_path)
    source_link = tmp_path / "source-link.md"
    _symlink_or_skip(source_link, canonical)

    common = {
        "run_dir": run_dir,
        "project": PROJECT,
        "source_of_truth_id": "state",
        "captured_at": TS,
        "valid_until": VALID_UNTIL,
        "facts": [FactSpec("state", "Current state")],
    }
    with pytest.raises(ProjectStateCaptureError, match="symlink or junction"):
        capture_project_state(
            **common, sources=[SourceSpec("CANONICAL_STATE", source_link)]
        )

    real_parent = tmp_path / "real-source-parent"
    real_parent.mkdir()
    parent_source = real_parent / "state.md"
    parent_source.write_bytes(b"current state\n")
    linked_parent = tmp_path / "linked-source-parent"
    _symlink_or_skip(linked_parent, real_parent, directory=True)
    with pytest.raises(ProjectStateCaptureError, match="symlink or junction"):
        capture_project_state(
            **common,
            sources=[SourceSpec("CANONICAL_STATE", linked_parent / "state.md")],
        )

    lane = run_dir / "inbox" / "project-state"
    lane.mkdir(parents=True)
    outside = tmp_path / "outside-output.json"
    outside.write_bytes(b"do not overwrite\n")
    output_link = lane / "current.artifact.json"
    _symlink_or_skip(output_link, outside)
    with pytest.raises(ProjectStateCaptureError, match="direct child|non-symlink"):
        capture_project_state(
            **common,
            sources=[SourceSpec("CANONICAL_STATE", canonical)],
            output=output_link,
        )
    assert outside.read_bytes() == b"do not overwrite\n"


def test_binding_role_fact_and_time_invariants_fail_closed(tmp_path):
    run_dir, _ = _make_run(tmp_path)
    canonical, _manifest = _make_sources(tmp_path)

    with pytest.raises(ProjectStateCaptureError, match="project mismatch"):
        capture_project_state(
            run_dir=run_dir,
            project="different-project",
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("CANONICAL_STATE", canonical)],
            facts=[FactSpec("state", "Current state")],
        )
    with pytest.raises(ProjectStateCaptureError, match="CANONICAL_STATE or LIVE_MANIFEST"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("SUPPORTING", canonical, "support")],
            facts=[FactSpec("state", "Current state", ("support",))],
        )
    with pytest.raises(ProjectStateCaptureError, match="undeclared source"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=VALID_UNTIL,
            sources=[SourceSpec("CANONICAL_STATE", canonical, "canonical")],
            facts=[FactSpec("state", "Current state", ("missing",))],
        )
    with pytest.raises(ProjectStateCaptureError, match="later than"):
        capture_project_state(
            run_dir=run_dir,
            project=PROJECT,
            source_of_truth_id="state",
            captured_at=TS,
            valid_until=TS,
            sources=[SourceSpec("CANONICAL_STATE", canonical)],
            facts=[FactSpec("state", "Current state")],
        )


def test_python_module_cli_captures_named_source(tmp_path):
    run_dir, _ = _make_run(tmp_path)
    canonical, _manifest = _make_sources(tmp_path)
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "research_agent_teams.tools.project_state_capture",
        "--run-dir",
        str(run_dir),
        "--project",
        PROJECT,
        "--source-of-truth-id",
        "cli-state",
        "--captured-at",
        TS,
        "--validity-seconds",
        "3600",
        "--source",
        f"canonical=CANONICAL_STATE={canonical}",
        "--fact",
        "direction=The canonical direction is current.",
        "--fact-source",
        "direction=canonical",
    ]

    result = subprocess.run(
        command, cwd=repo_root, text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    artifact_path = Path(summary["artifact_path"])
    assert artifact_path.is_file()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["payload"]["valid_until"] == "2026-08-13T11:00:00Z"
    assert validate_artifact(artifact) == []
