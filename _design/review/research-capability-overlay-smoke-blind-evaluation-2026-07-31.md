# Research Capability Overlay：Stage-A 盲评对账

日期：2026-07-31  
状态：`BLIND_RECONCILIATION_COMPLETE / QUALITATIVE_IMPROVEMENT_OBSERVED / PREREGISTERED_STAGE_A_PASS_NOT_MET / STAGE_B_REQUIRED`

## 1. 结论

三名互盲 judge 已对五个请求的 X/Y 输出完成评分，且 judge 文件所绑定的 blind packet 与实际盲包一致。揭盲后，X 是 baseline，Y 是 capability-overlay enhanced。增强组在五个请求上均不劣于 baseline，三评审平均总分从 `29.73/32` 上升到 `31.40/32`，平均配对差为 `+1.67`；改善主要来自 Q7 可执行与可追溯性。

但预注册 Stage-A 通过规则没有全部满足：

- 无 judge 报告输出级 fatal defect，但 A/B resolved runtime model 与实际 token/budget 没有独立 receipt，因而最后一条 A/B parity fatal 条件只能记为“没有发现不一致、但不能独立证实一致”。
- 增强组 S2 的 Q3 证据深度三评审均值为 `2.67`，其中方法/统计 judge 给 `2`，低于预注册下限 `3`。
- 以保持原始 `0–32` 量尺的“三 judge 总分均值/请求”作为对账单位，并按中文“2 分以上”的通常包含式语义解释为 `≥2`，S1、S2、S3 共 `3/5` 达标。若事后改用严格 `>2`，则只有 `2/5`；预注册文本没有冻结这个严格解释，故它只作为敏感性说明，不能替代主判定。

因此本轮 verdict 是：

```text
ROUTING_SMOKE_PASS
+ STAGE_A_BLIND_OUTPUT_EVAL_COMPLETE
+ QUALITATIVE_IMPROVEMENT_OBSERVED
+ PREREGISTERED_STAGE_A_PASS_NOT_MET
+ A_B_PARITY_PROVENANCE_CAVEAT
+ STAGE_B_20_REQUEST_PREREGISTERED_EVALUATION_REQUIRED
```

Stage A 本来就不能建立统计显著性；本结果也不得写成“显著提升”“paired evaluation pass”或由 overlay 导致的已证实因果改善。

## 2. 输入、揭盲与完整性链

### 2.1 冻结分组事实与揭盲

parent dispatch contract 冻结的生成条件为：两组均使用 `fork_turns=none`、`agent_type=default`、同五个 prompts、每题同为最多 350 中文词、且均无额外 source packet；唯一 intended treatment 是 baseline 禁止读取 overlay，而 enhanced 读取并应用同一 pinned overlay catalog。没有生成 resolved model、service tier 或 token-usage envelope。

密封映射揭示：

| 盲标 | 源文件 | 生成条件 |
|---|---|---|
| X | `author-a.md` | baseline ordinary reasoning；禁止读取 overlay |
| Y | `author-b.md` | enhanced；要求读取并应用 pinned overlay catalog |

`sealed-mapping.json` 本身只密封了 `X/Y → author file`，没有密封 `author file → baseline/enhanced condition`。因此第三列来自 parent dispatch contract，而不是密封文件。这是 provenance 缺口，不影响对现有 X/Y 分数的算术复核，但阻止本轮成为可独立重放的严格因果 A/B receipt。

### 2.2 SHA-256 与 packet 重建

| 文件 | 实算 SHA-256 | 核验结果 |
|---|---|---|
| `blind-packet.md` | `6ce0c5d292b428adc266f5c538e403a0ad6ecea55432a1a45ea16fbf803a5f44` | 与 sealed mapping 及三份 judge 的 `packet_sha256` 全部一致 |
| `sealed-mapping.json` | `95481461c601ab4e4bbdb2ee7730a10b04fc53320ad595b1912671fb0c52d358` | 本次对账记录；此前没有独立 self-hash/ledger commitment |
| `judge-domain.json` | `1d1d3b124e1097677b7ae9271a49f4fce9e06dc17e735126849bda8a71c7ecc3` | JSON 可解析、公共语义 shape 通过、packet hash 一致 |
| `judge-methods.json` | `8dfe061779648c021625fc8ff7a2d08af886f57c799b9ab7b7bb67f539298f76` | JSON 可解析、公共语义 shape 通过、packet hash 一致 |
| `judge-evidence.json` | `b1d77599eef12b56910dcd06b156f6fb53c482903101c5617e6823fc76686bde` | JSON 可解析、公共语义 shape 通过、packet hash 一致 |
| `author-a.md` | `91bab4875f7df69d0bda9bc981a72460c57367b43006534c57aeb778886f610e` | 与 sealed mapping 一致 |
| `author-b.md` | `d64df1908d1292e3c9e010ff8e6cd3ce5de2414c42adfd0e56fa4832be8535f3` | 与 sealed mapping 一致 |

进一步核验：

- S1–S5 的 X 文本逐段等于 `author-a.md` 对应段，Y 文本逐段等于 `author-b.md` 对应段。
- 以两个小写 source SHA-256 无分隔符拼接后重算，`author-a.md_then_author-b.md` 为 `ac2b2f0ddada7072f025cd6e45dd5642af02e28c955760597c796f15144d78bc`，`author-b.md_then_author-a.md` 为 `ca5e9614741cd51d843cb7eeef47ca8f9e64667990fa236524564e11f0c5695d`。前者字典序更小，故 X=`author-a.md`、Y=`author-b.md` 与密封选择规则一致。
- 三份 judge 均覆盖且仅覆盖 S1–S5；每案均含 X/Y、Q1–Q8 整数分数、fatal defect 数组、winner 与非空 rationale；所有分数均在 `0–4`；winner 与各自 Q1–Q8 总分方向一致。
- 三份 judge 的公共语义 shape 通过，但它们没有使用同一结构化 schema：两个文件的 `cases` 是 object，一个是 array，且 `rubric_version` 三种写法不同。这里是自定义公共 shape 验证，不应冒充对单一发布版 JSON Schema 的验证。

## 3. 逐案、逐 judge 总分

每个候选每案总分为 Q1–Q8 之和，范围 `0–32`。差值统一为 `enhanced(Y) − baseline(X)`。

| 请求 | judge | baseline X | enhanced Y | 差值 | 盲评 winner |
|---|---|---:|---:|---:|---|
| S1 | 领域/机制 | 29 | 32 | +3 | Y |
| S1 | 方法/统计 | 27 | 30 | +3 | Y |
| S1 | 证据/诚信 | 28 | 32 | +4 | Y |
| S2 | 领域/机制 | 27 | 30 | +3 | Y |
| S2 | 方法/统计 | 27 | 30 | +3 | Y |
| S2 | 证据/诚信 | 29 | 31 | +2 | Y |
| S3 | 领域/机制 | 30 | 32 | +2 | Y |
| S3 | 方法/统计 | 30 | 32 | +2 | Y |
| S3 | 证据/诚信 | 30 | 32 | +2 | Y |
| S4 | 领域/机制 | 32 | 32 | 0 | TIE |
| S4 | 方法/统计 | 32 | 32 | 0 | TIE |
| S4 | 证据/诚信 | 30 | 31 | +1 | Y |
| S5 | 领域/机制 | 32 | 32 | 0 | TIE |
| S5 | 方法/统计 | 32 | 32 | 0 | TIE |
| S5 | 证据/诚信 | 31 | 31 | 0 | TIE |

逐请求聚合采用三位 judge 总分的算术均值，避免把“跨 judge 求和后的 +6”错误解释成原 `0–32` 量尺上的“提高 6 分”。

| 请求 | baseline 均值 | enhanced 均值 | 配对差 | judge winner 构成 | 不劣于 | `≥2` |
|---|---:|---:|---:|---|---|---|
| S1 | 28.00 | 31.33 | +3.33 | 3×Y | 是 | 是 |
| S2 | 27.67 | 30.33 | +2.67 | 3×Y | 是 | 是 |
| S3 | 30.00 | 32.00 | +2.00 | 3×Y | 是 | 是 |
| S4 | 31.33 | 31.67 | +0.33 | 1×Y、2×TIE | 是 | 否 |
| S5 | 31.67 | 31.67 | 0.00 | 3×TIE | 是 | 否 |
| 全部 | 29.73 | 31.40 | +1.67 | 10×Y、5×TIE、0×X | 5/5 | 3/5 |

judge 的离散 winner 在 S1、S2、S3 为一致 Y，在 S5 为一致 TIE；S4 是两名 TIE、一名 Y。五案中四案完全一致，即 raw exact agreement 为 `80%`。样本只有五案且类别高度偏斜，本轮不把该比例升级成可靠的一致性系数。

## 4. Q1–Q8 维度均值

每个均值覆盖 `5 请求 × 3 judges = 15` 个评分。

| 维度 | baseline X | enhanced Y | Y−X |
|---|---:|---:|---:|
| Q1 scope fidelity | 4.00 | 4.00 | 0.00 |
| Q2 机制与可证伪性 | 3.67 | 3.93 | +0.27 |
| Q3 证据深度 | 3.47 | 3.60 | +0.13 |
| Q4 实验有效性 | 3.67 | 3.93 | +0.27 |
| Q5 跨学科转译 | 3.60 | 3.93 | +0.33 |
| Q6 result–claim calibration | 4.00 | 4.00 | 0.00 |
| Q7 可执行与可追溯 | 3.40 | 4.00 | +0.60 |
| Q8 最终表达 | 3.93 | 4.00 | +0.07 |

最大观察改善是 Q7；Q1 与 Q6 两侧已在天花板。维度总均值不能代替逐请求核心维度门槛。增强组逐案 Q1/Q3/Q4/Q6 中，唯一低于 3 的聚合单元是 `S2/Q3=2.67`，其 judge 原始值为 `[3,2,3]`。

## 5. 预注册规则逐条判定

| 规则 | 结果 | 判定 |
|---|---|---|
| 无 fatal defect | 30 个候选×请求评分单元的 `fatal_defects` 均为空；judge 未发现 fabrication、false execution、leakage、越权或 canonical drift | 输出内容层面通过；A/B runtime/budget parity 缺独立 receipt，保留 provenance caveat |
| 每请求 Q1/Q3/Q4/Q6 ≥3 | enhanced 的 S2/Q3 均值 `2.67`，且单 judge 最低为 `2` | **不通过** |
| B 至少 4/5 请求不劣于 A | 三 judge 均值差为 `[+3.33,+2.67,+2.00,+0.33,0.00]` | **通过：5/5** |
| B 至少 3/5 请求总分提高 2 分以上 | 按预注册中文的通常包含式语义 `≥2`，S1、S2、S3 达标；严格 `>2` 的事后敏感性计数为 2/5 | **通过：3/5** |

结论不依赖对“不劣于”的宽松解释：没有任何 judge 在任何请求上给 X 更高总分，也没有任何 winner 写为 X。改善计数按包含式阈值通过；Stage-A pass 因核心维度 floor 失败而仍不成立，A/B parity receipt 缺口则进一步阻止严格的因果归因。

## 6. 小样本配对描述

这部分是事后透明描述，不是预注册 confirmatory test。统计单位是请求；先对三位 judge 的 `0–32` 总分取均值，再做五个请求的配对差：

```text
[3.3333, 2.6667, 2.0000, 0.3333, 0.0000]
mean = 1.6667 points
```

- 穷举 paired case bootstrap：从五个请求有放回抽取五个，枚举全部 `5^5=3125` 个有序重采样；用线性插值 percentile 得到描述性 95% interval `[0.53, 2.80]` 分。
- 精确 paired sign-flip：去除一个零差请求，对四个非零配对差枚举 `2^4=16` 种符号；观察均值 `+1.6667`，双侧 `p=0.125`，单侧 `p=0.0625`。

bootstrap interval 在五个全非负案例上不跨 0，而精确 sign-flip 双侧值仍为 0.125，正说明 `n=5` 时 percentile bootstrap 很不稳定。两者都只能描述这五个 smoke fixtures；不得用来声称统计显著性、总体泛化或 overlay 的因果收益。

## 7. 缺陷与具体修复

1. **Condition 标签未进入 seal。** `sealed-mapping.json` 只含 X/Y 与 author 文件。下一轮在任何 judge 看包前写入不可变 `condition_manifest.json`，至少密封 condition id、prompt hashes、overlay catalog hash、source packet hash/none、author artifact hash 和 X/Y mapping；再把 manifest hash 写入 tamper-evident ledger。
2. **Runtime/model/budget parity 没有 receipt。** parent dispatch 固定了 agent type、prompt 与字数上限，但未记录 resolved model、service tier、context/token budget 与实际 usage。Stage B 必须为每个 pair 保存同 runtime policy、同预算及 usage receipt；唯一允许差异是预注册 treatment。
3. **Judge schema 不统一。** 下一轮发布一个 `judge-sheet.schema.json`，冻结一个 `rubric_version`、统一 object/array 结构，并用确定性 validator 产出 validation receipt；judge 文件及 validator receipt 的哈希一并 seal。
4. **S2 证据深度未过 floor。** enhanced S2 应为每个方向加入 `source_ref / borrowed principle / translated mechanism / evidence status / prior-art collision status` 矩阵；没有冻结来源时明确写 `UNVERIFIED`，在排序前触发定向证据检索与 collision check，不能只靠概念类比和良好的实验设计获得 Q3 通过。
5. **Stage-A 聚合单位与边界符号未写死。** “每请求提高 2 分以上”没有说明三名 judge 如何聚合，也没有用符号冻结包含式 `≥2` 或严格式 `>2`。本次采用不改变 `0–32` 量尺的 judge 均值，并按中文通常语义取 `≥2`；不得使用跨 judge 总和放大差值。Stage B 需在开包前冻结 primary score、judge aggregation、边界符号、tie 规则、缺失评分处理、最小有意义差值和区间方法。
6. **S3–S5 有明显天花板。** baseline 在这些请求已为 `30–31.67/32`，使两分阈值难以辨别增益。不能事后改 Stage-A 门槛；Stage B 应预注册更有区分度的真实/半真实请求和对抗性缺失输入，同时保留全部失败例，避免只选 overlay 易赢的案例。

## 8. Stage B 必须保留的边界

若要支持“质量提升”，仍须完成至少 20 个预注册、跨学科与任务类型覆盖的 paired requests，并在揭盲前冻结：

- 输入、source packet、overlay treatment、resolved model、service tier、预算与实际 usage receipt；
- primary paired score、最小有意义差值、judge aggregation、配对 permutation/bootstrap 方法和 judge-agreement 指标；
- Q1/Q3/Q4/Q6 非系统性下降规则、fatal defect 处理和全部失败例公开方式。

只有 Stage B 无 fatal defect、primary 差值达到预设最小值且预注册区间不跨 0，才可考虑 `PAIRED_EVALUATION_PASS`。本文件没有修改 `blind-packet.md`、`sealed-mapping.json`、任何 author 源文件或任何 judge JSON。
