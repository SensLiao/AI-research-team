import json
import os
import subprocess
from pathlib import Path

import pytest

from research_agent_teams.operate.output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
    resolve_effective_output,
    sha256,
)


TS = "2026-07-15T00:00:00Z"


def _node(index: int, label: str, logical: Path, run_dir: Path) -> dict:
    rel = logical.relative_to(run_dir).as_posix()
    return {
        "id": f"{index}:{label}:{rel}",
        "label": label,
        "output_path": logical,
        "output_rel": rel,
    }


def _link_directory_or_skip(link: Path, target: Path) -> str:
    """Create a real symlink, or a Windows junction where link privilege is absent."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symbolic links unavailable on this filesystem: {symlink_error}")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(
                "symbolic links and Windows junctions unavailable on this filesystem: "
                f"{symlink_error}; {result.stderr or result.stdout}"
            )
        return "junction"


def test_duplicate_canonical_labels_get_isolated_supplement_lineage(tmp_path):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    formalize = inbox / "FORMALIZE.bundle.json"
    mechanism = inbox / "MECHANISM.bundle.json"
    unique = inbox / "CONTRADICTION.bundle.json"
    formalize.write_text(json.dumps({"kind": "formalize-original"}), encoding="utf-8")
    mechanism.write_text(json.dumps({"kind": "mechanism-original"}), encoding="utf-8")
    unique.write_text(json.dumps({"kind": "contradiction-original"}), encoding="utf-8")

    repeated_label = "mathematical-formalizer"
    unique_label = "contradiction-miner"
    nodes = [
        _node(0, repeated_label, formalize, run_dir),
        _node(1, repeated_label, mechanism, run_dir),
        _node(2, unique_label, unique, run_dir),
    ]
    plan = prepare_plan(
        run_dir,
        "DISCOVER",
        1,
        nodes,
        {repeated_label, unique_label},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )

    repeated_rows = [row for row in plan["outputs"] if row["agent"] == repeated_label]
    assert len({row["physical_output"] for row in repeated_rows}) == 2
    assert len({row["original_snapshot"] for row in repeated_rows}) == 2
    assert all("mathematical-formalizer--" in row["physical_output"] for row in repeated_rows)

    unique_row = next(row for row in plan["outputs"] if row["agent"] == unique_label)
    assert unique_row["physical_output"].endswith(
        "/corrected/contradiction-miner.bundle.json"
    )
    assert unique_row["original_snapshot"].endswith(
        "/originals/contradiction-miner.bundle.json"
    )

    formalize_out = physical_output(run_dir, plan, nodes[0]["id"])
    mechanism_out = physical_output(run_dir, plan, nodes[1]["id"])
    assert formalize_out is not None
    assert mechanism_out is not None
    assert formalize_out != mechanism_out
    first_snapshot = json.loads(
        (run_dir / repeated_rows[0]["original_snapshot"]).read_text(encoding="utf-8")
    )
    second_snapshot = json.loads(
        (run_dir / repeated_rows[1]["original_snapshot"]).read_text(encoding="utf-8")
    )
    assert first_snapshot != second_snapshot

    formalize_out.parent.mkdir(parents=True, exist_ok=True)
    formalize_out.write_text(json.dumps({"kind": "formalize-corrected"}), encoding="utf-8")
    mechanism_out.write_text(json.dumps({"kind": "mechanism-corrected"}), encoding="utf-8")

    finalize_output(run_dir, "DISCOVER", 1, nodes[0]["id"], TS)
    assert resolve_effective_output(run_dir, "DISCOVER", formalize) == formalize_out
    assert resolve_effective_output(run_dir, "DISCOVER", mechanism) == mechanism

    finalize_output(run_dir, "DISCOVER", 1, nodes[1]["id"], TS)
    assert resolve_effective_output(run_dir, "DISCOVER", formalize) == formalize_out
    assert resolve_effective_output(run_dir, "DISCOVER", mechanism) == mechanism_out
    assert json.loads(formalize_out.read_text(encoding="utf-8"))["kind"] == (
        "formalize-corrected"
    )
    assert json.loads(mechanism_out.read_text(encoding="utf-8"))["kind"] == (
        "mechanism-corrected"
    )


def test_v1_finalized_output_hash_drift_is_not_silently_accepted(tmp_path):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    logical = inbox / "legacy.bundle.json"
    logical.write_text(json.dumps({"version": 1}), encoding="utf-8")
    node = _node(0, "legacy-worker", logical, run_dir)
    plan = prepare_plan(
        run_dir,
        "DESIGN",
        1,
        [node],
        {"legacy-worker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected = physical_output(run_dir, plan, node["id"])
    assert corrected is not None
    corrected.parent.mkdir(parents=True, exist_ok=True)
    corrected.write_text(json.dumps({"version": 2}), encoding="utf-8")
    finalize_output(run_dir, "DESIGN", 1, node["id"], TS)

    plan_file = run_dir / "inbox/supplements/DESIGN/repair-001/repair-plan.json"
    finalized_plan = json.loads(plan_file.read_text(encoding="utf-8"))
    finalized_plan["contract_version"] = "supplement-lineage/v1"
    plan_file.write_text(json.dumps(finalized_plan), encoding="utf-8")
    corrected.write_text(json.dumps({"version": 3}), encoding="utf-8")

    with pytest.raises(ValueError, match="finalized repair output hash drift"):
        resolve_effective_output(run_dir, "DESIGN", logical)


def test_finalize_cannot_redefine_a_finalized_output_in_same_cycle(tmp_path):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    logical = inbox / "worker.bundle.json"
    logical.write_text(json.dumps({"version": 1}), encoding="utf-8")
    node = _node(0, "worker", logical, run_dir)
    plan = prepare_plan(
        run_dir,
        "DESIGN",
        1,
        [node],
        {"worker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected = physical_output(run_dir, plan, node["id"])
    assert corrected is not None
    corrected.parent.mkdir(parents=True, exist_ok=True)
    corrected.write_text(json.dumps({"version": 2}), encoding="utf-8")
    finalize_output(run_dir, "DESIGN", 1, node["id"], TS)
    plan_file = run_dir / "inbox/supplements/DESIGN/repair-001/repair-plan.json"
    first = json.loads(plan_file.read_text(encoding="utf-8"))["outputs"][0]

    corrected.write_text(json.dumps({"version": 3}), encoding="utf-8")
    with pytest.raises(ValueError, match="finalized repair output hash drift"):
        finalize_output(run_dir, "DESIGN", 1, node["id"], TS)

    second = json.loads(plan_file.read_text(encoding="utf-8"))["outputs"][0]
    assert second["output_sha256"] == first["output_sha256"]
    assert second["completed_at"] == first["completed_at"]


@pytest.mark.parametrize(
    "field",
    [
        "logical_output",
        "physical_output",
        "original_snapshot",
        "supersedes_ref",
        "repair_scope.target_artifact_ref",
    ],
)
def test_tampered_plan_cannot_resolve_any_row_path_outside_run(
        tmp_path, field):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    logical = inbox / "worker.bundle.json"
    logical.write_text(json.dumps({"version": 1}), encoding="utf-8")
    node = _node(0, "worker", logical, run_dir)
    prepare_plan(
        run_dir,
        "DESIGN",
        1,
        [node],
        {"worker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    outside = tmp_path / "outside-secret.json"
    outside.write_text(json.dumps({"secret": "outside-run"}), encoding="utf-8")
    outside_before = outside.read_bytes()
    plan_file = run_dir / "inbox/supplements/DESIGN/repair-001/repair-plan.json"
    tampered = json.loads(plan_file.read_text(encoding="utf-8"))
    row = tampered["outputs"][0]
    if field == "repair_scope.target_artifact_ref":
        row["repair_scope"]["target_artifact_ref"] = str(outside.resolve())
    else:
        row[field] = str(outside.resolve())
    row["output_sha256"] = sha256(outside)
    row["completed_at"] = TS
    plan_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="must be a normalized run-relative path"):
        resolve_effective_output(run_dir, "DESIGN", logical)
    with pytest.raises(ValueError, match="must be a normalized run-relative path"):
        physical_output(run_dir, tampered, node["id"])
    with pytest.raises(ValueError, match="must be a normalized run-relative path"):
        finalize_output(run_dir, "DESIGN", 1, node["id"], TS)
    assert outside.read_bytes() == outside_before


def test_plan_physical_output_is_confined_to_current_corrected_lane(tmp_path):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    logical = inbox / "worker.bundle.json"
    logical.write_text(json.dumps({"version": 1}), encoding="utf-8")
    node = _node(0, "worker", logical, run_dir)
    plan = prepare_plan(
        run_dir,
        "DESIGN",
        1,
        [node],
        {"worker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    plan["outputs"][0]["physical_output"] = "inbox/worker.bundle.json"

    with pytest.raises(ValueError, match="unsafe repair plan physical_output"):
        physical_output(run_dir, plan, node["id"])


def test_plan_physical_output_rejects_linked_corrected_lane(tmp_path):
    run_dir = tmp_path / "run"
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True)
    logical = inbox / "worker.bundle.json"
    logical.write_text(json.dumps({"version": 1}), encoding="utf-8")
    node = _node(0, "worker", logical, run_dir)
    plan = prepare_plan(
        run_dir,
        "DESIGN",
        1,
        [node],
        {"worker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    corrected_lane = run_dir / "inbox/supplements/DESIGN/repair-001/corrected"
    _link_directory_or_skip(corrected_lane, outside)

    with pytest.raises(
        ValueError,
        match="unsafe repair plan physical_output.*(?:SYMLINK_PATH|REPARSE_PATH)",
    ):
        physical_output(run_dir, plan, node["id"])


def test_repair_plan_write_rejects_linked_parent_before_touching_outside(tmp_path):
    """An actual symlink/reparse parent cannot redirect a plan outside the run."""
    run_dir = tmp_path / "run"
    (run_dir / "inbox").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside_repair = outside / "DESIGN" / "repair-001"
    outside_repair.mkdir(parents=True)
    marker = outside / "director-owned.txt"
    marker.write_text("unchanged", encoding="utf-8")
    linked_parent = run_dir / "inbox" / "supplements"
    predictable_tmp = outside_repair / "repair-plan.json.tmp"
    link_kind = _link_directory_or_skip(linked_parent, outside)
    if link_kind == "symlink":
        predictable_tmp.symlink_to(marker)

    with pytest.raises(ValueError, match="unsafe supplement plan path.*(?:SYMLINK_PATH|REPARSE_PATH)"):
        prepare_plan(
            run_dir,
            "DESIGN",
            1,
            [],
            set(),
            {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
        )

    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (outside_repair / "repair-plan.json").exists()
