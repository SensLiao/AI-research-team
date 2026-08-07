"""Operate recipe for the `m2_accept` mode (DESIGN -> EXECUTE -> ANALYZE -> VERIFY -> REPORT).

The acceptance product of the experiment tail: freeze a design, hand it to the external executor,
then report — in one director-facing Markdown — whether the experiment ACTUALLY ran, what it found,
and which acceptance conditions passed. The registry's own productization gap for this mode is
"distinguishes planned, attempted, and completed execution", so that distinction is the module's
spine rather than a caveat bolted onto the end.

Composition, not a second copy. `full_rigor_minimal` already owns the deterministic experiment tail,
so every scientific decision here is delegated:

  * the planned/attempted/completed classifier is the ONE canonical
    `tools.full_rigor_execution_truth.execution_state`, reached through
    `_panel_recipe.execution_truth` / `refuse_metrics_without_receipt` / `execution_boundary_section`;
  * numbers come from `derive_numeric_evidence` (attested executor receipts -> raw rows -> run
    records), never from a worker, and the analyst's candidates are cross-checked with
    `full_rigor_minimal`'s own `_candidate_findings_match` / `_candidate_per_seed_match`;
  * every verdict (variable control, metric impls, alignment, preflight, touch guard, parity,
    sanity, adversarial review) is a `tools/*` builder that derives PASS/BLOCK from violations.

What this module genuinely owns is what a spec cannot supply: the 15 hand-written dispatch orders for
THIS mode's roster (`full_rigor_minimal`'s seats are a different roster and are not dispatchable here),
the three mode-specific hard gates below, and the deterministic acceptance-report renderer.

Mode-specific hard gates (each has a test that really trips it):

  1. **One frozen protocol, three independent audits of THAT protocol.** `protocol-compiler` must
     copy the planner's bundle verbatim into `frozen_design` (any edit BLOCKs — a compiler that
     re-authors the design has un-frozen it), and each of the three DESIGN auditors must echo a
     freeze witness (condition ids + studied variables + primary metric) that matches the frozen
     design exactly. An auditor that audited something else is named and BLOCKed. The witness is a
     copied content fingerprint, not model arithmetic: deterministic code owns the sha256 record, so
     an LLM is never asked to hash and no gate depends on its ability to.
  2. **No metric without a receipt.** Planned run records may carry no metrics, a missing journal
     forces every record to `planned`, receipts without provisional records are ambiguous, and any
     numeric claim while `executed` is false is refused outright.
  3. **No self-certification.** `result-analyzer` produces; `result-sanity-checker` and
     `adversarial-reviewer` review, each declaring independence and re-opening the committed
     artifacts. A reviewer may not author result numbers, and `result_ready` is derived from the five
     independent checks rather than self-declared.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

from . import _panel_recipe, _shared, full_rigor_minimal as fr
from ..artifacts import GateBlock, write_artifact
from ...tools import prereg as prereg_tool
from ...tools import variable_touch_guard
from ...tools.alignment_checker import build_report as alignment_build
from ...tools.alignment_checker import detect_zero_training
from ...tools.compare_metric_impls import build_report as metric_build
from ...tools.execution_receipt_import import (
    ExecutionReceiptError,
    IMPORT_ARTIFACT_REL,
    build_execution_import,
    canonical_json_bytes,
    import_note_payload,
    validate_records_against_import,
)
from ...tools.experiment_planner import build_matrix
from ...tools.full_rigor_execution_truth import ExecutionTruthError, derive_numeric_evidence
from ...tools.parity_checker import build_report as parity_build
from ...tools.preflight_checker import build_report as preflight_build
from ...tools.protocol_compiler import compile_protocol
from ...tools.result_analyzer import build_result_summary, build_result_summary_with_stats
from ...tools.review_checker import build_report as review_build
from ...tools.sanity_checker import build_report as sanity_build
from ...tools.variable_control_checker import build_report as vc_build

MODE = "m2_accept"
STAGES = ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

#: Upstream artifact refs are `full_rigor_minimal`'s — same evidence layout, one set of constants.
MATRIX_REF = fr.MATRIX_REF
PROTOCOL_REF = fr.PROTOCOL_REF
ALIGNMENT_REF = fr.ALIGNMENT_REF
PREREG_REF = fr.PREREG_REF
FREEZE_REF = "evidence/DESIGN/design-freeze.artifact.json"
RESULT_REF = "evidence/ANALYZE/result-summary.artifact.json"

REVIEW_CHECKS = fr.REVIEW_CHECKS

_HONESTY = (
    "HONESTY (hard, never relaxed): invent nothing — no slug, DOI, metric number, raw result row, "
    "journal, receipt, or run. `planned` means scripts exist and nothing executed; `provisional` "
    "requires persisted executor evidence and stays non-citable until /promote-to-vault. Thin "
    "evidence is reported as thin, never padded. If this prompt carries a REPAIR ATTEMPT block, fix "
    "EXACTLY what the gate named, change nothing else, re-emit the COMPLETE bundle, and never argue "
    "with the gate or relax this paragraph to satisfy it."
)


# --------------------------------------------------------------------------- DESIGN dispatch orders

PLANNER_PROMPT = """You are `experiment-planner`, the only seat in m2_accept DESIGN that AUTHORS the \
experiment. You design; you never audit your own design and never claim anything ran.

REQUEST: {request}

{north_star}

Read, by reference: the run's task frame, the active domain profile's metric list, and any committed
artifact from an earlier stage of this run. Design ONE clean comparison: exactly one baseline
condition, the studied variable isolated, every other variable either controlled or frozen, runnable
train/test pipelines whose only intended difference is the studied variable, one metric implementation
per metric reused identically across conditions, and a preregistered analysis contract.

Write ONLY this JSON to `{out}`:
{{"candidate_bundle": {{
  "design": {{"rq": "<the atomic question this experiment answers>",
    "variables": {{"studied": ["<the one thing under test>"], "controlled": ["<explorable>"],
                  "frozen": ["<must not move>"]}},
    "conditions": [{{"id": "c0", "factors": {{"<factor>": "<value>"}}, "baseline": true}},
                   {{"id": "c1", "factors": {{"<factor>": "<value>"}}}}],
    "ranked_batch": [{{"rank": 1, "condition_id": "c1", "hypothesis": "<falsifiable prediction>"}}],
    "leakage": "<explicit written statement of why no test information reaches training>"}},
  "train": {{"preprocessing": {{}}, "augmentation": {{"enabled": true}}, "pretrained": "<ref|none>",
            "precision": "<fp32|amp|...>", "inference": {{}}, "label_space": ["<label>"]}},
  "test": {{"preprocessing": {{}}, "augmentation": {{"enabled": false}}, "pretrained": "<ref|none>",
           "precision": "<same as train unless justified>", "inference": {{}}, "label_space": ["<label>"]}},
  "shared_config": {{"<key shared by every condition>": "<value>"}},
  "metric_impls": [{{"condition_id": "c0", "metric_impls": {{"<Metric>": {{"impl_ref": "<library.fn>",
      "spacing": null, "postprocess": null}}}}}}],
  "prereg": {{"primary_metric": "<one metric>", "secondary_metrics": [],
             "n_seeds_planned": 3, "stopping_rule": "<fixed rule, decided now>",
             "analysis_plan": "<test, correction, alpha — decided before any data is seen>"}}}}}}

Quantities are FLOORS with NO upper bound: >=2 conditions (exactly one `baseline: true`), >=1
`ranked_batch` entry with ranks forming the contiguous sequence 1..N, and a `metric_impls` entry for
EVERY condition covering EVERY metric the active domain profile declares. Emit every condition and
every ranked hypothesis your design can genuinely test — never drop a testable contrast to keep the
bundle short. `n_seeds_planned` must be the number you would really run.

{honesty}"""

COMPILER_PROMPT = """You are `protocol-compiler` in m2_accept DESIGN. You FREEZE the design. You do \
not improve it, reorder it, rename anything in it, or fill a gap you noticed.

{north_star}

Read the planner's bundle at:
- `{planner_bundle}`

Copy its `candidate_bundle` value VERBATIM into `frozen_design`. Deterministic code compares your copy
against the planner's original and BLOCKs on ANY difference — a compiler that re-authors the design has
un-frozen it, and the three independent audits downstream would then be auditing different things. If
you believe the design is wrong, say so in `freeze_note` and still copy it unchanged; the auditors and
the director decide, not you.

Write ONLY this JSON to `{out}`:
{{"protocol_freeze": {{
  "frozen_design": {{<the planner's candidate_bundle, byte-for-byte>}},
  "freeze_note": "<what you checked while freezing; any concern you are handing to the auditors>",
  "seed_policy": "<how seeds are assigned across conditions and why that keeps the contrast paired>",
  "freeze_witness": {{"condition_ids": ["<every condition id, in the frozen design's order>"],
                     "studied_variables": ["<the frozen design's studied variables, in order>"],
                     "primary_metric": "<the frozen design's prereg primary_metric>"}}}}}}

`freeze_witness` is copied content, not a calculation — read it out of `frozen_design`. Deterministic
code recomputes the true witness and the freeze fingerprint; a witness that does not match the design
you froze is a hard BLOCK.

{honesty}"""

_AUDITOR_TAIL = """
You did NOT design this experiment and you are not resolving anyone else's opinion. Your job is an
INDEPENDENT audit of the ONE frozen protocol at:
- `{compiler_bundle}`

Read `protocol_freeze.frozen_design` and audit THAT — not the request, not your idea of a better
design. Do not read a sibling auditor's bundle; three overlapping opinions are worth less than three
independent ones.

Write ONLY this JSON to `{out}`:
{{"{bundle_key}": {{
  "seat": "{seat}",
  "audited_freeze_witness": {{"condition_ids": ["<copied from the frozen design, same order>"],
      "studied_variables": ["<copied from the frozen design, same order>"],
      "primary_metric": "<copied from the frozen design's prereg>"}},
  "verdict": "PASS|REVISE",
  "blocking_concerns": ["<a defect that makes this design unable to answer its own question>"],
  "findings": [{{"where": "<the exact field/condition you inspected>",
                "observation": "<what you found there>",
                "severity": "blocking|material|note"}}]}}}}

`audited_freeze_witness` is your proof that you audited the frozen design; deterministic code compares
it to the design and names you if it disagrees. `findings` is a FLOOR of one entry with NO upper bound
— report every real observation, including the ones that turn out fine, and never trim the list for
brevity. Say `REVISE` only with at least one blocking concern; say `PASS` only if you genuinely found
none. A `REVISE` halts the stage and returns to the planner, so be specific enough to act on.

{honesty}"""

VARIABLE_CONTROL_PROMPT = """You are `variable-control-auditor` in m2_accept DESIGN.

{north_star}

Audit confounding: does exactly one baseline exist; does every non-baseline condition differ from the
baseline ONLY in declared studied variables; is any frozen variable moving between conditions; is any
studied variable also listed as controlled or frozen; would any contrast in `ranked_batch` be
attributable to more than one change at once.
""" + _AUDITOR_TAIL

ALIGNMENT_AUDITOR_PROMPT = """You are `train-test-alignment-auditor` in m2_accept DESIGN.

{north_star}

Audit train/test parity: preprocessing and spacing identity, augmentation off on test, pretrained
weights and precision consistency, inference/threshold identity, label-space identity, split freezing,
and any path by which test information could reach training. Name the exact field that breaks parity.
""" + _AUDITOR_TAIL

METRIC_AUDITOR_PROMPT = """You are `metric-implementation-auditor` in m2_accept DESIGN.

{north_star}

Audit the metric implementations: is the SAME implementation reference used for a metric across every
condition; does every metric the active domain profile declares have an implementation; do spacing and
postprocessing settings match across conditions; is the preregistered `primary_metric` among the
implemented metrics; could any metric be computed on a different frame in one condition than another.
""" + _AUDITOR_TAIL


# --------------------------------------------------------------------------- EXECUTE dispatch orders

TRAINSET_PROMPT = """You are `trainset-builder` in m2_accept EXECUTE. You author the REAL runnable \
training-set construction script. You do not run it and you never report a metric.

{north_star}

Read only committed DESIGN artifacts:
- `{matrix_ref}` (the frozen matrix)
- `{protocol_ref}` (the compiled per-condition configs)

Write ONLY this JSON to `{out}`:
{{"train_script": {{"split": "train", "script": "<real runnable code, not prose>",
  "from_protocol_ref": "{protocol_ref}",
  "data_hash_expected": "<the hash the built train set must have; required before any run>",
  "augmentation_enabled": true, "frozen": false}}}}

`script` must be code a person could execute unchanged: real imports, real paths taken from the
compiled config, deterministic seeding, and the expected data hash computed by the script itself.
Length is a FLOOR, not a cap — include every step the build genuinely needs (manifest read, split
selection, preprocessing, caching, hash emission) and never elide a step to keep it short.

{honesty}"""

TESTSET_PROMPT = """You are `testset-builder` in m2_accept EXECUTE. You author the REAL runnable \
test-set construction script. The test set is immutable: frozen, no augmentation, ever.

{north_star}

Read only committed DESIGN artifacts:
- `{matrix_ref}`
- `{protocol_ref}`

Write ONLY this JSON to `{out}`:
{{"test_script": {{"split": "test", "script": "<real runnable code, not prose>",
  "from_protocol_ref": "{protocol_ref}",
  "data_hash_expected": "<the hash the built test set must have; required before any run>",
  "augmentation_enabled": false, "frozen": true}}}}

`augmentation_enabled: false` and `frozen: true` are structural — the schema and the preflight gate
both refuse anything else. Emit every step the build genuinely needs; length is a floor, not a cap.

{honesty}"""

TOUCH_GUARD_PROMPT = """You are `variable-touch-guard` in m2_accept EXECUTE. You are the constitution \
check on the two build scripts: a build may fix bugs and move CONTROLLED variables, but it may never \
touch a STUDIED or FROZEN variable.

{north_star}

Read the frozen matrix and both scripts:
- `{matrix_ref}`
- `{train_bundle}`
- `{test_bundle}`

Enumerate every variable the two scripts actually set, override, or derive — read the code, do not
trust a summary. Write ONLY this JSON to `{out}`:
{{"touch_report": {{
  "touched_variables": ["<every variable name the scripts really set, matrix spelling>"],
  "evidence": [{{"variable": "<name>", "where": "<script + the line or call that sets it>"}}],
  "guard_note": "<what you read, and anything you could not determine from the code>"}}}}

`touched_variables` is a FLOOR — list every variable you can evidence, with no upper bound. Omitting a
variable to make the guard pass is the single worst thing you can do here: the deterministic guard
compares your list against the frozen matrix and a hidden studied-variable change silently invalidates
the whole experiment. If a variable's origin is unclear from the code, LIST it and say so in
`guard_note`; an over-broad honest list is cheap, a missing one is not.

{honesty}"""

PREFLIGHT_PROMPT = """You are `preflight-checker` in m2_accept EXECUTE. You gather the evidence the \
deterministic preflight gate needs. The gate — not you — decides PASS or BLOCK.

{north_star}

Read:
- `{train_bundle}` and `{test_bundle}` (the two scripts)
- `{protocol_ref}` (compiled configs) and `{alignment_ref}` (the alignment verdict)

Verify the identity of every input file the scripts will read, and hand the gate a sha256 manifest for
them. Write ONLY this JSON to `{out}`:
{{"preflight_inputs": {{
  "file_identity_manifests": [{{"manifest_ref": "<what this manifest covers>",
      "manifest": {{"<relative path>": "<64-char sha256 hex>"}},
      "required_paths": ["<relative path the run must find>"]}}],
  "inspection_note": "<what you actually opened and what you could not reach>",
  "unresolved": ["<any input whose identity you could NOT verify>"]}}}}

Only list a path whose bytes you really hashed. `file_identity_manifests` may be an empty list when no
input file is reachable from this run directory — say that in `inspection_note` rather than inventing a
hash. Every unverifiable input goes in `unresolved`; that list is a floor with no cap.

{honesty}"""

ABLATION_RUNNER_PROMPT = """You are `ablation-runner` in m2_accept EXECUTE. You are NOT the executor. \
A non-LLM executor runs jobs and deposits signed receipts; you TRANSCRIBE what is actually there.

{north_star}

Inspect the real run store for this run: `{run_dir}/executor-receipts/` and
`{run_dir}/execution-results/`, plus the compiled configs at `{protocol_ref}`.

- If those directories are empty or absent: NOTHING RAN. Emit one `planned`, metric-free record per
  compiled condition and an empty `executor_receipt_refs`.
- If signed receipts exist: emit one `provisional` record per (condition, seed) the receipts actually
  cover, copying provenance hashes from the receipt, and list every receipt's relative path.

Write ONLY this JSON to `{out}`:
{{"execution_evidence": {{
  "run_records": [{{"condition_id": "<from the compiled config>", "status": "planned|provisional",
      "provenance": {{"config_hash": "<hash>", "data_hash": "<hash|null>", "git_sha": "<hash|null>",
                     "seed": 0}},
      "metrics": {{}}, "notes": "<optional>"}}],
  "executor_receipt_refs": ["executor-receipts/<job>.json"],
  "evidence_boundary": "<one sentence: exactly what you found in the run store, or that it was empty>"}}}}

A `planned` record MUST have `metrics: {{}}` — deterministic code BLOCKs a planned record that carries
a number, and receipts listed without provisional records are treated as ambiguous execution state.
Never author, paste, sign, repair, or "reconstruct" a receipt or a metric value; if the run store
disagrees with what you expected, report the run store. `run_records` is a floor: cover every compiled
condition, with no upper bound.

{honesty}"""

JOURNALER_PROMPT = """You are `experiment-journaler` in m2_accept EXECUTE. You record the provenance \
of what really ran, so the parity verifier can mechanically re-check that the designed contract held.

{north_star}

Read:
- `{runner_bundle}` (the run records the runner transcribed)
- `{matrix_ref}` and `{protocol_ref}` (designed pipeline facts)
- the receipts and raw result files the runner listed, if any

If every run record is `planned`, there is NO journal: emit `"journal": null`. Do not invent a journal
to make the stage look complete — a null journal is the honest record of an experiment that has not
run, and deterministic code cross-checks this against the receipts either way.

Write ONLY this JSON to `{out}`:
{{"journal_evidence": {{"journal": null}}}}
  ... or, when signed receipts really exist:
{{"journal_evidence": {{"journal": {{
  "condition_id": "<the condition this entry covers>", "config_hash": "<hash>",
  "data_hash": "<hash|null>", "git_sha": "<hash|null>", "seed": 0,
  "designed_train": {{<pipeline facts DESIGN specified for train>}},
  "designed_test": {{<pipeline facts DESIGN specified for test>}},
  "actual_train": {{<pipeline facts that ACTUALLY ran>}},
  "actual_test": {{<pipeline facts that ACTUALLY ran>}},
  "metrics_snapshot": {{"raw_result_rows": [{{"job_id": "<from the receipt>", "row_id": "<row id>",
      "condition_id": "<condition>", "seed": 0, "metric": "<metric>", "value": 0.0}}]}}}}}}

Every raw result row must be copied from an attested executor result file and must match it exactly —
deterministic code compares your rows against the receipt-bound files row by row and BLOCKs on any
divergence. `raw_result_rows` is a floor: copy EVERY row the receipts cover, with no upper bound;
selecting a favourable subset is fabrication. `designed_*` comes from DESIGN, `actual_*` from the run.

{honesty}"""

PARITY_PROMPT = """You are `train-test-parity-verifier` in m2_accept EXECUTE. You independently check \
that what RAN matches what was DESIGNED. You did not write the scripts or the journal.

{north_star}

Read:
- `{journaler_bundle}` (the journal, which may be null)
- `{alignment_ref}` (the designed alignment contract)
- `{matrix_ref}`

Compare `actual_train`/`actual_test` against `designed_train`/`designed_test` field by field. Write
ONLY this JSON to `{out}`:
{{"parity_claim": {{
  "journal_present": true,
  "designed_vs_actual": [{{"field": "<the exact field>", "designed": "<value>", "actual": "<value>",
      "matches": true}}],
  "unverifiable": ["<any designed field the journal does not report>"],
  "seat_summary": "<what you compared and what you could not>"}}}}

When the journal is null, set `journal_present: false`, leave `designed_vs_actual` empty, and say in
`seat_summary` that nothing ran so nothing can be compared — the deterministic verifier then records
parity as honestly SKIPPED rather than PASS. `designed_vs_actual` is a floor covering every field the
alignment contract names, with no upper bound. Never report `matches: true` for a field you could not
read; put it in `unverifiable`.

{honesty}"""


# --------------------------------------------------------------------------- ANALYZE / VERIFY orders

ANALYZER_PROMPT = """You are `result-analyzer` in m2_accept ANALYZE. You locate and interpret \
evidence. You are NOT a numeric source: deterministic code rebuilds every number from the attested \
executor receipts and compares it to yours.

{north_star}

Read only committed artifacts:
- `{matrix_ref}`, `{prereg_ref}` (what was preregistered)
- `evidence/EXECUTE/run-record-*.artifact.json`, `evidence/EXECUTE/journal-entry.artifact.json`
- the receipt-bound raw result files those artifacts point to

If every run record is `planned` (nothing ran): emit `candidate_findings: []` and
`candidate_per_seed: null`, and write the interpretation as a PLAN — what this experiment would show,
under what threshold, and what it does not yet show. A number here would be refused outright.

Write ONLY this JSON to `{out}`:
{{"analysis": {{
  "candidate_findings": [{{"metric": "<metric>", "value": 0.0, "condition_id": "<condition>",
      "baseline_value": 0.0, "baseline_condition_id": "<baseline>"}}],
  "candidate_per_seed": {{"<condition>": {{"<metric>": [0.0]}}}},
  "interpretation": "<what the evidence does and does not establish, in the preregistered frame>",
  "caveats": ["<every material limit on reading these numbers>"],
  "claim_boundary": "<the outer edge of what may be claimed from this run>",
  "next_experiment": "<the single most informative next run>"}}}}

Every candidate value must be traceable to a raw result row — deterministic code BLOCKs on any
mismatch, extra row, or missing row, so copy, never round or reconstruct. `candidate_findings`,
`caveats` are FLOORS with no upper bound: report every finding the evidence supports and every caveat
that genuinely applies; dropping an inconvenient caveat is the failure mode this seat exists to avoid.

{honesty}"""

SANITY_PROMPT = """You are `result-sanity-checker` in m2_accept ANALYZE. You did NOT produce this \
analysis. Your entire job is to independently re-open the evidence and try to find it wrong.

{north_star}

Read, independently of the analyst's reasoning:
- `evidence/EXECUTE/run-record-*.artifact.json`, `evidence/EXECUTE/journal-entry.artifact.json`
- `{matrix_ref}`, `{prereg_ref}`
- and only then `{analyzer_bundle}` to see what is being claimed

Check: are values inside each metric's valid range; is any value NaN/inf/impossible; is a "better"
direction assumed that the metric does not have; is the baseline the preregistered one; is any
condition missing coverage for the primary metric; is the seed set paired across conditions; does the
interpretation quietly exceed the preregistered analysis plan.

Write ONLY this JSON to `{out}`:
{{"sanity_review": {{
  "independent_of_analyzer": true,
  "recomputed_from": ["<each artifact path you actually re-opened>"],
  "verdict": "PASS|REVISE",
  "concerns": [{{"where": "<field/metric/condition>", "concern": "<what is wrong or unsupported>",
      "severity": "blocking|material|note"}}],
  "seat_summary": "<what you re-derived and what you could not>"}}}}

Do NOT emit findings, per-seed vectors, p-values, or any result number — deterministic code owns those
and will BLOCK a reviewer that authors them. `recomputed_from` must name real paths you opened;
`concerns` is a floor with no cap. Say `REVISE` only with at least one blocking concern, and `PASS`
only if you genuinely could not break it. When nothing ran, that is what you report: there is no
result to sanity-check, and `recomputed_from` names the planned records you read.

{honesty}"""

ADVERSARIAL_PROMPT = """You are `adversarial-reviewer` in m2_accept VERIFY — the last independent \
pass before the director sees an acceptance report. You did not design, run, or analyze this \
experiment. Assume the claim is WRONG and try to prove it.

REQUEST: {request}

{north_star}

Read every committed artifact of this run, including:
- `{matrix_ref}`, `{prereg_ref}`, `{protocol_ref}`
- `evidence/EXECUTE/*` (scripts, preflight, run records, journal, parity)
- `{result_ref}` and `evidence/ANALYZE/sanity-verdict.artifact.json` when they exist

Run all five refutation checks and report each with the evidence you actually opened:
`leakage` (any path from test to train, including hyperparameter selection),
`fairness` (is the baseline given the same budget, data, and tuning),
`eval_frame` (is the metric computed on the same frame, at the same threshold, over the same cases),
`provenance` (do config/data/code hashes and receipts actually bind the numbers to a real run),
`overclaim` (does any sentence in the analysis exceed what the numbers support).

Write ONLY this JSON to `{out}`:
{{"adversarial_review": {{
  "independent_of_analyzer": true,
  "checks": {{"leakage": {{"pass": true, "evidence": "<what you opened and concluded>"}},
             "fairness": {{"pass": true, "evidence": "..."}},
             "eval_frame": {{"pass": true, "evidence": "..."}},
             "provenance": {{"pass": true, "evidence": "..."}},
             "overclaim": {{"pass": true, "evidence": "..."}}}},
  "result_ready": false,
  "refutation_attempts": [{{"attempt": "<the refutation you tried>",
      "outcome": "<held|broke|inconclusive>", "detail": "<what you saw>"}}],
  "claim_boundary": "<the outer edge of what may be claimed>",
  "next_experiment": "<the run that would most efficiently refute what survived>"}}}}

Every check needs real `evidence`; an empty evidence string fails the check by contract. `pass: true`
under uncertainty is not allowed — default to `false` and say why. `result_ready` must equal "all five
checks passed"; deterministic code re-derives it and BLOCKs a self-declared value, and it must be
`false` whenever nothing actually ran. `refutation_attempts` is a FLOOR with no upper bound: record
every angle you tried, including the ones that held — an audit trail of failed refutations is exactly
what makes a surviving claim credible.

{honesty}"""


# --------------------------------------------------------------------------- panels

def _seats(run_dir, stage: str, request: str) -> List[_panel_recipe.Seat]:
    """This mode's roster for one stage, with every prompt already formatted.

    `full_rigor_minimal`'s panel is a DIFFERENT roster (script-author / synthesizers / critics) and is
    not dispatchable under this mode's `agent_subset`, so the dispatch layer is m2_accept's own while
    every deterministic decision below is delegated to the shared tools.
    """
    north_star = _shared.north_star_block(run_dir)
    path = lambda label: _panel_recipe.bundle_path(run_dir, stage, label)  # noqa: E731
    common = {"north_star": north_star, "honesty": _HONESTY, "matrix_ref": MATRIX_REF,
              "protocol_ref": PROTOCOL_REF, "alignment_ref": ALIGNMENT_REF, "prereg_ref": PREREG_REF,
              "result_ref": RESULT_REF, "run_dir": run_dir}

    if stage == "DESIGN":
        planner = path("experiment-planner")
        compiler = path("protocol-compiler")
        auditors = (
            ("variable-control-auditor", "variable_control_audit", VARIABLE_CONTROL_PROMPT),
            ("train-test-alignment-auditor", "train_test_alignment_audit", ALIGNMENT_AUDITOR_PROMPT),
            ("metric-implementation-auditor", "metric_implementation_audit", METRIC_AUDITOR_PROMPT),
        )
        seats = [
            # `design` (-> opus): designing an experiment and compiling the protocol that freezes it
            # are the director's 实验设计 tier, not "writing something already decided". `reason` was
            # routing both to sonnet, which is the one place a cheap model changes what gets measured.
            _panel_recipe.Seat(
                "experiment-planner", PLANNER_PROMPT.format(request=request, out=planner, **common),
                "candidate_bundle", tier="design"),
            _panel_recipe.Seat(
                "protocol-compiler",
                COMPILER_PROMPT.format(planner_bundle=planner, out=compiler, **common),
                "protocol_freeze", tier="design", depends_on=("experiment-planner",)),
        ]
        seats += [
            _panel_recipe.Seat(
                label, prompt.format(compiler_bundle=compiler, out=path(label), seat=label,
                                     bundle_key=key, **common),
                key, tier="audit", depends_on=("protocol-compiler",))
            for label, key, prompt in auditors
        ]
        return seats

    if stage == "EXECUTE":
        train, test = path("trainset-builder"), path("testset-builder")
        runner, journaler = path("ablation-runner"), path("experiment-journaler")
        return [
            _panel_recipe.Seat("trainset-builder",
                               TRAINSET_PROMPT.format(out=train, **common),
                               "train_script", tier="reason"),
            _panel_recipe.Seat("testset-builder",
                               TESTSET_PROMPT.format(out=test, **common),
                               "test_script", tier="reason"),
            _panel_recipe.Seat("variable-touch-guard",
                               TOUCH_GUARD_PROMPT.format(train_bundle=train, test_bundle=test,
                                                         out=path("variable-touch-guard"), **common),
                               "touch_report", tier="audit",
                               depends_on=("trainset-builder", "testset-builder")),
            _panel_recipe.Seat("preflight-checker",
                               PREFLIGHT_PROMPT.format(train_bundle=train, test_bundle=test,
                                                       out=path("preflight-checker"), **common),
                               "preflight_inputs", tier="audit",
                               depends_on=("trainset-builder", "testset-builder",
                                           "variable-touch-guard")),
            _panel_recipe.Seat("ablation-runner",
                               ABLATION_RUNNER_PROMPT.format(out=runner, **common),
                               "execution_evidence", tier="tool",
                               depends_on=("preflight-checker",)),
            _panel_recipe.Seat("experiment-journaler",
                               JOURNALER_PROMPT.format(runner_bundle=runner, out=journaler, **common),
                               "journal_evidence", tier="tool", depends_on=("ablation-runner",)),
            _panel_recipe.Seat("train-test-parity-verifier",
                               PARITY_PROMPT.format(journaler_bundle=journaler,
                                                    out=path("train-test-parity-verifier"), **common),
                               "parity_claim", tier="audit",
                               depends_on=("experiment-journaler",)),
        ]

    if stage == "ANALYZE":
        analyzer = path("result-analyzer")
        return [
            # `audit` (-> opus): reading a result is where a wrong call becomes a wrong claim.
            _panel_recipe.Seat("result-analyzer", ANALYZER_PROMPT.format(out=analyzer, **common),
                               "analysis", tier="audit"),
            _panel_recipe.Seat("result-sanity-checker",
                               SANITY_PROMPT.format(analyzer_bundle=analyzer,
                                                    out=path("result-sanity-checker"), **common),
                               "sanity_review", tier="audit", depends_on=("result-analyzer",)),
        ]

    if stage == "VERIFY":
        return [
            _panel_recipe.Seat("adversarial-reviewer",
                               ADVERSARIAL_PROMPT.format(request=request,
                                                         out=path("adversarial-reviewer"), **common),
                               "adversarial_review", tier="audit"),
        ]
    return []


_PANEL_NOTES = {
    "DESIGN": ("Plan, then FREEZE, then audit the freeze three ways. The compiler copies the design "
               "verbatim; the three auditors are dispatched only after the freeze exists and each "
               "must prove it audited that same frozen design."),
    "EXECUTE": ("Build both dataset scripts in parallel, guard the studied/frozen variables, gather "
                "preflight evidence, then transcribe (never author) whatever the external executor "
                "actually deposited and verify designed-vs-actual parity."),
    "ANALYZE": ("The analyst locates evidence and interprets it; the sanity checker re-opens the same "
                "artifacts independently. Deterministic code owns every number in between."),
    "VERIFY": ("One independent adversarial pass that assumes the claim is wrong. It did not design, "
               "run, or analyze the experiment, so it cannot be certifying its own work."),
}


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The panel to dispatch for a stage. REPORT is deterministic and dispatches nothing."""
    del vault  # this mode reads the run store and committed artifacts, never the vault
    seats = _seats(run_dir, stage, request)
    if not seats:
        return None
    return _panel_recipe.panel(run_dir, stage, MODE, seats,
                               panel_note=_PANEL_NOTES[stage], model_policy=model_policy)


def _bundles(run_dir, stage: str, request: str = "") -> dict:
    return _panel_recipe.load_seat_bundles(run_dir, stage, MODE, _seats(run_dir, stage, request))


# --------------------------------------------------------------------------- shared gate plumbing

def _condition_ids(matrix: dict) -> List[str]:
    return [str(row.get("id")) for row in (matrix.get("conditions") or []) if row.get("id")]


def _gates(run_dir, stage: str, ts: str, bundles: dict, *, refs=(), known=()) -> tuple:
    """The three common gates, with the committed direction anchor folded into the drift input.

    A design/execute panel's own text is code, hashes and condition ids, so the north-star drift
    gate's "zero anchor coverage" rule would fire on shape rather than on drift. Anchoring on the
    committed research question is what `full_rigor_minimal` does for the same reason; the
    out-of-scope half of the gate still reads the panel's real output unmodified.
    """
    anchored = {"_committed_direction_anchor": fr._direction_anchor(run_dir), **bundles}
    return _panel_recipe.common_gates(run_dir, stage, ts, mode=MODE, bundles=anchored,
                                      downstream_refs=refs, known_ids=known)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateBlock(f"{MODE} {message}")


# --------------------------------------------------------------------------- DESIGN

def _freeze_witness(design: dict) -> dict:
    """The witness every DESIGN auditor must echo — copied content, never model arithmetic."""
    return {
        "condition_ids": _condition_ids(design.get("design") or {}),
        "studied_variables": [str(v) for v in
                              (((design.get("design") or {}).get("variables") or {}).get("studied") or [])],
        "primary_metric": str((design.get("prereg") or {}).get("primary_metric") or ""),
    }


def _fingerprint(value) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _frozen_design(bundles: dict) -> tuple:
    """HARD GATE 1: one frozen protocol, provably audited by all three independent auditors."""
    proposal = bundles["candidate_bundle"]
    freeze = bundles["protocol_freeze"]
    _require(isinstance(proposal, dict) and isinstance(freeze, dict),
             "DESIGN candidate_bundle and protocol_freeze must both be objects")
    frozen = freeze.get("frozen_design")
    _require(
        frozen == proposal,
        "DESIGN freeze BLOCK: protocol-compiler.frozen_design is not the planner's candidate_bundle "
        "verbatim. A compiler that re-authors the design has un-frozen it, and the three independent "
        "audits would then be auditing different objects. Copy the planner's bundle unchanged and put "
        "any concern in freeze_note.")
    _shared.require_bundle_keys(
        frozen, ["design", "train", "test", "shared_config", "metric_impls", "prereg"],
        stage="DESIGN", mode=MODE)

    truth = _freeze_witness(frozen)
    _require(freeze.get("freeze_witness") == truth,
             f"DESIGN freeze BLOCK: protocol-compiler's freeze_witness {freeze.get('freeze_witness')!r} "
             f"does not describe the design it froze (true witness {truth!r})")
    for label, key in (("variable-control-auditor", "variable_control_audit"),
                       ("train-test-alignment-auditor", "train_test_alignment_audit"),
                       ("metric-implementation-auditor", "metric_implementation_audit")):
        audit = bundles[key]
        _require(isinstance(audit, dict), f"DESIGN {label} bundle must be an object")
        _require(
            audit.get("audited_freeze_witness") == truth,
            f"DESIGN independence BLOCK: {label} audited "
            f"{audit.get('audited_freeze_witness')!r}, not the ONE frozen protocol {truth!r}. Three "
            f"audits are only independent evidence when they audit the same frozen design; re-run "
            f"this auditor against protocol_freeze.frozen_design.")
        verdict = audit.get("verdict")
        _require(verdict in {"PASS", "REVISE"},
                 f"DESIGN {label} verdict must be PASS or REVISE, got {verdict!r}")
        concerns = [str(c) for c in (audit.get("blocking_concerns") or []) if str(c).strip()]
        _require(verdict == "PASS" or concerns,
                 f"DESIGN {label} says REVISE without naming a blocking concern")
        if concerns:
            raise GateBlock(
                f"{MODE} DESIGN audit BLOCK: {label} refuses the frozen design: {concerns}. The design "
                f"is not frozen-acceptable; revise it with the planner and re-freeze.")
    return frozen, truth


def _design_dets(run_dir, ts, bundles) -> tuple:
    frozen, witness = _frozen_design(bundles)
    profile = _shared.domain_profile(run_dir)
    design = frozen["design"]
    paths: List[str] = []

    try:
        matrix = build_matrix(design["rq"], design["variables"], design["conditions"],
                             design["ranked_batch"], design["leakage"])
    except (KeyError, ValueError) as exc:
        raise GateBlock(f"{MODE} DESIGN experiment-matrix design-hygiene BLOCK: {exc}") from exc

    variable_control = vc_build(matrix, profile=profile)
    paths.append(write_artifact(
        run_dir, "DESIGN", "variable-control-report.artifact.json", "variable_control_report",
        "variable-control-auditor", variable_control, ts,
        "blocked" if variable_control["verdict"] == "BLOCK" else "approved"))
    if variable_control["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} variable-control BLOCK: {variable_control['violations']}")

    # Same dual-locked escape hatch as design_experiment: the auditor's declared `zero_training`
    # fact AND an explicit zero_training entry in the design's frozen-variable list. A frozen,
    # inference-only pipeline has no training run for the parity invariants to compare against.
    design_variables = design.get("variables") or {}
    zero_training = detect_zero_training(
        bool(frozen.get("zero_training") or (frozen.get("train") or {}).get("zero_training")),
        design_variables.get("frozen") or [])
    alignment = alignment_build(frozen["train"], frozen["test"], profile=profile,
                               train_ref="train-pipeline", test_ref="test-pipeline",
                               zero_training=zero_training)
    paths.append(write_artifact(
        run_dir, "DESIGN", "alignment-report.artifact.json", "alignment_report",
        "train-test-alignment-auditor", alignment, ts,
        "blocked" if alignment["verdict"] == "BLOCK" else "approved"))
    if alignment["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} train-test-alignment BLOCK: {alignment['violations']}")

    # A metric implementation that differs across conditions along a STUDIED variable is the
    # treatment, not an inconsistency. Undeclared differences still BLOCK.
    studied_variables = {
        str(v).split(" --")[0].strip().casefold()
        for v in (design_variables.get("studied") or [])
    }
    metric_report = metric_build(frozen["metric_impls"], profile=profile,
                                 studied_variables=studied_variables)
    paths.append(write_artifact(
        run_dir, "DESIGN", "metric-impl-report.artifact.json", "metric_impl_report",
        "metric-implementation-auditor", metric_report, ts,
        "blocked" if metric_report["verdict"] == "BLOCK" else "approved"))
    if metric_report["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} metric-implementation BLOCK: {metric_report['violations']}")

    protocol = compile_protocol(matrix, from_matrix_ref=MATRIX_REF, shared=frozen["shared_config"],
                               seed=fr._seed(run_dir))
    paths.append(write_artifact(run_dir, "DESIGN", "protocol-spec.artifact.json", "protocol_spec",
                                "protocol-compiler", protocol, ts))
    try:
        prereg = prereg_tool.build_prereg(matrix, **frozen["prereg"])
    except (TypeError, ValueError) as exc:
        raise GateBlock(f"{MODE} preregistration BLOCK (analysis contract not frozen): {exc}") from exc
    paths.append(write_artifact(run_dir, "DESIGN", "preregistration.artifact.json", "preregistration",
                                "experiment-planner", prereg, ts))
    paths.append(write_artifact(run_dir, "DESIGN", "experiment-matrix.artifact.json",
                                "experiment_matrix", "experiment-planner", matrix, ts))

    fingerprint = _fingerprint(frozen)
    paths.append(write_artifact(
        run_dir, "DESIGN", "design-freeze.artifact.json", "note", "protocol-compiler",
        {"title": f"{MODE} frozen design {fingerprint}",
         "body": json.dumps({"design_fingerprint": fingerprint, "freeze_witness": witness,
                             "audited_by": ["variable-control-auditor",
                                            "train-test-alignment-auditor",
                                            "metric-implementation-auditor"],
                             "freeze_note": str(bundles["protocol_freeze"].get("freeze_note") or ""),
                             "seed_policy": str(bundles["protocol_freeze"].get("seed_policy") or "")},
                            ensure_ascii=False, indent=2),
         "refs": [MATRIX_REF, PROTOCOL_REF, PREREG_REF]}, ts))

    ranked = [str(row.get("condition_id") or "") for row in matrix.get("ranked_batch") or []]
    gate_paths, frag = _gates(run_dir, "DESIGN", ts, bundles,
                              refs=ranked, known=set(_condition_ids(matrix)))
    return paths + gate_paths, {
        "design_frozen": True, "design_fingerprint": fingerprint,
        "independent_design_audits": 3,
        "vc_gate": variable_control["verdict"], "alignment_gate": alignment["verdict"],
        "metric_gate": metric_report["verdict"], "prereg_frozen": True,
        "n_conditions": len(matrix["conditions"]), **frag}


# --------------------------------------------------------------------------- EXECUTE

def _execute_dets(run_dir, ts, bundles) -> tuple:
    profile = _shared.domain_profile(run_dir)
    matrix = fr._read_payload(run_dir, MATRIX_REF)
    protocol = fr._read_payload(run_dir, PROTOCOL_REF)
    alignment = fr._read_payload(run_dir, ALIGNMENT_REF)
    train_script, test_script = bundles["train_script"], bundles["test_script"]
    evidence, preflight_inputs = bundles["execution_evidence"], bundles["preflight_inputs"]
    paths: List[str] = []

    paths.append(write_artifact(run_dir, "EXECUTE", "trainset-script.artifact.json",
                                "dataset_script_record", "trainset-builder", train_script, ts))
    paths.append(write_artifact(run_dir, "EXECUTE", "testset-script.artifact.json",
                                "dataset_script_record", "testset-builder", test_script, ts))

    # HARD GATE: a build may move controlled variables only — never a studied or frozen one.
    touch = bundles["touch_report"]
    _require(isinstance(touch, dict) and isinstance(touch.get("touched_variables"), list),
             "EXECUTE variable-touch-guard must emit a touched_variables list")
    touch_verdict = variable_touch_guard.check_debug_session(
        {"touched_variables": touch["touched_variables"]}, matrix)
    touch_verdict["checked_against"] = MATRIX_REF
    paths.append(write_artifact(
        run_dir, "EXECUTE", "variable-touch-verdict.artifact.json", "variable_touch_verdict",
        "variable-touch-guard", touch_verdict, ts,
        "blocked" if touch_verdict["verdict"] == "BLOCK" else "approved"))
    if touch_verdict["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} variable-touch BLOCK: {touch_verdict['violations']}")

    _require(isinstance(preflight_inputs, dict),
             "EXECUTE preflight-checker must emit a preflight_inputs object")
    preflight = preflight_build(
        train_script, test_script, protocol, alignment, profile=profile,
        protocol_ref=PROTOCOL_REF, alignment_ref=ALIGNMENT_REF,
        file_identity_manifests=preflight_inputs.get("file_identity_manifests"))
    paths.append(write_artifact(
        run_dir, "EXECUTE", "preflight-report.artifact.json", "preflight_report",
        "preflight-checker", preflight, ts,
        "blocked" if preflight["verdict"] == "BLOCK" else "approved"))
    if preflight["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} preflight BLOCK: {preflight['violations']}")

    # HARD GATE: planned vs attempted vs completed. Numbers exist only behind a receipt.
    _require(isinstance(evidence, dict), "EXECUTE ablation-runner must emit an execution_evidence object")
    records = evidence.get("run_records") or []
    receipt_refs = evidence.get("executor_receipt_refs")
    journal = (bundles["journal_evidence"] or {}).get("journal")
    _require(isinstance(records, list) and records,
             "EXECUTE ablation-runner emitted no run_records — every compiled condition needs one")
    _require(isinstance(receipt_refs, list)
             and all(isinstance(ref, str) and ref.strip() for ref in receipt_refs),
             "EXECUTE executor_receipt_refs must be a list of non-empty relative paths")
    declared = set(_condition_ids(matrix))
    for index, record in enumerate(records, start=1):
        status = record.get("status")
        if status == "planned" and (record.get("metrics") or {}):
            raise GateBlock(
                f"{MODE} EXECUTE BLOCK: planned run_record {record.get('condition_id')!r} carries "
                f"metrics. `planned` means nothing executed; it is never numeric evidence.")
        if journal is None and status != "planned":
            raise GateBlock(
                f"{MODE} EXECUTE BLOCK: run_record {index} is {status!r} with no journal. No journal "
                f"= no real run: every record must be planned and metric-free.")
        _require(str(record.get("condition_id") or "") in declared,
                 f"EXECUTE run_record {index} reports condition "
                 f"{record.get('condition_id')!r}, which the frozen matrix never declared")

    provisional = any(record.get("status") == "provisional" for record in records)
    if provisional:
        try:
            execution_import = build_execution_import(run_dir, receipt_refs,
                                                     run_id=fr._run_id(run_dir), created_at=ts)
            validate_records_against_import(records, execution_import)
        except ExecutionReceiptError as exc:
            raise GateBlock(f"{MODE} executor receipt/import BLOCK: {exc}") from exc
        paths.append(write_artifact(run_dir, "EXECUTE", IMPORT_ARTIFACT_REL.name, "note",
                                    "execution-receipt-importer",
                                    import_note_payload(execution_import), ts))
    elif receipt_refs:
        raise GateBlock(
            f"{MODE} EXECUTE BLOCK: executor receipts were listed without any provisional run_record, "
            f"so the execution state is ambiguous — neither planned nor completed.")

    for index, record in enumerate(records, start=1):
        paths.append(write_artifact(run_dir, "EXECUTE", f"run-record-{index}.artifact.json",
                                    "run_record", "ablation-runner", record, ts))

    parity_claim = bundles["parity_claim"]
    _require(isinstance(parity_claim, dict), "EXECUTE train-test-parity-verifier must emit an object")
    if journal is None:
        _require(parity_claim.get("journal_present") is not True,
                 "EXECUTE train-test-parity-verifier claims a journal is present while the journaler "
                 "emitted none — parity cannot be verified against a journal that does not exist")
        parity_label = "SKIPPED(no real run)"
    else:
        paths.append(write_artifact(run_dir, "EXECUTE", "journal-entry.artifact.json",
                                    "journal_entry", "experiment-journaler", journal, ts))
        parity = parity_build(journal, alignment, profile=profile,
                              journal_ref="journal_entry", alignment_ref=ALIGNMENT_REF)
        paths.append(write_artifact(
            run_dir, "EXECUTE", "parity-verdict.artifact.json", "parity_verdict",
            "train-test-parity-verifier", parity, ts,
            "blocked" if parity["verdict"] == "BLOCK" else "approved"))
        if parity["verdict"] == "BLOCK":
            raise GateBlock(f"{MODE} parity BLOCK: {parity['violations']}")
        parity_label = parity["verdict"] if provisional else "PASS(no completed run_records)"

    # Classified by the ONE canonical execution-truth core, only after the evidence is on disk.
    state = _panel_recipe.execution_truth(run_dir)
    gate_paths, frag = _gates(run_dir, "EXECUTE", ts, bundles,
                              refs=[str(r.get("condition_id") or "") for r in records],
                              known=declared)
    return paths + gate_paths, {
        "touch_gate": touch_verdict["verdict"], "preflight_gate": preflight["verdict"],
        "parity_gate": parity_label, "scripts_emitted": True,
        "execution_state": state["label"], "executed": bool(state["executed"]),
        "n_run_records": len(records),
        "executor_receipts_verified": len(receipt_refs) if state["executed"] else 0, **frag}


# --------------------------------------------------------------------------- ANALYZE

_FORBIDDEN_REVIEWER_NUMERICS = ("findings", "candidate_findings", "per_seed", "candidate_per_seed",
                                "p_value", "effect_size", "metrics")


def _independent_reviewer(review: dict, *, seat: str, stage: str) -> None:
    """HARD GATE 3: a reviewer declares independence and never authors a result number."""
    _require(isinstance(review, dict), f"{stage} {seat} bundle must be an object")
    _require(review.get("independent_of_analyzer") is True,
             f"{stage} independence BLOCK: {seat} did not declare independent_of_analyzer — a seat "
             f"that produced the analysis may not also certify it")
    authored = sorted(set(review) & set(_FORBIDDEN_REVIEWER_NUMERICS))
    _require(not authored,
             f"{stage} independence BLOCK: {seat} authored result field(s) {authored}; deterministic "
             f"code owns every number, a reviewer only re-opens the evidence")


def _analyze_dets(run_dir, ts, bundles) -> tuple:
    analysis, review = bundles["analysis"], bundles["sanity_review"]
    _require(isinstance(analysis, dict), "ANALYZE result-analyzer bundle must be an object")
    _shared.require_bundle_keys(
        analysis, ["candidate_findings", "candidate_per_seed", "interpretation", "caveats",
                   "claim_boundary", "next_experiment"], stage="ANALYZE", mode=MODE)
    _independent_reviewer(review, seat="result-sanity-checker", stage="ANALYZE")
    _require(isinstance(review.get("recomputed_from"), list) and review["recomputed_from"],
             "ANALYZE result-sanity-checker must name the artifact(s) it re-opened in recomputed_from")
    _require(review.get("verdict") in {"PASS", "REVISE"},
             f"ANALYZE result-sanity-checker verdict must be PASS or REVISE, got {review.get('verdict')!r}")

    matrix = fr._read_payload(run_dir, MATRIX_REF)
    prereg = fr._read_payload(run_dir, PREREG_REF)
    state = _panel_recipe.execution_truth(run_dir)
    candidates = analysis["candidate_findings"] or []
    per_seed = analysis["candidate_per_seed"]
    profile = _shared.domain_profile(run_dir)
    paths: List[str] = []

    # HARD GATE 2 (the mode's core honesty boundary): no number without an execution receipt.
    _panel_recipe.refuse_metrics_without_receipt(state, candidates, mode=MODE,
                                                what="aggregate result findings")
    _panel_recipe.refuse_metrics_without_receipt(state, per_seed, mode=MODE,
                                                what="per-seed result vectors")

    blocking = [row for row in (review.get("concerns") or [])
                if isinstance(row, dict) and row.get("severity") == "blocking"]
    if review["verdict"] == "REVISE" or blocking:
        _require(bool(blocking),
                 "ANALYZE result-sanity-checker says REVISE without a blocking concern")
        raise GateBlock(
            f"{MODE} ANALYZE sanity BLOCK: the independent sanity checker refuses this analysis: "
            f"{[row.get('concern') for row in blocking]}")

    if not state["executed"]:
        gate_paths, frag = _gates(run_dir, "ANALYZE", ts, bundles)
        return paths + gate_paths, {
            "analysis_status": f"PLANNED({state['label']})", "executed": False,
            "result_summary_emitted": False, "stats_computed": False,
            "sanity_gate": "NOT_APPLICABLE(no result to check)",
            "execution_state": state["label"], **frag}

    try:
        truth = derive_numeric_evidence(run_dir, matrix, prereg)
    except ExecutionTruthError as exc:
        raise GateBlock(f"{MODE} ANALYZE execution-evidence BLOCK: {exc}") from exc
    fr._candidate_findings_match(candidates, truth["findings"])
    fr._candidate_per_seed_match(per_seed, truth["per_seed"])

    caveats = [str(c) for c in (analysis["caveats"] or [])] + list(truth["caveats"])
    if truth["per_seed"]:
        result = build_result_summary_with_stats(truth["findings"], truth["per_seed"],
                                                seed=fr._seed(run_dir), caveats=caveats)
        stats_computed = bool(result.get("stats", {}).get("n_findings_tested"))
    else:
        if not any("no significance computed" in caveat for caveat in caveats):
            caveats.append("no significance computed - no paired per-seed execution evidence")
        result = build_result_summary(truth["findings"], caveats=caveats)
        stats_computed = False
    paths.append(write_artifact(run_dir, "ANALYZE", "result-summary.artifact.json", "result_summary",
                                "result-analyzer", result, ts))

    sanity = sanity_build(result, profile=profile)
    paths.append(write_artifact(
        run_dir, "ANALYZE", "sanity-verdict.artifact.json", "sanity_verdict",
        "result-sanity-checker", sanity, ts,
        "blocked" if sanity["verdict"] == "BLOCK" else "approved"))
    if sanity["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} sanity BLOCK: {sanity['violations']}")

    deviation = prereg_tool.build_deviation_verdict(prereg, result)
    paths.append(write_artifact(
        run_dir, "ANALYZE", "prereg-deviation-verdict.artifact.json", "analysis_check_verdict",
        "result-sanity-checker", deviation, ts, "approved" if deviation["pass"] else "blocked"))
    if not deviation["pass"]:
        raise GateBlock(f"{MODE} prereg-deviation BLOCK: {deviation['violations']}")

    gate_paths, frag = _gates(
        run_dir, "ANALYZE", ts, bundles,
        refs=[str(row.get("condition_id") or "") for row in result.get("findings") or []],
        known=set(_condition_ids(matrix)))
    return paths + gate_paths, {
        "analysis_status": "REAL_RUN", "executed": True, "result_summary_emitted": True,
        "stats_computed": stats_computed, "sanity_gate": sanity["verdict"],
        "prereg_deviation_gate": "PASS" if deviation["pass"] else "BLOCK",
        "raw_result_rows": truth["raw_result_row_count"],
        "executor_receipts": truth["executor_receipt_count"],
        "execution_state": state["label"], **frag}


# --------------------------------------------------------------------------- VERIFY

def _verify_dets(run_dir, ts, bundles) -> tuple:
    review = bundles["adversarial_review"]
    _independent_reviewer(review, seat="adversarial-reviewer", stage="VERIFY")
    checks = review.get("checks")
    _require(isinstance(checks, dict), "VERIFY adversarial-reviewer must emit a checks object")
    for name in REVIEW_CHECKS:
        row = checks.get(name)
        _require(isinstance(row, dict) and isinstance(row.get("pass"), bool),
                 f"VERIFY adversarial-reviewer did not investigate {name} with a boolean pass")
    state = _panel_recipe.execution_truth(run_dir)
    paths: List[str] = []

    if not state["executed"]:
        _require(review.get("result_ready") is not True,
                 f"VERIFY BLOCK: result_ready cannot be true while execution state is "
                 f"{state['label']!r} — there is no result to be ready")
        gate_paths, frag = _gates(run_dir, "VERIFY", ts, bundles)
        return paths + gate_paths, {
            "review_gate": f"SKIPPED({state['label']})", "executed": False,
            "execution_state": state["label"], **frag}

    fr._read_payload(run_dir, RESULT_REF)
    expected_ready = all(bool(checks[name]["pass"]) for name in REVIEW_CHECKS)
    _require(review.get("result_ready") is expected_ready,
             f"VERIFY BLOCK: result_ready must be derived from the five independent checks "
             f"({expected_ready}), never self-declared")
    verdict = review_build({name: {"pass": bool(checks[name]["pass"]),
                                   "evidence": str(checks[name].get("evidence") or "")}
                            for name in REVIEW_CHECKS})
    paths.append(write_artifact(
        run_dir, "VERIFY", "review-report.artifact.json", "review_report", "adversarial-reviewer",
        verdict, ts, "blocked" if verdict["verdict"] == "BLOCK" else "approved"))
    if verdict["verdict"] == "BLOCK":
        raise GateBlock(f"{MODE} adversarial-review BLOCK: {verdict['blocking_reasons']}")

    gate_paths, frag = _gates(run_dir, "VERIFY", ts, bundles)
    return paths + gate_paths, {"review_gate": verdict["verdict"], "executed": True,
                                "execution_state": state["label"], **frag}


# --------------------------------------------------------------------------- REPORT

def _payload_or_none(run_dir, ref: str) -> Optional[dict]:
    path = Path(run_dir) / ref
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("payload")
    except (OSError, ValueError):
        return None


def _rows(items) -> str:
    return "\n".join(f"- {line}" for line in items) if items else "- (none)"


def _acceptance_sections(run_dir, state: dict) -> dict:
    """Every director-facing section, derived from the COMMITTED artifacts rather than stage memory.

    Rendering from disk is what makes the acceptance report deterministic and re-derivable: the same
    run directory always produces the same report, and a section can only claim what an artifact says.
    """
    matrix = _payload_or_none(run_dir, MATRIX_REF) or {}
    prereg = _payload_or_none(run_dir, PREREG_REF) or {}
    protocol = _payload_or_none(run_dir, PROTOCOL_REF) or {}
    freeze = _payload_or_none(run_dir, FREEZE_REF) or {}
    variables = matrix.get("variables") or {}
    conditions = matrix.get("conditions") or []

    design = "\n".join([
        f"**Research question.** {matrix.get('research_question') or '(no committed matrix)'}",
        "",
        f"**Freeze.** {freeze.get('title') or 'no design-freeze record committed'} — copied verbatim "
        f"from the planner and independently audited by variable-control-auditor, "
        f"train-test-alignment-auditor and metric-implementation-auditor, each of which had to prove "
        f"it audited this same frozen design.",
        "",
        f"**Variables.** studied: {', '.join(variables.get('studied') or []) or '(none)'} · "
        f"controlled: {', '.join(variables.get('controlled') or []) or '(none)'} · "
        f"frozen: {', '.join(variables.get('frozen') or []) or '(none)'}",
        "",
        "**Conditions.**",
        _rows([f"`{row.get('id')}`{' (baseline)' if row.get('baseline') else ''}: "
               f"{json.dumps(row.get('factors') or {}, ensure_ascii=False, sort_keys=True)}"
               for row in conditions]),
        "",
        "**Ranked hypotheses.**",
        _rows([f"rank {row.get('rank')} · `{row.get('condition_id')}`: {row.get('hypothesis')}"
               for row in matrix.get("ranked_batch") or []]),
        "",
        f"**Preregistered before any data.** primary metric `{prereg.get('primary_metric') or '?'}` · "
        f"{prereg.get('n_seeds_planned') or '?'} seeds · stopping rule: "
        f"{prereg.get('stopping_rule') or '(none)'} · analysis plan: "
        f"{prereg.get('analysis_plan') or '(none)'} · compiled configs: "
        f"{len(protocol.get('configs') or [])}",
        "",
        f"**Leakage declaration.** {matrix.get('leakage_declaration') or '(none recorded)'}",
    ])

    records = state.get("records") or []
    journal = _payload_or_none(run_dir, "evidence/EXECUTE/journal-entry.artifact.json")
    preflight = _payload_or_none(run_dir, "evidence/EXECUTE/preflight-report.artifact.json") or {}
    raw_rows = ((journal or {}).get("metrics_snapshot") or {}).get("raw_result_rows") or []
    execution = "\n".join([
        _panel_recipe.execution_boundary_section(state),
        "",
        f"**Run records.** {len(records)} committed — "
        f"planned: {sum(1 for r in records if r.get('status') == 'planned')} · "
        f"provisional: {sum(1 for r in records if r.get('status') == 'provisional')}. "
        f"Journal: {'present' if journal else 'none (nothing ran)'}. "
        f"Attested raw result rows: {len(raw_rows)}. "
        f"Executor import verified: {bool(state.get('executor_import_verified'))}.",
        "",
        "**Per condition.**",
        _rows([f"`{row.get('condition_id')}` — {row.get('status')}"
               + (f", metrics: {json.dumps(row.get('metrics') or {}, sort_keys=True)}"
                  if row.get("metrics") else ", no metrics (correct for a planned record)")
               for row in records]),
        "",
        f"**Preflight.** {preflight.get('verdict') or 'not run'}"
        + (f" — {preflight.get('violations')}" if preflight.get("violations") else ""),
    ])

    result = _payload_or_none(run_dir, RESULT_REF)
    if result:
        analysis = "\n".join([
            f"**Status.** {result.get('status')} · citable in the thesis: "
            f"{bool(result.get('can_cite_thesis'))} (a run-store result is never citable until "
            f"/promote-to-vault re-derives it).",
            "",
            "**Findings** (rebuilt by deterministic code from receipt-bound raw rows, not authored "
            "by any worker).",
            _rows([f"`{row.get('condition_id')}` {row.get('metric')} = {row.get('value')}"
                   + (f" vs baseline `{row.get('baseline_condition_id')}` "
                      f"{row.get('baseline_value')}" if row.get("baseline_value") is not None else "")
                   for row in result.get("findings") or []]),
            "",
            "**Caveats.**",
            _rows(result.get("caveats") or []),
            "",
            f"**Statistics.** {json.dumps(result.get('stats') or {}, ensure_ascii=False, sort_keys=True)}",
        ])
    else:
        analysis = (
            "**No result analysis exists.** Execution state is `"
            f"{state.get('label')}`, so no result summary was produced and no metric may be read from "
            "this run. What is committed is a frozen design and runnable scripts; the numbers a reader "
            "might expect here would have to come from an attested execution that has not happened. "
            "Any figure appearing elsewhere in this report is a target or a script parameter."
        )

    sanity = _payload_or_none(run_dir, "evidence/ANALYZE/sanity-verdict.artifact.json") or {}
    parity = _payload_or_none(run_dir, "evidence/EXECUTE/parity-verdict.artifact.json") or {}
    touch = _payload_or_none(run_dir, "evidence/EXECUTE/variable-touch-verdict.artifact.json") or {}
    deviation = _payload_or_none(
        run_dir, "evidence/ANALYZE/prereg-deviation-verdict.artifact.json") or {}
    checks = "\n".join([
        _rows([
            f"**Variable touch guard** (studied/frozen variables untouched by the build): "
            f"{touch.get('verdict') or 'not run'}"
            + (f" — {touch.get('violations')}" if touch.get("violations") else ""),
            f"**Train/test parity** (designed vs what actually ran): "
            f"{parity.get('verdict') or 'skipped — no journal, nothing ran'}"
            + (f" — {parity.get('violations')}" if parity.get("violations") else ""),
            f"**Result sanity** (ranges, directions, impossible values): "
            f"{sanity.get('verdict') or 'not applicable — no result to check'}"
            + (f" — {sanity.get('violations')}" if sanity.get("violations") else ""),
            f"**Preregistration deviation**: "
            f"{('PASS' if deviation.get('pass') else 'BLOCK') if deviation else 'not applicable'}"
            + (f" — {deviation.get('violations')}" if deviation.get("violations") else ""),
        ]),
        "",
        "Each verdict above is derived from violations by deterministic code; no worker set one.",
    ])

    review = _payload_or_none(run_dir, "evidence/VERIFY/review-report.artifact.json")
    if review:
        adversarial = "\n".join([
            f"**Verdict.** {review.get('verdict')}"
            + (f" — blocking: {review.get('blocking_reasons')}"
               if review.get("blocking_reasons") else ""),
            "",
            "**Five refutation checks**, run by a seat that did not design, run, or analyze this "
            "experiment.",
            _rows([f"`{name}`: {'pass' if (review.get('checks') or {}).get(name, {}).get('pass') else 'FAIL'}"
                   f" — {((review.get('checks') or {}).get(name) or {}).get('evidence') or 'no evidence'}"
                   for name in REVIEW_CHECKS]),
        ])
    else:
        adversarial = (
            "**No adversarial verification of a result was possible.** Execution state is `"
            f"{state.get('label')}`, so there is no result claim to refute. The reviewer recorded that "
            "the five refutation checks are not applicable rather than passing them vacuously — a "
            "design that has not run cannot earn a verification pass."
        )

    ready = bool(review and review.get("verdict") == "APPROVE-FREEZE")
    readiness = ("The result passed every independent check and is ready for the director to judge on "
                 "the science." if ready else
                 "NOT ready for an acceptance decision on results.")
    decision = "\n".join([
        "**What the director is being asked to accept.** Whether this experiment's evidence is strong "
        "enough to act on. This report is not a promotion: only /promote-to-vault admits anything into "
        "the knowledge base, and it re-derives every audit itself.",
        "",
        "**Gate inputs.**",
        _rows([
            f"Design frozen and audited three ways independently: "
            f"{'yes' if freeze else 'no freeze record'}",
            f"Execution really happened: {'yes' if state.get('executed') else 'NO'} "
            f"(`{state.get('label')}`)",
            f"Result summary exists: {'yes' if result else 'no'}",
            f"Adversarial verification: {review.get('verdict') if review else 'not applicable'}",
        ]),
        "",
        f"**Acceptance readiness.** {readiness}",
        "",
        "**What would change this.** "
        + ("Run the frozen protocol through the attested external executor, then re-run this mode: "
           "ANALYZE and VERIFY only become meaningful once receipts, raw result rows and a journal "
           "exist." if not state.get("executed")
           else "Independent replication on a second seed set, and an external held-out site, are the "
                "next things that would move this from provisional to citable."),
    ])

    return {"Frozen design": design, "Execution journal": execution, "Result analysis": analysis,
            "Sanity and parity checks": checks, "Adversarial verification": adversarial,
            "Acceptance decision inputs": decision}


def _report(run_dir, ts) -> tuple:
    state = _panel_recipe.execution_truth(run_dir)
    sections = _acceptance_sections(run_dir, state)
    rel = _panel_recipe.render_director_markdown(run_dir, MODE, sections, ts=ts,
                                                 lead="research-orchestrator")
    if state["executed"]:
        summary = (
            f"{MODE}: the frozen design ran. Findings were rebuilt from receipt-bound raw result rows, "
            f"every deterministic gate passed, and the result stays provisional and non-citable until "
            f"/promote-to-vault re-derives it. Acceptance report: {rel}")
        open_questions = ["Does the surviving claim replicate on an independent seed set and site?"]
    else:
        summary = (
            f"{MODE}: experiment PLAN only — execution state `{state['label']}`. Scripts and a frozen, "
            f"three-way-audited design exist; no result, no metric and no acceptance-on-results claim "
            f"does. The report says so in plain words. Acceptance report: {rel}")
        open_questions = ["Run the frozen protocol through the attested executor, then re-run "
                          "ANALYZE/VERIFY — until then there is nothing to accept on results."]
    paths, _frag = _panel_recipe.report_note(run_dir, ts, mode=MODE, summary=summary,
                                             references=[rel], open_questions=open_questions)
    gate_paths, frag = _gates(run_dir, "REPORT", ts, {"acceptance_report": sections})
    return paths + gate_paths, {"director_acceptance_report": rel,
                                "execution_state": state["label"],
                                "executed": bool(state["executed"]), **frag}


# --------------------------------------------------------------------------- recipe contract

def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for one stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DESIGN":
        return _design_dets(run_dir, ts, _bundles(run_dir, "DESIGN"))
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts, _bundles(run_dir, "EXECUTE"))
    if stage == "ANALYZE":
        return _analyze_dets(run_dir, ts, _bundles(run_dir, "ANALYZE"))
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts, _bundles(run_dir, "VERIFY"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
