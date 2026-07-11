# P6 — Codex Work-Orders: re-read existing papers into the 0+3+1 card

> **Who runs this:** the DIRECTOR hands one work-order at a time to Codex (`/codex:rescue`), Codex reads the
> paper and fills the new template, the director reviews. The machine does NOT auto-run these.
> **Why Codex (not the machine):** the director chose (2026-06-26) to delegate the *re-reading labor* of the
> ~60 legacy paper pages to Codex rather than have the machine bulk-deepen them. New reads going forward use
> the machine's `read_paper_deep` / `ingest_paper` one-button modes; this P6 is purely for BACKFILLING the
> existing library.
> **Honest default:** un-touched skims STAY `reading-status: skimmed` (Tier S) — they are not broken, just
> shallow. Only deepen a paper when it needs to back a thesis citation or you want its full card.

---

## What "done" looks like for one paper
The page at `AI agent database/PhD-Research-OS/02-wiki/papers/<...>/<slug>.md` is rewritten to the
new `04-templates/paper.md` 0+3+1 structure, to the depth its `reading-status` declares, such that
`python 06-scripts/lint_vault.py` shows **no new READING_DEPTH warning** for that page. Graduation
(enforced by the lint check, WARN during migration):

| reading-status | sections that must be filled |
|---|---|
| `skimmed` (Tier S) | Stage 0 positioning · TL;DR · Pass 1 contract (5 C's + one-sentence contract) |
| `read` | + Pass 2 (claim→evidence table + method breakdown + results table) |
| `deep-read` / `cited` | + Pass 2b figure reading + Pass 3 appraisal + Stage 4 (typed relations + trend/opportunity) |

A paper that is only worth a skim KEEPS `reading-status: skimmed` and only needs Stage 0 + Pass 1 — do
NOT inflate depth. To deepen, the director sets the target `reading-status` in the work-order.

---

## Prioritization (which papers first)
Deepen in this order; skip anything that does not need it:
1. **Thesis-citable now** — pages with `relevance: direct` that already back (or will back) a claim, and any
   page whose `reading-status` is `read`/`deep-read`/`cited` but predates the new template (their depth is
   there, it just needs reshaping into the new sections).
2. **Active-direction baselines** — the numeric baselines / method anchors of the live direction
   (e.g. `iac-sota/`, `peft-adapters/`, `medical-sam-adaptation/`, `continuity-topology/`).
3. **Novelty-threat / comparator pages** — the bespoke role-driven pages (P2T-comparators, novelty
   threats) — reshape into the card while preserving their role-specific findings.
4. Everything else stays `skimmed` until pulled.

The director (or a quick machine scan) produces the concrete batch list from
`02-wiki/papers/**` by `relevance` + `reading-status`; this file is the per-paper contract.

---

## THE WORK-ORDER TEMPLATE (one per paper — paste into `/codex:rescue`)

```
## 任务目标
Re-read the paper "<TITLE>" and rewrite its vault page to the new 0+3+1 research-card template,
to reading-status depth = <skimmed | read | deep-read>.

## 上下文摘要 (Codex has no prior context — this is all it gets)
- This is the PhD-Research-OS markdown knowledge vault (System D). The page already exists; you are
  UPGRADING its shape, not creating a new page. Keep its slug + frontmatter identity.
- The NEW page structure is defined by the template at:
  AI agent database/PhD-Research-OS/04-templates/paper.md
  Mirror its section headings + the inline "<!-- required: ... -->" graduation markers EXACTLY.
- Read the PAPER ITSELF (PDF/source under 01-raw/ or the source_ref in the page frontmatter) — by
  reference, do not paste long source passages into the page.
- HONESTY: never invent a number, a citation, a slug, or a figure reading. If you cannot confirm a
  field, leave it blank/❓ rather than fabricate. Every claim in the Pass-2 ledger must anchor to a
  real table/figure/section you actually read, with the directness + risk columns filled.
- The appraisal (Pass 3) is a READING AID — score the 7 dimensions and list weaknesses, but never
  write a "verdict / accept / reject" — you are appraising, not deciding.

## 可改文件范围
- ONLY this one page: AI agent database/PhD-Research-OS/02-wiki/papers/<...>/<slug>.md
- You MAY add typed stub pages for any NEW method/dataset/model the paper introduces (per the vault's
  fan-out convention) IF the director's work-order says so; otherwise leave links as [[slug]] to be
  created later.

## 禁改文件范围
- Any OTHER vault page, any 00-system/ / 05-registry/ / 06-scripts/ file, anything in research_agent_teams/.
- Do NOT change the page's slug, `type:`, `evidence-class:`, or downgrade its `reading-status`.
- Do NOT promote/freeze anything (the vault's /promote-to-vault gate is the director's, not yours).

## 验收标准
1. The page's body matches the new template's sections for its reading-status depth (graduation table above).
2. Frontmatter carries the Stage-0 fields: paper-type, read-purpose, reading-objective (+ the existing
   reading-status, relevance).
3. The Pass-2 claim→evidence table (if depth ≥ read) has every row anchored (Fig/Table/§) with
   directness + supports? + risk filled.
4. No fabricated content; unknowns left explicitly blank.

## 必跑验证项
- From the vault root: `python 06-scripts/lint_vault.py 2>&1 | grep "<slug>"`
  → there must be NO `READING_DEPTH` warning for this page (other advisory warnings like VOCAB_TAG are fine).

## 返回格式
1. 本轮完成内容（一句话）
2. 修改文件列表
3. 改动说明（which passes filled, to what depth）
4. 验证结果（the lint grep output for this slug）
5. 未完成项 / 风险项（fields left blank for lack of evidence)
```

---

## Worked example (a real page to start with)
Target: `02-wiki/papers/iac-sota/u-mamba2-2025.md` (the primary numeric baseline; currently a thin skim).
Fill in the template above with `<TITLE>` = the U-Mamba2 paper title, depth = `read` (it's a baseline the
thesis cites, so it earns Pass-2 method + claim-evidence table; figure reading + full appraisal optional
unless promoted to `deep-read`). Same pattern for `peft-adapters/hu-2021-lora.md`,
`continuity-topology/shit-2021-cldice.md`, and the `medical-sam-adaptation/` pages.

---

## Boundary reminder
- This backfill is OPTIONAL and director-paced — the library is fully functional with most pages at
  `skimmed`; deepening is on-demand.
- The machine's NEW reads (`read_paper_deep` / `ingest_paper`) already produce the card shape directly —
  P6 only exists because the ~60 legacy pages predate the upgrade.
