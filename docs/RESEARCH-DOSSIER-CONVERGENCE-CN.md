# 研究 dossier 的作者—审查—返修—复核标准

本标准把一次真实项目复盘中有效的做法固化为通用机器合同。它不保存模型的隐藏思维链；保存的是可审计的
产物版本、审查发现、证据锚点、修复责任、验收条件和每轮收敛结果。

## 这次升级固化了什么反馈过程

旧版 `deep_research` 在 `landscape-mapper` 综合后就结束，能产出一份有用 dossier，却没有证明这份 dossier
经过了独立方法审、实现审和证据审。真实复盘中，最有价值的改进不是继续增加 brainstorm 作者，而是让不同
审查者连续发现并修掉以下不同类型的问题：closest-prior claim 过宽、跨 state 公式定义域不成立、field swap
违反 grammar、训练 job 数与三 seed 承诺不闭合、gold/predicted exposure 不匹配、旧 snapshot 覆盖 live state、
以及 citation BLOCK 被误读成 novelty 已核验。

因此本次把“人手驱动的多轮反馈”改造成机器可重复的合同：

1. 作者只负责综合和返修，不自审；
2. 三个 reviewer 只覆盖互补 lens，不各自重写全文；
3. 主审只做完整性、去重和 H-Max，不发明新论点；
4. 每个严重问题都携带 locus、evidence、owner、repair action、acceptance check；
5. 新一轮 reviewer 看新 artifact，不看旧 review 文本，避免围着上一轮答案做表面修辞；
6. deterministic checker 负责 hash、instance、coverage、严重度、计数和状态边界，不能只信 reviewer 自报。

三个 reviewer 加一个 chair 是当前的最小非冗余组合。新增更多 agent 只有在出现新的独立 lens（例如真实临床
workflow 或正式统计审计）且现有 coverage check 无法表达时才合理；同一 lens 的重复意见不作为扩席理由。

## 固定顺序

1. `landscape-mapper` 是唯一作者，先生成完整的 typed brief 与 Markdown draft。
2. 三名审查者在调度/提示合同层互相独立地读取同一个冻结作者 bundle：
   - `research-dossier-method-reviewer`：方法、论文、prior art、对照与干预合法性；
   - `research-dossier-implementation-reviewer`：项目真实状态、代码/数据合同、leakage、预算与 seed chain；
   - `research-dossier-evidence-reviewer`：证据、引用、覆盖完整性、状态与 gate 语义。
3. `research-convergence-chair` 运行 H-Max 合并：不得漏掉发现，不得降低严重度。
4. 存在 CRITICAL/MAJOR 时，只把修复任务退回唯一作者；三名审查者与主审随后以新 instance 对新 hash
   重新盲审，不接收旧 finding 文本作为提示。
5. 只有内部 CRITICAL=0 且 MAJOR=0，才叫“内容收敛”。MINOR 继续公开；缺全文、缺当前项目快照等外部
   blocker 继续公开，不能靠改措辞消失。

## 机器层的不可绕过约束

这套流程不是只把 reviewer 名字写进 prompt，而是把审查独立性和返修范围变成可验证状态：

- scheduler 为作者、三名 reviewer 和 chair 的每次 dispatch 发放唯一 `dispatch_instance_id` 并写入授权
  receipt；worker 自报 ID、实际输出路径、agent、cycle 必须与 receipt 完全一致。无 receipt 的预写输出直接拒绝。
- 同一 run 的全部历史 dispatch ID 必须全局唯一；返修后的 blind refresh 必须使用新 instance 和新作者 hash，
  不能把旧 review 改个文件名当复核。
- reviewer 的 `coverage_checks` 必须精确覆盖自己 lens 的机器清单。`FAIL` 必须落到 CRITICAL/MAJOR
  finding 或 external blocker；`N/A` 只允许预先声明的项目类型例外。
- implementation reviewer 必须声明 `project_state_assessment`。只有位于
  `inbox/project-state/*.artifact.json`、通过 `project_state_snapshot` schema、由
  `project-state-capture` 创建、在 reviewer dispatch 时仍未过期，并且逐个绑定 canonical/live source
  路径与 SHA-256 的快照才能标 `CURRENT_HASH_BOUND`；任意普通 run JSON 不能冒充项目状态。
  `MISSING/STALE/UNBOUND` 必须成为 external blocker，不能由作者补一句说明假装闭环。
  标准 producer 是 `python -m research_agent_teams.tools.project_state_capture ...`：它只复制导演显式
  指定的非秘密 source，绑定 task frame/project/hash/有效期，并把 approved snapshot 写进专用 lane；
  它不自动扫描项目，也不读取 `.env`、key、credential 或 token-shaped 文件。
- 每个严重 finding 都携带 `allowed_json_pointers`。返修 plan 同时冻结目标 artifact 路径、SHA-256 和
  可修改 JSON Pointer；任何越界改动都 fail closed，并停留在同一 repair cycle 等待正确重做。
- chair 只能对三份 source findings 做 H-Max、去重和精确 pointer 并集，不能扩大作者可写范围，也不能改写
  reviewer blocker 的 `kind` 或 `required_input`。

这里的约束是 scheduler/receipt/hash/prompt/input contract 的隔离，不是操作系统级不可读 sandbox。系统不会
把“未授权输入没有被注入”夸大成“进程物理上绝不可能读取文件”。

## 最终交付边界

`research-delivery-boundary.artifact.json` 是最终交接的机器真值面。它绑定 reviewers/chair 实际审阅的最终
`landscape-mapper` bundle hash、convergence artifact hash、四类 scientific gates，以及逐条保真的原始
external blockers。Markdown 和 REPORT 都必须读取它，而不是从作者措辞推断状态。

- 没有独立、精确绑定同一作者 snapshot、且 gate artifact 自身也有 hash 的 novelty PASS 时，novelty 固定为
  `UNVERIFIED`。
- evidence、citation、citation-attribution、existence 任一 gate 非 PASS，或仍有 external blocker 时，交付只能
  是 `USABLE_WITH_CAVEATS`；content convergence 不会覆盖它们。
- 当 novelty 不是独立、精确作者绑定且 hash-bound 的 `VERIFIED_PASS` 时，authoritative Markdown 使用
  `MACHINE_ONLY_UNVERIFIED` allowlist 投影：只显示 IDs、枚举、gates、support relation、refs/hash/counts；
  作者、perspective、claim、locus 与论文的自由文本完整保留在原始 JSON 供审计和发散，但不进入正式结论区。
  external blocker 的 `description/required_input` 只在显式标记的 non-authoritative 附录逐字保留。自然语言
  denylist 仅是辅助 lint，不再承担安全边界；只有可信 novelty gate PASS 才解锁 `FULL_VERIFIED` prose。
- `CONTENT_CONVERGED` 永远不等于项目批准、实验完成、人类下注或 vault promotion。

## 何时才增加更多 agent

本次新增了三名互补 reviewer 和一名 convergence chair。成本不是限制，但重复 lens 会制造伪共识，因此扩席
依据是新的独立失效面，而不是“多一个 agent 看起来更严谨”。例如，只有论文开始承载正式统计推断或真实临床
workflow claim 时，才应新增统计审计或临床流程 agent，并同时新增该 agent 专属的 coverage contract、schema 和
可失败测试；否则现有 reviewer 应直接在自己的 lens 内覆盖。

## 三类状态不能混写

- `CONTENT_CONVERGED`：内容内部合同已收敛。
- citation / attribution gate：引用是否存在、locator 是否可重开、是否完整蕴含 claim。
- novelty / project / human gate：是否在限定检索范围内无碰撞、是否批准方向、是否启动实验或进库。

前一个状态永远不能自动抬高后两个状态。尤其 formal citation `BLOCK/UNVERIFIED` 时，创新只能保持
`UNVERIFIED`，不能写成“已查重通过”。

## 审查者必须机械检查的高价值问题

- 处理效应是否有同架构 `no-treatment` 对照；shuffled 只能作 placebo/diagnostic。
- 字段是否能合法独立干预；结构绑定字段必须做 joint intervention。
- 比较是否同输入、同 encoder/editor 注入点、同参数/训练预算，还是混入 source/exposure confound。
- predicted chain 是否真的被 downstream 消费；gold/oracle 只能是上界。
- multi-stage seeds 是否以 A↔A、B↔B、C↔C 绑定全部上游/compiler/editor checkpoint hashes。
- 当前状态是否来自 live manifest；带时间戳的旧 review packet 只能作为历史证据。
- project code/vault/mirror 的 source-of-truth 是否明确，是否把副本漂移当成事实。
- inference-visible、metadata-only、train/VAL label 与 locked TEST 是否物理和语义隔离。
- 论文事实、数值、分母、表格/章节 locator 与“推断”是否分开。
- 可选实验是否被误写成核心贡献，训练 fit 数与三 seed 稳定性是否算术闭合。

## 严重度与责任

- `CRITICAL`：会使核心 novelty、方法定义、证据真实性或 leakage 边界失效。
- `MAJOR`：会使关键的比较不可执行、不可归因或与项目真实状态矛盾。
- `MINOR`：措辞、展示或非关键的覆盖问题。

每个内部 finding 必须包含 `responsible_agent=landscape-mapper`、目标 artifact、repair action、acceptance
check 和 evidence refs。审查者不得兼任修复 owner。外部 blocker 只记录需要的输入，不生成虚假修复。

## 终止条件

返修沿用 bounded repair 的 cap/plateau 规则。到上限仍有 CRITICAL/MAJOR 时，run 保持未收敛并上报剩余
finding IDs；不得以 `USABLE_WITH_CAVEATS` 偷换成内容已通过。若内容已收敛但外部证据仍阻塞，则交付
`CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS`，并让正式 evidence/citation gate 继续 fail-closed。

这里的“互相独立/盲刷新”是 scheduler 与 prompt/input contract 的隔离：sibling review 不会被授权或注入；它
不是操作系统级 filesystem sandbox。独立性证据因此应表述为调度合同、冻结 hash 与 fresh instance，而非
声称进程在物理上无法读取其他文件。
