# 可用性加固 + 通用汇报层 — 2026-08-01

状态：`SHIPPED / 3836 tests green / 0 regression`
上一轮基线：2026-07-31 `3809 passed`（见 `research-capability-overlay-evaluation-2026-07-31.md`）

本轮不是新增科研能力，而是**让已有能力真正被导演够得着**，并补上导演点名要的通用汇报模块。
方针（导演 2026-08-01 lock）：**架构 + 格式的简洁验证**，不做人海战术、不做字数挑刺、不因一点格式
不对就重做；要的是**能用、高效、分工明确、科研能力强、体验好**，而不是更严的代码治理。

---

## 1. 先验证：上一轮四件事是不是真的

只做架构级抽查（有没有真凭据 + 自不自洽），不逐字复核。

| 项 | 结论 | 凭据 |
|---|---|---|
| A6000 巡检与排期 | ✅ 真 | `Honor degree/projects/petct_textual_intent/records/2026-07-31-independent-goal-server-audit.md` —— OOF 已 COMMITTED（597 cases / 378 patients，ready SHA-256 已钉），随后外层 root 因部署端 `--mode identity` 不识别而 FAILED；含 7 步安全续跑计划 |
| 第二台服务器入册 | ✅ 真 | `resources/resource_registry.yaml` + `resources/verification/server.usyd.bdav_z390_3090-preflight-2026-07-31.yaml` —— 只读已验证、执行被封、密钥只以 env 名存在 |
| PET/CT 3.1–3.6 | ✅ 真 | `Honor degree/projects/petct_textual_intent/docs/00-OVERVIEW-AND-READING-ORDER.md §3.1–3.6` 冻结答案表 + `01`–`12` 详档 |
| 科研团队升级 | ⚠️ 部分 | overlays / 157 agents / 12 modes 都在，但**入口文档失真**（见 §2）且缺汇报模块 |

---

## 2. 修掉的三个真问题

### 2.1 主入口不认识自己一半的本事（最严重，直接害体验）

`operate/modes/REGISTRY` 真实有 **12** 个一键模式，但导演能看到的入口写的是：

- `.claude/skills/research-orchestrator/SKILL.md` → `SEVEN`
- `.claude/CLAUDE.md` → `EIGHT`
- `.claude/commands/run-mode.md` → `7`
- `AI-RESEARCH-TEAM-ARCHITECTURE-CN.md` → `10`

后果：`read_paper_deep` / `ingest_paper` / `manuscript_authoring` / `manuscript_review` /
`deep_ideation` 五个真实能力**对导演不可见**。

**处理**：重写主入口 SKILL（改成人话路由表：导演说什么 → 走哪个模式 → 走哪些阶段 → 产出什么），
同步另外三份文档。**防复发**：`tests/test_reporting.py` 新增 entry-doc truth 测试 —— 入口文档漏掉任一
一键模式、或写死一个与 registry 不符的数量，测试直接失败。

### 2.2 四个模式根本没有路由

`plan_catalog.yaml` 只有 5 条 intent，覆盖 12 个模式中的 8 个。导演说「帮我精读这篇论文」
「设计这个实验」「审一遍我的稿」都匹配不到，**静默回落**到找方向的路线。

**处理**：新增 3 条 intent（`read_paper` / `design_experiment` / `write_manuscript`）+ 对应的
phase_rank + 4 个模式的追问项（例如深读必问「读哪一篇」）。**防复发**：新增
`test_every_one_button_mode_is_reachable_from_some_intent` 与 `test_each_intent_matches_its_own_phrasing`。

### 2.3 质量记分板永久全红

完成的运行里 12 个不达标 —— 经查**全部是 pre-product-contract 的旧运行**，靠重渲染修不好，
只能重跑（导演的决定）。它们把 `overall_status` 永久钉在 `blocked`，于是没人再看这块板。

**处理**：按 product contract 分「当前合同 / 旧合同」两档。只有**当前合同**下缺主产物才 BLOCK；
旧运行计数并**逐个列名**在 `legacy_failure_run_ids`，不隐藏、不阻塞。
记分板从 `blocked` → `needs_manual`（仍有 1 项人工检查未关），当前合同下 0 FAIL。

**安全前提已验证**：12 个一键模式**全部**在 `mode_registry.yaml` 钉了 `handoff.product_version`，
所以今天新建的运行一定算「当前合同」，真回归照样被拦。由
`test_every_one_button_mode_pins_a_product_contract` +
`test_a_live_regression_is_not_hidden_by_a_legacy_backlog` 守住。

---

## 3. 新增：通用汇报层 `reporting/`

导演 lock：**每次做任务前先扫库出计划并汇报；做完后用大白话汇报进度，不要一堆缩写和字母代号。**

| 文件 | 职责 |
|---|---|
| `reporting/plain_words.py` | 内部代号 → 人话的唯一词表（模式名、阶段名、关卡、判定、执行阻断原因、报告内容块）。未收录的词**原样保留**而不是悄悄丢掉，`untranslated()` 列出待补 |
| `reporting/scan.py` | 只读扫描：知识库分类计数、与本次请求相关的现成条目、注册项目、最近运行、算力与检索资源、真实一键模式清单。任何一角读不到就诚实降级为 `available: False`，不抛异常 |
| `reporting/briefing.py` | 开工前计划卡：要做什么 / 库里已有什么 / 打算怎么做（分层方案 + 推荐理由）/ 会在哪个人类关卡停 / 有什么资源做不了什么 |
| `reporting/progress.py` | 收工后进度汇报：一句话结论 / 阶段进度条 / 能打开看什么 / 哪些还不能说 / 要你做什么决定 / 下一步 |

命令：`operate brief --request "…" --project <slug>` 与 `operate report --run-id <id>`。
两者都**确定性只读**：brief 不启动任何运行，report 不修改任何运行（各有测试守住）。

**一处诚实性 bug 当场修掉**：第二台服务器声明了 `submit_job` 能力，早期版本的计划卡直接照抄，
读起来像「这台能训练」。现在硬件资源报**有效**能力而非**声明**能力 —— 被封的机器不会显示
「可以提交任务」，并逐条列出卡在哪（硬盘满 / 环境没装 / 排队系统没配 / 没做写入试跑授权）。
声明值仍保留在 `declared_capabilities` 供审计。

---

## 4. 验收

```powershell
cd research_agent_teams
python -m pytest -q -p no:cacheprovider tests
```

`3836 passed, 4 skipped`（2026-07-31 基线 3809；本轮净 +27，**0 回归**）。

两个新命令均已在真实数据上实跑：`brief` 对 6 类请求正确路由并渲染；`report` 对既有运行
`v3-read-ritm-20260711` 正确读出阶段、产物、缺失内容块与待决决定。

---

## 5. 本轮明确**没有**做的事（不许含糊）

- 没有跑任何 GPU 实验；没有改 PET/CT 的科学结论；没有动知识库内容。
- 没有让 Stage-B 盲评真跑 —— 它仍卡在 `HOST_USAGE_CALLBACK_BLOCKED`（缺逐调用 provider usage
  回执的 host signer）。本轮**没有**为了让它变绿而弱化它的合同，也**没有**把它当成质量证据。
  因此「科研质量显著提升」这句话**依然不能说**；能说的只是：可用性和可达性变好了，且有测试守住。
- 没有新增科研能力（agent / mode 数量未变：157 agents / 12 一键模式 / 26 modes）。
