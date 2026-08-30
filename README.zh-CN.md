<div align="right"><a href="README.md">English</a></div>

<p align="center"><img src="docs/hero.png" alt="Research Agent Teams — auditable multi-agent research orchestration" width="100%"></p>

Research Agent Teams 是一个可审计的多智能体研究编排系统。它引导 AI 智能体走完一套真实的研究工作流——从发现到成稿——而不丢失可追溯性与人为控制。证据全程可审计：引用归因（citation attribution）会从一个本地、不可变的快照中重新计算每一条 claim→source（论断到来源）跨度，并且每一次运行都会记录在一条哈希链式、仅追加的账本中。上手最快的方式是运行测试套件。

**一次运行的产物——一个 director-review packet（主管评审包）：**

- 证据简报（evidence briefs）
- 想法下注（idea bets）
- 实验方案（experiment plans）
- 一份手稿初稿（manuscript draft）
- 一份评审报告（reviewer report）

## ✨ 亮点

- **天生可追溯** — 引用归因会从一个本地、不可变的快照中重新计算每一条 claim→source 跨度，因此任何论断都能被追溯回它的来源。
- **可验伪的记录** — 一条哈希链式、仅追加的账本，配合单写者锁，记录每一次运行。
- **由人执笔** — 5 道人工决策关卡，在结构上确保模型无法为自己的想法下注。
- **双重校验的产物** — 每一件产物在流转到下游之前，都会对照 JSON-Schema 契约校验两次。
- **可追踪的检索饱和度** — 一条证据检索饱和度（evidence-search-saturation）轨迹，记录检索何时已被穷尽。
- **受控的晋升** — 一道带关卡的晋升接缝，只有通过明确的关卡，结果才会被移入一个独立的研究保险库（research vault）。

## 🏗 架构

<p align="center"><img src="docs/architecture.png" alt="Research Agent Teams architecture — seven-stage pipeline over control, execution and evidence planes" width="100%"></p>

<p align="center"><sub>七个流水线阶段，架设在三个平面之上：控制面、执行与修复、证据与审计。</sub></p>

运行会流经一条七阶段流水线——**DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT**——由一个控制面驱动，其中保存着编排器的阶段图（stage graph）、一份 26 个模式（modes）的注册表，以及一份 166 个专业化智能体的名册。执行运行在一条被操作的主干（operated spine：begin → workers → commit → report）之上，并带有有界修复（bounded repair）；5 道人工决策关卡分布在阶段之间，需由人签核后工作才会继续推进——其位置的安排，使模型在结构上无法为自己的想法下注。运行产出的一切都会经过证据层：170 个 JSON-Schema 契约对每一件产物做双重校验，引用归因把每一条论断系回其来源跨度，哈希链式、仅追加的账本记录整次运行。一次完整的流程以 director-review packet 收尾；而把结果移入那个独立的研究保险库，只能通过唯一的一道带关卡的晋升接缝。

## 🧰 技术栈

| 层次 | 选择 |
| --- | --- |
| 语言 | Python，标准库优先（standard-library-first） |
| 主要依赖库 | PyYAML、jsonschema、cryptography、PyMuPDF、paramiko |
| 契约 | JSON Schema Draft 2020-12 |
| 钩子 | 两个 Node hooks |

由此构成的系统规模：

| 指标 | 数量 |
| --- | --- |
| 专业化智能体 | 166 |
| 流水线阶段 | 7（DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT） |
| 模式（modes） | 26（其中 23 个已投入运行） |
| 工具（tools） | 146 |
| JSON-Schema 契约 | 170（全部 170 个均可解析） |
| 人工决策关卡 | 5 |
| 测试文件 | 245 |

## 🚀 快速开始

前置条件：Python 与 pytest。检出目录必须命名为 `research_agent_teams`——模块以 `research_agent_teams.*` 的形式导入。

```bash
python -m pytest tests/ -q
```

本仓库不包含打包好的端到端示例项目，因此上手最快的方式是测试套件加上阅读架构文档。

## 🧪 测试

本仓库包含 **245 个测试文件**。运行方式：

```bash
python -m pytest tests/ -q
```

全部 170 个 JSON-Schema 契约均可解析，且每一件产物都会对照这些契约进行双重校验。

## 📌 局限

一个个人研究基础设施项目，由 **Ruixuan Liao** 独立设计并端到端构建。它已可用，并由其测试套件加以检验；在克隆之前，有两条实际注意事项值得先知道：检出目录必须命名为 `research_agent_teams`，且本仓库不随附打包好的端到端示例项目。

## 📄 许可证

本仓库当前不包含 LICENSE 文件，因此使用条款尚未确定。

<p align="center"><sub>Built by <a href="https://github.com/SensLiao">Ruixuan "Sens" Liao</a> · USYD Advanced Computing (Honours)</sub></p>
