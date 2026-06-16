---
description: "Director-only GUARDED removal of a project's machine-side scratch (soft-delete then purge). The vault is NEVER touched. The model never self-deletes."
argument-hint: "<slug>"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /project-delete — 删除项目机器侧足迹 (GUARDED, human-only)

> `disable-model-invocation: true` — 只有导演能跑；模型从不自删。
> 删的只是**机器侧 scratch**（`projects/<slug>/` + `runs/<project>/`）；**vault（已 promote 的知识 +
> 注册表）永不被触碰**。推荐走两步安全路径，确认无误后才物理清除。

## 安全两步删除（推荐）

1. **Soft-delete**（可逆）——藏起来 + 撤销该项目所有 active leases；磁盘不删：
   ```powershell
   python -m research_agent_teams.operate project-soft-delete --project <slug>
   ```
   反悔了？随时 `/project-restore` 复原。
2. **Purge**（物理清除）——必须先 hidden，且**拒绝**执行除非：无 active run / 无 active lease /
   无 promoted vault claims。`--confirm` 必须等于 slug：
   ```powershell
   python -m research_agent_teams.operate project-purge --project <slug> --confirm <slug>
   ```
   读回 JSON 确认清了什么；被拒会说明原因（多半是还有活跃 run/lease，或有 promoted 记录 —— 后者保护 vault）。

## 一步硬删（逃生口，少用）

确定要**立刻抹掉**整个机器侧足迹、跳过 hidden-first 守卫时才用（vault 仍不动）：
```powershell
python -m research_agent_teams.operate project-delete --project <slug> --confirm <slug>
```
