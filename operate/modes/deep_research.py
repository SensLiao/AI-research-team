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
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ..output_versions import resolve_effective_output
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
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None) -> str:
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries)


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
- agent Web Search fallback when API recall is empty/off-topic or a named method is absent; accept
  only paper originals, official publisher/project pages, or authors' official repositories, and
  carry them by resolvable reference through the same citation gates

{_prior_inputs(run_dir, prior_agents)}
Write ONLY JSON to `{out}`. The output must be compressed research judgment, not raw notes.
Never invent slugs, DOIs, papers, datasets, or metrics.

When the topic asks whether an idea is novel or collides with prior art, metadata, titles, abstracts,
snippets, and shared components only discover candidates. A fatal collision requires reading the
closest paper's full method and decision-relevant results and recording inspectable loci. Compare the
central claim, input/output contract, mechanism, causal controls, evaluation target, and scope. Use
the relations exact_collision, partial_component_prior, enabling_base, gap_source, orthogonal, and
uncertain. If decisive full text is unavailable, state UNVERIFIED; never infer global novelty or a
collision. Choose the retrieval and reasoning route yourself; this evidence boundary is the contract.
"""
    perspective = {agent_name: (pid, angle) for agent_name, pid, angle in PERSPECTIVE_WORKERS}
    if agent == "lit-scout":
        return common + """
Task: gather the shared source set for the whole research topic.
Output exactly: {"evidence_table": {"evidence_contract_version":"evidence-table/v2",
"source_quality_report_ref":"evidence/DISCOVER/source-quality-report.artifact.json",
"search_trace_ref":"evidence/DISCOVER/evidence-search-trace.artifact.json",
query, sources, "saturation_reached":false}}.
Use 5-10 sources when available, including negative and boundary evidence. For novelty questions,
retrieve candidates across the central claim, mechanism, input/output contract, causal assay, and
strongest falsifying alternative; do not stop at topical similarity. The saturation field is a
fixed compatibility placeholder; only the deterministic search-trace evaluator derives completion.
"""
    if agent == "source-quality-ranker":
        return common + """
Task: independently audit every source at inspectable locators.
Output exactly: {"source_quality_report": {"quality_contract_version":"source-methodology/v1",
"review_status":"CURRENT", ranked_sources, ranking_rationale, n_sources_ranked}}.
Every row must contain review_status, directness, study_design, all methodology_review and
sample_evaluation_review dimensions, applicability, evidence_refs with locator plus exact quote or
reported result, and limitations. Judge applicability against the full research question in the task
frame, not one convenient subclaim. Use `direct` only when the source directly addresses the whole
atomic question; a source covering one component of a bundled question remains `partial` or
`indirect`. Never upgrade applicability merely to clear a gate. `rigor_score` is only an ordering hint
and never proves strength.
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
For `source_ref`, copy the evidence-table row's resolvable `ref` value, never its local `id` such as
`s1`; the id is only an internal join key and is not a citable reference.
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
For `source_ref`, copy the evidence-table row's resolvable `ref` value, never its local `id` such as `s1`.
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
saturation_reached,evidence_ref}, "usage": {iterations_without_new_evidence, fulltext_reads}}.
You may also include an optional `research_markdown_brief` worker draft with
{topic,markdown,evidence_refs,perspective_ids,quality_caveats}.
The bottom_line must explicitly state the belief update, confidence boundary, and immediate
project/idea/experiment implication. actionable_next_questions must put the single highest expected
information-value evidence first. Any worker Markdown is advisory only; the final director page and
its typed artifact are rendered and linted deterministically from all panel structures. Keep the research
brief's saturation_reached compatibility field false; search completion is derived elsewhere. For a
novelty question, distinguish exact collision, partial prior, enabling base, gap source, orthogonal
work, and unresolved uncertainty, and state what the closest paper did, did not do, and what
falsifiable delta survives. Never convert missing full text into a novelty conclusion.
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
        logical = _bundle_path(run_dir, agent)
        try:
            p = resolve_effective_output(Path(run_dir), "DISCOVER", logical)
        except ValueError as exc:
            raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
        if not p.exists():
            if not (replay is not None and agent in {
                "citation-coverage-auditor", "evidence-search-moderator"
            }):
                missing.append(agent)
            continue
        raw[agent] = _load_json(p)
    if missing:
        raise GateBlock(f"deep_research DISCOVER missing worker bundle(s): {missing}")

    def take(agent: str, key: str, *, required: bool = True, default=None):
        source = raw.get(agent)
        if source is None:
            if required:
                raise GateBlock(
                    f"deep_research DISCOVER missing worker bundle for {agent}"
                )
            return default
        return _shared.extract_worker_bundle_value(
            source, key, stage="DISCOVER", mode="deep_research", agent=agent,
            required=required, default=default,
        )

    perspective_notes = []
    for agent, _pid, _angle in PERSPECTIVE_WORKERS:
        perspective_notes.append(take(agent, "research_perspective_note"))

    b = {
        "evidence_table": take("lit-scout", "evidence_table"),
        "source_quality_report": take("source-quality-ranker", "source_quality_report"),
        "perspective_notes": perspective_notes,
        "claim_list": take("claim-extractor", "claim_list"),
        "evidence_search_trace": take(
            "evidence-search-moderator", "evidence_search_trace",
            required=replay is None, default=None,
        ),
        "claim_evidence_map": take("claim-evidence-linker", "claim_evidence_map"),
        "citation_audit": take(
            "citation-coverage-auditor", "citation_audit",
            required=replay is None, default=None,
        ),
        "contradiction_report": take("contradiction-miner", "contradiction_report"),
        "research_brief": take("landscape-mapper", "research_brief"),
        "usage": take("landscape-mapper", "usage"),
        "research_markdown_brief": take(
            "landscape-mapper", "research_markdown_brief", required=False, default=None,
        ),
        "legacy_replay": replay is not None,
    }
    missing_keys = [
        k for k, v in b.items()
        if v is None and k != "research_markdown_brief"
    ]
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
        # Workers often describe an official foundation-model release as a
        # `model`.  The evidence schema classifies the citable object rather
        # than its subject, so an official model repository is a `repo`.
        # Normalize this representation-only label before schema validation;
        # otherwise a complete research panel is terminally failed for a
        # harmless vocabulary mismatch.
        "model": "repo",
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
    # Some otherwise well-grounded workers use the evidence table's local id
    # (`s1`) where the citation contract requires the row's citable `ref`.
    # The mapping is unique inside one frozen evidence table, so resolving it
    # is a representation-only normalization; unknown ids remain untouched and
    # still fail the citation gate.
    source_ref_by_id = {
        str(row.get("id")): str(row.get("ref"))
        for row in (b.get("evidence_table") or {}).get("sources") or []
        if row.get("id") and row.get("ref")
    }
    for row in (b.get("claim_list") or {}).get("claims") or []:
        row["kind"] = claim_kind.get(row.get("kind"), row.get("kind"))
        row["source_ref"] = source_ref_by_id.get(
            str(row.get("source_ref")), row.get("source_ref")
        )
    for mapping in (b.get("claim_evidence_map") or {}).get("mappings") or []:
        for locus in mapping.get("loci") or []:
            locus["source_ref"] = source_ref_by_id.get(
                str(locus.get("source_ref")), locus.get("source_ref")
            )
    for row in (b.get("contradiction_report") or {}).get("conflicts") or []:
        row["kind"] = conflict_kind.get(row.get("kind"), row.get("kind"))
        row["resolution_status"] = resolution.get(
            row.get("resolution_status"), row.get("resolution_status")
        )
    for note in b.get("perspective_notes") or []:
        if not isinstance(note, dict):
            continue
        confidence = note.get("confidence")
        if isinstance(confidence, dict):
            overall = str(confidence.get("overall") or "").casefold()
            note["confidence"] = "high" if overall.startswith("high") else (
                "low" if overall.startswith("low") else "medium"
            )
        if isinstance(note.get("finding_summary"), dict):
            rich_summary = note["finding_summary"]
            note["finding_summary"] = str(
                rich_summary.get("changed_belief")
                or rich_summary.get("project_implication")
                or json.dumps(rich_summary, ensure_ascii=False, sort_keys=True)
            )
        elif isinstance(note.get("finding_summary"), list):
            note["finding_summary"] = " ".join(str(item) for item in note["finding_summary"])
        for field in ("actionable_opportunities", "kill_criteria"):
            values = note.get(field)
            if isinstance(values, list):
                note[field] = [
                    value if isinstance(value, str) else json.dumps(
                        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                    for value in values
                ]
        refs = note.get("source_refs")
        if isinstance(refs, list):
            note["source_refs"] = [
                str(value.get("source_ref") or value.get("ref") or "")
                if isinstance(value, dict) else str(value)
                for value in refs
            ]


def _data_descendants(agent: str) -> list[str]:
    impacted = set()
    frontier = {agent}
    while frontier:
        current = frontier.pop()
        for candidate, dependencies in DEEP_RESEARCH_DEPENDENCIES.items():
            if current in dependencies and candidate not in impacted:
                impacted.add(candidate)
                frontier.add(candidate)
    impacted.discard(agent)
    return [candidate for candidate in PANEL_AGENTS if candidate in impacted]


def _validate_payloads(run_dir, b: dict) -> dict:
    _normalize_compat_enums(b)
    # Normalize every typed worker payload before scientific gates consume it.
    # Original bundles stay immutable; richer fields are hash-bound in
    # inbox/normalization sidecars and the canonical projection is what reaches
    # evidence/.  This is a zero-worker representation repair.
    plan = (
        ("evidence_table", "evidence_table", "lit-scout"),
        ("source_quality_report", "source_quality_report", "source-quality-ranker"),
        ("evidence_search_trace", "evidence_search_trace", "evidence-search-moderator"),
        ("claim_list", "claim_list", "claim-extractor"),
        ("claim_evidence_map", "claim_evidence_map", "claim-evidence-linker"),
        ("contradiction_report", "contradiction_report", "contradiction-miner"),
        ("research_brief", "research_brief", "landscape-mapper"),
    )
    errors = []
    defects = []
    reports = []
    for atype, key, agent in plan:
        if b.get("legacy_replay") and b.get(key) is None:
            continue
        normalized, item_errors, report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", agent, atype, b.get(key), label=key,
        )
        b[key] = normalized
        reports.append(report)
        for e in item_errors:
            errors.append(f"{key}: {e}")
        if item_errors:
            defects.append({
                "defect_id": f"deep-research-schema-{key.replace('_', '-')}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/{key}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": [agent],
                "refresh_agents": _data_descendants(agent),
            })
    perspective_agent = {pid: agent for agent, pid, _angle in PERSPECTIVE_WORKERS}
    for i, note in enumerate(b.get("perspective_notes") or [], start=1):
        pid = str((note or {}).get("perspective_id") or f"P{i}") if isinstance(note, dict) else f"P{i}"
        agent = perspective_agent.get(pid, PERSPECTIVE_WORKERS[min(i - 1, 3)][0])
        normalized, item_errors, report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", agent, "research_perspective_note", note,
            label=f"research-perspective-{pid}",
        )
        b["perspective_notes"][i - 1] = normalized
        reports.append(report)
        for e in item_errors:
            errors.append(f"perspective_notes[{i}]: {e}")
        if item_errors:
            defects.append({
                "defect_id": f"deep-research-schema-perspective-{pid}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/perspective_notes/{i}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": [agent],
                "refresh_agents": _data_descendants(agent),
            })
    if errors:
        raise TargetedGateBlock(
            f"deep_research payload needs a local supplement after automatic normalization: {errors}",
            defects,
        )
    return {
        "normalized_payloads": sum(
            1 for report in reports
            if report.get("changes") or report.get("preserved_extras")
        ),
        "format_changes": sum(len(report.get("changes") or []) for report in reports),
        "preserved_extra_fields": sum(
            len(report.get("preserved_extras") or []) for report in reports
        ),
    }


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
            raise TargetedGateBlock(
                f"search trace source(s) outside evidence table: {outside_trace}",
                [{
                    "defect_id": "deep-research-unfrozen-search-hit",
                    "location": "DISCOVER/evidence-search-trace",
                    "summary": "Freeze, assess, and include each discovered literature source in the "
                               "evidence table before using it in the search trace.",
                    "target_agents": ["lit-scout", "source-quality-ranker", "evidence-search-moderator"],
                    "refresh_agents": [
                        "model-dataset-scout", "future-work-miner", "cross-domain-transfer-scout",
                        "weakness-spotter", "claim-extractor", "claim-evidence-linker",
                        "citation-coverage-auditor", "contradiction-miner", "landscape-mapper",
                    ],
                }],
            )

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
    normalization = _validate_payloads(run_dir, b)
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
    evidence_reasons = list(ev.get("reasons") or [])
    strength_shortfall_only = bool(evidence_reasons) and all(
        str(reason).startswith("too few strong-support sources")
        for reason in evidence_reasons
    )
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "draft" if legacy or (
                                    ev["verdict"] == "BLOCK" and strength_shortfall_only
                                ) else
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK" and not legacy and not strength_shortfall_only:
        raise TargetedGateBlock(
            f"evidence gate BLOCK: {evidence_reasons}",
            [{
                "defect_id": "deep-research-evidence-input",
                "location": "DISCOVER/evidence-table + source-quality + search-trace",
                "summary": "Refresh the frozen source set, methodology assessment, and search trace; "
                           "then refresh every dependent synthesis bundle.",
                "target_agents": ["lit-scout", "source-quality-ranker", "evidence-search-moderator"],
                "refresh_agents": [
                    "model-dataset-scout", "future-work-miner", "cross-domain-transfer-scout",
                    "weakness-spotter", "claim-extractor", "claim-evidence-linker",
                    "citation-coverage-auditor", "contradiction-miner", "landscape-mapper",
                ],
            }],
        )
    # A source-strength shortfall is an important scientific boundary, but it
    # is not a reason to discard a fully attributed literature landscape.  In
    # particular, an exploratory research question may deliberately target a
    # gap for which no existing paper directly proves the proposed mechanism.
    # Preserve the deterministic BLOCK verdict for promotion/downstream
    # contracts, then deliver the brief with an explicit caveat.  Citation,
    # attribution, integrity, and execution failures remain fail-closed below.
    evidence_block = ev["verdict"] == "BLOCK" and not legacy

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
        "representation_normalization": normalization,
    }
    if evidence_block:
        report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
        report["evidence_gate_reasons"] = list(ev.get("reasons") or [])
    render_caveats = []
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
        render_caveats.append(f"deterministic Markdown fallback used: {exc}")

    markdown_advisory_path = (
        Path(run_dir) / "inbox" / "deep_research-markdown-quality-advisory.json"
    )
    if markdown_advisory_path.is_file():
        markdown_advisory = _load_json(markdown_advisory_path)
        advisory_warnings = [
            str(row) for row in markdown_advisory.get("warnings") or []
            if str(row).strip()
        ]
        render_caveats.extend(advisory_warnings)
        if markdown_advisory.get("delivery_status") == "USABLE_WITH_CAVEATS":
            report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
    if evidence_block:
        render_caveats.extend(str(row) for row in ev.get("reasons") or [])

    rendered_markdown = Path(report["director_markdown_brief"]).read_text(encoding="utf-8")
    evidence_refs = list(dict.fromkeys(
        str(source.get("ref") or "").strip()
        for source in et.get("sources") or []
        if str(source.get("ref") or "").strip()
    ))
    if not evidence_refs:
        evidence_refs = list(dict.fromkeys(
            str(ref).strip()
            for ref in brief.get("evidence_ref") or []
            if str(ref).strip()
        ))
    perspective_ids = list(dict.fromkeys(
        str(note.get("perspective_id") or "").strip()
        for note in b["perspective_notes"]
        if str(note.get("perspective_id") or "").strip()
    ))
    markdown_payload = {
        "topic": str(brief.get("topic") or et.get("query") or "deep research brief"),
        "markdown": rendered_markdown,
        "evidence_refs": evidence_refs,
        "perspective_ids": perspective_ids,
        "quality_caveats": list(dict.fromkeys(render_caveats)),
    }
    paths.append(write_artifact(
        run_dir, "DISCOVER", "research-markdown-brief.artifact.json",
        "research_markdown_brief", "deterministic-research-brief-renderer",
        markdown_payload, ts, "draft" if legacy else "approved",
    ))
    return paths, report


def _report(run_dir, ts) -> tuple:
    verdict_path = Path(run_dir) / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json"
    verdict = _load_json(verdict_path) if verdict_path.is_file() else {}
    verdict_payload = verdict.get("payload") or {}
    evidence_block = str(verdict_payload.get("verdict") or "") == "BLOCK"
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
        "delivery_status": "USABLE_WITH_CAVEATS" if evidence_block else "USABLE",
        "delivery_caveats": list(verdict_payload.get("reasons") or []) if evidence_block else [],
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
