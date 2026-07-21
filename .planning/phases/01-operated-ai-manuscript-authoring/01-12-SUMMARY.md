---
phase: 01-operated-ai-manuscript-authoring
plan: "12"
subsystem: literature-routing
tags: [local-first, vault-recall, paper-search, frozen-trace, metadata-only, tdd]
requires:
  - phase: 01-03
    provides: Hermetic local-corpus and retrieval-truth gold cases
  - phase: 01-07
    provides: Existing scholarly metadata search and secret-safe provider diagnostics
  - phase: 01-09
    provides: Registered closed local_literature_coverage schema
provides:
  - Explicit six-axis local literature coverage through bounded read-only vault recall
  - Named-deficit frozen query plans using only the existing paper_search.search_many port
  - Exact three-state retrieval truth derived from complete hash-bound attempt traces
  - Metadata-only candidate projection that cannot establish entailment or local ownership
affects: [manuscript-authoring-recipe, evidence-stewardship, section-dispatch, manuscript-audit]
tech-stack:
  added: []
  patterns: [recall-before-search, named-deficit-authorization, exhaustive-trace-reduction, metadata-only-projection]
key-files:
  created:
    - tools/manuscript_literature.py
    - tests/test_manuscript_literature.py
  modified: []
key-decisions:
  - "An empty bounded local recall remains UNVERIFIED; only a named frozen deficit authorization may change the axis to DEFICIT and permit metadata search."
  - "Each deficit freezes one query and an exact provider-attempt set, executed only through injected paper_search.search_many calls."
  - "NO_EVIDENCE_AFTER_VALID_SEARCH requires exact plan/trace hashes, one-to-one terminal closure, and successful empty responses from every required attempt."
  - "Provider rows are reduced to a seven-field metadata-only projection with no content, URL, entailment, exact-span, local-full-text, or manuscript-admission authority."
patterns-established:
  - "Retrieval truth reducer: provider failure, unresolved partial state, and exhaustive valid-empty state remain mutually distinct."
  - "Vault read adapter: declared root equality plus symlink/reparse surface checks precede every six-axis recall pass."
requirements-completed: [EVID-01, EVID-02, EVID-03, SAFE-01, SAFE-02, VERI-02]
coverage:
  - id: D1
    description: All six D-06 literature axes are assessed independently through bounded read-only PhD-Research-OS recall and expose stable local refs only.
    requirement: EVID-01
    verification:
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_bounded_local_recall_covers_all_axes_and_returns_references_only
        status: pass
    human_judgment: false
  - id: D2
    description: Sufficient local coverage performs zero search calls, while only a named UNVERIFIED axis can freeze and execute a targeted provider plan.
    requirement: EVID-02
    verification:
      - kind: integration
        ref: tests/test_manuscript_literature.py#test_sufficient_local_coverage_suppresses_every_search_call
        status: pass
      - kind: integration
        ref: tests/test_manuscript_literature.py#test_named_deficit_calls_only_search_many_and_keeps_openalex_metadata_only
        status: pass
    human_judgment: false
  - id: D3
    description: Provider outage, incomplete or mismatched traces, and exhaustive successful empty traces reduce to three exact non-interchangeable truth states.
    requirement: EVID-03
    verification:
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_any_incomplete_or_unresolved_zero_result_is_never_absence
        status: pass
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_no_evidence_requires_exact_successful_terminal_closure
        status: pass
    human_judgment: false
  - id: D4
    description: Search output is metadata-only, OpenAlex has no direct content path, and the module exposes no write, promotion, acquisition, or subprocess surface.
    requirement: SAFE-01
    verification:
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_module_has_no_write_promotion_download_or_direct_provider_surface
        status: pass
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_nonempty_rows_are_forced_to_metadata_only_and_never_prove_absence
        status: pass
    human_judgment: false
  - id: D5
    description: Unsafe vault roots and secret-bearing queries fail before retrieval, and provider diagnostics are URL/credential redacted.
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_unapproved_or_linked_vault_roots_fail_before_recall
        status: pass
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_provider_errors_and_request_urls_are_redacted_before_return
        status: pass
    human_judgment: false
  - id: D6
    description: Malformed or unbound search responses cannot self-certify a valid empty result or an exhaustive evidence-absence claim.
    requirement: VERI-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_literature.py#test_malformed_search_response_can_never_prove_exhaustive_absence
        status: pass
    human_judgment: false
duration: 22min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 12: Local-First Literature Coverage Summary

**A bounded six-axis vault-first router now authorizes only named literature deficits, records complete frozen provider traces, and preserves metadata-only retrieval truth without adding any acquisition path.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-07-21T13:16:35Z
- **Completed:** 2026-07-21T13:38:37Z
- **Tasks:** 1
- **Files modified:** 2 new files

## Accomplishments

- Added explicit coverage for related comparison, technical method, implementation detail, dataset, metric/evaluation, and industry prior art, with bounded root validation and stable vault references.
- Kept locally sufficient axes offline and required a named `DEF-*` authorization plus canonical plan hash before invoking the existing metadata search port.
- Derived `PROVIDER_FAILURE`, `PARTIAL_OR_UNRESOLVED_ZERO_RESULT`, and `NO_EVIDENCE_AFTER_VALID_SEARCH` from exact required-attempt, query, provider, response, plan, and trace closure.
- Reduced every returned paper to schema-authorized metadata only; OpenAlex remains an existing metadata provider with no PDF, content, bulk acquisition, or downloader path.
- Rejected unsafe/symlinked recall roots, secret-bearing queries, unbound provider records, malformed responses, and unredacted provider diagnostics before they could become coverage evidence.

## Task Commits

1. **TDD RED: Define local-first literature and retrieval-truth gates** - `d4b4694`
2. **TDD GREEN: Implement six-axis coverage and deficit routing** - `c1e4f3a`
3. **Security fix: Reject malformed or unbound search responses** - `c431c15`

## Files Created/Modified

- `tools/manuscript_literature.py` - Pure bounded recall, frozen query-plan, search-trace, outcome-reduction, and metadata-projection functions.
- `tests/test_manuscript_literature.py` - Hermetic local-first, deficit authorization, retrieval truth, schema, path, redaction, and no-acquisition regressions.

## Verification

- `python -m pytest tests/test_manuscript_literature.py tests/test_paper_search.py tests/test_scholar_clients.py -q` - 51 passed.
- `python -m pytest tests/test_manuscript_schema_contracts.py -q` - 36 passed.
- `python -m ruff check tools/manuscript_literature.py tests/test_manuscript_literature.py` - passed.
- `python -m compileall -q tools/manuscript_literature.py tests/test_manuscript_literature.py` - passed.
- `git diff --check -- tools/manuscript_literature.py tests/test_manuscript_literature.py` - passed.
- Focused AppSec follow-up for F-001 returned PASS after the malformed-response regressions passed.

## Decisions Made

- Missing local recall is not a deficit and never proves absence; it stays `UNVERIFIED` until a named query plan is frozen.
- A query plan is minimal per deficit and freezes stable provider-specific attempt IDs; routing makes one existing `search_many` call per required provider using the injected transport.
- The raw trace retains observed provider states, while the registered coverage schema receives a closed safe projection appropriate to the derived outcome.
- Search records are always follow-up metadata. Caller-supplied claims of entailment, exact-span support, local full-text ownership, or manuscript admissibility are discarded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Security] Required a valid provider-response contract before absence derivation**

- **Found during:** Post-GREEN AppSec review
- **Issue:** An arbitrary mapping such as `{}` could be interpreted as a successful empty provider response, locally hashed, and combined with an otherwise complete trace to produce a false `NO_EVIDENCE_AFTER_VALID_SEARCH` conclusion.
- **Fix:** Required exact requested-query binding, explicit `records` and `source_errors` types, and per-record source/found-in binding before any success state. Malformed responses now become provider failure and cannot certify absence.
- **Files modified:** `tools/manuscript_literature.py`, `tests/test_manuscript_literature.py`
- **Verification:** Empty-mapping and query-mismatch regressions pass; the full 51-test plan command passes; focused AppSec rereview returned PASS.
- **Committed in:** `c431c15`

---

**Total deviations:** 1 auto-fixed (1 missing critical security/correctness requirement)
**Impact on plan:** The fix closes a false-absence path inside the planned retrieval-truth boundary without adding a provider, transport, schema, dependency, or extra product surface.

## TDD Gate Compliance

- RED gate: `d4b4694` failed at import because the implementation module did not yet exist.
- GREEN gate: `c1e4f3a` followed RED and passed the planned suite.
- Security correction: `c431c15` added and passed the malformed-response regression without changing the public scope.

## Issues Encountered

None beyond the auto-fixed response-validation gap documented above.

## Known Stubs

None. No placeholder data path, empty UI payload, TODO, or unwired mock remains in either created file.

## Authentication Gates

None.

## User Setup Required

None - no package, credential, server, provider, or external service configuration was added.

## Next Phase Readiness

Later authoring orchestration can consume a schema-valid six-axis coverage record, exact frozen query plans, and complete search traces. Any future evidence worker must still retrieve and validate primary content separately; these metadata rows deliberately cannot support manuscript claims.

## Self-Check: PASSED

Both created files and this summary exist; RED `d4b4694`, GREEN `c1e4f3a`, and security fix `c431c15` resolve as commits; the 51-test plan suite, 36-test schema suite, Ruff, compileall, AppSec follow-up, stub scan, and whitespace checks passed.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
