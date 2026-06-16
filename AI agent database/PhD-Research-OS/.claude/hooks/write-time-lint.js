#!/usr/bin/env node
/**
 * PostToolUse hook — runs the vault's OWN Python lint on a just-written 02-wiki/*.md file,
 * surfacing schema / citation-gate violations at write-time instead of only at session end /
 * pre-commit. Single source of truth: it calls 06-scripts/lint_vault.py --file <rel> and never
 * re-implements the rules.
 *
 * Cross-platform spawn: uses shell:true so `python` / `py` resolve via PATH on Windows, and
 * passes the VAULT-RELATIVE path (ASCII, no spaces) with cwd=VAULT_ROOT so the spaced/unicode
 * vault root never reaches the command line. Accepts only the lint's known exit codes (0/1/2);
 * anything else means that interpreter is absent, so it tries the next one. Degrades gracefully
 * if no Python is found (pre-commit / CI still enforce) — never bricks a session.
 *
 * Contract: exit 2 = surface lint errors to the agent. exit 0 = clean / skipped.
 */
const path = require("path");
const { spawnSync } = require("child_process");

const VAULT_ROOT = path.resolve(__dirname, "..", "..");
const LINT = "06-scripts/lint_vault.py";
const PYTHON_CANDIDATES = ["python", "python3", "py -3"];

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  // Design note on fail-closed policy for this hook:
  // write-time-lint is a PostToolUse ADVISORY hook — exit 2 surfaces lint errors to the agent
  // but does NOT prevent the write from having already occurred. Its block domain is therefore
  // "show the agent lint errors so it can self-correct", not "prevent a write".
  // Because there is no hard block responsibility, internal errors → exit 0 + stderr warning
  // is the correct policy: we never want a lint harness crash to appear as a schema violation.
  // The pre-commit hook and full `lint_vault.py --json` run remain the hard enforcement layer.
  let input;
  try {
    input = JSON.parse(raw || "{}");
  } catch (e) {
    process.stderr.write(
      "[write-time-lint] WARNING: unparseable hook input — lint skipped (advisory only; " +
        "pre-commit still enforces). Error: " + String(e.message) + "\n"
    );
    process.exit(0);
  }
  const ti = input.tool_input || {};
  const fp = ti.file_path || "";
  if (!fp) process.exit(0);
  const abs = path.isAbsolute(fp) ? fp : path.resolve(process.cwd(), fp);
  const rel = path.relative(VAULT_ROOT, abs).split(path.sep).join("/");
  if (!rel.startsWith("02-wiki/") || !rel.endsWith(".md")) process.exit(0); // only wiki notes

  let ran = null;
  for (const c of PYTHON_CANDIDATES) {
    let r;
    try {
      r = spawnSync(`${c} ${LINT} --file "${rel}"`, {
        cwd: VAULT_ROOT,
        shell: true,
        encoding: "utf8",
      });
    } catch (e) {
      continue;
    }
    // Only the lint itself returns 0/1/2; "command not found" returns other codes → try next.
    if (!r.error && [0, 1, 2].includes(r.status)) {
      ran = r;
      break;
    }
  }

  if (!ran) {
    process.stderr.write(
      "[write-time-lint] Python not found; skipped " + rel + " (pre-commit / CI still enforce).\n"
    );
    process.exit(0);
  }
  if (ran.status === 2) {
    process.stderr.write(
      "[write-time-lint] lint dependency missing (e.g. python-frontmatter); skipped " + rel + ".\n"
    );
    process.exit(0);
  }
  if (ran.status === 1) {
    process.stderr.write(
      "[write-time-lint] schema / citation-gate issue in " + rel + ":\n" + (ran.stdout || "") + "\n"
    );
    process.exit(2);
  }
  process.exit(0);
});
