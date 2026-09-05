# AgentSearch 检索方法并入记录（2026-09-05）

写给导演。起因：导演要求调查 https://agent-search.readthedocs.io 并把它的能力加进 research_agent_teams，让文献搜索更强。

## 1. 调查结论

AgentSearch 是 SciPhi 公司 2023 年底发布的开源项目（GitHub SciPhi-AI/agent-search，Apache-2.0 许可，554 星）。它分两半：一半是调用 SciPhi 托管服务的客户端，另一半是一个可以自己部署的本地搜索引擎。

托管服务已经停了。2026-09-05 实测：api.sciphi.ai 连接超时，www.sciphi.ai 的 TLS 握手（网站加密连接的第一步）失败，search.sciphi.ai 返回 Vercel 的"部署不存在"。注册页打不开，拿不到 API key，所以客户端那一半完全用不了。SciPhi 后来把精力转到了 R2R 项目。

本地引擎那一半需要 AgentSearch-V1 数据集：1.26 TB，5000 万篇文档、10 亿段落，来源是 arXiv、维基百科、Common Crawl 网页、StackExchange 等，2023 年 10 月的快照，之后没更新。跑起来还要 Postgres、Qdrant 向量数据库和 768 维的 Jina 向量模型。PyPI 上的包停在 0.1.0（2024-01-14），依赖锁死在 pydantic 1、openai 0.27.8、Python 3.11 以下，装进现在的环境会冲突。仓库最后一次提交是 2024-01-16。

所以没有安装这个包，也没有接它的服务。值得拿过来的是它的检索方法，一共三条：

| 它的做法 | 机器里原本的做法 | 现在的做法 |
|---|---|---|
| 分四步筛：先取 1000 条粗召回，按网址去重到 100，每篇取最贴题的一段重排到 25，再按域名权威度混合排到 10 | 四个来源各取 10 条，去重后按引用数排序，各来源自己的排名被丢掉 | 四个来源各取 20 条，先按各来源自己的排名做融合，再按摘要里最贴题的一段重排，最后按引用数和年份做小权重的权威度调整 |
| 每次回答附带"相关追问"，按深度乘宽度递归再搜 | 追问由 agent 自己想，没有机器帮它提，也没有轮次预算 | 从检索到的标题里提出追问（优先两个词的短语，附带命中篇数），按 --depth 和 --breadth 递归，连续两轮没有新文献就停 |
| 统一的结果格式：分数、网址、标题、正文片段、来源库 | 只有元数据，没有正文片段 | 每条结果带 score、text（不超过 400 字的摘要片段）、dataset（哪个来源） |

## 2. 做了什么

新增工具 `research_agent_teams/tools/search_funnel.py`，纯标准库实现，没有抄上游代码，模块开头写明了出处和许可。用法：

```bash
python -m research_agent_teams.tools.search_funnel "<query>" --final 10 --json <out>
python -m research_agent_teams.tools.search_funnel "<query>" --depth 2 --breadth 2 --json <out>
```

四步分别是：

1. 粗召回。走原有的 paper_search 入口，arXiv、OpenAlex、Crossref、Semantic Scholar 各取 20 条。paper_search 现在额外返回每个来源自己的排名顺序（channel_rankings），原有调用方不受影响。
2. 跨来源融合。用 Reciprocal Rank Fusion（把几个来源各自的名次合成一个总分，两个来源都排前面的文献得分最高），复用了 recall 模块里已有的实现。标题和问题不沾边的先按原有规则滤掉。
3. 段落重排。对融合后的文献，用一次 OpenAlex 批量请求（每 50 个 DOI 一次）取摘要，选出和问题最贴的一句话作为 text，段落得分和融合得分各占一半。也可以传入本地全文。取不到摘要就只按融合得分排，并在 source_errors 里记一条。
4. 权威度调整。最终分 = 0.9 × 相关度 + 0.1 × 权威度，权威度 = 引用数（对数刻度，1000 次封顶）加年份新旧。0.1 这个权重照搬上游的 pagerank_importance，用 --alpha 可以改。

递归搜索加了两道保护。追问里保留原问题的前四个关键词，避免搜着搜着丢掉"segmentation"这种核心词；追问搜回来的文献还要再过一遍原问题的标题相关度，过不了的记进 n_drift_rejected，不进合并列表。合并列表先按对原问题的相关度排，再按各自的分数排，因为不同问题的分数之间不能直接比。

边界照机器原有规则：所有分数和 text 片段只用于挑先读哪篇，不给 claim_support 打分，不进证据表（to_evidence_sources 原样不变），不替代读原文。递归停下来只是"不再扩展"，不是"证据已饱和"，evidence-search-moderator 仍然自己填 evidence-search-trace/v1；trace_rounds() 只给它一个带问题和命中来源的轮次骨架。输出写到 runs/<run>/inbox/search-funnel.json，和原来的 search-results.json 并存，不替换。来源失联照旧记在 channels_lost 和 source_errors 里。

配套改动：skills/research-lookup.md 加了用法一节；skills/literature-review.md 第二阶段加了一句指引；PLATFORM-FACTS.md 第 0 节的工具数和测试文件数按磁盘重新数过（163 个工具、258 个测试文件，之前写的 159 和 254 已经过期），5.1 节加了一段；README.md 加了 wave 2 一条。agent 说明文件没有动，避免触发 inline twin 镜像检查。上游 skill 来源登记表（external_research_skill_sources.json 等）也没有动，那些表被测试钉死在 9 个来源、359 个 skill、25 项能力，而且 AgentSearch 是代码框架不是 skill 仓库，按 wave 1 的先例走原生实现加出处说明。

## 3. 怎么验证的

离线单元测试 `tests/machine/test_search_funnel.py`，18 个用例，全部离线用假数据跑：两个来源都命中的文献排第一；5000 次引用的离题文献被过滤；摘要只发一次批量请求；摘要取不到时排名照常并记错误；alpha 取 0 和 1 时分别等于纯相关度和纯权威度；分数不会漏进证据表；追问里没有"for""with"这类虚词；递归在连续两轮零新增后停止、不重复搜同一问题、深度宽度生效；追问搜回来的离题文献被拦下；轮次骨架能通过 evidence_search_trace 的 schema 校验且被判为 INCOMPLETE；写文件拒绝知识库路径；命令行输出正确。连同 paper_search 原有 13 个用例一起跑，31 个全部通过。

联网实测（2026-09-05，问题 "interactive PET/CT lesion segmentation with text prompts"）：

| 项目 | 结果 |
|---|---|
| 单次四步筛 | 原始 65 条，去重 64，融合后 37，段落重排 20，最终 8 |
| 第一名 | Towards Interactive Lesion Segmentation in Whole-Body PET/CT with Promptable Models（arXiv 2508.21680，arXiv 和 Semantic Scholar 同时命中），正是导演论文库里已有的 autoPET IV 那篇 |
| 递归 depth 2 / breadth 2 | 搜了 3 个问题，第二轮追问是 "... segmentation whole body" 和 "... segmentation models"，新增 7 篇，其中有 Rethinking Annotator Simulation（arXiv 2404.01816），离题拦截 0 篇 |
| 来源失联 | Semantic Scholar 在第二轮一次 429 限流、一次超时，都记在 source_errors 里，其余来源照常 |

加追问关键词保护之前的一次实测，第二轮追问丢了"segmentation"，混进了 1995 年的肺癌 PET 分期论文和一本 PET/CT 扫描规程，这就是加保护的原因。

全量测试：改动前后各跑一次 `python -m pytest tests/`，结果见第 5 节。

## 3.1 接进默认步骤（导演 2026-09-05 拍板）

导演决定：四步筛接进 pre-search 默认步骤，deep_research 默认多跑一轮追问，不引入向量模型。改动如下。

原本 `operate pre-search` 只跑一次多源搜索，写 search-results.json。现在同一步里紧接着跑四步筛：其它入口模式跑一层（只有四步），deep_research 跑两层（四步加一轮追问，每个问题最多追两个）。命令行加了 `--funnel-depth`、`--funnel-breadth`、`--no-funnel` 三个开关。

写出来的东西分两处。search-results.json 保持原有格式，只是每条文献多了 funnel_rank 和 funnel_score，只有四步筛找到的文献按元数据追加进去并标 found_via，整个列表按四步筛的名次重排，另附 related_queries 和一个 funnel 小结（各阶段数量、追问停止原因、失联来源）。原有的 source_errors 和相关度过滤统计原样不动，所以旧测试里"四个来源全失联记 4 条错误"的断言照旧成立。search-funnel.json 放完整结果：每个问题的各阶段数量、每轮追问、每条文献的摘要片段。四步筛自身出错时记成 funnel.status = failed，主流程照常。

deep_research 的 worker 提示词里加了两行，告诉 agent 文献列表已按四步筛名次排好，摘要片段和追问在 search-funnel.json，只用于挑先读哪篇。另外给 Semantic Scholar 加了每秒最多一次请求的节流，之前连续追问时它返回过 429。

验证：新增 5 个用例（合并逻辑、默认开启、关闭开关和中文请求不跑、失败不影响主流程、deep_research 默认两层），连同受影响的 32 个模式和命令行测试文件一起跑，633 通过、1 跳过。联网实测 deep_research.pre_search（同一个 PET/CT 问题）：22 秒，原本多源搜索得到 18 条，四步筛加追问后列表变成 35 条，其中 17 条是追问新找到的，前五名里有 RADIANT-PET 和 Rethinking Annotator Simulation 两篇，追问词是 "fdg"、"18f fdg"、"pet images"。

## 4. 没有做的

没有装 agent-search 包，没有接 SciPhi 服务，没有下载 1.26 TB 数据集，没有引入向量模型。第三步的"最贴题一段"用的是词汇重合，不是上游的向量相似度，这是不加依赖的代价。如果以后要本地向量检索，recall 模块的注释里留了位置（第五条通道）。

## 5. 全量测试结果

`python -m pytest tests/`，工作区根目录，最终代码：4 失败 / 5369 通过 / 52 跳过，7 分 53 秒。4 个失败改动前就有，与本次无关：editor3d receipt 自声明、manuscript authoring 证据链聚合、vendor 目录清单两项（nature-skills 里多出一个 manifest.yaml）。改动前同一台机器的记录是 5 个失败，少掉的那个是 PLATFORM-FACTS 第 0 节计数校验，这次把过期数字改成磁盘实数后它通过了。两轮测试同时跑时 test_scientific_figure 的一个 PDF 渲染用例偶发失败，单独重跑通过，属于并发冲突。

接进默认步骤之后再跑一遍全量：3 失败 / 5386 通过 / 52 跳过，10 分 15 秒。3 个失败仍是改动前就有的那几个（editor3d receipt、vendor 清单两项）；manuscript authoring 那个失败在这期间被另一个同时在改本仓库的会话修掉了。通过数比上一轮多 17，来自本次新增的 5 个用例和另一个会话新增的测试文件。
