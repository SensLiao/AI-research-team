"""SPECS-lite review-calibration harness (absorption wave 1; AAAI-26 pilot + SPECS pattern).

The AAAI-26 AI-review pilot validated staged criterion review at production scale, and SPECS
measured reviewer quality by SEEDING known errors into papers and scoring planted-error recall.
This is the machine's first EXTERNAL ground truth for its mock-review prompts: seed errors into a
copy of a fixture paper, run the blind panel, score what they caught. A regression test for every
persona/prompt/model change — when recall drops, the prompt change regressed.

Division of labour (machine constitution):
  - The harness DESIGNER writes error_specs: where to inject, what the error is, which of the
    five AAAI criteria it violates, and the detect_patterns that count as a catch.
  - The PANEL (LLM reviewers) reviews the seeded copy blind.
  - THIS code does everything deterministic: injection (fail-loud), catch-matching
    (case-insensitive substring over the review text), recall math, payload assembly.
  - EVIDENCE only: a low recall flags prompts for revision; nothing is auto-rewritten.

Fixture hygiene: seeding always happens on a COPY under tests/ or runs/ scratch — never a vault
original (the caller passes text in; this module does no file I/O).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

CRITERIA = ("clarity", "novelty", "soundness", "significance", "reproducibility")


def _validate_spec(spec: dict) -> None:
    for f in ("error_id", "criterion", "description", "injection"):
        if not spec.get(f):
            raise ValueError(f"error spec missing {f!r}: {spec!r}")
    if spec["criterion"] not in CRITERIA:
        raise ValueError(f"criterion must be one of {CRITERIA}, got {spec['criterion']!r}")
    pats = spec.get("detect_patterns")
    if not pats or not all(isinstance(p, str) and p.strip() for p in pats):
        raise ValueError(f"error spec {spec['error_id']!r} needs non-empty detect_patterns "
                         f"(what counts as a catch must be decided BEFORE the panel runs)")


def seed_errors(paper_text: str, error_specs: List[dict]) -> Tuple[str, List[dict]]:
    """Inject every spec'd error into ``paper_text``; return (seeded_text, planted_key).

    Injection modes (deterministic, fail-loud):
      {"mode": "replace", "anchor": <text occurring EXACTLY once>, "replacement": <text>}
      {"mode": "append",  "text": <paragraph appended at the end>}
    """
    ids = [s.get("error_id") for s in error_specs]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate error_id in specs: {sorted(x for x in ids if ids.count(x) > 1)}")
    seeded = paper_text
    planted: List[dict] = []
    for spec in error_specs:
        _validate_spec(spec)
        inj = spec["injection"]
        mode = inj.get("mode")
        if mode == "replace":
            anchor, replacement = inj.get("anchor"), inj.get("replacement")
            if not anchor or replacement is None:
                raise ValueError(f"replace injection needs anchor+replacement: {spec['error_id']}")
            n = seeded.count(anchor)
            if n != 1:
                raise ValueError(f"injection anchor for {spec['error_id']!r} must occur exactly "
                                 f"once in the fixture (found {n}): {anchor[:60]!r}")
            seeded = seeded.replace(anchor, replacement)
        elif mode == "append":
            text = inj.get("text")
            if not text:
                raise ValueError(f"append injection needs text: {spec['error_id']}")
            seeded = seeded.rstrip() + "\n\n" + text
        else:
            raise ValueError(f"unknown injection mode {mode!r} for {spec['error_id']!r}")
        planted.append({"error_id": spec["error_id"], "criterion": spec["criterion"],
                        "description": spec["description"]})
    return seeded, planted


def _caught_by(spec: dict, review_text: str) -> bool:
    text = (review_text or "").casefold()
    return any(p.casefold() in text for p in spec["detect_patterns"])


def score_catch(error_specs: List[dict], reviews: List[dict], fixture_ref: str,
                evidence_ref: List[str], leniency_anchor: Optional[float] = None,
                explicit_catches: Optional[Dict[str, List[dict]]] = None) -> dict:
    """Score the panel's planted-error recall; returns the ``calibration_report`` payload.

    reviews: [{"by": seat label, "review_ref": artifact ref, "text": the review's full text}].
    explicit_catches: optional adjudicated catches {error_id: [{"by", "review_ref"}]} merged in
    (for paraphrases the substring patterns missed — adjudication is a human/LLM call recorded
    upstream; this code only merges it).
    """
    if not fixture_ref or not str(fixture_ref).strip():
        raise ValueError("fixture_ref is required")
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list")
    for spec in error_specs:
        _validate_spec(spec)
    for r in reviews:
        if not r.get("by"):
            raise ValueError(f"each review needs a 'by' seat label: {r!r}")
        # text MAY be empty only when catches are adjudicated out-of-band via explicit_catches
        # (the substring matcher has nothing to scan, but the adjudicator supplies the catch).
        if not str(r.get("text", "")).strip() and not explicit_catches:
            raise ValueError(f"each review needs non-empty text (unless explicit_catches is supplied): {r!r}")

    planted = [{"error_id": s["error_id"], "criterion": s["criterion"],
                "description": s["description"]} for s in error_specs]
    caught: List[dict] = []
    caught_ids = set()
    for spec in error_specs:
        for rev in reviews:
            if _caught_by(spec, str(rev.get("text", ""))):
                entry = {"error_id": spec["error_id"], "by": rev["by"]}
                if rev.get("review_ref"):
                    entry["review_ref"] = rev["review_ref"]
                caught.append(entry)
                caught_ids.add(spec["error_id"])
        for adj in (explicit_catches or {}).get(spec["error_id"], []):
            entry = {"error_id": spec["error_id"], "by": adj["by"]}
            if adj.get("review_ref"):
                entry["review_ref"] = adj["review_ref"]
            if entry not in caught:
                caught.append(entry)
                caught_ids.add(spec["error_id"])

    missed = [s["error_id"] for s in error_specs if s["error_id"] not in caught_ids]
    by_crit: Dict[str, List[str]] = {}
    for s in error_specs:
        by_crit.setdefault(s["criterion"], []).append(s["error_id"])
    recall_by_criterion = {
        crit: round(sum(1 for e in eids if e in caught_ids) / len(eids), 4)
        for crit, eids in sorted(by_crit.items())
    }
    payload = {
        "fixture_ref": fixture_ref,
        "planted": planted,
        "caught": caught,
        "missed": missed,
        "recall_overall": round(len(caught_ids) / len(error_specs), 4) if error_specs else 0.0,
        "recall_by_criterion": recall_by_criterion,
        "evidence_ref": list(evidence_ref),
    }
    if leniency_anchor is not None:
        payload["leniency_anchor"] = float(leniency_anchor)
    return payload
