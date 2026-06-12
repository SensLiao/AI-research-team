"""Operate recipe for the `full_rigor_minimal` mode (DESIGN->EXECUTE->ANALYZE->VERIFY->REPORT).

The M2 spine slice — the machine's highest-rigor chain — wired into the one-button operate layer
(audit B1). It is the operated twin of tests/test_m2_spine_slice.py: the SAME deterministic cores
and hard gates, driven stage-by-stage with real LLM workers in the WORK slot instead of one opaque
agent_fn. Division of labour, per stage:

  - LLM workers (sub-agents) do the design reasoning / script authoring / finding extraction that a
    deterministic tool cannot. Each worker prompt carries the north-star block, the COMPLETE bundle
    JSON shape, an HONESTY clause (never fabricate a slug / number / run), and a REPAIR clause.
  - Deterministic cores do EVERY gate (never an LLM): variable-control + metric-impl + alignment +
    preregistration (DESIGN), preflight + train-test-parity (EXECUTE), result-sanity +
    goal-alignment + prereg-deviation (ANALYZE), adversarial-review (VERIFY), and the north-star
    drift gate at every stage boundary. A BLOCK writes its verdict artifact (so the refusal is
    auditable) and raises GateBlock — the run halts at that stage, never reaching the next.

Cross-stage state: the CLI drives each stage as an INDEPENDENT process, so there is NO in-memory
carry between stages. A stage that needs an upstream product re-reads it from
`evidence/<UPSTREAM>/<name>.artifact.json` (the checkpointed, contract-valid artifact) — the same
single source of truth the ledger pins.

Honesty boundary (the EXECUTE gate): a `journal == null` bundle is the truthful "scripts emitted but
the experiment did NOT run on a GPU" path — every run_record must then be status 'planned' (a
provisional record with metrics but no journal is a self-claim of a run that never happened, and
BLOCKs). A real journal unlocks the parity gate and lets run_records be 'provisional'. A result
stays 'provisional' until the human `/promote-to-vault` gate re-derives it — this recipe never
freezes a number.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

from .. import bounded_repair
from . import _shared
from ..artifacts import GateBlock, write_artifact
from ...tools import prereg as prereg_tool
from ...tools.alignment_checker import build_report as alignment_build
from ...tools.compare_metric_impls import build_report as metric_build
from ...tools.experiment_planner import build_matrix
from ...tools.goal_alignment_audit import build_verdict as goal_alignment_build
from ...tools.preflight_checker import build_report as preflight_build
from ...tools.protocol_compiler import compile_protocol
from ...tools.result_analyzer import build_result_summary, build_result_summary_with_stats
from ...tools.review_checker import build_report as review_build
from ...tools.sanity_checker import build_report as sanity_build
from ...tools.variable_control_checker import build_report as vc_build

STAGES = ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

# Cross-stage artifact references (run-relative; the canonical names the spine slice checkpoints).
MATRIX_REF = "evidence/DESIGN/experiment-matrix.artifact.json"
PROTOCOL_REF = "evidence/DESIGN/protocol-spec.artifact.json"
ALIGNMENT_REF = "evidence/DESIGN/alignment-report.artifact.json"
PREREG_REF = "evidence/DESIGN/preregistration.artifact.json"


# --------------------------------------------------------------------------- worker prompts (LLM WORK)

_HONESTY = ("HONESTY (hard): never invent a slug / DOI / metric number / run that did not happen; a "
            "result is 'provisional' until the human /promote gate, never frozen here; distinguish "
            "PLANNED (scripts emitted, not executed) from PROVISIONAL (really ran on a GPU). If this "
            "prompt carries a REPAIR ATTEMPT block, fix EXACTLY what the gate names, change nothing "
            "else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).")

_DESIGN_PROMPT = """You are the DESIGN worker of a full-rigor experiment run, for the request:

    REQUEST: {request}

{north_star_block}

Design ONE clean comparison: a research question, the studied/controlled/frozen variable split, a
baseline + treatment condition that isolate exactly the studied variable, a ranked next-run batch, a
leakage declaration, the train + test pipeline facts, the per-condition metric implementations, and
the PREREGISTRATION that freezes what you will measure and how (before any number exists).

{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "design": {{"rq":"<research question>",
     "variables":{{"studied":["<v>"],"controlled":["<v>"],"frozen":["<v>"]}},
     "conditions":[{{"id":"c0","factors":{{"<factor>":"<val>"}},"baseline":true}},
                   {{"id":"c1","factors":{{"<factor>":"<val>"}}}}],
     "ranked_batch":[{{"rank":1,"condition_id":"c1","hypothesis":"<falsifiable hypothesis>"}}],
     "leakage":"<explicit leakage-safety statement>"}},
  "train": {{"preprocessing":{{...}},"augmentation":{{"enabled":true}},"pretrained":"none|<ckpt>",
     "precision":"fp32","inference":{{"threshold":0.5}},"label_space":["bg","fg"]}},
  "test": {{"preprocessing":{{...}},"augmentation":{{"enabled":false}},"pretrained":"none|<ckpt>",
     "precision":"fp32","inference":{{"threshold":0.5}},"label_space":["bg","fg"]}},
  "shared_config": {{"optimizer":"adamw"}},
  "metric_impls": [{{"condition_id":"c0","metric_impls":{{"Dice":{{"impl_ref":"<ref>","spacing":null,
       "postprocess":null}}}}}},
                   {{"condition_id":"c1","metric_impls":{{"Dice":{{"impl_ref":"<ref>","spacing":null,
       "postprocess":null}}}}}}],
  "prereg": {{"primary_metric":"Dice","secondary_metrics":[],"n_seeds_planned":3,
     "stopping_rule":"fixed 3 seeds per condition","analysis_plan":"paired permutation vs baseline on \
the primary metric, Holm-corrected, alpha=0.05"}}
}}
Quantities: exactly ONE baseline; ranks contiguous 1..N; metric_impls IDENTICAL across conditions \
(same impl_ref/spacing/postprocess) or the metric gate BLOCKs; test augmentation MUST be disabled. \
After writing, verify valid JSON. Return one line: rq + #conditions + primary_metric."""

_EXECUTE_PROMPT = """You are the EXECUTE worker of a full-rigor run, for the request:

    REQUEST: {request}

{north_star_block}

Emit the REAL runnable dataset-construction scripts (code, not prose) for the frozen design, and
record each condition's run. CRITICAL honesty fork:
  - If the experiment did NOT actually run on a GPU (the usual case here — no in-machine executor):
    set `journal` to null and make EVERY run_record status "planned" (scripts emitted, not executed).
  - If a real run happened: provide the journal (designed vs actual pipeline facts) and run_records
    may be "provisional" with metrics.

{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "train_script": {{"split":"train","script":"def build_train():\\n    return load('train')",
     "from_protocol_ref":"protocol_spec","data_hash_expected":"<hash>"}},
  "test_script": {{"split":"test","script":"def build_test():\\n    return load('test')",
     "from_protocol_ref":"protocol_spec","data_hash_expected":"<hash>",
     "augmentation_enabled":false,"frozen":true}},
  "journal": null,
  "run_records": [{{"condition_id":"c1","status":"planned",
     "provenance":{{"config_hash":"<hash>","data_hash":"<hash>","seed":<int>}}}}]
}}
(For a REAL run, journal = {{"condition_id":"c1","config_hash":"<h>","designed_train":{{...}},
"designed_test":{{...}},"actual_train":{{...}},"actual_test":{{...}},"metrics_snapshot":{{...}}}} and a
run_record may be "provisional" with "metrics".) After writing, verify valid JSON. Return one line: \
scripts emitted + executed(yes/no) + #run_records."""

_ANALYZE_PROMPT = """You are the ANALYZE worker of a full-rigor run, for the request:

    REQUEST: {request}

{north_star_block}

Report the findings the run produced — ONLY metrics you preregistered, ONLY conditions you declared
(an undeclared metric/condition is outcome-switching and will BLOCK; put exploratory numbers in
`caveats` prose). If you have PER-SEED values for a condition and its baseline, include them so a
real paired significance test can run; otherwise omit per_seed and the report will state "no
significance computed".

{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "findings": [{{"metric":"Dice","value":0.81,"condition_id":"c1","baseline_value":0.78,
     "baseline_condition_id":"c0"}}],
  "per_seed": {{"c1":{{"Dice":[0.80,0.81,0.82]}},"c0":{{"Dice":[0.77,0.78,0.79]}}}},
  "caveats": ["<any honest caveat>"]
}}
(Set per_seed to null when you have no per-seed data.) After writing, verify valid JSON. Return one \
line: #findings + stats(yes/no) + primary-metric value."""

_VERIFY_PROMPT = """You are the adversarial VERIFY reviewer of a full-rigor run, for the request:

    REQUEST: {request}

{north_star_block}

Try to REFUTE the result before it can be trusted, across five checks. For EACH, investigate (open
the eval code / data pipeline read-only) and report {{pass, evidence}} — a claimed pass with no
evidence is treated as not-defensible (default-to-BLOCK under uncertainty).

{honesty}

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "checks": {{
    "leakage":    {{"pass":true,"evidence":"<what you verified>"}},
    "fairness":   {{"pass":true,"evidence":"<...>"}},
    "eval_frame": {{"pass":true,"evidence":"<...>"}},
    "provenance": {{"pass":true,"evidence":"<...>"}},
    "overclaim":  {{"pass":true,"evidence":"<...>"}}
  }}
}}
After writing, verify valid JSON. Return one line: which checks pass + any blocking reason."""


# --------------------------------------------------------------------------- seed + cross-stage reads

def _run_id(run_dir) -> str:
    return str(_shared.task_frame(run_dir)["payload"].get("task_id") or Path(run_dir).name)


def _seed(run_dir) -> int:
    """A deterministic per-run seed derived from the run_id (no wall clock) — threaded into the
    permutation / bootstrap RNGs so the same run yields byte-identical statistics."""
    return int(hashlib.sha256(_run_id(run_dir).encode("utf-8")).hexdigest()[:8], 16)


def _read_payload(run_dir, ref: str) -> dict:
    """Read an upstream artifact's payload from its run-relative path (the cross-stage carry).
    A missing upstream artifact is a readable GateBlock (the stage was driven out of order)."""
    p = Path(run_dir) / ref
    if not p.is_file():
        raise GateBlock(
            f"full_rigor: required upstream artifact {ref} is missing — the producing stage must "
            "complete (and checkpoint) before this stage runs")
    return json.loads(p.read_text(encoding="utf-8"))["payload"]


def _direction_anchor(run_dir) -> List[str]:
    """The run's direction-bearing text (the frozen DESIGN research_question + hypotheses) that a
    downstream stage carries into its drift check. EXECUTE/ANALYZE/VERIFY emit thin, code-shaped
    output (condition ids, metric names) that holds no north-star vocabulary on its own; pairing it
    with the rq the stage is SERVING lets the drift gate's zero-coverage rule judge real direction
    (a stage executing the run's rq is on-direction), while its out-of-scope-topic rule still fires
    on any injected off-direction term in the stage's own output."""
    try:
        matrix = _read_payload(run_dir, MATRIX_REF)
    except GateBlock:
        return []
    bits = [str(matrix.get("research_question") or "")]
    bits += [str(r.get("hypothesis") or "") for r in (matrix.get("ranked_batch") or [])]
    return [b for b in bits if b]


# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The single LLM worker to dispatch for a stage (REPORT is deterministic -> None).

    Tier: max_quality -> all-opus; default -> task-appropriate (DESIGN = the heavy judgment, opus;
    EXECUTE script authoring + ANALYZE extraction = sonnet; VERIFY adversarial review = opus)."""
    prompts = {"DESIGN": _DESIGN_PROMPT, "EXECUTE": _EXECUTE_PROMPT,
               "ANALYZE": _ANALYZE_PROMPT, "VERIFY": _VERIFY_PROMPT}
    if stage not in prompts:
        return None
    out = f"{run_dir}/inbox/{stage}.bundle.json"
    if model_policy == "max_quality":
        model = "opus"
    else:
        model = "sonnet" if stage in ("EXECUTE", "ANALYZE") else "opus"
    labels = {"DESIGN": "design-worker", "EXECUTE": "execute-worker",
              "ANALYZE": "analyze-worker", "VERIFY": "adversarial-reviewer"}
    return {"label": labels[stage], "model": model, "output": out,
            "prompt": prompts[stage].format(
                request=request, north_star_block=_shared.north_star_block(run_dir),
                honesty=_HONESTY, out=out)}


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- DESIGN

def _design_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ["design", "train", "test", "shared_config", "metric_impls",
                                    "prereg"], stage="DESIGN", mode="full_rigor_minimal")
    prof = _shared.domain_profile(run_dir)
    paths: List[str] = []
    d = b["design"]
    try:
        matrix = build_matrix(d["rq"], d["variables"], d["conditions"], d["ranked_batch"], d["leakage"])
    except ValueError as e:  # design-hygiene guard (e.g. zero/two baselines, bad ranks) -> readable gate
        raise GateBlock(f"experiment-matrix design-hygiene BLOCK: {e}")

    vc = vc_build(matrix, profile=prof)                                      # HARD GATE 1
    paths.append(write_artifact(run_dir, "DESIGN", "variable-control-report.artifact.json",
                                "variable_control_report", "variable-control-auditor", vc, ts,
                                "blocked" if vc["verdict"] == "BLOCK" else "approved"))
    if vc["verdict"] == "BLOCK":
        raise GateBlock(f"variable-control BLOCK: {vc['violations']}")

    mi = metric_build(b["metric_impls"], profile=prof)                       # HARD GATE 2
    paths.append(write_artifact(run_dir, "DESIGN", "metric-impl-report.artifact.json",
                                "metric_impl_report", "metric-implementation-auditor", mi, ts,
                                "blocked" if mi["verdict"] == "BLOCK" else "approved"))
    if mi["verdict"] == "BLOCK":
        raise GateBlock(f"metric-impl BLOCK: {mi['violations']}")

    proto = compile_protocol(matrix, from_matrix_ref=MATRIX_REF, shared=b["shared_config"],
                             seed=_seed(run_dir))
    paths.append(write_artifact(run_dir, "DESIGN", "protocol-spec.artifact.json",
                                "protocol_spec", "protocol-compiler", proto, ts))

    al = alignment_build(b["train"], b["test"], profile=prof,                # HARD GATE 3
                         train_ref="train-pipeline", test_ref="test-pipeline")
    paths.append(write_artifact(run_dir, "DESIGN", "alignment-report.artifact.json",
                                "alignment_report", "train-test-alignment-auditor", al, ts,
                                "blocked" if al["verdict"] == "BLOCK" else "approved"))
    if al["verdict"] == "BLOCK":
        raise GateBlock(f"alignment BLOCK: {al['violations']}")

    try:                                                                     # HARD GATE 4 (freeze)
        prereg_payload = prereg_tool.build_prereg(matrix, **b["prereg"])
    except ValueError as e:  # an unfrozen analysis contract is fail-loud -> readable gate
        raise GateBlock(f"preregistration BLOCK (analysis contract not frozen): {e}")
    paths.append(write_artifact(run_dir, "DESIGN", "preregistration.artifact.json",
                                "preregistration", "experiment-planner", prereg_payload, ts))

    # north-star drift gate over the run's substantive design vocabulary (rq + hypotheses + ids)
    drift_texts = [d["rq"]]
    drift_texts += [str(r.get("hypothesis") or "") for r in matrix["ranked_batch"]]
    drift_texts += [str(c.get("id") or "") for c in matrix["conditions"]]
    dpath, _f = _shared.run_drift_gate(run_dir, "DESIGN", ts, drift_texts)
    paths.append(dpath)

    paths.append(write_artifact(run_dir, "DESIGN", "experiment-matrix.artifact.json",   # exit
                                "experiment_matrix", "experiment-planner", matrix, ts))
    report = {"vc_gate": vc["verdict"], "metric_gate": mi["verdict"], "alignment_gate": al["verdict"],
              "prereg_frozen": True, "n_conditions": len(matrix["conditions"])}
    return paths, report


# --------------------------------------------------------------------------- EXECUTE

def _execute_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ["train_script", "test_script", "journal", "run_records"],
                                stage="EXECUTE", mode="full_rigor_minimal")
    prof = _shared.domain_profile(run_dir)
    paths: List[str] = []

    # 1. dataset scripts (schema self-checks: test must be frozen + augmentation off)
    paths.append(write_artifact(run_dir, "EXECUTE", "trainset-script.artifact.json",
                                "dataset_script_record", "trainset-builder", b["train_script"], ts))
    paths.append(write_artifact(run_dir, "EXECUTE", "testset-script.artifact.json",
                                "dataset_script_record", "testset-builder", b["test_script"], ts))

    # 2. preflight (reads the DESIGN protocol + alignment payloads — the cross-stage carry)
    protocol = _read_payload(run_dir, PROTOCOL_REF)
    alignment = _read_payload(run_dir, ALIGNMENT_REF)
    pf = preflight_build(b["train_script"], b["test_script"], protocol, alignment,   # HARD GATE 1
                         profile=prof, protocol_ref=PROTOCOL_REF, alignment_ref=ALIGNMENT_REF)
    paths.append(write_artifact(run_dir, "EXECUTE", "preflight-report.artifact.json",
                                "preflight_report", "preflight-checker", pf, ts,
                                "blocked" if pf["verdict"] == "BLOCK" else "approved"))
    if pf["verdict"] == "BLOCK":
        raise GateBlock(f"preflight BLOCK: {pf['violations']}")

    journal = b["journal"]
    run_records = b["run_records"] or []
    if journal is None:
        # Honest "scripts emitted, NOT executed" path: no journal == no real run == no real metrics.
        # Every run_record must be planned; a provisional record (esp. with metrics) is a self-claim
        # of a run that never happened -> BLOCK. Parity is SKIPPED (nothing ran to re-verify).
        for rr in run_records:
            if rr.get("status") != "planned":
                raise GateBlock(
                    "no journal = no real run = no metrics: run_record "
                    f"{rr.get('condition_id')!r} is {rr.get('status')!r}, but without a journal "
                    "every run_record must be 'planned' (scripts emitted, the experiment did not run)")
        parity_label = "SKIPPED(no real run)"
        executed = False
    else:
        # Real run: journal artifact + parity gate; run_records may be provisional.
        paths.append(write_artifact(run_dir, "EXECUTE", "journal-entry.artifact.json",
                                    "journal_entry", "experiment-journaler", journal, ts))
        from ...tools.parity_checker import build_report as parity_build         # HARD GATE 2
        pv = parity_build(journal, alignment, profile=prof,
                          journal_ref="journal_entry", alignment_ref=ALIGNMENT_REF)
        paths.append(write_artifact(run_dir, "EXECUTE", "parity-verdict.artifact.json",
                                    "parity_verdict", "train-test-parity-verifier", pv, ts,
                                    "blocked" if pv["verdict"] == "BLOCK" else "approved"))
        if pv["verdict"] == "BLOCK":
            raise GateBlock(f"parity BLOCK: {pv['violations']}")
        parity_label = "PASS"
        executed = True

    # 3. run_record artifacts (condition_id + notes feed the drift gate; the script CODE body does not)
    drift_texts: List[str] = list(_direction_anchor(run_dir))   # the rq this run is serving
    for i, rr in enumerate(run_records):
        paths.append(write_artifact(run_dir, "EXECUTE", f"run-record-{i + 1}.artifact.json",
                                    "run_record", "ablation-runner", rr, ts))
        drift_texts.append(str(rr.get("condition_id") or ""))
        if rr.get("notes"):
            drift_texts.append(str(rr["notes"]))
    dpath, _f = _shared.run_drift_gate(run_dir, "EXECUTE", ts, drift_texts)
    paths.append(dpath)

    report = {"preflight_gate": pf["verdict"], "parity_gate": parity_label,
              "scripts_emitted": True, "executed": executed}
    return paths, report


# --------------------------------------------------------------------------- ANALYZE

def _analyze_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ["findings", "per_seed", "caveats"],
                                stage="ANALYZE", mode="full_rigor_minimal")
    prof = _shared.domain_profile(run_dir)
    paths: List[str] = []
    findings = b["findings"] or []
    caveats = list(b["caveats"] or [])
    per_seed = b["per_seed"]

    if per_seed:
        rs = build_result_summary_with_stats(findings, per_seed, seed=_seed(run_dir), caveats=caveats)
        stats_computed = bool(rs.get("stats", {}).get("n_findings_tested"))
    else:
        rs = build_result_summary(findings,
                                  caveats=caveats + ["no significance computed — no per-seed data"])
        stats_computed = False

    sv = sanity_build(rs, profile=prof)                                      # HARD GATE 1
    paths.append(write_artifact(run_dir, "ANALYZE", "sanity-verdict.artifact.json",
                                "sanity_verdict", "result-sanity-checker", sv, ts,
                                "blocked" if sv["verdict"] == "BLOCK" else "approved"))
    if sv["verdict"] == "BLOCK":
        raise GateBlock(f"sanity BLOCK: {sv['violations']}")

    matrix = _read_payload(run_dir, MATRIX_REF)
    ga = goal_alignment_build(matrix, rs, profile=prof)                      # HARD GATE 2 (audit W2)
    paths.append(write_artifact(run_dir, "ANALYZE", "goal-alignment-verdict.artifact.json",
                                "analysis_check_verdict", "goal-alignment-checker", ga, ts,
                                "blocked" if not ga["pass"] else "approved"))
    if not ga["pass"]:
        raise GateBlock(f"goal-alignment BLOCK: {ga['violations']}")

    prereg_payload = _read_payload(run_dir, PREREG_REF)
    dv = prereg_tool.build_deviation_verdict(prereg_payload, rs)             # HARD GATE 3 (outcome-switch)
    paths.append(write_artifact(run_dir, "ANALYZE", "prereg-deviation-verdict.artifact.json",
                                "analysis_check_verdict", "compliance-auditor", dv, ts,
                                "blocked" if not dv["pass"] else "approved"))
    if not dv["pass"]:
        raise GateBlock(f"prereg-deviation BLOCK: {dv['violations']}")

    # drift gate over the run's direction (rq) + the findings' metric/condition vocabulary + caveats
    drift_texts: List[str] = [str(matrix.get("research_question") or "")]
    drift_texts += [str(r.get("hypothesis") or "") for r in (matrix.get("ranked_batch") or [])]
    for f in findings:
        drift_texts.append(str(f.get("metric") or ""))
        drift_texts.append(str(f.get("condition_id") or ""))
    drift_texts += [str(c) for c in caveats]
    dpath, _f = _shared.run_drift_gate(run_dir, "ANALYZE", ts, drift_texts)
    paths.append(dpath)

    paths.append(write_artifact(run_dir, "ANALYZE", "result-summary.artifact.json",   # exit
                                "result_summary", "result-analyzer", rs, ts))
    report = {"sanity_gate": sv["verdict"], "goal_alignment_gate": "PASS" if ga["pass"] else "BLOCK",
              "prereg_deviation_gate": "PASS" if dv["pass"] else "BLOCK",
              "stats_computed": stats_computed}
    return paths, report


# --------------------------------------------------------------------------- VERIFY

def _verify_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ["checks"], stage="VERIFY", mode="full_rigor_minimal")
    paths: List[str] = []
    review = review_build(b["checks"])                                       # HARD GATE
    paths.append(write_artifact(run_dir, "VERIFY", "review-report.artifact.json",
                                "review_report", "adversarial-reviewer", review, ts,
                                "blocked" if review["verdict"] == "BLOCK" else "approved"))
    if review["verdict"] == "BLOCK":
        raise GateBlock(f"adversarial-review BLOCK: {review['blocking_reasons']}")

    drift_texts = list(_direction_anchor(run_dir))      # the rq this review is judging
    drift_texts.append(str(review["verdict"]))
    for name, c in (b["checks"] or {}).items():
        drift_texts.append(str(name))
        if isinstance(c, dict) and c.get("evidence"):
            drift_texts.append(str(c["evidence"]))
    dpath, _f = _shared.run_drift_gate(run_dir, "VERIFY", ts, drift_texts)
    paths.append(dpath)
    return paths, {"review_gate": review["verdict"]}


# --------------------------------------------------------------------------- REPORT

def _report(run_dir, ts) -> tuple:
    # Honest executed-vs-scripts-only distinction, read from the EXECUTE run-record statuses.
    executed = _was_executed(run_dir)
    ran = ("the experiment really ran (journal present)" if executed
           else "scripts were emitted but the experiment did NOT run on a GPU (run_records 'planned')")
    note = {"summary": f"full_rigor_minimal complete: {ran}. Every DESIGN/EXECUTE/ANALYZE/VERIFY hard "
                       "gate passed. The result stays PROVISIONAL until the human /promote-to-vault "
                       "gate re-derives it — this run never freezes a number.",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def _was_executed(run_dir) -> bool:
    """True iff the EXECUTE stage recorded a real journal (any run_record is 'provisional')."""
    return (Path(run_dir) / "evidence" / "EXECUTE" / "journal-entry.artifact.json").is_file()


# --------------------------------------------------------------------------- dispatch

def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock when a
    hard gate refuses (the run halts; the stage is NOT committed; the next stage is never reached)."""
    if stage == "DESIGN":
        return _design_dets(run_dir, ts, _load_bundle(run_dir, "DESIGN"))
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts, _load_bundle(run_dir, "EXECUTE"))
    if stage == "ANALYZE":
        return _analyze_dets(run_dir, ts, _load_bundle(run_dir, "ANALYZE"))
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts, _load_bundle(run_dir, "VERIFY"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"full_rigor_minimal has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop around a stage's hard gates: ("ok", (paths, report)) or
    ("retry", feedback) when blocked and the budget allows another in-stage attempt; re-raises the
    original GateBlock when the repair cap is reached (director escalation)."""
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts))
