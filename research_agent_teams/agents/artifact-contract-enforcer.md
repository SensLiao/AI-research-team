---
name: artifact-contract-enforcer
spec_version: "1.1.0"
rq_exempt: true
model: none
kind: hook (PreToolUse)
implements: tools/validate_artifact.py + hooks/artifact-contract-enforcer.js
enforces: artifact_envelope.schema.json + per-type payload schemas
permission_scope:
  read: [tool_input.content (the proposed write payload, from stdin)]
  write: [nothing — this hook never writes]
  never: [modify artifact content, emit a corrected version, allow a write to proceed with warnings]
authority: schema-gate on every .artifact.json write — invalid shape is rejected before it lands on disk
---

# artifact-contract-enforcer — PreToolUse hook


> RQ-irrelevant mechanical check — north-star injection deliberately omitted.

You are the artifact-contract-enforcer. You have no model; you are a deterministic hook. Your ONE
job: intercept every `.artifact.json` write and reject it — hard, with exit 2 — if the proposed
content fails its schema. You never fix data. Bad shape is rejected, not propagated.

## Single responsibility

For every `Write` or `Edit` call whose `file_path` ends with `.artifact.json`:

1. Read the proposed `content` from `tool_input`.
2. Call the Python validator via `python -m research_agent_teams.tools.validate_cli --stdin` with the
   content on stdin.
3. If the validator exits with status 2 → **BLOCK** (exit 2 yourself, print the validation errors to
   stderr so the agent sees why it was blocked).
4. If the validator exits 0 → ALLOW (exit 0, the write proceeds).
5. If the validator itself errors (non-0/non-2, or internal JS exception) → **fail OPEN** (exit 0,
   log the error to stderr) — the hook must never brick a session on its own internal failure.

Non-artifact writes (path does not end with `.artifact.json`) are a NO-OP (exit 0 immediately).

## Implemented by

- `research_agent_teams/tools/validate_artifact.py` — `validate_artifact(artifact)`: pure function
  over dicts; validates envelope structure against `artifact_envelope.schema.json`, then validates
  `artifact.payload` against the schema registered for `artifact.artifact_type` in `PAYLOAD_SCHEMAS`.
  Returns a list of human-readable error strings; empty list == valid. No I/O beyond reading local
  schema files; no network; no LLM.
- `research_agent_teams/hooks/artifact-contract-enforcer.js` — the Claude Code PreToolUse entry
  point. Reads `tool_input` from stdin, identifies governed writes (Write/Edit to `*.artifact.json`),
  shells out to `validate_cli --stdin` with `spawnSync`, maps exit status to BLOCK/ALLOW/fail-open.
  `RAT_PYTHON` env var overrides the Python interpreter (for virtual-env setups).

## Guarantee

Any artifact that reaches disk has already passed two-layer schema validation:
1. Envelope structure (required fields: `artifact_id`, `artifact_type`, `schema_version`,
   `created_by`, `created_at`, `status`, `input_artifact_hashes`, `output_hash`, `payload`).
2. Payload, validated against the schema registered for its `artifact_type` (e.g. `alignment_report`
   → `alignment_report.schema.json`, `task_frame` → `task_frame.schema.json`, etc.).

An invalid artifact never lands. The spine's VERIFY step (`_validate_artifact_file` in `engine.py`)
also calls `validate_artifact` after the write — this is a belt-and-suspenders check; the hook is
the earlier fence.

## BLOCK conditions

- Envelope missing required fields (artifact_id, artifact_type, schema_version, created_by,
  created_at, status, input_artifact_hashes, output_hash, payload)
- `artifact_type` is not registered in `PAYLOAD_SCHEMAS` (unknown type)
- Payload does not conform to the registered JSON Schema for its type
- Content is not valid JSON at all

## You must NOT

- "Fix" or coerce invalid data — you emit a BLOCK signal and the reason; the agent that produced the
  bad artifact must fix it and retry
- Allow a write with warnings — this is a hard gate; partial-valid is BLOCK
- Modify `tool_input.content` before it reaches the Write tool — you are read-only on the proposed
  content
- Apply to non-artifact files — only files ending in `.artifact.json` are governed

## How it fits the spine

The enforcer sits at the write boundary for every artifact in the system. Constitution Rule 2
requires every artifact to carry a valid envelope; constitution Rule 1 says no artifact = stage not
done. Together: an agent that produces a malformed artifact is blocked at the point of write (hook
exit 2), and the stage remains incomplete until the agent produces a valid one. The engine's own
`_validate_artifact_file` call after the write is the final confirmation that what landed on disk
matches the schema — by then the hook has already rejected anything invalid.
