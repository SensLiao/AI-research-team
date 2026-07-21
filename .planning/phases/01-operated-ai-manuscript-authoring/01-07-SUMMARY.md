---
phase: 01-operated-ai-manuscript-authoring
plan: "07"
subsystem: scholarly-retrieval-security
tags: [url-redaction, typed-failures, openalex, metadata-only, tdd]
requires: []
provides:
  - Query-free scholarly request identities and centrally sanitized lookup exceptions
  - Fail-closed OpenAlex query-key handling before transport
  - Independent source_errors redaction at collection and persistence boundaries
  - Regression proof that provider failure remains distinct from absence and partial success
affects: [scholarly-retrieval, evidence-search, durable-run-artifacts, citation-verification]
tech-stack:
  added: []
  patterns: [sanitize-at-construction-and-sinks, provider-isolated-failure, query-key-fail-closed]
key-files:
  created: []
  modified:
    - tools/scholar_clients.py
    - tools/paper_search.py
    - tests/test_scholar_clients.py
    - tests/test_paper_search.py
key-decisions:
  - "Strip every scholarly URL query and fragment before an exception can become durable while retaining scheme, host, path, provider, and status diagnostics."
  - "Reject a configured OpenAlex API key before transport because the supported authentication channel is query-only; continue all other providers independently."
  - "Keep contact identity exclusively in User-Agent and preserve Semantic Scholar key authentication exclusively in its existing header."
  - "Redact source_errors independently when collected and immediately before bundle serialization."
patterns-established:
  - "Three-boundary redaction: exception construction, returned provider outcomes, and serialized artifacts each sanitize independently."
  - "Failure is not absence: 404 lookup semantics remain None while transport, HTTP, and parse faults remain typed ScholarLookupError outcomes."
requirements-completed: [EVID-02, EVID-03, SAFE-02, VERI-02, VERI-04]
coverage:
  - id: D1
    description: Scholarly exception messages retain safe provider/host/path/status identity but cannot retain URL query values or configured credential/contact values.
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: tests/test_scholar_clients.py#test_scholar_errors_keep_safe_request_identity_but_strip_query_values
        status: pass
      - kind: unit
        ref: tests/test_scholar_clients.py#test_parse_failure_redacts_request_query
        status: pass
    human_judgment: false
  - id: D2
    description: A configured OpenAlex query key fails before transport without suppressing successful results from other metadata providers.
    requirement: EVID-03
    verification:
      - kind: integration
        ref: tests/test_paper_search.py#test_openalex_key_failure_does_not_suppress_other_provider_results
        status: pass
    human_judgment: false
  - id: D3
    description: Returned and persisted source_errors are independently sanitized even when supplied a raw tainted diagnostic at each boundary.
    requirement: VERI-02
    verification:
      - kind: integration
        ref: tests/test_paper_search.py#test_source_errors_are_redacted_when_collected_and_persisted
        status: pass
    human_judgment: false
  - id: D4
    description: OpenAlex remains metadata-only with claim_support none and no content, PDF, or download surface.
    requirement: EVID-02
    verification:
      - kind: unit
        ref: tests/test_paper_search.py#test_openalex_results_remain_metadata_only
        status: pass
    human_judgment: false
duration: 14min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 07: Scholarly Failure Redaction Summary

**Three-layer scholarly error redaction now strips secret-bearing URL data, fails closed on OpenAlex query keys, and preserves partial results plus metadata-only evidence semantics.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-21T10:31:11Z
- **Completed:** 2026-07-21T10:45:14Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments

- Added `sanitize_scholar_url()` and `sanitize_scholar_error()` so HTTP, network, parse, and injected provider failures preserve safe request identity without query values, credentials, or contact sentinels.
- Made OpenAlex reject a configured `RAT_OPENALEX_API_KEY` before transport, removed contact identity from its URLs, and kept contact only in `User-Agent`; Semantic Scholar header authentication is unchanged.
- Redacted `source_errors` when provider outcomes are collected, when multi-query outcomes are merged, and again before a search bundle is serialized.
- Preserved 404-as-`None`, typed failure-versus-absence semantics, successful results from unaffected providers, and OpenAlex metadata-only records with `claim_support: none`.

## Task Commits

1. **RED: Add failing scholarly redaction regressions** - `137edca`
2. **GREEN: Redact scholarly provider failures** - `f989ed2`

## TDD Gate Compliance

- **RED:** Seven focused regressions produced six expected failures and one already-passing metadata-boundary assertion before implementation.
- **GREEN:** `python -m pytest tests/test_scholar_clients.py tests/test_paper_search.py -q` passed all 29 tests.
- Git history contains the required `test(01-07)` commit before the `feat(01-07)` commit.

## Files Modified

- `tools/scholar_clients.py` - central URL/error sanitizers and pre-transport OpenAlex key rejection.
- `tools/paper_search.py` - defense-in-depth redaction for returned, merged, and serialized provider errors.
- `tests/test_scholar_clients.py` - URL, key/contact, HTTP/network/parse, and transport-call regressions.
- `tests/test_paper_search.py` - provider-isolation, persistence-redaction, and metadata-only regressions.

## Decisions Made

- Redaction removes the entire query and fragment rather than trying to maintain an allowlist of safe query parameters; stable scheme/host/path and status diagnostics remain available.
- The sanitizer also removes configured OpenAlex, Semantic Scholar, and contact values plus common token, credential, secret, mail, and contact assignments.
- OpenAlex key configuration is an explicit typed provider failure, never silent unauthenticated success and never evidence absence.
- Serialization creates a fresh sanitized `source_errors` mapping and does not mutate the caller's result object.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected stale SDK progress rendering**

- **Found during:** Final GSD metadata update
- **Issue:** `state.update-progress` correctly returned 7/20 and 35%, but the generated STATE frontmatter/body retained `percent: 0` and the previous 25% display.
- **Fix:** Updated the two stale fields to the SDK's returned 35% result.
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE records Plan 7 of 20 with 35% in both machine-readable and human-readable fields.
- **Committed in:** Final plan metadata commit.

---

**Total deviations:** 1 auto-fixed (1 blocking metadata defect)
**Impact on plan:** Documentation-only correction; implementation scope and runtime behavior are unchanged.

## Issues Encountered

All four target files contained user-owned unstaged changes before execution, including an older OpenAlex URL assertion that contradicted this security plan. The RED and GREEN commits were built with per-hunk/plan-only index patches; no baseline hunk was included. The combined working tree was verified green, and the pre-existing baseline changes remain unstaged after both commits.

## User Setup Required

None. If `RAT_OPENALEX_API_KEY` is configured, OpenAlex intentionally reports a sanitized provider failure until a non-query authentication channel is supported; the other providers continue normally.

## Next Phase Readiness

The scholarly retrieval boundary can now feed durable evidence and manuscript workflows without propagating secret-bearing request data. No provider, package, downloader, content/PDF acquisition path, vault writer, or network behavior beyond the existing metadata clients was added, and Plan 01-08 was not started.

## Self-Check: PASSED

All four target files, this summary, and commits `137edca` and `f989ed2` were verified on disk. The exact 29-test command passed, the summary has no whitespace errors, and all four pre-existing baseline working diffs remain unstaged.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
