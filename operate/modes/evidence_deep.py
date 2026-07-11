"""Operate recipe for `evidence_deep` (DISCOVER -> REPORT).

This mode is now a real evidence panel, not one merged worker pretending to be
ten roles. The panel gathers sources, ranks quality, extracts claims, links
evidence, mines contradictions, audits datasets/staleness, maps the landscape,
and writes a director-facing Markdown evidence brief.

The database is still read by reference only. Invalidation records are draft
proposals until `/promote-to-vault` admits them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
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
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# bundle key -> artifact type / worker / output file / artifact status
ARTIFACT_PLAN = (
    ("evidence_table", "evidence_table", "lit-scout", "evidence-table.artifact.json", "approved"),
    ("source_quality_report", "source_quality_report", "source-quality-ranker",
     "source-quality-report.artifact.json", "approved"),
    ("evidence_search_trace", "evidence_search_trace", "evidence-search-moderator",
     "evidence-search-trace.artifact.json", "approved"),
    ("claim_list", "claim_list", "claim-extractor", "claim-list.artifact.json", "approved"),
    ("claim_evidence_map", "claim_evidence_map", "claim-evidence-linker",
     "claim-evidence-map.artifact.json", "approved"),
    ("contradiction_report", "contradiction_report", "contradiction-miner",
     "contradiction-report.artifact.json", "approved"),
    ("landscape_map", "landscape_map", "landscape-mapper", "landscape-map.artifact.json",
     "approved"),
)

PANEL_AGENTS = (
    "lit-scout",
    "source-quality-ranker",
    "claim-extractor",
    "evidence-search-moderator",
    "claim-evidence-linker",
    "citation-coverage-auditor",
    "contradiction-miner",
    "dataset-card-builder",
    "staleness-auditor",
    "landscape-mapper",
)

PANEL_DEPENDENCIES = {
    "lit-scout": [],
    "source-quality-ranker": ["lit-scout"],
    "claim-extractor": ["lit-scout"],
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
        "claim-extractor", "claim-evidence-linker", "citation-coverage-auditor",
    ],
    "dataset-card-builder": ["lit-scout"],
    "staleness-auditor": ["lit-scout", "source-quality-ranker"],
    "landscape-mapper": [
        "lit-scout", "source-quality-ranker", "claim-extractor",
        "evidence-search-moderator", "claim-evidence-linker",
        "citation-coverage-auditor", "contradiction-miner",
        "dataset-card-builder", "staleness-auditor",
    ],
}

EVIDENCE_DEEP_PARALLEL_GROUPS = [
    ["lit-scout"],
    ["source-quality-ranker", "claim-extractor"],
    ["evidence-search-moderator", "dataset-card-builder", "staleness-auditor"],
    ["claim-evidence-linker"],
    ["citation-coverage-auditor"],
    ["contradiction-miner"],
    ["landscape-mapper"],
]


def _worker_model(model_policy: str, agent: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    if agent in {"source-quality-ranker", "citation-coverage-auditor", "staleness-auditor",
                 "contradiction-miner"}:
        return "opus"
    return "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step exposed on every evidence mode."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def fulltext_pre(run_dir: str, question: str, doc_paths, ts: str) -> Optional[str]:
    """Prepare local, hash-addressed text snapshots before the evidence panel runs."""
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
    common = f"""You are `{agent}` in the TRUE multi-worker `evidence_deep` panel.

REQUEST: {request}

{north_star}

Sources by reference only:
- vault: `{vault}/02-wiki/`
- live retrieval bundle if present: `{run_dir}/inbox/search-results.json`
- fulltext contexts if present: `{run_dir}/inbox/fulltext-qa.json`
- exact citation offsets if present: `{run_dir}/inbox/citation-snapshots/fulltext-contexts.manifest.json`

{_prior_inputs(run_dir, prior_agents)}
Write ONLY JSON to `{out}`. Never invent slugs, DOIs, datasets, numbers, or source quality.
"""
    bodies = {
        "lit-scout": """
Task: gather and grade the source set for this evidence review.
Output exactly: {"evidence_table": {"evidence_contract_version":"evidence-table/v2",
"source_quality_report_ref":"evidence/DISCOVER/source-quality-report.artifact.json",
"search_trace_ref":"evidence/DISCOVER/evidence-search-trace.artifact.json",
query, sources, "saturation_reached":false}}.
Use 5-10 sources when available, including negative/boundary evidence. The saturation field is a
fixed compatibility placeholder; only the deterministic search-trace evaluator derives completion.
""",
        "source-quality-ranker": """
Task: independently audit every evidence-table source at inspectable locators.
Output exactly: {"source_quality_report": {"quality_contract_version":"source-methodology/v1",
"review_status":"CURRENT", ranked_sources, ranking_rationale, n_sources_ranked}}.
Every ranked source must include review_status, directness, study_design, all five methodology_review
dimensions, all four sample_evaluation_review dimensions, applicability, evidence_refs with locator
plus exact_quote/reported_result, and limitations. `rigor_score` is only a compatibility ordering hint
and never establishes strength. Do not omit weak or unverified sources.
""",
        "claim-extractor": """
Task: extract 3-6 atomic claims that matter for the director's research decision.
Output exactly: {"claim_list": {source_scope, claims:[{claim_id,text,source_ref,kind,confidence}]}}.
Claims must be falsifiable and trace to real source refs. Include material limitation or boundary
claims, not only positive findings, so the final briefing can show a real belief update.
""",
        "evidence-search-moderator": """
Task: moderate at least three grounded question/search rounds over the frozen sources and claims.
Output exactly: {"evidence_search_trace": {"search_contract_version":"evidence-search-trace/v1",
research_question, critical_claims, representativeness_dimensions, rounds, stop_reason,
budget_exhausted}}. Each round records questions, source_hits (with hashes when available),
claim_ids_addressed, contradiction_claim_ids_queried, representativeness_dimensions_queried, and
source-grounded findings. Cover every critical claim with explicit counterevidence queries and every
representativeness dimension. Continue through two trailing low-information rounds before using
semantic_complete. Never emit or self-set saturation; budget exhaustion is not completion.
""",
        "claim-evidence-linker": """
Task: link every claim to exact evidence spans from immutable source/fulltext snapshots.
Output exactly: {"claim_evidence_map": {attribution_contract_version:"claim-span/v1",
mappings:[{claim_id,overall_support,loci,claim_risk}]}}.
Every locus must include source_ref, location, kind, reported_result, supports_claim, support_relation,
directness, span_id, snapshot_ref, document_hash, parser_version, exact_quote, and either char_start/char_end,
table_cell_ref, or figure_region_ref. Use partial/insufficient instead of inflating support. You only link;
a different worker reopens every locator and independently judges semantic support.
""",
        "citation-coverage-auditor": """
Task: independently audit claim support. You did not extract or link the claims. Reopen each snapshot
and exact locator; ignore the linker's supports_claim conclusion until after your own reading. Check
direction, magnitude, units, denominator, confidence interval, population, condition, negation, and scope.
Output exactly: {"citation_audit": {"contract_version":"citation-attribution/v1",
"independent_of_linker":true,"claim_results":[{"claim_id":"C1",
"verdict":"entails|partial|contradicts|insufficient","locator_verified":true,
"verified_locus_ids":["L1"],"unsupported_locus_ids":[],"notes":"<independent reason>"}]}}.
Emit exactly one result per claim. A source existing or mentioning the topic is not entailment.
""",
        "contradiction-miner": """
Task: compare claims and source findings for conflicts; propose invalidation only for real vault claims.
Output exactly: {"contradiction_report": {n_claims_checked, summary, conflicts},
"invalidation_proposals": [{claim_slug, invalidated_by_slug, edge_type, invalid_at, basis,
evidence_ref}]}.
Empty invalidation_proposals is normal. Never invent a claim_slug. For each conflict, distinguish
unresolved counterevidence from a scope/protocol difference that explains the apparent conflict.
""",
        "dataset-card-builder": """
Task: build dataset cards only for datasets that materially affect the evidence review.
Output exactly: {"dataset_cards": [dataset_card, ...]}.
Use an empty list when no concrete dataset is involved. For each card, include splits and leakage_risks.
""",
        "staleness-auditor": """
Task: audit whether each important source is current, aging, stale, superseded, or unknown.
Output exactly: {"staleness_reports": [staleness_report, ...]}.
Use one report per important source. Mark SUPERSEDED only with a named successor_ref.
""",
        "landscape-mapper": """
Task: synthesize methods, datasets, gaps, and decision-relevant uncertainty from the panel artifacts.
Output exactly: {"landscape_map": {domain_query, methods, datasets_in_landscape, coverage_gaps,
n_methods_found, n_gaps_identified}}.
Every coverage gap description must name the missing evidence and the project/idea/experiment
decision it prevents; make the highest-severity gap specific enough to become the next evidence run.
""",
    }
    return common + bodies[agent]


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage != "DISCOVER":
        return None
    north_star = _shared.north_star_block(run_dir)
    workers = []
    for agent in PANEL_AGENTS:
        prior = list(PANEL_DEPENDENCIES[agent])
        out = str(_bundle_path(run_dir, agent)).replace("\\", "/")
        workers.append({
            "label": agent,
            "model": _worker_model(model_policy, agent),
            "output": out,
            "depends_on": prior,
            "prompt": _prompt(agent, request, run_dir, out, vault, north_star, prior),
        })
    return {
        "label": "evidence-deep-panel",
        "workers": workers,
        "worker_order": list(PANEL_AGENTS),
        "parallel_groups": EVIDENCE_DEEP_PARALLEL_GROUPS,
        "panel_note": "Run the sparse seven-wave evidence DAG. Source quality and claim extraction "
                      "are independent; search moderation, dataset cards, and staleness audit can run "
                      "together. Exact-span linking precedes the independent citation-coverage-auditor, then "
                      "contradiction analysis and final landscape synthesis.",
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_worker_bundles(run_dir) -> dict:
    try:
        replay = load_explicit_legacy_replay(run_dir)
    except ValueError as exc:
        raise GateBlock(str(exc)) from exc
    out = {}
    missing = []
    for agent in PANEL_AGENTS:
        p = _bundle_path(run_dir, agent)
        if not p.exists():
            if not (replay is not None and agent in {
                "citation-coverage-auditor", "evidence-search-moderator"
            }):
                missing.append(agent)
            continue
        out[agent] = _load_json(p)
    if missing:
        raise GateBlock(
            f"evidence_deep DISCOVER missing worker bundle(s): {missing}. "
            "A deep evidence review is not complete when one role is absent."
        )
    b = {
        "evidence_table": out["lit-scout"].get("evidence_table"),
        "source_quality_report": out["source-quality-ranker"].get("source_quality_report"),
        "claim_list": out["claim-extractor"].get("claim_list"),
        "evidence_search_trace": (out.get("evidence-search-moderator") or {}).get("evidence_search_trace"),
        "claim_evidence_map": out["claim-evidence-linker"].get("claim_evidence_map"),
        "citation_audit": (out.get("citation-coverage-auditor") or {}).get("citation_audit"),
        "contradiction_report": out["contradiction-miner"].get("contradiction_report"),
        "invalidation_proposals": out["contradiction-miner"].get("invalidation_proposals") or [],
        "dataset_cards": out["dataset-card-builder"].get("dataset_cards") or [],
        "staleness_reports": out["staleness-auditor"].get("staleness_reports") or [],
        "landscape_map": out["landscape-mapper"].get("landscape_map"),
        "legacy_replay": replay is not None,
    }
    missing_keys = [k for k, v in b.items() if v is None]
    if replay is not None:
        missing_keys = [k for k in missing_keys if k not in {"citation_audit", "evidence_search_trace"}]
    if missing_keys:
        raise GateBlock(f"evidence_deep bundle key BLOCK: missing {missing_keys}")
    return b


def _validate_payloads(b: dict) -> None:
    errors = []
    for key, atype, _agent, _fname, _status in ARTIFACT_PLAN:
        if b.get("legacy_replay") and b.get(key) is None:
            continue
        for e in validate_payload(atype, b[key] if isinstance(b[key], dict) else {}):
            errors.append(f"{key}: {e}")
    for i, card in enumerate(b.get("dataset_cards") or [], start=1):
        for e in validate_payload("dataset_card", card if isinstance(card, dict) else {}):
            errors.append(f"dataset_cards[{i}]: {e}")
    for i, report in enumerate(b.get("staleness_reports") or [], start=1):
        for e in validate_payload("staleness_report", report if isinstance(report, dict) else {}):
            errors.append(f"staleness_reports[{i}]: {e}")
    for i, prop in enumerate(b.get("invalidation_proposals") or [], start=1):
        for f in ("claim_slug", "invalidated_by_slug"):
            if not _SLUG.match(str((prop or {}).get(f, ""))):
                raise GateBlock(
                    f"invalidation proposal {i}: {f} is not a real slug shape "
                    f"({(prop or {}).get(f)!r}) - never invent a slug"
                )
        for e in validate_payload("invalidation_record", prop if isinstance(prop, dict) else {}):
            errors.append(f"invalidation_proposals[{i}]: {e}")
    if errors:
        raise GateBlock(f"evidence_deep artifact schema BLOCK: {errors}")


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

    ranked = b["source_quality_report"].get("ranked_sources") or []
    missing_ranked = [r.get("source_ref") for r in ranked if str(r.get("source_ref") or "") not in refs]
    if missing_ranked:
        raise GateBlock(f"source-quality consistency BLOCK: ranked source(s) not in evidence table {missing_ranked}")

    claim_ids = {str(c.get("claim_id")) for c in (b["claim_list"].get("claims") or [])}
    missing_claim_source = [
        c.get("claim_id") for c in (b["claim_list"].get("claims") or [])
        if str(c.get("source_ref") or "") not in refs
    ]
    if missing_claim_source:
        raise GateBlock(f"claim source consistency BLOCK: claims cite sources outside evidence table {missing_claim_source}")

    mapping_ids = {str(m.get("claim_id")) for m in (b["claim_evidence_map"].get("mappings") or [])}
    missing_maps = sorted(claim_ids - mapping_ids)
    if missing_maps:
        raise GateBlock(f"claim-evidence consistency BLOCK: unmapped claim ids {missing_maps}")

    conflicts = b["contradiction_report"].get("conflicts") or []
    bad_conflicts = []
    for conf in conflicts:
        a = str(conf.get("claim_ref_a") or "")
        c = str(conf.get("claim_ref_b") or "")
        if a not in claim_ids or c not in claim_ids:
            bad_conflicts.append(conf.get("conflict_id"))
    if bad_conflicts:
        raise GateBlock(f"contradiction consistency BLOCK: conflict(s) reference unknown claim ids {bad_conflicts}")

    for i, prop in enumerate(b.get("invalidation_proposals") or [], start=1):
        for f in ("claim_slug", "invalidated_by_slug"):
            if not _SLUG.match(str(prop.get(f, ""))):
                raise GateBlock(
                    f"invalidation proposal {i}: {f} is not a real slug shape "
                    f"({prop.get(f)!r}) - never invent a slug"
                )


def _discover_dets(run_dir, ts, b) -> tuple:
    _validate_payloads(b)
    _consistency_checks(b)

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
    texts = [str(et.get("query") or "")]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    texts += [str((b["contradiction_report"] or {}).get("summary") or "")]
    texts += [str(g.get("description") or "") for g in (b["landscape_map"].get("coverage_gaps") or [])]
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

    epath, ex = _shared.run_existence_gate(
        run_dir, "DISCOVER", ts, _shared.external_refs(et, b["claim_evidence_map"])
    )
    paths.append(epath)

    for key, atype, agent, fname, status in ARTIFACT_PLAN:
        if b.get(key) is None:
            continue
        payload = et if key == "evidence_table" else b[key]
        paths.append(write_artifact(run_dir, "DISCOVER", fname, atype, agent, payload, ts,
                                    "draft" if legacy else status))

    for i, card in enumerate(b.get("dataset_cards") or [], start=1):
        paths.append(write_artifact(run_dir, "DISCOVER", f"dataset-card-{i}.artifact.json",
                                    "dataset_card", "dataset-card-builder", card, ts, "approved"))
    for i, stale in enumerate(b.get("staleness_reports") or [], start=1):
        paths.append(write_artifact(run_dir, "DISCOVER", f"staleness-{i}.artifact.json",
                                    "staleness_report", "staleness-auditor", stale, ts, "approved"))
    n_props = 0
    for i, prop in enumerate(b.get("invalidation_proposals") or [], start=1):
        paths.append(write_artifact(run_dir, "DISCOVER", f"invalidation-{i}.artifact.json",
                                    "invalidation_record", "contradiction-miner", prop, ts,
                                    status="draft"))
        n_props += 1

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
        "n_ranked_sources": len(b["source_quality_report"].get("ranked_sources") or []),
        "n_claims": len(b["claim_list"].get("claims") or []),
        "n_mappings": len(b["claim_evidence_map"].get("mappings") or []),
        "n_conflicts": len(b["contradiction_report"].get("conflicts") or []),
        "n_invalidation_proposals": n_props,
        "n_dataset_cards": len(b.get("dataset_cards") or []),
        "n_staleness_reports": len(b.get("staleness_reports") or []),
        "n_landscape_gaps": len(b["landscape_map"].get("coverage_gaps") or []),
    }
    try:
        report["director_markdown_brief"] = write_research_brief_markdown(
            run_dir,
            mode="evidence_deep",
            evidence_table=et,
            claim_list=b["claim_list"],
            claim_evidence_map=b["claim_evidence_map"],
            report=report,
            source_quality_report=b["source_quality_report"],
            search_trace=search_trace,
            contradiction_report=b["contradiction_report"],
            landscape_map=b["landscape_map"],
            staleness_reports=b.get("staleness_reports") or [],
            dataset_cards=b.get("dataset_cards") or [],
        )
    except ValueError as exc:
        report["director_markdown_brief"] = write_research_brief_fallback(
            run_dir, mode="evidence_deep", reason=str(exc), report=report)
        report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
    return paths, report


def _report(run_dir, ts) -> tuple:
    note = {
        "summary": "evidence_deep: staged evidence panel completed with source quality, "
                   "claim/evidence mapping, contradiction mining, landscape gaps, and a "
                   "director-facing Markdown evidence brief.",
        "references": [
            "director-review/evidence/evidence-deep-brief.md",
            "evidence/DISCOVER/evidence-table.artifact.json",
            "evidence/DISCOVER/landscape-map.artifact.json",
            "evidence/DISCOVER/contradiction-report.artifact.json",
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
    raise ValueError(f"evidence_deep has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
