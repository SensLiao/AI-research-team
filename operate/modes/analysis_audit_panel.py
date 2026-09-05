"""Operate recipe for the `analysis_audit_panel` mode (ANALYZE -> REPORT) — wave 2.

The registry's own productization gap names why this mode exists: *"Add an operated recipe that runs
diagnostic seats independently before synthesis."* Independence is the whole product. Eleven seats
diagnose the SAME analysis without seeing each other's conclusions, and only then do two resolver
seats reconcile them. Three consequences are wired deterministically rather than requested politely:

  * **Independence is declared and machine-checked, not promised.** Every judgment seat carries a
    scheduler `input_contract` whose `forbidden_inputs` names the other judgment seats' bundles, so
    the panel scheduler refuses a panel that would let one auditor read another's verdict, and the
    dispatch receipt records the boundary. `figure-generator` is the one deliberate exception in the
    read direction: its figure specs are the OBJECT under audit, so both figure auditors read them —
    and neither reads the other.

  * **Disagreement is surfaced, never resolved.** `_disagreements` derives contradictions between
    independent seats (and between a seat's declared judgment and the deterministic core that
    recomputes it) and renders BOTH positions to the director with an explicit
    `unresolved` marker. The machine does not pick a winner; picking one would silently destroy the
    only signal an independent panel buys you.

  * **Every calibrated claim must be traceable.** `_claim_evidence_gate` BLOCKs when a calibrated
    claim carries no resolvable `evidence_ref`. Resolvable means: a file that really exists under the
    run (outside every other seat's output) or a `[[slug]]` that really exists in the vault. Prose
    like "our results" is not evidence, and the calibrator may not launder another seat's conclusion
    into its own citation list.

Verdict boundaries this mode does NOT cross: a diagnostic finding — a sanity BLOCK, a failing
fairness verdict, an axis-truncation flag — is reported in "Blocking issues and repairs", never
turned into a run halt. Halting on the audited party's defect would hide the audit. The gates that
DO halt are the panel's own integrity gates (a missing seat, an unresolvable claim, a fabricated
figure id, a coverage gap) plus the three gates every operated mode carries.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ...tools import (
    baseline_audit,
    claim_calibration,
    compliance_audit,
    fairness_audit,
    figure_critique_check,
    goal_alignment_audit,
    integrity_scan,
    sanity_checker,
    stage_scorecard as scorecard_tool,
    variance_audit,
    viz_audit,
)

MODE = "analysis_audit_panel"
STAGE = "ANALYZE"
STAGES = _panel_recipe.stage_path(MODE)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

#: Where the director stages the analysis under audit. This mode audits work that was produced
#: elsewhere, so the panel needs one agreed read root instead of guessing at a layout.
AUDIT_INPUT_DIR = "inbox/analysis-under-audit"

_CORE = ("result-sanity-checker", "baseline-comparison-auditor", "variance-analyzer")
_VALIDITY = ("fairness-auditor", "compliance-auditor", "goal-alignment-checker",
             "failure-case-miner")
_FIGURE_PRODUCER = "figure-generator"
_FIGURE_AUDITORS = ("visualization-auditor", "figure-vlm-critic")
_CLAIM = "claim-strength-calibrator"
_RESOLVERS = ("quality-controller", "integrity-refusal-recommender")

#: The three registry panels' seats — what `quality-controller` must have covered (11).
DIAGNOSTIC_SEATS = _CORE + _VALIDITY + (_FIGURE_PRODUCER,) + _FIGURE_AUDITORS + (_CLAIM,)

#: The seats whose CONCLUSIONS must be mutually blind (10 = DIAGNOSTIC_SEATS minus the producer).
#: `figure-generator` emits the audited object, not a verdict about it, so it is excluded here and
#: only here — see the module docstring.
INDEPENDENT_JUDGMENT_SEATS = _CORE + _VALIDITY + _FIGURE_AUDITORS + (_CLAIM,)

#: (label, bundle_key, tier, depends_on) — the single source of truth for dispatch AND ingest.
_SEAT_SPECS = (
    # All three were `reason` (-> sonnet). They are quality seats: sanity-checking a result,
    # analysing its variance and auditing its compliance are exactly the judgments the director's
    # rule keeps on the frontier tier. Every seat in this panel grades someone else's numbers.
    ("result-sanity-checker", "result_summary", "audit", ()),
    ("baseline-comparison-auditor", "baseline_audit_inputs", "audit", ()),
    ("variance-analyzer", "variance_inputs", "audit", ()),
    ("fairness-auditor", "fairness_inputs", "audit", ()),
    ("compliance-auditor", "compliance_inputs", "audit", ()),
    ("goal-alignment-checker", "alignment_inputs", "audit", ()),
    ("failure-case-miner", "failure_inventory", "audit", ()),
    (_FIGURE_PRODUCER, "figure_spec_bundle", "reason", ()),
    (_CLAIM, "claim_calibration_inputs", "audit", ()),
    ("visualization-auditor", "viz_audit_inputs", "audit", (_FIGURE_PRODUCER,)),
    ("figure-vlm-critic", "figure_critique_inputs", "audit", (_FIGURE_PRODUCER,)),
    ("quality-controller", "coverage_review", "audit", DIAGNOSTIC_SEATS),
    ("integrity-refusal-recommender", "integrity_scan_input", "audit", DIAGNOSTIC_SEATS),
)

_BUNDLE_KEY = {label: key for label, key, _t, _d in _SEAT_SPECS}

#: A vault page reference, the only non-path evidence shape a calibrated claim may cite.
_SLUG_RE = re.compile(r"^\[\[([a-z0-9]+(?:-[a-z0-9]+)*)\]\]$")

#: Read roots that are never another seat's output: the audited analysis and its upstream evidence.
_SOURCE_INPUTS = (
    "task_frame.artifact.json",
    f"{AUDIT_INPUT_DIR}/**",
    "inbox/upstream-grounding.json",
    "evidence/DESIGN/**",
    "evidence/EXECUTE/**",
)

_HONESTY = (
    "HONESTY (hard): transcribe, never invent. Every number you report must be readable at a real "
    "path you name; never invent a metric value, a seed, a condition_id, a figure, a DOI or a "
    "[[slug]]. If the audited analysis does not state something you need, write that it is ABSENT "
    "rather than reconstructing it. Thin evidence is reported as thin, never padded. If a REPAIR "
    "ATTEMPT block is attached, fix EXACTLY what the gate names and nothing else, re-emit the "
    "COMPLETE bundle, never argue with the gate and never relax this paragraph."
)


# --------------------------------------------------------------------------- worker prompts

_SANITY_PROMPT = """You are the result-sanity checker on an INDEPENDENT analysis-audit panel. You \
did not produce the analysis under audit and you are not reviewing anyone else's verdict: you are \
the first person to read the raw numbers.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis under `{run_dir}/{audit_dir}/` (plus `evidence/EXECUTE/` when this run \
was threaded onto an upstream execution run). Transcribe EVERY reported metric value exactly as the \
analysis reports it — including the ones that look wrong. A deterministic screen (NaN/Inf, \
out-of-range against the domain profile, corrupt baselines, leakage smell) runs on what you \
transcribe; your job is faithful coverage, not a verdict.

{honesty}

Write ONLY this JSON to `{out}`:
{{"result_summary": {{
  "findings": [{{"metric": "<exact metric name as reported>", "value": 0.0,
                 "condition_id": "<exact condition id>", "baseline_value": 0.0,
                 "source_ref": "<run-relative path where this number is written>"}}],
  "caveats": ["<what the analysis itself admits>"],
  "sources_read": ["<run-relative path>"]}}}}
`findings` has a FLOOR of every metric/condition pair the analysis reports and NO upper bound — one \
entry per pair, all conditions, all metrics, all folds/subsets that are reported separately. Do not \
drop a finding to keep the list short; a partial transcription silently exonerates the analysis. \
Use `baseline_value: null` only when no baseline is reported for that pair. Return one line: \
findings transcribed + metrics covered + files read."""

_BASELINE_PROMPT = """You are the baseline-comparison auditor on an INDEPENDENT analysis-audit \
panel. You did not run these experiments and you are NOT reviewing another auditor's finding — your \
question is your own: was the baseline given the same conditions as the method?

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's configuration under `{run_dir}/{audit_dir}/` (and \
`evidence/DESIGN/`, `evidence/EXECUTE/` when present). Reconstruct the experiment matrix as the \
analysis actually declares it, one entry per condition, with the comparison-critical factors spelled \
out: `data_hash` / `data_source`, the compute budget key it really uses (`epochs`, `max_epochs`, \
`steps`, `total_steps`, `iterations`, `flops`, ...), `metric_impl_ref`, `primary_metric`, and \
`postprocess`. A factor the analysis never declares must be OMITTED, not guessed — absence is itself \
an auditable asymmetry and the deterministic comparator flags it for you.

{honesty}

Write ONLY this JSON to `{out}`:
{{"baseline_audit_inputs": {{
  "baseline_condition_id": "<the condition the analysis calls the baseline>",
  "method_condition_id": "<the condition it calls the method>",
  "experiment_matrix": {{"research_question": "<the RQ as written>",
    "conditions": [{{"id": "<condition id>",
      "factors": {{"data_source": "...", "epochs": 0, "metric_impl_ref": "...",
                   "primary_metric": "...", "postprocess": "..."}}}}]}},
  "notes": "<what you could not verify and where you looked>",
  "sources_read": ["<run-relative path>"]}}}}
`conditions` has a FLOOR of every condition the analysis declares and no upper bound — include the \
ablations and the extra baselines, not just the headline pair. Return one line: conditions \
reconstructed + factors found + factors absent."""

_VARIANCE_PROMPT = """You are the variance analyst on an INDEPENDENT analysis-audit panel. Nobody \
hands you a variance estimate: you rebuild it from the per-seed runs, and you must NOT read any \
other seat's bundle.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's per-run records under `{run_dir}/{audit_dir}/` (and \
`evidence/EXECUTE/` when present). One entry per RUN, carrying its own `seed` and its own `metrics` \
map. Re-running one seed is not two seeds — record the seed exactly as logged so the deterministic \
counter can collapse duplicates itself. Also record, verbatim, the stability wording the analysis \
CLAIMS ("stable", "consistent across seeds", ...) in `declared_stability_label`; the panel compares \
your transcription against the seed count deterministically, and a mismatch is reported to the \
director as a disagreement.

{honesty}

Write ONLY this JSON to `{out}`:
{{"variance_inputs": {{
  "condition_id": "<the condition these runs belong to>",
  "run_records": [{{"condition_id": "...", "seed": 0,
                    "metrics": {{"<metric>": 0.0}},
                    "source_ref": "<run-relative path>"}}],
  "declared_stability_label": "stable|unstable|insufficient_data|null",
  "notes": "<seeds you could not find, logs that were missing>",
  "sources_read": ["<run-relative path>"]}}}}
`run_records` has a FLOOR of every run the analysis logged and no upper bound. If only one seed \
exists, say so with one record — do not manufacture siblings. Return one line: runs found + \
distinct seeds + metrics per run."""

_FAIRNESS_PROMPT = """You are the fairness auditor on an INDEPENDENT analysis-audit panel. You did \
not produce the results and you may NOT read another auditor's bundle — your subgroup reading has to \
stand on the raw records alone.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis under `{run_dir}/{audit_dir}/` (and `evidence/EXECUTE/` when present) and \
transcribe results AT SUBGROUP GRANULARITY: for every finding and every run, carry the `stratum` (the \
subgroup VALUE, e.g. a site, an anatomy region, a scanner, a demographic bucket) and `stratum_key` \
(the dimension name) whenever the analysis reports them. If the analysis only reports aggregates, \
transcribe the aggregates and say so — the deterministic checker then flags subgroup fairness as \
unverifiable, which is the honest outcome and must not be papered over with an invented stratum.

{honesty}

Write ONLY this JSON to `{out}`:
{{"fairness_inputs": {{
  "result_summary": {{"findings": [{{"metric": "...", "value": 0.0, "condition_id": "...",
     "stratum": "<subgroup value or omit>", "stratum_key": "<dimension name or omit>"}}]}},
  "run_records": [{{"condition_id": "...", "stratum": "...", "stratum_key": "...",
                    "metrics": {{"<metric>": 0.0}}}}],
  "notes": "<which subgroups are reported, which are missing, and where you looked>",
  "sources_read": ["<run-relative path>"]}}}}
Both arrays are FLOORED at everything the analysis reports per subgroup, with no upper bound — one \
entry per (subgroup x condition x metric). Return one line: strata found + strata absent + \
aggregate-only yes/no."""

_COMPLIANCE_PROMPT = """You are the compliance auditor on an INDEPENDENT analysis-audit panel. Your \
single question is mechanical and yours alone: was everything that was DECLARED actually RUN, and was \
anything run that was never declared? Do not read another seat's bundle.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's plan and its run logs under `{run_dir}/{audit_dir}/` (and \
`evidence/DESIGN/`, `evidence/EXECUTE/` when present). Transcribe the declared condition list from \
the plan and, separately, the condition ids that actually have a run record. Keep the two lists \
independent — do not reconcile them yourself; the deterministic comparator does that and names both \
directions (declared-but-not-run, run-but-not-declared).

{honesty}

Write ONLY this JSON to `{out}`:
{{"compliance_inputs": {{
  "experiment_matrix": {{"conditions": [{{"id": "<declared condition id>"}}]}},
  "run_records": [{{"condition_id": "<condition id that really has a run log>",
                    "source_ref": "<run-relative path>"}}],
  "notes": "<where the plan lives, where the logs live, what is ambiguous>",
  "sources_read": ["<run-relative path>"]}}}}
Both lists are FLOORED at everything present, with no upper bound; include ablations, seeds-only \
reruns and abandoned conditions. Return one line: declared + logged + any you could not classify."""

_ALIGNMENT_PROMPT = """You are the goal-alignment checker on an INDEPENDENT analysis-audit panel. \
You are not grading the science; you are checking that the CLAIMS the analysis makes are the claims \
its experiments can support. You may NOT read another seat's bundle.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis under `{run_dir}/{audit_dir}/`. Transcribe (a) the research question and \
headline claims IN THE ANALYSIS'S OWN WORDS — generalization, out-of-distribution, external, \
transfer, robustness, state-of-the-art, beats, outperforms wording matters and must be preserved \
verbatim, because the deterministic checker keys on it; and (b) the condition ids and the finding \
condition ids, with the tags the analysis really uses (`external`, `ood`, `held-out`, \
`domain_shift`, `baseline`, ...). Never re-word a claim into something safer and never attach a tag \
the analysis did not use — either move silently converts an unsupported claim into a supported one.

{honesty}

Write ONLY this JSON to `{out}`:
{{"alignment_inputs": {{
  "experiment_matrix": {{"research_question": "<RQ and headline claims, verbatim>",
    "conditions": [{{"id": "<condition id>", "factors": {{"baseline": false}}}}]}},
  "result_summary": {{"findings": [{{"metric": "...", "value": 0.0, "condition_id": "..."}}]}},
  "notes": "<claims you found, where each is written, which have no matching condition>",
  "sources_read": ["<run-relative path>"]}}}}
The claim text is FLOORED at every headline claim the analysis makes — concatenate them all into \
`research_question`; a claim you leave out is a claim that escapes the check. Return one line: \
claims transcribed + conditions found + tags found."""

_FAILURE_PROMPT = """You are the failure-case miner on an INDEPENDENT analysis-audit panel. Averages \
hide failures; your job is the individual cases the analysis's summary table does not show. Do not \
read another seat's bundle — nobody hands you a failure list.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's per-case outputs, logs, error tables and qualitative sections under \
`{run_dir}/{audit_dir}/` (and `evidence/EXECUTE/` when present). Mine concrete, individually \
identifiable failures and TYPE each one (false_positive, false_negative, boundary_error, \
connectivity_failure, shape_mismatch, outlier, oom, crash, other). Point each at the specific case \
and the metric context that shows it. A hypothesized cause is welcome but must be labelled as a \
hypothesis, not a finding.

{honesty}

Write ONLY this JSON to `{out}`:
{{"failure_inventory": {{
  "condition_id": "<the condition this inventory covers>",
  "failures": [{{"type": "<typed label>", "description": "<what went wrong, concretely>",
                 "case_ref": "<sample/image/run id or run-relative path, null if unknown>",
                 "metric_context": "<e.g. Dice=0.12 on case 042, null if unknown>",
                 "hypothesized_cause": "<advisory, unverified, or null>"}}],
  "summary": "<the failure pattern you see across the cases>",
  "sources_read": ["<run-relative path>"]}}}}
`failures` has a FLOOR of 6 typed cases when the material supports six and NO upper bound — mine \
every failure you can actually point at. If the audited analysis genuinely publishes no per-case \
material, emit `failures: []` and say exactly that in `summary`; an empty inventory is reported to \
the director as a coverage gap, which is honest. Never invent a case to fill the floor. Return one \
line: cases mined + types seen + per-case material available yes/no."""

_FIGURE_PROMPT = """You are the figure engineer on an INDEPENDENT analysis-audit panel. You are NOT \
an auditor here and you must not judge: you produce the machine-readable description of the figures \
the audited analysis actually shows, so that two independent auditors can audit them. Do not read \
any other seat's bundle.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's figures, plotting code and captions under `{run_dir}/{audit_dir}/`. For \
each figure, describe it AS DRAWN, not as it should have been drawn. The axis bounds are the whole \
point: if a bar chart's y-axis starts at 0.94, record `y_axis: {{"min": 0.94}}` — do not normalise it \
to zero, and do not omit it. Record `y_axis.error_bars` only when the figure really draws them, and \
`y_axis.secondary` only when a second scale really exists.

{honesty}

Write ONLY this JSON to `{out}`:
{{"figure_spec_bundle": {{
  "run_ref": "<run-relative path of the analysis this describes, or null>",
  "figures": [{{"figure_id": "<stable id, e.g. fig2_dice_by_condition>",
    "figure_type": "bar|boxplot|line|scatter|table|heatmap|other",
    "title": "<title as printed>", "data_source": "<run-relative path or condition id plotted>",
    "x_axis": {{"label": "...", "min": null}},
    "y_axis": {{"label": "...", "min": 0.0, "max": null, "error_bars": null, "secondary": null}},
    "conditions": ["<condition id>"], "metrics": ["<metric name>"],
    "caption": "<caption as printed>", "notes": "<what the figure omits>"}}]}}
`figures` has a FLOOR of every figure and results table the analysis presents, including \
supplementary ones, with no upper bound. Every `figure_id` you mint is the id the auditors will \
cite, so keep them stable and distinct. Return one line: figures described + axis mins recorded + \
figures you could not find source data for."""

_VIZ_AUDIT_PROMPT = """You are the visualization auditor on an INDEPENDENT analysis-audit panel. You \
did not draw these figures. There is a SECOND, separate figure critic on this panel and you will \
never see its bundle, nor it yours — that is deliberate: the director wants two independent readings \
and will be shown where they disagree, so do not try to guess or match what the other critic would \
say.

{north_star}

Read exactly two things: the figure specifications at \
`{run_dir}/inbox/ANALYZE.figure-generator.bundle.json` (the OBJECT you audit) and the audited \
analysis under `{run_dir}/{audit_dir}/`. Judge whether each figure's visual encoding could mislead a \
reader about the size of the effect: truncated or cherry-picked axes, a dual scale, absent error bars \
on a claim about a small delta, a colour/ordering choice that manufactures a gap.

A deterministic checker independently recomputes axis truncation against the domain profile's valid \
metric ranges. Your `declared_clean` bit is compared against it, and a mismatch is shown to the \
director. So set `declared_clean` to what you actually believe, not to what you think will match.

{honesty}

Write ONLY this JSON to `{out}`:
{{"viz_audit_inputs": {{
  "declared_clean": false,
  "per_figure": [{{"figure_id": "<an id from the figure spec bundle>",
    "concern": "misleading_axis|truncated_axis|dual_axis_confusion|missing_error_bars|cherry_picked_range|unclear|ok",
    "severity": "info|warn|critical",
    "detail": "<what a reader would wrongly conclude, and why>",
    "evidence_ref": ["<figure_spec/<figure_id>/... or a run-relative path>"]}}],
  "notes": "<figures you could not assess and why>"}}}}
`per_figure` is FLOORED at one entry for EVERY figure_id in the spec bundle — including the clean \
ones (`concern: "ok"`), because a figure you silently skip is indistinguishable from a figure you \
cleared. No upper bound: raise every concern you have, several per figure if warranted. Every \
`figure_id` must exist in the spec bundle; an id nobody produced is a hard BLOCK. Return one line: \
figures audited + concerns raised + your clean/not-clean call."""

_FIGURE_CRITIC_PROMPT = """You are the second, independent figure critic on an analysis-audit panel. \
A different auditor is reviewing the same figures from the visual-integrity angle. You will NEVER see \
its bundle and it will never see yours. The director is shown BOTH readings and every place they \
disagree, so an honest divergence is valuable output — matching the other seat is not a goal and \
guessing at it would destroy the only reason you were dispatched.

{north_star}

Read exactly two things: the figure specifications at \
`{run_dir}/inbox/ANALYZE.figure-generator.bundle.json` and the audited analysis under \
`{run_dir}/{audit_dir}/`. Read each figure as a sceptical reviewer meeting it for the first time: \
does the figure support the claim its caption makes? Is the comparison it invites the comparison the \
experiment actually ran? Does it show variability, or only means? Does the visual emphasis match the \
effect size?

Note the honest ceiling: no image is rendered here, so you are critiquing the SPECIFICATION and the \
caption, not pixels. Say so when a concern would need the rendered image to confirm.

{honesty}

Write ONLY this JSON to `{out}`:
{{"figure_critique_inputs": {{
  "per_figure": [{{"figure_id": "<an id from the figure spec bundle>",
    "finding_type": "misleading_axis|truncated_axis|dual_axis_confusion|missing_error_bars|cherry_picked_range|unclear|ok",
    "severity": "info|warn|critical",
    "detail": "<the misreading this figure invites, and what would fix it>",
    "evidence_ref": ["<figure_spec/<figure_id>/... or a run-relative path>"]}}],
  "notes": "<what you could not judge without the rendered image>"}}}}
`per_figure` is FLOORED at one entry for EVERY figure_id in the spec bundle, clean ones included \
(`finding_type: "ok"`), with no upper bound on findings per figure. Every `figure_id` must exist in \
the spec bundle; a fabricated id is a hard BLOCK. Return one line: figures critiqued + findings by \
severity + how many needed pixels you did not have."""

_CALIBRATOR_PROMPT = """You are the claim-strength calibrator on an INDEPENDENT analysis-audit panel. \
You may NOT read any other seat's bundle — in particular you do not get the variance analyst's \
report. You re-derive the numbers you need from the raw per-seed material yourself, which is the \
point: two seats reach the "is this improvement real?" question independently and the director is \
shown where they disagree.

    AUDIT REQUEST: {request}

{north_star}

Read the audited analysis's claims AND its raw per-seed results under `{run_dir}/{audit_dir}/` (and \
`evidence/EXECUTE/` when present). For every quantitative claim the analysis makes, extract the \
claim verbatim, the metric, the `delta` it asserts over its baseline, and a `variance` you compute \
from the per-seed spread (std or half-CI) — not one you assume. A deterministic calibrator recomputes \
the strength label from delta vs variance, so `original_strength` must record the strength the \
ANALYSIS asserts, so that the downgrade is visible.

EVIDENCE IS MANDATORY AND CHECKED. Every claim needs at least one `evidence_ref` that resolves to a \
file that really exists under this run (a results file, a log, a per-seed dump — name it \
run-relative) or a `[[slug]]` page that really exists in the vault. Prose such as "our results", \
"Table 2" or "as reported" does NOT resolve and is a hard BLOCK on the whole panel. Do not cite \
another seat's bundle or artifact; those are not admissible here.

{honesty}

Write ONLY this JSON to `{out}`:
{{"claim_calibration_inputs": {{
  "source_ref": "<run-relative path of the claim source, or null>",
  "claims": [{{"original_claim": "<the claim verbatim>", "metric": "<metric or null>",
    "delta": 0.0, "variance": 0.0, "original_strength": "strong|moderate|marginal|inconclusive",
    "evidence_ref": ["<run-relative path that exists, or [[slug]]>"]}}],
  "notes": "<claims whose delta or variance is simply not derivable, named individually>"}}}}
`claims` has a FLOOR of 8 when the analysis makes eight quantitative claims, and NO upper bound — \
every abstract sentence, every headline number, every "significantly better" is a claim. Use \
`delta: null` / `variance: null` when the material genuinely does not support a number (the \
calibrator then downgrades to inconclusive, which is the honest result); never fill them with a \
guess to avoid a downgrade. Return one line: claims extracted + variances computed + claims left \
uncalibratable."""

_QUALITY_PROMPT = """You are the quality controller on an analysis-audit panel. Eleven seats have \
just diagnosed the same analysis WITHOUT seeing each other's work. You are the first reader allowed \
to see all of it, and your job is coverage and contradiction — NOT arbitration. You do not overrule a \
seat, you do not average them, and you do not pick a winner: the director is shown both sides of \
every disagreement.

{north_star}

Read all eleven bundles (they are listed in your scheduler_contract, under \
`{run_dir}/inbox/ANALYZE.<seat>.bundle.json`) plus the audited analysis under \
`{run_dir}/{audit_dir}/` when you need the source.

Two deterministic checks bind you. First, COVERAGE: you must name every one of the eleven seats \
below, and a seat you omit is a hard BLOCK — silence about a seat is how an unread diagnostic \
disappears. Second, the stage scorecard is derived from the seats' own verdicts, not from your \
opinion, so a pass you assert over a failing verdict is structurally impossible.

The eleven seats: {seat_list}

{honesty}

Write ONLY this JSON to `{out}`:
{{"coverage_review": {{
  "seats_reviewed": [{{"seat": "<exact seat label>", "reviewed": true,
    "verdict_read": "PASS|FAIL|ADVISORY|EMPTY",
    "note": "<what this seat established, in one sentence>"}}],
  "disagreements": [{{"topic": "<the single conclusion two seats disagree about>",
    "seat_a": "<label>", "position_a": "<what a concluded, in a's terms>",
    "seat_b": "<label>", "position_b": "<what b concluded>",
    "why_it_matters": "<what changes for the paper depending on who is right>"}}],
  "unreviewed_gaps": ["<a diagnostic you believe is MISSING from this panel entirely>"],
  "notes": "<your overall read of whether the analysis supports its claims>"}}}}
`seats_reviewed` is exactly the eleven, no more, no fewer. `disagreements` is FLOORED at every real \
contradiction you can see and has no upper bound; the panel also derives disagreements \
deterministically and shows the director both your list and the derived one, so report a \
contradiction even if you suspect the machine already caught it. Return one line: seats covered + \
disagreements found + your headline concern."""

_INTEGRITY_PROMPT = """You are the integrity-refusal recommender on an analysis-audit panel. You are \
ADVISORY BY CONSTRUCTION: you can recommend that a human pause, and you can never block, authorize, \
or decide. The director's gates remain the only deciders. Say what you see and stop there.

{north_star}

Read all eleven diagnostic bundles (listed in your scheduler_contract, under \
`{run_dir}/inbox/ANALYZE.<seat>.bundle.json`) and the audited analysis under \
`{run_dir}/{audit_dir}/`. You are looking for the integrity risks the other gates structurally \
cannot see:
  - a number asserted with NO citation at all (the citation gates only inspect refs that exist);
  - a result asserted with no evidence whatsoever, where an honest refusal was the right answer;
  - a fabricated-data smell: values too clean, placeholder-looking, or impossible to have measured;
  - completion pressure: a sign that a confident answer was traded for an honest one.

{honesty}

Write ONLY this JSON to `{out}`:
{{"integrity_scan_input": {{
  "claims": [{{"claim_id": "IC-1", "text": "<the claim as the analysis states it>",
    "evidence_ref": ["<run-relative path or [[slug]] — omit or leave empty when there really is none>"],
    "asserts_result": true}}],
  "extra_flags": [{{"kind": "fabricated_data_smell|completion_pressure",
    "locus": "<claim_id, seat label, or run-relative path>",
    "severity": "low|medium|high",
    "detail": "<the specific tell you saw, not a general worry>"}}],
  "notes": "<what you deliberately did NOT flag, and why>"}}}}
`claims` is FLOORED at every result-asserting sentence you can find, with no upper bound, and an \
uncited claim MUST be recorded with an empty `evidence_ref` rather than skipped — the missing \
citation is the finding. `extra_flags` uses ONLY the two kinds above (unsupported numbers and \
missing-evidence refusals are derived from `claims` for you); each flag needs a concrete tell. \
Return one line: claims scanned + uncited claims + extra flags raised."""

_PROMPTS = {
    "result-sanity-checker": _SANITY_PROMPT,
    "baseline-comparison-auditor": _BASELINE_PROMPT,
    "variance-analyzer": _VARIANCE_PROMPT,
    "fairness-auditor": _FAIRNESS_PROMPT,
    "compliance-auditor": _COMPLIANCE_PROMPT,
    "goal-alignment-checker": _ALIGNMENT_PROMPT,
    "failure-case-miner": _FAILURE_PROMPT,
    _FIGURE_PRODUCER: _FIGURE_PROMPT,
    "visualization-auditor": _VIZ_AUDIT_PROMPT,
    "figure-vlm-critic": _FIGURE_CRITIC_PROMPT,
    _CLAIM: _CALIBRATOR_PROMPT,
    "quality-controller": _QUALITY_PROMPT,
    "integrity-refusal-recommender": _INTEGRITY_PROMPT,
}


# --------------------------------------------------------------------------- dispatch

def _bundle_rel(label: str) -> str:
    return f"inbox/{STAGE}.{label}.bundle.json"


def _seats(run_dir, request: str = "", *, prompts: bool = True) -> list:
    """The 13 declared seats. `prompts=False` builds the ingest-only view (labels + bundle keys)."""
    north_star = _shared.north_star_block(run_dir) if prompts else ""
    seat_list = ", ".join(DIAGNOSTIC_SEATS)
    out = []
    for label, key, tier, depends_on in _SEAT_SPECS:
        prompt = ""
        if prompts:
            prompt = _PROMPTS[label].format(
                request=request, north_star=north_star, run_dir=run_dir,
                audit_dir=AUDIT_INPUT_DIR, honesty=_HONESTY, seat_list=seat_list,
                out=f"{run_dir}/{_bundle_rel(label)}")
        out.append(_panel_recipe.Seat(label=label, prompt=prompt, bundle_key=key, tier=tier,
                                     depends_on=tuple(depends_on)))
    return out


def _input_contract(label: str) -> dict:
    """The declared read boundary that makes independence machine-checkable, not merely requested."""
    if label in _RESOLVERS:
        return {"allowed_inputs": list(_SOURCE_INPUTS)
                + [_bundle_rel(seat) for seat in DIAGNOSTIC_SEATS] + ["evidence/ANALYZE/**"],
                "forbidden_inputs": [], "blind": False}
    readable = [_bundle_rel(_FIGURE_PRODUCER)] if label in _FIGURE_AUDITORS else []
    blind_to = [_bundle_rel(seat) for seat in INDEPENDENT_JUDGMENT_SEATS if seat != label]
    if label == _FIGURE_PRODUCER:
        blind_to = [_bundle_rel(seat) for seat in INDEPENDENT_JUDGMENT_SEATS]
    return {"allowed_inputs": list(_SOURCE_INPUTS) + readable,
            "forbidden_inputs": blind_to, "blind": True}


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The 13-seat panel: 9 blind diagnostics, then 2 figure auditors, then 2 resolvers."""
    if stage != STAGE:
        return None  # REPORT is deterministic
    spec = _panel_recipe.panel(
        run_dir, stage, MODE, _seats(run_dir, request), model_policy=model_policy,
        panel_note=(
            "Wave 1: nine seats diagnose the SAME analysis blind to each other (sanity, baseline "
            "symmetry, variance, fairness, compliance, goal alignment, failure cases, figure specs, "
            "claim calibration). Wave 2: two figure auditors read the figure SPECS — the object under "
            "audit — and never each other. Wave 3: quality-controller and integrity-refusal-"
            "recommender are the first seats allowed to see everything; they reconcile coverage and "
            "name contradictions, and they never pick a winner. Every disagreement reaches the "
            "director as two positions, not one verdict."))
    for worker in spec["workers"]:
        worker["input_contract"] = _input_contract(worker["label"])
    return spec


# --------------------------------------------------------------------------- deterministic helpers

def _normalized(run_dir, agent: str, artifact_type: str, payload):
    """Project one seat payload into its delivery schema; a real gap targets its OWNING seat."""
    value, errors, _report = _shared.normalize_worker_payload(
        run_dir, STAGE, agent, artifact_type, payload, label=artifact_type)
    if errors:
        raise TargetedGateBlock(
            f"{MODE} {agent} {artifact_type} needs a supplement after normalization: {errors}",
            [{"defect_id": f"analysis-audit-{artifact_type.replace('_', '-')}",
              "category": "schema-semantic-gap", "location": f"{STAGE}/{artifact_type}",
              "summary": "; ".join(str(e) for e in errors)[:4000],
              "target_agents": [agent], "refresh_agents": list(_RESOLVERS)}])
    return value


def _resolvable_evidence(run_dir, ref: str, vault_slugs) -> bool:
    """A claim ref resolves iff it points at something real that is NOT another seat's output.

    Two admissible shapes: a run-relative (or run-internal absolute) file that exists outside
    `inbox/*.bundle.json` and `evidence/`, or a `[[slug]]` page the vault really has. An unreachable
    vault degrades to accepted-with-a-warning (offline-safe); a slug the vault denies does not.
    """
    text = str(ref or "").strip()
    if not text:
        return False
    slug = _SLUG_RE.match(text)
    if slug:
        return vault_slugs is None or slug.group(1) in vault_slugs
    root = Path(run_dir).resolve()
    candidate = Path(text)
    try:
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=True)
        rel = resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return False
    if rel.startswith("evidence/") or (rel.startswith("inbox/") and rel.endswith(".bundle.json")):
        return False
    return resolved.is_file()


def _claim_evidence_gate(run_dir, claims: list, vault_slugs) -> list:
    """Every calibrated claim must trace to a specific, resolvable evidence_ref — or the panel BLOCKs."""
    unsupported = []
    for index, claim in enumerate(claims, start=1):
        refs = claim.get("evidence_ref")
        refs = [refs] if isinstance(refs, str) else list(refs or [])
        resolved = [r for r in refs if _resolvable_evidence(run_dir, r, vault_slugs)]
        if not resolved:
            unsupported.append(
                f"claim #{index} {str(claim.get('original_claim') or '')[:90]!r}: "
                f"evidence_ref {refs!r} resolves to nothing readable")
    if unsupported:
        raise GateBlock(
            f"{MODE} claim-evidence BLOCK — a calibrated claim must be traceable to a specific "
            f"piece of evidence: {unsupported}. Cite a run-relative file that exists or a real "
            f"[[slug]]; prose references and other seats' bundles are not evidence.")
    return [{"claim_index": i, "refs": list(c.get("evidence_ref") or [])}
            for i, c in enumerate(claims, start=1)]


def _figure_findings(bundle: dict, key: str, known_ids: set, agent: str) -> list:
    """Seat-authored per-figure findings, with a fabricated figure_id treated as a hard BLOCK."""
    rows, unknown = [], []
    for row in (bundle.get(key) or []):
        figure_id = str(row.get("figure_id") or "").strip()
        if figure_id not in known_ids:
            unknown.append(figure_id or "<blank>")
            continue
        finding_type = str(row.get("finding_type") or row.get("concern") or "unclear")
        refs = [str(r) for r in (row.get("evidence_ref") or []) if str(r).strip()]
        rows.append({"figure_id": figure_id, "finding_type": finding_type,
                     "severity": str(row.get("severity") or "info"),
                     "evidence_ref": refs or [f"figure_spec/{figure_id}"],
                     "detail": str(row.get("detail") or "")})
    if unknown:
        raise GateBlock(
            f"{MODE} {agent} cites figure_id(s) {unknown} that figure-generator never produced "
            f"(known: {sorted(known_ids)}) — a finding about a figure nobody drew is a fabricated "
            f"reference.")
    return rows


def _disagreements(sanity, baseline, variance, declared_stability, viz, declared_clean,
                   viz_rows, critic_rows, calibrated) -> list:
    """Contradictions between INDEPENDENT positions. Both sides are kept; no winner is chosen.

    The two figure seats are compared on their OWN rows, never on the merged artifact: the shared
    deterministic structural findings would otherwise manufacture agreement neither seat reached.
    """
    out = []

    def add(topic, a, pa, b, pb, why):
        out.append({"topic": topic, "seat_a": a, "position_a": pa, "seat_b": b, "position_b": pb,
                    "why_it_matters": why, "resolution": "UNRESOLVED — shown to the director"})

    if sanity.get("leakage_smell") and baseline.get("clean"):
        add("is the reported improvement plausibly earned?",
            "result-sanity-checker", "leakage smell: the jump over baseline is implausibly large",
            "baseline-comparison-auditor", "no asymmetry found — the comparison looks fair",
            "either the win is real and unusually large, or the two seats are looking at different "
            "conditions; one of them is wrong and the paper's headline depends on which.")
    derived_stability = str(variance.get("stability_label") or "")
    declared = str(declared_stability or "").strip()
    if declared and derived_stability and declared != derived_stability:
        add("are the results stable across seeds?",
            "variance-analyzer (transcribed claim)", f"the analysis calls the result {declared!r}",
            "variance-analyzer (deterministic recount)",
            f"{variance.get('n_seeds')} distinct seed(s) -> {derived_stability!r}",
            "a stability word the seed count cannot support is an overclaim in the abstract.")
    if declared_clean is True and not viz.get("clean", True):
        add("do the figures mislead about effect size?",
            "visualization-auditor (own judgment)", "declared the figures clean",
            "visualization-auditor (deterministic axis check)",
            f"axis truncation flagged on {[f['figure_id'] for f in viz['axis_truncation_flags']]}",
            "a truncated axis the auditor cleared is a figure that ships exaggerated.")
    seat_concerns = {row["figure_id"]: row["finding_type"] for row in viz_rows
                     if row["finding_type"] != "ok"}
    critic_concerns = {row["figure_id"]: row["finding_type"] for row in critic_rows
                       if row["finding_type"] != "ok"}
    for figure_id in sorted(set(seat_concerns) | set(critic_concerns)):
        left, right = seat_concerns.get(figure_id), critic_concerns.get(figure_id)
        if bool(left) != bool(right):
            add(f"figure {figure_id}: is it misleading?",
                "visualization-auditor", left or "raised no concern",
                "figure-vlm-critic", right or "raised no concern",
                "two independent readings of the same figure diverged; the director decides whether "
                "the figure is redrawn.")
    if variance.get("seed_count_insufficient"):
        strong = [row["original_claim"][:90] for row in calibrated.get("calibrated") or []
                  if row.get("strength") == "strong"]
        if strong:
            add("can a 'strong' claim stand on this seed count?",
                "claim-strength-calibrator", f"{len(strong)} claim(s) calibrated strong: {strong}",
                "variance-analyzer",
                f"seed count insufficient ({variance.get('n_seeds')} distinct seed(s))",
                "the calibrator's own delta/variance said strong while the seed count says the "
                "variance estimate is not yet trustworthy.")
    return out


def _coverage_gate(review: dict) -> list:
    """The registry's cross-panel coverage check: the controller may not silently drop a seat."""
    rows = [row for row in (review.get("seats_reviewed") or []) if isinstance(row, dict)]
    named = {str(row.get("seat") or "").strip() for row in rows}
    missing = [seat for seat in DIAGNOSTIC_SEATS if seat not in named]
    unreviewed = [str(row.get("seat")) for row in rows if row.get("reviewed") is not True]
    stray = sorted(named - set(DIAGNOSTIC_SEATS) - {""})
    if missing or unreviewed:
        raise GateBlock(
            f"{MODE} cross-panel coverage BLOCK — quality-controller left diagnostic seat(s) "
            f"{missing} unnamed and {unreviewed} marked not-reviewed. A synthesis that skips an "
            f"independent diagnostic is how a finding disappears; name all "
            f"{len(DIAGNOSTIC_SEATS)} seats.")
    return stray


def _verdict_rows(sanity, baseline, variance, fairness, compliance, alignment,
                  failure_rows, viz, critique_rows) -> list:
    """The ANALYZE dimension verdicts, read from the artifacts — never from the controller's opinion."""
    return [
        {"dimension": "result_sanity", "pass": sanity["verdict"] == "PASS",
         "evidence_ref": "evidence/ANALYZE/sanity-verdict.artifact.json"},
        {"dimension": "baseline_symmetry", "pass": bool(baseline["clean"]),
         "evidence_ref": "evidence/ANALYZE/baseline-audit-report.artifact.json"},
        {"dimension": "variance_sufficiency", "pass": not variance["seed_count_insufficient"],
         "evidence_ref": "evidence/ANALYZE/variance-report.artifact.json"},
        {"dimension": "fairness", "pass": bool(fairness["pass"]),
         "evidence_ref": "evidence/ANALYZE/fairness-verdict.artifact.json"},
        {"dimension": "compliance", "pass": bool(compliance["pass"]),
         "evidence_ref": "evidence/ANALYZE/compliance-verdict.artifact.json"},
        {"dimension": "goal_alignment", "pass": bool(alignment["pass"]),
         "evidence_ref": "evidence/ANALYZE/goal-alignment-verdict.artifact.json"},
        {"dimension": "failure_case_coverage", "pass": bool(failure_rows),
         "evidence_ref": "evidence/ANALYZE/failure-inventory.artifact.json"},
        {"dimension": "figure_integrity", "pass": bool(viz["clean"]) and not any(
            row["severity"] == "critical" for row in critique_rows),
         "evidence_ref": "evidence/ANALYZE/viz-audit-report.artifact.json"},
    ]


# --------------------------------------------------------------------------- director Markdown

def _bullets(rows: list, empty: str) -> str:
    return "\n".join(f"- {row}" for row in rows) if rows else empty


def _sections(state, sanity, baseline, variance, declared_stability, fairness, compliance,
              alignment, failure_rows, failure_summary, figures, viz, critique_rows, calibrated,
              blocking, disagreements, coverage_note) -> dict:
    scope = [
        f"**{len(DIAGNOSTIC_SEATS)} diagnostic seats ran blind to each other**, then 2 resolver "
        f"seats reconciled them. {len(disagreements)} unresolved cross-panel disagreement(s) — see "
        f"the disagreements section; the machine deliberately picks no winner.",
        f"Audited material was read from `{AUDIT_INPUT_DIR}/`: "
        f"{len(sanity.get('checked_metrics') or [])} metric/condition pair(s), "
        f"{len(baseline.get('conditions_compared') or [])} condition(s) compared, "
        f"{variance.get('n_seeds')} distinct seed(s), {len(figures.get('figures') or [])} figure(s), "
        f"{len(calibrated.get('calibrated') or [])} claim(s) calibrated.",
        f"**This run measured nothing itself.** Execution state: `{state.get('label')}`. Every "
        f"number above is the audited analysis's own reported value, transcribed by a seat and "
        f"traced to a file — this panel checks whether the claims are supported, it does not re-run "
        f"the experiment.",
        coverage_note,
    ]
    sanity_lines = [f"sanity verdict: **{sanity['verdict']}** over "
                    f"{len(sanity.get('checked_metrics') or [])} metric(s); "
                    f"NaN/Inf={sanity.get('nan_or_inf')}, "
                    f"out-of-range={sanity.get('out_of_range') or 'none'}, "
                    f"leakage smell={sanity.get('leakage_smell')}"]
    sanity_lines += [f"sanity violation: {row}" for row in sanity.get("violations") or []]
    sanity_lines.append(
        f"baseline comparison over {baseline.get('conditions_compared')}: "
        f"{'symmetric — no asymmetry found' if baseline['clean'] else 'ASYMMETRIC'}")
    sanity_lines += [f"asymmetry [{row['dimension']}]: {row['detail']}"
                     for row in baseline.get("asymmetry_flags") or []]

    variance_lines = [
        f"{variance.get('n_seeds')} distinct seed(s) vs required "
        f"{variance.get('min_seeds_required')} -> stability `{variance.get('stability_label')}`"
        + (f"; the analysis itself claims `{declared_stability}`" if declared_stability else ""),
    ]
    variance_lines += [
        f"{row['metric']}: mean={row['mean']}, std={row['std']} over {len(row.get('values') or [])} seed(s)"
        for row in variance.get("per_metric_variance") or []]
    variance_lines.append(
        f"fairness verdict: **{'PASS' if fairness['pass'] else 'FAIL'}** over "
        f"{fairness.get('checked_items') or 'no declared stratification key'}")
    variance_lines += [f"fairness violation: {row}" for row in fairness.get("violations") or []]
    variance_lines.append(
        f"compliance verdict: **{'PASS' if compliance['pass'] else 'FAIL'}**; goal alignment: "
        f"**{'PASS' if alignment['pass'] else 'FAIL'}**")
    variance_lines += [f"compliance violation: {row}" for row in compliance.get("violations") or []]
    variance_lines += [f"alignment violation: {row}" for row in alignment.get("violations") or []]

    failures = [f"[{row['type']}] {row['description']}"
                + (f" (case {row['case_ref']})" if row.get("case_ref") else "")
                + (f" — {row['metric_context']}" if row.get("metric_context") else "")
                for row in failure_rows]

    figure_lines = [f"{len(figures.get('figures') or [])} figure(s) described; axis-truncation check "
                    f"{'clean' if viz['clean'] else 'FLAGGED'}"]
    figure_lines += [f"axis truncation: {row['detail']}" for row in viz.get("axis_truncation_flags") or []]
    figure_lines += [f"[{row['severity']}] {row['figure_id']}: {row['finding_type']} — {row['detail']}"
                     for row in critique_rows if row["finding_type"] != "ok"]

    claim_lines = [
        f"**{row['strength']}**{' (downgraded)' if row.get('downgraded') else ''}: "
        f"{row['calibrated_claim']} — {row['caveat']}"
        for row in calibrated.get("calibrated") or []]

    return {
        "Analysis scope": "\n".join(f"- {row}" for row in scope if str(row).strip()),
        "Sanity and baseline findings": _bullets(sanity_lines, "无 —— 面板没有拿到任何可筛的数字。"),
        "Variance and subgroup findings": _bullets(
            variance_lines, "无 —— 没有任何 per-seed 或 subgroup 记录可读。"),
        "Failure cases": _bullets(
            failures,
            f"无 —— failure-case-miner 报告该分析没有公开任何 per-case 材料"
            f"（{failure_summary or 'no summary given'}）。这本身是一个覆盖缺口，不是干净的证明。"),
        "Figure and visualization audit": _bullets(
            figure_lines, "无 —— 该分析没有提供任何图或结果表。"),
        "Calibrated claims": _bullets(
            claim_lines, "无 —— 该分析没有做出任何可校准的量化主张。"),
        "Blocking issues and repairs": _bullets(
            blocking, f"无 —— 已检查 {len(DIAGNOSTIC_SEATS)} 个独立诊断 agent 的产出，没有阻断项。"),
    }


def _extra_sections(disagreements, controller_claimed, stray, unreviewed_gaps) -> dict:
    rows = []
    for row in disagreements:
        rows.append(
            f"- **{row['topic']}** ({row['resolution']})\n"
            f"  - `{row['seat_a']}`: {row['position_a']}\n"
            f"  - `{row['seat_b']}`: {row['position_b']}\n"
            f"  - why it matters: {row['why_it_matters']}")
    derived = "\n".join(rows) if rows else (
        "无 —— 在 5 条确定性对照（leakage vs baseline symmetry、宣称稳定性 vs 种子数、"
        "auditor 自评 vs 轴截断计算、两位独立看图人逐图对照、strong 主张 vs 种子充分性）上没有发现矛盾。")
    seat_side = "\n".join(
        f"- **{row.get('topic')}**: `{row.get('seat_a')}` 说 {row.get('position_a')}；"
        f"`{row.get('seat_b')}` 说 {row.get('position_b')}"
        for row in controller_claimed) or "无 —— quality-controller 自己没有报告额外矛盾。"
    independence = [
        f"Read boundary is declared per seat and validated by the panel scheduler: each of the "
        f"{len(INDEPENDENT_JUDGMENT_SEATS)} judgment seats forbids the other judgment seats' bundles.",
        "The one shared read is `figure-generator`'s spec bundle — the object under audit — which "
        "both figure auditors see and neither auditor's verdict reaches the other.",
        f"quality-controller named all {len(DIAGNOSTIC_SEATS)} diagnostic seats (coverage gate).",
    ]
    if stray:
        independence.append(f"Controller also named non-panel seat(s) {stray} — ignored, not a seat here.")
    if unreviewed_gaps:
        independence.append("Diagnostics the controller believes are MISSING from this panel: "
                            + "; ".join(str(row) for row in unreviewed_gaps))
    return {
        "Cross-panel disagreements (machine-derived, unresolved)": derived,
        "Cross-panel disagreements (quality-controller's own reading)": seat_side,
        "Panel independence and coverage": "\n".join(f"- {row}" for row in independence),
    }


# --------------------------------------------------------------------------- the stages

def _analyze_dets(run_dir, ts) -> tuple:
    seats = _seats(run_dir, prompts=False)
    bundles = _panel_recipe.load_seat_bundles(run_dir, STAGE, MODE, seats)
    profile = _shared.domain_profile(run_dir)
    vault_root = _shared.resolve_vault_root(DEFAULT_VAULT)
    vault_slugs = _shared.vault_slugs(vault_root)
    paths, blocking = [], []

    figures = _normalized(run_dir, _FIGURE_PRODUCER, "figure_spec_bundle",
                          bundles["figure_spec_bundle"])
    figure_ids = {str(row.get("figure_id")) for row in figures["figures"]}
    viz_seat = bundles["viz_audit_inputs"] if isinstance(bundles["viz_audit_inputs"], dict) else {}
    critic_seat = (bundles["figure_critique_inputs"]
                   if isinstance(bundles["figure_critique_inputs"], dict) else {})
    viz_rows = _figure_findings(viz_seat, "per_figure", figure_ids, "visualization-auditor")
    critic_rows = _figure_findings(critic_seat, "per_figure", figure_ids, "figure-vlm-critic")

    claim_input = bundles["claim_calibration_inputs"]
    raw_claims = list((claim_input or {}).get("claims") or [])
    claim_trace = _claim_evidence_gate(run_dir, raw_claims, vault_slugs)

    # Ids the panel itself produced: an internal-shaped reference to anything else is fabricated.
    known_ids = set(figure_ids)
    for key in ("baseline_audit_inputs", "compliance_inputs", "alignment_inputs"):
        matrix = (bundles.get(key) or {}).get("experiment_matrix") or {}
        known_ids |= {str(row.get("id")) for row in (matrix.get("conditions") or []) if row.get("id")}
    known_ids |= {str(row.get("claim_id")) for row in
                  ((bundles.get("integrity_scan_input") or {}).get("claims") or [])
                  if row.get("claim_id")}
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, STAGE, ts, mode=MODE, bundles=bundles,
        downstream_refs=[ref for row in claim_trace for ref in row["refs"]],
        known_ids=known_ids, vault=DEFAULT_VAULT)
    paths.extend(gate_paths)

    sanity = sanity_checker.build_report(bundles["result_summary"], profile=profile)
    paths.append(write_artifact(run_dir, STAGE, "sanity-verdict.artifact.json", "sanity_verdict",
                                "result-sanity-checker", sanity, ts,
                                "blocked" if sanity["verdict"] == "BLOCK" else "approved"))
    blocking += [f"sanity: {row}" for row in sanity["violations"]]

    baseline_in = bundles["baseline_audit_inputs"]
    baseline = baseline_audit.build_report(
        str(baseline_in.get("baseline_condition_id") or "<undeclared-baseline>"),
        str(baseline_in.get("method_condition_id") or "<undeclared-method>"),
        baseline_in.get("experiment_matrix") or {}, profile)
    baseline["notes"] = str(baseline_in.get("notes") or "")
    paths.append(write_artifact(run_dir, STAGE, "baseline-audit-report.artifact.json",
                                "baseline_audit_report", "baseline-comparison-auditor", baseline, ts,
                                "approved" if baseline["clean"] else "blocked"))
    blocking += [f"baseline asymmetry [{row['dimension']}]: {row['detail']}"
                 for row in baseline["asymmetry_flags"]]

    variance_in = bundles["variance_inputs"]
    declared_stability = variance_in.get("declared_stability_label")
    variance = variance_audit.build_report(
        str(variance_in.get("condition_id") or "<all-conditions>"),
        list(variance_in.get("run_records") or []), profile)
    paths.append(write_artifact(run_dir, STAGE, "variance-report.artifact.json", "variance_report",
                                "variance-analyzer", variance, ts,
                                "blocked" if variance["seed_count_insufficient"] else "approved"))
    if variance["seed_count_insufficient"]:
        blocking.append(f"variance: {variance['n_seeds']} distinct seed(s) is below the required "
                        f"{variance['min_seeds_required']} — variance estimates are not trustworthy")

    fairness_in = bundles["fairness_inputs"]
    fairness = fairness_audit.build_verdict(
        fairness_in.get("result_summary") or {}, list(fairness_in.get("run_records") or []),
        profile, notes=str(fairness_in.get("notes") or ""))
    paths.append(write_artifact(run_dir, STAGE, "fairness-verdict.artifact.json",
                                "analysis_check_verdict", "fairness-auditor", fairness, ts,
                                "approved" if fairness["pass"] else "blocked"))
    blocking += [f"fairness: {row}" for row in fairness["violations"]]

    compliance_in = bundles["compliance_inputs"]
    compliance = compliance_audit.build_verdict(
        compliance_in.get("experiment_matrix") or {},
        list(compliance_in.get("run_records") or []), profile)
    paths.append(write_artifact(run_dir, STAGE, "compliance-verdict.artifact.json",
                                "analysis_check_verdict", "compliance-auditor", compliance, ts,
                                "approved" if compliance["pass"] else "blocked"))
    blocking += [f"compliance: {row}" for row in compliance["violations"]]

    alignment_in = bundles["alignment_inputs"]
    alignment = goal_alignment_audit.build_verdict(
        alignment_in.get("experiment_matrix") or {}, alignment_in.get("result_summary") or {},
        profile, notes=str(alignment_in.get("notes") or ""))
    paths.append(write_artifact(run_dir, STAGE, "goal-alignment-verdict.artifact.json",
                                "analysis_check_verdict", "goal-alignment-checker", alignment, ts,
                                "approved" if alignment["pass"] else "blocked"))
    blocking += [f"goal alignment: {row}" for row in alignment["violations"]]

    failure_in = bundles["failure_inventory"] if isinstance(bundles["failure_inventory"], dict) else {}
    failure_rows = [row for row in (failure_in.get("failures") or []) if isinstance(row, dict)]
    failure_summary = str(failure_in.get("summary") or "")
    # R3 C4 (2026-08-07): the worker prompt already asks for sources_read; carry it into the
    # persisted artifact instead of dropping it — grounding the prompt promised, the schema
    # now has room for, and the old producer dict silently discarded.
    failure_sources_read = [str(x) for x in (failure_in.get("sources_read") or []) if str(x).strip()]
    if failure_rows:
        inventory = _normalized(run_dir, "failure-case-miner", "failure_inventory", {
            "condition_id": str(failure_in.get("condition_id") or "<all-conditions>"),
            "failures": failure_rows, "summary": failure_summary,
            "sources_read": failure_sources_read})
        failure_rows = inventory["failures"]
        paths.append(write_artifact(run_dir, STAGE, "failure-inventory.artifact.json",
                                    "failure_inventory", "failure-case-miner", inventory, ts))
    else:
        blocking.append("failure-case-miner surfaced no per-case material — subgroup and "
                        "failure-mode claims in this analysis are unverified, not clean")

    paths.append(write_artifact(run_dir, STAGE, "figure-spec-bundle.artifact.json",
                                "figure_spec_bundle", _FIGURE_PRODUCER, figures, ts))
    viz = viz_audit.build_report(figures, profile)
    viz["notes"] = str(viz_seat.get("notes") or "")
    paths.append(write_artifact(run_dir, STAGE, "viz-audit-report.artifact.json", "viz_audit_report",
                                "visualization-auditor", viz, ts,
                                "approved" if viz["clean"] else "blocked"))
    blocking += [f"figure axis truncation: {row['detail']}" for row in viz["axis_truncation_flags"]]

    # viz_audit is deliberately NOT merged in: the second critic must stay structurally independent,
    # otherwise it inherits the first auditor's flags and the disagreement signal is destroyed.
    critique = figure_critique_check.build_critique(figures, viz_audit=None)
    seen = {(row["figure_id"], row["finding_type"]) for row in critique["findings"]}
    critique["findings"] += [row for row in critic_rows
                             if (row["figure_id"], row["finding_type"]) not in seen]
    critique["findings"].sort(key=lambda row: (row["figure_id"], row["finding_type"]))
    critique = _normalized(run_dir, "figure-vlm-critic", "figure_critique", critique)
    paths.append(write_artifact(run_dir, STAGE, "figure-critique.artifact.json", "figure_critique",
                                "figure-vlm-critic", critique, ts))
    blocking += [f"figure critique [{row['severity']}] {row['figure_id']}: {row['detail']}"
                 for row in critique["findings"] if row.get("severity") == "critical"]

    calibrated = claim_calibration.build_report(
        raw_claims, source_ref=(claim_input or {}).get("source_ref"))
    paths.append(write_artifact(run_dir, STAGE, "calibrated-claims.artifact.json",
                                "calibrated_claims", _CLAIM, calibrated, ts))
    blocking += [f"claim downgraded to {row['strength']}: {row['original_claim'][:90]}"
                 for row in calibrated["calibrated"] if row.get("downgraded")]

    review = bundles["coverage_review"] if isinstance(bundles["coverage_review"], dict) else {}
    stray = _coverage_gate(review)
    card = scorecard_tool.build_stage_scorecard(STAGE, _verdict_rows(
        sanity, baseline, variance, fairness, compliance, alignment, failure_rows, viz,
        critique["findings"]))
    card["notes"] = (f"Rolled up from {len(DIAGNOSTIC_SEATS)} independent diagnostic seats; "
                     f"pass bits read from their artifacts, not from the controller's opinion.")
    paths.append(write_artifact(run_dir, STAGE, "stage-scorecard.artifact.json", "stage_scorecard",
                                "quality-controller", card, ts,
                                "approved" if card["stage_pass"] else "blocked"))

    integrity_in = (bundles["integrity_scan_input"]
                    if isinstance(bundles["integrity_scan_input"], dict) else {})
    extra_flags = [row for row in (integrity_in.get("extra_flags") or []) if isinstance(row, dict)]
    bad_kinds = sorted({str(row.get("kind")) for row in extra_flags
                        if str(row.get("kind")) not in
                        {"fabricated_data_smell", "completion_pressure"}})
    if bad_kinds:
        raise GateBlock(
            f"{MODE} integrity-refusal-recommender used extra_flags kind(s) {bad_kinds}; only "
            f"'fabricated_data_smell' and 'completion_pressure' may be hand-raised — "
            f"unsupported_number and missing_evidence_refusal are derived from claims.")
    recommendation = integrity_scan.build_recommendation(
        "IR-analysis-audit-1", [row for row in (integrity_in.get("claims") or [])
                                if isinstance(row, dict)],
        scanned_artifacts=[p.replace("\\", "/") for p in paths], extra_flags=extra_flags)
    paths.append(write_artifact(run_dir, STAGE, "integrity-recommendation.artifact.json",
                                "integrity_recommendation", "integrity-refusal-recommender",
                                recommendation, ts))
    if recommendation["recommendation"] != "PROCEED":
        blocking.append(f"integrity {recommendation['recommendation']} (advisory, the director "
                        f"decides): {recommendation['rationale']}")

    state = _panel_recipe.execution_truth(run_dir)
    disagreements = _disagreements(sanity, baseline, variance, declared_stability, viz,
                                   viz_seat.get("declared_clean"), viz_rows, critic_rows, calibrated)
    coverage_note = (
        f"Coverage: {len(DIAGNOSTIC_SEATS)} of {len(DIAGNOSTIC_SEATS)} diagnostic seats delivered "
        f"and were named by quality-controller; stage scorecard "
        f"{'PASS' if card['stage_pass'] else 'FAIL'} over {len(card['dimension_results'])} dimensions.")
    rel = _panel_recipe.render_director_markdown(
        run_dir, MODE,
        _sections(state, sanity, baseline, variance, declared_stability, fairness, compliance,
                  alignment, failure_rows, failure_summary, figures, viz, critique["findings"],
                  calibrated, blocking, disagreements, coverage_note),
        ts=ts, lead="quality-controller + integrity-refusal-recommender",
        extra=_extra_sections(disagreements, review.get("disagreements") or [], stray,
                              review.get("unreviewed_gaps") or []))

    report = {"seats_dispatched": len(_SEAT_SPECS),
              "independent_diagnostic_seats": len(DIAGNOSTIC_SEATS),
              "sanity_gate": sanity["verdict"], "baseline_clean": bool(baseline["clean"]),
              "n_seeds": variance["n_seeds"],
              "variance_sufficient": not variance["seed_count_insufficient"],
              "fairness_gate": "PASS" if fairness["pass"] else "FAIL",
              "compliance_gate": "PASS" if compliance["pass"] else "FAIL",
              "goal_alignment_gate": "PASS" if alignment["pass"] else "FAIL",
              "n_failure_cases": len(failure_rows), "n_figures": len(figures["figures"]),
              "viz_clean": bool(viz["clean"]), "n_figure_findings": len(critique["findings"]),
              "n_calibrated_claims": len(calibrated["calibrated"]),
              "n_claims_downgraded": sum(1 for row in calibrated["calibrated"]
                                         if row.get("downgraded")),
              "claim_evidence_gate": "PASS",
              "cross_panel_coverage": "PASS",
              "n_disagreements_derived": len(disagreements),
              "n_disagreements_seat_reported": len(review.get("disagreements") or []),
              "stage_pass": bool(card["stage_pass"]),
              "integrity_recommendation": recommendation["recommendation"],
              "n_blocking_issues": len(blocking),
              "execution_state": state.get("label"),
              "director_markdown": rel}
    report.update(frag)
    (Path(run_dir) / "inbox" / f"{MODE}-panel-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths, report


def _report_dets(run_dir, ts) -> tuple:
    rel = _panel_recipe.target_markdown(MODE)["path"]
    summary_path = Path(run_dir) / "inbox" / f"{MODE}-panel-summary.json"
    facts = {}
    if summary_path.is_file():
        try:
            facts = json.loads(summary_path.read_text(encoding="utf-8"))
        except ValueError:
            facts = {}
    open_questions = [
        f"{facts.get('n_disagreements_derived', 0)} cross-panel disagreement(s) are UNRESOLVED by "
        f"design — the machine shows both positions and the director decides which seat is right.",
    ]
    if facts.get("integrity_recommendation") not in (None, "PROCEED"):
        open_questions.append(
            f"integrity recommendation is {facts['integrity_recommendation']} — advisory only; "
            f"pausing is the director's call.")
    if not facts.get("n_failure_cases"):
        open_questions.append(
            "No per-case failure material was available, so failure-mode claims stay unverified.")
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary=(
            f"analysis_audit_panel: {facts.get('independent_diagnostic_seats', len(DIAGNOSTIC_SEATS))} "
            f"diagnostic seats audited the analysis independently, then 2 resolver seats reconciled "
            f"them. sanity={facts.get('sanity_gate', 'n/a')}, baseline_clean="
            f"{facts.get('baseline_clean', 'n/a')}, variance_sufficient="
            f"{facts.get('variance_sufficient', 'n/a')}, figures_clean={facts.get('viz_clean', 'n/a')}, "
            f"{facts.get('n_calibrated_claims', 0)} claim(s) calibrated "
            f"({facts.get('n_claims_downgraded', 0)} downgraded), "
            f"{facts.get('n_blocking_issues', 0)} blocking issue(s), "
            f"{facts.get('n_disagreements_derived', 0)} unresolved disagreement(s). Every calibrated "
            f"claim traced to a resolvable evidence_ref; this run executed nothing itself "
            f"(execution state {facts.get('execution_state', 'unknown')})."),
        references=[rel], open_questions=open_questions)


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == STAGE:
        return _analyze_dets(run_dir, ts)
    if stage == "REPORT":
        return _report_dets(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
