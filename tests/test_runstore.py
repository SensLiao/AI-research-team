"""Real tests for run-store: crash-safe checkpoint + stop/resume + manifest anchoring."""
from __future__ import annotations

import pytest
import yaml

from research_agent_teams.tools._latex_sandbox import LatexSandboxViolation
from research_agent_teams.tools.runstore import (
    atomic_write_text,
    checkpoint_stage,
    classify_status,
    create_run,
    fail_run,
    mark_gate_pending,
    prepare_resume,
    read_manifest,
    start_stage,
)
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-08T00:00:00Z"


def _artifact(tmp_path, name="note.md", body="hello"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_create_run_makes_valid_manifest_and_dirs(tmp_path):
    m = create_run(tmp_path, "run1", "design_experiment", "DESIGN", TS, domain_profile_ref="cv-medical-segmentation")
    run_dir = tmp_path / "run1"
    assert (run_dir / "manifest.yaml").exists()
    assert (run_dir / "ledger.jsonl").exists()
    assert (run_dir / "evidence").is_dir() and (run_dir / "inbox").is_dir()
    assert validate_against("run_manifest.schema.json", m) == []
    assert m["status"] == "running"
    assert m["next_step"]["stage"] == "DESIGN"


def test_checkpoint_advances_and_is_clean(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    art = _artifact(tmp_path)
    m = checkpoint_stage(run_dir, "DISCOVER", [art], "idem-1", TS)
    assert len(m["completed_work"]) == 1
    assert m["last_boundary_hash"] is not None
    assert m["next_step"]["stage"] == "IDEATE"
    assert classify_status(run_dir) == "clean_boundary"


def test_atomic_write_leaves_no_tmp(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    assert list(run_dir.glob("*.tmp")) == []


def test_atomic_write_does_not_follow_a_predictable_tmp_symlink(tmp_path):
    """A stale ``<target>.tmp`` link must not redirect a manifest-like write."""

    target = tmp_path / "evidence" / "receipt.json"
    target.parent.mkdir()
    outside = tmp_path / "director-owned.txt"
    outside.write_text("unchanged", encoding="utf-8")
    predictable_tmp = target.with_name(target.name + ".tmp")
    try:
        predictable_tmp.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable on this filesystem: {exc}")

    atomic_write_text(target, '{"state":"safe"}\n')

    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert target.read_text(encoding="utf-8") == '{"state":"safe"}\n'
    assert not target.is_symlink()


def test_atomic_write_rejects_a_linked_parent_before_creating_any_output(tmp_path):
    run_root = tmp_path / "run"
    outside = tmp_path / "outside"
    run_root.mkdir()
    outside.mkdir()
    linked = run_root / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable on this filesystem: {exc}")

    with pytest.raises(LatexSandboxViolation, match="UNSAFE_OUTPUT_PARENT"):
        atomic_write_text(linked / "new" / "receipt.json", "safe\n")

    assert not (outside / "new" / "receipt.json").exists()


def test_full_run_reaches_done(tmp_path):
    create_run(tmp_path, "run1", "m", "ANALYZE", TS)
    run_dir = tmp_path / "run1"
    for stage in ("ANALYZE", "VERIFY", "REPORT"):
        checkpoint_stage(run_dir, stage, [_artifact(tmp_path, f"{stage}.md", stage)], f"k-{stage}", TS)
    m = read_manifest(run_dir)
    assert m["status"] == "done"
    assert m["next_step"] is None
    assert len(m["completed_work"]) == 3
    assert classify_status(run_dir) == "done"


def test_crashed_mid_stage_detected(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    start_stage(run_dir, "IDEATE", TS)  # started but never checkpointed = crash
    assert classify_status(run_dir) == "crashed_mid_stage"


def test_hard_gate_failure_is_terminal_and_not_a_crash(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"

    manifest = fail_run(run_dir, "DISCOVER", "citation gate BLOCK: missing primary source", TS)

    assert manifest["status"] == "failed"
    assert manifest["next_step"] is None
    assert manifest["failure"]["stage"] == "DISCOVER"
    assert classify_status(run_dir) == "failed"
    with pytest.raises(RuntimeError, match="hard gate"):
        prepare_resume(run_dir, TS)
    with pytest.raises(RuntimeError, match="failed hard gate"):
        start_stage(run_dir, "DISCOVER", TS)


def test_start_stage_refuses_to_bypass_a_pending_director_gate(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    mark_gate_pending(run_dir, "DISCOVER", TS, "IDEATE")

    with pytest.raises(RuntimeError, match="awaiting director"):
        start_stage(run_dir, "IDEATE", TS)


def test_resume_from_crash_reruns_same_stage(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    start_stage(run_dir, "IDEATE", TS)
    res = prepare_resume(run_dir, TS)
    assert res["resume_stage"] == "IDEATE"  # re-run the stage that crashed


def test_resume_from_clean_boundary_advances(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    res = prepare_resume(run_dir, TS)
    assert res["resume_stage"] == "IDEATE"  # next_step after the boundary


def test_double_resume_rejected(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    prepare_resume(run_dir, TS)  # consumes the boundary
    with pytest.raises(RuntimeError, match="double-resume"):
        prepare_resume(run_dir, TS)  # same boundary, no progress


def test_inconsistent_manifest_blocks_resume(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    # Tamper the manifest's anchor so it disagrees with the ledger.
    m = read_manifest(run_dir)
    m["last_boundary_hash"] = "sha256:deadbeef"
    (run_dir / "manifest.yaml").write_text(yaml.safe_dump(m), encoding="utf-8")
    assert classify_status(run_dir) == "inconsistent"
    with pytest.raises(RuntimeError, match="inconsistent"):
        prepare_resume(run_dir, TS)


def test_tampered_ledger_blocks_resume(tmp_path):
    create_run(tmp_path, "run1", "m", "DISCOVER", TS)
    run_dir = tmp_path / "run1"
    checkpoint_stage(run_dir, "DISCOVER", [_artifact(tmp_path)], "k", TS)
    checkpoint_stage(run_dir, "IDEATE", [_artifact(tmp_path, "b.md", "b")], "k2", TS)
    ledger = run_dir / "ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    import json
    e = json.loads(lines[1])
    e["payload"]["idempotency_key"] = "FORGED"
    lines[1] = json.dumps(e, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert classify_status(run_dir) == "tampered"
    with pytest.raises(RuntimeError, match="tampered"):
        prepare_resume(run_dir, TS)
