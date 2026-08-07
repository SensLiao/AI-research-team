"""Operate recipe for the `design_experiment` mode (DESIGN -> REPORT) — wave 2.

The registry already carried this mode's whole shape (11 seats, a three-segment
`minimum_worker_pipeline`, a six-section director Markdown). What it had no recipe for was the part
its own `productization_gaps` named: **deterministic cross-artifact consistency checks** and a
deterministic Markdown assembly. Ten separate workers each author one slice of an experiment design;
ten individually schema-valid slices can still describe ten different experiments. So this recipe's
centre of gravity is `cross_artifact_violations` — one pure function that proves the slices describe
ONE experiment before any audit verdict is allowed to say PASS.

Three things this recipe is deliberate about:

  * **The three audits grade a frozen design, and they grade the SAME one.** All of
    `variable-control-auditor` / `train-test-alignment-auditor` / `metric-implementation-auditor`
    depend on every one of the six `design_protocol` seats and on none of each other, so no auditor
    can read a design a sibling auditor has not seen. On top of that, the variable-control auditor
    must independently re-enumerate what each condition changes versus the baseline, and the recipe
    compares that enumeration against the same `_changed_factors` core the gate itself uses. An
    auditor whose reading disagrees with the frozen matrix is not a passing gate — it is an audit
    that read a different design, and it BLOCKs.

  * **Designing is not running.** Every stage here is a plan. `execution_truth` is consulted and
    reported verbatim, and any result-shaped key in any worker bundle BLOCKs through
    `refuse_metrics_without_receipt`: this mode emits no metric, only the metric it intends to
    measure. The director Markdown says so in its own section rather than leaving the reader to
    infer it.

  * **The model never decides for the director.** `decision-surfacer` may only SURFACE open
    decisions; the recipe assigns the ADR ids, forces `status: proposed` and `chosen_option: null`,
    and BLOCKs a bundle that arrived pre-decided. Unresolved decisions are rendered into the
    Markdown's "Risks and director decisions" section, which is where a human picks them up.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, write_artifact
from ...tools.alignment_checker import build_report as alignment_build
from ...tools.alignment_checker import detect_zero_training
from ...tools.compare_metric_impls import build_report as metric_build
from ...tools.experiment_planner import build_matrix
from ...tools.prereg import build_prereg
from ...tools.validate_config import validate_config
from ...tools.validate_split import validate_split
from ...tools.variable_control_checker import build_report as vc_build

# The SAME core the variable-control gate computes its verdict from. Imported rather than
# re-implemented on purpose: a second copy of "what changed versus baseline" could disagree with
# the gate, and then the independence cross-check would be grading its own arithmetic.
from ...tools.variable_control_checker import _changed_factors as changed_factors

MODE = "design_experiment"
STAGES = _panel_recipe.stage_path(MODE)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

#: The explicit artifact handoff chain. Each downstream seat must name the exact upstream artifact
#: it designed against, and the recipe checks the string — a handoff nobody can name is a handoff
#: nobody made (registry gap: "explicit artifact handoffs").
RQ_CHAIN_REF = "evidence/DESIGN/rq-hypothesis-chain.artifact.json"
MATRIX_REF = "evidence/DESIGN/experiment-matrix.artifact.json"
SPLIT_REF = "evidence/DESIGN/split-manifest.artifact.json"
PROTOCOL_REF = "evidence/DESIGN/data-protocol.artifact.json"
CONFIG_REF = "evidence/DESIGN/unified-config.artifact.json"

#: Result-shaped keys. A design bundle carrying any of these is claiming a measurement, and this
#: mode never has one — `refuse_metrics_without_receipt` turns that into a BLOCK.
_RESULT_KEYS = frozenset({
    "achieved", "achieved_metrics", "actual_results", "findings", "measured_metrics",
    "measured_values", "metrics", "observed_metrics", "result_summary", "results", "run_records",
})

_HONESTY = """HONESTY (hard): never invent a module path, dataset count, metric implementation, or \
config value — write what you can actually justify from the run's inputs and say plainly when a \
number is unknown (use null, never a plausible-looking guess). A thin design is reported as thin, \
never padded. If this prompt carries a REPAIR ATTEMPT block, fix EXACTLY what the gate feedback \
names, change nothing else, re-emit the COMPLETE bundle, and never argue with the gate or relax \
these honesty requirements."""

_PLAN_ONLY = """THIS IS A DESIGN, NOT A RUN. Nothing has been executed. Emit no measured value, no \
achieved score, no result table — only what you PLAN to measure and the conditions under which you \
plan to measure it. A results/metrics/findings key anywhere in your bundle is a hard BLOCK."""


# --------------------------------------------------------------------------- seat roster

def _seat_specs() -> tuple:
    """(label, bundle_key, tier, depends_on) for all 11 dispatched seats.

    Segment 1 `frame_decisions` frames the question; segment 2 `design_protocol` designs the
    experiment along its real read order (each seat reads the bundle it designs against, so the
    waves are the honest dependency waves, not a claimed six-way parallel); segment 3
    `independent_design_audits` grades the frozen result of segment 2.
    """
    protocol = ("experiment-planner", "dataset-split-planner", "data-protocol-designer",
                "config-unifier", "method-integration-planner", "baseline-fairness-planner")
    # Tier note (director's rule, 2026-08-05): every seat that DESIGNS the experiment is `design`
    # (-> opus). Only `config-unifier` is `tool`, because it merges decisions that are already made
    # into one config rather than making any of them. "Planning" is not a licence to go cheap here:
    # a wrong split, protocol or fairness plan invalidates every number the campaign later produces.
    return (
        ("rq-architect", "rq_hypothesis_chain", "design", ()),
        ("decision-surfacer", "design_decisions", "design", ()),
        ("experiment-planner", "experiment_design", "design",
         ("rq-architect", "decision-surfacer")),
        ("dataset-split-planner", "split_manifest", "design", ("experiment-planner",)),
        ("data-protocol-designer", "data_protocol", "design",
         ("experiment-planner", "dataset-split-planner")),
        ("config-unifier", "unified_config", "tool",
         ("experiment-planner", "data-protocol-designer")),
        ("method-integration-planner", "integration_plan", "design",
         ("experiment-planner", "config-unifier")),
        ("baseline-fairness-planner", "baseline_fairness_plan", "design",
         ("experiment-planner", "dataset-split-planner", "config-unifier")),
        # Segment 3: identical dependency set == one frozen design, and no auditor depends on
        # another, so none of the three can inherit a sibling's judgment.
        ("variable-control-auditor", "variable_control_facts", "audit", protocol),
        ("train-test-alignment-auditor", "alignment_facts", "audit", protocol),
        ("metric-implementation-auditor", "metric_impl_facts", "audit", protocol),
    )


def _bundle_seats() -> List[_panel_recipe.Seat]:
    """Seats for bundle loading only (prompts are irrelevant when reading from disk)."""
    return [_panel_recipe.Seat(label=label, prompt="", bundle_key=key, tier=tier,
                               depends_on=deps)
            for label, key, tier, deps in _seat_specs()]


def _bundle(run_dir, label: str) -> str:
    return f"{run_dir}/inbox/DESIGN.{label}.bundle.json"


# --------------------------------------------------------------------------- dispatch

def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The 11-seat DESIGN panel. REPORT is deterministic and dispatches nobody."""
    if stage != "DESIGN":
        return None
    ns = _shared.north_star_block(run_dir)
    prompts = _prompts(run_dir, request, vault, ns)
    seats = [_panel_recipe.Seat(label=label, prompt=prompts[label], bundle_key=key, tier=tier,
                                depends_on=deps)
             for label, key, tier, deps in _seat_specs()]
    return _panel_recipe.panel(
        run_dir, "DESIGN", MODE, seats, model_policy=model_policy,
        panel_note="Frame the question and surface the open decisions; design the experiment along "
                   "its real read order (matrix -> split -> protocol -> config -> integration + "
                   "fairness); then three mutually independent auditors grade that one frozen "
                   "design. Every artifact is a plan; nothing here has been executed.")


def _frozen_design(run_dir) -> str:
    """The six `design_protocol` bundle paths — the ONE frozen design all three auditors grade."""
    return ", ".join(f"`{_bundle(run_dir, label)}`" for label in (
        "experiment-planner", "dataset-split-planner", "data-protocol-designer", "config-unifier",
        "method-integration-planner", "baseline-fairness-planner"))


def _prompts(run_dir, request: str, vault: str, ns: str) -> dict:
    """Hand-written dispatch orders, one per seat. Never generated from registry text."""
    frozen = _frozen_design(run_dir)
    p: dict = {}

    p["rq-architect"] = f"""You are the RQ architect opening a new experiment design.

    REQUEST: {request}

{ns}

Read the run's `task_frame.artifact.json` and, when they exist, the project's canonical question and
decision register under the vault at `{vault}/`. Decompose the request into a chain of INDEPENDENTLY
FALSIFIABLE hypotheses: each must name what would be observed if it is true AND what would be
observed if it is false, so a later result can actually kill it.

Write ONLY this JSON to `{_bundle(run_dir, 'rq-architect')}`:
{{"rq_hypothesis_chain":{{"research_question":"<one sentence — the whole question>",
"hypotheses":[{{"hypothesis_id":"H1","statement":"<what it claims>",
"falsifiable_prediction":"<observable outcome separating true from false>",
"evidence_needed":["<experiment or measurement that would test it>"],"depends_on":[],"notes":null}}],
"rq_notes":"<scope and assumptions of the question>"}}}}

Quantities are FLOORS with NO upper bound: >=3 hypotheses, >=1 `evidence_needed` each. Emit every
hypothesis the question genuinely contains — never drop a defensible one to keep the chain short.
`depends_on` may only name hypothesis_ids that exist in YOUR chain. Downstream seats copy
`research_question` VERBATIM, so write the version you want frozen.
{_PLAN_ONLY}
{_HONESTY}"""

    p["decision-surfacer"] = f"""You are the decision surfacer. You do not design the experiment and \
you do not decide anything.

    REQUEST: {request}

{ns}

Two jobs. FIRST, surface every design decision a human — not a model — must settle: real trade-offs
where two or more defensible options exist and the choice changes what the experiment MEANS. SECOND,
state the acceptance criteria this design commits to BEFORE any number exists: the one primary
metric, any secondary metrics, how many seeds, when collection stops, and the analysis to be run.
Read the frozen question at `{_bundle(run_dir, 'rq-architect')}` when it is already present.

Write ONLY this JSON to `{_bundle(run_dir, 'decision-surfacer')}`:
{{"design_decisions":{{"open_decisions":[{{"question":"<the decision, as a question>",
"options":["<option A>","<option B>"],"evidence":["<what is known that bears on it>"],
"locks":["<artifact path this decision would freeze>"]}}],
"acceptance_criteria":{{"primary_metric":"<THE primary outcome metric>",
"secondary_metrics":["<other metric that may be reported>"],"n_seeds_planned":3,
"stopping_rule":"<when collection stops>","analysis_plan":"<the committed statistical analysis>"}}}}}}

Quantities are FLOORS with NO upper bound: >=2 open decisions whenever the design genuinely has two
or more, >=2 options each. Surface every decision you can defend — an unsurfaced decision is one the
machine will silently make instead of the director. You may NOT pick a winner: never emit
`chosen_option`, never emit a `status`, never rank the options; a pre-decided bundle is a hard BLOCK.
`primary_metric` and every secondary metric must be one the conditions can actually compute.
When an idea does not fit the machine's real hardware, that is itself an open decision to surface
(buy / borrow / stage down / change the question) — never a reason to silently shrink the design.
{_PLAN_ONLY}
{_HONESTY}"""

    p["experiment-planner"] = f"""You are the experiment planner. The research question is already \
frozen — you turn it into a conditions x factors grid that isolates one variable at a time.

{ns}

Read the frozen chain and the acceptance criteria: `{_bundle(run_dir, 'rq-architect')}`,
`{_bundle(run_dir, 'decision-surfacer')}`.

Declare exactly ONE baseline condition. Every other condition must differ from the baseline ONLY in
studied factors — a second simultaneous change makes the contrast uninterpretable and a downstream
deterministic auditor will BLOCK it. Factor keys must come from your own variables declaration.

Write ONLY this JSON to `{_bundle(run_dir, 'experiment-planner')}`:
{{"experiment_design":{{"research_question":"<VERBATIM from the rq-architect bundle>",
"variables":{{"studied":["<the variable under test>"],"controlled":["<held equal across conditions>"],
"frozen":["<must never move>"]}},
"conditions":[{{"id":"conf1","factors":{{"<factor>":"<value>"}},"baseline":true}},
{{"id":"conf2","factors":{{"<factor>":"<value>"}}}}],
"ranked_batch":[{{"rank":1,"condition_id":"conf2","hypothesis":"<which hypothesis this run tests>",
"cost_gpu_hours":null,"expected_signal":"<what would count as signal>"}}],
"leakage_declaration":"<written statement of what makes this design leakage-safe>",
"hypothesis_coverage":{{"H1":["conf2"]}}}}}}

FEASIBILITY LANDING (this stage owns cost; ideation deliberately does not).
Read the machine's real resource registry first (`research_agent_teams/resources/*.yaml`; the A6000
pair is the execution target, the 3090 is read-only) and stage the design against ACTUAL
VRAM/storage/runtime; declare per-stage cost against that hardware, and when a stage does not fit,
say exactly what is missing instead of shrinking the idea silently. Never invent a spec — when the
registry cannot be read, write `unknown` and say so. An idea arriving here tagged
`exceeds_current_hardware` is not a defect and is not to be redesigned into something smaller on your
own authority: name the shortfall (how much VRAM / storage / wall-clock / how many GPUs), name the
cheapest staging that would still test the SAME claim, and hand the trade-off to the director.

Quantities are FLOORS with NO upper bound: >=2 conditions counting the baseline, >=1 ranked_batch
entry per non-baseline condition. `ranked_batch` ranks must be the contiguous set 1..N.
`hypothesis_coverage` must map EVERY hypothesis_id in the frozen chain to >=1 condition id that
tests it — a hypothesis no condition tests BLOCKs, and a condition id outside your grid BLOCKs.
Every `studied` variable must actually differ in >=1 condition. Use `cost_gpu_hours: null` unless
you can justify the estimate.
{_PLAN_ONLY}
{_HONESTY}"""

    p["dataset-split-planner"] = f"""You are the dataset split planner. You did not design the grid.

{ns}

Read the frozen grid at `{_bundle(run_dir, 'experiment-planner')}` and the active domain profile
(`payload.domain_profile_ref` in the task_frame -> `profiles/<ref>.profile.yaml`) when one is set.
Choose a split UNIT the profile allows — a forbidden unit (a slice of a volume, a token of a
document) leaks by construction and is rejected deterministically. Lock the evaluation split before
training by marking it `frozen: true`.

Write ONLY this JSON to `{_bundle(run_dir, 'dataset-split-planner')}`:
{{"split_manifest":{{"split_unit":"<patient|case|document|...>",
"splits":[{{"name":"train","fraction":0.7,"n_units":null,"stratification_keys":["<key>"],
"frozen":false}},{{"name":"test","fraction":0.3,"n_units":null,"stratification_keys":["<key>"],
"frozen":true}}],
"leakage_declaration":"<which disjointness you assert and how it is checked>",
"from_domain_profile":null,"notes":null}}}}

Quantities are FLOORS with NO upper bound: >=2 splits. Fractions may not sum above 1.0. Use
`n_units: null` unless you have really counted the data — a fabricated count is worse than an honest
null. Every split you declare must be one some processing step touches or some metric is measured
on; a split nobody uses BLOCKs.
{_PLAN_ONLY}
{_HONESTY}"""

    p["data-protocol-designer"] = f"""You are the data protocol designer. You did not choose the split.

{ns}

Read the frozen grid and split: `{_bundle(run_dir, 'experiment-planner')}`,
`{_bundle(run_dir, 'dataset-split-planner')}`.

Declare every preprocessing / normalization / resampling / augmentation / postprocessing step, in
order, and for each say whether it is train-only. Augmentation applied to evaluation data is a
leakage bug and is rejected structurally, so any `kind:"augmentation"` step MUST be
`train_only: true`. Spell split names EXACTLY as the split manifest spells them.

Write ONLY this JSON to `{_bundle(run_dir, 'data-protocol-designer')}`:
{{"data_protocol":{{"from_split_manifest_ref":"{SPLIT_REF}",
"steps":[{{"step_id":"S1","kind":"preprocessing","description":"<what it does>","train_only":false,
"params":{{}},"applies_to_splits":["train","test"]}}],"notes":null}}}}

Quantities are FLOORS with NO upper bound: >=3 steps, and every step that differs between training
and evaluation must be listed separately rather than merged. `from_split_manifest_ref` must be the
exact string above. Every name in `applies_to_splits` must exist in the split manifest.
{_PLAN_ONLY}
{_HONESTY}"""

    p["config-unifier"] = f"""You are the config unifier. You did not design the grid or the protocol.

{ns}

Read the frozen grid and data protocol: `{_bundle(run_dir, 'experiment-planner')}`,
`{_bundle(run_dir, 'data-protocol-designer')}`.

Put everything that must be IDENTICAL across conditions into `shared_config`, and list per condition
only the keys that genuinely differ. Every divergence needs a non-empty justification — an
unjustified divergence is un-reviewable and is rejected deterministically. A divergence key must be
a variable the grid declares (studied or controlled); diverging on a FROZEN variable BLOCKs.

Write ONLY this JSON to `{_bundle(run_dir, 'config-unifier')}`:
{{"unified_config":{{"from_protocol_ref":"{PROTOCOL_REF}",
"shared_config":{{"<key>":"<value identical everywhere>"}},
"conditions":[{{"condition_id":"conf1","divergences":[]}},{{"condition_id":"conf2",
"divergences":[{{"key":"<the studied variable>","value":"<this condition's value>",
"justification":"<why it differs>"}}]}}],"notes":null}}}}

Include one entry per condition in the grid — exactly the same condition ids, no more and no fewer.
`from_protocol_ref` must be the exact string above. Put every genuinely shared key into
`shared_config` (a FLOOR, no upper bound): a key you leave out is a key nobody froze.
{_PLAN_ONLY}
{_HONESTY}"""

    p["method-integration-planner"] = f"""You are the method integration planner. You did not design \
the grid or the configs.

{ns}

Read the frozen grid and unified config: `{_bundle(run_dir, 'experiment-planner')}`,
`{_bundle(run_dir, 'config-unifier')}`.

Say, per condition, what code actually runs it. Exactly ONE condition — the baseline — carries
`module: null` (it needs no new code); every other condition names a real module path and an entry
point. Shared infrastructure (data loaders, metric code) must stay identical across conditions, and
you say so explicitly.

Write ONLY this JSON to `{_bundle(run_dir, 'method-integration-planner')}`:
{{"integration_plan":{{"research_question":"<VERBATIM from the rq-architect bundle>",
"from_matrix_ref":"{MATRIX_REF}",
"conditions":[{{"condition_id":"conf1","module":null,"entry_point":"<baseline script>",
"patch_description":null,"dependencies":[],"notes":null}},{{"condition_id":"conf2",
"module":"<pkg.module>","entry_point":"<script or function>",
"patch_description":"<what code changes>","dependencies":["<package>"],"notes":null}}],
"shared_infra_notes":"<what must remain identical across conditions>"}}}}

One entry per condition in the grid — exactly the same condition ids. The `module: null` condition
must be the SAME one the grid marks `baseline: true`. `from_matrix_ref` must be the exact string
above. List every dependency you actually need (a FLOOR, no upper bound). Never invent a module path
that does not exist — if the code must still be written, say so in `patch_description`.
{_PLAN_ONLY}
{_HONESTY}"""

    p["baseline-fairness-planner"] = f"""You are the baseline fairness planner. You did not design \
the grid, the split, or the configs.

{ns}

Read the frozen grid, split and config: `{_bundle(run_dir, 'experiment-planner')}`,
`{_bundle(run_dir, 'dataset-split-planner')}`, `{_bundle(run_dir, 'config-unifier')}`.

Your job is to make the comparison honest BEFORE it is run: baseline and treatments must see the
same data, the same compute budget, and the same metric configuration. Check each and report what
you find — including mismatches you cannot fix.

Write ONLY this JSON to `{_bundle(run_dir, 'baseline-fairness-planner')}`:
{{"baseline_fairness_plan":{{"baseline_ref":"<the grid's baseline condition id>",
"treatment_refs":["<every non-baseline condition id>"],
"fairness_checks":[{{"check_name":"data_hash","baseline_value":"<planned value or null>",
"treatment_values":{{"conf2":"<planned value or null>"}},"mismatch_detected":false}}],
"fairness_violations":[],"override_justification":null,"notes":null}}}}

Quantities are FLOORS with NO upper bound: >=3 checks (data, compute budget, metric configuration at
minimum) and one `treatment_values` entry per treatment. `treatment_refs` must be exactly the grid's
non-baseline condition ids. Report EVERY mismatch in `fairness_violations` — an unreported mismatch
is the whole failure mode this seat exists to prevent. A non-empty `fairness_violations` with an
empty `override_justification` BLOCKs: if a mismatch is deliberate (it IS the studied variable) say
so in `override_justification`; otherwise leave the violation standing and let the gate stop the
design rather than quietly passing an unfair comparison.
{_PLAN_ONLY}
{_HONESTY}"""

    p["variable-control-auditor"] = f"""You are the variable-control auditor. You produced NO part of \
this design; your job is to independently re-read it and state what each condition really changes. \
You never edit the design, and you never compute the verdict — a deterministic checker does that.

{ns}

Read the ONE frozen design — all six bundles: {frozen}.

For EVERY non-baseline condition, enumerate every factor key whose value differs from the baseline
condition — studied or not, and independently of what the planner claims is studied. Then say
whether any condition's input derives from test labels or a case-specific oracle.

Write ONLY this JSON to `{_bundle(run_dir, 'variable-control-auditor')}`:
{{"variable_control_facts":{{"audited_matrix_ref":"{MATRIX_REF}","independent_of_planner":true,
"conditions_reviewed":[{{"condition_id":"conf2",
"changed_vs_baseline":["<every differing factor key>"]}}],"leakage_flagged":false,
"leakage_note":"<what you checked for leakage and what you found>"}}}}

Review EVERY non-baseline condition — that count is a FLOOR, not a cap, and a missing one BLOCKs.
List every differing factor you can defend; never trim the list to keep the bundle short.
`changed_vs_baseline` is compared
against the frozen grid mechanically: if your enumeration disagrees with the design, the run BLOCKs,
because an audit that read a different design is not a passing gate. Set `leakage_flagged: true`
whenever you find label leakage — that is an automatic refusal, and suppressing it to let the design
through is the one thing this seat must never do.
{_PLAN_ONLY}
{_HONESTY}"""

    p["train-test-alignment-auditor"] = f"""You are the train/test/inference alignment auditor. You \
designed NO pipeline; you independently gather the pipeline facts and a deterministic checker \
computes PASS/BLOCK.

{ns}

Read the ONE frozen design — all six bundles: {frozen}.

State the TRAIN pipeline and the EVAL pipeline as structured facts, and name which declared split
each runs on. Training and evaluating on the same split is the classic leak and BLOCKs; the
evaluation split must be the one the split manifest marks `frozen: true`.

Write ONLY this JSON to `{_bundle(run_dir, 'train-test-alignment-auditor')}`:
{{"alignment_facts":{{"independent_of_designers":true,"train_split":"<split name from the manifest>",
"test_split":"<split name from the manifest>","zero_training":false,
"train":{{"preprocessing":["<step ids or names, in order>"],"precision":"<fp32|amp|...>",
"label_space":["<label>"],"pretrained":"<checkpoint or 'none'>","augmentation":{{"enabled":true}}}},
"test":{{"preprocessing":["<must equal train's>"],"precision":"<must equal train's>",
"label_space":["<must equal train's>"],"augmentation":{{"enabled":false}},
"inference":{{"<threshold / sliding-window / tta setting>":"<value>"}}}}}}}}

Report the pipelines AS DESIGNED, not as they ought to be: if preprocessing really differs between
train and eval, write the difference and let the checker BLOCK. `train.pretrained` must be present
even when the answer is `"none"`, and `test.inference` must be present. Enumerate every preprocessing
step (a FLOOR, no upper bound) — a step you omit is a mismatch nobody can see.

`zero_training` (default false): set it TRUE only when this design genuinely trains nothing — a
frozen model run in inference mode only. The train/eval parity invariants assume a training run
exists; on a zero-training design they are unsatisfiable rather than violated, so declaring it
honestly is what stops a real design being BLOCKed for a training run it never had. It is
DUAL-LOCKED and cannot be used as an escape hatch by itself: this flag only takes effect when the
experiment design ALSO carries an explicit `zero_training` entry in `variables.frozen`. Setting it
true on a design that does train is a false declaration, and the invariants it would skip
(preprocessing / precision / label-space parity, and the pretrained declaration) are exactly the
ones that catch a leak. Whatever the value, `test.augmentation.enabled` must still be false,
`test.inference` must still be declared, and `test.preprocessing` must still be non-empty.
{_PLAN_ONLY}
{_HONESTY}"""

    p["metric-implementation-auditor"] = f"""You are the metric-implementation auditor. You designed \
neither the grid nor the configs; you independently record which metric implementation each \
condition would use, and a deterministic checker computes PASS/BLOCK.

{ns}

Read the ONE frozen design — all six bundles: {frozen}.

Also read the active domain profile when one is set: every metric it declares must appear in EVERY
condition and must use the profile's canonical `implementation_ref`. Two conditions scored by
different metric code are not comparable, however similar the numbers would look.

Write ONLY this JSON to `{_bundle(run_dir, 'metric-implementation-auditor')}`:
{{"metric_impl_facts":{{"independent_of_planner":true,
"evaluated_splits":["<split name(s) the metrics are computed on>"],
"conditions":[{{"condition_id":"conf1","metric_impls":{{"<metric name>":{{
"impl_ref":"<module.Class or function>","spacing":"<or null>","postprocess":"<or null>",
"varies_by":["<studied variable this implementation deliberately tracks, or omit>"]}}}}}}]}}}}

One entry per condition in the grid — exactly the same condition ids. Record every metric the design
would compute (a FLOOR, no upper bound), including the primary metric the acceptance criteria name:
a preregistered primary metric that no condition implements BLOCKs. Every name in `evaluated_splits`
must exist in the split manifest. Record the implementations AS DESIGNED — if two conditions really
differ, write the difference and let the checker BLOCK rather than harmonising them on paper.

`varies_by` is the one legitimate reason a metric implementation may differ across conditions: when
the difference IS the treatment. Name the studied variable(s) it tracks, using the design's own
`variables.studied` spelling (a ` -- <reason>` suffix is stripped before matching). A difference
that every affected condition declares, and whose named variables are all genuinely studied by this
experiment, is recorded as a treatment variation instead of an inconsistency. An UNDECLARED
difference — or one that names a variable this experiment does not study — is still a BLOCK, and
correctly so: it means two conditions are being scored by different code for no stated reason.
{_PLAN_ONLY}
{_HONESTY}"""

    return p


# --------------------------------------------------------------------------- honesty boundary

def _result_key_hits(value, path: str = "", depth: int = 0) -> List[str]:
    """Pointers to result-shaped keys anywhere in the worker bundles."""
    if depth > 10:
        return []
    hits: List[str] = []
    if isinstance(value, dict):
        for key, sub in value.items():
            here = f"{path}/{key}"
            if str(key).lower() in _RESULT_KEYS:
                hits.append(here)
            hits.extend(_result_key_hits(sub, here, depth + 1))
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            hits.extend(_result_key_hits(sub, f"{path}/{index}", depth + 1))
    return hits


# --------------------------------------------------------------------------- cross-artifact gate

def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _ids(rows: Sequence[dict], key: str) -> set:
    return {str(row.get(key)) for row in rows or [] if row.get(key) is not None}


def cross_artifact_violations(chain: dict, matrix: dict, coverage, split: dict, protocol: dict,
                              config: dict, integration: dict, fairness: dict, vc_facts: dict,
                              align_facts: dict, metric_facts: dict, acceptance: dict) -> List[str]:
    """Prove the design slices describe ONE experiment. Non-empty == the design is incoherent.

    This is the check the registry's `productization_gaps` asked for. Every slice is already
    schema-valid alone; what nothing tested before this function is whether they AGREE — one research
    question, one condition set, one baseline, one split vocabulary, one variable declaration, audits
    that really read this design, and a primary metric something actually implements.
    """
    v: List[str] = []
    conditions = matrix.get("conditions") or []
    cond_ids = _ids(conditions, "id")
    baseline_ids = {str(c.get("id")) for c in conditions if c.get("baseline")}
    baseline = next(iter(baseline_ids), None)
    treatments = cond_ids - baseline_ids
    split_names = _ids(split.get("splits") or [], "name")

    # --- the research question must be ONE string, not three paraphrases
    rqs = {"rq-architect": chain.get("research_question"),
           "experiment-planner": matrix.get("research_question"),
           "method-integration-planner": integration.get("research_question")}
    if len({_norm(t) for t in rqs.values()}) > 1:
        v.append(f"the research question differs across seats {({k: str(t)[:70] for k, t in rqs.items()})}"
                 f" — downstream seats copy the frozen question verbatim, never paraphrase it")

    # --- hypothesis chain -> conditions: a hypothesis no condition tests is untested
    chain_ids = _ids(chain.get("hypotheses") or [], "hypothesis_id")
    for row in chain.get("hypotheses") or []:
        dangling = sorted({str(d) for d in row.get("depends_on") or []} - chain_ids)
        if dangling:
            v.append(f"hypothesis {row.get('hypothesis_id')!r} depends_on {dangling}, which the chain "
                     f"does not declare")
    if not isinstance(coverage, dict) or not coverage:
        v.append("experiment_design.hypothesis_coverage is missing — every hypothesis must name the "
                 "condition(s) testing it, or the design cannot answer the question it was built for")
    else:
        keys = {str(k) for k in coverage}
        if keys != chain_ids:
            v.append(f"hypothesis_coverage covers {sorted(keys)} but the frozen chain declares "
                     f"{sorted(chain_ids)} — untested {sorted(chain_ids - keys)}, "
                     f"unknown {sorted(keys - chain_ids)}")
        for hid, cids in coverage.items():
            named = {str(c) for c in cids or []}
            if not named:
                v.append(f"hypothesis {str(hid)!r} maps to no condition — an untested hypothesis")
            if named - cond_ids:
                v.append(f"hypothesis {str(hid)!r} maps to condition(s) {sorted(named - cond_ids)} "
                         f"that are not in the grid")

    # --- one condition set and one baseline, everywhere
    for who, rows in (("unified_config", config.get("conditions")),
                      ("integration_plan", integration.get("conditions")),
                      ("metric_impl_facts", metric_facts.get("conditions"))):
        theirs = _ids(rows or [], "condition_id")
        if theirs != cond_ids:
            v.append(f"{who} covers conditions {sorted(theirs)} but the grid declares "
                     f"{sorted(cond_ids)} — missing {sorted(cond_ids - theirs)}, "
                     f"unknown {sorted(theirs - cond_ids)}")
    null_module = {str(c.get("condition_id")) for c in integration.get("conditions") or []
                   if c.get("module") is None}
    if null_module != baseline_ids:
        v.append(f"integration_plan calls {sorted(null_module)} the no-new-code baseline but the grid "
                 f"marks {sorted(baseline_ids)} — the baseline must be the same condition")
    if str(fairness.get("baseline_ref")) != str(baseline):
        v.append(f"baseline_fairness_plan.baseline_ref={fairness.get('baseline_ref')!r} is not the "
                 f"grid's baseline {baseline!r}")
    fair_treatments = {str(r) for r in fairness.get("treatment_refs") or []}
    if fair_treatments != treatments:
        v.append(f"baseline_fairness_plan.treatment_refs={sorted(fair_treatments)} is not the grid's "
                 f"non-baseline set {sorted(treatments)}")
    if fairness.get("fairness_violations") and not str(fairness.get("override_justification") or "").strip():
        v.append(f"baseline_fairness_plan reports {list(fairness['fairness_violations'])} with no "
                 f"override_justification — an unfair comparison is fixed or justified by a human, "
                 f"never shipped silently")

    # --- explicit artifact handoffs: a handoff nobody can name is a handoff nobody made
    for who, got, want in (
            ("data_protocol.from_split_manifest_ref", protocol.get("from_split_manifest_ref"), SPLIT_REF),
            ("unified_config.from_protocol_ref", config.get("from_protocol_ref"), PROTOCOL_REF),
            ("integration_plan.from_matrix_ref", integration.get("from_matrix_ref"), MATRIX_REF),
            ("variable_control_facts.audited_matrix_ref", vc_facts.get("audited_matrix_ref"), MATRIX_REF)):
        if str(got or "") != want:
            v.append(f"{who}={got!r} does not name the upstream artifact it was designed against "
                     f"(expected {want!r})")

    # --- split vocabulary, both directions: no phantom split, no orphan split
    protocol_splits = {str(n) for step in protocol.get("steps") or []
                       for n in step.get("applies_to_splits") or []}
    evaluated = {str(n) for n in metric_facts.get("evaluated_splits") or []}
    train_split = str(align_facts.get("train_split") or "")
    test_split = str(align_facts.get("test_split") or "")
    pipeline_splits = {n for n in (train_split, test_split) if n}
    if not evaluated:
        v.append("metric_impl_facts.evaluated_splits is empty — the design never says which split the "
                 "metrics are computed on")
    for who, names in (("data_protocol.applies_to_splits", protocol_splits),
                       ("metric_impl_facts.evaluated_splits", evaluated),
                       ("alignment_facts train/test split", pipeline_splits)):
        if names - split_names:
            v.append(f"{who} names split(s) {sorted(names - split_names)} that the split manifest does "
                     f"not declare (declared: {sorted(split_names)})")
    orphan = sorted(split_names - (protocol_splits | evaluated | pipeline_splits))
    if orphan:
        v.append(f"split manifest declares split(s) {orphan} that no protocol step processes, no metric "
                 f"measures, and no pipeline trains or evaluates on")
    if train_split and train_split == test_split:
        v.append(f"alignment_facts trains and evaluates on the same split {train_split!r} — evaluation "
                 f"must run on held-out data")
    frozen_splits = {str(s.get("name")) for s in split.get("splits") or [] if s.get("frozen")}
    if test_split and test_split not in frozen_splits:
        v.append(f"the evaluation split {test_split!r} is not frozen in the split manifest "
                 f"(frozen: {sorted(frozen_splits)}) — the test set is locked before training")
    total = sum(float(s.get("fraction") or 0) for s in split.get("splits") or [])
    if total > 1.0 + 1e-6:
        v.append(f"split fractions sum to {round(total, 6)} — more than the whole dataset is allocated")

    # --- every variable the config moves must be a variable the audit can see
    declared = matrix.get("variables") or {}
    studied = {str(x) for x in declared.get("studied") or []}
    frozen_vars = {str(x) for x in declared.get("frozen") or []}
    all_vars = studied | {str(x) for x in declared.get("controlled") or []} | frozen_vars
    for cond in config.get("conditions") or []:
        cid = str(cond.get("condition_id"))
        for div in cond.get("divergences") or []:
            key = str(div.get("key"))
            if key not in all_vars:
                v.append(f"unified_config {cid!r} diverges on {key!r}, which the grid declares neither "
                         f"studied, controlled nor frozen — an undeclared variable is invisible to the "
                         f"variable-control audit")
            if key in frozen_vars:
                v.append(f"unified_config {cid!r} diverges on frozen variable {key!r} — frozen means "
                         f"it never moves")
    base_row = next((c for c in conditions if c.get("baseline")), {})
    machine_changed = {str(c.get("id")): changed_factors(base_row, c)
                       for c in conditions if not c.get("baseline")}
    varied = set().union(*machine_changed.values()) if machine_changed else set()
    if studied - varied:
        v.append(f"variable(s) {sorted(studied - varied)} are declared studied but differ in no "
                 f"condition — a studied variable nobody varies is not being studied")

    # --- the audits must be independent, and must have read THIS design
    for who, facts, flag in (("variable-control-auditor", vc_facts, "independent_of_planner"),
                             ("train-test-alignment-auditor", align_facts, "independent_of_designers"),
                             ("metric-implementation-auditor", metric_facts, "independent_of_planner")):
        if facts.get(flag) is not True:
            v.append(f"{who} did not attest {flag}=true — an audit that produced or inherited what it "
                     f"grades is not an independent verdict")
    reviewed = _ids(vc_facts.get("conditions_reviewed") or [], "condition_id")
    if reviewed != treatments:
        v.append(f"variable-control-auditor reviewed {sorted(reviewed)} but the grid has non-baseline "
                 f"condition(s) {sorted(treatments)} — every contrast must be audited")
    for row in vc_facts.get("conditions_reviewed") or []:
        cid = str(row.get("condition_id"))
        theirs = {str(x) for x in row.get("changed_vs_baseline") or []}
        if cid in machine_changed and theirs != machine_changed[cid]:
            v.append(f"variable-control-auditor read condition {cid!r} as changing {sorted(theirs)} but "
                     f"the frozen grid changes {sorted(machine_changed[cid])} — the auditor and the "
                     f"design disagree, so this audit graded a different experiment")

    # --- a preregistered metric nothing implements cannot be the committed outcome
    implemented = [{str(k).lower() for k in (c.get("metric_impls") or {})}
                   for c in metric_facts.get("conditions") or []]
    everywhere = set.intersection(*implemented) if implemented else set()
    wanted = [str(acceptance.get("primary_metric") or "")]
    wanted += [str(m) for m in acceptance.get("secondary_metrics") or []]
    for name in [m for m in wanted if m.strip()]:
        if name.lower() not in everywhere:
            v.append(f"acceptance criteria name metric {name!r}, which not every condition implements "
                     f"(implemented everywhere: {sorted(everywhere)}) — it cannot be the outcome this "
                     f"design commits to")
    return v


# --------------------------------------------------------------------------- deterministic stage

def _adr_payloads(decisions: dict) -> List[dict]:
    """Open decisions -> proposed ADRs. The recipe owns id/status/choice, so the model cannot decide."""
    rows = decisions.get("open_decisions")
    if not isinstance(rows, list) or not rows:
        raise GateBlock(
            "decision-surfacer surfaced no open_decisions — an experiment design with zero decisions "
            "for the director is a design that quietly decided everything itself. Surface the "
            "trade-offs, or say in each one why it is settled.")
    out: List[dict] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise GateBlock(f"open_decisions[{index - 1}] is not an object")
        if row.get("chosen_option") is not None or row.get("status") is not None:
            raise GateBlock(
                f"open decision {str(row.get('question'))[:80]!r} arrived pre-decided "
                f"(chosen_option/status set) — only the director chooses; the surfacer may only "
                f"surface the options.")
        options = [str(o) for o in row.get("options") or [] if str(o).strip()]
        if len(options) < 2:
            raise GateBlock(
                f"open decision {str(row.get('question'))[:80]!r} offers {len(options)} option(s) — a "
                f"decision the director can only answer one way is not a decision")
        out.append({"decision_id": f"ADR-{index:04d}", "question": str(row.get("question") or ""),
                    "options": options, "chosen_option": None, "reason": None,
                    "evidence": [str(e) for e in row.get("evidence") or []], "status": "proposed",
                    "approved_by": None, "approved_at": None,
                    "downstream_locked_artifacts": [str(x) for x in row.get("locks") or []]})
    return out


#: (filename stem, artifact_type, accountable seat, bundle key) for the seven design producers.
_PRODUCERS = (
    ("rq-hypothesis-chain", "rq_hypothesis_chain", "rq-architect", "rq_hypothesis_chain"),
    ("experiment-matrix", "experiment_matrix", "experiment-planner", None),  # assembled, see below
    ("split-manifest", "split_manifest", "dataset-split-planner", "split_manifest"),
    ("data-protocol", "data_protocol", "data-protocol-designer", "data_protocol"),
    ("unified-config", "unified_config", "config-unifier", "unified_config"),
    ("integration-plan", "integration_plan", "method-integration-planner", "integration_plan"),
    ("baseline-fairness-plan", "baseline_fairness_plan", "baseline-fairness-planner",
     "baseline_fairness_plan"),
)


def _design_dets(run_dir, ts) -> tuple:
    b = _panel_recipe.load_seat_bundles(run_dir, "DESIGN", MODE, _bundle_seats())
    profile = _shared.domain_profile(run_dir)
    paths: List[str] = []

    def put(stem, atype, seat, payload, status="approved"):
        paths.append(write_artifact(run_dir, "DESIGN", f"{stem}.artifact.json", atype, seat,
                                    payload, ts, status))

    # Honesty boundary FIRST: a design run holds no measurement, so a result-shaped key anywhere in
    # the bundles BLOCKs before a single artifact is written.
    state = _panel_recipe.execution_truth(run_dir)
    result_hits = _result_key_hits(b)
    _panel_recipe.refuse_metrics_without_receipt(
        state, result_hits, mode=MODE,
        # Name the exact JSON pointers: "there is a measurement somewhere" is not actionable, and a
        # worker asked to repair a bundle it cannot locate will guess.
        what=f"measured results at {result_hits}")

    chain, design, decisions = b["rq_hypothesis_chain"], b["experiment_design"], b["design_decisions"]
    acceptance = decisions.get("acceptance_criteria") or {}
    coverage = design.get("hypothesis_coverage")
    try:
        matrix = build_matrix(design.get("research_question"), design.get("variables") or {},
                             design.get("conditions") or [], design.get("ranked_batch") or [],
                             design.get("leakage_declaration"))
    except (ValueError, KeyError, TypeError) as exc:
        raise GateBlock(f"experiment-matrix design-hygiene BLOCK: {exc}") from exc
    for validate, payload, what in ((validate_split, b["split_manifest"], "split-manifest"),
                                    (validate_config, b["unified_config"], "unified-config")):
        try:
            validate(payload, profile)
        except ValueError as exc:
            raise GateBlock(f"{what} BLOCK: {exc}") from exc
    for stem, atype, seat, key in _PRODUCERS:
        put(stem, atype, seat, matrix if key is None else b[key])

    # THE mode's own hard gate: seven schema-valid slices, one experiment — or none.
    consistency = cross_artifact_violations(
        chain, matrix, coverage, b["split_manifest"], b["data_protocol"], b["unified_config"],
        b["integration_plan"], b["baseline_fairness_plan"], b["variable_control_facts"],
        b["alignment_facts"], b["metric_impl_facts"], acceptance)
    # Signed by decision-surfacer, a DECLARED seat of this mode. The control-plane contract role
    # that "owns" artifact contracts must NOT be named here: control never takes a seat or signs for
    # a worker artifact (D7), and the seat census reads recipe source text, so even a mention would
    # register as an undeclared dispatch. A cross-artifact disagreement is what decision-surfacer
    # exists to put in front of the director, so it is also the honest owner of this verdict.
    put("design-consistency-verdict", "analysis_check_verdict", "decision-surfacer",
        {"panel_role": "compliance", "pass": not consistency, "violations": consistency,
         "checked_items": sorted(_ids(matrix["conditions"], "id")),
         "notes": "cross-artifact design consistency: research question, hypothesis coverage, "
                  "condition set, baseline, artifact handoffs, split vocabulary, variable "
                  "declaration, audit independence, preregistered-metric implementability"},
        "blocked" if consistency else "approved")
    if consistency:
        raise GateBlock(f"design cross-artifact consistency BLOCK: {consistency}")

    # All three audits are computed and persisted before any of them halts the run: the director is
    # owed every independent verdict, not just the first one that failed.
    af = b["alignment_facts"]
    design_variables = (b["experiment_design"].get("variables") or {})
    # A zero-training pipeline (frozen model, inference only) has no training run to keep parity
    # with, so the parity invariants are unsatisfiable rather than violated. The escape hatch is
    # DUAL-LOCKED on purpose: the auditor's own declared fact AND an explicit zero_training entry in
    # the design's frozen-variable list. One unchecked flag from either side is never enough.
    zero_training = detect_zero_training(
        bool(af.get("zero_training")), design_variables.get("frozen") or [])
    # The variables the experiment actually STUDIES. A metric implementation that differs across
    # conditions along one of these is the treatment, not an inconsistency — the ` -- <reason>`
    # suffix the packets allow is stripped before matching.
    studied_variables = {
        str(v).split(" --")[0].strip().casefold()
        for v in (design_variables.get("studied") or [])
    }
    audits = (
        ("variable-control-report", "variable_control_report", "variable-control-auditor",
         vc_build(matrix, profile=profile,
                  leakage_flagged=bool(b["variable_control_facts"].get("leakage_flagged")))),
        ("alignment-report", "alignment_report", "train-test-alignment-auditor",
         alignment_build(af.get("train") or {}, af.get("test") or {}, profile=profile,
                         train_ref=str(af.get("train_split") or ""),
                         test_ref=str(af.get("test_split") or ""),
                         zero_training=zero_training)),
        ("metric-impl-report", "metric_impl_report", "metric-implementation-auditor",
         metric_build(b["metric_impl_facts"].get("conditions") or [], profile=profile,
                      studied_variables=studied_variables)),
    )
    for stem, atype, seat, verdict in audits:
        put(stem, atype, seat, verdict, "blocked" if verdict["verdict"] == "BLOCK" else "approved")
    blocked = [f"{seat}: {verdict['violations']}" for _s, _a, seat, verdict in audits
               if verdict["verdict"] == "BLOCK"]
    if blocked:
        raise GateBlock(f"independent DESIGN audit BLOCK — {'; '.join(blocked)}")
    vc, alignment, metric = (row[3] for row in audits)

    try:
        prereg = build_prereg(
            matrix, primary_metric=str(acceptance.get("primary_metric") or ""),
            n_seeds_planned=acceptance.get("n_seeds_planned"),
            stopping_rule=str(acceptance.get("stopping_rule") or ""),
            analysis_plan=str(acceptance.get("analysis_plan") or ""),
            secondary_metrics=[str(m) for m in acceptance.get("secondary_metrics") or []])
    except (ValueError, TypeError) as exc:
        raise GateBlock(f"preregistration BLOCK (the analysis contract is not frozen): {exc}") from exc
    put("preregistration", "preregistration", "decision-surfacer", prereg)
    adrs = _adr_payloads(decisions)
    for row in adrs:
        put(f"adr-{row['decision_id'].lower()}", "adr", "decision-surfacer", row, "draft")

    cond_ids = sorted(_ids(matrix["conditions"], "id"))
    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "DESIGN", ts, mode=MODE, bundles=b,
        downstream_refs=sorted(set(cond_ids)
                               | _ids(b["unified_config"].get("conditions") or [], "condition_id")
                               | _ids(b["integration_plan"].get("conditions") or [], "condition_id")
                               | {str(k) for k in (coverage or {})}),
        known_ids=set(cond_ids) | _ids(chain.get("hypotheses") or [], "hypothesis_id"))
    paths.extend(gate_paths)

    report = {"consistency_gate": "PASS", "variable_control_gate": vc["verdict"],
              "alignment_gate": alignment["verdict"], "metric_impl_gate": metric["verdict"],
              "n_conditions": len(cond_ids), "n_hypotheses": len(chain.get("hypotheses") or []),
              "n_open_director_decisions": len(adrs), "prereg_frozen": True,
              "execution_state": state.get("label"), "executed": bool(state.get("executed")),
              "reported_metric_values": 0}
    report.update(frag)
    report["director_markdown"] = _panel_recipe.render_director_markdown(
        run_dir, MODE, _sections(chain, matrix, coverage, b["split_manifest"], b["data_protocol"],
                                 b["unified_config"], b["integration_plan"],
                                 b["baseline_fairness_plan"], vc, alignment, metric, prereg, adrs,
                                 state),
        ts=ts, lead="DESIGN ONLY — no experiment has been executed",
        extra={"Execution boundary": _panel_recipe.execution_boundary_section(state)})
    return paths, report


# --------------------------------------------------------------------------- director Markdown

def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c).replace("\n", " ") for c in row) + " |" for row in rows]
    return "\n".join(out)


def _sections(chain, matrix, coverage, split, protocol, config, integration, fairness, vc,
              alignment, metric, prereg, adrs, state) -> dict:
    """The registry's six required sections. Every one is PLANNED work; none is a measurement."""
    conditions = matrix.get("conditions") or []
    baseline = next((str(c.get("id")) for c in conditions if c.get("baseline")), "—")
    coverage = coverage if isinstance(coverage, dict) else {}
    variables = matrix.get("variables") or {}
    modules = {str(c.get("condition_id")): c for c in integration.get("conditions") or []}

    rq = (f"**Research question (frozen):** {matrix.get('research_question')}\n\n"
          + _table(["hypothesis", "claim", "falsifiable prediction", "tested by"],
                   [[h.get("hypothesis_id"), h.get("statement"), h.get("falsifiable_prediction"),
                     ", ".join(str(c) for c in coverage.get(str(h.get("hypothesis_id"))) or []) or "—"]
                    for h in chain.get("hypotheses") or []])
          + f"\n\nThese are hypotheses to be tested, not findings. Nothing below has been run "
            f"(execution state: `{state.get('label')}`).")

    cond = (_table(["condition", "role", "factors", "runs on"],
                   [[c.get("id"), "baseline" if c.get("baseline") else "treatment",
                     ", ".join(f"{k}={v}" for k, v in (c.get("factors") or {}).items()) or "—",
                     modules.get(str(c.get("id")), {}).get("module") or "(baseline — no new code)"]
                    for c in conditions])
            + f"\n\n- **studied:** {', '.join(variables.get('studied') or []) or 'none declared'}\n"
              f"- **controlled:** {', '.join(variables.get('controlled') or []) or 'none declared'}\n"
              f"- **frozen:** {', '.join(variables.get('frozen') or []) or 'none declared'}\n\n"
              f"Variable-control audit: **{vc['verdict']}** "
              f"({vc.get('n_confounded_conditions', 0)} confounded contrast(s)). Every contrast is "
              f"against baseline `{baseline}`; only studied factors may differ.")

    data = (_table(["split", "fraction", "units", "stratified by", "frozen"],
                   [[s.get("name"), s.get("fraction"), s.get("n_units") if s.get("n_units") is not None
                     else "not counted yet", ", ".join(s.get("stratification_keys") or []) or "—",
                     "yes" if s.get("frozen") else "no"] for s in split.get("splits") or []])
            + f"\n\n- **split unit:** `{split.get('split_unit')}`\n"
              f"- **leakage declaration (split):** {split.get('leakage_declaration')}\n"
              f"- **leakage declaration (design):** {matrix.get('leakage_declaration')}\n\n"
            + _table(["step", "kind", "train only", "applies to", "what it does"],
                     [[s.get("step_id"), s.get("kind"), "yes" if s.get("train_only") else "no",
                       ", ".join(s.get("applies_to_splits") or []) or "(inferred)",
                       s.get("description")] for s in protocol.get("steps") or []])
            + f"\n\nTrain/eval alignment audit: **{alignment['verdict']}** — trains on "
              f"`{alignment.get('train_ref')}`, evaluates on `{alignment.get('test_ref')}`. "
              f"Unit counts are `not counted yet` wherever the data has not been counted; no count "
              f"here is a measurement.")

    method = (_table(["condition", "module", "entry point", "code change", "dependencies"],
                     [[c.get("condition_id"), c.get("module") or "null (baseline)",
                       c.get("entry_point"), c.get("patch_description") or "—",
                       ", ".join(c.get("dependencies") or []) or "—"]
                      for c in integration.get("conditions") or []])
              + f"\n\n**Shared infrastructure:** {integration.get('shared_infra_notes') or 'not declared'}\n\n"
              + _table(["fairness check", "baseline value (planned)", "treatments (planned)", "mismatch"],
                       [[c.get("check_name"), c.get("baseline_value"),
                         ", ".join(f"{k}={v}" for k, v in (c.get("treatment_values") or {}).items()) or "—",
                         "yes" if c.get("mismatch_detected") else "no"]
                        for c in fairness.get("fairness_checks") or []])
              + "\n\nFairness violations: "
              + (f"{fairness['fairness_violations']} — justified as: "
                 f"{fairness.get('override_justification')}" if fairness.get("fairness_violations")
                 else "none found — data, compute and metric configuration were each checked against "
                      "the baseline.")
              + "\n\nEvery value above is a planned setting; none was produced by a run.")

    metrics_md = (f"- **primary metric (preregistered):** `{prereg.get('primary_metric')}`\n"
                  f"- **secondary metrics:** "
                  f"{', '.join('`' + m + '`' for m in prereg.get('secondary_metrics') or []) or 'none'}\n"
                  f"- **seeds planned per condition:** {prereg.get('n_seeds_planned')}\n"
                  f"- **stopping rule:** {prereg.get('stopping_rule')}\n"
                  f"- **analysis plan:** {prereg.get('analysis_plan')}\n\n"
                  f"Metric-implementation audit: **{metric['verdict']}** over "
                  f"{len(metric.get('checked_metrics') or [])} metric(s) "
                  f"({', '.join('`' + m + '`' for m in metric.get('checked_metrics') or []) or '—'}); "
                  f"missing from some condition: {metric.get('missing_metrics') or 'none'}; "
                  f"implementation mismatches: {metric.get('impl_mismatches') or 'none'}.\n\n"
                  f"The analysis contract is frozen BEFORE any number exists, so a later run cannot "
                  f"pick the metric that happened to win. **This section contains no results — "
                  f"0 metric values are reported, because nothing has been measured.**")

    risks = ("**Open decisions — the director decides these, the machine has not:**\n\n"
             + (_table(["ADR", "decision", "options", "would freeze"],
                       [[r["decision_id"], r["question"], " / ".join(r["options"]),
                         ", ".join(r["downstream_locked_artifacts"]) or "—"] for r in adrs])
                if adrs else "none surfaced")
             + f"\n\nEvery ADR above is `proposed` with no chosen option: the recipe assigns the id "
               f"and the status, so no model can record a choice on the director's behalf.\n\n"
               f"**Design risks carried forward:**\n\n"
             + "\n".join(
                 [f"- residual confound risk: {vc.get('n_confounded_conditions', 0)} contrast(s) flagged; "
                  f"invariants checked: {', '.join(vc.get('checked_invariants') or []) or 'none from a profile'}",
                  f"- alignment invariants checked: "
                  f"{', '.join(alignment.get('checked_invariants') or []) or 'none from a profile'}",
                  f"- unit counts are unknown until the data is counted (`n_units: null` above)",
                  f"- **nothing has been executed**: execution state `{state.get('label')}` — "
                  f"this document is a plan, and every number in it is a target or a parameter."]))

    return {"Research question and hypotheses": rq, "Variables and conditions": cond,
            "Data and split protocol": data, "Method and baseline fairness": method,
            "Metrics and analysis plan": metrics_md, "Risks and director decisions": risks}


# --------------------------------------------------------------------------- spine contract

def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DESIGN":
        return _design_dets(run_dir, ts)
    if stage == "REPORT":
        return _panel_recipe.report_note(
            run_dir, ts, mode=MODE,
            summary="design_experiment: an 11-seat DESIGN panel (frame -> protocol -> three "
                    "independent audits) produced a cross-artifact-consistent experiment design and "
                    "a deterministically rendered director brief. PLANNED work only — no experiment "
                    "was executed and no metric is reported.",
            references=[str(_panel_recipe.target_markdown(MODE)["path"])],
            open_questions=["the proposed ADRs are unresolved until the director chooses"])
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
