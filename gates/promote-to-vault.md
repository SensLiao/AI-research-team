---
name: promote-to-vault
kind: human-gate
disable-model-invocation: true
stage: post-RECORD (promotion)
reads: promotion_candidate (runs/<run>/inbox/)
writes: System-D vault page + promotion_record + adr
---

# /promote-to-vault — Director Gate (human-only; model never invoked)

## Purpose

The `/promote-to-vault` gate is the **only path knowledge enters System D** (the research database,
the crown jewels). It is **human-only**: `disable-model-invocation: true` means the model is never
invoked during this gate. The director promotes a vetted run artifact into the vault; the gate
**re-derives** its status from the actual audits and writes a re-derived page — it never trusts a
self-claim.

## Invariant (non-negotiable)

**The machine never promotes its own work, and never self-freezes.**

A worker stages a `promotion_candidate` into `runs/<run>/inbox/` carrying **references** (path+sha) to
the real audit artifacts — never a self-claimed status. The candidate has **no `human_freeze` field**;
that flag is supplied only here, by the director. `promote.py` then reads the ACTUAL referenced audits
and re-derives:

```
frozen          = human_freeze AND reviewer==APPROVE-FREEZE AND leakage==PASS AND fairness==pass
                  AND source-status not terminal
can-cite-thesis = (frozen) AND leakage==PASS AND fairness==pass        # derived; manual override forbidden
admissible      = frozen AND can-cite-thesis                            # provisional ⇒ NOT promotable
```

The machine's `result_summary` ceiling is const `provisional` (schema-enforced), so the only path to a
`frozen`, citable vault page is a **human freeze through this gate** with the audits actually passing.
A forged self-claim (a candidate that says `can_cite_thesis: true` while its real leakage audit is
`BLOCK`) is **ignored by construction** — re-derivation recomputes from the referenced audits and
rejects. This is the crown-jewel red line: a more capable model still cannot promote or cite its own work.

## What the director does

1. Open the `promotion_candidate` at `runs/<run>/inbox/promotion-candidate-<slug>.json` and skim the run's
   evidence (the result, the leakage/sanity verdict, the fairness verdict, the adversarial-reviewer report).
2. Decide whether to **freeze** this result (the human freeze act). If not freezing, do not invoke the gate —
   the result stays `provisional` in the run-store.
3. Run the gate. `promote.py`:
   - resolves the candidate's audit references, extracts the native verdicts,
   - re-derives `frozen` / `can-cite-thesis` / `admissible`,
   - on **admit**: writes `<vault>/02-wiki/<type>/<slug>.md` with the **re-derived** frontmatter
     (`status: completed`, `result-status: frozen`, `can-cite-thesis: true`, `leakage-audit: pass`,
     `fairness-audit: pass`), then appends `00-system/index.md` + `07-logs/log.md` (vault write discipline),
   - on **reject**: writes nothing into the vault.
4. The gate emits a `promotion_record` (the audit trail: admissible, re-derived status, reasons, vault_path)
   to `runs/<run>/inbox/promotion-record-<slug>.json` + a `promote` ledger event.
5. Record the promotion decision as an `adr`:
   - `decision_id`: a new `ADR-NNNN`.
   - `question`: `"Promote run <run_id> result <slug> into System D?"`
   - `options`: `["PROMOTE-FROZEN", "HOLD-PROVISIONAL", "REJECT"]`.
   - `chosen_option`, `reason` (cite the re-derivation), `status: "approved"`, `approved_by: "director"`,
     `approved_at`: ISO-8601.
6. Validate the `adr` against `adr.schema.json` and the `promotion_record` against
   `promotion_record.schema.json` before proceeding.

## Hard rule on the derivation ↔ write relationship

`admissible == true` is structurally tied (schema `allOf` + `promote.py`) to
`rederived_result_status == "frozen"` AND `rederived_can_cite_thesis == true` AND a written `vault_path`.
The director can never produce an "admitted but provisional" record, and the gate never writes the vault
on a reject. `can-cite-thesis` is written from the derivation, never from input (schema-contract §6
`DERIVED_INCONSISTENT`).

## Boundaries

- The gate is the **only** writer into `PhD-Research-OS/` — fenced agents are blocked from the vault by
  `permission-scope-guard` and stage only into `runs/<run>/inbox/`.
- The gate **reads** the DB contracts (status-registry derivation, evidence-contract, 3-layer boundary)
  and never modifies them (schema-contract §9.9 crown jewels).
- Slugs are lowercase-kebab and never renamed (schema-contract §5).
