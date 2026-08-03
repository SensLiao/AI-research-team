"""P0 acceptance tests for the operated ``full_rigor_minimal`` recipe.

The fixtures stand in for LLM workers and a lab runner.  All scientific gates,
panel composition, execution-evidence binding, statistics, and Markdown are the
real operated code paths.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import full_rigor_minimal as fr
from research_agent_teams.tools import full_rigor_markdown as full_rigor_md
from research_agent_teams.tools.full_rigor_markdown import (
    EXPERIMENT_PLAN_REL,
    RESULT_READINESS_REL,
    experiment_plan_path,
    result_readiness_path,
)
from research_agent_teams.tools.execution_receipt_import import (
    canonical_json_bytes,
    receipt_attestation_message,
    sha256_bytes,
    sha256_file,
    trust_public_key_env_name,
)
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.validate_artifact import validate_artifact


TS = "2026-06-13T00:00:00Z"
EXECUTOR_KEY_ID = "full-rigor-test-runner"
EXECUTOR_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"test-only-external-full-rigor-private-key").digest()
)
EXECUTOR_PUBLIC_KEY = EXECUTOR_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
PROFILE = "cv-medical-segmentation"
REQUEST = "compare a LoRA adapter against full fine-tune for 3D segmentation at equal budget"
NORTH_STAR = {
    "statement": REQUEST,
    "in_scope": ["LoRA adapter", "segmentation"],
    "out_of_scope": ["diffusion"],
}

PROFILE_METRICS = [
    "Dice",
    "IoU",
    "HD95",
    "clDice",
    "centerline_continuity",
    "topology_break_count",
    "small_structure_recall",
    "false_disconnection_rate",
]

PANELS = {
    "DESIGN": (
        "experiment-planner",
        "baseline-fairness-critic",
        "protocol-critic",
        "statistics-critic",
        "design-synthesizer",
    ),
    "EXECUTE": (
        "script-author",
        "execution-evidence-auditor",
        "execute-synthesizer",
    ),
    "ANALYZE": (
        "result-extractor",
        "statistician",
        "failure-attribution-skeptic",
        "analysis-synthesizer",
    ),
    "VERIFY": (
        "methodology-reviewer",
        "domain-reviewer",
        "adversarial-reviewer",
        "verify-synthesizer",
    ),
}


@pytest.fixture(autouse=True)
def _executor_trust_root(monkeypatch):
    monkeypatch.setenv(
        trust_public_key_env_name(EXECUTOR_KEY_ID),
        base64.b64encode(EXECUTOR_PUBLIC_KEY).decode("ascii"),
    )


def _all_metric_impls():
    impls = {
        metric: {
            "impl_ref": f"monai.{metric.lower()}",
            "spacing": None,
            "postprocess": None,
        }
        for metric in PROFILE_METRICS
    }
    return [
        {"condition_id": "c0", "metric_impls": impls},
        {"condition_id": "c1", "metric_impls": dict(impls)},
    ]


def _design_bundle(**over):
    rq = over.get("rq", "Does a LoRA adapter match full fine-tune at equal data budget on fold0?")
    conditions = over.get(
        "conditions",
        [
            {
                "id": "c0",
                "factors": {
                    "adapter": "none",
                    "lr": 1e-4,
                    "epochs": 50,
                    "backbone": "sam-vit-b",
                    "split": "fold0",
                },
                "baseline": True,
            },
            {
                "id": "c1",
                "factors": {
                    "adapter": "lora",
                    "lr": 1e-4,
                    "epochs": 50,
                    "backbone": "sam-vit-b",
                    "split": "fold0",
                },
            },
        ],
    )
    return {
        "design": {
            "rq": rq,
            "variables": {
                "studied": ["adapter"],
                "controlled": ["lr", "epochs"],
                "frozen": ["backbone", "split"],
            },
            "conditions": conditions,
            "ranked_batch": [
                {
                    "rank": 1,
                    "condition_id": "c1",
                    "hypothesis": "LoRA adapter matches full fine-tune at equal budget",
                }
            ],
            "leakage": "All inputs derive from training images only; test masks never read.",
        },
        "train": {
            "preprocessing": {"spacing": [1, 1, 1]},
            "augmentation": {"enabled": True},
            "pretrained": "none",
            "precision": "fp32",
            "inference": {"threshold": 0.5},
            "label_space": ["bg", "vessel"],
        },
        "test": {
            "preprocessing": {"spacing": [1, 1, 1]},
            "augmentation": {"enabled": False},
            "pretrained": "none",
            "precision": "fp32",
            "inference": {"threshold": 0.5},
            "label_space": ["bg", "vessel"],
        },
        "shared_config": {"optimizer": "adamw"},
        "metric_impls": over.get("metric_impls", _all_metric_impls()),
        "prereg": over.get(
            "prereg",
            {
                "primary_metric": "Dice",
                "secondary_metrics": [],
                "n_seeds_planned": 3,
                "stopping_rule": "fixed 3 seeds per condition",
                "analysis_plan": (
                    "paired permutation vs baseline on Dice, Holm-corrected, alpha=0.05"
                ),
            },
        ),
    }


def _execute_bundle(
    executed=False,
    *,
    values=None,
    extra_metrics=None,
    include_seed=True,
    **over,
):
    code_hash = sha256_bytes(b"full-rigor-test-code")
    data_hash = sha256_bytes(b"full-rigor-test-data")
    train_script = {
        "split": "train",
        "script": "def build_train():\n    return load('train')",
        "from_protocol_ref": "protocol_spec",
        "data_hash_expected": over.get("train_data_hash", "dh-train"),
    }
    test_script = {
        "split": "test",
        "script": "def build_test():\n    return load('test')",
        "from_protocol_ref": "protocol_spec",
        "data_hash_expected": over.get("test_data_hash", "dh-test"),
        "augmentation_enabled": False,
        "frozen": True,
    }
    if "test_data_hash" in over and over["test_data_hash"] is None:
        test_script["data_hash_expected"] = None

    if executed:
        metric_values = values or {
            "c0": {"Dice": [0.77, 0.78, 0.79]},
            "c1": {"Dice": [0.80, 0.81, 0.82]},
        }
        for metric, by_condition in (extra_metrics or {}).items():
            for condition_id, rows in by_condition.items():
                metric_values.setdefault(condition_id, {})[metric] = list(rows)

        run_records = []
        raw_rows = []
        for condition_id, metrics in sorted(metric_values.items()):
            n_rows = max(len(rows) for rows in metrics.values())
            for index in range(n_rows):
                seed = index if include_seed else None
                job_id = f"job-{condition_id}-seed-{seed}"
                config_hash = sha256_bytes(
                    f"config:{condition_id}:{seed}".encode("utf-8")
                )
                record_metrics = {}
                for metric, rows in sorted(metrics.items()):
                    value = rows[index]
                    record_metrics[metric] = value
                    raw_rows.append(
                        {
                            "job_id": job_id,
                            "condition_id": condition_id,
                            "seed": seed,
                            "metric": metric,
                            "value": value,
                            "row_id": f"{condition_id}-{metric}-{index}",
                        }
                    )
                run_records.append(
                    {
                        "condition_id": condition_id,
                        "status": "provisional",
                        "provenance": {
                            "config_hash": config_hash,
                            "data_hash": data_hash,
                            "git_sha": code_hash,
                            "seed": seed,
                        },
                        "metrics": record_metrics,
                    }
                )
        journal = {
            "condition_id": "c1",
            "config_hash": sha256_bytes(b"config:c1:0"),
            "data_hash": data_hash,
            "git_sha": code_hash,
            "seed": 0 if include_seed else None,
            "designed_train": _design_bundle()["train"],
            "designed_test": _design_bundle()["test"],
            "actual_train": _design_bundle()["train"],
            "actual_test": _design_bundle()["test"],
            "metrics_snapshot": {"raw_result_rows": raw_rows},
        }
    else:
        journal = None
        run_records = [
            {
                "condition_id": condition_id,
                "status": "planned",
                "provenance": {
                    "config_hash": sha256_bytes(f"planned:{condition_id}".encode("utf-8")),
                    "data_hash": data_hash,
                    "git_sha": code_hash,
                    "seed": 0,
                },
            }
            for condition_id in ("c0", "c1")
        ]

    journal = over.get("journal", journal)
    run_records = over.get("run_records", run_records)
    return {
        "train_script": train_script,
        "test_script": test_script,
        "file_identity_manifests": [],
        "journal": journal,
        "run_records": run_records,
        "executor_receipt_refs": over.get("executor_receipt_refs", []),
    }


def _analyze_bundle(**over):
    return {
        "findings": over.get(
            "findings",
            [
                {
                    "metric": "Dice",
                    "value": 0.81,
                    "condition_id": "c1",
                    "baseline_value": 0.78,
                    "baseline_condition_id": "c0",
                }
            ],
        ),
        "per_seed": over.get(
            "per_seed",
            {
                "c0": {"Dice": [0.77, 0.78, 0.79]},
                "c1": {"Dice": [0.80, 0.81, 0.82]},
            },
        ),
        "caveats": over.get("caveats", []),
        "failure_attribution": over.get(
            "failure_attribution",
            {
                "outcome": "inconclusive",
                "attribution": "unknown",
                "hypothesis_ref": f"{fr.MATRIX_REF}#ranked_batch/0",
                "attribution_state": "symptom_only",
                "implementation_valid": True,
                "data_valid": True,
                "evaluation_valid": True,
                "protocol_valid": True,
                "statistics_valid": False,
                "counterfactual_check": "not_tested",
                "replication_status": "not_attempted",
                "diagnostic_intervention": None,
                "replication_artifacts": [],
                "summary": "The effect is provisional; implementation and sampling alternatives remain.",
                "next_action_hint": "escalate",
            },
        ),
        "claim_boundary": over.get(
            "claim_boundary",
            "Only the preregistered within-fold comparison is supported; no external generalization claim.",
        ),
        "next_experiment": over.get(
            "next_experiment",
            "Repeat the paired comparison on the preregistered seeds and an external held-out site.",
        ),
    }


def _scripts_only_analysis_bundle(**over):
    return _analyze_bundle(findings=[], per_seed=None, **over)


def _verify_bundle(all_pass=True, result_ready=None):
    evidence = "opened canonical artifacts and independently verified this check" if all_pass else ""
    return {
        "checks": {
            name: {"pass": all_pass, "evidence": evidence}
            for name in ("leakage", "fairness", "eval_frame", "provenance", "overclaim")
        },
        "result_ready": all_pass if result_ready is None else result_ready,
        "claim_boundary": "No claim extends beyond the preregistered conditions and metric.",
        "next_experiment": "Run the same protocol on the held-out external site.",
    }


def _execution_file(run_dir: Path, relative: str, content: str) -> dict:
    path = run_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "path": relative.replace("\\", "/"),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _install_executor_receipts(run_dir, payload, *, signing_key=EXECUTOR_PRIVATE_KEY):
    run_path = Path(run_dir)
    task_frame = json.loads(
        (run_path / "task_frame.artifact.json").read_text(encoding="utf-8")
    )
    run_id = task_frame["payload"]["task_id"]
    journal_rows = ((payload.get("journal") or {}).get("metrics_snapshot") or {}).get(
        "raw_result_rows"
    ) or []
    refs = []
    for record in payload.get("run_records") or []:
        if record.get("status") != "provisional":
            continue
        provenance = record["provenance"]
        condition_id = record["condition_id"]
        seed = provenance.get("seed")
        selected = [
            row for row in journal_rows
            if row.get("condition_id") == condition_id and row.get("seed") == seed
        ]
        job_id = selected[0]["job_id"] if selected else f"job-{condition_id}-seed-{seed}"
        root = f"execution-results/{job_id}"
        stdout = _execution_file(run_path, f"{root}/stdout.log", "completed\n")
        stderr = _execution_file(run_path, f"{root}/stderr.log", "")
        result = _execution_file(
            run_path,
            f"{root}/raw-results.json",
            json.dumps({"raw_result_rows": selected}, sort_keys=True),
        )
        argv = ["python", "run.py", "--condition", condition_id, "--seed", str(seed)]
        receipt = {
            "receipt_version": "executor-receipt/v1",
            "producer_kind": "non-llm-executor",
            "run_id": run_id,
            "job_id": job_id,
            "condition_id": condition_id,
            "seed": seed,
            "command": {
                "argv": argv,
                "command_hash": sha256_bytes(canonical_json_bytes(argv)),
            },
            "code_hash": provenance["git_sha"],
            "config_hash": provenance["config_hash"],
            "data_hash": provenance["data_hash"],
            "exit_status": 0,
            "started_at": "2026-06-12T23:59:00Z",
            "finished_at": TS,
            "stdout": stdout,
            "stderr": stderr,
            "result_files": [{
                **result,
                "role": "raw_result_rows",
                "media_type": "application/json",
            }],
            "attestation": {
                "scheme": "ed25519",
                "key_id": EXECUTOR_KEY_ID,
                "signature": "ed25519:" + base64.b64encode(b"0" * 64).decode("ascii"),
            },
        }
        receipt["attestation"]["signature"] = "ed25519:" + base64.b64encode(
            signing_key.sign(receipt_attestation_message(receipt))
        ).decode("ascii")
        ref = f"executor-receipts/{job_id}.json"
        receipt_path = run_path / ref
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        refs.append(ref)
    payload["executor_receipt_refs"] = refs
    return refs


def _install_support_receipt(run_dir, payload, *, role: str, job_id: str, seed: int) -> dict:
    run_path = Path(run_dir)
    task_frame = json.loads(
        (run_path / "task_frame.artifact.json").read_text(encoding="utf-8")
    )
    root = f"execution-results/{job_id}"
    stdout = _execution_file(run_path, f"{root}/stdout.log", "completed\n")
    stderr = _execution_file(run_path, f"{root}/stderr.log", "")
    result = _execution_file(
        run_path,
        f"{root}/result.json",
        json.dumps({"job_id": job_id, "role": role, "verified": True}, sort_keys=True),
    )
    argv = ["python", "diagnostic.py", "--role", role, "--seed", str(seed)]
    receipt = {
        "receipt_version": "executor-receipt/v1",
        "producer_kind": "non-llm-executor",
        "run_id": task_frame["payload"]["task_id"],
        "job_id": job_id,
        "condition_id": f"{role}-c1",
        "seed": seed,
        "command": {
            "argv": argv,
            "command_hash": sha256_bytes(canonical_json_bytes(argv)),
        },
        "code_hash": sha256_bytes(b"diagnostic-code"),
        "config_hash": sha256_bytes(f"{role}-config".encode("utf-8")),
        "data_hash": sha256_bytes(b"full-rigor-test-data"),
        "exit_status": 0,
        "started_at": "2026-06-12T23:58:00Z",
        "finished_at": TS,
        "stdout": stdout,
        "stderr": stderr,
        "result_files": [{
            **result,
            "role": role,
            "media_type": "application/json",
        }],
        "attestation": {
            "scheme": "ed25519",
            "key_id": EXECUTOR_KEY_ID,
            "signature": "ed25519:" + base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    receipt["attestation"]["signature"] = "ed25519:" + base64.b64encode(
        EXECUTOR_PRIVATE_KEY.sign(receipt_attestation_message(receipt))
    ).decode("ascii")
    ref = f"executor-receipts/{job_id}.json"
    path = run_path / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    payload["executor_receipt_refs"].append(ref)
    return {"artifact_ref": result["path"], "sha256": result["sha256"]}


def _panel_payloads(stage, payload):
    seats = PANELS[stage]
    first_round = list(seats[:-1])
    if stage == "DESIGN":
        rows = {"experiment-planner": {"candidate_bundle": payload}}
        for seat in first_round[1:]:
            rows[seat] = {
                "assessment": {
                    "verdict": "PASS",
                    "blocking_concerns": [],
                    "recommendations": [f"{seat} independently found no blocking issue"],
                }
            }
        rows["design-synthesizer"] = {
            "source_seats": first_round,
            "resolution_log": [],
            "synthesized_bundle": payload,
        }
        return rows

    if stage == "EXECUTE":
        script_bundle = {
            key: payload[key]
            for key in ("train_script", "test_script", "file_identity_manifests")
        }
        execution_evidence = {
            key: payload[key]
            for key in ("journal", "run_records", "executor_receipt_refs")
        }
        return {
            "script-author": {"script_bundle": script_bundle},
            "execution-evidence-auditor": {
                "execution_evidence": execution_evidence,
                "assessment": {
                    "verdict": "PASS",
                    "blocking_concerns": [],
                    "evidence_boundary": (
                        "journal/run records are advisory; only signed executor receipts and "
                        "freshly hashed result files establish execution"
                    ),
                },
            },
            "execute-synthesizer": {
                "source_seats": first_round,
                "resolution_log": [],
                "synthesized_bundle": payload,
            },
        }

    if stage == "ANALYZE":
        failure = payload["failure_attribution"]
        return {
            "result-extractor": {
                "candidate_findings": payload["findings"],
                "evidence_refs": ["evidence/EXECUTE/run-record-*.artifact.json"],
            },
            "statistician": {
                "candidate_per_seed": payload["per_seed"],
                "assessment": {
                    "method": "paired permutation with Holm correction",
                    "uncertainty_limit": "Only paired recorded seeds are eligible.",
                },
            },
            "failure-attribution-skeptic": {
                "failure_attribution": failure,
                "alternative_explanations": ["sampling variance", "implementation drift"],
                "next_experiment": payload["next_experiment"],
                "claim_boundary": payload["claim_boundary"],
            },
            "analysis-synthesizer": {
                "source_seats": first_round,
                "resolution_log": [],
                "synthesized_bundle": {
                    "caveats": payload["caveats"],
                    "failure_attribution": failure,
                    "claim_boundary": payload["claim_boundary"],
                    "next_experiment": payload["next_experiment"],
                },
            },
        }

    if stage == "VERIFY":
        rows = {
            seat: {
                "checks": payload["checks"],
                "seat_summary": f"{seat} completed an independent review",
                "next_experiment": payload["next_experiment"],
            }
            for seat in first_round
        }
        rows["verify-synthesizer"] = {
            "source_seats": first_round,
            "checks": payload["checks"],
            "result_ready": payload["result_ready"],
            "claim_boundary": payload["claim_boundary"],
            "next_experiment": payload["next_experiment"],
        }
        return rows

    raise AssertionError(stage)


def _write_panel(run_dir, stage, payload, *, omit=None):
    inbox = Path(run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for seat, row in _panel_payloads(stage, payload).items():
        if seat == omit:
            continue
        (inbox / f"{stage}.{seat}.bundle.json").write_text(
            json.dumps(row), encoding="utf-8"
        )


def _validate_written(paths):
    for path in paths:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        assert validate_artifact(artifact) == [], f"artifact failed contract: {path}"


def _begin(runs, run_id, north_star=NORTH_STAR, profile=PROFILE):
    return spine.begin(
        str(runs),
        run_id,
        REQUEST,
        "full_rigor_minimal",
        TS,
        domain_profile_ref=profile,
        north_star=north_star,
    )


def _drive(run_dir, stage, payload=None):
    if payload is not None:
        if (
            stage == "EXECUTE"
            and any(row.get("status") == "provisional" for row in payload.get("run_records") or [])
            and not payload.get("executor_receipt_refs")
        ):
            _install_executor_receipts(run_dir, payload)
        _write_panel(run_dir, stage, payload)
    spine.open_stage(run_dir, stage, TS)
    paths, report = fr.run_dets(run_dir, stage, TS)
    result = spine.commit_stage(run_dir, stage, paths, TS)
    if result["gate"] == "director_signoff":
        spine.resolve_director_gate(
            run_dir,
            stage,
            "approved",
            TS,
            reason="test fixture simulates director approval",
        )
    return result, report, paths


def test_full_rigor_runs_end_to_end_with_evidence_bound_results(tmp_path):
    plan = _begin(tmp_path / "runs", "fr1")
    run_dir = plan["run_dir"]
    assert plan["stages"] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]

    _, design_report, design_paths = _drive(run_dir, "DESIGN", _design_bundle())
    assert design_report == {
        "vc_gate": "PASS",
        "metric_gate": "PASS",
        "alignment_gate": "PASS",
        "prereg_frozen": True,
        "n_conditions": 2,
    }
    _validate_written(design_paths)

    _, execute_report, execute_paths = _drive(
        run_dir, "EXECUTE", _execute_bundle(executed=True)
    )
    assert execute_report == {
        "preflight_gate": "PASS",
        "parity_gate": "PASS",
        "scripts_emitted": True,
        "executed": True,
        "executor_receipts_verified": 6,
    }
    _validate_written(execute_paths)

    _, analyze_report, analyze_paths = _drive(run_dir, "ANALYZE", _analyze_bundle())
    assert analyze_report["sanity_gate"] == "PASS"
    assert analyze_report["goal_alignment_gate"] == "PASS"
    assert analyze_report["prereg_deviation_gate"] == "PASS"
    assert analyze_report["stats_computed"] is True
    assert analyze_report["evidence_bound"] is True
    assert analyze_report["executor_receipts"] == 6
    _validate_written(analyze_paths)

    result = json.loads(
        (Path(run_dir) / "evidence" / "ANALYZE" / "result-summary.artifact.json").read_text()
    )["payload"]
    finding = result["findings"][0]
    assert finding["condition_id"] == "c1"
    assert finding["metric"] == "Dice"
    assert finding["value"] == pytest.approx(0.81)
    assert finding["baseline_value"] == pytest.approx(0.78)
    assert finding["delta"] == pytest.approx(0.03)
    assert finding["n_seeds"] == 3
    assert result["stats"]["n_findings_tested"] == 1
    assert (Path(run_dir) / "evidence" / "ANALYZE" / "failure-attribution.artifact.json").is_file()

    _, verify_report, verify_paths = _drive(run_dir, "VERIFY", _verify_bundle())
    assert verify_report["review_gate"] == "APPROVE-FREEZE"
    _validate_written(verify_paths)

    report_result, report, report_paths = _drive(run_dir, "REPORT")
    assert report_result["done"] is True
    _validate_written(report_paths)
    assert report["director_experiment_plan"].replace("\\", "/").endswith(
        EXPERIMENT_PLAN_REL.as_posix()
    )
    assert report["director_result_readiness"].replace("\\", "/").endswith(
        RESULT_READINESS_REL.as_posix()
    )

    plan_text = experiment_plan_path(run_dir).read_text(encoding="utf-8")
    result_text = result_readiness_path(run_dir).read_text(encoding="utf-8")
    assert "Status label: `real-run`" in plan_text
    for heading in (
        "## Result Snapshot",
        "## Effect Size And Uncertainty",
        "## Failure Attribution",
        "## Claim Boundary",
        "## Next Experiment",
    ):
        assert heading in result_text
    assert "absolute effect" in result_text
    assert "uncertainty" in result_text.lower()
    assert "sampling variance" in result_text
    assert "external held-out site" in result_text
    assert "Adversarial review verdict: `APPROVE-FREEZE`" in result_text
    assert "/promote-to-vault" in result_text

    note = json.loads(Path(report_paths[0]).read_text(encoding="utf-8"))["payload"]
    assert EXPERIMENT_PLAN_REL.as_posix() in note["references"]
    assert RESULT_READINESS_REL.as_posix() in note["references"]
    assert verify_chain(read_events(Path(run_dir) / "ledger.jsonl")) == []
    assert report_result["gate"] == "director_signoff"
    assert result["status"] == "provisional"
    assert result["can_cite_thesis"] is False


def test_experiment_plan_heading_alias_is_advisory_not_stage_block(
    tmp_path, monkeypatch
):
    run_dir = _begin(tmp_path / "runs", "fr-markdown-alias")["run_dir"]
    original_builder = full_rigor_md.build_experiment_plan_markdown

    def _aliased_builder(*args, **kwargs):
        return original_builder(*args, **kwargs).replace(
            "## Baselines And Conditions", "## Baselines & Conditions"
        )

    monkeypatch.setattr(
        full_rigor_md,
        "build_experiment_plan_markdown",
        _aliased_builder,
    )

    _result, report, _paths = _drive(run_dir, "DESIGN", _design_bundle())

    assert report["vc_gate"] == "PASS"
    assert "## Baselines & Conditions" in experiment_plan_path(run_dir).read_text(
        encoding="utf-8"
    )
    advisory = json.loads(
        (Path(run_dir) / "inbox" / "experiment-plan-markdown-quality-advisory.json")
        .read_text(encoding="utf-8")
    )
    assert advisory["delivery_blocking"] is False
    assert advisory["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert advisory["gate_ready"] is True
    assert "missing heading: ## Baselines And Conditions" in advisory["warnings"]


def test_experiment_plan_missing_scientific_inputs_remains_hard_block(tmp_path):
    with pytest.raises(ValueError, match="experiment-matrix artifact missing"):
        full_rigor_md.write_experiment_plan_markdown(tmp_path, generated_at=TS)

    assert not experiment_plan_path(tmp_path).exists()


def test_hidden_promotion_boundary_marks_result_gate_not_ready(
    tmp_path, monkeypatch
):
    run_dir = _begin(tmp_path / "runs", "fr-hidden-promotion-boundary")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True))
    original_builder = full_rigor_md.build_result_readiness_markdown

    def _hidden_boundary_builder(*args, **kwargs):
        return original_builder(*args, **kwargs).replace(
            "/promote-to-vault", "promotion command intentionally hidden"
        )

    monkeypatch.setattr(
        full_rigor_md,
        "build_result_readiness_markdown",
        _hidden_boundary_builder,
    )

    _result, report, _paths = _drive(run_dir, "ANALYZE", _analyze_bundle())

    assert report["evidence_bound"] is True
    advisory = json.loads(
        (Path(run_dir) / "inbox" / "result-readiness-markdown-quality-advisory.json")
        .read_text(encoding="utf-8")
    )
    assert advisory["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert advisory["delivery_blocking"] is False
    assert advisory["gate_ready"] is False
    assert advisory["gate_blockers"] == [
        "result/readiness brief must surface the promotion boundary"
    ]


def test_scripts_only_can_report_but_never_emits_result_readiness(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr2")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _, execute_report, _ = _drive(run_dir, "EXECUTE", _execute_bundle(executed=False))
    assert execute_report["executed"] is False
    assert execute_report["parity_gate"] == "SKIPPED(no real run)"

    _, analyze_report, analyze_paths = _drive(
        run_dir, "ANALYZE", _scripts_only_analysis_bundle()
    )
    assert analyze_report["result_summary_emitted"] is False
    assert analyze_report["analysis_status"] == "SKIPPED(scripts-only)"
    assert not (Path(run_dir) / "evidence" / "ANALYZE" / "result-summary.artifact.json").exists()
    _validate_written(analyze_paths)

    _, verify_report, verify_paths = _drive(
        run_dir, "VERIFY", _verify_bundle(result_ready=False)
    )
    assert verify_report["review_gate"] == "SKIPPED(scripts-only)"
    assert not (Path(run_dir) / "evidence" / "VERIFY" / "review-report.artifact.json").exists()
    _validate_written(verify_paths)

    stale_readiness = result_readiness_path(run_dir)
    stale_readiness.parent.mkdir(parents=True, exist_ok=True)
    stale_readiness.write_text("stale numeric readiness from an older renderer", encoding="utf-8")
    result, report, report_paths = _drive(run_dir, "REPORT")
    assert result["done"] is True
    assert "director_result_readiness" not in report
    assert experiment_plan_path(run_dir).is_file()
    assert not result_readiness_path(run_dir).exists()
    plan_text = experiment_plan_path(run_dir).read_text(encoding="utf-8")
    assert "Status label: `scripts-only`" in plan_text
    assert "experiment plan only" in plan_text.lower()
    assert "no metric claim is valid yet" in plan_text
    note = json.loads(Path(report_paths[0]).read_text(encoding="utf-8"))["payload"]
    assert note["references"] == [EXPERIMENT_PLAN_REL.as_posix()]
    assert "PROVISIONAL" not in note["summary"]


def test_scripts_only_skips_eight_result_workers_deterministically(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr2-fast")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=False))

    assert fr.llm_step(run_dir, "ANALYZE", REQUEST) is None
    for seat in PANELS["ANALYZE"]:
        assert (Path(run_dir) / "inbox" / f"ANALYZE.{seat}.bundle.json").is_file()
    _, analyze_report, _ = _drive(run_dir, "ANALYZE")
    assert analyze_report["analysis_status"] == "SKIPPED(scripts-only)"

    assert fr.llm_step(run_dir, "VERIFY", REQUEST) is None
    for seat in PANELS["VERIFY"]:
        assert (Path(run_dir) / "inbox" / f"VERIFY.{seat}.bundle.json").is_file()
    _, verify_report, _ = _drive(run_dir, "VERIFY")
    assert verify_report["review_gate"] == "SKIPPED(scripts-only)"


@pytest.mark.parametrize("journal_present", [False, True])
def test_scripts_only_or_all_planned_blocks_numeric_analysis(tmp_path, journal_present):
    run_dir = _begin(tmp_path / f"runs-{journal_present}", f"fr2-{journal_present}")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    execute = _execute_bundle(executed=False)
    if journal_present:
        execute["journal"] = _execute_bundle(executed=True)["journal"]
    _drive(run_dir, "EXECUTE", execute)

    _write_panel(run_dir, "ANALYZE", _analyze_bundle())
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="scripts-only.*numeric|numeric.*scripts-only"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    assert not (Path(run_dir) / "evidence" / "ANALYZE" / "result-summary.artifact.json").exists()
    assert not result_readiness_path(run_dir).exists()


def test_execute_without_journal_blocks_nonplanned_or_planned_metrics(tmp_path):
    for suffix, record in (
        (
            "provisional",
            {
                "condition_id": "c1",
                "status": "provisional",
                "provenance": {"config_hash": "cfg", "seed": 0},
                "metrics": {"Dice": 0.81},
            },
        ),
        (
            "planned-metric",
            {
                "condition_id": "c1",
                "status": "planned",
                "provenance": {"config_hash": "cfg", "seed": 0},
                "metrics": {"Dice": 0.81},
            },
        ),
    ):
        run_dir = _begin(tmp_path / suffix, f"fr-{suffix}")["run_dir"]
        _drive(run_dir, "DESIGN", _design_bundle())
        execute = _execute_bundle(executed=False, run_records=[record])
        _write_panel(run_dir, "EXECUTE", execute)
        spine.open_stage(run_dir, "EXECUTE", TS)
        with pytest.raises(GateBlock, match="no real run|planned run_record carries metrics"):
            fr.run_dets(run_dir, "EXECUTE", TS)


def test_analysis_rejects_model_number_not_in_execution_evidence(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr3")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True))
    fabricated = _analyze_bundle(
        findings=[
            {
                "metric": "Dice",
                "value": 0.99,
                "condition_id": "c1",
                "baseline_value": 0.78,
                "baseline_condition_id": "c0",
            }
        ]
    )
    _write_panel(run_dir, "ANALYZE", fabricated)
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="candidate finding.*execution evidence|trace"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    assert not (Path(run_dir) / "evidence" / "ANALYZE" / "result-summary.artifact.json").exists()


def test_analysis_requires_raw_rows_to_match_run_records(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr4")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    execute = _execute_bundle(executed=True)
    execute["journal"]["metrics_snapshot"]["raw_result_rows"][-1]["value"] = 0.50
    _drive(run_dir, "EXECUTE", execute)
    _write_panel(run_dir, "ANALYZE", _analyze_bundle())
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="raw result rows.*run_record|run_record.*raw result rows"):
        fr.run_dets(run_dir, "ANALYZE", TS)


def test_analysis_requires_primary_metric_for_every_declared_condition(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr5")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    execute = _execute_bundle(executed=True)
    execute["run_records"] = [
        row for row in execute["run_records"] if row["condition_id"] != "c0"
    ]
    execute["journal"]["metrics_snapshot"]["raw_result_rows"] = [
        row
        for row in execute["journal"]["metrics_snapshot"]["raw_result_rows"]
        if row["condition_id"] != "c0"
    ]
    _drive(run_dir, "EXECUTE", execute)
    _write_panel(run_dir, "ANALYZE", _analyze_bundle())
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="primary metric.*c0|c0.*primary metric"):
        fr.run_dets(run_dir, "ANALYZE", TS)


def test_variable_control_gate_blocks_confounded_design(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr6")["run_dir"]
    confounded = [
        {
            "id": "c0",
            "factors": {
                "adapter": "none",
                "lr": 1e-4,
                "epochs": 50,
                "backbone": "sam-vit-b",
                "split": "fold0",
            },
            "baseline": True,
        },
        {
            "id": "c1",
            "factors": {
                "adapter": "lora",
                "lr": 5e-4,
                "epochs": 50,
                "backbone": "sam-vit-b",
                "split": "fold0",
            },
        },
    ]
    _write_panel(run_dir, "DESIGN", _design_bundle(conditions=confounded))
    spine.open_stage(run_dir, "DESIGN", TS)
    with pytest.raises(GateBlock, match="confounded"):
        fr.run_dets(run_dir, "DESIGN", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "DESIGN" / "variable-control-report.artifact.json").read_text()
    )["payload"]
    assert verdict["verdict"] == "BLOCK"


def test_preflight_gate_blocks_missing_test_data_hash(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr7")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _write_panel(run_dir, "EXECUTE", _execute_bundle(test_data_hash=None))
    spine.open_stage(run_dir, "EXECUTE", TS)
    with pytest.raises(GateBlock, match="preflight"):
        fr.run_dets(run_dir, "EXECUTE", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "EXECUTE" / "preflight-report.artifact.json").read_text()
    )["payload"]
    assert verdict["verdict"] == "BLOCK"


def test_sanity_gate_still_blocks_out_of_range_execution_value(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr8")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    values = {
        "c0": {"Dice": [0.77, 0.78, 0.79]},
        "c1": {"Dice": [1.5, 1.5, 1.5]},
    }
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True, values=values))
    bad_analysis = _analyze_bundle(
        findings=[
            {
                "metric": "Dice",
                "value": 1.5,
                "condition_id": "c1",
                "baseline_value": 0.78,
                "baseline_condition_id": "c0",
            }
        ],
        per_seed={
            "c0": {"Dice": [0.77, 0.78, 0.79]},
            "c1": {"Dice": [1.5, 1.5, 1.5]},
        },
    )
    _write_panel(run_dir, "ANALYZE", bad_analysis)
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="sanity"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "ANALYZE" / "sanity-verdict.artifact.json").read_text()
    )["payload"]
    assert verdict["verdict"] == "BLOCK"
    assert verdict["out_of_range"] == ["Dice"]


def test_goal_alignment_gate_still_blocks_unsupported_generalization(tmp_path):
    north_star = {
        "statement": "show the LoRA adapter generalizes across segmentation sites",
        "in_scope": ["LoRA adapter", "segmentation"],
        "out_of_scope": ["diffusion"],
    }
    run_dir = spine.begin(
        str(tmp_path / "runs"),
        "fr9",
        "show the LoRA adapter generalizes across segmentation sites",
        "full_rigor_minimal",
        TS,
        domain_profile_ref=PROFILE,
        north_star=north_star,
    )["run_dir"]
    rq = "Does the LoRA adapter generalize to a new segmentation site at equal budget?"
    _drive(run_dir, "DESIGN", _design_bundle(rq=rq))
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True))
    _write_panel(run_dir, "ANALYZE", _analyze_bundle())
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="goal-alignment"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "ANALYZE" / "goal-alignment-verdict.artifact.json").read_text()
    )["payload"]
    assert verdict["pass"] is False


def test_prereg_gate_still_blocks_evidence_bound_outcome_switching(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr10")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    extra = {"IoU": {"c0": [0.69, 0.70, 0.71], "c1": [0.73, 0.74, 0.75]}}
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True, extra_metrics=extra))
    analysis = _analyze_bundle(
        findings=[
            {
                "metric": "Dice",
                "value": 0.81,
                "condition_id": "c1",
                "baseline_value": 0.78,
                "baseline_condition_id": "c0",
            },
            {
                "metric": "IoU",
                "value": 0.74,
                "condition_id": "c1",
                "baseline_value": 0.70,
                "baseline_condition_id": "c0",
            },
        ],
        per_seed={
            "c0": {"Dice": [0.77, 0.78, 0.79], "IoU": [0.69, 0.70, 0.71]},
            "c1": {"Dice": [0.80, 0.81, 0.82], "IoU": [0.73, 0.74, 0.75]},
        },
    )
    _write_panel(run_dir, "ANALYZE", analysis)
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="prereg-deviation"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "ANALYZE" / "prereg-deviation-verdict.artifact.json").read_text()
    )["payload"]
    assert any("IoU" in violation for violation in verdict["violations"])


def test_missing_panel_seat_blocks_stage(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr11")["run_dir"]
    _write_panel(
        run_dir,
        "DESIGN",
        _design_bundle(),
        omit="statistics-critic",
    )
    spine.open_stage(run_dir, "DESIGN", TS)
    with pytest.raises(GateBlock, match="statistics-critic"):
        fr.run_dets(run_dir, "DESIGN", TS)


def test_drift_gate_blocks_out_of_scope_topic_in_synthesized_design(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr12")["run_dir"]
    rq = "Does a diffusion adapter beat the LoRA adapter at equal budget on segmentation?"
    _write_panel(run_dir, "DESIGN", _design_bundle(rq=rq))
    spine.open_stage(run_dir, "DESIGN", TS)
    with pytest.raises(GateBlock, match="drift"):
        fr.run_dets(run_dir, "DESIGN", TS)
    verdict = json.loads(
        (Path(run_dir) / "evidence" / "DESIGN" / "drift-verdict.artifact.json").read_text()
    )["payload"]
    assert verdict["pass"] is False


def test_coherent_llm_journal_and_run_records_without_receipt_are_blocked(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr-no-receipt")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    coherent = _execute_bundle(executed=True)
    _write_panel(run_dir, "EXECUTE", coherent)
    spine.open_stage(run_dir, "EXECUTE", TS)
    with pytest.raises(GateBlock, match="executor receipt|at least one executor receipt"):
        fr.run_dets(run_dir, "EXECUTE", TS)
    assert not (Path(run_dir) / "evidence/EXECUTE/execution-import.artifact.json").exists()


def test_llm_forged_executor_receipt_with_wrong_attestation_is_blocked(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr-forged-receipt")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    forged = _execute_bundle(executed=True)
    attacker_key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"llm-attacker-private-key").digest()
    )
    _install_executor_receipts(run_dir, forged, signing_key=attacker_key)
    _write_panel(run_dir, "EXECUTE", forged)
    spine.open_stage(run_dir, "EXECUTE", TS)
    with pytest.raises(GateBlock, match="attestation failed"):
        fr.run_dets(run_dir, "EXECUTE", TS)


def test_result_file_tampering_after_execute_invalidates_analysis(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr-tampered-result")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True))
    result_path = Path(run_dir) / "execution-results/job-c1-seed-0/raw-results.json"
    result_path.write_text(
        json.dumps({"raw_result_rows": [{"value": 0.99}]}), encoding="utf-8"
    )
    _write_panel(run_dir, "ANALYZE", _analyze_bundle())
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="invalid-execution-evidence|hash mismatch|size mismatch"):
        fr.run_dets(run_dir, "ANALYZE", TS)


def test_self_reported_intervention_confirmation_is_blocked(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr-self-attribution")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    _drive(run_dir, "EXECUTE", _execute_bundle(executed=True))
    attribution = {
        **_analyze_bundle()["failure_attribution"],
        "attribution": "implementation",
        "attribution_state": "intervention_confirmed",
        "replication_status": "replicated",
        "diagnostic_intervention": {
            "artifact_ref": "execution-results/invented/diagnostic.json",
            "sha256": "sha256:" + "a" * 64,
        },
        "replication_artifacts": [{
            "artifact_ref": "execution-results/invented/replication.json",
            "sha256": "sha256:" + "b" * 64,
        }],
    }
    _write_panel(run_dir, "ANALYZE", _analyze_bundle(failure_attribution=attribution))
    spine.open_stage(run_dir, "ANALYZE", TS)
    with pytest.raises(GateBlock, match="not present in the verified executor import"):
        fr.run_dets(run_dir, "ANALYZE", TS)
    assert not (Path(run_dir) / "evidence/ANALYZE/failure-attribution.artifact.json").exists()


def test_hypothesis_attribution_accepts_only_receipt_bound_diagnostic_and_replication(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr-bound-attribution")["run_dir"]
    _drive(run_dir, "DESIGN", _design_bundle())
    execute = _execute_bundle(executed=True)
    _install_executor_receipts(run_dir, execute)
    diagnostic = _install_support_receipt(
        run_dir,
        execute,
        role="diagnostic_intervention",
        job_id="job-diagnostic-c1",
        seed=100,
    )
    replication = _install_support_receipt(
        run_dir,
        execute,
        role="replication_evidence",
        job_id="job-replication-c1",
        seed=101,
    )
    _drive(run_dir, "EXECUTE", execute)
    attribution = {
        **_analyze_bundle()["failure_attribution"],
        "outcome": "regressed",
        "attribution": "hypothesis",
        "attribution_state": "intervention_confirmed",
        "statistics_valid": True,
        "replication_status": "replicated",
        "diagnostic_intervention": diagnostic,
        "replication_artifacts": [replication],
        "next_action_hint": "revise_hypothesis",
    }
    _, report, _ = _drive(
        run_dir, "ANALYZE", _analyze_bundle(failure_attribution=attribution)
    )
    assert report["evidence_bound"] is True
    feedback = json.loads(
        (Path(run_dir) / "evidence/ANALYZE/failure-attribution.artifact.json").read_text()
    )["payload"]
    assert feedback["hypothesis_ref"] == f"{fr.MATRIX_REF}#ranked_batch/0"
    assert feedback["diagnostic_intervention"] == diagnostic
    assert feedback["replication_artifacts"] == [replication]


def test_llm_panels_have_blind_first_round_and_synthesis_only_aggregation(tmp_path):
    run_dir = _begin(tmp_path / "runs", "fr13")["run_dir"]
    for stage, expected_seats in PANELS.items():
        panel = fr.llm_step(run_dir, stage, REQUEST, model_policy="default")
        assert panel["worker_order"] == list(expected_seats)
        assert panel["parallel_groups"] == [list(expected_seats[:-1]), [expected_seats[-1]]]
        workers = panel["workers"]
        assert [worker["label"] for worker in workers] == list(expected_seats)
        first_round = workers[:-1]
        synthesizer = workers[-1]

        for worker in first_round:
            assert worker["output"].endswith(
                f"inbox/{stage}.{worker['label']}.bundle.json"
            )
            assert "do not read any sibling" in worker["prompt"].lower()
            for peer in first_round:
                if peer is not worker:
                    assert peer["output"] not in worker["prompt"]
            for marker in ("NORTH STAR", "HONESTY", "REPAIR ATTEMPT"):
                assert marker in worker["prompt"]

        for worker in first_round:
            assert worker["output"] in synthesizer["prompt"]
        assert "ONLY seat allowed to read" in synthesizer["prompt"]
        assert synthesizer["model"] == "opus"

    execute_panel = fr.llm_step(run_dir, "EXECUTE", REQUEST, model_policy="default")
    assert execute_panel["workers"][0]["model"] == "sonnet"
    analyze_panel = fr.llm_step(run_dir, "ANALYZE", REQUEST, model_policy="default")
    assert analyze_panel["workers"][0]["model"] == "sonnet"
    max_quality = fr.llm_step(run_dir, "ANALYZE", REQUEST, model_policy="max_quality")
    assert all(worker["model"] == "opus" for worker in max_quality["workers"])
    assert fr.llm_step(run_dir, "REPORT", REQUEST) is None
