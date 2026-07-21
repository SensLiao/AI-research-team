---
phase: 01
slug: operated-ai-manuscript-authoring
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-21
---

# Phase 01 - Validation Strategy

> Final feedback contract for 20 plans, 25 executable tasks, and 6 dependency waves. The independent plan checker passed with zero blockers and zero warnings.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2, repository-default discovery |
| **Config file** | none; `tests/test_*.py` convention |
| **Shared fixtures** | `tests/conftest.py` hermetic network/vault defaults |
| **Quick run command** | `python -m pytest tests/test_manuscript_predraft_schemas.py tests/test_manuscript_delivery_schemas.py tests/test_manuscript_schema_contracts.py -q` |
| **Focused integration command** | `python -m pytest tests/test_manuscript_integration.py tests/test_manuscript_renderer.py tests/test_director_packet.py tests/test_operate_manuscript_authoring.py tests/test_operate_manuscript_review.py tests/test_latex_build.py tests/test_manuscript_audit.py tests/test_manuscript_security.py -q` |
| **Full suite command** | `python -m pytest tests -q --junitxml=.planning/evidence/phase-01/full-suite-junit.xml` |
| **Estimated runtime** | focused target: <=30 seconds; the full suite runs at the phase gate with an explicit evidence timeout and cannot be inferred from focused results |

---

## Sampling Rate

- **After every TDD task commit:** run the owning test module plus the nearest affected boundary test.
- **After every plan wave:** run all manuscript-focused modules plus `test_operate_wiring.py`, `test_capability_catalog.py`, `test_panel_scheduler.py`, `test_validate_artifact.py`, `test_scope_guard.py`, `test_scholar_clients.py`, and `test_paper_search.py`.
- **Before `$gsd-verify-work`:** retain green full-suite, AI-eval, security, route, real-Windows-PDF, missing-toolchain, immutable-Docker-Linux, renderer, director-packet, and changed-file evidence at the paths below.
- **Max feedback latency:** 30 seconds for per-task focused tests; long integration/full-suite runs occur at wave and phase gates.

---

## Final Per-Task Verification Map

| Task | Wave | Automated command | Execution status |
|------|------|-------------------|------------------|
| 01-01-T1 | 1 | `python -m pytest tests/test_manuscript_predraft_schemas.py -q` | planned |
| 01-02-T1 | 1 | `python -m pytest tests/test_manuscript_delivery_schemas.py -q` | planned |
| 01-03-T1 | 1 | `python -c "import json,pathlib; r=pathlib.Path('tests/fixtures/manuscript'); d=json.loads((r/'gold_cases.json').read_text(encoding='utf-8')); assert len(d['cases']) == 17; assert all({'input_manifest','expected_tool_calls','expected_bundles','expected_hard_findings','expected_status','rationale'} <= set(x) for x in d['cases'])"` | planned |
| 01-04-T1 | 1 | `python -c "from pathlib import Path; fs=[Path('agents')/n for n in ['manuscript-venue-corpus-scout.md','manuscript-architect.md','manuscript-evidence-steward.md','manuscript-introduction-author.md','manuscript-related-work-author.md']]; assert all(p.is_file() for p in fs)"` | planned |
| 01-05-T1 | 1 | `python -c "from pathlib import Path; ns=['manuscript-methods-author.md','manuscript-results-author.md','manuscript-figure-table-engineer.md','manuscript-integrator.md','manuscript-section-author.md']; assert all((Path('agents')/n).is_file() for n in ns)"` | planned |
| 01-06-T1 | 1 | `python -c "from pathlib import Path; ns=['manuscript-factual-auditor.md','manuscript-citation-auditor.md','manuscript-style-latex-auditor.md','manuscript-submission-packager.md']; assert all((Path('agents')/n).is_file() for n in ns)"` | planned |
| 01-06-T2 | 1 | `python -c "from pathlib import Path; ns=['manuscript-domain-contribution-reviewer.md','manuscript-methods-reproducibility-reviewer.md','manuscript-figure-table-reviewer.md']; assert all((Path('agents')/n).is_file() for n in ns)"` | planned |
| 01-07-T1 | 1 | `python -m pytest tests/test_scholar_clients.py tests/test_paper_search.py -q` | planned |
| 01-08-T1 | 1 | `python -m pytest tests/test_manuscript_security.py tests/test_scope_guard.py tests/test_path_boundaries.py -q` | planned |
| 01-09-T1 | 2 | `python -m pytest tests/test_manuscript_schema_contracts.py tests/test_validate_artifact.py -q` | planned |
| 01-10-T1 | 2 | `python -m pytest tests/test_agent_connectivity.py tests/test_graph_spec.py -q` | planned |
| 01-10-T2 | 2 | `python -m pytest tests/test_agent_connectivity.py tests/test_capability_catalog.py tests/test_graph_spec.py -q` | planned |
| 01-11-T1 | 3 | `python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_schema_contracts.py -q` | planned |
| 01-12-T1 | 3 | `python -m pytest tests/test_manuscript_literature.py tests/test_paper_search.py tests/test_scholar_clients.py -q` | planned |
| 01-13-T1 | 3 | `python -m pytest tests/test_manuscript_integration.py tests/test_manuscript_security.py tests/test_manuscript_schema_contracts.py -q` | planned |
| 01-14-T1 | 3 | `python -m pytest tests/test_manuscript_audit.py tests/test_manuscript_security.py tests/test_execution_receipt_import.py -q` | planned |
| 01-15-T1 | 3 | `python -m pytest tests/test_latex_build.py tests/test_manuscript_security.py -q` | planned |
| 01-16-T1 | 3 | `python -m pytest tests/test_manuscript_renderer.py -q` | planned |
| 01-16-T2 | 3 | `python -m pytest tests/test_director_packet.py tests/test_manuscript_renderer.py -q` | planned |
| 01-17-T1 | 4 | `python -m pytest tests/test_operate_manuscript_authoring.py -q` | planned |
| 01-18-T1 | 4 | `python -m pytest tests/test_operate_manuscript_review.py -q` | planned |
| 01-19-T1 | 5 | `python -m pytest tests/test_operate_manuscript_authoring.py tests/test_operate_manuscript_review.py tests/test_operate_wiring.py tests/test_operate_wave1_modes.py -q` | planned |
| 01-19-T2 | 5 | `python -m pytest tests/test_agent_connectivity.py tests/test_capability_catalog.py tests/test_operate_wiring.py -q` | planned |
| 01-20-T1 | 6 | `python -m pytest tests/test_manuscript_environment.py tests/test_manuscript_completion.py tests/test_capability_catalog.py -q --junitxml=.planning/evidence/phase-01/completion-junit.xml` | planned |
| 01-20-T2 | 6 | `python -m pytest tests/test_manuscript_completion.py -q --junitxml=.planning/evidence/phase-01/director-route-junit.xml` | planned |

The map has exactly 25 task rows. Every row names its final plan task and an automated check; no task relies on a watch process or a manual-only pass condition.

---

## Required 17-Case Hermetic Set

1. Local corpus is sufficient, emits a frozen coverage artifact, and makes zero scholarly network calls.
2. A schema-valid named deficit authorizes only its targeted query plan through the existing search port.
3. All attempted providers fail and the reducer emits `PROVIDER_FAILURE`, never evidence absence.
4. A provider returns partial or unresolved zero-result data and the reducer emits `PARTIAL_OR_UNRESOLVED_ZERO_RESULT`.
5. A complete frozen query plan and trace exhaust every attempt with valid empty responses and emit `NO_EVIDENCE_AFTER_VALID_SEARCH`.
6. Contract precedence is deterministic and official hard rules reject a conflicting override.
7. Changing an upstream frozen hash invalidates descendants while leaving unrelated artifacts reusable.
8. Each frozen `required_sections` entry for empirical, theory, dataset, survey, and system papers maps to exactly one specialized or parameterized section bundle.
9. The integrator rejects a missing or duplicate required section and never authors replacement prose.
10. Format repair is bounded to two attempts; unauthorized or orphan dependencies fail closed.
11. An unsupported load-bearing claim prevents submission readiness.
12. Citation identity or entailment mismatch prevents submission readiness and remains visible in the readable packet.
13. Numeric/receipt mismatch, including a false execution claim, fails the scientific truth gate.
14. Traversal, symlink/reparse, Unicode-space escape, or mutation of a director-owned asset is rejected without changing the asset hash.
15. With frozen `requires_pdf=true`, driver readiness is probed under the exact sanitized build environment: healthy latexmk may compile, while latexmk present without discoverable Perl must select the healthy direct pdflatex plus bibliography fallback; either path emits selected-driver executable/argv evidence and a sanitized current-source/PDF-hash-bound `COMPILED` receipt. With `requires_pdf=false`, PDF absence alone is not a readiness blocker.
16. The isolated missing-toolchain branch emits `TOOLCHAIN_MISSING`, no PDF claim, readable daily output, and `submission_ready=false` when PDF is required.
17. End-to-end authoring emits the full human-first product set, while at least two blind reviewer receipts consume the frozen manuscript hash, cannot mutate the authoring run, retain all reconciled findings, and emit a separate review packet.

---

## Planned Test Artifacts

- [ ] Plan 01-01 creates `tests/test_manuscript_predraft_schemas.py` for PREP-01 through PREP-04 and the frozen `requires_pdf`/retrieval-state contract.
- [ ] Plan 01-02 creates `tests/test_manuscript_delivery_schemas.py` for delivery, review, readable-status, and submission-readiness separation.
- [ ] Plan 01-03 creates the exact 17-case fixture set under `tests/fixtures/manuscript/`.
- [ ] Plans 01-07 and 01-08 extend scholarly client/search and path/security tests for URL, log, artifact, TeX, vault, and boundary controls.
- [ ] Plan 01-09 creates `tests/test_manuscript_schema_contracts.py` and registers every new schema centrally.
- [ ] Plans 01-11 through 01-16 create contract, literature, integration, audit, LaTeX, renderer, and director-packet suites; Plan 01-15 includes readiness/build sanitized-environment identity and latexmk-present/Perl-unavailable direct-fallback regressions.
- [ ] Plans 01-17 and 01-18 create distinct operated authoring/review suites with adaptive-section and six-capability reviewer coverage.
- [ ] Plan 01-20 creates environment/completion suites and executable route, AI-eval, security, Windows, Docker Linux, and changed-file evidence gates.
- [ ] No plan installs another test framework, schema validator, scholarly provider, downloader, or transport package.

`wave_0_complete` stays `false` until execution creates these files and their RED checks have been observed. Planning completeness does not imply test execution.

---

## Executable Release Gates

All commands run from `research_agent_teams/` unless a command explicitly changes directory. Any nonzero exit, absent evidence file, malformed evidence, threshold miss, or skipped mandatory detected-host build fails the gate.

### 1. Current Windows MiKTeX/latexmk real build plus always-run missing branch

```powershell
New-Item -ItemType Directory -Force '.planning/evidence/phase-01/windows' | Out-Null
$phasePerlCommand = Get-Command perl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $phasePerlCommand) { $env:RAT_LATEX_DRIVER_RUNTIME_CANDIDATES = Split-Path -Parent $phasePerlCommand.Source } else { Remove-Item Env:RAT_LATEX_DRIVER_RUNTIME_CANDIDATES -ErrorAction SilentlyContinue }
$env:RAT_REQUIRE_REAL_LATEX = '1'
$env:RAT_MANUSCRIPT_EVIDENCE_DIR = (Resolve-Path '.planning/evidence/phase-01/windows').Path
python -m pytest tests/test_latex_build.py::test_driver_readiness_uses_build_sanitized_environment tests/test_latex_build.py::test_latexmk_present_without_perl_falls_back_to_direct_pipeline tests/test_latex_build.py::test_real_latex_build_emits_sanitized_receipt tests/test_latex_build.py::test_toolchain_missing_is_truthful tests/test_manuscript_environment.py -q --junitxml=.planning/evidence/phase-01/windows-targeted.xml
if ($LASTEXITCODE -ne 0) { throw 'Windows driver-readiness, fallback, real-build, or missing-toolchain gate failed' }
$phaseBuildReceiptRaw = Get-Content -Raw '.planning/evidence/phase-01/windows/real-build-receipt.json'
if ($phaseBuildReceiptRaw -match '(?i)[A-Z]:\\Users\\') { throw 'Raw username-bearing path persisted in build receipt' }
$phaseBuildReceipt = $phaseBuildReceiptRaw | ConvertFrom-Json
$phaseSelectedDriver = [IO.Path]::GetFileName([string]$phaseBuildReceipt.executable)
if ($phaseSelectedDriver -notmatch '^(latexmk|pdflatex)(\.exe)?$' -or -not $phaseBuildReceipt.argv) { throw 'Selected-driver executable/argv evidence is absent' }
[xml]$phaseWindowsJUnit = Get-Content -Raw '.planning/evidence/phase-01/windows-targeted.xml'
$phaseWindowsCases = @($phaseWindowsJUnit.SelectNodes('//testcase') | ForEach-Object { $_.name })
if ('test_driver_readiness_uses_build_sanitized_environment' -notin $phaseWindowsCases -or 'test_latexmk_present_without_perl_falls_back_to_direct_pipeline' -notin $phaseWindowsCases) { throw 'Driver-readiness or direct-fallback testcase evidence is absent' }
```

Required evidence: `windows-targeted.xml` has zero failures/errors/skips and contains the named sanitized-environment identity plus latexmk-without-Perl fallback testcases. `windows/real-build-receipt.json` is `COMPILED`, binds current source and PDF hashes, and records sanitized selected executable/version/argv/OS/return-code/log data without a raw user/runtime path. The isolated test also proves `TOOLCHAIN_MISSING` with no PDF claim. Because this host has a usable TeX pipeline, failure to select either a ready latexmk driver or the healthy direct fallback is failure.

### 2. Immutable cached Docker Desktop linux/amd64 target

```powershell
$phaseImage = 'python@sha256:cb1503943096ba7e3713bab3a59c4fa493c1799949c1f16dedfc2a7ff80754da'
New-Item -ItemType Directory -Force '.planning/evidence/phase-01/linux' | Out-Null
$dockerPlatform = docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
if ($LASTEXITCODE -ne 0 -or $dockerPlatform.Trim() -ne 'linux/amd64') { throw 'Docker Desktop linux/amd64 is unavailable' }
$dockerPlatform | Set-Content -Encoding utf8 '.planning/evidence/phase-01/linux/docker-platform.txt'
$dockerDigest = docker image inspect $phaseImage --format '{{index .RepoDigests 0}}'
if ($LASTEXITCODE -ne 0 -or $dockerDigest -notmatch '@sha256:cb1503943096ba7e3713bab3a59c4fa493c1799949c1f16dedfc2a7ff80754da$') { throw 'Required immutable cached image is unavailable or mismatched' }
$dockerDigest | Set-Content -Encoding utf8 '.planning/evidence/phase-01/linux/docker-image.txt'
$machineRoot = (Get-Location).Path
$linuxEvidence = (Resolve-Path '.planning/evidence/phase-01/linux').Path
docker run --rm --platform linux/amd64 --mount "type=bind,source=$machineRoot,target=/workspace/research_agent_teams,readonly" --mount "type=bind,source=$linuxEvidence,target=/evidence" $phaseImage sh -lc "python -m pip install --disable-pip-version-check --no-cache-dir -r /workspace/research_agent_teams/requirements-dev.txt && cd /tmp && PYTHONPATH=/workspace python -m pytest -p no:cacheprovider /workspace/research_agent_teams/tests/test_manuscript_environment.py /workspace/research_agent_teams/tests/test_manuscript_security.py /workspace/research_agent_teams/tests/test_manuscript_literature.py /workspace/research_agent_teams/tests/test_scholar_clients.py /workspace/research_agent_teams/tests/test_latex_build.py -q --basetemp=/tmp/pytest --junitxml=/evidence/targeted.xml"
if ($LASTEXITCODE -ne 0) { throw 'Docker linux/amd64 targeted gate failed' }
```

The repository bind is read-only, only pinned existing distributions from `requirements-dev.txt` are installed, pytest cache is disabled, and `/evidence` is the sole writable bind. If Docker, the cached digest, linux/amd64, dependency installation, or the targeted suite is unavailable, PLAT-01 remains unverified; no Linux verification claim is permitted.

### 3. AI eval

```powershell
Push-Location ..
python -m research_agent_teams.tools.rat_eval_harness --out research_agent_teams/.planning/evidence/phase-01/ai-eval-scorecard.json --no-manual
$phaseEvalExit = $LASTEXITCODE
Pop-Location
if ($phaseEvalExit -ne 0) { throw 'AI eval process failed' }
$phaseScore = Get-Content -Raw '.planning/evidence/phase-01/ai-eval-scorecard.json' | ConvertFrom-Json
if ([int]$phaseScore.required_machine_failures -ne 0 -or [int]$phaseScore.fail -ne 0) { throw 'AI eval thresholds failed' }
```

### 4. Security and route behavior

```powershell
python -m pytest tests/test_manuscript_security.py tests/test_scholar_clients.py tests/test_scope_guard.py tests/test_operate_manuscript_authoring.py tests/test_operate_manuscript_review.py -q --junitxml=.planning/evidence/phase-01/security-junit.xml
if ($LASTEXITCODE -ne 0) { throw 'Security gate failed' }
python -m pytest tests/test_manuscript_completion.py -q --junitxml=.planning/evidence/phase-01/director-route-junit.xml
if ($LASTEXITCODE -ne 0) { throw 'Director route gate failed' }
```

The route suite must execute both exact mode routes, find no `manuscript_review_pack` identifier, observe zero scholarly transport calls before a schema-valid named deficit, and observe only existing `paper_search` calls after authorization. The security suite must leave every URL, exception, log, persisted artifact, and director-facing packet sentinel-free.

### 5. Completion, renderer, director packet, and full suite

```powershell
python -m pytest tests/test_manuscript_completion.py tests/test_capability_catalog.py tests/test_operate_wiring.py tests/test_manuscript_integration.py tests/test_manuscript_renderer.py tests/test_director_packet.py -q --junitxml=.planning/evidence/phase-01/completion-junit.xml
if ($LASTEXITCODE -ne 0) { throw 'Completion/renderer gate failed' }
python -m pytest tests -q --junitxml=.planning/evidence/phase-01/full-suite-junit.xml
if ($LASTEXITCODE -ne 0) { throw 'Full suite gate failed' }
```

### 6. Machine-repository versus workspace-interface changed-file evidence

```powershell
git status --short -- . | Set-Content -Encoding utf8 '.planning/evidence/phase-01/machine-changed-files.txt'
$workspaceInterfaces = @('../AGENTS.md','../.agents/skills/research-orchestrator/SKILL.md','../.agents/skills/source-command-run-mode/SKILL.md','../.agents/skills/source-command-start-research/SKILL.md')
$workspaceInterfaceEvidence = foreach ($phasePath in $workspaceInterfaces) { $phaseItem = Get-Item -LiteralPath $phasePath; [pscustomobject]@{ scope='same-workspace-interface-outside-machine-git'; path=$phaseItem.FullName; sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $phaseItem.FullName).Hash.ToLowerInvariant() } }
$workspaceInterfaceEvidence | ConvertTo-Json | Set-Content -Encoding utf8 '.planning/evidence/phase-01/workspace-interface-files.json'
```

`README.md`, `PLATFORM-FACTS.md`, tests, manifests, runtime, and registry files are machine-repository evidence. The four `../` interfaces are reported separately and must never be represented as machine-repository commit evidence.

---

## Release Thresholds

| Gate | Required threshold |
|------|--------------------|
| Windows targeted JUnit | zero failures, zero errors, no skipped mandatory real-build test |
| Driver readiness/fallback | readiness probe and build use the same sanitized environment; selected executable/argv exists; latexmk-present/Perl-unavailable testcase proves direct pdflatex plus bibliography fallback |
| Real-build receipt | `COMPILED`; current source/PDF hashes; sanitized provenance; file exists |
| Missing-toolchain case | `TOOLCHAIN_MISSING`; no PDF claim; always executed |
| Docker target | exact immutable digest, `linux/amd64`, zero targeted JUnit failures/errors |
| AI eval | `required_machine_failures=0` and `fail=0` |
| Security JUnit | zero failures/errors and no sentinel leakage in three persistence layers |
| Director-route JUnit | exact two modes, obsolete id absent, zero network before named deficit |
| Completion/renderer/full suite | every JUnit file exists with zero failures/errors |
| Review panel | all six capabilities covered; at least two distinct blind authorization receipts; all findings retained through reconciliation |

---

## Real Local Build Evidence Available to Execution

On 2026-07-21 this Windows host produced a real BibTeX-resolved PDF with MiKTeX 25.12, Strawberry Perl 5.42.2.1, and latexmk 4.88 using `latexmk -gg -pdf -interaction=nonstopmode -halt-on-error -file-line-error main.tex`.

The smoke PDF was 35,362 bytes, SHA-256 `19b1639769b2b0e8d79c85fae1a74cab8b5aa0429de69755a9927d7e1d0eb13b`, the final log had zero unresolved-reference warnings, and `chktex -q` exited 0. This proves only that the host toolchain was detected during planning; execution must resolve/inject any Perl candidate without a username literal, probe the selected driver under the actual sanitized build environment, compile the current phase source into fresh selected-driver evidence, prove latexmk-to-direct fallback, and separately prove the missing-toolchain branch.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Six-capability scientific review usefulness | AUDT-01, DELV-02 | Expert usefulness cannot be reduced to deterministic syntax checks | Confirm domain contribution, methods/reproducibility, figure/table, factual, citation, and venue/style/LaTeX coverage; inspect at least two distinct blind authorization receipts and verify reconciliation retains blocking, minority, and non-blocking findings without a fixed global reviewer count. |
| Current official venue policy interpretation | PREP-01 | Official rules can change and contain venue-specific judgment | Director or venue-compliance reviewer checks frozen source URLs/retrieval date, `requires_pdf`, anonymity, privacy, style, and LaTeX policy before any submission-ready claim. |
| Final submission decision | DELV-02 | Director-owned commitment | Director reviews readable packet, current-source PDF when required, checklist, remaining risks, and independent review, then decides whether to submit; the machine never submits autonomously. |

---

## Validation Sign-Off

- [x] Final map contains exactly 20 plans, 25 tasks, and waves 1 through 6.
- [x] Every task has an `<automated>` verification command.
- [x] Sampling continuity has no three consecutive tasks without automated verification.
- [x] The planned test artifacts cover every required contract, integration, renderer, operated, security, and completion boundary.
- [x] The required hermetic set is named and contains exactly 17 cases.
- [x] No watch-mode flags are used.
- [x] Focused feedback targets <=30 seconds; long suites are explicit wave/phase gates.
- [x] Windows same-sanitized-environment driver readiness, username-independent Perl injection, latexmk-to-direct fallback, real-build, always-run missing-toolchain, immutable Docker Linux, AI-eval, security, route, completion, and full-suite gates have exact evidence paths and thresholds.
- [x] Plan checker rerun passed this revision with zero blockers and zero warnings; `nyquist_compliant` is `true`.

**Approval:** independent checker PASS on 2026-07-21.
