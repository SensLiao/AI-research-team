# Audit 02 — Pipeline tools & hardening (Auditor B, 2026-08-20)

> Inputs: `_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md` (items A1–F),
> machine `tools/`, and the ad-hoc tools of
> `runs/ref-free-seg-qa/deep_research-20260819T055022Z/tools/`.
> Implements the audit halves of TU-3 (search hardening) and TU-8 (single loader) in
> `_design/2026-08-20-team-upgrade/DECISIONS.md`.
> All run paths below are relative to `runs/ref-free-seg-qa/deep_research-20260819T055022Z/`;
> all machine paths relative to the machine root. Line numbers are from the 2026-08-20 tree.

---

## Q1 — Promote / merge / leave table

Hard boundary applied throughout: **the machine control plane stays domain-general**. Every
medical-imaging vocabulary found in the run tools (screening keyword lists, domain stopwords,
acronym brace-lists, the QA-function ontology) stays in `profiles/*.yaml` or run-local; only the
engines move. Concretely domain-bound and therefore **not** promotable as-is:
`tools/screen.py:28-77` (FUNC/SEG/MED/REJECT/INPUT_QUALITY), `tools/harvest.py:67-126` (QUERIES)
and `:487-506` (CORE/SEG/MED/NEG scoring), `tools/verify_corpus.py:49-58` (DOMAIN_STOP),
`tools/mkbib.py:25-29` (BRACE acronyms), `tools/recode_v2.py:49-65` (ontology classes).

| run tool | verdict | target module (machine) | public API sketch |
|---|---|---|---|
| `tools/harvest.py` (v1) | **LEAVE** run-local (superseded, carries the A1 breaker defect at `:130-147`); **MERGE its channel connectors** | `tools/scholar_clients.py` | add `search_pubmed(query, limit, transport)`, `search_europepmc(...)`, `search_dblp(...)`, `resolve_unpaywall(doi, mailto, transport)` — normalized to the existing record shape (`scholar_clients.py:22-25`). PubMed boolean-term builder (`harvest.py:226-234`) and DBLP 3-token rule (`:402-411`) come along as pure helpers; the query lists stay run-local. |
| `tools/harvest_v2.py` | **PROMOTE the engine** (cursor-paged, breaker-free, delta-reporting) | new `tools/search_campaign.py` | `run_campaign(queries: list[str], sources: list[str], out_dir, *, pages, per_page, checkpoint_every=1, transport) -> CampaignReport`; per-query checkpoint file + resume; per-source yield table; merge/delta report as in `harvest_v2.py:376-429` (`pct_of_v2_already_in_v1` / `pct_of_v1_recovered_by_v2` both stated, `:413-415`). No breaker, by contract (`harvest_v2.py:56-61`). Note: v2's own search streams still write only at the end (`:202-205`); the promoted engine must checkpoint per query like `chase_v2`/`fetch_t1_v2` do. |
| `tools/chase_v2.py` | **PROMOTE** (JBI step 3; catalog A4) | new `tools/citation_chase.py` | `chase(seeds: list[{slug,title,doi?,arxiv?}], out_path, *, transport, resume=True) -> ChaseReport`. S2 references+citations at 2 requests/seed (`chase_v2.py:4-9`), offset paging (`:86-103`), per-seed checkpoint + `.done` set (`:116-131,163`), unresolved seeds counted never dropped (`:147-149,167-174`). Requires adding an `offset` param to `scholar_clients.get_references_s2/get_citations_s2` (`scholar_clients.py:380-393` currently cap at one page). |
| `tools/screen.py` + `tools/screen_v2.py` | **PROMOTE the engine, vocabulary injected**; vocabularies stay in profile/run | new `tools/corpus_screener.py` | `screen_records(records, vocab: ScreeningVocab, *, known_ids=None) -> ScreenReport`; `ScreeningVocab = {functions:{name:[phrases]}, object_terms, domain_terms, reject_terms, object_quality_exception}` loaded from `profiles/<domain>.yaml`. Engine keeps: recall-biased tiering T1/T2/T3 (`screen.py:11-13`), reason-coded exclusions (`:84-131`), the no-abstract→T2 unresolved paths (`:106-114`), one-rule-for-all-waves (`screen_v2.py:4-9,28`), two-key dedup richer-record fold (`screen_v2.py:51-85`). |
| `tools/verify_corpus.py` | **PROMOTE** (catalog B2/B3: PDF-identity verification is currently run-local only) | new `tools/document_identity.py` | `distinctive_word_containment(expected, candidate, stopwords) -> float` (`verify_corpus.py:61-107`), `pdf_title_candidates(pdf) -> [(text, how)]` (`:114-153`), `verify_pdf_identity(pdf, expected_title, *, stopwords, threshold=0.45) -> IdentityVerdict`, plus the one-way adjudication ledger (`correct-confirmed` only, survives regeneration, `:172-188`). Ships with generic-English default stopwords; the domain stoplist is a profile parameter. **B2 rule becomes a test contract: the module ships with known-bad regression pairs** (the bigram false-positive documented at `:43-48`) and cannot claim to guard until they fail correctly. |
| `tools/synthesize.py::load()` | **PROMOTE the fold** (see Q4); the evidence-map/matrix body stays run-local | new `tools/corpus_loader.py` | see Q4. Domain fields (`SIGNALS`/`FUNCS`, RQ paths at `synthesize.py:29-37,152-244`) never move. |
| `tools/recode_v2.py` | **LEAVE** (campaign ontology recode) | — | the schema *rule* it encodes — "labels record observations only; nothing is implied by another label" (`recode_v2.py:79-149`; catalog C3) — is TU-4 material for the extraction-schema policy in profiles, not a machine tool. |
| `tools/ref_audit.py` | **PROMOTE** as a new tool; **MERGE its title-match rule** into `citation_existence` | new `tools/bib_audit.py` (+ patch `tools/citation_existence.py`) | `audit_bib(bib_path, *, doi_overrides: dict, worknote_patterns: list[regex], transport) -> AuditReport` with defect classes PREPRINT_SUPERSEDED / MISSING_DOI / LEAKED_WORKNOTE / SUFFIX_RENDER_HAZARD / VENUE_MISMATCH / UNRESOLVED (`ref_audit.py:13-21`). Title acceptance = exact normalized equality, or containment **plus year agreement ±1**, else UNRESOLVED-never-guessed (`:129-175` — the fix for the D4 U-Net 2017-reprint miss). `DOI_OVERRIDE` (`:120-126`) becomes a caller table; `WORKNOTE_PAT` (`:44-46`) is caller-supplied (run-idiom text). Merge into machine: `citation_existence._check_title` currently accepts any `ratio >= 0.92` with **no year agreement** (`citation_existence.py:57,117-139`) — add an optional `year` param applying the same ±1 rule when the caller has one. |
| `tools/fix_bib.py` | **MERGE** into `bib_audit.py` as its `fix` subcommand | `tools/bib_audit.py fix` | applies only authority-supported classes; never auto-applies VENUE_MISMATCH/UNRESOLVED (`fix_bib.py:15-24`). Its `clean()` — html.unescape **then** LaTeX-escape, in that order (`:49-64`, the `&amp;` build-killer from catalog D4) — becomes the ONE machine "authority metadata → BibTeX field" escaper. Suffix repair `Wells III → Wells, III, William M.` (`:67-75`); preprint→published promotion keeping the arXiv id as an audit note (`:97-114`). |
| `tools/dual_reader.py` | **PROMOTE the harness** (catalog C1); field list is campaign input | new `tools/dual_read.py` | `sample(units, fraction, seed) -> SamplePlan` (fixed seed, reproducible from the article alone, `dual_reader.py:41-43`); `compare(first_units, second_dir, fields: list[(path, kind)]) -> AgreementReport` with pinned normalization (hyphen≡underscore — catalog C2; `:89-104`), Jaccard partial credit for set fields (`:107-116`), per-field + overall agreement, and the mandatory honesty caveat emitted by the tool itself (machine–machine agreement bounds reproducibility, not correctness, `:14-19,169-171`). |
| `tools/mkdeposit.py` | **PROMOTE** (write-once release hashing — consistent with TU-2/E1) | new `tools/deposit_manifest.py` | `build_manifest(root, groups: dict[str, list[path]], out_path) -> {root_sha256, n_files, missing_declared_items, files[]}` (`mkdeposit.py:79-114`); optional macro-emit hook so the document quotes the root hash from the same code path (`:117-122`). Runs at deposit/release moments only, producing a receipt trusted until the artifact set changes (catalog E1 policy; `DECISIONS.md` TU-2). |
| `tools/reconcile_v2.py` | **LEAVE the file; PROMOTE the stale-macro pattern** into the Q4 checker | `tools/corpus_count_check.py` (Q4) | live recompute vs quoted macros with named deltas (`reconcile_v2.py:89-104,126-135`); the campaign-specific audit-chain rows (`:61-86`) stay run-local. |
| `tools/fetch_t1_v2.py` | **PROMOTE the engine** (already written to the failure catalog's spec, `fetch_t1_v2.py:9-17`) | new `tools/fulltext_fetch.py` | `fetch(queue: list[record], out_dirs, *, verify: IdentityVerdictFn, transport) -> FetchManifest`. OA-only ladder record-URLs → arXiv → Unpaywall → Europe PMC (`:110-141`), landing pages never scraped (`:177-178`), identity verification on arrival with quarantine (`:144-158,184-190`), per-record checkpointed manifest (`:191-199`), `unfetchable` as a first-class reason-coded status (catalog F; `:191-196`). Depends on `document_identity` above. |
| `tools/extract_text.py` (dependency of fetch/verify, `fetch_t1_v2.py:46-47`) | **PROMOTE with** `document_identity` | `tools/document_identity.py` (same module) | `pdf_text(pdf) -> (text, n_pages)` + `clean(text)`; PyMuPDF with the honesty rule of `fulltext_qa.py:117-146` (no text ⇒ say so). |

Machine tools already covering adjacent ground (do **not** duplicate): existence checking stays in
`tools/citation_existence.py` (three-state verdict, `:188-230`); retraction stays in
`tools/fulltext_qa.py::retraction_check` (`:207-235`); claim–evidence gating stays in
`tools/citation_checker.py`. `bib_audit.py` is about *metadata correctness of a .bib*, which none
of those do — the catalog's D4 question "why were they not dispatched?" is half answered here:
the seats existed but **no machine tool did the .bib-level job**, so dispatching them could not
have produced `ref_audit`'s findings. (The dispatch half is Auditor A/E3 territory.)

---

## Q2 — `tools/scholar_clients.py` defect list (line-numbered) + minimal fixes

Direct answers first: **circuit breakers that permanently kill channels — none exist** (the
client is stateless; `paper_search.search` retries every source fresh per query,
`tools/paper_search.py:186-196`), so the run's A1 defect (`runs/.../tools/harvest.py:130-147`)
is *not* in the machine. The machine's defect set is the mirror image: **no resilience and no
visibility**. Budget-429 awareness — **none**. Per-query checkpointing — **none**.
Channel-yield watchdog — **none**. Citation-chase endpoints — **present but not operable**.

1. **No retry, no backoff, no pacing anywhere.** `default_transport` makes exactly one attempt
   and raises on any HTTPError (`tools/scholar_clients.py:123-140`); the module never imports
   `time` (`:27-38`). One transient 429/503 = that source lost for that query, recorded as a
   string in `source_errors` (`tools/paper_search.py:186-201`).
   *Fix:* bounded retry inside `default_transport` (or a `retrying_transport` wrapper): on
   429/500/502/503/504 sleep `min(cap, Retry-After or base*2^attempt)`, ≤ 4 attempts, then raise.
   Never a breaker (TU-3). Keep the injectable-transport contract so tests stay offline.

2. **429 is never classified; OpenAlex daily budget is unknown to the machine** (catalog A2:
   OpenAlex 429 is a daily request budget resetting 00:00 UTC — backoff can never succeed).
   `_HTTPStatusError` keeps `.status` (`:112-115`) but every caller flattens it to a sanitized
   string (`tools/paper_search.py:189-190,201`), so "budget exhausted for today" and "throttled
   for 2s" are indistinguishable downstream.
   *Fix:* after retries are exhausted on a 429, raise `ScholarBudgetError(ScholarLookupError)`
   carrying `{source, status, retry_after_s|None}`; for OpenAlex, the error text names the
   documented daily-budget semantics ("resets 00:00 UTC — do not spin"). `paper_search` records
   structured `source_errors[src] = {kind: "budget"|"http"|"network", detail}` so the operate
   brief/report can say which channel is *gone for the day* vs merely flaky. Related:
   `_reject_openalex_query_key` (`:268-273`) forecloses key-based budget lifts entirely — fine
   as a security stance, but it makes budget classification the *only* mitigation, so the error
   text must teach it.

3. **No per-query checkpointing in the fan-out layer** (catalog A5). `search_many` accumulates
   everything in memory (`tools/paper_search.py:240-312`) and the operate pre-step writes one
   bundle at the very end (`operate/modes/_shared.py:590-643`, write at `:643`;
   `write_search_bundle` single write `tools/paper_search.py:379-404`). A kill loses the plan.
   *Fix:* optional `checkpoint_path` on `search_many`: after each query, rewrite a
   `search-results.partial.json` (the pattern of `runs/.../tools/harvest.py:558-565`) and skip
   already-completed queries on resume; `pre_search` passes
   `<run>/inbox/search-results.partial.json`.

4. **No channel-yield watchdog** (catalog A1/A6 detection gap). `search`/`search_many` keep
   per-query error strings and aggregate relevance counters (`tools/paper_search.py:198-217,
   240-312`, counters `:298-306`) but never compute per-source yield; a declared source can
   error on every query or contribute 0 records across the whole plan and the bundle still looks
   complete. `pre_search` even maps *total* failure to an empty-records bundle and proceeds
   vault-only (`operate/modes/_shared.py:641-643`) — legitimate as degradation, but today the
   channel loss is buried, violating hard boundary §6 ("a retrieval channel that fails must be
   named, never silently degraded around", `.claude/CLAUDE.md`).
   *Fix:* `search_many` returns `source_yield = {src: {queries_attempted, queries_errored,
   records_contributed}}`; `pre_search` promotes any declared source with
   `records_contributed == 0` into a loud top-level `channels_lost: [src…]` field of the bundle,
   which `operate brief`/`report` must print and which marks that channel's coverage claims
   UNVERIFIED. Zero-yield-with-zero-errors on every query is also flagged (A6's "+0 (raw 0)"
   tripwire), as `channels_zero_yield`.

5. **Citation chase is declared but not drivable** (catalog A4). The endpoints exist —
   `get_references_s2` (`tools/scholar_clients.py:380-385`) and `get_citations_s2` (`:388-393`)
   — but (a) nothing deterministic calls them: the only references are prompt text
   (`agents/lit-scout.md:71-72`, `skills/literature-review.md:38`, `skills/research-lookup.md:26`);
   `_SEARCHERS` exposes only the four search functions (`tools/paper_search.py:50-55`) and no
   `pre_search`-style pre-step exists for chase; (b) both functions are single-page — a `limit`
   with no `offset` (`:382-385,390-393`), while a real chase pages (`runs/.../tools/chase_v2.py:86-103`).
   *Fix:* add `offset: int = 0` to both client functions; promote `chase_v2` as
   `tools/citation_chase.py` (Q1); add an operate pre-step (e.g. `operate chase` or a
   `--chase-seeds` flag on `pre-search`) that writes `inbox/citation-chase.json` with per-seed
   checkpointing and an unresolved-seed count.

6. **arXiv pacing contract is violated by multi-query plans.** `search_arxiv` sends immediately
   (`tools/scholar_clients.py:262-265`) and `search_many` loops queries with no inter-query
   pacing (`tools/paper_search.py:246-247`), while arXiv asks ≥3 s between requests (the run
   respected it: `runs/.../tools/harvest.py:218`). Combined with defect 1, a throttle = a lost
   source for that query.
   *Fix:* a per-source minimum-interval map in the facade (`{"arxiv": 3.0}` default), applied
   between successive requests to the same source.

Non-defects worth recording: 404-vs-error discipline is right (`:13-15,309-346`); read-time
network failures are normalized (`:131-140`); parse failures degrade to "could not check"
(`:150-162`); secrets/URLs are sanitized before persistence (`:55-102`); S2 key goes in a header
(`:295-297`). Preserve all of these through any fix.

---

## Q3 — The one LaTeX-generation discipline, and where to encode it

The three D6 incidents (catalog `00-inputs-failure-catalog.md:73-75`) are one class: **an
escape-significant string passed through an interpreting layer it was not written for.**
- BELL: `"\a"` in a non-raw Python literal → U+0007 in the .tex, pdflatex stops
  (`runs/.../tools/mktable3.py:62-65`; same lesson re-learned at `tools/claims.py:206-208`).
- Halved backslashes: `\\` collapsing once per shell/heredoc layer
  (`runs/.../tools/mktables_v2.py:23-24` builds `BS = chr(92)` for exactly this reason).
- Literal `\n`: heredoc text reaching the file unexpanded (catalog D6).

**The discipline (one rule):**

> **LaTeX-bearing text is only ever produced by a generator that exists as a `.py` file in the
> tree, edited by file-edit tools and executed as `python tools/<gen>.py`. No LaTeX, BibTeX, or
> other escape-significant text may pass through any shell string layer — bash heredoc, `echo`,
> `python -c`, PowerShell here-string. Inside generator files, every backslash-bearing literal
> is a raw string (`r"..."`) or composed from `chr(92)`; string constants containing C0 control
> characters are forbidden. A generator emits data and its caption/prose from the same code path
> (catalog D3) and stamps `%% AUTO-GENERATED by tools/<gen>.py — do not hand-edit` as line 1;
> hand-editing a stamped file is forbidden.**

One rule kills the whole class because it removes every second interpreter between the author
and the bytes: the only escape semantics in play are Python's, pinned by raw strings/`chr(92)`,
and the only writer is a diffable, re-runnable file. The stamped header + same-code-path caption
also carry catalog D3 and match the run's own surviving pattern
(`runs/.../tools/mkdeposit.py:117-122` emits the macro next to the manifest;
`runs/.../tools/check_prose.py:1-21` is the pre-build checker the catalog says to keep).

**What the machine enforces today — checked:**
- `tools/latex_build.py` validates at *build* time only: UTF-8 (`:201-205`), TeX command/package
  allowlist via `validate_tex_sources` (`:278-280`; allowlist mechanics in
  `tools/manuscript_security.py:454-491,522+`), asset existence (`:286-288`), label/ref closure
  (`:289-292`), unresolved-ref log scan (`:72-76,789-790`), secret scans. **Nothing rejects
  control characters**: U+0007 is valid UTF-8, `_CONTROL_SEQUENCE_RE` matches `\name` TeX
  sequences, not C0 bytes — the BELL incident would compile-fail *inside* pdflatex, not be named
  by preflight. **No generation-provenance rule exists.**
- `tools/manuscript_renderer.py` writes Markdown reports and projects canonical `source/`
  byte-for-byte (`:443-449`); it never composes .tex — so it can't enforce generation
  discipline either.

**Where to encode it (three small seats, no new subsystem):**
1. `tools/latex_build.py::_preflight` (`:257-293`): add two checks — reject any C0 control
   character other than `\t`/`\n`/`\r` in `.tex`/`.bib` sources (names the BELL class with a
   real error code, e.g. `TEX_CONTROL_CHARACTER`), and reject residual XML entities
   (`&amp;`-class) in `.bib` (names the D4 build-killer).
2. A ~60-line `tools/latex_gen_lint.py`: AST-walk the campaign's `tools/*.py` that write under
   the manuscript `src/`; flag (a) string constants containing C0 control chars (catches `"\a"`
   at author time), (b) generated files on disk missing the `%% AUTO-GENERATED` stamp, (c) any
   stamped file whose mtime is newer than its generator run receipt (hand-edit tripwire). Wire
   it beside the run's `check_prose.py` slot in the pinned path.
3. The rule text itself goes in the pinned manuscript path doc (`docs/MANUSCRIPT-PATH-CN.md`,
   TU-1) and in the format-warden seat instructions (TU-5): *generators are files; shell
   heredocs emitting LaTeX are forbidden; raw strings or `chr(92)` for every backslash.*

---

## Q4 — The single-loader mechanism (catalog B1)

Incident: duplicate folding lived only in `synthesize.load()`
(`runs/.../tools/synthesize.py:48-82`: identity `_idkey` DOI→arXiv→normalized-title `:40-45`,
richer-record-wins `:75`, fold notes + decision-conflict surfacing `:69-82`), while
`N-TASK-LEDGER.md` quoted raw record counts — 75 vs the true 73 — until `reconcile_v2.py`
proved the manuscript right and the ledger wrong (`runs/.../tools/reconcile_v2.py:17-19`).
The run today has at least four identity/fold policies (`synthesize.py:40-45`;
`harvest.py:447-483`; `screen_v2.py:51-85`; `chase_v2.py:120`) and the machine two more
(`tools/paper_search.py:161-166`; `tools/systematic_review_corpus.py:76-101`). That is the
disease: counts fork wherever identity forks.

The machine already owns the precedent: `tools/systematic_review_corpus.py` derives every count
from rows and **refuses stale scalars** (`:341-342` `records_retrieved`, `:513-521`
`legacy_claimed_total`/`legacy_scalar_matches`, PRISMA arithmetic `:643-669`) — but it hard-requires
two-reviewer screening (`:109-114,258-261`), which a single-reader campaign cannot satisfy;
that is exactly why the run rolled its own loader. So the mechanism is a lightweight sibling,
not a replacement:

**1. One loader — new `tools/corpus_loader.py` (deterministic, stdlib):**
```python
LOADER_VERSION = "corpus-loader/v1"
# identity: reuse canonical_report_identity + IDENTITY_POLICY_VERSION
# ("report-identity/doi-arxiv-pmid-title/v1") from systematic_review_corpus.py:29,76-101

def load_units(records, *, id_fn=canonical_report_identity) -> Census
```
`Census` = `{loader_version, identity_policy_version, n_records, n_units, n_folded,
folds: [{unit_identity, kept_record, dropped_records, field_conflicts}], units: [...],
census_sha256}` — richer-record-wins (canonical-JSON length, the shared rule of
`synthesize.py:53-56,75` and `screen_v2.py:51-58`), decision-field conflicts surfaced in the
fold row (never silently resolved, `synthesize.py:76-79`), `census_sha256` computed by the
existing `tools/hash_artifact.py::hash_payload` (`:26-28`) over the counts block. No screening
semantics, no PRISMA, no document-type policy — folding and counting only.

**2. One rule (TU-8):** any artifact quoting corpus counts obtains them from the census and
names its origin — a `counts_from: {loader_version, census_sha256}` field in JSON artifacts, a
`%% counts_from corpus-loader/v1 sha256:<...>` comment line in generated `.tex` macro files
(the run's `src/tab/corpus_numbers.tex` pattern, written by `mktables`), and the task ledger's
§1 numbers are pasted from the census block, never typed. Consumers in the run that must switch
to it: `synthesize.py`, `recode_v2.py:44` and `dual_reader.py:39` and `chase_v2.py:41` (already
import `load` — the promoted loader keeps that import surface), `mkbib.py` (same fold rule,
`synthesize.py:53-56`), `ledger_v2.py`, `mktables*.py`, `N-TASK-LEDGER.md`.

**3. One check — new `tools/corpus_count_check.py` (~80 lines):** given the census and a list of
count-quoting files, (a) verify each file's declared `counts_from.census_sha256` matches the
live census, (b) recompute the numeric macros/fields it declares and print named deltas, exit
non-zero on drift — the generalization of `reconcile_v2.py:89-104`'s stale-macro detector.
Wire it as a tripwire in the pinned manuscript path (runs with `check_prose.py`, pre-build) and
in the report stage, so a ledger or manuscript quoting unfolded numbers fails loudly the same
day, not after an external review.

Kept deliberately small: one loader function, one census artifact, one checker; identity policy
reused from the existing manifest tool rather than invented; hashing via the existing
`hash_artifact` helpers; no scheduled re-hashing (TU-2 — the census hash is recomputed only when
the census is regenerated).
