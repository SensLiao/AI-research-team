---
type: registry
registry-of: evidence-classes
updated: 2026-05-01
---

# Evidence Registry

Authoritative list of evidence classes used in the `evidence-class:` frontmatter field and in inline citations per `00-system/evidence-contract.md`.

---

## 8 evidence classes

| Class | Source artifact | Inline citation form | When required |
|---|---|---|---|
| `CODE-LIVE` | A file `Read` in this session, line citation | `<absolute_path>:<line_range>` | Any function / class / attribute / module / file / parameter / config-key name |
| `VAULT-CITE` | A `02-wiki/` page `Read` this session | `[[slug]] §<heading>` | Any project rule, decision, or canonical synthesis |
| `EXP-RESULT` | A metrics / log file opened this session, gated through citation gate | `<path>` (file) or `<path>:<key>` (JSON) | Any benchmark / training / inference number |
| `PAPER-CITE` | A `02-wiki/papers/` page `Read` this session | `[[paper-slug]] §<section>` or DOI | Any external claim |
| `DATA-CITE` | A `02-wiki/datasets/` page `Read` this session | `[[dataset-slug]] §<section>` | Dataset size, label set, split, or hash |
| `MEETING-CITE` | A `02-wiki/meetings/` page `Read` this session | `[[meeting-slug]] §<section>` | Supervisor instruction or team decision from a meeting |
| `DECISION-CITE` | A `02-wiki/decisions/` page `Read` this session | `[[dec-NNNN-slug]] §<section>` | Reference to a prior locked decision |
| `ASSUMPTION` | None — inferred / cannot verify | Prefix line `ASSUMPTION:` + invalidation condition | Default when no other class applies |

---

## Default rule

Any unlabeled claim is **`ASSUMPTION`**.

The agent must:
1. Label every fact when reasoning aloud or writing user-facing text
2. Treat `ASSUMPTION` as a flag for "go verify if this is load-bearing"
3. Convert `ASSUMPTION` → typed class as soon as a verification command is run

---

## Frontmatter usage

Some pages benefit from declaring their primary evidence backing in frontmatter:

```yaml
evidence-class: CODE-LIVE   # this page is grounded in a specific source file
```

or for multi-source pages:

```yaml
evidence-class: [VAULT-CITE, EXP-RESULT]
```

This is **optional** but useful for filtering in `.base` views.

---

## Confidence calibration

The `confidence:` frontmatter field is set primarily by the strongest evidence class on the page:

| Strongest evidence class | Suggested confidence |
|---|---|
| `CODE-LIVE` + `EXP-RESULT` (both live) | `high` |
| `CODE-LIVE` or `EXP-RESULT` (one live) | `high` |
| `VAULT-CITE` only (canonical rule) | `high` |
| `PAPER-CITE` deep-read only | `medium` to `high` |
| `PAPER-CITE` skimmed only | `medium` |
| `DECISION-CITE` only (no fresh evidence) | `medium` |
| `MEETING-CITE` only (one source) | `medium` |
| `ASSUMPTION` dominant | `low` or `unverified` |

This is heuristic, not enforced. Override when reasoning differs.

---

## Extension policy

Evidence classes should stay small and orthogonal. Before adding a 9th class, ask:
- Does this represent a fundamentally new evidence channel (not a sub-category)?
- Will the 9th class be invoked in ≥10% of citations?
- Is there a real risk of conflating it with an existing class?

If yes to all three, register it here, update `00-system/evidence-contract.md` Part 1, and update `00-system/AGENTS.md` §3.

Plausible future classes:
- `BENCHMARK-CITE` — reference to a third-party leaderboard / shared benchmark (currently subsumed under `PAPER-CITE`)
- `INTERVIEW-CITE` — qualitative research transcripts (only relevant for HCI / mixed-methods work)
- `SIMULATION-CITE` — deterministic computational simulations (currently subsumed under `EXP-RESULT`)
