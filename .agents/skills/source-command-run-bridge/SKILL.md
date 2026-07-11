---
name: "source-command-run-bridge"
description: "Run ONE stage-transition bridge (e.g. design_to_execute). Ready when the 'from' stage is committed and the 'to' stage is pending; not-ready prints a repair menu and exits 3."
---

# source-command-run-bridge

Use this skill when the user asks to run the migrated source command `run-bridge`.

## Command Template

# /run-bridge — 跑单个 stage 过渡桥 (One Bridge)

> Bridge = 两个相邻 stage 之间的交接：把上游 stage 已 commit 的产物转成下游 stage 的输入。
> bridge_id 来自 `research_agent_teams/workspace/registries/bridge_registry.yaml`，例如：
> `discover_to_ideate`（证据+gap → 排序的 idea 候选）、`design_to_execute`（实验协议+scripts → 可跑的 job plan）。

1. 跑指定 bridge（默认操作项目最近的 run；要指定加 `--run-id <id>`）：
   ```powershell
   python -m research_agent_teams.operate run-bridge --project <slug> --bridge <bridge_id>
   ```
   例：
   ```powershell
   python -m research_agent_teams.operate run-bridge --project <slug> --bridge design_to_execute
   ```
2. 读回 JSON 的 `ready`：
   - **ready: true** ⇒ note 会显示 `from_stage -> to_stage` 与 `required_skills`；之后按正常循环
     commit `to_stage`。
   - **ready: false（退出码 3）** ⇒ 先做 `repair_actions`（通常是 from_stage 还没 commit，或 to_stage
     不是当前待办）；缺失输入绝不被 fabricate。
   边界：bridge 永不绕过 gate，vault 永不被触碰。
