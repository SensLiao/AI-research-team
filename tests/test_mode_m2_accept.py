"""Operate-level acceptance tests for the `m2_accept` recipe (wave 2).

The fixtures stand in for the 15 LLM seats and for a non-LLM lab executor. Everything else — panel
composition, the three mode-specific hard gates, the planned/attempted/completed classifier, numeric
reconstruction from signed receipts, and the acceptance-report renderer — is the real operated code.

The mode's whole reason to exist is the planned-vs-ran distinction, so the happy path is tested
TWICE: once where nothing ran (the report must say so in plain words and carry no number) and once
where an attested execution really happened (the numbers must be rebuilt from receipts, not accepted
from the analyst).
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from statistics import fmean

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, m2_accept
from research_agent_teams.tools.execution_receipt_import import (
    canonical_json_bytes,
    receipt_attestation_message,
    sha256_bytes,
    sha256_file,
    trust_public_key_env_name,
)
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T00:00:00Z"
MODE = "m2_accept"
REQUEST = "compare a LoRA adapter against a full fine-tune for 3D vessel segmentation at equal budget"
NORTH_STAR = {"statement": REQUEST, "in_scope": ["LoRA adapter", "segmentation"],
              "out_of_scope": ["diffusion"]}

EXECUTOR_KEY_ID = "m2-accept-test-runner"
EXECUTOR_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"test-only-m2-accept-external-executor-key").digest())
EXECUTOR_PUBLIC_KEY = EXECUTOR_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

SEED_VALUES = {"c0": {"Dice": [0.77, 0.78, 0.79]}, "c1": {"Dice": [0.80, 0.81, 0.82]}}


@pytest.fixture(autouse=True)
def _executor_trust_root(monkeypatch):
    monkeypatch.setenv(trust_public_key_env_name(EXECUTOR_KEY_ID),
                       base64.b64encode(EXECUTOR_PUBLIC_KEY).decode("ascii"))


def _mk_run(tmp_path) -> Path:
    run_dir = tmp_path / "run-m2"
    (run_dir / "inbox").mkdir(parents=True)
    frame = {"payload": {"task_id": "run-m2", "mode": MODE, "request_text": REQUEST,
                         "north_star": NORTH_STAR,
                         "budget": {"max_agent_hops": 24, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(frame), encoding="utf-8")
    return run_dir


def _write(run_dir, stage: str, seat: str, payload: dict) -> None:
    path = Path(run_dir) / "inbox" / f"{stage}.{seat}.bundle.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- DESIGN fixtures

def _pipeline(augment: bool) -> dict:
    return {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": augment},
            "pretrained": "none", "precision": "fp32", "inference": {"threshold": 0.5},
            "label_space": ["bg", "vessel"]}


def _design(**over) -> dict:
    impls = {"Dice": {"impl_ref": "monai.dice", "spacing": None, "postprocess": None}}
    return {
        "design": {
            "rq": over.get("rq", "Does a LoRA adapter match a full fine-tune for vessel "
                                "segmentation at equal data budget on fold0?"),
            "variables": over.get("variables", {"studied": ["adapter"],
                                                "controlled": ["lr", "epochs"],
                                                "frozen": ["backbone", "split"]}),
            "conditions": over.get("conditions", [
                {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50,
                                         "backbone": "sam-vit-b", "split": "fold0"},
                 "baseline": True},
                {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50,
                                         "backbone": "sam-vit-b", "split": "fold0"}}]),
            "ranked_batch": [{"rank": 1, "condition_id": "c1",
                              "hypothesis": "A LoRA adapter matches the full fine-tune on Dice "
                                            "for vessel segmentation at equal budget"}],
            "leakage": "Every input derives from training images only; test masks are never read.",
        },
        "train": _pipeline(True), "test": _pipeline(False),
        "shared_config": {"optimizer": "adamw"},
        "metric_impls": [{"condition_id": "c0", "metric_impls": dict(impls)},
                         {"condition_id": "c1", "metric_impls": dict(impls)}],
        "prereg": {"primary_metric": "Dice", "secondary_metrics": [], "n_seeds_planned": 3,
                   "stopping_rule": "fixed 3 seeds per condition",
                   "analysis_plan": "paired permutation vs the baseline on Dice, alpha=0.05"},
    }


_AUDIT_SEATS = (("variable-control-auditor", "variable_control_audit"),
                ("train-test-alignment-auditor", "train_test_alignment_audit"),
                ("metric-implementation-auditor", "metric_implementation_audit"))


def _write_design_panel(run_dir, *, design=None, frozen=None, witness_override=None,
                        witness_for=None, verdicts=None) -> dict:
    """Feed all five DESIGN seats. `frozen`/`witness_*` let a test break one seat only."""
    design = design if design is not None else _design()
    frozen = frozen if frozen is not None else design
    truth = m2_accept._freeze_witness(frozen)
    _write(run_dir, "DESIGN", "experiment-planner", {"candidate_bundle": design})
    _write(run_dir, "DESIGN", "protocol-compiler", {"protocol_freeze": {
        "frozen_design": frozen,
        "freeze_note": "Copied the planner's bundle unchanged; no concern to hand on.",
        "seed_policy": "The same three seeds run in both conditions so the contrast stays paired.",
        "freeze_witness": truth}})
    for seat, key in _AUDIT_SEATS:
        witness = witness_override if (witness_override is not None and seat == witness_for) else truth
        verdict = (verdicts or {}).get(seat, {"verdict": "PASS", "blocking_concerns": []})
        _write(run_dir, "DESIGN", seat, {key: {
            "seat": seat, "audited_freeze_witness": witness,
            "verdict": verdict["verdict"], "blocking_concerns": verdict["blocking_concerns"],
            "findings": [{"where": "conditions/c1", "observation": f"{seat} inspected the frozen "
                                                                  "design and recorded this",
                          "severity": "note"}]}})
    return design


# --------------------------------------------------------------------------- EXECUTE fixtures

def _scripts() -> tuple:
    train = {"split": "train", "script": "def build_train():\n    return load('train')",
             "from_protocol_ref": m2_accept.PROTOCOL_REF, "data_hash_expected": "dh-train",
             "augmentation_enabled": True, "frozen": False}
    test = {"split": "test", "script": "def build_test():\n    return load('test')",
            "from_protocol_ref": m2_accept.PROTOCOL_REF, "data_hash_expected": "dh-test",
            "augmentation_enabled": False, "frozen": True}
    return train, test


def _execution_file(run_dir: Path, relative: str, content: str) -> dict:
    path = run_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _real_execution(run_dir: Path) -> tuple:
    """Install signed executor receipts and return (run_records, journal, receipt_refs)."""
    data_hash = sha256_bytes(b"m2-accept-data")
    code_hash = sha256_bytes(b"m2-accept-code")
    records, rows, refs = [], [], []
    for condition_id, metrics in sorted(SEED_VALUES.items()):
        for seed, value in enumerate(metrics["Dice"]):
            job_id = f"job-{condition_id}-seed-{seed}"
            config_hash = sha256_bytes(f"config:{condition_id}:{seed}".encode("utf-8"))
            row = {"job_id": job_id, "row_id": f"{condition_id}-Dice-{seed}",
                   "condition_id": condition_id, "seed": seed, "metric": "Dice", "value": value}
            rows.append(row)
            records.append({"condition_id": condition_id, "status": "provisional",
                            "provenance": {"config_hash": config_hash, "data_hash": data_hash,
                                           "git_sha": code_hash, "seed": seed},
                            "metrics": {"Dice": value}})
            root = f"execution-results/{job_id}"
            argv = ["python", "run.py", "--condition", condition_id, "--seed", str(seed)]
            receipt = {
                "receipt_version": "executor-receipt/v1", "producer_kind": "non-llm-executor",
                "run_id": "run-m2", "job_id": job_id, "condition_id": condition_id, "seed": seed,
                "command": {"argv": argv,
                            "command_hash": sha256_bytes(canonical_json_bytes(argv))},
                "code_hash": code_hash, "config_hash": config_hash, "data_hash": data_hash,
                "exit_status": 0, "started_at": "2026-08-03T23:59:00Z", "finished_at": TS,
                "stdout": _execution_file(run_dir, f"{root}/stdout.log", "completed\n"),
                "stderr": _execution_file(run_dir, f"{root}/stderr.log", ""),
                "result_files": [{**_execution_file(
                    run_dir, f"{root}/raw-results.json",
                    json.dumps({"raw_result_rows": [row]}, sort_keys=True)),
                    "role": "raw_result_rows", "media_type": "application/json"}],
                "attestation": {"scheme": "ed25519", "key_id": EXECUTOR_KEY_ID, "signature": ""},
            }
            receipt["attestation"]["signature"] = "ed25519:" + base64.b64encode(
                EXECUTOR_PRIVATE_KEY.sign(receipt_attestation_message(receipt))).decode("ascii")
            ref = f"executor-receipts/{job_id}.json"
            path = run_dir / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
            refs.append(ref)
    journal = {"condition_id": "c1", "config_hash": sha256_bytes(b"config:c1:0"),
               "data_hash": data_hash, "git_sha": code_hash, "seed": 0,
               "designed_train": _pipeline(True), "designed_test": _pipeline(False),
               "actual_train": _pipeline(True), "actual_test": _pipeline(False),
               "metrics_snapshot": {"raw_result_rows": rows}}
    return records, journal, refs


def _write_execute_panel(run_dir, *, executed=False, records=None, journal=None, refs=None,
                         touched=None, parity_present=None) -> None:
    train, test = _scripts()
    _write(run_dir, "EXECUTE", "trainset-builder", {"train_script": train})
    _write(run_dir, "EXECUTE", "testset-builder", {"test_script": test})
    _write(run_dir, "EXECUTE", "variable-touch-guard", {"touch_report": {
        "touched_variables": ["lr", "epochs"] if touched is None else touched,
        "evidence": [{"variable": "lr", "where": "train script, optimizer construction"}],
        "guard_note": "Read both scripts end to end; only controlled variables are set."}})
    _write(run_dir, "EXECUTE", "preflight-checker", {"preflight_inputs": {
        "file_identity_manifests": [], "unresolved": [],
        "inspection_note": "No input file is reachable from this run directory, so no hash "
                           "manifest is claimed."}})
    if executed:
        real_records, real_journal, real_refs = _real_execution(Path(run_dir))
    else:
        real_records = [{"condition_id": condition_id, "status": "planned",
                         "provenance": {"config_hash": sha256_bytes(
                             f"planned:{condition_id}".encode("utf-8")),
                             "data_hash": None, "git_sha": None, "seed": 0},
                         "metrics": {}} for condition_id in ("c0", "c1")]
        real_journal, real_refs = None, []
    records = real_records if records is None else records
    journal = real_journal if journal is None else journal
    refs = real_refs if refs is None else refs
    _write(run_dir, "EXECUTE", "ablation-runner", {"execution_evidence": {
        "run_records": records, "executor_receipt_refs": refs,
        "evidence_boundary": ("Signed receipts cover every condition/seed pair." if refs
                              else "The run store is empty; nothing executed.")}})
    _write(run_dir, "EXECUTE", "experiment-journaler", {"journal_evidence": {"journal": journal}})
    present = (journal is not None) if parity_present is None else parity_present
    _write(run_dir, "EXECUTE", "train-test-parity-verifier", {"parity_claim": {
        "journal_present": present,
        "designed_vs_actual": ([{"field": "augmentation.enabled(test)", "designed": False,
                                 "actual": False, "matches": True}] if present else []),
        "unverifiable": [],
        "seat_summary": ("Compared every field the alignment contract names." if present else
                         "Nothing ran, so nothing can be compared.")}})


# --------------------------------------------------------------------------- ANALYZE / VERIFY

def _expected_evidence() -> tuple:
    per_seed = {cid: {"Dice": list(metrics["Dice"])} for cid, metrics in SEED_VALUES.items()}
    findings = [{"metric": "Dice", "value": fmean(SEED_VALUES["c1"]["Dice"]), "condition_id": "c1",
                 "baseline_value": fmean(SEED_VALUES["c0"]["Dice"]),
                 "baseline_condition_id": "c0"}]
    return findings, per_seed


def _write_analyze_panel(run_dir, *, executed=False, findings=None, per_seed=None,
                         independent=True, review_verdict="PASS", concerns=None) -> None:
    if executed:
        real_findings, real_per_seed = _expected_evidence()
    else:
        real_findings, real_per_seed = [], None
    _write(run_dir, "ANALYZE", "result-analyzer", {"analysis": {
        "candidate_findings": real_findings if findings is None else findings,
        "candidate_per_seed": real_per_seed if per_seed is None else per_seed,
        "interpretation": ("The LoRA adapter matches the full fine-tune on Dice within the "
                           "preregistered frame." if executed else
                           "Nothing has run. If executed, this design would show whether a LoRA "
                           "adapter matches the full fine-tune on Dice at equal budget."),
        "caveats": ["Bounded to fold0 and to the preregistered Dice comparison."],
        "claim_boundary": "Only the preregistered within-fold segmentation comparison is supported.",
        "next_experiment": "Repeat the paired comparison on an external held-out site."}})
    sanity = {"independent_of_analyzer": independent,
              "recomputed_from": ["evidence/EXECUTE/run-record-1.artifact.json",
                                  m2_accept.MATRIX_REF, m2_accept.PREREG_REF],
              "verdict": review_verdict, "concerns": concerns or [],
              "seat_summary": "Re-opened the committed records and matrix independently."}
    _write(run_dir, "ANALYZE", "result-sanity-checker", {"sanity_review": sanity})


def _write_verify_panel(run_dir, *, executed=False, independent=True, all_pass=None,
                        result_ready=None) -> None:
    passed = executed if all_pass is None else all_pass
    evidence = ("Opened the canonical artifacts and independently verified this check."
                if executed else "Not applicable: nothing ran, so there is no claim to refute.")
    _write(run_dir, "VERIFY", "adversarial-reviewer", {"adversarial_review": {
        "independent_of_analyzer": independent,
        "checks": {name: {"pass": passed, "evidence": evidence}
                   for name in m2_accept.REVIEW_CHECKS},
        "result_ready": passed if result_ready is None else result_ready,
        "refutation_attempts": [{"attempt": "Looked for test-set leakage through tuning",
                                 "outcome": "held", "detail": "Split frozen before any tuning."}],
        "claim_boundary": "No claim extends beyond the preregistered condition and metric.",
        "next_experiment": "Run the same protocol on the held-out external site."}})


def _drive(run_dir, stages=m2_accept.STAGES) -> dict:
    """Run each stage's deterministic half and assert every artifact it wrote is contract-valid."""
    reports = {}
    for stage in stages:
        paths, report = m2_accept.run_dets(str(run_dir), stage, TS)
        assert paths, f"{stage} produced no artifact"
        for path in paths:
            artifact = json.loads(Path(path).read_text(encoding="utf-8"))
            assert validate_artifact(artifact) == [], f"{stage} wrote an invalid artifact: {path}"
        reports[stage] = report
    return reports


def _report_text(run_dir) -> str:
    rel = _panel_recipe.target_markdown(MODE)["path"]
    path = Path(run_dir) / rel
    assert path.is_file(), f"the acceptance report was not written to {rel}"
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 1. happy paths

def test_scripts_only_happy_path_reports_a_plan_not_a_result(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=False)
    _write_analyze_panel(run_dir, executed=False)
    _write_verify_panel(run_dir, executed=False)

    reports = _drive(run_dir)

    assert reports["DESIGN"]["design_frozen"] is True
    assert reports["DESIGN"]["independent_design_audits"] == 3
    assert reports["EXECUTE"]["execution_state"] == "scripts-only"
    assert reports["EXECUTE"]["executed"] is False
    assert reports["EXECUTE"]["parity_gate"] == "SKIPPED(no real run)"
    assert reports["ANALYZE"]["result_summary_emitted"] is False
    assert reports["VERIFY"]["review_gate"] == "SKIPPED(scripts-only)"
    # No result artifact, and therefore no number, may exist in a plan-only run.
    assert not (Path(run_dir) / m2_accept.RESULT_REF).exists()
    assert not (Path(run_dir) / "evidence/VERIFY/review-report.artifact.json").exists()

    text = _report_text(run_dir)
    for section in _panel_recipe.target_markdown(MODE)["required_sections"]:
        assert f"## {section}" in text, f"missing required section {section!r}"
    assert "Did NOT run — this is a plan, not a result." in text
    assert "No result analysis exists." in text
    assert "NOT ready for an acceptance decision on results." in text


def test_real_run_happy_path_rebuilds_the_numbers_and_renders_the_report(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=True)
    _write_analyze_panel(run_dir, executed=True)
    _write_verify_panel(run_dir, executed=True)

    reports = _drive(run_dir)

    assert reports["EXECUTE"]["execution_state"] == "real-run"
    assert reports["EXECUTE"]["executed"] is True
    assert reports["EXECUTE"]["executor_receipts_verified"] == 6
    assert reports["ANALYZE"]["analysis_status"] == "REAL_RUN"
    assert reports["ANALYZE"]["raw_result_rows"] == 6
    assert reports["ANALYZE"]["sanity_gate"] == "PASS"
    assert reports["ANALYZE"]["stats_computed"] is True
    assert reports["VERIFY"]["review_gate"] == "APPROVE-FREEZE"

    result = json.loads((Path(run_dir) / m2_accept.RESULT_REF).read_text(encoding="utf-8"))
    findings, _per_seed = _expected_evidence()
    assert result["payload"]["findings"][0]["value"] == findings[0]["value"]

    text = _report_text(run_dir)
    for section in _panel_recipe.target_markdown(MODE)["required_sections"]:
        assert f"## {section}" in text
    assert "**Really ran.**" in text
    assert "APPROVE-FREEZE" in text
    # A run-store result is still not knowledge: the report must say so.
    assert "/promote-to-vault" in text


# --------------------------------------------------------------------------- 2. missing seat

def test_missing_seat_bundle_blocks_and_names_the_file(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    (Path(run_dir) / "inbox" / "DESIGN.metric-implementation-auditor.bundle.json").unlink()

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    assert "DESIGN.metric-implementation-auditor.bundle.json" in str(exc.value)


# --------------------------------------------------------------------------- 3. hard gate 1

def test_auditor_that_audited_another_design_is_blocked_by_name(tmp_path):
    """The headline gate: three audits are evidence only if they audited the SAME frozen design."""
    run_dir = _mk_run(tmp_path)
    design = _design()
    wrong = m2_accept._freeze_witness(design)
    wrong["condition_ids"] = wrong["condition_ids"] + ["c9"]
    _write_design_panel(run_dir, design=design, witness_override=wrong,
                        witness_for="train-test-alignment-auditor")

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    message = str(exc.value)
    assert "train-test-alignment-auditor" in message
    assert "ONE frozen protocol" in message


def test_compiler_that_edits_the_design_it_froze_is_blocked(tmp_path):
    run_dir = _mk_run(tmp_path)
    design = _design()
    edited = json.loads(json.dumps(design))
    edited["prereg"]["n_seeds_planned"] = 5  # a silent "improvement" during the freeze
    _write_design_panel(run_dir, design=design, frozen=edited)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    assert "not the planner's candidate_bundle verbatim" in str(exc.value)


def test_auditor_refusal_blocks_the_freeze(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir, verdicts={"variable-control-auditor": {
        "verdict": "REVISE",
        "blocking_concerns": ["lr moves with the adapter, so the contrast is confounded"]}})

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    assert "variable-control-auditor refuses the frozen design" in str(exc.value)


# --------------------------------------------------------------------------- 4. hard gate 2

def test_planned_run_record_carrying_a_metric_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    _write_execute_panel(run_dir, executed=False, records=[
        {"condition_id": "c0", "status": "planned",
         "provenance": {"config_hash": "sha256:" + "0" * 64, "seed": 0}, "metrics": {}},
        {"condition_id": "c1", "status": "planned",
         "provenance": {"config_hash": "sha256:" + "1" * 64, "seed": 0},
         "metrics": {"Dice": 0.81}}])

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "EXECUTE", TS)
    assert "planned run_record" in str(exc.value)
    assert "never numeric evidence" in str(exc.value)


def test_receipts_without_a_provisional_record_are_ambiguous_not_a_pass(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    _write_execute_panel(run_dir, executed=False, refs=["executor-receipts/job-c1-seed-0.json"])

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "EXECUTE", TS)
    assert "ambiguous" in str(exc.value)


def test_findings_without_an_execution_receipt_are_refused(tmp_path):
    """The honesty boundary itself: a number may not appear while `executed` is false."""
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=False)
    _drive(run_dir, ["DESIGN", "EXECUTE"])
    findings, per_seed = _expected_evidence()
    _write_analyze_panel(run_dir, executed=False, findings=findings, per_seed=per_seed)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "ANALYZE", TS)
    message = str(exc.value)
    assert "aggregate result findings" in message
    assert "scripts-only" in message
    assert not (Path(run_dir) / m2_accept.RESULT_REF).exists()


def test_analyst_findings_must_match_the_receipt_bound_rows(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=True)
    _drive(run_dir, ["DESIGN", "EXECUTE"])
    findings, per_seed = _expected_evidence()
    inflated = json.loads(json.dumps(findings))
    inflated[0]["value"] = 0.95  # a number no raw row supports
    _write_analyze_panel(run_dir, executed=True, findings=inflated, per_seed=per_seed)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "ANALYZE", TS)
    assert "does not match traceable execution evidence" in str(exc.value)


# --------------------------------------------------------------------------- 5. hard gate 3

def test_sanity_checker_must_declare_independence(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=False)
    _drive(run_dir, ["DESIGN", "EXECUTE"])
    _write_analyze_panel(run_dir, executed=False, independent=False)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "ANALYZE", TS)
    assert "may not also certify it" in str(exc.value)


def test_reviewer_may_not_author_result_numbers(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=False)
    _drive(run_dir, ["DESIGN", "EXECUTE"])
    _write_analyze_panel(run_dir, executed=False)
    path = Path(run_dir) / "inbox" / "ANALYZE.result-sanity-checker.bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["sanity_review"]["findings"] = [{"metric": "Dice", "value": 0.9, "condition_id": "c1"}]
    path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "ANALYZE", TS)
    assert "authored result field(s)" in str(exc.value)


def test_result_ready_cannot_be_self_declared(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=True)
    _write_analyze_panel(run_dir, executed=True)
    _drive(run_dir, ["DESIGN", "EXECUTE", "ANALYZE"])
    _write_verify_panel(run_dir, executed=True, all_pass=False, result_ready=True)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "VERIFY", TS)
    assert "never self-declared" in str(exc.value)


def test_a_plan_can_never_be_result_ready(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    _write_execute_panel(run_dir, executed=False)
    _write_analyze_panel(run_dir, executed=False)
    _drive(run_dir, ["DESIGN", "EXECUTE", "ANALYZE"])
    _write_verify_panel(run_dir, executed=False, result_ready=True)

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "VERIFY", TS)
    assert "no result to be ready" in str(exc.value)


# --------------------------------------------------------------------------- 6. touch guard

def test_build_touching_a_frozen_variable_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design_panel(run_dir)
    m2_accept.run_dets(str(run_dir), "DESIGN", TS)
    _write_execute_panel(run_dir, executed=False, touched=["lr", "backbone"])

    with pytest.raises(GateBlock) as exc:
        m2_accept.run_dets(str(run_dir), "EXECUTE", TS)
    assert "variable-touch BLOCK" in str(exc.value)
    assert "backbone" in str(exc.value)


# --------------------------------------------------------------------------- 7. contract

def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="has no stage"):
        m2_accept.run_dets(str(run_dir), "DISCOVER", TS)


def test_every_dispatched_seat_is_declared_and_writes_exactly_one_bundle(tmp_path):
    run_dir = _mk_run(tmp_path)
    declared = set(_panel_recipe.declared_seats(MODE))
    dispatched, outputs = [], []
    for stage in m2_accept.STAGES:
        # max_quality is now an explicit override, not the default — pass it, because the
        # invariant under test is "全 OPUS really puts EVERY seat on opus".
        step = m2_accept.llm_step(str(run_dir), stage, REQUEST, model_policy="max_quality")
        if stage == "REPORT":
            assert step is None, "REPORT must be deterministic and dispatch no worker"
            continue
        for worker in step["workers"]:
            assert worker["label"] in declared, f"{worker['label']} is not in the agent_subset"
            assert worker["model"] == "opus", "max_quality must put every seat on opus"
            dispatched.append(worker["label"])
            outputs.append(worker["output"])
        assert step["parallel_groups"], f"{stage} declared no dispatch waves"

    assert len(dispatched) == len(set(dispatched)), "a seat was dispatched twice"
    assert len(outputs) == len(set(outputs)), "two seats share one bundle path"
    # The registry's minimum_distinct_workers counts the deterministic renderer too; every other
    # declared seat must really be dispatched.
    assert set(dispatched) == declared
    assert m2_accept.STAGES == _panel_recipe.stage_path(MODE)


def test_no_dispatch_order_imposes_an_output_ceiling(tmp_path):
    """The 2026-08-03 regression guard: a cap phrasing silently shrinks a worker's output."""
    run_dir = _mk_run(tmp_path)
    for stage in ("DESIGN", "EXECUTE", "ANALYZE", "VERIFY"):
        for worker in m2_accept.llm_step(str(run_dir), stage, REQUEST)["workers"]:
            prompt, lowered = worker["prompt"], worker["prompt"].lower()
            for banned in ("at most", "最多", "up to a maximum", "no more than", "top n"):
                assert banned not in lowered, f"{worker['label']} prompt caps its own output: {banned}"
            assert "NORTH STAR" in prompt, f"{worker['label']} prompt lost the north star"
            for placeholder in ("{out}", "{north_star}", "{honesty}", "{matrix_ref}"):
                assert placeholder not in prompt, f"{worker['label']} prompt left {placeholder}"
            # protocol-compiler copies a frozen object verbatim, so it has nothing to enumerate.
            if worker["label"] != "protocol-compiler":
                assert "floor" in lowered, f"{worker['label']} states no output floor"
