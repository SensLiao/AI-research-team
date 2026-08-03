---
phase: 01-operated-ai-manuscript-authoring
plan: "20"
subsystem: release-evidence-and-director-entry
tags: [environment, latex, docker, evidence, routing, completion]
status: complete
completed: 2026-07-22
---

# Phase 01 Plan 20: Release Evidence and Completion Summary

Phase 01 is release-verified against a before/after SHA-256 snapshot of the
current executable source tree. The machine has twelve concrete operated modes,
including separate `manuscript_authoring` and `manuscript_review` recipes, and
the release evidence proves their build, routing, safety, and documentation
contracts across Windows and Docker Linux.

## Delivered

- Added exact runtime and development manifests using only already-observed
  distributions: `PyYAML`, `jsonschema`, `cryptography`, `PyMuPDF`, `paramiko`,
  and `pytest`.
- Added fail-closed environment and completion checks. They validate pinned
  dependencies, mode/registry/catalog parity, the 17-case matrix, D-07
  no-search-before-named-deficit routing, director-facing entries, JUnit
  thresholds, the Windows receipt, and explicit post-command release evidence.
- Produced a real Windows MiKTeX/latexmk `COMPILED` receipt with sanitized
  executable/argv, source/log/recorder/PDF hashes, and `--disable-installer`.
  The direct fallback and `TOOLCHAIN_MISSING` branches remain tested.
- Ran the immutable Docker `linux/amd64` target using
  `python@sha256:cb1503943096ba7e3713bab3a59c4fa493c1799949c1f16dedfc2a7ff80754da`
  with a read-only repository mount and writable evidence mount only.
- Synchronized `README.md`, `PLATFORM-FACTS.md`, and all workspace director
  entry interfaces to the two exact operated manuscript mode ids; the obsolete
  `manuscript_review_pack` id is absent.
- Closed final full-suite defects instead of masking them: three producer output
  types now have closed hash-bound schemas, the capability-count assertion is
  twelve, and the hermetic MiKTeX fixture simulates its target platform on Linux.
- Made the three declared manuscript handoffs real lifecycle outputs: authoring
  persists venue/evidence slices after contract freeze, while the separate review
  run persists the advisory submission checklist. The review-only packager is no
  longer advertised or dispatched in authoring.
- Kept orchestration light: hard checks bind evidence, source, PDF, and run
  boundaries; paper prose, section allocation, token use, and specialist work
  remain adaptive rather than globally template-locked.
- Hardened the final manuscript path during release verification: no predictable
  temporary write paths, binary secret scanning, MiKTeX implicit-install
  suppression, review input no-follow checks, and advisory-only review truth
  without an externally signed scheduler verifier.

## Verification Evidence

All evidence is under `.planning/evidence/phase-01/`.

| Gate | Result |
|---|---|
| Windows real build / readiness / fallback / missing toolchain | 4 passed, 0 failures/errors/skips; `windows/real-build-receipt.json` is `COMPILED` |
| Immutable Docker Linux `linux/amd64` | 125 passed, 1 expected non-host-TeX skip, 0 failures/errors; `linux/targeted.xml` |
| AI evaluation | 4/4 scenarios pass; 13/13 machine checks; 0 required machine failures |
| Security suite | 141 passed, 1 platform-permission skip, 0 failures/errors |
| Director route | 5 passed; D-07 transport spy retained |
| Completion / integration / renderer | 111 passed |
| Final full suite | 3728 passed, 4 expected platform skips, 0 failures/errors |
| Current-source binding | 765 source files; identical pre/post inventory `255734222d705c84856705272ddd8d0fb3b55b9daae0f2a34de975ee795719fe` |
| Explicit release-evidence parser | 1 passed with `RAT_VERIFY_PHASE_EVIDENCE=1` |

## Machine Repository Changes

- Machine files: `requirements*.txt`, manuscript schemas/registry/tests,
  LaTeX and renderer safety adapters, operated review adapter, `README.md`,
  `PLATFORM-FACTS.md`, and `.planning/` phase artifacts.
- Evidence: `machine-changed-files.txt` records the actual machine git status;
  it may include pre-existing unrelated dirty-worktree entries and is not a
  claim that those entries belong to this plan.

## Same-Workspace Interface Synchronization

The following files are synchronized interface outputs outside the machine git
root and are listed with SHA-256 values in
`.planning/evidence/phase-01/workspace-interface-files.json`:

- `../AGENTS.md`
- `../.agents/skills/research-orchestrator/SKILL.md`
- `../.agents/skills/source-command-run-mode/SKILL.md`
- `../.agents/skills/source-command-start-research/SKILL.md`

They are not represented as machine-repository commit evidence.

## Boundaries Retained

- This does not promote anything to the vault/database, download paper full text,
  run a GPU experiment, submit a paper, or make a venue decision.
- `manuscript_review` is useful advisory review only until a deployment supplies
  a verifiable signed external scheduler receipt; it remains
  `submission_ready: false` in that state.
- The release tests prove concrete recipes and fixtures. No completed real
  scientific authoring/review run is claimed by this summary.
