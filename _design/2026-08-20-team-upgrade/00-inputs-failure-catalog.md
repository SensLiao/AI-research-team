# Team-upgrade inputs — failure catalog (2026-08-20)

> Shared input for the four upgrade auditors. Every item below actually happened in the
> `ref-free-seg-qa` deep_research run (`runs/ref-free-seg-qa/deep_research-20260819T055022Z/`)
> or was demanded by the external Reject review of the resulting manuscript. Nothing here is
> hypothetical. Director directive (2026-08-20): upgrade the team for near-defect-free,
> broad-coverage dispatch; clear division of labour; quality checks; automatic route
> optimisation; a pinned, non-drifting manuscript path with a format reference; all content
> verified; read everything retrievable (skip what cannot be found or fetched); **cut what
> deserves cutting; stop hash-verifying routinely — hash only when it matters.**

## A. Search / retrieval layer

- **A1 — channel silently lost.** `harvest.py` circuit breaker (`_BREAK_AFTER = 3`)
  permanently disabled OpenAlex after three 429s; the executed search ran with its most
  important index contributing **0 records** and nothing alarmed. Detection gap: no
  channel-yield watchdog ("a declared channel returned zero" should be a loud failure).
- **A2 — 429 misread.** OpenAlex 429 is a **daily request budget** (resets 00:00 UTC), not a
  throttle. Exponential backoff burned ~126 s/request and could never succeed. No
  budget-aware client exists in machine `tools/` (`scholar_clients.py` to be checked).
- **A3 — no adversarial query arms.** No dedicated searches for the evidence classes most
  likely to falsify headline claims (prospective deployment, radiotherapy QA, post-market
  monitoring). The reviewer found the killer counterexample (DL-SpiQA, Lancet Digital
  Health) that all 6,204 v1 records missed; the dedicated arm retrieved it immediately.
- **A4 — JBI step 3 absent.** No backward/forward citation chasing anywhere in the executed
  mode. Run-local `chase_v2.py` (Semantic Scholar, 2 requests/seed) now proves it cheap:
  73 seeds → 3,221 records, 151 new deep-read candidates.
- **A5 — no checkpointing.** v1 accumulated in memory and wrote once at the end; an
  interruption lost the whole harvest. Run-local v2 now checkpoints per query/seed.
- **A6 — zero-yield rows ignored.** "+0 (raw 0)" printed repeatedly with no tripwire.

## B. Corpus identity / integrity layer

- **B1 — two count truths.** Duplicate-record folding lived only in `synthesize.load()`
  (120 records → 118 papers → 73 pool); `N-TASK-LEDGER.md` quoted unfolded numbers (75).
  Consumers must share ONE loader; the ledger drifted for a day before being caught.
- **B2 — verifier with no discriminative power.** The slug↔PDF title check (bigram Jaccard)
  passed a wrong-content PDF because domain-shared words carried the similarity. Fixed with
  distinctive-word comparison + regression pins, but the lesson generalises: **a verifier
  must be validated against known-bad inputs before it guards anything.**
- **B3 — PDF-identity verification is run-local**, not a machine capability.

## C. Extraction layer

- **C1 — single reader, no reproducibility number.** External review scored this 2.5/10.
  Run-local dual-reader study now exists (24 papers, 33 %, blind): overall 82.8 %;
  `action_named` and `prospective` at 100 %; **leakage-risk at 37.5 %** — that field's
  vocabulary does not reproduce and must be redesigned or demoted.
- **C2 — vocabulary drift inside our own schema.** `not-assessable` vs `not_assessable`
  counted as disagreement until normalised; hyphen/underscore never pinned.
- **C3 — ontology allowed derived labels.** The cumulative F1–F4 ladder wrote labels no one
  observed (26/73 credited *estimate*, 27 *detect*, 11 *localise* with no such output; 33
  studies had no slot). Schema rule needed: **labels record observations only; nothing is
  implied by another label.**

## D. Synthesis / manuscript layer

- **D1 — certainty by arithmetic.** "established = ≥2 groups + ≥1 external validation"
  baked verdicts into a generator; all 11 "established" claims had zero prospective support.
- **D2 — adjudicative prose.** settled / what displaced it / direction knowable / apparatus
  largely exists — no linter for verdict vocabulary existed.
- **D3 — caption/data divergence.** A caption asserted "independent labels" while the column
  was still ladder-generated (caught mid-upgrade). Generated artifacts must emit caption and
  data from the same code path.
- **D4 — reference metadata.** 88/171 bib entries defective (42 preprints with published
  versions, 36 missing DOIs, 2 leaked work-notes, 2 name-suffix render bugs). Fuzzy title
  matching accepted a 2017 reprint for U-Net until year-agreement was enforced; Crossref XML
  entities (`&amp;`) reached the .bib unescaped and killed the build. Machine seats
  (`bibliography-validator`, `citation-integrity-auditor`) and tools (`citation_checker`,
  `citation_existence`) exist — **why were they not dispatched?**
- **D5 — venue format not owned.** Monochrome/no-badge/no-panel had to be retrofitted by
  directive; no seat owns "format per reference template".
- **D6 — LaTeX-from-heredoc escaping class.** BELL (`\a`), halved backslashes, literal `\n`
  — three separate incidents in one day. Generators must live in files; the build's
  prose-vs-corpus checker caught one and is the pattern to keep.

## E. Process / governance / economics

- **E1 — hash over-verification (director directive).** Deposit root-hash and colour checks
  re-run habitually. Policy wanted: **write-once hashing at release/deposit/promote moments
  only; a recorded receipt is trusted until the artifact changes; never re-hash unchanged
  artifacts per build or per report.** Tamper-evident ledger append-time hashing stays (cheap,
  integrity-critical). Audit where `hash_artifact.py` / `hash_manifest_validator.py` /
  `vendor_upstream_skills.py verify` / `example_replay.py` actually run today.
- **E2 — no pinned writing path.** Section/table/figure order, per-stage ownership and
  fold-in protocol for new corpus reads existed only in my head; drift was possible at every
  step. The director wants the path pinned, with tripwires, format authority named.
- **E3 — dispatch gap (the big one).** The machine rosters 175 seats including manuscript-*,
  citation-*, search seats — yet the run hand-rolled ~15 ad-hoc scripts on the main thread.
  Either the recipes never dispatch these seats for review-response work, or the seats are
  unreachable from any operated mode. `manuscript_reconstruction` (respond-to-external-review)
  does not exist as a mode.
- **E4 — external-review response is a standard research task** with no route: parse review →
  verify each claim against artifacts → registered decisions → mechanical recomputes →
  prose repairs → rebuild → re-review. This whole run was that, done freehand.

## F. Explicit scope decisions already made by the director

- Read everything retrievable; **unfindable or unfetchable full texts are out of scope** —
  name them, count them, never claim them read, never bypass paywalls.
- The 290-paper T1 v2 queue is the concrete reading backlog (fetch → verify identity →
  extract → dual-lane read → fold-in via a versioned manuscript revision).
- Cuts are authorised, including governance-adjacent economics (hash frequency), but the
  five human gates and the crown-jewel honesty invariants are NOT candidates.
