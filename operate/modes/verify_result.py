"""Operate recipe for the `verify_result` mode (VERIFY -> REPORT) — wave 2, the independence panel.

`verify_result` is the machine's independent second opinion on a result somebody ELSE produced. Its
whole value is REVIEWER SEPARATION, so the recipe is built around the three deterministic guarantees
the registry's `productization_gaps` asked for:

  * **Separate reviewer bundles.** `review-configurator` freezes who reviews what — distinct lens
    territories, validated by `tools/check_review_independence`. Six seats then review IN PARALLEL,
    each writing its OWN bundle (methodology / domain / adversarial / an independent scientific
    critic / a baseline-completeness scout / a sub-domain historian). No dispatch order lets one
    seat read another's output, and `_independence_violations` refuses a bundle that cites a sibling
    seat's output file, re-uses a sibling's finding id, or repeats a sibling's finding text verbatim.
    Contamination is TERMINAL: a reviewer that has seen another verdict cannot be un-seen by a retry.

  * **Evidence coverage.** `review-synthesizer` is the only seat that reads all six. Every claim,
    disagreement and next action it writes must name at least one REAL upstream finding id, critic
    flag or adversarial check; an unresolvable ref — or a conclusion with no ref at all — is the
    "synthesis invented material" failure and blocks. The verdict itself is DERIVED (from
    `tools/check_synthesis_coverage` plus the adversarial gate's own derived verdict), never declared.

  * **Deterministic Markdown.** The director brief is rendered in plain Python from the checked
    payloads (`_panel_recipe.render_director_markdown`), so a required section cannot be dropped and
    reviewer disagreement cannot be quietly resolved into one tidy story.

Two honesty boundaries worth stating out loud:

  * A reviewer BLOCK, an adversarial BLOCK, or an unrebutted critic flag is a legitimate DELIVERED
    outcome — "the panel refuses this result" — not a machine failure. Those flow into
    `panel_synthesis.verdict = BLOCK` and reach the director. Only an INTEGRITY failure halts the
    run: a contaminated reviewer, a silently dropped BLOCK, a fabricated ref, a missing
    "still cannot claim" line.

  * This mode reviews; it never authors and never produces the thing under review (the same split
    the project keeps between `manuscript_authoring` and `manuscript_review`). It never freezes and
    never promotes either: `gate_level` is director_signoff and the vault stays behind
    /promote-to-vault.

`scientific-critic`'s agent card describes it running AFTER the two panel reviews (the M2 / venue
panel shape). In THIS mode the registry's `minimum_worker_pipeline` puts it in the parallel
independent wave, so here it cross-examines the WORK's own internal tensions rather than the other
reviewers' prose — a deliberate, documented difference, not a drift.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ...tools.check_review_independence import check_review_independence
from ...tools.check_synthesis_coverage import check_synthesis_coverage
from ...tools.claim_calibration import build_report as build_calibrated_claims
from ...tools.review_checker import CHECKS as ADVERSARIAL_CHECK_NAMES
from ...tools.review_checker import build_report as build_review_report
from ...tools.validate_artifact import validate_payload

MODE = "verify_result"
STAGES = _panel_recipe.stage_path(MODE)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

CONFIGURATOR = "review-configurator"
METHODOLOGY = "methodology-reviewer"
DOMAIN = "domain-reviewer"
ADVERSARIAL = "adversarial-reviewer"
CRITIC = "scientific-critic"
BASELINE = "baseline-scout"
HISTORIAN = "sub-domain-historian"
SYNTHESIZER = "review-synthesizer"

#: label -> (bundle_key, tier, depends_on). One accountable writer per bundle, three waves:
#: configure -> six genuinely independent reviews -> one synthesis allowed to read all six.
_SEAT_SPECS: Tuple[Tuple[str, str, str, tuple], ...] = (
    (CONFIGURATOR, "review_scope", "audit", ()),
    (METHODOLOGY, "methodology_review", "audit", (CONFIGURATOR,)),
    (DOMAIN, "domain_review", "audit", (CONFIGURATOR,)),
    (ADVERSARIAL, "adversarial_checks", "audit", (CONFIGURATOR,)),
    (CRITIC, "critic_memo", "audit", (CONFIGURATOR,)),
    # `audit`, not `reason`: despite the name this seat is one of `_REVIEWING_SEATS` and answers
    # "is the comparison set complete?" — a quality judgment. An independence panel with one cheap
    # seat has a weak link exactly where independence is the point.
    (BASELINE, "baseline_review", "audit", (CONFIGURATOR,)),
    (HISTORIAN, "historical_review", "audit", (CONFIGURATOR,)),
    (SYNTHESIZER, "synthesis_draft", "audit",
     (METHODOLOGY, DOMAIN, ADVERSARIAL, CRITIC, BASELINE, HISTORIAN)),
)

#: The six seats bound by the independence contract. The configurator scopes and the synthesizer
#: reconciles; only these six must never have seen each other's conclusions.
_REVIEWING_SEATS = (METHODOLOGY, DOMAIN, ADVERSARIAL, CRITIC, BASELINE, HISTORIAN)
_KEY_BY_SEAT = {label: key for label, key, _tier, _deps in _SEAT_SPECS}
#: The four seats that emit a `panel_review`, and the lens each one owns in this mode.
_PANEL_LENS_BY_SEAT = {METHODOLOGY: "methodology", DOMAIN: "domain",
                       BASELINE: "baseline-completeness", HISTORIAN: "historical-context"}
#: `review_config.lenses[].lens` only enumerates these three, so exactly these three must be
#: configured; the other three seats are anchored by their remit plus the synthesis mandate.
_MANDATORY_LENS_SEAT = {"methodology": METHODOLOGY, "domain": DOMAIN, "adversarial": ADVERSARIAL}
_ARTIFACT_FILE_BY_SEAT = {
    METHODOLOGY: "methodology-review.artifact.json",
    DOMAIN: "domain-review.artifact.json",
    BASELINE: "baseline-scout-review.artifact.json",
    HISTORIAN: "sub-domain-historian-review.artifact.json",
    ADVERSARIAL: "review-report.artifact.json",
    CRITIC: "critic-memo.artifact.json",
}
#: Two seats cannot be "independent" while sharing prose. Short strings collide by chance, so the
#: verbatim-copy rule only looks at text long enough to be a real finding.
_COPY_MIN_CHARS = 40
#: A finding id short enough to appear by accident ("F1", "T3") is not evidence that one seat read
#: another; only a distinctive id counts as a cross-seat citation.
_CITED_ID_MIN_CHARS = 4
_MIN_RESOLUTION_NOTE = 20
#: Refs a reviewer may legitimately cite in prose. Tight enough that the pattern only matches
#: something that IS a reference — no prose is ever mistaken for a citation.
_REF_RE = re.compile(
    r"\[\[[a-z0-9]+(?:-[a-z0-9]+)*\]\]"
    r"|(?:doi:|https?://(?:dx\.)?doi\.org/)10\.\d{4,9}/[^\s\"'<>]+"
    r"|arxiv:\s?\d{4}\.\d{4,5}(?:v\d+)?",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- dispatch orders
# Hand-written, one per seat. Quantities are FLOORS with no upper bound: the 2026-08-03 measurement
# showed a worker's volume is set by the wording of its order, and an "at most N" phrasing held a
# 122-paper panel to a handful of rows. Nothing here is templated from the registry.

CONFIGURATOR_PROMPT = """You are the review-configurator — wave 1 of the verify_result independence \
panel. You review nothing yourself: you decide WHO reviews WHAT, and you freeze it before any \
reviewer starts.

    REQUEST: {request}

{north_star}

Read, at these real paths:
  - `{run_dir}/task_frame.artifact.json` — this run's own contract.
  - every result / analysis / protocol / experiment artifact the request names: look under
    `{run_dir}/evidence/` first, else open the path the request gives.
  - the vault at `{vault}/02-wiki/` BY REFERENCE only, to learn what this sub-domain treats as a
    defensible result. Cite pages as real `[[slug]]`s or not at all.

Your job, in order:
  1. Pin the RESULT UNDER REVIEW precisely — which numbers, which table/figure, which claim,
     produced by which run or file. If you cannot pin it to something that really exists, write
     `result_under_review` as "UNPINNED: <exactly what is missing>" instead of guessing. A review
     of an unnamed result is worthless, and saying so is more useful than inventing a target.
  2. Give each lens a DIFFERENT factual territory (`anchor`). Overlapping anchors mean two
     reviewers audit the same passage while nobody audits the rest; a deterministic checker rejects
     duplicate lenses, empty anchors, and byte-identical anchor text.
  3. Fill `inputs_to_review` with the exact artifact/file refs the panel may open — every one a ref
     you actually opened or listed. NEVER put a reviewer's own output, bundle, or receipt in this
     list: the six reviewers must not be able to read each other, and a config that hands them each
     other's output is refused downstream.
  4. Write the `synthesis_mandate`: what the synthesizer MUST cover, what counts as an addressable
     gap versus a fatal one, and the standing rule that reviewer disagreement is REPORTED, never
     settled by preferring the more convenient reviewer.

This mode always seats six independent reviewers: methodology, domain, adversarial, an independent
scientific critic, a baseline-completeness scout, and a sub-domain historian. The `review_config`
contract only carries lens rows for `methodology`, `domain` and `adversarial` — declare all three
(a seat with no configured anchor is refused). The other three are anchored by their own remit plus
your `synthesis_mandate`, so write that mandate wide enough to cover them.

Floors, no ceiling: `inputs_to_review` >= 3 refs when three real ones exist, and each `anchor` is a
full territory description, not a label. Never trim to look tidy.

HONESTY (hard): never invent an artifact path, a `[[slug]]`, a DOI, or a number. If the result under
review is thin, under-specified or missing, that is itself a finding — write it down rather than
inflating the scope so the panel has something to chew on.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, and re-emit the COMPLETE bundle. Never argue with the gate; never relax honesty.

Write ONLY this JSON to `{out}`:
{{
  "review_scope": {{
    "result_under_review": "<the pinned result: metric + table/figure + producing run or file>",
    "result_refs": ["<real artifact/file ref>", "..."],
    "review_config": {{
      "run_ref": "{run_dir}",
      "lenses": [
        {{"lens": "methodology",
          "anchor": "<territory 1 — e.g. statistical design, variable control, split integrity>",
          "reviewer_agent": "methodology-reviewer",
          "notes": "<what is deliberately NOT in this territory>"}},
        {{"lens": "domain",
          "anchor": "<territory 2 — domain invariants, metric validity, protocol fidelity>",
          "reviewer_agent": "domain-reviewer",
          "notes": "<...>"}},
        {{"lens": "adversarial",
          "anchor": "<territory 3 — leakage, unfair baseline, eval frame, provenance, overclaim>",
          "reviewer_agent": "adversarial-reviewer",
          "notes": "<...>"}}
      ],
      "synthesis_mandate": "<what must be covered; addressable vs fatal; disagreement is reported>",
      "inputs_to_review": ["<real artifact/file ref>", "..."]
    }}
  }}
}}
Every `result_refs` entry must also appear in `inputs_to_review`. After writing, verify valid JSON."""

_REVIEWER_CONTRACT = """You are an INDEPENDENT seat. You did not produce the result under review, \
and your job is to check it — not to help it pass.

INDEPENDENCE (hard, and mechanically enforced): read `{config_bundle}` for your anchor and
`review_config.inputs_to_review` for what you may open. You may NOT open, quote, or reason about any
other reviewer's bundle, artifact, receipt or verdict — they are working at the same time as you. A
deterministic checker refuses your bundle if it names another seat's output file, re-uses another
seat's finding id, or repeats another seat's finding text; a contaminated seat is TERMINAL, not
retried. If another reviewer's output somehow became visible to you, say so plainly in your notes
field instead of using it.

HONESTY (hard): never invent a `[[slug]]`, a DOI, a file path or a number. Every finding cites a
real locus you opened. Thin evidence is reported as thin — an empty finding list is a legitimate,
respected answer, and padding it is worse than admitting you found nothing.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, re-emit the COMPLETE bundle. Never argue with the gate; never relax honesty.

Do NOT set `overall_verdict` by hand — it is DERIVED (BLOCK iff you filed a BLOCK finding) and a
declared value that disagrees with your own findings is refused."""

METHODOLOGY_PROMPT = """You are the methodology-reviewer in the verify_result independence panel.

    REQUEST: {request}

{north_star}

{reviewer_contract}

Work your methodology territory to the bottom: variable control (does each condition change only
the studied variable?), statistical design (seeds, n, power, the fairness of the comparison budget),
evaluation framing (is the metric aggregated the way it is defined? does the frame match the
question?), split and leakage STRUCTURE, and reproducibility from declared provenance.

Floors, no ceiling: examine every concern your anchor covers and file EVERY finding that stands on a
real locus — there is no maximum. Do not merge two distinct problems into one row to shorten the
list, and do not drop a defensible NOTE because it is minor.

Write ONLY this JSON to `{out}`:
{{
  "methodology_review": {{
    "lens": "methodology",
    "findings": [
      {{"finding_id": "meth-01",
        "anchor": "<the specific section / table / figure / result you cite>",
        "evidence": "<specific numbers, code paths or text proving it — never a vague worry>",
        "severity": "BLOCK|WARN|NOTE",
        "rebuttal_required": true}}
    ],
    "reviewer_notes": "<what you could NOT check and why — that gap is information>"
  }}
}}
`rebuttal_required` is true exactly when severity is BLOCK. Reserve BLOCK for a defect that makes the
result indefensible as stated. After writing, verify valid JSON."""

DOMAIN_PROMPT = """You are the domain-reviewer in the verify_result independence panel.

    REQUEST: {request}

{north_star}

{reviewer_contract}

Read the active domain profile for this run (metrics, hard_invariants, alignment_invariants,
protocol_fields) and check the work against it: is every hard invariant honoured, is each metric
appropriate and computed on the frame the domain requires, are domain-specific protocol fields
consistent across everything being compared? Read the invariants from the profile every time —
never from memory, never hardcoded.

Floors, no ceiling: one finding per invariant or metric you actually checked and found wanting; file
all of them. If the profile is missing or does not cover this work, that is a finding too.

Write ONLY this JSON to `{out}`:
{{
  "domain_review": {{
    "lens": "domain",
    "findings": [
      {{"finding_id": "dom-01",
        "anchor": "<the claim, result or invariant at issue>",
        "evidence": "<quote the invariant text + the specific result/config that violates it>",
        "severity": "BLOCK|WARN|NOTE",
        "rebuttal_required": true}}
    ],
    "reviewer_notes": "<which profile you read, and what it does not cover>"
  }}
}}
`rebuttal_required` is true exactly when severity is BLOCK. After writing, verify valid JSON."""

ADVERSARIAL_PROMPT = """You are the adversarial-reviewer in the verify_result independence panel. \
Your job is to try to make this result FAIL before anyone leans on it. You are not loyal to the
team's hope.

    REQUEST: {request}

{north_star}

{reviewer_contract}

Investigate all five refutation checks yourself, in the work's own files:
  1. leakage    — re-derive the data path. Does any input touch test labels or a case-specific
                  oracle? Do not trust a dataset card; open the code.
  2. fairness   — same split, same eval frame, same metric definition, same n as the baseline?
                  Find the asymmetry rather than concluding there is none.
  3. eval_frame — open the evaluation code. Is the metric computed and aggregated correctly, on the
                  right frame (raw vs post-processed)? This is where results most often break.
  4. provenance — do the cited commit, data version and env lock exist and reconstruct the number?
  5. overclaim  — does the wording exceed what the number supports?

A claimed pass with no evidence is treated as NOT defensible and forces a block: the verdict is
computed from your five findings by a deterministic checker, so do not write a verdict, a status,
`meets_bar`, or any freeze/accept field — you have no such authority and the human executes any
freeze. Under uncertainty, say what you could not verify; the default is to block, and that is the
correct outcome for an unverified number.

Floors, no ceiling: all five checks must be present, with the fullest evidence you can cite in each.

Write ONLY this JSON to `{out}`:
{{
  "adversarial_checks": {{
    "leakage":    {{"pass": true, "evidence": "<what you opened and what it showed>"}},
    "fairness":   {{"pass": true, "evidence": "<...>"}},
    "eval_frame": {{"pass": true, "evidence": "<...>"}},
    "provenance": {{"pass": true, "evidence": "<...>"}},
    "overclaim":  {{"pass": true, "evidence": "<...>"}}
  }}
}}
After writing, verify valid JSON."""

CRITIC_PROMPT = """You are the scientific-critic in the verify_result independence panel — the seat \
that cross-examines the WORK's own reasoning.

    REQUEST: {request}

{north_star}

{reviewer_contract}

In this mode you run at the SAME TIME as the other reviewers, so you are not summarising them: you
cross-examine the result under review directly. Hunt for internal tensions the work has with itself
— a conclusion its own numbers do not carry, a methodological assumption its domain framing
contradicts, an alternative explanation it never rules out, a metric that answers a different
question than the one asked, a limitation admitted in one place and forgotten in another.

`involved_lenses` names which DIMENSIONS a tension spans (`methodology`, `domain`) — it is not a
claim about what another reviewer said. Set `source` to your OWN assessment plus the locus you read.

A `block_flag` is your statement that the synthesis must not approve without documenting the issue.
File one for every tension you cannot see a path around from the evidence in front of you, and give
`defensible_path` when you can see the minimal change that would fix it (empty when you cannot).

Floors, no ceiling: every tension and every gap you found goes in. An empty `block_flags` list is a
legitimate answer and means the work is internally consistent as far as you could read it — say that
in `critic_notes` rather than manufacturing a flag.

Write ONLY this JSON to `{out}`:
{{
  "critic_memo": {{
    "cross_findings": [
      {{"description": "<the tension, in one specific sentence>",
        "involved_lenses": ["methodology", "domain"],
        "resolution_path": "<how it could be resolved, or empty if you see none>"}}
    ],
    "block_flags": [
      {{"flag_text": "<one-line blocking issue>",
        "source": "<the locus you read + your assessment>",
        "defensible_path": "<minimal change that would make it defensible, or empty>"}}
    ],
    "gaps": ["<important topic the work never addresses>"],
    "critic_notes": "<what you could not read, and what that costs the conclusion>"
  }}
}}
After writing, verify valid JSON."""

BASELINE_PROMPT = """You are the baseline-scout in the verify_result independence panel. Your \
question is not "are the included baselines fair?" but "is the baseline SET complete?".

    REQUEST: {request}

{north_star}

{reviewer_contract}

1. List every baseline the work compares against (method, year, venue).
2. Hunt for the ones it should have included, through the sanctioned read-only connector
   `python -m research_agent_teams.tools.paper_search "<task + dataset query>"` (arXiv / OpenAlex /
   Crossref / Semantic Scholar) plus the vault at `{vault}/02-wiki/` by `[[slug]]`. Search at least
   the task + dataset, the metric + dataset, and the method family.
3. For each candidate the work did NOT compare against, judge honestly whether it is a REAL omission:
   same task, same data regime, published before the work's cutoff, reproducible. A concurrent or
   unpublished method is a NOTE, never a BLOCK.

Never demand "beat SOTA" — completeness is about the comparison SET, not the leaderboard. Every ref
you cite must resolve: a live existence checker runs over your refs and a confirmed-nonexistent ref
is a fabrication signal. If retrieval is unavailable, say so and mark your coverage UNVERIFIED
rather than guessing at what exists.

Floors, no ceiling: check every credible candidate you can retrieve and file every real omission —
there is no cap, and a long honest list is the point of this seat.

Write ONLY this JSON to `{out}`:
{{
  "baseline_review": {{
    "lens": "baseline-completeness",
    "findings": [
      {{"finding_id": "base-01",
        "anchor": "<the comparison table or claim the baseline is missing from>",
        "evidence": "<missing method + its real ref (doi:/ arXiv: / [[slug]]) + why comparable>",
        "severity": "BLOCK|WARN|NOTE",
        "rebuttal_required": false}}
    ],
    "reviewer_notes": "<how many candidates you checked, which channels answered, what was UNVERIFIED>"
  }}
}}
BLOCK only when a clearly stronger, clearly comparable published baseline is absent AND the work's
central claim depends on being best. After writing, verify valid JSON."""

HISTORIAN_PROMPT = """You are the sub-domain-historian in the verify_result independence panel. \
Where the baseline seat asks what method is missing from the table, you ask what HISTORY is missing \
from the story.

    REQUEST: {request}

{north_star}

{reviewer_contract}

1. Read the work's positioning and related-work claims.
2. Reconstruct the sub-domain's real trajectory from the vault at `{vault}/02-wiki/papers/` by
   reference (cite real `[[slug]]`s); the run's own evidence and any search bundle supplement it.
3. For each positioning claim, judge: is the lineage attributed correctly? Is "first to X" really
   first within the cited scope? Does the work revive an abandoned direction without addressing why
   it was abandoned (cite the paper that abandoned it)? Has the sub-domain moved on in a way the
   work never engages with?

Do not punish honest scoping — a narrow, stated scope for a "first" claim is legitimate. Never
invent a slug or a lineage fact; every historical claim points at a real page or a resolvable ref.

Floors, no ceiling: reconstruct at least a 3-5 hop trajectory and file every mis-positioning you can
substantiate.

Write ONLY this JSON to `{out}`:
{{
  "historical_review": {{
    "lens": "historical-context",
    "findings": [
      {{"finding_id": "hist-01",
        "anchor": "<the positioning or novelty claim>",
        "evidence": "<the lineage facts with [[slug]] / doi: refs>",
        "severity": "BLOCK|WARN|NOTE",
        "rebuttal_required": false}}
    ],
    "reviewer_notes": "<the trajectory you reconstructed, hop by hop, and where the vault is silent>"
  }}
}}
BLOCK only for a false novelty or lineage claim that is central to the contribution. After writing,
verify valid JSON."""

SYNTHESIZER_PROMPT = """You are the review-synthesizer — the ONLY seat allowed to read all six \
independent reviews. You reconcile them; you do not re-review, and you never produce or repair the \
work under review.

    REQUEST: {request}

{north_star}

Read all six, at these real paths, plus the frozen scope in `{config_bundle}`:
  - `{methodology_bundle}`   (methodology findings)
  - `{domain_bundle}`        (domain findings)
  - `{adversarial_bundle}`   (the five refutation checks)
  - `{critic_bundle}`        (cross-findings and block flags)
  - `{baseline_bundle}`      (missing-baseline findings)
  - `{historical_bundle}`    (lineage findings)

Four rules that a deterministic checker enforces, so read them as hard constraints:

  1. **Nothing may be dropped.** Every reviewer BLOCK finding and every critic `block_flag` must
     appear in EXACTLY one of `addressed_blocks` (with a real rebuttal citing run evidence),
     `unaddressed_blocks`, or `open_critic_flags`. Silently omitting one halts the run. Leaving one
     unaddressed is allowed and honest — it simply means the panel blocks this result, which is a
     legitimate answer you must be willing to give.
  2. **Nothing may be invented.** Every claim, every position inside a disagreement, and every next
     action must cite >=1 real upstream ref: a reviewer `finding_id`, a critic `flag_text`, an
     adversarial check name (leakage / fairness / eval_frame / provenance / overclaim), or
     `cross-<N>` for the Nth entry of the critic's `cross_findings` (1-based, in its own order). A
     ref nobody produced, or a conclusion with no ref, halts the run.
  3. **Disagreement is reported, never resolved by preference.** Every one of the critic's
     `cross_findings` must be picked up by a `disagreements` entry naming it, and every disagreement
     must carry >=2 positions on DIFFERENT lenses, each with its own text and refs. You may only
     mark `resolution: "resolved_by_evidence"` when the evidence itself settles it — and then write
     out that evidence. Otherwise it stays `"unresolved"` and BOTH positions go to the director.
  4. **Every claim states what it still cannot support.** `cannot_claim` is mandatory and non-empty
     on every claim; a claim without it halts the run. This is the field that stops a verified
     result from silently growing into a bigger one, so write the real limit — the population it
     does not cover, the condition it was not tested under, the generalisation it does not license.

You do not set the verdict, and you do not calibrate strength: give the honest numbers
(`delta`, `variance`) and whatever strength the source claimed (`original_strength`), and a
deterministic calibrator recomputes it. If a number is not available, use null — never fill it in to
make a claim look stronger, and never restate a number you did not read in a real file.

Floors, no ceiling: one claim row per distinct assertion the result makes (>=1, and every one that
matters), every disagreement, and one next action per gap that has an owner. Never shorten the lists
to look decisive.

HONESTY (hard): no invented refs, no invented numbers, no rebuttal you cannot ground in run
evidence. If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names,
change nothing else, re-emit the COMPLETE bundle, and never argue with the gate.

Write ONLY this JSON to `{out}`:
{{
  "synthesis_draft": {{
    "overall_summary": "<what the panel collectively found, in plain prose>",
    "addressed_blocks": [
      {{"block_source": "<the finding_id / anchor / flag_text verbatim>",
        "rebuttal": "<why it does not stand, citing run evidence>"}}
    ],
    "unaddressed_blocks": ["<finding_id / anchor you could not rebut>"],
    "open_critic_flags": ["<flag_text you could not resolve>"],
    "disagreements": [
      {{"topic": "<what the panel disagrees about>",
        "critic_cross_finding_ref": "cross-1",
        "positions": [
          {{"lens": "methodology", "position": "<this lens's reading>", "finding_refs": ["meth-01"]}},
          {{"lens": "domain", "position": "<the other reading>", "finding_refs": ["dom-02"]}}
        ],
        "resolution": "unresolved",
        "resolution_note": "<why the evidence does not settle it, or the evidence that does>"}}
    ],
    "claims": [
      {{"original_claim": "<the claim as the result states it>",
        "metric": "<metric name or null>", "delta": 0.021, "variance": 0.014,
        "original_strength": "strong|moderate|marginal|inconclusive|null",
        "supported_by": ["meth-01"], "contradicted_by": ["dom-02"],
        "cannot_claim": "<what this result still does NOT license anyone to say>"}}
    ],
    "required_next_actions": [
      {{"action": "<the specific thing that must happen>",
        "owner_stage": "DESIGN|EXECUTE|ANALYZE|VERIFY|REPORT",
        "finding_refs": ["base-01"]}}
    ]
  }}
}}
After writing, verify valid JSON."""


# --------------------------------------------------------------------------- seats
def _bare_seats() -> List[_panel_recipe.Seat]:
    """Seat identities only — enough for `load_seat_bundles`, no prompt formatting."""
    return [_panel_recipe.Seat(label=label, prompt="", bundle_key=key, tier=tier, depends_on=deps)
            for label, key, tier, deps in _SEAT_SPECS]


def _seats(run_dir, request: str, vault: str) -> List[_panel_recipe.Seat]:
    outs = {label: _panel_recipe.bundle_path(run_dir, "VERIFY", label)
            for label, _key, _tier, _deps in _SEAT_SPECS}
    shared = {
        "request": request,
        "north_star": _shared.north_star_block(run_dir),
        "run_dir": run_dir,
        "vault": vault,
        "config_bundle": outs[CONFIGURATOR],
        "methodology_bundle": outs[METHODOLOGY],
        "domain_bundle": outs[DOMAIN],
        "adversarial_bundle": outs[ADVERSARIAL],
        "critic_bundle": outs[CRITIC],
        "baseline_bundle": outs[BASELINE],
        "historical_bundle": outs[HISTORIAN],
    }
    contract = _REVIEWER_CONTRACT.format(config_bundle=outs[CONFIGURATOR])
    templates = {CONFIGURATOR: CONFIGURATOR_PROMPT, METHODOLOGY: METHODOLOGY_PROMPT,
                 DOMAIN: DOMAIN_PROMPT, ADVERSARIAL: ADVERSARIAL_PROMPT, CRITIC: CRITIC_PROMPT,
                 BASELINE: BASELINE_PROMPT, HISTORIAN: HISTORIAN_PROMPT,
                 SYNTHESIZER: SYNTHESIZER_PROMPT}
    return [
        _panel_recipe.Seat(
            label=label, bundle_key=key, tier=tier, depends_on=deps,
            prompt=templates[label].format(out=outs[label], reviewer_contract=contract, **shared))
        for label, key, tier, deps in _SEAT_SPECS
    ]


def llm_step(run_dir, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The eight-seat VERIFY panel. REPORT is deterministic and dispatches nobody.

    The scheduler re-enters here once per wave, so the frozen review scope is validated the moment
    it exists — before any reviewer is authorised to spend a hop on a config that cannot support an
    independent panel. `run_dets` re-checks the same thing as the authoritative gate.
    """
    if stage != "VERIFY":
        return None
    scope = _read_seat_bundle(run_dir, CONFIGURATOR)
    if scope is not None:
        violations = _scope_violations(scope)
        if violations:
            raise ValueError(
                f"{MODE} cannot open the reviewer wave: the frozen review scope is not independent "
                f"or not reviewable — {violations}. Re-dispatch {CONFIGURATOR} before any reviewer "
                f"spends a hop.")
    return _panel_recipe.panel(
        run_dir, stage, MODE, _seats(run_dir, request, vault), model_policy=model_policy,
        panel_note=(
            "Wave 1 freezes WHO reviews WHAT. Wave 2 is six mutually blind reviewers — methodology, "
            "domain, adversarial, an independent critic, a baseline-completeness scout and a "
            "sub-domain historian — each writing its own bundle and forbidden to read the others. "
            "Wave 3 is the only seat allowed to read all six; it reconciles and must surface every "
            "disagreement rather than pick a winner."))


# --------------------------------------------------------------------------- deterministic checks
def _read_seat_bundle(run_dir, seat: str) -> Optional[dict]:
    """One seat's own bundle value, or None when it has not been written yet."""
    path = Path(_panel_recipe.bundle_path(run_dir, "VERIFY", seat))
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"{MODE} cannot read {seat}'s bundle at {path}: {exc}") from exc
    return _shared.extract_worker_bundle_value(
        raw, _KEY_BY_SEAT[seat], stage="VERIFY", mode=MODE, agent=seat)


def _require_schema(artifact_type: str, payload: dict, seat: str) -> None:
    """A worker payload that misses its contract is a LOCAL, repairable defect — name the seat."""
    errors = validate_payload(artifact_type, payload)
    if errors:
        raise TargetedGateBlock(
            f"{MODE} VERIFY: {seat}'s {artifact_type} does not meet its contract: {errors}",
            [{"defect_id": f"verify-result-{artifact_type.replace('_', '-')}",
              "category": "schema-semantic-gap",
              "location": f"VERIFY/{seat}",
              "summary": "; ".join(str(e) for e in errors)[:4000],
              "target_agents": [seat],
              "refresh_agents": [SYNTHESIZER] if seat != SYNTHESIZER else []}])


def _scope_violations(scope) -> List[str]:
    """Is the frozen review scope reviewable AND independent? Reused by llm_step and run_dets."""
    if not isinstance(scope, dict):
        return [f"{CONFIGURATOR} did not emit a review_scope object"]
    violations: List[str] = []
    pinned = str(scope.get("result_under_review") or "").strip()
    if not pinned:
        violations.append(
            "result_under_review is empty — a panel cannot independently review an unnamed result")
    config = scope.get("review_config")
    if not isinstance(config, dict):
        return violations + ["review_scope carries no review_config object"]
    if any(not isinstance(row, dict) for row in (config.get("lenses") or [])):
        return violations + ["review_config.lenses must be a list of lens objects"]
    violations.extend(check_review_independence(config))
    inputs = [str(ref).strip() for ref in (config.get("inputs_to_review") or []) if str(ref).strip()]
    if not inputs:
        violations.append(
            "inputs_to_review is empty — the reviewers would have no authorised material to open")
    leaked = sorted({
        ref for ref in inputs
        for marker in list(_ARTIFACT_FILE_BY_SEAT.values())
        + [f"VERIFY.{seat}.bundle.json" for seat in _REVIEWING_SEATS]
        if marker in ref})
    if leaked:
        violations.append(
            f"inputs_to_review hands the panel another reviewer's own output {leaked} — that "
            f"destroys the independence the config exists to create")
    refs = [str(ref).strip() for ref in (scope.get("result_refs") or []) if str(ref).strip()]
    if not refs:
        violations.append("result_refs is empty — the pinned result points at no real file")
    orphans = sorted(set(refs) - set(inputs))
    if orphans:
        violations.append(
            f"result_refs {orphans} are not in inputs_to_review — the panel is not allowed to open "
            f"the very result it is reviewing")
    configured = {str(row.get("lens") or "").strip().lower(): row
                  for row in (config.get("lenses") or [])}
    for lens, seat in sorted(_MANDATORY_LENS_SEAT.items()):
        row = configured.get(lens)
        if row is None:
            violations.append(
                f"lens {lens!r} has no configured anchor, but {seat} reviews in every "
                f"{MODE} panel — an unanchored reviewer is not an independent reviewer")
            continue
        named = str(row.get("reviewer_agent") or "").strip()
        if named != seat:
            violations.append(
                f"lens {lens!r} is assigned to {named!r} but this mode seats {seat} — the anchor "
                f"would be frozen for a seat that never runs")
    return violations


def _finding_rows(review, seat: str) -> List[dict]:
    """Flatten one panel_review into checkable rows, with the id `check_synthesis_coverage` uses."""
    rows: List[dict] = []
    for index, finding in enumerate((review or {}).get("findings") or [], start=1):
        declared = str(finding.get("finding_id") or "").strip()
        anchor = str(finding.get("anchor") or "").strip()
        rows.append({
            "seat": seat, "lens": str((review or {}).get("lens") or ""),
            "id": declared or anchor or f"{seat}-finding-{index}", "declared_id": declared,
            "anchor": anchor, "evidence": str(finding.get("evidence") or ""),
            "severity": str(finding.get("severity") or "")})
    return rows


def _independence_violations(by_seat: Dict[str, object], rows_by_seat: Dict[str, List[dict]]) -> List[str]:
    """Did any of the six read another's conclusions? Three precise, prose-safe signals."""
    violations: List[str] = []
    blobs = {seat: "\n".join(_panel_recipe.collect_texts(by_seat[seat])) for seat in _REVIEWING_SEATS}
    owned_ids = {seat: {row["declared_id"] for row in rows_by_seat.get(seat, [])
                        if len(row["declared_id"]) >= _CITED_ID_MIN_CHARS}
                 for seat in _REVIEWING_SEATS}

    for seat in _REVIEWING_SEATS:
        blob = blobs[seat]
        for other in _REVIEWING_SEATS:
            if other == seat:
                continue
            for marker in (f"VERIFY.{other}.bundle.json", _ARTIFACT_FILE_BY_SEAT[other]):
                if marker in blob:
                    violations.append(
                        f"{seat} cites {other}'s output file {marker!r} — an independent seat "
                        f"cannot have read a sibling reviewer's bundle")
            cited = sorted(fid for fid in owned_ids[other]
                           if fid not in owned_ids[seat] and fid in blob)
            if cited:
                violations.append(
                    f"{seat} cites {other}'s finding id(s) {cited} — those ids exist only in "
                    f"{other}'s bundle, so {seat} read it")

    seen: Dict[str, str] = {}
    for seat in _REVIEWING_SEATS:
        for text in _panel_recipe.collect_texts(by_seat[seat]):
            normalized = " ".join(str(text).split())
            if len(normalized) < _COPY_MIN_CHARS:
                continue
            owner = seen.setdefault(normalized, seat)
            if owner != seat:
                violations.append(
                    f"{seat} repeats {owner}'s text verbatim ({normalized[:60]!r}...) — "
                    f"byte-identical prose across two seats is not independent review")
    return violations


def _lens_violations(by_seat: Dict[str, object]) -> List[str]:
    """Did each panel seat answer the lens this mode assigned it?"""
    violations: List[str] = []
    for seat, lens in sorted(_PANEL_LENS_BY_SEAT.items()):
        got = str((by_seat[seat] or {}).get("lens") or "")
        if got != lens:
            violations.append(
                f"{seat} produced lens {got!r} but this panel assigns it {lens!r} — a seat "
                f"answering the wrong lens leaves its own territory unreviewed")
    return violations


def _derive_overall_verdict(review, seat: str) -> str:
    """PASS/BLOCK is DERIVED from the findings; a declared value that disagrees is refused."""
    rows = _finding_rows(review, seat)
    derived = "BLOCK" if any(row["severity"] == "BLOCK" for row in rows) else "PASS"
    declared = str((review or {}).get("overall_verdict") or "").strip()
    if declared and declared != derived:
        raise TargetedGateBlock(
            f"{MODE} VERIFY: {seat} declared overall_verdict {declared!r} while its own findings "
            f"derive {derived!r} — this verdict is computed, never asserted",
            [{"defect_id": "verify-result-declared-verdict", "category": "derived-field-asserted",
              "location": f"VERIFY/{seat}", "summary": f"declared={declared} derived={derived}",
              "target_agents": [seat], "refresh_agents": [SYNTHESIZER]}])
    return derived


def _cited_refs(text_refs) -> List[str]:
    """Real citation-shaped refs found in reviewer prose (never a prose fragment)."""
    found: Dict[str, None] = {}
    for text in text_refs:
        for match in _REF_RE.findall(str(text)):
            found.setdefault(str(match).rstrip(".,;)]}"))
    return list(found)


def _coverage_violations(draft: dict, known_refs: set, block_ids: List[str],
                         critic_flags: List[str], cross_refs: List[str]) -> List[str]:
    """Every synthesis conclusion must trace upstream, and nothing upstream may vanish."""
    violations: List[str] = []
    acknowledged = {str(row.get("block_source") or "").strip()
                    for row in (draft.get("addressed_blocks") or [])}
    acknowledged |= {str(item).strip() for item in (draft.get("unaddressed_blocks") or [])}
    acknowledged |= {str(item).strip() for item in (draft.get("open_critic_flags") or [])}
    for block_id in block_ids:
        if not any(block_id == entry or block_id in entry for entry in acknowledged if entry):
            violations.append(
                f"reviewer BLOCK {block_id!r} appears nowhere in the synthesis — a BLOCK may be "
                f"rebutted or left standing, never dropped")
    for flag in critic_flags:
        if not any(flag == entry or flag in entry for entry in acknowledged if entry):
            violations.append(
                f"critic block_flag {flag[:60]!r} appears nowhere in the synthesis — it must be "
                f"rebutted or left open, never dropped")

    def _check(refs, where: str, required: bool) -> None:
        clean = [str(ref).strip() for ref in (refs or []) if str(ref).strip()]
        if required and not clean:
            violations.append(
                f"{where} cites no upstream finding — a synthesis conclusion with no reviewer "
                f"behind it is material the panel never produced")
        unknown = sorted(set(clean) - known_refs)
        if unknown:
            violations.append(
                f"{where} cites {unknown}, which no reviewer, critic flag or adversarial check "
                f"produced — a fabricated reference")

    if not (draft.get("claims") or []):
        violations.append(
            "the synthesis calibrates no claim at all — a verification that says nothing about what "
            "the result does and does not support is not a verification")
    for index, claim in enumerate((draft.get("claims") or []), start=1):
        _check(claim.get("supported_by"), f"claims[{index}].supported_by", True)
        _check(claim.get("contradicted_by"), f"claims[{index}].contradicted_by", False)
        for field in ("delta", "variance"):
            value = claim.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                violations.append(
                    f"claims[{index}].{field} is {value!r}, not a number or null — the calibrator "
                    f"compares delta against variance and cannot read a number that is not one")
        if not str(claim.get("cannot_claim") or "").strip():
            violations.append(
                f"claims[{index}] has no `cannot_claim` — every verified claim must state what it "
                f"still does NOT license, or the result quietly grows past its evidence")
    for index, action in enumerate((draft.get("required_next_actions") or []), start=1):
        _check(action.get("finding_refs"), f"required_next_actions[{index}].finding_refs", True)
    for index, row in enumerate((draft.get("disagreements") or []), start=1):
        ref = str(row.get("critic_cross_finding_ref") or "").strip()
        if ref and ref not in set(cross_refs):
            violations.append(
                f"disagreements[{index}] names {ref!r}, which is not one of the critic's "
                f"cross_findings {cross_refs}")
        for position_index, position in enumerate((row.get("positions") or []), start=1):
            _check(position.get("finding_refs"),
                   f"disagreements[{index}].positions[{position_index}].finding_refs", True)
    return violations


def _disagreement_violations(draft: dict, cross_refs: List[str],
                             verdicts: Dict[str, str]) -> List[str]:
    """A split panel must reach the director as a split panel."""
    violations: List[str] = []
    rows = list(draft.get("disagreements") or [])
    named = {str(row.get("critic_cross_finding_ref") or "").strip() for row in rows}
    for ref in cross_refs:
        if ref not in named:
            violations.append(
                f"the critic's {ref} is not carried into any disagreement — a recorded cross-panel "
                f"tension may not be dropped in synthesis")
    if len(set(verdicts.values())) > 1 and not rows:
        violations.append(
            f"the panel is split ({sorted(set(verdicts.items()))}) but the synthesis reports no "
            f"disagreement at all — a split panel is reported, never averaged away")
    for index, row in enumerate(rows, start=1):
        positions = [p for p in (row.get("positions") or []) if isinstance(p, dict)]
        lenses = {str(p.get("lens") or "").strip() for p in positions if str(p.get("lens") or "").strip()}
        stated = [p for p in positions if str(p.get("position") or "").strip()]
        if len(lenses) < 2 or len(stated) < 2:
            violations.append(
                f"disagreements[{index}] records fewer than two stated positions on different "
                f"lenses — that is picking a winner, not reporting a disagreement")
        resolution = str(row.get("resolution") or "").strip()
        if resolution not in {"unresolved", "resolved_by_evidence"}:
            violations.append(
                f"disagreements[{index}].resolution must be 'unresolved' or "
                f"'resolved_by_evidence', got {resolution!r}")
        elif resolution == "resolved_by_evidence" and \
                len(str(row.get("resolution_note") or "").strip()) < _MIN_RESOLUTION_NOTE:
            violations.append(
                f"disagreements[{index}] claims the evidence settles it but writes no evidence — "
                f"an unwritten resolution is a preference")
    return violations


# --------------------------------------------------------------------------- director Markdown
def _findings_block(rows: List[dict], verdict: str, empty: str) -> str:
    if not rows:
        return f"{empty} (verdict {verdict})"
    lines = [f"verdict **{verdict}** · {len(rows)} finding(s)", ""]
    for row in rows:
        lines.append(f"- **{row['severity']}** `{row['id']}` — {row['anchor']}")
        lines.append(f"  - evidence: {row['evidence']}")
    return "\n".join(lines)


def _sections(scope: dict, reviews: Dict[str, object], verdicts: Dict[str, str],
              rows_by_seat: Dict[str, List[dict]], adversarial: dict, critic: dict,
              draft: dict, synthesis: dict, calibrated: dict, refs: List[str],
              gate_frag: dict) -> dict:
    config = scope["review_config"]
    result_refs = [str(r) for r in (scope.get("result_refs") or [])]

    lens_table = ["| lens | reviewer seat | frozen territory |", "|---|---|---|"]
    for row in config.get("lenses") or []:
        lens_table.append(
            f"| {row.get('lens')} | {row.get('reviewer_agent')} | {row.get('anchor')} |")
    unconfigured = sorted(set(_REVIEWING_SEATS) - {str(r.get("reviewer_agent"))
                                                   for r in (config.get("lenses") or [])})

    panel_parts = []
    for seat in (METHODOLOGY, DOMAIN):
        panel_parts.append(f"### {seat}\n\n" + _findings_block(
            rows_by_seat[seat], verdicts[seat], "No finding filed — the seat reports it found none."))
    panel_parts.append("### adversarial-reviewer (five refutation checks)\n\n" + "\n".join(
        [f"verdict **{adversarial['verdict']}**", ""]
        + [f"- `{name}`: {'pass' if adversarial['checks'][name]['pass'] else 'NOT DEFENSIBLE'}"
           f" — {adversarial['checks'][name].get('evidence') or 'no evidence cited'}"
           for name in ADVERSARIAL_CHECK_NAMES]
        + ([""] + [f"- blocking: {reason}" for reason in adversarial["blocking_reasons"]]
           if adversarial["blocking_reasons"] else [])))
    cross = critic.get("cross_findings") or []
    flags = critic.get("block_flags") or []
    critic_lines = (
        [f"- `cross-{i}` — {row.get('description')} "
         f"(lenses: {', '.join(row.get('involved_lenses') or [])})"
         for i, row in enumerate(cross, start=1)]
        + [f"- **flag** {row.get('flag_text')} (source: {row.get('source')})" for row in flags]
        + [f"- gap not covered by any seat: {gap}" for gap in (critic.get("gaps") or [])])
    panel_parts.append("### scientific-critic (independent cross-examination)\n\n" + "\n".join(
        [f"{len(cross)} cross-finding(s), {len(flags)} block flag(s), "
         f"{len(critic.get('gaps') or [])} uncovered gap(s)", ""]
        + (critic_lines or ["The critic found no internal tension it could substantiate."])))

    disagreements = draft.get("disagreements") or []
    if disagreements:
        rows = ["### Disagreements — both readings, no winner picked", ""]
        for index, row in enumerate(disagreements, start=1):
            rows.append(f"**{index}. {row.get('topic')}** "
                        f"({row.get('resolution')}; {row.get('critic_cross_finding_ref') or 'no cross-ref'})")
            for position in row.get("positions") or []:
                rows.append(f"  - `{position.get('lens')}`: {position.get('position')} "
                            f"[{', '.join(position.get('finding_refs') or [])}]")
            if str(row.get("resolution_note") or "").strip():
                rows.append(f"  - note: {row.get('resolution_note')}")
        disagreement_block = "\n".join(rows)
    else:
        disagreement_block = ("### Disagreements\n\nNone — all "
                              f"{len(set(verdicts.values()))} distinct seat verdict(s) agreed and "
                              "the critic recorded no cross-panel tension.")
    panel_parts.append(disagreement_block)

    scholar_parts = []
    for seat, title in ((BASELINE, "baseline-scout — is the comparison set complete?"),
                        (HISTORIAN, "sub-domain-historian — does the work know its lineage?")):
        scholar_parts.append(f"### {title}\n\n" + _findings_block(
            rows_by_seat[seat], verdicts[seat],
            "No finding filed — the seat reports it found none.")
            + f"\n\nseat notes: {(reviews[seat] or {}).get('reviewer_notes') or '(none)'}")
    scholar_parts.append(
        f"Refs these two seats cited: {len(refs)}. Live existence check: "
        f"**{gate_frag.get('existence_gate')}** "
        f"({gate_frag.get('existence_warnings')} warning(s)); referential integrity: "
        f"**{gate_frag.get('referential_integrity')}** "
        f"({gate_frag.get('referential_warnings')} warning(s)). "
        "A confirmed-nonexistent ref would have blocked this run; an offline lookup degrades to a "
        "warning and is NOT evidence the ref is real.")

    claim_rows = ["| claim | metric | delta vs variance | recomputed strength | STILL CANNOT CLAIM |",
                  "|---|---|---|---|---|"]
    for source, row in zip(draft.get("claims") or [], calibrated["calibrated"]):
        delta = "n/a" if row["delta"] is None else f"{row['delta']:.4g}"
        variance = "n/a" if row["variance"] is None else f"{row['variance']:.4g}"
        mark = " (downgraded)" if row["downgraded"] else ""
        claim_rows.append(
            f"| {row['original_claim']} | {row['metric'] or 'n/a'} | {delta} vs {variance} | "
            f"**{row['strength']}**{mark} | {source.get('cannot_claim')} |")
    calibration = "\n".join(claim_rows) + (
        f"\n\nStrength is recomputed from delta against variance by the deterministic calibrator, "
        f"never taken from the synthesizer's wording; "
        f"{sum(1 for r in calibrated['calibrated'] if r['downgraded'])} of "
        f"{len(calibrated['calibrated'])} claim(s) were downgraded. "
        f"Panel verdict: **{synthesis['verdict']}**"
        + (f" — {len(synthesis['violations'])} coverage violation(s), "
           f"{len(synthesis['unaddressed_blocks'])} block(s) left standing, "
           f"{len(synthesis['open_critic_flags'])} critic flag(s) still open."
           if synthesis["verdict"] == "BLOCK" else
           " — every reviewer BLOCK and critic flag was rebutted with run evidence."))

    actions = draft.get("required_next_actions") or []
    action_block = "\n".join(
        [f"- **{row.get('owner_stage')}** — {row.get('action')} "
         f"[traces to: {', '.join(row.get('finding_refs') or [])}]" for row in actions]
    ) if actions else (
        "No action required by the panel: no seat filed a BLOCK or WARN that needs work before "
        "this result may be used as stated.")

    return {
        "Result under review": (
            f"{scope.get('result_under_review')}\n\n"
            + "\n".join(f"- reviewed by reference: `{ref}`" for ref in result_refs)
            + "\n\nThis run REVIEWED that result; it did not produce it, re-run it, or repair it. "
              "Nothing here freezes or promotes anything — this brief is advisory input to the "
              "director's sign-off, and the vault is still reachable only through "
              "/promote-to-vault."),
        "Review configuration": (
            "\n".join(lens_table)
            + f"\n\n**Synthesis mandate.** {config.get('synthesis_mandate')}\n\n"
            + f"**Independence.** {len(_REVIEWING_SEATS)} seats reviewed in parallel, each writing "
              "its own bundle; the deterministic checks found no duplicate/empty/identical lens "
              "anchor, no seat citing another's output file or finding ids, and no verbatim prose "
              "shared between seats.\n\n"
            + (f"**Honest gap.** {unconfigured} carry no configured lens row: the review_config "
               "contract only enumerates methodology/domain/adversarial, so those seats are "
               "anchored by their own remit plus the synthesis mandate above."
               if unconfigured else "Every seat carries a configured lens row.")),
        "Independent panel findings": "\n\n".join(panel_parts),
        "Baseline and historical context": "\n\n".join(scholar_parts),
        "Claim calibration": calibration,
        "Required next actions": (
            action_block
            + f"\n\nDirector gate: this mode's `gate_level` is director_signoff — the panel reports, "
              f"the director decides. North-star drift gate: **{gate_frag.get('drift_gate')}**."),
    }


# --------------------------------------------------------------------------- stages
def _verify_dets(run_dir, ts) -> tuple:
    seats = _bare_seats()
    bundles = _panel_recipe.load_seat_bundles(run_dir, "VERIFY", MODE, seats)
    by_seat = {label: bundles[key] for label, key, _tier, _deps in _SEAT_SPECS}
    not_objects = sorted(label for label, value in by_seat.items() if not isinstance(value, dict))
    if not_objects:
        raise GateBlock(
            f"{MODE} VERIFY: seat(s) {not_objects} emitted a non-object payload under their declared "
            f"bundle key — every seat's bundle must be the JSON object its dispatch order specifies")

    scope = by_seat[CONFIGURATOR]
    scope_violations = _scope_violations(scope)
    if scope_violations:
        raise GateBlock(
            f"{MODE} VERIFY review-scope BLOCK: {scope_violations}. The panel's independence is "
            f"decided before anyone reviews; a scope this weak cannot produce an independent "
            f"judgment, so nothing is delivered from it.")
    config = scope["review_config"]
    _require_schema("review_config", config, CONFIGURATOR)

    rows_by_seat = {seat: _finding_rows(by_seat[seat], seat) for seat in _PANEL_LENS_BY_SEAT}
    lens_violations = _lens_violations(by_seat)
    if lens_violations:
        raise GateBlock(f"{MODE} VERIFY lens-coverage BLOCK: {lens_violations}")
    independence = _independence_violations(by_seat, rows_by_seat)
    if independence:
        raise GateBlock(
            f"{MODE} VERIFY reviewer-independence BLOCK: {independence}. A reviewer that has seen "
            f"another seat's conclusions cannot un-see them, so this is terminal: start a fresh "
            f"panel rather than re-prompting the contaminated seat.")

    paths: List[str] = [write_artifact(run_dir, "VERIFY", "review-config.artifact.json",
                                       "review_config", CONFIGURATOR, config, ts)]
    verdicts: Dict[str, str] = {}
    for seat, lens in sorted(_PANEL_LENS_BY_SEAT.items()):
        review = dict(by_seat[seat] or {})
        verdicts[seat] = _derive_overall_verdict(review, seat)
        review["overall_verdict"] = verdicts[seat]
        _require_schema("panel_review", review, seat)
        by_seat[seat] = review
        paths.append(write_artifact(
            run_dir, "VERIFY", _ARTIFACT_FILE_BY_SEAT[seat], "panel_review", seat, review, ts,
            "blocked" if verdicts[seat] == "BLOCK" else "approved"))

    adversarial = build_review_report(dict(by_seat[ADVERSARIAL] or {}))
    verdicts[ADVERSARIAL] = "BLOCK" if adversarial["verdict"] == "BLOCK" else "PASS"
    _require_schema("review_report", adversarial, ADVERSARIAL)
    paths.append(write_artifact(
        run_dir, "VERIFY", _ARTIFACT_FILE_BY_SEAT[ADVERSARIAL], "review_report", ADVERSARIAL,
        adversarial, ts, "blocked" if adversarial["verdict"] == "BLOCK" else "approved"))
    critic = dict(by_seat[CRITIC] or {})
    _require_schema("critic_memo", critic, CRITIC)
    paths.append(write_artifact(run_dir, "VERIFY", _ARTIFACT_FILE_BY_SEAT[CRITIC], "critic_memo",
                                CRITIC, critic, ts))

    draft = dict(by_seat[SYNTHESIZER] or {})
    panel_reviews = [by_seat[seat] for seat in _PANEL_LENS_BY_SEAT]
    block_ids = [row["id"] for rows in rows_by_seat.values() for row in rows
                 if row["severity"] == "BLOCK"]
    critic_flags = [str(flag.get("flag_text") or "").strip()
                    for flag in (critic.get("block_flags") or []) if flag.get("flag_text")]
    cross_refs = [f"cross-{i}" for i in range(1, len(critic.get("cross_findings") or []) + 1)]
    known_refs = ({row["id"] for rows in rows_by_seat.values() for row in rows}
                  | {row["declared_id"] for rows in rows_by_seat.values() for row in rows
                     if row["declared_id"]}
                  | set(critic_flags) | set(cross_refs) | set(ADVERSARIAL_CHECK_NAMES))

    integrity = (_coverage_violations(draft, known_refs, block_ids, critic_flags, cross_refs)
                 + _disagreement_violations(draft, cross_refs, verdicts))
    if integrity:
        raise TargetedGateBlock(
            f"{MODE} VERIFY synthesis-integrity BLOCK: {integrity}. Leaving a reviewer BLOCK "
            f"standing is a legitimate answer; dropping one, inventing a reference, omitting a "
            f"claim's limit, or resolving a disagreement by preference is not.",
            [{"defect_id": "verify-result-synthesis-integrity",
              "category": "unsupported-synthesis",
              "location": "VERIFY/review-synthesizer",
              "summary": "; ".join(integrity)[:4000],
              "target_agents": [SYNTHESIZER], "refresh_agents": []}])

    unaddressed = [str(item) for item in (draft.get("unaddressed_blocks") or [])]
    open_flags = [str(item) for item in (draft.get("open_critic_flags") or [])]
    candidate = {"verdict": "APPROVE" if not (unaddressed or open_flags) else "BLOCK",
                 "violations": [],
                 "addressed_blocks": [{"block_source": str(row.get("block_source") or ""),
                                       "rebuttal": str(row.get("rebuttal") or "")}
                                      for row in (draft.get("addressed_blocks") or [])],
                 "unaddressed_blocks": unaddressed, "open_critic_flags": open_flags,
                 "overall_summary": str(draft.get("overall_summary") or "")}
    violations = list(check_synthesis_coverage(panel_reviews, critic, candidate))
    rebutted = {row["block_source"] for row in candidate["addressed_blocks"]
                if len(row["rebuttal"].split()) >= 2}
    violations += [f"adversarial refutation gate BLOCK, not rebutted: {reason}"
                   for reason in adversarial["blocking_reasons"]
                   if not any(reason == entry or reason in entry for entry in rebutted)]
    synthesis = dict(candidate)
    synthesis["violations"] = violations
    if violations:
        synthesis["verdict"] = "BLOCK"
    _require_schema("panel_synthesis", synthesis, SYNTHESIZER)
    paths.append(write_artifact(
        run_dir, "VERIFY", "panel-synthesis.artifact.json", "panel_synthesis", SYNTHESIZER,
        synthesis, ts, "blocked" if synthesis["verdict"] == "BLOCK" else "approved"))

    calibrated = build_calibrated_claims(
        [{"original_claim": str(claim.get("original_claim") or ""),
          "metric": claim.get("metric"), "delta": claim.get("delta"),
          "variance": claim.get("variance"), "original_strength": claim.get("original_strength")}
         for claim in (draft.get("claims") or [])],
        source_ref=str(scope.get("result_under_review") or "") or None)
    for source, row in zip(draft.get("claims") or [], calibrated["calibrated"]):
        row["caveat"] = (f"{row['caveat']} STILL CANNOT CLAIM: "
                         f"{str(source.get('cannot_claim') or '').strip()}")
    _require_schema("calibrated_claims", calibrated, SYNTHESIZER)
    paths.append(write_artifact(run_dir, "VERIFY", "calibrated-claims.artifact.json",
                                "calibrated_claims", SYNTHESIZER, calibrated, ts))

    refs = _cited_refs(_panel_recipe.collect_texts(by_seat[BASELINE])
                      + _panel_recipe.collect_texts(by_seat[HISTORIAN]))
    gate_paths, gate_frag = _panel_recipe.common_gates(
        run_dir, "VERIFY", ts, mode=MODE, bundles=bundles,
        evidence_table={"sources": [{"ref": ref} for ref in refs]},
        downstream_refs=refs, known_ids=known_refs)
    paths.extend(gate_paths)

    markdown = _panel_recipe.render_director_markdown(
        run_dir, MODE,
        _sections(scope, by_seat, verdicts, rows_by_seat, adversarial, critic, draft, synthesis,
                  calibrated, refs, gate_frag),
        ts=ts, lead=f"{SYNTHESIZER} (every verdict on this page is deterministically derived)")

    report = {"panel_verdict": synthesis["verdict"],
              "adversarial_gate": adversarial["verdict"],
              "reviewer_independence": "PASS",
              "seats_reviewed": len(_REVIEWING_SEATS),
              "seat_verdicts": {seat: verdicts[seat] for seat in sorted(verdicts)},
              "n_findings": sum(len(rows) for rows in rows_by_seat.values()),
              "n_reviewer_blocks": len(block_ids),
              "n_critic_block_flags": len(critic_flags),
              "n_cross_findings": len(cross_refs),
              "n_disagreements": len(draft.get("disagreements") or []),
              "n_coverage_violations": len(violations),
              "n_claims": len(calibrated["calibrated"]),
              "n_claims_downgraded": sum(1 for row in calibrated["calibrated"] if row["downgraded"]),
              "scholar_refs_checked": len(refs),
              "director_verification_brief": markdown}
    report.update(gate_frag)
    return paths, report


def _report_dets(run_dir, ts) -> tuple:
    rel = _panel_recipe.target_markdown(MODE)["path"]
    path = Path(run_dir) / "evidence" / "VERIFY" / "panel-synthesis.artifact.json"
    if path.is_file():
        synthesis = json.loads(path.read_text(encoding="utf-8"))["payload"]
        outcome = (f"The panel's derived verdict is {synthesis['verdict']} "
                   f"({len(synthesis['unaddressed_blocks'])} reviewer block(s) left standing, "
                   f"{len(synthesis['open_critic_flags'])} critic flag(s) open, "
                   f"{len(synthesis['violations'])} coverage violation(s)).")
    else:
        outcome = "No panel synthesis was written, so this run produced NO verification judgment."
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary=(
            "verify_result ran an eight-seat independence panel: one configurator froze who reviews "
            "what, six seats reviewed in parallel without reading each other, and one synthesizer "
            "reconciled them under deterministic independence, evidence-coverage, disagreement and "
            f"claim-calibration checks. {outcome} Claim strength was recomputed from delta against "
            "variance, and every claim carries what it still cannot support. This is an advisory "
            "review for the director's sign-off: it freezes nothing and promotes nothing."),
        references=[rel],
        open_questions=[
            "Does the director accept the panel's verdict, or send the result back for repair?",
            "Nothing here is citable knowledge until /promote-to-vault re-derives it.",
        ])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report_dets(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
