---
name: "source-command-run-stage"
description: "Run ONE FSM stage mid-flight (DISCOVER…REPORT), dependency-checked against the run manifest. Ready -> drives the normal loop; not-ready -> prints a repair menu and exits 3."
---

# source-command-run-stage

Use this skill when the user asks to run the migrated source command `run-stage`.

## Command Template

# /run-stage — 跑单个 stage (One Stage, mid-flight)

> 7 个 stage：`DISCOVER IDEATE DESIGN EXECUTE ANALYZE VERIFY REPORT`。
> 这是在 begin/worker/run-dets/commit 循环之上的「插一刀」——它**从不绕过 gate**，会先对照
> tamper-evident manifest 做依赖检查，再决定能不能跑。机器**从不**编造缺失的输入。

1. 解析这个 stage（默认操作项目最近的 run；要指定就加 `--run-id <id>`）：
   ```powershell
   python -m research_agent_teams.operate run-stage --project <slug> --stage <STAGE>
   ```
2. 读回 JSON 的 `ready`：
   - **ready: true** ⇒ 这个 stage 是 run 的待办下一步，按 `next` 提示走正常循环：
     ```powershell
     python -m research_agent_teams.operate worker   --run-id <id> --stage <STAGE>
     python -m research_agent_teams.operate run-dets --run-id <id> --stage <STAGE>
     python -m research_agent_teams.operate commit   --run-id <id> --stage <STAGE>
     ```
   - **ready: false（退出码 3）** ⇒ 打印 `repair_actions` 修复菜单后退出；先把缺的前置补上
     （多半是上游 stage 没 commit），别试图跳步。
   边界：gate 照常跑，缺失输入绝不被 fabricate。
