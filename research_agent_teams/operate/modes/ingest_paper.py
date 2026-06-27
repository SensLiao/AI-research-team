"""Operate recipe for the `ingest_paper` mode (DISCOVER -> REPORT) — paper-reading upgrade P4.

The Tier-S quick typed note, operated: one DISCOVER worker distils ONE paper into the `paper_note`
SPINE — title / source_ref / summary / atomic claims, plus the OPTIONAL Stage-0 positioning
(paper_type / read_purpose / relation_to_thesis / reading_objective / reading_status) and the Pass-1
`paper_contract`. No deeper passes (those are the `read_paper_deep` mode). Ingestion produces DRAFT
knowledge only — it never freezes; the note reaches the vault only through /promote-to-vault.

Gate posture (gate_level record_only): a quick note is a cheap, low-commitment read, so there is no
director pause. The live gate is the north-star drift gate + the paper_note schema contract (a malformed
note BLOCKs with a readable error).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _shared
from ..artifacts import GateBlock, write_artifact
from ..bounded_repair import attempt_with_repair
from ...tools.validate_artifact import validate_payload

STAGES = ["DISCOVER", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

DISCOVER_WORKER_PROMPT = """You are the DISCOVER worker of the ingest_paper mode: distil ONE paper \
into a typed, citable NOTE (the Tier-S spine — no deep passes), for this request:

    REQUEST: {request}

{north_star}
Source (by reference, never inlined): the paper itself (its source_ref — a file path, [[slug]], DOI, \
or arXiv id).

HONESTY (hard): never invent a source_ref/DOI/slug; `claims` are atomic flat strings drawn from what \
the paper actually states; leave a positioning field null rather than guess it. Ingestion produces \
DRAFT knowledge — it never freezes and never decides anything.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names and re-emit \
the COMPLETE bundle.

Write ONLY this JSON to `{out}` (ends in .bundle.json):
{{
  "paper_note": {{"title":"<title>","source_ref":"<file/[[slug]]/DOI/arXiv>","summary":"<3-5 lines>",
     "claims":["<atomic claim>", ...],
     "methods":["<...>"],"datasets":["<...>"],"metrics":["<...>"],
     "paper_type":"method|theory|empirical|dataset-benchmark|tool|review|position",
     "read_purpose":"idea|method|baseline|related-work|reproduce|review",
     "relation_to_thesis":"A-core|B-related|C-background","reading_objective":"<one line>",
     "reading_status":"skimmed",
     "paper_contract":{{"category":"<...>","context":"<...>","correctness_prior":"<...>",
        "contributions":["<...>"],"clarity":"<...>",
        "contract_sentence":"problem -> method -> vs prior -> evidence -> applicability"}}}}
}}
The Stage-0 positioning + paper_contract are optional but preferred. After writing, verify valid JSON. \
Return one line: claims count + reading_status."""


def _worker_model(model_policy: str) -> str:
    return "opus" if model_policy == "max_quality" else "sonnet"


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "max_quality") -> Optional[dict]:
    if stage == "DISCOVER":
        out = f"{run_dir}/inbox/DISCOVER.bundle.json"
        return {"label": "literature-ingest-worker", "model": _worker_model(model_policy),
                "output": out,
                "prompt": DISCOVER_WORKER_PROMPT.format(request=request, out=out,
                                                        north_star=_shared.north_star_block(run_dir))}
    return None


def _load_bundle(run_dir, stage) -> dict:
    p = Path(run_dir) / "inbox" / f"{stage}.bundle.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{stage} worker bundle missing at {p} — dispatch the {stage} LLM worker first (see llm_step).")
    return json.loads(p.read_text(encoding="utf-8"))


def _discover_dets(run_dir, ts, b) -> tuple:
    _shared.require_bundle_keys(b, ("paper_note",), stage="DISCOVER", mode="ingest_paper")
    pn = b["paper_note"] or {}
    contract = pn.get("paper_contract") or {}
    texts = [str(pn.get("summary") or "")]
    texts += [str(c or "") for c in (pn.get("claims") or [])]
    texts.append(str(contract.get("contract_sentence") or ""))
    dpath, _ = _shared.run_drift_gate(run_dir, "DISCOVER", ts, texts)        # NORTH-STAR gate (H2)
    errs = validate_payload("paper_note", pn if isinstance(pn, dict) else {})
    if errs:
        raise GateBlock(f"ingest_paper paper_note schema BLOCK: {errs}")
    npath = write_artifact(run_dir, "DISCOVER", "paper-note.artifact.json",
                           "paper_note", "literature-ingest", pn, ts, status="draft")  # draft, never freezes
    return [dpath, npath], {"reading_status": pn.get("reading_status"),
                            "n_claims": len(pn.get("claims") or [])}


def _report(run_dir, ts) -> tuple:
    note = {"summary": "ingest_paper: one paper distilled into a typed paper_note (Tier-S spine). "
                       "Draft knowledge — promote via /promote-to-vault.",
            "references": [], "produced_artifacts": [], "open_questions": []}
    return ([write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                            "report_note", "research-orchestrator", note, ts)], {})


def run_dets(run_dir, stage, ts) -> tuple:
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts, _load_bundle(run_dir, "DISCOVER"))
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"ingest_paper has no stage {stage!r}")


def run_dets_with_repair(run_dir, stage, ts):
    """Bounded revise loop (OpenScholar shape): ok / retry-with-feedback / escalate at the cap."""
    return attempt_with_repair(run_dir, stage, _shared.budget(run_dir), ts,
                               lambda: run_dets(run_dir, stage, ts))
