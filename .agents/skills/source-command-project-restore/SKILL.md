---
name: "source-command-project-restore"
description: "Bring an archived or soft-deleted project back to active."
---

# source-command-project-restore

Use this skill when the user asks to run the migrated source command `project-restore`.

## Command Template

# /project-restore — 恢复项目 (Restore a Project)

> 把一个 archived 或 soft-deleted 的项目拉回 **active**。
> 这是 `/project-archive` 和 `/project-soft-delete` 的反向操作；purge 过的项目无法靠它复原。

1. 先确认目标项目处于 hidden 状态（看得到它需要 `--include-hidden`）：
   ```powershell
   python -m research_agent_teams.operate index --include-hidden
   ```
2. 恢复到 active：
   ```powershell
   python -m research_agent_teams.operate project-restore --project <slug>
   ```
3. 读回 JSON：`lifecycle_status` 回到 active，note 确认「back to active」。
   - 找不到该 slug / 报错 ⇒ 它可能从没注册，或已被 `/project-delete` 的 purge 物理清除（不可逆）。
   恢复后即可 `/start-research` 继续在这个项目上开跑。边界：vault 永不被触碰。
