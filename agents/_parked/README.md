# `agents/_parked/` — 写好了但没接线的 agent 规格

`tools/worker_census.py::agent_files()` 扫的是 `agents/*.md`（**非递归**），所以放进这个子目录的
规格文件不会被当成在册 agent。它们**没有被删除**，随时可以一条 `mv` 挪回去。

放进来的唯一条件：这份规格**没有任何东西引用它** —— 不在 `orchestrator/roster.yaml`、
不在 `orchestrator/graph.yaml` 的任何 stage、不在 `mode_registry.yaml` 任何 mode 的 `agent_subset`、
不在任何 recipe 或 tool 里。也就是说，它在册只会让 census 报"孤儿 agent"，而不会让机器多出任何能力。

要把一份规格接回线，四件事缺一不可：
1. `orchestrator/roster.yaml` 里加名字（放进它 `stage:` 对应的分组）；
2. `orchestrator/graph.yaml` 对应 stage 的 `allowed_agents` 里加名字；
3. 至少一个 mode 的 `agent_subset` 里加名字（否则 `_panel_recipe.py::panel()` 会在派工时拒绝）；
4. 它的运行时输出要与 recipe 一致：科研控制 artifact 才进 schema；直接 `.tex/.bib/.md/.tsv`
   工作文件由调度器文件所有权和阶段 reducer 检查，不为它们另造 JSON schema。

---

## `contribution-ledger-builder.md` · `threats-to-validity-writer.md`（2026-08-20 停放，导演授权）

- **来源**：2026-08-20 team-upgrade 审计 Q4（`_design/2026-08-20-team-upgrade/01-seats-and-dispatch.md`）。
  两席都在 manuscript_review 的 registry `agent_subset` 里挂名，但 recipe 从未派发过
  （`operate/modes/manuscript_review.py` 零引用）——正是"在册 ≠ 会派"的活例子。
- **谁接替**：贡献审计由 `manuscript-domain-contribution-reviewer`（盲评能力位）+ 确定性
  reducer 承担；limitations/threats 文本由 authoring 合同的 section owner 撰写、由
  methods/adversarial 评审攻击。工具核 `tools/check_contribution_binding.py` 与
  `tools/check_threats_coverage.py` 保留在册，测试照跑。
- **同批清理**：`synthesis-writer` 已从三个 spec-only `minimum_worker_pipeline` 移除；这些模式
  的 Markdown 由确定性 renderer 负责，不再用一个未消费的 LLM agent 增加 token。
