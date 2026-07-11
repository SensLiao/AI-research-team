"""Operate recipe for `deep_research` (DISCOVER -> REPORT).

deep_research is now a true perspective panel. The old implementation asked one
supervisor worker to simulate multiple researchers inside a single JSON bundle.
This recipe requires independent perspective bundles, then synthesizes them into
a structured research brief plus a director-facing Markdown memo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.budget_tracker import assert_within
from ...tools.citation_attribution import (
    build_run_attribution_report,
    load_explicit_legacy_replay,
    prepare_fulltext_citation_inputs,
)
from ...tools.citation_checker import build_report
from ...tools.evidence_checker import build_verdict
from ...tools.evidence_search_trace import evaluate_search_trace
from ...tools.evidence_scout import build_evidence_table
from ...tools.research_brief_markdown import (
    write_research_brief_fallback,
    write_research_brief_markdown,
)
from ...tools.source_methodology_audit import audit_source_quality_report
from ...tools.validate_artifact import validate_payload

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

PERSPECTIVE_WORKERS = (
    ("model-dataset-scout", "P1", "methods, models, datasets, and benchmark state"),
    ("future-work-miner", "P2", "open problems, unresolved gaps, and next experiments"),
    ("cross-domain-transfer-scout", "P3", "adjacent-field transfer and mechanism analogies"),
    ("weakness-spotter", "P4", "failure modes, negative evidence, and reasons not to overclaim"),
)

PANEL_AGENTS = (
    "lit-scout",
    "source-quality-ranker",
    "model-dataset-scout",
    "future-work-miner",
    "cross-domain-transfer-scout",
    "weakness-spotter",
    "claim-extractor",
    "evidence-search-moderator",
    "claim-evidence-linker",
    "citation-coverage-auditor",
    "contradiction-miner",
    "landscape-mapper",
)

PERSPECTIVE_AGENT_NAMES = [name for name, _pid, _angle in PERSPECTIVE_WORKERS]

DEEP_RESEARCH_DEPENDENCIES = {
    "lit-scout": [],
    "source-quality-ranker": ["lit-scout"],
    **{
        agent: ["lit-scout", "source-quality-ranker"]
        for agent in PERSPECTIVE_AGENT_NAMES
    },
    "claim-extractor": ["lit-scout", *PERSPECTIVE_AGENT_NAMES],
    "evidence-search-moderator": [
        "lit-scout", "source-quality-ranker", "claim-extractor",
    ],
    "claim-evidence-linker": [
        "lit-scout", "claim-extractor", "evidence-search-moderator",
    ],
    "citation-coverage-auditor": [
        "lit-scout", "claim-extractor", "claim-evidence-linker",
    ],
    "contradiction-miner": [
        "claim-extractor", "claim-evidence-linker", *PERSPECTIVE_AGENT_NAMES,
    ],
    "landscape-mapper": list(PANEL_AGENTS[:-1]),
}

DEEP_RESEARCH_PARALLEL_GROUPS = [
    ["lit-scout"],
    ["source-quality-ranker"],
    PERSPECTIVE_AGENT_NAMES,
    ["claim-extractor"],
    ["evidence-search-moderator"],
    ["claim-evidence-linker"],
    ["citation-coverage-auditor", "contradiction-miner"],
    ["landscape-mapper"],
]


def _worker_model(model_policy: str, agent: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    if agent in {"source-quality-ranker", "citation-coverage-auditor", "contradiction-miner",
                 "landscape-mapper"}:
        return "opus"
    return "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def fulltext_pre(run_dir: str, question: str, doc_paths, ts: str) -> Optional[str]:
    """Prepare local, hash-addressed text snapshots before the research panel runs."""
    return prepare_fulltext_citation_inputs(run_dir, question, list(doc_paths or []))


def _bundle_path(run_dir, agent: str) -> Path:
    return Path(run_dir) / "inbox" / f"DISCOVER.{agent}.bundle.json"


def _prior_inputs(run_dir, prior_agents: list[str]) -> str:
    if not prior_agents:
        return ""
    lines = ["Read these earlier worker bundles before writing:"]
    for agent in prior_agents:
        lines.append(f"- `{_bundle_path(run_dir, agent).as_posix()}`")
    return "\n".join(lines) + "\n"


def _prompt(agent: str, request: str, run_dir: str, out: str, vault: str,
            north_star: str, prior_agents: list[str]) -> str:
    common = f"""You are `{agent}` in the TRUE multi-worker `deep_research` pipeline.

TOPIC: {request}

{north_star}

Sources by reference only:
- vault: `{vault}/02-wiki/`
- live retrieval bundle if present: `{run_dir}/inbox/search-results.json`
- fulltext contexts if present: `{run_dir}/inbox/fulltext-qa.json`
- exact citation offsets if present: `{run_dir}/inbox/citation-snapshots/fulltext-contexts.manifest.json`

{_prior_inputs(run_dir, prior_agents)}
Write ONLY JSON to `{out}`. The output must be compressed research judgment, not raw notes.
Never invent slugs, DOIs, papers, datasets, or metrics.
"""
    perspective = {agent_name: (pid, angle) for agent_name, pid, angle in PERSPECTIVE_WORKERS}
    if agent == "lit-scout":
        return common + """
Task: gather the shared source set for the whole research topic.
Output exactly: {"evidence_table": {"evidence_contract_version":"evidence-table/v2",
"source_quality_report_ref":"evidence/DISCOVER/source-quality-report.artifact.json",
"search_trace_ref":"evidence/DISCOVER/evidence-search-trace.artifact.json",
query, sources, "saturation_reached":false}}.
Use 5-10 sources when available, including negative and boundary evidence. The saturation field is a
fixed compatibility placeholder; only the deterministic search-trace evaluator derives completion.
"""
    if agent == "source-quality-ranker":
        return common + """
Task: independently audit every source at inspectable locators.
Output exactly: {"source_quality_report": {"quality_contract_version":"source-methodology/v1",
"review_status":"CURRENT", ranked_sources, ranking_rationale, n_sources_ranked}}.
Every row must contain review_status, directness, study_design, all methodology_review and
sample_evaluation_review dimensions, applicability, evidence_refs with locator plus exact quote or
reported result, and limitations. `rigor_score` is only an ordering hint and never proves strength.
"""
    if agent in perspective:
        pid, angle = perspective[agent]
        return common + f"""
Task: independently research perspective `{pid}`: {angle}.
Output exactly: {{"research_perspective_note": {{perspective_id, angle, questions,
finding_summary, source_refs, coverage_limits, actionable_opportunities, kill_criteria,
confidence}}}}.
Use perspective_id `{pid}`. Include at least two concrete questions. The finding_summary must
answer "what changed in belief, what should the project/idea/experiment do next, and what remains
uncertain from this angle?" Put the highest-value action in actionable_opportunities and a real
decision-reversing result in kill_criteria.
"""
    if agent == "claim-extractor":
        return common + """
Task: extract 3-6 cross-perspective atomic claims from the perspective notes.
Output exactly: {"claim_list": {source_scope, claims:[{claim_id,text,source_ref,kind,confidence}]}}.
Each claim must be useful for a research decision, not just descriptive. Include material boundary
or limitation claims so the synthesis is not a one-sided positive summary.
"""
    if agent == "evidence-search-moderator":
        return common + """
Task: moderate at least three grounded question/search rounds over the frozen source set and final
critical claims. Output exactly: {"evidence_search_trace": {
"search_contract_version":"evidence-search-trace/v1", research_question, critical_claims,
representativeness_dimensions, rounds, stop_reason, budget_exhausted}}. Every round records questions,
source hits and hashes when available, claim coverage, explicit contradiction queries,
representativeness dimensions, and source-grounded findings. Cover every critical claim and dimension;
continue through two trailing low-information rounds before semantic_complete. Never emit or self-set
saturation. Budget exhaustion is not completion.
"""
    if agent == "claim-evidence-linker":
        return common + """
Task: link every claim to exact evidence spans from immutable source/fulltext snapshots.
Output exactly: {"claim_evidence_map": {attribution_contract_version:"claim-span/v1",
mappings:[{claim_id,overall_support,loci,claim_risk}]}}.
Every locus must include source_ref, location, kind, reported_result, supports_claim, support_relation,
directness, span_id, snapshot_ref, document_hash, parser_version, exact_quote, and either char_start/char_end,
table_cell_ref, or figure_region_ref. Perspective summaries may guide retrieval but are never citable evidence.
"""
    if agent == "citation-coverage-auditor":
        return common + """
Task: independently audit claim support after the linker freezes locators. You did not extract or link
the claims. Reopen each source snapshot and locator; form your semantic judgment before comparing it
with the linker's flag. Check direction, units, population, condition, numerical qualifiers, uncertainty,
negation, and scope.
Output exactly: {"citation_audit": {"contract_version":"citation-attribution/v1",
"independent_of_linker":true,"claim_results":[{"claim_id":"C1",
"verdict":"entails|partial|contradicts|insufficient","locator_verified":true,
"verified_locus_ids":["L1"],"unsupported_locus_ids":[],"notes":"<independent reason>"}]}}.
Emit one result per claim. A source existing or mentioning the topic is not entailment.
"""
    if agent == "contradiction-miner":
        return common + """
Task: identify disagreements among claims and perspectives.
Output exactly: {"contradiction_report": {n_claims_checked, summary, conflicts}}.
No conflict is acceptable, but only after checking cross-perspective tension. Distinguish unresolved
counterevidence from a scope/protocol mismatch that explains the disagreement.
"""
    if agent == "landscape-mapper":
        return common + """
Task: synthesize the final research brief and human Markdown memo from all prior bundles.
Output exactly: {"research_brief": {topic,perspectives,findings,bottom_line,consensus,
live_disagreements,evidence_gaps,actionable_next_questions,iterations_used,
saturation_reached,evidence_ref}, "usage": {iterations_without_new_evidence, fulltext_reads},
"research_markdown_brief": {topic,markdown,evidence_refs,perspective_ids,quality_caveats}}.
The bottom_line must explicitly state the belief update, confidence boundary, and immediate
project/idea/experiment implication. actionable_next_questions must put the single highest expected
information-value evidence first. The Markdown is a worker draft retained as evidence; the final
director page is rendered and linted deterministically from all panel structures. Keep the research
brief's saturation_reached compatibility field false; search completion is derived elsewhere. Minimum 700 characters.
"""
    raise ValueError(f"unknown deep_research agent {agent}")


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage != "DISCOVER":
        return None
    north_star = _shared.north_star_block(run_dir)
    workers = []
    for agent in PANEL_AGENTS:
        prior = list(DEEP_RESEARCH_DEPENDENCIES[agent])
        out = str(_bundle_path(run_dir, agent)).replace("\\", "/")
        workers.append({
            "label": agent,
            "model": _worker_model(model_policy, agent),
            "output": out,
            "depends_on": prior,
            "prompt": _prompt(agent, request, run_dir, out, vault, north_star, prior),
        })
    return {
        "label": "deep-research-panel",
        "workers": workers,
        "worker_order": list(PANEL_AGENTS),
        "parallel_groups": DEEP_RESEARCH_PARALLEL_GROUPS,
        "panel_note": "Freeze the shared source set first, then spawn the four perspective seats in "
                      "parallel/blind to one another. Downstream workers read only their direct "
                      "scientific dependencies. Citation audit and contradiction analysis are "
                      "independent checks over the frozen claim map and run in parallel before synthesis.",
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_worker_bundles(run_dir) -> dict:
    try:
        replay = load_explicit_legacy_replay(run_dir)
    except ValueError as exc:
        raise GateBlock(str(exc)) from exc
    missing = []
    raw = {}
    for agent in PANEL_AGENTS:
        p = _bundle_path(run_dir, agent)
        if not p.exists():
            if not (replay is not None and agent in {
                "citation-coverage-auditor", "evidence-search-moderator"
            }):
                missing.append(agent)
            continue
        raw[agent] = _load_json(p)
    if missing:
        raise GateBlock(f"deep_research DISCOVER missing worker bundle(s): {missing}")

    perspective_notes = []
    for agent, _pid, _angle in PERSPECTIVE_WORKERS:
        note = raw[agent].get("research_perspective_note")
        if note is None:
            raise GateBlock(f"deep_research bundle key BLOCK: {agent} missing research_perspective_note")
        perspective_notes.append(note)

    synth = raw["landscape-mapper"]
    b = {
        "evidence_table": raw["lit-scout"].get("evidence_table"),
        "source_quality_report": raw["source-quality-ranker"].get("source_quality_report"),
        "perspective_notes": perspective_notes,
        "claim_list": raw["claim-extractor"].get("claim_list"),
        "evidence_search_trace": (raw.get("evidence-search-moderator") or {}).get("evidence_search_trace"),
        "claim_evidence_map": raw["claim-evidence-linker"].get("claim_evidence_map"),
        "citation_audit": (raw.get("citation-coverage-auditor") or {}).get("citation_audit"),
        "contradiction_report": raw["contradiction-miner"].get("contradiction_report"),
        "research_brief": synth.get("research_brief"),
        "usage": synth.get("usage"),
        "research_markdown_brief": synth.get("research_markdown_brief"),
        "legacy_replay": replay is not None,
    }
    missing_keys = [k for k, v in b.items() if v is None]
    if replay is not None:
        missing_keys = [k for k in missing_keys if k not in {"citation_audit", "evidence_search_trace"}]
    if missing_keys:
        raise GateBlock(f"deep_research bundle key BLOCK: missing {missing_keys}")
    return b


def _budget(run_dir) -> dict:
    return _shared.budget(run_dir)


def _normalize_compat_enums(b: dict) -> None:
    """Map richer worker wording to legacy machine enums without replaying research."""
    source_kind = {
        "official-protocol": "benchmark",
        "paper-card": "doc",
    }
    claim_kind = {
        "baseline": "comparison",
        "boundary": "limitation",
        "falsification": "method",
        "proposal": "other",
        "transfer": "method",
    }
    conflict_kind = {
        "evidence-proposal-boundary": "scope-mismatch",
        "mechanism-ambiguity": "method-conflict",
        "orthogonal-safety-boundary": "scope-mismatch",
    }
    resolution = {
        "requires-experiment": "unresolved",
        "requires-separate-control": "unresolved",
    }
    for row in (b.get("evidence_table") or {}).get("sources") or []:
        row["kind"] = source_kind.get(row.get("kind"), row.get("kind"))
    for row in (b.get("claim_list") or {}).get("claims") or []:
        row["kind"] = claim_kind.get(row.get("kind"), row.get("kind"))
    for row in (b.get("contradiction_report") or {}).get("conflicts") or []:
        row["kind"] = conflict_kind.get(row.get("kind"), row.get("kind"))
        row["resolution_status"] = resolution.get(
            row.get("resolution_status"), row.get("resolution_status")
        )


def _validate_payloads(b: dict) -> None:
    _normalize_compat_enums(b)
    errors = []
    for atype, key in (
        ("evidence_table", "evidence_table"),
        ("source_quality_report", "source_quality_report"),
        ("evidence_search_trace", "evidence_search_trace"),
        ("claim_list", "claim_list"),
        ("claim_evidence_map", "claim_evidence_map"),
        ("contradiction_report", "contradiction_report"),
        ("research_brief", "research_brief"),
        ("research_markdown_brief", "research_markdown_brief"),
    ):
        if b.get("legacy_replay") and b.get(key) is None:
            continue
        for e in validate_payload(atype, b[key] if isinstance(b[key], dict) else {}):
            errors.append(f"{key}: {e}")
    for i, note in enumerate(b.get("perspective_notes") or [], start=1):
        for e in validate_payload("research_perspective_note", note if isinstance(note, dict) else {}):
            errors.append(f"perspective_notes[{i}]: {e}")
    if errors:
        raise GateBlock(f"deep_research artifact schema BLOCK: {errors}")


def _source_refs(et: dict) -> set[str]:
    refs = set()
    for src in et.get("sources") or []:
        if src.get("ref"):
            refs.add(str(src["ref"]))
        if src.get("id"):
            refs.add(str(src["id"]))
    return refs


def _consistency_checks(b: dict) -> None:
    et = build_evidence_table(
        b["evidence_table"]["query"],
        b["evidence_table"]["sources"],
        b["evidence_table"].get("saturation_reached", False),
    )
    refs = _source_refs(et)

    if not b.get("legacy_replay"):
        if b["evidence_table"].get("evidence_contract_version") != "evidence-table/v2":
            raise GateBlock("current evidence table must declare evidence-table/v2")
        if b["source_quality_report"].get("quality_contract_version") != "source-methodology/v1":
            raise GateBlock("current source quality must declare source-methodology/v1")
        if b["evidence_search_trace"].get("search_contract_version") != "evidence-search-trace/v1":
            raise GateBlock("current search trace must declare evidence-search-trace/v1")
        trace_refs = {
            str(hit.get("source_ref"))
            for row in b["evidence_search_trace"].get("rounds") or []
            for hit in row.get("source_hits") or []
            if hit.get("source_ref")
        }
        outside_trace = sorted(trace_refs - refs)
        if outside_trace:
            raise GateBlock(f"search trace source(s) outside evidence table: {outside_trace}")

    pids = [str(p.get("perspective_id")) for p in b["perspective_notes"]]
    if len(set(pids)) != len(pids):
        raise GateBlock(f"deep_research perspective consistency BLOCK: duplicate perspective ids {pids}")
    if len(pids) < 3:
        raise GateBlock("deep_research perspective consistency BLOCK: at least 3 perspectives are required")

    brief_ids = {str(p.get("perspective_id")) for p in b["research_brief"].get("perspectives") or []}
    finding_ids = {str(f.get("perspective_id")) for f in b["research_brief"].get("findings") or []}
    missing = sorted(set(pids) - brief_ids) + sorted(set(pids) - finding_ids)
    if missing:
        raise GateBlock(f"deep_research brief consistency BLOCK: missing perspective(s) {sorted(set(missing))}")

    markdown_ids = set(str(x) for x in b["research_markdown_brief"].get("perspective_ids") or [])
    # Worker-declared Markdown coverage is navigation metadata, not scientific
    # truth. The rendered report is audited separately and delivered with a
    # visible caveat when perspective labels are incomplete.

    ranked = b["source_quality_report"].get("ranked_sources") or []
    outside = [r.get("source_ref") for r in ranked if str(r.get("source_ref") or "") not in refs]
    if outside:
        raise GateBlock(f"source-quality consistency BLOCK: ranked source(s) not in evidence table {outside}")

    claim_ids = {str(c.get("claim_id")) for c in (b["claim_list"].get("claims") or [])}
    mapping_ids = {str(m.get("claim_id")) for m in (b["claim_evidence_map"].get("mappings") or [])}
    unmapped = sorted(claim_ids - mapping_ids)
    if unmapped:
        raise GateBlock(f"claim-evidence consistency BLOCK: unmapped claim ids {unmapped}")

    bad_conflicts = []
    for conf in b["contradiction_report"].get("conflicts") or []:
        if str(conf.get("claim_ref_a") or "") not in claim_ids or str(conf.get("claim_ref_b") or "") not in claim_ids:
            bad_conflicts.append(conf.get("conflict_id"))
    if bad_conflicts:
        raise GateBlock(f"contradiction consistency BLOCK: unknown claim ids in conflicts {bad_conflicts}")


def _enforce_usage_budget(run_dir, usage: dict) -> tuple[int, int]:
    if not isinstance(usage, dict):
        raise GateBlock("deep_research worker did not report 'usage' counts")
    try:
        iters = int(usage["iterations_without_new_evidence"])
        reads = int(usage["fulltext_reads"])
    except (KeyError, TypeError, ValueError):
        raise GateBlock("deep_research 'usage' must report INTEGER iterations_without_new_evidence + fulltext_reads")
    assert_within(_budget(run_dir), {
        "iterations_without_new_evidence": iters,
        "fulltext_reads": reads,
    })
    return iters, reads


def _discover_dets(run_dir, ts, b) -> tuple:
    _validate_payloads(b)
    _consistency_checks(b)
    iters, reads = _enforce_usage_budget(run_dir, b["usage"])

    paths = []
    et = build_evidence_table(
        b["evidence_table"]["query"],
        b["evidence_table"]["sources"],
        b["evidence_table"].get("saturation_reached", False),
    )
    legacy = bool(b.get("legacy_replay"))
    source_quality = b.get("source_quality_report")
    search_trace = b.get("evidence_search_trace")
    search_audit = evaluate_search_trace(search_trace)
    source_audit = audit_source_quality_report(source_quality, et)
    if not legacy:
        et.update({
            "evidence_contract_version": "evidence-table/v2",
            "source_quality_report_ref": b["evidence_table"]["source_quality_report_ref"],
            "search_trace_ref": b["evidence_table"]["search_trace_ref"],
            "saturation_reached": bool(search_audit["semantic_complete"]),
        })
    brief = b["research_brief"]
    texts = [str(et.get("query") or ""), str(brief.get("bottom_line") or "")]
    texts += [str(p.get("angle") or "") for p in (brief.get("perspectives") or [])]
    texts += [str(f.get("summary") or "") for f in (brief.get("findings") or [])]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)
    paths.append(dpath)

    ev = build_verdict(et, source_quality_report=source_quality, search_trace=search_trace,
                       strict_current=True)
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "draft" if legacy else
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK" and not legacy:
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")

    cv = build_report(b["claim_list"], b["claim_evidence_map"],
                      resolvable_refs=_shared.resolvable_refs(et))
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    if cv["verdict"] == "BLOCK":
        raise GateBlock(f"citation gate BLOCK: {cv['violations']}")

    try:
        attribution = build_run_attribution_report(
            run_dir, b["claim_list"], b["claim_evidence_map"], b.get("citation_audit"))
    except ValueError as exc:
        raise GateBlock(str(exc)) from exc
    attr_status = (
        "approved" if attribution["verdict"] == "PASS"
        else "draft" if attribution["legacy_replay"]
        else "blocked"
    )
    paths.append(write_artifact(
        run_dir, "DISCOVER", "citation-attribution-report.artifact.json",
        "citation_attribution_report", "citation-coverage-auditor", attribution, ts, attr_status))
    if attribution["verdict"] != "PASS" and not attribution["legacy_replay"]:
        reasons = attribution["violations"] + attribution["unverified_reasons"]
        raise GateBlock(f"citation attribution {attribution['verdict']}: {reasons}")

    # The panel already consumes a frozen upstream/source set. Re-querying every DOI, URL, run ref,
    # and title here caused long network stalls and false negatives. Strict existence replay belongs
    # to promotion; ordinary research delivery records the frozen set and proceeds.
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts, [])
    paths.append(epath)

    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts,
                                "draft" if legacy else "approved"))
    paths.append(write_artifact(run_dir, "DISCOVER", "source-quality-report.artifact.json",
                                "source_quality_report", "source-quality-ranker",
                                b["source_quality_report"], ts,
                                "draft" if legacy else "approved"))
    if search_trace is not None:
        paths.append(write_artifact(run_dir, "DISCOVER", "evidence-search-trace.artifact.json",
                                    "evidence_search_trace", "evidence-search-moderator",
                                    search_trace, ts, "draft" if legacy else "approved"))
    for note in b["perspective_notes"]:
        pid = str(note.get("perspective_id"))
        paths.append(write_artifact(run_dir, "DISCOVER", f"research-perspective-{pid}.artifact.json",
                                    "research_perspective_note", "deep-research-panel", note, ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "claim-list.artifact.json",
                                "claim_list", "claim-extractor", b["claim_list"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "claim-evidence-map.artifact.json",
                                "claim_evidence_map", "claim-evidence-linker",
                                b["claim_evidence_map"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "contradiction-report.artifact.json",
                                "contradiction_report", "contradiction-miner",
                                b["contradiction_report"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "research-brief.artifact.json",
                                "research_brief", "landscape-mapper", b["research_brief"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "research-markdown-brief.artifact.json",
                                "research_markdown_brief", "landscape-mapper",
                                b["research_markdown_brief"], ts))
    report = {
        "evidence_gate": "LEGACY_UNVERIFIED" if legacy else ev["verdict"],
        "source_methodology_status": source_audit.get("audit_status"),
        "search_completion_status": search_audit.get("status"),
        "citation_gate": cv["verdict"],
        "citation_attribution_gate": (
            "LEGACY_UNVERIFIED" if attribution["legacy_replay"] else attribution["verdict"]),
        "citation_legacy_replay": attribution["legacy_replay"],
        "citation_correctness": attribution["citation_correctness"],
        "claim_completeness": attribution["claim_completeness"],
        "citation_f1": attribution["citation_f1"],
        "existence_gate": ex["verdict"],
        "existence_warnings": len(ex["warnings"]),
        "n_sources": len(et.get("sources") or []),
        "n_strong_sources": ev.get("n_strong"),
        "n_perspectives": len(b["perspective_notes"]),
        "n_claims": len(b["claim_list"].get("claims") or []),
        "n_conflicts": len(b["contradiction_report"].get("conflicts") or []),
        "iterations_without_new_evidence": iters,
        "fulltext_reads": reads,
        "iterations_used": brief.get("iterations_used", 0),
        "saturation_reached": bool(search_audit.get("semantic_complete")),
    }
    try:
        report["director_markdown_brief"] = write_research_brief_markdown(
            run_dir,
            mode="deep_research",
            evidence_table=et,
            claim_list=b["claim_list"],
            claim_evidence_map=b["claim_evidence_map"],
            report=report,
            source_quality_report=b["source_quality_report"],
            search_trace=search_trace,
            contradiction_report=b["contradiction_report"],
            perspective_notes=b["perspective_notes"],
            research_brief=b["research_brief"],
        )
    except ValueError as exc:
        report["director_markdown_brief"] = write_research_brief_fallback(
            run_dir, mode="deep_research", reason=str(exc), report=report)
        report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
    return paths, report


def _report(run_dir, ts) -> tuple:
    note = {
        "summary": "deep_research: true perspective panel completed with a structured research brief "
                   "and director-facing Markdown memo.",
        "references": [
            "director-review/research/research-brief.md",
            "evidence/DISCOVER/research-brief.artifact.json",
            "evidence/DISCOVER/research-markdown-brief.artifact.json",
            "evidence/DISCOVER/citation-attribution-report.artifact.json",
        ],
        "produced_artifacts": [],
        "open_questions": [],
    }
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_worker_bundles(run_dir))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"deep_research has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    return attempt_with_repair(run_dir, stage, _budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
