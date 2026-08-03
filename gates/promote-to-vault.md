---
name: promote-to-vault
kind: director-command-gate
invocation-policy: explicit-top-level-user-skill
disable-worker-invocation: true
stage: post-RECORD (promotion)
reads: promotion_candidate (runs/<run>/inbox/)
writes: System-D vault page + promotion_record + adr
---

# /promote-to-vault — Director-command gate

## Purpose

The `/promote-to-vault` gate is the **only path knowledge enters System D** (the research database,
the crown jewels). It is director-command-only: the primary assistant may execute it only when the
top-level user explicitly invokes this source command. Workers, subagents, research modes, schedules,
and automatic completions cannot invoke it. The gate **re-derives** status from the actual audits and
writes a re-derived page — it never trusts a self-claim.

## Invariant (non-negotiable)

**A research worker never promotes its own work, and a completed mode never self-freezes.**

A worker stages a `promotion_candidate` into `runs/<run>/inbox/` carrying **references** (path+sha) to
the real audit artifacts — never a self-claimed status. The candidate has **no `human_freeze` field**;
that flag is supplied only by this director-command gate after an explicit top-level user invocation.
`promote.py` then reads the ACTUAL referenced audits
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

## Presentation and authorization

The user explicitly invokes `/promote-to-vault` after reviewing the candidate. That call is the director
authorization; the primary handler passes `--director-invoked` and the promotion record records
`authorization_basis: explicit-director-command`. The legacy exact environment variables remain available
for external CLI workflows. No ordinary research run, worker, subagent, or scheduler may manufacture this
invocation context. See the source-command skill for the enforcement policy.

## What the director-command handler does after the explicit user call

1. Inspect the `promotion_candidate` at `runs/<run>/inbox/promotion-candidate-<slug>.json` and the run's
   evidence (result, leakage/sanity verdict, fairness verdict, adversarial-reviewer report).
2. Run the deterministic gate with `--director-invoked`. `promote.py`:
   - resolves the candidate's audit references, extracts the native verdicts,
   - re-derives `frozen` / `can-cite-thesis` / `admissible`,
   - on **admit**: writes `<vault>/02-wiki/<type>/<slug>.md` with the **re-derived** frontmatter
     (`status: completed`, `result-status: frozen`, `can-cite-thesis: true`, `leakage-audit: pass`,
     `fairness-audit: pass`), then appends `00-system/index.md` + `07-logs/log.md` (vault write discipline),
   - on **reject**: writes nothing into the vault.
3. The gate emits a `promotion_record` (the audit trail: admissible, authorization basis, re-derived status, reasons, vault_path)
   to `runs/<run>/inbox/promotion-record-<slug>.json` + a `promote` ledger event.
4. Record the promotion decision as an `adr`:
   - `decision_id`: a new `ADR-NNNN`.
   - `question`: `"Promote run <run_id> result <slug> into System D?"`
   - `options`: `["PROMOTE-FROZEN", "HOLD-PROVISIONAL", "REJECT"]`.
   - `chosen_option`, `reason` (cite the re-derivation), `status: "approved"`, `approved_by: "director"`,
     `approved_at`: ISO-8601.
5. Validate the `adr` against `adr.schema.json` and the `promotion_record` against
   `promotion_record.schema.json` before proceeding.

## Hard rule on the derivation ↔ write relationship

`admissible == true` is structurally tied (schema `allOf` + `promote.py`) to
`rederived_result_status == "frozen"` AND `rederived_can_cite_thesis == true` AND a written `vault_path`.
The director can never produce an "admitted but provisional" record, and the gate never writes the vault
on a reject. `can-cite-thesis` is written from the derivation, never from input (schema-contract §6
`DERIVED_INCONSISTENT`).

## Director-reviewed Markdown admission lane

The frozen-result lane above remains unchanged. A separate document-admission lane exists for a final,
human-readable `paper`, `synthesis`, or `idea` Markdown artifact that the director has reviewed and wants
to retain in System D before its scratch run is cleaned up.

It is not a result promotion. The document gate SHA-verifies the source Markdown, copies the complete
readable body into a type-conformant vault page, records the source path and hash, and updates the vault
navigation. It never creates `result-status`, `can-cite-thesis`, a metric claim, a global novelty
certificate, or a clinical-validity claim.

The explicit top-level user call authorizes the batch; the primary source-command handler runs:

```powershell
python -m research_agent_teams.tools.promote_gate --document-batch <batch-directory> --admission-id <admission-id> --workspace-root . --decided-by director --director-invoked
```

The batch preflights every source SHA, project binding, slug collision, and live vault-page contract before
writing any page, so a failed file cannot leave a partially migrated archive. The legacy environment
capability remains supported for external automation but is not required for a direct user skill call.

## Boundaries

- The gate is the **only** writer into `PhD-Research-OS/` — fenced agents are blocked from the vault by
  `permission-scope-guard` and stage only into `runs/<run>/inbox/`.
- The gate **reads** the DB contracts (status-registry derivation, evidence-contract, 3-layer boundary)
  and never modifies them (schema-contract §9.9 crown jewels).
- Slugs are lowercase-kebab and never renamed (schema-contract §5).
