---
last_mapped_commit: "165d62a6deaa4cd57eee18352d5a48aab626c49d"
working_tree_state: dirty
analysis_date: "2026-07-21"
focus: concerns
---

# Codebase Concerns

**Analysis Date:** 2026-07-21

## Tech Debt

**Unpinned Python environment:**
- Issue: The repository has no committed `pyproject.toml`, requirements file, lockfile, or pytest configuration, while runtime code imports `jsonschema`, `yaml`, optional `paperqa`, optional PyMuPDF/`fitz`, and lazy `paramiko` in `tools/validate_artifact.py`, `tests/conftest.py`, `tools/fulltext_qa.py`, and `execute/runner.py`.
- Files: `README.md`, `tools/validate_artifact.py`, `tools/fulltext_qa.py`, `execute/runner.py`, `tests/conftest.py`
- Impact: A clean machine cannot reconstruct the tested dependency versions, and PDF/SSH behavior can silently differ by environment.
- Fix approach: Add a supported Python version, direct dependency manifest, optional extras for PDF/SSH, and a lockfile; keep optional dependency tests explicit in `tests/test_citation_attribution.py`.

**Oversized orchestration modules:**
- Issue: Core files combine dispatch, validation, repair, rendering, and policy logic. `operate/modes/read_paper_deep.py` is over 2,300 lines; `tools/schema_normalizer.py` is over 1,400; `operate/cli.py` is about 960; several other operated modes exceed 800 lines.
- Files: `operate/modes/read_paper_deep.py`, `tools/schema_normalizer.py`, `operate/cli.py`, `operate/modes/new_direction.py`, `operate/modes/evidence_deep.py`
- Impact: Small contract changes have a large review surface and make targeted ownership, testing, and safe reuse harder.
- Fix approach: Split stable contracts, worker prompts, deterministic checks, renderers, and CLI adapters into focused modules while retaining mode-level regression tests in `tests/test_operate_read_paper_deep.py` and `tests/test_schema_normalizer.py`.

**Central schema registry pressure:**
- Issue: `PAYLOAD_SCHEMAS` and schema loading are centralized in one growing file, and each validation call reopens and reparses schema JSON.
- Files: `tools/validate_artifact.py`, `schemas/`, `tests/test_validate_artifact.py`
- Impact: Registry merge conflicts increase, and repeated validation performs avoidable filesystem/JSON work across a 3,250-test suite.
- Fix approach: Preserve one authoritative registry but generate or compose it from typed domain sections; cache immutable loaded schemas and compiled validators with tests proving identical errors.

**Dirty-worktree reproducibility risk:**
- Issue: The mapped worktree contains 120 porcelain entries: 107 modified tracked files and 13 untracked files, while HEAD remains `165d62a6deaa4cd57eee18352d5a48aab626c49d`.
- Files: `.env.example`, `PLATFORM-FACTS.md`, `operate/`, `orchestrator/`, `schemas/`, `tests/`, `tools/`, `workspace/audit_log.jsonl`, `workspace/lease_registry.jsonl`
- Impact: HEAD alone cannot reproduce the behavior analyzed here; unrelated changes can be committed together, and mutable workspace ledgers can be added accidentally.
- Fix approach: Partition changes into reviewable commits, decide whether `workspace/*.jsonl` is durable or ignored runtime state, and require a clean-tree or recorded-diff hash before reproducibility-sensitive execution receipts.

## Known Bugs

**Scholar-client errors can expose sensitive URL parameters:**
- Symptoms: HTTP, network, and malformed-response exceptions include the full request URL. OpenAlex puts `api_key` and `mailto` in that URL, and `paper_search.search()` persists the exception text in `source_errors`.
- Files: `tools/scholar_clients.py`, `tools/paper_search.py`, `tests/test_scholar_clients.py`, `tests/test_paper_search.py`
- Trigger: Set `RAT_OPENALEX_API_KEY` or `RAT_CONTACT_MAIL`, then receive an HTTP/network failure or malformed OpenAlex response through `default_transport()` or `_fetch_parse()`.
- Workaround: Avoid sharing raw `source_errors` from keyed requests; the durable fix is URL sanitization before exception construction and serialization.

## Security Considerations

**Secret redaction at scholarly API boundaries:**
- Risk: An OpenAlex API key or contact address can enter a run artifact, CLI output, or downstream diagnostic because error messages retain query strings.
- Files: `tools/scholar_clients.py`, `tools/paper_search.py`, `operate/cli.py`
- Current mitigation: API keys are not placed in normalized publication records, and run scratch is excluded by `.gitignore`; this does not redact exception text.
- Recommendations: Centralize a URL sanitizer that removes at least `api_key`, `mailto`, and future token-like parameters; store provider, host/path, status, and an opaque request id only. Add a sentinel-secret regression in `tests/test_scholar_clients.py` and a persistence assertion in `tests/test_paper_search.py`.

**Trust-boundary code is strong but dispersed:**
- Risk: Vault, live SSH, promotion, and full-text fences depend on several independent implementations staying aligned.
- Files: `tools/fulltext_qa.py`, `tools/paper_search.py`, `tools/document_promotion.py`, `execute/runner.py`, `tools/scope_guard.py`
- Current mitigation: Default-deny authorization, vault path fences, host-key verification, schema validation, and adversarial tests exist in `tests/test_execute.py`, `tests/test_scope_guard.py`, and `tests/test_document_promotion.py`.
- Recommendations: Keep boundary tests mandatory and factor shared path/redaction primitives rather than adding new substring checks in individual modules.

## Performance Bottlenecks

**Full test-suite feedback latency:**
- Problem: Pytest collects 3,250 tests; the documented all-suite command did not produce a result within a 120-second mapping ceiling.
- Files: `tests/`, `README.md`, `tests/conftest.py`
- Cause: Broad schema matrices and operated-mode integration suites run together without committed markers, shards, or parallel-run configuration.
- Improvement path: Define fast/unit, contract, mode-integration, and slow markers; run deterministic shards in CI and keep one full serial gate for shared-state assumptions. Do not lower assertions or skip security gates.

**Multi-query scholarly search is serial across queries:**
- Problem: Providers are parallelized within one query, but `search_many()` loops over query plans sequentially; each provider transport uses a 20-second timeout.
- Files: `tools/paper_search.py`, `tools/scholar_clients.py`
- Cause: `ThreadPoolExecutor` is scoped to a single `search()` call, while the outer query loop has no bounded concurrency, cache, retry, or backoff policy.
- Improvement path: Add rate-aware bounded query concurrency or a request cache with deterministic merge order, explicit provider quotas, redacted errors, and offline tests in `tests/test_paper_search.py`.

**Repeated schema compilation:**
- Problem: Every validation call reads JSON and constructs a `Draft202012Validator`.
- Files: `tools/validate_artifact.py`, `schemas/`
- Cause: `_load_schema()` and `_errors()` do not cache schemas or validators.
- Improvement path: Cache by schema filename and add invalidation-free tests because committed schemas are immutable during a process.

## Fragile Areas

**Twenty-worker paper-reading mode:**
- Files: `operate/modes/read_paper_deep.py`, `operate/panel_scheduler.py`, `tests/test_operate_read_paper_deep.py`
- Why fragile: A large sparse dependency graph, optional specialist rules, incremental supplements, truth gates, and Markdown delivery contracts meet in one mode.
- Safe modification: Change one contract layer at a time, preserve immutable worker bundles, and run the dedicated mode, schema, citation, and director-packet tests.
- Test coverage: Extensive local coverage exists, but the module size and evolving working tree keep regression risk high.

**Mirrored mode and agent registries:**
- Files: `operate/modes/__init__.py`, `orchestrator/mode_registry.yaml`, `orchestrator/graph.yaml`, `orchestrator/roster.yaml`, `tests/test_operate_wiring.py`, `tests/test_agent_connectivity.py`
- Why fragile: A worker or mode must agree across multiple declarative and executable registries.
- Safe modification: Update all mirrors in one change and run connectivity, capability-catalog, and operate-wiring tests before changing product status.
- Test coverage: Mirror tests are strong; failures still have a broad repair surface because ownership is distributed.

**Schema normalization truth boundary:**
- Files: `tools/schema_normalizer.py`, `tools/validate_artifact.py`, `tests/test_schema_normalizer.py`
- Why fragile: Representation-only changes and heuristic scientific classifications coexist, so an apparently harmless normalizer can alter truth-gate inputs.
- Safe modification: Preserve original bundles, record every transformation, keep heuristic rules explicit, and require worker confirmation for scientific classifications.
- Test coverage: A large regression suite exists, but the implementation remains concentrated in a single large module.

## Scaling Limits

**Local-first literature boundary:**
- Current capacity: Metadata search runs against arXiv, OpenAlex, Crossref, and Semantic Scholar, while deep evidence accepts complete local PDF, HTML-body, or UTF-8 snapshots.
- Limit: `fulltext-pre` requires the operator to supply local documents with `--doc`; `evidence_deep` blocks when critical local sources are not frozen and bound.
- Scaling path: Preserve local-first as the safe default, but add an explicit, governed open-access acquisition lane with licensing, MIME/size, hash, and run-scratch checks.
- Files: `tools/paper_search.py`, `operate/cli.py`, `tools/fulltext_qa.py`, `operate/modes/evidence_deep.py`

**OpenAlex no-download boundary:**
- Current capacity: `tools/scholar_clients.py` normalizes OpenAlex title, year, DOI, venue, authors, URL, and citation count for metadata triage.
- Limit: The OpenAlex client does not resolve or download full text, and `tools/paper_search.py` deliberately emits by-reference evidence rows with `claim_support="none"`.
- Scaling path: If automatic acquisition is desired, implement it as a separate open-access downloader rather than silently expanding the metadata client; require hash-bound scratch storage and never bypass paywalls.
- Files: `tools/scholar_clients.py`, `tools/paper_search.py`, `skills/research-lookup.md`

## Dependencies at Risk

**Optional PDF and SSH libraries are unpinned:**
- Risk: `paperqa`, PyMuPDF/`fitz`, and `paramiko` availability and behavior depend on the local Python environment.
- Impact: Full-text extraction can degrade to unavailable, PDF tests can skip, and live server support cannot be reproduced from the repository alone.
- Migration plan: Add pinned optional extras and environment verification; keep lazy imports and honest degradation in `tools/fulltext_qa.py` and `execute/runner.py`.
- Files: `tools/fulltext_qa.py`, `execute/runner.py`, `tests/test_citation_attribution.py`, `README.md`

## Missing Critical Features

**Operated manuscript-generation pipeline:**
- Problem: `manuscript_review_pack` is `registry_routable_spec_only`; it has no staged manuscript intake, independent operated panel, deterministic renderer, or `operate/modes/*.py` recipe. Existing workers review or polish inputs rather than generate an end-to-end submission artifact.
- Blocks: The machine cannot honestly claim one-button manuscript creation or a submission-ready manuscript pack.
- Files: `orchestrator/mode_registry.yaml`, `operate/modes/__init__.py`, `PLATFORM-FACTS.md`, `tests/test_capability_catalog.py`

**Native LaTeX/PDF production chain:**
- Problem: Active code and tests contain no `latexmk`, `pdflatex`, `xelatex`, `lualatex`, `tectonic`, Pandoc, or Quarto render invocation. Literature-review skill notes explicitly strip LaTeX/PDF generation.
- Blocks: Markdown outputs cannot be compiled natively into a venue-ready `.tex`/PDF package with bibliography, figures, and deterministic build receipts.
- Files: `skills/literature-review.md`, `skills/hypothesis-generation.md`, `orchestrator/mode_registry.yaml`, `operate/modes/__init__.py`

**Automatic lawful full-text acquisition:**
- Problem: Live literature lookup stops at metadata and by-reference evidence; deep reads require locally supplied documents.
- Blocks: Large evidence panels cannot progress unattended from an OpenAlex hit to a complete source snapshot.
- Files: `tools/scholar_clients.py`, `tools/paper_search.py`, `operate/cli.py`, `operate/modes/evidence_deep.py`

## Test Coverage Gaps

**Scholar URL redaction:**
- What's not tested: No test places a sentinel OpenAlex key/contact into a failing request and asserts that exception text and persisted `source_errors` are redacted.
- Files: `tests/test_scholar_clients.py`, `tests/test_paper_search.py`, `tools/scholar_clients.py`
- Risk: Credential or contact leakage can regress unnoticed even while functional lookup tests pass.
- Priority: High

**Manuscript and PDF build products:**
- What's not tested: No operated manuscript recipe, `.tex` contract, bibliography build, PDF compiler, or reproducible build receipt exists to test.
- Files: `orchestrator/mode_registry.yaml`, `operate/modes/__init__.py`, `tests/test_capability_catalog.py`
- Risk: Review-pack readiness may be mistaken for manuscript-generation capability.
- Priority: High

**Real external execution:**
- What's not tested: Default tests intentionally avoid live scholarly APIs, the real vault, SSH, and GPU execution.
- Files: `tests/conftest.py`, `tests/test_execute.py`, `PLATFORM-FACTS.md`
- Risk: Provider drift, server configuration, and real executor integration remain outside hermetic regression evidence.
- Priority: Medium

**Coverage and full-suite release signal:**
- What's not tested: No coverage threshold or committed CI configuration is detected, and the all-suite run has no result under the mapping time ceiling.
- Files: `README.md`, `tests/`, `.gitignore`
- Risk: A targeted green suite can coexist with unmeasured modules or slow regressions.
- Priority: Medium

---

*Concerns audit: 2026-07-21*
