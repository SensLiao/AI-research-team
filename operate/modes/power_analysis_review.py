"""Operate recipe for the `power_analysis_review` mode (DESIGN -> REPORT) — wave 2.

The registry's own `productization_gaps` named the exact failure this recipe fixes: "a power
auditor that validates its own assumptions and then interprets its own result is a self-approval."
This recipe wires the registry-declared three-seat panel — a staged input -> computation ->
independent-review chain built on `_panel_recipe` — instead of one worker marking its own homework:

  - `data-protocol-designer` (validate_inputs) freezes the reviewed design's data handling into the
    schema's `data_protocol` (`steps` + `notes`). The schema has no dedicated fields for sample
    size / endpoint / grouping / missingness, so this seat writes them as an ITEMIZED, auditable
    restatement inside `notes` — the one place they legitimately live without inventing a new
    artifact type ("artifact 类型不许发明").
  - `statistics-power-auditor` (compute_power) reads that protocol and DECLARES a floor of
    `MIN_SENSITIVITY_SCENARIOS` labeled assumption sets in its bundle (never a single point
    estimate — the 2026-08-03 measurement showed "at most N" prompt wording alone crushes a
    worker's output, so every quantity here is phrased as a floor). `run_dets` then RECOMPUTES
    every scenario's power with `tools.stats_test.approx_paired_power` and re-derives `sufficient`
    from the same n_seeds-vs-floor rule the auditor's own agent card documents — the worker's
    numbers are evidence for the gate, never the verdict itself.
  - `methodology-reviewer` (independent_interpretation) reads both bundles WITHOUT recomputing
    anything and challenges their assumptions. Its `panel_review` (lens=methodology) must carry a
    non-blank `reviewer_notes` — an empty rubber stamp would defeat the entire point of a THIRD,
    independent seat, so it is refused.

Markdown rendering is deterministic (`_panel_recipe.render_director_markdown`; no worker ever
authors it), so a self-approving "sufficient: true/false" binary can never stand in for the
registry-required "decision options" — the renderer always assembles concrete, evidence-grounded
design-change options from the recomputed scenarios plus the independent reviewer's notes.
"""
from __future__ import annotations

from typing import Optional

from . import _panel_recipe as pr
from . import _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ...tools.stats_test import approx_paired_power

MODE = "power_analysis_review"
STAGES = ["DESIGN", "REPORT"]           # mirrors the registry's stage_path (see mode_registry.yaml)
DEFAULT_VAULT = pr.DEFAULT_VAULT

MIN_SENSITIVITY_SCENARIOS = 3     # FLOOR: a single scenario is a point estimate wearing a
                                  # sensitivity-analysis costume — this mode's worst failure mode
POWER_TOLERANCE = 0.03            # recomputation match band for the worker-reported power
DEFAULT_SEED_FLOOR = 3            # the auditor's own agent-card fallback when no profile minimum is
                                  # declared: "domain-standard practice (>=3 seeds...)"
TARGET_POWER = 0.8                # conventional target power for the "what would it take" option

_REQUIRED_SCENARIO_KEYS = ("label", "mean_diff", "sd_diff", "n", "alpha", "reported_power", "rationale")


# --------------------------------------------------------------------------- prompts (hand-written)
# Quantities are phrased as FLOORS ("emit >= N", never "at most N") per the 2026-08-03 measurement:
# a cap-worded prompt held a 122-item panel to a handful of rows on the SAME model and inputs.

_DATA_PROTOCOL_PROMPT = """You are the `data-protocol-designer` seat of power_analysis_review's \
validate_inputs stage. Your job is to make the reviewed design AUDITABLE, not to judge it.

REQUEST (the proposed experiment design to review): {request}

{north_star}

Read the request in full; if the director attached upstream design notes under `{run_dir}/inbox/`, \
read those too. Never guess a number the request does not state — an unstated input is reported as \
UNSTATED, never invented.

Emit exactly one `data_protocol` object (schema requires `steps`; `notes` is free text):
  - `steps`: the concrete data-handling steps this design relies on (>=1) — e.g. how missing data \
is imputed/dropped (kind "preprocessing" or "resampling"), any normalization, any postprocessing of \
the primary endpoint. Any step with kind "augmentation" MUST carry `train_only: true` \
(schema-enforced — test-time augmentation is a leakage bug).
  - `notes`: an ITEMIZED, auditable restatement of sample size, primary endpoint (what is measured, \
at what timepoint), grouping/arms (how units are assigned, ratio), and missingness assumptions \
(expected dropout and how it is handled). Write "UNSTATED — <what is missing>" for anything the \
request does not specify; never fill a gap with a guess.

HONESTY (hard): never invent a sample size, endpoint, or protocol detail the request does not \
support. If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what it names, change nothing \
else, and re-emit the COMPLETE bundle — never argue with the gate, never relax honesty.

Write ONLY this JSON to `{out}`:
{{"data_protocol": {{"from_split_manifest_ref": null,
  "steps": [{{"step_id": "s1", "kind": "preprocessing", "description": "<what it does>",
             "train_only": true, "params": {{}}, "applies_to_splits": []}}],
  "notes": "Sample size: ... Primary endpoint: ... Grouping: ... Missingness: ..."}}}}
Return one line: step count and whether any input was UNSTATED."""

_POWER_AUDITOR_PROMPT = """You are the `statistics-power-auditor` seat of power_analysis_review's \
compute_power stage: assess whether this design can actually detect what it targets.

REQUEST (the proposed experiment design to review): {request}

{north_star}

Read `{dp_bundle}` (the frozen data protocol and its sample/endpoint/grouping/missingness notes) \
before you compute anything.

Quantities below are FLOORS with NO upper bound — more labeled scenarios are always welcome, never \
trim to "the important ones":
  - Emit >= {min_scenarios} labeled sensitivity scenarios — never a single point estimate; a lone \
number dressed as a conclusion is the one thing this seat must never produce. Each scenario needs \
an EXPLICIT, sourced assumption set: `mean_diff` and `sd_diff` (from a stated pilot/prior result, \
or an explicitly labeled convention such as a Cohen's-d small/medium/large bracket — say which), an \
`n` (seeds/units actually analyzable — vary this across scenarios when dropout would shrink it), \
and `alpha`. Compute each scenario's power yourself with the standard paired z-approximation and \
report it as `reported_power`; you will be independently re-checked, so compute honestly rather \
than defensively.
  - At least one scenario must use the MOST CONSERVATIVE credible assumption (smallest effect / \
largest dropout) — sensitivity analysis exists to show the discouraging case, not just the hopeful \
one.
  - Derive `sufficient` from the seed-count rule: `n_seeds_declared >= min_seeds_required` when a \
minimum is stated; otherwise apply the domain-standard floor of {seed_floor} seeds. Never set \
`sufficient: true` when the count fails that rule.
  - List concrete `power_concerns` (e.g. "n=1 gives no variance estimate").

HONESTY (hard): never invent `mean_diff`/`sd_diff` with no stated or explicitly-labeled-conventional \
source; a design with no usable effect-size basis still gets >= {min_scenarios} scenarios built \
from labeled conventional brackets, explicitly marked as conventions, never presented as measured. \
If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what it names, change nothing else, and \
re-emit the COMPLETE bundle — never argue with the gate, never relax honesty.

Write ONLY this JSON to `{out}`:
{{"power_audit_report": {{"sufficient": true, "n_seeds_declared": 0, "min_seeds_required": null,
   "power_concerns": ["..."], "adr_override_ref": null, "notes": "...",
   "sensitivity_scenarios": [{{"label": "conservative", "mean_diff": 0.0, "sd_diff": 0.0, "n": 0,
     "alpha": 0.05, "reported_power": 0.0,
     "rationale": "<source: pilot ref, prior result, or labeled convention>"}}]}}}}
Return one line: n_seeds_declared, sufficient, and the number of scenarios emitted."""

_METHODOLOGY_REVIEWER_PROMPT = """You are the `methodology-reviewer` seat of power_analysis_review's \
independent_interpretation stage. You did NOT design the protocol and you did NOT compute the power \
numbers — your job is to independently interpret them and challenge their assumptions. A bare \
"sufficient: true/false" restatement is a self-approval and is exactly what this third seat exists \
to prevent.

REQUEST (the proposed experiment design to review): {request}

{north_star}

Read, without editing:
  - `{dp_bundle}`
  - `{pa_bundle}` (including its `sensitivity_scenarios` — check whether the scenarios span a \
credible range and whether the conservative case was taken seriously, not buried).

For each concern, add a finding: `anchor` (the exact scenario/assumption/step you are citing, \
non-blank), `evidence` (non-blank, specific), `severity` (BLOCK only for a methodological flaw that \
invalidates the whole analysis — e.g. an unaccounted leakage step or an internally inconsistent \
sufficient verdict; WARN for an addressable weakness; NOTE for advisory).

`reviewer_notes` is MANDATORY and is where the decision options belong (never leave it blank) — lay \
out at least two concrete, costed alternatives the director could choose between (e.g. "collect 2 \
more seeds to reach the declared floor" vs. "accept the conservative-scenario power and narrow the \
claim accordingly"), not a single up/down recommendation.

HONESTY (hard): never invent a number neither prior bundle stated; if you found no issues say so \
explicitly in `reviewer_notes` rather than leaving it implicit. If this prompt carries a REPAIR \
ATTEMPT block: fix EXACTLY what it names, change nothing else, and re-emit the COMPLETE bundle — \
never argue with the gate, never relax honesty.

Write ONLY this JSON to `{out}`:
{{"panel_review": {{"lens": "methodology", "findings": [{{"anchor": "...", "evidence": "...",
  "severity": "WARN", "rebuttal_required": false, "finding_id": "meth-1"}}],
  "reviewer_notes": "<decision options, costed, plural>"}}}}
Return one line: finding count by severity and whether you flagged the sufficient verdict itself."""


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The registry's staged input -> computation -> independent-review panel. REPORT is deterministic."""
    if stage != "DESIGN":
        return None
    north_star = _shared.north_star_block(run_dir)
    dp_out = pr.bundle_path(run_dir, "DESIGN", "data-protocol-designer")
    pa_out = pr.bundle_path(run_dir, "DESIGN", "statistics-power-auditor")
    mr_out = pr.bundle_path(run_dir, "DESIGN", "methodology-reviewer")
    seats = [
        # `design`, not `reason`: this seat designs the measurement protocol the power audit is
        # computed against, so it is experiment design and stays on the frontier tier.
        pr.Seat(label="data-protocol-designer", bundle_key="data_protocol", tier="design",
                prompt=_DATA_PROTOCOL_PROMPT.format(
                    request=request, north_star=north_star, run_dir=run_dir, out=dp_out)),
        pr.Seat(label="statistics-power-auditor", bundle_key="power_audit_report", tier="audit",
                depends_on=("data-protocol-designer",),
                prompt=_POWER_AUDITOR_PROMPT.format(
                    request=request, north_star=north_star, dp_bundle=dp_out, out=pa_out,
                    min_scenarios=MIN_SENSITIVITY_SCENARIOS, seed_floor=DEFAULT_SEED_FLOOR)),
        pr.Seat(label="methodology-reviewer", bundle_key="panel_review", tier="audit",
                depends_on=("data-protocol-designer", "statistics-power-auditor"),
                prompt=_METHODOLOGY_REVIEWER_PROMPT.format(
                    request=request, north_star=north_star, dp_bundle=dp_out, pa_bundle=pa_out,
                    out=mr_out)),
    ]
    return pr.panel(run_dir, "DESIGN", MODE, seats,
                    panel_note="Freeze the reviewed design's data protocol; independently compute a "
                               "floor of labeled power/sensitivity scenarios; then independently "
                               "interpret and challenge those assumptions without recomputing them.",
                    model_policy=model_policy)


def _load_seats() -> list:
    """label/bundle_key pairs for `pr.load_seat_bundles` — labels must match `llm_step`'s dispatch."""
    return [pr.Seat(label=label, bundle_key=key, prompt="") for label, key in (
        ("data-protocol-designer", "data_protocol"),
        ("statistics-power-auditor", "power_audit_report"),
        ("methodology-reviewer", "panel_review"),
    )]


def _defect(defect_id: str, location: str, summary: str, *agents: str) -> dict:
    return {"defect_id": defect_id, "location": location, "summary": summary,
            "target_agents": list(agents), "refresh_agents": []}


def _normalize(run_dir, agent: str, artifact_type: str, payload: dict) -> dict:
    """Schema-normalize one seat's raw payload; an unresolvable gap is a repairable supplement."""
    normalized, errors, _report = _shared.normalize_worker_payload(
        run_dir, "DESIGN", agent, artifact_type, payload, label=artifact_type)
    if errors:
        raise TargetedGateBlock(
            f"power_analysis_review {artifact_type} needs a local supplement after normalization: "
            f"{errors}",
            [_defect(f"power-analysis-review-schema-{artifact_type.replace('_', '-')}",
                     f"DESIGN/{agent}/{artifact_type}", "; ".join(errors)[:2000], agent)])
    return normalized


def _validate_scenarios(scenarios) -> list:
    """Deterministic floor + explicit-assumption + recomputation gate (this mode's own hard gate).

    A single scenario, a scenario missing an explicit input, or a `reported_power` the standard
    paired z-approximation cannot reproduce all BLOCK — the worker's numbers are evidence for this
    gate, never the verdict.
    """
    if not isinstance(scenarios, list) or len(scenarios) < MIN_SENSITIVITY_SCENARIOS:
        n = len(scenarios) if isinstance(scenarios, list) else 0
        raise TargetedGateBlock(
            f"power_analysis_review compute_power emitted {n} sensitivity scenario(s), below the "
            f"floor of {MIN_SENSITIVITY_SCENARIOS} — a single point estimate dressed as a "
            f"conclusion is this mode's worst failure mode.",
            [_defect("power-analysis-review-scenario-floor",
                     "DESIGN/statistics-power-auditor/sensitivity_scenarios",
                     f"Emit >= {MIN_SENSITIVITY_SCENARIOS} labeled scenarios, each with an explicit "
                     f"mean_diff/sd_diff/n/alpha/rationale and a reported_power.",
                     "statistics-power-auditor")])
    rows = []
    for raw in scenarios:
        if not isinstance(raw, dict):
            raise TargetedGateBlock(
                "power_analysis_review compute_power emitted a non-object sensitivity scenario",
                [_defect("power-analysis-review-scenario-shape",
                         "DESIGN/statistics-power-auditor/sensitivity_scenarios",
                         "Every sensitivity scenario must be a JSON object with the documented keys.",
                         "statistics-power-auditor")])
        label = raw.get("label")
        missing = [k for k in _REQUIRED_SCENARIO_KEYS if raw.get(k) in (None, "")]
        if missing:
            raise TargetedGateBlock(
                f"power_analysis_review sensitivity scenario {label!r} is missing explicit "
                f"assumption(s) {missing} — every scenario's inputs must be stated, never implied.",
                [_defect("power-analysis-review-scenario-explicit",
                         "DESIGN/statistics-power-auditor/sensitivity_scenarios",
                         f"Scenario {label!r} must state {missing} explicitly.",
                         "statistics-power-auditor")])
        try:
            mean_diff = float(raw["mean_diff"]); sd_diff = float(raw["sd_diff"])
            n = int(raw["n"]); alpha = float(raw["alpha"]); reported = float(raw["reported_power"])
        except (TypeError, ValueError) as exc:
            raise TargetedGateBlock(
                f"power_analysis_review scenario {label!r} has a non-numeric assumption field: {exc}",
                [_defect("power-analysis-review-scenario-type",
                         "DESIGN/statistics-power-auditor/sensitivity_scenarios",
                         f"Scenario {label!r} must give numeric mean_diff/sd_diff/n/alpha/"
                         f"reported_power.", "statistics-power-auditor")]) from exc
        recomputed = approx_paired_power(mean_diff, sd_diff, n, alpha)
        if abs(recomputed - reported) > POWER_TOLERANCE:
            raise TargetedGateBlock(
                f"power_analysis_review scenario {label!r} claims reported_power={reported} but "
                f"the deterministic recomputation gives {round(recomputed, 4)} — outside the "
                f"{POWER_TOLERANCE} tolerance band.",
                [_defect("power-analysis-review-power-recompute",
                         "DESIGN/statistics-power-auditor/sensitivity_scenarios",
                         f"Recompute scenario {label!r}'s power with the standard paired "
                         f"z-approximation; the declared reported_power did not match.",
                         "statistics-power-auditor")])
        rows.append({**raw, "mean_diff": mean_diff, "sd_diff": sd_diff, "n": n, "alpha": alpha,
                    "reported_power": reported, "recomputed_power": round(recomputed, 4)})
    return rows


def _check_sufficient(power_audit: dict) -> None:
    """Re-derive `sufficient` from the seed-count rule — never trust the worker's own say-so."""
    n_seeds = power_audit.get("n_seeds_declared")
    floor = power_audit.get("min_seeds_required")
    floor = floor if isinstance(floor, int) else DEFAULT_SEED_FLOOR
    expected = isinstance(n_seeds, int) and n_seeds >= floor
    if bool(power_audit.get("sufficient")) != expected:
        raise TargetedGateBlock(
            f"power_analysis_review power_audit_report claims sufficient="
            f"{power_audit.get('sufficient')!r} but n_seeds_declared={n_seeds!r} vs the floor "
            f"{floor} derives {expected} — sufficient must follow the seed-count rule, never a "
            f"worker's own say-so.",
            [_defect("power-analysis-review-sufficient-mismatch",
                     "DESIGN/statistics-power-auditor/power_audit_report",
                     f"Re-derive sufficient from n_seeds_declared >= {floor}.",
                     "statistics-power-auditor")])


def _check_panel_review(panel_review: dict) -> None:
    """Discriminator + non-blank-interpretation gate — an empty review is a self-approval by omission."""
    lens = panel_review.get("lens")
    if lens != "methodology":
        raise TargetedGateBlock(
            f"power_analysis_review independent_interpretation expected lens='methodology', got "
            f"{lens!r} — this seat's one declared discriminator for this mode.",
            [_defect("power-analysis-review-lens", "DESIGN/methodology-reviewer/panel_review",
                     "Set lens to 'methodology'.", "methodology-reviewer")])
    if not str(panel_review.get("reviewer_notes") or "").strip():
        raise TargetedGateBlock(
            "power_analysis_review independent_interpretation left reviewer_notes blank — a bare "
            "findings list with no interpretation prose is a self-approval by omission; this third "
            "seat exists specifically to add decision-option prose the first two seats cannot.",
            [_defect("power-analysis-review-reviewer-notes",
                     "DESIGN/methodology-reviewer/panel_review",
                     "Write reviewer_notes with >=2 concrete, costed decision options.",
                     "methodology-reviewer")])


def _scenario_line(row: dict) -> str:
    return (f"- **{row.get('label')}**: mean_diff={row['mean_diff']}, sd_diff={row['sd_diff']}, "
            f"n={row['n']}, alpha={row['alpha']} -> recomputed power={row['recomputed_power']} "
            f"({row.get('rationale')})")


def _min_n_for_target_power(worst: dict, target: float = TARGET_POWER, max_n: int = 1000) -> Optional[int]:
    """Deterministic search: smallest n reaching `target` power under the WORST-CASE scenario's
    effect-size assumption — a real, honest "what would it take" design-change option."""
    mean_diff, sd_diff, alpha = worst["mean_diff"], worst["sd_diff"], worst["alpha"]
    if sd_diff <= 0:
        return None
    for n in range(2, max_n + 1):
        if approx_paired_power(mean_diff, sd_diff, n, alpha) >= target:
            return n
    return None


def _render_sections(ns: dict, data_protocol: dict, power_audit: dict, scenarios: list,
                     panel_review: dict, worst: dict, best: dict, n_for_target) -> dict:
    decision_question = (
        f"{ns['statement']}\n\nCan the proposed design detect the effect it targets with adequate "
        f"statistical power, and if not, what design changes would fix that?"
    )
    steps_lines = "\n".join(
        f"- `{s.get('step_id')}` ({s.get('kind')}, train_only={s.get('train_only')}): "
        f"{s.get('description')}"
        for s in (data_protocol.get("steps") or [])
    ) or "- none declared"
    inputs_and_assumptions = (
        f"{data_protocol.get('notes') or '(no assumption notes recorded)'}\n\n"
        f"Data-handling steps:\n{steps_lines}"
    )
    power_section = (
        f"sufficient (seed-count rule): **{power_audit.get('sufficient')}** — "
        f"n_seeds_declared={power_audit.get('n_seeds_declared')}, "
        f"min_seeds_required={power_audit.get('min_seeds_required')}. Recomputed power across "
        f"{len(scenarios)} scenarios ranges {worst['recomputed_power']:.3f} (worst case, "
        f"{worst.get('label')}) to {best['recomputed_power']:.3f} (best case, {best.get('label')})."
    )
    scenario_lines = "\n".join(_scenario_line(row) for row in scenarios)
    change_options = []
    if n_for_target:
        change_options.append(
            f"- Reach n={n_for_target} (under the conservative {worst.get('label')!r} scenario's "
            f"assumed effect) to cross power>={TARGET_POWER}."
        )
    else:
        change_options.append(
            f"- No seed count up to 1000 reaches power>={TARGET_POWER} under the conservative "
            f"{worst.get('label')!r} scenario's assumed effect size — the design change needed is a "
            f"larger/cleaner effect (tighter protocol, better measurement), not more seeds."
        )
    reviewer_notes = str(panel_review.get("reviewer_notes") or "").strip()
    if reviewer_notes:
        change_options.append(f"- Independent reviewer's options: {reviewer_notes}")
    recommended_changes = "\n".join(change_options)
    findings = panel_review.get("findings") or []
    if findings:
        uncertainty_lines = "\n".join(
            f"- [{f.get('severity')}] {f.get('anchor')}: {f.get('evidence')}" for f in findings
        )
    else:
        uncertainty_lines = "none found — the independent reviewer raised no methodological findings"
    remaining_uncertainty = (
        f"{uncertainty_lines}\n\nThis review is advisory only (gate_level: record_only) — a "
        f"director ADR override is required to proceed with known-insufficient power."
    )
    return {
        "Decision question": decision_question,
        "Inputs and assumptions": inputs_and_assumptions,
        "Power or precision analysis": power_section,
        "Sensitivity scenarios": scenario_lines,
        "Recommended design changes": recommended_changes,
        "Remaining uncertainty": remaining_uncertainty,
    }


def _design_dets(run_dir, ts) -> tuple:
    bundles = pr.load_seat_bundles(run_dir, "DESIGN", MODE, _load_seats())

    data_protocol_raw = bundles["data_protocol"]
    power_audit_value = bundles["power_audit_report"]
    panel_review_raw = bundles["panel_review"]
    if not isinstance(data_protocol_raw, dict):
        raise GateBlock("power_analysis_review data_protocol bundle is not a JSON object")
    if not isinstance(power_audit_value, dict):
        raise GateBlock("power_analysis_review power_audit_report bundle is not a JSON object")
    if not isinstance(panel_review_raw, dict):
        raise GateBlock("power_analysis_review panel_review bundle is not a JSON object")

    power_audit_raw = dict(power_audit_value)
    scenarios = _validate_scenarios(power_audit_raw.pop("sensitivity_scenarios", None))

    paths = []
    data_protocol_payload = _normalize(run_dir, "data-protocol-designer", "data_protocol",
                                       data_protocol_raw)
    paths.append(write_artifact(run_dir, "DESIGN", "data-protocol.artifact.json", "data_protocol",
                                "data-protocol-designer", data_protocol_payload, ts))

    power_audit_payload = _normalize(run_dir, "statistics-power-auditor", "power_audit_report",
                                     power_audit_raw)
    _check_sufficient(power_audit_payload)
    power_audit_payload["power_concerns"] = (
        list(power_audit_payload.get("power_concerns") or [])
        + [_scenario_line(row) for row in scenarios]
    )
    paths.append(write_artifact(run_dir, "DESIGN", "power-audit-report.artifact.json",
                                "power_audit_report", "statistics-power-auditor",
                                power_audit_payload, ts))

    panel_review_payload = _normalize(run_dir, "methodology-reviewer", "panel_review",
                                      panel_review_raw)
    _check_panel_review(panel_review_payload)
    paths.append(write_artifact(run_dir, "DESIGN", "panel-review.artifact.json", "panel_review",
                                "methodology-reviewer", panel_review_payload, ts))

    gate_paths, frag = pr.common_gates(run_dir, "DESIGN", ts, mode=MODE, bundles=bundles)
    paths.extend(gate_paths)

    worst = min(scenarios, key=lambda row: row["recomputed_power"])
    best = max(scenarios, key=lambda row: row["recomputed_power"])
    n_for_target = _min_n_for_target_power(worst)

    ns = _shared.north_star(run_dir)
    sections = _render_sections(ns, data_protocol_payload, power_audit_payload, scenarios,
                                panel_review_payload, worst, best, n_for_target)
    md_rel = pr.render_director_markdown(run_dir, MODE, sections, ts=ts)

    report = {
        "n_scenarios": len(scenarios),
        "sufficient": power_audit_payload.get("sufficient"),
        "n_seeds_declared": power_audit_payload.get("n_seeds_declared"),
        "min_seeds_required": power_audit_payload.get("min_seeds_required"),
        "worst_case_power": worst["recomputed_power"],
        "best_case_power": best["recomputed_power"],
        "n_for_target_power_worst_case": n_for_target,
        "reviewer_findings": len(panel_review_payload.get("findings") or []),
        "reviewer_block_findings": sum(
            1 for f in (panel_review_payload.get("findings") or []) if f.get("severity") == "BLOCK"),
        "director_markdown": md_rel,
    }
    report.update(frag)
    return paths, report


def _report(run_dir, ts) -> tuple:
    return pr.report_note(
        run_dir, ts, mode=MODE,
        summary="power_analysis_review: staged data-protocol / power-and-sensitivity / independent-"
                "methodology-review panel; every sensitivity scenario and the sufficient verdict "
                "were deterministically recomputed, never taken on the worker's word; director "
                "brief rendered with costed design-change options, not a binary self-approval.",
        references=[pr.target_markdown(MODE)["path"]])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DESIGN":
        return _design_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"power_analysis_review has no stage {stage!r}")


run_dets_with_repair = pr.make_repair(MODE, run_dets)
