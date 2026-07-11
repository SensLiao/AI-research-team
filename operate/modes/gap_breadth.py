"""Operate recipe for a prosecuted, mechanism-grounded `gap_breadth` scan.

The differentiation engine's focused scan, with the 5-hunter taxonomy REALLY parallel for the
first time in the operated path: `llm_step` returns FIVE independent hunter workers (the audit's
W4 finding was that the flagship consolidated them into one mind — here each hunter is its own
dispatch, so the diversity is structural, not prompt-discipline):

    future-work-miner          -> stated_open_problem signals          (gap ids FW-*)
    weakness-spotter           -> methodological_gap signals           (gap ids WK-*)
    white-space-mapper         -> coverage_gap signals                 (gap ids WS-*)
    cross-domain-transfer-scout-> transfer_gap signals                 (gap ids XF-*)
    contrarian-angle-generator -> assumption_gap signals               (gap ids CA-*)

The five hunters stay mutually blind. Their frozen outputs then pass through three independent,
ordered workers:

    gap-prosecutor       -> search for the paper or result that closes each proposed gap
    mechanism-synthesizer-> build a falsifiable scientific dossier for every survivor
    gap-quality-auditor  -> audit importance, openness, falsifiability, information gain,
                            mechanism clarity, and feasibility without making a bet

Deterministic gates require complete coverage across those handoffs. "Nothing found" can only be
UNVERIFIED; CLOSED requires a concrete paper, completed scope, and result locator. The final
Markdown is a director review product, while JSON bundles remain machine evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.classify_gap import build_classification
from ...tools.gap_breadth_markdown import lint_gap_scan, render_gap_scan
from ...tools.novelty_aggregate import aggregate_novelty
from ...tools.project_memory import (
    append_gap_inventory,
    load_gap_inventory,
    prior_overlaps,
    workspace_for_run,
)

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"
GAP_SCAN_REL = Path("director-review") / "gaps" / "gap-scan.md"
POST_HUNTER_AGENTS = ("gap-prosecutor", "mechanism-synthesizer", "gap-quality-auditor")
KNOWLEDGE_QUADRANTS = ("Known Known", "Unknown Known", "Known Unknown", "Unknown Unknown")
CLOSURE_STATUSES = ("OPEN", "CLOSED", "UNVERIFIED")
CLOSURE_SCOPE_CONTRACT = "gap-closure-scope/v1"
AUDIT_VERDICTS = ("PASS", "REVISE", "BLOCK")
QUALITY_DIMENSIONS = (
    "importance",
    "openness",
    "falsifiability",
    "information_gain",
    "mechanism_clarity",
    "feasibility",
)
QUALITY_WEIGHTS = {
    "importance": 0.25,
    "openness": 0.10,
    "falsifiability": 0.20,
    "information_gain": 0.20,
    "mechanism_clarity": 0.20,
    "feasibility": 0.05,
}

# hunter name -> (gap-id prefix, the lens, the signal fields that set its gap type)
HUNTERS = {
    "future-work-miner": ("FW", "stated future work / limitations the authors themselves name",
                          'set `statement` + `source_ref`; derived_from ["future_work"]'),
    "weakness-spotter": ("WK", "methodological weaknesses that are improvement opportunities",
                         'set `locus` + `opportunity`; derived_from ["weakness_opportunity"]'),
    "white-space-mapper": ("WS", "coverage white space — combinations/settings nobody touched",
                           'set `white_space_present:true`; derived_from ["white_space_present"]'),
    "cross-domain-transfer-scout": ("XF", "methods proven elsewhere, untried in this domain",
                                    'set `source_domain` + `target_hook`; derived_from ["transfer_potential"]'),
    "contrarian-angle-generator": ("CA", "assumptions everyone shares that may be wrong",
                                   'set `challenged_assumption`; derived_from ["contrarian_angle"]'),
}
POST_HUNTER_DEPENDENCIES = {
    "gap-prosecutor": tuple(HUNTERS),
    "mechanism-synthesizer": ("gap-prosecutor",),
    "gap-quality-auditor": ("gap-prosecutor", "mechanism-synthesizer"),
}

HUNTER_PROMPT = """You are the {hunter} of a research machine — ONE of five independent gap hunters \
scanning a real knowledge vault in parallel. Your lens (hunt ONLY this): {lens}.

    REQUEST: {request}

{north_star}

Read the real vault at `{vault}/02-wiki/papers/` (glob the .md pages relevant to the request; read \
~8-12 fully). IF `{run_dir}/inbox/search-results.json` exists, use its live-retrieval records to \
avoid proposing gaps recent literature already closed.

HONESTY (hard): reference papers ONLY by their real `[[slug]]`; never invent a slug (a deterministic \
gate checks every slug against the vault). Ground every signal in what a page actually states. Stay \
inside YOUR lens — the other four hunters cover the rest; overlap wastes the panel's diversity.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit \
the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json):
{{
  "signals": [{{"gap_id":"{prefix}-1","statement":"<the gap, one sharp sentence>",
     "source_ref":"[[<slug>]]","evidence_ref":["[[<slug>]]"],
     {type_fields_hint}}}]
}}
Quantities: 2-4 signals, ids {prefix}-1.. ; field discipline: {type_fields}. \
After writing, verify valid JSON. Return one line: pages read + your sharpest gap."""

_TYPE_FIELDS_HINT = '"derived_from":["<your lens tag>"], "...type-setting fields per your lens..."'

PROSECUTOR_PROMPT = """You are the independent `gap-prosecutor`. You did not generate the gaps and
must try to close them. Read all five frozen hunter bundles:
{hunter_inputs}
Also read `{run_dir}/inbox/search-results.json` when present. For every gap, run targeted searches
for the exact method/problem/setting combination; when available, use the scholarly connector or
harness web search and record the actual query. Inspect the paper, not only its title.
A CLOSED decision must be auditable from a run-local UTF-8 full-text snapshot; title, abstract, or
source existence alone can never close a gap.

{north_star}

Status contract:
- CLOSED only when a specific real paper already completed the material scope and reports a result.
  It requires `closure_evidence` with source_ref, title, completed_scope, reported_result,
  result_locator, and `scope_verification`. Save the inspected full text under this run's `inbox/`,
  bind its SHA-256, and quote separate exact spans for scope and result. The deterministic gate reopens
  the snapshot and verifies both character ranges.
- OPEN requires positive evidence of an unresolved limitation/boundary, with a source and locator.
- A failed, unavailable, or bounded search is UNVERIFIED. "No paper found" never proves openness.

Write ONLY JSON to `{out}` with exactly one prosecution per hunter gap:
{{"prosecutions":[{{
  "gap_id":"FW-1","search_query":"<targeted query>",
  "closure_status":"OPEN|CLOSED|UNVERIFIED","why_status":"<evidence-bounded reason>",
  "strongest_prior_art":[{{"source_ref":"[[slug]] or doi:/arXiv:","title":"<title>",
    "relationship":"same|adjacent|precursor","result_locator":"<page/section/table>"}}],
  "positive_open_evidence":[{{"source_ref":"[[slug]]","open_scope_or_limitation":"<exact boundary>",
    "locator":"<page/section/table>"}}],
  "closure_evidence":[{{"source_ref":"[[slug]] or doi:/arXiv:","title":"<title>",
    "completed_scope":"<what was actually run>","reported_result":"<what was observed>",
    "result_locator":"<page/section/table/result>",
    "scope_verification":{{"contract_version":"gap-closure-scope/v1",
      "verification_method":"fulltext_snapshot","independent_of_hunter":true,
      "snapshot_ref":"inbox/closure-snapshots/<gap>.txt",
      "document_hash":"sha256:<64 lowercase hex>","parser_version":"<extractor/version>",
      "scope_span":{{"start_char":0,"end_char":42,"exact_quote":"<exact scope quote>"}},
      "result_span":{{"start_char":43,"end_char":91,"exact_quote":"<exact result quote>"}},
      "scope_match_rationale":"<why materially same scope>",
      "result_match_rationale":"<why this is a completed result>"}}}}],
  "strongest_counterevidence":"<best reason this is not a gap>",
  "evidence_ref":["<real source ref>"]
}}]}}
Use empty arrays when the corresponding positive evidence does not exist. Never rank or bet."""

SYNTHESIZER_PROMPT = """You are the independent `mechanism-synthesizer`. Read the five frozen hunter
bundles and the completed prosecutor bundle:
{hunter_inputs}
- `{prosecutor_input}`

{north_star}

Build exactly one dossier for every gap whose prosecutor status is OPEN or UNVERIFIED; omit only
evidenced CLOSED gaps. Integrate related signals across hunters through `related_gap_ids`, but keep
one primary `gap_id` so every survivor remains traceable.

Knowledge quadrant contract:
- Known Known: established facts that bound the proposed question.
- Unknown Known: relevant knowledge exists in another field/source but has not been connected here.
- Known Unknown: the literature explicitly recognizes the uncertainty or open boundary.
- Unknown Unknown: a hidden assumption/blind spot inferred from anomalies; treat it as high risk.

Write ONLY JSON to `{out}`:
{{"dossiers":[{{
  "gap_id":"FW-1","related_gap_ids":[],"knowledge_quadrant":"Known Unknown",
  "quadrant_basis":"<why this quadrant, with evidence>",
  "problem_statement":"<precise research question>","evidence_refs":["<real ref>"],
  "why_open":"<what the closest work still does not establish>",
  "recent_prior_art":[{{"source_ref":"<real ref>","contribution":"<what it established>",
    "remaining_boundary":"<what remains unresolved>"}}],
  "mechanism_chain":["<cause/constraint>","<mediator or intervention>","<observable outcome>"],
  "cross_domain_bridge":{{"source_domain":"<field or none identified>",
    "transferable_mechanism":"<mechanism or none identified>","target_fit":"<why it may fit>",
    "boundary_conditions":"<where transfer should fail>"}},
  "strongest_counterargument":"<best scientific objection>",
  "counterevidence":["<specific contrary result or unresolved objection>"],
  "minimum_discriminating_experiment":{{"hypothesis":"<falsifiable statement>",
    "intervention":"<one minimal contrast>","baseline_controls":["<control>"],
    "primary_outcome":"<measurable outcome>","success_threshold":"<predeclared threshold>",
    "failure_threshold":"<what refutes/weakens it>","kill_criteria":"<stop condition>"}},
  "resources":{{"data":"<needed data>","compute":"<needed compute>",
    "implementation":"<needed implementation>","estimated_effort":"<bounded estimate>"}},
  "next_step":"<single next evidence-producing action>"
}}]}}
Do not invent an experiment result or select a winning gap."""

AUDITOR_PROMPT = """You are the independent `gap-quality-auditor`. Read all frozen hunter bundles,
the prosecutor bundle, and the mechanism dossier bundle:
{hunter_inputs}
- `{prosecutor_input}`
- `{synthesizer_input}`

{north_star}

Audit every surviving dossier independently. Score each dimension 1-5 and justify it with a concrete
scientific reason: importance, openness, falsifiability, information_gain, mechanism_clarity, and
feasibility. Feasibility is deliberately only a small dimension; easy work is not automatically good
science. Name the strongest objection and missing evidence. PASS means dossier-complete for human
review, not approval; REVISE means repairable; BLOCK means currently untestable, unsupported, or
materially contradicted. Never bet, select, approve, or write a director decision.

Write ONLY JSON to `{out}`:
{{"audits":[{{
  "gap_id":"FW-1","verdict":"PASS|REVISE|BLOCK",
  "dimensions":{{
    "importance":{{"score":1,"rationale":"<why>"}},
    "openness":{{"score":1,"rationale":"<why>"}},
    "falsifiability":{{"score":1,"rationale":"<why>"}},
    "information_gain":{{"score":1,"rationale":"<why>"}},
    "mechanism_clarity":{{"score":1,"rationale":"<why>"}},
    "feasibility":{{"score":1,"rationale":"<why>"}}
  }},
  "strongest_objection":"<best reason not to spend research budget>",
  "required_repairs":["<repair or missing evidence>"],
  "evidence_ref":["<real predecessor/source ref>"]
}}]}}"""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def pre_search(run_dir: str, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Live-retrieval pre-step (audit H5/M1)."""
    return _shared.pre_search(run_dir, request, ts, transport=transport,
                              sources=sources, limit_per_source=limit_per_source)


def _bundle_path(run_dir, agent: str) -> Path:
    return Path(run_dir) / "inbox" / f"DISCOVER.{agent}.bundle.json"


def _input_list(run_dir: str, agents) -> str:
    return "\n".join(f"- `{_bundle_path(run_dir, agent).as_posix()}`" for agent in agents)


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    """Return a four-wave panel: five blind hunters, then prosecution, synthesis, and audit."""
    if stage != "DISCOVER":
        return None
    ns_block = _shared.north_star_block(run_dir)
    workers = []
    for hunter, (prefix, lens, type_fields) in HUNTERS.items():
        out = str(_bundle_path(run_dir, hunter)).replace("\\", "/")
        workers.append({
            "label": hunter, "model": _worker_model(model_policy), "output": out,
            "depends_on": [], "execution_group": "blind-hunters",
            "prompt": HUNTER_PROMPT.format(hunter=hunter, lens=lens, request=request,
                                           north_star=ns_block, vault=vault, run_dir=run_dir,
                                           out=out, prefix=prefix, type_fields=type_fields,
                                           type_fields_hint=_TYPE_FIELDS_HINT)})

    hunter_inputs = _input_list(run_dir, HUNTERS)
    prosecutor_path = _bundle_path(run_dir, "gap-prosecutor")
    synthesizer_path = _bundle_path(run_dir, "mechanism-synthesizer")
    post_prompts = {
        "gap-prosecutor": PROSECUTOR_PROMPT.format(
            hunter_inputs=hunter_inputs,
            run_dir=run_dir,
            north_star=ns_block,
            out=prosecutor_path.as_posix(),
        ),
        "mechanism-synthesizer": SYNTHESIZER_PROMPT.format(
            hunter_inputs=hunter_inputs,
            prosecutor_input=prosecutor_path.as_posix(),
            north_star=ns_block,
            out=synthesizer_path.as_posix(),
        ),
        "gap-quality-auditor": AUDITOR_PROMPT.format(
            hunter_inputs=hunter_inputs,
            prosecutor_input=prosecutor_path.as_posix(),
            synthesizer_input=synthesizer_path.as_posix(),
            north_star=ns_block,
            out=_bundle_path(run_dir, "gap-quality-auditor").as_posix(),
        ),
    }
    for agent in POST_HUNTER_AGENTS:
        workers.append({
            "label": agent,
            "model": _worker_model(model_policy),
            "output": _bundle_path(run_dir, agent).as_posix(),
            "depends_on": list(POST_HUNTER_DEPENDENCIES[agent]),
            "execution_group": agent,
            "prompt": post_prompts[agent],
        })

    return {
        "label": "gap-breadth-scientific-panel",
        "workers": workers,
        "worker_order": [*HUNTERS, *POST_HUNTER_AGENTS],
        "parallel_groups": [list(HUNTERS), ["gap-prosecutor"],
                            ["mechanism-synthesizer"], ["gap-quality-auditor"]],
        "panel_note": (
            "Wave 1: spawn all FIVE hunters in parallel and keep them mutually blind. Freeze their "
            "bundles. Waves 2-4: spawn gap-prosecutor, mechanism-synthesizer, and gap-quality-auditor "
            "strictly in that order; each reads the named predecessor bundles. Then run-dets."
        ),
    }


def _load_hunter_bundles(run_dir) -> dict:
    bundles, missing = {}, []
    for hunter in HUNTERS:
        p = _bundle_path(run_dir, hunter)
        if not p.exists():
            missing.append(hunter)
            continue
        bundles[hunter] = json.loads(p.read_text(encoding="utf-8"))
    if missing:
        raise GateBlock(
            f"gap_breadth DISCOVER: hunter bundle(s) missing for {missing} — spawn ALL five "
            "hunters (see llm_step) before run-dets; the panel's diversity is structural")
    return bundles


def _load_post_hunter_bundles(run_dir) -> dict:
    bundles, missing = {}, []
    for agent in POST_HUNTER_AGENTS:
        p = _bundle_path(run_dir, agent)
        if not p.exists():
            missing.append(agent)
            continue
        try:
            bundles[agent] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateBlock(f"gap_breadth DISCOVER: invalid {agent} bundle: {exc}") from exc
    if missing:
        raise GateBlock(
            f"gap_breadth DISCOVER: staged worker bundle(s) missing for {missing} — dispatch "
            "gap-prosecutor -> mechanism-synthesizer -> gap-quality-auditor after the five hunters"
        )
    return bundles


def gap_scan_path(run_dir) -> Path:
    return Path(run_dir) / GAP_SCAN_REL


def _text(value: object, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise GateBlock(f"gap_breadth dossier contract BLOCK: `{field}` must be non-empty")
    return value


def _list(value: object, field: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list):
        raise GateBlock(f"gap_breadth dossier contract BLOCK: `{field}` must be a list")
    if nonempty and not value:
        raise GateBlock(f"gap_breadth dossier contract BLOCK: `{field}` must not be empty")
    return value


def _dict(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise GateBlock(f"gap_breadth dossier contract BLOCK: `{field}` must be an object")
    return value


def _text_list(value: object, field: str, *, nonempty: bool = False) -> list[str]:
    values = _list(value, field, nonempty=nonempty)
    for index, item in enumerate(values):
        _text(item, f"{field}[{index}]")
    return [str(item).strip() for item in values]


def _index_gap_items(items: object, field: str) -> dict[str, dict]:
    rows = _list(items, field)
    indexed = {}
    for index, row in enumerate(rows):
        row = _dict(row, f"{field}[{index}]")
        gap_id = _text(row.get("gap_id"), f"{field}[{index}].gap_id")
        if gap_id in indexed:
            raise GateBlock(f"gap_breadth dossier contract BLOCK: duplicate gap_id `{gap_id}` in {field}")
        indexed[gap_id] = row
    return indexed


def _require_exact_coverage(actual: set[str], expected: set[str], field: str) -> None:
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    if missing or extra:
        raise GateBlock(
            f"gap_breadth dossier contract BLOCK: {field} coverage mismatch; "
            f"missing={missing}, extra={extra}"
        )


def _resolvable_source_ref(value: object) -> bool:
    ref = str(value or "").strip()
    lowered = ref.lower()
    return bool(
        re.fullmatch(r"\[\[[^\[\]]+\]\]", ref)
        or lowered.startswith(("doi:", "arxiv:", "http://", "https://"))
    )


def _status_source_ref(value: object) -> bool:
    """Status-changing evidence needs a scholarly id or a vault page, not a bare web URL."""
    ref = str(value or "").strip()
    lowered = ref.lower()
    return bool(
        re.fullmatch(r"\[\[[^\[\]]+\]\]", ref)
        or lowered.startswith(("doi:", "arxiv:"))
    )


def _closure_snapshot(run_dir: str, snapshot_ref: str, gap_id: str) -> tuple[Path, bytes, str]:
    ref_path = Path(snapshot_ref)
    if ref_path.is_absolute():
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} snapshot_ref must be run-relative"
        )
    run_root = Path(run_dir).resolve()
    inbox_root = (run_root / "inbox").resolve()
    snapshot = (run_root / ref_path).resolve()
    try:
        snapshot.relative_to(inbox_root)
    except ValueError as exc:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} snapshot_ref must stay under run inbox/"
        ) from exc
    if not snapshot.is_file():
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} full-text snapshot missing at {snapshot_ref}"
        )
    raw = snapshot.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} snapshot must be UTF-8 full text"
        ) from exc
    return snapshot, raw, text


def _validate_exact_span(span: object, text: str, field: str, gap_id: str) -> str:
    row = _dict(span, field)
    start = row.get("start_char")
    end = row.get("end_char")
    quote = _text(row.get("exact_quote"), f"{field}.exact_quote")
    if isinstance(start, bool) or isinstance(end, bool) \
            or not isinstance(start, int) or not isinstance(end, int):
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} {field} needs integer character offsets"
        )
    if start < 0 or end <= start or end > len(text):
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} {field} range [{start}, {end}) is outside "
            f"the {len(text)}-character snapshot"
        )
    if len(quote.strip()) < 16:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} {field} exact_quote is too thin"
        )
    if text[start:end] != quote:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} {field} exact_quote does not match the "
            "snapshot at the declared offsets"
        )
    return quote


def _ascii_content_tokens(value: object) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 4
    }


def _require_material_overlap(statement: str, quote: str, field: str, gap_id: str) -> None:
    statement_tokens = _ascii_content_tokens(statement)
    quote_tokens = _ascii_content_tokens(quote)
    if len(statement_tokens) < 3 or len(quote_tokens) < 3:
        return
    overlap = len(statement_tokens & quote_tokens) / len(statement_tokens)
    if overlap < 0.25:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} {field} has no material lexical binding "
            f"to its exact full-text span (overlap={overlap:.2f})"
        )


def _validate_closure_scope(run_dir: str, gap_id: str, paper: dict, field: str) -> None:
    verification = _dict(paper.get("scope_verification"), f"{field}.scope_verification")
    if verification.get("contract_version") != CLOSURE_SCOPE_CONTRACT:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} requires "
            f"scope_verification.contract_version={CLOSURE_SCOPE_CONTRACT!r}"
        )
    if verification.get("verification_method") != "fulltext_snapshot":
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} closure must be verified from a fulltext_snapshot"
        )
    if verification.get("independent_of_hunter") is not True:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} scope verification must be independent of "
            "the proposing hunter"
        )
    snapshot_ref = _text(
        verification.get("snapshot_ref"), f"{field}.scope_verification.snapshot_ref")
    document_hash = _text(
        verification.get("document_hash"), f"{field}.scope_verification.document_hash")
    _text(verification.get("parser_version"), f"{field}.scope_verification.parser_version")
    _text(verification.get("scope_match_rationale"),
          f"{field}.scope_verification.scope_match_rationale")
    _text(verification.get("result_match_rationale"),
          f"{field}.scope_verification.result_match_rationale")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", document_hash):
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} document_hash must be lowercase sha256"
        )
    _snapshot, raw, text = _closure_snapshot(run_dir, snapshot_ref, gap_id)
    actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_hash != document_hash:
        raise GateBlock(
            f"gap_breadth closure scope BLOCK: {gap_id} full-text snapshot hash mismatch"
        )
    scope_quote = _validate_exact_span(
        verification.get("scope_span"), text, f"{field}.scope_verification.scope_span", gap_id)
    result_quote = _validate_exact_span(
        verification.get("result_span"), text, f"{field}.scope_verification.result_span", gap_id)
    completed_scope = _text(paper.get("completed_scope"), f"{field}.completed_scope")
    reported_result = _text(paper.get("reported_result"), f"{field}.reported_result")
    _require_material_overlap(completed_scope, scope_quote, "completed_scope", gap_id)
    _require_material_overlap(reported_result, result_quote, "reported_result", gap_id)


def _validate_prosecutions(bundle: dict, signal_ids: set[str], run_dir: str) -> dict[str, dict]:
    prosecutions = _index_gap_items(bundle.get("prosecutions"), "prosecutions")
    _require_exact_coverage(set(prosecutions), signal_ids, "prosecutions")
    for gap_id, row in prosecutions.items():
        _text(row.get("search_query"), f"prosecutions[{gap_id}].search_query")
        status = _text(row.get("closure_status"), f"prosecutions[{gap_id}].closure_status")
        if status not in CLOSURE_STATUSES:
            raise GateBlock(
                f"gap_breadth closure gate BLOCK: {gap_id} has invalid status {status!r}; "
                f"allowed={list(CLOSURE_STATUSES)}"
            )
        _text(row.get("why_status"), f"prosecutions[{gap_id}].why_status")
        _text(row.get("strongest_counterevidence"),
              f"prosecutions[{gap_id}].strongest_counterevidence")
        _text_list(row.get("evidence_ref"), f"prosecutions[{gap_id}].evidence_ref", nonempty=True)

        prior_art = _list(row.get("strongest_prior_art"),
                          f"prosecutions[{gap_id}].strongest_prior_art")
        for index, paper in enumerate(prior_art):
            paper = _dict(paper, f"prosecutions[{gap_id}].strongest_prior_art[{index}]")
            source_ref = _text(paper.get("source_ref"),
                               f"prosecutions[{gap_id}].strongest_prior_art[{index}].source_ref")
            if not _resolvable_source_ref(source_ref):
                raise GateBlock(
                    f"gap_breadth prior-art gate BLOCK: {gap_id} source_ref must be a resolvable "
                    "wikilink, DOI, arXiv id, or URL"
                )
            for key in ("title", "relationship", "result_locator"):
                _text(paper.get(key),
                      f"prosecutions[{gap_id}].strongest_prior_art[{index}].{key}")

        open_evidence = _list(row.get("positive_open_evidence"),
                              f"prosecutions[{gap_id}].positive_open_evidence")
        closure_evidence = _list(row.get("closure_evidence"),
                                 f"prosecutions[{gap_id}].closure_evidence")
        if status == "CLOSED":
            if not closure_evidence:
                raise GateBlock(
                    f"gap_breadth closure gate BLOCK: {gap_id} CLOSED requires exact "
                    "completed-paper evidence"
                )
            for index, paper in enumerate(closure_evidence):
                field = f"prosecutions[{gap_id}].closure_evidence[{index}]"
                paper = _dict(paper, field)
                source_ref = _text(
                    paper.get("source_ref"),
                    f"{field}.source_ref",
                )
                if not _status_source_ref(source_ref):
                    raise GateBlock(
                        f"gap_breadth closure gate BLOCK: {gap_id} closure source_ref must be a "
                        "vault wikilink, DOI, or arXiv id"
                    )
                for key in ("title", "completed_scope", "reported_result", "result_locator"):
                    _text(paper.get(key),
                          f"{field}.{key}")
                _validate_closure_scope(run_dir, gap_id, paper, field)
        elif closure_evidence:
            raise GateBlock(
                f"gap_breadth closure gate BLOCK: {gap_id} carries closure evidence but status is "
                f"{status}; resolve the contradiction"
            )

        if status == "OPEN":
            if not open_evidence:
                raise GateBlock(
                    f"gap_breadth openness gate BLOCK: {gap_id} OPEN requires positive source-located "
                    "evidence; no search hit is only UNVERIFIED"
                )
            for index, evidence in enumerate(open_evidence):
                evidence = _dict(evidence,
                                 f"prosecutions[{gap_id}].positive_open_evidence[{index}]")
                source_ref = _text(
                    evidence.get("source_ref"),
                    f"prosecutions[{gap_id}].positive_open_evidence[{index}].source_ref",
                )
                if not _status_source_ref(source_ref):
                    raise GateBlock(
                        f"gap_breadth openness gate BLOCK: {gap_id} open-evidence ref must be a "
                        "vault wikilink, DOI, or arXiv id"
                    )
                for key in ("open_scope_or_limitation", "locator"):
                    _text(evidence.get(key),
                          f"prosecutions[{gap_id}].positive_open_evidence[{index}].{key}")
        elif open_evidence:
            raise GateBlock(
                f"gap_breadth openness gate BLOCK: {gap_id} carries positive open evidence but status "
                f"is {status}; resolve the contradiction"
            )
    return prosecutions


def _status_evidence_refs(prosecutions: dict[str, dict]) -> list[str]:
    refs = []
    for row in prosecutions.values():
        field = "closure_evidence" if row["closure_status"] == "CLOSED" else \
            "positive_open_evidence" if row["closure_status"] == "OPEN" else None
        if field:
            refs.extend(str(item["source_ref"]).strip() for item in row[field])
    return list(dict.fromkeys(refs))


def _validate_dossiers(bundle: dict, prosecutions: dict[str, dict],
                       signal_ids: set[str]) -> dict[str, dict]:
    dossiers = _index_gap_items(bundle.get("dossiers"), "dossiers")
    survivors = {
        gap_id for gap_id, row in prosecutions.items()
        if row["closure_status"] != "CLOSED"
    }
    _require_exact_coverage(set(dossiers), survivors, "dossiers")
    for gap_id, row in dossiers.items():
        related = _text_list(row.get("related_gap_ids"), f"dossiers[{gap_id}].related_gap_ids")
        unknown_related = sorted(set(related) - signal_ids)
        if gap_id in related or unknown_related:
            raise GateBlock(
                f"gap_breadth dossier contract BLOCK: {gap_id} related_gap_ids invalid; "
                f"self_reference={gap_id in related}, unknown={unknown_related}"
            )
        quadrant = _text(row.get("knowledge_quadrant"),
                         f"dossiers[{gap_id}].knowledge_quadrant")
        if quadrant not in KNOWLEDGE_QUADRANTS:
            raise GateBlock(
                f"gap_breadth quadrant gate BLOCK: {gap_id} uses {quadrant!r}; "
                f"allowed={list(KNOWLEDGE_QUADRANTS)}"
            )
        for key in ("quadrant_basis", "problem_statement", "why_open",
                    "strongest_counterargument", "next_step"):
            _text(row.get(key), f"dossiers[{gap_id}].{key}")
        if prosecutions[gap_id]["closure_status"] == "UNVERIFIED" and \
                "unverified" not in str(row.get("why_open") or "").lower():
            raise GateBlock(
                f"gap_breadth honesty gate BLOCK: {gap_id} is UNVERIFIED; why_open must say so "
                "instead of presenting absence-of-search as an open gap"
            )
        _text_list(row.get("evidence_refs"), f"dossiers[{gap_id}].evidence_refs", nonempty=True)
        prior_art = _list(row.get("recent_prior_art"),
                          f"dossiers[{gap_id}].recent_prior_art", nonempty=True)
        for index, paper in enumerate(prior_art):
            paper = _dict(paper, f"dossiers[{gap_id}].recent_prior_art[{index}]")
            for key in ("source_ref", "contribution", "remaining_boundary"):
                _text(paper.get(key), f"dossiers[{gap_id}].recent_prior_art[{index}].{key}")
        mechanism = _text_list(row.get("mechanism_chain"),
                               f"dossiers[{gap_id}].mechanism_chain", nonempty=True)
        if len(mechanism) < 2:
            raise GateBlock(
                f"gap_breadth mechanism gate BLOCK: {gap_id} needs at least two linked mechanism steps"
            )
        bridge = _dict(row.get("cross_domain_bridge"),
                       f"dossiers[{gap_id}].cross_domain_bridge")
        for key in ("source_domain", "transferable_mechanism", "target_fit", "boundary_conditions"):
            _text(bridge.get(key), f"dossiers[{gap_id}].cross_domain_bridge.{key}")
        _text_list(row.get("counterevidence"), f"dossiers[{gap_id}].counterevidence", nonempty=True)

        experiment = _dict(row.get("minimum_discriminating_experiment"),
                           f"dossiers[{gap_id}].minimum_discriminating_experiment")
        for key in ("hypothesis", "intervention", "primary_outcome", "success_threshold",
                    "failure_threshold", "kill_criteria"):
            _text(experiment.get(key),
                  f"dossiers[{gap_id}].minimum_discriminating_experiment.{key}")
        _text_list(experiment.get("baseline_controls"),
                   f"dossiers[{gap_id}].minimum_discriminating_experiment.baseline_controls",
                   nonempty=True)
        resources = _dict(row.get("resources"), f"dossiers[{gap_id}].resources")
        for key in ("data", "compute", "implementation", "estimated_effort"):
            _text(resources.get(key), f"dossiers[{gap_id}].resources.{key}")
    return dossiers


def _validate_audits(bundle: dict, survivor_ids: set[str]) -> dict[str, dict]:
    audits = _index_gap_items(bundle.get("audits"), "audits")
    _require_exact_coverage(set(audits), survivor_ids, "audits")
    for gap_id, row in audits.items():
        verdict = _text(row.get("verdict"), f"audits[{gap_id}].verdict")
        if verdict not in AUDIT_VERDICTS:
            raise GateBlock(
                f"gap_breadth quality gate BLOCK: {gap_id} verdict {verdict!r} is invalid"
            )
        dimensions = _dict(row.get("dimensions"), f"audits[{gap_id}].dimensions")
        missing = sorted(set(QUALITY_DIMENSIONS) - set(dimensions))
        if missing:
            raise GateBlock(
                f"gap_breadth quality gate BLOCK: {gap_id} missing quality dimensions {missing}"
            )
        for dimension in QUALITY_DIMENSIONS:
            item = _dict(dimensions[dimension], f"audits[{gap_id}].dimensions.{dimension}")
            score = item.get("score")
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise GateBlock(
                    f"gap_breadth quality gate BLOCK: {gap_id}.{dimension}.score must be integer 1-5"
                )
            _text(item.get("rationale"), f"audits[{gap_id}].dimensions.{dimension}.rationale")
        _text(row.get("strongest_objection"), f"audits[{gap_id}].strongest_objection")
        repairs = _text_list(row.get("required_repairs"), f"audits[{gap_id}].required_repairs")
        if verdict != "PASS" and not repairs:
            raise GateBlock(
                f"gap_breadth quality gate BLOCK: {gap_id} {verdict} requires a concrete repair list"
            )
        _text_list(row.get("evidence_ref"), f"audits[{gap_id}].evidence_ref", nonempty=True)
    return audits


def _collect_wikilinks(value: object) -> list[str]:
    if isinstance(value, dict):
        return [ref for item in value.values() for ref in _collect_wikilinks(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _collect_wikilinks(item)]
    if isinstance(value, str):
        return re.findall(r"\[\[[^\[\]]+\]\]", value)
    return []


def _write_gap_scan_markdown(run_dir, classification: dict, novelty: dict,
                             signals: list[dict], prosecutions: dict[str, dict],
                             dossiers: dict[str, dict], audits: dict[str, dict],
                             grounded: bool) -> str:
    out = gap_scan_path(run_dir)
    text = render_gap_scan(
        classification, novelty, signals, prosecutions, dossiers, audits,
        QUALITY_DIMENSIONS, QUALITY_WEIGHTS, grounded,
    )
    errors = lint_gap_scan(text, {str(signal["gap_id"]) for signal in signals})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    advisory = {
        "contract_version": "research-markdown-advisory/v1",
        "delivery_blocking": False,
        "delivery_status": "USABLE" if not errors else "USABLE_WITH_CAVEATS",
        "warnings": errors,
    }
    advisory_path = Path(run_dir) / "inbox" / "gap-markdown-quality-advisory.json"
    advisory_path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out)


def _discover_dets(run_dir, ts) -> tuple:
    bundles = _load_hunter_bundles(run_dir)
    staged = _load_post_hunter_bundles(run_dir)
    paths = []
    signals, per_hunter = [], {}
    for hunter, b in bundles.items():
        _shared.require_bundle_keys(b, ("signals",), stage="DISCOVER", mode=f"gap_breadth[{hunter}]")
        hs = [s for s in b["signals"] if isinstance(s, dict)]
        per_hunter[hunter] = len(hs)
        signals += hs
    if not signals:
        raise GateBlock("gap_breadth DISCOVER: all five hunters returned zero signals — nothing to classify")

    signal_map = _index_gap_items(signals, "hunter_signals")
    prosecutions = _validate_prosecutions(staged["gap-prosecutor"], set(signal_map), run_dir)
    dossiers = _validate_dossiers(
        staged["mechanism-synthesizer"], prosecutions, set(signal_map)
    )
    audits = _validate_audits(staged["gap-quality-auditor"], set(dossiers))

    # NORTH-STAR drift gate over the merged panel output (audit H2).
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts,
                                      [str(s.get("statement") or "") for s in signals]
                                      + [str(d.get("problem_statement") or "")
                                         for d in dossiers.values()])
    paths.append(dpath)

    # Vault-slug referential integrity (audit H3): no worker may invent a vault page.
    root = _shared.resolve_vault_root(DEFAULT_VAULT)
    refs = _collect_wikilinks({"hunters": bundles, "staged": staged})
    violations, warnings = _shared.check_referential_integrity(
        refs, known_ids=set(), vault_slug_set=_shared.vault_slugs(root))
    if violations:
        raise GateBlock(f"vault-slug integrity BLOCK: {violations}")

    status_evidence_warnings = []
    status_refs = _status_evidence_refs(prosecutions)
    if status_refs:
        existence_path, existence = _shared.run_existence_gate(
            run_dir, "DISCOVER", ts, status_refs
        )
        paths.append(existence_path)
        status_evidence_warnings = existence.get("warnings") or []
        unresolved = [
            row["ref"] for row in existence.get("checked", [])
            if row.get("state") == "lookup_error"
        ]
        if unresolved:
            raise GateBlock(
                "gap_breadth status-evidence gate BLOCK: external status evidence could not be "
                f"existence-verified for {unresolved}; downgrade affected gaps to UNVERIFIED"
            )

    paths.append(write_artifact(
        run_dir, "DISCOVER", "gap-prosecution.artifact.json", "gap_prosecution",
        "gap-prosecutor", staged["gap-prosecutor"], ts))
    paths.append(write_artifact(
        run_dir, "DISCOVER", "gap-dossiers.artifact.json", "gap_dossier_set",
        "mechanism-synthesizer", staged["mechanism-synthesizer"], ts))
    paths.append(write_artifact(
        run_dir, "DISCOVER", "gap-quality-audit.artifact.json", "gap_quality_audit",
        "gap-quality-auditor", staged["gap-quality-auditor"], ts))

    gc = build_classification(signals)                       # fail-loud: a gap never silently vanishes
    paths.append(write_artifact(run_dir, "DISCOVER", "gap-classification.artifact.json",
                                "gap_classification", "gap-classifier", gc, ts))

    records = _shared.search_records(run_dir)
    ns_signals = _shared.novelty_signals_from_search(gc["gaps"], records)
    nv = aggregate_novelty(gc["gaps"], signals=ns_signals)   # SCORE-ONLY, never a cut
    paths.append(write_artifact(run_dir, "DISCOVER", "novelty-score.artifact.json",
                                "novelty_score", "novelty-scorer", nv, ts))

    overlaps = []
    surviving_gaps = [
        gap for gap in gc["gaps"]
        if prosecutions[str(gap["gap_id"])]["closure_status"] != "CLOSED"
    ]
    ws = workspace_for_run(run_dir)
    if ws is not None:
        run_id = _shared.task_frame(run_dir)["payload"]["task_id"]
        overlaps = prior_overlaps(surviving_gaps, load_gap_inventory(ws), run_id=run_id)
        append_gap_inventory(ws, run_id, ts, surviving_gaps)

    report = {"signals_per_hunter": per_hunter, "gaps_classified": len(gc["gaps"]),
              "novelty_grounded": bool(records), "prior_gap_overlaps": overlaps,
              "slug_warnings": warnings,
              "status_evidence_warnings": status_evidence_warnings,
              "closure_statuses": {gap_id: row["closure_status"]
                                   for gap_id, row in prosecutions.items()},
              "dossiers_built": len(dossiers),
              "quality_verdicts": {gap_id: row["verdict"] for gap_id, row in audits.items()},
              "closed_ids": sorted(set(signal_map) - set(dossiers))}
    report["director_gap_scan"] = _write_gap_scan_markdown(
        run_dir, gc, nv, signals, prosecutions, dossiers, audits, bool(records)
    )
    if not records:
        report["note"] = (
            "novelty is vault-only (no pre-search bundle); prosecution must leave search-absence "
            "cases UNVERIFIED until targeted retrieval is available"
        )
    return paths, report


def _report(run_dir, ts) -> tuple:
    note = {"summary": "gap_breadth scan: five blind hunters -> independent closure prosecution -> "
                       "mechanism dossiers -> six-dimension quality audit -> director Markdown; "
                       "the system does not self-bet",
            "references": [GAP_SCAN_REL.as_posix(),
                           "inbox/DISCOVER.gap-prosecutor.bundle.json",
                           "inbox/DISCOVER.mechanism-synthesizer.bundle.json",
                           "inbox/DISCOVER.gap-quality-auditor.bundle.json",
                           "evidence/DISCOVER/gap-prosecution.artifact.json",
                           "evidence/DISCOVER/gap-dossiers.artifact.json",
                           "evidence/DISCOVER/gap-quality-audit.artifact.json",
                           "evidence/DISCOVER/gap-classification.artifact.json",
                           "evidence/DISCOVER/novelty-score.artifact.json"],
            "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"gap_breadth has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop — a hunter's gate feedback re-dispatches only what failed."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
