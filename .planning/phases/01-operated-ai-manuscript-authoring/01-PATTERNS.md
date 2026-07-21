# Phase 1 Pattern Map: Operated AI Manuscript Authoring

**Mapped:** 2026-07-21  
**Scope:** Planning guidance for Phase 1 only  
**Rule:** Reuse the native operated-mode control plane. Analog files define structure and safety conventions; `01-RESEARCH.md` defines behavior where no exact manuscript analog exists.

## File Classification

| Planned file | Class | Primary analog | Required pattern to preserve |
|---|---|---|---|
| `operate/modes/manuscript_authoring.py` | SIMILAR | `operate/modes/read_paper_deep.py` | `ARTIFACT_PLAN`, sparse dependency declarations, frozen shared representation, scoped worker inputs, deterministic reducer, targeted repair, readable report |
| `operate/modes/manuscript_review.py` | SIMILAR | `operate/modes/venue_readiness.py` | frozen precommit input, blind reviewers, independent receipts, deterministic meta-verdict, report product |
| `tools/manuscript_contract.py` | ADAPT | `operate/modes/read_paper_deep.py::_write_shared_paper_representation` and `tools/runstore.py` | canonical JSON, immutable snapshot, source hashes, run-local atomic persistence |
| `tools/manuscript_literature.py` | ADAPT | `tools/recall.py`, `tools/paper_search.py::search_many` | bounded vault reads first; explicit deficit authorizes existing search; provider failure is not no-result |
| `tools/manuscript_integrator.py` | ADAPT | `operate/output_versions.py::resolve_effective_output`, `operate/artifacts.py::write_artifact` | one canonical writer, immutable candidates, hash-linked effective versions, validated atomic writes |
| `tools/latex_build.py` | NEW-BY-RESEARCH | `tools/path_boundaries.py`, `tools/runstore.py` plus `01-RESEARCH.md` LaTeX Build Contract | argument-array subprocess, run-owned paths, bounded execution, receipt-gated PDF truth |
| `tools/manuscript_audit.py` | ADAPT | deterministic gates in `operate/modes/read_paper_deep.py` and `operate/modes/venue_readiness.py` | pure audits; scientific truth fail-closed; advisory defects remain visible; status derived from facts |
| `tools/manuscript_renderer.py` | SIMILAR | `tools/director_packet.py::build_packet` and mode-specific Markdown writers | human-first Markdown, stable paths, evidence links and hashes, no hidden JSON-only result |
| `schemas/manuscript_contract.schema.json` | SIMILAR | `schemas/task_frame.schema.json`, `schemas/run_manifest.schema.json` | Draft 2020-12, explicit required fields, closed objects, stable schema version |
| `schemas/manuscript_section_bundle.schema.json` | SIMILAR | `schemas/panel_synthesis.schema.json` | structured worker candidate with provenance, declared dependencies, uncertainty, content hash |
| `schemas/manuscript_integration.schema.json` | SIMILAR | `schemas/panel_synthesis.schema.json` | canonical inventory, reconciliation findings, unresolved interfaces, source-tree hash |
| `schemas/manuscript_build_receipt.schema.json` | SIMILAR | `schemas/run_manifest.schema.json` | command/tool/environment facts, return state, logs, source/PDF hashes; no inferred success |
| `schemas/manuscript_review_verdict.schema.json` | SIMILAR | venue-review schemas and `schemas/panel_synthesis.schema.json` | input hash binding, blind-read receipt, findings, deterministic disposition |
| `schemas/local_literature_coverage.schema.json` | SIMILAR | `schemas/paper_search_result.schema.json` and task-frame schemas | six named coverage axes, local refs, deficits, query authorization, provider outcome separation |
| `schemas/manuscript_asset_manifest.schema.json` | SIMILAR | artifact-envelope/run-manifest schema family | stable label, immutable source hash, run-owned output, caption, result refs, render command |
| `schemas/manuscript_quality_report.schema.json` | SIMILAR | gate-verdict schema family | deterministic findings, severity/class, repair target, daily status, independent submission status |
| `agents/manuscript-*.md` | SIMILAR | current paper-reading and venue-review agent specs | one capability per agent, explicit inputs/outputs, no canonical-tree write permission, independence scope |
| `profiles/paper_design_tokens/*.yaml` | NEW-BY-RESEARCH | existing domain profiles plus `01-AI-SPEC.md` token contract | domain-neutral base; AI-research overlay; hard/advisory split; no transient deadline hardcoding |
| `tests/test_manuscript_contract.py` | SIMILAR | `tests/test_validate_artifact.py` | public behavior, closed schemas, bad input rejection, deterministic hashes |
| `tests/test_manuscript_literature.py` | SIMILAR | paper-search and recall tests | injected transport, sufficient-local suppression, deficit-only activation, failure/no-result distinction |
| `tests/test_latex_build.py` | NEW-BY-RESEARCH | `tests/test_scope_guard.py` plus `01-VALIDATION.md` | fake compiler, timeout/unsafe path/false PDF negatives, hermetic command receipts |
| `tests/test_manuscript_audit.py` | SIMILAR | truth/advisory tests in `tests/test_operate_read_paper_deep.py` | unsupported claims/numbers hard-fail; style gaps caveat; pure status reducer |
| `tests/test_manuscript_schema_contracts.py` | SIMILAR | `tests/test_validate_artifact.py` | every schema registered, valid examples pass, unknown/additional fields reject where contracted |
| `tests/test_operate_manuscript_authoring.py` | SIMILAR | `tests/test_operate_read_paper_deep.py` | full artifact plan, sparse waves, frozen snapshot, supplements, renderer, honest delivery status |
| `tests/test_operate_manuscript_review.py` | SIMILAR | `tests/test_operate_venue_readiness.py` | frozen input hashes, reviewer isolation, no authoring mutation, reviewer/report outputs |
| `tests/test_manuscript_security.py` | SIMILAR | `tests/test_scope_guard.py`, scholarly-client error tests | vault write denial, traversal/symlink defense, secret redaction, TeX command/path safety |
| `operate/modes/__init__.py` | MODIFY | existing `REGISTRY` at line 33 | add a mode only with a real recipe; keep keys synchronized with wiring/capability tests |
| `orchestrator/mode_registry.yaml` | MODIFY | existing operated/spec-only entries | mirror executable truth; remove or replace spec-only manuscript entry only when recipe exists |
| `tools/validate_artifact.py` | MODIFY | `PAYLOAD_SCHEMAS` at line 23; `validate_payload` at line 203 | register every new schema centrally; never mode-local bypass validation |
| `tools/scholar_clients.py` | MODIFY | `ScholarLookupError` line 56, `_fetch_parse` line 98 | sanitize credential-bearing query values before exception text crosses persistence boundaries |
| `tools/capability_catalog.py` and facts manifests | MODIFY | existing capability projection | derive operated status from `operate/modes/__init__.py`, never claim based on YAML alone |
| `tests/test_operate_wiring.py` | MODIFY | lines 32, 40, 45, 77, 142 | exact registry mirror, stage routing, worker labels, next-wave authorization |
| `tests/test_capability_catalog.py` | MODIFY | lines 23, 33, 46 | catalog schema, exact real registry mirror, spec-only honesty |

## Pattern Details

### 1. Operated recipe anatomy

Use `operate/modes/read_paper_deep.py` as the authoring recipe analog:

- `ARTIFACT_PLAN` (line 47) is the complete product contract, not a best-effort list.
- `READ_PAPER_PARALLEL_GROUPS` (line 95), `OPTIONAL_SPECIALISTS` (line 110), and `WORKER_DEPENDENCIES` (line 121) separate capability coverage from adaptive worker count.
- `_active_worker_agents` (line 623), `_write_shared_paper_representation` (line 650), and `_worker_input_contract` (line 673) create frozen common facts plus least-privilege predecessor slices.
- `llm_step` (line 707) exposes worker work; `run_dets` and `run_dets_with_repair` (lines 2520/2528) keep deterministic reduction and bounded repair separate.

The authoring recipe must remain thin. Token resolution, local literature assessment, integration, build, audit, and rendering belong in focused `tools/` modules.

### 2. Independent review product

Use `operate/modes/venue_readiness.py` for review isolation:

- `llm_step` (line 268) stages probabilistic reviewers.
- `run_dets` / `run_dets_with_repair` (lines 428/436) derive and repair structured review state.
- `tests/test_operate_venue_readiness.py` lines 553, 563, 580, 597, and 610 prove precommit timing, reviewer blindness, read-scope restrictions, frozen-hash integrity, and reducer ordering.

`manuscript_review` consumes contract/manuscript/PDF hashes. It must not update section bundles or the authoring canonical tree.

### 3. Dependency and receipt enforcement

`operate/panel_scheduler.py::schedule_next_wave` (line 691) is authoritative. Declared parallel groups are release hints only. Plans must use dependency receipts, forbidden read scopes, hop budgets, and immutable supplements already exercised in `tests/test_panel_scheduler.py` lines 59, 96, 145, 238, 255, 399, 408, and 439.

### 4. Candidate-to-canonical boundary

- Worker and section outputs are candidates written with `operate/artifacts.py::write_artifact` (line 53).
- Scientific hard failures use `GateBlock` / `TargetedGateBlock` (lines 18/22).
- Repair uses `operate/bounded_repair.py::attempt_with_repair` (line 124).
- Effective originals/supplements resolve through `operate/output_versions.py::resolve_effective_output` (line 72).
- Only `tools/manuscript_integrator.py` may create or replace the run-owned canonical LaTeX tree.

### 5. Schema authority

All worker/deterministic products use the existing envelope and central registry:

- add schema keys to `tools/validate_artifact.py::PAYLOAD_SCHEMAS` (line 23);
- validate via `validate_payload` (line 203) before data becomes dependency-visible;
- follow the current Draft 2020-12 closed-object schema family;
- extend `tests/test_validate_artifact.py`, especially the missing-field, additional-property, and unknown-type behaviors at lines 49-108.

### 6. Local-first evidence state machine

The order is fixed: bounded `tools/recall.py` references -> six-axis local coverage report -> named deficit -> query plan -> `tools/paper_search.py::search_many` (line 191). Search output remains a candidate reference. A transport/provider error is a distinct outcome, and no branch downloads PDFs or writes the vault.

### 7. Build truth and path safety

There is no exact existing LaTeX module; follow `01-RESEARCH.md` and `01-AI-SPEC.md`:

- discover tools without a username-specific path;
- invoke a fixed executable with an argv list, no shell expansion;
- compile only inside a run-owned source tree with time/size/process bounds;
- bind source hash, command receipt, log/recorder files, PDF existence and PDF hash;
- derive `BUILT`, `BUILD_FAILED`, or `TOOLCHAIN_MISSING` from observed facts;
- reject `\write18`, shell escape, traversal, external includes, unsafe symlinks/reparse points, and unowned output paths.

### 8. Human-first rendering

Use `tools/director_packet.py::build_packet` (line 353) and mode-specific Markdown renderers. `director-review/00-REVIEW-PACKET.md` is the entry point; overview, coverage, plan, quality, reviewer report, and checklist must link to their immutable evidence and the run-owned LaTeX/PDF products.

### 9. Operated truth mirrors

`operate/modes/__init__.py::REGISTRY` (line 33) is executable truth. `tests/test_operate_wiring.py` and `tests/test_capability_catalog.py` require exact mirrors. Update the Python registry, YAML contract, capability facts, stage labels, and tests in one serialized plan after both recipes are runnable.

## Shared Patterns

Every applicable plan must preserve these cross-cutting patterns:

1. **Machine/database seam:** PhD-Research-OS is read-only; no task may invoke promotion or create a database write path.
2. **Run ownership:** drafts, manifests, assets, TeX, logs, PDFs, and Markdown are run-local scratch products.
3. **Truth before presentation:** deterministic claim/evidence/number/build/permission defects cannot be waived by a worker score.
4. **Usable-first:** presentation/style/completeness advisories do not hide readable outputs; submission readiness stays strict.
5. **Single canonical writer:** section agents and reviewers never modify the integrated source tree.
6. **Blindness and least privilege:** auditors receive only the sources needed for their independent judgment.
7. **Secret-safe persistence:** redact scholarly URLs and exception text before ledger, artifact, TeX, log, or director packet writes.
8. **Cross-platform:** use `pathlib`, argument lists, injected subprocess/transport seams, and Windows/Linux tests.
9. **No new framework:** native JSON Schema, pytest, runstore, scheduler, and operated spine remain authoritative.
10. **TDD for reducers:** cascade, coverage routing, build-state, audit/status, and safety boundary functions are driven RED -> GREEN -> REFACTOR.

## No Analog Found

| Planned concern | Source of truth |
|---|---|
| Paper Design Token cascade and hard/advisory override algebra | `01-AI-SPEC.md` Sections 3-5 and `01-RESEARCH.md` code examples |
| Secure LaTeX build receipt and real PDF truth | `01-RESEARCH.md` “LaTeX Build Contract”, official `latexmk`/MiKTeX behavior, and `01-VALIDATION.md` fake/real compiler cases |
| Manuscript-specific deterministic audit matrix | `01-AI-SPEC.md` evaluation/guardrail sections and `01-VALIDATION.md` requirement-to-test map |

These are intentional new domain modules, not permission to introduce a parallel control plane or new runtime dependency.

## Planner Use

- Every PLAN action that creates/modifies a classified file must name its primary analog and the concrete pattern being copied.
- If implementation must diverge, the action must cite the controlling decision/research contract and explain the compatibility boundary.
- Same-wave plans must not overlap `files_modified`; registry/capability mirrors serialize after both operated recipes and schema contracts exist.
- All 24 locked decisions and all 28 requirement IDs remain mandatory; this map does not reduce scope.
