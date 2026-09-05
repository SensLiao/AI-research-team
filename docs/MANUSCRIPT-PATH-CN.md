# 论文撰写路径与格式权威（钉死版）

> 本文件是机器的**论文撰写路径合同**：从检索到发布的阶段序列一经锁定不得偏离，格式以参考范本为
> 唯一权威，每一个进入稿件的内容主张都必须可核验。它固化的是 `ref-free-seg-qa` 一次真实综述
> 写作与一次真实 Reject 返修中被证明有效的做法，不是设想。

## 0.1 2026-08-23 覆盖规则：AI-native artifact diet

本节优先级高于下方旧参考运行中的脚本名。参考运行证明了科学风险，但它的“每个问题新写一个脚本、每次交接新建一层 JSON、每个中间文件反复 hash”不是产品合同。

长期保留的工作面只有：

| 文件 | 用途 | 谁写 |
|---|---|---|
| `draft/REVIEW-METHOD.md` | 综述身份、问题、范围、检索、纳排、appraisal、综合方法 | architect |
| `draft/MANUSCRIPT-ONTOLOGY.md` | 概念/别名、claim、分母、value origin、章节与外审验收条件 | architect；之后 synthesis editor 单写 |
| `draft/SOURCES.tsv` | 每个 report/version 一行的身份与获取边界 | evidence steward |
| `draft/EVIDENCE.tsv` | 每个 claim/field/locus 一行，逐字证据与归因 | evidence steward |
| `draft/refs.bib` | 真正的 BibTeX source of truth | evidence/bibliography owner |
| `draft/sections/*.tex` | 分节正文 | 每文件一个 section owner |
| `draft/synthesis/sections/*.tex` | 串行综合后的交稿 | synthesis editor |
| `draft/REVIEW-CLOSURE.md` | 旧审稿意见逐条关闭表 | synthesis editor，reconstruction/review 复核 |

Agent 不为单次稿件写代码/脚本，不把正文或整份 BibTeX 塞进 JSON。机器 JSON 仅保留 FSM 必需的阶段、证据、构建和评审回执，由 reducer 从磁盘生成。Hash 只发生在三处：证据语料冻结、最终 source tree、最终 PDF/评审；其余交接依赖文件所有权和磁盘 diff。

这些工作文件是内部执行面，不得把 agent 名、run id、JSON/schema/hash、修复历史、写稿过程或“待人类审核”塞进科学正文。Methods 只报告与研究有效性相关且真实发生的检索、筛选、抽取、复核和分析；目标期刊要求的工具披露按真实事实单独处理，绝不为了外观编造人类步骤。

外部方法锚点（只吸收原则，不复制项目）：

- [SANRA](https://doi.org/10.1186/s41073-019-0064-8)：critical/narrative review 的目标、检索、引用、推理和 endpoint 六维检查。
- [PRISMA-S](https://doi.org/10.1186/s13643-020-01542-z) 与 [PRESS](https://www.cda-amc.ca/press-peer-review-electronic-search-strategies)：检索记录与检索式同行复核；只作为搜索透明度/质量锚点，不把 critical review 冒充 systematic review。
- [STORM](https://aclanthology.org/2024.naacl-long.347/)：先多视角提问和证据，再冻结 outline；本文落成 `REVIEW-METHOD.md` + ontology。
- [PaperQA](https://doi.org/10.48550/arXiv.2312.07559)：检索、证据聚合和回答分开；本文把证据检索面与 LaTeX 成稿面分开。
- [latexmk](https://ctan.org/pkg/latexmk)：让一个维护好的构建入口处理多 pass 依赖，不让每篇稿件重新发明 build script。

最小字段（够用即止，不再套一层 schema）：

```text
SOURCES.tsv
source_id  bibkey  stable_id  version_read  acquisition_channel  search_receipt  local_ref  access_scope  supplement_scope  figure_scope  code_scope  inclusion_status

EVIDENCE.tsv
source_id  claim_id  field  status  value  locus  exact_quote  value_origin  derivation  suspected_source_error
```

`MANUSCRIPT-ONTOLOGY.md` 只保留五张小表：canonical term↔aliases、claim↔canonical locus、denominator↔definition、value origin↔allowed attribution、section/file↔owner。Agent 用全文搜索/按行筛选取上下文，不把整个知识库复制进 prompt。若项目已有可检索知识库，TSV 行可只保存稳定引用和 locus；正文仍只消费已核验 source bytes。
>
> 与其他 docs/ 标准一致：**规则和指针，不缓存会腐烂的计数**。工具行为以工具源码为准，模式清单以
> `operate brief` 为准；本文只钉"顺序、问责、产物、检查"。

---

## 0. 两个锚点与本文地位

| 锚点 | 路径 | 是什么 |
|---|---|---|
| 参考实现（executed reference） | `runs/ref-free-seg-qa/deep_research-20260819T055022Z/` | 真实执行过的流水线：`tools/` 下的确定性脚本 + `corpus/` 下的全部证据 |
| 格式参考范本（format reference） | `runs/ref-free-seg-qa/Ref_Free_Seg_QA_Review_v1.0/` | 现行稿件即模板：`src/type.tex` + `build.sh` + `src/main.tex` |

- **路径是领域无关的**：阶段、问责、检查对任何论文线成立；`ref-free-seg-qa` 的工具是具体范例，
  新论文线克隆的是**形状**（每 run 一套 `tools/`、每稿一个带 `VERSION` 的稿件根），不是词表。
- **偏离的定义**：任何未经登记决定（`12-DECISION-REGISTER.md` 语义：先登记，再同步，再执行）就
  改变阶段顺序、跳过检查、手改生成物或绕开格式权威的行为。
- run-local 工具向机器 `tools/` 的搬迁由团队升级另行处理；工具搬家**不改变**本路径的阶段、产物
  与检查定义。

---

## 1. 阶段序列（锁定）

### 1.1 主路径 S1–S12

规则先行：

- **一个阶段一个问责席，一个唯一签收 artifact**（硬边界 5）。阶段产出多个文件时，表中"唯一
  artifact"是问责席签收提交的那一个，其余为其附件。
- 执行体是确定性脚本时，问责席负责**跑它并签收其输出**，不得代之以手工结果。
- agent 名以 `agents/` 名册为准；下表全部使用现有名册 agent。

| 阶段 | 干什么 | 输入 | 输出（唯一 artifact） | 负责 agent | 该停下检查什么 |
|---|---|---|---|---|---|
| **S1 检索** | 多通道元数据检索（`harvest.py search`、`harvest_v2.py openalex/groups`），含**对抗性查询组**（专搜最可能证伪头条主张的证据类）；JBI 第 3 步双向引文追踪（`chase_v2.py`）；`merge.py` 合并去重，`annotations.py` 回放持久标注 | 冻结种子（`seeds.py`／proposal refs）、查询清单、机器 pre-search bundle（`inbox/search-results.json`） | `corpus/retrieval/records-merged.json`（附 `merge-provenance.json` 每通道计数） | literature-search-strategist（策略）+ lit-scout（执行） | 每个**声明过的通道 yield > 0**，零产出=大声失败；429 按预算语义处理（配额型不得指数退避硬试）；每查询/每种子 checkpoint 已写进文件；三个对抗查询组在场；引文追踪已跑；失败通道点名记录，永不静默绕过 |
| **S2 筛选** | 词法、召回偏置的题录筛选（`screen.py`），分 T1 深读／T2 结构化略读／T3 排除三层；后续波次用**同一条规则**（`screen_v2.py` 直接 `import screen.screen()`） | `records-merged.json`（及各波次新记录） | `corpus/retrieval/screening-flow.json`（附各层清单 `screened-*.json`） | source-quality-ranker | v1/v2 波次是否同一 `screen()`（不同规则=计数不可合并）；每条 T3 带排除理由；落在资格边缘的记录已登记进边界记录（见 §3） |
| **S3 获取＋身份** | OA 解析与下载（`harvest.py oa/pdf`、`fetch_t1_v2.py`：逐记录 checkpoint、无熔断、不可得记录带理由码）；按标题经 resolver 重取（`reacquire.py`，绝不用凭记忆的标识符）；**到货即验身份**（`verify_corpus.py` 判别词比对，首页标题 vs slug）；不合格进 `corpus/quarantine/`，绝不静默保留 | T1/T2 清单 | `corpus/retrieval/pdf-manifest.json`（附 `corpus/pdf/`、`logs/corpus-verification.json`） | evidence-verifier | 每个 PDF 都过身份验证；**验证器上岗前先过已知坏样本回归**（一个没被坏输入考过的验证器不配守门）；unfetchable = 点名＋计数＋理由码；永不绕过付费墙 |
| **S4 文本抽取** | PDF→纯文本，多引擎回退（`extract_text.py`：PyMuPDF→pdftotext→pdfplumber） | `corpus/pdf/` | `corpus/text/<slug>.txt` 全集（附 `logs/extract-report.json`） | evidence-verifier（签收） | 低于最小字符数的判 image-only/OCR-needed，**登记不丢弃** |
| **S5 深读抽取** | 最关键的论文定向深读；每 3 篇持久化一次 `SOURCES.tsv`/`EVIDENCE.tsv` 增量 | 本地全文、补充材料、页面图像、代码快照 | 两个追加式 TSV | deep-reader / figure-reader / repo-code-verifier（按需） | 逐字转录；`version_read`、access/supplement/figure/code scope、value origin 和 derivation 不得丢；不为每篇再建大 JSON |
| **S6 综合与 ontology** | 用查询/筛选读取 TSV，形成 consensus/contradiction/boundary/implication 和方法学 appraisal；统一 claim、术语、分母 | `SOURCES.tsv` + `EVIDENCE.tsv` | `MANUSCRIPT-ONTOLOGY.md` 更新 | landscape-mapper + architect | ontology 是共享脑；分母只有一个定义；新证据修改 ontology 后才允许进文稿 |
| **S7 直接稿源准备** | 直接维护 `refs.bib`、表格 `.tex` 和已有图文件。只有重复、纯确定性的计数/绘图且仓库已有维护工具时才运行工具；禁止为一次修改新建脚本 | ontology + TSV + 已有工具 | `draft/refs.bib`、`draft/tables/*.tex`、`draft/figures/*` | evidence steward + figure/table engineer | caption 与数据一致；手工表可以直接编辑；外部图有许可；无“为了有 receipt 而写 renderer” |
| **S8 章节撰写与综合** | 每个 section owner 直接写唯一 `.tex`；全部交接后 synthesis editor 串行写 `draft/synthesis/sections/*.tex` | Markdown ontology、相关 TSV 行、真实 `.bib` | direct LaTeX + `SYNTHESIS-HANDOFF.md` | section owners → synthesis editor | 同一文件同时只有一个 writer；不写 JSON prose；不全量复制语料进 prompt；题目/摘要/正文/结论用同一概念表 |
| **S9 冻结与构建** | reducer 从实际工作树生成一个 source inventory，原子冻结 `source/`；用维护好的 `latexmk`/`latex_build.py` 一次完成需要的多 pass 构建并检查 log/PDF | direct working tree | canonical `source/` + PDF + 一个 build receipt | deterministic integrator/build adapter | 只在 source/PDF 边界 hash；无未解析引用、重复 label、致命 warning；必须看最终渲染页 |
| **S10 文献与一致性审计** | 对实际 `refs.bib`、`.tex`、表图和 PDF 检查 identity/version、引用邻接、citation stacking、术语别名、分母候选冲突、专名、metadata 和许可 | 最终 source/PDF + 权威元数据 | reviewer findings + 必要修复 | citation/factual/style/figure reviewers | 工具只做候选筛；agent 逐条裁决；修复直接回 `.tex/.bib`，不新写 patch 脚本 |
| **S11 双读可靠性** | 双读者盲评一致性研究（`dual_reader.py`：固定 seed、样本占保留池约三分之一、第二读者对首读记录盲）→ 逐字段一致率 | 保留池 + `corpus/text/` | `corpus/synthesis/dualread-agreement.json`（附 `corpus/dualread/*.json`） | 第二 deep-reader 盲实例（fresh dispatch）+ landscape-mapper（汇总） | 结果按**机机复现性**报告，永不冒充效度（两个读者可以一致地错）；**不能复现的字段必须重设计或降级**，不得再承载任何 headline 计数（参考实现：leakage-risk 一致率过低即降级）；一致率数字印进稿件 |
| **S12 发布** | `mkdeposit.py` 建 deposit 清单：逐文件 SHA-256 + 全集 root hash + 完整 inventory；root hash 印进正文；`VERSION` 定格 | 全部承印文件（检索日志、综合件、深读记录、稿源） | `DEPOSIT-MANIFEST.json`（附 `tab/deposit_numbers.tex`、`VERSION`） | manuscript-submission-packager | 清单完整性（缺文件必须可见，不是静默缺席）；**哈希只发生在此刻**（§4）；此后任何进清单的文件变化=下一次发布前重跑 mkdeposit 一次 |

回边（允许的循环，全部有名有向）：S10→S9（bib 修复后重建）；S11→S6（字段降级后重综合、重生成、重建）；
其余任何回跳都必须以登记决定为前提。

### 1.2 评审响应环 R1–R7（命名子路径；`manuscript_reconstruction` 模式将驱动）

这是外部评审（含 Reject）返回后的标准路径，即参考实现真实走过的返修环。模式
`manuscript_reconstruction` **当前尚未注册**（本次升级新增项）；注册前由 `research-orchestrator`
主线程按本环显式驱动，绝不再手搓散步骤。

| 阶段 | 干什么 | 输入 | 输出（唯一 artifact） | 负责 agent | 该停下检查什么 |
|---|---|---|---|---|---|
| **R1 评审解析** | 从 DOCX/Markdown（含 Word comments）读取全文，按稳定 segment 拆成逐条主张，并与当前稿 crosswalk | 外部评审全文 + 当前 LaTeX | 逐条 current-status/acceptance 清单 | external-review-decomposer | 无一条被改写、重复覆盖或悄悄丢弃；`ALREADY_SATISFIED` 与 `OPEN` 分开；不可判定显式标注 |
| **R2 逐条核验** | 每条主张**对 artifact 重算**判成立/不成立/部分成立（范例：`reconcile_v2.py` 对审计链质疑现场重算，证明稿件对、记录表错） | R1 清单 + 全部 run artifact | 核验表（逐条verdict＋证据） | manuscript-factual-auditor | "评审说得对不对"只由重算回答，不由记忆或辩护回答；无法重算=UNVERIFIED，不许写成已驳回 |
| **R3 登记决定** | 每条成立主张→登记决定（先登记，再同步，再执行）；**翻转 headline 的收录/排除裁决 staged 给 director**（边界记录模式，机器不替导演做决定） | R2 核验表 | 决定登记条目（含 staged 裁决单） | research-orchestrator 主线程 + director | 未登记的改动不得进 R4/R5；每条决定绑定它将触碰的 artifact |
| **R4 必要重算** | 只有证据规则或原始数据变了才重算；优先运行已有、测试过的 loader/tool。没有维护工具时在 ontology/TSV 中透明重算并双重核查，不为一次返修写脚本 | R3 决定 + TSV/原始记录 | 更新后的 TSV/ontology/table | figure-table engineer / factual owner | 新旧口径和 value origin 明写；caption、表和正文同一分母 |
| **R5 直接文字修复** | 对 `draft/sections/*.tex` 做最小直接编辑；每条 R# 在 `REVIEW-CLOSURE.md` 写 final locus 和验收证据 | R3/R4 + current LaTeX | 更新 `.tex` + closure Markdown | 对应 section owner → synthesis editor 收口 | 不写 patch 脚本，不重新生成未受影响章节；旧意见已满足则标 `ALREADY_SATISFIED`，不重复改 |
| **R6 重建** | 回 S9（含 pass 0 闸）＋ S10 文献审计 | `src/` | 新 PDF + 构建报告 | manuscript-integrator | 同 S9/S10 全部检查 |
| **R7 盲复审** | 新 instance、新稿件 hash、**不喂旧 review 文本**（盲刷新合同见 `docs/RESEARCH-DOSSIER-CONVERGENCE-CN.md`）；对外投稿判定走 `venue_readiness` | R6 新稿 | 新一轮 review artifact | manuscript_review 席组／venue-reviewer-* + 主审 | 盲性=调度合同（fresh dispatch instance、冻结 hash），不是口头声明；同一版本不重复消费同一盲评 |

**环出口**：CRITICAL=MAJOR=0 → `VERSION` bump → S12 发布；残余 MINOR 公开随稿。
到达返修上限仍有 CRITICAL/MAJOR → 保持未收敛并上报，不许换措辞蒙混。

### 1.3 新语料折入协议（fold-in）

任何新一批文献（如 T1 v2 阅读队列）折入在制稿件，唯一合法方式：

1. **staging 隔离**：新批次的 PDF/文本/隔离区一律落 staging 命名空间（参考实现：`pdf-v2/`、
   `text-v2/`、`quarantine-v2/`），**永不直写主语料**。
2. **全程走 S3→S5**：新记录从身份验证起过全部阶段，不因"只是补充"而抄近路。
3. **折入是原子事件**：staging 并入 → **全量重跑 S6–S7 所有生成器**（不挑着跑）→ `VERSION`
   bump → S9 全量重建 → S10 审计 → R7 盲复审。
4. **绝不手改任何计数、表格、caption**；折入前后的口径差异由生成器 delta 报告证明。
5. 折入期间主稿冻结；半折入状态不得构建交付，更不得发布。

---

## 2. 格式权威（format authority）

### 2.1 权威文件——三件，缺一不可

| 文件 | 权威范围 | 合同 |
|---|---|---|
| `src/type.tex` | 版式、语义宏、box 预算、调色板、**MONOCHROME 重定义块**（文件末尾，整块可删即可逆） | 任何新样式必须进 type.tex；section 文件内联定义样式=违规 |
| `build.sh` | 构建即体检：pass 0 prose-vs-corpus 闸、4-pass 编译、构建报告、渲染检查 | "失败构建"=pass 0 红／编译错／任何未解析 `??`；exit 0 不等于成功 |
| `src/main.tex` | 输入顺序＋**宏文件注册表**（头部注释写明哪个生成器供给哪个 `*_numbers.tex`） | 注释即合同；"Never hand-edit these three files -- regenerate them from the deep-read records" 按字面执行 |

新论文线克隆这三件的**结构**（预算化 box、语义宏经调色板名、构建报告、宏注册表），逐venue参数
（页边距、引文样式）按该线的 venue 证据改。

### 2.2 单色规则（monochrome，导演指令 2026-08-20）

- **不用彩色文字；不用 pill/badge（统一小型大写 `\textsc`）；不用填色 panel**。
- 区分只靠四种手段：**字重、small caps、rule 线、位置**。图内允许四档灰阶填充。
- box 预算：全文至多三个 box，且每个都必须能降级为普通 subsection 而不丢内容；其余强调一律
  takeaway 规则线（无框无填充）。
- 实现方式是**末尾重定义块**：调色板名（ink/muted/navy/teal/…）整体塌缩到灰阶，call site 一个
  不改，可逆=删块。因此**新宏、新图取色必须经调色板名，禁止内联 HTML 色值**——内联色绕过重定义，
  是单色规则唯一的漏法。
- 单色合规检查在**改 type.tex 时做一次**，不逐 build 扫描（§4）。

### 2.3 硬性格式合同

1. **摘要 150–250 词，以渲染 PDF 页计**（`check_rendered.py`）。摘要满是计数宏，源码比页面短约
   20 词——源码词数无效，此项只能在渲染页上裁。
2. **语料数字只经生成宏**（`tab/*_numbers.tex`，如 `\corpusPool{}`、`\actionNamed{}`）。需要的数字
   没有宏→报告缺口，**不打数字**。
3. **caption 与数据同一代码路径生成**（D3 教训：caption 声称"独立标签"而列还是阶梯生成的）。
4. **研究级数字**（从单篇论文转录的数值）每次构建过 `check_numbers.py` 报告；该检查是**报告不是
   闸**（年份、页数、自算比值合法地不在记录里），但未匹配项必须人工清点完才可交付。
5. 正文里"没说"与"没做"永远分开写；en-dash 表"未报告"。

### 2.4 裁决语禁列表（adjudicative-language ban list）

以下词式**禁止出现在任何节**，各配语料域替换范式（全部取自参考实现的真实修复）：

| 禁语 | 为什么禁 | 替换范式 |
|---|---|---|
| *settled*（已成定论） | 语料撑不起终局裁决 | *Observed in this corpus*＋写明比较未跨解剖/指标/患病率/分割器匹配 |
| *what displaced it*（何者淘汰了它，目的论时代叙事） | 把主导权更替写成进化裁决 | 只写"在本语料中何者**接替了主导地位**"，逐时代给可核记录 |
| *direction knowable*（方向可知） | 方向断言超出观察 | 只写观察到的效应方向＋其成立条件 |
| *the apparatus largely exists*（装置已大体存在） | 修辞跑在证据前面 | *components demonstrated repeatedly in retrospective settings; whether they compose is untested* |
| *most accurate*（最准） | 比较未匹配，不可总排名 | *reports the strongest … in this corpus*＋不可泛化限定 |
| *most consistent*（最一致） | 单次匹配比较≠总排名 | *most stable across the matched comparisons available in our corpus* |
| *never will (exist)* 等绝对时间量词 | 过度绝对 | *unavailable at the moment of decision* |
| 算术裁决成熟度（"established=≥2 组+≥1 外验"） | 把作者判断伪装成推导（D1） | 状态记录表只记**发生过什么**（复制/外验/多中心/前瞻/矛盾证据各自独立旗标），judgement 留给批判综合并署名为作者论证 |

执行：S8 交稿与 R5 补丁后对 `sec/*.tex` 跑禁列表扫描（**待落地**的确定性 lint，D2 修复项，本次
升级新增）；命中退回作者席。禁列表是活清单：每轮外部评审新指认的裁决语，经登记决定追加进来。

---

## 3. 不偏离机制（drift tripwires）

逐阶段的确定性绊线。"闸"挡住流程，"报告"必须人工清点后才可交付；两者都不许静默绕过。

| 绊线 | 挂在 | 类型 | 规则 | 状态 |
|---|---|---|---|---|
| 零产出通道 watchdog | S1 | 闸 | 声明过的检索通道 raw yield=0 ⇒ 大声失败并点名；"+0 (raw 0)" 静默滚屏即事故（A1/A6） | 参考实现已去熔断；watchdog 机器化=本次升级新增 |
| 预算语义 429 | S1 | 规则 | 配额型 429（按日重置）不得指数退避硬试；换通道或等窗口，全部记录 | 待落地（A2；机器需预算感知客户端） |
| 同规则筛选 | S2 | 闸 | 各波次必须 import 同一 `screen()`；改进只许进 screen.py 使之同时作用于所有波次 | 参考实现已有 |
| 到货验身份 | S3 | 闸 | 每个 PDF 首页标题 vs slug 判别词比对；验证器先过已知坏样本回归再上岗 | 参考实现已有（B2/B3；机器化待升级） |
| 独立标签 | S5 | 规则 | schema 只记观察，无派生字段；任何标签不得由另一标签蕴含；null≠no | 参考实现已改（C3 recode 教训） |
| 单一 loader | S6 | 闸 | 一切分母经 `synthesize.load()` 或其继任；记录表、报告、任何消费者不得自行数记录（B1 双真相教训） | 参考实现已有 |
| 域限定零 | S6/S8 | 规则 | 任何"0 项为 X"必须点名语料＋判据（"在本语料 N 项保留研究中，按…判据，0 项…"），永不写成领域断言 | 写作合同已含；lint 待落地 |
| 边界记录 | S2/S8 | 规则 | 任何零主张附最近未中样本清单（near misses）；翻转 headline 的收录/排除 staged 给 director 裁决 | 参考实现已有（`screened-boundary-records.md`） |
| prose-vs-corpus | S9 每次构建 | 闸 | `check_prose.py`：坏 citekey、存在但未 `\input` 的图表、悬空 `\cref`、零值宏——LaTeX 全都看不见，所以在编译前查 | 参考实现已有，**每次构建保留** |
| 数字转录报告 | S9 每次构建 | 报告 | `check_numbers.py`：每个研究级数字对着它旁边 citekey 的记录核对；未匹配项人工清点 | 参考实现已有 |
| 渲染页检查 | S9 | 闸 | `check_rendered.py`：摘要渲染词数 150–250；正文字数对规划带报告不强制 | 参考实现已有 |
| 生成物不可手改 | S7/R4 | 规则 | `tab/`、`fig/`、`*_numbers.tex`、`refs.bib` 只能由生成器写；生成器活在文件里，禁 heredoc（D6） | 参考实现已有 |
| 精确补丁 | R5 | 闸 | 文字修复=恰好匹配一次的三元组；未匹配/多匹配硬错 | 参考实现已有（`patch_overclaims.py` 模式） |
| 折入协议 | 新批次 | 闸 | §1.3 全条款：staging→全生成器重跑→版本 bump→全量重建→盲复审；**绝不手改计数** | 本文钉死（F 决定） |
| 裁决语 lint | S8/R5 | 闸 | §2.4 禁列表扫描 | 待落地（D2，本次升级新增） |

---

## 4. 验证经济学（导演指令 E1）

1. **哈希只在发布时刻**：`mkdeposit.py` 在 release/deposit/promote 时写一次 deposit 清单（逐文件
   SHA-256＋root hash），root hash 印进正文。平时不哈希。
2. **凭证在 artifact 未变前持续可信**：已记录的验证凭证（身份验证、审计、deposit）不因出报告、
   开新会话而重验。ledger 追加时哈希保留（便宜且完整性关键）。清单内文件变化后的**下一次发布**
   重跑 mkdeposit 一次——仅此一次。
3. **构建检查每次构建都跑**：pass 0 闸＋数字报告＋渲染检查是构建的一部分（廉价的 grep/parse，
   不是哈希），永不豁免。
4. **盲评每版本一次**：每个 `VERSION` 一次盲复审（内部 R7 或 `venue_readiness`）。给看过稿的
   reviewer 再看一遍不算盲评；返修后=新版本、新 instance。

**明令禁止**：逐报告重验 root hash；逐 build 扫描单色合规（结构性由 type.tex 重定义块保证，改
type.tex 时人查一次）；对未变化 artifact 的任何例行重哈希。

---

## 5. 路线寻优（routing）

导演话型 → 模式 → 本路径接入点：

| 导演话型（示例） | 模式 | 接入点 |
|---|---|---|
| "写综述" / "做一篇 review" / "deep research 建语料" | `deep_research`（语料）＋ `manuscript_authoring`（成稿，独立 run） | S1 起全程；成稿 run 从 S7 接 |
| "回应审稿意见" / "审稿人说…" / "被拒了怎么办" | `manuscript_reconstruction`（**待注册**；注册前由 research-orchestrator 按 R 环显式驱动） | R1 |
| "重构稿件" / "按新证据重写" | `manuscript_reconstruction` | R3/R4；涉新语料先走 §1.3 折入 |
| "投稿体检" / "这稿能投吗" / "venue readiness" | `venue_readiness`（只读） | 在 S9–S12 产物之上运行 |
| "继续读" / "消化 T1 队列" / "把新一批文献折进去" | `deep_research` 后续 run ＋ §1.3 折入 | S3（staging） |
| "改格式" / "单色" / "版式统一" | `manuscript_authoring` 的 style/latex 审计席 | S8–S9；格式权威文件本身只随导演指令改 |

规则：

1. **`operate brief` 在请求命中上表话型时必须点名本文件并给出接入点**——路线寻优的"优"就是
   命中钉死路径，而不是每次现编流程。
2. `manuscript_authoring` 与 `manuscript_review` 永远是两个 run（作者不得自评，CLAUDE.md §4）。
3. 模式清单与一键拆分以 `operate brief` 实时输出为准，永不从本文引述模式表规模。
4. 从表列接入点以外的位置切入路径，须先过登记决定。

---

## 6. 范围规则（scope rules，导演决定 F）

1. **能取尽读**（read everything retrievable）：进入 T1 的每条记录都走完 S3→S5。
2. **不可得=点名＋计数＋出界**：取不到全文的记录带理由码留在 fetch 清单里，声明节如实报告；
   永不声称读过。
3. **永不绕过付费墙**。
4. **未读材料永不进任何计数**：仅摘要级引用的论文零数字、零分母、不进任何表；背景引用层
   （`background_refs.py`）与证据引用层物理分离——背景层引文不进证据地图与方法清单。
5. **边界样本显式裁决**：资格边缘记录逐条登记证据与读法（边界记录文件），其中翻转 headline 的
   收录/排除是 director 的裁决，不是机器的。

---

## 7. 本文的修订权

- 阶段序列、格式权威、绊线、经济学规则的任何改动：导演指令 → 登记决定 → 修订本文 → 同步受影响
  的模式/agent/测试。顺序不可倒。
- 参考范本升版（如稿件大版本重构）不自动改写本文；范本路径变更须同步 §0 锚点表。
- 本文与工具源码冲突时，以**登记决定的时间序**裁定谁过时，并当日修复该冲突。
