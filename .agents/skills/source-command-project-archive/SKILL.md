---
name: "source-command-project-archive"
description: "Hide a project from the active picker (fully reversible via /project-restore; deletes nothing)."
---

# source-command-project-archive

Use this skill when the user asks to run the migrated source command `project-archive`.

## Command Template

# /project-archive — 归档项目 (Archive a Project, reversible)

> 把一个项目从 active picker 里**藏起来**——不删任何东西，完全可逆。
> 适合：项目暂时搁置，但以后还想捡回来。要真删机器侧 scratch 走 `/project-delete`（GUARDED）。

1. 归档（hide from the active picker；磁盘上一个字节都不删）：
   ```powershell
   python -m research_agent_teams.operate project-archive --project <slug>
   ```
2. 读回 JSON：`lifecycle_status` 变为 archived，note 会确认「nothing deleted — 可经 project-restore 复原」。
3. 之后：
   - 想再看到它 → `/project-list --include-hidden`。
   - 想恢复 active → `/project-restore`（见该命令）。
   边界：可逆操作，vault 与机器侧数据都完整保留；只改 lifecycle 标记。
