"""Promotion gate core — the M⇒D seam, write side (the ONLY path knowledge enters System D).

`/promote-to-vault` is a human gate (disable-model-invocation). This module is its deterministic
core: given a promotion_candidate that REFERENCES the real audit artifacts (it never carries a
self-claimed status), re-derive frozen / can-cite-thesis from the ACTUAL referenced verdicts plus the
human freeze flag, and ONLY then write a re-derived page into the vault.

Crown-jewel rules honoured (read, never modified — schema-contract §9.9):
  - can-cite-thesis is DERIVED: (result-status=='frozen') AND leakage==pass AND fairness==pass
    (05-registry/status-registry.md). Manual override forbidden; a self-claim is ignored.
  - provisional / UNVERIFIED are structurally non-promotable (blueprint §4). The machine's
    result_summary ceiling is const 'provisional' — only a HUMAN freeze re-derives 'frozen'.
  - the promoter "re-derives status and never trusts a sidecar's self-claim" (blueprint §0).

Pure where it can be (extract_signals / rederive / make_slug / render_vault_page); I/O isolated in
promote_to_vault. No network, no LLM. Mirrors the derive-then-validate family of venue_score.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

# --- native verdict vocab of the referenced audit artifacts (read from their schemas) ---
SANITY_PASS = "PASS"          # sanity_verdict.verdict ∈ {PASS, BLOCK}  (leakage / result-sanity)
REVIEWER_FREEZE = "APPROVE-FREEZE"   # review_report.verdict ∈ {APPROVE-FREEZE, BLOCK}
REVIEWER_BLOCK = "BLOCK"

# result-status values that can never be re-frozen (status-registry terminal states)
_TERMINAL_NONFROZEN = {"invalid", "superseded"}


# ---------- pure: extract normalized signals from the REAL audit artifacts ----------

def extract_signals(sanity_payload: dict, fairness_payload: dict, review_payload: dict) -> dict:
    """Map the three referenced audit artifacts to normalized booleans.

    Reads the ACTUAL artifact payloads (never a self-claim):
      - sanity_verdict.verdict == 'PASS'                  -> leakage_pass
      - analysis_check_verdict.pass is True (fairness)    -> fairness_pass
      - review_report.verdict == 'APPROVE-FREEZE'         -> reviewer_approves_freeze
    Missing / malformed -> the safe value (False / not-approve), so a thin bundle fails closed.
    """
    leakage_pass = (sanity_payload or {}).get("verdict") == SANITY_PASS
    fairness_pass = (fairness_payload or {}).get("pass") is True \
        and (fairness_payload or {}).get("panel_role") == "fairness"
    reviewer_verdict = (review_payload or {}).get("verdict")
    reviewer_approves_freeze = reviewer_verdict == REVIEWER_FREEZE
    return {
        "leakage_pass": leakage_pass,
        "fairness_pass": fairness_pass,
        "reviewer_approves_freeze": reviewer_approves_freeze,
        "reviewer_verdict": reviewer_verdict,
    }


# ---------- pure: the re-derivation (the safety core) ----------

def rederive(*, leakage_pass: bool, fairness_pass: bool, reviewer_approves_freeze: bool,
             human_freeze: bool, source_result_status: str = "provisional") -> dict:
    """Re-derive the promotion decision. Returns a dict that validates against
    promotion_record.schema.json's derived fields (admissible / rederived_* / reasons)."""
    reasons: List[str] = []
    source_killed = source_result_status in _TERMINAL_NONFROZEN

    frozen = (
        bool(human_freeze)
        and reviewer_approves_freeze
        and leakage_pass
        and fairness_pass
        and not source_killed
    )
    if frozen:
        status = "frozen"
    elif source_killed:
        status = source_result_status            # honest pass-through of a terminal state
    else:
        status = "provisional"                    # ceiling: anything unproven stays provisional

    can_cite = (status == "frozen") and leakage_pass and fairness_pass
    admissible = (status == "frozen") and can_cite

    if not human_freeze:
        reasons.append("no human_freeze (machine cannot self-promote; ceiling = provisional)")
    if not reviewer_approves_freeze:
        reasons.append("adversarial-reviewer did not APPROVE-FREEZE")
    if not leakage_pass:
        reasons.append("leakage/sanity audit != PASS")
    if not fairness_pass:
        reasons.append("fairness audit != pass")
    if source_killed:
        reasons.append(f"source result-status='{source_result_status}' is terminal (non-promotable)")
    if admissible:
        reasons.append("admitted: frozen ∧ leakage_pass ∧ fairness_pass ∧ human_freeze ∧ reviewer_approves_freeze")
    if not reasons:  # defensive: schema requires minItems 1 (should be unreachable)
        reasons.append("rejected: re-derivation did not yield frozen")

    return {
        "admissible": admissible,
        "rederived_result_status": status,
        "rederived_can_cite_thesis": can_cite,
        "reasons": reasons,
    }


# ---------- pure: slug + page rendering ----------

def make_slug(raw: str) -> str:
    """Lowercase-kebab, the vault slug discipline (schema-contract §5)."""
    out = []
    for ch in (raw or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_/":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def render_vault_page(*, slug: str, vault_type: str, project: str, title: str,
                      created: str, decision: dict, candidate: dict) -> str:
    """Render an admitted vault page: universal frontmatter + re-derived result fields.
    can-cite-thesis is written FROM the derivation, never from input."""
    body = candidate.get("body", "").strip()
    fm = [
        "---",
        f"title: {title}",
        f"type: {vault_type}",
        "status: completed",
        "confidence: high",
        f"created: {created}",
        f"updated: {created}",
        f"project: {project}",
        "evidence-class: EXP-RESULT",
        "owner: promote-to-vault-gate",
        f"result-status: {decision['rederived_result_status']}",
        f"can-cite-thesis: {str(decision['rederived_can_cite_thesis']).lower()}",
        "leakage-audit: pass",
        "fairness-audit: pass",
        "---",
        "",
        f"# {title}",
        "",
        body or "_Promoted, re-derived frozen result. See evidence-artifact references in the run._",
        "",
    ]
    return "\n".join(fm)


# ---------- I/O: the gate's executable core ----------

def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = path.read_text(encoding="utf-8") if path.exists() else ""
    if prev and not prev.endswith("\n"):
        prev += "\n"
    path.write_text(prev + line + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def promote_to_vault(candidate: dict, *, signals: dict, human_freeze: bool,
                     vault_root, decided_by: str, decided_at: str,
                     candidate_path: Optional[str] = None,
                     candidate_sha: Optional[str] = None) -> dict:
    """Run the gate: re-derive -> on admit write the vault page + bump index/log -> return the
    promotion_record dict. NEVER writes the vault unless admissible. `signals` come from
    extract_signals() over the REAL referenced audit artifacts.

    Returns a promotion_record (validate it with validate_payload('promotion_record', ...))."""
    decision = rederive(
        leakage_pass=signals["leakage_pass"],
        fairness_pass=signals["fairness_pass"],
        reviewer_approves_freeze=signals["reviewer_approves_freeze"],
        human_freeze=human_freeze,
        source_result_status=candidate.get("source_result_status", "provisional"),
    )

    vault_path: Optional[str] = None
    vault_slug: Optional[str] = None

    if decision["admissible"]:
        vault_type = candidate.get("vault_type", "result")
        folder = candidate.get("vault_folder") or (vault_type + "s")
        vault_slug = make_slug(candidate["slug"])
        page = render_vault_page(
            slug=vault_slug,
            vault_type=vault_type,
            project=candidate.get("project", "unknown"),
            title=candidate.get("title", vault_slug),
            created=decided_at[:10],
            decision=decision,
            candidate=candidate,
        )
        page_path = Path(vault_root) / "02-wiki" / folder / f"{vault_slug}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page, encoding="utf-8")
        vault_path = str(page_path)
        # vault write discipline: always update index.md + log.md (vault CLAUDE.md §5)
        _append_line(Path(vault_root) / "00-system" / "index.md",
                     f"- [[{vault_slug}]] ({vault_type}) — promoted {decided_at[:10]}")
        _append_line(Path(vault_root) / "07-logs" / "log.md",
                     f"PROMOTE [[{vault_slug}]] — frozen, can-cite-thesis, by {decided_by} {decided_at}")

    record = {
        "candidate_ref": {
            "path": candidate_path or candidate.get("_path", "inbox/promotion-candidate.json"),
            "sha256": candidate_sha or candidate.get("_sha256", "sha256:" + "0" * 64),
        },
        "admissible": decision["admissible"],
        "rederived_result_status": decision["rederived_result_status"],
        "rederived_can_cite_thesis": decision["rederived_can_cite_thesis"],
        "reasons": decision["reasons"],
        "vault_path": vault_path,
        "vault_slug": vault_slug,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }
    return record
