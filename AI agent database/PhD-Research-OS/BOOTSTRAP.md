# BOOTSTRAP — Instantiate this template for a new research topic

> **Read this if you are an LLM agent or a human about to turn this skeleton into a working vault.**
>
> The goal: given a research topic + a few intake answers, produce a vault that is immediately usable for ingest, experiments, and writing — without rebuilding the schema each time.

---

## §1 — How instantiation works

```
PhD-Research-OS-Template/  (this folder)
        │
        │   1. cp -r → <your-research-root>/<project-slug>/
        │
        ▼
Your project vault                 ── 2. fill 12 intake answers ──▶  bootstrap-intake.yml
        │
        │   3. run scripts/bootstrap.py  (or paste intake to an LLM)
        │
        ▼
Customized vault:
  - 00-system/hot.md              ← initial state cache
  - 00-system/index.md            ← empty section headers, ready
  - 05-registry/project-registry  ← your project + sub-projects
  - 05-registry/contribution-registry ← your C1, C2, ... thesis contributions
  - 02-wiki/sources/project-brief.md     ← from intake
  - 02-wiki/sources/research-questions.md ← from intake
  - 02-wiki/decisions/dec-0001-scope.md   ← initial scope decision
  - 07-logs/log.md                ← initial INGEST entry
```

The skeleton is the same for every topic. The intake fills the variable slots.

---

## §2 — The 12 intake questions

Answer these in `bootstrap-intake.yml` (copy from `bootstrap-intake.template.yml`) before touching the vault.

```yaml
# bootstrap-intake.yml

# 1. What is the project slug? (lowercase-kebab, no spaces)
project_slug: ""

# 2. What is the human-readable project title?
project_title: ""

# 3. Phase: undergraduate-thesis | masters-thesis | phd-chapter | phd-program | postdoc | independent
phase: ""

# 4. What is the supervisor / advisor name (if any)?
supervisor: ""

# 5. Domain (1-3 keywords): e.g., medical-imaging, nlp, robotics, hci
domain: []

# 6. Primary research questions (RQ1..RQn) — short imperative form
research_questions:
  - id: RQ1
    text: ""
  - id: RQ2
    text: ""

# 7. Intended thesis-level contributions (C1..Cn)
contributions:
  - id: C1
    text: ""
    serves_rq: [RQ1]
  - id: C2
    text: ""
    serves_rq: [RQ1]

# 8. Primary methods you will use / build (placeholder; can grow)
methods_planned:
  - ""

# 9. Primary datasets / corpora (placeholder; can grow)
datasets_planned:
  - ""

# 10. Reproducibility commitment level: full | partial | minimal
# (full = git commit + container digest + data hash + env lock for every run)
# (partial = git commit + env lock only)
# (minimal = git commit only)
reproducibility_level: ""

# 11. Citation gate strictness: strict | moderate | lenient
# (strict = can-cite-thesis requires frozen + leakage-pass + fairness-pass + reproducibility-pass)
# (moderate = frozen + leakage-pass + fairness-pass)
# (lenient = frozen only)
citation_gate: ""

# 12. Stakeholders the vault must be readable to (besides the user)
# (informs writing tone, language, naming)
stakeholders: []
```

---

## §3 — Bootstrap procedure (LLM agent version)

If you are an LLM agent reading this to instantiate the vault, do the following in order:

### Step 1 — Validate intake

- Read `bootstrap-intake.yml`.
- Confirm all 12 fields are filled. If any are empty, ask the human for the missing ones.
- Validate `project_slug` is lowercase-kebab.
- Validate at least 1 RQ and 1 contribution exist.

### Step 2 — Customize CLAUDE.md banner

In `00-system/CLAUDE.md`, replace the `{{PROJECT_TITLE}}` and `{{PROJECT_SLUG}}` placeholders with the intake values. Keep everything else unchanged.

### Step 3 — Fill registries

#### `05-registry/project-registry.md`
Add a row for this project with: slug, title, phase, supervisor, domain, status `active`, created (today's date).

#### `05-registry/contribution-registry.md`
Add one row per contribution with: id, text, serves_rq, status `proposed`.

### Step 4 — Seed wiki source pages

Create:
- `02-wiki/sources/project-brief.md` — type `source`, source-type `runbook`. Body: project title, phase, domain, supervisor, top-level scope, intake answers verbatim.
- `02-wiki/sources/research-questions.md` — type `source`, source-type `rules`. Body: every RQ from intake with placeholder for evidence pages.
- `02-wiki/decisions/dec-0001-scope.md` — type `decision`. Body: "Scope set at instantiation. Reproducibility = {{REPRO_LEVEL}}, citation gate = {{GATE_LEVEL}}." Status `accepted`. Date today.

### Step 5 — Initialize hot.md

Write `00-system/hot.md` with:
- `## Project status` — one paragraph, "Just instantiated. RQ1..RQn, C1..Cn open."
- `## Must-read pointers` — links to the 3 source pages just created
- `## Next active task` — "First raw ingest pending."
- `## Hard rules` — citation gate level, reproducibility level

Keep ≤500 words.

### Step 6 — Seed index.md

Write `00-system/index.md` with section headers for every type-folder under `02-wiki/`, each containing one bullet "(empty — first ingest pending)".

### Step 7 — Initialize log.md

In `07-logs/log.md`, append:
```
## YYYY-MM-DD

- BOOTSTRAP: vault instantiated for project [[<project_slug>]]. Intake fields filled. project-registry + contribution-registry seeded. 3 wiki source pages created. hot.md + index.md initialized.
```

### Step 8 — Print bootstrap summary to user

Print:
```
Vault [[<project_slug>]] instantiated.

Created:
- 00-system/hot.md
- 00-system/index.md
- 05-registry/project-registry.md (1 row)
- 05-registry/contribution-registry.md (N rows for C1..Cn)
- 02-wiki/sources/project-brief.md
- 02-wiki/sources/research-questions.md
- 02-wiki/decisions/dec-0001-scope.md
- 07-logs/log.md (BOOTSTRAP entry)

Next steps:
1. Drop your first PDF / transcript / dataset doc into 01-raw/<subfolder>/
2. Run /ingest <raw-path> to create the first wiki page
3. Read 00-system/agent-startup-router.md before any code or experiment work
```

### Step 9 — Stop

Do NOT begin actual research work in the same session as bootstrap. Bootstrap is its own session.

---

## §4 — Bootstrap procedure (human / no-agent version)

If you don't have an LLM agent to run §3, do it manually:

1. Copy `bootstrap-intake.template.yml` → `bootstrap-intake.yml` and fill all 12 fields.
2. Run `python 06-scripts/bootstrap.py bootstrap-intake.yml` (writes the 7 seed files).
3. Verify with `python 06-scripts/lint_vault.py` — should report 0 errors on a fresh bootstrap.
4. Commit: `git init && git add . && git commit -m "bootstrap: instantiate <project_slug>"`.

---

## §5 — What NOT to do during bootstrap

- ❌ Skip filling intake fields — empty registries cause downstream LINT failures
- ❌ Begin ingesting research papers before bootstrap completes — first ingest's `[[<project>-brief]]` link will dangle
- ❌ Modify `00-system/CLAUDE.md` semantics (only fill placeholders)
- ❌ Modify `00-system/evidence-contract.md` or `00-system/schema-contract.md` — these are the immutable kernel
- ❌ Add a new `type:` value during bootstrap — wait until you have ≥3 candidate pages

---

## §6 — 4-week landing plan (after bootstrap)

If this is your first time using a vault of this complexity, follow this:

### Week 1 — Skeleton & first ingests

- Bootstrap (§3 / §4)
- Ingest 5-10 of your most-cited papers into `02-wiki/papers/`
- Write the first 3 `concept` pages for the most central terms in your field
- First `/close` to refresh hot.md

**Goal**: vault is browsable, you can `[[grep]]` for any of your central concepts.

### Week 2 — Lint & integrity

- Run `python 06-scripts/lint_vault.py` — fix any orphans, broken links, missing source
- Install pre-commit hook: `pre-commit install`
- Set up `06-scripts/check_citation_gate.py` to run on every push

**Goal**: schema is enforced automatically, not by goodwill.

### Week 3 — Reproducibility layer

- For your first experiment: write `experiment` page + at least one `run` page + one `result` page + one `compute-budget` entry
- Lock your environment: `conda-lock` or `uv lock` → store in `08-artifact-manifests/env-locks/`
- Tag your code: every `run.git-commit` field must be a real SHA in your code repo

**Goal**: any past result can be reproduced from frontmatter alone.

### Week 4 — Writing layer

- Write your first `claim` pages — one per central thesis claim
- Build the claim-chain: each claim links to the result(s) supporting it
- Render a draft thesis section using `06-scripts/render_claim_chain.py`
- Set up the `03-views/00-thesis-citable-results.base` dashboard in Obsidian

**Goal**: from claim to thesis paragraph is one script invocation, not one writing session.

---

## §7 — Failure mode catalog

Common ways bootstrap or early-week work goes wrong, and the fix:

| Failure | Symptom | Fix |
|---|---|---|
| Schema drift | Agent invents a new `type:` not in registry | Reject; add to registry first via `05-registry/type-registry.md` extension ritual |
| Citation leak | A number from a `provisional` row appears in a thesis paragraph as fact | `lint_vault.py` should flag; if not, file a process-memory entry |
| Orphan ingest | A new wiki page has no inbound `[[link]]` | `/ghost` flags; add the page to a parent index or synthesis |
| Hot.md decay | hot.md > 600 words and full of historical narrative | Run `/close`; if it doesn't shrink, manually rewrite as state-snapshot |
| Decision amnesia | You can't remember why you chose method A over B | If you didn't write a `decision` page at the time, write one retroactively with `confidence: medium` |
| Reproducibility rot | A 6-month-old result can't be re-run | Compare current code SHA against `run.git-commit`; if env doesn't restore, file `negative-result` and rerun fresh |

---

## §8 — Multi-project setup (PhD with sub-projects)

If your PhD spans 3+ sub-projects, use the **meta-vault pattern**:

```
research-root/
├── meta-vault/                    ← cross-project methodology, PMs, agent rules
│   └── (a vault built from this template, but its 02-wiki/ holds only:
│        process-memory/, syntheses/, methods/, concepts/)
│
├── shared-paper-pool/             ← single source of truth for all PDFs
│   ├── pdfs/                      ← raw PDFs (one copy each)
│   ├── bibtex/                    ← exported BibTeX
│   └── paper-notes-symlink/       ← symlinks into project vaults
│
├── project-A/                     ← sub-project 1
│   └── (vault from this template)
│
├── project-B/                     ← sub-project 2
│   └── (vault from this template)
│
└── project-C/                     ← sub-project 3
    └── (vault from this template)
```

Rule: `process-memory` (PM) entries live in **meta-vault**, not in project vaults. PMs are reusable bug-class lessons; they shouldn't fragment per project. Project-specific `negative-result` entries stay in the project vault.

---

## §9 — Cross-references

- `00-system/CLAUDE.md` — vault operations contract
- `00-system/AGENTS.md` — agent entry contract
- `05-registry/type-registry.md` — authoritative type list
- `04-templates/*.md` — one template per type
- `06-scripts/bootstrap.py` — programmatic instantiation (optional)
- `06-scripts/lint_vault.py` — schema enforcement
