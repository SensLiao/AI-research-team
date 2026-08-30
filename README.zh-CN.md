<div align="right"><a href="README.md">English</a></div>

<p align="center"><img src="docs/hero.png" alt="Research Agent Teams banner" width="100%"></p>

<p align="center"><b>经过编排的研究流程：每一条论断都可追溯到来源，并在每一道关卡由人来签核。</b></p>

<p align="center">
<img src="https://img.shields.io/badge/Python-stdlib--first-7c6cf0?style=flat-square" alt="Python stdlib-first">
<img src="https://img.shields.io/badge/Agents-166-7c6cf0?style=flat-square" alt="166 agents">
<img src="https://img.shields.io/badge/Pipeline-7%20stages-7c6cf0?style=flat-square" alt="7-stage pipeline">
<img src="https://img.shields.io/badge/JSON%20Schema-Draft%202020--12-7c6cf0?style=flat-square" alt="JSON Schema Draft 2020-12">
<img src="https://img.shields.io/badge/Human%20gates-5-7c6cf0?style=flat-square" alt="5 human gates">
<img src="https://img.shields.io/badge/License-planned-64748b?style=flat-square" alt="License planned">
</p>

Research Agent Teams 是一个可审计的多智能体研究编排系统。它引导 AI 智能体走完一套真实的研究工作流——从发现到成稿——而不丢失可追溯性与人为控制。每一次运行都会产出一个 **director-review packet（主管评审包）**：证据简报（evidence briefs）、想法下注（idea bets）、实验方案（experiment plans）、一份手稿初稿（manuscript draft），以及一份评审报告（reviewer report）。

证据全程可审计：引用归因（citation attribution）会从一个本地、不可变的快照中重新计算每一条 claim→source（论断到来源）跨度，并且每一次运行都会记录在一条哈希链式、仅追加的账本中。上手最快的方式是运行测试套件（见 [快速开始](#-快速开始)）。

**一次运行的产物——一个 director-review packet：**

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

## 📊 关键数字

| 指标 | 数量 |
| --- | --- |
| 专业化智能体 | 166 |
| 流水线阶段 | 7（DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT） |
| 模式（modes） | 26（其中 23 个已投入运行） |
| 工具（tools） | 146 |
| JSON-Schema 契约 | 170（全部 170 个均可解析） |
| 人工决策关卡 | 5 |
| 测试文件 | 245 |

## 🏗 架构

<p align="center"><img src="docs/architecture.png" alt="Research Agent Teams architecture" width="100%"></p>

运行会流经一条七阶段流水线——**DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT**——并在阶段之间设有 5 道人工决策关卡，需由人签核后工作才会继续推进。智能体以带类型的模式运行并调用一套共享工具；它们产出的每一件产物都会对照 JSON-Schema 契约被校验两次、追加进哈希链式账本，并（在晋升时）通过唯一的一道带关卡的接缝被移入一个独立的研究保险库。

## 🧰 技术栈

- **语言：** Python，标准库优先（standard-library-first）
- **主要依赖库：** PyYAML、jsonschema、cryptography、PyMuPDF、paramiko
- **契约：** JSON Schema Draft 2020-12
- **钩子：** 两个 Node hooks

## 🚀 快速开始

检出目录必须命名为 `research_agent_teams`——模块以 `research_agent_teams.*` 的形式导入。

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

## 📌 项目状态

一个个人研究基础设施项目，由 **Ruixuan Liao** 独立设计并端到端构建。它已可用，并由其测试套件加以检验；请留意上文两条实际注意事项——检出目录必须命名为 `research_agent_teams`，且本仓库不随附打包好的端到端示例项目。仓库计划改名为 `research-agent-teams`。

## 📄 许可证

计划添加许可证，但目前尚未添加——本仓库当前不包含 LICENSE 文件。

<p align="center"><sub>Built by <a href="https://github.com/SensLiao">Ruixuan "Sens" Liao</a> · USYD Advanced Computing (Honours)</sub></p>
