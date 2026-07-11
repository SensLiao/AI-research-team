# /aers-reference-approve

**Type:** human gate, `disable-model-invocation`

This gate lets the director approve or reject a staged AERS candidate as a
**reference-only** input to a RAT run.

## What Approval Means

An approved AERS reference may be exported into a run inbox as:

```text
inbox/external-skill-references/<review_id>.json
```

It remains constrained:

- `reference_allowed=true`
- `execution_allowed=false`
- `vault_write=false`
- `child_skill_body_read=false`
- `run_inbox_only=true`

Approval does **not** import the skill into RAT, execute it, read its child
`SKILL.md` body by default, or write the PhD-Research-OS vault.

## Deterministic Core

```powershell
python -m research_agent_teams.operate aers-reference-approve `
  --registry <registry.json> `
  --review-id <aers-review-id> `
  --decision approve `
  --reviewed-by director `
  --decision-note "approved as reference-only for this run" `
  --confirm-review-id <aers-review-id>
```

The typed `--confirm-review-id` must exactly match `--review-id`.

## Reject

```powershell
python -m research_agent_teams.operate aers-reference-approve `
  --registry <registry.json> `
  --review-id <aers-review-id> `
  --decision reject `
  --reviewed-by director `
  --decision-note "not suitable for this project" `
  --confirm-review-id <aers-review-id>
```

## Boundary

This gate never writes the vault. Optional run-inbox export uses the path guard
and refuses vault destinations.
