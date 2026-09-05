"""Operate recipe for `evidence_deep` (DISCOVER -> REPORT).

This mode is now a real evidence panel, not one merged worker pretending to be
ten roles. The panel gathers sources, ranks quality, extracts claims, links
evidence, mines contradictions, audits datasets/staleness, maps the landscape,
and writes a director-facing Markdown evidence brief.

The database is still read by reference only. Invalidation records are draft
proposals until `/promote-to-vault` admits them.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ..output_versions import resolve_effective_output
from ...tools.citation_attribution import (
    CITATION_MANIFEST_REL,
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
from ...tools.systematic_review_corpus import (
    validate_manifest as validate_systematic_review_manifest,
)

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"
SOURCE_PREFLIGHT_REQUIRED = True
SOURCE_PREFLIGHT_VERSION = "evidence-deep-source-preflight/v1"
SOURCE_PREFLIGHT_REL = Path("inbox/evidence-deep-source-preflight.json")
FULLTEXT_QA_REL = Path("inbox/fulltext-qa.json")
SYSTEMATIC_REVIEW_MANIFEST_REL = Path(
    "inbox/systematic-review/systematic-review-execution-manifest.json"
)
_COMPLETE_SOURCE_PARSERS = {
    "pymupdf-page-text/v1",
    "html-body-text/v1",
    "utf8-source-text/v1",
    "mixed-local-source/v1",
}
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


def persist_systematic_review_manifest(run_dir, ts: str) -> str:
    """Persist an already executed, validated review corpus as reusable evidence."""

    source = Path(run_dir) / SYSTEMATIC_REVIEW_MANIFEST_REL
    if not source.is_file():
        raise GateBlock(
            "publication review requires a run-local systematic-review execution manifest"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise GateBlock(
            f"systematic-review execution manifest is unreadable: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise GateBlock("systematic-review execution manifest must be a JSON object")
    try:
        validate_systematic_review_manifest(payload)
    except ValueError as exc:
        raise GateBlock(f"systematic-review execution manifest BLOCK: {exc}") from exc
    return write_artifact(
        run_dir,
        "DISCOVER",
        "systematic-review-execution-manifest.artifact.json",
        "systematic_review_execution_manifest",
        "research-orchestrator",
        payload,
        ts,
        "approved",
    )


def _worker_model(model_policy: str, agent: str) -> str:
    if model_policy == "max_quality":
        return "opus"
    # landscape-mapper joined the opus set on 2026-08-07: drawing the map of a field is a judgment
    # about what the field IS, and every seat reading that map inherits the call.
    if agent in {"source-quality-ranker", "citation-coverage-auditor", "staleness-auditor",
                 "contradiction-miner", "landscape-mapper"}:
        return "opus"
    return "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, **funnel_kwargs) -> str:
    """Live-retrieval pre-step exposed on every evidence mode."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source, queries=queries,
                              **funnel_kwargs)


def fulltext_pre(run_dir: str, question: str, doc_paths, ts: str) -> Optional[str]:
    """Prepare local, hash-addressed text snapshots before the evidence panel runs."""
    return prepare_fulltext_citation_inputs(run_dir, question, list(doc_paths or []))


def _normalise_doc_ref(value: object) -> str:
    """Normalise a copied scratch document path without accepting path traversal."""
    return str(Path(str(value)).resolve())


def _validated_fulltext_context_docs(root: Path, error_type):
    """Return documents with usable QA contexts or raise the caller's gate error.

    The citation snapshot is the complete-source record, while fulltext-qa.json
    is the worker-facing compact context record.  Both are required for a
    source-bound novelty decision: accepting a snapshot when the QA report says
    ``available=false`` would let a panel start with contradictory evidence
    state.
    """
    path = root / FULLTEXT_QA_REL
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise error_type(f"evidence_deep source preflight requires a readable fulltext-qa report: {exc}") from exc
    if report.get("available") is not True:
        reason = str(report.get("reason") or "no usable source context")
        raise error_type(f"evidence_deep source preflight rejects unavailable fulltext QA: {reason}")
    contexts = report.get("contexts")
    if not isinstance(contexts, list) or not contexts:
        raise error_type("evidence_deep source preflight requires at least one fulltext QA context")
    return {
        _normalise_doc_ref(row.get("doc_ref"))
        for row in contexts
        if isinstance(row, dict)
        and str(row.get("doc_ref") or "").strip()
        and str(row.get("excerpt") or "").strip()
    }


def register_source_preflight(run_dir: str, source_refs, doc_paths, ts: str) -> str:
    """Bind each director-selected critical source to a frozen local full-text snapshot.

    ``evidence_deep`` is used for source-bound decisions such as novelty gates.
    It must not spend a ten-worker panel discovering that a load-bearing paper
    has no immutable full text.  The CLI calls this immediately after
    ``fulltext-pre``; this function only writes run scratch, never the vault.
    """
    root = Path(run_dir)
    refs = [str(value or "").strip() for value in (source_refs or [])]
    docs = [_normalise_doc_ref(value) for value in (doc_paths or [])]
    if not refs:
        raise ValueError("evidence_deep source preflight requires at least one --source-ref")
    if len(refs) != len(docs):
        raise ValueError("evidence_deep requires exactly one --source-ref for each --doc")
    if any(not value for value in refs):
        raise ValueError("evidence_deep source preflight contains an empty source_ref")
    if len(set(refs)) != len(refs):
        raise ValueError("evidence_deep source preflight source_ref values must be unique")
    qa_context_docs = _validated_fulltext_context_docs(root, ValueError)
    missing_qa_docs = [doc for doc in docs if doc not in qa_context_docs]
    if missing_qa_docs:
        raise ValueError(
            "critical source document(s) did not yield fulltext QA contexts: " + ", ".join(missing_qa_docs)
        )
    manifest_path = root / CITATION_MANIFEST_REL
    if not manifest_path.is_file():
        raise ValueError("fulltext-pre did not create a citation snapshot manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid citation snapshot manifest: {exc}") from exc
    if manifest.get("contract_version") != "citation-context-snapshot/v1":
        raise ValueError("citation snapshot manifest has an unsupported contract version")
    if manifest.get("parser_version") not in _COMPLETE_SOURCE_PARSERS:
        raise ValueError(
            "evidence_deep requires complete local PDF, HTML-body, or UTF-8 source extraction for every critical source"
        )
    snapshot_ref = str(manifest.get("snapshot_ref") or "")
    snapshot = root / snapshot_ref
    if not snapshot_ref or not snapshot.is_file():
        raise ValueError("citation snapshot manifest points to a missing frozen text snapshot")
    # The digest is still RECORDED (it goes into the preflight payload below and stays useful for
    # after-the-fact inspection); the COMPARISON against the manifest was removed 2026-08-07 per the
    # director's no-hash-gating lock. The snapshot must still exist and be a complete-parser
    # extraction — that is what makes the downstream quote checks readable.
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    context_parsers = {
        _normalise_doc_ref(row.get("doc_ref")): str(row.get("parser_version") or manifest.get("parser_version") or "")
        for row in (manifest.get("contexts") or [])
        if isinstance(row, dict) and str(row.get("doc_ref") or "").strip()
    }
    missing_docs = [doc for doc in docs if doc not in context_parsers]
    if missing_docs:
        raise ValueError(
            "critical source document(s) did not yield frozen page text: " + ", ".join(missing_docs)
        )
    payload = {
        "contract_version": SOURCE_PREFLIGHT_VERSION,
        "created_at": ts,
        "snapshot_ref": snapshot_ref,
        "document_hash": digest,
        "parser_version": manifest["parser_version"],
        "coverage_boundary": manifest.get("coverage_boundary"),
        "sources": [
            {"source_ref": source_ref, "doc_ref": doc_ref,
             "parser_version": context_parsers[doc_ref]}
            for source_ref, doc_ref in zip(refs, docs)
        ],
    }
    out = root / SOURCE_PREFLIGHT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)


def source_preflight(run_dir: str) -> dict:
    """Validate mandatory frozen sources before the first panel worker is released."""
    root = Path(run_dir)
    path = root / SOURCE_PREFLIGHT_REL
    if not path.is_file():
        raise GateBlock(
            "evidence_deep source preflight BLOCK: no critical-source freeze found. "
            "Run fulltext-pre with one --source-ref per local primary PDF before dispatching the panel."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"evidence_deep source preflight BLOCK: unreadable freeze record: {exc}") from exc
    if payload.get("contract_version") != SOURCE_PREFLIGHT_VERSION:
        raise GateBlock("evidence_deep source preflight BLOCK: unsupported freeze-record contract")
    sources = payload.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise GateBlock("evidence_deep source preflight BLOCK: no critical source bindings recorded")
    refs = [str(row.get("source_ref") or "").strip() for row in sources if isinstance(row, dict)]
    if len(refs) != len(sources) or not all(refs) or len(set(refs)) != len(refs):
        raise GateBlock("evidence_deep source preflight BLOCK: invalid or duplicate critical source_ref binding")
    qa_context_docs = _validated_fulltext_context_docs(root, GateBlock)
    missing_qa_docs = [
        str(row.get("doc_ref") or "")
        for row in sources
        if _normalise_doc_ref(row.get("doc_ref")) not in qa_context_docs
    ]
    if missing_qa_docs:
        raise GateBlock(
            "evidence_deep source preflight BLOCK: critical source binding(s) absent from fulltext QA contexts: "
            + ", ".join(missing_qa_docs)
        )
    manifest_path = root / CITATION_MANIFEST_REL
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateBlock(f"evidence_deep source preflight BLOCK: missing snapshot manifest: {exc}") from exc
    snapshot_ref = str(payload.get("snapshot_ref") or "")
    snapshot = root / snapshot_ref
    if not snapshot_ref or not snapshot.is_file():
        raise GateBlock("evidence_deep source preflight BLOCK: frozen snapshot is missing")
    # Recorded, not compared (2026-08-07): existence and parser completeness stay hard gates.
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if payload.get("parser_version") not in _COMPLETE_SOURCE_PARSERS or manifest.get("parser_version") not in _COMPLETE_SOURCE_PARSERS:
        raise GateBlock(
            "evidence_deep source preflight BLOCK: critical sources need complete local PDF, HTML-body, or UTF-8 source extraction"
        )
    context_parsers = {
        _normalise_doc_ref(row.get("doc_ref")): str(row.get("parser_version") or manifest.get("parser_version") or "")
        for row in (manifest.get("contexts") or [])
        if isinstance(row, dict) and str(row.get("doc_ref") or "").strip()
    }
    missing_docs = [
        str(row.get("doc_ref") or "")
        for row in sources
        if _normalise_doc_ref(row.get("doc_ref")) not in context_parsers
    ]
    if missing_docs:
        raise GateBlock(
            "evidence_deep source preflight BLOCK: critical source binding(s) absent from frozen text: "
            + ", ".join(missing_docs)
        )
    unsupported_source_parsers = [
        str(row.get("source_ref") or "")
        for row in sources
        if str(row.get("parser_version") or "") not in _COMPLETE_SOURCE_PARSERS
        or context_parsers.get(_normalise_doc_ref(row.get("doc_ref"))) != row.get("parser_version")
    ]
    if unsupported_source_parsers:
        raise GateBlock(
            "evidence_deep source preflight BLOCK: unsupported or changed parser binding for source(s): "
            + ", ".join(unsupported_source_parsers)
        )
    return {
        "source_preflight": "PASS",
        "required_source_refs": refs,
        "snapshot_ref": snapshot_ref,
        "document_hash": digest,
    }


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
- mandatory frozen primary sources: `{run_dir}/inbox/evidence-deep-source-preflight.json`
- agent Web Search fallback when API recall is empty/off-topic or a named method is absent; accept
  only paper originals, official publisher/project pages, or authors' official repositories, and
  carry them by resolvable reference through the same citation gates

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
Use >=30 sources when available — a FLOOR with no upper bound, so use every relevant record rather than
a sample — including negative/boundary evidence. The saturation field is a
fixed compatibility placeholder; only the deterministic search-trace evaluator derives completion.
Every `source_ref` declared in the mandatory source-preflight record is load-bearing and MUST appear
unchanged in the evidence table. Do not substitute a search snippet, abstract, or derivative page for it.
For every important source record version_read, access_scope, supplement_scope, figure_scope, code_scope,
acquisition_channel, search_receipt_ref, and local snapshot ref/hash. A logged-in IEEE result is
IEEE_XPLORE_MANUAL only when the run carries its query/filter/date/document-id receipt; a worksheet is
NOT_EXECUTED and contributes no search-completion claim. Do not copy cookies, tokens, or headers.
""",
        "source-quality-ranker": """
Task: independently audit every evidence-table source at inspectable locators.
Output exactly: {"source_quality_report": {"quality_contract_version":"source-methodology/v1",
"review_status":"CURRENT", ranked_sources, ranking_rationale, n_sources_ranked}}.
Every ranked source must include review_status, directness, study_design, all five methodology_review
dimensions, all four sample_evaluation_review dimensions, applicability, evidence_refs with locator
plus exact_quote/reported_result, and limitations. `rigor_score` is only a compatibility ordering hint
and never establishes strength. Each `ranked_sources[].source_ref` MUST exactly equal the matching
`evidence_table.sources[].ref` (not a local short id), so the deterministic audit can close the
source-methodology chain. Judge `applicability` against the full research question in the task frame,
not against one convenient subclaim: `direct` means the source directly addresses the whole atomic
question. If the question bundles several independent components and a source covers only one, keep
`partial` or `indirect`; never upgrade applicability merely to satisfy the strong-source gate. A gate
BLOCK then means a new atomic evidence review is required. Do not omit weak or unverified sources.
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
Every locus must include locus_id (unique per map, e.g. "CE-C1-L1"), source_ref, location, kind,
reported_result, supports_claim, support_relation, directness, span_id, snapshot_ref, document_hash,
parser_version, exact_quote, and either char_start/char_end, table_cell_ref, or figure_region_ref.
Also preserve version_read and value_origin. SOURCE_REPORTED is the only origin that may be attributed
as "the paper reports"; RE_DERIVED/REVIEWER_COUNT require a formula and input loci; suspected source
errors remain separate annotations and exact_quote stays verbatim.
Closed enums (machine-readable; any other value BLOCKS the run):
  overall_support ∈ {"supported","partial","contradicted","not-found"} — never a support_relation word;
  kind ∈ {"table","figure","text","code","dataset","appendix","other"} — never a source-channel label;
  directness ∈ {"direct","indirect","proxy","assumed"};
  claim_risk is an OPTIONAL OBJECT {"level":"high|medium|low","note":"<why>"} — never a bare string.
Use partial/insufficient instead of inflating support. You only link;
a different worker reopens every locator and independently judges semantic support.
""" + _shared.SUPPORT_RELATION_CONTRACT,
        "citation-coverage-auditor": """
Task: independently audit claim support. You did not extract or link the claims. Reopen each snapshot
and exact locator; ignore the linker's supports_claim conclusion until after your own reading. Check
direction, magnitude, units, denominator, confidence interval, population, condition, negation, and scope.
Output exactly: {"citation_audit": {"contract_version":"citation-attribution/v1",
"independent_of_linker":true,"claim_results":[{"claim_id":"C1",
"verdict":"entails|partial|contradicts|insufficient","locator_verified":true,
"verified_locus_ids":["L1"],"unsupported_locus_ids":[],"notes":"<independent reason>"}]}}.
Emit exactly one result per claim. A source existing or mentioning the topic is not entailment.
Independently check value origin and attribution, not only numeric equality. Re-derived values with no
formula/input loci, or source-reported wording applied to reviewer counts, are unsupported even when the
number itself is correct.
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
             model_policy: str = "default") -> Optional[dict]:
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
        out[agent] = _load_json(p)
    if missing:
        raise GateBlock(
            f"evidence_deep DISCOVER missing worker bundle(s): {missing}. "
            "A deep evidence review is not complete when one role is absent."
        )

    def take(agent: str, key: str, *, required: bool = True, default=None):
        source = out.get(agent)
        if source is None:
            if required:
                raise GateBlock(
                    f"evidence_deep DISCOVER missing worker bundle for {agent}"
                )
            return default
        return _shared.extract_worker_bundle_value(
            source, key, stage="DISCOVER", mode="evidence_deep", agent=agent,
            required=required, default=default,
        )

    b = {
        "evidence_table": take("lit-scout", "evidence_table"),
        "source_quality_report": take("source-quality-ranker", "source_quality_report"),
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
        "invalidation_proposals": take(
            "contradiction-miner", "invalidation_proposals",
            required=False, default=[],
        ) or [],
        "dataset_cards": take(
            "dataset-card-builder", "dataset_cards", required=False, default=[],
        ) or [],
        "staleness_reports": take(
            "staleness-auditor", "staleness_reports", required=False, default=[],
        ) or [],
        "landscape_map": take("landscape-mapper", "landscape_map"),
        "legacy_replay": replay is not None,
    }
    missing_keys = [k for k, v in b.items() if v is None]
    if replay is not None:
        missing_keys = [k for k in missing_keys if k not in {"citation_audit", "evidence_search_trace"}]
    if missing_keys:
        raise GateBlock(f"evidence_deep bundle key BLOCK: missing {missing_keys}")
    return b


def _data_descendants(agent: str) -> list[str]:
    impacted = set()
    frontier = {agent}
    while frontier:
        current = frontier.pop()
        for candidate, dependencies in PANEL_DEPENDENCIES.items():
            if current in dependencies and candidate not in impacted:
                impacted.add(candidate)
                frontier.add(candidate)
    impacted.discard(agent)
    return [candidate for candidate in PANEL_AGENTS if candidate in impacted]


def _normalize_source_quality_compat(b: dict) -> None:
    """Project rich source-review prose into conservative machine categories.

    The prose is retained verbatim in ``limitations``. Unknown judgments map
    to ``unclear`` rather than being guessed into a stronger quality class.
    """

    quality_levels = {"strong", "adequate", "weak", "unclear", "not-applicable"}
    method_fields = (
        "design_appropriateness",
        "bias_control",
        "measurement_validity",
        "statistical_validity",
        "reproducibility",
    )
    sample_fields = (
        "sample_adequacy",
        "evaluation_independence",
        "comparator_fairness",
        "uncertainty_reporting",
    )

    def preserve(row: dict, field: str, value: object) -> None:
        if value in (None, ""):
            return
        note = f"Original {field} description (conservatively normalized): {value}"
        limitations = row.setdefault("limitations", [])
        if note not in limitations:
            limitations.append(note)

    def quality_block(row: dict, key: str, fields: tuple[str, ...]) -> dict:
        raw = row.get(key)
        raw = raw if isinstance(raw, dict) else {}
        normalized = {}
        for field in fields:
            value = raw.get(field)
            if value in quality_levels:
                normalized[field] = value
            else:
                preserve(row, f"{key}.{field}", value)
                normalized[field] = "unclear"
        for field, value in raw.items():
            if field not in fields:
                preserve(row, f"{key}.{field}", value)
        return normalized

    for row in (b.get("source_quality_report") or {}).get("ranked_sources") or []:
        if not isinstance(row, dict):
            continue
        directness = str(row.get("directness") or "").strip()
        if directness not in {"direct", "indirect", "background"}:
            preserve(row, "directness", directness)
            token = directness.upper()
            if "FULLTEXT_PRIMARY" in token:
                row["directness"] = "direct"
            elif any(label in token for label in ("SURVEY", "BACKGROUND", "CONTEXT")):
                row["directness"] = "background"
            else:
                row["directness"] = "indirect"

        if not row.get("tier"):
            ref = str(row.get("source_ref") or "").casefold()
            row["tier"] = (
                "preprint"
                if ref.startswith("arxiv:")
                or "10.48550/arxiv" in ref
                or ref.startswith("doi:10.2139/")
                else "peer-reviewed"
                if ref.startswith("doi:")
                else "other"
            )

        score = row.get("rigor_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            if score > 1.0:
                preserve(row, "rigor_score", score)
                row["rigor_score"] = max(0.0, min(1.0, float(score) / 100.0))

        row["methodology_review"] = quality_block(
            row, "methodology_review", method_fields
        )
        row["sample_evaluation_review"] = quality_block(
            row, "sample_evaluation_review", sample_fields
        )

        for evidence in row.get("evidence_refs") or []:
            if isinstance(evidence, dict) and not evidence.get("evidence_ref"):
                evidence["evidence_ref"] = str(row.get("source_ref") or "source")


def _normalize_search_trace_compat(b: dict) -> None:
    """Keep only frozen literature rows in ``source_hits``.

    Scheduler/controller files are provenance inputs, not scholarly hits.
    Newly discovered external identities remain visible as boundary findings
    until a later run freezes and assesses them in the evidence table.
    """

    frozen_refs = {
        str(row.get("ref"))
        for row in (b.get("evidence_table") or {}).get("sources") or []
        if isinstance(row, dict) and row.get("ref")
    }
    for round_row in (b.get("evidence_search_trace") or {}).get("rounds") or []:
        if not isinstance(round_row, dict):
            continue
        kept = []
        external = []
        for hit in round_row.get("source_hits") or []:
            if not isinstance(hit, dict) or not hit.get("source_ref"):
                continue
            ref = str(hit["source_ref"])
            if ref in frozen_refs:
                kept.append(hit)
            elif re.match(r"^(?:doi:|arxiv:|pmid:|https?://)", ref, re.I):
                external.append(ref)
        round_row["source_hits"] = kept
        findings = round_row.setdefault("findings", [])
        existing = {
            str(ref)
            for finding in findings
            if isinstance(finding, dict)
            for ref in finding.get("source_refs") or []
        }
        round_index = int(round_row.get("round_index") or 0)
        for offset, ref in enumerate(external, start=1):
            if ref in existing:
                continue
            findings.append(
                {
                    "finding_id": f"unfrozen-search-lead-r{round_index}-{offset}",
                    "source_refs": [ref],
                    "claim_ids": list(round_row.get("claim_ids_addressed") or []),
                    "finding_kind": "boundary",
                }
            )


def _validate_payloads(run_dir, b: dict) -> dict:
    errors = []
    defects = []
    reports = []
    for key, atype, agent, _fname, _status in ARTIFACT_PLAN:
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
                "defect_id": f"evidence-deep-schema-{key.replace('_', '-')}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/{key}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": [agent],
                "refresh_agents": _data_descendants(agent),
            })
    for i, card in enumerate(b.get("dataset_cards") or [], start=1):
        normalized, item_errors, report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", "dataset-card-builder", "dataset_card", card,
            label=f"dataset-card-{i}",
        )
        b["dataset_cards"][i - 1] = normalized
        reports.append(report)
        for e in item_errors:
            errors.append(f"dataset_cards[{i}]: {e}")
        if item_errors:
            defects.append({
                "defect_id": f"evidence-deep-schema-dataset-card-{i}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/dataset_cards/{i}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": ["dataset-card-builder"],
                "refresh_agents": _data_descendants("dataset-card-builder"),
            })
    for i, report in enumerate(b.get("staleness_reports") or [], start=1):
        normalized, item_errors, norm_report = _shared.normalize_worker_payload(
            run_dir, "DISCOVER", "staleness-auditor", "staleness_report", report,
            label=f"staleness-report-{i}",
        )
        b["staleness_reports"][i - 1] = normalized
        reports.append(norm_report)
        for e in item_errors:
            errors.append(f"staleness_reports[{i}]: {e}")
        if item_errors:
            defects.append({
                "defect_id": f"evidence-deep-schema-staleness-{i}",
                "category": "schema-semantic-gap",
                "location": f"DISCOVER/staleness_reports/{i}",
                "summary": "; ".join(item_errors)[:4000],
                "target_agents": ["staleness-auditor"],
                "refresh_agents": _data_descendants("staleness-auditor"),
            })
    if errors:
        raise TargetedGateBlock(
            f"evidence_deep payload needs a local supplement after automatic normalization: {errors}",
            defects,
        )
    invalidation_errors = []
    for i, prop in enumerate(b.get("invalidation_proposals") or [], start=1):
        for f in ("claim_slug", "invalidated_by_slug"):
            if not _SLUG.match(str((prop or {}).get(f, ""))):
                raise GateBlock(
                    f"invalidation proposal {i}: {f} is not a real slug shape "
                    f"({(prop or {}).get(f)!r}) - never invent a slug"
                )
        # Invalidation proposals eventually cross the vault trust boundary, so
        # they intentionally remain strict instead of using delivery-time
        # projection.
        from ...tools.validate_artifact import validate_payload
        for e in validate_payload("invalidation_record", prop if isinstance(prop, dict) else {}):
            invalidation_errors.append(f"invalidation_proposals[{i}]: {e}")
    if invalidation_errors:
        raise GateBlock(f"evidence_deep invalidation proposal schema BLOCK: {invalidation_errors}")
    return {
        "normalized_payloads": sum(
            1 for row in reports if row.get("changes") or row.get("preserved_extras")
        ),
        "format_changes": sum(len(row.get("changes") or []) for row in reports),
        "preserved_extra_fields": sum(
            len(row.get("preserved_extras") or []) for row in reports
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
            raise TargetedGateBlock(
                "current source quality must declare source-methodology/v1",
                [{
                    "defect_id": "evidence-deep-source-quality-contract",
                    "location": "inbox/DISCOVER.source-quality-ranker.bundle.json",
                    "summary": "Current evidence_deep requires an inspectable source-methodology/v1 "
                               "review; preserve the frozen source set and repair only the "
                               "source-quality contract.",
                    "target_agents": ["source-quality-ranker"],
                    "refresh_agents": [],
                }],
            )
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
    _normalize_source_quality_compat(b)
    _normalize_search_trace_compat(b)
    normalization = _validate_payloads(run_dir, b)
    _consistency_checks(b)

    paths = []
    if (Path(run_dir) / SYSTEMATIC_REVIEW_MANIFEST_REL).is_file():
        paths.append(persist_systematic_review_manifest(run_dir, ts))
    et = build_evidence_table(
        b["evidence_table"]["query"],
        b["evidence_table"]["sources"],
        b["evidence_table"].get("saturation_reached", False),
    )
    # The operate CLI requires this preflight before releasing the panel.  If
    # a freeze record exists, re-derive it here as defense in depth and ensure
    # the lit-scout did not silently discard a director-selected primary paper.
    preflight = None
    if (Path(run_dir) / SOURCE_PREFLIGHT_REL).is_file():
        preflight = source_preflight(run_dir)
        missing_required = sorted(
            set(preflight["required_source_refs"]) - _source_refs(et)
        )
        if missing_required:
            raise GateBlock(
                "evidence_deep source preflight BLOCK: evidence table omitted frozen critical source(s): "
                + ", ".join(missing_required)
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
    # Evidence sufficiency is a real gate, but it is not a reason to hide a
    # fully attributable source/claim landscape from the director. Continue
    # through the independent citation and delivery path below, then preserve
    # the same BLOCK after the caveated Markdown brief has been written.
    evidence_block = ev["verdict"] == "BLOCK" and not legacy

    cv = build_report(b["claim_list"], b["claim_evidence_map"],
                      resolvable_refs=_shared.resolvable_refs(et))
    paths.append(write_artifact(run_dir, "DISCOVER", "citation-verdict.artifact.json",
                                "citation_integrity_verdict", "citation-integrity-auditor", cv, ts,
                                "blocked" if cv["verdict"] == "BLOCK" else "approved"))
    # A citation failure must still leave the director a readable, explicitly
    # caveated account of the source/claim landscape.  Do not checkpoint the
    # stage: defer the same hard failure until after the Markdown renderer has
    # consumed only the already-validated worker outputs.
    citation_block_reason = (
        f"citation gate BLOCK: {cv['violations']}"
        if cv["verdict"] == "BLOCK" else None
    )

    attribution = None
    attribution_block_reason = None
    try:
        attribution = build_run_attribution_report(
            run_dir, b["claim_list"], b["claim_evidence_map"], b.get("citation_audit"))
    except ValueError as exc:
        # Preserve the original error as the eventual hard block, but render
        # the rest of the validated evidence instead of hiding it behind an
        # attribution parser/contract failure.
        attribution_block_reason = str(exc)
    else:
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
            attribution_block_reason = f"citation attribution {attribution['verdict']}: {reasons}"

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

    attribution_report = attribution or {}
    report = {
        "evidence_gate": "LEGACY_UNVERIFIED" if legacy else ev["verdict"],
        "source_methodology_status": source_audit.get("audit_status"),
        "search_completion_status": search_audit.get("status"),
        "citation_gate": cv["verdict"],
        "citation_attribution_gate": (
            "LEGACY_UNVERIFIED" if attribution_report.get("legacy_replay")
            else attribution_report.get("verdict", "NOT_RUN")),
        "citation_legacy_replay": bool(attribution_report.get("legacy_replay")),
        "citation_correctness": attribution_report.get("citation_correctness", 0.0),
        "claim_completeness": attribution_report.get("claim_completeness", 0.0),
        "citation_f1": attribution_report.get("citation_f1", 0.0),
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
        "representation_normalization": normalization,
    }
    if preflight:
        report["source_preflight"] = preflight["source_preflight"]
        report["frozen_critical_source_refs"] = preflight["required_source_refs"]
    delivery_caveats = []
    if evidence_block:
        delivery_caveats.extend(str(reason) for reason in (ev.get("reasons") or []))
    if citation_block_reason:
        delivery_caveats.append(citation_block_reason)
    if attribution_block_reason:
        delivery_caveats.append(attribution_block_reason)
    if delivery_caveats:
        report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
        report["delivery_caveats"] = delivery_caveats
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
    # Preserve the original hard-gate precedence while ensuring readable
    # director output exists first.  `run_dets` still raises, so the operate
    # layer cannot commit DISCOVER (and the blocked verdict artifact is a
    # second defense against a stray commit attempt).
    if citation_block_reason:
        raise GateBlock(citation_block_reason)
    if attribution_block_reason:
        raise GateBlock(attribution_block_reason)
    if evidence_block:
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")
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
            "evidence/DISCOVER/systematic-review-execution-manifest.artifact.json",
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
