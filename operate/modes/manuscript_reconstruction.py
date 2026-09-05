"""Operate recipe for `manuscript_reconstruction` (DISCOVER -> VERIFY -> REPORT) — 2026-08-20.

Responding to a REAL external review was, until today, the one standard research task with no
route: the ref-free-seg-qa Reject response was done freehand on the main thread with ~38 ad-hoc
scripts, because every suitable seat was an illegal dispatch for the running mode
(catalog E3/E4, `_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md`;
dispatch analysis in `_design/2026-08-20-team-upgrade/01-seats-and-dispatch.md` Q1).

v1 scope — deliberately narrow and honest about it:

  DISCOVER  external-review-decomposer atomises the review into typed points, verifies each
            against frozen artifacts, and assigns exactly one repair lane per point.
  VERIFY    manuscript-factual-auditor independently re-opens the cited evidence for every
            verified-true / verified-false / partially-true point — blind concurrence, not
            re-decomposition. Judgment DISSENTS do not silently rewrite anything: they are
            surfaced to the director as contested points. Mechanical failures (a ref that
            does not resolve, an unaudited point) BLOCK.
  REPORT    a deterministic reconstruction plan renders the lanes, owners, contested points
            and director decisions. No LLM writes the director Markdown.

The repairs themselves are NOT executed here: prose/mechanical lanes chain to a
`manuscript_authoring` run (`--upstream-run` this run), and the rebuilt manuscript is
re-reviewed by an independent `manuscript_review` run — authoring and review stay separate
runs (.claude/CLAUDE.md §4). This mode's product is the verified response plan, which is the
part that was actually missing. The fuller five-stage reconstruction (in-run repair panel)
is sketched in `_design/2026-08-20-team-upgrade/01-seats-and-dispatch.md` Q3 and stays a
registered next step, not a claim.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from xml.etree import ElementTree
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, TargetedGateBlock, write_artifact

STAGES = _panel_recipe.stage_path("manuscript_reconstruction")
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

INPUT_REL = "inbox/manuscript-reconstruction/external-review-input.json"
SEGMENTS_REL = "inbox/manuscript-reconstruction/review-segments.tsv"

CLAIM_CHECKS = ("verified-true", "verified-false", "partially-true", "unverifiable-here")
LANES = ("mechanical_recompute", "prose_repair", "evidence_supplement",
         "registered_decision", "rebuttal_only", "director_decision")
VERIFIED_KINDS = ("verified-true", "verified-false", "partially-true")

_DECOMPOSER = "external-review-decomposer"
_AUDITOR = "manuscript-factual-auditor"

DECOMPOSER_PROMPT = """You are the external-review-decomposer — the DISCOVER owner of \
manuscript_reconstruction. Your ONE job: turn the external review named below into a complete, \
typed, artifact-verified work decomposition. You decompose a review that actually arrived, \
against evidence that actually exists; you never draft rebuttal prose, never soften a point, \
never edit the manuscript.

REQUEST: {request}

{north_star}

INPUT (read first): `{run_dir}/{input_rel}` — it names the review text (either inline \
`review_text` or a `review_path` file), and optionally `manuscript_dir` and `bib_path`. Read the \
review IN FULL. The deterministic paragraph/comment segmentation is at `{run_dir}/{segments_rel}`; \
use those stable segment ids exactly. Read your own seat spec's rules at `{agent_spec}` and follow them exactly.

What to produce:
1. frozen_inputs: use an empty object. The deterministic reducer, not you, computes the one review/manuscript/bibliography freeze receipt from disk.
2. points: EVERY actionable reviewer point as an atomic item: stable id "R1","R2",... in review \
order; `quote` = the reviewer's EXACT words (verbatim substring of the review, whitespace may \
collapse); `claim_check` in {claim_checks} decided by OPENING the artifacts (manuscript source, \
corpus records, logs) — never memory; `evidence_refs` = the file paths you actually opened \
(workspace-relative), REQUIRED for every verified-*/partially-true verdict; `lane` — exactly one \
of {lanes}; `owner` = the manuscript section or asset the repair belongs to (null when the lane \
has no single owner).
3. Map every deterministic source segment exactly once: each point carries `source_segment_ids`; \
all praise/summary/boilerplate segment ids go in `non_actionable_segment_ids`. Also record \
`current_status` in OPEN/ALREADY_SATISFIED/CONTESTED/NOT_CHECKABLE, exact `current_loci`, \
`required_change`, `acceptance_criterion`, and `target_refs`. This distinguishes an old comment \
that the current LaTeX already fixed from a real remaining repair.
4. lane_totals: counts per lane.

HONESTY (hard): a point you cannot verify is "unverifiable-here" with the missing evidence \
named — never dropped, never guessed. Severity is the reviewer's; only evidence may rebut it. \
Every quote must be genuinely from the review — fabricated or paraphrased quotes are BLOCKed \
mechanically downstream.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{"decomposition": {{"frozen_inputs": {{"review_sha256": "<hex>", "manuscript_tree_sha256": null, \
"bib_sha256": null}}, "points": [{{"id": "R1", "quote": "<verbatim>", "claim_check": \
"<enum>", "evidence_refs": ["<path>"], "lane": "<enum>", "owner": "<section or null>", \
"source_segment_ids":["S001"],"current_status":"OPEN","current_loci":["src/sec/x.tex:12"], \
"required_change":"<change>","acceptance_criterion":"<observable check>","target_refs":["src/sec/x.tex"]}}], \
"non_actionable_segment_ids": ["S002"], "lane_totals": {{"prose_repair": 0}}}}}}
Quantities are a FLOOR with NO upper bound: decompose the WHOLE review, never a top-N subset. \
After writing, verify valid JSON. Return one line: point count and lane totals."""

AUDITOR_PROMPT = """You are manuscript-factual-auditor, acting as the INDEPENDENT claim-check \
verifier of manuscript_reconstruction. You did NOT decompose the review; \
external-review-decomposer already did (read its complete bundle at \
`{run_dir}/inbox/DISCOVER.external-review-decomposer.bundle.json`). Your ONE job: for EVERY \
point whose claim_check is verified-true, verified-false or partially-true, independently OPEN \
the point's evidence_refs and judge whether the cited evidence actually supports that verdict. \
You are blind to the decomposer's reasoning; you check its citations, not its prose.

REQUEST: {request}

{north_star}

For each such point record: the point id; refs_ok (did every cited path exist and contain \
relevant content); concur (does the evidence support the claim_check verdict); a one-line \
reason citing what you saw in the file (with a locus). You MAY NOT re-lane points, invent new \
points, or soften the reviewer.

HONESTY (hard): if a ref exists but does not support the verdict, concur=false with the reason \
— a dissent is a legitimate result and goes to the director; never bend a reading to agree. \
If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change \
nothing else, and re-emit the COMPLETE bundle.

Write ONLY this JSON to `{out}`:
{{"claim_check_audit": [{{"id": "R1", "refs_ok": true, "concur": true, \
"reason": "<what you saw, with locus>"}}]}}
Quantities are a FLOOR: audit EVERY verified-*/partially-true point, never a sample. After \
writing, verify valid JSON. Return one line: points audited, concur count, dissent count."""


# ------------------------------------------------------------------ helpers
def _input_path(run_dir) -> Path:
    return Path(run_dir) / INPUT_REL


def _docx_text(path: Path) -> str:
    """Read reviewer prose and Word comments without executing Office or using a conversion script."""

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    parts: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in ("word/document.xml", "word/comments.xml", "word/footnotes.xml", "word/endnotes.xml"):
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except KeyError:
                    continue
                if name == "word/comments.xml":
                    for comment in root.iter(namespace + "comment"):
                        author = comment.attrib.get(namespace + "author", "reviewer")
                        text = "".join(
                            node.text or "" for node in comment.iter()
                            if node.tag in {namespace + "t", namespace + "delText"}
                        ).strip()
                        if text:
                            parts.append(f"[WORD COMMENT — {author}] {text}")
                else:
                    for paragraph in root.iter(namespace + "p"):
                        text = "".join(
                            node.text or "" for node in paragraph.iter()
                            if node.tag in {namespace + "t", namespace + "delText"}
                        ).strip()
                        if text:
                            parts.append(text)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise GateBlock(f"manuscript_reconstruction: unreadable DOCX review ({type(exc).__name__})") from exc
    return "\n".join(parts)


def _read_review_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return _docx_text(path)
    if suffix not in {".txt", ".md", ".rst"}:
        raise GateBlock("manuscript_reconstruction: review_path must be DOCX, Markdown, or plain text")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateBlock(f"manuscript_reconstruction: unreadable review text ({type(exc).__name__})") from exc


def _review_segments(text: str) -> list[dict[str, str]]:
    rows = [re.sub(r"\s+", " ", row).strip() for row in text.splitlines()]
    rows = [row for row in rows if row]
    return [{"segment_id": f"S{index:04d}", "text": row} for index, row in enumerate(rows, 1)]


def _tree_sha256(path: Path) -> str | None:
    if not path.is_dir():
        return None
    rows = []
    for file in sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.casefold() in {".tex", ".bib", ".md", ".tsv"}):
        rows.append({
            "path": file.relative_to(path).as_posix(),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        })
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_input(run_dir) -> dict:
    p = _input_path(run_dir)
    if not p.exists():
        raise GateBlock(
            f"manuscript_reconstruction: missing {INPUT_REL} — the director (or the orchestrator "
            "on their behalf) must supply the external review before this mode can run. "
            'Shape: {"review_text": "..."} or {"review_path": "<file>", '
            '"manuscript_dir": "<dir|null>", "bib_path": "<file|null>"}')
    data = json.loads(p.read_text(encoding="utf-8"))
    text = data.get("review_text")
    if not text and data.get("review_path"):
        rp = Path(data["review_path"])
        if not rp.is_absolute():
            rp = Path(run_dir) / rp
        if not rp.exists():
            raise GateBlock(f"manuscript_reconstruction: review_path {rp} does not exist")
        text = _read_review_path(rp)
    if not (text or "").strip():
        raise GateBlock("manuscript_reconstruction: the review text is empty — nothing to decompose")
    data["_review_text"] = text
    data["_review_segments"] = _review_segments(text)
    manuscript_raw = str(data.get("manuscript_dir") or "").strip()
    manuscript_dir = Path(manuscript_raw) if manuscript_raw else None
    data["_manuscript_tree_sha256"] = _tree_sha256(manuscript_dir) if manuscript_dir else None
    bib_raw = str(data.get("bib_path") or "").strip()
    bib_path = Path(bib_raw) if bib_raw else None
    data["_bib_sha256"] = (
        hashlib.sha256(bib_path.read_bytes()).hexdigest() if bib_path and bib_path.is_file() else None
    )
    return data


def _write_review_segments(run_dir, rows: list[dict[str, str]]) -> None:
    path = Path(run_dir) / SEGMENTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "segment_id\ttext\n" + "\n".join(
        f"{row['segment_id']}\t{row['text'].replace(chr(9), ' ')}" for row in rows
    ) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") != text:
        raise GateBlock("manuscript_reconstruction: frozen review segmentation changed")
    if not path.is_file():
        path.write_text(text, encoding="utf-8")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _workspace_root(run_dir) -> Path:
    # runs/<project>/<run> -> workspace root that also holds the machine + project trees
    return Path(run_dir).resolve().parents[3]


def _resolve_ref(ref: str, run_dir) -> bool:
    ref = str(ref or "").strip()
    if not ref or ref.startswith("[["):
        return False
    for base in (Path(run_dir), _workspace_root(run_dir)):
        try:
            if (base / ref).exists():
                return True
        except OSError:
            return False
    return Path(ref).exists()


# ------------------------------------------------------------------ llm steps
def llm_step(run_dir, stage, request, vault=DEFAULT_VAULT, model_policy="max_quality") -> Optional[dict]:
    north_star = _shared.north_star_block(run_dir)
    if stage == "DISCOVER":
        input_data = _load_input(run_dir)  # fail fast, before any worker is dispatched
        _write_review_segments(run_dir, input_data["_review_segments"])
        out = _panel_recipe.bundle_path(run_dir, "DISCOVER", _DECOMPOSER)
        spec = Path(__file__).resolve().parents[2] / "agents" / f"{_DECOMPOSER}.md"
        seats = (_panel_recipe.Seat(
            label=_DECOMPOSER, bundle_key="decomposition", tier="audit",
            prompt=DECOMPOSER_PROMPT.format(
                request=request, north_star=north_star, run_dir=run_dir,
                input_rel=INPUT_REL, segments_rel=SEGMENTS_REL, agent_spec=spec, out=out,
                claim_checks=", ".join(CLAIM_CHECKS), lanes=", ".join(LANES))),)
        return _panel_recipe.panel(
            run_dir, "DISCOVER", "manuscript_reconstruction", seats, model_policy=model_policy,
            panel_note="one accountable decomposer; every reviewer point typed, quoted verbatim, "
                       "verified against artifacts, and assigned exactly one repair lane.")
    if stage == "VERIFY":
        out = _panel_recipe.bundle_path(run_dir, "VERIFY", _AUDITOR)
        seats = (_panel_recipe.Seat(
            label=_AUDITOR, bundle_key="claim_check_audit", tier="audit",
            prompt=AUDITOR_PROMPT.format(request=request, north_star=north_star,
                                         run_dir=run_dir, out=out)),)
        return _panel_recipe.panel(
            run_dir, "VERIFY", "manuscript_reconstruction", seats, model_policy=model_policy,
            panel_note="independent concurrence on every verified claim_check: the auditor opens "
                       "the cited evidence itself; dissents surface to the director, they are "
                       "never silently resolved.")
    return None  # REPORT is deterministic


# ------------------------------------------------------------------ dets
def _discover_dets(run_dir, ts) -> tuple:
    data = _load_input(run_dir)
    review_text = data["_review_text"]
    seats = (_panel_recipe.Seat(label=_DECOMPOSER, prompt="", bundle_key="decomposition",
                                tier="audit"),)
    bundles = _panel_recipe.load_seat_bundles(run_dir, "DISCOVER", "manuscript_reconstruction", seats)
    dec = bundles["decomposition"]
    if not isinstance(dec, dict):
        raise GateBlock("manuscript_reconstruction DISCOVER: decomposition must be an object")

    points = dec.get("points") or []
    defects = []

    frozen_inputs = {
        "review_sha256": _sha256_text(review_text),
        "manuscript_tree_sha256": data.get("_manuscript_tree_sha256"),
        "bib_sha256": data.get("_bib_sha256"),
    }

    ids = [str(p.get("id") or "") for p in points]
    if len(ids) != len(set(ids)) or any(not i for i in ids):
        defects.append({"summary": "point ids must be unique and non-empty (R1, R2, …)"})
    norm_review = _norm_ws(review_text)
    segment_ids = {row["segment_id"] for row in data["_review_segments"]}
    claimed_segments: list[str] = []
    for p in points:
        pid = p.get("id")
        if str(p.get("claim_check")) not in CLAIM_CHECKS:
            defects.append({"summary": f"{pid}: claim_check {p.get('claim_check')!r} not in {CLAIM_CHECKS}"})
        if str(p.get("lane")) not in LANES:
            defects.append({"summary": f"{pid}: lane {p.get('lane')!r} not in {LANES}"})
        q = _norm_ws(str(p.get("quote") or ""))
        if not q or q not in norm_review:
            defects.append({"summary": f"{pid}: quote is not a verbatim substring of the review — "
                                       "quotes anchor the decomposition and may not be paraphrased."})
        point_segments = [str(value) for value in p.get("source_segment_ids") or []]
        if not point_segments:
            defects.append({"summary": f"{pid}: source_segment_ids is required"})
        claimed_segments.extend(point_segments)
        current_status = str(p.get("current_status") or "")
        if current_status not in {"OPEN", "ALREADY_SATISFIED", "CONTESTED", "NOT_CHECKABLE"}:
            defects.append({"summary": f"{pid}: invalid current_status {current_status!r}"})
        if current_status == "ALREADY_SATISFIED" and not (p.get("current_loci") or []):
            defects.append({"summary": f"{pid}: ALREADY_SATISFIED requires a current manuscript locus"})
        if not str(p.get("acceptance_criterion") or "").strip():
            defects.append({"summary": f"{pid}: acceptance_criterion is required"})
        if current_status in {"OPEN", "CONTESTED"} and not (p.get("target_refs") or []):
            defects.append({"summary": f"{pid}: open/contested issue requires target_refs"})
        if str(p.get("claim_check")) in VERIFIED_KINDS:
            refs = [r for r in (p.get("evidence_refs") or []) if str(r).strip()]
            if not refs:
                defects.append({"summary": f"{pid}: {p.get('claim_check')} carries no evidence_refs — "
                                           "a verdict without a citation is not a verdict."})
            else:
                dead = [r for r in refs if not _resolve_ref(r, run_dir)]
                if dead:
                    defects.append({"summary": f"{pid}: evidence_refs do not resolve: {dead}"})

    non_actionable_ids = [str(value) for value in dec.get("non_actionable_segment_ids") or []]
    claimed_segments.extend(non_actionable_ids)
    if set(claimed_segments) != segment_ids:
        defects.append({"summary": "points plus non_actionable_segment_ids must cover every deterministic review segment exactly"})
    duplicates = sorted({value for value in claimed_segments if claimed_segments.count(value) > 1})
    if duplicates:
        defects.append({"summary": f"review segments assigned more than once: {duplicates}"})
    unknown_segments = sorted(set(claimed_segments) - segment_ids)
    if unknown_segments:
        defects.append({"summary": f"unknown review segment ids: {unknown_segments}"})

    declared = dec.get("lane_totals") or {}
    actual: dict = {}
    for p in points:
        actual[str(p.get("lane"))] = actual.get(str(p.get("lane")), 0) + 1
    if {k: v for k, v in declared.items() if v} != {k: v for k, v in actual.items() if v}:
        defects.append({"summary": f"lane_totals declared {declared} but computed {actual} — "
                                   "totals must be the arithmetic of the points."})

    if defects:
        raise TargetedGateBlock(
            f"manuscript_reconstruction DISCOVER: {len(defects)} defect(s) in the decomposition",
            [{"defect_id": f"reconstruction-discover-{i}", "location": "DISCOVER/decomposition",
              "summary": d["summary"], "target_agents": [_DECOMPOSER], "refresh_agents": []}
             for i, d in enumerate(defects, 1)])

    paths, frag = _panel_recipe.common_gates(
        run_dir, "DISCOVER", ts, mode="manuscript_reconstruction",
        bundles={"decomposition": dec})

    coverage = 1.0

    payload = {"frozen_inputs": frozen_inputs,
               "points": points,
               "review_segments": data["_review_segments"],
               "non_actionable_segment_ids": non_actionable_ids,
               "lane_totals": actual,
               "notes": "deterministic review-segment coverage: 100% (hard-gated)"}
    paths.append(write_artifact(run_dir, "DISCOVER", "external-review-decomposition.artifact.json",
                                "external_review_decomposition", _DECOMPOSER, payload, ts, "approved"))
    report = {"n_points": len(points), "lane_totals": actual, "coverage": coverage}
    report.update(frag)
    return paths, report


def _load_decomposition(run_dir) -> dict:
    seats = (_panel_recipe.Seat(label=_DECOMPOSER, prompt="", bundle_key="decomposition",
                                tier="audit"),)
    return _panel_recipe.load_seat_bundles(
        run_dir, "DISCOVER", "manuscript_reconstruction", seats)["decomposition"]


def _verify_dets(run_dir, ts) -> tuple:
    dec = _load_decomposition(run_dir)
    points = dec.get("points") or []
    must_audit = {str(p["id"]) for p in points if str(p.get("claim_check")) in VERIFIED_KINDS}

    seats = (_panel_recipe.Seat(label=_AUDITOR, prompt="", bundle_key="claim_check_audit",
                                tier="audit"),)
    audit = _panel_recipe.load_seat_bundles(
        run_dir, "VERIFY", "manuscript_reconstruction", seats)["claim_check_audit"]
    if not isinstance(audit, list):
        raise GateBlock("manuscript_reconstruction VERIFY: claim_check_audit must be a list")

    audited = {str(a.get("id") or "") for a in audit}
    unknown = sorted(audited - {str(p.get("id")) for p in points})
    missing = sorted(must_audit - audited)
    defects = []
    if unknown:
        defects.append({"summary": f"audited point id(s) {unknown} do not exist in the decomposition"})
    if missing:
        defects.append({"summary": f"verified points never audited: {missing} — coverage is total, "
                                   "not sampled"})
    if defects:
        raise TargetedGateBlock(
            f"manuscript_reconstruction VERIFY: {len(defects)} coverage defect(s)",
            [{"defect_id": f"reconstruction-verify-{i}", "location": "VERIFY/claim_check_audit",
              "summary": d["summary"], "target_agents": [_AUDITOR], "refresh_agents": []}
             for i, d in enumerate(defects, 1)])

    paths, frag = _panel_recipe.common_gates(
        run_dir, "VERIFY", ts, mode="manuscript_reconstruction",
        bundles={"claim_check_audit": audit})

    dissents = [a for a in audit if not a.get("concur")]
    payload = {"n_audited": len(audit), "n_concur": len(audit) - len(dissents),
               "n_dissent": len(dissents), "dissents": dissents,
               "notes": "dissents are contested points for the director; nothing was auto-resolved"}
    paths.append(write_artifact(run_dir, "VERIFY", "claim-check-concurrence.artifact.json",
                                "claim_check_concurrence", _AUDITOR, payload, ts, "approved"))
    report = {"n_audited": len(audit), "n_dissent": len(dissents)}
    report.update(frag)
    return paths, report


def _report_dets(run_dir, ts) -> tuple:
    dec = _load_decomposition(run_dir)
    points = dec.get("points") or []
    seats = (_panel_recipe.Seat(label=_AUDITOR, prompt="", bundle_key="claim_check_audit",
                                tier="audit"),)
    audit = _panel_recipe.load_seat_bundles(
        run_dir, "VERIFY", "manuscript_reconstruction", seats)["claim_check_audit"]
    concur = {str(a.get("id")): a for a in audit}

    by_lane: dict = {}
    for p in points:
        by_lane.setdefault(str(p.get("lane")), []).append(p)

    def _fmt(p) -> str:
        a = concur.get(str(p.get("id")))
        mark = ""
        if a is not None:
            mark = " — independently CONFIRMED" if a.get("concur") else " — **CONTESTED by the auditor**"
        owner = f" (owner: {p['owner']})" if p.get("owner") else ""
        loci = ", ".join(str(value) for value in p.get("current_loci") or []) or "not located"
        acceptance = str(p.get("acceptance_criterion") or "not specified")
        return (f"- **{p.get('id')}** [{p.get('claim_check')} / {p.get('current_status')}]{mark}{owner}: "
                f"“{_norm_ws(str(p.get('quote') or ''))[:180]}”  \n"
                f"  Current locus: `{loci}`; acceptance: {acceptance}")

    lane_lines = []
    for lane in LANES:
        pts = by_lane.get(lane, [])
        if not pts:
            continue
        lane_lines.append(f"**{lane}** ({len(pts)}):")
        lane_lines.extend(_fmt(p) for p in pts)
    decomposition_sec = "\n".join(lane_lines) or "The review contained no actionable points."

    dissents = [a for a in audit if not a.get("concur")]
    if dissents:
        ver_lines = [f"{len(audit)} verified point(s) independently re-checked; "
                     f"**{len(dissents)} contested** — the evidence did not support the verdict "
                     "as decomposed. Contested points go to the director; nothing was auto-resolved:"]
        ver_lines += [f"- **{a.get('id')}**: {a.get('reason') or 'no reason recorded'}" for a in dissents]
        verification_sec = "\n".join(ver_lines)
    else:
        verification_sec = (f"All {len(audit)} verified point(s) independently re-checked against "
                            "their cited evidence; the auditor concurred with every verdict.")

    repair_pts = by_lane.get("prose_repair", []) + by_lane.get("mechanical_recompute", [])
    if repair_pts:
        repair_sec = ("Execute these through a `manuscript_authoring` run chained with "
                      "`--upstream-run` on this run (authoring never happens inside this mode):\n"
                      + "\n".join(_fmt(p) for p in repair_pts))
    else:
        repair_sec = "No prose or recompute lanes — nothing routes to manuscript_authoring."

    decision_pts = by_lane.get("registered_decision", []) + by_lane.get("director_decision", [])
    supplement = by_lane.get("evidence_supplement", [])
    dec_lines = []
    if decision_pts:
        dec_lines.append("Decisions that are the director's alone (register before any repair):")
        dec_lines.extend(_fmt(p) for p in decision_pts)
    if supplement:
        dec_lines.append("Evidence supplements (route through the corpus fold-in protocol, "
                         "docs/MANUSCRIPT-PATH-CN.md):")
        dec_lines.extend(_fmt(p) for p in supplement)
    if dissents:
        dec_lines.append("Contested claim-checks above also need the director's adjudication.")
    decisions_sec = "\n".join(dec_lines) or "None — no reviewer point requires a director decision."

    sections = {"Review decomposition": decomposition_sec,
                "Claim verification": verification_sec,
                "Repair lanes and owners": repair_sec,
                "Decisions for the director": decisions_sec}
    md_path = _panel_recipe.render_director_markdown(run_dir, "manuscript_reconstruction",
                                                     sections, ts=ts)
    return _panel_recipe.report_note(
        run_dir, ts, mode="manuscript_reconstruction",
        summary=(f"manuscript_reconstruction: {len(points)} reviewer point(s) decomposed, "
                 f"{len(audit)} claim-check(s) independently re-verified "
                 f"({len(dissents)} contested), repair lanes and director decisions rendered to "
                 f"{md_path}. No repair was executed and nothing was submitted — repairs chain "
                 "to manuscript_authoring; re-review chains to manuscript_review."),
        references=[md_path])


def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report_dets(run_dir, ts)
    raise ValueError(f"manuscript_reconstruction has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair("manuscript_reconstruction", run_dets)
