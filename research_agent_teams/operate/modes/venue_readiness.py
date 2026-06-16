"""Operate recipe for the `venue_readiness` mode (VERIFY -> REPORT) — audit B1.

The mode-registry's strongest-built chain with zero reachability: this recipe wires it into the
one-button operate layer. "Is this manuscript good enough for venue X?" is answered by a BLIND
review PANEL whose verdict is DERIVED, never self-declared:

  - LLM workers (sub-agents) do the only part a deterministic tool cannot: a venue-selector reads
    the venue's rubric material + the manuscript and instantiates the venue_profile (7-dim weights,
    reject-triggers, accept-condition, personas); then THREE persona reviewers
    (methodology / domain / adversarial) each emit a venue_review — pre-commitment anchor FIRST,
    asymmetric-cost low-when-uncertain, anti-bias suppressors honoured, the adversarial persona
    opening the eval code itself.
  - Deterministic cores do the GATING / DERIVATION (never an LLM): structural consistency
    (persona<->venue_id, the profile's declared personas + a mandatory adversarial seat present),
    a deterministic pairwise lexical INDEPENDENCE check (an echo-chamber panel cannot reach a
    publication verdict), and `venue_score.derive_meets_bar` — the single source of truth for the
    readiness verdict (MEETS-BAR / BORDERLINE / NOT-YET / WRONG-PATH / DEGRADED-REVIEW).

The verdict labels are INFORMATION for the director (the next step is the human `/venue-pick` /
`/venue-decide` gates); only STRUCTURAL failure (a missing worker, a missing/extra persona, a
venue_id mismatch, an invalid schema, north-star drift) is a GateBlock that halts the stage.

Inline operate twin of agents/venue-reviewer-persona.md + agents/area-chair-synthesizer.md — any
change to those specs' worker duties MUST be mirrored here (audit M5).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .. import bounded_repair
from . import _shared
from ..artifacts import GateBlock, write_artifact
from ...tools.idea_dedup import lexical_similarity
from ...tools.venue_score import collect_unresolved_triggers, derive_meets_bar

STAGES = ["VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

INDEPENDENCE_SIM_THRESHOLD = 0.3  # >= this between any two reviews == echo chamber (DEGRADED-REVIEW)
PERSONAS = ("methodology", "domain", "adversarial")


# --------------------------------------------------------------------------- worker prompts (LLM WORK)

_PROFILE_WORKER_PROMPT = """You are the VENUE-SELECTOR of a venue_readiness run. The director has \
chosen a target venue; your job is to instantiate that venue's review rubric into a scorecard for \
THIS manuscript, for the request:

    REQUEST: {request}

{north_star_block}

Read (by reference, never inline):
  1. The venue rubric material under `research_agent_teams/agents/references/venue-rubrics/` — pick \
the file matching the target venue's tier (tier1-conf-ml / tier2-med-imaging / tier3-journal), plus \
`reject-triggers.md`, `anti-bias-suppressors.md`, `rubric-7d.md`.
  2. The manuscript / result artifacts the request points at (read them; do not trust a summary).

HONESTY (hard): instantiate ONLY triggers that genuinely apply to this venue; annotate `our_risk` \
only where you can name this paper's CONCRETE risk against the trigger (else omit it). Never invent \
a venue. The personas list MUST include "adversarial" (the panel always carries an adversary).

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "venue_profile": {{
    "venue_id": "<e.g. NeurIPS-2025 / MICCAI-2025 / TPAMI>",
    "tier": "conf|med|journal",
    "paper_type": "methodological|application-clinical",
    "dimension_weights": {{"D1":{{"weight":1.0,"gating":true}},"D2":{{"weight":1.0}},
      "D3":{{"weight":1.0}},"D4":{{"weight":1.5,"gating":true}},"D5":{{"weight":1.0}},
      "D6":{{"weight":0.5}},"D7":{{"weight":0.0}}}},
    "reject_triggers": [{{"trigger_id":"RT-D4-BASELINE","dimension":"D4",
      "description":"<what fires it>","our_risk":"<this paper's concrete risk, optional>"}}],
    "accept_condition": "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger",
    "anti_bias_suppressors": ["hasn't beaten SOTA alone", "new-combination-of-existing alone"],
    "personas": ["methodology","domain","adversarial"],
    "evidence_ref": ["<rubric path>", "<manuscript path / artifact id>"]
  }}
}}
After writing, verify it is valid JSON. Return one line: venue_id + tier + persona count + #triggers."""

_PERSONA_WORKER_PROMPT = """You are a BLIND reviewer for venue **{venue_hint}**, playing the \
**{persona}** role, reviewing the manuscript for the request:

    REQUEST: {request}

{north_star_block}

母版 = the adversarial-reviewer discipline. You have NO authority to decide acceptance: you emit a \
`venue_review` evidentiary record ONLY — it carries NO verdict / meets_bar / decision / accept \
field (the schema forbids them). The area chair derives the readiness verdict deterministically.

PROTOCOL (do these IN ORDER):
  1. Write your PRE-COMMITMENT ANCHOR first (the standard you will hold this paper to for {persona}); \
read `{run_dir}/evidence/VERIFY/venue-profile.artifact.json` for the venue's rubric, reject-triggers, \
and anti-bias suppressors. You MAY NOT loosen the anchor after reading the manuscript.
  2. Score the applicable dimensions (D1..D7, 1-4: 4=excellent 3=good 2=fair 1=poor). EVERY score \
needs >=1 concrete `evidence_ref` (file:line / section / metric / table) — a score with no evidence \
is score 1. Omit dimensions not applicable to this venue/paper_type.
  3. Run the venue's reject-triggers. For each that fires: record trigger_id + dimension + locus \
(exact manuscript location) + required_fix. A fired trigger means you CANNOT recommend accept.
  4. ASYMMETRIC COST — default LOW when uncertain (a weak paper scored high wastes a whole \
submission cycle; a strong paper scored low is recoverable by rebuttal).
  5. ANTI-BIAS SUPPRESSORS — you MUST NOT fire a reject-trigger on a suppressed ground ALONE \
(e.g. "didn't beat SOTA", "small fixable issues", "just a new combination of existing techniques", \
"didn't cite a specific preprint", "rebuttal didn't add a requested experiment").
{adversarial_clause}
HONESTY (hard): never fabricate an evidence_ref, a metric, or a manuscript locus; never read another \
reviewer's output before emitting yours (independence). venue_id MUST equal the profile's venue_id.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}` (filename ends in .bundle.json, NOT .artifact.json):
{{
  "venue_review": {{
    "persona": "{persona}",
    "venue_id": "<= the profile's venue_id>",
    "dimension_scores": {{"D1":{{"score":3,"evidence_ref":["<file:line>"],"notes":"<why>"}},
      "D4":{{"score":3,"evidence_ref":["<metric path>"],"notes":"<why>"}}}},
    "reject_triggers_fired": [{{"trigger_id":"RT-D4-BASELINE","dimension":"D4",
      "locus":"<section/table>","required_fix":"<concrete fix>"}}],
    "overall": "<venue-scale recommendation, e.g. 'Weak Accept' / 'Reject'>",
    "confidence": 4,
    "evidence_ref": ["<>=1 pointer you actually read: file:line / section / metric path>"],
    "minimal_fix": "<smallest change set resolving your fired triggers, optional>"
  }}
}}
After writing, verify valid JSON. Return one line: persona + #dims scored + #triggers fired + overall."""

_ADVERSARIAL_CLAUSE = (
    "  6. ADVERSARIAL OBLIGATION (you are the adversary): OPEN THE EVAL CODE YOURSELF "
    "(read-only) — do not trust the paper's description. Personally check for: test-label "
    "leakage into training, an unfair / under-tuned baseline, test-set tuning, wrong metric "
    "aggregation. Apply D3 (novelty) and D4 (evaluation rigor) with the venue's anti-leaderboard "
    "suppressor in force.\n"
)
_NONADVERSARIAL_CLAUSE = (
    "  6. Stay within your {persona} lens; the adversarial seat (a separate reviewer) owns the "
    "eval-code re-derivation — you focus on your dimension competencies.\n"
)


# --------------------------------------------------------------------------- stage plan (what the skill spawns)

def _persona_filename_stub(persona: str) -> str:
    return f"VERIFY.review.{persona}"


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """The LLM workers to dispatch for a stage (None = the stage is purely deterministic).

    VERIFY is a MULTI-WORKER stage: the venue-selector (profile) worker runs FIRST and writes the
    venue_profile bundle; the three persona reviewers run AFTER it (they read its bundle), ideally
    in parallel. Reviewing is a judgment task with asymmetric cost — BOTH model policies pick opus
    (a misjudged venue-readiness verdict wastes a whole submission cycle), so the tier is opus
    regardless of `model_policy`."""
    if stage != "VERIFY":
        return None  # REPORT is deterministic
    nsb = _shared.north_star_block(run_dir)
    profile_out = f"{run_dir}/inbox/VERIFY.profile.bundle.json"
    # judgment task: opus in BOTH policies (the ternary documents the deliberate non-branch).
    model = "opus" if model_policy == "max_quality" else "opus"
    w_profile = {
        "label": "venue-selector", "model": model, "output": profile_out,
        "prompt": _PROFILE_WORKER_PROMPT.format(request=request, north_star_block=nsb, out=profile_out),
    }
    workers = [w_profile]
    for persona in PERSONAS:
        out = f"{run_dir}/inbox/{_persona_filename_stub(persona)}.bundle.json"
        clause = (_ADVERSARIAL_CLAUSE if persona == "adversarial"
                  else _NONADVERSARIAL_CLAUSE.format(persona=persona))
        workers.append({
            "label": f"venue-reviewer-{persona}", "model": model, "output": out,
            "prompt": _PERSONA_WORKER_PROMPT.format(
                request=request, persona=persona, venue_hint="the chosen venue", run_dir=run_dir,
                north_star_block=nsb, adversarial_clause=clause, out=out),
        })
    return {
        "label": "venue-panel", "workers": workers,
        "note": "spawn the profile worker FIRST; the three persona workers run AFTER it "
                "(they read its bundle), ideally in parallel",
    }


# --------------------------------------------------------------------------- bundle loaders

def _load_profile_bundle(run_dir) -> dict:
    p = Path(run_dir) / "inbox" / "VERIFY.profile.bundle.json"
    if not p.exists():
        raise GateBlock(
            "venue VERIFY: the venue-selector (profile) worker bundle is missing at "
            f"{p} — dispatch the profile worker FIRST (it must run before the persona reviewers)")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_review_bundle(run_dir, persona) -> dict:
    p = Path(run_dir) / "inbox" / f"{_persona_filename_stub(persona)}.bundle.json"
    if not p.exists():
        raise GateBlock(
            f"venue VERIFY: the {persona!r} persona reviewer bundle is missing at {p} — the panel "
            "needs all of methodology/domain/adversarial; re-dispatch the missing reviewer")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- deterministic gates + derivation

def _review_text(review: dict) -> str:
    """The text basis for the independence check: overall + every dimension note + each fired
    trigger's locus/required_fix (the substantive prose a reviewer authored)."""
    bits: List[str] = [str(review.get("overall") or "")]
    for ds in (review.get("dimension_scores") or {}).values():
        if isinstance(ds, dict) and ds.get("notes"):
            bits.append(str(ds["notes"]))
    for t in (review.get("reject_triggers_fired") or []):
        bits.append(str(t.get("locus") or ""))
        bits.append(str(t.get("required_fix") or ""))
    return " ".join(b for b in bits if b)


def _independence(reviews: List[dict], personas: List[str]) -> dict:
    """Deterministic pairwise lexical independence over the review texts.

    verdict 'degraded' iff any pair's similarity >= the echo-chamber threshold — derive_meets_bar
    honours BOTH the explicit verdict label AND the per-pair / max_sim shape (defence in depth)."""
    pairs = []
    max_sim = 0.0
    for i in range(len(reviews)):
        for j in range(i + 1, len(reviews)):
            sim = round(lexical_similarity(_review_text(reviews[i]), _review_text(reviews[j])), 4)
            pairs.append({"a": personas[i], "b": personas[j], "sim": sim})
            max_sim = max(max_sim, sim)
    return {"pairs": pairs, "max_sim": round(max_sim, 4),
            "verdict": "degraded" if max_sim >= INDEPENDENCE_SIM_THRESHOLD else "ok"}


def _verify_dets(run_dir, ts) -> tuple:
    paths: List[str] = []

    # 1. profile bundle -> venue_profile artifact (write_artifact self-validates the schema)
    pb = _load_profile_bundle(run_dir)
    _shared.require_bundle_keys(pb, ["venue_profile"], stage="VERIFY", mode="venue_readiness")
    profile = pb["venue_profile"]
    profile_path = write_artifact(run_dir, "VERIFY", "venue-profile.artifact.json",
                                  "venue_profile", "venue-selector", profile, ts)
    paths.append(profile_path)
    venue_id = str(profile.get("venue_id") or "")

    # 2. the three persona reviews -> venue_review artifacts + structural consistency gates
    reviews: List[dict] = []
    review_paths: List[str] = []
    for persona in PERSONAS:
        rb = _load_review_bundle(run_dir, persona)
        _shared.require_bundle_keys(rb, ["venue_review"], stage="VERIFY", mode="venue_readiness")
        review = rb["venue_review"]
        if str(review.get("persona") or "") != persona:
            raise GateBlock(
                f"venue VERIFY: the {persona!r} reviewer bundle declares persona "
                f"{review.get('persona')!r} — the persona field must match the file's reviewer slot")
        if str(review.get("venue_id") or "") != venue_id:
            raise GateBlock(
                f"venue VERIFY: {persona!r} review venue_id {review.get('venue_id')!r} != profile "
                f"venue_id {venue_id!r} — every reviewer must be calibrated to the chosen venue")
        rp = write_artifact(run_dir, "VERIFY", f"review-{persona}.artifact.json",
                            "venue_review", "venue-reviewer-persona", review, ts)
        reviews.append(review)
        review_paths.append(rp)
        paths.append(rp)

    # 3. router guardrail (VERIFY blocking gate): every persona the profile DECLARED must be present
    #    AND the adversarial seat is mandatory (a panel without an adversary cannot judge a venue).
    declared = list(profile.get("personas") or [])
    present = {str(r.get("persona")) for r in reviews}
    missing = [p for p in declared if p not in present]
    if missing:
        raise GateBlock(
            f"venue VERIFY: profile declares personas {declared} but the panel is missing {missing} "
            "— every declared reviewer seat must be filled before a readiness verdict")
    if "adversarial" not in present:
        raise GateBlock(
            "venue VERIFY: no adversarial reviewer in the panel — the adversarial seat is mandatory "
            "(it owns the eval-code re-derivation that catches leakage / unfair baselines)")

    # 4. deterministic independence (an echo chamber must not reach a publication verdict)
    independence = _independence(reviews, list(PERSONAS))

    # 5. derive the verdict (the SINGLE source of truth) and bind REAL evidence refs.
    #    derive_meets_bar returns evidence_ref as a placeholder — replace it with the real review
    #    artifact paths (relative to the run dir, so the trace is portable).
    verdict_payload = derive_meets_bar(reviews, profile, independence)
    rel_review_refs = [_rel(run_dir, rp) for rp in review_paths]
    verdict_payload["evidence_ref"] = rel_review_refs
    verdict_payload["independence_ref"] = (
        f"(deterministic pairwise lexical independence; max_sim={independence['max_sim']})")
    verdict_path = write_artifact(run_dir, "VERIFY", "venue-readiness-verdict.artifact.json",
                                  "venue_readiness_verdict", "area-chair-synthesizer",
                                  verdict_payload, ts)
    paths.append(verdict_path)

    # 6. north-star drift gate over the substantive review text + verdict (audit H2)
    drift_texts = [venue_id]
    drift_texts += [_review_text(r) for r in reviews]
    drift_texts.append(str(verdict_payload["verdict"]))
    dpath, _facts = _shared.run_drift_gate(run_dir, "VERIFY", ts, drift_texts)
    paths.append(dpath)

    unresolved = collect_unresolved_triggers(reviews)
    report = {"verdict": verdict_payload["verdict"], "unresolved_triggers": len(unresolved),
              "independence_max_sim": independence["max_sim"], "personas": sorted(present)}
    return paths, report


def _rel(run_dir, abs_path) -> str:
    """A run-relative reference (evidence/VERIFY/...) for an artifact path; falls back to the
    basename if the path is not under the run dir (never raises — refs are advisory text)."""
    try:
        return str(Path(abs_path).resolve().relative_to(Path(run_dir).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return Path(abs_path).name


def _report(run_dir, ts) -> tuple:
    note = {"summary": "venue_readiness: blind 3-persona panel reviewed against the venue rubric; "
                       "the readiness verdict is DERIVED by venue_score (never self-declared). "
                       "Venue choice is /venue-pick, the publish decision is /venue-decide — both "
                       "human gates; the panel only informs them.",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock on a
    STRUCTURAL failure (missing worker / persona, venue_id mismatch, schema, drift). The readiness
    verdict label itself is information for the director, NOT a GateBlock."""
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"venue_readiness has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop around the structural gates: ("ok", (paths, report)) or
    ("retry", feedback) when a worker bundle was malformed and the budget allows another attempt;
    re-raises the original GateBlock when the repair cap is reached (director escalation)."""
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts))
