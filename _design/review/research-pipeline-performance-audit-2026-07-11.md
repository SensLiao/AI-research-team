# AI Research Team 性能审计与优化报告

日期：2026-07-11

## 目标

本轮只优化一件事：在不降低科研质量的前提下，减少无效串行、重复上下文、无数据分析和治理型消耗。六篇论文重读与 ideas 主线在审计期间保持暂停，已有产物没有删除或覆盖。

## 总体结论

- 10 个 operated mode 中，主要性能问题集中在 `evidence_deep`、`deep_research`、`new_direction`、`deep_ideation`、`read_paper_deep` 和 scripts-only 的 `full_rigor_minimal`。
- `gap_breadth`、`evidence_review`、`venue_readiness`、真实结果路径的 `full_rigor_minimal`、`ingest_paper` 已经具有合理的独立性与并行结构，不应为了少几次调用而合并关键科研角色。
- `quality-controller`、`integrity-refusal-recommender`、`novelty-scorer`、`evidence-verifier`、`citation-integrity-auditor` 等多个 registry 角色在 operated 路径中由确定性程序执行，并不占 LLM worker 席位。它们应继续保留为低成本校验，不是本轮资源浪费来源。
- 15 个 spec-only mode 当前没有一键运行性能问题；其中 11 个的未来目标 worker 数大于当前 hop budget。它们在产品化前必须重新对齐预算与真实 DAG，不能按现规格直接接线。

## 优化前后

| Mode | 科研 worker | 优化前 LLM 波次 | 优化后 LLM 波次 | 变化 |
|---|---:|---:|---:|---|
| `new_direction` | 8 | 8 | 7 | DISCOVER 的 formalization 与 contradiction 并行 |
| `deep_ideation` | 9 | 9 | 8 | 同上，保留后续 mechanism 与 analogy 依赖 |
| `gap_breadth` | 8 | 4 | 4 | 已合理：5 个盲猎手并行，后接 prosecution、synthesis、audit |
| `evidence_review` | 6 | 5 | 5 | 已合理：quality 与 claim extraction 并行 |
| `evidence_deep` | 10 | 10 | 7 | quality/claim 并行；search/dataset/staleness 并行 |
| `deep_research` | 12 | 9 | 8 | citation audit 与 contradiction 独立并行 |
| `venue_readiness` | 6 | 4 | 4 | 已合理：3 个 blind reviewers 并行 |
| `full_rigor_minimal`，有真实结果 | 16 | 8 | 8 | 保留全部设计、统计、归因和盲审角色 |
| `full_rigor_minimal`，scripts-only | 16 | 8 | 4 | 无结果时确定性跳过 ANALYZE 4 席与 VERIFY 4 席 |
| `ingest_paper` | 2 | 2 | 2 | extractor 与独立 verifier 必须串行 |
| `read_paper_deep` | 14-20 | 20 | 最多 12 | 20 个角色改为 12 波，planner 可安全跳过不适用专家 |

这里的“波次”是墙钟时间的主要近似，而不是简单 worker 数。独立科研判断仍保留；只有没有信息增量的等待和无数据调用被删除。

## 上下文与重复读取

- `evidence_deep` 的 predecessor bundle 引用数从 45 降到 26，减少约 42%。
- `deep_research` 的 predecessor bundle 引用数从 60 降到 40，减少约 33%。
- 跨 mode 链现在把完整 upstream evidence 只交给根 worker。下游 worker 默认读取本地直接前驱，只保留一个 upstream 指针，避免同一份长摘要复制到每个 prompt。
- upstream handoff 现在显式记录可复用的 search、evidence table、source quality、claim list、claim-evidence、citation audit、contradiction 和 landscape 文件路径，要求先复用再补检索。

## 质量不变的硬边界

本轮没有删除以下角色或责任：

- 独立 citation auditor 与 exact-span 支持判断。
- contradiction miner / gap prosecutor / adversarial reviewer。
- 四个互盲 `deep_research` perspectives。
- venue 的三个 blind reviewers 与 post-hoc meta-review。
- 有真实执行结果时的 statistician、failure attribution、methodology/domain/adversarial review。
- paper deep read 的 blind second reader、reconciliation、citation/figure/result/math/reproducibility audit 和最终质量审计。

scripts-only 快速分支不产生任何结果数字、统计结论、failure attribution 或 result-ready 判断。它只明确记录“没有结果可分析”，因此比让 LLM 写四份空分析更严格。

## 仍需继续优化

1. 给每个 worker invocation 增加稳定的 `worker_key`，避免同一 agent 承担两个工序时 targeted supplement 误刷新两个输出。
2. 建立 project 级、内容哈希寻址的 source/fulltext cache，并带 freshness 与 query-scope 检查；不能直接复用过期搜索。
3. 记录每个 worker 的输入 token、输出 token、等待时间、cache hit 和科学缺陷修复收益，按真实数据继续裁剪。
4. 将 evidence mode 的 dataset specialist 做成证据表驱动的安全激活。只有明确无数据集问题时才能跳过，模糊状态仍启动。
5. spec-only mode 产品化时先重建稀疏 DAG，并修复 11 个“目标 worker 数大于 hop budget”的不可能规格。

## 当前建议

保持现有独立审计骨架，不再继续合并科研角色。下一轮最值得做的是稳定 worker identity、跨 run 内容缓存和真实 token/时延遥测；这三项能继续提速，同时不会把科研质量变成主观猜测。

## 验证

- 聚焦性能与 mode 回归：112 项通过。
- scripts-only full-rigor 与 scheduler 回归：37 项通过。
- 完整测试集：3045 项通过，耗时 134.61 秒。
- 四个主要优化 mode 的真实 scheduler 波次已实际释放并验证：`new_direction=3`、`deep_ideation=4`、`evidence_deep=7`、`deep_research=8`（均指 DISCOVER 阶段）。
