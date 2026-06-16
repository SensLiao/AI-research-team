# `.claude/` — the Director Layer (Phase 1)

> This folder makes "the human is the brain, the AI team is the hands" a **mechanical guarantee**,
> not a prompt-level hope. Installed 2026-06-06. See `_design/research-os-blueprint-v1.md` for the why.

Claude Code reads this folder automatically when you run it **with this vault as the working
directory**. (Running Claude Code from a parent folder will not activate these hooks.)

## What's here

| File | Role |
|---|---|
| `settings.json` | Wires the two hooks + lets read-only tools run without prompting (Tier 1). |
| `hooks/schema-write-block.js` | **PreToolUse gate.** Blocks the AI team from writing the rules that govern it, and from destructive commands. |
| `hooks/write-time-lint.js` | **PostToolUse.** Runs `06-scripts/lint_vault.py --file` on each just-written `02-wiki/*.md`, surfacing schema/citation-gate errors at write-time. |
| `agents/*.md` | The 5 tool-allowlisted team roles (below). |
| `skills/{ingest,recall,trace,close,ghost}.md` | The vault rituals (pre-existing). |

## The 3 access tiers (enforced by `schema-write-block.js`)

- **Tier 1 — ALLOW, never prompt:** `Read` / `Glob` / `Grep`, `git status|log|diff`.
- **Tier 2 — ASK:** writes to `02-wiki/`, `00-system/{index,hot}.md`, `07-logs/log.md`, running experiments — normal permission prompt.
- **Tier 3 — DENY (exit 2):** any write to `00-system/` contracts, `05-registry/`, `04-templates/`, `06-scripts/*.py`, `.claude/{settings.json,hooks/,agents/}`, `01-raw/`, `.pre-commit-config.yaml`; plus `rm -rf`, `git reset --hard`, `git push --force`, `git clean -f`. **The team can never rewrite its own rules.** Changes to these are the human director's job, via the schema-migration ritual (`00-system/CLAUDE.md` §3.5).

## The 5 team roles & why their tools are scoped

| Agent | Model | Has launch power? | Can freeze a result? |
|---|---|---|---|
| `literature-ingest` | sonnet | no | no |
| `experiment-planner` | opus | **no Bash — physically cannot start a GPU job; it only proposes** | no |
| `ablation-runner` | sonnet | yes (approved specs only) | no |
| `result-analyzer` | sonnet | reads metrics | no — writes `provisional` only |
| `adversarial-reviewer` | opus | no | **no Write — issues a verdict; the human freezes** |

This encodes the operating model: **the planner can't run, the runner can't decide truth, the
analyst can't freeze, the reviewer can't rubber-stamp itself.** Autonomy = approve-each-batch:
nothing hits the GPU until the human approves a planner batch.

## Verify it works

From inside the vault directory:

```bash
# 1. director gate blocks a rules edit (expect: exit 2 + BLOCKED message)
echo '{"tool_name":"Write","tool_input":{"file_path":"06-scripts/lint_vault.py"}}' | node .claude/hooks/schema-write-block.js; echo "exit=$?"

# 2. allows a normal wiki write (expect: exit 0)
echo '{"tool_name":"Write","tool_input":{"file_path":"02-wiki/papers/x.md"}}' | node .claude/hooks/schema-write-block.js; echo "exit=$?"

# 3. blocks rm -rf (expect: exit 2)
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf foo"}}' | node .claude/hooks/schema-write-block.js; echo "exit=$?"

# 4. the integrity layer still passes
python 06-scripts/lint_vault.py
```

## Not yet built (later phases — see the blueprint)
DVC+Hydra reproducibility sidecar · aexp experiment harness · Phoenix/Orze/Telegram monitoring ·
Obsidian Spaced-Repetition + Socratic-before-decision learning loops · negative-result/dead-end memory loop.
