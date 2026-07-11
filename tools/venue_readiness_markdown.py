"""Director-facing Markdown renderer for venue readiness runs.

Canonical evidence stays under evidence/VERIFY/*.artifact.json. This module
writes only:

    director-review/venue/venue-readiness.md

The page is a review packet for the director. It never chooses a venue, never
records a submit/iterate decision, and never writes the vault.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


VENUE_READINESS_REL = Path("director-review") / "venue" / "venue-readiness.md"
DIM_LABELS = {
    "D1": "Soundness / correctness",
    "D2": "Significance / impact",
    "D3": "Originality / novelty",
    "D4": "Evaluation rigor / fairness",
    "D5": "Reproducibility",
    "D6": "Clarity / presentation",
    "D7": "Clinical / domain validity",
}
REQUIRED_HEADINGS = [
    "## Decision Snapshot",
    "## Blind Review Protocol",
    "## Venue Fit And Rubric",
    "## Area Chair Verdict",
    "## Reviewer Panel",
    "## Reviewer Disagreements",
    "## Dimension Matrix",
    "## Strongest Rejection Case",
    "## Fatal Vs Repairable",
    "## Repair Order",
    "## Reject Triggers And Fixes",
    "## Human Venue Gate",
    "## Next Actions",
    "## Evidence Pointers",
]

PRECOMMIT_REL = Path("inbox") / "VERIFY.precommit.receipt.json"
PANEL_RECEIPT_REL = Path("inbox") / "VERIFY.reviews.receipt.json"


def venue_readiness_path(run_dir) -> Path:
    return Path(run_dir) / VENUE_READINESS_REL


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _payload(path: Path) -> dict:
    payload = _read_json(path).get("payload")
    return payload if isinstance(payload, dict) else {}


def _stage_payload(run_path: Path, filename: str) -> dict:
    return _payload(run_path / "evidence" / "VERIFY" / filename)


def _task_payload(run_path: Path) -> dict:
    return _payload(run_path / "task_frame.artifact.json")


def _one_line(value: object, *, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _csv(values: list | tuple | None, *, limit: int = 6) -> str:
    vals = [str(v) for v in (values or []) if str(v).strip()]
    if not vals:
        return "none recorded"
    shown = vals[:limit]
    suffix = f", +{len(vals) - limit} more" if len(vals) > limit else ""
    return ", ".join(f"`{v}`" for v in shown) + suffix


def _review_payloads(run_path: Path) -> list[dict]:
    verify_dir = run_path / "evidence" / "VERIFY"
    rows = []
    if verify_dir.exists():
        for p in sorted(verify_dir.glob("review-*.artifact.json")):
            payload = _payload(p)
            if payload:
                rows.append(payload)
    return sorted(rows, key=lambda r: str(r.get("persona") or ""))


def _min_scores(reviews: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for review in reviews:
        for dim, row in (review.get("dimension_scores") or {}).items():
            if isinstance(row, dict) and isinstance(row.get("score"), int):
                out[dim] = min(out.get(dim, row["score"]), row["score"])
    return out


def _gating_dims(profile: dict) -> set[str]:
    dims = set()
    for dim, row in (profile.get("dimension_weights") or {}).items():
        if isinstance(row, dict) and row.get("gating") is True:
            dims.add(dim)
    return dims


def _trigger_rows(reviews: list[dict]) -> list[dict]:
    rows = []
    for review in reviews:
        persona = str(review.get("persona") or "unknown")
        for trig in review.get("reject_triggers_fired") or []:
            if isinstance(trig, dict):
                row = dict(trig)
                row["persona"] = persona
                rows.append(row)
    return rows


def _status_line(verdict: str) -> str:
    if verdict == "MEETS-BAR":
        return ("The deterministic readiness screen clears the configured bar. This is advisory "
                "evidence, not a venue acceptance prediction or decision.")
    if verdict == "BORDERLINE":
        return "The advisory screen sees a plausible path, but non-gating weaknesses remain."
    if verdict == "NOT-YET":
        return "The advisory screen finds unresolved gaps; repair and re-review before submission."
    if verdict == "WRONG-PATH":
        return "The advisory screen finds structural mismatch or core weaknesses in this venue path."
    if verdict == "DEGRADED-REVIEW":
        return "The panel review itself is degraded; do not treat the venue verdict as publication-ready."
    return "No derived verdict was found."


def build_venue_readiness_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    task = _task_payload(run_path)
    profile = _stage_payload(run_path, "venue-profile.artifact.json")
    verdict = _stage_payload(run_path, "venue-readiness-verdict.artifact.json")
    reviews = _review_payloads(run_path)
    precommit = _read_json(run_path / PRECOMMIT_REL)
    panel_receipt = _read_json(run_path / PANEL_RECEIPT_REL)
    meta = _stage_payload(run_path, "venue-meta-review.artifact.json")
    if not profile:
        raise ValueError("venue Markdown BLOCK: venue-profile artifact missing")
    if not verdict:
        raise ValueError("venue Markdown BLOCK: venue-readiness-verdict artifact missing")
    if not reviews:
        raise ValueError("venue Markdown BLOCK: no venue review artifacts found")
    if not precommit or not panel_receipt:
        raise ValueError("venue Markdown BLOCK: blind-review precommit/panel receipt missing")
    if not meta or meta.get("advisory_only") is not True:
        raise ValueError("venue Markdown BLOCK: validated advisory meta-review missing")

    run_id = task.get("task_id") or run_path.name
    project = task.get("project") or "unregistered"
    request = task.get("request_text") or ""
    north_star = task.get("north_star") or {}
    statement = north_star.get("statement") or request
    venue_id = profile.get("venue_id") or "unknown"
    verdict_label = verdict.get("verdict") or "UNKNOWN"
    unresolved = verdict.get("unresolved_reject_triggers") or []
    min_scores = _min_scores(reviews)
    gating = _gating_dims(profile)
    triggers = _trigger_rows(reviews)

    lines: list[str] = [
        "---",
        f"run_id: {run_id}",
        f"project: {project}",
        f"mode: venue_readiness",
        f"venue_id: {venue_id}",
        f"generated_at: {generated_at or ''}",
        "primary_human_action: /venue-pick or /venue-decide",
        "records_submission_decision: false",
        "advisory_only: true",
        "json_evidence_root: ../../evidence",
        "---",
        "",
        f"# Venue Readiness Packet - {venue_id} - {run_id}",
        "",
        "## Decision Snapshot",
        "",
        f"- North star: {_one_line(statement, limit=420)}",
        f"- Derived readiness verdict: `{verdict_label}`.",
        f"- Interpretation: {_status_line(str(verdict_label))}",
        f"- Review panel: {len(reviews)} persona(s): {_csv([r.get('persona') for r in reviews])}.",
        f"- Unresolved reject triggers: {len(unresolved)} ({_csv(unresolved)}).",
        "- This page records an advisory readiness screen. It is not an acceptance fact or venue decision.",
        "- It does not pick a venue, submit, promote, or publish.",
        "",
        "## Blind Review Protocol",
        "",
        f"- Protocol: `{precommit.get('protocol_version')}`.",
        f"- Frozen precommit hash: `{precommit.get('precommit_hash')}`.",
        f"- Frozen profile hash: `{precommit.get('profile_hash')}`.",
        f"- Shared profile ref: `{precommit.get('profile_ref')}`.",
        f"- Shared config ref: `{precommit.get('config_ref')}`.",
        f"- Reviewer instance ids: {_csv(list((panel_receipt.get('reviewer_instance_ids') or {}).values()), limit=8)}.",
        "- Each reviewer emitted a separate bundle before the area-chair meta-review was allowed to start.",
        "- Lexical similarity is only an echo-chamber warning; hash/ref, read-scope, and ordering checks are the protocol gate.",
        "",
        "## Venue Fit And Rubric",
        "",
        f"- Venue: `{venue_id}`; tier `{profile.get('tier')}`; paper type `{profile.get('paper_type')}`.",
        f"- Accept condition: `{profile.get('accept_condition')}`.",
        f"- Active gating dimensions: {_csv(sorted(gating))}.",
        f"- Anti-bias suppressors: {_csv(profile.get('anti_bias_suppressors'), limit=8)}.",
        f"- Rubric evidence: {_csv(profile.get('evidence_ref'), limit=8)}.",
        "",
        "## Area Chair Verdict",
        "",
        f"- Verdict: `{verdict_label}`.",
        f"- Independence evidence: `{verdict.get('independence_ref', 'not recorded')}`.",
    ]
    synth = verdict.get("dimension_synthesis") or []
    if synth:
        lines.append("- Dimension synthesis:")
        for row in synth:
            dim = row.get("dimension")
            score = row.get("agreed_score", "n/a")
            lines.append(f"  - `{dim}` {DIM_LABELS.get(str(dim), '')}: min/anchor score `{score}`. {_one_line(row.get('argument'), limit=360)}")
    gaps = verdict.get("gaps") or []
    if gaps:
        lines.append("- Required fixes routed by area chair:")
        for gap in gaps:
            lines.append(
                f"  - `{gap.get('stage')}`: {_one_line(gap.get('gap'), limit=180)} -> "
                f"{_one_line(gap.get('what_to_add'), limit=280)}"
            )
    strengths = verdict.get("strengths") or []
    shore_up = verdict.get("shore_up") or []
    if strengths:
        lines.append(f"- Strengths to preserve: {_csv(strengths, limit=8)}.")
    if shore_up:
        lines.append(f"- Shore-up before submission: {_csv(shore_up, limit=8)}.")
    lines.extend(["", "## Reviewer Panel", ""])
    for review in reviews:
        persona = review.get("persona") or "unknown"
        lines.extend([
            f"### {persona}",
            "",
            f"- Overall: `{review.get('overall')}`; confidence `{review.get('confidence')}`.",
            f"- Evidence read: {_csv(review.get('evidence_ref'), limit=8)}.",
        ])
        if review.get("minimal_fix"):
            lines.append(f"- Minimal fix: {_one_line(review.get('minimal_fix'), limit=360)}")
        dims = review.get("dimension_scores") or {}
        if dims:
            lines.append("- Dimension notes:")
            for dim in sorted(dims):
                row = dims[dim] if isinstance(dims[dim], dict) else {}
                lines.append(
                    f"  - `{dim}` score `{row.get('score')}`: {_one_line(row.get('notes'), limit=320)} "
                    f"(refs: {_csv(row.get('evidence_ref'), limit=5)})"
                )
        fired = review.get("reject_triggers_fired") or []
        if fired:
            lines.append("- Fired triggers:")
            for trig in fired:
                lines.append(
                    f"  - `{trig.get('trigger_id')}` at {trig.get('locus')}: "
                    f"{_one_line(trig.get('required_fix'), limit=260)}"
                )
        else:
            lines.append("- Fired triggers: none recorded.")
        lines.append("")

    lines.extend(["## Reviewer Disagreements", ""])
    disagreements = meta.get("reviewer_disagreements") or []
    if disagreements:
        for row in disagreements:
            lines.append(
                f"- `{row.get('dimension')}` span `{row.get('score_span')}` across "
                f"{_csv(row.get('personas'), limit=6)}: {_one_line(row.get('synthesis'), limit=420)} "
                f"(refs: {_csv(row.get('evidence_ref'), limit=6)})"
            )
    else:
        lines.append("- No cross-reviewer score disagreement was recorded.")

    lines.extend([
        "",
        "## Dimension Matrix",
        "",
        "| Dimension | Label | Gating | Min score | Methodology | Domain | Adversarial |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    by_persona = {str(r.get("persona")): r for r in reviews}
    for dim in ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]:
        vals = []
        for persona in ["methodology", "domain", "adversarial"]:
            row = ((by_persona.get(persona) or {}).get("dimension_scores") or {}).get(dim) or {}
            vals.append(str(row.get("score", "")))
        lines.append(
            f"| `{dim}` | {DIM_LABELS[dim]} | {'yes' if dim in gating else 'no'} | "
            f"{min_scores.get(dim, '')} | {vals[0]} | {vals[1]} | {vals[2]} |"
        )

    strongest = meta.get("strongest_reject_reason") or {}
    lines.extend([
        "",
        "## Strongest Rejection Case",
        "",
        f"- Classification: `{strongest.get('status', 'unknown')}`.",
        f"- Argument: {_one_line(strongest.get('reason'), limit=520)}",
        f"- Source reviewers: {_csv(strongest.get('source_personas'), limit=6)}.",
        f"- Evidence: {_csv(strongest.get('evidence_ref'), limit=8)}.",
        "- This is the strongest challenge the director should try to falsify before acting on a positive screen.",
        "",
        "## Fatal Vs Repairable",
        "",
        "### Fatal to this venue/path",
        "",
    ])
    fatal_gaps = meta.get("fatal_gaps") or []
    if fatal_gaps:
        for gap in fatal_gaps:
            lines.append(
                f"- `{gap.get('gap_id')}` ({gap.get('responsible_stage')}): "
                f"{_one_line(gap.get('reason'), limit=420)} "
                f"(trigger: `{gap.get('trigger_id', 'none')}`; refs: "
                f"{_csv(gap.get('evidence_ref'), limit=6)})"
            )
    else:
        lines.append("- No fatal-to-this-venue/path gap was recorded by the meta-review.")
    lines.extend(["", "### Repairable before submission", ""])
    repairable_gaps = meta.get("repairable_gaps") or []
    if repairable_gaps:
        for gap in repairable_gaps:
            lines.append(
                f"- `{gap.get('gap_id')}` ({gap.get('responsible_stage')}): "
                f"{_one_line(gap.get('reason'), limit=420)} "
                f"(trigger: `{gap.get('trigger_id', 'none')}`; refs: "
                f"{_csv(gap.get('evidence_ref'), limit=6)})"
            )
    else:
        lines.append("- No repairable gap was recorded by the meta-review.")

    lines.extend(["", "## Repair Order", ""])
    repair_sequence = meta.get("repair_sequence") or []
    if repair_sequence:
        for step in sorted(repair_sequence, key=lambda row: row.get("priority", 999)):
            lines.append(
                f"{step.get('priority')}. `{step.get('gap_id')}` -> "
                f"{_one_line(step.get('action'), limit=360)} "
                f"[{step.get('responsible_stage')}]; verify: "
                f"{_one_line(step.get('verification'), limit=300)}"
            )
    else:
        lines.append("- No repair step is currently required by the meta-review.")

    lines.extend(["", "## Reject Triggers And Fixes", ""])
    if triggers:
        for trig in triggers:
            lines.append(
                f"- `{trig.get('trigger_id')}` ({trig.get('dimension')}, {trig.get('persona')}): "
                f"locus `{trig.get('locus')}`; required fix: {_one_line(trig.get('required_fix'), limit=360)}"
            )
    else:
        lines.append("- No reject trigger fired in the panel.")
    active = profile.get("reject_triggers") or []
    if active:
        lines.append("")
        lines.append("Active venue trigger risks from the profile:")
        for trig in active:
            risk = trig.get("our_risk") or "no paper-specific risk recorded"
            lines.append(f"- `{trig.get('trigger_id')}` ({trig.get('dimension')}): {_one_line(risk, limit=280)}")

    lines.extend([
        "",
        "## Human Venue Gate",
        "",
        "- `/venue-pick`: the director chooses or changes the target venue; no worker may do this.",
        "- `/venue-decide`: the director chooses SUBMIT / ADD-EXPERIMENTS / CHANGE-METHOD / PIVOT / RE-REVIEW.",
        "- A `MEETS-BAR` screen is not an acceptance probability, acceptance promise, or submission authorization.",
        "",
        "## Next Actions",
        "",
        "1. Use `/venue-pick` only if the target venue itself still needs a human choice.",
        "2. Use `/venue-decide` for SUBMIT / ADD-EXPERIMENTS / CHANGE-METHOD / PIVOT / RE-REVIEW.",
        "3. If verdict is `NOT-YET`, route each listed gap to the named stage before submitting.",
        "4. If verdict is `DEGRADED-REVIEW`, rerun or diversify the review panel before acting.",
        "5. Do not promote the result to the database unless `/promote-to-vault` later re-derives a frozen claim.",
        "",
        "## Evidence Pointers",
        "",
        "- Profile: `evidence/VERIFY/venue-profile.artifact.json`.",
        "- Review config: `evidence/VERIFY/review-config.artifact.json`.",
        "- Frozen precommit: `inbox/VERIFY.precommit.receipt.json`.",
        "- Frozen review panel: `inbox/VERIFY.reviews.receipt.json`.",
        "- Area-chair meta-review: `evidence/VERIFY/venue-meta-review.artifact.json` "
        "(validated from `inbox/VERIFY.meta.bundle.json`).",
        "- Reviews: `evidence/VERIFY/review-methodology.artifact.json`, `review-domain.artifact.json`, `review-adversarial.artifact.json` when present.",
        "- Derived verdict: `evidence/VERIFY/venue-readiness-verdict.artifact.json`.",
        f"- Verdict evidence refs: {_csv(verdict.get('evidence_ref'), limit=8)}.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def lint_venue_readiness_markdown(run_dir) -> list[str]:
    run_path = Path(run_dir)
    out = venue_readiness_path(run_path)
    errors: list[str] = []
    if not out.is_file():
        return [f"missing {VENUE_READINESS_REL.as_posix()}"]
    text = out.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    profile = _stage_payload(run_path, "venue-profile.artifact.json")
    verdict = _stage_payload(run_path, "venue-readiness-verdict.artifact.json")
    if profile and str(profile.get("venue_id")) not in text:
        errors.append("Markdown venue packet omits venue_id")
    if verdict and str(verdict.get("verdict")) not in text:
        errors.append("Markdown venue packet omits derived verdict")
    for review in _review_payloads(run_path):
        persona = str(review.get("persona") or "")
        if persona and persona not in text:
            errors.append(f"Markdown venue packet omits persona: {persona}")
    if "records_submission_decision: false" not in text:
        errors.append("Markdown venue packet must state records_submission_decision: false")
    if "advisory_only: true" not in text:
        errors.append("Markdown venue packet must state advisory_only: true")
    if "/venue-pick" not in text or "/venue-decide" not in text:
        errors.append("Markdown venue packet must surface both human venue gates")
    precommit = _read_json(run_path / PRECOMMIT_REL)
    if precommit and str(precommit.get("precommit_hash")) not in text:
        errors.append("Markdown venue packet omits frozen precommit hash")
    meta = _stage_payload(run_path, "venue-meta-review.artifact.json")
    strongest = (meta.get("strongest_reject_reason") or {}).get("reason") if meta else None
    if strongest and _one_line(strongest, limit=520) not in text:
        errors.append("Markdown venue packet omits strongest rejection case")
    if len(text.strip()) < 900:
        errors.append("venue readiness Markdown packet is too short to be decision-useful")
    return errors


def write_venue_readiness_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    out = venue_readiness_path(run_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_venue_readiness_markdown(run_path, generated_at=generated_at), encoding="utf-8")
    errors = lint_venue_readiness_markdown(run_path)
    if errors:
        raise ValueError(f"venue readiness Markdown BLOCK: {errors}")
    return str(out)
