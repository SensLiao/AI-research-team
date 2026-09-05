# gap_breadth 科研问题挖掘面板

本文档描述 `operate/modes/gap_breadth.py` 的 operated worker contract。它关注的是科研问题质量，
不是项目治理。最终人类产物固定为 `director-review/gaps/gap-scan.md`；worker JSON 只作为可追溯证据。

## 科研流水线

```text
Wave 1（并行、互相独立）
  future-work-miner
  weakness-spotter
  white-space-mapper
  cross-domain-transfer-scout
  contrarian-angle-generator

Wave 2（读取冻结的五份 hunter bundle）
  gap-prosecutor

Wave 3（读取 hunter + prosecution）
  mechanism-synthesizer

Wave 4（读取全部前序产物，独立审计）
  gap-quality-auditor

Deterministic gates
  完整性、证据状态、知识象限、机制 dossier、六维审计、Markdown lint
```

五个 hunter 必须互相独立，避免相互锚定。后三个 worker 必须串行，避免 prosecutor 在看到“漂亮机制”后替候选
辩护，也避免 auditor 复用 synthesizer 的自评分。

## 三个后置角色

### gap-prosecutor

目标不是证明新颖，而是尽最大努力找到能够关闭候选 gap 的确切论文或结果。

- 为每个 hunter gap 生成 method × problem × setting 的针对性检索式。
- 阅读论文范围和结果位置，不能只看标题或摘要相似度。
- `CLOSED`：必须给出真实论文、已经完成的 scope、结果 locator。
- `OPEN`：必须给出来源定位明确的未解决限制、边界或作者陈述。
- `UNVERIFIED`：检索缺失、检索失败、覆盖不足、只有“没搜到”时的唯一合法状态。
- 每个输入 gap 恰好一条 prosecution，不得遗漏、合并或暗中淘汰。

### mechanism-synthesizer

对所有非 `CLOSED` gap 建立可证伪 dossier，不负责押注。

每份 dossier 必须包含：

- 知识象限及判定依据；
- 精确问题陈述、证据和为什么仍开放或未验证；
- 最近 prior art 及其尚未覆盖的边界；
- 至少两步机制或因果链；
- 跨域桥、适配条件和失效边界；
- 最强反对理由与反证；
- 最小判别实验、baseline/control、success/failure/kill；
- 数据、算力、实现、工期和下一步。

### gap-quality-auditor

独立审计每个 survivor，不平均掉异议，不做 director decision。

六个维度均为 1-5 分，并必须给出理由：

| 维度 | 权重 | 科研含义 |
|---|---:|---|
| importance | 25% | 回答后会改变什么科学认识或决策 |
| openness | 10% | 是否有正面证据显示问题尚未闭合 |
| falsifiability | 20% | 是否存在能够推翻命题的观察或实验 |
| information_gain | 20% | 最小实验能否显著减少不确定性 |
| mechanism_clarity | 20% | 是否有明确、可检验的作用链和失效条件 |
| feasibility | 5% | 资源可达性，只是小维度，不能主导科学排序 |

审计结果：

- `PASS`：dossier 足以进入人类评阅，不代表批准。
- `REVISE`：有价值但证据、机制或实验合同需要明确修补。
- `BLOCK`：当前不支持、不可证伪或被实质反证；修复前不得推进。

## 四类知识问题

| 象限 | 在本 mode 中的操作定义 |
|---|---|
| Known Known | 已被可靠建立、用于限定问题和设计 controls 的知识 |
| Unknown Known | 其他领域或来源已经知道，但当前问题尚未建立连接的知识 |
| Known Unknown | 文献明确承认的未知、限制或开放边界 |
| Unknown Unknown | 从异常、失败模式或共享假设中挖出的盲点，风险和不确定性最高 |

象限不是新颖度等级。`Unknown Unknown` 不天然优于 `Known Unknown`，`Unknown Known` 也不意味着迁移必然有效。

## 硬边界

1. 没搜到论文不等于 gap；只能标 `UNVERIFIED`。
2. 改变 `OPEN/CLOSED` 状态的外部证据必须是可核验 DOI、arXiv id 或真实 vault page；联网失败时降回 `UNVERIFIED`。
3. novelty score 只保留为历史/检索信号，不进入科学机会主排序。
4. 最终排序由独立六维审计确定，feasibility 权重仅 5%。
5. `CLOSED` gap 不进入 survivor dossier，但必须在 Markdown 中列出关闭论文和结果定位，不能静默消失。
6. 所有 survivor 和 closed gap 都必须出现在 Markdown；不得以模型偏好自选或 self-bet。
7. 运行仍停在 scratch；只有后续人类 gate 能决定是否进入 `new_direction` 或其他流程。

## 定向返修

- hunter 缺失或引用虚构：只重跑对应 hunter。
- closure status 无证据或矛盾：重跑 `gap-prosecutor`，并使后续 dossier/audit 失效。
- dossier 缺机制、反证或最小实验：重跑 `mechanism-synthesizer`，随后重跑 auditor。
- auditor 维度缺失、分数无理由或非 PASS 无 repair：只重跑 `gap-quality-auditor`。
- Markdown lint 失败：修复渲染输入或 gap 专属 renderer，不能删除质量栏目绕过。
