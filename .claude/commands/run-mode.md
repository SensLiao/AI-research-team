---
description: "Start a full mode run (one of the 7 wired modes), then drive the worker -> run-dets -> commit loop stage by stage until the director gate."
argument-hint: "<mode> <slug> [request]"
allowed-tools: Bash, Read
---

# /run-mode — 跑一个完整模式 (Full Mode Run)

> 7 个已接通模式：`new_direction` / `gap_breadth` / `evidence_review` / `evidence_deep` /
> `deep_research` / `venue_readiness` / `full_rigor_minimal`。每个 run 必属于一个已注册项目。

1. **开跑**（创建 run + 打印第一个 stage 的 worker spec；记下回传的 `run_id`）：
   ```powershell
   python -m research_agent_teams.operate begin --mode <mode> --project <slug> --request "..."
   ```
   可选 `--model-policy max_quality`（全 OPUS，导演 lock 的默认）/ `--north-star "..."` 钉死方向。
2. **逐 stage 推进** —— 对每个 stage 走三步循环（spawn worker → 跑确定性 gate → checkpoint）：
   ```powershell
   python -m research_agent_teams.operate worker   --run-id <id> --stage <STAGE>
   python -m research_agent_teams.operate run-dets --run-id <id> --stage <STAGE>
   python -m research_agent_teams.operate commit   --run-id <id> --stage <STAGE>
   ```
   - `run-dets` 退出码 3 + `"gate":"BLOCK"` ⇒ 硬门拒绝，stage 未 commit，如实上报，别绕过。
   - `commit` 回 `paused_for_director: true` ⇒ 到了导演 gate（如 IDEATE 边界即 `/idea-bet`），停下等导演。
3. **诚实边界**：`full_rigor_minimal` 的 EXECUTE **只产出可运行 scripts**——真在 GPU 上跑需要先接通
   服务器（CLAUDE.md §6，目前未接）；没有 journal 时 run_records 结构性地停在 `planned`、metrics 为空，
   绝不把「设计 run」说成「实验真跑了」。
