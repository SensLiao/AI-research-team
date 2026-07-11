# 存储、版本、跨 Mode 流水线与未入库清单

## 1. 三层存储模型

| 层 | 路径 | 内容 | 生命周期 |
|---|---|---|---|
| Workshop scratch | `runs/<project>/<run_id>/` | worker bundles、evidence、ledger、director review | 可删除；不进 Git |
| Project workspace | `projects/<project>/` | 拉取结果、脚本、图、临时研究笔记 | 项目级可重建；不进 Git |
| Permanent vault | `AI agent database/PhD-Research-OS/` | 已批准论文、claims、experiments、decisions | 永久；仅 `/promote-to-vault` 写入 |

GitHub 发布只包含 machine 代码、agents、modes、schemas、tests、profiles、模板和文档。绝不包含实际 runs、projects、PDF、真实 vault 内容或 credentials。

跨 run 的科研进展报告放在 `projects/<project>/reports/progress/<period>/progress.md`。它可以引用多个
run 的 frozen handoff，但仍属于项目工作区；普通周报、临时图和运行索引不进入 vault。只有人类确认具有长期价值的
结论、决策或冻结结果，才通过 `/promote-to-vault` 转为永久知识页。

## 2. 一个 run 的标准目录

```text
runs/<project>/<run_id>/
  task_frame.artifact.json       # immutable request / north star / mode / budget
  manifest.yaml                  # run status and committed stage outputs
  ledger.jsonl                   # tamper-evident boundary history
  inbox/                         # worker bundles and upstream handoff
    upstream-grounding.json      # mode-handoff/v2
    supplements/                 # local incremental repair, never whole-stage overwrite
  evidence/<STAGE>/              # validated machine artifacts
  director-review/               # primary human Markdown products
    00-REVIEW-PACKET.md
```

## 3. 三个不同的版本号

1. `schema_version`：单个 artifact payload/envelope 的结构版本。
2. `product_version`：一个 mode 对下游承诺的科研产品版本，例如 `paper-reading/v3`、`research-brief/v2`、`idea-investment-memo/v2`。
3. `mode-handoff/v2`：跨 run/mode 的运输合同，记录路径、相对路径、SHA-256、artifact type、schema version、run status 和 delivery status。

三者不能混用。schema 相同不代表产品语义兼容；文件名相同也不代表 hash 相同。

新 run 会把完整 `product_contract` 冻结进 `task_frame.artifact.json`，并随 task frame 一起进入
hash-chained ledger。后续 registry 升级不能把历史 run 重新解释为新产品版本。旧 run 没有冻结合同时，
只能使用显式标记为 `registry_fallback_for_legacy_run` 的兼容回退，不能伪装成已冻结。

## 4. 跨 Mode 接口

每个 operated mode 在 `orchestrator/mode_registry.yaml` 声明：

```yaml
handoff:
  contract_version: mode-handoff/v2
  product_version: <semantic product version>
  primary_markdown: <human entry>
  reusable_artifacts: [<machine evidence>]
  accepts: [<compatible upstream product versions>]
```

启动下游时：

1. 检查上游 `product_version` 是否在下游 `accepts` 中。
2. 生成 `upstream-grounding.json`。
3. 把 `upstream-grounding.json` 自身的 SHA-256 记录进下游 ledger；防止路径、版本与期望 hash 被一起替换。
4. 下游读取前重新计算每个上游文件 SHA-256；missing/replaced file 直接停止连接，不重跑上游。
5. 按 registry 的 `reusable_artifacts` 实际解析文件；缺失项进入 `missing_declared_artifacts`，不再只写声明不执行。
6. 下游复用上游 artifact，不重复检索和总结。
7. 科研内容是否正确由上游自己的 quality status 负责；handoff 只验证运输完整性和语义版本。

推荐主线：

```text
paper-reading/v3
  -> evidence-deep/v2 or research-brief/v2
  -> gap-dossier/v1
  -> idea-investment-memo/v2
  -> /idea-bet ADR
  -> full-rigor/v2
  -> venue-readiness/v2
  -> /promote-to-vault
```

## 5. 修复与版本替换

- 原 bundle 永久保留在 run 中。
- 局部补充写入 `inbox/supplements/<stage>/repair-xxx/`。
- repair plan 记录 supersedes hash、changed paths 和新 hash。
- 格式兼容由确定性 normalizer 完成，消耗 0 research worker hops。
- 只有核心 claim 变化才刷新依赖它的下游；标题、字段别名和 Markdown 表达不刷新科研链。

## 6. 2026-07-11 未入库清单

当前有 9 个最新 run package 在 vault 中均为 0 引用：

| 类型 | 数量 | 状态 |
|---|---:|---|
| 六篇核心论文深读 | 6 | 可供 director 审阅；尚未 promote |
| Deep research brief | 1 | 可用；尚未 promote |
| Gap dossier | 1 | 可用；尚未 promote |
| Idea portfolio + EV-1 ADR | 1 | 已有人类 bet；实验尚未执行 |
| 真实 GPU result | 0 | 没有可入库结果 |

对应 run IDs：

- `hq2-read-autopetv-official-20260711`
- `hq2-read-cbdice-20260711`
- `hq2-read-cldice-20260711`
- `hq2-read-deepigeos-20260711`
- `hq2-read-flans-20260711`
- `hq2-read-ritm-20260711`
- `deep_research-20260711T075139Z`
- `gap_breadth-20260711T080148Z`
- `deep_ideation-20260711T080452Z`

建议 promotion 顺序：先审六篇 paper card，再审 research brief 和 gap dossier，最后审 idea portfolio/ADR。实验计划可以进入项目决策区，但不能登记成实验结果。

## 7. 当前判断

旧规则的主要问题是跨 mode 依赖绝对路径与文件名，缺少产品语义版本、冻结合同和 hash manifest。
`mode-handoff/v2` 已修复这一点：产品合同随 task frame 冻结，handoff manifest 自身进入 ledger，声明的
reusable artifacts 会被实际解析；同时保留旧的 `key_artifacts`/`reusable_inputs` 字段，现有 worker prompt 不需要重写。

后续如升级产品语义，应增加新 `product_version` 并显式声明兼容关系；不要原地改变同一版本的含义。
