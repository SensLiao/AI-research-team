"""Deterministic core of the repo-code-verifier.

Given a repo reference string and a facts dict gathered from the repo
(has_code, has_license, has_pinned_commit, has_weights, pretrained_loads_grepped,
license_id, commit — all optional), build the repo_verification payload and
derive the verdict mechanically:

  BLOCK      — has_code is False (no code at all; nothing else matters)
  UNVERIFIED — has_code is True but license or pinned_commit is absent
  VERIFIED   — has_code, has_license, and has_pinned_commit all True
               (weights / pretrained_loads recorded but NOT required for VERIFIED)

The LLM agent gathers facts from the repo; this function — not the LLM — decides
the verdict, so the gate is mechanical, not a vibe.
"""
from __future__ import annotations

from typing import List, Optional


def verify_repo(repo_ref: str, facts: Optional[dict] = None) -> dict:
    """Build and return a repo_verification payload.

    Parameters
    ----------
    repo_ref:
        A non-empty string identifying the repository (e.g. a GitHub URL or
        ``owner/repo`` slug).
    facts:
        Optional dict of facts gathered from the repo.  All keys are optional;
        unknown keys are silently ignored.

        Boolean facts (default False):
            has_code, has_license, has_pinned_commit, has_weights,
            pretrained_loads_grepped
        String facts (default None):
            license_id, commit
    """
    if facts is None:
        facts = {}

    # --- unpack facts with safe defaults ---------------------------------
    has_code: bool = bool(facts.get("has_code", False))
    has_license: bool = bool(facts.get("has_license", False))
    has_pinned_commit: bool = bool(facts.get("has_pinned_commit", False))
    has_weights: bool = bool(facts.get("has_weights", False))
    pretrained_loads_grepped: bool = bool(facts.get("pretrained_loads_grepped", False))
    license_id: Optional[str] = facts.get("license_id", None)
    commit: Optional[str] = facts.get("commit", None)

    # --- build checks object (schema requires the four boolean fields) ----
    checks: dict = {
        "has_code": has_code,
        "has_license": has_license,
        "has_pinned_commit": has_pinned_commit,
        "has_weights": has_weights,
        "pretrained_loads_grepped": pretrained_loads_grepped,
        "license_id": license_id,
        "commit": commit,
    }

    # --- derive missing list ----------------------------------------------
    missing: List[str] = []
    if not has_code:
        missing.append("code")
    if not has_license:
        missing.append("license")
    if not has_pinned_commit:
        missing.append("pinned_commit")

    # --- derive verdict (never set by hand) ------------------------------
    if not has_code:
        verdict = "BLOCK"
    elif missing:  # license or pinned_commit absent
        verdict = "UNVERIFIED"
    else:
        verdict = "VERIFIED"

    return {
        "verdict": verdict,
        "repo_ref": repo_ref,
        "checks": checks,
        "missing": missing,
    }
