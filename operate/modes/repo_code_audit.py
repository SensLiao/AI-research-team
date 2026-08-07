"""Operate recipe for the `repo_code_audit` mode (DISCOVER -> EXECUTE -> REPORT) — wave 2.

The registry called this mode `registry_routable_spec_only` because its nine code seats were
reachable but had "no mode-level staged collaboration, patch-authorization boundary, or final
Markdown audit product". This module supplies those three things.

**The patch-authorization boundary is the point of the mode.** An audit that can quietly become a
patch is not an audit, so authorization is a DETERMINISTIC SWITCH, never a model judgment:

  * no `inbox/repo-patch-authorization.json` -> **audit-only branch**: `repo-code-verifier` finds
    and `patch-planner` proposes. Not one file changes, the plan stays `draft`, and the "Authorized
    changes" section says so in words.
  * a well-formed marker with `repo_patch: true` -> **authorized-patch branch**, which additionally
    dispatches `code-implementer` / `unit-test-writer` / `sandbox-runner` / `repro-runner` and turns
    the three change-boundary guards below into real gates.
  * a marker the machine cannot read is a GateBlock, never a silent downgrade: the director meant to
    authorize something and deserves to be told the marker is broken.

The marker lives in the run inbox rather than the task_frame because `task_frame.schema.json` is
`additionalProperties: false` and a recipe may not widen a pinned, hash-chained contract. Its shape
mirrors the explicit-marker precedent in `tools/citation_attribution.load_explicit_legacy_replay`:
opt-in, strictly validated, raises rather than guesses.

**Three guards, reinterpreted for a change set instead of an experiment.** The registry assigns
`preflight-checker` / `variable-touch-guard` / `train-test-parity-verifier` to this mode's
`reproduce_and_guard` step and calls their product "change-boundary verdicts", so here they bound the
authorized patch — computed in plain Python exactly as `full_rigor_minimal` computes them, because
each schema insists the verdict is derived and never hand-set: preflight (every PLANNED path is
inside the authorized scope), change-boundary (every TOUCHED path is authorized and planned), parity
(applied change set == planned change set). In the audit-only branch none is written and both report
and Markdown say `NOT_APPLICABLE`: a PASS for a gate with nothing to check is a fake pass.

**Findings, proposals and applied changes never share a column** — confusing them is this mode's
worst failure. The verifier may only find (its prompt forbids proposing), the planner may only
propose (it did not audit and cannot approve its own plan), and only the implementer's record —
reachable solely through the authorization branch — may say a file changed.

**No worker number survives without an execution receipt.** Every seat here is fenced (the agent
specs forbid Bash), so a reported `smoke_passed` / `repro_passed` / `coverage_pct` / `exit_code` is
by construction not a measurement; `_panel_recipe.refuse_metrics_without_receipt` BLOCKs it unless
`tools.full_rigor_execution_truth` calls the run real. The honest default is "scripts emitted,
nothing ran".

Findings have no registered artifact type (no payload schema is a code-finding list, and a recipe may
not invent one), so the deterministic dedup/severity pipeline lands in the registry's declared
product — the director Markdown — plus the stage report's counts, with the worker's raw bundle left
immutable on disk as the audit trail.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _panel_recipe, _shared
from ..artifacts import GateBlock, write_artifact
from ...tools.repo_verifier import verify_repo

MODE = "repo_code_audit"
STAGES = _panel_recipe.stage_path(MODE)
DEFAULT_VAULT = _panel_recipe.DEFAULT_VAULT

#: The director's opt-in patch authorization. Absent == audit-only, by design.
AUTHORIZATION_REL = "inbox/repo-patch-authorization.json"
AUTHORIZATION_VERSION = "repo-patch-authorization/v1"

_VERIFIER = "repo-code-verifier"
_PLANNER = "patch-planner"
_PATCH_SEATS = ("code-implementer", "unit-test-writer", "sandbox-runner", "repro-runner")

#: Artifacts only the authorized-patch branch may ever produce. Their presence in an unauthorized
#: run is evidence that something changed files without a mandate — a hard stop, not a warning.
_PATCH_ONLY_ARTIFACTS = (
    "implementation-record.artifact.json", "test-suite-record.artifact.json",
    "sandbox-report.artifact.json", "repro-record.artifact.json",
    "preflight-report.artifact.json", "variable-touch-verdict.artifact.json",
    "parity-verdict.artifact.json",
)

# --- deterministic severity model -------------------------------------------------------------
# A worker writes a severity word; the recipe decides what it MEANS. Unknown words block rather
# than default, and a structurally severe category cannot be talked down.
_SEVERITY_ALIASES = {
    "critical": "critical", "blocker": "critical", "block": "critical", "severe": "critical",
    "high": "high", "major": "high",
    "medium": "medium", "moderate": "medium", "warn": "medium", "warning": "medium",
    "low": "low", "minor": "low", "note": "low", "nit": "low", "info": "low",
}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_STRUCTURAL_FLOOR = {
    "test-set-leakage": "critical", "train-test-contamination": "critical",
    "eval-on-train": "critical", "data-leakage": "critical", "hardcoded-secret": "critical",
    "metric-mismatch": "high", "nondeterministic-seed": "high", "silent-except": "high",
    "unpinned-dependency": "high",
}

#: Strings a hash / script field must never be. A provenance field that is a placeholder is worse
#: than a missing one: it looks pinned and is not.
_PLACEHOLDERS = ("", "n/a", "na", "none", "null", "todo", "tbd", "unknown", "placeholder",
                 "<hash>", "0" * 64)


# =========================================================================== the authorization gate

def _norm_path(value) -> str:
    """One spelling for a repo-relative path. Case is PRESERVED: a case-folded compare would let
    `SRC/secret.py` slip past an `src/` authorization, and the asymmetric cost says fail closed."""
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _inside(path: str, prefixes) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def load_patch_authorization(run_dir) -> Optional[dict]:
    """The director's patch authorization, or None for the audit-only branch.

    Strict on purpose. `repo_patch: false` is an explicit refusal and returns None; anything the
    machine cannot read as an unambiguous yes/no raises, because silently auditing when the director
    asked for a patch — or worse, patching on a half-written marker — are both unacceptable.
    """
    path = Path(run_dir) / AUTHORIZATION_REL
    if not path.is_file():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise GateBlock(
            f"{MODE}: {AUTHORIZATION_REL} is present but unreadable ({exc}). A patch authorization "
            f"the machine cannot parse is never downgraded to audit-only — fix or delete it.") from exc
    if not isinstance(marker, dict):
        raise GateBlock(f"{MODE}: {AUTHORIZATION_REL} must be a JSON object")
    if marker.get("authorization_contract_version") != AUTHORIZATION_VERSION:
        raise GateBlock(
            f"{MODE}: {AUTHORIZATION_REL} must declare "
            f"authorization_contract_version={AUTHORIZATION_VERSION!r}")
    flag = marker.get("repo_patch")
    if flag is False:
        return None                      # an explicit "no" — audit-only, and that is legitimate
    if flag is not True:
        raise GateBlock(
            f"{MODE}: {AUTHORIZATION_REL} must set repo_patch to the boolean true or false, "
            f"got {flag!r} — the patch branch is never opened on an ambiguous value")
    who = str(marker.get("authorized_by") or "").strip()
    if not who:
        raise GateBlock(f"{MODE}: {AUTHORIZATION_REL} requires a non-empty authorized_by")
    note = str(marker.get("scope_note") or "").strip()
    if len(note) < 10:
        raise GateBlock(
            f"{MODE}: {AUTHORIZATION_REL} requires a specific scope_note (what may change and why)")
    raw_paths = marker.get("authorized_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise GateBlock(
            f"{MODE}: {AUTHORIZATION_REL} requires a non-empty authorized_paths list — an "
            f"unbounded patch authorization is not an authorization")
    prefixes = []
    for entry in raw_paths:
        norm = _norm_path(entry)
        if not norm or norm.startswith("/") or ".." in norm.split("/") or ":" in norm:
            raise GateBlock(
                f"{MODE}: authorized_paths entry {entry!r} is not a safe repo-relative prefix")
        prefixes.append(norm)
    return {"contract_version": AUTHORIZATION_VERSION, "repo_patch": True, "authorized_by": who,
            "authorized_paths": tuple(dict.fromkeys(prefixes)), "scope_note": note,
            "marker_ref": AUTHORIZATION_REL}


def _dispatch_authorized(run_dir) -> bool:
    """Branch choice for `llm_step` only. A broken marker dispatches the audit-only panel and lets
    the deterministic stage raise the readable GateBlock — dispatch is not a gate surface."""
    try:
        return load_patch_authorization(run_dir) is not None
    except GateBlock:
        return False


# =========================================================================== hand-written seat prompts

VERIFIER_PROMPT = """You are the repository code verifier and the ONLY seat in this run that reads \
the codebase.

REQUEST: {request}

{north_star}

READ (real paths, nothing inlined):
  1. `{run_dir}/task_frame.artifact.json` — the request and the north star you serve.
  2. The repository or subtree the request names. Glob and Grep it yourself and OPEN every file you
     cite. If the request names no repository, audit the repository this run lives in and say so in
     `notes`.
  3. `{vault}/02-wiki/` ONLY when a finding needs a project convention to judge against; cite a page
     by its real `[[slug]]` or not at all.
You may spawn read-only assistants to widen coverage; they write nothing, and you sign for their work.

YOUR TWO OUTPUTS, in ONE JSON object:
  (a) the repository-scope FACTS. You gather them; a deterministic verifier — not you — turns them
      into the verdict, so record only what you actually saw.
  (b) the FINDINGS. One entry per real defect or risk you can point at inside a file.

HONESTY (hard): every finding must name a file that EXISTS and locate the evidence inside it; never
invent a path, symbol, line number, slug or commit. A fact you did not check is `false`, never an
optimistic `true`. If a path is unreadable, say so in `notes` and set `has_code` from what you could
actually read. You NEVER propose a fix here — proposing belongs to the patch-planner, and blurring
finding with proposal is the exact failure this mode exists to prevent. A thin codebase yields a
thin finding list; report it thin rather than padded.

Write ONLY this JSON to `{out}` (it ends in .bundle.json, NOT .artifact.json):
{{"repo_audit": {{
  "repo_ref": "<the repository or subtree you audited: owner/repo, a URL, or a relative path>",
  "checks": {{"has_code": true, "has_license": false, "license_id": null,
              "has_pinned_commit": false, "commit": null, "has_weights": false,
              "pretrained_loads_grepped": false}},
  "surfaces_examined": ["<a directory or file you really walked>", "..."],
  "findings": [
    {{"finding_id": "F-001",
      "path": "<relative path of a file that exists>",
      "locus": "<function / class / line range; \\"\\" when the whole file is the locus>",
      "category": "<test-set-leakage | train-test-contamination | eval-on-train | data-leakage | \
hardcoded-secret | metric-mismatch | nondeterministic-seed | silent-except | unpinned-dependency | \
correctness | resource | api-misuse | dead-code | readability | other>",
      "severity": "critical|high|medium|low",
      "title": "<one line: what is wrong>",
      "impact": "<what breaks, or which conclusion stops being valid>",
      "evidence": ["<path:locus plus the exact snippet or symbol you read>", "..."],
      "recommendation": "<what would have to change, DESCRIBED — never a patch>"}}
  ],
  "notes": "<what the deterministic layer must know: unreadable paths, conventions you judged \
against, how many read-only assistants you used>"
}}}}

Quantities are FLOORS with NO upper bound. Walk >=8 distinct surfaces (files or directories) and
report EVERY defensible finding — >=6 whenever the code supports that many. That is a floor, not a
cap: never drop a finding you can evidence in order to keep the list short, and never invent one to
reach the floor. Two findings sharing path + locus + category are ONE finding — merge them yourself.
The deterministic layer merges any you miss and KEEPS THE HIGHEST severity in the group, so an
understated severity cannot hide inside a merge; a structurally severe category (leakage /
contamination / secret) is escalated by rule whatever you write.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, and re-emit the COMPLETE bundle. Never argue with the gate; never relax the honesty
requirements above.
After writing, confirm the file is valid JSON. Return one line: repo_ref, surfaces walked, findings
by severity."""

PLANNER_PROMPT = """You are the patch planner. You did NOT audit this code and you change NO file: \
you turn another seat's findings into a scoped, reviewable PLAN.

REQUEST: {request}

{north_star}

READ (real paths):
  - `{run_dir}/inbox/DISCOVER.repo-code-verifier.bundle.json` — the findings you plan against. You
    are independently reading someone else's findings; you did not produce them.
  - `{run_dir}/evidence/DISCOVER/repo-verification.artifact.json` — the derived repository verdict.
  - `{run_dir}/{auth_rel}` — the director's patch authorization IF IT EXISTS. When it is absent,
    NOTHING may be implemented in this run: your plan is a proposal only, and you say that in
    `rationale`. When it is present, every path you plan MUST sit inside its `authorized_paths`; a
    planned path outside that scope is a hard BLOCK downstream, so do not plan one.
  - Every file a finding names, so you can confirm the path exists before scoping a change to it.

HONESTY (hard): one change per file. A path you have not opened is not a path you may plan. Never
plan a change no finding supports, and never silently drop a critical or high finding — if you
deliberately do not plan one, name it and say why in `rationale`. `status` MUST be `"draft"`: you
are a planner, never your own approver, and the recipe — not you — records the director's
authorization.

Write ONLY this JSON to `{out}`:
{{"patch_plan": {{
  "status": "draft",
  "title": "<short title for this change set>",
  "rationale": "<which findings this addresses, which it deliberately does not, and why>",
  "changes": [{{"path": "<relative path that exists, or a new file you intend to create>",
                "change_type": "create|modify|delete",
                "description": "<what changes and why — enough for the implementer to act without \
asking you again>",
                "snippet": "<representative code or pseudocode, or null>",
                "risk_note": "<blast radius / shared-infrastructure risk, or null>"}}]
}}}}

Quantities are FLOORS with NO upper bound: scope a change for EVERY critical and high finding you
can (>=1 change, and more whenever the findings support more). A floor, not a cap — never trim the
plan for brevity, never invent a change to pad it.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, re-emit the COMPLETE bundle, and do not argue with the gate.
After writing, confirm valid JSON. Return one line: number of changes, which finding ids are covered
and which are not."""

IMPLEMENTER_PROMPT = """You are the code implementer. You are running ONLY because the director \
dropped an explicit patch authorization into this run. You change exactly what the recorded plan \
scopes, inside the authorized paths, and nothing else.

{north_star}

READ (real paths):
  - `{run_dir}/evidence/EXECUTE/patch-plan.artifact.json` — the recorded, director-authorized plan.
    It is your ONLY mandate.
  - `{run_dir}/inbox/EXECUTE.patch-planner.bundle.json` — the planner's full reasoning.
  - `{run_dir}/{auth_rel}` — the authorized path scope. A file outside it stays off-limits even when
    the plan names it; report that conflict instead of resolving it yourself.
  - Every file you are about to change, BEFORE you change it.

HONESTY (hard): `files_changed` records what you REALLY changed — not what you intended and not what
the plan asked for. A file you touched appears here even if the edit was trivial; a planned file you
did not touch does NOT appear. Deterministic guards compare this list against both the plan and the
authorized scope and BLOCK on any drift, so an inaccurate list is caught rather than hidden. Never
report a line count you did not compute. Never claim a test or reproduction result — you do not run
anything.

Write ONLY this JSON to `{out}`:
{{"implementation_record": {{
  "from_patch_plan_ref": "evidence/EXECUTE/patch-plan.artifact.json",
  "condition_id": "<the patch identity shared by this run's sandbox and repro records>",
  "summary": "<what the change set does, in one or two sentences>",
  "files_changed": [{{"path": "<relative path you really touched>",
                      "change_type": "created|modified|deleted",
                      "lines_added": 0, "lines_removed": 0,
                      "notes": "<anything the reviewer must know about this file>"}}],
  "out_of_scope_writes_blocked": false,
  "git_sha": null,
  "caveats": ["<what you deliberately left undone, and why>"]
}}}}

Quantities are FLOORS with NO upper bound: implement EVERY change the plan scopes that the
authorization allows, and list EVERY file you touched. A floor, not a cap.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, and re-emit the COMPLETE bundle without arguing with the gate.
After writing, confirm valid JSON. Return one line: files changed and anything you could not do."""

TEST_WRITER_PROMPT = """You are the unit-test writer for an authorized patch. You did not plan and \
did not implement the change: you write the tests that would CATCH it if it were wrong.

{north_star}

READ (real paths):
  - `{run_dir}/evidence/EXECUTE/implementation-record.artifact.json` — what really changed.
  - `{run_dir}/inbox/EXECUTE.code-implementer.bundle.json` — the implementer's own account.
  - `{run_dir}/evidence/DISCOVER/repo-verification.artifact.json` plus
    `{run_dir}/inbox/DISCOVER.repo-code-verifier.bundle.json` — the finding each test must pin down.
  - the changed files themselves, and the repository's existing test layout so your tests match it.

HONESTY (hard): you WRITE tests; you do not RUN them. `coverage_pct` MUST be null and you must not
report a pass, a fail, or a number you did not measure — a deterministic gate BLOCKs any measured
claim that has no execution receipt. Every `test_files` path must be a file you actually wrote.
Prefer a test that fails on the ORIGINAL defect over a test that merely exercises the new code.

Write ONLY this JSON to `{out}`:
{{"test_suite_record": {{
  "from_implementation_ref": "evidence/EXECUTE/implementation-record.artifact.json",
  "test_targets": ["<logical target: the loader / the metric / the guard / ...>"],
  "test_files": [{{"path": "<relative path of a test file you wrote>", "n_tests": 1,
                   "covers": ["<which test_targets this file exercises>"]}}],
  "coverage_pct": null,
  "notes": "<gaps you knowingly left, edge cases deferred, why>"
}}}}

Quantities are FLOORS with NO upper bound: >=1 target per critical or high finding the patch
addresses, and a regression test for EVERY changed file. A floor, not a cap.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, re-emit the COMPLETE bundle, and do not argue with the gate.
After writing, confirm valid JSON. Return one line: targets and test files written."""

SANDBOX_PROMPT = """You are the sandbox runner. You EMIT a runnable smoke script for the authorized \
patch; you do not execute it — this seat is fenced and has no shell.

{north_star}

READ (real paths):
  - `{run_dir}/evidence/EXECUTE/implementation-record.artifact.json` — the files that changed.
  - `{run_dir}/evidence/EXECUTE/test-suite-record.artifact.json` — the tests already written, so
    your smoke script drives them instead of duplicating them.
  - the changed files and the repository's entry points, so `invoke_command` is real.

HONESTY (hard): `smoke_passed`, `exit_code`, `stdout_tail` and `stderr_tail` MUST all be null. You
did not run anything, so any value there would be fabricated, and a deterministic gate BLOCKs a
measured claim that carries no execution receipt. `smoke_script` must be REAL runnable code — no
prose, no `TODO`, no placeholder. `condition_id` must be the same patch identity the
implementation record uses.

Write ONLY this JSON to `{out}`:
{{"sandbox_report": {{
  "condition_id": "<same patch identity as the implementation record>",
  "from_implementation_ref": "evidence/EXECUTE/implementation-record.artifact.json",
  "smoke_script": "<the actual runnable script text>",
  "invoke_command": "<the exact shell command that runs it>",
  "smoke_passed": null, "exit_code": null, "stdout_tail": null, "stderr_tail": null,
  "notes": "<what the script proves, what it cannot prove, what it needs installed>"
}}}}

Cover, as a FLOOR with no upper bound, every changed file's import path and every test file the
suite record names. A floor, not a cap.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, re-emit the COMPLETE bundle, and do not argue with the gate.
After writing, confirm valid JSON. Return one line: what the smoke script covers and how to run it."""

REPRO_PROMPT = """You are the reproduction runner. You lock the provenance triple that lets someone \
else re-run this authorized patch and get the same thing. You do not execute it — this seat is fenced.

{north_star}

READ (real paths):
  - `{run_dir}/evidence/EXECUTE/implementation-record.artifact.json` — what changed.
  - `{run_dir}/evidence/EXECUTE/sandbox-report.artifact.json` — the smoke script to reproduce.
  - `{run_dir}/evidence/EXECUTE/test-suite-record.artifact.json` — the tests in scope.
  - the config and fixture files you are about to hash, so the hashes are of real bytes.

HONESTY (hard): `seed`, `config_hash` and `data_hash` are schema-required and must be REAL. Compute
each hash from actual file bytes and record the exact command you used in `notes`; a placeholder
(`unknown`, `n/a`, `todo`, all-zeros) is BLOCKed deterministically, because a fake hash looks pinned
and is not. If the change genuinely has no dataset, hash the exact test fixture the reproduction
pins and say so in `notes` — never invent a value to satisfy the schema. `repro_passed` and
`result_delta` MUST be null: you ran nothing. `condition_id` must match the implementation and
sandbox records.

Write ONLY this JSON to `{out}`:
{{"repro_record": {{
  "condition_id": "<same patch identity as the implementation and sandbox records>",
  "from_run_record_ref": null,
  "seed": 0,
  "config_hash": "<sha256 of the exact config bytes>",
  "data_hash": "<sha256 of the exact data or fixture bytes>",
  "git_sha": null,
  "repro_script": "<the runnable script that reproduces the check>",
  "repro_passed": null, "result_delta": null,
  "notes": "<the exact hashing commands, the environment assumed, what stays unpinned>"
}}}}

Pin, as a FLOOR with no upper bound, every input the smoke script reads. A floor, not a cap.

If this prompt carries a REPAIR ATTEMPT block: fix EXACTLY what the gate feedback names, change
nothing else, re-emit the COMPLETE bundle, and do not argue with the gate.
After writing, confirm valid JSON. Return one line: seed plus the two hashes and how you computed them."""


# =========================================================================== dispatch

def _seats(run_dir, stage: str, request: str, vault: str, *, authorized: bool) -> list:
    """The seats for one stage. The authorized-patch branch is strictly ADDITIVE."""
    north_star = _shared.north_star_block(run_dir)
    out = lambda label: _panel_recipe.bundle_path(run_dir, stage, label)  # noqa: E731
    if stage == "DISCOVER":
        return [_panel_recipe.Seat(
            label=_VERIFIER, bundle_key="repo_audit", tier="audit",
            prompt=VERIFIER_PROMPT.format(request=request, north_star=north_star, vault=vault,
                                          run_dir=run_dir, out=out(_VERIFIER)))]
    seats = [_panel_recipe.Seat(
        label=_PLANNER, bundle_key="patch_plan", tier="reason",
        prompt=PLANNER_PROMPT.format(request=request, north_star=north_star, run_dir=run_dir,
                                     auth_rel=AUTHORIZATION_REL, out=out(_PLANNER)))]
    if not authorized:
        return seats
    seats += [
        _panel_recipe.Seat(
            label="code-implementer", bundle_key="implementation_record", tier="reason",
            depends_on=(_PLANNER,),
            prompt=IMPLEMENTER_PROMPT.format(north_star=north_star, run_dir=run_dir,
                                             auth_rel=AUTHORIZATION_REL,
                                             out=out("code-implementer"))),
        _panel_recipe.Seat(
            label="unit-test-writer", bundle_key="test_suite_record", tier="reason",
            depends_on=("code-implementer",),
            prompt=TEST_WRITER_PROMPT.format(north_star=north_star, run_dir=run_dir,
                                             out=out("unit-test-writer"))),
        _panel_recipe.Seat(
            label="sandbox-runner", bundle_key="sandbox_report", tier="tool",
            depends_on=("code-implementer",),
            prompt=SANDBOX_PROMPT.format(north_star=north_star, run_dir=run_dir,
                                         out=out("sandbox-runner"))),
        _panel_recipe.Seat(
            label="repro-runner", bundle_key="repro_record", tier="tool",
            depends_on=("code-implementer", "unit-test-writer", "sandbox-runner"),
            prompt=REPRO_PROMPT.format(north_star=north_star, run_dir=run_dir,
                                       out=out("repro-runner"))),
    ]
    return seats


def llm_step(run_dir: str, stage: str, request: str, vault: str = DEFAULT_VAULT,
             model_policy: str = "default") -> Optional[dict]:
    """The seats to dispatch for a stage. REPORT is deterministic and dispatches nobody."""
    if stage not in ("DISCOVER", "EXECUTE"):
        return None
    authorized = _dispatch_authorized(run_dir)
    seats = _seats(run_dir, stage, request, vault, authorized=authorized)
    if stage == "DISCOVER":
        note = ("One accountable reader walks the repository and separates facts from findings; it "
                "may fan out read-only assistants and signs for them. It never proposes a fix.")
    elif authorized:
        note = (f"AUTHORIZED-PATCH branch ({AUTHORIZATION_REL} present): plan, then implement, then "
                f"write tests and emit the smoke script in parallel, then lock the reproduction "
                f"triple. Change-boundary guards run deterministically afterwards.")
    else:
        note = (f"AUDIT-ONLY branch (no {AUTHORIZATION_REL}): the planner PROPOSES and nothing is "
                f"implemented. The patch seats are not dispatched and no file is changed.")
    return _panel_recipe.panel(run_dir, stage, MODE, seats, panel_note=note,
                               model_policy=model_policy)


# =========================================================================== findings pipeline

def _require_text(value, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise GateBlock(f"{MODE}: {what} is required and must be non-empty")
    return text


def _severity(raw, category: str, finding_id: str) -> str:
    key = str(raw or "").strip().casefold()
    resolved = _SEVERITY_ALIASES.get(key)
    if resolved is None:
        raise GateBlock(
            f"{MODE}: finding {finding_id!r} carries severity {raw!r}, which is not one of "
            f"{sorted(set(_SEVERITY_ALIASES))} — severity is never silently defaulted")
    floor = _STRUCTURAL_FLOOR.get(category)
    if floor and _SEVERITY_RANK[floor] < _SEVERITY_RANK[resolved]:
        return floor                     # a structurally severe category cannot be talked down
    return resolved


def normalize_findings(audit: dict) -> list:
    """Validate and normalize the verifier's raw findings. Shape defects BLOCK, never coerce."""
    raw = audit.get("findings")
    if raw is None:
        raise GateBlock(
            f"{MODE}: the {_VERIFIER} bundle has no 'findings' key. An empty list is a legitimate "
            f"answer ('nothing found'); a missing key means the seat did not do the job.")
    if not isinstance(raw, list):
        raise GateBlock(f"{MODE}: 'findings' must be a JSON array, got {type(raw).__name__}")
    seen_ids: set = set()
    out = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise GateBlock(f"{MODE}: finding #{index} is not a JSON object")
        fid = _require_text(item.get("finding_id"), f"finding #{index} finding_id")
        if fid in seen_ids:
            raise GateBlock(f"{MODE}: finding_id {fid!r} appears twice — ids must be unique")
        seen_ids.add(fid)
        path = _norm_path(_require_text(item.get("path"), f"finding {fid} path"))
        if path.startswith("/") or ".." in path.split("/"):
            raise GateBlock(f"{MODE}: finding {fid} path {path!r} is not repo-relative")
        category = (_require_text(item.get("category"), f"finding {fid} category")
                    .casefold().replace("_", "-").replace(" ", "-"))
        evidence = [str(e).strip() for e in (item.get("evidence") or []) if str(e).strip()]
        if not evidence:
            raise GateBlock(
                f"{MODE}: finding {fid} carries no evidence — an unevidenced finding is an opinion")
        out.append({
            "finding_id": fid, "path": path, "locus": str(item.get("locus") or "").strip(),
            "category": category, "severity": _severity(item.get("severity"), category, fid),
            "title": _require_text(item.get("title"), f"finding {fid} title"),
            "impact": str(item.get("impact") or "").strip(),
            "recommendation": str(item.get("recommendation") or "").strip(),
            "evidence": list(dict.fromkeys(evidence)),
        })
    return out


def dedupe_findings(findings: list) -> list:
    """Merge on (path, locus, category) and order totally. Fully deterministic.

    The merge is deliberately narrow — it never crosses files or categories — and it keeps the
    HIGHEST severity in a group, so merging can only ever raise a finding's priority, never launder
    a critical one into a note. The sort key is total, so the same input always renders identically.
    """
    groups: dict = {}
    for finding in findings:
        groups.setdefault((finding["path"], finding["locus"], finding["category"]), []).append(finding)
    merged = []
    for members in groups.values():
        members = sorted(members, key=lambda f: f["finding_id"])
        lead = dict(members[0])
        lead["severity"] = min((m["severity"] for m in members), key=lambda s: _SEVERITY_RANK[s])
        lead["evidence"] = list(dict.fromkeys(e for m in members for e in m["evidence"]))
        lead["merged_ids"] = [m["finding_id"] for m in members]
        lead["merged_titles"] = list(dict.fromkeys(m["title"] for m in members))
        merged.append(lead)
    return sorted(merged, key=lambda f: (_SEVERITY_RANK[f["severity"]], f["path"], f["locus"],
                                         f["finding_id"]))


def _histogram(findings: list) -> dict:
    return {level: sum(1 for f in findings if f["severity"] == level) for level in _SEVERITY_RANK}


# =========================================================================== DISCOVER

def _facts(audit: dict) -> dict:
    """The five repo facts, strictly typed. `verify_repo` — not a worker — derives the verdict."""
    raw = audit.get("checks")
    if not isinstance(raw, dict):
        raise GateBlock(f"{MODE}: the {_VERIFIER} bundle needs a 'checks' object of gathered facts")
    facts = {}
    for key in ("has_code", "has_license", "has_pinned_commit", "has_weights",
                "pretrained_loads_grepped"):
        value = raw.get(key, False)
        if not isinstance(value, bool):
            raise GateBlock(
                f"{MODE}: checks.{key} must be a real boolean, got {value!r} — an unchecked fact "
                f"is false, never a truthy string")
        facts[key] = value
    for key in ("license_id", "commit"):
        value = raw.get(key)
        facts[key] = None if value is None else str(value).strip() or None
    return facts


def _discover_dets(run_dir, ts) -> tuple:
    seats = _seats(run_dir, "DISCOVER", "", DEFAULT_VAULT, authorized=False)
    bundles = _panel_recipe.load_seat_bundles(run_dir, "DISCOVER", MODE, seats)
    audit = bundles["repo_audit"]
    if not isinstance(audit, dict):
        raise GateBlock(f"{MODE}: 'repo_audit' must be a JSON object")

    repo_ref = _require_text(audit.get("repo_ref"), "repo_audit.repo_ref")
    raw_findings = normalize_findings(audit)
    findings = dedupe_findings(raw_findings)
    verification = verify_repo(repo_ref, _facts(audit))

    paths = [write_artifact(run_dir, "DISCOVER", "repo-verification.artifact.json",
                            "repo_verification", _VERIFIER, verification, ts,
                            "blocked" if verification["verdict"] == "BLOCK" else "approved")]
    if verification["verdict"] == "BLOCK":
        raise GateBlock(
            f"{MODE} repository scope BLOCK: {repo_ref!r} has no usable code "
            f"(missing {verification['missing']}) — there is nothing to audit. Point the run at a "
            f"real code surface, or accept 'no code' as the answer and stop here.")

    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "DISCOVER", ts, mode=MODE, bundles=bundles,
        downstream_refs=[e for f in findings for e in f["evidence"]],
        known_ids=[f["finding_id"] for f in findings] + [f["path"] for f in findings] + [repo_ref])
    paths += gate_paths

    surfaces = [str(s).strip() for s in (audit.get("surfaces_examined") or []) if str(s).strip()]
    report = {"repo_ref": repo_ref, "repo_verification": verification["verdict"],
              "repo_facts_missing": verification["missing"],
              "n_surfaces_examined": len(surfaces),
              "n_findings_raw": len(raw_findings), "n_findings": len(findings),
              "n_findings_merged": sum(len(f["merged_ids"]) - 1 for f in findings),
              "severity_histogram": _histogram(findings),
              "finding_ids": [f["finding_id"] for f in findings]}
    report.update(frag)
    return paths, report


# =========================================================================== EXECUTE

def _discover_findings(run_dir) -> tuple:
    """Re-read the immutable DISCOVER bundle so EXECUTE can render findings it did not produce."""
    path = Path(_panel_recipe.bundle_path(run_dir, "DISCOVER", _VERIFIER))
    if not path.is_file():
        raise GateBlock(
            f"{MODE} EXECUTE cannot render an audit without its findings: {path.name} is missing. "
            f"Run DISCOVER first — the patch plan has nothing to be a plan ABOUT.")
    audit = _shared.extract_worker_bundle_value(
        json.loads(path.read_text(encoding="utf-8")), "repo_audit",
        stage="DISCOVER", mode=MODE, agent=_VERIFIER)
    return dedupe_findings(normalize_findings(audit)), audit


def _refuse_unauthorized_change_evidence(run_dir, plan: dict) -> None:
    """The audit-only branch may not carry a single trace of an applied change.

    This is the mode's signature gate. Anything that would let a report say "we changed X" without
    a director authorization stops the run here: a patch seat's bundle on disk, a patch-only
    artifact already written, or a plan that promotes itself past `draft`.
    """
    inbox = Path(run_dir) / "inbox"
    stray = [f"inbox/EXECUTE.{seat}.bundle.json" for seat in _PATCH_SEATS
             if (inbox / f"EXECUTE.{seat}.bundle.json").is_file()]
    stray += [f"evidence/EXECUTE/{name}" for name in _PATCH_ONLY_ARTIFACTS
              if (Path(run_dir) / "evidence" / "EXECUTE" / name).is_file()]
    if stray:
        raise GateBlock(
            f"{MODE} audit-only BLOCK: this run has no {AUTHORIZATION_REL}, yet it carries "
            f"applied-change evidence {stray}. An audit that quietly became a patch is exactly what "
            f"this branch exists to prevent — delete the stray evidence, or have the director "
            f"authorize the patch explicitly.")
    if str(plan.get("status")) != "draft":
        raise GateBlock(
            f"{MODE} audit-only BLOCK: the patch plan declares status "
            f"{plan.get('status')!r}. Without {AUTHORIZATION_REL} no plan in this run is approved, "
            f"and a planner never approves its own plan.")


def _plan_payload(plan, *, authorized: bool, auth: Optional[dict]) -> dict:
    """The schema-valid patch_plan. The worker always writes `draft`; the RECIPE records approval."""
    if not isinstance(plan, dict):
        raise GateBlock(f"{MODE}: 'patch_plan' must be a JSON object")
    if str(plan.get("status")) != "draft":
        raise GateBlock(
            f"{MODE}: {_PLANNER} must emit status='draft' (got {plan.get('status')!r}) — approval is "
            f"recorded by the recipe from the director's authorization, never by the planner")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        raise GateBlock(
            f"{MODE}: the patch plan needs at least one scoped change. If no finding is worth a "
            f"change, say that in the audit rather than emitting an empty plan.")
    rows = []
    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            raise GateBlock(f"{MODE}: planned change #{index} is not a JSON object")
        kind = str(change.get("change_type") or "").strip()
        if kind not in ("create", "modify", "delete"):
            raise GateBlock(
                f"{MODE}: planned change #{index} has change_type {kind!r} "
                f"(expected create/modify/delete)")
        rows.append({
            "path": _norm_path(_require_text(change.get("path"), f"planned change #{index} path")),
            "change_type": kind,
            "description": _require_text(change.get("description"),
                                         f"planned change #{index} description"),
            "snippet": (str(change["snippet"]) if change.get("snippet") else None),
            "risk_note": (str(change["risk_note"]) if change.get("risk_note") else None),
        })
    payload = {"status": "approved" if authorized else "draft",
               "title": str(plan.get("title") or "").strip() or None,
               "rationale": str(plan.get("rationale") or "").strip() or None,
               "from_protocol_ref": None, "changes": rows,
               "review_notes": (
                   f"director-authorized via {auth['marker_ref']} by {auth['authorized_by']}; "
                   f"scope {list(auth['authorized_paths'])}" if authorized and auth else
                   f"PROPOSAL ONLY — no {AUTHORIZATION_REL} in this run, so nothing was implemented")}
    return payload


def _preflight(run_dir, ts, plan: dict, auth: dict) -> tuple:
    """Before a single file is touched: is every planned path inside the authorized scope?"""
    prefixes = auth["authorized_paths"]
    violations = [f"planned path {row['path']!r} is outside the authorized scope {list(prefixes)}"
                  for row in plan["changes"] if not _inside(row["path"], prefixes)]
    payload = {"verdict": "BLOCK" if violations else "PASS", "violations": violations,
               "checks_performed": [
                   f"patch plan is non-empty ({len(plan['changes'])} change(s))",
                   f"every planned path is inside authorized_paths from {auth['marker_ref']}",
                   f"authorization signed by {auth['authorized_by']}"],
               "protocol_ref": None, "alignment_ref": None}
    path = write_artifact(run_dir, "EXECUTE", "preflight-report.artifact.json", "preflight_report",
                          "preflight-checker", payload, ts,
                          "blocked" if violations else "approved")
    if violations:
        raise GateBlock(f"{MODE} preflight BLOCK: {violations}")
    return path, payload


def _change_boundary(run_dir, ts, plan: dict, record: dict, auth: dict) -> tuple:
    """Did the change that REALLY happened stay inside the authorization and inside the plan?"""
    prefixes = auth["authorized_paths"]
    planned = {row["path"] for row in plan["changes"]}
    touched = [row["path"] for row in record["files_changed"]]
    violations = []
    for path in touched:
        if not _inside(path, prefixes):
            violations.append(f"touched {path!r} is outside the authorized scope {list(prefixes)}")
        if path not in planned:
            violations.append(f"touched {path!r} appears in no planned change")
    payload = {"verdict": "BLOCK" if violations else "PASS", "violations": violations,
               "checked_against": auth["marker_ref"], "touched": touched}
    path = write_artifact(run_dir, "EXECUTE", "variable-touch-verdict.artifact.json",
                          "variable_touch_verdict", "variable-touch-guard", payload, ts,
                          "blocked" if violations else "approved")
    if violations:
        raise GateBlock(f"{MODE} change-boundary BLOCK: {violations}")
    return path, payload


_APPLIED = {"create": "created", "modify": "modified", "delete": "deleted"}


def _plan_applied_parity(run_dir, ts, plan: dict, record: dict) -> tuple:
    """Plan-vs-applied drift: the same schema question as train/test parity, asked of a change set."""
    planned = {row["path"]: _APPLIED[row["change_type"]] for row in plan["changes"]}
    applied = {row["path"]: row["change_type"] for row in record["files_changed"]}
    violations = [f"planned {path!r} ({kind}) was never applied"
                  for path, kind in sorted(planned.items()) if path not in applied]
    violations += [f"applied {path!r} ({kind}) was never planned"
                   for path, kind in sorted(applied.items()) if path not in planned]
    violations += [f"{path!r} drifted from design: planned={planned[path]!r} applied={applied[path]!r}"
                   for path in sorted(set(planned) & set(applied)) if planned[path] != applied[path]]
    payload = {"verdict": "BLOCK" if violations else "PASS", "violations": violations,
               "drift_checks": [f"planned paths ({len(planned)}) vs applied paths ({len(applied)})",
                                "change_type of every path present on both sides"],
               "journal_ref": None, "alignment_ref": None}
    path = write_artifact(run_dir, "EXECUTE", "parity-verdict.artifact.json", "parity_verdict",
                          "train-test-parity-verifier", payload, ts,
                          "blocked" if violations else "approved")
    if violations:
        raise GateBlock(f"{MODE} plan-vs-applied parity BLOCK: {violations}")
    return path, payload


def _no_placeholder(value, what: str) -> str:
    text = str(value or "").strip()
    if text.casefold() in _PLACEHOLDERS:
        raise GateBlock(
            f"{MODE}: {what} is the placeholder {value!r}. A fake provenance value looks pinned and "
            f"is not — compute it from real bytes or say in notes that you cannot.")
    return text


def _measured_claims(suite: dict, sandbox: dict, repro: dict) -> dict:
    """Every field only a real execution could fill. Present-and-not-None == a measurement claim."""
    candidates = {"test_suite_record.coverage_pct": suite.get("coverage_pct"),
                  "sandbox_report.smoke_passed": sandbox.get("smoke_passed"),
                  "sandbox_report.exit_code": sandbox.get("exit_code"),
                  "sandbox_report.stdout_tail": sandbox.get("stdout_tail"),
                  "sandbox_report.stderr_tail": sandbox.get("stderr_tail"),
                  "repro_record.repro_passed": repro.get("repro_passed"),
                  "repro_record.result_delta": repro.get("result_delta")}
    return {name: value for name, value in candidates.items() if value is not None}


def _patch_payloads(bundles: dict) -> tuple:
    """Shape-check the four patch bundles and bind them by a single shared patch identity."""
    record = bundles["implementation_record"]
    suite = bundles["test_suite_record"]
    sandbox = bundles["sandbox_report"]
    repro = bundles["repro_record"]
    for name, value in (("implementation_record", record), ("test_suite_record", suite),
                        ("sandbox_report", sandbox), ("repro_record", repro)):
        if not isinstance(value, dict):
            raise GateBlock(f"{MODE}: {name!r} must be a JSON object")

    files = record.get("files_changed")
    if not isinstance(files, list) or not files:
        raise GateBlock(
            f"{MODE}: the authorized-patch branch ran but implementation_record.files_changed is "
            f"empty. If nothing needed changing, that is an audit-only outcome — say so instead of "
            f"reporting an empty patch.")
    changed = []
    for index, row in enumerate(files, start=1):
        if not isinstance(row, dict):
            raise GateBlock(f"{MODE}: files_changed #{index} is not a JSON object")
        kind = str(row.get("change_type") or "").strip()
        if kind not in ("created", "modified", "deleted"):
            raise GateBlock(f"{MODE}: files_changed #{index} change_type {kind!r} is invalid")
        changed.append({
            "path": _norm_path(_require_text(row.get("path"), f"files_changed #{index} path")),
            "change_type": kind,
            "lines_added": row.get("lines_added") if isinstance(row.get("lines_added"), int) else None,
            "lines_removed": (row.get("lines_removed")
                              if isinstance(row.get("lines_removed"), int) else None),
            "notes": str(row["notes"]) if row.get("notes") else None,
        })

    condition = _require_text(sandbox.get("condition_id"), "sandbox_report.condition_id")
    for name, value in (("repro_record.condition_id", repro.get("condition_id")),):
        if _require_text(value, name) != condition:
            raise GateBlock(
                f"{MODE}: {name} is {value!r} but sandbox_report.condition_id is {condition!r} — "
                f"the smoke test and the reproduction must describe the SAME patch")
    impl_condition = str(record.get("condition_id") or "").strip()
    if impl_condition and impl_condition != condition:
        raise GateBlock(
            f"{MODE}: implementation_record.condition_id {impl_condition!r} does not match the "
            f"sandbox/repro patch identity {condition!r}")

    targets = [str(t).strip() for t in (suite.get("test_targets") or []) if str(t).strip()]
    if not targets:
        raise GateBlock(f"{MODE}: test_suite_record.test_targets needs at least one real target")
    test_files = []
    for index, row in enumerate(suite.get("test_files") or [], start=1):
        if not isinstance(row, dict):
            raise GateBlock(f"{MODE}: test_files #{index} is not a JSON object")
        test_files.append({
            "path": _norm_path(_require_text(row.get("path"), f"test_files #{index} path")),
            "n_tests": row.get("n_tests") if isinstance(row.get("n_tests"), int) else None,
            "covers": [str(c).strip() for c in (row.get("covers") or []) if str(c).strip()],
        })

    seed = repro.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise GateBlock(
            f"{MODE}: repro_record.seed must be an integer, got {seed!r} — an unpinned seed is not "
            f"a reproduction")

    record_payload = {
        "from_patch_plan_ref": _require_text(record.get("from_patch_plan_ref"),
                                             "implementation_record.from_patch_plan_ref"),
        "condition_id": impl_condition or None,
        "summary": str(record.get("summary") or "").strip() or None,
        "files_changed": changed,
        "out_of_scope_writes_blocked": bool(record.get("out_of_scope_writes_blocked", False)),
        "git_sha": str(record["git_sha"]).strip() if record.get("git_sha") else None,
        "caveats": [str(c).strip() for c in (record.get("caveats") or []) if str(c).strip()],
    }
    suite_payload = {
        "from_implementation_ref": (str(suite["from_implementation_ref"])
                                    if suite.get("from_implementation_ref") else None),
        "test_targets": targets, "test_files": test_files,
        "coverage_pct": suite.get("coverage_pct"),
        "notes": str(suite.get("notes") or "").strip() or None,
    }
    sandbox_payload = {
        "condition_id": condition,
        "from_implementation_ref": (str(sandbox["from_implementation_ref"])
                                    if sandbox.get("from_implementation_ref") else None),
        "smoke_script": _no_placeholder(_require_text(sandbox.get("smoke_script"),
                                                      "sandbox_report.smoke_script"),
                                        "sandbox_report.smoke_script"),
        "invoke_command": (str(sandbox["invoke_command"]).strip()
                           if sandbox.get("invoke_command") else None),
        "smoke_passed": sandbox.get("smoke_passed"), "exit_code": sandbox.get("exit_code"),
        "stdout_tail": sandbox.get("stdout_tail"), "stderr_tail": sandbox.get("stderr_tail"),
        "notes": str(sandbox.get("notes") or "").strip() or None,
    }
    repro_payload = {
        "condition_id": condition, "from_run_record_ref": None, "seed": seed,
        "config_hash": _no_placeholder(_require_text(repro.get("config_hash"),
                                                     "repro_record.config_hash"),
                                       "repro_record.config_hash"),
        "data_hash": _no_placeholder(_require_text(repro.get("data_hash"),
                                                   "repro_record.data_hash"),
                                     "repro_record.data_hash"),
        "git_sha": str(repro["git_sha"]).strip() if repro.get("git_sha") else None,
        "repro_script": str(repro["repro_script"]) if repro.get("repro_script") else None,
        "repro_passed": repro.get("repro_passed"), "result_delta": repro.get("result_delta"),
        "notes": str(repro.get("notes") or "").strip() or None,
    }
    return record_payload, suite_payload, sandbox_payload, repro_payload


def _execute_dets(run_dir, ts) -> tuple:
    auth = load_patch_authorization(run_dir)
    authorized = auth is not None
    seats = _seats(run_dir, "EXECUTE", "", DEFAULT_VAULT, authorized=authorized)
    bundles = _panel_recipe.load_seat_bundles(run_dir, "EXECUTE", MODE, seats)
    findings, audit = _discover_findings(run_dir)
    state = _panel_recipe.execution_truth(run_dir)

    if not authorized:
        _refuse_unauthorized_change_evidence(run_dir, bundles["patch_plan"]
                                             if isinstance(bundles["patch_plan"], dict) else {})
    plan = _plan_payload(bundles["patch_plan"], authorized=authorized, auth=auth)
    paths = [write_artifact(run_dir, "EXECUTE", "patch-plan.artifact.json", "patch_plan", _PLANNER,
                            plan, ts, "approved" if authorized else "draft")]

    record = suite = sandbox = repro = None
    guards = {"preflight_gate": "NOT_APPLICABLE", "change_boundary_gate": "NOT_APPLICABLE",
              "plan_applied_parity_gate": "NOT_APPLICABLE"}
    if authorized:
        preflight_path, _ = _preflight(run_dir, ts, plan, auth)
        paths.append(preflight_path)
        guards["preflight_gate"] = "PASS"

        record, suite, sandbox, repro = _patch_payloads(bundles)
        _panel_recipe.refuse_metrics_without_receipt(
            state, _measured_claims(suite, sandbox, repro), mode=MODE,
            what="test / smoke / reproduction outcomes")
        paths += [
            write_artifact(run_dir, "EXECUTE", "implementation-record.artifact.json",
                           "implementation_record", "code-implementer", record, ts),
            write_artifact(run_dir, "EXECUTE", "test-suite-record.artifact.json",
                           "test_suite_record", "unit-test-writer", suite, ts),
            write_artifact(run_dir, "EXECUTE", "sandbox-report.artifact.json", "sandbox_report",
                           "sandbox-runner", sandbox, ts),
            write_artifact(run_dir, "EXECUTE", "repro-record.artifact.json", "repro_record",
                           "repro-runner", repro, ts),
        ]
        boundary_path, _ = _change_boundary(run_dir, ts, plan, record, auth)
        parity_path, _ = _plan_applied_parity(run_dir, ts, plan, record)
        paths += [boundary_path, parity_path]
        guards["change_boundary_gate"] = "PASS"
        guards["plan_applied_parity_gate"] = "PASS"

    gate_paths, frag = _panel_recipe.common_gates(
        run_dir, "EXECUTE", ts, mode=MODE, bundles=bundles,
        downstream_refs=[row["path"] for row in plan["changes"]]
                        + [row["path"] for row in (record or {}).get("files_changed", [])],
        known_ids=[f["finding_id"] for f in findings] + [f["path"] for f in findings])
    paths += gate_paths

    report = {"branch": "authorized_patch" if authorized else "audit_only",
              "authorization_ref": auth["marker_ref"] if authorized else None,
              "authorized_paths": list(auth["authorized_paths"]) if authorized else [],
              "patch_plan_status": plan["status"], "n_planned_changes": len(plan["changes"]),
              "n_findings": len(findings), "severity_histogram": _histogram(findings),
              "n_files_changed": len(record["files_changed"]) if record else 0,
              "n_test_targets": len(suite["test_targets"]) if suite else 0,
              "smoke_status": _smoke_status(sandbox), "repro_status": _repro_status(repro),
              "execution_label": state.get("label"), "execution_executed": bool(state.get("executed"))}
    report.update(guards)
    report.update(frag)
    report["director_markdown"] = _render(run_dir, ts, findings=findings, audit=audit, plan=plan,
                                          auth=auth, record=record, suite=suite, sandbox=sandbox,
                                          repro=repro, state=state, report=report)
    return paths, report


def _smoke_status(sandbox: Optional[dict]) -> str:
    if sandbox is None:
        return "NOT_APPLICABLE"
    passed = sandbox.get("smoke_passed")
    return "NOT_EXECUTED" if passed is None else ("PASSED" if passed else "FAILED")


def _repro_status(repro: Optional[dict]) -> str:
    if repro is None:
        return "NOT_APPLICABLE"
    passed = repro.get("repro_passed")
    return "NOT_EXECUTED" if passed is None else ("REPRODUCED" if passed else "NOT_REPRODUCIBLE")


# =========================================================================== director Markdown

def _cell(value) -> str:
    text = " ".join(str(value or "").split()).replace("|", "\\|")
    return text or "—"


def _table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _scope_section(audit: dict, findings: list, plan: dict, auth: Optional[dict]) -> str:
    verification = verify_repo(str(audit.get("repo_ref") or ""), _facts(audit))
    surfaces = [str(s).strip() for s in (audit.get("surfaces_examined") or []) if str(s).strip()]
    checks = verification["checks"]
    branch = (f"**AUTHORIZED-PATCH branch** — `{auth['marker_ref']}` authorizes "
              f"{list(auth['authorized_paths'])} (signed by {auth['authorized_by']}): "
              f"{auth['scope_note']}") if auth else (
        f"**AUDIT-ONLY branch** — no `{AUTHORIZATION_REL}` in this run, so no file was changed.")
    lines = [
        f"- Audited surface: `{verification['repo_ref']}`",
        f"- Repository verdict (derived, never worker-set): **{verification['verdict']}**"
        + (f" — missing {verification['missing']}" if verification["missing"] else ""),
        f"- Surfaces really walked: {len(surfaces)}"
        + (f" — {', '.join('`' + s + '`' for s in surfaces[:12])}" if surfaces else " (none reported)"),
        f"- Findings after deterministic merge: {len(findings)}; planned changes: {len(plan['changes'])}",
        f"- {branch}",
        "",
        _table(["fact", "value"],
               [["has_code", checks["has_code"]], ["has_license", checks["has_license"]],
                ["license_id", checks["license_id"] or "—"],
                ["has_pinned_commit", checks["has_pinned_commit"]],
                ["commit", checks["commit"] or "—"], ["has_weights", checks["has_weights"]],
                ["pretrained_loads_grepped", checks["pretrained_loads_grepped"]]]),
    ]
    notes = str(audit.get("notes") or "").strip()
    if notes:
        lines += ["", f"Verifier notes: {notes}"]
    return "\n".join(lines)


def _findings_section(findings: list) -> str:
    if not findings:
        return ("无 —— verifier 报告了零个 finding。这是「没找到」，不是「没查」：仓库 scope 与真正走过的 "
                "surface 数量见上一节；空清单只在 verifier 的 bundle 落盘、且经过 schema 与证据校验后才会渲染成这一行。\n\n"
                "None found — the verifier reported zero findings. This row is rendered only after its "
                "bundle passed shape and evidence validation, so it means 'nothing found', not "
                "'nothing looked at'.")
    histogram = _histogram(findings)
    head = (f"**FINDINGS — what is wrong. Not proposals, not changes.** "
            f"{len(findings)} after merge "
            f"(critical {histogram['critical']} · high {histogram['high']} · "
            f"medium {histogram['medium']} · low {histogram['low']}). Order is deterministic: "
            f"severity, then path, then locus, then id. A merged group keeps its highest severity.")
    rows = []
    for index, finding in enumerate(findings, start=1):
        merged = (f" (merged {len(finding['merged_ids'])}: {', '.join(finding['merged_ids'])})"
                  if len(finding["merged_ids"]) > 1 else "")
        rows.append([index, finding["severity"].upper(), finding["category"],
                     f"`{finding['path']}`" + (f" @ {finding['locus']}" if finding["locus"] else ""),
                     finding["title"] + merged, finding["impact"] or "—",
                     "; ".join(finding["evidence"][:3])])
    return head + "\n\n" + _table(
        ["#", "severity", "category", "location", "finding", "impact", "evidence"], rows)


def _plan_section(plan: dict, findings: list) -> str:
    head = (f"**PROPOSALS — what the planner says should change. Nothing here has been applied.** "
            f"Plan status: `{plan['status']}`. {len(plan['changes'])} scoped change(s).")
    if plan["title"]:
        head += f" Title: {plan['title']}."
    body = _table(["#", "path", "change_type", "description", "risk"],
                  [[index, f"`{row['path']}`", row["change_type"], row["description"],
                    row["risk_note"] or "—"]
                   for index, row in enumerate(plan["changes"], start=1)])
    tail = [head, "", body]
    if plan["rationale"]:
        tail += ["", f"Planner rationale (including findings deliberately not planned): "
                     f"{plan['rationale']}"]
    unplanned = [f for f in findings if f["severity"] in ("critical", "high")
                 and f["path"] not in {row["path"] for row in plan["changes"]}]
    if unplanned:
        tail += ["", "Critical/high findings with NO planned change (deterministically detected by "
                     "path): " + ", ".join(f"{f['finding_id']} (`{f['path']}`)" for f in unplanned)]
    if plan["review_notes"]:
        tail += ["", f"Approval record: {plan['review_notes']}"]
    return "\n".join(tail)


def _applied_section(plan: dict, auth: Optional[dict], record: Optional[dict],
                     guards: dict) -> str:
    if record is None:
        return (f"**未授权 —— 只出了计划，没有改动任何文件。** 本次 run 的 inbox 里没有 "
                f"`{AUTHORIZATION_REL}`，所以 `code-implementer` / `unit-test-writer` / "
                f"`sandbox-runner` / `repro-runner` 四个席位一个都没派，仓库里零个文件被写过。"
                f"上一节的 {len(plan['changes'])} 条是**提议**，不是改动。\n\n"
                f"三道改动边界守卫（preflight / change-boundary / plan-vs-applied parity）标记为 "
                f"**NOT_APPLICABLE**：它们没有东西可查，所以没有写出任何 verdict artifact —— "
                f"给一个没查过的门写 PASS 就是假的通过。\n\n"
                f"要真的改代码，导演需要在 `{AUTHORIZATION_REL}` 放一份 "
                f"`{AUTHORIZATION_VERSION}` marker（`repo_patch: true` + `authorized_paths` + "
                f"`authorized_by` + `scope_note`），然后重跑 EXECUTE。\n\n"
                f"**NOT AUTHORIZED — a plan only; not one file was changed.** No "
                f"`{AUTHORIZATION_REL}`, so the four patch seats were never dispatched and the three "
                f"change-boundary guards are NOT_APPLICABLE (no verdict artifact was written, "
                f"because a gate with nothing to check has not passed).")
    lines = [
        f"**APPLIED CHANGES — files that really changed, under `{auth['marker_ref']}` signed by "
        f"{auth['authorized_by']}.** {len(record['files_changed'])} file(s).",
        "",
        _table(["path", "change_type", "+", "-", "notes"],
               [[f"`{row['path']}`", row["change_type"],
                 "—" if row["lines_added"] is None else row["lines_added"],
                 "—" if row["lines_removed"] is None else row["lines_removed"],
                 row["notes"] or "—"] for row in record["files_changed"]]),
        "",
        "Change-boundary guards (deterministic, verdicts derived not declared): "
        f"preflight **{guards['preflight_gate']}** · touched-paths-vs-authorization "
        f"**{guards['change_boundary_gate']}** · planned-vs-applied parity "
        f"**{guards['plan_applied_parity_gate']}**.",
    ]
    if record["summary"]:
        lines += ["", f"Implementer summary: {record['summary']}"]
    if record["out_of_scope_writes_blocked"]:
        lines += ["", "The scope guard blocked at least one attempted write outside this stage's "
                      "scope during implementation."]
    if record["caveats"]:
        lines += ["", "Implementer caveats: " + "; ".join(record["caveats"])]
    return "\n".join(lines)


def _evidence_section(suite: Optional[dict], sandbox: Optional[dict], repro: Optional[dict],
                      state: dict) -> str:
    if suite is None:
        return (f"**NOT_APPLICABLE —— audit-only 分支没有测试也没有复现证据，因为没有任何改动需要被验证。**"
                f"`unit-test-writer` / `sandbox-runner` / `repro-runner` 都没被派；这里没有被跳过的测试，"
                f"只有不存在的改动。\n\n"
                f"Execution state of this run: `{state.get('label')}`.\n\n"
                f"**NOT_APPLICABLE — the audit-only branch has no test or reproduction evidence "
                f"because it has no change to verify.** Nothing was skipped; there is nothing to skip.")
    lines = [
        f"Test targets ({len(suite['test_targets'])}): "
        + ", ".join(f"`{t}`" for t in suite["test_targets"]),
        "",
        _table(["test file", "n_tests", "covers"],
               [[f"`{row['path']}`", "—" if row["n_tests"] is None else row["n_tests"],
                 ", ".join(row["covers"]) or "—"] for row in suite["test_files"]]
              or [["(none written)", "—", "—"]]),
        "",
        f"- Smoke test: **{_smoke_status(sandbox)}** · invoke: "
        f"`{sandbox['invoke_command'] or '(no command recorded)'}`",
        f"- Reproduction: **{_repro_status(repro)}** · seed `{repro['seed']}` · config_hash "
        f"`{repro['config_hash'][:16]}…` · data_hash `{repro['data_hash'][:16]}…`",
        f"- Measured coverage: "
        + ("not measured (no execution receipt)" if suite["coverage_pct"] is None
           else f"{suite['coverage_pct']}%"),
    ]
    if repro["notes"]:
        lines += ["", f"Reproduction notes: {repro['notes']}"]
    if sandbox["notes"]:
        lines += ["", f"Smoke-script notes: {sandbox['notes']}"]
    if suite["notes"]:
        lines += ["", f"Test-suite notes: {suite['notes']}"]
    return "\n".join(lines)


def _risks_section(findings: list, plan: dict, record: Optional[dict], sandbox: Optional[dict],
                   repro: Optional[dict], state: dict) -> str:
    planned = {row["path"] for row in plan["changes"]}
    open_findings = [f for f in findings if f["path"] not in planned]
    lines = []
    if open_findings:
        lines.append("Findings left open by this plan (no change scoped to their file): "
                     + "; ".join(f"{f['finding_id']} [{f['severity'].upper()}] `{f['path']}` — "
                                 f"{f['title']}" for f in open_findings))
    else:
        lines.append("No finding was left without a scoped change — every finding's file appears in "
                     "the plan. That is coverage of the FILE, not proof the fix is correct.")
    risky = [row for row in plan["changes"] if row["risk_note"]]
    if risky:
        lines.append("Planner-declared blast radius: "
                     + "; ".join(f"`{row['path']}` — {row['risk_note']}" for row in risky))
    if record is None:
        lines.append(f"Nothing was applied, so no regression risk was introduced by this run. The "
                     f"risk that remains is entirely the {len(findings)} finding(s) still in the code.")
    else:
        lines.append(f"{len(record['files_changed'])} file(s) really changed. Smoke test is "
                     f"{_smoke_status(sandbox)} and reproduction is {_repro_status(repro)}, so the "
                     f"patch is recorded, not validated.")
    if not state.get("executed"):
        lines.append("No number in this brief was measured: this run has no attested executor "
                     "receipt, so every test/reproduction field is a script parameter, not a result.")
    lines.append("Deterministic limits of this audit: severity is normalized and floor-escalated by "
                 "rule, and findings are merged only on identical path+locus+category — a defect the "
                 "verifier never opened is absent from every section above, and absence here is not "
                 "evidence of correctness.")
    return "\n\n".join(lines)


def _render(run_dir, ts, *, findings, audit, plan, auth, record, suite, sandbox, repro, state,
            report) -> str:
    """Render the registry's declared director Markdown. Section keys are verbatim from the registry."""
    guards = {key: report[key] for key in
              ("preflight_gate", "change_boundary_gate", "plan_applied_parity_gate")}
    sections = {
        "Repository scope": _scope_section(audit, findings, plan, auth),
        "Prioritized findings": _findings_section(findings),
        "Patch plan": _plan_section(plan, findings),
        "Authorized changes": _applied_section(plan, auth, record, guards),
        "Test and reproduction evidence": _evidence_section(suite, sandbox, repro, state),
        "Residual risks": _risks_section(findings, plan, record, sandbox, repro, state),
    }
    return _panel_recipe.render_director_markdown(
        run_dir, MODE, sections, ts=ts, lead="research-orchestrator",
        extra={"Execution boundary": _panel_recipe.execution_boundary_section(state)})


# =========================================================================== REPORT

def _report(run_dir, ts) -> tuple:
    rel = _panel_recipe.target_markdown(MODE)["path"]
    if not (Path(run_dir) / rel).is_file():
        raise GateBlock(
            f"{MODE} REPORT cannot reference {rel} because it was never rendered — commit EXECUTE "
            f"first. A report note pointing at a missing brief is a fabricated reference.")
    authorized = load_patch_authorization(run_dir) is not None
    branch = ("authorized-patch branch: findings, an approved plan, the applied change set and its "
              "three change-boundary verdicts"
              if authorized else
              "audit-only branch: findings and a proposed plan ONLY — no file was changed and the "
              "change-boundary guards are NOT_APPLICABLE")
    return _panel_recipe.report_note(
        run_dir, ts, mode=MODE,
        summary=(f"{MODE}: {branch}. Findings, proposals and applied changes are kept in separate "
                 f"sections of {rel}; severity is normalized and floor-escalated deterministically, "
                 f"and no test or reproduction number is reported without an execution receipt."),
        references=[rel],
        open_questions=([] if authorized else
                        [f"Apply any of the proposed changes? That needs an explicit "
                         f"{AUTHORIZATION_VERSION} marker at {AUTHORIZATION_REL}."]))


# =========================================================================== spine contract

def run_dets(run_dir, stage, ts) -> tuple:
    """Deterministic producers/gates for a stage -> (artifact_paths, report). Raises GateBlock."""
    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "EXECUTE":
        return _execute_dets(run_dir, ts)
    if stage == "REPORT":
        return _report(run_dir, ts)
    raise ValueError(f"{MODE} has no stage {stage!r}")


run_dets_with_repair = _panel_recipe.make_repair(MODE, run_dets)
