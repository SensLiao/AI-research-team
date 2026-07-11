---
name: "source-command-run-skill"
description: "Run ONE mid-stage skill (e.g. literature_pull, server_query). Ready when its owning stage is current or already committed; not-ready prints a repair menu and exits 3."
---

# source-command-run-skill

Use this skill when the user asks to run the migrated source command `run-skill`.

## Command Template

# /run-skill — 跑单个 mid-stage skill (One Skill)

> 比整个 stage 更细的执行单元：直接调用一个 skill，而不是跑整模式。
> skill_id 来自 `research_agent_teams/workspace/registries/skill_registry.yaml`，例如：
> `literature_pull`（DISCOVER：拉 + 总结相关论文）、`server_query`（EXECUTE：只读 GPU 状态）。

1. 跑指定 skill（默认操作项目最近的 run；要指定加 `--run-id <id>`）：
   ```powershell
   python -m research_agent_teams.operate run-skill --project <slug> --skill <skill_id>
   ```
   例：
   ```powershell
   python -m research_agent_teams.operate run-skill --project <slug> --skill literature_pull
   ```
2. 读回 JSON 的 `ready`：
   - **ready: true** ⇒ 在它所属 stage 内执行（note 会说它 consumes/produces 什么）。
     注：`server_query` 需先绑定 `primary_gpu` + 环境授权（`RAT_SERVER_QUERY_AUTHORIZED`），且**只读**。
   - **ready: false（退出码 3）** ⇒ 先做 `repair_actions`；缺的输入绝不被 fabricate。
   边界：skill 永不绕过 gate，永不打印任何 secret。
