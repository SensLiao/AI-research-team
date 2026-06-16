#!/usr/bin/env node
/**
 * PreToolUse hook — artifact contract enforcer (the machine side).
 *
 * When an agent Writes a governed artifact file (name ends with ".artifact.json"), validate the
 * proposed CONTENT against its schema BEFORE it lands, by shelling out to the Python validator:
 *     python -m research_agent_teams.tools.validate_cli --stdin
 * Invalid artifact -> exit 2 (BLOCK). Non-artifact writes -> NO-OP (exit 0).
 * Contract: exit 2 = BLOCK, 0 = ALLOW.
 *
 * Governance fail-closed (audit Wave D): this hook ONLY fires on `.artifact.json` writes, which ARE the
 * governed contract path. So an INTERNAL ERROR while handling such a write (validator process failed to
 * spawn, schema failed to load, content unreadable) now fails CLOSED (exit 2): blocking an artifact
 * write is safe and retryable — the agent re-emits it — whereas letting an unvalidated artifact land
 * silently corrupts the contract. A non-artifact write (or a payload that does not even parse into one)
 * still NO-OPs (exit 0) so the hook never bricks an unrelated session.
 */
const path = require("path");
const { spawnSync } = require("child_process");

const PROJECT_ROOT = path.resolve(__dirname, "..", ".."); // research_agent_teams/hooks -> project root
const PY = process.env.RAT_PYTHON || "python";

function isArtifactWrite(raw) {
  // Best-effort: is this payload a Write/Edit of a *.artifact.json file? Usable from the catch block.
  // Returns the target path on a match, else null (non-artifact, or unparseable payload).
  const input = JSON.parse(raw || "{}");
  const tool = input.tool_name || "";
  const target = (input.tool_input || {}).file_path || "";
  return (tool === "Write" || tool === "Edit") && target.endsWith(".artifact.json") ? target : null;
}

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  try {
    const input = JSON.parse(raw || "{}");
    const tool = input.tool_name || "";
    const ti = input.tool_input || {};
    const target = ti.file_path || "";
    if (!(tool === "Write" || tool === "Edit") || !target.endsWith(".artifact.json")) {
      process.exit(0); // not a governed artifact write -> NO-OP
    }
    // Test-only fault injection to exercise the governance fail-closed catch deterministically over a
    // real artifact write; production never sets RAT_ENFORCER_FORCE_FAULT.
    if (process.env.RAT_ENFORCER_FORCE_FAULT) throw new Error("forced internal fault (test)");
    const content = ti.content != null ? String(ti.content) : "";
    const res = spawnSync(PY, ["-m", "research_agent_teams.tools.validate_cli", "--stdin"], {
      input: content, cwd: PROJECT_ROOT, encoding: "utf-8",
    });
    if (res.status === 2) {
      console.error(`[artifact-contract-enforcer] BLOCK invalid artifact ${target}:\n${res.stderr || ""}`);
      process.exit(2);
    }
    if (res.status !== 0) {
      // Validator could not run (spawn failure / schema load error / crash). On the governed artifact
      // path this fails CLOSED — an unvalidated artifact must not land.
      console.error(`[artifact-contract-enforcer] validator error on artifact ${target}, failing CLOSED (BLOCK): ${res.stderr || res.error}`);
      process.exit(2);
    }
    process.exit(0);
  } catch (e) {
    // If this was (recoverably) an artifact write, fail CLOSED; otherwise NO-OP (never brick a session).
    let target = null;
    try { target = isArtifactWrite(raw); } catch (_) { /* unparseable -> not a known artifact write */ }
    if (target) {
      console.error(`[artifact-contract-enforcer] internal error on artifact ${target}, failing CLOSED (BLOCK): ${e.message}`);
      process.exit(2);
    }
    console.error(`[artifact-contract-enforcer] internal error (non-artifact), failing OPEN: ${e.message}`);
    process.exit(0);
  }
});
