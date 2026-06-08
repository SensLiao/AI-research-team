#!/usr/bin/env node
/**
 * PreToolUse hook — permission-scope guard for fenced work-stage agents (the machine side).
 *
 * Mirrors research_agent_teams/tools/scope_guard.py. A fenced agent may only write inside its own
 *   runs/<active_run>/evidence/<active_stage>/   or   runs/<active_run>/inbox/
 * and may NOT: run Bash, write run infra (manifest.yaml/ledger.jsonl/LOCK), write the vault, or
 * write another run/stage. Paths outside every governed tree are a NO-OP.
 *
 * Active scope comes from env (set by the orchestrator when it dispatches a fenced agent):
 *   RAT_RUN_ROOT, RAT_RUN_ID, RAT_STAGE, RAT_VAULT_ROOT (optional)
 * If RAT_RUN_ID is unset -> NO-OP (not operating a fenced agent). Contract: exit 2 = BLOCK, 0 = ALLOW.
 * Fails OPEN on internal error (never bricks a session) but says so on stderr.
 */
const path = require("path");

const WRITE_TOOLS = new Set(["Write", "Edit", "NotebookEdit"]);
const INFRA_FILES = new Set(["manifest.yaml", "ledger.jsonl", "LOCK"]);

function within(child, root) {
  let c = path.resolve(child);
  let r = path.resolve(root);
  if (process.platform === "win32") { c = c.toLowerCase(); r = r.toLowerCase(); }
  return c === r || c.startsWith(r + path.sep);
}

function decide(tool, target, scope) {
  if (tool === "Bash") return [false, "fenced agent: Bash is blocked (cannot prove command safety)"];
  if (!WRITE_TOOLS.has(tool)) return [true, "read-only tool, allowed"];
  if (!target) return [false, "fail-closed: write with no target path"];

  const runDir = path.join(scope.runRoot, scope.runId);
  if (INFRA_FILES.has(path.basename(target)) && within(target, runDir))
    return [false, `blocked: ${path.basename(target)} is single-writer infra (orchestrator only)`];
  if (within(target, path.join(runDir, "evidence", scope.stage)) || within(target, path.join(runDir, "inbox")))
    return [true, "within agent's stage scope"];
  if (scope.vaultRoot && within(target, scope.vaultRoot))
    return [false, "blocked: cannot write the vault directly (promote via the human gate)"];
  if (within(target, scope.runRoot))
    return [false, "blocked: outside this agent's stage scope (another run/stage)"];
  return [true, "non-governed path (no-op)"];
}

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  try {
    const runId = process.env.RAT_RUN_ID;
    if (!runId) process.exit(0); // not operating a fenced agent -> NO-OP
    const input = JSON.parse(raw || "{}");
    const tool = input.tool_name || "";
    const ti = input.tool_input || {};
    const target = ti.file_path || ti.notebook_path || null;
    const scope = {
      runRoot: process.env.RAT_RUN_ROOT || "",
      runId,
      stage: process.env.RAT_STAGE || "",
      vaultRoot: process.env.RAT_VAULT_ROOT || "",
    };
    const [allowed, reason] = decide(tool, target, scope);
    if (!allowed) {
      console.error(`[permission-scope-guard] BLOCK: ${reason} -> ${target || tool}`);
      process.exit(2);
    }
    process.exit(0);
  } catch (e) {
    console.error(`[permission-scope-guard] internal error, failing OPEN: ${e.message}`);
    process.exit(0);
  }
});
