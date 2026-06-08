---
name: permission-scope-guard
model: none
kind: hook (PreToolUse)
implements: tools/scope_guard.py + hooks/permission-scope-guard.js
enforces: per-agent path and tool fences
permission_scope:
  read: [tool_name, tool_input.file_path from stdin; env vars RAT_RUN_ROOT / RAT_RUN_ID / RAT_STAGE / RAT_VAULT_ROOT]
  write: [nothing — this hook never writes]
  never: [modify tool_input, allow-but-warn, fail-closed on internal error (must fail OPEN)]
authority: hard fence — "agent secretly edits another stage / the vault" is architecturally impossible
---

# permission-scope-guard — PreToolUse hook

You are the permission-scope-guard. You have no model; you are a deterministic hook. Your ONE job:
enforce the path and tool fence for every fenced work-stage agent, so that no agent can write
outside its allowed scope. You are fail-loud (exit 2 = BLOCK) on violations and NO-OP on everything
outside the governed trees.

## Single responsibility

For every tool call while `RAT_RUN_ID` is set in the environment (i.e. while the orchestrator is
dispatching a fenced work-stage agent):

1. **Bash is always blocked** for fenced agents: shell commands cannot be proven safe → exit 2.
2. **Read-only tools** (anything not in `{Write, Edit, NotebookEdit}`) → exit 0 (allowed; agents
   may read freely within their Read permission).
3. **Write/Edit/NotebookEdit** → check the target path against the agent's scope:
   - `runs/<run>/evidence/<active_stage>/` — allowed (the agent's own stage evidence directory)
   - `runs/<run>/inbox/` — allowed (promotion staging)
   - `runs/<run>/manifest.yaml`, `ledger.jsonl`, `LOCK` — **BLOCK** (single-writer infra;
     orchestrator/state-tracker only)
   - Vault root (`RAT_VAULT_ROOT` if set) — **BLOCK** (vault writes go through human promotion gate)
   - Any other path inside `run_root` (another run, another stage) — **BLOCK**
   - Path outside every governed tree — **NO-OP** (exit 0; guard never bricks unrelated work)

If `RAT_RUN_ID` is unset → the hook is not operating a fenced agent → exit 0 (NO-OP globally).

## Implemented by

- `research_agent_teams/tools/scope_guard.py` — `decide(tool, target_path, scope)`: pure function;
  returns `(allowed: bool, reason: str)`. Used by the engine's `_drive` loop (the Python-side fence)
  and by tests. `scope = {run_root, run_id, stage, vault_root?}`. Path comparison is normalised
  (`os.path.normcase(os.path.normpath(os.path.abspath(...)))`) for both POSIX and Windows.
- `research_agent_teams/hooks/permission-scope-guard.js` — the Claude Code PreToolUse entry point.
  Reads `tool_name` and `tool_input` from stdin; loads scope from env (`RAT_RUN_ROOT`, `RAT_RUN_ID`,
  `RAT_STAGE`, `RAT_VAULT_ROOT`); calls the JS `decide` mirror (same rule set as the Python core);
  exits 2 on BLOCK, 0 on allow. Fails OPEN on internal error (never bricks session), but logs to
  stderr. Windows path case-insensitive comparison (`toLowerCase()`) is handled.

The Python `scope_guard.decide` and JS `decide` are kept in sync by rule: any rule change must be
made in both files simultaneously.

## Guarantee

Under large fan-out, every sub-agent is fenced to exactly:
- `runs/<run>/evidence/<its_stage>/` for evidence output
- `runs/<run>/inbox/` for promotion staging

An agent writing to another stage's evidence directory, to the run infra files, to the vault, or to
another run is blocked at the hook before the write reaches the filesystem. The engine's Python-side
`decide` call in `_drive` provides a belt-and-suspenders check at the engine layer; the hook is the
earlier, runtime fence. Together they make "an agent secretly edits another stage / the vault"
architecturally impossible.

## BLOCK conditions

- Tool is `Bash` and `RAT_RUN_ID` is set (fenced agent context)
- Write/Edit/NotebookEdit targets a run infra file (`manifest.yaml`, `ledger.jsonl`, `LOCK`) inside
  the active run directory
- Write/Edit/NotebookEdit targets a path inside `RAT_VAULT_ROOT`
- Write/Edit/NotebookEdit targets any path inside `run_root` that is outside the agent's
  `evidence/<stage>/` directory or `inbox/`
- Write/Edit/NotebookEdit with no target path (fail-closed: `target == null`)

## You must NOT

- Fail-closed on internal JS/parsing errors — internal errors must fail OPEN (exit 0) so the hook
  never bricks an unrelated session; but always log the error to stderr
- Block writes to paths outside every governed tree — unrelated project files are NO-OP
- Modify `tool_input` — you are purely a gate; you never alter what the agent is trying to write

## How it fits the spine

The orchestrator sets `RAT_RUN_ROOT`, `RAT_RUN_ID`, `RAT_STAGE`, and optionally `RAT_VAULT_ROOT`
in the environment before dispatching each work-stage agent. This hook fires on every tool call that
agent makes. The fence is transparent to agents doing the right thing (their writes land in their
evidence directory without friction) and hard-blocks the wrong thing (cross-stage writes, vault
writes, Bash invocations) before they happen. The result is that the run-store's single-writer
invariant for infra files and the vault's human-gate invariant are both enforced at the tool level,
not merely by convention.
