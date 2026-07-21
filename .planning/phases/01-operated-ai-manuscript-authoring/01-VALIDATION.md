---
phase: 01
slug: operated-ai-manuscript-authoring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-21
---

# Phase 01 — Validation Strategy

> Per-phase feedback contract for the operated AI manuscript authoring and independent review capability. The planner must replace provisional task IDs/waves with its final plan IDs without weakening these checks.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2, repository-default discovery |
| **Config file** | none; `tests/test_*.py` convention |
| **Shared fixtures** | `tests/conftest.py` hermetic network/vault defaults |
| **Quick run command** | `python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_literature.py tests/test_manuscript_schema_contracts.py -q` |
| **Focused integration command** | `python -m pytest tests/test_operate_manuscript_authoring.py tests/test_operate_manuscript_review.py tests/test_latex_build.py tests/test_manuscript_audit.py tests/test_manuscript_security.py -q` |
| **Full suite command** | `python -m pytest tests -q` |
| **Estimated runtime** | focused target: <=30 seconds; full suite currently exceeds the prior 120-second mapping ceiling and must run with an explicit evidence timeout rather than being assumed green |

---

## Sampling Rate

- **After every TDD task commit:** run the owning new test module plus the nearest affected boundary test.
- **After every plan wave:** run all manuscript-focused modules plus `test_operate_wiring.py`, `test_capability_catalog.py`, `test_panel_scheduler.py`, `test_validate_artifact.py`, `test_scope_guard.py`, `test_scholar_clients.py`, and `test_paper_search.py`.
- **Before `$gsd-verify-work`:** full suite, AI eval, security review, a real local PDF build, deterministic missing-toolchain fixture, rendered director packet, and changed-file audit must be green.
- **Max feedback latency:** 30 seconds for per-task focused tests; long integration/full-suite runs occur at wave/phase gates.

---

## Per-Task Verification Map

| Provisional Task | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------------------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-W0-01 | TBD | 0 | PREP-01–PREP-04, PLAT-02 | T-01 token override | Official hard rules cannot be overridden; resolved snapshot is canonical and hashed | unit/property/schema | `python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_schema_contracts.py -q` | ❌ W0 | ⬜ pending |
| 01-W0-02 | TBD | 0 | EVID-01–EVID-03, SAFE-02, VERI-02 | T-02 secret/search leakage | Local corpus is assessed first; only named deficits invoke existing search; failures remain failures; URLs/errors redact secrets | unit/contract/security | `python -m pytest tests/test_manuscript_literature.py tests/test_scholar_clients.py tests/test_paper_search.py tests/test_manuscript_security.py -q` | ❌ W0 | ⬜ pending |
| 01-W1-01 | TBD | 1 | ORCH-01–ORCH-02 | T-03 unauthorized context | Sparse dependencies and scoped slices are enforced; one integrator owns final source | unit/contract/integration | `python -m pytest tests/test_panel_scheduler.py tests/test_operate_manuscript_authoring.py -q` | ❌ W1 | ⬜ pending |
| 01-W2-01 | TBD | 2 | LATX-01–LATX-02, ASST-01 | T-04 subprocess/overwrite | Safe argv/no shell escape, real PDF receipt, truthful missing/failure states, owned assets only | unit/integration | `python -m pytest tests/test_latex_build.py tests/test_manuscript_audit.py tests/test_manuscript_security.py -q` | ❌ W2 | ⬜ pending |
| 01-W3-01 | TBD | 3 | AUDT-01, DELV-02, SAFE-03, VERI-03–VERI-04 | T-05 false science/status | Unsupported claims, citation/number mismatch, false execution, and invalid submission readiness fail closed | unit/property/security | `python -m pytest tests/test_manuscript_audit.py tests/test_manuscript_contract.py tests/test_manuscript_security.py -q` | ❌ W3 | ⬜ pending |
| 01-W4-01 | TBD | 4 | OPER-02 | T-06 author/reviewer collapse | Review consumes frozen manuscript hash, cannot mutate authoring run, and emits its own packet | operated integration | `python -m pytest tests/test_operate_manuscript_review.py -q` | ❌ W4 | ⬜ pending |
| 01-W5-01 | TBD | 5 | OPER-01, DELV-01, VERI-01 | T-07 incomplete product | Start/resume and complete authoring fixture produce all human-first/machine products and honest build state | operated E2E | `python -m pytest tests/test_operate_manuscript_authoring.py -q` | ❌ W5 | ⬜ pending |
| 01-W5-02 | TBD | 5 | OPER-03 | T-08 false operated claim | Recipe, registry, capability catalog, and platform facts remain mirror-consistent | integration | `python -m pytest tests/test_operate_wiring.py tests/test_capability_catalog.py -q` | ✅ extend | ⬜ pending |
| 01-W5-03 | TBD | 5 | SAFE-01, PLAT-01 | T-09 vault/path escape | Vault stays unchanged; traversal/reparse/Unicode-space paths are bounded and portable | security/cross-platform | `python -m pytest tests/test_scope_guard.py tests/test_manuscript_security.py tests/test_latex_build.py -q` | ❌ W0–W2 | ⬜ pending |
| 01-GATE | TBD | gate | VERI-05 | all | Focused, operated, AI-eval/security, and full completion evidence are retained | release | `python -m pytest tests -q` | ✅ command; coverage pending | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Required 16-Case Hermetic Set

- 2 local-corpus cases: sufficient coverage makes zero network calls; a named deficit calls only the existing search port.
- 2 retrieval-truth cases: `SEARCH_FAILED` is not evidence absence; valid exhaustive search may return traced no-evidence.
- 2 token/snapshot cases: deterministic precedence/hard-rule rejection; changed upstream hash invalidates only descendants.
- 2 bundle/DAG cases: at most two format repairs; unauthorized/orphan dependency fails closed.
- 3 scientific-truth cases: unsupported claim, citation identity/entailment mismatch, numeric/receipt mismatch, including false execution.
- 2 asset/path cases: traversal rejected; director asset hash unchanged.
- 2 build cases: real or deterministic fake compiler produces hashed PDF; genuine missing toolchain preserves source and truthful state.
- 1 review-separation case and 1 end-to-end authoring case.

---

## Wave 0 Requirements

- [ ] `tests/test_manuscript_contract.py` — PREP-01–PREP-04, VERI-03.
- [ ] `tests/test_manuscript_literature.py` — EVID-01–EVID-03, VERI-02.
- [ ] `tests/test_manuscript_schema_contracts.py` — valid and truth-sensitive invalid payloads.
- [ ] `tests/test_manuscript_audit.py` — AUDT-01, DELV-02, SAFE-03, VERI-04.
- [ ] `tests/test_latex_build.py` — LATX-01/LATX-02, fake success/failure, conditional real smoke, genuine missing branch.
- [ ] `tests/test_manuscript_security.py` — SAFE-01/SAFE-02, paths, TeX directives, vault writes, sentinel secrets.
- [ ] `tests/test_operate_manuscript_authoring.py` and `tests/test_operate_manuscript_review.py` — operated/E2E/product separation.
- [ ] Register all new schemas in `PAYLOAD_SCHEMAS`; do not install another test framework or validator.

---

## Real Local Build Evidence Available to Execution

On 2026-07-21 this Windows host produced a real BibTeX-resolved PDF with MiKTeX 25.12, Strawberry Perl 5.42.2.1, and latexmk 4.88 using:

`latexmk -gg -pdf -interaction=nonstopmode -halt-on-error -file-line-error main.tex`

The smoke PDF was 35,362 bytes, SHA-256 `19b1639769b2b0e8d79c85fae1a74cab8b5aa0429de69755a9927d7e1d0eb13b`, the final log had zero unresolved-reference warnings, and `chktex -q` exited 0. This proves the local toolchain only; execution must also test `TOOLCHAIN_MISSING` and direct `pdflatex -> bibtex -> pdflatex x2` fallback paths.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Scientific contribution/venue fit and reviewer usefulness | AUDT-01, DELV-02 | Expert judgment cannot be reduced to a deterministic check | Two independent role-scoped reviewers score the frozen manuscript against the AI-SPEC rubric; reconcile blocking scientific findings and retain the report. |
| Current official venue policy interpretation | PREP-01 | Official rules can change and contain venue-specific judgment | Director or venue-compliance reviewer checks the frozen source URLs/retrieval date and approves the venue profile before a submission-ready claim. |
| Final submission decision | DELV-02 | Director-owned commitment | Director reviews packet, PDF, checklist, remaining risks, and independently decides whether to submit; the machine never submits autonomously. |

---

## Validation Sign-Off

- [ ] Planner replaces provisional IDs/waves with final plan tasks.
- [ ] All tasks have `<automated>` verification or explicit Wave 0 dependencies.
- [ ] Sampling continuity: no three consecutive tasks without automated verification.
- [ ] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Focused feedback target is <=30 seconds; long suites are wave/phase gates.
- [ ] `nyquist_compliant: true` set after planner/checker alignment.

**Approval:** pending plan/checker alignment
