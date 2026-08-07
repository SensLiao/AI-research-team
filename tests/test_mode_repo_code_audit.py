"""Mode-level end-to-end tests for the `repo_code_audit` operate recipe (wave 2).

The registry asked for "mode-level end-to-end tests for audit-only, patched, failed-test, and
non-reproducible outcomes". Three of those four are covered directly. The fourth pair — a REAL
failed test / non-reproducible reproduction — is only reachable behind an attested executor import,
so what is tested here is the boundary that guards it: a worker that reports a test or reproduction
outcome without an execution receipt is BLOCKed rather than believed. Fabricating a receipt chain to
manufacture a "failed test" would be exactly the dishonesty the gate exists to stop.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, repo_code_audit as mode
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T09:00:00Z"
MODE = "repo_code_audit"
NORTH_STAR = {
    "statement": "audit the residual-correction training code for leakage and reproducibility defects",
    "in_scope": ["training code", "leakage", "reproducibility"],
    "out_of_scope": ["topology continuity"],
}


# --------------------------------------------------------------------------- fixtures

def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": MODE,
                      "request_text": "audit the training code for leakage",
                      "north_star": NORTH_STAR,
                      "budget": budget or {"max_agent_hops": 10, "max_debug_retries_per_run": 2}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _bundle(run_dir, stage, label, payload):
    path = Path(run_dir) / "inbox" / f"{stage}.{label}.bundle.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _audit_bundle(**overrides):
    audit = {
        "repo_ref": "org/petct-residual-correction",
        "checks": {"has_code": True, "has_license": True, "license_id": "MIT",
                   "has_pinned_commit": True, "commit": "abc1234", "has_weights": False,
                   "pretrained_loads_grepped": True},
        "surfaces_examined": ["src/", "src/train.py", "src/metrics.py", "tests/"],
        "findings": [
            # severity 'low' on a structurally severe category: the floor must escalate it.
            {"finding_id": "F-001", "path": "src/train.py", "locus": "build_loader",
             "category": "test-set-leakage", "severity": "low",
             "title": "the test split is concatenated into the training loader",
             "impact": "every reported training metric is invalid",
             "evidence": ["src/train.py:88 `ds = train_ds + test_ds`"],
             "recommendation": "build the loader from the train split only"},
            # same path+locus, category spelled with underscores: must merge into F-001.
            {"finding_id": "F-002", "path": "src/train.py", "locus": "build_loader",
             "category": "test_set_leakage", "severity": "medium",
             "title": "the same leakage reaches the validation loader",
             "impact": "validation can no longer select a model",
             "evidence": ["src/train.py:91"]},
            {"finding_id": "F-003", "path": "src/metrics.py", "locus": "",
             "category": "nondeterministic-seed", "severity": "medium",
             "title": "the training code seeds numpy but never torch",
             "impact": "no run is reproducible",
             "evidence": ["src/metrics.py:12 `np.random.seed(cfg.seed)`"]},
        ],
        "notes": "walked four surfaces; no read-only assistants used",
    }
    audit.update(overrides)
    return {"repo_audit": audit}


def _plan_bundle(**overrides):
    plan = {
        "status": "draft", "title": "stop the training-loader leakage",
        "rationale": "covers the leakage findings F-001/F-002 and the seeding finding F-003",
        "changes": [
            {"path": "src/train.py", "change_type": "modify",
             "description": "build the training loader from the train split only; the test-split "
                            "leakage ends here",
             "snippet": "ds = train_ds", "risk_note": "every downstream training run changes"},
            {"path": "src/metrics.py", "change_type": "modify",
             "description": "seed torch alongside numpy so reproducibility holds",
             "snippet": None, "risk_note": None},
        ],
    }
    plan.update(overrides)
    return {"patch_plan": plan}


def _impl_bundle(**overrides):
    record = {
        "from_patch_plan_ref": "evidence/EXECUTE/patch-plan.artifact.json",
        "condition_id": "patch-leakage-1",
        "summary": "the training loader no longer sees the test split",
        "files_changed": [
            {"path": "src/train.py", "change_type": "modified", "lines_added": 3,
             "lines_removed": 4, "notes": "loader split"},
            {"path": "src/metrics.py", "change_type": "modified", "lines_added": 2,
             "lines_removed": 0, "notes": "torch seeding"},
        ],
        "out_of_scope_writes_blocked": False, "git_sha": None, "caveats": [],
    }
    record.update(overrides)
    return {"implementation_record": record}


def _suite_bundle(**overrides):
    suite = {
        "from_implementation_ref": "evidence/EXECUTE/implementation-record.artifact.json",
        "test_targets": ["training loader split", "torch seeding"],
        "test_files": [{"path": "tests/test_loader_split.py", "n_tests": 2,
                        "covers": ["training loader split"]}],
        "coverage_pct": None, "notes": "the GPU path is not covered",
    }
    suite.update(overrides)
    return {"test_suite_record": suite}


def _sandbox_bundle(**overrides):
    sandbox = {
        "condition_id": "patch-leakage-1",
        "from_implementation_ref": "evidence/EXECUTE/implementation-record.artifact.json",
        "smoke_script": "import src.train\nassert 'test' not in src.train.build_loader('train').splits\n",
        "invoke_command": "python -m pytest tests/test_loader_split.py",
        "smoke_passed": None, "exit_code": None, "stdout_tail": None, "stderr_tail": None,
        "notes": "imports the training module and asserts the loader split",
    }
    sandbox.update(overrides)
    return {"sandbox_report": sandbox}


def _repro_bundle(**overrides):
    repro = {
        "condition_id": "patch-leakage-1", "seed": 17,
        "config_hash": "a" * 64, "data_hash": "b" * 64, "git_sha": None,
        "repro_script": "python -m pytest tests/test_loader_split.py -q",
        "repro_passed": None, "result_delta": None,
        "notes": "hashes computed with sha256sum over configs/train.yaml and tests/fixtures/",
    }
    repro.update(overrides)
    return {"repro_record": repro}


AUTHORIZATION = {
    "authorization_contract_version": mode.AUTHORIZATION_VERSION, "repo_patch": True,
    "authorized_by": "director",
    "authorized_paths": ["src/"],
    "scope_note": "fix the training-loader leakage and the seeding defect only",
}


def _authorize(run_dir, **overrides):
    marker = dict(AUTHORIZATION)
    marker.update(overrides)
    (Path(run_dir) / mode.AUTHORIZATION_REL).write_text(
        json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    return marker


def _seed_audit_only(tmp_path, audit=None, plan=None):
    run_dir = _mk_run(tmp_path)
    _bundle(run_dir, "DISCOVER", "repo-code-verifier", audit or _audit_bundle())
    _bundle(run_dir, "EXECUTE", "patch-planner", plan or _plan_bundle())
    return run_dir


def _seed_patch(tmp_path, **bundles):
    run_dir = _seed_audit_only(tmp_path, plan=bundles.get("plan"))
    _authorize(run_dir, **(bundles.get("marker") or {}))
    _bundle(run_dir, "EXECUTE", "code-implementer", bundles.get("impl") or _impl_bundle())
    _bundle(run_dir, "EXECUTE", "unit-test-writer", bundles.get("suite") or _suite_bundle())
    _bundle(run_dir, "EXECUTE", "sandbox-runner", bundles.get("sandbox") or _sandbox_bundle())
    _bundle(run_dir, "EXECUTE", "repro-runner", bundles.get("repro") or _repro_bundle())
    return run_dir


def _assert_artifacts_valid(paths):
    assert paths, "a stage produced no artifact"
    for path in paths:
        art = json.loads(Path(path).read_text(encoding="utf-8"))
        assert not validate_artifact(art), f"{path} failed its contract: {validate_artifact(art)}"


def _markdown(run_dir):
    rel = _panel_recipe.target_markdown(MODE)["path"]
    path = Path(run_dir) / rel
    assert path.is_file(), f"director Markdown was never rendered at {rel}"
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 1. happy paths

def test_audit_only_branch_delivers_findings_and_a_proposal_but_changes_nothing(tmp_path):
    run_dir = _seed_audit_only(tmp_path)

    paths, discover = mode.run_dets(run_dir, "DISCOVER", TS)
    _assert_artifacts_valid(paths)
    assert discover["repo_verification"] == "VERIFIED"
    # 3 raw findings -> 2 after the path+locus+category merge; the merged group keeps CRITICAL
    # (the worker wrote 'low' on a leakage category and the structural floor overrode it), and the
    # nondeterministic-seed finding was floor-escalated from 'medium' to 'high'.
    assert (discover["n_findings_raw"], discover["n_findings"], discover["n_findings_merged"]) == (3, 2, 1)
    assert discover["severity_histogram"] == {"critical": 1, "high": 1, "medium": 0, "low": 0}
    assert discover["drift_gate"] == "PASS"
    assert discover["existence_gate"] == "NOT_APPLICABLE"      # a code audit has no bibliography

    paths, execute = mode.run_dets(run_dir, "EXECUTE", TS)
    _assert_artifacts_valid(paths)
    assert execute["branch"] == "audit_only"
    assert execute["patch_plan_status"] == "draft"
    assert execute["authorization_ref"] is None
    assert execute["n_files_changed"] == 0
    assert (execute["preflight_gate"], execute["change_boundary_gate"],
            execute["plan_applied_parity_gate"]) == ("NOT_APPLICABLE",) * 3
    assert (execute["smoke_status"], execute["repro_status"]) == ("NOT_APPLICABLE",) * 2
    # No patch-branch artifact may exist in an unauthorized run.
    for name in mode._PATCH_ONLY_ARTIFACTS:
        assert not (Path(run_dir) / "evidence" / "EXECUTE" / name).exists()

    text = _markdown(run_dir)
    for section in _panel_recipe.target_markdown(MODE)["required_sections"]:
        assert f"## {section}" in text, f"missing rendered section {section!r}"
    applied = text.split("## Authorized changes", 1)[1].split("\n## ", 1)[0]
    assert "未授权" in applied and "NOT AUTHORIZED" in applied
    assert "NOT_APPLICABLE" in applied
    assert "PROPOSALS" in text and "FINDINGS" in text          # the three-way split is explicit

    paths, _ = mode.run_dets(run_dir, "REPORT", TS)
    _assert_artifacts_valid(paths)
    note = json.loads(Path(paths[0]).read_text(encoding="utf-8"))["payload"]
    assert note["references"] == [_panel_recipe.target_markdown(MODE)["path"]]
    assert note["open_questions"], "an audit-only run must ask whether to authorize the patch"


def test_authorized_patch_branch_records_applied_changes_and_all_three_guards(tmp_path):
    run_dir = _seed_patch(tmp_path)

    _assert_artifacts_valid(mode.run_dets(run_dir, "DISCOVER", TS)[0])
    paths, execute = mode.run_dets(run_dir, "EXECUTE", TS)
    _assert_artifacts_valid(paths)

    assert execute["branch"] == "authorized_patch"
    assert execute["patch_plan_status"] == "approved"
    assert execute["authorization_ref"] == mode.AUTHORIZATION_REL
    assert execute["n_files_changed"] == 2
    assert execute["n_test_targets"] == 2
    assert (execute["preflight_gate"], execute["change_boundary_gate"],
            execute["plan_applied_parity_gate"]) == ("PASS",) * 3
    # Fenced seats ran nothing, so the honest status is NOT_EXECUTED — never a silent pass.
    assert (execute["smoke_status"], execute["repro_status"]) == ("NOT_EXECUTED", "NOT_EXECUTED")
    assert execute["execution_executed"] is False

    written = {Path(p).name for p in paths}
    assert set(mode._PATCH_ONLY_ARTIFACTS) <= written

    text = _markdown(run_dir)
    for section in _panel_recipe.target_markdown(MODE)["required_sections"]:
        assert f"## {section}" in text
    applied = text.split("## Authorized changes", 1)[1].split("\n## ", 1)[0]
    assert "APPLIED CHANGES" in applied and "src/train.py" in applied and "director" in applied
    assert "未授权" not in applied
    assert "Did NOT run" in text                               # the execution-boundary sentence

    _assert_artifacts_valid(mode.run_dets(run_dir, "REPORT", TS)[0])


# --------------------------------------------------------------------------- 2. missing seat bundle

def test_missing_seat_bundle_blocks_and_names_the_file(tmp_path):
    run_dir = _seed_patch(tmp_path)
    (Path(run_dir) / "inbox" / "EXECUTE.repro-runner.bundle.json").unlink()
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "EXECUTE.repro-runner.bundle.json" in str(exc.value)


def test_execute_without_discover_findings_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _bundle(run_dir, "EXECUTE", "patch-planner", _plan_bundle())
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "DISCOVER.repo-code-verifier.bundle.json" in str(exc.value)


# --------------------------------------------------------------------------- 3. the mode's own gates

def test_audit_only_blocks_when_a_patch_seat_bundle_exists(tmp_path):
    """The signature gate: an unauthorized run may not carry one trace of an applied change."""
    run_dir = _seed_audit_only(tmp_path)
    _bundle(run_dir, "EXECUTE", "code-implementer", _impl_bundle())
    mode.run_dets(run_dir, "DISCOVER", TS)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    message = str(exc.value)
    assert "audit-only BLOCK" in message
    assert "inbox/EXECUTE.code-implementer.bundle.json" in message


def test_audit_only_blocks_when_an_applied_change_artifact_exists(tmp_path):
    run_dir = _seed_audit_only(tmp_path)
    stray = Path(run_dir) / "evidence" / "EXECUTE" / "implementation-record.artifact.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("{}", encoding="utf-8")
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "evidence/EXECUTE/implementation-record.artifact.json" in str(exc.value)


def test_audit_only_blocks_a_self_approved_plan(tmp_path):
    run_dir = _seed_audit_only(tmp_path, plan=_plan_bundle(status="approved"))
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "audit-only BLOCK" in str(exc.value)


def test_planner_may_not_approve_its_own_plan_even_when_authorized(tmp_path):
    run_dir = _seed_patch(tmp_path, plan=_plan_bundle(status="approved"))
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "status='draft'" in str(exc.value)


def test_touched_path_outside_the_authorized_scope_blocks(tmp_path):
    impl = _impl_bundle(files_changed=[
        {"path": "src/train.py", "change_type": "modified", "lines_added": 3, "lines_removed": 4,
         "notes": "loader split"},
        {"path": "src/metrics.py", "change_type": "modified", "lines_added": 2, "lines_removed": 0,
         "notes": "torch seeding"},
        {"path": "deploy/secrets.env", "change_type": "modified", "lines_added": 1,
         "lines_removed": 0, "notes": "unrelated"},
    ])
    run_dir = _seed_patch(tmp_path, impl=impl)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    message = str(exc.value)
    assert "change-boundary BLOCK" in message and "deploy/secrets.env" in message


def test_planned_path_outside_the_authorized_scope_blocks_at_preflight(tmp_path):
    plan = _plan_bundle(changes=[
        {"path": "docs/README.md", "change_type": "modify",
         "description": "document the training-loader leakage fix", "snippet": None,
         "risk_note": None}])
    run_dir = _seed_patch(tmp_path, plan=plan)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "preflight BLOCK" in str(exc.value) and "docs/README.md" in str(exc.value)


def test_planned_but_unapplied_change_blocks_on_parity(tmp_path):
    impl = _impl_bundle(files_changed=[
        {"path": "src/train.py", "change_type": "modified", "lines_added": 3, "lines_removed": 4,
         "notes": "loader split"}])
    run_dir = _seed_patch(tmp_path, impl=impl)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    message = str(exc.value)
    assert "parity BLOCK" in message and "src/metrics.py" in message


def test_placeholder_reproduction_hash_blocks(tmp_path):
    run_dir = _seed_patch(tmp_path, repro=_repro_bundle(data_hash="unknown"))
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "repro_record.data_hash" in str(exc.value)


def test_worker_claimed_test_outcome_without_an_execution_receipt_blocks(tmp_path):
    """A fenced seat cannot have measured anything — a claimed pass is refused, not recorded."""
    run_dir = _seed_patch(tmp_path, sandbox=_sandbox_bundle(smoke_passed=True, exit_code=0))
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    message = str(exc.value)
    assert "not-started" in message and "test / smoke / reproduction outcomes" in message


def test_worker_claimed_test_failure_is_also_refused_without_a_receipt(tmp_path):
    run_dir = _seed_patch(tmp_path, repro=_repro_bundle(repro_passed=False,
                                                        result_delta="dice diverged by 0.04"))
    with pytest.raises(GateBlock):
        mode.run_dets(run_dir, "EXECUTE", TS)


def test_mismatched_patch_identity_blocks(tmp_path):
    run_dir = _seed_patch(tmp_path, repro=_repro_bundle(condition_id="some-other-patch"))
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "EXECUTE", TS)
    assert "SAME patch" in str(exc.value)


def test_repository_without_usable_code_stops_the_audit(tmp_path):
    audit = _audit_bundle()
    audit["repo_audit"]["checks"]["has_code"] = False
    run_dir = _seed_audit_only(tmp_path, audit=audit)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "DISCOVER", TS)
    assert "nothing to audit" in str(exc.value)


def test_unevidenced_finding_blocks(tmp_path):
    audit = _audit_bundle()
    audit["repo_audit"]["findings"][0]["evidence"] = []
    run_dir = _seed_audit_only(tmp_path, audit=audit)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "DISCOVER", TS)
    assert "no evidence" in str(exc.value)


def test_unknown_severity_blocks_instead_of_defaulting(tmp_path):
    audit = _audit_bundle()
    audit["repo_audit"]["findings"][0]["severity"] = "spicy"
    run_dir = _seed_audit_only(tmp_path, audit=audit)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "DISCOVER", TS)
    assert "severity" in str(exc.value) and "never silently defaulted" in str(exc.value)


def test_non_boolean_repo_fact_blocks(tmp_path):
    audit = _audit_bundle()
    audit["repo_audit"]["checks"]["has_license"] = "yes"
    run_dir = _seed_audit_only(tmp_path, audit=audit)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "DISCOVER", TS)
    assert "checks.has_license" in str(exc.value)


# --------------------------------------------------------------------------- 4. unknown stage

def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _seed_audit_only(tmp_path)
    with pytest.raises(ValueError):
        mode.run_dets(run_dir, "IDEATE", TS)


def test_stage_path_mirrors_the_registry(tmp_path):
    assert mode.STAGES == _panel_recipe.stage_path(MODE) == ["DISCOVER", "EXECUTE", "REPORT"]


# --------------------------------------------------------------------------- 5. dispatch contract

def test_every_dispatched_label_is_a_declared_seat(tmp_path):
    declared = set(_panel_recipe.declared_seats(MODE))
    audit_only = _seed_audit_only(tmp_path / "a")
    patched = _seed_patch(tmp_path / "b")
    for run_dir in (audit_only, patched):
        for stage in ("DISCOVER", "EXECUTE"):
            spec = mode.llm_step(run_dir, stage, "audit the training code", model_policy="max_quality")
            labels = [worker["label"] for worker in spec["workers"]]
            assert labels, f"{stage} dispatched nobody"
            assert set(labels) <= declared, f"{stage} dispatched undeclared seat(s)"
            assert all(worker["model"] == "opus" for worker in spec["workers"])
            for worker in spec["workers"]:
                assert "NORTH STAR" in worker["prompt"]
                # Never a ceiling: worker volume is floor-bounded (measured 2026-08-03).
                assert "at most" not in worker["prompt"].casefold()
    assert mode.llm_step(audit_only, "REPORT", "x") is None


def test_dispatch_branches_on_the_authorization_marker(tmp_path):
    audit_only = mode.llm_step(_seed_audit_only(tmp_path / "a"), "EXECUTE", "x")
    patched = mode.llm_step(_seed_patch(tmp_path / "b"), "EXECUTE", "x")
    assert [w["label"] for w in audit_only["workers"]] == ["patch-planner"]
    assert "AUDIT-ONLY" in audit_only["panel_note"]
    assert [w["label"] for w in patched["workers"]] == [
        "patch-planner", "code-implementer", "unit-test-writer", "sandbox-runner", "repro-runner"]
    assert patched["parallel_groups"] == [["patch-planner"], ["code-implementer"],
                                          ["unit-test-writer", "sandbox-runner"], ["repro-runner"]]
    assert len(patched["workers"]) <= _panel_recipe.mode_budget(MODE)["max_agent_hops"]


# --------------------------------------------------------------------------- 6. the authorization switch

def test_absent_marker_is_audit_only(tmp_path):
    assert mode.load_patch_authorization(_mk_run(tmp_path)) is None


def test_explicit_repo_patch_false_is_audit_only(tmp_path):
    run_dir = _mk_run(tmp_path)
    _authorize(run_dir, repo_patch=False)
    assert mode.load_patch_authorization(run_dir) is None


@pytest.mark.parametrize("overrides, expected", [
    ({"repo_patch": "true"}, "boolean true or false"),
    ({"authorization_contract_version": "repo-patch-authorization/v0"}, "authorization_contract_version"),
    ({"authorized_paths": []}, "non-empty authorized_paths"),
    ({"authorized_paths": ["../../etc"]}, "safe repo-relative prefix"),
    ({"authorized_by": ""}, "authorized_by"),
    ({"scope_note": "too short"}, "scope_note"),
])
def test_malformed_marker_blocks_rather_than_degrading_to_audit_only(tmp_path, overrides, expected):
    run_dir = _mk_run(tmp_path)
    _authorize(run_dir, **overrides)
    with pytest.raises(GateBlock) as exc:
        mode.load_patch_authorization(run_dir)
    assert expected in str(exc.value)


def test_unparseable_marker_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    (Path(run_dir) / mode.AUTHORIZATION_REL).write_text("{not json", encoding="utf-8")
    with pytest.raises(GateBlock) as exc:
        mode.load_patch_authorization(run_dir)
    assert "never downgraded to audit-only" in str(exc.value)
    # A broken marker still dispatches the audit-only panel; the deterministic stage raises.
    assert mode._dispatch_authorized(run_dir) is False


# --------------------------------------------------------------------------- 7. deterministic findings

def test_structural_floor_overrides_the_worker_severity():
    findings = mode.normalize_findings(_audit_bundle()["repo_audit"])
    # F-001 was written 'low' and F-002 'medium' on a leakage category -> both floored to critical;
    # F-003 was written 'medium' on nondeterministic-seed -> floored to high. A worker cannot talk
    # a structurally severe category down.
    assert [f["severity"] for f in findings] == ["critical", "critical", "high"]


def test_merge_keeps_the_highest_severity_and_orders_totally():
    findings = mode.normalize_findings(_audit_bundle()["repo_audit"])
    merged = mode.dedupe_findings(findings)
    assert [f["finding_id"] for f in merged] == ["F-001", "F-003"]
    assert merged[0]["merged_ids"] == ["F-001", "F-002"]
    assert merged[0]["evidence"] == ["src/train.py:88 `ds = train_ds + test_ds`", "src/train.py:91"]
    # Re-running on a reshuffled input yields byte-identical ordering.
    assert mode.dedupe_findings(list(reversed(findings))) == merged


def test_merge_cannot_launder_a_severe_finding_into_a_mild_one():
    """A group's severity is the MAX of its members, on a category with no structural floor."""
    audit = _audit_bundle(findings=[
        {"finding_id": "F-010", "path": "src/train.py", "locus": "step", "category": "correctness",
         "severity": "low", "title": "off-by-one in the training loop bound",
         "evidence": ["src/train.py:210"]},
        {"finding_id": "F-011", "path": "src/train.py", "locus": "step", "category": "correctness",
         "severity": "high", "title": "the same bound drops the final training batch",
         "evidence": ["src/train.py:211"]},
    ])["repo_audit"]
    merged = mode.dedupe_findings(mode.normalize_findings(audit))
    assert len(merged) == 1
    assert merged[0]["severity"] == "high"                      # never the 'low' of the lead entry
    assert merged[0]["merged_ids"] == ["F-010", "F-011"]


def test_findings_never_merge_across_files_or_categories():
    audit = _audit_bundle()["repo_audit"]
    audit["findings"][1]["category"] = "correctness"            # same path+locus, other category
    merged = mode.dedupe_findings(mode.normalize_findings(audit))
    assert len(merged) == 3


def test_missing_findings_key_blocks_but_an_empty_list_is_a_legitimate_answer(tmp_path):
    audit = _audit_bundle()
    audit["repo_audit"].pop("findings")
    run_dir = _seed_audit_only(tmp_path / "a", audit=audit)
    with pytest.raises(GateBlock) as exc:
        mode.run_dets(run_dir, "DISCOVER", TS)
    assert "did not do the job" in str(exc.value)

    empty = _seed_audit_only(tmp_path / "b", audit=_audit_bundle(findings=[]))
    _, discover = mode.run_dets(empty, "DISCOVER", TS)
    assert discover["n_findings"] == 0
    _, _ = mode.run_dets(empty, "EXECUTE", TS)
    findings_section = _markdown(empty).split("## Prioritized findings", 1)[1].split("\n## ", 1)[0]
    assert findings_section.strip(), "'nothing found' must still render a non-empty section"
    assert "None found" in findings_section
