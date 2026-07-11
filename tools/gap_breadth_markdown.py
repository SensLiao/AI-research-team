"""Director-facing scientific gap dossiers for the operated ``gap_breadth`` mode."""
from __future__ import annotations

from collections import Counter
import re


QUADRANT_DESCRIPTIONS = {
    "Known Known": "Established knowledge that bounds the question and supplies controls.",
    "Unknown Known": "Relevant knowledge exists elsewhere but has not been connected to this problem.",
    "Known Unknown": "The literature explicitly recognizes the unresolved question or boundary.",
    "Unknown Unknown": "A hidden assumption or blind spot inferred from anomalies; highest uncertainty.",
}

REQUIRED_HEADINGS = (
    "## Bottom Line",
    "## Knowledge Quadrants",
    "## Ranked Scientific Opportunities",
    "## Why Worth Studying",
    "## Evidence Anchors",
    "## Gap Dossiers",
    "## Novelty Uncertainty",
    "## First Falsification Experiment",
    "## Kill Criteria",
    "## Closed By Prior Art",
    "## Decision Boundary",
    "## Next Action",
)


def _one_line(value: object, default: str = "not recorded") -> str:
    text = " ".join(str(value or "").split()) or default
    return text.replace("|", "/")


def _score(value: object) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "n/a"


def scientific_opportunity_score(audit: dict, dimensions, weights) -> float:
    weighted = sum(
        float(audit["dimensions"][dimension]["score"]) * weights[dimension]
        for dimension in dimensions
    )
    return round((weighted / 5.0) * 100.0, 1)


def _signal_statement(signal: dict, classified: dict) -> str:
    for key in ("statement", "opportunity", "target_hook", "challenged_assumption",
                "untested_condition", "untested_dataset"):
        if signal.get(key):
            return _one_line(signal[key])
    return f"{classified.get('gap_type', 'research')} question"


def build_entries(classification: dict, novelty: dict, signals: list[dict],
                  prosecutions: dict[str, dict], dossiers: dict[str, dict],
                  audits: dict[str, dict], dimensions, weights) -> list[dict]:
    signal_map = {str(row["gap_id"]): row for row in signals}
    class_map = {str(row["gap_id"]): row for row in classification.get("gaps", [])}
    novelty_map = {str(row["gap_id"]): row for row in novelty.get("scores", [])}
    order = {str(row["gap_id"]): index for index, row in enumerate(signals)}
    verdict_order = {"PASS": 0, "REVISE": 1, "BLOCK": 2}
    entries = []
    for gap_id, dossier in dossiers.items():
        audit = audits[gap_id]
        classified = class_map.get(gap_id, {})
        novelty_row = novelty_map.get(gap_id, {})
        entries.append({
            "gap_id": gap_id,
            "signal": signal_map.get(gap_id, {}),
            "classified": classified,
            "novelty": novelty_row,
            "prosecution": prosecutions[gap_id],
            "dossier": dossier,
            "audit": audit,
            "opportunity_score": scientific_opportunity_score(audit, dimensions, weights),
            "statement": _signal_statement(signal_map.get(gap_id, {}), classified),
            "original_order": order.get(gap_id, 10_000),
        })
    return sorted(
        entries,
        key=lambda row: (
            verdict_order.get(row["audit"]["verdict"], 3),
            -row["opportunity_score"],
            row["original_order"],
        ),
    )


def _paper_summary(paper: dict) -> str:
    ref = _one_line(paper.get("source_ref"))
    title = _one_line(paper.get("title"), "title not recorded")
    contribution = _one_line(
        paper.get("contribution") or paper.get("completed_scope") or paper.get("relationship")
    )
    boundary = _one_line(
        paper.get("remaining_boundary") or paper.get("result_locator"), "boundary not recorded"
    )
    verification = paper.get("scope_verification") or {}
    if verification:
        snapshot = _one_line(verification.get("snapshot_ref"), "snapshot not recorded")
        digest = _one_line(verification.get("document_hash"), "hash not recorded")
        scope_span = verification.get("scope_span") or {}
        result_span = verification.get("result_span") or {}
        provenance = (
            f" full-text snapshot `{snapshot}`; hash `{digest}`; scope span "
            f"[{scope_span.get('start_char')}, {scope_span.get('end_char')}); result span "
            f"[{result_span.get('start_char')}, {result_span.get('end_char')})."
        )
    else:
        provenance = " no independently verified full-text snapshot was recorded."
    return f"`{ref}` ({title}): {contribution}; boundary/locator: {boundary}.{provenance}"


def render_gap_scan(classification: dict, novelty: dict, signals: list[dict],
                    prosecutions: dict[str, dict], dossiers: dict[str, dict],
                    audits: dict[str, dict], dimensions, weights, grounded: bool) -> str:
    entries = build_entries(
        classification, novelty, signals, prosecutions, dossiers, audits, dimensions, weights
    )
    closed = [
        (gap_id, row) for gap_id, row in prosecutions.items()
        if row["closure_status"] == "CLOSED"
    ]
    status_counts = Counter(row["closure_status"] for row in prosecutions.values())
    verdict_counts = Counter(row["audit"]["verdict"] for row in entries)
    quadrant_counts = Counter(row["dossier"]["knowledge_quadrant"] for row in entries)
    reviewable = [row for row in entries if row["audit"]["verdict"] != "BLOCK"]
    grounding = (
        "Live retrieval was available; each closure claim still requires paper-level scope and result evidence."
        if grounded else
        "No shared pre-search bundle was available. Search absence cannot establish openness; unresolved cases remain UNVERIFIED."
    )

    lines = [
        "# Scientific Gap Dossiers - gap_breadth",
        "",
        "## Bottom Line",
        "",
        f"- Five mutually blind hunters produced {len(signals)} signals; independent prosecution marked "
        f"OPEN={status_counts['OPEN']}, UNVERIFIED={status_counts['UNVERIFIED']}, "
        f"CLOSED={status_counts['CLOSED']}.",
        f"- Independent dossier audit: PASS={verdict_counts['PASS']}, REVISE={verdict_counts['REVISE']}, "
        f"BLOCK={verdict_counts['BLOCK']}.",
        f"- {grounding}",
    ]
    if reviewable:
        top = reviewable[0]
        lines.append(
            f"- Highest audit-admissible dossier for human review is `{top['gap_id']}` "
            f"(scientific opportunity score {_score(top['opportunity_score'])}/100). This is triage, not a bet."
        )
    else:
        lines.append("- No dossier is currently audit-admissible; repair evidence or falsifiability before ideation.")

    lines.extend([
        "",
        "## Knowledge Quadrants",
        "",
        "| Quadrant | Operational meaning | Surviving dossiers |",
        "|---|---|---:|",
    ])
    for quadrant, description in QUADRANT_DESCRIPTIONS.items():
        lines.append(f"| {quadrant} | {description} | {quadrant_counts[quadrant]} |")

    lines.extend([
        "",
        "## Ranked Scientific Opportunities",
        "",
        "These ranked gaps are derived from an independent six-dimension audit: importance 25%, openness 10%, "
        "falsifiability 20%, information gain 20%, mechanism clarity 20%, feasibility 5%. "
        "Novelty is not part of this rank and feasibility cannot dominate it.",
        "",
        "| Rank | Gap | Quadrant | Closure | Audit | Score | Importance | Falsifiability | Info gain | Mechanism | Feasibility |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for rank, row in enumerate(entries, start=1):
        dims = row["audit"]["dimensions"]
        lines.append(
            f"| {rank} | `{row['gap_id']}` | {row['dossier']['knowledge_quadrant']} | "
            f"{row['prosecution']['closure_status']} | {row['audit']['verdict']} | "
            f"{_score(row['opportunity_score'])} | {dims['importance']['score']} | "
            f"{dims['falsifiability']['score']} | {dims['information_gain']['score']} | "
            f"{dims['mechanism_clarity']['score']} | {dims['feasibility']['score']} |"
        )

    lines.extend(["", "## Why Worth Studying", ""])
    for row in entries:
        rationale = row["audit"]["dimensions"]["importance"]["rationale"]
        lines.append(f"- `{row['gap_id']}`: {_one_line(rationale)}")

    lines.extend(["", "## Evidence Anchors", ""])
    for row in entries:
        refs = list(dict.fromkeys(
            list(row["dossier"].get("evidence_refs") or [])
            + list(row["prosecution"].get("evidence_ref") or [])
        ))
        lines.append(f"- `{row['gap_id']}`: " + ", ".join(f"`{_one_line(ref)}`" for ref in refs))

    lines.extend(["", "## Gap Dossiers", ""])
    for rank, row in enumerate(entries, start=1):
        dossier, prosecution, audit = row["dossier"], row["prosecution"], row["audit"]
        experiment, resources = dossier["minimum_discriminating_experiment"], dossier["resources"]
        bridge = dossier["cross_domain_bridge"]
        lines.extend([
            f"### {rank}. `{row['gap_id']}` - {_one_line(dossier['problem_statement'])}",
            "",
            f"- **Knowledge quadrant:** {dossier['knowledge_quadrant']}. {_one_line(dossier['quadrant_basis'])}",
            f"- **Classification:** `{row['classified'].get('gap_type', 'not recorded')}`; "
            f"closure status `{prosecution['closure_status']}`.",
            f"- **Why still open / uncertain:** {_one_line(dossier['why_open'])}",
            f"- **Strongest counterargument:** {_one_line(dossier['strongest_counterargument'])}",
            f"- **Prosecutor's strongest counterevidence:** {_one_line(prosecution['strongest_counterevidence'])}",
            f"- **Counterevidence:** {'; '.join(_one_line(item) for item in dossier['counterevidence'])}",
            f"- **Related hunter signals:** {', '.join(f'`{item}`' for item in dossier['related_gap_ids']) or 'none'}.",
            "",
            "**Recent prior art**",
            "",
        ])
        for paper in dossier["recent_prior_art"]:
            lines.append(f"- {_paper_summary(paper)}")
        lines.extend(["", "**Mechanism / causal chain**", ""])
        for index, step in enumerate(dossier["mechanism_chain"], start=1):
            lines.append(f"{index}. {_one_line(step)}")
        lines.extend([
            "",
            "**Cross-domain bridge**",
            "",
            f"- Source domain: {_one_line(bridge['source_domain'])}",
            f"- Transferable mechanism: {_one_line(bridge['transferable_mechanism'])}",
            f"- Target fit: {_one_line(bridge['target_fit'])}",
            f"- Boundary conditions: {_one_line(bridge['boundary_conditions'])}",
            "",
            "**Minimum discriminating experiment**",
            "",
            f"- Hypothesis: {_one_line(experiment['hypothesis'])}",
            f"- Intervention: {_one_line(experiment['intervention'])}",
            f"- Baselines / controls: {'; '.join(_one_line(item) for item in experiment['baseline_controls'])}",
            f"- Primary outcome: {_one_line(experiment['primary_outcome'])}",
            f"- Success threshold: {_one_line(experiment['success_threshold'])}",
            f"- Failure threshold: {_one_line(experiment['failure_threshold'])}",
            f"- Kill criteria: {_one_line(experiment['kill_criteria'])}",
            "",
            "**Resources and audit**",
            "",
            f"- Data: {_one_line(resources['data'])}",
            f"- Compute: {_one_line(resources['compute'])}",
            f"- Implementation: {_one_line(resources['implementation'])}",
            f"- Estimated effort: {_one_line(resources['estimated_effort'])}",
            f"- Audit verdict: `{audit['verdict']}`; strongest objection: {_one_line(audit['strongest_objection'])}",
            f"- Required repairs: {'; '.join(_one_line(item) for item in audit['required_repairs']) or 'none'}.",
            f"- Next step: {_one_line(dossier['next_step'])}",
            "",
        ])

    lines.extend(["## Novelty Uncertainty", "", f"- {grounding}"])
    lines.append("- Novelty remains score-only and is not proof of an open gap, even when retrieval finds no close title.")
    for row in entries:
        novelty_row = row["novelty"]
        lines.append(
            f"- `{row['gap_id']}`: novelty={_score(novelty_row.get('novelty'))}, "
            f"legacy feasibility signal={_score(novelty_row.get('feasibility_signal'))}; "
            f"prosecuted status={row['prosecution']['closure_status']}."
        )

    lines.extend(["", "## First Falsification Experiment", ""])
    for row in entries:
        exp = row["dossier"]["minimum_discriminating_experiment"]
        lines.append(
            f"- `{row['gap_id']}`: {_one_line(exp['intervention'])}; compare against "
            f"{'; '.join(_one_line(item) for item in exp['baseline_controls'])}; "
            f"primary outcome {_one_line(exp['primary_outcome'])}."
        )

    lines.extend(["", "## Kill Criteria", ""])
    for row in entries:
        exp = row["dossier"]["minimum_discriminating_experiment"]
        lines.append(f"- `{row['gap_id']}`: {_one_line(exp['kill_criteria'])}")

    lines.extend(["", "## Closed By Prior Art", ""])
    if not closed:
        lines.append("- No gap was cut as CLOSED. This does not mean the remaining gaps are proven open.")
    for gap_id, prosecution in closed:
        lines.append(f"- `{gap_id}` was cut only because the prosecutor supplied completed-paper evidence:")
        for paper in prosecution["closure_evidence"]:
            lines.append(f"  - {_paper_summary(paper)}")

    lines.extend([
        "",
        "## Decision Boundary",
        "",
        "- This scan does not self-bet, approve an idea, or claim novelty. It prosecutes candidate gaps "
        "and orders surviving dossiers for director review.",
        "- CLOSED requires a real completed paper plus an independently re-opened full-text snapshot, "
        "document hash, and exact scope/result spans. Source existence or title similarity alone is "
        "insufficient. OPEN requires positive source-located evidence. Everything else is UNVERIFIED.",
        "- JSON bundles are machine evidence. This Markdown is the human review product and remains scratch "
        "unless a later human gate promotes a vetted result.",
        "",
        "## Next Action",
        "",
    ])
    if reviewable:
        lines.append(
            f"- Review `{reviewable[0]['gap_id']}` first because it is the strongest audit-admissible "
            "dossier under the declared scientific rubric; the director still decides whether to run `new_direction`."
        )
    lines.append("- For every UNVERIFIED dossier, run targeted full-text prior-art retrieval before spending experiment budget.")
    lines.append("- Send REVISE dossiers back to the named repair list; do not average away the objection.")
    lines.append("- Do not advance BLOCK dossiers until their evidence or falsifiability defect is repaired.")
    return "\n".join(lines).rstrip() + "\n"


def lint_gap_scan(text: str, expected_gap_ids) -> list[str]:
    errors = []
    if text.lstrip().startswith(("{", "[")):
        errors.append("director product is JSON, not Markdown")
    if len(text) < 900:
        errors.append(f"director product is too thin ({len(text)} chars; minimum 900)")
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    for quadrant in QUADRANT_DESCRIPTIONS:
        if quadrant not in text:
            errors.append(f"missing knowledge quadrant: {quadrant}")
    for gap_id in expected_gap_ids:
        if f"`{gap_id}`" not in text:
            errors.append(f"missing gap dossier or closure record: {gap_id}")
    if "not proof" not in text.lower():
        errors.append("missing explicit absence-of-evidence / novelty boundary")
    if "does not self-bet" not in text.lower():
        errors.append("missing no-self-bet decision boundary")
    if re.search(r"<[A-Za-z][^>\n]{0,120}>", text):
        errors.append("unresolved placeholder marker in Markdown")
    return errors
