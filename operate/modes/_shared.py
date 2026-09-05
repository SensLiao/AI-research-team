"""Shared deterministic helpers for operate recipes (audit waves A-B, 2026-06-13).

One implementation of the cross-mode gates so six recipes cannot drift apart:

  - north-star plumbing (audit H2): read the run's immutable direction contract from the
    task_frame, render the standard worker-prompt block, and run the per-stage drift gate
    (tools/drift_gate) — provable drift (out-of-scope topic / zero anchor coverage) BLOCKs.
  - bundle precheck (audit H3/W4): a worker bundle missing a required top-level key raises a
    readable GateBlock instead of a bare KeyError.
  - referential integrity (audit H3): downstream ids must resolve to real upstream ids; vault
    ``[[slug]]`` refs must name a page that actually exists; internal-shaped ids not produced by
    any upstream stage are fabricated references and BLOCK.
  - live existence gate (audit H4): external refs (DOI / arXiv / title) go through
    tools/citation_existence — confirmed-nonexistent BLOCKs, offline degrades to warnings.
  - pre-search (audit H5/M1): the sanctioned live-retrieval pre-step, generalized from
    deep_research so every DISCOVER-entry mode can ground novelty in real literature.
  - negative-result memory (audit C2): ideas are lexically matched against the vault's
    negative-results cluster (read-only) — "you already falsified this" becomes a visible caveat.

All helpers are deterministic given their inputs; ``EXISTENCE_TRANSPORT`` is the single
test-injection point for the network-facing gate (run_dets signatures stay CLI-fixed).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import yaml

from ..artifacts import GateBlock, write_artifact
from ..output_versions import resolve_effective_output
from ...tools.citation_existence import ExistenceCache, build_existence_verdict
from ...tools.drift_gate import build_verdict as _build_drift_verdict
from ...tools.idea_dedup import lexical_similarity
from ...tools.novelty_collision import SOURCE_WORKER, VERDICT_DEAD, build_collision_verdict
from ...tools import project_memory as _pm
from ...tools.paper_search import (
    no_semantic_neighbor_found,
    script_of,
    search_many,
    write_search_bundle,
)
from ...tools.schema_normalizer import normalize_payload, write_report
from ...tools.scholar_clients import sanitize_scholar_error
from ...tools.search_funnel import (
    FUNNEL_VERSION,
    combine_funnel_results,
    combine_related_queries,
    funnel as run_funnel,
    merge_funnel_into_search_result,
    recursive_search,
    write_funnel_bundle,
)
from ...tools.scope_guard import discover_vault_root
from ...tools.validate_artifact import PROFILE_DIR, validate_payload

# Test-injection point for the live existence checker. Production leaves it None (real network;
# a dead network degrades to lookup_error WARNINGS — never a false BLOCK, never silently verified).
EXISTENCE_TRANSPORT = None

# Test-injection point for the vault used by slug-integrity / negative-result checks.
# None (production) -> discover the real two-repo layout; a path -> force that vault;
# False -> force 'no vault reachable' (slug checks degrade to warnings — the offline-safe state).
VAULT_ROOT_OVERRIDE = None

# Four-stage funnel inside pre-search (director decision 2026-09-05: ON by default). Depth 1 runs
# the four stages over the plan's queries; deep_research passes funnel_depth=2 so one round of
# machine-proposed related queries follows. `funnel=False` (CLI `--no-funnel`) skips it.
FUNNEL_DEPTH = 1
FUNNEL_BREADTH = 2
FUNNEL_LIMIT_BROAD = 20      # per source at stage 1 (the facade's own plan keeps limit_per_source)
FUNNEL_LIMIT_FINAL = 10      # per query after stage 4


def resolve_vault_root(default_vault=None):
    """The vault root the deterministic checks read (READ-ONLY), honoring the test override."""
    if VAULT_ROOT_OVERRIDE is False:
        return None
    if VAULT_ROOT_OVERRIDE:
        return VAULT_ROOT_OVERRIDE
    root = discover_vault_root()
    if root:
        return root
    if default_vault and Path(default_vault).is_dir():
        return default_vault
    return None

#: The `support_relation` enum, restated for every linker prompt that asks for the field.
#:
#: Registered as D9 (2026-08-06).  `claim_evidence_map.schema.json` has declared a four-value enum
#: since claim-span/v1, and `evidence_review` spelled it out in its prompt — but `deep_research`,
#: `evidence_deep` and `read_paper_deep` named the field without ever stating its legal values.  The
#: 2026-08-04 deep_research run is the measurement: 146 loci carried **22 distinct** relation labels
#: and only **one of them** was inside the enum.  The gate then had nothing machine-readable to tell
#: "the source refutes this" apart from "the source was unreachable", so it called both a
#: contradiction.  Naming the enum at the seat is the input-side half of D9; `tools/citation_checker`
#: is the gate-side half.  Fail-closed by construction: an unrecognised label still blocks.
SUPPORT_RELATION_CONTRACT = """
`support_relation` IS A CLOSED ENUM — use one of exactly four values, verbatim and lowercase, and
never invent a more descriptive label. A label outside this set is not machine-readable, so the
deterministic gate cannot tell your nuance apart from a refutation and BLOCKS the run:
  - "entails"      — this locus, on its own, establishes the claim.
  - "partial"      — this locus supports the claim but narrows, bounds, or qualifies it. Use this for
                     a locus that supports the claim while contextualising it; it is NOT a refutation.
  - "contradicts"  — this locus reports the OPPOSITE of the claim, or refutes its attribution.
  - "insufficient" — you could NOT establish support here: the source was unreachable, paywalled,
                     403/404, truncated, or simply does not address the point. This records an
                     UNVERIFIED locus, NOT a contradiction, and it is how retrieval failure is
                     reported honestly instead of being dressed up as counter-evidence.
Set `supports_claim` consistently with it: true for "entails" and "partial", false for "contradicts"
and "insufficient". Put the nuance your label wanted to carry into `reported_result`, which is free
prose with no length limit. A claim every one of whose loci is "insufficient" is an UNSUPPORTED claim
and still blocks — the enum buys honesty about WHY, never a pass.
"""

_SLUG_REF_RE = re.compile(r"^\[\[([a-z0-9]+(?:-[a-z0-9]+)*)\]\]$")
# Internal artifact ids (GAP-1, IH2, IDEA-003, EV-1, FW-2, conf1, c1) — anchored tightly, same
# discipline as tools/idea_grounding._INTERNAL_RE: a fabricated internal-shaped id must BLOCK.
_INTERNAL_ID_RE = re.compile(r"^(GAP|IH|IDEA|EV|FW|conf|c)[-_]?\d+$")

NEGATIVE_RESULT_SIM_THRESHOLD = 0.45

_WORKER_BUNDLE_WRAPPERS = ("payload", "result", "data")
_WORKER_FAILURE_STATES = {
    "error", "failed", "failure", "blocked", "cancelled", "canceled",
    "timeout", "timed_out",
}


def _present_error(value) -> bool:
    return value not in (None, False, "", [], {})


def _worker_failure(mapping: dict, location: str) -> Optional[str]:
    """Return a readable failure receipt for an execution envelope, if any.

    A scientific payload may legitimately contain a status-like field, so a
    failed ``status`` is considered an execution failure only when it is paired
    with error-envelope detail.  Explicit ``error`` and ``ok/success=false``
    receipts are unambiguous on their own.
    """
    explicit_error = next(
        (
            mapping.get(field)
            for field in ("error", "errors", "exception")
            if _present_error(mapping.get(field))
        ),
        None,
    )
    if explicit_error is not None:
        detail = explicit_error
    elif mapping.get("ok") is False or mapping.get("success") is False:
        detail = (
            mapping.get("message") or mapping.get("reason")
            or mapping.get("detail") or "worker returned success=false"
        )
    else:
        status = str(mapping.get("status") or "").strip().casefold()
        detail = (
            mapping.get("message") or mapping.get("reason")
            or mapping.get("detail")
        )
        if status not in _WORKER_FAILURE_STATES:
            return None
        if not _present_error(detail):
            detail = f"worker status={status}"
    if isinstance(detail, str):
        rendered = detail.strip()
    else:
        rendered = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    return f"{location}: {rendered[:4000] or 'worker reported failure'}"


def extract_worker_bundle_value(
    bundle,
    canonical_key: str,
    *,
    stage: str,
    mode: str,
    agent: Optional[str] = None,
    required: bool = True,
    default=None,
):
    """Extract one worker value without guessing through representation shells.

    Accepted representations are either ``{canonical_key: value}`` or exactly
    one single-level ``payload``/``result``/``data`` object containing that
    canonical key.  A direct canonical value anchors duplicate wrapper copies:
    byte-equivalent JSON values are accepted, while any conflict is blocked.
    When no direct value exists, multiple wrapper candidates are ambiguous even
    if they happen to compare equal, so the function refuses to choose.

    The returned value is a deep copy.  Deterministic compatibility transforms
    downstream can therefore never mutate the immutable worker bundle loaded
    from disk.
    """
    who = f"{mode}[{agent}]" if agent else mode
    context = f"{who} {stage}"
    if not isinstance(bundle, dict):
        raise GateBlock(f"{context} worker bundle is not a JSON object")

    failure = _worker_failure(bundle, "<root>")
    if failure:
        raise GateBlock(f"{context} worker failure envelope: {failure}")

    wrapper_candidates = []
    malformed_wrappers = []
    for wrapper in _WORKER_BUNDLE_WRAPPERS:
        if wrapper not in bundle:
            continue
        wrapped = bundle[wrapper]
        if not isinstance(wrapped, dict):
            malformed_wrappers.append(wrapper)
            continue
        failure = _worker_failure(wrapped, wrapper)
        if failure:
            raise GateBlock(f"{context} worker failure envelope: {failure}")
        if canonical_key in wrapped:
            wrapper_candidates.append((wrapper, wrapped[canonical_key]))

    if canonical_key in bundle:
        direct = bundle[canonical_key]
        conflicts = [
            wrapper for wrapper, candidate in wrapper_candidates
            if candidate != direct
        ]
        if conflicts:
            raise GateBlock(
                f"{context} worker bundle has conflicting {canonical_key!r} values "
                f"at <root> and wrapper(s) {conflicts}; refusing to guess"
            )
        return copy.deepcopy(direct)

    if len(wrapper_candidates) == 1:
        return copy.deepcopy(wrapper_candidates[0][1])
    if len(wrapper_candidates) > 1:
        locations = [wrapper for wrapper, _value in wrapper_candidates]
        raise GateBlock(
            f"{context} worker bundle has multiple wrapped candidates for "
            f"{canonical_key!r} at {locations}; refusing to guess"
        )
    if not required:
        return copy.deepcopy(default)
    malformed = (
        f"; malformed non-object wrapper(s): {malformed_wrappers}"
        if malformed_wrappers else ""
    )
    raise GateBlock(
        f"{context} worker bundle is missing required key {canonical_key!r}"
        f" at <root> or one single-level payload/result/data wrapper{malformed}"
    )


def worker_bundle_has_key(bundle, canonical_key: str) -> bool:
    """Read-only key presence check across the same accepted one-level shapes."""
    if not isinstance(bundle, dict):
        return False
    if canonical_key in bundle:
        return True
    return any(
        isinstance(bundle.get(wrapper), dict)
        and canonical_key in bundle[wrapper]
        for wrapper in _WORKER_BUNDLE_WRAPPERS
    )

_TRUST_CONTROL_EXTRA_FIELDS = {
    "accept", "accepted", "bet", "can_cite_thesis", "chosen", "decision",
    "executed", "execution_status", "fabricated", "human_freeze", "leakage",
    "meets_bar", "metrics", "promote", "promotion_status", "ran", "reject",
    "rejected", "result", "results", "selected", "status", "supports_claim",
    "unsupported", "verdict", "winner",
}
_TRUST_CONTROL_EXTRA_PREFIXES = (
    "director_", "promotion_", "vault_", "execution_", "secret_",
    "credential_", "token_",
)
_TRUST_CONTROL_EXTRA_MARKERS = (
    "accept", "blind_contamination", "can_cite", "credential", "decision",
    "contradict", "execut", "fabricat", "ground_truth", "hash", "human_freeze",
    "leakage", "meets_bar", "oracle", "permission", "promot", "receipt",
    "reject", "secret", "selected", "signature", "split", "support", "tamper",
    "token", "truth_access", "unsupported", "vault", "verdict",
)


def _control_field_name(name: str) -> bool:
    """Recognise trust-bearing extras across snake/camel/kebab spelling.

    This is intentionally about *field names*, not values.  It prevents an
    otherwise useful lossless projection from hiding a worker disclosure such
    as ``groundTruthAccess`` or ``supportsClaim`` in the normalization sidecar.
    The field remains preserved, but the owning worker must resolve the
    scientific/control conflict before downstream consumers are released.
    """
    folded = str(name or "").casefold()
    compact = re.sub(r"[^a-z0-9]+", "", folded)
    compact_markers = {
        re.sub(r"[^a-z0-9]+", "", marker)
        for marker in _TRUST_CONTROL_EXTRA_MARKERS
    }
    return (
        folded in _TRUST_CONTROL_EXTRA_FIELDS
        or folded.startswith(_TRUST_CONTROL_EXTRA_PREFIXES)
        or any(marker in folded for marker in _TRUST_CONTROL_EXTRA_MARKERS)
        or any(marker and marker in compact for marker in compact_markers)
    )


def _attach_at_pointer(document, pointer: str, value) -> bool:
    """Set `value` at a JSON Pointer inside `document` (in place). Returns False
    when the pointer's parent target does not exist — the caller then escalates.
    Only dict/list structural walking; no scientific judgment is applied."""
    if not pointer or pointer == "/":
        return False
    parts = [
        str(part).replace("~1", "/").replace("~0", "~")
        for part in pointer.lstrip("/").split("/")
    ]
    node = document
    for part in parts[:-1]:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    last = parts[-1]
    if isinstance(node, dict):
        node[last] = value
        return True
    if isinstance(node, list) and last.isdigit() and int(last) < len(node):
        node[int(last)] = value
        return True
    return False


def normalize_worker_payload(
    run_dir,
    stage: str,
    agent: str,
    artifact_type: str,
    payload,
    *,
    label: Optional[str] = None,
):
    """Project a worker-authored payload into its canonical delivery schema.

    Ordinary research workers are allowed to return richer JSON than the stable
    machine contract.  Representation-only differences (extra fields, canonical
    enum spelling, schema defaults, or a structured value in a text field) are
    normalized before scientific gates consume the payload.  The original
    worker bundle remains immutable and every removed value is retained in a
    hash-bound sidecar under ``inbox/normalization``.

    This helper is deliberately *not* used by promotion, permission, receipt,
    secret, or path-trust boundaries.  It never coerces scientific booleans or
    numbers, invents required facts, or changes citation/execution verdicts.
    Remaining validation errors therefore mean a real local supplement is
    needed, not that formatting should be silently guessed.
    """
    normalized, report = normalize_payload(artifact_type, payload)
    errors = validate_payload(artifact_type, normalized)
    report = dict(report)
    conflicts = list(report.get("representation_conflicts") or [])
    conflict_advisories = []
    blocking_conflicts = []
    for row in conflicts:
        # When a valid canonical field already exists, it wins deterministically;
        # the disagreeing alias is retained in the sidecar as an advisory.  A
        # conflict without an authoritative canonical value still needs a
        # targeted supplement rather than a silent guess.
        if row.get("canonical_field") and row.get("canonical_value") is not None:
            conflict_advisories.append(row)
        else:
            blocking_conflicts.append(row)
            errors.append(
                f"representation conflict at {row.get('pointer') or '<root>'}: "
                f"{row.get('rule')}"
            )
    heuristic_changes = list(report.get("heuristic_scientific_changes") or [])
    errors.extend(
        f"scientific value requires worker confirmation at "
        f"{row.get('pointer') or '<root>'}: {row.get('rule')}"
        for row in heuristic_changes
    )
    report["representation_advisories"] = conflict_advisories
    report["blocking_representation_conflicts"] = blocking_conflicts
    # Director lock 2026-08-16: a trust/scientific control field carried as an extra is
    # RE-ATTACHED into the canonical payload and recorded as an advisory — it no longer
    # triggers a repair wave. Bookkeeping classes (provenance hints, hash bindings) must
    # not loop the machine when the science is verified; the advisories stay visible in
    # the normalization report for the director.
    unsafe_extras = []
    kept_control_fields = []
    for row in report.get("preserved_extras") or []:
        pointer = str(row.get("pointer") or "")
        leaf = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~").casefold()
        if _control_field_name(leaf):
            unsafe_extras.append(row)
            value = row.get("value")
            if _attach_at_pointer(normalized, pointer, value):
                kept_control_fields.append({"pointer": pointer, "value": value})
            else:
                errors.append(
                    f"trust/scientific control field {leaf!r} at {pointer or '<root>'} "
                    "could not be re-attached (pointer target missing)"
                )
    report["unsafe_preserved_extras"] = unsafe_extras
    report["kept_control_fields"] = kept_control_fields
    if kept_control_fields:
        post_errors = validate_payload(artifact_type, normalized)
        for err in post_errors:
            if err not in errors:
                errors.append(err)
    report.update({
        "stage": str(stage),
        "agent": str(agent),
        "label": str(label or artifact_type),
        "post_normalization_errors": list(errors),
    })
    if report.get("changes") or report.get("preserved_extras") or errors:
        safe_agent = re.sub(r"[^A-Za-z0-9._-]+", "-", str(agent)).strip("-.") or "worker"
        safe_label = re.sub(
            r"[^A-Za-z0-9._-]+", "-", str(label or artifact_type)
        ).strip("-.") or "payload"
        report_path = (
            Path(run_dir) / "inbox" / "normalization" /
            f"{stage}.{safe_agent}.{safe_label}.json"
        )
        report["report_path"] = str(report_path)
        write_report(report_path, report)
    return normalized, errors, report


# --------------------------------------------------------------------------- task_frame / north star

def task_frame(run_dir) -> dict:
    return json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))


def budget(run_dir) -> dict:
    return dict(task_frame(run_dir)["payload"].get("budget") or {})


def north_star(run_dir) -> dict:
    """The run's direction contract; legacy frames (no north_star) fall back to request_text."""
    p = task_frame(run_dir)["payload"]
    ns = p.get("north_star") or {}
    return {"statement": str(ns.get("statement") or p.get("request_text") or ""),
            "in_scope": list(ns.get("in_scope") or []),
            "out_of_scope": list(ns.get("out_of_scope") or [])}


def north_star_block(run_dir) -> str:
    """The standard NORTH STAR section every worker prompt carries (audit A2 — injection 100%)."""
    ns = north_star(run_dir)
    in_s = ", ".join(ns["in_scope"]) if ns["in_scope"] else "(none declared)"
    out_s = ", ".join(ns["out_of_scope"]) if ns["out_of_scope"] else "(none declared)"
    return (
        "NORTH STAR (the run's ONLY direction — a deterministic drift gate checks every stage's "
        "output against it; naming an out_of_scope topic, or producing output with zero connection "
        "to this direction, is a hard BLOCK):\n"
        f"    {ns['statement']}\n"
        f"  in_scope (TOPIC boundary — what this run is ABOUT): {in_s}\n"
        f"  out_of_scope (hard exclusions): {out_s}\n"
        "in_scope is a TOPIC boundary, NOT a solution menu and NOT a component list to fill in. Any "
        "mechanism, architecture, loss, training procedure or computation that addresses this "
        "direction is in scope, including one that no term above names and one that replaces a "
        "named component entirely. Proposing a solution the north star did not anticipate is the "
        "point of the run, not drift. Only naming an excluded topic, or answering a different "
        "question, is drift. If your inputs pull elsewhere, SAY SO in your output instead of "
        "silently following them; you never re-scope the run — only the director may."
    )


def domain_profile(run_dir) -> Optional[dict]:
    """The active domain-profile BODY (profiles/<ref>.profile.yaml), or None when unset/missing."""
    ref = task_frame(run_dir)["payload"].get("domain_profile_ref")
    if not ref:
        return None
    p = Path(PROFILE_DIR) / f"{ref}.profile.yaml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- bundle precheck (W4)

def require_bundle_keys(bundle: dict, keys: Iterable[str], *, stage: str, mode: str) -> None:
    """A worker bundle missing required top-level keys is a readable gate failure, not a KeyError."""
    if not isinstance(bundle, dict):
        raise GateBlock(f"{mode} {stage} worker bundle is not a JSON object")
    missing = [k for k in keys if k not in bundle]
    if missing:
        raise GateBlock(
            f"{mode} {stage} worker bundle is missing required key(s) {missing} — re-dispatch the "
            f"{stage} worker; it must emit the COMPLETE bundle shape its prompt specifies")


# --------------------------------------------------------------------------- drift gate (H2)

def run_drift_gate(run_dir, stage: str, ts: str, texts: Iterable[str]) -> Tuple[str, dict]:
    """Write the stage's drift verdict (analysis_check_verdict / goal_alignment); BLOCK on drift."""
    payload, facts = _build_drift_verdict(north_star(run_dir), texts, stage)
    path = write_artifact(run_dir, stage, "drift-verdict.artifact.json",
                          "analysis_check_verdict", "goal-alignment-checker", payload, ts,
                          "blocked" if not payload["pass"] else "approved")
    if not payload["pass"]:
        raise GateBlock(f"north-star drift gate BLOCK at {stage}: {payload['violations']}")
    return path, facts


# --------------------------------------------------------------------------- citation gates (H3/H4)

def resolvable_refs(evidence_table: dict) -> Set[str]:
    """The known-good ref set for citation_checker.build_report (audit W2 — the half-gate fix)."""
    return {str(s.get("ref")) for s in (evidence_table.get("sources") or []) if s.get("ref")}


def external_refs(evidence_table: dict, claim_evidence_map: Optional[dict] = None) -> List[str]:
    """Every non-slug ref a worker cited (sources + loci) — the existence gate's input."""
    refs: Dict[str, None] = {}
    for s in (evidence_table.get("sources") or []):
        r = str(s.get("ref") or "").strip()
        if r and not _SLUG_REF_RE.match(r):
            refs.setdefault(r)
    for m in ((claim_evidence_map or {}).get("mappings") or []):
        for locus in (m.get("loci") or []):
            r = str(locus.get("source_ref") or "").strip()
            if r and not _SLUG_REF_RE.match(r):
                refs.setdefault(r)
    return list(refs)


def run_existence_gate(run_dir, stage: str, ts: str, refs: List[str]) -> Tuple[str, dict]:
    """Live three-state existence check over external refs (audit H4 — the unplugged weapon, plugged).

    Three states, and only one of them halts a run:
      BLOCK       a ref is CONFIRMED not to exist (the fabrication signal) -> GateBlock.
      UNVERIFIED  nothing could be checked at all — zero refs, or every lookup errored (offline).
                  The artifact is written with status="draft" so the run continues while carrying,
                  in writing, that NO external existence check actually happened. Reporting the
                  absence of a check as a PASS was the defect this state exists to remove.
      PASS        at least one ref was really resolved and none came back not-found.
    The per-run sqlite cache makes re-checks free and the verdict reproducible.
    """
    clean = [r for r in dict.fromkeys(str(r).strip() for r in refs) if r]
    cache = ExistenceCache(str(Path(run_dir) / "inbox" / "citation-cache.sqlite"))
    try:
        # Local, hash-bound refs are evidence pointers, not paper titles.  Permit only files that
        # resolve inside this run or the machine workspace; citation_existence re-reads and hashes
        # them on every call, while DOI/arXiv/title refs retain the existing live lookup path.
        workspace_root = Path(__file__).resolve().parents[3]
        verdict = build_existence_verdict(
            clean,
            ts,
            transport=EXISTENCE_TRANSPORT,
            cache=cache,
            local_roots=(Path(run_dir).resolve(), workspace_root),
        )
    finally:
        cache.close()
    status = {"BLOCK": "blocked", "UNVERIFIED": "draft"}.get(str(verdict["verdict"]), "approved")
    path = write_artifact(run_dir, stage, "citation-existence-verdict.artifact.json",
                          "citation_existence_verdict", "citation-integrity-auditor", verdict, ts,
                          status)
    if verdict["verdict"] == "BLOCK":
        raise GateBlock(f"citation existence gate BLOCK at {stage}: {verdict['violations']}")
    return path, verdict


def vault_slugs(vault_root) -> Optional[Set[str]]:
    """Every real page slug in the vault's 02-wiki (read-only), or None when no vault is reachable."""
    if not vault_root:
        return None
    wiki = Path(vault_root) / "02-wiki"
    if not wiki.is_dir():
        return None
    return {p.stem.lower() for p in wiki.rglob("*.md")}


def check_referential_integrity(refs: Iterable[str], known_ids: Set[str],
                                vault_slug_set: Optional[Set[str]] = None) -> Tuple[List[str], List[str]]:
    """(violations, warnings) for downstream refs (audit H3 — the broken-chain fix).

    A ref must be: a known upstream id, a vault slug that EXISTS, or an external ref (owned by
    the existence gate). An internal-shaped id nobody upstream produced is a fabricated reference."""
    violations: List[str] = []
    warnings: List[str] = []
    for ref in refs:
        r = str(ref).strip()
        if not r:
            violations.append("empty evidence_ref entry (a reference must point at something)")
            continue
        if r in known_ids:
            continue
        m = _SLUG_REF_RE.match(r)
        if m:
            if vault_slug_set is None:
                warnings.append(f"{r}: vault unreachable — slug existence unverified")
            elif m.group(1) not in vault_slug_set:
                violations.append(f"{r}: no such page in the vault (never invent a slug)")
            continue
        if _INTERNAL_ID_RE.match(r):
            violations.append(
                f"{r}: internal-shaped id that no upstream stage produced "
                f"(known ids: {sorted(known_ids)[:10]}…) — fabricated reference")
            continue
        # external ref (doi/arXiv/title/url): the existence gate owns it
    return violations, warnings


# --------------------------------------------------------------------------- pre-search (H5/M1)

def pre_search(run_dir, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8,
               queries=None, funnel: bool = True, funnel_depth: int = FUNNEL_DEPTH,
               funnel_breadth: int = FUNNEL_BREADTH) -> str:
    """Deterministic live-retrieval pre-step: drop inbox/search-results.json for the worker AND
    the novelty grounding signal. A dead network degrades to an empty-records bundle with
    source_errors recorded — the run proceeds vault-only and the report says so; nothing is
    fabricated. (Generalized from deep_research; every DISCOVER-entry recipe shares it.)

    C1 guard (2026-08-07): the scholarly APIs behind `search_many` are English-biased. Firing a raw
    non-Latin request at them returns wrong or empty results that then get reported as real
    coverage — retrieval poison, and worse than no retrieval because it looks grounded. When no
    explicit `queries` were supplied and the request is not Latin-script, the direct query is
    REFUSED: an empty-records bundle is written carrying `query_language_block`, which names the
    detected script and the action required (supply English `queries`). Passing `queries` yourself
    always bypasses the guard — translating the request is the caller's judgment, not the machine's.
    """
    if not queries and script_of(request) != "latin":
        detected = script_of(request)
        res = {
            "query": request,
            "records": [],
            "source_errors": {},
            "task_request": request,
            "query_language_block": {
                "detected": detected,
                "reason": (
                    f"the request is {detected}-script and no explicit English queries were "
                    "supplied; the arXiv/OpenAlex/Crossref/Semantic-Scholar facade is "
                    "English-biased, so querying it with this string directly would return "
                    "wrong-or-empty results that later read as real literature coverage"
                ),
                "required_action": (
                    "re-run `operate pre-search` with explicit English `queries` (translate the "
                    "research question, keeping domain terms as the target literature writes "
                    "them), or proceed vault-only and mark novelty UNVERIFIED"
                ),
            },
        }
        path = write_search_bundle(run_dir, request, res, ts)
        # `write_search_bundle` projects a fixed key set, so the block is re-attached here. The
        # tidier home is a passthrough inside that writer (tools/paper_search.py, W-gates' file) —
        # reported rather than reached into, since one owner per file is what keeps this parallel.
        bundle_path = Path(path)
        written = json.loads(bundle_path.read_text(encoding="utf-8"))
        written["query_language_block"] = res["query_language_block"]
        bundle_path.write_text(json.dumps(written, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    try:
        res = search_many(queries or [request], sources=sources,
                          limit_per_source=limit_per_source, transport=transport)
        res["task_request"] = request
    except Exception as e:  # total failure (e.g. bad query) -> recorded, never invented
        res = {"query": request, "records": [], "source_errors": {"all": str(e)}}
        return write_search_bundle(run_dir, request, res, ts)
    if funnel:
        run_funnel_step(run_dir, res, list(queries or [request]), ts, transport=transport,
                        sources=sources, depth=funnel_depth, breadth=funnel_breadth)
    return write_search_bundle(run_dir, request, res, ts)


def run_funnel_step(run_dir, res: dict, queries: List[str], ts: str, *, transport=None,
                    sources=("arxiv", "openalex", "crossref", "s2"), depth: int = FUNNEL_DEPTH,
                    breadth: int = FUNNEL_BREADTH) -> dict:
    """The AgentSearch-pattern four-stage funnel (tools/search_funnel) over the same query plan,
    folded into the pre-search bundle IN PLACE.

    - the full result (passage snippets, per-stage counts, rounds) is written to
      ``inbox/search-funnel.json``; the metadata bundle only gains ``funnel_rank`` /
      ``funnel_score`` on its records, funnel-only records as metadata rows, the
      ``related_queries`` menu and a ``funnel`` summary;
    - never raises: a failure is recorded as ``funnel.status == "failed"`` and the facade's
      own records / ``source_errors`` stand exactly as ``search_many`` produced them.
    """
    summary = {"status": "ok", "version": FUNNEL_VERSION, "depth": int(depth),
               "breadth": int(breadth), "bundle": "inbox/search-funnel.json"}
    try:
        per_query = []
        for q in queries:
            kw = dict(sources=sources, limit_broad=FUNNEL_LIMIT_BROAD, limit_final=FUNNEL_LIMIT_FINAL,
                      transport=transport)
            per_query.append(recursive_search(q, depth=int(depth), breadth=int(breadth), **kw)
                             if int(depth) > 1 else run_funnel(q, **kw))
        combined = combine_funnel_results(per_query)
        write_funnel_bundle(run_dir, {"funnel_version": FUNNEL_VERSION, "queries": list(queries),
                                      "depth": int(depth), "breadth": int(breadth),
                                      "results": per_query, "records": combined}, ts)
        summary["stage_counts"] = [r.get("stage_counts") for r in per_query if r.get("stage_counts")]
        summary["expansion_stop_reasons"] = [r["expansion_stop_reason"] for r in per_query
                                             if r.get("expansion_stop_reason")]
        summary["channels_lost"] = sorted({c for r in per_query for c in (r.get("channels_lost") or [])})
        summary["source_errors"] = {f"q{i}:{k}": sanitize_scholar_error(v)
                                    for i, r in enumerate(per_query, 1)
                                    for k, v in (r.get("source_errors") or {}).items()}
        merge_funnel_into_search_result(res, combined, summary=summary)
        res["related_queries"] = combine_related_queries(per_query)
    except Exception as e:
        res["funnel"] = dict(summary, status="failed", error=sanitize_scholar_error(e))
    return res


def search_records(run_dir) -> List[dict]:
    """The live-retrieval records dropped by pre_search ([] when the pre-step did not run)."""
    p = Path(run_dir) / "inbox" / "search-results.json"
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("records") or [])
    except (OSError, ValueError):
        return []


def novelty_signals_from_search(gaps: List[dict], records: List[dict]) -> Dict[str, List[str]]:
    """Per-gap retrieval-grounded novelty signals for aggregate_novelty(signals=...) (audit H5).

    A gap whose statement surfaces NO semantically-near retrieved title earns the positive
    'no_semantic_neighbor_found' signal. Empty records -> {} (novelty stays in-vault counting,
    and the recipe's report says so honestly)."""
    if not records:
        return {}
    out: Dict[str, List[str]] = {}
    for g in gaps:
        stmt = str(g.get("statement") or "")
        gid = str(g.get("gap_id") or "")
        if not stmt or not gid:
            continue
        sig = no_semantic_neighbor_found(stmt, records)
        if sig["no_semantic_neighbor_found"]:
            out[gid] = ["no_semantic_neighbor_found"]
    return out


# --------------------------------------------------------------------------- negative-result memory (C2)

def negative_result_caveats(vault_root, ideas: List[dict],
                            threshold: float = NEGATIVE_RESULT_SIM_THRESHOLD) -> Dict[str, List[str]]:
    """Match idea summaries against the vault's negative-results cluster (READ-ONLY).

    Returns {idea_id: [caveat, ...]} for ideas lexically close to a recorded negative result —
    'this one was already tried and falsified' becomes a visible menu caveat, never a cut."""
    out: Dict[str, List[str]] = {}
    if not vault_root:
        return out
    nr_dir = Path(vault_root) / "02-wiki" / "negative-results"
    if not nr_dir.is_dir():
        return out
    pages: List[Tuple[str, List[str]]] = []
    for p in sorted(nr_dir.rglob("*.md")):
        try:
            head = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:50]
        except OSError:
            continue
        candidates = [p.stem.replace("-", " ")]
        candidates += [ln.lstrip("# ").strip() for ln in head if ln.startswith("#")]
        pages.append((p.stem, [c for c in candidates if c]))
    for idea in ideas:
        summary = str(idea.get("summary") or "")
        iid = str(idea.get("idea_id") or "")
        if not summary or not iid:
            continue
        for slug, candidates in pages:
            best = max((lexical_similarity(summary, c) for c in candidates), default=0.0)
            if best >= threshold:
                out.setdefault(iid, []).append(
                    f"possible prior NEGATIVE result: [[{slug}]] (lexical similarity "
                    f"{round(best, 2)}) — check it before betting on this idea")
    return out


# --------------------------------------------------------------------------- novelty-collision gate (2026-06-18)

def collision_findings_bundle(run_dir) -> Optional[dict]:
    """The independent collision-checker worker's bundle (inbox/COLLISION.bundle.json), or None.

    Missing/corrupt -> None: the gate then treats the run as not-retrieval-grounded (every idea
    UNVERIFIED, nothing cut) and the recipe report says novelty was NOT verified — never a false cut,
    never a silently-clean menu (mandatory-check honesty, design §4)."""
    logical = Path(run_dir) / "inbox" / "COLLISION.bundle.json"
    try:
        p = resolve_effective_output(Path(run_dir), "IDEATE", logical)
    except ValueError as exc:
        raise GateBlock(f"supplement lineage BLOCK: {exc}") from exc
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _verify_collision_fulltext_snapshot(run_dir, paper: dict) -> bool:
    """Presence-and-fencing check on the worker's exact-collision full-text receipt.

    2026-08-07 (director lock: no hash gating): the SHA-256 comparison against the worker's declared
    digest is gone. What remains is the part that was never about integrity accounting — a
    destructive cut must still be bound to a full text that is actually present INSIDE this run's
    directory, so the cut is inspectable after the fact.

    Deliberately not made to return a constant False. `novelty_collision._is_full_claim_collision`
    requires this flag, so a hard-coded False would make the prior-art cut unsatisfiable — turning a
    hash removal into a silent removal of the one destructive gate the director keeps (an EVIDENCED
    prior-art collision may cut an idea; a novelty SCORE never may). Raised with the team lead.

    A missing, external, or unreadable snapshot still yields False, which downgrades the collision to
    UNVERIFIED — it never stops delivery and never removes an idea on its own.
    """
    ref = str((paper or {}).get("fulltext_snapshot_ref") or "").strip()
    if not ref:
        return False
    root = Path(run_dir).resolve()
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def run_collision_gate(run_dir, stage: str, ts: str, menu_ideas: List[dict], *,
                       hard_block: bool = True,
                       cut_requires_experiments: bool = True) -> Tuple[List[dict], dict, str]:
    """Mandatory pre-/idea-bet prior-art COLLISION gate (novelty-collision-upgrade 2026-06-18).

    An EVIDENCED collision — a real, existence-verified, full-text-reviewed paper that tested the same
    central claim, input/output contract, and causal assay with required experiments — may be cut.
    Component overlap and lexical ledger matches are retrieval leads only. A novelty score never cuts.
    Offline (no collision bundle / no retrieval) -> nothing is cut, every idea is UNVERIFIED. Returns
    (survivors, verdict_payload, artifact_path). Never raises on a collision (a cut is not a run halt —
    the run continues with the survivors; an empty survivor set is the honest 'all already done')."""
    bundle = collision_findings_bundle(run_dir)
    if bundle is not None:
        # Formatting defects are repaired locally where possible.  A bundle
        # that remains schema-invalid does not stop the run, but it is never
        # allowed to remove an idea: degrade the novelty decision to
        # UNVERIFIED and preserve the normalization report for repair.
        normalized, bundle_errors, _report = normalize_worker_payload(
            run_dir,
            stage,
            "novelty-collision-checker",
            "collision_findings",
            bundle,
            label="collision-findings-gate",
        )
        bundle = normalized if not bundle_errors else None
    findings = copy.deepcopy([
        f for f in (bundle or {}).get("findings", []) if isinstance(f, dict)
    ])
    for finding in findings:
        for paper in finding.get("colliding_papers") or []:
            if isinstance(paper, dict):
                paper["_fulltext_snapshot_verified"] = (
                    _verify_collision_fulltext_snapshot(run_dir, paper)
                )
    # A non-empty JSON file is not a retrieval receipt. Current workers report
    # complete/partial/unavailable per idea; missing or unavailable status is
    # conservatively ungrounded (legacy bundles can be replayed but cannot cut).
    # Since 2026-08-07 this reads `retrieval_status` ONLY — the snapshot-hash channel it used to
    # sit beside is gone, and grounding is a statement about whether retrieval happened, never
    # about whether a file's bytes matched a digest.
    retrieval_grounded = (
        bundle is not None and bool(findings)
        and all(str(f.get("retrieval_status") or "") in {"complete", "partial"}
                for f in findings)
    )

    # Existence-verify every claimed colliding ref (reuse the live, offline-safe checker). A cut can
    # only stand on a paper that PASSES citation_existence — never a fabricated/unconfirmable one.
    refs: List[str] = []
    for f in findings:
        for cp in (f.get("colliding_papers") or []):
            r = str((cp or {}).get("ref") or "").strip()
            if r:
                refs.append(r)
    existence_by_ref: Dict[str, str] = {}
    if refs:
        cache = ExistenceCache(str(Path(run_dir) / "inbox" / "citation-cache.sqlite"))
        try:
            ver = build_existence_verdict(list(dict.fromkeys(refs)), ts,
                                          transport=EXISTENCE_TRANSPORT, cache=cache)
        finally:
            cache.close()
        existence_by_ref = {c["ref"]: c["state"] for c in ver.get("checked", [])}

    # Cross-run prior-art memory supplies search leads. It has no inherited veto:
    # every current idea still needs a fresh full-paper claim-equivalence finding.
    prior_art_hits: Dict[str, dict] = {}
    ws = _pm.workspace_for_run(run_dir)
    if ws is not None:
        prior_art_hits = _pm.prior_art_matches(menu_ideas, _pm.load_prior_art(ws))

    verdict = build_collision_verdict(
        menu_ideas, findings, existence_by_ref, prior_art_hits,
        hard_block=hard_block, cut_requires_experiments=cut_requires_experiments,
        retrieval_grounded=retrieval_grounded)

    status = "blocked" if verdict["cut_ids"] else "approved"
    path = write_artifact(run_dir, stage, "novelty-collision-verdict.artifact.json",
                          "novelty_collision_report", "novelty-collision-checker", verdict, ts, status)

    # Record fresh worker-confirmed DEAD cuts as future retrieval leads. A later
    # idea may improve on them, so the ledger never auto-cuts by lexical match.
    if ws is not None and verdict["cut_ids"]:
        run_id = task_frame(run_dir)["payload"]["task_id"]
        ideas_by_id = {str(i.get("idea_id")): i for i in menu_ideas}
        finding_by_id = {str(f.get("idea_id")): f for f in findings if f.get("idea_id")}
        dead_rows: List[dict] = []
        for e in verdict["ideas"]:
            if e.get("verdict") == VERDICT_DEAD and e.get("source") == SOURCE_WORKER and e.get("cut"):
                iid = e["idea_id"]
                fnd = finding_by_id.get(iid, {})
                fp = " | ".join(str(fnd.get(k) or "") for k in
                                ("method_combination", "application", "domain")).strip(" |")
                dead_rows.append({
                    "idea_id": iid,
                    "fingerprint": fp or str(ideas_by_id.get(iid, {}).get("summary") or ""),
                    "summary": str(ideas_by_id.get(iid, {}).get("summary") or ""),
                    "colliding_refs": [p.get("ref") for p in (e.get("colliding_papers") or [])
                                       if p.get("ref")],
                    "experimentally_validated": any(
                        p.get("experimentally_validated") for p in (e.get("colliding_papers") or [])),
                })
        if dead_rows:
            _pm.append_prior_art(ws, run_id, ts, dead_rows)

    cut = set(verdict["cut_ids"])
    survivors = [i for i in menu_ideas if str(i.get("idea_id")) not in cut]
    return survivors, verdict, path
