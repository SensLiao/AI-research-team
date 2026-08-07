"""Operated Tier-S paper ingest: extract, independently verify, then report.

This mode remains deliberately smaller than ``read_paper_deep``. It performs a
skim-level typed extraction and an independent source/claim check, but it does
not attempt full method teardown, figure reading, result-table audit, novelty
judgment, or reproducibility assessment.

New runs use two ordered workers:

1. ``paper-note-extractor`` reads one source snapshot and emits a draft note
   plus atomic claim records.
2. ``source-claim-verifier`` independently reopens that same snapshot and
   judges source identity, every claim, summary scope, and structured fields.

The deterministic layer enforces complete coverage and reconstructs the final
``paper_note`` from supported content only. Historical ``DISCOVER.bundle.json``
files remain replayable, but are explicitly marked ``LEGACY_UNVERIFIED``.
Nothing in this mode writes the vault; promotion remains a human gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.ingest_paper_markdown import (
    legacy_verification,
    verify_and_filter_panel,
    write_quick_note_markdown,
)

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

EXTRACTOR_PROMPT = """You are the paper-note extractor in the Tier-S ingest_paper panel.

REQUEST: {request}

{north_star}

Read exactly ONE real source. Prefer an immutable local snapshot already under `{run_dir}/inbox/`;
otherwise use the exact DOI/arXiv/source reference supplied by the request. This is a skim, not a
deep read. Extract only what the source explicitly states. Do not judge correctness, novelty, project
value, or whether the note passes verification.

HONESTY:
- Never invent a title, source_ref, DOI, method, dataset, metric, or result.
- Keep claims atomic. A result claim must identify what was actually reported; do not turn an abstract
  aspiration, method description, or future-work statement into an empirical result.
- `snapshot_fingerprint` is `sha256:<64 hex>` for a local file, or an immutable DOI/arXiv/version id.
- Leave optional positioning fields null rather than guessing.
- If a REPAIR ATTEMPT is present, repair exactly the named contract failure and emit the full bundle.

Write ONLY JSON to `{out}`:
{{
  "worker_contract": {{"role":"paper-note-extractor","source_read":true}},
  "source_snapshot": {{
    "source_ref":"<exact file/DOI/arXiv ref>",
    "snapshot_ref":"<exact local snapshot path or immutable external snapshot ref>",
    "snapshot_fingerprint":"sha256:<64 hex> or immutable version id",
    "title":"<title from source>"
  }},
  "paper_note": {{
    "title":"<title>", "source_ref":"<same exact source_ref>",
    "summary":"<concise skim summary grounded in the source>",
    "claims":["<atomic source-stated claim>"],
    "methods":["<explicit method>"], "datasets":["<explicit dataset>"],
    "metrics":["<explicit metric>"],
    "paper_type":"method|theory|empirical|dataset-benchmark|tool|review|position",
    "read_purpose":"idea|method|baseline|related-work|reproduce|review",
    "relation_to_thesis":"A-core|B-related|C-background",
    "reading_objective":"<one line>", "reading_status":"skimmed",
    "paper_contract": {{
      "category":"<category>", "context":"<context>",
      "correctness_prior":"unverified skim",
      "contributions":["<source-stated contribution>"], "clarity":"<skim observation>",
      "contract_sentence":"problem -> method -> vs prior -> evidence -> applicability"
    }}
  }},
  "claim_records": [{{
    "claim_id":"C1", "claim":"<exact string also present in paper_note.claims>",
    "source_section":"<abstract/method/results/discussion/etc>",
    "source_location":"<page/section/table/figure when available>",
    "evidence_excerpt":"<short source excerpt>"
  }}]
}}

There must be exactly one claim_record for every paper_note claim. Verify valid JSON and stop."""

VERIFIER_PROMPT = """You are the independent source/claim verifier in the Tier-S ingest_paper panel.

{north_star}

You did not extract the note and must not rewrite it. First read the extractor bundle at
`{extractor_bundle}` only to learn the claimed source identity and items to check. Then independently
reopen the exact `source_snapshot.snapshot_ref`, verify its fingerprint when possible, and form your
own judgments from that source. Source existence or topical overlap is not support.

PASS requires local snapshot bytes that deterministic code can reopen and hash against
`snapshot_fingerprint`. A DOI/arXiv/URL identifier without a local immutable snapshot is
NEEDS_DEEP_READ and must request a fulltext snapshot; never self-attest external bytes.

Check all of the following:
1. source_ref and title match the reopened snapshot;
2. every atomic claim is explicitly supported, unsupported, or unclear;
3. the summary stays within what this skim can support;
4. every method/dataset/metric item is source-supported;
5. no abstract aspiration or method description has been presented as an empirical result.

Verdict rules:
- PASS: identity matches and every summary/claim/field item is supported with no section confusion.
- NEEDS_DEEP_READ: identity matches, but any content is partial, unsupported, unclear, or needs deeper
  inspection. This is a valid outcome; deterministic code will remove unsupported content.
- BLOCK: source identity/fingerprint fails, the source cannot be reopened, or verification cannot be
  performed honestly.

Do not include `paper_note` or `claim_records` in your output. Write ONLY JSON to `{out}`:
{{
  "worker_contract": {{
    "role":"source-claim-verifier",
    "independent_of_extractor":true,
    "reopened_source_snapshot":true
  }},
  "verification": {{
    "verdict":"PASS|NEEDS_DEEP_READ|BLOCK",
    "source_identity": {{
      "source_ref":"<exact source_ref>", "snapshot_ref":"<exact snapshot_ref>",
      "snapshot_fingerprint":"<exact fingerprint>", "verified_title":"<title from source>",
      "source_ref_match":true, "title_match":true
    }},
    "summary_result": {{"verdict":"SUPPORTED|PARTIAL|UNSUPPORTED","reason":"<why>"}},
    "claim_results": [{{
      "claim_id":"C1", "claim":"<exact extractor claim string>",
      "verdict":"SUPPORTED|UNSUPPORTED|UNCLEAR", "reason":"<claim-level reason>",
      "source_location":"<independently reopened location>",
      "section_confusion":false
    }}],
    "field_results": [{{
      "field":"methods|datasets|metrics", "item":"<exact extractor item>",
      "verdict":"SUPPORTED|UNSUPPORTED|UNCLEAR", "reason":"<why>"
    }}],
    "section_confusion_check": {{
      "abstract_or_method_presented_as_result":false, "reasons":[]
    }},
    "deep_read_reasons":[]
  }}
}}

Return exactly one claim_result per claim and one field_result per method/dataset/metric item. A PASS
with any non-supported item is contract-invalid and will be blocked."""


def _worker_model(model_policy: str, *, verifier: bool = False) -> str:
    if model_policy == "max_quality":
        return "opus"
    return "opus" if verifier else "sonnet"


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """Return the real ordered two-worker Tier-S ingest panel."""
    if stage != "DISCOVER":
        return None
    north_star = _shared.north_star_block(run_dir)
    extractor_out = f"{run_dir}/inbox/DISCOVER.paper-note-extractor.bundle.json"
    verifier_out = f"{run_dir}/inbox/DISCOVER.source-claim-verifier.bundle.json"
    workers = [
        {
            "label": "paper-note-extractor",
            "model": _worker_model(model_policy),
            "output": extractor_out,
            "task_capabilities": ["source_read", "pdf_or_fulltext_read", "atomic_claim_extraction"],
            "prompt": EXTRACTOR_PROMPT.format(
                request=request, north_star=north_star, run_dir=run_dir, out=extractor_out),
        },
        {
            "label": "source-claim-verifier",
            "model": _worker_model(model_policy, verifier=True),
            "output": verifier_out,
            "task_capabilities": ["source_reopen", "claim_entailment", "scope_audit"],
            "prompt": VERIFIER_PROMPT.format(
                north_star=north_star, extractor_bundle=extractor_out, out=verifier_out),
        },
    ]
    return {
        "label": "ingest-paper-panel",
        "workers": workers,
        "worker_order": [worker["label"] for worker in workers],
        "panel_note": (
            "spawn IN ORDER: extractor reads the source snapshot; verifier independently reopens "
            "that same snapshot and may only judge, never rewrite, the note"
        ),
    }


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateBlock(f"invalid ingest worker JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateBlock(f"ingest worker bundle must be a JSON object: {path}")
    return payload


def _extract_ingest_worker_bundle(raw: dict, agent: str) -> dict:
    required = (
        ("worker_contract", "source_snapshot", "paper_note", "claim_records")
        if agent == "paper-note-extractor"
        else ("worker_contract", "verification")
    )
    extracted = {
        key: _shared.extract_worker_bundle_value(
            raw, key, stage="DISCOVER", mode="ingest_paper", agent=agent,
        )
        for key in required
    }
    # Preserve explicit verifier overreach so the deterministic independence
    # check can reject it; representation unwrapping must never hide a worker
    # that attempted to rewrite the extractor's scientific output.
    if agent == "source-claim-verifier":
        for forbidden in ("paper_note", "claim_records"):
            if _shared.worker_bundle_has_key(raw, forbidden):
                extracted[forbidden] = _shared.extract_worker_bundle_value(
                    raw, forbidden, stage="DISCOVER", mode="ingest_paper", agent=agent,
                )
    return extracted


def _load_bundle(run_dir, stage) -> dict:
    root = Path(run_dir) / "inbox"
    if stage == "DISCOVER":
        extractor = root / "DISCOVER.paper-note-extractor.bundle.json"
        verifier = root / "DISCOVER.source-claim-verifier.bundle.json"
        if extractor.exists() or verifier.exists():
            missing = [path.name for path in (extractor, verifier) if not path.exists()]
            if missing:
                raise GateBlock(f"ingest_paper panel missing bundle(s): {missing}")
            return {
                "contract": "ingest-panel/v1",
                "extractor": _extract_ingest_worker_bundle(
                    _read_json(extractor), "paper-note-extractor"),
                "verifier": _extract_ingest_worker_bundle(
                    _read_json(verifier), "source-claim-verifier"),
            }

    legacy = root / f"{stage}.bundle.json"
    if not legacy.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {legacy}; dispatch the {stage} workers first")
    bundle = _read_json(legacy)
    return {"contract": "legacy-single-worker", "legacy_bundle": bundle}


def _relative_to_run(path: str, run_dir) -> str:
    try:
        return Path(path).resolve().relative_to(Path(run_dir).resolve()).as_posix()
    except ValueError:
        return str(path)


def _discover_dets(run_dir, ts, bundle) -> tuple:
    contract = bundle.get("contract")
    if contract == "ingest-panel/v1":
        try:
            paper_note, verification = verify_and_filter_panel(
                run_dir, bundle["extractor"], bundle["verifier"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GateBlock(f"ingest_paper verification BLOCK: {exc}") from exc
        created_by = "ingest-panel-deterministic-filter"
    elif contract == "legacy-single-worker":
        legacy = bundle["legacy_bundle"]
        paper_note = _shared.extract_worker_bundle_value(
            legacy, "paper_note", stage="DISCOVER", mode="ingest_paper",
            agent="legacy-single-worker",
        ) or {}
        verification = legacy_verification(paper_note)
        created_by = "literature-ingest-legacy-unverified"
    else:
        raise GateBlock(f"unknown ingest_paper bundle contract {contract!r}")

    contract_body = paper_note.get("paper_contract") or {}
    drift_texts = [str(paper_note.get("summary") or "")]
    drift_texts.extend(str(claim or "") for claim in (paper_note.get("claims") or []))
    drift_texts.append(str(contract_body.get("contract_sentence") or ""))
    drift_path, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, drift_texts)

    paper_note, errors, note_norm = _shared.normalize_worker_payload(
        run_dir, "DISCOVER", "paper-note-extractor", "paper_note", paper_note,
        label="paper-note",
    )
    verification, verification_errors, verification_norm = _shared.normalize_worker_payload(
        run_dir, "DISCOVER", "source-claim-verifier", "paper_note_verification",
        verification, label="paper-note-verification",
    )
    schema_defects = []
    if errors:
        schema_defects.append({
            "defect_id": "ingest-paper-note-schema",
            "category": "schema-semantic-gap",
            "location": "DISCOVER/paper_note",
            "summary": "; ".join(errors)[:4000],
            "target_agents": ["paper-note-extractor"],
            "refresh_agents": ["source-claim-verifier"],
        })
    if verification_errors:
        schema_defects.append({
            "defect_id": "ingest-paper-verification-schema",
            "category": "schema-semantic-gap",
            "location": "DISCOVER/paper_note_verification",
            "summary": "; ".join(verification_errors)[:4000],
            "target_agents": ["source-claim-verifier"],
            "refresh_agents": [],
        })
    if schema_defects:
        raise TargetedGateBlock(
            "ingest_paper payload needs a local supplement after automatic normalization",
            schema_defects,
        )

    note_path = write_artifact(
        run_dir, "DISCOVER", "paper-note.artifact.json", "paper_note", created_by,
        paper_note, ts, status="draft")
    verification_path = write_artifact(
        run_dir, "DISCOVER", "paper-note-verification.artifact.json",
        "paper_note_verification", "source-claim-verifier", verification, ts,
        status="draft")
    markdown_path = write_quick_note_markdown(run_dir, paper_note, verification)
    report = {
        "reading_status": paper_note.get("reading_status"),
        "n_claims": len(paper_note.get("claims") or []),
        "n_claims_submitted": verification.get("n_claims_submitted"),
        "verification_verdict": verification.get("verdict"),
        "legacy_unverified": verification.get("legacy_unverified", False),
        "director_markdown": _relative_to_run(markdown_path, run_dir),
        "representation_normalization": {
            "normalized_payloads": sum(
                1 for row in (note_norm, verification_norm)
                if row.get("changes") or row.get("preserved_extras")
            ),
            "format_changes": sum(
                len(row.get("changes") or []) for row in (note_norm, verification_norm)
            ),
            "preserved_extra_fields": sum(
                len(row.get("preserved_extras") or [])
                for row in (note_norm, verification_norm)
            ),
        },
    }
    return [drift_path, note_path, verification_path], report


def _report(run_dir, ts) -> tuple:
    review_dir = Path(run_dir) / "director-review" / "papers"
    markdown = sorted(review_dir.glob("*-quick-note.md")) if review_dir.exists() else []
    references = [_relative_to_run(str(path), run_dir) for path in markdown]
    summary = (
        "ingest_paper: ordered extractor + independent source/claim verifier produced a "
        "skimmed draft quick note; unsupported content was deterministically removed. "
        "This is not a deep read and is not promoted."
        if references else
        "ingest_paper REPORT found no quick-note Markdown; DISCOVER must complete first."
    )
    note = {
        "summary": summary,
        "references": references,
        "produced_artifacts": references,
        "open_questions": ["Run read_paper_deep before scientific citation or promotion."],
    }
    return ([write_artifact(
        run_dir, "REPORT", "report-note.artifact.json", "report_note",
        "research-orchestrator", note, ts)], {"director_markdown": references})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"ingest_paper has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded repair loop; deterministic verifier failures are never self-waived."""
    return attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts,
        lambda: run_dets(run_dir, stage, ts))
