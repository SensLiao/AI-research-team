---
name: "source-command-project-list"
description: "List every project the machine knows (registry + workspaces + runs) with lifecycle status and current FSM stage."
---

# source-command-project-list

Use this skill when the user asks to run the migrated source command `project-list`.

## Command Template

# /project-list — 项目总览 (Project Index)

> 一眼看全部项目：lifecycle status（active / archived / soft-deleted）+ 每个项目的当前 stage。
> 比旧的 project-list 更丰富——这就是 workspace 的 index 视图。

1. 列出所有 **active** 项目（默认隐藏归档 / soft-deleted）：
   ```powershell
   python -m research_agent_teams.operate index
   ```
2. 要把归档 / soft-deleted 的也显示出来（比如准备 `/project-restore`）：
   ```powershell
   python -m research_agent_teams.operate index --include-hidden
   ```
3. 读回 JSON 的 `projects` 数组：每行含 slug、lifecycle_status、current stage、近期 run。
   - 想深入某一个项目 → 之后可在该项目上 `/start-research` / `/run-mode`。
   - 看不到想要的项目 → 它可能没注册（`/project-new`）或被归档（加 `--include-hidden`）。
   边界：纯只读，不动任何项目数据，vault 永不被触碰。
