# Team-upgrade decisions — 2026-08-20 (director-authorised)

Authority: director's directive of 2026-08-20 ("升级 team；高质量几乎无缺陷、覆盖面广的
agents 调动；分工、质检、自动路线寻优；论文撰写路径钉死、格式按参考范本；内容全部验证；
读完一切能取到的文献，取不到的出局；该砍的砍；哈希不要总验").

| id | decision | status |
|---|---|---|
| TU-1 | **Manuscript path pinned** as `docs/MANUSCRIPT-PATH-CN.md`: locked stage order search→release, per-stage owner seat + single artifact + tripwire; review-response sub-path named; format authority = the ref-free-seg-qa manuscript's `type.tex` + `build.sh` checks (monochrome, macro-quoted numbers, generated captions); adjudicative-language ban list. | implemented this round |
| TU-2 | **Verification economics**: hashing (deposit root hash, vendor verify, example replay, pixel/colour sweeps) runs at *release/promote moments only*, producing a receipt (hash + timestamp + coverage) trusted until the artifact set changes. Ledger append-time hashing (write-once) and the per-build prose-vs-corpus checks stay — they are cheap and caught three real bugs this week. No scheduled or per-report re-hashing of unchanged artifacts. | implemented this round |
| TU-3 | **Search layer hardening** (from run failures A1–A6): no permanent circuit breakers; budget-429 distinguished from throttle-429; per-unit checkpointing; channel-yield watchdog (a declared channel contributing 0 records fails loudly); citation chasing (backward+forward) is a standard search step. Encoded in machine tools + path doc. | implemented this round |
| TU-4 | **Extraction discipline**: independent labels only (no reader-derived fields — derivation is a generator's job); pinned vocabularies (underscore-only); leakage-style judgement fields require an explicit-statement rule; dual-reader reproducibility measurement is a standard per-corpus step with results quoted in the manuscript. | implemented this round |
| TU-5 | **Seats**: add the missing owners identified by Auditor A (search recovery / citation chase / blind second reader / format warden / review-response decomposition as applicable); park the redundant seats on Auditor A's justified list. Gates, hooks, convergence contract and ideation ring untouched. | per audit 01 |
| TU-6 | **Mode `manuscript_reconstruction`** (respond to an external review): registered per Auditor A's wiring verdict — one-button if the wiring is clean, else spec-registered with honest "manual drive" labelling. | per audit 01 |
| TU-7 | **Reading campaign v2**: fetch OA full texts for the 290-candidate queue (unfetchable = named, counted, out of scope; no paywall bypass); identity-verify on arrival; read against the frozen schema into `deepread-v2/` staging; fold-in only as a versioned revision re-running every generator. Contract: `runs/.../corpus/READING-CAMPAIGN-V2.md`. | fetch running; campaign staged |
| TU-8 | **Single-loader rule**: any artifact quoting corpus counts must obtain them through the canonical folding loader (or its machine successor); the N-TASK-LEDGER drift (73 vs 75) is the motivating incident. | per audit 02 |
