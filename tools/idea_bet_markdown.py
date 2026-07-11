"""Director-facing Markdown renderer for the /idea-bet decision surface.

The canonical machine evidence stays under evidence/<STAGE>/*.artifact.json.
This file writes only the human review page:

    director-review/ideas/idea-bet-menu.md

It is deliberately descriptive. It never records a selected idea and never writes
the vault/database.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .idea_quality_eval import build_quality_eval
from .scientific_investment_score import validate_assessments


IDEA_BET_REL = Path("director-review") / "ideas" / "idea-bet-menu.md"
MEMO_CONTRACT_VERSION = "idea-investment-memo/v1"
REQUIRED_HEADINGS = [
    "## Decision Snapshot",
    "## Portfolio Execution Map",
    "## Candidate Ideas",
    "## Cut Before Betting",
    "## Evidence And Quality",
    "## Next Actions",
    "## Technical Pointers",
]
REQUIRED_MEMO_LABELS = [
    "Research question",
    "Mechanism hypothesis",
    "Causal chain",
    "Difference from prior art",
    "Novelty status",
    "Why now",
    "Minimal falsification experiment",
    "Baselines",
    "Controls",
    "Success thresholds",
    "Failure thresholds",
    "Kill criteria",
    "Resource and data feasibility",
    "Main risks",
    "Execution order",
    "Scientific investment score",
    "Strongest rejection case",
]


def idea_bet_menu_path(run_dir) -> Path:
    return Path(run_dir) / IDEA_BET_REL


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _payload(path: Path) -> dict:
    payload = _read_json(path).get("payload")
    return payload if isinstance(payload, dict) else {}


def _stage_payload(run_path: Path, stage: str, filename: str) -> dict:
    return _payload(run_path / "evidence" / stage / filename)


def _stage_payloads(run_path: Path, stage: str, pattern: str) -> list[dict]:
    d = run_path / "evidence" / stage
    if not d.exists():
        return []
    return [_payload(p) for p in sorted(d.glob(pattern))]


def _task_payload(run_path: Path) -> dict:
    return _payload(run_path / "task_frame.artifact.json")


def _rel(run_path: Path, path: Path) -> str:
    try:
        return path.relative_to(run_path).as_posix()
    except ValueError:
        return str(path)


def _csv(values: list | tuple | None, *, limit: int = 6) -> str:
    vals = [str(v) for v in (values or []) if str(v).strip()]
    if not vals:
        return "none recorded"
    shown = vals[:limit]
    suffix = f", +{len(vals) - limit} more" if len(vals) > limit else ""
    return ", ".join(f"`{v}`" for v in shown) + suffix


def _one_line(value: object, *, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _table_cell(value: object, *, limit: int = 150) -> str:
    return _one_line(value, limit=limit).replace("|", "\\|") or "not recorded"


def _by_id(rows: list[dict], key: str = "idea_id") -> dict[str, dict]:
    return {str(r.get(key)): r for r in rows if isinstance(r, dict) and r.get(key)}


def _grounding_by_id(grounding: dict) -> dict[str, dict]:
    return _by_id([g for g in (grounding.get("ideas") or []) if isinstance(g, dict)])


def _bundle(run_path: Path, stem: str) -> dict:
    data = _read_json(run_path / "inbox" / f"{stem}.bundle.json")
    return data if isinstance(data, dict) else {}


def _rows(bundle: dict, key: str) -> list[dict]:
    return [row for row in (bundle.get(key) or []) if isinstance(row, dict)]


def _text(value: object, fallback: str) -> str:
    value = _one_line(value, limit=620)
    return value if value else fallback


def _values(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_one_line(item, limit=360) for item in value if _one_line(item, limit=360)]


def _plain_list(value: object, fallback: str) -> str:
    values = _values(value)
    return "; ".join(values) if values else fallback


def _resource_line(resources: object, feasibility: dict) -> str:
    resources = resources if isinstance(resources, dict) else {}
    parts = []
    for key in ("compute", "data", "time"):
        value = resources.get(key)
        if value in (None, ""):
            value = feasibility.get(key)
        parts.append(f"{key}={_one_line(value, limit=180) or 'not recorded'}")
    deps = _values(resources.get("dependencies"))
    if deps:
        parts.append("dependencies=" + "; ".join(deps))
    return "; ".join(parts)


def _risk_line(risks: object, caveats: object) -> str:
    out = []
    for risk in risks if isinstance(risks, list) else []:
        if isinstance(risk, dict):
            name = _one_line(risk.get("risk"), limit=220)
            mitigation = _one_line(risk.get("mitigation"), limit=240)
            if name:
                out.append(f"{name} (mitigation: {mitigation or 'not recorded'})")
        elif _one_line(risk):
            out.append(_one_line(risk, limit=300))
    if not out:
        out = _values(caveats)
    return "; ".join(out) if out else "No explicit risk register was recorded in this legacy run."


def _prior_art_line(rows: object) -> str:
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        ref = _one_line(row.get("ref"), limit=100) or "unresolved-ref"
        title = _one_line(row.get("title"), limit=180)
        relation = _one_line(row.get("relationship"), limit=100)
        difference = _one_line(row.get("difference"), limit=260)
        label = f"`{ref}`"
        if title:
            label += f" {title}"
        details = "; ".join(x for x in (relation, difference) if x)
        out.append(f"{label} ({details})" if details else label)
    return "; ".join(out) if out else "No closest-work row was recorded within this run's coverage."


def _stage_lines(stages: object) -> list[str]:
    rows = [stage for stage in stages if isinstance(stage, dict)] if isinstance(stages, list) else []
    if not rows:
        return ["- No staged ladder was recorded; begin with the minimum direct falsification test."]
    lines = []
    for idx, stage in enumerate(rows, start=1):
        sid = _one_line(stage.get("stage_id"), limit=40) or f"S{idx}"
        kind = _one_line(stage.get("stage_type"), limit=80) or "direct"
        name = _one_line(stage.get("name"), limit=200) or "Unnamed stage"
        lines.extend([
            f"{idx}. **{name}** (`{kind}`, `{sid}`)",
            f"   - Purpose: {_text(stage.get('purpose'), 'not recorded')}",
            f"   - Setup: {_text(stage.get('setup'), 'not recorded')}",
            f"   - Baselines: {_plain_list(stage.get('baselines'), 'not recorded')}",
            f"   - Controls: {_plain_list(stage.get('controls'), 'not recorded')}",
            f"   - Advance when: {_text(stage.get('success_threshold'), 'not recorded')}",
            f"   - Fail when: {_text(stage.get('failure_threshold'), 'not recorded')}",
            f"   - Kill when: {_text(stage.get('kill_criteria'), 'not recorded')}",
            f"   - Depends on: {_plain_list(stage.get('depends_on'), 'none')}",
        ])
    return lines


def _strict_memo_contract(*bundles: dict) -> bool:
    return any(b.get("memo_contract_version") == MEMO_CONTRACT_VERSION for b in bundles)


def _memo_contract_errors(run_path: Path, ranked: list[dict]) -> list[str]:
    proposal = _bundle(run_path, "IDEATE")
    ranking = _bundle(run_path, "RANKING")
    collision = _bundle(run_path, "COLLISION")
    experiment = _bundle(run_path, "EXPERIMENT")
    if not _strict_memo_contract(proposal, ranking, collision, experiment):
        return []

    errors = []
    for name, bundle in (("IDEATE", proposal), ("RANKING", ranking),
                         ("COLLISION", collision), ("EXPERIMENT", experiment)):
        if bundle.get("memo_contract_version") != MEMO_CONTRACT_VERSION:
            errors.append(f"{name}.bundle.json missing memo_contract_version={MEMO_CONTRACT_VERSION}")

    ideas = _by_id(_rows(proposal, "ideas") + _rows(ranking, "evolved"))
    assessments = _by_id(_rows(ranking, "investment_assessments"))
    findings = _by_id(_rows(collision, "findings"))
    sketches = _by_id(_rows(experiment, "sketches"), "idea_ref")
    for row in ranked:
        iid = str(row.get("idea_id"))
        idea = ideas.get(iid) or {}
        for field in ("research_question", "mechanism_hypothesis", "intended_contribution", "why_now"):
            if not str(idea.get(field) or "").strip():
                errors.append(f"{iid}: proposal missing {field}")
        if len(_values(idea.get("causal_chain"))) < 2:
            errors.append(f"{iid}: proposal causal_chain needs at least two links")
        assessment = assessments.get(iid) or {}
        for field in ("investment_case", "rank_rationale"):
            if not str(assessment.get(field) or "").strip():
                errors.append(f"{iid}: ranker missing {field}")
        finding = findings.get(iid) or {}
        if not str(finding.get("difference_from_prior_art") or "").strip():
            errors.append(f"{iid}: collision checker missing difference_from_prior_art")
        sketch = sketches.get(iid) or {}
        for field in ("experiment", "falsifier"):
            if not str(sketch.get(field) or "").strip():
                errors.append(f"{iid}: planner missing {field}")
        for field in ("baselines", "controls", "metrics", "success_thresholds",
                      "failure_thresholds", "kill_criteria", "main_risks",
                      "execution_order", "stages"):
            if field == "main_risks":
                if not isinstance(sketch.get(field), list) or not sketch.get(field):
                    errors.append(f"{iid}: planner main_risks must be a non-empty list")
            elif not _values(sketch.get(field)):
                errors.append(f"{iid}: planner {field} must be non-empty")
        resources = sketch.get("resource_feasibility")
        if not isinstance(resources, dict) or any(
                not str(resources.get(field) or "").strip() for field in ("compute", "data", "time")):
            errors.append(f"{iid}: planner resource_feasibility needs compute, data, and time")
    errors.extend(validate_assessments(assessments.values(), [str(row.get("idea_id")) for row in ranked]))
    return errors


def _quality_payload(run_path: Path, ranked_ideas: list[dict]) -> dict:
    existing = _stage_payload(run_path, "REPORT", "idea-quality-eval.artifact.json")
    if existing:
        return existing
    if not ranked_ideas:
        return {}

    mechanism_graph = _stage_payload(run_path, "DISCOVER", "mechanism-graph.artifact.json") or None
    mappings = _stage_payloads(run_path, "DISCOVER", "mechanism-mapping-*.artifact.json") or None
    contradiction = _stage_payload(run_path, "DISCOVER", "contradiction-report.artifact.json") or None
    sketches = _stage_payloads(run_path, "IDEATE", "experiment-sketch-*.artifact.json") or None
    collision = _stage_payload(run_path, "IDEATE", "novelty-collision-verdict.artifact.json") or None
    grounding = _stage_payload(run_path, "IDEATE", "idea-grounding-report.artifact.json")
    grounding_scores = {
        str(g.get("idea_id")): float(g.get("soundness"))
        for g in (grounding.get("ideas") or [])
        if isinstance(g, dict)
        and g.get("idea_id") is not None
        and isinstance(g.get("soundness"), (int, float))
    } or None
    ideas = [
        {"idea_id": str(i.get("idea_id")), "evidence_ref": list(i.get("evidence_ref") or [])}
        for i in ranked_ideas
        if i.get("idea_id")
    ]
    try:
        return build_quality_eval(
            "QE-preview",
            ideas,
            mechanism_graph=mechanism_graph,
            mechanism_mappings=mappings,
            contradiction=contradiction,
            experiment_sketches=sketches,
            collision_verdict=collision,
            grounding_by_id=grounding_scores,
        )
    except (TypeError, ValueError):
        return {}


def build_idea_bet_menu_markdown(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    task = _task_payload(run_path)
    run_id = task.get("task_id") or run_path.name
    mode = task.get("mode") or "unknown"
    project = task.get("project") or "unregistered"
    request = task.get("request_text") or ""
    north_star = task.get("north_star") or {}
    statement = north_star.get("statement") or request

    backlog = _stage_payload(run_path, "IDEATE", "idea-backlog.artifact.json")
    ranked = [i for i in (backlog.get("ranked_ideas") or []) if isinstance(i, dict)]
    if not ranked:
        raise ValueError("idea-bet Markdown BLOCK: idea-backlog has no ranked_ideas")

    contract_errors = _memo_contract_errors(run_path, ranked)
    if contract_errors:
        raise ValueError(f"idea-bet investment memo BLOCK: {contract_errors}")

    proposal_bundle = _bundle(run_path, "IDEATE")
    ranking_bundle = _bundle(run_path, "RANKING")
    collision_bundle = _bundle(run_path, "COLLISION")
    experiment_bundle = _bundle(run_path, "EXPERIMENT")
    proposal_by = _by_id(_rows(proposal_bundle, "ideas") + _rows(ranking_bundle, "evolved"))
    assessment_by = _by_id(_rows(ranking_bundle, "investment_assessments"))
    raw_collision_by = _by_id(_rows(collision_bundle, "findings"))
    raw_sketch_by = _by_id(_rows(experiment_bundle, "sketches"), "idea_ref")
    hypotheses = _stage_payload(run_path, "IDEATE", "hypothesis-set.artifact.json")
    hypothesis_by = _by_id(hypotheses.get("hypotheses") or [], "hypothesis_id")

    tournament = _stage_payload(run_path, "IDEATE", "idea-tournament.artifact.json")
    elo = _by_id(tournament.get("ratings") or [])
    collision = _stage_payload(run_path, "IDEATE", "novelty-collision-verdict.artifact.json")
    collision_by = _by_id(collision.get("ideas") or [])
    grounding = _stage_payload(run_path, "IDEATE", "idea-grounding-report.artifact.json")
    grounding_by = _grounding_by_id(grounding)
    sketches = _by_id(_stage_payloads(run_path, "IDEATE", "experiment-sketch-*.artifact.json"), "idea_ref")
    lineage = _stage_payload(run_path, "IDEATE", "idea-lineage.artifact.json")
    lineage_by = _by_id(lineage.get("lineages") or [])
    quality = _quality_payload(run_path, ranked)
    quality_by = _by_id(quality.get("per_idea") or [])
    cut = [c for c in (collision.get("ideas") or []) if isinstance(c, dict) and c.get("cut")]
    unverified = [c for c in (collision.get("ideas") or []) if c.get("verdict") == "UNVERIFIED"]

    top = ranked[0]
    top_investment = top.get("scientific_investment") or {}
    retrieval_grounded = collision.get("retrieval_grounded")
    if retrieval_grounded is True:
        novelty_line = "prior-art collision retrieval was grounded for this run"
    elif retrieval_grounded is False:
        novelty_line = "prior-art collision retrieval was NOT grounded; treat novelty as unverified"
    else:
        novelty_line = "no prior-art collision verdict was found"

    lines: list[str] = [
        "---",
        f"run_id: {run_id}",
        f"project: {project}",
        f"mode: {mode}",
        f"generated_at: {generated_at or ''}",
        "primary_human_action: /idea-bet",
        "records_selection: false",
        "json_evidence_root: ../../evidence",
        "---",
        "",
        f"# Idea Bet Menu - {run_id}",
        "",
        "## Decision Snapshot",
        "",
        f"- Project: `{project}`; mode: `{mode}`.",
        f"- North star: {_one_line(statement, limit=420)}",
        f"- Candidate menu: {len(ranked)} idea(s); cut before betting: {len(cut)}; unverified novelty flags: {len(unverified)}.",
        (
            f"- Current top scientific-investment rank: `{top.get('idea_id')}` with score "
            f"`{top_investment.get('score')}` ({top_investment.get('confidence')})."
            if top_investment else
            f"- Legacy feasibility-only rank: `{top.get('idea_id')}` with score "
            f"`{(top.get('feasibility') or {}).get('score')}`; rerun under the strict memo contract "
            "before treating this as a scientific priority."
        ),
        f"- Novelty status: {novelty_line}.",
        "- This page is a decision aid. It does not choose, approve, or promote any idea.",
        "- Standing option: `PIVOT` means bet on none of these and re-scope.",
        "",
        "## Portfolio Execution Map",
        "",
        "This is a scan-first dependency view, not a machine-selected bet.",
        "",
        "| Rank | Idea | First decisive stage | Primary kill criterion | Recovery / next branch |",
        "|---:|---|---|---|---|",
    ]

    for idea in ranked:
        iid = str(idea.get("idea_id") or "")
        proposal = proposal_by.get(iid) or idea
        sketch = raw_sketch_by.get(iid) or {}
        stages = [row for row in (sketch.get("stages") or []) if isinstance(row, dict)]
        first_stage = stages[0] if stages else {}
        first = first_stage.get("name") or sketch.get("experiment") or "not recorded"
        kill = (sketch.get("kill_criteria") or [first_stage.get("kill_criteria") or "not recorded"])[0]
        branch = sketch.get("next_branch") or "advance only after the declared threshold passes"
        lines.append(
            f"| {idea.get('rank')} | `{iid}` {_table_cell(proposal.get('summary'), limit=70)} "
            f"| {_table_cell(first)} | {_table_cell(kill)} | {_table_cell(branch)} |"
        )

    lines.extend([
        "",
        "## Candidate Ideas",
        "",
    ])

    for idea in ranked:
        iid = str(idea.get("idea_id"))
        proposal = proposal_by.get(iid) or idea
        assessment = assessment_by.get(iid) or {}
        feas = idea.get("feasibility") or {}
        investment = idea.get("scientific_investment") or {}
        erow = elo.get(iid) or {}
        crow = collision_by.get(iid) or {}
        raw_collision = raw_collision_by.get(iid) or {}
        grow = grounding_by.get(iid) or {}
        qrow = quality_by.get(iid) or {}
        sketch = dict(raw_sketch_by.get(iid) or {})
        sketch.update(sketches.get(iid) or {})
        lin = lineage_by.get(iid) or {}
        hyp = hypothesis_by.get(str(proposal.get("from_hypothesis_ref") or "")) or {}

        summary = _text(proposal.get("summary") or idea.get("summary"), "Untitled proposal")
        research_question = _text(
            proposal.get("research_question"),
            f"Can the central claim in '{summary}' survive a controlled test?",
        )
        mechanism = _text(
            proposal.get("mechanism_hypothesis") or hyp.get("statement"),
            "The mechanism was not separately recorded in this legacy worker bundle.",
        )
        causal_chain = _values(proposal.get("causal_chain"))
        if not causal_chain:
            causal_chain = [
                _text(hyp.get("statement"), "proposed intervention changes an unknown mediator"),
                _text(hyp.get("falsifiable_prediction"), "the mediator should change the target metric"),
            ]
        intended = _text(
            proposal.get("intended_contribution"),
            "No separate contribution statement was recorded; inspect the prior-art delta before betting.",
        )
        why_now = _text(
            proposal.get("why_now"),
            "The timing case was not separately recorded in this legacy run.",
        )
        investment_case = _text(
            assessment.get("investment_case"),
            "The independent ranker did not record a prose investment case in this legacy run.",
        )
        rank_rationale = _text(
            assessment.get("rank_rationale"),
            "See feasibility and tournament signals below.",
        )
        novelty_status = str(crow.get("verdict") or raw_collision.get("verdict") or "UNVERIFIED")
        prior_delta = _text(
            raw_collision.get("difference_from_prior_art") or proposal.get("intended_contribution")
            or crow.get("reason"),
            "No explicit prior-art delta was recorded; novelty remains unresolved.",
        )
        closest = raw_collision.get("closest_prior_art") or raw_collision.get("colliding_papers") or []
        baselines = sketch.get("baselines") or []
        if not baselines and sketch.get("controls"):
            baselines = ["Comparator embedded in the controls; separate it before preregistration."]
        controls = sketch.get("controls") or ["No explicit control set recorded in this legacy run."]
        success = sketch.get("success_thresholds") or sketch.get("observable_signals") or []
        failure = sketch.get("failure_thresholds") or ([sketch.get("falsifier")] if sketch.get("falsifier") else [])
        kill = sketch.get("kill_criteria") or failure
        execution = sketch.get("execution_order") or [
            "reproduce the strongest baseline",
            "run the minimum falsification experiment",
            "advance only if the preregistered threshold clears",
        ]
        caveats = idea.get("caveats") or []

        lines.extend([
            f"### Rank {idea.get('rank')} - {iid}",
            "",
            summary,
            "",
            "#### Research bet memo",
            "",
            f"- **Research question:** {research_question}",
            f"- **Mechanism hypothesis:** {mechanism}",
            f"- **Causal chain:** {' -> '.join(causal_chain)}",
            f"- **Intended contribution:** {intended}",
            f"- **Why now:** {why_now}",
            f"- **Independent investment case:** {investment_case}",
            f"- **Rank rationale:** {rank_rationale}",
            f"- **Scientific investment score:** {_text(investment.get('score'), 'legacy run; not computed')}; "
            f"confidence `{investment.get('confidence', 'legacy')}`.",
            f"- **Strongest rejection case:** {_text(investment.get('strongest_rejection_case') or assessment.get('strongest_rejection_case'), 'not recorded')}",
            "",
            "#### Prior art and novelty",
            "",
            f"- **Novelty status:** `{novelty_status}`; {_text(crow.get('reason'), 'coverage caveat not recorded')}",
            f"- **Difference from prior art:** {prior_delta}",
            f"- **Closest prior art:** {_prior_art_line(closest)}",
            "",
            "#### Minimal experiment sketch and falsification plan",
            "",
            f"- **Minimal falsification experiment:** {_text(sketch.get('experiment'), 'No planner sketch was recorded; do not bet until one exists.')}",
            f"- **Baselines:** {_plain_list(baselines, 'not recorded')}",
            f"- **Controls:** {_plain_list(controls, 'not recorded')}",
            f"- **Metrics:** {_plain_list(sketch.get('metrics'), 'not recorded')}",
            f"- **Success thresholds:** {_plain_list(success, 'not recorded')}",
            f"- **Failure thresholds:** {_plain_list(failure, 'not recorded')}",
            f"- **Falsifier:** {_text(sketch.get('falsifier'), 'not recorded')}",
            f"- **Kill criteria:** {_plain_list(kill, 'not recorded')}",
            "",
            "#### Staged experiment ladder",
            "",
        ])
        if not sketch:
            lines.append(
                "- Minimal experiment sketch: not present; dispatch experiment-planner before betting."
            )
        lines.extend(_stage_lines(sketch.get("stages")))
        lines.extend([
            "",
            "#### Feasibility, risks, and sequence",
            "",
            f"- **Resource and data feasibility:** {_resource_line(sketch.get('resource_feasibility'), feas)}",
            f"- **Main risks:** {_risk_line(sketch.get('main_risks'), caveats)}",
            f"- **Execution order:** {_plain_list(execution, 'not recorded')}",
        ])
        if sketch.get("next_branch"):
            lines.append(f"- **Recovery branch:** {_one_line(sketch.get('next_branch'), limit=420)}")

        signal_bits = [f"feasibility={feas.get('score')}"]
        if investment:
            signal_bits.extend(
                f"{key}={investment.get(key)}" for key in (
                    "scientific_merit", "tournament_signal", "evidence_grounding",
                    "falsification_readiness"
                )
            )
        if erow:
            signal_bits.append(f"Elo rank={erow.get('rank')} (Elo {erow.get('elo')})")
        if grow:
            signal_bits.append(f"grounding={grow.get('soundness')}")
        if qrow:
            scores = qrow.get("scores") or {}
            signal_bits.extend(f"{key}={scores.get(key)}" for key in (
                "depth", "breadth", "refutation", "falsifiability", "novelty"
            ) if key in scores)
        lines.append(f"- **Decision signals:** {'; '.join(signal_bits)}")
        lines.append(f"- **Evidence refs:** {_csv(idea.get('evidence_ref'), limit=8)}")
        if lin:
            lin_bits = []
            for key in ("problem_ref", "mechanism_graph_ref", "hypothesis_ref", "experiment_sketch_ref"):
                if lin.get(key):
                    lin_bits.append(f"{key} `{lin.get(key)}`")
            if lin.get("gap_refs"):
                lin_bits.append("gap_refs " + _csv(lin.get("gap_refs"), limit=5))
            if lin_bits:
                lines.append("- **Lineage:** " + "; ".join(lin_bits))
        for caveat in caveats[:5]:
            lines.append(f"- **Caveat:** {_one_line(caveat, limit=360)}")
        lines.append("")

    lines.extend([
        "## Cut Before Betting",
        "",
    ])
    if cut:
        for row in cut:
            papers = row.get("colliding_papers") or []
            paper_refs = [p.get("ref") for p in papers if isinstance(p, dict) and p.get("ref")]
            lines.append(
                f"- `{row.get('idea_id')}` was cut as `{row.get('verdict')}`: "
                f"{_one_line(row.get('reason'), limit=460)} Colliders: {_csv(paper_refs, limit=4)}."
            )
    else:
        lines.append("- No idea was cut by an existence-verified prior-art collision.")

    lines.extend([
        "",
        "## Evidence And Quality",
        "",
        f"- Backlog evidence: `evidence/IDEATE/idea-backlog.artifact.json`.",
        f"- Tournament evidence: `evidence/IDEATE/idea-tournament.artifact.json` ({len(tournament.get('matchups') or [])} matchup(s)).",
        f"- Collision evidence: `evidence/IDEATE/novelty-collision-verdict.artifact.json`; retrieval_grounded=`{retrieval_grounded}`.",
        f"- Grounding evidence: `evidence/IDEATE/idea-grounding-report.artifact.json`.",
        f"- Quality source: {'REPORT artifact' if (run_path / 'evidence' / 'REPORT' / 'idea-quality-eval.artifact.json').is_file() else 'pre-bet preview computed from typed artifacts'}.",
        "- Strict runs are ordered by the transparent scientific-investment composite. Feasibility is only one component, and the rank is not a research bet.",
        "",
        "## Next Actions",
        "",
        "1. Choose one menu option through `/idea-bet`, or choose `PIVOT`.",
        "2. If novelty is unverified, run or re-run with `operate pre-search` plus the novelty-collision worker before committing to the direction.",
        "3. After a human bet, send the chosen idea into `full_rigor_minimal` or the relevant experiment-design mode for preregistered design.",
        "4. Promote nothing to the database until `/promote-to-vault` re-derives a frozen, citable result.",
        "",
        "## Technical Pointers",
        "",
        f"- This Markdown page lives at `{IDEA_BET_REL.as_posix()}`.",
        "- JSON evidence remains under `evidence/`; this page is the human reading layer.",
        "- The run's pinned request is in `task_frame.artifact.json` and the gate trace is in `ledger.jsonl`.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _candidate_block(text: str, idea_id: str) -> str:
    match = re.search(rf"^### Rank \d+ - {re.escape(idea_id)}\s*$", text, flags=re.MULTILINE)
    if not match:
        return ""
    next_candidate = re.search(r"^### Rank \d+ - ", text[match.end():], flags=re.MULTILINE)
    cut_heading = re.search(r"^## Cut Before Betting\s*$", text[match.end():], flags=re.MULTILINE)
    ends = [m.start() for m in (next_candidate, cut_heading) if m]
    end = match.end() + min(ends) if ends else len(text)
    return text[match.start():end]


def lint_idea_bet_menu(run_dir) -> list[str]:
    run_path = Path(run_dir)
    out = idea_bet_menu_path(run_path)
    errors: list[str] = []
    if not out.is_file():
        return [f"missing {IDEA_BET_REL.as_posix()}"]
    text = out.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    backlog = _stage_payload(run_path, "IDEATE", "idea-backlog.artifact.json")
    idea_ids = [str(i.get("idea_id")) for i in (backlog.get("ranked_ideas") or []) if i.get("idea_id")]
    for iid in idea_ids:
        block = _candidate_block(text, iid)
        if not block:
            errors.append(f"missing idea in Markdown menu: {iid}")
            continue
        for label in REQUIRED_MEMO_LABELS:
            if f"**{label}:**" not in block:
                errors.append(f"{iid}: missing investment memo field: {label}")
    errors.extend(_memo_contract_errors(run_path, backlog.get("ranked_ideas") or []))
    if "records_selection: false" not in text:
        errors.append("Markdown menu must state records_selection: false")
    if len(text.strip()) < 700:
        errors.append("idea-bet Markdown menu is too short to be decision-useful")
    return errors


def write_idea_bet_menu(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    out = idea_bet_menu_path(run_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_idea_bet_menu_markdown(run_path, generated_at=generated_at), encoding="utf-8")
    errors = lint_idea_bet_menu(run_path)
    if errors:
        raise ValueError(f"idea-bet Markdown BLOCK: {errors}")
    return str(out)
