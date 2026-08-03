"""Promote-gate orchestration — the runnable entrypoint for /promote-to-vault (governance red line ②).

`promote.py` holds the safety CORE (re-derive frozen/can-cite from signals; write the vault page on admit).
But that core (a) had NO runnable entrypoint — only tests called it; (b) trusted caller-passed `signals`
instead of reading the candidate's REFERENCED audit artifacts and verifying their sha256; and (c) wrote the
vault page + index + log but never the run ledger. This module closes all three:

  load_and_verify_signals(candidate, base_dir) — read each referenced audit, verify its file sha256 == the
      candidate's ref (fail-closed on mismatch / missing / out-of-run-dir path), schema-validate, extract.
  run_promote_gate(...) — read+verify -> promote_to_vault -> append a tamper-evident `promote` ledger event.

WORKERS CAN NEVER SELF-PROMOTE. Authorization is granted either by an exact legacy environment value or
by the primary source-command handler after the director explicitly invokes `/promote-to-vault` in the
top-level conversation. Worker agents, mode recipes, and scheduled jobs never receive that
director-command capability. Even with authorization, the deterministic core still ceilings anything
unproven at 'provisional'. No network, no LLM.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

from research_agent_teams.tools import promote
from research_agent_teams.tools.ledger import append_event
from research_agent_teams.tools.validate_artifact import validate_payload

# candidate ref field -> the schema its referenced artifact must satisfy (and which extract_signals reads)
_REF_FIELDS = {
    "leakage_audit_ref": "sanity_verdict",
    "fairness_audit_ref": "analysis_check_verdict",
    "reviewer_ref": "review_report",
}


def _sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def document_candidate_paths(batch_root: Path) -> List[Path]:
    """Return staged inputs only, never prior admission records.

    Record names used to inherit a candidate filename and therefore could themselves end in
    ``.document-promotion-candidate.json``.  A repeated preflight would then treat its own audit
    records as untrusted candidates.  The explicit prefix exclusion makes reruns idempotent and
    keeps a rejected preflight from poisoning the next director-authorized attempt.
    """
    return sorted(
        path for path in batch_root.glob("*.document-promotion-candidate.json")
        if not path.name.startswith("document-promotion-record-")
    )


def _path_within(child, root) -> bool:
    c = os.path.normcase(os.path.normpath(os.path.abspath(str(child))))
    r = os.path.normcase(os.path.normpath(os.path.abspath(str(root))))
    return c == r or c.startswith(r + os.sep)


def freeze_is_authorized(run_id: str, *, explicit_director_command: bool = False) -> bool:
    """Accept a direct director command or legacy exact environment authorization.

    The explicit flag is supplied only by the top-level source-command handler after a user directly
    invokes `/promote-to-vault`; workers never receive that invocation context. Leakage, fairness,
    and reviewer re-derivation remain mandatory in both authorization modes.
    """
    return bool(run_id) and (
        bool(explicit_director_command)
        or os.environ.get("RAT_PROMOTE_AUTHORIZED", "") == run_id
    )


def authorization_basis(*, explicit_director_command: bool, external_authorized: bool) -> Optional[str]:
    """Record the director authorization channel without trusting a worker assertion."""
    if explicit_director_command:
        return "explicit-director-command"
    if external_authorized:
        return "out-of-band-env"
    return None


def load_and_verify_signals(candidate: dict, base_dir) -> Tuple[dict, List[str]]:
    """Read the candidate's REFERENCED audit artifacts (never the caller's word), verify each file's sha256
    matches the candidate ref, fence the path inside base_dir, schema-validate, then extract_signals.

    Returns (signals, errors). On ANY problem (missing ref, file missing, sha mismatch, path escape, bad JSON
    or schema) the offending audit is treated as ABSENT — its signal stays the safe/failing value AND an error
    is recorded so the gate hard-rejects. A forged signals dict can therefore never reach the re-derivation."""
    base = Path(base_dir)
    errors: List[str] = []
    payloads = {"leakage_audit_ref": None, "fairness_audit_ref": None, "reviewer_ref": None}

    for field, schema in _REF_FIELDS.items():
        ref = candidate.get(field)
        if not ref:
            errors.append(f"{field} missing — cannot verify the {schema} audit (fail-closed)")
            continue
        rel = ref.get("path", "")
        want_sha = ref.get("sha256", "")
        p = Path(rel) if Path(rel).is_absolute() else (base / rel)
        if not _path_within(p, base):
            errors.append(f"{field} path {rel!r} escapes the run dir (refused)")
            continue
        if not p.exists():
            errors.append(f"{field} file {rel!r} not found")
            continue
        raw = p.read_bytes()
        got_sha = _sha256_bytes(raw)
        if got_sha != want_sha:
            errors.append(f"{field} sha256 mismatch (forged or stale audit): ref={want_sha[:23]}.. file={got_sha[:23]}..")
            continue
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f"{field} is not valid JSON ({exc})")
            continue
        # on-disk artifacts are enveloped ({..., payload:{...}}); unwrap to the body the checker validates
        body = loaded.get("payload", loaded) if isinstance(loaded, dict) else loaded
        verrs = validate_payload(schema, body)
        if verrs:
            errors.append(f"{field} fails the {schema} contract: {verrs}")
            continue
        payloads[field] = body

    signals = promote.extract_signals(
        payloads["leakage_audit_ref"], payloads["fairness_audit_ref"], payloads["reviewer_ref"])
    return signals, errors


def _reject_record(candidate: dict, reason: str, decided_by: str, decided_at: str) -> dict:
    return {
        "candidate_ref": {"path": candidate.get("_path", "inbox/promotion-candidate.json"),
                          "sha256": candidate.get("_sha256", "sha256:" + "0" * 64)},
        "admissible": False,
        "rederived_result_status": "missing-audit",
        "rederived_can_cite_thesis": False,
        "reasons": [reason],
        "vault_path": None,
        "vault_slug": None,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }


def _append_promote_event(run_dir, record: dict, ts: str) -> None:
    """Append a tamper-evident `promote` ledger event so 'knowledge entered (or was refused entry to) the
    vault' is on the permanent record — the audit trail that was previously missing entirely."""
    ledger = Path(run_dir) / "ledger.jsonl"
    if not ledger.parent.exists():
        return  # no run context to anchor to (ad-hoc promote) — nothing to record
    append_event(ledger, "promote", {
        "admissible": record["admissible"],
        "vault_slug": record.get("vault_slug"),
        "vault_path": record.get("vault_path"),
        "rederived_result_status": record["rederived_result_status"],
        "candidate_sha256": record["candidate_ref"]["sha256"],
        "decided_by": record["decided_by"],
        "authorization_basis": record.get("authorization_basis"),
    }, ts)


def run_promote_gate(candidate: dict, *, run_dir, vault_root, human_freeze: bool,
                     decided_by: str, decided_at: str,
                     authorization_basis: Optional[str] = None) -> dict:
    """The full gate: verify the candidate's referenced audits (sha + schema) -> re-derive from the VERIFIED
    signals -> write the vault page on admit -> append a `promote` ledger event. Returns the promotion_record.

    Verification failure HARD-REJECTS before any vault write (forged/stale audits can't promote). `human_freeze`
    is a bool here for testability; the CLI derives it from the explicit-director-command or legacy-env gate."""
    run_dir = Path(run_dir)
    signals, errors = load_and_verify_signals(candidate, run_dir)

    if errors:
        rec = _reject_record(
            candidate, "rejected: referenced-audit verification failed — " + "; ".join(errors),
            decided_by, decided_at)
    else:
        rec = promote.promote_to_vault(
            candidate, signals=signals, human_freeze=human_freeze, vault_root=vault_root,
            decided_by=decided_by, decided_at=decided_at,
            candidate_path=candidate.get("_path"), candidate_sha=candidate.get("_sha256"))
    if authorization_basis:
        rec = {**rec, "authorization_basis": authorization_basis}
    _append_promote_event(run_dir, rec, decided_at)
    return rec


# --------------------------------------------------------------------------- CLI (the gate entrypoint)

def _ts_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    import argparse

    from research_agent_teams.tools.scope_guard import discover_vault_root

    p = argparse.ArgumentParser(
        prog="python -m research_agent_teams.tools.promote_gate",
        description="Director-command promotion gate (/promote-to-vault). Re-derives frozen/can-cite from the REAL "
                    "referenced audits (sha-verified), writes the vault page on admit, records a tamper-evident "
                    "promote event. Authorization comes from an explicit top-level director command or the legacy "
                    "exact RAT_PROMOTE_AUTHORIZED capability.")
    p.add_argument("--run-id", required=False, help="required for the frozen-result lane")
    p.add_argument("--runs-dir", default="research_agent_teams/runs")
    p.add_argument("--candidate", help="path to a frozen-result promotion_candidate JSON (staged in the run inbox)")
    p.add_argument("--document-batch", help="directory containing *.document-promotion-candidate.json files")
    p.add_argument("--admission-id", help="director-reviewed Markdown admission batch identifier")
    p.add_argument("--workspace-root", default=".", help="repository root for source-path verification in document admission")
    p.add_argument("--vault", default=None, help="vault root (default: the discovered PhD-Research-OS)")
    p.add_argument("--decided-by", default="director")
    p.add_argument("--director-invoked", action="store_true", help=(
        "set only by the primary source-command handler after an explicit top-level director request; "
        "workers, modes, and scheduled jobs must never use it"))
    p.add_argument("--ts", default=None)
    a = p.parse_args(argv)

    if a.director_invoked and a.decided_by != "director":
        p.error("--director-invoked is reserved for an explicit director command and requires --decided-by director")

    if bool(a.candidate) == bool(a.document_batch):
        p.error("provide exactly one of --candidate (frozen result) or --document-batch (final Markdown documents)")

    vault_root = a.vault or discover_vault_root()
    if not vault_root:
        print(json.dumps({"error": "no vault root (pass --vault or set RAT_VAULT_ROOT)"}))
        return 2

    if a.document_batch:
        if not a.admission_id:
            p.error("--admission-id is required with --document-batch")
        from research_agent_teams.tools.document_promotion import (
            document_admission_is_authorized,
            run_document_admission_batch,
        )
        batch_root = Path(a.document_batch)
        if not batch_root.exists() or not batch_root.is_dir():
            print(json.dumps({"error": f"document batch directory not found: {batch_root}"}))
            return 2
        candidate_paths = document_candidate_paths(batch_root)
        if not candidate_paths:
            print(json.dumps({"error": "no *.document-promotion-candidate.json files found in batch"}))
            return 2
        candidates = []
        for candidate_path in candidate_paths:
            raw = candidate_path.read_bytes()
            try:
                candidate = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                print(json.dumps({"error": f"invalid document candidate {candidate_path}: {exc}"}))
                return 2
            candidate.setdefault("_path", str(candidate_path))
            candidate.setdefault("_sha256", _sha256_bytes(raw))
            candidates.append((candidate, candidate_path, _sha256_bytes(raw)))
        ts = a.ts or _ts_now()
        external_authorized = document_admission_is_authorized(a.admission_id)
        authorized = document_admission_is_authorized(
            a.admission_id, explicit_director_command=a.director_invoked
        )
        basis = authorization_basis(
            explicit_director_command=a.director_invoked, external_authorized=external_authorized
        )
        records = run_document_admission_batch(
            candidates,
            admission_id=a.admission_id,
            admission_root=batch_root,
            workspace_root=Path(a.workspace_root),
            vault_root=Path(vault_root),
            human_authorized=authorized,
            decided_by=a.decided_by,
            decided_at=ts,
            authorization_basis=basis,
        )
        admissible = bool(records) and all(record["admissible"] for record in records)
        print(json.dumps({
            "admission_id": a.admission_id,
            "admissible": admissible,
            "records": records,
            "gate_note": None if authorized else (
                "NOT ADMITTED: no explicit director command and RAT_DOCUMENT_ADMISSION_AUTHORIZED != admission-id."
            ),
        }, ensure_ascii=False, indent=2))
        return 0 if admissible else 3

    if not a.run_id:
        p.error("--run-id is required with --candidate")

    from research_agent_teams.tools.runstore import find_run_dir
    try:
        run_dir = find_run_dir(a.runs_dir, a.run_id)     # either layout: runs/<project>/<id> or flat
    except FileNotFoundError:
        run_dir = Path(a.runs_dir) / a.run_id            # ad-hoc promote without a run context
    # NOTE: an AMBIGUOUS run id (same id in two project groups) raises RuntimeError and must
    # surface — promoting against a guessed flat path would verify refs in the wrong directory.
    cand_path = Path(a.candidate)
    raw = cand_path.read_bytes()
    candidate = json.loads(raw.decode("utf-8"))
    candidate.setdefault("_path", str(cand_path))
    candidate.setdefault("_sha256", _sha256_bytes(raw))

    external_authorized = freeze_is_authorized(a.run_id)
    human_freeze = freeze_is_authorized(a.run_id, explicit_director_command=a.director_invoked)
    basis = authorization_basis(
        explicit_director_command=a.director_invoked, external_authorized=external_authorized
    )
    ts = a.ts or _ts_now()
    rec = run_promote_gate(candidate, run_dir=run_dir, vault_root=vault_root,
                           human_freeze=human_freeze, decided_by=a.decided_by, decided_at=ts,
                           authorization_basis=basis)
    if not human_freeze:
        rec = dict(rec, gate_note=("NOT FROZEN: no explicit director command and RAT_PROMOTE_AUTHORIZED != run-id, "
                                   "so human_freeze=False and the provisional ceiling holds."))
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0 if rec["admissible"] else 3


if __name__ == "__main__":
    import sys
    sys.exit(main())
