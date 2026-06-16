---
type: registry
registry-of: contributions
updated: 2026-05-01
---

# Contribution Registry

Authoritative list of thesis-level contributions (C1, C2, ...) for each project. Filled at bootstrap.

A "contribution" is a defensible novelty claim — something you will defend at the viva / dissertation defense. Most theses have 2-4 contributions. Some have 1 big one + 2 supporting. ≥6 is usually a sign you haven't yet narrowed the story.

---

## Active contributions

| project-slug | id | text | serves-rq | status | confidence | first-stated | last-revised |
|---|---|---|---|---|---|---|---|
| (empty — fill at bootstrap) | | | | | | | |

---

## Schema

| field | description |
|---|---|
| `project-slug` | from `project-registry.md` |
| `id` | `C1`, `C2`, ... — sequential, never renumbered |
| `text` | one-sentence contribution claim, paste-ready for the thesis intro |
| `serves-rq` | list of `RQ<n>` it answers |
| `status` | `proposed | committed | shipped | weakened | abandoned` |
| `confidence` | `high | medium | low` — how confident you currently are this contribution holds |
| `first-stated` | YYYY-MM-DD when first written |
| `last-revised` | YYYY-MM-DD when text last changed |

---

## Contribution status

| status | meaning | implication |
|---|---|---|
| `proposed` | Bootstrap-time aspiration | Frame all early experiments as testing this |
| `committed` | Locked after first solid evidence | All `claim`s for this contribution must point at it |
| `shipped` | Evidence chain complete + thesis paragraph drafted | Citation gate validates everything |
| `weakened` | Evidence weaker than expected; contribution narrowed | Update `text` field; log the narrowing |
| `abandoned` | Evidence collapsed; cannot defend | Move to deprecated; document in a `decision` |

---

## Rule: every claim links to a contribution

```yaml
# in any 02-wiki/claims/<slug>.md
supports-contrib: [C1]
```

LINT flags `claim` pages with empty `supports-contrib:`.

LINT flags contributions with no `claim` pointing at them after 60 days of `committed` status.

---

## Contribution status transitions

```
proposed → committed (first solid evidence + at least 1 claim with claim-status: supported)
proposed → abandoned (early kill — no evidence after N weeks)
committed → shipped (claim-status: thesis-ready + paragraph-draft filled)
committed → weakened (evidence weaker than hoped; narrow the text)
weakened → shipped (after narrowing succeeds)
weakened → abandoned (after narrowing also fails)
shipped → (terminal — never demote)
abandoned → (terminal — write postmortem in 02-wiki/syntheses/)
```

---

## Maintenance

- Review every supervisor meeting: are contributions still defensible given latest results?
- Touch `last-revised` whenever text changes
- Never silently rename a contribution — file a decision page explaining the change
