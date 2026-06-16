---
description: "Director-only human gate — promote a vetted run result into the PhD-Research-OS vault. Re-derives frozen / can-cite-thesis from the REAL sha-verified audits; the model can never self-promote."
argument-hint: "<run-id> <candidate-path>"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /promote-to-vault — Director Gate (human-only)

> Full spec & invariants: `research_agent_teams/gates/promote-to-vault.md`.
> `disable-model-invocation: true` — only the director runs this; the model is never invoked.

The ONLY path knowledge enters System D (the crown jewels). The gate **re-derives** frozen /
can-cite-thesis from the ACTUAL referenced audit artifacts (sha256-verified) — it never trusts a
self-claim — writes the re-derived page on admit, and records a tamper-evident `promote` ledger event.

## Steps (you, the director)

1. Confirm the staged candidate `runs/<run-id>/inbox/<candidate>.json` references the real audits
   (leakage / fairness / reviewer) by `path` + `sha256`.
2. **Certify the freeze out-of-band** — this is what proves a HUMAN froze the result. The model must
   NEVER set this variable (same red line as `RAT_EXECUTE_AUTHORIZED` for GPU runs):
   ```powershell
   $env:RAT_PROMOTE_AUTHORIZED = "<run-id>"
   ```
3. Run the deterministic gate:
   ```powershell
   python -m research_agent_teams.tools.promote_gate --run-id <run-id> --candidate runs/<run-id>/inbox/<candidate>.json --decided-by director
   ```
4. Read the printed `promotion_record`. `admissible: true` ⇒ the page was written into `02-wiki/`, index.md
   + log.md updated, and a `promote` event appended to the run ledger. `admissible: false` ⇒ nothing was
   written; `reasons` say why (no freeze, reviewer BLOCK, leakage/fairness fail, sha mismatch, unsafe candidate).
5. Clear the authorization when done: `Remove-Item Env:RAT_PROMOTE_AUTHORIZED`.

Without step 2, `human_freeze=False`, the provisional ceiling holds, and the result is structurally
non-promotable — exactly as designed. A reject is honest: the crown jewels stay untouched.
