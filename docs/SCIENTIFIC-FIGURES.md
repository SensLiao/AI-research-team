# 科研绘图：最小团队、工具与交付标准

实施于 2026-09-05。适用科研论文的机制图、概念图、证据图表与真实统计图；不调度网页 UI、海报或品牌设计 skills。

## 1. 一次期刊确认，贯穿图与论文

每个**最终交付轮次**由主线程问一次：“这次最终稿准备投什么期刊？”带上已有目标或最推荐的一个期刊。内部修图、编译重试不重复问。

- 用户指定目标：采用该期刊，读取官方指南与实际模板。
- 用户暂未指定/无偏好：主线程或现有 venue scout 根据主题、文章类型、分子/临床/方法范围推荐一个期刊，写明简短理由；按该推荐完成。
- 不把 IJMS 设为所有科研项目的默认期刊；IJMS profile 只是已验证使用的首个例子。
- 必须真实发问，再记录 `USER_CONFIRMED` 或 `RECOMMENDED_NO_PREFERENCE`。记录不等于独立的用户授权证明，不能虚构回答。
- 换期刊时更换 profile；冻结稿件已经有另一目标时，创建新 snapshot，不暗改契约。

`tools/journal_render.py` 提供 `journal_question`、`choose_journal`、`validate_journal_choice`。规范区分 `official_requirements` 与 `internal_targets`，并记录官方页面访问状态。网站限流时不能把索引副本冒充实时完整核验。

## 2. 复用三个角色，不新增编排系统

| 角色 | 输入与工作 | 只交回什么 |
|---|---|---|
| `manuscript-architect` | 已确认/推荐的期刊、相关段落与证据；定义一图一句图意、面板、关系及最终宽度 | 现有 asset plan + 简短图规格；不重复整篇文献 |
| `manuscript-figure-table-engineer` | 对应图规格、必要来源片段、已取得且许可清楚的素材 | 原生可编辑 SVG、图注、关系/素材记录；不靠效果图新增科学关系 |
| `manuscript-figure-table-reviewer` | 实际 PDF/PNG、图规格、对应来源片段 | 逐图科学/视觉问题及精确位置；未见真实输出不得称看过版面 |

主线程调用确定性工具处理渲染和文件检查。图作者不自行授予独立审图结论；审图者不编辑被评图。每轮仅回传有问题的图/面板和短修复清单。默认一次设计、一次制图、一次审图，局部修复最多两轮；仍有实质问题如实列出并定向解决，不以分数或预算把问题清零。

这不是图越多越好。纯排版重试不重新读论文；图/来源/规则哈希未变时复用已验证输出。每个 agent 只读取该图所需内容。

## 3. 两条绘图路径

**概念/机制图：** 原生 SVG 是可编辑母版；使用语义分组、真实文字、反应箭头与 T 形抑制线。生物组件可以来自许可清楚的矢量库或原创绘制。蛋白轮廓不是结构模型，示意细胞数不是数据，图标不是证据。图像生成可作为可选视觉草稿，不能取代关系核对和最终尺寸检查；默认不用付费 API。

**真实统计图：** 复用现有数据绑定的 Matplotlib/统计渲染路径；保留样本单位、方向、误差、量纲和真实数据。`scientific_figure` 不把概念 SVG 升级为定量结果。

已核查的专用 skills 方法：K-Dense scientific-visualization、scientific-schematics、sai-tv academic-figures、PaperFactory scientific-figure。只吸收适合本地工作的方法，没有安装整套上游库或执行其脚本。特别是目前的 scientific-schematics 为外部 API、PNG-only 路径，不能提供本项目所需的矢量主线。来源对比与许可见本次运行的 `research/scientific-drawing-sources.md`。

## 4. 实际工具

`python -m research_agent_teams.tools.scientific_figure doctor` 检查本地 Python/PyMuPDF/Pillow。当前运行已实际导出三张 SVG/PDF/RGB PNG，不需新增账号、API key 或浏览器软件。

`python -m research_agent_teams.tools.scientific_figure check --run-dir RUN --spec draft/figures/Figure-1.json` 检查本地规格。

`python -m research_agent_teams.tools.scientific_figure render --run-dir RUN --spec draft/figures/Figure-1.json` 只创建新文件，返回真实 v2 asset/receipt 与检查结果。概念图不需要伪造 `numeric_cells` 或结果数字。

`python -m research_agent_teams.tools.journal_render question --run-dir RUN --profile draft/journal-profile.json` 生成要向用户实际发送的期刊问题。收到回答后使用同一模块的 `choose --asked --answer IJMS --render-id final-1 --output draft/journal-choice.json`（同样带 `--run-dir`、`--profile`）；无偏好时省略 `--answer` 并提供 `--reason`。这不是自动提交论文的权限。

最小规格包含：`run_id, asset_id, label, purpose, caption, accessibility_text, svg_source(ref/sha256), source_inputs, claim_refs, relations, artwork, width_mm, dpi, min_font_pt, journal, output_stem`。

- `relations` 仅记录有科学意义的连线：SVG 的普通 `id`、关系类型、reported/proposed/context、相应 claim IDs。
- `artwork` 逐项记录原始文件/sha256、来源URL、作者、许可URL和核验依据；本工具要求非 CC0 素材的 credit 同时出现在图注，并核验其存在。少量已用 CC0 组件与出处缓存于 `resources/scientific-figures/`，无需每轮重新下载整个素材库。
- 内置可处理 CC0、CC BY 4.0、MIT 的明确记录；其他许可需要先完成具体使用场景的许可核查，不能默认免费即任意使用。
- SVG 使用静态安全元素；禁止脚本、外部链接、foreignObject、嵌入远程内容及路径逃逸。基因斜体仅允许静态 `normal/italic/oblique`。
- 当前 PyMuPDF 会忽略部分 SVG dash 样式，因此工具将直线虚线变成明确短线段。曲线/offset 虚线需先作显式分段，不能悄悄画成实线。

## 5. 自动接入最终渲染

图作者在 run 中提供 `draft/scientific-figures.json`：

```json
{
  "journal_profile_ref": "draft/journal-profile.json",
  "journal_choice_ref": "draft/journal-choice.json",
  "figure_specs": ["draft/figures/Figure-1.json", "draft/figures/Figure-2.json"],
  "manifest_ref": "evidence/ANALYZE/scientific-asset-manifest.json"
}
```

`journal_render.prepare_figure_plan` 验证期刊选择，自动导出全部规格中的图、核对实际计划是否全部兑现，并返回当前 `manuscript_asset_manifest/v2`。`manuscript_authoring._analyze_dets` 在有此规格且尚无 manifest 时直接调用它，然后进入现有 source integration/build。重复调用仅在输入、工具、输出均未变时复用；变更后的图使用新的 revision 路径。

已修复 v2 消费接缝：v2 原件保留，SVG/PDF/PNG 的真实来源、字节、所有权和许可逐项核对，按冻结 asset plan 选择主输出。不是把概念图强转成需要数字的旧 v1 记录。

期刊 TeX 模板支持已有安全集合内的、hash-bound 本地 skeleton，三个插槽为 `@@MANUSCRIPT_TITLE@@`、`@@MANUSCRIPT_SECTIONS@@`、`@@MANUSCRIPT_BIBLIOGRAPHY@@`。最后一个插槽填为 `refs`，位于模板自己的 bibliography 命令内。没有扩张 TeX 执行权限；未支持的期刊 class 仍不能执行。IJMS 本次完整交付使用已验证的官方 Word 模板命名样式与同源 PDF 导出，不声称通用安全 TeX builder 已支持所有期刊。

## 6. 检查与停止依据

自动检查：真实文件/哈希、来源/许可、SVG安全、最终物理宽度、实际字体、包含画布外对象的文字边界、RGB、实际像素/有效 DPI、图是否齐全、禁止覆盖原件。600 dpi、8 pt 最小标签是本项目内部设置，不是冒充 IJMS 的强制数值。

人工/模型看图：基因与蛋白、代谢物与催化酶、作用方向、膜内外、物种/组织、观察与推测、箭头端点、文字相碰、图例和图注。自动检查通过时依然返回 `scientific_review: REQUIRED` 和 `visual_review: REQUIRED`。

机制图的关系核对落实到原始实验：蛋白互作不自动证明对某个酶的直接抑制，总组织酶活下降不等同特定酶的纯化活性实验；未直接验证的连线使用虚线并在图注说明。转录调控若以蛋白图标承接，应标明 transcription/expression，避免被读成蛋白催化或直接活化。不同论文报告相同反应，不足以建立基因别名或序列同一性；保留来源命名，核清后才合并。

最后把图放入实际论文再检查一次：图注同页、引用编号、正文边界、有效分辨率与完整文字。正文 PDF/DOCX 必须由同一源生成。保持历史版本，更新交付说明。

正式交付统一放在 `projects/<project>/output/<revision>/`，并更新项目 README；最终链接指向项目内文件。Windows 长路径问题优先用短文件名和 `runs/_render/<revision>/` 临时编译，再核对字节并归回项目。不得默认写到用户 Documents。临时编译稿、历史版本和当前正式稿须有明确区分。

本次真实回归包括：完全越出画布的文字不可悄悄丢失；虚线在输出中必须仍是间断；缺少计划图不能自行声明 CLOSED；无出处/许可、hash漂移、外链/脚本、过小字体、重复输出都不能通过。审美与科学正确性仍由真实审图判断，不由像素或模型自评分替代。
