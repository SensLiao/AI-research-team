"""Blind first-round worker panels for ``full_rigor_minimal``."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..artifacts import GateBlock
from . import _shared


PANEL_SPECS = {
    "DESIGN": {
        "first": (
            "experiment-planner",
            "baseline-fairness-critic",
            "protocol-critic",
            "statistics-critic",
        ),
        "synth": "design-synthesizer",
    },
    "EXECUTE": {
        "first": ("script-author", "execution-evidence-auditor"),
        "synth": "execute-synthesizer",
    },
    "ANALYZE": {
        "first": ("result-extractor", "statistician", "failure-attribution-skeptic"),
        "synth": "analysis-synthesizer",
    },
    "VERIFY": {
        "first": ("methodology-reviewer", "domain-reviewer", "adversarial-reviewer"),
        "synth": "verify-synthesizer",
    },
}

_HONESTY = (
    "HONESTY (hard): never invent a slug, DOI, metric number, raw row, journal, or run. "
    "PLANNED means scripts emitted but not executed; PROVISIONAL requires persisted execution "
    "evidence and remains non-citable until /promote-to-vault. If this prompt carries a REPAIR "
    "ATTEMPT block, repair exactly the named defect and re-emit the complete bundle."
)


def bundle_path(run_dir, stage: str, seat: str) -> Path:
    return Path(run_dir) / "inbox" / f"{stage}.{seat}.bundle.json"


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _worker_model(model_policy: str, seat: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    if seat in {"script-author", "result-extractor"}:
        return "sonnet"
    return "opus"


def _blind_prompt(run_dir: str, stage: str, seat: str, request: str, out: str) -> str:
    role_tasks = {
        "experiment-planner": (
            "Independently propose one clean baseline/treatment experiment. Output "
            '{"candidate_bundle": {"design":...,"train":...,"test":...,"shared_config":...,'
            '"metric_impls":...,"prereg":...}}. The design needs exactly one baseline, isolated '
            "studied variables, frozen controls, runnable pipelines, identical metric implementations, "
            "and a preregistered primary metric, seed count, stopping rule, and analysis plan."
        ),
        "baseline-fairness-critic": (
            "Independently identify baseline fairness, confounding, leakage, and comparison risks. "
            'Output {"assessment":{"verdict":"PASS|REVISE","blocking_concerns":[],'
            '"recommendations":[]}}.'
        ),
        "protocol-critic": (
            "Independently audit train/test parity, split freezing, preprocessing, inference, label "
            'space, and reproducibility requirements. Output {"assessment":{"verdict":"PASS|REVISE",'
            '"blocking_concerns":[],"recommendations":[]}}.'
        ),
        "statistics-critic": (
            "Independently audit the primary outcome, seed plan, pairing, uncertainty, multiplicity, "
            'stopping rule, and failure criteria. Output {"assessment":{"verdict":"PASS|REVISE",'
            '"blocking_concerns":[],"recommendations":[]}}.'
        ),
        "script-author": (
            "Read only committed DESIGN artifacts and author runnable train/test dataset scripts. "
            'Output {"script_bundle":{"train_script":...,"test_script":...,'
            '"file_identity_manifests":[]}}. Do not claim execution.'
        ),
        "execution-evidence-auditor": (
            "Independently inspect the actual run store. If nothing ran, emit journal null, only "
            "planned records without metrics, and no receipt refs. If it ran, preserve the journal, "
            "provisional per-condition/per-seed run records, and point to receipts already deposited "
            "by the non-LLM executor under executor-receipts/. Never paste, author, sign, or repair a "
            "receipt. Output "
            '{"execution_evidence":{"journal":...,"run_records":[],"executor_receipt_refs":[]},'
            '"assessment":'
            '{"verdict":"PASS|BLOCK","blocking_concerns":[],"evidence_boundary":"..."}}.'
        ),
        "result-extractor": (
            "Read only committed DESIGN/EXECUTE artifacts. Extract candidate aggregate findings from "
            "raw rows and run records, or an empty list for scripts-only. Output "
            '{"candidate_findings":[],"evidence_refs":[]}. Every numeric candidate must carry '
            "condition_id, metric, value, and baseline fields when applicable."
        ),
        "statistician": (
            "Read only committed DESIGN/EXECUTE artifacts and preregistration. Reconstruct eligible "
            "per-seed vectors, or null for scripts-only/unpaired evidence. Output "
            '{"candidate_per_seed":null,"assessment":{"method":"...",'
            '"uncertainty_limit":"..."}}. Do not invent p-values or confidence intervals.'
        ),
        "failure-attribution-skeptic": (
            "Independently seek implementation, environment, data, evaluation, protocol, statistics, "
            "and hypothesis explanations. Never attribute a failure to the hypothesis unless all five "
            "validity flags are true and a valid replication still refutes it. "
            'Output {"failure_attribution":{"hypothesis_ref":"evidence/DESIGN/'
            'experiment-matrix.artifact.json#ranked_batch/N",'
            '"outcome":"improved|regressed|inconclusive|failed",'
            '"attribution":"hypothesis|implementation|environment|data|evaluation|protocol|statistics|inconclusive|unknown",'
            '"attribution_state":"symptom_only|associated|reproduced|intervention_confirmed|counterfactually_supported",'
            '"implementation_valid":true,"data_valid":true,"evaluation_valid":true,'
            '"protocol_valid":true,"statistics_valid":true,'
            '"counterfactual_check":"not_tested|supports|does_not_support|inconclusive",'
            '"replication_status":"not_attempted|failed_to_reproduce|reproduced_once|replicated",'
            '"diagnostic_intervention":null|{"artifact_ref":"...","sha256":"sha256:..."},'
            '"replication_artifacts":[]|[{"artifact_ref":"...","sha256":"sha256:..."}],'
            '"summary":"...","next_action_hint":"revise_hypothesis|fix_implementation|fix_environment|fix_data|fix_evaluation|fix_protocol|increase_precision|run_diagnostic|escalate|stop"},'
            '"alternative_explanations":[],"claim_boundary":"...","next_experiment":"..."}.'
        ),
        "methodology-reviewer": (
            "Independently try to refute the result from experimental-method and statistical-design "
            "angles. Output all five checks leakage/fairness/eval_frame/provenance/overclaim as "
            '{pass,evidence}, plus seat_summary and next_experiment.'
        ),
        "domain-reviewer": (
            "Independently review domain validity, metric interpretation, clinically/task-relevant "
            "failure modes, and claim scope. Output all five checks as {pass,evidence}, plus "
            "seat_summary and next_experiment."
        ),
        "adversarial-reviewer": (
            "Independently assume the claim is wrong and seek leakage, unfair baselines, evaluation "
            "frame errors, provenance gaps, and overclaim. Output all five checks as {pass,evidence}, "
            "plus seat_summary and next_experiment."
        ),
    }
    return f"""You are `{seat}`, a FIRST-ROUND INDEPENDENT seat in full_rigor_minimal {stage}.

REQUEST: {request}

{_shared.north_star_block(run_dir)}

Independence rule: do not read any sibling worker bundle or another first-round answer. You may read
only the pinned request and committed artifacts from earlier stages. Your diversity must be real.

{role_tasks[seat]}

{_HONESTY}

Write ONLY valid JSON to `{out}`.
"""


def _synthesis_prompt(run_dir: str, stage: str, seat: str, request: str, out: str,
                      first_paths: list[str]) -> str:
    inputs = "\n".join(f"- `{path}`" for path in first_paths)
    tasks = {
        "DESIGN": (
            "Resolve every critic concern and emit {source_seats,resolution_log,synthesized_bundle}. "
            "synthesized_bundle must have design/train/test/shared_config/metric_impls/prereg."
        ),
        "EXECUTE": (
            "Emit {source_seats,resolution_log,synthesized_bundle}. Copy scripts exactly from the "
            "script author and journal/run_records/executor_receipt_refs exactly from the evidence "
            "auditor; never create, sign, or alter execution evidence."
        ),
        "ANALYZE": (
            "Emit {source_seats,resolution_log,synthesized_bundle}. The synthesized bundle may contain "
            "only caveats, failure_attribution, claim_boundary, and next_experiment. It must not contain "
            "findings, per_seed, p-values, effects, or any other result number; deterministic code owns them."
        ),
        "VERIFY": (
            "Emit {source_seats,checks,result_ready,claim_boundary,next_experiment}. A synthesized check "
            "may pass only when every independent seat passed it; preserve disagreements and evidence."
        ),
    }
    return f"""You are `{seat}`, the ONLY seat allowed to read and aggregate same-stage answers.

REQUEST: {request}

{_shared.north_star_block(run_dir)}

Read every first-round bundle before writing:
{inputs}

{tasks[stage]}

{_HONESTY}

Write ONLY valid JSON to `{out}`.
"""


def llm_step(run_dir: str, stage: str, request: str, vault: Optional[str] = None,
             model_policy: str = "max_quality") -> Optional[dict]:
    del vault
    spec = PANEL_SPECS.get(stage)
    if spec is None:
        return None
    first = list(spec["first"])
    synth = str(spec["synth"])
    workers = []
    for seat in first:
        out = _posix(bundle_path(run_dir, stage, seat))
        workers.append({
            "label": seat,
            "model": _worker_model(model_policy, seat),
            "output": out,
            "prompt": _blind_prompt(run_dir, stage, seat, request, out),
        })
    synth_out = _posix(bundle_path(run_dir, stage, synth))
    workers.append({
        "label": synth,
        "model": _worker_model(model_policy, synth),
        "output": synth_out,
        "prompt": _synthesis_prompt(
            run_dir, stage, synth, request, synth_out, [worker["output"] for worker in workers]
        ),
    })
    order = [*first, synth]
    return {
        "label": f"full-rigor-{stage.lower()}-panel",
        "workers": workers,
        "worker_order": order,
        "parallel_groups": [first, [synth]],
        "panel_note": (
            "Spawn the first group in parallel with sibling-bundle access disabled; spawn the "
            "synthesizer only after every first-round bundle exists."
        ),
    }


def load_panel(run_dir, stage: str) -> dict[str, dict]:
    spec = PANEL_SPECS[stage]
    seats = [*spec["first"], spec["synth"]]
    bundles: dict[str, dict] = {}
    missing = []
    for seat in seats:
        path = bundle_path(run_dir, stage, seat)
        if not path.is_file():
            missing.append(seat)
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise GateBlock(f"{stage} panel bundle for {seat} is invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise GateBlock(f"{stage} panel bundle for {seat} must be a JSON object")
        bundles[seat] = value
    if missing:
        raise GateBlock(
            f"{stage} panel missing worker bundle(s): {missing}; every independent seat and the "
            "synthesizer are required"
        )
    return bundles


__all__ = ["PANEL_SPECS", "bundle_path", "llm_step", "load_panel"]
