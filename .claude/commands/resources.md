---
description: "List the shared resource pool (capabilities only — never a secret value) and, with --project, what that project binds."
argument-hint: "[--project <slug>] [--scope shared|personal]"
allowed-tools: Bash, Read
---

# /resources — 资源池总览 (Resource Pool, capabilities only)

> 看机器能用哪些资源（GPU 服务器 / 论文 API / harness web 工具 / 个人 connector）。
> **只显示 capabilities，永不打印任何 secret 值**——池里存的全是 `.env` 变量名的引用，不是凭据本身。

1. 列出整个共享资源池（capabilities + 状态）：
   ```powershell
   python -m research_agent_teams.operate resources
   ```
2. 看某个项目绑了哪些资源（每条多一个 `bound_as` = 该项目的 alias，未绑为 null）：
   ```powershell
   python -m research_agent_teams.operate resources --project <slug>
   ```
3. 只看某一类（shared 池资源 / personal connector）：
   ```powershell
   python -m research_agent_teams.operate resources --scope shared
   python -m research_agent_teams.operate resources --scope personal
   ```
4. 想把某个资源绑给项目用 → `/resource-bind`（在 default-deny 之下授权 capabilities/stages/skills）。
   边界：纯只读、纯 capability 视图；任何 secret 值都不会出现在输出里。
