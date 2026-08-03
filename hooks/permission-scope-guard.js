#!/usr/bin/env node
/**
 * PreToolUse hook — permission-scope guard for fenced work-stage agents (the machine side).
 *
 * Mirrors research_agent_teams/tools/scope_guard.py. A fenced agent may only write inside its own
 *   runs/<active_run>/evidence/<active_stage>/   or   runs/<active_run>/inbox/
 * and may NOT: run Bash, write run infra (manifest.yaml/ledger.jsonl/LOCK), write the vault, write
 * the project workspace (projects/<slug>/ is operator-managed), or write another run/stage.
 * Paths outside every governed tree are a NO-OP.
 *
 * Active scope comes from env (set by the orchestrator when it dispatches a fenced agent):
 *   RAT_RUN_ROOT, RAT_RUN_ID, RAT_STAGE, RAT_VAULT_ROOT (optional), RAT_PROJECTS_ROOT (optional)
 * If RAT_RUN_ID is unset -> NO-OP (not operating a fenced agent). Contract: exit 2 = BLOCK, 0 = ALLOW.
 *
 * Governance fail-closed (audit Wave D): the old catch block failed OPEN unconditionally ("never brick
 * a session"). But a write that targets the VAULT (path contains "phd-research-os") or single-writer
 * run INFRA (basename ledger.jsonl / manifest.yaml) is on a GOVERNANCE path — there, internal error
 * MUST fail CLOSED (exit 2): a transiently-failing guard must not become an open door into the crown
 * jewels. Everything else stays fail-OPEN (exit 0 + stderr warning) so an unrelated parse hiccup never
 * bricks a session; a completely unparseable payload also stays fail-OPEN.
 */
const path = require("path");
const fs = require("fs");

const WRITE_TOOLS = new Set(["Write", "Edit", "NotebookEdit"]);
const INFRA_FILES = new Set(["manifest.yaml", "ledger.jsonl", "LOCK"]);
// Governance-path markers for the fail-closed catch: the vault dir name + single-writer run-infra files.
// LOCK is intentionally NOT here — it is a transient lockfile, not a tamper-evident governance artifact,
// so a parse failure over it should not hard-block (the in-band decide() still blocks LOCK on the happy path).
const GOVERNANCE_INFRA = new Set(["ledger.jsonl", "manifest.yaml"]);
const VAULT_MARKER = "phd-research-os";

function extractTarget(raw) {
  // Best-effort target-path extraction usable from the catch block, where decide()'s scope is unavailable.
  // Returns the raw file_path/notebook_path string, or null if the payload cannot yield one.
  const input = JSON.parse(raw || "{}");
  const ti = input.tool_input || {};
  return ti.file_path || ti.notebook_path || null;
}

function isGovernancePath(target) {
  // Normalize case-insensitively + slash-agnostically (Windows path.sep is "\\"; payloads may carry "/").
  if (!target) return false;
  const norm = String(target).toLowerCase().replace(/\\/g, "/");
  if (norm.includes(VAULT_MARKER)) return true;
  const base = norm.split("/").pop();
  return GOVERNANCE_INFRA.has(base);
}

// research_agent_teams/hooks -> the machine's project root. Derived from __dirname so it is
// independent of the hook process cwd (Claude Code launches hooks with the Bash tool's PERSISTENT
// shell cwd, which drifts as commands cd around).
const MACHINE_ROOT = path.resolve(__dirname, "..", "..");

function within(child, root) {
  // Anchor a relative path to the project root, NOT to process.cwd(). decide()'s default verdict is
  // ALLOW ("non-governed path"), so a cwd-relative mis-resolution would read as "outside every
  // governed tree" and silently open a path into the vault / another run's stage.
  let c = path.isAbsolute(child) ? path.resolve(child) : path.resolve(MACHINE_ROOT, child);
  let r = path.isAbsolute(root) ? path.resolve(root) : path.resolve(MACHINE_ROOT, root);
  if (process.platform === "win32") { c = c.toLowerCase(); r = r.toLowerCase(); }
  return c === r || c.startsWith(r + path.sep);
}

function discoverVaultRoot() {
  // Mirror of scope_guard.discover_vault_root: walk up from this hook to a parent holding
  // `AI agent database/PhD-Research-OS/00-system`. Lets the vault block fire WITHOUT the optional
  // RAT_VAULT_ROOT being set (the gap the audit flagged). Returns null in a bare tree.
  let dir = __dirname;
  while (true) {
    const marker = path.join(dir, "AI agent database", "PhD-Research-OS", "00-system");
    try { if (fs.statSync(marker).isDirectory()) return path.dirname(marker); } catch (e) {}
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function discoverProjectsRoot() {
  // Mirror of scope_guard.discover_projects_root: the machine's own per-project workspace root
  // (research_agent_teams/projects/, sibling of hooks/). Operator-managed; fenced agents never write it.
  return path.join(path.dirname(__dirname), "projects");
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
  if (scope.projectsRoot && within(target, scope.projectsRoot))
    return [false, "blocked: the project workspace is operator-managed (fenced agents write only their run scope)"];
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
    // Test-only fault injection to exercise the governance fail-closed catch deterministically; production
    // never sets RAT_GUARD_FORCE_FAULT. Thrown AFTER `raw` is fully received so the catch can still recover
    // the target path from the (valid) payload via extractTarget(raw).
    if (process.env.RAT_GUARD_FORCE_FAULT) throw new Error("forced internal fault (test)");
    const input = JSON.parse(raw || "{}");
    const tool = input.tool_name || "";
    const ti = input.tool_input || {};
    const target = ti.file_path || ti.notebook_path || null;
    const scope = {
      runRoot: process.env.RAT_RUN_ROOT || "",
      runId,
      stage: process.env.RAT_STAGE || "",
      // ③: env wins, else discover by layout — the vault block no longer depends on RAT_VAULT_ROOT being set.
      vaultRoot: process.env.RAT_VAULT_ROOT || discoverVaultRoot() || "",
      projectsRoot: process.env.RAT_PROJECTS_ROOT || discoverProjectsRoot() || "",
    };
    const [allowed, reason] = decide(tool, target, scope);
    if (!allowed) {
      console.error(`[permission-scope-guard] BLOCK: ${reason} -> ${target || tool}`);
      process.exit(2);
    }
    process.exit(0);
  } catch (e) {
    // Governance fail-closed: if we can still recover a target path AND it is on a governance path
    // (vault or single-writer run-infra), BLOCK — a flaky guard must never become an open door into
    // the crown jewels. Otherwise fail OPEN (never brick an unrelated session).
    let target = null;
    try { target = extractTarget(raw); } catch (_) { /* payload unparseable -> target stays null */ }
    if (isGovernancePath(target)) {
      console.error(`[permission-scope-guard] internal error on a GOVERNANCE path, failing CLOSED (BLOCK): ${e.message} -> ${target}`);
      process.exit(2);
    }
    console.error(`[permission-scope-guard] internal error, failing OPEN (non-governance): ${e.message}`);
    process.exit(0);
  }
});
