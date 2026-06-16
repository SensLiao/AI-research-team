---
description: "Registry-check a project slug against the vault, then create its machine-side workspace (projects/<slug>/). The director adds the registry row first."
argument-hint: "<slug>"
allowed-tools: Bash, Read
---

# /project-new — 新建项目工作台 (Create a Project Workspace)

> 给一个**已在 vault 注册**的项目 `<slug>` 建立机器侧 durable workspace（`projects/<slug>/`）。
> 注册表是单一真相源：导演先在 `AI agent database/PhD-Research-OS/05-registry/project-registry.md`
> 加一行；机器**从不**写注册表，只校验 + 建工作台。Slug = lowercase-kebab，永不改名。

1. 确认导演已在 vault 的 `05-registry/project-registry.md` 加了这个 `<slug>` 的行。
2. 校验注册 + 创建工作台（registry-check 通过才建 `projects/<slug>/`）：
   ```powershell
   python -m research_agent_teams.operate project-init --project <slug>
   ```
3. 读回 JSON：`project_check` 通过 ⇒ workspace 已就位；`error` ⇒ 多半是注册表里没有这个 slug
   （回到第 1 步让导演补行）。
4. 建好后即可 `/start-research`（或直接 `/run-mode`）在这个项目上开跑。
   边界：这一步只动机器侧（`projects/<slug>/`），vault 永不被触碰。
