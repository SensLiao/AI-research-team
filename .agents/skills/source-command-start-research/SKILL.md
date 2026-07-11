---
name: "source-command-start-research"
description: "Entry router — open the workspace, pick a project, set it active, then route the request to a full run (run-mode) or one stage (run-stage)."
---

# source-command-start-research

Use this skill when the user asks to run the migrated source command `start-research`.

## Command Template

# /start-research — 工作台入口 (Workspace Entry Router)

> 给导演的总入口：先看有哪些项目、选一个、设为 active，再决定跑「整模式」还是「单 stage」。
> The machine never writes the vault registry — the director adds project rows there (see AGENTS.md §2).

1. 列出机器知道的所有项目（lifecycle status + 当前 stage），挑一个 `<slug>`：
   ```powershell
   python -m research_agent_teams.operate index
   ```
2. 把工作台指向选中的项目（只是个 pointer，不动任何数据）：
   ```powershell
   python -m research_agent_teams.operate set-active --project <slug>
   ```
3. 路由这次请求 —— 二选一：
   - **整模式跑一遍**（10 个 operated 模式之一：new_direction / deep_ideation / gap_breadth / evidence_review / evidence_deep / deep_research / venue_readiness / full_rigor_minimal / ingest_paper / read_paper_deep）→ 用 `/run-mode`：
     ```powershell
     python -m research_agent_teams.operate begin --mode <mode> --project <slug> --request "..."
     ```
   - **只跑一个 stage**（DISCOVER…REPORT，半路插入、依赖会被校验）→ 用 `/run-stage`：
     ```powershell
     python -m research_agent_teams.operate run-stage --project <slug> --stage <STAGE>
     ```
4. 没有合适项目？先 `/project-new` 建一个，或 `/project-list --include-hidden` 看归档的。
   诚实边界：full_rigor_minimal 的 EXECUTE 只产出可运行 scripts，真在 GPU 上跑要先接通服务器（AGENTS.md §6，目前未接）。
