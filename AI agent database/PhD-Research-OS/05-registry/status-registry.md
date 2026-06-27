---
type: registry
registry-of: status
updated: 2026-06-07
---

# Status Registry

Authoritative list of recognized `status:` values plus type-specific status overlays.

---

## Universal `status:` (every knowledge-note page)

| status | Meaning | Typical next state |
|--------|---------|-------------------|
| `draft` | Just created, body incomplete or unverified | → `active` after review |
| `active` | Curated, in-use, linked into the workflow | → `deprecated` or `parked` |
| `completed` | Finished work — primarily for `experiment`, `meeting`, `decision`, `run` types where the work has a definite end | (terminal — never delete) |
| `deprecated` | Superseded by another page; kept for history | (terminal — never delete) |
| `parked` | Paused / deferred / blocked | → `active` when unblocked, or `deprecated` |

### Universal status rules

1. **Never delete** a page — mark `status: deprecated` with a note pointing at the replacement
2. A `deprecated` page must list the replacing page's slug in the body
3. A `parked` page must state the blocker in a `## Blockers` section
4. LINT flags pages stuck in `draft` longer than 30 days
5. LINT flags `deprecated.base` view periodically — keep archive clean

---

## Type-specific status overlays

Some types carry a domain-level status field beyond the universal `status:`. Both fields coexist; they measure different things.

### `paper.reading-status`

Reading-pass progress:

| value | meaning | citable? |
|---|---|---|
| `to-read` | Identified, not yet read | no |
| `skimmed` | Abstract + figures + conclusion only | indicative only |
| `read` | First-pass full read | yes with caveat |
| `deep-read` | 3-pass full read with notes | yes |
| `cited` | Used in a thesis claim | yes |
| `deprecated` | Superseded by a later paper | history only |

#### Allowed transitions (the granularity ladder — added 2026-06-07)

```
to-read   → skimmed | deprecated
skimmed   → read | deprecated          (promote only via the deep-read worklist)
read      → deep-read | deprecated
deep-read → cited | deprecated
cited     → deprecated                 (only if a later paper supersedes it)
```

**Forbidden:** implicit rung-skipping (`to-read → deep-read` without passing through) and silent demotion (`deep-read → skimmed`). A paper whose direction is abandoned KEEPS its earned depth — see "Direction pivot" below.

#### Granularity-controller drive rules (the zoom lens)

This is the **driver** that turns `reading-status` from a hand-set label into a controlled dial — the counterpart of what `result-status` already has. The zoom moves from "scan trends" (coarse) to "read implementation" (fine):

1. **`relevance: direct` ⇒ deep-read CANDIDATE**, not automatic deep-read. The paper enters the *deep-read worklist* (`03-views/11-granularity-worklists.base`). It is promoted to `read`/`deep-read` only when **(a)** the director commits to that thread's direction, or **(b)** the director hand-picks it from the worklist. (Rationale: when most papers in a library are `direct`, auto-promoting all of them would light the whole library on fire, not zoom.)
2. **`relevance: background` ⇒ capped at `skimmed`.** Background establishes context, not implementation; deep-reading it is over-zoom. LINT flags `background ∧ deep-read` as a likely over-read.
3. **`relevance: adjacent` ⇒ promote on demand only** (director flag or thesis-write pull).
4. **Per-thread deep-read soft cap ≈ `ceil(sqrt(thread_size))`** (e.g. a 12-paper thread → ≤4 deep-reads). A soft advisory, never a hard block — encodes "deliberately ignore most, deep-read a sqrt-small core".
5. **Direction commit is the director's call, always.** AI emits the "this thread looks ready / saturated" signal; the human decides which direction to zoom into. Setting an `idea` to `idea-status: greenlit` is the commit signal — it moves that direction's `direct` papers from candidate to deep-read target.

#### Section graduation (the reading-status → required body sections map — added 2026-06-26, paper-reading-upgrade)

`reading-status` is also a **body-completeness contract**: a paper page must carry the body sections its depth earns (cumulative — each rung inherits the rung below it). The section template is `04-templates/paper.md`.

| reading-status | required body sections (cumulative) |
|---|---|
| `to-read` | (stub; none) |
| `skimmed` | Stage-0 positioning · Pass-1 (TL;DR + paper contract + key contributions) |
| `read` | + Pass-2 (claim→evidence table + method breakdown + results table) |
| `deep-read` | + Pass-2 figure reading + Pass-3 appraisal checklist + Stage-4 (typed relations + trend) |
| `cited` | same as `deep-read` (already gated for citation by `render_claim_chain.py`) |
| reproduce-level (a rigor flag on `deep-read`, not a status) | + reproducibility checklist + per-term loss filled |

**LINT enforces this** (`06-scripts/lint_vault.py`, check `READING_DEPTH`): heading match is tolerant (distinctive words, case-insensitive) so renaming a heading does not false-fail. It is emitted as a **WARN during the legacy-page migration window** so the ~60 pre-upgrade pages do not fail-all; it is designed to **HARDEN to ERROR at `reading-status >= read`** once the legacy pages are re-deepened. A companion check `READING_STATUS_ENUM` (WARN) flags any `reading-status` outside the enum above. Don't fake depth — a deliberately shallow page keeps a shallow `reading-status`.

#### Promotion audit

Every reading-status promotion appends one line to the paper's `## Reading log` section:
`YYYY-MM-DD: <old> → <new> — promoted by <director-flag | direction-commit | thesis-pull>`.
Append-only, matches the evidence-contract labelling philosophy.

#### Direction pivot (abandoning a direction)

When the director parks a direction (`idea-status: greenlit → parked`), papers already at `read`/`deep-read` **keep their depth** (the knowledge isn't wasted) — only their worklist claim is released, and a `Reading log` line records `direction parked YYYY-MM-DD`. Depth is **never silently demoted**.

#### Zoom = rigor (crown-jewel guard)

Zooming out only lowers the model tier and scout depth of the COARSE pass; it **never** lowers the freeze-gate / citation-gate / evidence-contract below the contract floor (global CLAUDE.md §3.7). A coarse (`skimmed`) paper can NEVER back a thesis citation — `render_claim_chain.py` already requires `reading-status ∈ {read, deep-read, cited}` AND a non-ASSUMPTION evidence-class.

### `claim.claim-status`

Thesis-claim epistemic state:

| value | meaning | citable in thesis? |
|---|---|---|
| `draft` | Proposed, no evidence yet | no |
| `supported` | At least one `[[result-slug]]` with `can-cite-thesis: true` | partially |
| `contested` | Supported AND contradicted by evidence | discussion only |
| `validated` | Multiple supports, no live contradictions, audit pass | yes |
| `thesis-ready` | Validated + paragraph-draft ready + chapter assigned | yes |
| `deprecated` | Replaced by another claim | history only |

### `result.result-status`

Atomic benchmark row validity (6 values, mutually exclusive — citation gate):

| value | meaning | `can-cite-thesis` | thesis cell allowed? |
|---|---|---|---|
| `frozen` | Reviewed; canonical eval frame; passes leakage + fairness audits | `true` | yes — direct value |
| `provisional` | Run completed, metrics generated, no review yet | `false` | only with verbatim "(provisional)" qualifier |
| `diagnostic-only` | Smoke / debug / sanity-check; never benchmark evidence | `false` | no |
| `invalid` | Run produced a number but a PM violation discovered | `false` | only with "(invalidated by <PM>)" qualifier |
| `superseded` | Run was correct at its time; replaced by later corrected run | `false` | no — quote the replacement |
| `missing-audit` | Completed and looks healthy, but a required cross-check is pending | `false` | only with "(subject to <audit>)" qualifier |

#### Allowed transitions
```
provisional   → frozen | invalid | missing-audit
missing-audit → frozen | invalid
frozen        → superseded | invalid (rare; requires PM + log entry)
diagnostic-only → (terminal)
invalid       → (terminal)
superseded    → (terminal)
```

**Forbidden:** `frozen → provisional`, `invalid → frozen`. Re-running a fix produces a NEW row, not a status flip.

#### Companion fields (locked)

`can-cite-thesis` (derived bool) · `eval-frame` · `metric-source` · `leakage-audit` · `fairness-audit` · `superseded-by` · `invalidated-by` · `evidence-artifact`.

#### Derived field rule
```
can-cite-thesis  ==  (result-status == "frozen")
                AND  (leakage-audit  == "pass")
                AND  (fairness-audit == "pass")
```
LINT verifies on every result page. Manual override forbidden.

### `decision.decision-status`

ADR state:

| value | meaning |
|---|---|
| `proposed` | Drafted, awaiting human sign-off |
| `accepted` | Locked; supersedes prior decisions on the same topic |
| `rejected` | Considered, declined; preserved for history |
| `superseded` | Was accepted, replaced by a later decision |
| `revisit-needed` | Conditions changed; pending re-decision |

### `process-memory.pm-status`

PM lifecycle:

| value | meaning |
|---|---|
| `draft` | Just discovered; not yet validated against existing rules |
| `active` | Confirmed; cited by other pages |
| `confirmed` | Active for ≥30 days, multiple references, durable |
| `retired` | No longer applicable (e.g., upstream code change made it moot) |

### `idea.idea-status`

Hypothesis pipeline:

| value | meaning |
|---|---|
| `preset` | Captured but not yet considered |
| `in-consideration` | Actively reasoning about it |
| `greenlit` | Decision to pursue, awaiting experiment |
| `shipped` | Implemented and tested |
| `parked` | Deferred indefinitely |

### `risk.risk-status`

Risk lifecycle:

| value | meaning |
|---|---|
| `open` | Identified, no mitigation in place |
| `mitigated` | Mitigation strategy active |
| `accepted` | Acknowledged, not mitigated; accepted as residual |
| `invalidated` | Conditions changed; risk no longer applies |

---

## Status extension ritual

To add a new universal status value:
1. Add a row to the universal table above
2. Update `04-templates/*.md` that enumerate statuses
3. Migration sweep across affected pages

To add a new type-specific status overlay:
1. Add a section here with the value table
2. Update the matching template under `04-templates/`
3. Update `05-registry/type-registry.md` per-type field row

Prefer adding a type-specific overlay over extending the universal `status:` — the universal list should stay small (5 values).
