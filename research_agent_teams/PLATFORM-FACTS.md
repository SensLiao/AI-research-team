# Platform Facts — what this research machine can actually do right now

> **The one place** the command palette + skills cite for "what can this machine do today, and what
> waits for the server." This is a **fact source, not marketing**. If something only emits a script,
> it says so. If something needs the GPU server, it says so. Communication default: 中文 (global §0).
>
> Authoritative upstream (this file condenses, never overrides): `.claude/CLAUDE.md` §3-§7 ·
> `_design/workspace-control-plane-LEDGER.md` (W0-W5) · `server_monitor/PLATFORM-NOTES.md` (server
> footguns — the deeper ref) · `workspace/registries/command_registry.yaml` (the palette).

---

## 0. 一句话定位

这是一台**只读知识库 + 干活工作坊**的双系统机器：工作坊（`research_agent_teams/`）做研究、出草稿、跑流程；
知识库（`PhD-Research-OS/`）只存被人审过的成品。绝大多数研究动作**今天就能一键跑、不需要 GPU**；唯一卡在
服务器上的是「**真的在 GPU 上跑实验**」——那一步现在只能产出可运行脚本，还没真跑过。

---

## 1. 能力边界 —— 三个诚实分桶（最重要的一节）

> 红线：**真能跑** ≠ **只有规格（spec-only）** ≠ **等服务器**。把「出脚本的设计跑」说成「实验真跑了」是
> 红线（CLAUDE.md §3）。

### ✅ 桶一 · 现在就能一键跑、不用 GPU（the SEVEN wired modes + 三个常驻动作）

这 7 个 mode 有 operate 配方、镜像测试过，导演一句话就能从头跑到尾：

| Mode | 干嘛用（业务价值） | 产出 |
|---|---|---|
| `new_direction` | 找研究方向：扫空白 → 锦标赛式评点子 → 排名菜单 | `/idea-bet` 菜单（导演下注） |
| `gap_breadth` | 扫空白点：5 个 hunter 并行 → 分类 → 只打新颖度分 | 空白点清单（score-only） |
| `evidence_review` | 评证据 / 文献快读 | 证据表 + 裁决 |
| `evidence_deep` | 文献深读 | 深度证据综述 |
| `deep_research` | 多源事实核查式调研 | 带引用的调研报告 |
| `venue_readiness` | 「够投顶会吗」：mock 盲审 | → `/venue-pick` · `/venue-decide` |
| `full_rigor_minimal` | 实验从 DESIGN→…→VERIFY（含预注册 + 显著性统计 + 诚实的「只出脚本」EXECUTE 路径） | 设计 + 可运行脚本（**不是真跑**） |

每个 wired run 都被逐 stage **north-star 漂移门**把关、**接地门**把关（引用是否真实存在 / 引用完整性），
全程记进**防篡改 run**。外加三个常驻动作（同样不用 GPU）：**ingest**（收论文进库）、**recall**（按引用查库）、
**promote**（经人类门把成品写进库）。

### 🧩 桶二 · 只有规格，**不是一键**（spec-only — 别当 push-button 介绍）

这些 mode 在 registry 里定义了、引擎测过了，但**还没有 operate 配方**，所以**不能**当按钮用（audit H8 诚实规则）：
`design_experiment(±minimal)` · `verify_result` · `ideate_ring` · `gap_scan` · `debug_failed_run` ·
`tree_explore` · `m2_accept` · `full_new_direction` · `check_run` · `ingest_paper`。

### ⏳ 桶三 · 等导演的 GPU 服务器（§6）—— 真跑实验

**真的在 GPU 上训练 / 推理**这一步等服务器。EXECUTE 那层**会写出真能跑的脚本**，但要跑起来需要已接好的服务器 +
凭据。今天的状态：**tested, NOT operated**（测过、没在真研究上运营过）—— 机器内没有 GPU executor。
结构性诚实保证：`full_rigor_minimal` 的 EXECUTE 若没有 journal，run_records 保持 `planned`、metrics 为空——
**所以一个「设计跑」永远不会被误当成「真跑」**。深层服务器注意事项（CRLF / `python` 是 py2 / 根分区满 /
conda `set -u` / SFTP 整文件替换 / BatchMode 不可用）见 `server_monitor/PLATFORM-NOTES.md`。

---

## 2. 新控制平面（W1-W5）—— 大白话

2026-06-16 给机器加了一层「工作坊管理台」（只加层，不动既有 mode / schema / 库；project-local，全局
`~/.claude/` 没碰）。建设进度账本：`_design/workspace-control-plane-LEDGER.md`。

- **W1 · 共享资源池（已建，2066 green）**：把 4 类资源（服务器凭据 / 研究 API / harness web 工具 /
  个人连接器）登记成一个池子，但**只存「引用」——环境变量名，绝不存值**。租约（lease）有 TTL，审计行**脱敏**
  （拒绝任何像密钥的键）；resolver 走 default-deny，解析出来的对象身上**不带任何密钥值**。
- **W2 · 只读服务器查询 skill（已建，2089 green）**：`server-query` 看服务器现况（tmux / nvidia-smi /
  训练进度 / 磁盘），**只读**——每条命令过 `ReadOnlyExecutor`，拒绝一切改动动词和 SFTP。真连 SSH 由
  `RAT_SERVER_QUERY_AUTHORIZED` 把关，**默认关**；模型不能自己授权。
- **W3 · 工作坊看板 + 项目生命周期（已建，2103 green）**：项目索引 / dashboard 从 run manifest **派生**
  （镜像库登记表，**绝不写库**）；生命周期 = archive（藏起来，可逆）/ soft_delete（藏 + 撤租约，**啥都不删**）/
  **有护栏的 hard_purge**（项目还有活 run / 活租约 / 已 promote 的成品 / 没先藏起来时**拒绝执行**，且
  **永远不碰库**）。
- **W4 · 执行颗粒度（CLI 已落、账本标 pending）**：可以中途**单跑一个 stage / skill / bridge**，会对着
  防篡改 manifest 做**依赖检查**——缺输入就给「修复菜单」并 exit 3，**绝不凭空捏造缺的输入**。
- **W5 · 命令面板（registry 已落、账本标 pending）**：`workspace/registries/command_registry.yaml` =
  导演面向的 slash 命令单一真相源；破坏性命令标 `disable_model_invocation`。

> 诚实边界：账本 Wave 表里 **W4 / W5 仍标 ⬜ pending**——CLI verbs 和 command registry 已经在仓库里、可用，
> 但这两个 wave 的**完整收尾 + 全量测试门**还没在账本上勾掉。按「真能跑 vs 规格」分类：这些 verb 真能跑，
> wave 的「完成签字」还没落。

---

## 3. 人类门（导演的签字点 —— 模型**永不**自决）

全部 `disable-model-invocation`，只有导演能跑（specs 在 `research_agent_teams/gates/`）：

- **`/idea-bet`** —— 押哪个研究方向（拒绝 = 「都不行，换方向」）。
- **`/promote-to-vault`** —— 把审过、人类冻结的成品收进库；门会**从真实审计重新推导** frozen / can-cite-thesis，
  `provisional` 的结果**结构上就不可 promote**（不信任 self-claim）。
- **`/venue-pick`** —— 选投稿目标。**`/venue-decide`** —— 发表 / 迭代 / 转向。

机器只产出**诚实的派生裁决**；下注、发表、写进皇冠珠宝的**决定永远是导演的**。

---

## 4. 双系统边界 + 唯一的缝

- **THE MACHINE** = `research_agent_teams/`（工作坊 + 控制平面 + run-store 草稿；git 仓库 #1）。
- **THE DATABASE** = `PhD-Research-OS/`（只存审过的知识；git 仓库 #2）。
- 两者**不混**，只在**一个缝**相连：机器**按引用读库**（`recall`），并**只经 `/promote-to-vault` 门写库**。
  其余一律不跨。草稿活在 `runs/<project>/<run_id>/`（临时、gitignored，**在库外**）。
- 皇冠珠宝对机器**只读**（can-cite-thesis 推导 / evidence-contract / status-registry / 3-layer 边界 /
  slug-never-rename：读，不改）。库登记表（`05-registry/project-registry.md`）导演加行、**机器永不写**。

---

## 5. 密钥纪律

- 凭据**绝不**进仓库 / git / chat / log；只在 **gitignored** 的 `research_agent_teams/.env`。
- 占位模板 = `research_agent_teams/.env.example`（提交它，无真值）。导演经**仓库外**交接文件
  `<仓库外临时路径，例如 ~/secrets/server-access-handoff.md>` 给凭据 → 转抄进 `.env` → 交接文件可删。
- 资源池**只存环境变量名**（引用），不存值；**连接时**才解析，**永不回显**。SSH **host-key 强校验**
  （非 trust-on-first-use，未知 host 直接拒）。

---

## 6. 今天导演能跑什么（快速参考）

> 面板单一真相源：`workspace/registries/command_registry.yaml`。真正的 operate verbs 见
> `operate/cli.py` `build_parser`（下表已对齐）。

| 想干嘛 | slash 命令 | 底层 operate verb |
|---|---|---|
| 开工作坊 / 看板 + 选项目 | `start-research` | `dashboard` / `index` |
| 跑一个完整 mode（7 个 wired） | `run-mode` | `begin`（→ `worker`→`pre-search`→`run-dets`→`commit`→`menu`） |
| 中途单跑一个 stage / skill / bridge | `run-stage` / `run-skill` / `run-bridge` | 同名 verb（依赖检查，不捏造缺输入） |
| 看 / 建 / 列 项目 | `project-new` / `project-list` | `project-init` / `index` |
| 藏 / 恢复 / **删** 项目 | `project-archive` / `project-restore` / `project-delete`† | `project-archive` / `project-restore` / `project-soft-delete`→`project-purge --confirm <slug>` |
| 看资源池 / 绑资源 | `resources` / `resource-bind` | `resources` / `resource-bind`（只显能力，无密钥） |
| 看 GPU 服务器状态（只读） | `server-query` | `python -m research_agent_teams.server_monitor`（`--live` 需 `RAT_SERVER_QUERY_AUTHORIZED`） |

† `project-delete` 标 `disable_model_invocation`：只有导演带 typed `--confirm <slug>` 才跑；有护栏、**库永不碰**。

跑机器自测：`python -m pytest research_agent_teams/tests/ -q`（当前 **2103 green**）。
