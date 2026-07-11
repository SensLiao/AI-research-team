# AERS SOP Packs For RAT

This directory records how metadata-approved Auto-Empirical-Research-Skills
entries are absorbed into Research Agent Teams.

The default catalog source is now the RAT-owned internal snapshot at
`research_agent_teams/agents/references/aers-catalog`. The external
`Auto-Empirical-Research-Skills/` checkout is optional and used only when
refreshing or re-auditing upstream metadata with `--aers-root`.

The rule is deliberately conservative:

- AERS entries are references and SOP hints, not executable RAT capabilities.
- `safe_reference` candidates may enter the appropriate SOP pack.
- `review_required` candidates require `/aers-reference-approve` before a run
  inbox can reference them.
- `do_not_use` candidates stay blocked.
- Child AERS `SKILL.md` bodies are not read by default.
- No AERS pack writes `PhD-Research-OS`; promotion still requires
  `/promote-to-vault`.

## Packs

| Pack | RAT Stage | Primary Agents |
| --- | --- | --- |
| `aers-literature-citation-pack` | DISCOVER | `aers-sop-curator`, `literature-search-strategist`, `bibliography-validator` |
| `aers-ideation-pack` | IDEATE | `hypothesis-generator`, `idea-tournament-ranker`, `idea-evolver` |
| `aers-data-design-pack` | DESIGN | `data-wrangling-auditor`, `data-protocol-designer`, `dataset-split-planner` |
| `aers-reproducibility-pack` | EXECUTE | `reproducibility-packager`, `repro-runner`, `experiment-journaler` |
| `aers-analysis-robustness-pack` | ANALYZE | `benchmark-evidence-auditor`, `variance-analyzer`, `result-sanity-checker` |
| `aers-peer-review-submission-pack` | VERIFY | `submission-guideline-scout`, `bibliography-validator`, `adversarial-reviewer` |
| `aers-writing-communication-pack` | REPORT | `manuscript-polish-editor`, `synthesis-writer`, `quality-controller` |

## Operating Pattern

1. Generate the integration plan:

   ```powershell
   python -m research_agent_teams.tools.aers_skill_integration_planner --out .planning/aers-skill-integration-plan.json
   ```

2. Stage any candidate that needs run-specific review:

   ```powershell
   python -m research_agent_teams.tools.external_skill_review stage `
     --query "<topic>" `
     --intended-use "<why this run needs the reference>" `
     --rat-stage <STAGE> `
     --out <registry.json>
   ```

3. The director may approve a reference with:

   ```powershell
   python -m research_agent_teams.operate aers-reference-approve `
     --registry <registry.json> `
     --review-id <id> `
     --decision approve `
     --reviewed-by director `
     --decision-note "reference-only approved" `
     --confirm-review-id <id>
   ```

4. Agents use the approved reference as a method hint. They still produce native
   RAT artifacts and pass native RAT gates.
