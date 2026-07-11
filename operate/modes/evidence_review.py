"""Operate recipe for the `evidence_review` mode (DISCOVER -> REPORT) — absorption wave 1.

Wires the second mode into the one-button operate layer (REGISTRY), with the OpenScholar
absorption: a bounded draft -> gate-critique -> revise loop. Split of labour:

  - Four separate workers do the reading: a source scout freezes the source set, a claim extractor
    writes atomic claims, a linker binds exact spans, and an independent citation auditor reopens them.
  - Deterministic cores do the GATING: evidence-verifier (evidence_checker.build_verdict) and
    citation-integrity-auditor (citation_checker.build_report) — the two DISCOVER hard gates.
  - The self-feedback loop is `run_dets_with_repair`: a gate BLOCK is fed back to the worker
    verbatim (operate/bounded_repair), capped by the mode budget's max_debug_retries_per_run;
    when the cap is reached the ORIGINAL GateBlock escalates to the director. The loop is the
    OpenScholar draft->critique->re-retrieve->revise shape with the machine's own deterministic
    critics as the loop-exit gate — never an LLM judging itself.

Legacy single bundles remain replayable, but only new four-worker claim-span runs can earn an
independent attribution PASS.
"""
from __future__ import annotations

import json
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

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of the evidence_review mode: assemble the \
VERIFIED evidence picture for this request:

    REQUEST: {request}

{north_star}

Sources you read (by reference, never inlined):
  1. The vault at `{vault}/02-wiki/` — glob the relevant clusters, read the most relevant pages \
fully; reference pages ONLY by their real `[[slug]]`.
  2. IF `{run_dir}/inbox/search-results.json` exists: the live-retrieval bundle from the \
sanctioned connector. Its `evidence_rows` are schema-ready source rows (claim_support arrives \
"none" — grading is YOUR job; upgrade only what the row's title/venue genuinely supports).

HONESTY (hard): never invent a slug, DOI, or paper; grade `claim_support` honestly (strong = \
directly + centrally supports); set `supports_claim` per locus from the ACTUAL reported result; \
a thin evidence picture is reported as thin (saturation_reached: false), never padded.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle (never argue with the gate, never relax honesty).

Write ONLY this JSON to `{out}` (ends in .bundle.json, NOT .artifact.json):
{{
  "evidence_table": {{"query": "<the request as searched>",
     "sources": [{{"id":"s1","kind":"paper","ref":"[[<slug>]] or doi:<doi> or arXiv:<id>",
                   "title":"<title>","year":2024,"claim_support":"strong"}}, ...],
     "saturation_reached": true}},
  "claim_list": {{"source_scope": "<scope>",
     "claims": [{{"claim_id":"c1","text":"<decision-relevant atomic claim>",
       "source_ref":"[[<slug>]]","kind":"performance|method|dataset|comparison|limitation|other",
       "confidence":"high|medium|low"}}]}},
  "claim_evidence_map": {{"mappings": [{{"claim_id":"c1","overall_support":"supported",
     "loci":[{{"locus_id":"l1","source_ref":"[[<slug>]]","location":"<section/table>","kind":"text",
       "reported_result":"<actual finding>","supports_claim":true,
       "directness":"direct|indirect|proxy|assumed"}}],
     "claim_risk":{{"level":"high|medium|low","note":"<why the claim may be overstated>"}}}}]}}
}}
Quantities: sources 4-8 (>=1 "strong"); claims 2-4, including a limitation claim when the sources \
support one. Each claim must be anchored by >=1 locus with reported_result, explicit supports_claim, \
directness, and an honest overclaim risk. Prefer claims that change what the current project, idea, \
or experiment should do next. After writing, verify valid JSON. Return one line: sources + claims + saturation."""

SCOUT_PROMPT = """You are the source scout in the lightweight evidence-review panel.

REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/` and `{run_dir}/inbox/search-results.json` when present.
Freeze a compact, decision-relevant source set. Never invent a source or inflate support.
Write ONLY JSON to `{out}`:
{{"evidence_table":{{"evidence_contract_version":"evidence-table/v2",
"source_quality_report_ref":"evidence/DISCOVER/source-quality-report.artifact.json",
"search_trace_ref":"evidence/DISCOVER/evidence-search-trace.artifact.json",
"query":"<query>","sources":[{{"id":"s1","kind":"paper",
"ref":"<real ref>","title":"<title>","year":2025,"claim_support":"strong|moderate|weak|none"}}],
"saturation_reached":false}}}}
Use 4-8 sources when available and include counterevidence. `saturation_reached` is a compatibility
placeholder and MUST remain false; only the deterministic search-trace evaluator may derive completion."""

SOURCE_QUALITY_PROMPT = """You are the independent source-methodology reviewer. You did not gather sources.

{north_star}

Read `{run_dir}/inbox/DISCOVER.lit-scout.bundle.json` and inspect every source at its real locator.
Write ONLY JSON to `{out}`:
{{"source_quality_report":{{"quality_contract_version":"source-methodology/v1",
"review_status":"CURRENT","ranked_sources":[{{"source_ref":"<ref>","rank":1,
"tier":"peer-reviewed|preprint|workshop|technical-report|blog|other","rigor_score":0.0,
"review_status":"VERIFIED|PARTIAL|UNVERIFIED","directness":"direct|indirect|background",
"study_design":"<schema enum>","methodology_review":{{"design_appropriateness":"strong|adequate|weak|unclear|not-applicable",
"bias_control":"...","measurement_validity":"...","statistical_validity":"...","reproducibility":"..."}},
"sample_evaluation_review":{{"sample_adequacy":"...","evaluation_independence":"...",
"comparator_fairness":"...","uncertainty_reporting":"..."}},
"applicability":"direct|partial|indirect|unclear","evidence_refs":[{{"evidence_ref":"<ref>",
"locator":"<section/table/page>","exact_quote":"<short quote>"}}],"limitations":["<material limit>"]}}],
"ranking_rationale":"<decision-relevant quality synthesis>","n_sources_ranked":1}}}}
Review every evidence-table source. `rigor_score` is an ordering hint only; never use it as proof of
strength. Methodology, evaluation, applicability, and inspectable locators are mandatory."""

SEARCH_MODERATOR_PROMPT = """You are the evidence-search moderator. You do not set saturation.

REQUEST: {request}

{north_star}

Read the frozen evidence table, claim list, source-methodology review, sanctioned search results, and
available fulltext snapshots. Run at least three grounded question/search rounds. Explicitly search
for support, contradiction/null results, and representative populations/domains/protocols/metrics.
Write ONLY JSON to `{out}`:
{{"evidence_search_trace":{{"search_contract_version":"evidence-search-trace/v1",
"research_question":"<question>","critical_claims":[{{"claim_id":"C1","question":"<claim question>",
"importance":"critical|major|supporting"}}],"representativeness_dimensions":["population","protocol"],
"rounds":[{{"round_index":0,"questions":["<query>"],"source_hits":[{{"source_ref":"<table ref>",
"source_hash":"<64 hex when available>"}}],"claim_ids_addressed":["C1"],
"contradiction_claim_ids_queried":["C1"],"representativeness_dimensions_queried":["population"],
"findings":[{{"finding_id":"F1","source_refs":["<table ref>"],"claim_ids":["C1"],
"finding_kind":"supportive|contradictory|boundary|null"}}]}}],"stop_reason":"semantic_complete|budget_exhausted|source_access_blocked|human_stop|inconclusive",
"budget_exhausted":false}}}}
Every finding must be grounded in a seen source. Cover every critical claim with contradiction queries
and every representativeness dimension. Continue through two trailing low-information rounds before
using `semantic_complete`; otherwise record the honest stop reason. Never emit `saturation_reached`."""

CLAIM_EXTRACTOR_PROMPT = """You are the claim extractor. You did not choose the source set.

REQUEST: {request}

{north_star}

Read `{run_dir}/inbox/DISCOVER.lit-scout.bundle.json`, then reopen the cited source/fulltext snapshots.
Write ONLY JSON to `{out}`:
{{"claim_list":{{"source_scope":"<scope>","claims":[{{"claim_id":"C1","text":"<atomic claim>",
"source_ref":"<real ref>","kind":"performance|method|dataset|comparison|limitation|other",
"confidence":"high|medium|low"}}]}}}}
Preserve direction, magnitude, population, condition, uncertainty, and limitations. Do not link or
judge your own claims. Include a material limitation claim when supported."""

CLAIM_LINKER_PROMPT = """You are the exact-span linker. You did not scout or extract the claims.

{north_star}

Read the frozen source set and claim list:
- `{run_dir}/inbox/DISCOVER.lit-scout.bundle.json`
- `{run_dir}/inbox/DISCOVER.claim-extractor.bundle.json`
- `{run_dir}/inbox/citation-snapshots/fulltext-contexts.manifest.json`

Reopen the cited source/fulltext snapshots. Write ONLY JSON to `{out}`:
{{"claim_evidence_map":{{"attribution_contract_version":"claim-span/v1","mappings":[{{
"claim_id":"C1","overall_support":"supported|partial|contradicted|not-found","loci":[{{
"locus_id":"L1","source_ref":"<real ref>","location":"<human locator>","kind":"text|table|figure",
"reported_result":"<actual finding>","supports_claim":true,"support_relation":"entails|partial|contradicts|insufficient",
"directness":"direct|indirect|proxy|assumed","span_id":"SPAN-1","snapshot_ref":"<immutable snapshot ref>",
"document_hash":"<64-char sha256>","parser_version":"<version>","exact_quote":"<short exact excerpt>",
"char_start":0,"char_end":20}}],"claim_risk":{{"level":"high|medium|low","note":"<risk>"}}}}]}}}}
For table/figure evidence use table_cell_ref or figure_region_ref instead of char offsets. Include a
claim_risk for every mapping. Do not judge the overall panel or select a decision."""

CITATION_AUDITOR_PROMPT = """You are the independent citation auditor. You did not scout, extract, or link.

{north_star}

Read the frozen source set, claim list, and locators in:
- `{run_dir}/inbox/DISCOVER.lit-scout.bundle.json`
- `{run_dir}/inbox/DISCOVER.claim-extractor.bundle.json`
- `{run_dir}/inbox/DISCOVER.claim-evidence-linker.bundle.json`

Reopen every snapshot and form your own support judgment before comparing the analyst flag. Check
direction, magnitude, units, population, condition, uncertainty, negation, and scope. Write ONLY JSON
to `{out}`:
{{"citation_audit":{{"contract_version":"citation-attribution/v1","independent_of_linker":true,
"claim_results":[{{"claim_id":"C1","verdict":"entails|partial|contradicts|insufficient",
"locator_verified":true,"verified_locus_ids":["L1"],"unsupported_locus_ids":[],
"notes":"<independent reason>"}}]}}}}
One result per claim. Source existence or topical overlap is not entailment."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit M1 — now exposed on every evidence mode)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def fulltext_pre(run_dir: str, question: str, doc_paths, ts: str) -> Optional[str]:
    """Prepare local, hash-addressed text snapshots before the evidence panel runs."""
    return prepare_fulltext_citation_inputs(run_dir, question, list(doc_paths or []))


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """Return the six-worker lightweight evidence panel."""
    if stage == "DISCOVER":
        north_star = _shared.north_star_block(run_dir)
        scout_out = f"{run_dir}/inbox/DISCOVER.lit-scout.bundle.json"
        quality_out = f"{run_dir}/inbox/DISCOVER.source-quality-ranker.bundle.json"
        extractor_out = f"{run_dir}/inbox/DISCOVER.claim-extractor.bundle.json"
        search_out = f"{run_dir}/inbox/DISCOVER.evidence-search-moderator.bundle.json"
        linker_out = f"{run_dir}/inbox/DISCOVER.claim-evidence-linker.bundle.json"
        audit_out = f"{run_dir}/inbox/DISCOVER.citation-coverage-auditor.bundle.json"
        workers = [
            {"label": "lit-scout", "model": _worker_model(model_policy), "output": scout_out,
             "prompt": SCOUT_PROMPT.format(request=request, north_star=north_star, vault=vault,
                                            run_dir=run_dir, out=scout_out)},
            {"label": "source-quality-ranker", "model": _worker_model(model_policy),
             "output": quality_out, "depends_on": ["lit-scout"],
             "prompt": SOURCE_QUALITY_PROMPT.format(north_star=north_star, run_dir=run_dir,
                                                     out=quality_out)},
            {"label": "claim-extractor", "model": _worker_model(model_policy),
             "output": extractor_out, "depends_on": ["lit-scout"],
             "prompt": CLAIM_EXTRACTOR_PROMPT.format(request=request, north_star=north_star,
                                                      run_dir=run_dir, out=extractor_out)},
            {"label": "evidence-search-moderator", "model": _worker_model(model_policy),
             "output": search_out,
             "depends_on": ["lit-scout", "source-quality-ranker", "claim-extractor"],
             "prompt": SEARCH_MODERATOR_PROMPT.format(request=request, north_star=north_star,
                                                        run_dir=run_dir, out=search_out)},
            {"label": "claim-evidence-linker", "model": _worker_model(model_policy),
             "output": linker_out,
             "depends_on": ["lit-scout", "claim-extractor", "evidence-search-moderator"],
             "prompt": CLAIM_LINKER_PROMPT.format(north_star=north_star,
                                                   run_dir=run_dir, out=linker_out)},
            {"label": "citation-coverage-auditor", "model": _worker_model(model_policy),
             "output": audit_out, "depends_on": ["claim-evidence-linker"],
             "prompt": CITATION_AUDITOR_PROMPT.format(north_star=north_star,
                                                       run_dir=run_dir, out=audit_out)},
        ]
        return {"label": "evidence-review-panel", "workers": workers,
                "worker_order": [worker["label"] for worker in workers],
                "parallel_groups": [["lit-scout"], ["source-quality-ranker", "claim-extractor"],
                                    ["evidence-search-moderator"], ["claim-evidence-linker"],
                                    ["citation-coverage-auditor"]],
                "panel_note": "Freeze sources; independently review methodology and extract claims; "
                              "moderate semantic search; bind exact spans; independently audit."}
    return None  # REPORT is deterministic


def _load_bundle(run_dir, stage) -> dict:
    if stage == "DISCOVER":
        try:
            replay = load_explicit_legacy_replay(run_dir)
        except ValueError as exc:
            raise GateBlock(str(exc)) from exc
        root = Path(run_dir) / "inbox"
        scout = root / "DISCOVER.lit-scout.bundle.json"
        quality = root / "DISCOVER.source-quality-ranker.bundle.json"
        extractor = root / "DISCOVER.claim-extractor.bundle.json"
        moderator = root / "DISCOVER.evidence-search-moderator.bundle.json"
        linker = root / "DISCOVER.claim-evidence-linker.bundle.json"
        auditor = root / "DISCOVER.citation-coverage-auditor.bundle.json"
        panel_paths = (scout, quality, extractor, moderator, linker, auditor)
        if any(path.exists() for path in panel_paths):
            missing = [path.name for path in panel_paths if not path.exists()]
            if missing:
                raise GateBlock(f"evidence_review panel missing bundle(s): {missing}")
            source = json.loads(scout.read_text(encoding="utf-8"))
            source_quality = json.loads(quality.read_text(encoding="utf-8"))
            claims = json.loads(extractor.read_text(encoding="utf-8"))
            search = json.loads(moderator.read_text(encoding="utf-8"))
            links = json.loads(linker.read_text(encoding="utf-8"))
            audit = json.loads(auditor.read_text(encoding="utf-8"))
            return {"evidence_table": source.get("evidence_table"),
                    "source_quality_report": source_quality.get("source_quality_report"),
                    "claim_list": claims.get("claim_list"),
                    "evidence_search_trace": search.get("evidence_search_trace"),
                    "claim_evidence_map": links.get("claim_evidence_map"),
                    "citation_audit": audit.get("citation_audit"),
                    "legacy_replay": False}
    else:
        replay = None
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    if stage == "DISCOVER" and replay is None:
        raise GateBlock(
            "evidence_review current run requires four separate DISCOVER worker bundles, including "
            "citation-coverage-auditor; a monolithic bundle is accepted only with an explicit "
            "citation-legacy-replay/v1 marker"
        )
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["legacy_replay"] = bool(replay)
    return payload


def _budget(run_dir) -> dict:
    tf = json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))
    return dict(tf["payload"].get("budget") or {})


def _discover_dets(run_dir, ts, b) -> tuple:
    legacy = bool(b.get("legacy_replay"))
    required = ["evidence_table", "claim_list", "claim_evidence_map"]
    if not legacy:
        required.extend(["source_quality_report", "evidence_search_trace", "citation_audit"])
    _shared.require_bundle_keys(b, tuple(required),
                                stage="DISCOVER", mode="evidence_review")
    paths = []
    if not legacy:
        errors = []
        for atype, key in (("evidence_table", "evidence_table"),
                           ("source_quality_report", "source_quality_report"),
                           ("evidence_search_trace", "evidence_search_trace")):
            errors.extend(f"{key}: {e}" for e in validate_payload(atype, b[key]))
        if errors:
            raise GateBlock(f"evidence_review current contract BLOCK: {errors}")
    et = build_evidence_table(b["evidence_table"]["query"], b["evidence_table"]["sources"],
                              b["evidence_table"].get("saturation_reached", False))
    source_quality = None if legacy else b["source_quality_report"]
    search_trace = None if legacy else b["evidence_search_trace"]
    if not legacy:
        et.update({
            "evidence_contract_version": "evidence-table/v2",
            "source_quality_report_ref": b["evidence_table"]["source_quality_report_ref"],
            "search_trace_ref": b["evidence_table"]["search_trace_ref"],
        })
        search_audit = evaluate_search_trace(search_trace)
        et["saturation_reached"] = bool(search_audit["semantic_complete"])
        table_refs = _shared.resolvable_refs(et)
        trace_refs = {
            str(hit.get("source_ref"))
            for row in search_trace.get("rounds") or []
            for hit in row.get("source_hits") or []
            if hit.get("source_ref")
        }
        outside = sorted(trace_refs - set(table_refs))
        if outside:
            raise GateBlock(f"search trace cites source(s) outside evidence table: {outside}")
    else:
        search_audit = evaluate_search_trace(None)
    source_audit = audit_source_quality_report(source_quality, et)
    texts = [str(et.get("query") or "")]
    texts += [str(s.get("title") or "") for s in (et.get("sources") or [])]
    texts += [str(c.get("text") or "") for c in (b["claim_list"].get("claims") or [])]
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)        # NORTH-STAR gate (H2)
    paths.append(dpath)
    if not legacy:
        paths.append(write_artifact(run_dir, "DISCOVER", "source-quality-report.artifact.json",
                                    "source_quality_report", "source-quality-ranker",
                                    source_quality, ts, "approved"))
        paths.append(write_artifact(run_dir, "DISCOVER", "evidence-search-trace.artifact.json",
                                    "evidence_search_trace", "evidence-search-moderator",
                                    search_trace, ts, "approved"))
    ev = build_verdict(et, source_quality_report=source_quality, search_trace=search_trace,
                       strict_current=True)                                  # HARD GATE 1
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-verdict.artifact.json",
                                "evidence_verdict", "evidence-verifier", ev, ts,
                                "draft" if legacy else
                                "blocked" if ev["verdict"] == "BLOCK" else "approved"))
    if ev["verdict"] == "BLOCK" and not legacy:
        raise GateBlock(f"evidence gate BLOCK: {ev['reasons']}")
    cv = build_report(b["claim_list"], b["claim_evidence_map"],              # HARD GATE 2 (W2 fix:
                      resolvable_refs=_shared.resolvable_refs(et))           #  loci must cite table sources)
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
    status = (
        "approved" if attribution["verdict"] == "PASS"
        else "draft" if attribution["legacy_replay"]
        else "blocked"
    )
    paths.append(write_artifact(
        run_dir, "DISCOVER", "citation-attribution-report.artifact.json",
        "citation_attribution_report", "citation-coverage-auditor", attribution, ts, status))
    if attribution["verdict"] != "PASS" and not attribution["legacy_replay"]:
        reasons = attribution["violations"] + attribution["unverified_reasons"]
        raise GateBlock(f"citation attribution {attribution['verdict']}: {reasons}")
    epath, ex = _shared.run_existence_gate(run_dir, "DISCOVER", ts,          # HARD GATE 3 (H4: live
                                           _shared.external_refs(et, b["claim_evidence_map"]))  # existence)
    paths.append(epath)
    paths.append(write_artifact(run_dir, "DISCOVER", "evidence-table.artifact.json",
                                "evidence_table", "lit-scout", et, ts,
                                "draft" if legacy else "approved"))
    paths.append(write_artifact(run_dir, "DISCOVER", "claim-list.artifact.json",
                                "claim_list", "claim-extractor", b["claim_list"], ts))
    paths.append(write_artifact(run_dir, "DISCOVER", "claim-evidence-map.artifact.json",
                                "claim_evidence_map", "claim-evidence-linker",
                                b["claim_evidence_map"], ts))
    report = {"evidence_gate": "LEGACY_UNVERIFIED" if legacy else ev["verdict"],
              "source_methodology_status": source_audit.get("audit_status"),
              "search_completion_status": search_audit.get("status"),
              "citation_gate": cv["verdict"],
              "citation_attribution_gate": (
                  "LEGACY_UNVERIFIED" if attribution["legacy_replay"] else attribution["verdict"]),
              "citation_legacy_replay": attribution["legacy_replay"],
              "citation_correctness": attribution["citation_correctness"],
              "claim_completeness": attribution["claim_completeness"],
              "citation_f1": attribution["citation_f1"],
              "existence_gate": ex["verdict"], "existence_warnings": len(ex["warnings"]),
              "n_sources": et["n_sources"], "n_strong_sources": ev.get("n_strong"),
              "n_claims": len(b["claim_list"].get("claims") or []),
              "n_mappings": len(b["claim_evidence_map"].get("mappings") or [])}
    try:
        report["director_markdown_brief"] = write_research_brief_markdown(
            run_dir,
            mode="evidence_review",
            evidence_table=et,
            claim_list=b["claim_list"],
            claim_evidence_map=b["claim_evidence_map"],
            report=report,
            source_quality_report=source_quality,
            search_trace=search_trace,
        )
    except ValueError as exc:
        report["director_markdown_brief"] = write_research_brief_fallback(
            run_dir, mode="evidence_review", reason=str(exc), report=report)
        report["markdown_delivery_status"] = "USABLE_WITH_CAVEATS"
    return paths, report


def _report(run_dir, ts) -> tuple:
    note = {"summary": "evidence_review: six-worker source/methodology/search/claim/link/independent-attribution panel + a deterministically "
                       "linted director briefing at director-review/evidence/evidence-review-brief.md; "
                       "all DISCOVER hard gates passed",
            "references": ["director-review/evidence/evidence-review-brief.md"], "produced_artifacts": [],
            "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"evidence_review has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """The OpenScholar loop entry: ("ok", (paths, report)) or ("retry", feedback-for-the-worker).
    Re-raises the original GateBlock when the budget's repair cap is reached (director escalation)."""
    return attempt_with_repair(run_dir, stage, _budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
