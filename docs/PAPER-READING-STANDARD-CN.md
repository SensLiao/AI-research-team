# 论文阅读标准与卡片模板

## 1. 目标

论文阅读的目标不是复述摘要，而是形成一个可以继续支持研究决策的可追溯判断：论文实际证明了什么、没有证明什么、方法如何工作、数字与图表是否支持主张、与当前项目有什么直接或间接关系、下一步应该做什么。

日常阅读优先交付可读 Markdown。JSON/schema 是机器证据层，不能因为标题、字段别名或非核心覆盖不足而推倒重读。

## 2. 两个阅读等级

| 等级 | Mode | 用途 | 输出 |
|---|---|---|---|
| 快速收录 | `ingest_paper` | 建立可检索的基本论文记录 | quick paper note |
| A-core 深读 | `read_paper_deep` | 核心论文、方法依据、实验设计依据 | `director-review/papers/<paper>.md` |

## 3. A-core 团队与执行顺序

当前名义上有 20 个科学职责，但按依赖关系执行为约 12 wave，不是 20 个串行签字：

1. blind second reader + reading planner
2. primary paper note
3. structure/figure/table map + project alignment
4. claim extraction
5. claim-evidence linking + method teardown + paper relations
6. independent citation audit + figure reading + math/algorithm audit
7. numeric result audit + reproducibility materials audit
8. critical appraisal
9. trend + domain transfer
10. blind/primary reconciliation
11. scientific quality audit
12. Chinese Markdown writer

以下职责不可省略：独立盲读、独立 citation audit、reconciliation、核心真实性检查。数学、视觉、数值结果、trend 和 transfer 等职责由 planner 根据论文类型决定是否运行；不适用时生成明确的 `not-applicable`，不调用科研 worker。

## 4. 必须回答的科学问题

1. 决策问题：为什么现在读这篇，它要改变哪个研究判断？
2. 来源边界：使用的版本、PDF/snapshot、页码和 hash 是什么？
3. 主张：哪些是作者直接证明的，哪些是解释或迁移推断？
4. 证据位置：每个核心 claim 对应哪个 section、table、figure 或公式？
5. 方法：输入、表示、训练流、推理流、loss、假设和失败机制是什么？
6. 数字：比较对象、数据切分、指标、数值和统计条件是否公平？
7. 图表：load-bearing figure/table 是否真正支持正文结论？
8. 批判：最强替代解释、泄漏风险、外推边界和未承认局限是什么？
9. 复现：代码、数据、配置、随机种子和关键缺失材料有哪些？
10. 项目关系：它对当前 idea、baseline、control 或 kill criterion 有什么作用？
11. 下一步：应复用什么、验证什么、禁止声称什么？

医学影像论文额外检查 patient-level split、模态/spacing、annotation protocol、病灶/器官分层、拓扑与临床失败事件，以及 oracle 信息是否进入可部署 arm。

## 5. 质量状态

| 状态 | 含义 |
|---|---|
| `USABLE` | 核心证据闭环，可直接用于后续研究 |
| `USABLE_WITH_CAVEATS` | 核心内容可用，但存在明确限制 |
| `NEEDS_SUPPLEMENT` | 有一个局部科研缺口，只补对应角色 |
| `BLOCK` | 核心来源缺失/伪造、snapshot 被替换、核心 claim 无支持、数字/比较失真、泄漏或虚假执行 |

Markdown 长度、标题措辞、非核心图表遗漏、字段顺序和 richer-than-schema 输出不触发科研重读。严格完整闭环只在 `/promote-to-vault` 再执行。

## 6. 人类可读卡片模板

```markdown
# <Paper title>

> Delivery status: USABLE | USABLE_WITH_CAVEATS
> Source: <paper ref / DOI / URL / local snapshot>
> Project: <project slug>

## 1. 决策问题
- 为什么读：
- 希望改变的判断：
- 一句话结论：

## 2. 项目关联
- 直接支持：
- 间接先例：
- 不能支持：

## 3. 主张与证据
| Claim ID | 主张 | 证据位置 | 支持强度 | 边界 |
|---|---|---|---|---|

## 4. 方法或理论重建
- 输入与输出：
- 表示/架构：
- 训练流程：
- 推理流程：
- Loss / 公式：
- 核心机制假设：

## 5. 数值结果审计
| Table/Result | 比较 | 指标 | 数值 | 是否公平 | 备注 |
|---|---|---|---|---|---|

## 6. 图表解读
| Figure/Table | 它证明什么 | 它没有证明什么 | 是否 load-bearing |
|---|---|---|---|

## 7. 批判性评价
- 最强贡献：
- 最强替代解释：
- 已承认局限：
- 未承认局限：
- 数据泄漏/公平性风险：

## 8. 可复现性
- 已有材料：
- 缺失材料：
- 最小复现路径：

## 9. 跨域迁移
| 可迁移机制 | 当前项目对应物 | 阻断假设 | 必需本地验证 |
|---|---|---|---|

## 10. 独立复核与分歧
- Blind reader 发现：
- Primary reader 发现：
- Reconciliation：

## 11. 医学影像检查表（适用时）
- Patient-level split：
- Annotation / modality / spacing：
- Clinical failure events：
- Oracle quarantine：

## 12. 下一步
1. 可以直接复用：
2. 必须先验证：
3. 不允许写进论文的过度结论：
```

## 7. 当前建议

- 保留上述标准，但不要求每篇都调用完整 20 个 worker；以 planner 的科学适用性裁剪。
- 卡片顶部增加 10 行以内的 decision snapshot，长证据表放后面。
- 单篇论文卡不声称 literature saturation；多来源结论交给 `evidence_deep` 或 `deep_research`。
- 论文卡进入后续 mode 时使用 `mode-handoff/v2` 的 hash 和 product version，不靠文件名猜版本。
