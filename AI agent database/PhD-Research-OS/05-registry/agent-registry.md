---
type: registry
registry-of: agents
updated: 2026-06-07
---

# Agent Registry

Authoritative roster of the research team + the ritual to extend it.

> **Why a registry, not just the `.md` files:** the agent *implementations* live in
> `.claude/agents/*.md` (Claude Code specific). This registry is the **contract** —
> agent-agnostic. It records who exists, their role, tool boundary, and model, plus the
> standard way to add / change one. Any agent reading the vault sees the roster here; the
> Claude-Code wiring is an implementation detail. **5 agents is a starting team, not a cap —
> extend via the ritual below.**

## Current roster (all `opus` as of 2026-06-07 — director's call: research quality over token cost)

| agent | pipeline stage | model | tools (= the boundary) | hard limit |
|---|---|---|---|---|
| `literature-ingest` | search / read | opus | Read·Glob·Grep·Write·Edit·**WebSearch·WebFetch** | cannot edit the rules |
| `experiment-planner` | design + variables | opus | Read·Glob·Grep·Write·Edit | **no Bash → cannot launch GPU** |
| `ablation-runner` | run | opus | Read·Glob·Grep·**Bash**·Write·Edit | cannot freeze a result |
| `result-analyzer` | analyze | opus | Read·Glob·Grep·Bash·Write·Edit | cannot set `frozen` / `can-cite-thesis` |
| `adversarial-reviewer` | refute → freeze | opus | Read·Glob·Grep·Bash | **no Write → cannot self-approve** |

Pipeline: `literature-ingest → experiment-planner →[DIRECTOR]→ ablation-runner → result-analyzer → adversarial-reviewer →[DIRECTOR]→ thesis`

## Design principles (every agent obeys)

1. **Tool = boundary (least privilege).** An agent's power is *exactly* its `tools:` list. To forbid an action, remove the tool (planner has no Bash; reviewer has no Write). This is **program-enforced**, not a prompt request.
2. **Model routing.** Default `opus` for this team. Drop a single high-volume mechanical sub-agent to sonnet/haiku only if token cost ever bites.
3. **Director gates between stages.** No agent runs the whole pipeline end-to-end; design→run and analyze→freeze both need human sign-off.
4. **Agents never edit the rules.** `00-system/` · `05-registry/` · `04-templates/` · `06-scripts/*.py` · `.claude/` are off-limits (schema-write-block hook enforces this in Claude Code).

## Ritual: ADD a new agent

1. **Scaffold** — copy the template below to `.claude/agents/<kebab-name>.md`. Pick the **minimum** tool set.
2. **Register** — add a roster row here (stage / model / tools / hard limit).
3. **Wire the router** — add it to `00-system/agent-startup-router.md` Stage 1b (which task row dispatches to it).
4. **Declare the boundary** — the agent's `## You must NOT` section must name what its missing tools physically prevent.
5. **Log** — a `SCHEMA:` line in `07-logs/log.md`, then commit.

## Ritual: CHANGE an agent (model / tools / scope)

Edit `.claude/agents/<name>.md` + update this roster row + `SCHEMA:` log line, one commit.
- Tightening a tool (removing a power) is always safe.
- **Widening** one (adding Bash / Write / a new MCP) needs a one-line justification in the log — it expands what the agent can physically do.

## Template (copy for a new agent)

```yaml
---
name: <kebab-name>
description: <one line — when to use it; what it must NOT do>
tools: Read, Glob, Grep        # add Write/Edit/Bash/WebSearch ONLY if the role needs it
model: opus
---

You are the <role>. <one-sentence mandate>.

## Read first
1. 00-system/AGENTS.md  (§2 citation gate, §3 evidence labels)
2. <role-specific required reading>

## What you do
- <core actions, each producing a typed vault note>

## You must NOT
- <the physical boundary — what its missing tools prevent>
- Write to 00-system/ · 05-registry/ · 04-templates/ · 06-scripts/ · .claude/ (the gate blocks it)

## Output to the user
<what it hands back>
```

## Extending SKILLS and TOOLS

- **Skills** (reusable command workflows) live in `.claude/skills/<name>.md` (existing: close · ghost · recall · trace). Add one by writing the workflow there and referencing it from the router or an agent.
- **Tools**: an agent's powers are Claude Code built-ins (Read/Write/Bash/WebSearch/…) in its `tools:` line. To reach an **external system** (Zotero, arXiv API, your GPU server), add an **MCP server** — the agent reaches it through the MCP tool. Usually no new agent needed: just widen one agent's `tools:` + justify in the log.

## Naming freeze
Agent names are referenced by the router dispatch table — renaming one breaks the wiring. Rename = update the router + this registry + log, in one commit.
