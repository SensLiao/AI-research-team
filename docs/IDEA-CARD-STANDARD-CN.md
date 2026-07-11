# Idea 卡片标准与投资模板

## 1. Idea 卡的用途

Idea 卡不是一句标题，也不是模型自选方向。它必须把一个研究机会转成可下注、可证伪、可停止的科学投资单元，并明确它与 prior art、上游 gap 和后续实验的关系。

当前合同版本：`idea-investment-memo/v1`。

## 2. 四个独立输入席位

| Bundle | Owner | 只负责什么 |
|---|---|---|
| `IDEATE.bundle.json` | hypothesis generator | hypotheses + original ideas |
| `RANKING.bundle.json` | independent ranker | round-robin tournament + evolved ideas + investment assessment |
| `COLLISION.bundle.json` | prior-art auditor | exact method x problem collision 与 surviving delta |
| `EXPERIMENT.bundle.json` | experiment planner | 最小证伪实验、阈值、资源、风险和阶段依赖 |

四席不得互相代写。确定性层只组装菜单，不替 director 下注；选择写入独立的 `/idea-bet` ADR。

## 3. 每张 Idea 卡必须包含

1. `idea_id` 与一句具体 summary。
2. 可回答的 research question。
3. mechanism hypothesis 与至少两步 causal chain。
4. 对 closest prior art 的具体 delta。
5. why now 与 evidence refs。
6. strongest rejection case。
7. baselines、controls、metrics。
8. success threshold、failure threshold、falsifier、kill criteria。
9. data/compute/time feasibility。
10. main risks 与 mitigation。
11. execution order 与 staged dependency。
12. 失败后 recovery branch 或 PIVOT 条件。

## 4. 排序与选择

机器排序综合 scientific merit、pairwise tournament、feasibility、evidence grounding 和 falsification readiness。排序是 decision aid，不是选择。

Evolved idea 必须保留 `parent_ids`。例如：

- `EV-1 = IDEA-1 + oracle-first 降风险`。
- `EV-2 = IDEA-3 baseline audit + IDEA-4 no-harm branch`。

## 5. Idea 卡模板

```markdown
### <Rank> - <IDEA-ID>: <Title>

#### Research bet memo
- Research question：
- Mechanism hypothesis：
- Causal chain：A -> B -> C
- Intended contribution：
- Why now：
- Independent investment case：
- Strongest rejection case：

#### Prior art and novelty
- Closest prior art：
- Exact difference：method / mechanism / evaluation / data / control regime
- Collision status：collision | adjacent | clear | unverified
- Retrieval limits：

#### Minimum falsification experiment
- Experiment：
- Strongest baseline：
- Controls：
- Metrics：
- Success threshold：
- Failure threshold：
- Falsifier：
- Kill criteria：

#### Staged ladder
| Stage | Type | Purpose | Depends on | Advance | Fail/Kill |
|---|---|---|---|---|---|

#### Feasibility and sequence
- Compute：
- Data：
- Time to first information：
- Main risks / mitigation：
- Execution order：
- Recovery branch / PIVOT：

#### Lineage
- Parent ideas：
- Hypothesis：
- Gap refs：
- Experiment sketch：
```

## 6. 已实施的优化

- 菜单顶部新增 `Portfolio Execution Map`，先显示 first decisive stage、主 kill criterion 和 recovery branch。
- 完整长卡仍保留，避免摘要替代科学细节。
- 每个 candidate 必须有 experiment sketch；confirmed prior-art collision 在菜单前剔除。
- `EV-1` 等组合 idea 保留父级 lineage，不再与原 idea 混成同一张卡。

## 7. 仍需注意

- 自动分数不能覆盖 director 的战略判断。
- `clear` 只表示当前检索未发现相同实验，不等于证明全球 novelty。
- 计划实验不能写成已执行；只有 receipt-bound raw results 才能进入结果链。
- 进入 `full_rigor_minimal` 时必须消费已批准 ADR，而不是简单读取 rank 1。
