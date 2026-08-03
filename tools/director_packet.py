"""Director-facing Markdown packet renderer for operated runs.

JSON artifacts remain the canonical machine evidence under evidence/<STAGE>/.
This module adds the human review surface: director-review/00-REVIEW-PACKET.md.
It never writes the vault/database.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from .idea_bet_markdown import idea_bet_menu_path, write_idea_bet_menu
from .full_rigor_markdown import (
    experiment_plan_path,
    result_readiness_path,
    write_full_rigor_markdown,
)
from .runstore import classify_status, read_manifest
from .venue_readiness_markdown import venue_readiness_path, write_venue_readiness_markdown
from .manuscript_security import ManuscriptPathViolation, validate_run_owned_path


PACKET_REL = Path("director-review") / "00-REVIEW-PACKET.md"
MANUSCRIPT_OVERVIEW_REL = Path("director-review") / "manuscript" / "00-OVERVIEW.md"
MANUSCRIPT_REVIEW_REPORT_REL = Path("director-review") / "manuscript" / "reviewer-report.md"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_SECRET_REF_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization|bearer|password|secret|sk-[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
REQUIRED_HEADINGS = [
    "## What Happened",
    "## What The Director Can Decide Now",
    "## Trust Boundary",
    "## Key Findings",
    "## Gate Trace",
    "## Evidence Index",
    "## Open Questions And Next Run",
]


def packet_path(run_dir) -> Path:
    return Path(run_dir) / PACKET_REL


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _payload(artifact: dict) -> dict:
    payload = artifact.get("payload")
    return payload if isinstance(payload, dict) else {}


def _task_frame(run_dir: Path) -> dict:
    return _read_json(run_dir / "task_frame.artifact.json")


def _artifact_files(run_dir: Path) -> list[Path]:
    evidence = run_dir / "evidence"
    if not evidence.exists():
        return []
    return sorted(p for p in evidence.glob("*/*.artifact.json") if p.is_file())


def _safe_director_report(run_dir: Path, relative_path: Path) -> Path | None:
    """Return a run-owned director report only when its path has no escape route.

    The top-level packet is a navigation surface, never a path authority.  In
    particular, a symlink/junction dropped under director-review must not turn
    into a link to another run, the database, or a secret-bearing location.
    """

    candidate = run_dir / relative_path
    try:
        checked = validate_run_owned_path(
            candidate,
            run_root=run_dir,
            purpose="read",
            owned_output_roots=(run_dir / "director-review",),
        )
    except (ManuscriptPathViolation, OSError, ValueError):
        return None
    if checked.get("existing_kind") != "file" or not candidate.is_file():
        return None
    return candidate


def _safe_evidence_ref(value: object) -> str | None:
    """Keep cross-run identities display-only and reject unsafe/redacted refs."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in normalized.split("/")
        or "\x00" in normalized
        or _SECRET_REF_RE.search(normalized)
    ):
        return None
    return normalized


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _verified_manuscript_review(
    rows: list[tuple[Path, dict]], *, expected_review_run_id: str
) -> dict | None:
    """Extract a separately identified review verdict for navigation only.

    This deliberately checks a compact subset of the closed verdict contract.
    Schema validation already occurs when normal artifacts are persisted; the
    second check makes hand-dropped/incomplete JSON fail closed before a
    director packet presents it as independent review evidence.
    """

    for _path, artifact in rows:
        if artifact.get("artifact_type") != "manuscript_review_verdict":
            continue
        payload = _payload(artifact)
        reviewer = payload.get("reviewer_identity")
        frozen = payload.get("frozen_inputs")
        receipt = payload.get("blind_read_receipt")
        if not (
            payload.get("review_run_id") == expected_review_run_id
            and isinstance(reviewer, dict)
            and reviewer.get("independent_from_authoring") is True
            and isinstance(frozen, dict)
            and isinstance(receipt, dict)
            and _safe_evidence_ref(frozen.get("manuscript_ref"))
            and _is_sha256(frozen.get("manuscript_sha256"))
            and _is_sha256(payload.get("verdict_sha256"))
            and _is_sha256(receipt.get("scheduler_authorization_sha256"))
        ):
            continue
        return {
            "manuscript_ref": _safe_evidence_ref(frozen["manuscript_ref"]),
            "manuscript_sha256": frozen["manuscript_sha256"].lower(),
            "verdict_sha256": payload["verdict_sha256"].lower(),
            "receipt_sha256": receipt["scheduler_authorization_sha256"].lower(),
        }
    return None


def _artifact_summary(path: Path, artifact: dict) -> str:
    payload = _payload(artifact)
    for key in ("summary", "research_question", "verdict", "title", "query", "topic"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:180]
    if "ranked_ideas" in payload:
        return f"{len(payload.get('ranked_ideas') or [])} ranked ideas"
    if "conditions" in payload:
        return f"{len(payload.get('conditions') or [])} experiment conditions"
    if "claims" in payload:
        return f"{len(payload.get('claims') or [])} claims"
    return artifact.get("artifact_type") or path.stem


def _maybe_write_idea_bet_menu(run_dir: Path, mode: str, generated_at: Optional[str]) -> None:
    """Regenerate the Markdown /idea-bet menu when the run has enough IDEATE evidence.

    This is an idempotent sidecar write into director-review/. It never writes evidence or the vault.
    Packet generation must not fail just because an old/incomplete run lacks optional deep artifacts.
    """
    if mode not in {"new_direction", "deep_ideation"}:
        return
    if not (run_dir / "evidence" / "IDEATE" / "idea-backlog.artifact.json").is_file():
        return
    try:
        write_idea_bet_menu(run_dir, generated_at=generated_at)
    except ValueError:
        return


def _maybe_write_venue_readiness_packet(run_dir: Path, mode: str, generated_at: Optional[str]) -> None:
    """Regenerate the venue Markdown packet for current or old venue runs when evidence exists."""
    if mode != "venue_readiness":
        return
    verify_dir = run_dir / "evidence" / "VERIFY"
    required = [
        verify_dir / "venue-profile.artifact.json",
        verify_dir / "venue-readiness-verdict.artifact.json",
    ]
    if not all(p.is_file() for p in required):
        return
    if not any(verify_dir.glob("review-*.artifact.json")):
        return
    try:
        write_venue_readiness_markdown(run_dir, generated_at=generated_at)
    except ValueError:
        return


def _maybe_write_full_rigor_experiment_packet(run_dir: Path, mode: str, generated_at: Optional[str]) -> None:
    """Regenerate the full-rigor experiment Markdown sidecars when design evidence exists."""
    if mode != "full_rigor_minimal":
        return
    design_dir = run_dir / "evidence" / "DESIGN"
    required = [
        design_dir / "experiment-matrix.artifact.json",
        design_dir / "protocol-spec.artifact.json",
        design_dir / "preregistration.artifact.json",
    ]
    if not all(p.is_file() for p in required):
        return
    try:
        write_full_rigor_markdown(run_dir, generated_at=generated_at)
    except ValueError:
        return


def _stage_of(path: Path, run_dir: Path) -> str:
    try:
        rel = path.relative_to(run_dir)
    except ValueError:
        return "UNKNOWN"
    return rel.parts[1] if len(rel.parts) > 2 and rel.parts[0] == "evidence" else "UNKNOWN"


def _primary_human_action(mode: str, artifacts: Iterable[dict]) -> str:
    if mode == "manuscript_authoring":
        return "review the authoring overview; independent manuscript_review remains a separate operated run"
    if mode == "manuscript_review":
        return "review the separate verdict and decide whether to revise; no automatic integration or submission"
    if mode in {"new_direction", "deep_ideation", "ideate_ring"}:
        return "/idea-bet"
    if mode == "venue_readiness":
        return "/venue-pick or /venue-decide"
    if mode == "gap_breadth":
        return "review gap scan; start new_direction only if the director wants to bet"
    if mode in {"read_paper_deep", "ingest_paper"}:
        return "/promote-to-vault after director review, if appropriate"
    if mode == "full_rigor_minimal":
        for artifact in artifacts:
            payload = _payload(artifact)
            if payload.get("verdict") == "BLOCK" or artifact.get("status") == "blocked":
                return "resolve BLOCK before execution or promotion"
        return "review execution truth boundary before any /promote-to-vault"
    return "review packet; no automatic human gate selected"


def _mode_findings(mode: str, rows: list[tuple[Path, dict]], run_dir: Path) -> list[str]:
    findings: list[str] = []
    by_name = {p.name: art for p, art in rows}
    completed_stages = {
        str(row.get("stage") or "")
        for row in read_manifest(run_dir).get("completed_work", [])
    }

    if mode == "manuscript_authoring":
        overview = _safe_director_report(run_dir, MANUSCRIPT_OVERVIEW_REL)
        if overview is not None:
            findings.append(
                "Primary manuscript product: "
                "[00-OVERVIEW.md](./manuscript/00-OVERVIEW.md)."
            )
        else:
            findings.append(
                "No verified manuscript overview is available yet; inspect the run evidence and do not infer a PDF or submission state."
            )
        findings.append(
            "No independently operated `manuscript_review` product is linked; any authoring self-audit remains internal."
        )

    if mode == "manuscript_review":
        run_id = str(read_manifest(run_dir).get("run_id") or run_dir.name)
        verdict = _verified_manuscript_review(rows, expected_review_run_id=run_id)
        reviewer_report = _safe_director_report(run_dir, MANUSCRIPT_REVIEW_REPORT_REL)
        if verdict is not None and reviewer_report is not None:
            findings.extend(
                [
                    "Independent review product: [reviewer-report.md](./manuscript/reviewer-report.md).",
                    f"It is bound to review run `{run_id}`, manuscript `{verdict['manuscript_ref']}`, "
                    f"manuscript SHA-256 `{verdict['manuscript_sha256']}`, "
                    f"verdict SHA-256 `{verdict['verdict_sha256']}`, and blind receipt SHA-256 `{verdict['receipt_sha256']}`.",
                ]
            )
        else:
            findings.append(
                "No verified independent manuscript-review verdict is available; the readable report, if any, is not presented as independent evidence."
            )

    if "idea-backlog.artifact.json" in by_name:
        ideas = _payload(by_name["idea-backlog.artifact.json"]).get("ranked_ideas") or []
        if ideas:
            top = ideas[0]
            findings.append(
                f"Top ranked idea is `{top.get('idea_id')}`: {top.get('summary', '')}"
            )
            findings.append(f"Idea menu contains {len(ideas)} ranked options.")
        idea_menu = idea_bet_menu_path(run_dir)
        if idea_menu.is_file():
            findings.append(f"Director-facing idea bet menu: `{idea_menu.relative_to(run_dir).as_posix()}`")

    if "idea-bet.adr.json" in by_name:
        adr = by_name["idea-bet.adr.json"]
        chosen = adr.get("chosen_option") or _payload(adr).get("chosen_option")
        if chosen:
            findings.append(f"Recorded director bet: {chosen}")

    if "experiment-matrix.artifact.json" in by_name:
        payload = _payload(by_name["experiment-matrix.artifact.json"])
        rq = payload.get("research_question")
        if rq:
            findings.append(f"Experiment question: {rq}")
        conds = payload.get("conditions") or []
        if conds:
            findings.append(
                "Experiment arms: "
                + ", ".join(str(c.get("id")) for c in conds if isinstance(c, dict))
            )

    if "preflight-report.artifact.json" in by_name:
        payload = _payload(by_name["preflight-report.artifact.json"])
        verdict = payload.get("verdict")
        violations = payload.get("violations") or []
        if verdict:
            findings.append(
                f"Preflight verdict is `{verdict}`"
                + (f": {'; '.join(violations)}" if violations else ".")
            )

    if mode == "full_rigor_minimal":
        experiment_plan = experiment_plan_path(run_dir)
        if experiment_plan.is_file():
            rel = experiment_plan.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing experiment plan: `{rel}`")
        result_brief = result_readiness_path(run_dir)
        if result_brief.is_file():
            rel = result_brief.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing result/readiness brief: `{rel}`")

    if "paper-note.artifact.json" in by_name:
        payload = _payload(by_name["paper-note.artifact.json"])
        title = payload.get("title")
        summary = payload.get("summary")
        if title:
            findings.append(f"Paper read: {title}")
        if summary:
            findings.append(summary)

    if "paper-reading-quality.artifact.json" in by_name:
        payload = _payload(by_name["paper-reading-quality.artifact.json"])
        verdict = payload.get("verdict")
        coverage = payload.get("coverage")
        anchoring = payload.get("anchoring")
        markdown_ready = payload.get("markdown_ready")
        promotion_ready = payload.get("promotion_ready")
        if verdict and mode != "read_paper_deep":
            findings.append(
                f"Paper reading quality audit: `{verdict}` "
                f"(coverage={coverage}, anchoring={anchoring}, markdown_ready={markdown_ready}, "
                f"promotion_ready={promotion_ready})."
            )
        attacks = payload.get("reviewer_attack_points") or []
        if attacks and mode != "read_paper_deep":
            findings.append("Reviewer attack points: " + "; ".join(str(x) for x in attacks[:3]))

    if "paper-markdown-card.artifact.json" in by_name:
        cards = sorted(
            p for p in (run_dir / "director-review" / "papers").glob("*.md")
            if not p.name.startswith("REPAIR-")
        )
        if cards and "REPORT" in completed_stages:
            rels = [p.relative_to(run_dir).as_posix() for p in cards[:3]]
            findings.append("Director-facing paper card: " + ", ".join(f"`{r}`" for r in rels))
        else:
            findings.append("Paper Markdown card artifact exists; inspect `paper-markdown-card.artifact.json`.")

    if mode == "venue_readiness":
        venue_packet = venue_readiness_path(run_dir)
        if venue_packet.is_file():
            rel = venue_packet.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing venue readiness packet: `{rel}`")
        profile = _payload(by_name.get("venue-profile.artifact.json") or {})
        verdict = _payload(by_name.get("venue-readiness-verdict.artifact.json") or {})
        if profile or verdict:
            unresolved = verdict.get("unresolved_reject_triggers") or []
            findings.append(
                f"Venue readiness summary: verdict `{verdict.get('verdict', 'UNKNOWN')}`, "
                f"venue `{profile.get('venue_id', 'unknown')}`, "
                f"unresolved triggers {len(unresolved)}."
            )
            if unresolved:
                findings.append(
                    "Unresolved trigger ids: "
                    + ", ".join(f"`{trigger}`" for trigger in unresolved[:6])
                )

    if mode == "evidence_deep":
        evidence_brief = run_dir / "director-review" / "evidence" / "evidence-deep-brief.md"
        if evidence_brief.is_file():
            rel = evidence_brief.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing evidence brief: `{rel}`")

    if mode == "gap_breadth":
        gap_scan = run_dir / "director-review" / "gaps" / "gap-scan.md"
        if gap_scan.is_file():
            rel = gap_scan.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing gap scan: `{rel}`")

        if "gap-classification.artifact.json" in by_name:
            payload = _payload(by_name["gap-classification.artifact.json"])
            gaps = payload.get("gaps") or []
            if gaps:
                findings.append(f"Gap scan classified {len(gaps)} research gap(s).")

        if "novelty-score.artifact.json" in by_name:
            payload = _payload(by_name["novelty-score.artifact.json"])
            scores = payload.get("scores") or []
            if scores:
                findings.append(f"Novelty scoring retained {len(scores)} gap(s); scores are advisory only.")

    if "source-quality-report.artifact.json" in by_name:
        payload = _payload(by_name["source-quality-report.artifact.json"])
        ranked = payload.get("ranked_sources") or []
        if ranked:
            top = ranked[0]
            findings.append(
                f"Top source by quality: `{top.get('source_ref')}` "
                f"({top.get('tier')}, rigor={top.get('rigor_score')})."
            )

    if "claim-list.artifact.json" in by_name:
        payload = _payload(by_name["claim-list.artifact.json"])
        claims = payload.get("claims") or []
        if claims:
            findings.append(f"Evidence panel extracted {len(claims)} anchored claims.")

    if "contradiction-report.artifact.json" in by_name:
        payload = _payload(by_name["contradiction-report.artifact.json"])
        conflicts = payload.get("conflicts") or []
        findings.append(f"Contradiction mining found {len(conflicts)} conflict(s).")

    if "landscape-map.artifact.json" in by_name:
        payload = _payload(by_name["landscape-map.artifact.json"])
        gaps = payload.get("coverage_gaps") or []
        if gaps:
            findings.append(f"Landscape map identifies {len(gaps)} coverage gap(s).")

    if "research-brief.artifact.json" in by_name:
        payload = _payload(by_name["research-brief.artifact.json"])
        topic = payload.get("topic")
        if topic:
            findings.append(f"Research brief topic: {topic}")
        bottom_line = payload.get("bottom_line")
        if bottom_line:
            findings.append(f"Research bottom line: {bottom_line}")
        f = payload.get("findings") or []
        if f:
            findings.append(f"Research brief includes {len(f)} findings.")

    if "research-markdown-brief.artifact.json" in by_name:
        brief = run_dir / "director-review" / "research" / "research-brief.md"
        if brief.is_file():
            rel = brief.relative_to(run_dir).as_posix()
            findings.append(f"Director-facing research brief: `{rel}`")

    if not findings:
        report = by_name.get("report-note.artifact.json")
        summary = _payload(report or {}).get("summary") if report else None
        if summary:
            findings.append(summary)
        elif "REPORT" in {str(row.get("stage") or "") for row in read_manifest(run_dir).get("completed_work", [])}:
            findings.append(f"{mode} completed REPORT evidence; inspect Evidence Index.")
        else:
            findings.append(f"{mode} has not completed REPORT; inspect Evidence Index and Gate Trace before acting.")

    return findings[:8]


def build_packet(run_dir, generated_at: Optional[str] = None) -> str:
    run_path = Path(run_dir)
    manifest = read_manifest(run_path)
    tf = _task_frame(run_path)
    payload = tf.get("payload", {})
    mode = payload.get("mode") or manifest.get("mode") or "unknown"
    _maybe_write_idea_bet_menu(run_path, mode, generated_at)
    _maybe_write_venue_readiness_packet(run_path, mode, generated_at)
    _maybe_write_full_rigor_experiment_packet(run_path, mode, generated_at)
    project = payload.get("project") or manifest.get("project")
    run_id = payload.get("task_id") or manifest.get("run_id") or run_path.name
    rows = [(p, _read_json(p)) for p in _artifact_files(run_path)]
    artifacts = [art for _, art in rows]
    stages = [c.get("stage") for c in manifest.get("completed_work", [])]
    action = _primary_human_action(mode, artifacts)
    findings = _mode_findings(mode, rows, run_path)
    status = classify_status(run_path)
    packet_status = "done" if status == "done" else manifest.get("status", status)

    # A paper card is intentionally written early so a blocked read can still
    # leave a readable working draft.  It becomes the compact human entry only
    # after the run itself has crossed the REPORT boundary; otherwise preserve
    # the ordinary packet's status and gate trace.
    if mode == "read_paper_deep" and status == "done":
        cards = sorted(
            p for p in (run_path / "director-review" / "papers").glob("*.md")
            if not p.name.startswith("REPAIR-")
        )
        if cards:
            card = cards[0]
            rel = card.relative_to(run_path).as_posix()
            title = next(
                (line[2:].strip() for line in card.read_text(encoding="utf-8").splitlines()
                 if line.startswith("# ")),
                "论文深读卡",
            )
            return "\n".join([
                "---",
                f"project: {project}",
                f"generated_at: {generated_at or ''}",
                "human_entry: true",
                "---",
                "",
                f"# {title}",
                "",
                "## What Happened",
                "",
                "这篇论文已经完成深读与人类可读性重写。后台保留逐主张、图表、方法、数字和复现证据；本页不展示机器审计过程。",
                "",
                "## What The Director Can Decide Now",
                "",
                f"请直接阅读完整论文卡：[{card.name}](./papers/{card.name})。卡片末尾给出可采用内容、不能外推的结论和下一步动作。",
                "",
                "## Trust Boundary",
                "",
                "这是一份单篇论文阅读产物，不代表已经穷尽相关文献，也不代表实验已经复现或结果已经进入研究数据库。",
                "",
                "## Key Findings",
                "",
                "核心背景、贡献、数据、方法、关键结论、数值边界、局限、复现条件和项目关系均已编辑进主卡。",
                "",
                "## Gate Trace",
                "",
                "机器审计记录保留在 `../evidence/`，不进入人类主阅读流。",
                "",
                "## Evidence Index",
                "",
                f"- 人类主卡：`{rel}`",
                "- 机器证据：`../evidence/`",
                "",
                "## Open Questions And Next Run",
                "",
                "请以主卡最后的“下一步研究动作”为准；任何入库、复现或实验执行仍需各自的独立人类决策。",
                "",
            ])

    lines: list[str] = [
        "---",
        f"run_id: {run_id}",
        f"project: {project}",
        f"mode: {mode}",
        f"status: {packet_status}",
        f"generated_at: {generated_at or ''}",
        f"primary_human_action: {action}",
        "json_evidence_root: ../evidence",
        "---",
        "",
        f"# Director Review Packet - {mode} - {run_id}",
        "",
        "## What Happened",
        "",
        f"- Run `{run_id}` belongs to project `{project}` and mode `{mode}`.",
        f"- Completed stages currently recorded in the manifest: {', '.join(stages) if stages else 'none'}.",
        f"- Machine-readable evidence stays under `evidence/`; this Markdown packet is the human entry point.",
        "",
        "## What The Director Can Decide Now",
        "",
        f"- Primary human action: `{action}`.",
        "- Do not treat this packet as a database promotion. `/promote-to-vault` remains the only vault write gate.",
        "",
        "## Trust Boundary",
        "",
        f"- Run-store status: `{status}`.",
        "- JSON artifacts are archived evidence, not the director-facing final output.",
        "- If a blocker or scripts-only execution is listed below, no metric/result claim is valid yet.",
        "",
        "## Key Findings",
        "",
    ]
    lines.extend(f"- {finding}" for finding in findings)
    lines.extend([
        "",
        "## Gate Trace",
        "",
    ])
    gate_rows = []
    for p, artifact in rows:
        payload = _payload(artifact)
        verdict = payload.get("verdict") or artifact.get("status")
        if verdict or "gate" in p.name or "verdict" in p.name or "report" in p.name:
            rel = p.relative_to(run_path).as_posix()
            gate_rows.append((rel, artifact.get("artifact_type", p.stem), verdict or "recorded"))
    if gate_rows:
        lines.extend([
            "| Evidence | Type | Status / verdict |",
            "|---|---|---|",
        ])
        lines.extend(f"| `{rel}` | `{typ}` | `{verdict}` |" for rel, typ, verdict in gate_rows)
    else:
        lines.append("- No explicit gate/verdict artifacts found.")
    lines.extend([
        "",
        "## Evidence Index",
        "",
        "| Stage | Evidence | Type | Status | Summary |",
        "|---|---|---|---|---|",
    ])
    for p, artifact in rows:
        rel = p.relative_to(run_path).as_posix()
        stage = _stage_of(p, run_path)
        typ = artifact.get("artifact_type", p.stem)
        art_status = artifact.get("status", "")
        summary = _artifact_summary(p, artifact).replace("|", "\\|")
        lines.append(f"| `{stage}` | `{rel}` | `{typ}` | `{art_status}` | {summary} |")
    lines.extend([
        "",
        "## Open Questions And Next Run",
        "",
    ])
    report = next((art for p, art in rows if p.name == "report-note.artifact.json"), {})
    open_questions = _payload(report).get("open_questions") or []
    if open_questions:
        lines.extend(f"- {q}" for q in open_questions)
    else:
        lines.append("- No open questions were recorded in `report-note.artifact.json`; audit the Key Findings and Gate Trace before acting.")
    lines.extend([
        "",
        "## Technical Appendix Pointers",
        "",
        "- `manifest.yaml` is the run-store state record.",
        "- `ledger.jsonl` is the tamper-evident event chain.",
        "- `task_frame.artifact.json` is the pinned direction contract.",
    ])
    return "\n".join(lines) + "\n"


def lint_packet(run_dir) -> list[str]:
    run_path = Path(run_dir)
    packet = packet_path(run_path)
    errors: list[str] = []
    if not packet.is_file():
        return [f"missing {PACKET_REL.as_posix()}"]
    text = packet.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"missing heading: {heading}")
    if len(text.strip()) < 500:
        errors.append("packet is too short to be a director-facing review packet")
    review_dir = run_path / "director-review"
    if review_dir.exists():
        for bad in review_dir.rglob("*.json"):
            errors.append(f"JSON is not allowed in director-review: {bad.relative_to(run_path).as_posix()}")
    return errors


def write_packet(run_dir, generated_at: Optional[str] = None) -> Path:
    run_path = Path(run_dir)
    out = packet_path(run_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_packet(run_path, generated_at=generated_at), encoding="utf-8")
    # Presentation lint is advisory at the daily-delivery boundary.  The file
    # itself is still delivered so useful research is never replaced by an
    # error-only response.  Strict completeness is rechecked at promotion.
    return out
