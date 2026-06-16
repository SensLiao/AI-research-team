#!/usr/bin/env node
/**
 * PreToolUse hook — the "director" access-control layer for the PhD-Research-OS vault.
 *
 * Deterministically enforces the rule that the AI team can NEVER rewrite the rules that
 * govern it (something a prompt alone cannot guarantee):
 *   - blocks Write / Edit / NotebookEdit to protected paths
 *       (schema contracts, registries, templates, integrity scripts, the hook+agent layer
 *        itself, and the immutable 01-raw/ inputs)
 *   - blocks destructive Bash (rm -rf, git reset --hard, git push --force, git clean -f)
 *   - best-effort: blocks shell writes (>, tee, sed -i) aimed at protected paths
 *
 * Contract: exit 2 = BLOCK (stderr is shown to the agent). exit 0 = ALLOW.
 * Fails OPEN on its own internal error so it can never brick a session — but says so on stderr.
 *
 * The human director is expected to make protected-file changes directly (outside the agent),
 * via the schema-migration / type-extension ritual in 00-system/CLAUDE.md §3.5.
 */
const path = require("path");

const VAULT_ROOT = path.resolve(__dirname, "..", "..");

// Operational files inside 00-system/ that the agent legitimately rewrites every INGEST / close.
const ALLOW_00_SYSTEM = new Set([
  "00-system/index.md",
  "00-system/hot.md",
  "00-system/README.md",
]);

function toRel(fp) {
  const abs = path.isAbsolute(fp) ? fp : path.resolve(process.cwd(), fp);
  return path.relative(VAULT_ROOT, abs).split(path.sep).join("/");
}

function isProtected(rel) {
  if (rel.startsWith("..")) return false; // outside the vault — not this hook's concern
  if (rel.startsWith("00-system/")) return !ALLOW_00_SYSTEM.has(rel);
  if (rel.startsWith("05-registry/")) return true;
  if (rel.startsWith("04-templates/")) return true;
  if (rel.startsWith("01-raw/")) return true;
  if (rel.startsWith(".claude/hooks/")) return true;
  if (rel.startsWith(".claude/agents/")) return true;
  if (rel === ".claude/settings.json") return true;
  if (rel.startsWith("06-scripts/") && rel.endsWith(".py")) return true;
  if (rel === ".pre-commit-config.yaml") return true;
  if (rel === "bootstrap-intake.yml") return true;
  return false;
}

const DESTRUCTIVE = [
  /\brm\s+-[a-z]*r[a-z]*f[a-z]*/i, // rm -rf / -rfv / -rvf ...
  /\brm\s+-[a-z]*f[a-z]*r[a-z]*/i, // rm -fr / -fvr ...
  /\brm\s+-r\b[^|;&\n]*\s-f\b/i, // rm -r ... -f
  /\brm\s+-f\b[^|;&\n]*\s-r\b/i, // rm -f ... -r
  /\bgit\s+reset\s+--hard\b/i,
  /\bgit\s+push\b[^|;&\n]*--force(?!-with-lease)/i,
  /\bgit\s+push\b[^|;&\n]*\s-f\b/i,
  /\bgit\s+clean\b[^|;&\n]*\s-[a-z]*f/i,
];

function shellWriteToProtected(cmd) {
  // best-effort: capture a path that follows a redirect / tee / sed -i, then test it
  const re = /(?:>>?|\btee\s+(?:-a\s+)?|\bsed\s+-i\S*\s+[^|;&]*?\s)\s*['"]?([^\s'"|;&>]+)/gi;
  let m;
  while ((m = re.exec(cmd)) !== null) {
    const rel = toRel(m[1]);
    if (isProtected(rel)) return rel;
  }
  return null;
}

function block(msg) {
  process.stderr.write("[director-gate] BLOCKED: " + msg + "\n");
  process.exit(2);
}

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(raw || "{}");
  } catch (e) {
    // Unparseable input: cannot recover the target path — fail open with a warning so we
    // never brick a session, but log so the director is aware.
    process.stderr.write(
      "[director-gate] WARNING: unparseable hook input (fail-open); session not bricked. Error: " +
        String(e.message) + "\n"
    );
    process.exit(0);
  }
  try {
    const tool = input.tool_name || "";
    const ti = input.tool_input || {};

    if (tool === "Write" || tool === "Edit" || tool === "NotebookEdit") {
      const fp = ti.file_path || ti.notebook_path || "";
      if (!fp) process.exit(0);
      const rel = toRel(fp);
      if (isProtected(rel)) {
        block(
          `'${rel}' is a protected rules / contract / integrity file. The AI team may not ` +
            `rewrite the rules that govern it. If this change is genuinely intended, the human ` +
            `director must make it directly, via the schema-migration ritual (00-system/CLAUDE.md §3.5).`
        );
      }
      process.exit(0);
    }

    if (tool === "Bash") {
      const cmd = ti.command || "";
      for (const re of DESTRUCTIVE) {
        if (re.test(cmd)) {
          block(`destructive command refused (matched ${re}): ${cmd.slice(0, 200)}`);
        }
      }
      const hit = shellWriteToProtected(cmd);
      if (hit) block(`shell write to protected path '${hit}' refused: ${cmd.slice(0, 200)}`);
      process.exit(0);
    }

    process.exit(0);
  } catch (e) {
    // Internal error after input was parsed: attempt to recover the target path from the
    // already-parsed input and apply fail-closed logic for protected paths.
    const ti = (input && input.tool_input) || {};
    const fp = ti.file_path || ti.notebook_path || "";
    if (fp) {
      let rel;
      try {
        rel = toRel(fp);
      } catch (_) {
        rel = null;
      }
      if (rel !== null && isProtected(rel)) {
        // Target path is protected and we had an internal error — fail closed to be safe.
        process.stderr.write(
          "[director-gate] internal error while checking protected path '" + rel +
            "' — blocking to fail-closed. Fix the hook if this is a false positive. Error: " +
            String(e.message) + "\n"
        );
        process.exit(2);
      }
    }
    // Either no path recoverable or path is not protected — fail open with a warning.
    process.stderr.write(
      "[director-gate] internal error (non-protected path or no path — failing open): " +
        String(e.message) + "\n"
    );
    process.exit(0);
  }
});
