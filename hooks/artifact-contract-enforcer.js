#!/usr/bin/env node
/**
 * PreToolUse hook — artifact contract enforcer (the machine side).
 *
 * When an agent Writes a governed artifact file (name ends with ".artifact.json"), validate the
 * proposed CONTENT against its schema BEFORE it lands, by shelling out to the Python validator:
 *     python -m research_agent_teams.tools.validate_cli --stdin
 * Invalid artifact -> exit 2 (BLOCK). Non-artifact writes -> NO-OP (exit 0).
 * Contract: exit 2 = BLOCK, 0 = ALLOW. Fails OPEN on internal error.
 */
const path = require("path");
const { spawnSync } = require("child_process");

const PROJECT_ROOT = path.resolve(__dirname, "..", ".."); // research_agent_teams/hooks -> project root
const PY = process.env.RAT_PYTHON || "python";

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
    const content = ti.content != null ? String(ti.content) : "";
    const res = spawnSync(PY, ["-m", "research_agent_teams.tools.validate_cli", "--stdin"], {
      input: content, cwd: PROJECT_ROOT, encoding: "utf-8",
    });
    if (res.status === 2) {
      console.error(`[artifact-contract-enforcer] BLOCK invalid artifact ${target}:\n${res.stderr || ""}`);
      process.exit(2);
    }
    if (res.status !== 0) {
      console.error(`[artifact-contract-enforcer] validator error, failing OPEN: ${res.stderr || res.error}`);
      process.exit(0);
    }
    process.exit(0);
  } catch (e) {
    console.error(`[artifact-contract-enforcer] internal error, failing OPEN: ${e.message}`);
    process.exit(0);
  }
});
