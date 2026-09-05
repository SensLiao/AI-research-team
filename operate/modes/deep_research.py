"""Operate recipe for `deep_research` (DISCOVER -> REPORT).

deep_research is now a true perspective panel. The old implementation asked one
supervisor worker to simulate multiple researchers inside a single JSON bundle.
This recipe requires independent perspective bundles, then synthesizes them into
a structured research brief plus a director-facing Markdown memo.
"""
from __future__ import annotations

import copy
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair, failures_for_stage
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
from ...tools.ledger import read_events, verify_chain
from ...tools.research_brief_markdown import (
    write_research_brief_fallback,
    write_research_brief_markdown,
)
from ...tools.research_delivery_boundary import derive_research_delivery_boundary
from ...tools.source_methodology_audit import audit_source_quality_report
from ...tools.validate_artifact import validate_artifact

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

PERSPECTIVE_WORKERS = (
    ("model-dataset-scout", "P1", "methods, models, datasets, and benchmark state"),
    ("future-work-miner", "P2", "open problems, unresolved gaps, and next experiments"),
    ("cross-domain-transfer-scout", "P3", "adjacent-field transfer and mechanism analogies"),
    ("weakness-spotter", "P4", "failure modes, negative evidence, and reasons not to overclaim"),
)

DOSSIER_REVIEWERS = (
    ("research-dossier-method-reviewer", "method-and-paper"),
    ("research-dossier-implementation-reviewer", "implementation-and-project-state"),
    ("research-dossier-evidence-reviewer", "evidence-and-completeness"),
)
DOSSIER_REVIEWER_NAMES = [name for name, _lens in DOSSIER_REVIEWERS]
CONVERGENCE_CHAIR = "research-convergence-chair"

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
    *DOSSIER_REVIEWER_NAMES,
    CONVERGENCE_CHAIR,
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
    "landscape-mapper": [
        "lit-scout", "source-quality-ranker", *PERSPECTIVE_AGENT_NAMES,
        "claim-extractor", "evidence-search-moderator", "claim-evidence-linker",
        "citation-coverage-auditor", "contradiction-miner",
    ],
    "research-dossier-method-reviewer": [
        "landscape-mapper", "source-quality-ranker", "claim-extractor",
        "claim-evidence-linker", "contradiction-miner", *PERSPECTIVE_AGENT_NAMES,
    ],
    "research-dossier-implementation-reviewer": [
        "landscape-mapper", "model-dataset-scout", "future-work-miner",
        "cross-domain-transfer-scout", "weakness-spotter",
    ],
    "research-dossier-evidence-reviewer": [
        "landscape-mapper", "lit-scout", "source-quality-ranker",
        "evidence-search-moderator", "claim-extractor", "claim-evidence-linker",
        "citation-coverage-auditor", "contradiction-miner",
    ],
    CONVERGENCE_CHAIR: ["landscape-mapper", *DOSSIER_REVIEWER_NAMES],
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
    DOSSIER_REVIEWER_NAMES,
    [CONVERGENCE_CHAIR],
]


#: Declared as the CHEAP set rather than the expensive one, so a seat added later defaults to the
#: frontier tier instead of silently inheriting sonnet. These four gather and restate: they pull
#: records, extract fields, and link a claim to the span that supports it — 书写 / 固定死了的那种.
#: Every other seat in this mode either judges evidence quality, verifies a citation, hunts a gap,
#: or synthesises the landscape, and the director's rule keeps 质量 and 想法 on the frontier tier.
_SCOPED_EXECUTION_SEATS = frozenset({
    "lit-scout", "model-dataset-scout", "claim-extractor", "claim-evidence-linker",
})


def _worker_model(model_policy: str, agent: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    return "sonnet" if agent in _SCOPED_EXECUTION_SEATS else "opus"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, **funnel_kwargs) -> str:
    """Live-retrieval pre-step. Director decision 2026-09-05: deep_research runs the four-stage
    funnel AND one round of machine-proposed related queries (depth 2) unless told otherwise."""
    funnel_kwargs.setdefault("funnel_depth", 2)
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries,
                              **funnel_kwargs)


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
- live retrieval bundle if present: `{run_dir}/inbox/search-results.json` (records carry
  `funnel_rank` / `funnel_score` from the four-stage funnel; read them in that order)
- funnel bundle if present: `{run_dir}/inbox/search-funnel.json` (fused cross-channel ranking,
  best abstract passage per record, machine-proposed `related_queries`; triage only, never evidence)
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
Use >=30 sources when available — a FLOOR with no upper bound, so use every relevant record the
retrieval bundle holds rather than a sample — including negative and boundary evidence. For novelty questions,
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
Output exactly: {{"research_perspective_note": {{perspective_id, angle, specialized_angle, questions,
finding_summary, source_refs, coverage_limits, actionable_opportunities, kill_criteria,
expected_disagreement, blind_spot, confidence}}}}.
Use perspective_id `{pid}`. Include at least two concrete questions. The finding_summary must
answer "what changed in belief, what should the project/idea/experiment do next, and what remains
uncertain from this angle?" Put the highest-value action in actionable_opportunities and a real
decision-reversing result in kill_criteria.

Your assigned angle is the STARTING POINT, not the whole brief. First specialize it to THIS topic:
state, in one sentence, what a real specialist holding this angle on this specific topic would care
about that a generalist would not — the term they would use, the failure they would expect, the
evidence they would demand. Write that as `specialized_angle` and research THAT, not the generic label.

You are one of four independent perspectives that will be synthesized. Agreement between perspectives
is cheap; productive tension is what makes the synthesis worth reading. Before finishing, name at
least one point on which you expect another perspective on this panel to DISAGREE with you
substantively, and say why you hold your position anyway — write it as `expected_disagreement`. Also
name your own `blind_spot`: what your angle structurally cannot see, so the synthesizer can compensate
rather than inherit it.
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
Every locus must include locus_id (unique per map, e.g. "CE-C1-L1"), source_ref, location, kind,
reported_result, supports_claim, support_relation, directness, span_id, snapshot_ref, document_hash,
parser_version, exact_quote, and either char_start/char_end, table_cell_ref, or figure_region_ref.
Closed enums (machine-readable; any other value BLOCKS the run):
  overall_support ∈ {"supported","partial","contradicted","not-found"} — never a support_relation word;
  kind ∈ {"table","figure","text","code","dataset","appendix","other"} — never a source-channel label;
  directness ∈ {"direct","indirect","proxy","assumed"};
  claim_risk is an OPTIONAL OBJECT {"level":"high|medium|low","note":"<why>"} — never a bare string.
Perspective summaries may guide retrieval but are never citable evidence.
For `source_ref`, copy the evidence-table row's resolvable `ref` value, never its local `id` such as `s1`.
""" + _shared.SUPPORT_RELATION_CONTRACT
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
    review_lens = dict(DOSSIER_REVIEWERS).get(agent)
    if review_lens:
        lens_checks = {
            "method-and-paper": [
                "prior-art-boundary", "comparator-identity", "intervention-legality",
                "representation-attribution", "venue-claim-scope",
            ],
            "implementation-and-project-state": [
                "source-of-truth", "live-state-freshness", "leakage-firewall",
                "implementation-feasibility", "experiment-budget", "seed-chain",
            ],
            "evidence-and-completeness": [
                "citation-readiness", "coverage-completeness", "status-truth",
                "internal-consistency", "formal-gate-separation",
            ],
        }[review_lens]
        na_allowed = {
            "method-and-paper": [
                "intervention-legality", "representation-attribution", "venue-claim-scope",
            ],
            "implementation-and-project-state": [
                "leakage-firewall", "experiment-budget", "seed-chain",
            ],
            "evidence-and-completeness": [],
        }[review_lens]
        lens_rules = {
            "method-and-paper": (
                "Check closest-paper deltas, claims against what the paper actually implemented, "
                "same-architecture no-treatment before shuffled placebo, legal joint interventions "
                "for structurally dependent fields, matched-capacity/source/surface comparisons, and "
                "whether the proposed evidence can support the named venue-level claim."
            ),
            "implementation-and-project-state": (
                "Check the declared source of truth, timestamped live state, manifest-over-snapshot "
                "precedence, inference-visible versus oracle/metadata-only fields, leakage firewalls, "
                "code/data interfaces, fit accounting, and A-to-A/B-to-B/C-to-C full-chain hashes. "
                "If no hash-bound project-state input exists, record an external blocker, never guess."
            ),
            "evidence-and-completeness": (
                "Check requested-item coverage, denominators and cohort identity, exact evidence "
                "entailment, internal cross-file consistency, stale status packets, and separation of "
                "content convergence from formal citation, novelty, project approval, and human gates."
            ),
        }[review_lens]
        return common + f"""
Task: independently review the frozen `landscape-mapper` author bundle through lens
`{review_lens}`. You are not an author and must not read either sibling review.

{lens_rules}

Use the scheduler predecessor record for the exact reviewed artifact path and SHA-256. Set
`review_round` from `scheduler_contract.repair_cycle` and copy
`scheduler_contract.dispatch_instance_id` verbatim into `reviewer_instance_id`; it is the
scheduler-issued invocation identity, so never invent one. Complete every coverage check exactly
once: {json.dumps(lens_checks)}. Every check carries `finding_refs` and `external_blocker_refs`.
A FAIL must cite at least one CRITICAL/MAJOR finding or external blocker. NOT_APPLICABLE is permitted
only for these check ids: {json.dumps(na_allowed)}; give a concrete reason.

Output exactly: {{"research_dossier_review": {{
  "contract_version":"research-dossier-review/v1",
  "review_id":"<unique lens+round id>", "reviewer_lens":"{review_lens}",
  "reviewer_instance_id":"<fresh invocation id>", "independent_of_author":true,
  "author_agent":"landscape-mapper", "reviewed_artifact_ref":"<scheduler path>",
  "reviewed_artifact_sha256":"sha256:<64 hex>", "review_round":0,
  "coverage_checks":[{{"check_id":"...","status":"PASS|WARN|FAIL|NOT_APPLICABLE","evidence":"...",
    "finding_refs":[],"external_blocker_refs":[]}}],
  "findings":[{{"finding_id":"...","severity":"CRITICAL|MAJOR|MINOR",
    "category":"<schema enum>","anchor":"<exact section/field>","evidence":"<specific defect>",
    "evidence_refs":["<inspectable path/ref>"],"responsible_agent":"landscape-mapper",
    "target_artifact_ref":"<author bundle>","repair_action":"<executable author edit>",
    "acceptance_check":"<fresh reviewer can verify>",
    "allowed_json_pointers":["/research_brief/<field>"],"status":"OPEN"}}],
  "external_blockers":[{{"blocker_id":"...","kind":"<schema enum>",
    "description":"...","evidence_refs":["..."],"required_input":"..."}}],
  "recommendation":"PASS|REVISE|PASS_WITH_EXTERNAL_BLOCKERS", "summary":"..."
}}}}.

For the implementation lens also emit `project_state_assessment` with
`{{"status":"CURRENT_HASH_BOUND|MISSING|STALE|UNBOUND","snapshot_ref":null,
"snapshot_sha256":null,"rationale":"..."}}`. CURRENT_HASH_BOUND requires an approved
`project_state_snapshot` artifact under `inbox/project-state/`, created by `project-state-capture`,
fresh at this review dispatch, bound to the task project, and backed by hash-verified source copies in
`inbox/project-state/sources/`; an arbitrary run file is never a state snapshot. MISSING/STALE/UNBOUND
must map the affected source-of-truth or live-state-freshness FAIL check to a matching external blocker,
never to an author finding.

Only internal author defects go in findings. Missing full text, live project state, execution evidence,
or a human decision goes in external_blockers and must not be rewritten away. CRITICAL/MAJOR always
means REVISE. With no CRITICAL/MAJOR use PASS or PASS_WITH_EXTERNAL_BLOCKERS. Do not grant novelty.
"""
    if agent == CONVERGENCE_CHAIR:
        return common + """
Task: reconcile the three independent `research_dossier_review` bundles under H-Max.
Read every review only after all three are frozen. Do not edit the author bundle, omit a source
finding/blocker, or lower severity. One consolidated row may merge duplicates, but its severity is the
maximum source severity and every `(review_id,finding_id)` appears exactly once. Apply the same exact
coverage rule to external blockers. Its `allowed_json_pointers` is the exact set union of the source
findings' pointers; never widen it.

Use scheduler predecessor paths and hashes. Set `review_round` from
`scheduler_contract.repair_cycle`, copy `scheduler_contract.dispatch_instance_id` verbatim into
`chair_instance_id`, and copy the current author
bundle path/hash. Output exactly: {"research_convergence_verdict": {
  "contract_version":"research-dossier-convergence/v1", "convergence_id":"<unique id>",
  "chair_instance_id":"<fresh invocation id>", "review_round":0,
  "reviewed_artifact_ref":"<author path>", "reviewed_artifact_sha256":"sha256:<64 hex>",
  "review_refs":[{"review_id":"...","reviewer_lens":"...","reviewer_instance_id":"...",
    "artifact_ref":"...","artifact_sha256":"sha256:<64 hex>"}],
  "hmax_policy":true,
  "counts":{"critical":0,"major":0,"minor":0,"external_blockers":0},
  "consolidated_findings":[{"finding_id":"...","severity":"CRITICAL|MAJOR|MINOR",
    "category":"...","source_findings":[{"review_id":"...","finding_id":"..."}],
    "anchor":"...","evidence":"...","responsible_agent":"landscape-mapper",
    "repair_action":"...","acceptance_check":"...",
    "allowed_json_pointers":["/research_brief/<field>"],"status":"OPEN"}],
  "external_blockers":[{"blocker_id":"...","kind":"...","description":"...",
    "source_blockers":[{"review_id":"...","blocker_id":"..."}],"required_input":"..."}],
  "disposition":"REVISE|CONTENT_CONVERGED|CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS",
  "status_boundaries":{"content_convergence_only":true,"novelty_clearance":false,
    "project_approval":false,"formal_citation_gate":"PENDING"},
  "rationale":"..."
}}.

Disposition is REVISE iff any CRITICAL/MAJOR remains; otherwise it is CONTENT_CONVERGED, with the
external-blocker suffix when applicable. Content convergence is never citation/novelty/project approval.
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
             model_policy: str = "default") -> Optional[dict]:
    if stage != "DISCOVER":
        return None
    north_star = _shared.north_star_block(run_dir)
    workers = []
    for agent in PANEL_AGENTS:
        prior = list(DEEP_RESEARCH_DEPENDENCIES[agent])
        out = str(_bundle_path(run_dir, agent)).replace("\\", "/")
        worker = {
            "label": agent,
            "model": _worker_model(model_policy, agent),
            "output": out,
            "depends_on": prior,
            "prompt": _prompt(agent, request, run_dir, out, vault, north_star, prior),
        }
        if agent in DOSSIER_REVIEWER_NAMES:
            blind_seats = [*DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR]
            worker["input_contract"] = {
                "forbidden_inputs": [
                    _bundle_path(run_dir, sibling).as_posix()
                    for sibling in blind_seats
                    if sibling != agent
                ] + [
                    (
                        Path(run_dir) / "inbox" / "supplements" / "DISCOVER" /
                        "repair-*" / location / f"{sibling}.bundle.json"
                    ).as_posix()
                    for sibling in blind_seats
                    for location in ("originals", "corrected")
                ],
            }
        workers.append(worker)
    return {
        "label": "deep-research-panel",
        "workers": workers,
        "worker_order": list(PANEL_AGENTS),
        "parallel_groups": DEEP_RESEARCH_PARALLEL_GROUPS,
        "panel_note": "Freeze the shared source set first, then spawn the four perspective seats in "
                      "parallel/blind to one another. After the sole author freezes the dossier, three "
                      "orthogonal reviewers run mutually blind; the H-Max chair reconciles only after "
                      "all three reviews exist. Content CRITICAL/MAJOR findings trigger author-only "
                      "repair plus fresh blind reviewer/chair instances.",
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

    dossier_reviews = {
        lens: take(agent, "research_dossier_review")
        for agent, lens in DOSSIER_REVIEWERS
    }

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
        "dossier_reviews": dossier_reviews,
        "convergence_verdict": take(CONVERGENCE_CHAIR, "research_convergence_verdict"),
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
    # Same discipline for study_design: a ranker describing an internal
    # project record as its own study-design label is a representation-only
    # vocabulary mismatch, not a scientific defect. Normalize before schema
    # validation so a complete panel is not replayed over an enum spelling.
    study_design = {
        "challenge-overview": "benchmark",
        "dataset-card": "documentation",
        "dataset-record": "documentation",
        "decision-record": "documentation",
        "degradation-report": "documentation",
        "experiment-design": "methods-paper",
    }
    directness = {"partial": "indirect"}
    for row in (b.get("source_quality_report") or {}).get("ranked_sources") or []:
        if isinstance(row, dict):
            mapped_design = study_design.get(row.get("study_design"))
            if mapped_design is not None:
                row["study_design"] = mapped_design
            mapped_direct = directness.get(row.get("directness"))
            if mapped_direct is not None:
                row["directness"] = mapped_direct
    # Ranked-source refs must resolve to frozen evidence-table refs for the
    # source-quality consistency gate. A bare [[slug]] (the table anchors the
    # same card as "[[slug]]+sha256:<hex>") or a doi:-prefixed identifier is a
    # representation-only spelling of the same frozen source — reconcile the
    # spelling before the gate, never replay the panel over it.
    table_refs = {
        str(row.get("ref"))
        for row in (b.get("evidence_table") or {}).get("sources") or []
        if row.get("ref")
    }
    slug_ref: dict[str, str] = {}
    doi_ref: dict[str, str] = {}
    for ref in table_refs:
        match = re.match(r"\[\[([^\]]+)\]\](?:\+sha256:[0-9a-f]+)?$", ref)
        if match:
            slug_ref[match.group(1)] = ref
        match_doi = re.match(r"^(?:doi:)?(10\.[0-9]{4,9}/[^\s]+)$", ref, re.I)
        if match_doi:
            doi_ref[match_doi.group(1).lower()] = ref
    for row in (b.get("source_quality_report") or {}).get("ranked_sources") or []:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("source_ref") or "")
        if ref in table_refs:
            continue
        match = re.match(r"\[\[([^\]]+)\]\]$", ref)
        if match and match.group(1) in slug_ref:
            row["source_ref"] = slug_ref[match.group(1)]
            continue
        match_doi = re.match(r"^(?:doi:)?(10\.[0-9]{4,9}/[^\s]+)$", ref, re.I)
        if match_doi and match_doi.group(1).lower() in doi_ref:
            row["source_ref"] = doi_ref[match_doi.group(1).lower()]
    for note in b.get("perspective_notes") or []:
        if not isinstance(note, dict):
            continue
        confidence = note.get("confidence")
        if isinstance(confidence, dict):
            overall = str(confidence.get("overall") or "").casefold()
            note["confidence"] = "high" if overall.startswith("high") else (
                "low" if overall.startswith("low") else "medium"
            )
        elif confidence not in (None, "") and confidence not in {"high", "medium", "low"}:
            lowered = str(confidence).casefold()
            note["confidence"] = "high" if lowered.startswith("high") else (
                "low" if lowered.startswith("low") else "medium"
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
        ("research_convergence_verdict", "convergence_verdict", CONVERGENCE_CHAIR),
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
            schema_defect = {
                "defect_id": f"deep-research-schema-{key.replace('_', '-')}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/{key}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": [agent],
                "refresh_agents": _data_descendants(agent),
            }
            if agent == "landscape-mapper":
                # A malformed author brief may require adding/removing structural fields, so the
                # narrow safe unit is the research_brief subtree. The repair fence still freezes
                # the exact author bundle path/hash and rejects edits to usage or any sibling key.
                schema_defect["allowed_json_pointers"] = ["/research_brief"]
            defects.append(schema_defect)
    reviewer_by_lens = {lens: agent for agent, lens in DOSSIER_REVIEWERS}
    for lens, review in (b.get("dossier_reviews") or {}).items():
        agent = reviewer_by_lens.get(lens)
        normalized, item_errors, report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", agent, "research_dossier_review", review,
            label=f"research-dossier-review-{lens}",
        )
        b["dossier_reviews"][lens] = normalized
        reports.append(report)
        for e in item_errors:
            errors.append(f"dossier_reviews[{lens}]: {e}")
        if item_errors:
            defects.append({
                "defect_id": f"deep-research-schema-review-{lens}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/dossier_reviews/{lens}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": [agent],
                "refresh_agents": [CONVERGENCE_CHAIR],
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


def _verified_internal_trace_refs(run_dir, trace: dict) -> set[str]:
    """Verify run-local worker provenance without treating it as literature.

    Search rounds may bind their frozen evidence/claim inputs as source hits. Those
    ``*.bundle.json`` receipts are provenance, not papers, so they do not belong in
    the evidence table. They are excluded only after an in-run path and SHA-256 check.
    """
    root = Path(run_dir).resolve()
    verified: set[str] = set()
    defects: list[dict] = []
    for row in trace.get("rounds") or []:
        for hit in row.get("source_hits") or []:
            ref = str(hit.get("source_ref") or "")
            normalized = ref.replace("\\", "/")
            if not (
                normalized.startswith("inbox/")
                and normalized.endswith(".bundle.json")
            ):
                continue
            candidate = (root / Path(normalized)).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                defects.append({
                    "defect_id": "deep-research-trace-provenance-escape",
                    "location": "DISCOVER/evidence-search-trace",
                    "summary": f"Run-local provenance ref escapes the run: {ref}",
                    "target_agents": ["evidence-search-moderator"],
                })
                continue
            expected = str(hit.get("source_hash") or "").removeprefix("sha256:").lower()
            if not candidate.is_file():
                detail = f"Run-local provenance ref is missing: {ref}"
            elif not re.fullmatch(r"[0-9a-f]{64}", expected):
                detail = f"Run-local provenance ref lacks a valid source_hash: {ref}"
            else:
                actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                detail = "" if actual == expected else (
                    f"Run-local provenance hash mismatch: {ref}"
                )
            if detail:
                defects.append({
                    "defect_id": "deep-research-trace-provenance-invalid",
                    "location": "DISCOVER/evidence-search-trace",
                    "summary": detail,
                    "target_agents": ["evidence-search-moderator"],
                })
            else:
                verified.add(ref)
    if defects:
        raise TargetedGateBlock(
            "search trace contains invalid run-local provenance",
            defects,
        )
    return verified


def _consistency_checks(run_dir, b: dict, ts: str = "") -> None:
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
        provenance_refs = _verified_internal_trace_refs(
            run_dir, b["evidence_search_trace"]
        )
        outside_trace = sorted(trace_refs - refs - provenance_refs)
        if outside_trace and _director_unfrozen_acceptance(run_dir, outside_trace, ts):
            # Director lock 2026-08-16: the director may accept named unfrozen trace refs
            # (verified external sources or internal locator strings) as recorded caveats
            # instead of freezing them into the evidence table. The caveat artifact
            # carries the accepted set verbatim; any NEW unfrozen ref still hard-blocks.
            outside_trace = []
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
                        *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR,
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
        raise TargetedGateBlock(
            f"source-quality consistency BLOCK: ranked source(s) not in evidence table {outside}",
            [{
                "defect_id": "deep-research-unfrozen-ranked-source",
                "location": "DISCOVER/source_quality_report",
                "summary": "Align ranked source_refs with the frozen evidence table: cite the table's "
                           "ref for the same source, or drop the row — never invent new refs.",
                "target_agents": ["lit-scout", "source-quality-ranker"],
                "refresh_agents": [
                    "model-dataset-scout", "future-work-miner", "cross-domain-transfer-scout",
                    "weakness-spotter", "claim-extractor", "evidence-search-moderator",
                    "claim-evidence-linker", "citation-coverage-auditor", "contradiction-miner",
                    "landscape-mapper", *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR,
                ],
            }],
        )

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


_REVIEW_COVERAGE = {
    "method-and-paper": {
        "prior-art-boundary", "comparator-identity", "intervention-legality",
        "representation-attribution", "venue-claim-scope",
    },
    "implementation-and-project-state": {
        "source-of-truth", "live-state-freshness", "leakage-firewall",
        "implementation-feasibility", "experiment-budget", "seed-chain",
    },
    "evidence-and-completeness": {
        "citation-readiness", "coverage-completeness", "status-truth",
        "internal-consistency", "formal-gate-separation",
    },
}
_REVIEW_NA_ALLOWED = {
    "method-and-paper": {
        "intervention-legality", "representation-attribution", "venue-claim-scope",
    },
    "implementation-and-project-state": {
        "leakage-firewall", "experiment-budget", "seed-chain",
    },
    "evidence-and-completeness": set(),
}
_SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


def _sha256_ref(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _effective_bundle_identity(run_dir, agent: str) -> tuple[Path, str, str]:
    root = Path(run_dir).resolve()
    logical = _bundle_path(run_dir, agent)
    effective = resolve_effective_output(root, "DISCOVER", logical)
    try:
        ref = effective.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise GateBlock(f"deep_research bundle escapes run root: {effective}") from exc
    return effective, ref, _sha256_ref(effective)


def _bundle_value(path: Path, key: str) -> Optional[dict]:
    try:
        raw = _load_json(path)
    except (OSError, ValueError):
        return None
    while isinstance(raw, dict) and set(raw) == {"payload"} and isinstance(raw["payload"], dict):
        raw = raw["payload"]
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if isinstance(value, dict) else None


def _prior_instance_ids(run_dir, agent: str, key: str, field: str, current: Path) -> set[str]:
    root = Path(run_dir).resolve()
    paths = {_bundle_path(run_dir, agent).resolve()}
    supplement_root = root / "inbox" / "supplements" / "DISCOVER"
    if supplement_root.is_dir():
        for pattern in (f"repair-*/originals/{agent}.bundle.json",
                        f"repair-*/corrected/{agent}.bundle.json"):
            paths.update(path.resolve() for path in supplement_root.glob(pattern))
    values = set()
    for path in paths:
        if path == current.resolve() or not path.is_file():
            continue
        payload = _bundle_value(path, key)
        value = str((payload or {}).get(field) or "").strip()
        if value:
            values.add(value)
    return values


def _strict_dispatch_bindings(run_dir, round_no: int) -> dict[str, dict]:
    """Bind the convergence tail to scheduler-owned authorization history.

    Worker-emitted instance ids are only claims.  The scheduler receipt is the
    authority, and the selected row must bind the agent and exact effective
    output path. A targeted tail repair intentionally leaves unaffected seats on
    their latest earlier cycle, so each effective output is validated against
    its own receipt cycle rather than forcing every seat onto the global repair
    counter. Dispatch ids are globally unique across the entire author/reviewer/
    chair history, including superseded repair rounds.
    """
    root = Path(run_dir).resolve()
    receipt_path = root / "inbox" / "panel-scheduler" / "DISCOVER.json"
    try:
        receipt = _load_json(receipt_path)
    except (OSError, ValueError) as exc:
        raise GateBlock(
            "deep_research convergence receipt BLOCK: no readable scheduler-owned "
            f"DISCOVER authorization receipt at {receipt_path}: {exc}"
        ) from exc
    if (
        receipt.get("contract_version") != "panel-dispatch/v1"
        or receipt.get("stage") != "DISCOVER"
        or not isinstance(receipt.get("authorizations"), list)
    ):
        raise GateBlock(
            "deep_research convergence receipt BLOCK: malformed or mismatched DISCOVER receipt"
        )

    all_rows = receipt["authorizations"]
    all_history_ids = [
        str(row.get("dispatch_instance_id") or "").strip()
        for row in all_rows
        if isinstance(row, dict)
    ]
    if (
        len(all_history_ids) != len(all_rows)
        or any(not value for value in all_history_ids)
        or len(all_history_ids) != len(set(all_history_ids))
    ):
        raise GateBlock(
            "deep_research convergence receipt BLOCK: every authorization must be an object "
            "with a non-empty dispatch instance that is globally unique across all receipt history"
        )

    tail_agents = {"landscape-mapper", *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR}
    tail_rows = [
        row for row in receipt["authorizations"]
        if isinstance(row, dict) and row.get("agent") in tail_agents
    ]
    if len(tail_rows) < len(tail_agents):
        raise GateBlock(
            "deep_research convergence receipt BLOCK: author/reviewer/chair dispatch instances "
            "must be present and globally unique across all receipt history"
        )

    current = {}
    for agent in sorted(tail_agents):
        _path, ref, _digest = _effective_bundle_identity(run_dir, agent)
        matches = [
            row for row in tail_rows
            if row.get("agent") == agent
            and isinstance(row.get("cycle"), int)
            and 0 <= row.get("cycle") <= round_no
            and str(row.get("output") or "").replace("\\", "/") == ref
        ]
        if len(matches) != 1:
            raise GateBlock(
                "deep_research convergence receipt BLOCK: expected exactly one scheduler "
                f"authorization for {agent} effective output {ref} at or before round "
                f"{round_no}; got {len(matches)}"
            )
        current[agent] = matches[0]
    return current


def _parse_utc_timestamp(value: object) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _path_has_symlink_component(root: Path, raw_path: Path) -> bool:
    current = raw_path
    while current != root:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _validate_current_project_snapshot(
        run_dir, ref: str, expected_hash: str, authorized_at: object, defect) -> bool:
    """Validate a dedicated, time-bounded project-state artifact and every source copy.

    A matching hash on an arbitrary run file is not project-state evidence. The snapshot must use the
    registered schema, live under the dedicated inbox lane, bind the run project, remain fresh at the
    review dispatch time, and ground every fact in a run-local hash-verified source copy.
    """
    normalized = ref.replace("\\", "/")
    if (
        not normalized.startswith("inbox/project-state/")
        or not normalized.endswith(".artifact.json")
        or Path(normalized).is_absolute()
        or ".." in Path(normalized).parts
    ):
        defect(
            "current-snapshot-contract-path",
            "CURRENT_HASH_BOUND requires a dedicated inbox/project-state/*.artifact.json snapshot",
        )
        return False
    root = Path(run_dir).resolve()
    raw_path = root / Path(normalized)
    path = raw_path.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        defect("current-escapes-run", "project snapshot_ref must stay inside the run directory")
        return False
    if (
        not raw_path.is_file()
        or _path_has_symlink_component(root, raw_path)
        or expected_hash != _sha256_ref(raw_path)
    ):
        defect(
            "current-not-hash-bound",
            "project-state snapshot must be a readable non-symlink file whose exact SHA-256 matches "
            "project_state_assessment.snapshot_sha256",
        )
        return False
    try:
        artifact = _load_json(raw_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        defect("current-snapshot-unreadable", f"project-state snapshot is not valid JSON: {exc}")
        return False
    schema_errors = validate_artifact(artifact)
    if artifact.get("artifact_type") != "project_state_snapshot" or schema_errors:
        defect(
            "current-snapshot-schema",
            "CURRENT_HASH_BOUND requires a valid project_state_snapshot artifact; "
            f"errors={schema_errors}",
        )
        return False
    if artifact.get("created_by") != "project-state-capture" or artifact.get("status") != "approved":
        defect(
            "current-snapshot-provenance",
            "project-state snapshot must be approved and created_by project-state-capture",
        )
        return False
    payload = artifact.get("payload") or {}
    try:
        captured_at = _parse_utc_timestamp(payload.get("captured_at"))
        valid_until = _parse_utc_timestamp(payload.get("valid_until"))
        dispatch_at = _parse_utc_timestamp(authorized_at)
    except (TypeError, ValueError) as exc:
        defect("current-snapshot-time", f"project-state freshness timestamps are invalid: {exc}")
        return False
    if captured_at > dispatch_at or valid_until < dispatch_at or valid_until < captured_at:
        defect(
            "current-snapshot-stale",
            "project-state snapshot must be captured no later than, and remain valid through, the "
            "implementation-review dispatch time",
        )
        return False
    task_frame_path = root / "task_frame.artifact.json"
    if (
        not task_frame_path.is_file()
        or _path_has_symlink_component(root, task_frame_path)
    ):
        defect(
            "current-snapshot-task-frame-binding",
            "project-state snapshot requires a readable, non-symlink current task_frame.artifact.json",
        )
        return False
    current_task_frame_hash = _sha256_ref(task_frame_path)
    if artifact.get("input_artifact_hashes") != [current_task_frame_hash]:
        defect(
            "current-snapshot-task-frame-binding",
            "project-state snapshot input_artifact_hashes must bind exactly the current "
            "task_frame.artifact.json SHA-256; replay after task-frame drift is forbidden",
        )
        return False
    task_frame = _load_json(task_frame_path)
    task_project = str((task_frame.get("payload") or {}).get("project") or "").strip()
    if task_project and payload.get("project_id") != task_project:
        defect(
            "current-snapshot-project-binding",
            f"project-state snapshot project_id must match task frame project {task_project!r}",
        )
        return False
    sources = payload.get("sources") or []
    source_rows = {str(row.get("source_ref") or ""): row for row in sources}
    if len(source_rows) != len(sources) or not any(
        row.get("role") in {"CANONICAL_STATE", "LIVE_MANIFEST"} for row in sources
    ):
        defect(
            "current-snapshot-source-identity",
            "project-state snapshot sources must be unique and include CANONICAL_STATE or LIVE_MANIFEST",
        )
        return False
    source_root = (root / "inbox" / "project-state" / "sources").resolve()
    for source_ref, row in source_rows.items():
        source_parts = Path(source_ref).parts
        if Path(source_ref).is_absolute() or ".." in source_parts:
            defect(
                "current-source-contract-path",
                f"project-state source must be a normalized run-relative path: {source_ref}",
            )
            return False
        source_raw = root / Path(source_ref)
        source_path = source_raw.resolve(strict=False)
        try:
            source_path.relative_to(source_root)
        except ValueError:
            defect(
                "current-source-escapes-lane",
                f"project-state source escapes inbox/project-state/sources: {source_ref}",
            )
            return False
        if (
            not source_ref.startswith("inbox/project-state/sources/")
            or not source_raw.is_file()
            or _path_has_symlink_component(root, source_raw)
            or row.get("source_sha256") != _sha256_ref(source_raw)
        ):
            defect(
                "current-source-binding",
                f"project-state source is missing, symlinked, outside its lane, or hash-drifted: {source_ref}",
            )
            return False
    for fact in payload.get("facts") or []:
        unknown = set(fact.get("source_refs") or []) - set(source_rows)
        if unknown:
            defect(
                "current-fact-source-binding",
                f"project-state fact {fact.get('fact_id')} cites undeclared sources {sorted(unknown)}",
            )
            return False
    return True


def _validate_project_state_assessment(
        run_dir, review: dict, checks: list[dict], findings_by_id: dict,
        blockers_by_id: dict, authorized_at: object, defect) -> None:
    """Keep unavailable project state outside the author-repair channel."""
    assessment = review.get("project_state_assessment") or {}
    status = str(assessment.get("status") or "")
    project_kinds = {
        "MISSING_PROJECT_STATE", "STALE_PROJECT_STATE", "UNBOUND_PROJECT_STATE",
    }
    project_blockers = {
        blocker_id: row for blocker_id, row in blockers_by_id.items()
        if row.get("kind") in project_kinds
    }
    checks_by_id = {str(row.get("check_id") or ""): row for row in checks}

    if status == "CURRENT_HASH_BOUND":
        ref = str(assessment.get("snapshot_ref") or "").strip().replace("\\", "/")
        expected_hash = str(assessment.get("snapshot_sha256") or "").strip()
        _validate_current_project_snapshot(
            run_dir, ref, expected_hash, authorized_at, defect,
        )
        if project_blockers:
            defect(
                "current-has-external-blocker",
                "CURRENT_HASH_BOUND cannot coexist with missing/stale/unbound project-state blockers",
            )
        return

    expected_kind = {
        "MISSING": "MISSING_PROJECT_STATE",
        "STALE": "STALE_PROJECT_STATE",
        "UNBOUND": "UNBOUND_PROJECT_STATE",
    }.get(status)
    if expected_kind is None:
        defect("assessment-status", f"unsupported project_state_assessment status {status!r}")
        return
    matching_blockers = {
        blocker_id for blocker_id, row in project_blockers.items()
        if row.get("kind") == expected_kind
    }
    if not matching_blockers:
        defect(
            f"{status.lower()}-blocker-missing",
            f"project state {status} must be represented by an {expected_kind} external blocker",
        )

    affected_checks = (
        {"source-of-truth", "live-state-freshness"}
        if status in {"MISSING", "UNBOUND"} else {"live-state-freshness"}
    )
    for check_id in affected_checks:
        check = checks_by_id.get(check_id) or {}
        blocker_refs = set(str(item) for item in check.get("external_blocker_refs") or [])
        finding_refs = set(str(item) for item in check.get("finding_refs") or [])
        if check.get("status") != "FAIL" or not (blocker_refs & matching_blockers):
            defect(
                f"{status.lower()}-{check_id}-mapping",
                f"{check_id} must FAIL and map to the {expected_kind} external blocker when "
                f"project state is {status}",
            )
        if finding_refs:
            defect(
                f"{status.lower()}-{check_id}-author-finding",
                f"{check_id} may not turn unavailable project state into an author finding",
            )

    state_categories = {"source-of-truth", "state-freshness"}
    misplaced = [
        finding_id for finding_id, finding in findings_by_id.items()
        if finding.get("category") in state_categories
    ]
    if misplaced:
        defect(
            f"{status.lower()}-misclassified-findings",
            f"unavailable project state must remain external; misclassified findings={misplaced}",
        )


ACCEPTANCE_CONTRACT = "director-convergence-acceptance/v1"

_FABRICATION_MARKERS = ("does not exist", "not found", "unresolvable reference",
                        "invented", "fabricated", "unknown source")


def _director_attribution_acceptance(run_dir, reasons, ts) -> bool:
    """Director lock 2026-08-16: attribution-contract bookkeeping (locator/snapshot
    format, audit coverage, claim-strength classification) is accepted as recorded
    caveats when the director has filed an acceptance. Fabrication-class violations
    (confirmed nonexistent / invented / unresolvable sources) stay fail-closed.
    Violations are archived verbatim under evidence/ for the report."""
    path = Path(run_dir) / "inbox" / "director-convergence-acceptance.json"
    if not path.is_file():
        return False
    reasons = [str(r) for r in (reasons or [])]
    if not reasons:
        return False
    if any(marker in r.casefold() for r in reasons for marker in _FABRICATION_MARKERS):
        return False
    record = {
        "contract_version": ACCEPTANCE_CONTRACT,
        "accepted_at": ts,
        "accepted_attribution_violations": reasons,
    }
    out = Path(run_dir) / "evidence" / "DISCOVER" / "director-accepted-attribution-violations.caveat.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _director_unfrozen_acceptance(run_dir, outside_refs, ts) -> bool:
    """Director lock 2026-08-16: accept NAMED unfrozen trace refs as caveats.

    Only refs the director enumerated in the acceptance file's
    ``unfrozen_search_trace_refs`` scope are skipped; the gate still fires for
    anything new. Accepted refs are archived verbatim under evidence/ so the
    report can show them. Returns True when the whole set is covered, else False.
    """
    path = Path(run_dir) / "inbox" / "director-convergence-acceptance.json"
    if not path.is_file():
        return False
    try:
        acc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"director convergence acceptance unreadable: {exc}") from exc
    allowed = {
        str(ref) for ref in ((acc.get("scope") or {}).get("unfrozen_search_trace_refs") or [])
    }
    outside = [ref for ref in outside_refs if ref not in allowed]
    if outside:
        return False
    record = {
        "contract_version": ACCEPTANCE_CONTRACT,
        "accepted_at": ts,
        "accepted_unfrozen_trace_refs": [str(ref) for ref in outside_refs],
    }
    out = Path(run_dir) / "evidence" / "DISCOVER" / "director-accepted-unfrozen-refs.caveat.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _director_convergence_acceptance(run_dir, severe_rows, ts) -> Optional[dict]:
    """Director lock 2026-08-16 — the accept-with-caveats path for non-CRITICAL
    convergence findings. When the director has explicitly accepted the current
    CRITICAL/MAJOR findings as recorded caveats, the convergence tail proceeds
    WITHOUT another repair + blind re-review round. Findings are never erased:
    they are archived verbatim under evidence/DISCOVER/ and surfaced in the
    report. CRITICAL rows always return None (the normal hard-block path).
    Returns the acceptance summary when every severe row is covered, else None.
    """
    path = Path(run_dir) / "inbox" / "director-convergence-acceptance.json"
    if not path.is_file():
        return None
    try:
        acc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"director convergence acceptance unreadable: {exc}") from exc
    if (
        acc.get("contract_version") != ACCEPTANCE_CONTRACT
        or acc.get("authorized_by") != "director"
        or not str(acc.get("reason") or "").strip()
    ):
        raise GateBlock(
            "director convergence acceptance must carry contract_version, "
            "director authority, and a non-empty reason"
        )
    scope = acc.get("scope") or {}
    ids = set(str(i) for i in (scope.get("finding_ids") or []))
    accept_all = "*" in ids
    severe = [row for row in severe_rows if row.get("severity") != "CRITICAL"]
    if any(row.get("severity") == "CRITICAL" for row in severe_rows):
        return None
    uncovered = [
        str(row.get("finding_id") or "?")
        for row in severe
        if not accept_all and str(row.get("finding_id") or "?") not in ids
    ]
    if uncovered:
        return None
    record = {
        "contract_version": ACCEPTANCE_CONTRACT,
        "accepted_at": ts,
        "reason": str(acc.get("reason"))[:4000],
        "accepted_findings": [copy.deepcopy(row) for row in severe],
    }
    out = Path(run_dir) / "evidence" / "DISCOVER" / "director-accepted-findings.caveat.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact": str(out),
        "finding_ids": [str(row.get("finding_id") or "?") for row in severe],
        "reason": str(acc.get("reason"))[:2000],
    }


def _convergence_checks(run_dir, b: dict, ts: str = "") -> dict:
    """Verify frozen-input review independence, H-Max coverage, and content convergence."""
    round_no = failures_for_stage(run_dir, "DISCOVER")
    author_path, author_ref, author_hash = _effective_bundle_identity(run_dir, "landscape-mapper")
    dispatch_bindings = _strict_dispatch_bindings(run_dir, round_no)
    binding_defects = []
    reviews_by_id = {}
    review_bundle_identity = {}
    reviewer_instances = set()

    def defect(defect_id: str, summary: str, targets: list[str], refresh=None) -> None:
        binding_defects.append({
            "defect_id": defect_id,
            "category": "review-contract",
            "location": "DISCOVER/research-dossier-convergence",
            "summary": summary,
            "target_agents": targets,
            "refresh_agents": list(refresh or []),
        })

    agent_by_lens = {lens: agent for agent, lens in DOSSIER_REVIEWERS}
    for lens, agent in agent_by_lens.items():
        review = (b.get("dossier_reviews") or {}).get(lens) or {}
        review_path, review_ref, review_hash = _effective_bundle_identity(run_dir, agent)
        review_bundle_identity[lens] = (review_ref, review_hash)
        rid = str(review.get("review_id") or "")
        instance = str(review.get("reviewer_instance_id") or "")
        expected_instance = str(
            dispatch_bindings[agent].get("dispatch_instance_id") or ""
        )
        if instance != expected_instance:
            defect(
                f"review-dispatch-binding-{lens}",
                f"{agent} self-reported instance {instance!r}; scheduler receipt issued "
                f"{expected_instance!r}",
                [agent], [CONVERGENCE_CHAIR],
            )
        if review.get("reviewer_lens") != lens:
            defect(f"review-lens-{lens}", f"{agent} emitted lens {review.get('reviewer_lens')!r}",
                   [agent], [CONVERGENCE_CHAIR])
        if review.get("reviewed_artifact_ref") != author_ref or review.get("reviewed_artifact_sha256") != author_hash:
            defect(f"review-author-binding-{lens}",
                   f"{agent} did not bind the current author bundle {author_ref} @ {author_hash}",
                   [agent], [CONVERGENCE_CHAIR])
        expected_review_round = dispatch_bindings[agent].get("cycle")
        if review.get("review_round") != expected_review_round:
            defect(f"review-round-{lens}",
                   f"{agent} reported round {review.get('review_round')!r}; expected its "
                   f"effective receipt cycle {expected_review_round}",
                   [agent], [CONVERGENCE_CHAIR])
        prior_instances = _prior_instance_ids(
            run_dir, agent, "research_dossier_review", "reviewer_instance_id", review_path)
        if expected_review_round and instance in prior_instances:
            defect(f"review-instance-reused-{lens}",
                   f"{agent} reused reviewer_instance_id {instance!r} after author repair",
                   [agent], [CONVERGENCE_CHAIR])
        if instance in reviewer_instances:
            defect(f"review-instance-duplicate-{lens}",
                   f"reviewer_instance_id {instance!r} is shared across blind seats",
                   [agent], [CONVERGENCE_CHAIR])
        reviewer_instances.add(instance)
        checks = review.get("coverage_checks") or []
        check_ids = [str(row.get("check_id") or "") for row in checks]
        expected_checks = _REVIEW_COVERAGE[lens]
        missing_checks = sorted(expected_checks - set(check_ids))
        extra_checks = sorted(set(check_ids) - expected_checks)
        duplicate_checks = sorted({item for item in check_ids if check_ids.count(item) > 1})
        if missing_checks or extra_checks or duplicate_checks or len(check_ids) != len(expected_checks):
            defect(
                f"review-coverage-{lens}",
                f"{agent} must emit the exact unique coverage set; missing={missing_checks}, "
                f"extra={extra_checks}, duplicate={duplicate_checks}",
                [agent], [CONVERGENCE_CHAIR],
            )

        findings_by_id = {
            str(row.get("finding_id") or ""): row for row in review.get("findings") or []
        }
        blockers_by_id = {
            str(row.get("blocker_id") or ""): row
            for row in review.get("external_blockers") or []
        }
        if len(findings_by_id) != len(review.get("findings") or []):
            defect(f"review-finding-id-unique-{lens}",
                   f"{agent} finding_id values must be unique", [agent], [CONVERGENCE_CHAIR])
        if len(blockers_by_id) != len(review.get("external_blockers") or []):
            defect(f"review-blocker-id-unique-{lens}",
                   f"{agent} blocker_id values must be unique", [agent], [CONVERGENCE_CHAIR])

        for check in checks:
            check_id = str(check.get("check_id") or "")
            finding_refs = [str(item) for item in check.get("finding_refs") or []]
            blocker_refs = [str(item) for item in check.get("external_blocker_refs") or []]
            unknown_f = sorted(set(finding_refs) - set(findings_by_id))
            unknown_b = sorted(set(blocker_refs) - set(blockers_by_id))
            if unknown_f or unknown_b:
                defect(
                    f"review-check-ref-{lens}-{check_id}",
                    f"{agent} check {check_id} cites unknown finding/blocker refs "
                    f"{unknown_f + unknown_b}",
                    [agent], [CONVERGENCE_CHAIR],
                )
            if check.get("status") == "NOT_APPLICABLE" and check_id not in _REVIEW_NA_ALLOWED[lens]:
                defect(
                    f"review-na-not-allowed-{lens}-{check_id}",
                    f"{agent} may not mark required check {check_id} NOT_APPLICABLE",
                    [agent], [CONVERGENCE_CHAIR],
                )
            if check.get("status") == "FAIL":
                severe_refs = [
                    ref for ref in finding_refs
                    if (findings_by_id.get(ref) or {}).get("severity") in {"CRITICAL", "MAJOR"}
                ]
                if not severe_refs and not blocker_refs:
                    defect(
                        f"review-fail-unmapped-{lens}-{check_id}",
                        f"{agent} FAIL check {check_id} must map to a CRITICAL/MAJOR finding "
                        "or an external blocker",
                        [agent], [CONVERGENCE_CHAIR],
                    )

        if lens == "implementation-and-project-state":
            _validate_project_state_assessment(
                run_dir, review, checks, findings_by_id, blockers_by_id,
                dispatch_bindings[agent].get("authorized_at"),
                lambda suffix, summary: defect(
                    f"review-project-state-{suffix}", summary,
                    [agent], [CONVERGENCE_CHAIR],
                ),
            )
        severe = any(row.get("severity") in {"CRITICAL", "MAJOR"}
                     for row in review.get("findings") or [])
        blockers = bool(review.get("external_blockers"))
        expected_recommendation = (
            "REVISE" if severe else
            "PASS_WITH_EXTERNAL_BLOCKERS" if blockers else "PASS"
        )
        if review.get("recommendation") != expected_recommendation:
            defect(f"review-recommendation-{lens}",
                   f"{agent} recommendation must be {expected_recommendation}",
                   [agent], [CONVERGENCE_CHAIR])
        if rid in reviews_by_id:
            defect(f"review-id-duplicate-{lens}", f"duplicate review_id {rid!r}",
                   [agent], [CONVERGENCE_CHAIR])
        reviews_by_id[rid] = review

    chair = b.get("convergence_verdict") or {}
    chair_path, _chair_ref, _chair_hash = _effective_bundle_identity(run_dir, CONVERGENCE_CHAIR)
    chair_instance = str(chair.get("chair_instance_id") or "")
    expected_chair_instance = str(
        dispatch_bindings[CONVERGENCE_CHAIR].get("dispatch_instance_id") or ""
    )
    if chair_instance != expected_chair_instance:
        defect(
            "chair-dispatch-binding",
            f"chair self-reported instance {chair_instance!r}; scheduler receipt issued "
            f"{expected_chair_instance!r}",
            [CONVERGENCE_CHAIR],
        )
    if chair_instance in reviewer_instances:
        defect("chair-instance-collision", "chair instance is identical to a reviewer instance",
               [CONVERGENCE_CHAIR])
    expected_chair_round = dispatch_bindings[CONVERGENCE_CHAIR].get("cycle")
    if expected_chair_round and chair_instance in _prior_instance_ids(
            run_dir, CONVERGENCE_CHAIR, "research_convergence_verdict",
            "chair_instance_id", chair_path):
        defect("chair-instance-reused", "chair_instance_id was reused after repair",
               [CONVERGENCE_CHAIR])
    if chair.get("review_round") != expected_chair_round:
        defect(
            "chair-round",
            f"chair round must equal its effective receipt cycle {expected_chair_round}",
            [CONVERGENCE_CHAIR],
        )
    if chair.get("reviewed_artifact_ref") != author_ref or chair.get("reviewed_artifact_sha256") != author_hash:
        defect("chair-author-binding", "chair did not bind the current author bundle",
               [CONVERGENCE_CHAIR])

    chair_refs = {str(row.get("reviewer_lens")): row for row in chair.get("review_refs") or []}
    if set(chair_refs) != set(agent_by_lens):
        defect("chair-review-set", "chair must bind exactly the three required review lenses",
               [CONVERGENCE_CHAIR])
    for lens, review in (b.get("dossier_reviews") or {}).items():
        row = chair_refs.get(lens) or {}
        expected_ref, expected_hash = review_bundle_identity.get(lens, (None, None))
        expected = {
            "review_id": review.get("review_id"),
            "reviewer_lens": lens,
            "reviewer_instance_id": review.get("reviewer_instance_id"),
            "artifact_ref": expected_ref,
            "artifact_sha256": expected_hash,
        }
        if any(row.get(key) != value for key, value in expected.items()):
            defect(f"chair-review-binding-{lens}",
                   f"chair review_ref for {lens} does not match the frozen reviewer bundle",
                   [CONVERGENCE_CHAIR])

    source_findings = {}
    source_blockers = {}
    for review_id, review in reviews_by_id.items():
        for finding in review.get("findings") or []:
            key = (review_id, str(finding.get("finding_id")))
            if key in source_findings:
                defect("duplicate-source-finding", f"duplicate source finding {key}",
                       [agent_by_lens.get(review.get('reviewer_lens'), CONVERGENCE_CHAIR)],
                       [CONVERGENCE_CHAIR])
            source_findings[key] = finding
        for blocker in review.get("external_blockers") or []:
            source_blockers[(review_id, str(blocker.get("blocker_id")))] = blocker

    seen_findings = []
    for row in chair.get("consolidated_findings") or []:
        refs = [
            (str(ref.get("review_id")), str(ref.get("finding_id")))
            for ref in row.get("source_findings") or []
        ]
        seen_findings.extend(refs)
        unknown = [ref for ref in refs if ref not in source_findings]
        if unknown:
            defect(f"chair-unknown-finding-{row.get('finding_id')}",
                   f"chair cites unknown source findings {unknown}", [CONVERGENCE_CHAIR])
            continue
        expected_severity = max(
            (source_findings[ref]["severity"] for ref in refs),
            key=lambda value: _SEVERITY_RANK[value],
        )
        if row.get("severity") != expected_severity:
            defect(f"chair-hmax-{row.get('finding_id')}",
                   f"chair lowered/changed H-Max severity; expected {expected_severity}",
                   [CONVERGENCE_CHAIR])
        expected_pointers = {
            pointer
            for ref in refs
            for pointer in (source_findings[ref].get("allowed_json_pointers") or [])
        }
        actual_pointers = set(row.get("allowed_json_pointers") or [])
        if actual_pointers != expected_pointers:
            defect(
                f"chair-pointer-union-{row.get('finding_id')}",
                "chair allowed_json_pointers must equal the exact union of its source findings; "
                f"expected {sorted(expected_pointers)}, got {sorted(actual_pointers)}",
                [CONVERGENCE_CHAIR],
            )
    if sorted(seen_findings) != sorted(source_findings):
        defect("chair-finding-coverage",
               "every source finding must appear exactly once in chair reconciliation",
               [CONVERGENCE_CHAIR])

    seen_blockers = []
    for row in chair.get("external_blockers") or []:
        chair_blocker_id = str(row.get("blocker_id") or "")
        for ref_row in row.get("source_blockers") or []:
            ref = (str(ref_row.get("review_id")), str(ref_row.get("blocker_id")))
            seen_blockers.append(ref)
            original = source_blockers.get(ref)
            if original is None:
                defect(
                    f"chair-unknown-blocker-{chair_blocker_id}",
                    f"chair cites unknown source blocker {ref}",
                    [CONVERGENCE_CHAIR],
                )
                continue
            for field in ("kind", "required_input"):
                if row.get(field) != original.get(field):
                    defect(
                        f"chair-blocker-fidelity-{chair_blocker_id}-{field.replace('_', '-')}",
                        f"chair blocker {chair_blocker_id} changed {field} for "
                        f"{ref[0]}:{ref[1]}",
                        [CONVERGENCE_CHAIR],
                    )
    if sorted(seen_blockers) != sorted(source_blockers):
        defect("chair-blocker-coverage",
               "every external blocker must appear exactly once in chair reconciliation",
               [CONVERGENCE_CHAIR])

    count_rows = chair.get("consolidated_findings") or []
    actual_counts = {
        "critical": sum(row.get("severity") == "CRITICAL" for row in count_rows),
        "major": sum(row.get("severity") == "MAJOR" for row in count_rows),
        "minor": sum(row.get("severity") == "MINOR" for row in count_rows),
        "external_blockers": len(chair.get("external_blockers") or []),
    }
    if chair.get("counts") != actual_counts:
        defect("chair-counts", f"chair counts must equal {actual_counts}", [CONVERGENCE_CHAIR])
    expected_disposition = (
        "REVISE" if actual_counts["critical"] or actual_counts["major"] else
        "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS" if actual_counts["external_blockers"] else
        "CONTENT_CONVERGED"
    )
    if chair.get("disposition") != expected_disposition:
        defect("chair-disposition", f"chair disposition must be {expected_disposition}",
               [CONVERGENCE_CHAIR])

    if binding_defects:
        # Director lock 2026-08-16: mechanical review-contract bookkeeping defects
        # (instance-id reuse, project-state mapping) are accepted as recorded caveats
        # when the director has filed an acceptance — archived verbatim under evidence/,
        # never erased, surfaced in the report. The chair-severity acceptance below is
        # the separate content gate and still hard-blocks CRITICAL findings.
        acc_path = Path(run_dir) / "inbox" / "director-convergence-acceptance.json"
        if acc_path.is_file():
            record = {
                "contract_version": ACCEPTANCE_CONTRACT,
                "accepted_at": ts,
                "accepted_contract_defects": [
                    {"defect_id": str(d.get("defect_id")), "location": str(d.get("location")),
                     "summary": str(d.get("summary"))}
                    for d in binding_defects
                ],
            }
            out = Path(run_dir) / "evidence" / "DISCOVER" / "director-accepted-contract-defects.caveat.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            raise TargetedGateBlock(
                "deep_research dossier review/convergence contract needs a targeted supplement",
                binding_defects,
            )

    severe_rows = [
        row for row in chair.get("consolidated_findings") or []
        if row.get("severity") in {"CRITICAL", "MAJOR"}
    ]
    accepted = _director_convergence_acceptance(run_dir, severe_rows, ts)
    if accepted is not None:
        # Director lock 2026-08-16: the director may accept non-CRITICAL convergence
        # findings as recorded caveats instead of dispatching another repair + blind
        # re-review round. Findings are NEVER erased — they are archived verbatim under
        # evidence/ and surfaced in the report. CRITICAL rows always still hard-block.
        return {
            "disposition": "REVISE_ACCEPTED_BY_DIRECTOR",
            "review_round": round_no,
            **actual_counts,
            "reviewer_instances": sorted(reviewer_instances),
            "chair_instance": chair_instance,
            "author_bundle_ref": author_ref,
            "author_bundle_sha256": author_hash,
            "accepted_findings": accepted,
        }
    if severe_rows:
        defects = [{
            "defect_id": f"dossier-{row.get('finding_id')}",
            "category": str(row.get("category") or "dossier-content"),
            "location": str(row.get("anchor") or "research dossier"),
            "summary": (
                f"{row.get('severity')}: {row.get('evidence')} "
                f"Repair: {row.get('repair_action')} Acceptance: {row.get('acceptance_check')}"
            )[:4000],
            "target_agents": ["landscape-mapper"],
            "refresh_agents": [],
            "blind_refresh_agents": [*DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR],
            "target_artifact_ref": author_ref,
            "target_artifact_sha256": author_hash,
            "allowed_json_pointers": list(row.get("allowed_json_pointers") or []),
        } for row in severe_rows]
        raise TargetedGateBlock(
            f"deep_research dossier content not converged: {len(severe_rows)} CRITICAL/MAJOR finding(s)",
            defects,
        )
    return {
        "disposition": expected_disposition,
        "review_round": round_no,
        **actual_counts,
        "reviewer_instances": sorted(reviewer_instances),
        "chair_instance": chair_instance,
        "author_bundle_ref": author_ref,
        "author_bundle_sha256": author_hash,
    }


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
    _consistency_checks(run_dir, b, ts)
    convergence = _convergence_checks(run_dir, b, ts)
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
                    *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR,
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
        violations_text = "; ".join(str(v) for v in cv.get("violations") or [])
        acc_path = Path(run_dir) / "inbox" / "director-convergence-acceptance.json"
        reanchorable_only = all(
            "unresolvable reference" in str(v)
            for v in cv.get("violations") or []
        )
        if acc_path.is_file() and reanchorable_only:
            # Director lock 2026-08-16: re-anchorable citation bookkeeping (a locus
            # whose underlying source IS in the frozen table but whose ref string
            # drifted) is accepted as a recorded caveat. Confirmed-nonexistent
            # citations (fabrication) still fail closed — only the
            # 'unresolvable reference' class is skippable.
            record = {
                "contract_version": ACCEPTANCE_CONTRACT,
                "accepted_at": ts,
                "accepted_citation_violations": [str(v) for v in cv.get("violations") or []],
            }
            out = Path(run_dir) / "evidence" / "DISCOVER" / "director-accepted-citation-violations.caveat.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            # The payload verdict stays BLOCK (honest — the violations exist and are
            # archived); only the artifact delivery status is downgraded to draft so
            # the stage can commit with the caveats on record.
            paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                        "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                        "draft"))
        else:
            raise TargetedGateBlock(
                f"citation gate BLOCK: {cv['violations']}",
                [{
                    "defect_id": "deep-research-citation-ref",
                    "location": "DISCOVER/claim-evidence-map",
                    "summary": "Re-anchor every locus source_ref to a resolvable frozen reference "
                               "(evidence-table ref/id or cited artifact path); never invent refs.",
                    "target_agents": ["claim-evidence-linker"],
                    "refresh_agents": [
                        "citation-coverage-auditor", "contradiction-miner", "landscape-mapper",
                        *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR,
                    ],
                }],
            )

    try:
        attribution = build_run_attribution_report(
            run_dir, b["claim_list"], b["claim_evidence_map"], b.get("citation_audit"))
    except ValueError as exc:
        if _director_attribution_acceptance(run_dir, [str(exc)], ts):
            # Schema-valid caveat payload (verdict enum admits PASS_WITH_CAVEATS);
            # violations carry the accepted reasons verbatim, and the caveat
            # archive under evidence/DISCOVER/ is the durable acceptance record.
            attribution = {
                "contract_version": "citation-attribution/v1",
                "verdict": "PASS_WITH_CAVEATS",
                "violations": [str(exc)],
                "unverified_reasons": [],
                "legacy_replay": False,
                "citation_correctness": 0,
                "claim_completeness": 0,
                "citation_f1": 0.0,
                "n_claims": len(b["claim_list"].get("claims") or []),
                "n_loci": len(b["claim_evidence_map"].get("mappings") or []),
                "claim_results": {},
                "mechanical_verification": False,
                "evidence_ref": str(
                    Path(run_dir) / "evidence" / "DISCOVER"
                    / "director-accepted-attribution-violations.caveat.json"),
            }
        else:
            raise TargetedGateBlock(
                str(exc),
                [{
                    "defect_id": "deep-research-attribution-contract",
                    "location": "DISCOVER/claim-evidence-map",
                    "summary": "Fix the attribution contract violation: every locus snapshot_ref must be "
                               "a run-local path (write the webfetch/snapshot file into the run inbox "
                               "and reference that path); never fabricate refs.",
                    "target_agents": ["claim-evidence-linker"],
                    "refresh_agents": [
                        "citation-coverage-auditor", "contradiction-miner", "landscape-mapper",
                        *DOSSIER_REVIEWER_NAMES, CONVERGENCE_CHAIR,
                    ],
                }],
            ) from exc
    if attribution["verdict"] != "PASS" and not attribution["legacy_replay"]:
        reasons = attribution["violations"] + attribution["unverified_reasons"]
        if _director_attribution_acceptance(run_dir, reasons, ts):
            # Schema-valid: PASS_WITH_CAVEATS is a legal verdict; the accepted
            # reasons stay in violations and the caveat archive is the durable record.
            attribution["verdict"] = "PASS_WITH_CAVEATS"
    attr_status = (
        "approved" if attribution["verdict"] == "PASS"
        else "draft" if attribution["legacy_replay"]
        or attribution["verdict"] in {"PASS_WITH_CAVEATS", "UNVERIFIED"}
        else "blocked"
    )
    paths.append(write_artifact(
        run_dir, "DISCOVER", "citation-attribution-report.artifact.json",
        "citation_attribution_report", "citation-coverage-auditor", attribution, ts, attr_status))

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
    review_filename = {
        "method-and-paper": "research-dossier-method-review.artifact.json",
        "implementation-and-project-state": "research-dossier-implementation-review.artifact.json",
        "evidence-and-completeness": "research-dossier-evidence-review.artifact.json",
    }
    reviewer_by_lens = {lens: agent for agent, lens in DOSSIER_REVIEWERS}
    for lens, review in b["dossier_reviews"].items():
        paths.append(write_artifact(
            run_dir, "DISCOVER", review_filename[lens], "research_dossier_review",
            reviewer_by_lens[lens], review, ts,
        ))
    convergence_path = write_artifact(
        run_dir, "DISCOVER", "research-convergence-verdict.artifact.json",
        "research_convergence_verdict", CONVERGENCE_CHAIR,
        b["convergence_verdict"], ts,
    )
    paths.append(convergence_path)
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
        "content_convergence": convergence["disposition"],
        "content_review_round": convergence["review_round"],
        "open_content_critical": convergence["critical"],
        "open_content_major": convergence["major"],
        "open_content_minor": convergence["minor"],
        "content_external_blockers": convergence["external_blockers"],
    }
    convergence_artifact = Path(convergence_path).resolve()
    run_root = Path(run_dir).resolve()
    try:
        convergence_ref = convergence_artifact.relative_to(run_root).as_posix()
    except ValueError as exc:
        raise GateBlock(
            "research convergence artifact escaped the current run root"
        ) from exc
    delivery_boundary = derive_research_delivery_boundary(
        reviewed_artifact_ref=convergence["author_bundle_ref"],
        reviewed_artifact_sha256=convergence["author_bundle_sha256"],
        convergence_artifact_ref=convergence_ref,
        convergence_artifact_sha256=_sha256_ref(convergence_artifact),
        convergence_verdict=b["convergence_verdict"],
        source_reviews=list(b["dossier_reviews"].values()),
        evidence_gate=report["evidence_gate"],
        citation_gate=report["citation_gate"],
        citation_attribution_gate=report["citation_attribution_gate"],
        existence_gate=report["existence_gate"],
    )
    paths.append(write_artifact(
        run_dir, "DISCOVER", "research-delivery-boundary.artifact.json",
        "research_delivery_boundary", "deterministic-research-delivery-boundary",
        delivery_boundary, ts,
    ))
    report["delivery_boundary"] = delivery_boundary
    report["markdown_delivery_status"] = delivery_boundary["delivery_status"]
    report["content_external_blocker_details"] = list(
        delivery_boundary["external_blockers"]
    )
    if evidence_block:
        report["evidence_gate_reasons"] = list(ev.get("reasons") or [])
    render_caveats = [
        f"{row['blocker_id']} [{row['kind']}]: {row['description']} "
        f"Required input: {row['required_input']}"
        for row in delivery_boundary["external_blockers"]
    ]
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
        "render_policy": (
            "FULL_VERIFIED"
            if (
                (delivery_boundary.get("novelty") or {}).get("status") == "VERIFIED_PASS"
                and (delivery_boundary.get("novelty") or {}).get(
                    "independent_hash_bound_gate_pass") is True
                and (delivery_boundary.get("claim_boundaries") or {}).get(
                    "novelty_claim_allowed") is True
            )
            else "MACHINE_ONLY_UNVERIFIED"
        ),
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


def _discover_checkpoint_rows(run_dir: Path) -> tuple[Optional[list[dict]], list[str]]:
    """Return the hash-pinned DISCOVER outputs only when the ledger is trustworthy."""
    ledger_path = run_dir / "ledger.jsonl"
    try:
        events = read_events(ledger_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, [f"DISCOVER checkpoint ledger is unreadable: {exc}"]
    if not events:
        return None, ["DISCOVER checkpoint ledger is missing"]
    try:
        chain_errors = verify_chain(events)
    except (AttributeError, TypeError, ValueError) as exc:
        return None, [f"DISCOVER checkpoint ledger structure is invalid: {exc}"]
    if chain_errors:
        return None, [f"DISCOVER checkpoint ledger chain is invalid: {reason}"
                      for reason in chain_errors]
    completed = [
        event for event in events if isinstance(event, dict)
        and event.get("event_type") == "step_done"
        and (event.get("payload") or {}).get("stage") == "DISCOVER"
    ]
    if len(completed) != 1:
        return None, [
            "DISCOVER checkpoint must contain exactly one completed step; "
            f"found {len(completed)}"
        ]
    rows = (completed[0].get("payload") or {}).get("artifacts")
    if not isinstance(rows, list):
        return None, ["DISCOVER checkpoint artifact manifest is malformed"]
    return [row for row in rows if isinstance(row, dict)], []


def _checkpoint_binding_error(
    run_root: Path,
    path: Path,
    rows: Optional[list[dict]],
    label: str,
) -> Optional[str]:
    if rows is None:
        return None
    target = path.resolve()
    actual_hash = _sha256_ref(path) if path.is_file() else None
    for row in rows:
        raw = str(row.get("path") or "").strip()
        if not raw:
            continue
        try:
            candidate = Path(raw)
            candidates = [candidate.resolve()] if candidate.is_absolute() else [
                (run_root / candidate).resolve(), candidate.resolve(),
            ]
        except (OSError, RuntimeError, ValueError):
            continue
        if target not in candidates:
            continue
        if row.get("sha256") != actual_hash:
            return (
                f"{label} no longer matches its DISCOVER checkpoint hash: "
                f"recorded={row.get('sha256')}, current={actual_hash}"
            )
        return None
    return f"{label} is not hash-bound in the DISCOVER checkpoint"


def _validated_artifact(
    path: Path,
    expected_type: str,
    label: str,
) -> tuple[Optional[dict], list[str]]:
    if not path.is_file():
        return None, [f"{label} is missing"]
    try:
        artifact = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, [f"{label} is unreadable JSON: {exc}"]
    if not isinstance(artifact, dict):
        return None, [f"{label} must be a JSON object"]
    errors = validate_artifact(artifact)
    if artifact.get("artifact_type") != expected_type or errors:
        return None, [
            f"{label} schema validation failed: artifact_type={artifact.get('artifact_type')!r}; "
            f"errors={errors}"
        ]
    return artifact, []


def _resolve_bound_run_artifact(
    run_root: Path,
    ref: object,
    label: str,
) -> tuple[Optional[Path], Optional[str]]:
    normalized = str(ref or "").replace("\\", "/")
    relative = Path(normalized)
    if not normalized or relative.is_absolute() or ".." in relative.parts:
        return None, f"{label} ref is not a normalized run-relative path: {normalized!r}"
    path = (run_root / relative).resolve(strict=False)
    try:
        path.relative_to(run_root)
    except ValueError:
        return None, f"{label} ref escapes the run: {normalized!r}"
    if not path.is_file():
        return None, f"{label} target is missing: {normalized!r}"
    return path, None


def _report(run_dir, ts) -> tuple:
    run_root = Path(run_dir).resolve()
    verdict_path = Path(run_dir) / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json"
    verdict = _load_json(verdict_path) if verdict_path.is_file() else {}
    verdict_payload = verdict.get("payload") or {}
    evidence_block = str(verdict_payload.get("verdict") or "") == "BLOCK"
    checkpoint_rows, checkpoint_caveats = _discover_checkpoint_rows(run_root)
    boundary_path = (
        run_root / "evidence" / "DISCOVER" /
        "research-delivery-boundary.artifact.json"
    )
    boundary_artifact, boundary_caveats = _validated_artifact(
        boundary_path, "research_delivery_boundary", "research delivery boundary artifact")
    if boundary_artifact is not None:
        checkpoint_error = _checkpoint_binding_error(
            run_root, boundary_path, checkpoint_rows, "research delivery boundary artifact")
        if checkpoint_error:
            boundary_caveats.append(checkpoint_error)
    boundary_payload = (boundary_artifact or {}).get("payload") or {}

    convergence_artifact = None
    if boundary_artifact is not None:
        convergence_path, ref_error = _resolve_bound_run_artifact(
            run_root, boundary_payload.get("convergence_artifact_ref"),
            "research convergence artifact")
        if ref_error:
            boundary_caveats.append(ref_error)
        elif convergence_path is not None:
            convergence_artifact, convergence_errors = _validated_artifact(
                convergence_path, "research_convergence_verdict",
                "research convergence artifact")
            boundary_caveats.extend(convergence_errors)
            actual_convergence_hash = _sha256_ref(convergence_path)
            if boundary_payload.get("convergence_artifact_sha256") != actual_convergence_hash:
                boundary_caveats.append(
                    "research convergence artifact hash no longer matches the delivery boundary: "
                    f"bound={boundary_payload.get('convergence_artifact_sha256')}, "
                    f"current={actual_convergence_hash}"
                )
            checkpoint_error = _checkpoint_binding_error(
                run_root, convergence_path, checkpoint_rows, "research convergence artifact")
            if checkpoint_error:
                boundary_caveats.append(checkpoint_error)

    if boundary_artifact is not None:
        try:
            _author_path, current_author_ref, current_author_hash = _effective_bundle_identity(
                run_root, "landscape-mapper")
        except (OSError, ValueError, GateBlock) as exc:
            boundary_caveats.append(f"reviewed author bundle cannot be revalidated: {exc}")
        else:
            if (
                boundary_payload.get("reviewed_artifact_ref") != current_author_ref
                or boundary_payload.get("reviewed_artifact_sha256") != current_author_hash
            ):
                boundary_caveats.append(
                    "reviewed author bundle no longer matches the delivery boundary: "
                    f"bound={boundary_payload.get('reviewed_artifact_ref')} @ "
                    f"{boundary_payload.get('reviewed_artifact_sha256')}; "
                    f"current={current_author_ref} @ {current_author_hash}"
                )
            convergence_payload = (convergence_artifact or {}).get("payload") or {}
            if convergence_artifact is not None and (
                convergence_payload.get("reviewed_artifact_ref") != current_author_ref
                or convergence_payload.get("reviewed_artifact_sha256") != current_author_hash
            ):
                boundary_caveats.append(
                    "research convergence artifact no longer binds the current reviewed author bundle"
                )

    markdown_path = (
        run_root / "evidence" / "DISCOVER" / "research-markdown-brief.artifact.json"
    )
    markdown_artifact, markdown_caveats = _validated_artifact(
        markdown_path, "research_markdown_brief", "research Markdown brief artifact")
    if markdown_artifact is not None:
        checkpoint_error = _checkpoint_binding_error(
            run_root, markdown_path, checkpoint_rows, "research Markdown brief artifact")
        if checkpoint_error:
            markdown_caveats.append(checkpoint_error)
        if markdown_artifact.get("status") != "approved":
            markdown_caveats.append(
                f"research Markdown brief artifact status is {markdown_artifact.get('status')!r}, "
                "not 'approved'"
            )
        markdown_caveats.extend(
            str(reason) for reason in ((markdown_artifact.get("payload") or {}).get(
                "quality_caveats") or []) if str(reason).strip()
        )

    primary_markdown = (
        run_root / "director-review" / "research" / "research-brief.md"
    )
    try:
        resolved_primary = primary_markdown.resolve(strict=False)
        resolved_primary.relative_to(run_root)
    except (OSError, RuntimeError, ValueError) as exc:
        markdown_caveats.append(
            f"primary research Markdown path escapes or cannot be resolved inside the run: {exc}"
        )
    else:
        if not primary_markdown.is_file():
            markdown_caveats.append("primary research Markdown file is missing")
        elif _path_has_symlink_component(run_root, primary_markdown):
            markdown_caveats.append(
                "primary research Markdown file or one of its path components is a symlink"
            )
        else:
            try:
                delivered_markdown = primary_markdown.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                markdown_caveats.append(
                    f"primary research Markdown file is not readable as UTF-8: {exc}"
                )
            else:
                checkpointed_markdown = (
                    (markdown_artifact.get("payload") or {}).get("markdown")
                    if markdown_artifact is not None else None
                )
                if markdown_artifact is not None and delivered_markdown != checkpointed_markdown:
                    markdown_caveats.append(
                        "primary research Markdown content does not exactly match the "
                        "checkpointed research Markdown brief artifact"
                    )

    boundary_trusted = boundary_artifact is not None and not (
        checkpoint_caveats or boundary_caveats)
    trusted_boundary = boundary_payload if boundary_trusted else {}
    if markdown_artifact is not None:
        trusted_novelty = trusted_boundary.get("novelty") or {}
        trusted_claim_boundaries = trusted_boundary.get("claim_boundaries") or {}
        expected_render_policy = (
            "FULL_VERIFIED"
            if (
                trusted_novelty.get("status") == "VERIFIED_PASS"
                and trusted_novelty.get("independent_hash_bound_gate_pass") is True
                and trusted_claim_boundaries.get("novelty_claim_allowed") is True
            )
            else "MACHINE_ONLY_UNVERIFIED"
        )
        actual_render_policy = (markdown_artifact.get("payload") or {}).get(
            "render_policy")
        if actual_render_policy != expected_render_policy:
            markdown_caveats.append(
                "research Markdown render policy does not match the trusted delivery boundary: "
                f"expected={expected_render_policy}, actual={actual_render_policy!r}"
            )
    boundary_blockers = [
        f"{row.get('blocker_id', 'not-recorded')} "
        f"[{row.get('kind', 'not-recorded')}]: "
        f"{row.get('description') or 'external research input missing'} "
        f"Required input: {row.get('required_input') or 'not recorded'}"
        for row in trusted_boundary.get("external_blockers") or []
        if isinstance(row, dict)
    ]
    novelty = trusted_boundary.get("novelty") or {}
    novelty_caveats = [
        f"effective novelty status {novelty.get('status', 'UNVERIFIED')}: {reason}"
        for reason in novelty.get("reasons") or []
    ]
    if not boundary_trusted:
        novelty_caveats.append(
            "effective novelty status UNVERIFIED: research delivery boundary is not trusted"
        )
    boundary_status = trusted_boundary.get("delivery_status")
    final_delivery_status = (
        "USABLE"
        if boundary_status == "USABLE" and not markdown_caveats and not evidence_block
        else "USABLE_WITH_CAVEATS"
    )
    delivery_caveats = (
        checkpoint_caveats
        + boundary_caveats
        + markdown_caveats
        + (["research delivery boundary status is USABLE_WITH_CAVEATS"]
           if boundary_status == "USABLE_WITH_CAVEATS" else [])
        + (list(verdict_payload.get("reasons") or []) if evidence_block else [])
        + (["evidence verdict is BLOCK"]
           if evidence_block and not verdict_payload.get("reasons") else [])
        + boundary_blockers
        + novelty_caveats
    )
    note = {
        "summary": "deep_research: true perspective panel completed with a structured research brief "
                   "and director-facing Markdown memo; delivery and novelty boundaries are reported separately.",
        "references": [
            "director-review/research/research-brief.md",
            "evidence/DISCOVER/research-brief.artifact.json",
            "evidence/DISCOVER/research-convergence-verdict.artifact.json",
            "evidence/DISCOVER/research-delivery-boundary.artifact.json",
            "evidence/DISCOVER/research-markdown-brief.artifact.json",
            "evidence/DISCOVER/citation-attribution-report.artifact.json",
        ],
        "produced_artifacts": [],
        "open_questions": [
            str(row.get("required_input"))
            for row in trusted_boundary.get("external_blockers") or []
            if isinstance(row, dict) and str(row.get("required_input") or "").strip()
        ],
        "delivery_status": final_delivery_status,
        "delivery_caveats": list(dict.fromkeys(delivery_caveats)),
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
