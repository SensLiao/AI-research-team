# 独立 Goal：Research Capability Overlay 完成与评估矩阵

日期：2026-07-31  
状态：`EVALUATION_CONTRACT / NOT_A_RUNTIME_RECEIPT`  
适用对象：本轮独立 goal 的服务器资源、PET/CT 静态科研审阅、外部科研 skills 选择性接入与质量评估

## 1. 独立范围与事实边界

本文件定义本轮独立 goal 如何判定“做完”和“确实变好”。它不延续此前 heartbeat/Dashboard 格式整理任务，也不把外部仓库变成运行时依赖。2026-07-31 用户依据教授要求另行作出明确 superseding decision：PET/CT 当前 canonical 必须从三类 add-only 迁移为六类双向 ADD/REMOVE；本文件据此评估迁移是否真实闭合，但不把迁移误写成已经运行的实验结果。

本轮四个工作包是：

1. 对既有 A6000 资源进行一次新的、只读的 live 状态核验，并据此安排后续任务；
2. 将 USyd BDAV Z390-3090 登记为第二服务器，验证连接、资源与最小权限边界；
3. 将 Honor Degree canonical、配置和下游代码迁移到教授要求的六类双向 taxonomy，并重新回答 PET/CT 3.1–3.6；
4. 审阅九个外部科研 skills 仓库，选择性形成 capability overlays，由 `research-orchestrator` 单入口自动建议，同时保留显式手动 mode 覆盖权。

以下内容明确不在本文件范围内：

- 不运行 PET/CT 训练、推理或 GPU 实验；
- 不运行第三方 installer、hook、MCP server、云服务、下载器或外部 AI 图像生成；
- 不读取、复述或持久化任何服务器密码、密钥或 `.env` 内容；
- 不改变 `M0→M1` 单轮验证边界，但用正/负 corrective scribble 与 ADD/REMOVE 六类合同覆盖旧三类 add-only 默认路径；
- 不调用 `/promote-to-vault`，不产生 result、metric 或 thesis-citable claim。

六类 `operation × target × scope` 双向 taxonomy 现为当前 canonical：`operation={ADD,REMOVE}`、`target={SAME,NEW}`、`scope={LOCAL,COMPLETE}`。合法组合为 `ADD/REMOVE × SAME × LOCAL/COMPLETE` 加 `ADD/REMOVE × NEW × COMPLETE`；两个 `NEW_LOCAL` 组合非法。旧三类 ADD-only joint 只可作为 historical provenance。完成条件包括 decision、schema、dataset、loss、metrics、power/fairness plan、代码与测试的一致迁移；在真实 OOF error atlas 出来前仍不得声称六类样本充分或 taxonomy exhaustive。

## 2. Completion matrix

| 工作包 | 完成条件 | 必须存在的证据 | 当前快照 | 未闭合时的准确表述 |
|---|---|---|---|---|
| G1：A6000 live status | 在本 goal 上下文中取得新的只读 lease；核验 GPU、tmux/process、campaign receipts、失败标记和下一可运行 gate；不产生远端写操作 | 带时间戳的 redacted query receipt、命令清单、exit code、状态摘要 | `A6000_HEALTHY / OOF_READY_COMMITTED_PASS / DOWNSTREAM_FAILED_BEFORE_M0_EVALUATION`；证据见 Honor Degree `records/2026-07-31-independent-goal-server-audit.md` | fold 4 已完成；`OOF_READY` 已 COMMITTED/PASS，覆盖 597 cases、378 patients，并闭合 597 predictions 与 597 probabilities，ready SHA-256=`4009a8b0072eac55a52ba7441dbcb57175e3e368437e7a3a1f42830a471ba710`。随后外层 root 在 M0 evaluation 前失败，因为服务器旧 `build_petct_source_case_manifest.py` 不接受 `--mode identity`；M0 evaluation 未运行。不得重跑 OOF；只能先同步 exact current bundle、重做 F0，再从 M0 evaluation 继续。该阻断是 downstream stale source/launcher defect，不是 A6000 故障 |
| G2：BDAV 资源登记 | resource、env-ref、policy、project alias 均可解析；可信 host key 已独立确认；登录、GPU/driver/CUDA、磁盘、`/mnt/HDD4`、Conda 与调度方式均核验；执行前另过写入/运行 gate | secret-free registry/policy diff、resolver tests、known-host proof、read-only inventory receipt、受控 workdir write/delete smoke receipt | `BDAV_3090_READ_ONLY_VERIFIED / EXECUTION_BLOCKED_DISK_ENV_SCHEDULER`；`secondary_gpu→server.usyd.bdav_z390_3090`；fresh inventory `2026-07-31T10:40:40Z` | strict auth、pinned host key 与 direct-IP route 已通过；Ubuntu 20.04.6、driver 535.230.02/CUDA 12.2、idle RTX 3090 24 GiB 已核验。GPU1 GTX 1080 Ti 被他人占用；`/mnt/HDD4` 仅约 66 GiB free 且 `df=100%`；项目 Conda 不在 PATH；Slurm 缺 site config。`submit_job` 仍 default-denied，未做写入 smoke、未提交任务；须先释放磁盘、准备项目环境并冻结 tmux/nohup 或修复 scheduler，再单独授权 execution preflight。两资源均可发现，但当前可执行底层资源只有 A6000 |
| G3：PET/CT 3.1–3.6 | 每个回答均能回指当前 Honor Degree 专题文件；paper claim、源码行为、项目 adapter 与实验状态分栏；不存在用历史 FDG/click 方案覆盖当前 PSMA/scribble 方案 | `docs/00,02,04,05,06,07,10,11` 的可定位条目、链接检查、术语/状态一致性检查 | `STATIC_REVIEW_COMPLETE / NO_EXECUTION` | 网络、数据与脚本设计已经审阅；模型有效性、episode 分母和结果仍未证明 |
| G4：外部 skills 审计 | 九个仓库均固定来源版本并完成 license、危险入口、能力重叠和可复用边界审阅；只选择具体 capability，不整仓启用 | source manifest、license decision、`ADOPT/ADAPTER/REIMPLEMENT/REJECT` 记录 | `SOURCE_AUDIT_COMPLETE` | 已下载并读过不等于已安装、可信或可运行 |
| G5：单入口 overlay 集成 | 自然语言可自动建议 mode 和 overlay；显式 mode 必须优先；operated/spec-only 状态不被改写；默认无网络、无外部执行 | schema/router tests、中文/英文 routing fixtures、manual override tests、truth-boundary tests | `IMPLEMENTED / 116 FOCUSED TESTS PASS` | 自动选择仍是建议；真正的一键 operated 能力继续由既有 operate registry 决定，spec-only mode 不会被伪装成可运行 |
| G6：科研质量评估 | 五个 smoke 请求全部完成路由与产物检查；随后用预注册的扩大样本做盲评，达到质量阈值且无 fatal defect | 匿名 A/B 产物、judge sheets、配对统计、缺陷与修复记录 | `STAGE-A_COMPLETE_NOT_PASS / STAGE-B_HARNESS_IMPLEMENTED / 20-REQUEST HOLDOUT_FROZEN / SIGNED_RECEIPT_INGESTION_IMPLEMENTED / HOST_USAGE_CALLBACK_BLOCKED / AUTHORS_AND_JUDGES_NOT_RUN`；Stage-A [对账证据](research-capability-overlay-smoke-blind-evaluation-2026-07-31.md) | Stage-B 已能生成 nonce-bound challenge，并对 provider-host Ed25519 receipt 做 dispatch/artifact hash、逐字段 source、token total 与 replay 验证；但当前 collaboration runtime 仍不导出真实 provider metadata/usage，也没有外部 host signer callback。旧 prepared plan 早于 challenge 合同，不能用于真实 author 调用；真实 authors/judges 尚未运行，故不得 seal 或声称显著提升、因果收益、`PAIRED_EVALUATION_PASS` |

## 3. 外部能力取舍矩阵

决策含义：

- `ADOPT_AS_IS`：只接入审计通过的最小 callable；仍需固定 HEAD、隔离依赖和本地测试，不代表整仓安装；
- `ADAPTER`：保留科研工作流思想，以本系统 task frame、source refs、run store 和输出接口包裹；
- `REIMPLEMENT`：只保留抽象机制，由本系统独立实现；不复制受限或无许可源码/提示正文；
- `REJECT`：不进入运行路径，必要时只保留来源和拒绝理由。

| 来源或能力 | 决策 | 接入边界 | 进入运行前的证据 |
|---|---|---|---|
| `scientific-agent-skills`：pydicom inventory / de-identification audit | `ADOPT_AS_IS`（选择性） | 只作医学数据清单和去标识审计；不得改写原始 DICOM，不接触未授权目录 | 固定 HEAD、MIT notice、synthetic fixture、read-only/deny-write test、PHI redaction test |
| `scientific-agent-skills`：`figure_export` | `ADOPT_AS_IS`（选择性） | 只负责确定性导出，不负责选择统计图或生成数据 | 固定 HEAD、isolated import、像素/DPI/字体/格式 golden tests |
| `AI-research-SKILLs` / Orchestra：双循环与 ideation | `ADAPTER` | 用“发散假设 → 机制化 → 对抗筛选 → 可证伪预测”增强现有 `new_direction/deep_ideation`；不替换现有 evidence/novelty truth gate | 来源版本、模式映射、重复想法与 prior-art collision fixtures |
| 核心仓库共同模式：hypothesis/prediction matrix | `ADAPTER` | 强制把跨学科灵感压成 motivation、mechanism、observable prediction、falsifier；不把类比当证据 | 三个跨域 fixture；每个 hypothesis 必须有可失败条件和测量变量 |
| `Academic Research Skills`：statistical power / unit-of-analysis | `ADAPTER` | 先锁实验单位、聚类层级、split 与 primary contrast，再给 power/MDE 建议；CC BY-NC 内容不整段复制 | license attribution、patient/sample leakage tests、unknown-effect honest fallback |
| 核心仓库共同模式：results → claim bundle | `ADAPTER` | 把结果、estimator、uncertainty、assumption、claim strength、counter-evidence 和可引用边界绑定为一个 bundle | no-result、null-result、conflicting-result、missing-denominator fixtures |
| `Academic Research Skills`：peer-review confidentiality / data fence | `ADAPTER` | blind reviewer 只收 frozen input；禁止读取作者隐藏工作区、secret、未授权数据和另一个 reviewer 的意见 | blind-input isolation、path allowlist、secret-token canary tests |
| CC BY-NC 来源中的 cross-model blind handoff | `REIMPLEMENT` | 独立设计 provider-neutral envelope；只传 source refs、frozen artifacts 与角色必要字段 | clean-room design note、schema tests、author/reviewer cross-contamination tests |
| `claude-scholar` 等：claim calibration、persuasion invariance、submission freshness | `REIMPLEMENT` | 形成 claim 强度检查和时效检查；不引入第二知识库、Zotero/Obsidian 强绑定或自动 hook | 同一结果不同文风应得相同 truth verdict；stale-date 与 superseded-source fixtures |
| 无许可证的 `agent-research-skills`：math ↔ code ↔ number provenance | `REIMPLEMENT` | 只采用“三向闭环”思想，独立实现 equation、implementation locator、reported number 的关联；不复制源码或 skill 文本 | no-license boundary note、equation mismatch、code-path mismatch、table-number mismatch fixtures |
| `scipilot-figure-skill` | `ADAPTER` | 只借鉴 export/layout/font-DPI QA；统计图型选择由设计与统计上下文重新实现 | MIT notice、固定 HEAD、不可凭数据形状自动作因果解释的测试 |
| `drawio-skills` | `ADAPTER` | 唯一图解 renderer 候选；采用 offline YAML-first 输入和 academic overlay；禁用 MCP、`npx @latest` 与 live backend | 固定 HEAD、MIT notices、allowlisted args/workdir、offline test、output receipt |
| `nature-skills` | `ADAPTER`（严格选片） | 只吸收 figure rubric、统计 checklist、methods 的 motivation–mechanism–evidence 三元组和 reviewer axes | Apache-2.0 notice、四类 overlay fixtures、不得复制已发表视觉资产 |
| `drawio-scientific-illustrator` | `REJECT`（首轮） | 与选定 drawio 路径重复，且含 legacy CDP/`Runtime.evaluate`/本地端口与安装面；不进入 runtime | 仅保留拒绝记录；若未来重审必须重新做 threat/dependency audit |
| 全仓 installer/hooks、自动依赖、云执行、强制外部 AI 生成图、第二知识库写入、secret-file 读取 | `REJECT` | 与单入口、两库边界、离线默认和 secret-safe 原则冲突 | 不适用；任何重新准入都需独立 decision |
| “检索不到即新颖”、通用 experiment generator 直接产结论 | `REJECT` | absence 只能是 `UNVERIFIED`；实验设计必须绑定领域、数据、单位、对照和 falsifier | novelty absence fixture、无数据时拒绝结果性结论 |

最小科研顺序固定为：

```text
hypothesis / prediction
→ power + unit of analysis
→ result–claim binding
→ blind handoff
→ submission freshness
```

这一顺序是质量骨架，不要求把每个 worker 的措辞或 Markdown 标题管死。自动路由只是建议器；用户显式指定 mode 时必须覆盖自动建议，但不能覆盖 operated/spec-only 的真实性。

## 4. 五个合成项目请求

这五个请求用于验证路由、角色分工、跨域深度和 truth boundary。它们是 smoke/evaluation fixtures，不创建真实项目注册项，不写 vault。

| ID | 合成请求 | 期望 route / overlays | 关键陷阱 | 合格产物 |
|---|---|---|---|---|
| S1 医学影像设计 | “为 patient-disjoint PSMA PET/CT 六类双向 residual correction 设计首篇论文实验，并指出什么结果会推翻 intent 假设。” | `design_experiment`（必须标 spec-only）＋ hypothesis/prediction ＋ unit-of-analysis/power | 不得退回旧三类 add-only；不得把五折称为五个 OOF baseline 或 ensemble；不得把设计称为结果 | 明确 RQ、patient-level split、正/负 cue、same-weight contrast、falsifier、双向 safety metrics、power gap 与 no-result 状态 |
| S2 跨学科新方向 | “把主动感知、教育学最小提示和医学交互分割结合，提出三个能被实验推翻的新方向。” | `new_direction` / `deep_ideation` ＋ Orchestra 双循环 ＋ hypothesis matrix | 概念烟花、无测量变量、把类比当支持证据 | 每个方向都有来源边界、机制、observable、最小实验、kill criterion 和 prior-art collision 状态 |
| S3 冲突证据审阅 | “审阅两个结论相反的 AI-for-science 方法，判断差异来自数据、单位、估计量还是过度主张。” | `evidence_deep` / `deep_research` ＋ result–claim bundle ＋ claim calibration | 只按摘要投票、忽略 contradiction、把没有发现反例写成已证实 | source table、exact claim refs、contradiction map、不可判定项和校准后的结论 |
| S4 结果可视化 | “根据冻结的真实结果表生成主结果图、方法流程图和 captions；若数据缺失则停止。” | publication output router ＋ `figure_export` ＋ SciPilot QA ＋ offline drawio adapter ＋ Nature figure rubric | 发明数字、外部 AI/云路由、用图形选择暗示未检验因果、复制论文资产 | data hash、figure spec、offline render receipt、caption–number audit；缺数据时为结构化拒绝 |
| S5 投稿前盲审 | “对一篇包含方法、结果和补充材料的稿件做互盲复核，检查 claim、统计、图表、引用和截至提交日的新证据。” | `manuscript_review` ＋ clean-room blind handoff ＋ reviewer axes ＋ submission freshness | reviewer 互相污染、读取作者私有目录、风格改变 truth verdict、过期检索 | 三份独立 review、meta-review、claim severity map、freshness receipt、可执行 revision list |

## 5. 盲评 rubric 与通过规则

### 5.1 两阶段评价

**阶段 A：5-request smoke。** 对 S1–S5 分别运行：

- A 组：同一版本的 `research-orchestrator`，关闭新 overlays；
- B 组：同一模型策略、同一输入、同一 source packet，开启新 overlays。

随机化 A/B 显示顺序并去除系统标识。三名互盲 judge 分别承担：领域/机制、方法/统计、证据/诚信；judge 不读取彼此评分。阶段 A 只证明路由和明显质量回归，不用于“统计显著提升”主张。

**阶段 B：扩大盲评。** 若要声称质量提升，至少使用 20 个预注册、覆盖不同学科和任务类型的请求，保持 paired inputs/model/budget，预先冻结 primary score、最小有意义差值和配对统计方法；报告配对 bootstrap 或 permutation interval、judge agreement、全部失败例。不得看完结果后更换 rubric 或只挑成功案例。

### 5.2 评分锚点

每个维度按 0–4 计分：`0=缺失/有害`，`1=表面提及`，`2=部分可用但有关键缺口`，`3=完整可执行`，`4=完整、可证伪且主动发现重要缺陷`。

| 维度 | 评分问题 |
|---|---|
| Q1 任务与 scope fidelity | 是否回答真实问题、尊重 frozen/current/future 边界，并避免无关扩张？ |
| Q2 机制与可证伪性 | 是否把灵感转成 mechanism、observable prediction 与 kill criterion？ |
| Q3 证据深度 | 是否区分 paper claim、源码行为、项目 adapter、矛盾证据和未知项？ |
| Q4 实验有效性 | 是否锁定实验单位、split、leakage、对照、estimator、power/MDE 与 multiplicity？ |
| Q5 跨学科转译 | 是否把外域原则落到可实现机制，而非只换术语？ |
| Q6 result–claim calibration | claim 是否不强于结果、uncertainty、assumption 与 evidence freshness？ |
| Q7 可执行与可追溯 | 是否给出最小动作、输入、输出、source refs、failure receipt 和复现边界？ |
| Q8 最终表达 | 最终作者是否把复杂材料组织成可读的决策文档/图，而未牺牲真实性？ |

### 5.3 Fatal defects 与门槛

任一产物出现下列问题即 `FAIL`，总分不能抵消：

- 伪造论文、引用、数字、实验、server 状态或 receipt；
- 从未执行的脚本推断有效性，或把 process/checkpoint/pseudo-metric 当科学结果；
- 泄露 secret/PHI，越权读取 blind/private 输入，或触发未授权服务器写入；
- 执行第三方 installer/hook/MCP/cloud path，或把 staging repo 当 runtime dependency；
- 未经 director decision 静默改变 PET/CT canonical、test 后改 primary contrast/margin，或以“未搜到”证明 novelty；本次六类迁移有 2026-07-31 明确 superseding decision，不属于静默漂移；
- A/B 两组输入、模型策略、source packet 或预算不一致且仍声称质量差异来自 overlay。

阶段 A 通过：无 fatal defect；每个请求 Q1/Q3/Q4/Q6 均不低于 3；B 组至少在 4/5 个请求上不劣于 A，且至少在 3/5 个请求上总分提高 2 分以上。  
阶段 B 才可支持“质量提升”：无 fatal defect；B 的预注册 primary paired score 达到预设最小差值且区间不跨 0；Q1/Q3/Q4/Q6 不出现系统性下降；同时公开失败例和 judge agreement。未完成阶段 B 时只能写 `SMOKE_PASS` 或 `QUALITATIVE_IMPROVEMENT_OBSERVED`，不能写“显著提升”。

## 6. 两条服务器分支

| 分支 | 当前可确认事实 | 阻断项 | 下一步最小动作 | 未通过前禁止声称 |
|---|---|---|---|---|
| A6000：`server.honor.gpu` / `primary_gpu` | 最新 live evidence 为 `A6000_HEALTHY / OOF_READY_COMMITTED_PASS`：fold 4 已完成，`OOF_READY` 覆盖 597 cases、378 patients、597 predictions 与 597 probabilities；ready SHA-256=`4009a8b0072eac55a52ba7441dbcb57175e3e368437e7a3a1f42830a471ba710` | OOF 发布后，外层 root 在 M0 evaluation 前失败：服务器上的旧 `build_petct_source_case_manifest.py` 不接受 launcher 传入的 `--mode identity`。这是 downstream stale source/launcher defect，不是 GPU、fold 或 A6000 故障；M0 evaluation 尚未运行 | 禁止重跑 OOF。先把 exact current bundle 同步到服务器并重做 F0，确认 source/launcher 合同一致后，只从 M0 evaluation 继续既定 downstream 链 | `OOF_READY` 是已闭合的执行产物，但不是科学结果；当前不能声称 M0 metrics、residual、scribble、P2T、editor、external comparison 或 statistics 已完成 |
| BDAV：`server.usyd.bdav_z390_3090` / `secondary_gpu` | secret-ref registry 和 policy 已登记；先前首次登录及强制密码轮换成功，但新凭据未被安全保留；验证证据状态为 `credential_recovery_required` | 当前没有可安全恢复的认证凭据；host fingerprint 尚未通过 University 管理员或已信任用户独立确认；GPU/driver/CUDA、磁盘、`/mnt/HDD4`、Conda、scheduler 均未核验 | 由 University 管理员向 director 重置/重发凭据，并通过独立可信渠道确认 host fingerprint；之后才能重新认证并做 redacted inventory 与隔离 workdir smoke | “当前可重复登录”“3090 已确认”“CUDA/Conda 可用”“适合训练”“已成为可调度执行资源” |

两台服务器的 `submit_job` 都必须独立经过 project binding、明确执行授权和当次 gate。注册表中声明一种 capability 只描述资源可能支持什么；policy 未允许、lease 未签发、live preflight 未通过时，系统不能使用它。

## 7. PET/CT 本轮静态审阅的不可宣称事项

当前 Honor Degree 文档支持以下状态：`OOF_READY_COMMITTED_PASS / REMOTE_STALE_SOURCE_LAUNCHER_BLOCKED / M0_EVALUATION_NOT_RUN / NO_SCIENTIFIC_RESULTS`。OOF 不得重跑；exact current bundle 同步与 F0 rebuild 通过后才可从 M0 evaluation 继续。因此：

- 五折训练是产生一套 OOF `M0` 的机制：五个 fold checkpoints、每例一个 held-out prediction；不是五个 baseline，也不是五模型 ensemble；
- natural primary 每个 eligible episode 是一条 foreground scribble curve；三策略 robustness 是三个 matched attempts，每次仍为一条，不是一次累计三条；
- 第一篇仍是一次 `M0→M1` 的 single-round correction，但现在同时覆盖正/负 cue 与 ADD/REMOVE；它不是 AutoPET V 完整多轮 loop；
- GT 是二值 semantic tumour mask，没有数据集原生 lesion instance IDs；lesion identity 由连通域派生；
- P2T/editor 网络和脚本存在但均未产生科学结果；joint-decoded target/scope 指标不能冒充 auxiliary heads 的独立准确率；
- `scribble_plus_intent` 与 `oracle_slots` 当前训练可见合同相同，两个命名角色不能当两个独立科学自变量；
- editor 当前等权 BCE + soft Dice + unauthorized-addition loss、downstream augmentation=`none`、seeded 但非 bitwise deterministic、无 a priori power/MDE 证明，均必须如实保留；
- 外部 comparator 的 paper/source 审阅、旧环境 smoke、checkpoint 存在或本地 clone 均不等于 current-config admission、fair comparison 或有效性结果。

## 7.1 Stage-B evaluation-only harness

Stage-A 暴露的六类确定性缺口已被收敛为一个独立、默认无网络且不调用模型的 Stage-B harness；它不修改生产 `research-orchestrator` 入口，也不执行任何第三方仓库。冻结输入与合同是：

- 20 个 holdout requests：`_design/review/research-capability-overlay-stage-b-requests-v1.json`；覆盖 18 个 domain、13 个 task type，且逐题保存合成 frozen source packet；
- condition schema：`schemas/overlay_ab_condition_manifest.schema.json`；
- 全局 author runtime policy schema：`schemas/overlay_ab_author_runtime_policy.schema.json`；
- provider-call receipt schema：`schemas/provider_call_receipt.schema.json`；
- 统一三评审 schema：`schemas/overlay_ab_judge_sheet.schema.json`；
- 只验不签的 receipt importer：`tools/provider_call_receipt_import.py`；
- prepare / seal / reconcile：`tools/research_capability_ab_eval.py`。

从本仓库父目录运行：

`<private-stage-b-author-runtime-policy.json>` 必须在 fresh prepare 前由 dispatcher 明确填写，不能由 seal 根据结果反推。结构如下（尖括号值必须替换成这次真实请求配置）：

```json
{
  "schema_version": "research-capability-overlay-author-runtime-policy/v1",
  "runtime_policy_id": "<immutable-policy-id>",
  "model_policy": "max_quality",
  "model": "<exact-requested-provider-model>",
  "service_tier": "<exact-requested-service-tier>",
  "reasoning_effort": "<exact-requested-reasoning-effort>",
  "agent_type": "<single-author-agent-type>",
  "context_budget_tokens": 1,
  "max_output_tokens": 1
}
```

其中两个 token 数的 `1` 只展示 schema 下界，不是推荐实验预算；真实值必须在 40 次调用前一次性冻结。

```powershell
python -m research_agent_teams.tools.research_capability_ab_eval prepare `
  --request-manifest research_agent_teams/_design/review/research-capability-overlay-stage-b-requests-v1.json `
  --overlay-catalog research_agent_teams/orchestrator/research_capability_overlays.json `
  --author-runtime-policy <private-stage-b-author-runtime-policy.json> `
  --out-dir <private-stage-b-root>/prepared

python -m research_agent_teams.tools.research_capability_ab_eval seal `
  --dispatch-plan <private-stage-b-root>/prepared/dispatch-plan.json `
  --artifact-root <private-stage-b-root>/author-artifacts `
  --out-dir <private-stage-b-root>/sealed

python -m research_agent_teams.tools.research_capability_ab_eval reconcile `
  --condition-manifest <private-stage-b-root>/sealed/condition-manifest.json `
  --judge <judge-domain.json> --judge <judge-methods.json> --judge <judge-evidence.json> `
  --out <private-stage-b-root>/stage-b-report.json
```

`prepare` 只产生私有 dispatch plan，逐题确定 X/Y treatment，固定 request、source packet、overlay catalog 与 prompt hashes；同时要求一个 schema-valid、全 40 次 author 共用的 runtime policy，明确 `model_policy / model / service_tier / reasoning_effort / agent_type / context_budget_tokens / max_output_tokens / runtime_policy_id`。该 policy 的完整正文进入每个 candidate，因此也进入每个唯一 challenge 的 dispatch SHA（另有 nonce、invocation id、预期 artifact path）；challenge 不构成执行声明。两个 authors 必须按 plan 的相对路径交付 Markdown，以及由模型进程之外的 host adapter 生成并 Ed25519 签名的 `provider-call-receipt/v1`。receipt 中 `requested` 必须逐份严格等于冻结 policy；`observed.resolved_model / service_tier / reasoning_effort / input_tokens / output_tokens / total_tokens` 必须逐字段标为 `provider_response`，`elapsed_ms` 必须标为 `host_monotonic`。`seal` 不只检查每对 X/Y，还要求 40 份 receipts 的 requested policy 及 provider-observed model/tier/effort 全局一致；实际 token/time 可以不同，但只能消费 importer 验证后返回的 `PROVIDER_ATTESTED` normalized usage。环境变量、worker self-report、人工填写、字数/token 估算和 CLI wall-clock 都会 fail closed。三个 judge 必须互盲且分别占用 `domain_mechanism`、`methods_statistics`、`evidence_integrity` 角色；`reconcile` 会拒绝缺案、重复案、packet hash 不同、winner 与 Q1–Q8 总分矛盾、fatal defect 或核心维度退化。

当前已运行合成 pytest 夹具验证 harness；历史上也执行过一次不调用模型的旧 `prepare`，但该产物缺少 challenge 与全局 runtime policy，已被新合同明确视为 legacy，不是可继续执行的 fresh prepare。仍不存在真实 author output、runtime receipt 或 judge sheet。聚焦复跑命令及结果：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q -p no:cacheprovider `
  research_agent_teams/tests/test_provider_call_receipt_import.py `
  research_agent_teams/tests/test_research_capability_ab_eval.py `
  research_agent_teams/tests/test_research_capability_router.py `
  research_agent_teams/tests/test_research_capability_overlay_evaluation.py `
  research_agent_teams/tests/test_router.py `
  research_agent_teams/tests/test_panel_scheduler.py `
  research_agent_teams/tests/test_operate_spine.py `
  research_agent_teams/tests/test_operate_wiring.py
```

2026-07-31 当前合同的 signed-receipt importer + Stage-B 最小复跑为 `34 passed in 28.03s`；把上方列出的 router/schema/scheduler/wiring/Stage-B tests 合并后的扩展 focused suite 为 `134 passed in 87.77s`。这些都只证明合同与 fail-closed 行为，不是 provider evidence 或 Stage-B 科研评价结果。测试私钥只存在于 pytest fixture，不能进入真实运行。

### 7.1.1 当前真实运行时阻断

当前仓库已经具有“验证并导入外部 signed receipt”的能力，但仍没有 author-call 级别的 host/provider usage exporter：

- `orchestrator/model_policy.py::codex_runtime_fields` 只从部署环境绑定可选 `runtime_model / reasoning_effort / service_tier`；它记录请求/配置，不证明 provider 实际执行值；
- `orchestrator/engine.py::_drive` 与 `operate/spine.py::commit_stage` 写入的是 logical model label 和上述可选环境绑定，没有写 `input_tokens / output_tokens / elapsed_ms`；
- `schemas/agent_run_log.schema.json` 已把部署绑定与 provider observation 分开，并把当前 reasoning call 标为 `unobserved`；历史 `cost_tokens` 仍是不可作为 provider attestation 的可空聚合字段；
- 当前 subagent dispatch 接口不返回可持久化的逐调用 token usage receipt。

安全执行边界仍停在 author 之前。`research_agent_teams/runs/research-capability-stage-b-20260731/prepared/` 的旧 plan（20 pairs，SHA-256=`B1F1339C6F77BDE6C0CAA2F6BD89C53D041D6E3C751186D03A5528A0FE84E432`）是在 challenge/attestation 与全局 runtime-policy 合同加入前生成的历史 prepare；seal 会明确按 legacy plan 拒绝，不得原地改写，也不能承载新的 signed receipts。只有 host callback 真正可用且具体 author runtime policy 已由 dispatcher 明确后，才能在新 immutable root 重新执行 deterministic `prepare`；冻结 request manifest、blinding salt 与 mapping 算法不变，但 policy hash 会参与 evaluation id，完整 policy 会参与 40 个随机 nonce challenges 的 dispatch hash。在此之前不应生成无法密封的 authors，更不能手工填写、伪签或估算 usage。本轮准确状态为 `GLOBAL_AUTHOR_RUNTIME_POLICY_CONTRACT_IMPLEMENTED / SIGNED_RECEIPT_INGESTION_IMPLEMENTED / HOST_USAGE_CALLBACK_BLOCKED / AUTHORS_AND_JUDGES_NOT_RUN`。

### 7.1.2 receipt 解锁后的端到端执行合同

独立审计结论是：Stage-B 可以由真实 reasoning workers 执行，不需要合成答案或伪造 judge sheet；但它当前不是一个 production `operate` mode，也不能把 20 个请求各自交给完整 mode pipeline。冻结 holdout 中有 12 个请求对应 `operated` mode、8 个对应 `spec_only` mode；若直接运行各 mode，既会令 8 个请求无法同等执行，也会使各题 worker 数、检索、上下文和成本不同，形成新的 A/B 混杂。`expected_mode` 在本评估中是路由与 overlay 选择标签，author 的实验单位仍是“一次隔离的单回答调用”。

真实输入输出与顺序必须保持如下：

| 顺序 | 执行者与数量 | 唯一允许输入 | 必须输出 | 进入下一步的条件 |
|---|---:|---|---|---|
| 0. runtime preflight | deterministic，0 个 model call | host/provider callback 能力与独立 trust public key | host adapter 能取得真实 response metadata、monotonic elapsed 并在 LLM runtime 外签名 | 私钥不能进入 reasoning worker；环境变量、人工填写、估算或文本长度换算均不合格 |
| 1. `prepare`（新 root 待执行） | harness，0 个 model call | 冻结 request manifest、live mode registry、pinned overlay catalog、一个明确的全局 author runtime policy | 私有 `dispatch-plan.json`、SHA sidecar、40 个 call challenges | 20 个 request、Stage-A holdout、mode 路由、source packet、X/Y mapping、prompt hashes、policy/evaluation/nonce/invocation/dispatch hash 全部闭合；旧 pre-challenge/pre-policy plan 不可复用或改写 |
| 2. paired authors | 40 个相互隔离的 model calls（20×X/Y） | 模型仅见 `candidate.prompt`；host 另取对应 challenge；不得给 sibling output、condition mapping、judge rubric 或其他私有文件 | `authors/HB-NN.X.md` / `authors/HB-NN.Y.md` 加各自对应的 signed runtime receipt | 全 40 次调用共用同一 requested policy/model/tier/effort/agent type/budgets，并保持 provider-observed resolved model/tier/effort 全局一致；实际 token/time 可以不同但必须经 importer 成为 `PROVIDER_ATTESTED`；artifact path/SHA 闭合 |
| 3. `seal` | harness，0 个 model call | immutable dispatch plan、40 份 Markdown、40 份 signed provider receipts、trust public key | `condition-manifest.json`、仅含 X/Y 文本的 `blind-packet.md` | schema、Ed25519、challenge nonce、dispatch/artifact hash、field source、token total、cross-call replay、冻结 policy 匹配、全 40 次配置/observed parity 任一失败，整批停止且不出 judge packet |
| 4. blind judges | 3 个相互隔离的 model calls，每名 judge 一次覆盖全部 20 对 | 只给相同 `blind-packet.md`、第 5.2 节冻结 rubric、自己的 role 和 `overlay_ab_judge_sheet.schema.json`；不得给 dispatch/condition mapping、runtime receipts 或 sibling sheet | 各一份严格 schema-valid JSON：`domain_mechanism`、`methods_statistics`、`evidence_integrity` | 三个独立 `judge_id`、相同 packet SHA、20 个且仅 20 个 cases、X/Y 均有 Q1–Q8/理由/fatal defects、blindness attestations 全为真 |
| 5. `reconcile` | harness，0 个 model call | sealed condition manifest、三份 judge sheets | `stage-b-report.json` | validator 先核验 schema、角色、去重、完整 case set、packet hash 和 winner/总分一致性，再揭盲和计算统计量 |

因此最低 reasoning-worker 数是 **43 次真实调用**：40 次 author + 3 次 judge；`prepare / seal / reconcile` 都是确定性本地步骤，不占 model call。不要把三个 judge 拆成 60 个逐案调用再手工合并，因为当前合同要求每名 judge 对同一个完整 blind packet 产出一份 20-case sheet，且没有发布版的跨调用 merge receipt。

并发不是冻结统计变量，harness 也没有写死全局并发上限。为降低隐藏的部署版本/负载漂移，推荐同一 request 的 X/Y 在同一 wave 启动，并为 20 对使用同一全局 author policy。若可用 reasoning worker 席位为 `C`，推荐并行 pair 数为 `floor(C/2)`，author waves 为 `ceil(20 / floor(C/2))`；三名 judges 在 `C>=3` 时可在一个后续 wave 并行。以当前“主线程 + 3 个 worker 席位”为例，保持 pair 同 wave 时是 20 个 author waves，再加 1 个 judge wave；理论上把 40 次调用塞进 14 个三席 wave 更快，但会让部分 X/Y 跨 wave，属于未被 harness 检测的时间漂移风险。

成本不能在 model、价格与真实 usage 出现前写成一个金额。可审计的 author 成本单位是 40 份 receipt 的 `sum(input_tokens)`、`sum(output_tokens)` 和 `sum(elapsed_ms)`；配置上界由每次调用的 context/output budget 组成。当前 judge schema 不带 provider usage receipt，因此 Stage-B gate 能闭合 author parity，却不能仅凭发布报告闭合三名 judges 的总 token/金额；若运行平台提供 receipt，应在私有 dispatcher ledger 中额外保存并与 judge artifact hash 绑定，但不得把这些 receipts 暴露给 judges 或事后改写冻结 gate。

### 7.1.3 现有 agents 的可复用边界

可以复用现有 research-agent catalog 的判断能力，但不能把不兼容的生产 artifact 冒充 Stage-B 输出：

- author 条件应使用同一个隔离的通用 reasoning worker（Stage-A 的 `agent_type=default` 做法可沿用，并在 40 次调用前冻结一个全局 policy）；不能让 `research-orchestrator` 主线程直接作答，因为其 agent contract 明确禁止自己做研究，也不能让每题完整运行 `expected_mode`；
- `domain_mechanism` 可复用 `domain-reviewer` 与 `mathematical-formalizer` 的检查视角，`methods_statistics` 可复用 `methodology-reviewer` 与 `statistics-critic`，`evidence_integrity` 可复用 `evidence-verifier` 与 `citation-integrity-auditor`；
- 上述现有 agents 的原生输出分别是 `panel_review`、`power_audit_report`、`evidence_verdict` 等，不是 `research-capability-overlay-judge-sheet/v1`。所以实际调用必须由顶层 dispatcher 建立三个全新、互盲、无历史上下文的 evaluator instances，并在 prompt 中固定对应 lens 与 judge schema；只有 validator 接受的真实 JSON 才算 judge evidence。当前不存在可诚实称为“一键 Stage-B”的 operated recipe 或专用 Stage-B agent；这是 dispatch wiring 状态，不是要求制造假数据。

执行状态应据此区分为：

```text
HARNESS_IMPLEMENTED
+ REQUESTS_AND_RUBRIC_FROZEN
+ STAGE_B_PREPARED_NOT_RUN
+ REAL_AGENT_LENSES_REUSABLE
+ MANUAL_DISPATCH_PLAN_DEFINED
+ SIGNED_RECEIPT_INGESTION_IMPLEMENTED
+ GLOBAL_AUTHOR_RUNTIME_POLICY_CONTRACT_IMPLEMENTED
+ HOST_USAGE_CALLBACK_BLOCKED
+ NOT_ONE_BUTTON_OPERATED
+ AUTHORS_AND_JUDGES_NOT_RUN
```

一旦真实 host callback 可用，必须用同一冻结 request manifest/blinding salt 在新 immutable root 运行带 challenge 的 `prepare`，再执行 2→5；不得改 request、mapping 算法或统计门槛，也不得复用合成 pytest fixtures、Stage-A authors/judges、旧上下文、旧 pre-challenge plan 或手工 receipt。有效执行仍可能得到 `PAIRED_EVALUATION_FAIL`：任一 fatal defect、平均配对差 `<1.0`、paired bootstrap 下界 `<=0`、Q1/Q3/Q4/Q6 任一平均退化，或任一 request 的配对差为负/含 fatal defect，都会进入公开 failure list。相反，命令返回 `PASS` 只代表当前 harness step 完成；只有最终 `evaluation_state=PAIRED_EVALUATION_PASS` 才满足本轮冻结门槛，且主张范围仍只限这 20 个 holdout requests。

## 8. 本独立 goal 的最终 release decision

只有 G1–G6 各自产生对应证据，且第 5.3 节无 fatal defect，才可把本独立 goal 标为 `COMPLETE`。允许分项结束，但必须使用准确状态：

- 服务器：`REGISTERED`、`CONFIGURED_UNVERIFIED`、`READ_ONLY_QUERY_PASS`、`EXECUTION_ADMITTED` 分开；
- PET/CT：`STATIC_REVIEW_COMPLETE` 与 `EXPERIMENT_EXECUTED` 分开；
- 外部能力：`SOURCE_AUDITED`、`SELECTED`、`INTEGRATED`、`TESTED`、`QUALITY_EVALUATED` 分开；
- 科研效果：`SMOKE_PASS`、`QUALITATIVE_IMPROVEMENT_OBSERVED`、`STAGE-B_PREPARED_NOT_RUN` 与 `PAIRED_EVALUATION_PASS` 分开。

在此之前，最强的诚实结论只能是：

> 第二服务器和 capability overlay 已完成安全的设计/登记或源码审阅；PET/CT 六类迁移只有在文档、配置、脚本和测试同时闭合后才算完成。Stage-A 盲评观察到定性改善但未达到预注册通过线；Stage-B 已冻结 20-request holdout，并实现 challenge-bound、只验不签、Ed25519/replay-fail-closed 的 provider receipt ingestion 与严格 statistics harness。但现有 prepared plan 早于 challenge 合同，当前 collaboration runtime 又没有逐调用 provider usage callback/host signer，所以真实 authors、provider receipts 和独立 judges 均未运行。外部能力运行、模型结果与可推广的科研质量提升仍必须由各自 receipt 及完整 Stage-B 盲评证明。
