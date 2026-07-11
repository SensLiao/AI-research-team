"""Staged operated recipe for venue-readiness peer review.

The worker sequence is profile -> config -> frozen precommit -> mutually blind reviews -> frozen
panel receipt -> area-chair meta-review -> deterministic readiness derivation. The final label is an
advisory screen, never an acceptance fact or submission decision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .. import bounded_repair
from ..artifacts import GateBlock, write_artifact
from . import _shared
from ...tools.idea_dedup import lexical_similarity
from ...tools import venue_review_protocol as protocol
from ...tools.venue_readiness_markdown import (
    VENUE_READINESS_REL,
    write_venue_readiness_markdown,
)
from ...tools.venue_score import collect_unresolved_triggers, derive_meets_bar


STAGES = ["VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"
INDEPENDENCE_SIM_THRESHOLD = 0.3

# Public aliases keep existing operate callers and fixtures compatible while the protocol logic
# lives in one venue-specific deterministic module.
PERSONAS = protocol.PERSONAS
PROTOCOL_VERSION = protocol.PROTOCOL_VERSION
PROFILE_BUNDLE_REL = protocol.PROFILE_BUNDLE_REL
CONFIG_BUNDLE_REL = protocol.CONFIG_BUNDLE_REL
PRECOMMIT_RECEIPT_REL = protocol.PRECOMMIT_RECEIPT_REL
PANEL_RECEIPT_REL = protocol.PANEL_RECEIPT_REL
META_BUNDLE_REL = protocol.META_BUNDLE_REL
PROFILE_ARTIFACT_REL = protocol.PROFILE_ARTIFACT_REL
CONFIG_ARTIFACT_REL = protocol.CONFIG_ARTIFACT_REL
PROFILE_REF = protocol.PROFILE_REF
CONFIG_REF = protocol.CONFIG_REF
PRECOMMIT_REF = protocol.PRECOMMIT_REF
PANEL_RECEIPT_REF = protocol.PANEL_RECEIPT_REF
prepare_review_precommit = protocol.prepare_review_precommit
prepare_review_panel_receipt = protocol.prepare_review_panel_receipt
_review_ref = protocol.review_ref


_PROFILE_WORKER_PROMPT = """You are the VENUE-SELECTOR in wave 1 of a staged venue-readiness run.

    REQUEST: {request}

{north_star_block}

Read the target venue rubric under `agents/references/venue-rubrics/` and the manuscript/result refs
named by the request. Instantiate the venue's real review standard for this work. Do not score the
paper, write a review, choose a different venue, or claim acceptance. Include all three personas.
Every evidence_ref must point to a rubric or work input you actually read.

Write ONLY this JSON to `{out}`:
{{
  "venue_profile": {{
    "venue_id": "<chosen target venue>",
    "tier": "conf|med|journal",
    "paper_type": "methodological|application-clinical",
    "dimension_weights": {{
      "D1":{{"weight":1.0,"gating":true}}, "D2":{{"weight":1.0}},
      "D3":{{"weight":1.0}}, "D4":{{"weight":1.5,"gating":true}},
      "D5":{{"weight":1.0}}, "D6":{{"weight":0.5}}, "D7":{{"weight":0.0}}
    }},
    "reject_triggers": [{{"trigger_id":"RT-D4-BASELINE","dimension":"D4",
      "description":"<what fires it>","our_risk":"<paper-specific risk, optional>"}}],
    "accept_condition": "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger",
    "anti_bias_suppressors": ["hasn't beaten SOTA alone", "new combination alone"],
    "personas": ["methodology","domain","adversarial"],
    "evidence_ref": ["<rubric path>","<manuscript/result ref>"]
  }}
}}
This is a candidate bundle. Reviewers are forbidden to read it; a deterministic step freezes it."""


_CONFIG_WORKER_PROMPT = """You are the VENUE-REVIEW-CONFIGURATOR in wave 2.

    REQUEST: {request}

{north_star_block}

Read ONLY `{profile_candidate}` plus rubric files named inside it. Do not read the manuscript,
results, code, reviewer outputs, or review prose. Freeze three distinct anchors before review:
methodology owns D1/D5, domain owns D2/D6/D7 when applicable, adversarial owns D3/D4.

`inputs_to_review` is the exact allowlist of manuscript, result, code, and data-pipeline refs that
reviewers may inspect. Never include candidate bundles, reviewer outputs, receipts, or meta output.

Write ONLY this JSON to `{out}`:
{{
  "review_config": {{
    "run_ref": "{run_dir}",
    "lenses": [
      {{"lens":"methodology","anchor":"<frozen venue-specific standard>",
        "reviewer_agent":"venue-reviewer-methodology-blind"}},
      {{"lens":"domain","anchor":"<different frozen standard>",
        "reviewer_agent":"venue-reviewer-domain-blind"}},
      {{"lens":"adversarial","anchor":"<different frozen standard>",
        "reviewer_agent":"venue-reviewer-adversarial-blind"}}
    ],
    "synthesis_mandate": "Surface all disagreements and strongest rejection; classify fatal vs
      repairable; order repairs; never claim acceptance; defer /venue-pick and /venue-decide.",
    "inputs_to_review": ["<manuscript/result/code/data refs only>"]
  }}
}}
The deterministic precommit step validates and hashes this config before any reviewer starts."""


_BLIND_REVIEW_PROMPT = """You are the `{persona}` reviewer in wave 4. You are blind to every other
reviewer and must remain so until your designated bundle is emitted.

    REQUEST: {request}

{north_star_block}

FROZEN INPUTS SHARED BY EVERY REVIEWER:
- profile `{profile_ref}`
- config `{config_ref}`
- receipt `{precommit_ref}`
- precommit hash `{precommit_hash}`

Read your frozen anchor FIRST. Then inspect only `review_config.inputs_to_review`, the task frame,
and the three frozen refs above. Never read profile/config candidates, another reviewer bundle,
review artifacts, the panel receipt, or meta output. If another review became visible, disclose it.

Deeply audit your owned dimensions. Every score needs a real manuscript/result/table/metric/code
locus; missing evidence means score 1. Fire only frozen-profile triggers and give a precise locus
and fix. Apply anti-bias suppressors and default low under uncertainty. The adversarial seat must
inspect evaluation code read-only for leakage, unfair baselines, test tuning, and aggregation bugs.

`overall` is reviewer advice on the venue scale, not an acceptance fact. Never emit verdict,
meets_bar, decision, status, or accept fields.

Write ONLY this JSON to `{out}`:
{{
  "venue_review": {{
    "persona": "{persona}", "venue_id": "{venue_id}",
    "dimension_scores": {{"D1":{{"score":3,"evidence_ref":["<real locus>"],
      "notes":"<evidence-based argument>"}}}},
    "reject_triggers_fired": [],
    "overall": "<venue-scale reviewer recommendation>", "confidence": 3,
    "evidence_ref": ["<real input pointer>"]
  }},
  "blind_review_attestation": {{
    "protocol_version": "{protocol_version}", "persona": "{persona}",
    "reviewer_instance_id": "venue-reviewer-{persona}-blind",
    "precommit_hash": "{precommit_hash}",
    "profile_ref": "{profile_ref}", "config_ref": "{config_ref}",
    "precommit_ref": "{precommit_ref}", "anchor_echo": "<copy frozen anchor exactly>",
    "input_refs": ["task_frame.artifact.json", "{profile_ref}", "{config_ref}",
      "{precommit_ref}", "<declared work input actually read>"],
    "other_review_refs_seen": [], "output_ref": "{output_ref}"
  }}
}}"""


_META_WORKER_PROMPT = """You are the AREA-CHAIR META-REVIEWER in the final judgment wave.

    REQUEST: {request}

{north_star_block}

All blind reviewers have finished. Read `{panel_receipt_ref}`, `{precommit_ref}`, and only the three
review bundles named by that receipt. Do not read manuscript/result/code inputs or candidate
bundles. Synthesize arguments, not means. Surface every score disagreement, the strongest credible
rejection case, every fired trigger, fatal-to-path vs repairable gaps, and a verified repair order.
Do not alter review hashes or claim the venue will accept. Deterministic scoring happens afterward.

Write ONLY this JSON to `{out}`:
{{
  "venue_meta_review": {{
    "protocol_version": "{protocol_version}",
    "precommit_hash": "{precommit_hash}",
    "review_receipt_ref": "{panel_receipt_ref}",
    "review_hashes": {review_hashes_json},
    "reviewer_disagreements": [{{"dimension":"D4",
      "personas":["methodology","domain","adversarial"],"score_span":1,
      "synthesis":"<why scores differ and which evidence is stronger>",
      "evidence_ref":["<all source review bundle refs>"]}}],
    "strongest_reject_reason": {{"status":"fatal|repairable|none","reason":"<strongest case>",
      "source_personas":["<persona>"],"evidence_ref":["<source review refs>"]}},
    "fatal_gaps": [{{"gap_id":"F1","trigger_id":"<omit when none>","reason":"<why fatal>",
      "evidence_ref":["<ref>"],"responsible_stage":"DESIGN|EXECUTE|ANALYZE|VERIFY"}}],
    "repairable_gaps": [{{"gap_id":"R1","trigger_id":"<omit when none>",
      "reason":"<fixable weakness>","evidence_ref":["<ref>"],
      "responsible_stage":"DESIGN|EXECUTE|ANALYZE|VERIFY"}}],
    "repair_sequence": [{{"priority":1,"gap_id":"R1","action":"<specific repair>",
      "responsible_stage":"<stage>","verification":"<objective re-check>"}}],
    "human_gates": ["/venue-pick","/venue-decide"], "advisory_only": true
  }}
}}
Every disagreement and gap must be represented; every gap needs a repair-sequence step."""


def _model_for_judgment(model_policy: str) -> str:
    # Compatibility workload tier; runtime provider/model selection is handled elsewhere.
    return "opus"


def _profile_worker(run_dir: str, request: str, model: str) -> dict:
    out = str(Path(run_dir) / PROFILE_BUNDLE_REL).replace("\\", "/")
    return {
        "label": "venue-selector", "model": model, "output": out,
        "prompt": _PROFILE_WORKER_PROMPT.format(
            request=request, north_star_block=_shared.north_star_block(run_dir), out=out,
        ),
    }


def _config_worker(run_dir: str, request: str, model: str) -> dict:
    out = str(Path(run_dir) / CONFIG_BUNDLE_REL).replace("\\", "/")
    return {
        "label": "venue-review-configurator", "model": model, "output": out,
        "prompt": _CONFIG_WORKER_PROMPT.format(
            request=request, run_dir=str(run_dir), out=out,
            profile_candidate=PROFILE_BUNDLE_REL.as_posix(),
            north_star_block=_shared.north_star_block(run_dir),
        ),
    }


def _review_worker(run_dir: str, request: str, model: str, persona: str,
                   profile: dict, receipt: dict) -> dict:
    output_ref = protocol.review_ref(persona)
    out = str(Path(run_dir) / output_ref).replace("\\", "/")
    return {
        "label": f"venue-reviewer-{persona}", "model": model, "output": out,
        "depends_on": ["freeze-venue-precommit"],
        "read_scope": list(receipt["allowed_reviewer_inputs"]),
        "forbidden_read_scope": list(receipt["forbidden_reviewer_inputs"]),
        "prompt": _BLIND_REVIEW_PROMPT.format(
            request=request, persona=persona, venue_id=profile["venue_id"], out=out,
            north_star_block=_shared.north_star_block(run_dir),
            profile_ref=PROFILE_REF, config_ref=CONFIG_REF, precommit_ref=PRECOMMIT_REF,
            precommit_hash=receipt["precommit_hash"], protocol_version=PROTOCOL_VERSION,
            output_ref=output_ref,
        ),
    }


def _meta_worker(run_dir: str, request: str, model: str, precommit: dict,
                 panel_receipt: dict) -> dict:
    out = str(Path(run_dir) / META_BUNDLE_REL).replace("\\", "/")
    return {
        "label": "area-chair-synthesizer", "model": model, "output": out,
        "depends_on": ["freeze-blind-review-panel"],
        "read_scope": [PRECOMMIT_REF, PANEL_RECEIPT_REF, *panel_receipt["review_refs"].values()],
        "forbidden_read_scope": [PROFILE_BUNDLE_REL.as_posix(), CONFIG_BUNDLE_REL.as_posix()],
        "prompt": _META_WORKER_PROMPT.format(
            request=request, out=out, protocol_version=PROTOCOL_VERSION,
            north_star_block=_shared.north_star_block(run_dir),
            precommit_hash=precommit["precommit_hash"], precommit_ref=PRECOMMIT_REF,
            panel_receipt_ref=PANEL_RECEIPT_REF,
            review_hashes_json=json.dumps(panel_receipt["review_hashes"], sort_keys=True),
        ),
    }


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """Return only the next legal worker wave; future-wave prompts stay unavailable."""
    if stage != "VERIFY":
        return None
    run_path = Path(run_dir)
    model = _model_for_judgment(model_policy)
    if not (run_path / PROFILE_BUNDLE_REL).exists():
        return _profile_worker(run_dir, request, model)
    if not (run_path / CONFIG_BUNDLE_REL).exists():
        return _config_worker(run_dir, request, model)

    if (run_path / PRECOMMIT_RECEIPT_REL).exists():
        profile, _config, precommit = protocol.load_precommit(run_dir)
    else:
        precommit = protocol.prepare_review_precommit(run_dir)
        profile, _config, precommit = protocol.load_precommit(run_dir)

    missing = [persona for persona in PERSONAS if not protocol.review_path(run_dir, persona).exists()]
    if missing:
        workers = [
            _review_worker(run_dir, request, model, persona, profile, precommit)
            for persona in missing
        ]
        return {
            "label": "venue-blind-review-panel", "workers": workers,
            "panel_note": "Spawn this wave concurrently. Every seat reads the same frozen "
                          f"precommit {precommit['precommit_hash']} and no reviewer output.",
            "protocol_version": PROTOCOL_VERSION,
            "precommit_hash": precommit["precommit_hash"],
        }

    panel_receipt = protocol.prepare_review_panel_receipt(run_dir)
    if not (run_path / META_BUNDLE_REL).exists():
        return _meta_worker(run_dir, request, model, precommit, panel_receipt)
    return None


def _review_text(review: dict) -> str:
    bits: List[str] = [str(review.get("overall") or "")]
    for score in (review.get("dimension_scores") or {}).values():
        if isinstance(score, dict) and score.get("notes"):
            bits.append(str(score["notes"]))
    for trigger in review.get("reject_triggers_fired") or []:
        bits.extend([str(trigger.get("locus") or ""), str(trigger.get("required_fix") or "")])
    return " ".join(bit for bit in bits if bit)


def _independence(reviews: List[dict], personas: List[str]) -> dict:
    pairs = []
    max_sim = 0.0
    for left in range(len(reviews)):
        for right in range(left + 1, len(reviews)):
            similarity = round(
                lexical_similarity(_review_text(reviews[left]), _review_text(reviews[right])), 4
            )
            pairs.append({"a": personas[left], "b": personas[right], "sim": similarity})
            max_sim = max(max_sim, similarity)
    return {
        "pairs": pairs,
        "max_sim": round(max_sim, 4),
        "verdict": "degraded" if max_sim >= INDEPENDENCE_SIM_THRESHOLD else "ok",
    }


def _rel(run_dir: str, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(run_dir).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return Path(path).name


def _verify_dets(run_dir: str, ts: str) -> tuple:
    run_path = Path(run_dir)
    profile, config, precommit = protocol.load_precommit(run_dir)
    panel_receipt = protocol.prepare_review_panel_receipt(run_dir)
    reviews_by_persona: Dict[str, dict] = {}
    for persona in PERSONAS:
        review, _attestation, _bundle = protocol.load_review_bundle_strict(
            run_dir, persona, profile, config, precommit,
        )
        reviews_by_persona[persona] = review
    meta = protocol.load_meta_review(run_dir, reviews_by_persona, panel_receipt)

    paths: List[str] = [
        str(run_path / PROFILE_ARTIFACT_REL),
        str(run_path / CONFIG_ARTIFACT_REL),
    ]
    paths.append(write_artifact(
        run_dir, "VERIFY", "venue-meta-review.artifact.json", "venue_meta_review",
        "area-chair-synthesizer", meta, ts,
    ))
    review_paths: List[str] = []
    reviews = [reviews_by_persona[persona] for persona in PERSONAS]
    for persona, review in zip(PERSONAS, reviews):
        path = write_artifact(
            run_dir, "VERIFY", f"review-{persona}.artifact.json", "venue_review",
            "venue-reviewer-persona", review, ts,
        )
        paths.append(path)
        review_paths.append(path)

    present = {str(review.get("persona")) for review in reviews}
    if set(profile.get("personas") or []) != present or present != set(PERSONAS):
        raise GateBlock("venue VERIFY: frozen personas do not match the completed blind panel")

    independence = _independence(reviews, list(PERSONAS))
    verdict = derive_meets_bar(reviews, profile, independence)
    verdict["evidence_ref"] = [_rel(run_dir, path) for path in review_paths]
    verdict["independence_ref"] = (
        f"{PRECOMMIT_REF} + {PANEL_RECEIPT_REF}; same_profile_hash="
        f"{precommit['profile_hash']}; lexical_max_sim={independence['max_sim']}"
    )
    paths.append(write_artifact(
        run_dir, "VERIFY", "venue-readiness-verdict.artifact.json",
        "venue_readiness_verdict", "area-chair-synthesizer", verdict, ts,
    ))

    strongest = meta.get("strongest_reject_reason") or {}
    drift_texts = [
        str(profile.get("venue_id") or ""),
        *[_review_text(review) for review in reviews],
        str(strongest.get("reason") or ""),
        str(verdict["verdict"]),
    ]
    drift_path, _facts = _shared.run_drift_gate(run_dir, "VERIFY", ts, drift_texts)
    paths.append(drift_path)

    unresolved = collect_unresolved_triggers(reviews)
    venue_markdown = write_venue_readiness_markdown(run_dir, generated_at=ts)
    return paths, {
        "verdict": verdict["verdict"],
        "unresolved_triggers": len(unresolved),
        "independence_max_sim": independence["max_sim"],
        "personas": sorted(present),
        "precommit_hash": precommit["precommit_hash"],
        "profile_hash": precommit["profile_hash"],
        "meta_advisory_only": meta["advisory_only"],
        "director_venue_readiness": venue_markdown,
    }


def _report(run_dir: str, ts: str) -> tuple:
    venue_markdown = write_venue_readiness_markdown(run_dir, generated_at=ts)
    note = {
        "summary": "venue_readiness used a frozen profile/config, three mutually blind persona "
                   "reviews, and a post-panel area-chair meta-review. The readiness label is "
                   "deterministically derived and advisory only. Venue choice remains /venue-pick; "
                   "submit/iterate/pivot remains /venue-decide.",
        "references": [VENUE_READINESS_REL.as_posix()],
        "produced_artifacts": [],
        "open_questions": [],
    }
    path = write_artifact(
        run_dir, "REPORT", "report-note.artifact.json", "report_note",
        "research-orchestrator", note, ts,
    )
    return [path], {"director_venue_readiness": venue_markdown}


def run_dets(run_dir: str, stage: str, ts: str) -> tuple:
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"venue_readiness has no stage {stage!r}")


def run_dets_with_repair(run_dir: str, stage: str, ts: str):
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts)
    )
