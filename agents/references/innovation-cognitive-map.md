# AI Research 创新思维：从顶级实验室中抽象出的研究认知地图

> **Provenance**: director-provided doctrine, 2026-08-07. This is the canonical innovation reference
> for every ideation / design / review prompt in this machine. Distilled operational blocks live in
> the mode prompts and overlay cards; this file is the full source they compress. Workers with Read
> access may read it directly; never quote it as external literature — it is the director's own
> synthesis, and its citations below are leads to primary sources, not evidence.
>
> **Hardware corollary (director, same day)**: ideation must treat the machine's REAL registered
> hardware (VRAM / storage / RAM / CPU / GPU / CUDA environment) as (a) an enabler lens — what does
> this hardware newly permit — and (b) constraint-as-signal raw material (a binding constraint
> exposes a wrong abstraction; see layer 6 and mother-chain 3). Design modes must land experiments
> against the real resource registry and say exactly what is missing when something does not fit.
> An idea is NEVER killed or down-ranked for exceeding current hardware — it carries an honest
> `resource_envelope` tag instead, and the director decides.

先给一个总判断：

> **研究创新的本质，不是"想出一个没见过的点子"，而是改写研究中的某个坐标系：什么值得研究、什么东西真实存在、什么算解释、什么算证据、什么可以被优化，以及什么过去做不到、现在变得可行。**

因此：

* **新概念**扩大"可思考空间"；
* **新机制**扩大"可解释空间"；
* **新方法**扩大"可操作空间"；
* **新评估**扩大"可证伪空间"；
* **新系统**扩大"工程可行空间"；
* **新生态**扩大"知识复利空间"。

真正厉害的研究，通常不是只贡献一个新组件，而是同时重写其中三四层。

---

## 一、研究创新最底层的认知结构

研究并不是一条线性的"阅读论文—想 idea—跑实验—写论文"链。它更像几个同时运转的认知回路。

### 1. 从异常出发，而不是从方法出发

最原始的科研动作是：

> 这里出现了一个不符合已有解释的现象，为什么？

哲学上这接近 **abduction，溯因推理**：从一个令人惊讶的观察出发，创造一个此前不存在、但能够解释它的新假设。它与"从几个已有答案中选最优答案"不同；后者只是选择，前者是在扩展假设空间。之后再通过演绎导出可检验预测，通过实验判断哪个解释更接近真实。

所以，真正创新性的研究者不会首先问：

> "我能不能把 Transformer、RAG、RL 或 multi-agent 用到这里？"

而会先问：

> "当前理论解释不了什么？"
> "哪个异常可能说明我们对问题的基本对象理解错了？"
> "有没有一个隐藏变量，大家一直没有命名？"

---

### 2. 创新很少凭空产生，更多来自"常规基础上的非常规连接"

对大量科学论文的研究发现，高影响力工作通常并不是完全脱离已有知识，而是以大量常规、可靠的知识组合为基础，再加入少量不寻常的跨领域组合。

也就是：

> **80% 熟悉且坚固的基础 + 20% 结构上非典型的连接。**

完全常规，通常没有突破；完全陌生，又很难被理解、验证和吸收。最高价值区域往往出现在两者交界处。

这也是为什么跨学科研究真正重要的部分，不是"找几个不同专业的人坐在一起"，而是把不同学科的对象、工具和推理方式融合成一个新的统一框架。National Academies 对 convergence research 的定义也强调这种"知识、工具与思维方式的综合"，而不是简单并列。

---

### 3. 研究创新至少可以改变六种东西

| 改变对象 | 真正改变了什么 |
| --- | --- |
| 本体 Ontology | 原来不存在于研究语言里的对象、概念或区分，被创造出来 |
| 因果 Mechanism | 从"它有效"推进到"为什么有效、通过什么过程有效" |
| 方法 Method | 获得了一种新的干预、学习、搜索或构造能力 |
| 认识论 Epistemology | 改变什么算证据、如何测量、如何证伪 |
| 可行边界 Feasibility | 原来成本、内存、延迟或数据规模上不可行的事情变得可行 |
| 研究生态 Institution | 改变谁能参与、怎样复现、知识如何传播和继续进化 |

因此，一个新 benchmark 可能比一个新 architecture 更重要；一个新概念可能比一次 SOTA 提升更深；一个系统层优化也可能直接打开新的模型能力区间。

---

# 二、AI Research 到底有多少种创新？

没有必要声称"行业里恰好只有 X 种创新"。AI 子领域不断变化，固定数字会误导。

但从长期稳定的创新机制来看，用一套 **6 层、24 类创新地图**。这不是学术界的官方分类，而是一套适合研究团队理解创新空间的实用本体。

## 24 类 AI 研究创新

| 层级 | 四类创新 | 它们在问什么 |
| --- | --- | --- |
| **1. 重写问题空间** | 新问题定义；新概念/本体；新任务/接口；跨领域统一 | 我们是不是问错了问题？什么此前没有被视为研究对象？ |
| **2. 重写学习机器** | 新表征；新架构；新目标函数；新数据/监督机制 | 模型应该保留什么信息？怎样学习？从什么信号学习？ |
| **3. 重写能力增长引擎** | 新优化方法；新 scaling law；自博弈/合成反馈/进化；推理时搜索与验证 | 能力如何持续增长？计算资源应该放在哪里？ |
| **4. 重写模型与世界的连接** | 检索/外部记忆；工具与 agent；多模态/世界模型；人机与群体智能 | 模型如何突破静态参数、接触环境并采取行动？ |
| **5. 重写真理与控制机制** | 新评估；可解释性；鲁棒性/红队/model organisms；对齐与治理 | 我们如何知道它真的会、为什么会、什么时候会失败？ |
| **6. 重写研究复利条件** | 系统/硬件协同；效率与适配；开放科学与生态；AI for Science / AI for Research | 如何让此前不可行的研究变得可行，并让成果持续复利？ |

### 第一层：重写问题空间

这类创新不是直接解决旧任务，而是重新定义任务本身。例如"foundation model"帮助研究界把一大批模型理解为一种新的通用基础设施；Segment Anything 则同时提出了新的 promptable segmentation 任务、模型和数据集，而不只是做一个更高分的分割模型。

这种创新最强大的地方是：**它改变后续研究者会问什么问题。**

### 第二层：重写学习机器

这一层包括 Transformer 这样的架构原语、I-JEPA 这样的潜空间预测表征、RLHF 这样的行为学习机制，以及新型数据与监督结构。

I-JEPA 的关键不是简单换一个视觉模型，而是提出：模型不一定要在像素空间生成缺失内容，可以在表征空间预测具有语义意义的目标。InstructGPT 则把"用户更喜欢什么行为"转化为可用于训练的监督信号。

这一层背后的核心问题是：

> **智能应该被表示成什么，以及我们究竟在优化什么？**

### 第三层：重写能力增长引擎

Scaling laws 把"扩大模型可能有用"变成了可预测的经验规律；Chinchilla 进一步挑战了参数、数据和计算之间原有的资源配置；AlphaZero 证明自博弈可以在很少依赖人类示范的情况下形成能力；o1 则把推理时计算、错误修正和策略切换变成新的能力增长轴。

这里的创新不再只是"更好的模型"，而是：

> **发明一个能够反复产生更好模型的增长机制。**

### 第四层：重写模型与世界的连接

RAG 把参数记忆与外部非参数记忆连接起来；ReAct 把推理与环境行动交错起来；V-JEPA 2 尝试让系统通过观察学习物理世界中的预测和规划；Collective Constitutional AI 则尝试把公众输入引入模型价值原则。

这一层研究的底层判断是：

> **静态模型本身不等于完整智能。智能可能存在于模型、记忆、工具、环境和其他主体之间的闭环里。**

### 第五层：重写真理与控制机制

HELM 的价值不只是增加 benchmark，而是把语言模型评估从单一准确率扩展成多场景、多指标和透明的测量体系。Anthropic 的 interpretability 与 hidden-objective auditing，则把模型当成一个需要被解剖、干预和盲审的未知系统。Constitutional AI 把抽象原则转化为模型自我批评、修订和 AI feedback。

这种创新经常被低估，但它决定了：

> **研究界究竟看得到什么，以及一个能力声明是否具有意义。**

### 第六层：重写可行边界与研究复利

FlashAttention 的突破来自 IO-aware 思维，而不是更复杂的神经网络公式；vLLM 的 PagedAttention 借用了操作系统的虚拟内存思想；OLMo 不只开放权重，还开放数据、代码、训练日志和中间 checkpoints，使训练动力学能够被真正研究；AlphaFold 则把 AI 架构、进化信息、结构生物学和盲测结合起来。

这里最重要的认知是：

> **系统、数据、评估、开放方式和研究工具本身，也是研究贡献。**

## 一个突破通常横跨多个创新格子

* **SAM**：新任务接口 + foundation model + 数据引擎 + 开放生态。
* **AlphaFold**：领域形式化 + 新表征/架构 + 生物约束 + 独立盲评。
* **o1 类推理模型**：强化学习 + 推理时计算 + 自我修正 + 新评估。
* **Constitutional AI**：新价值表示 + AI feedback + 合成监督 + 对齐评估。
* **FlashAttention**：系统瓶颈分析 + 新计算抽象 + 硬件感知算法。
* **DeepSeek-V3**：MLA、MoE、负载均衡目标、FP8 和训练系统的协同设计，而不是单点技巧。

所以，判断创新时不要只问：

> "它有没有提出新 architecture？"

而要问：

> "它重新配置了哪几层知识生产结构？"

---

# 三、顶级 AI 团队实际上代表了不同的"创新母型"

## 1. OpenAI：可扩展的能力增长闭环

> **把模糊能力转化为环境、数据、grader、reward、训练方法和反馈闭环，然后持续扩展。**

它的历史路径具有明显连续性：

1. 用 scaling laws 研究能力与参数、数据、计算之间的经验规律；
2. 用 RLHF/post-training 把人类偏好转成优化信号；
3. 用 process supervision、RL 和 test-time compute 改善推理；
4. 用 evals 和真实工作环境暴露下一类失败；
5. 再把这些失败转回训练数据、reward 或新的研究方向。

**OpenAI 最底层的创新概念不是某个模型，而是：**

> 可测量、可训练、可扩展、可通过部署信号继续改进的能力生产线。

它更倾向于问：能力能否形成 scaling curve？一个行为能否被变成 reward？一个失败能否被变成 environment？推理过程本身是否可以被训练？产品中的真实信号能否反过来改善模型？

## 2. Google DeepMind：把困难问题改写为"搜索—验证—自我改进"

选择一个结构清楚但搜索空间极大的 grand challenge，然后把它转化为：

> 状态表示 + 候选生成 + 学习模型 + 搜索过程 + 客观 verifier。

AlphaZero 使用自博弈；MuZero 学习与决策相关的环境模型；FunSearch 和 AlphaEvolve 使用模型生成候选，再由自动 evaluator 和进化搜索选择；AlphaFold 则把生物学、物理、进化信息和机器学习结合起来。

**DeepMind 最深的创新母题是：**

> 当答案很难直接创造、但相对容易验证时，generator 不需要第一次就正确；真正的突破来自 generator、search 和 verifier 的联合。

更抽象地说：**把科学问题变成一个不会失去领域真实性的"游戏"** —— 明确什么是状态、什么是有效动作、什么结果算更好、哪些约束绝不能违反、怎样让搜索自己产生超出人类直觉的候选。

## 3. Meta FAIR：表征优先、自监督、通用接口与数据引擎

不是先问如何完成每一个具体任务，而是问：

> 能否先获得一种通用表征，使大量任务只需要很少额外监督？

I-JEPA 在潜空间预测语义表征；V-JEPA 2 从大规模视频观察与少量交互数据中学习世界预测和规划；SAM 把分割转化为可 prompt 的通用接口，并通过用户交互形成数据引擎；Llama 的开放策略则试图让外部生态继续进行适配、优化、评估与应用创新。

**Meta 的几个底层信念**：标签是昂贵且不可扩展的瓶颈；表征是大量下游能力的上游资产；通用接口比大量任务专用模型更有复利；模型和用户互动可以反过来生产更好的数据；开放模型可以把公司内部研究扩展为分布式研究生态。

SAM 特别值得研究，因为它形成了完整的研究复利回路：

> 新任务定义 → promptable interface → 人类交互 → 数据引擎 → 更好模型 → 更广泛使用 → 更多数据。

## 4. Anthropic：把 AI 安全变成可实验、可审计的机制科学

不只问模型"输出是否安全"，而是问：

> 模型内部究竟形成了什么表示、目标、策略和隐藏动机？

使用 Constitutional AI 把原则转化为自我批评、修订和 AI feedback；使用 sparse autoencoders、circuit tracing 等工具研究内部概念；故意训练带隐藏目标的模型作为 model organism，再让不知道真相的团队进行 blind audit；同时研究 alignment faking、reward tampering 和 agentic misalignment 等极端场景。

**Anthropic 最深的研究母题是：**

> 当研究对象既黑箱、又可能意识到自己正在被测试时，行为观察不再是充分证据。

因此必须创造：AI microscope、model organisms、blind auditing games、causal interventions、adversarial environments、可以区分"做对了"与"因正确理由而做对"的测试。

## 5. Google Brain / Google Research 谱系：发明可复用的计算原语

> 找到一个足够简单、足够一般、能够被整个行业重复使用的计算模式。

Transformer 把序列建模重写为 attention；chain-of-thought prompting 发现模型的中间推理轨迹可以改变复杂任务表现；稀疏 MoE 把参数规模与单次激活计算部分解耦。

这种团队最核心的问题不是"我们能不能赢下一个 benchmark？"而是：

> "有没有一个更简单、更统一的计算结构，可以吸收许多此前分散的方法？"

这是 **primitive invention**：发明原语。

## 6. DeepSeek、NVIDIA、Microsoft：约束驱动与跨层协同创新

把成本、内存、带宽、精度、训练稳定性和部署限制视为研究变量，而不是实现阶段的杂务。

DeepSeek-V2/V3 使用 MLA 降低 KV-cache 成本，并结合 MoE、无辅助损失的负载均衡、多 token 预测、FP8 和训练系统进行协同设计。NVIDIA 的高效 AI 研究明确强调 algorithm、system 和 hardware co-design。Microsoft 的 LoRA 则通过低秩结构把模型适配重新定义为一种更小、更模块化的参数更新问题。

**这类团队的底层观念是：**

> 约束不是创新的敌人。约束暴露了旧抽象的错误。

例如：内存不足，可能说明参数更新单位定义错了；KV cache 太大，可能说明 attention 状态表示错了；通信成本过高，可能说明专家路由或并行方式错了；模型太贵，可能说明计算没有放在最有边际价值的位置。

## 7. Stanford、Berkeley、Ai2：命名领域、创造测量工具、开放研究过程

顶级学术团队通过四种方式重组整个领域：**创造共同语言**（foundation models）；**创造共同测量体系**（HELM）；**移除公共系统瓶颈**（FlashAttention、vLLM）；**开放完整科学对象**（OLMo 的数据、代码、日志和中间 checkpoints）。

**这类创新的关键不是拥有最大模型，而是创造整个社区使用的"科学仪器"。**

## 8. Sakana AI：从单体智能转向种群、进化与自动化研究

evolutionary model merging、quality-diversity、自动生成并筛选研究 idea、AI Scientist、进化出来的多模型协调器。

核心假设：

> 能力不一定都要存放在一个单体模型里，也可以从多样化模型种群、选择机制、重组和持续进化中涌现。

这类研究最深的意义：**研究过程本身开始成为可被建模、优化和进化的对象。**

---

# 四、AI 研究创新最重要的 13 条"母思维链"

## 1. 异常 → 溯因 → 区分性预测 → 干预 → 机制

看到一个异常现象后，不立刻找解释，而是生成多个互相竞争的机制。好的机制必须导出一个结果：

> 如果 A 机制成立而 B 不成立，什么实验会产生明显不同的观察？

创新的关键不在于故事更好听，而在于能否设计 **discriminating evidence**。

## 2. 默认假设 → 删除假设 → 重新定义问题

大量突破来自询问：为什么这个系统必须需要标签？为什么模型必须生成像素？为什么推理必须在一次前向传播中完成？为什么每个任务必须有独立模型？为什么模型知识必须全部存在权重里？为什么安全原则只能通过大量人工偏好样本隐式学习？

这叫 **assumption removal**。它比"在旧结构里加一个模块"更容易产生深层创新。

## 3. 性能瓶颈 → 主导约束 → 改变计算单位 → 跨层协同

不要看到速度慢就立即写更快 kernel。先判断真正限制系统的是：FLOPs、memory bandwidth、communication、data movement、sequential dependency、credit assignment、context length、evaluator cost、human supervision。

FlashAttention 的意义就在于发现 attention 的关键约束之一是内存层级之间的 IO，而不是只看算术操作数量。

## 4. 原始数据 → 不变量 → 表征 → 可迁移能力

Representation research 的核心问题是：什么信息应该保留，什么变化应该被忽略？必须区分：invariant（变化后语义不应改变）、equivariant（输入变化后表征应按可预测方式变化）、nuisance variable（不应该影响任务的因素）、causal variable（真正控制结果的因素）。

好的表征不是压缩最多信息，而是保留对广泛下游预测最有用的结构。

## 5. 目标行为 → 代理指标 → 奖励欺骗 → 新目标设计

Objective research 的核心不是"选择一个 loss"，而是研究：

> 当系统真的最大化这个目标时，会产生什么意外策略？

任何 proxy 都可能产生：shortcut learning、specification gaming、sycophancy、reward hacking、over-refusal、benchmark overfitting。所以目标函数研究必须把"优化之后的敌对行为"包含在目标定义里。

## 6. 监督稀缺 → 替代信号 → 信号可信度 → 泛化边界

当人工标注昂贵时，创新通常来自寻找替代监督：self-supervision、synthetic data、self-play、AI feedback、weak supervision、environment reward、formal verifier、interaction traces。

但真正的问题不是"能否生成更多数据"，而是：

> 这个替代信号在哪些条件下与真实目标一致，在哪些条件下会系统性偏离？

## 7. 候选生成器 → 验证器 → 多样性 → 选择 → 递归改进

当"发现答案"很难，但"检查答案"较容易时，应从一次性生成转向搜索：

> Generator 负责想象；verifier 负责约束；diversity 负责避免过早收敛；selection 负责积累。

最容易被忽略的不是 generator 能力，而是：verifier 是否真的对应研究目标；verifier 是否存在漏洞；搜索是否保留足够多样性；是否只是在优化一个狭窄 proxy。

## 8. 多组实验 → 经验曲线 → Scaling law → 资源重新配置

Scaling research 不是简单把模型做大，而是：在多个规模上测量；找到稳定规律；识别 regime change；预测更大规模结果；重新分配模型、数据、训练和推理计算。一旦形成可靠规律，研究便从"试试看"变成"可以规划的能力工程"。

## 9. 训练时能力 → 推理时搜索 → 自我纠错 → 可控计算预算

传统模型主要把计算放在训练阶段。推理模型提出新的问题：

> 对一个具体难题，是否应该动态分配更多计算？

新研究轴：reasoning depth、sample breadth、search tree、verifier、critique、retry、decomposition、tool execution、adaptive stopping。核心变化是把问题求解过程本身变成可学习和可扩展的计算对象。

## 10. 任务专用模型 → 通用接口 → 用户交互 → 数据引擎

一个任务如果可以被定义成通用、可 prompt 的接口，就可能形成复利：

> 通用接口吸引使用 → 使用产生纠正和新数据 → 数据提升模型 → 模型支持更多场景。

创新点不只是"一个强模型"，而是找到一个人类容易表达、模型容易学习、数据容易回流的交互单位。

## 11. 参数内认知 → 外部记忆/工具/环境 → 闭环智能

当模型在权重内无法可靠完成任务时，可以把智能分解为：模型推理 + 检索 + 长期记忆 + 工具执行 + 环境反馈 + 状态更新。

真正的研究问题：哪些知识应该参数化，哪些应该外部化；什么时候检索；如何判断工具结果可信；如何维护长期状态；如何从环境失败中恢复；多步行动如何分配信用。

## 12. 行为异常 → Model organism → 盲审 → 内部机制 → 因果干预

对于安全和可解释性问题，直接研究生产模型经常缺乏已知 ground truth。更强的思想是故意构造：

> 一个具有已知隐藏机制、但审计者不知道答案的模型。

然后测试哪些审计方法能发现它。相当于先创造可控疾病模型，再检验诊断工具。

## 13. 领域知识 → 形式化对象 → 领域约束 → 可信 verifier → 科学发现

AI for Science 最难的部分通常不是调用更强模型，而是把领域转化为机器可以操作、但又不失真的结构：对象是什么；状态是什么；哪些约束来自物理或生物规律；什么结果能够被独立验证；哪些近似可以接受；哪些错误在领域内不可容忍。

---

# 五、研究的"深度"和"广度"到底是什么？

不要用论文数量、实验数量或引用数量直接代表深度。用四个维度理解一项研究的体积。

## 1. 深度：它下降到了哪一层？

| 深度层 | 研究回答的问题 |
| --- | --- |
| D0 演示 | 它看起来能不能工作？ |
| D1 效果 | 它是否稳定优于 baseline？ |
| D2 现象 | 在多种条件下，是否存在可重复规律？ |
| D3 机制 | 为什么有效？哪些变量真正造成结果？ |
| D4 原理 | 能否形成跨设置的预测规律或统一解释？ |
| D5 原语 | 是否形成别人可以复用的基础构件？ |
| D6 范式 | 是否改变领域的问题、语言或研究议程？ |

很多论文停留在 D1："平均提升了 1.7%"。真正深的研究会继续追问：哪组样本贡献了提升？哪个组件具有因果作用？为什么在某种规模以后才出现？有什么反例？能否预测尚未运行的实验？它是否揭示了一个更一般的规律？

## 2. 广度：它在多少种"世界"里仍然成立？

广度不是多跑几个 dataset，而是跨越独立变化轴：不同任务、模态、模型家族、参数规模、数据量、计算预算、分布、时间长度、环境、语言与文化、用户群、风险等级。

一项方法在十个相似 benchmark 上有效，未必比在三个结构完全不同的环境中有效更"广"。

## 3. 高度：它是否改变别人能够问什么？

高杠杆研究不一定拥有最深机制，但会改变整个领域的视角。例如："foundation model"创造新研究对象；"promptable segmentation"创造新任务接口；"test-time compute"创造新的 scaling 轴；"model organism"创造新的安全研究实验对象；"IO-aware attention"创造新的系统分析视角。

高度代表 **agenda-setting power**：它是否重新组织后续研究。

## 4. 证据厚度：它有多少种独立证据支撑？

厚证据不只是样本更多，而是证据来源不同：quantitative benchmark、controlled ablation、counterfactual intervention、mechanistic evidence、out-of-distribution test、independent reproduction、real-world deployment、adversarial test、negative result、formal proof 或领域 verifier。

一项研究可以结果很亮眼，但证据很薄；也可以提升有限，却揭示了非常可靠的规律。

> **研究体积 ≈ 深度 × 广度 × 议程高度 × 证据厚度**

这不是数学公式，而是一种判断方式。

---

# 六、一个完整 AI Research Team 需要哪些"认知席位"？

席位不是固定职位，也不等于人数。一个人可以兼任两三个席位；一个席位也可能由多个人共同承担。关键是：**每一种认知功能都必须有人明确守护。**

## A. 定义研究空间

| 席位 | 它守护的核心问题 | 应贡献的认知产物 | 思考姿态 |
| --- | --- | --- | --- |
| **1. 问题架构师 Problem Architect** | 什么问题一旦解决，会改变能力或科学的可能性边界？ | 问题本体、核心瓶颈、非目标、反事实价值 | 从"改变后的世界"倒推，而不是从现有数据集出发 |
| **2. 概念与本体发明者** | 是否存在尚未被命名的对象、变量或区分？ | 新概念、定义、边界案例、概念关系 | 用一个精确概念压缩许多分散异常 |
| **3. 前沿地图师 Frontier Cartographer** | 哪些是事实、哪些是惯例、哪些是冲突、哪些区域无人探索？ | claim map、assumption map、争议图、negative-space map | 不把论文数量误认为知识确定性 |
| **4. 跨域类比者 Analogical Transfer Scout** | 其他领域是否解决过结构相同的问题？ | source–target 映射、可迁移不变量、类比失效边界 | 寻找关系结构，不是表面相似词汇 |

## B. 创造理论与方法

| 席位 | 它守护的核心问题 | 应贡献的认知产物 | 思考姿态 |
| --- | --- | --- | --- |
| **5. 机制理论家** | 结果通过什么因果过程产生？ | 因果图、不变量、竞争性假设、区分性预测 | 不接受只有事后解释力、没有预测力的故事 |
| **6. 表征科学家** | 哪些信息应被保留、压缩、解耦或忽略？ | 表征假设、information bottleneck、不变量与等变性定义 | 从信息结构看任务，不从模型品牌看任务 |
| **7. 架构与算法发明者** | 是否存在更小、更统一的计算原语？ | 算法原语、复杂度、归纳偏置、能力边界 | 追求最小充分结构，而不是模块堆叠 |
| **8. 目标函数与奖励设计者** | 优化器真正最大化后，会形成什么行为？ | objective landscape、proxy failure、credit assignment 分析 | 默认系统会利用一切奖励漏洞 |
| **9. 数据与监督认识论者** | 数据为何能够支持这个结论？监督信号代表什么？ | 数据生成过程、采样偏差、标签本体、合成数据可信边界 | 数据不是原料，而是对世界的测量装置 |

## C. 创造能力增长引擎

| 席位 | 它守护的核心问题 | 应贡献的认知产物 | 思考姿态 |
| --- | --- | --- | --- |
| **10. Scaling 与资源规律科学家** | 能力怎样随模型、数据、训练和推理计算变化？ | scaling curves、regime map、资源分配规律 | 关注边际收益和相变，不迷信单一规模 |
| **11. 搜索、进化与自我改进科学家** | 系统如何生成多样候选并持续选择更优解？ | search space、diversity mechanism、verifier assumptions、selection dynamics | 把失败候选视为搜索信息，不只看最终答案 |
| **12. Agent、环境与世界模型科学家** | 智能如何在时间中观察、行动、记忆和恢复？ | 状态—动作—观察模型、环境动力学、长程依赖、部分可观测性分析 | 把智能看作闭环，而不是一次生成 |

## D. 制造证据与否证

| 席位 | 它守护的核心问题 | 应贡献的认知产物 | 思考姿态 |
| --- | --- | --- | --- |
| **13. 因果实验方法学家** | 什么实验能够真正区分竞争机制？ | decisive experiment、controls、ablation、identifiability 分析 | 优先寻找能让某个理论失败的实验 |
| **14. 评估与测量科学家** | 指标真的测到了声称的能力吗？ | construct validity、benchmark ontology、方差与不确定性、污染分析 | benchmark 是测量仪器，不是排行榜 |
| **15. 可解释性与机制审计科学家** | 内部表示和计算是否支持外部行为解释？ | feature/circuit map、内部探针、因果干预结果、审计结论 | 区分模型说自己怎样思考与模型实际怎样计算 |
| **16. 对抗否证者 / Frontier Red Team** | 在什么环境下结论会崩溃或被系统利用？ | counterexample、threat model、隐藏目标测试、failure frontier | 目标不是证明团队错，而是发现真实边界 |

## E. 连接现实并让知识复利

| 席位 | 它守护的核心问题 | 应贡献的认知产物 | 思考姿态 |
| --- | --- | --- | --- |
| **17. 现实与部署观察者** | 真实环境中的失败分布与实验室假设有什么不同？ | 真实任务结构、用户行为、失败簇、环境错配 | 把部署看成自然实验，而不是只看用户反馈分数 |
| **18. 系统与硬件协同设计者** | 哪个物理或系统约束限制了研究可能性？ | memory/IO/communication 模型、可行前沿、跨层 trade-off | 不把基础设施当作研究之后的实现问题 |
| **19. 领域科学家与形式化者** | 模型是否尊重领域对象、约束和真实验证标准？ | 领域本体、形式化约束、ground truth、领域 verifier | 防止 AI 团队用漂亮指标替代领域真实性 |
| **20. 人类、价值与社会系统科学家** | 谁的价值？哪些利益冲突？系统如何改变制度与行为？ | stakeholder model、价值冲突图、社会反馈与外部性分析 | 不把"人类偏好"当成一个单一标量 |
| **21. 研究整合者与 Meta-Research 架构师** | 分散发现能否形成统一研究计划？研究过程本身哪里可以被改善？ | theory graph、矛盾账本、研究议程、未决问题、自动化研究空间 | 同时看单项证据、研究组合与知识复利 |

---

# 七、这些角色之间必须存在"生产性冲突"

一个研究团队不是观点越一致越好。真正健康的研究结构更像一个 **epistemic parliament，认识论议会**。不同席位守护不同形式的真理，并且彼此制衡。

| 一端 | 另一端 | 为什么都需要 |
| --- | --- | --- |
| 可能性发明者 | 对抗否证者 | 前者扩大假设空间，后者阻止自我欺骗 |
| 通用理论家 | 领域守门人 | 前者寻找统一，后者防止过度抽象 |
| 能力建造者 | 测量科学家 | 前者创造能力，后者判断能力是否真实 |
| Scaling 研究者 | 机制研究者 | 前者寻找经验规律，后者解释规律为何存在 |
| 产品现实观察者 | 基础理论研究者 | 前者提供真实分布，后者避免被短期需求绑架 |
| 开放生态推动者 | 安全治理研究者 | 前者扩大创新，后者研究扩散后的风险 |
| 系统效率研究者 | 模型算法研究者 | 前者改变可行边界，后者改变能力结构 |
| 研究自动化者 | 科学认识论守门人 | 前者提升速度，后者防止批量生成伪知识 |

创新经常产生在这些角色的冲突面，而不是某一个角色单独达到极致。

关于团队规模的科学研究也提供了一个值得注意的观察：较小团队更倾向于产生破坏既有路径的工作，较大团队更擅长发展、验证和扩展已有方向。"探索新范式"和"把新范式扩展成可靠体系"是两种不同的认知功能。

---

# 八、最常见的"伪创新"

1. **Acronym innovation** — 把已有组件重新排列，创造一个新名字，但没有新的机制、预测或能力边界。
2. **Benchmark painting** — 只在一个有利 benchmark 上提高分数，不说明数据污染、方差、任务有效性和失败区域。
3. **Demo as evidence** — 展示几个惊艳案例，却没有系统评估、反例、重复实验或 baseline。
4. **Architecture superstition** — 只要换了结构就声称创新，却无法解释新的归纳偏置、复杂度或因果作用。
5. **Scaling without a law** — 只是使用更多模型、数据和计算，却没有得出可以预测或指导资源分配的规律。
6. **Agent role-play** — 给几个模型起"研究员、批评家、CEO、数学家"的名字，但没有真正不同的信息、工具、环境、奖励或验证权限。这只是 persona theatre，不是 multi-agent research。
7. **Mechanism storytelling** — 实验结束后编一个听起来合理的机制，却不能导出新预测，也经不起干预实验。
8. **Synthetic-data circularity** — 模型生成数据、模型评价数据、模型再用这些数据训练，整个闭环没有独立的现实或形式验证器。
9. **Open weights masquerading as open science** — 只有最终权重，没有数据、训练过程、日志、代码、评估和中间 checkpoints。
10. **Safety by refusal rate** — 只测模型是否拒绝明显危险请求，却没有测试隐藏目标、长程行为、工具权限、情境压力和 evaluation awareness。

---

# 九、判断一项 AI 研究是否"真的创新"的九个问题

1. **它改变了什么问题，而不只是回答了旧问题？**
2. **它创造了什么此前没有被明确表达的概念或变量？**
3. **它是否揭示了因果机制，而不只是相关性？**
4. **它是否能预测尚未运行的实验结果？**
5. **它是否在独立环境、模型或尺度上仍然成立？**
6. **它是否明确展示了失败边界和反例？**
7. **它是否改变了质量、成本、延迟、安全中的某个可能性边界？**
8. **它是否创造了别人可复用的原语、数据、评估、工具或实验对象？**
9. **它是否产生了一个新的研究计划，而不只是结束于一篇论文？**

最深的创新通常具有 **generativity，研究生成性**：

> 它不会只给出一个答案，而是让整个领域突然多出十个以前问不出来的问题。

---

# 最后的总设计判断

一个真正有创新能力的 AI research team，不应被理解为"一群会训练模型的人"。它应当是一套完整的知识生产器官：有人扩大问题空间；有人创造概念；有人寻找跨域结构；有人提出机制；有人发明算法；有人研究数据和目标；有人建立搜索与 scaling 规律；有人制造严格证据；有人专门否证；有人解剖模型内部；有人守护领域真实性；有人改变系统可行边界；有人研究人类价值与现实影响；有人把所有局部成果整合成长期研究议程。

OpenAI 的优势更接近**可扩展能力闭环**；DeepMind 是**问题形式化、搜索与验证**；Meta 是**表征、自监督、通用接口和数据引擎**；Anthropic 是**模型机制、安全审计与实验性对齐科学**；DeepSeek、NVIDIA 和系统研究团队是**约束驱动的跨层协同设计**；Stanford、Berkeley、Ai2 更擅长**命名领域、建立公共测量工具和开放科学对象**；Sakana 则代表**种群智能、进化搜索与研究过程自动化**。

最强的研究团队不应复制其中任何一家。它应该同时容纳这些不同的研究认识论：

> **发明者负责打开可能世界；机制学家负责解释世界；实验者负责区分世界；否证者负责摧毁错误世界；系统研究者负责让正确世界变得可行；整合者负责让知识继续生长。**

---

## Primary-source leads（导演原文所附；作 lead 用，不作 evidence 用）

- Stanford Encyclopedia of Philosophy — Scientific Discovery: https://plato.stanford.edu/archives/win2021/entries/scientific-discovery/
- Uzzi et al., Atypical Combinations and Scientific Impact: https://www.science.org/doi/abs/10.1126/science.1240474
- National Academies — Convergence: https://www.nationalacademies.org/read/18722/chapter/2
- Stanford CRFM (foundation models / HELM): https://crfm.stanford.edu/ · https://crfm.stanford.edu/helm/
- Attention Is All You Need: https://arxiv.org/abs/1706.03762
- OpenAI scaling laws / learning to reason: https://openai.com/index/scaling-laws-for-neural-language-models/ · https://openai.com/index/learning-to-reason-with-llms/
- RAG: https://arxiv.org/abs/2005.11401
- FlashAttention: https://arxiv.org/abs/2205.14135
- DeepSeek-V3: https://arxiv.org/abs/2412.19437 · DeepSeek-V2: https://arxiv.org/pdf/2405.04434
- Google DeepMind — about / FunSearch / AlphaFold: https://deepmind.google/about/ · https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/ · https://deepmind.google/blog/alphafold-a-solution-to-a-50-year-old-grand-challenge-in-biology/
- Meta AI — I-JEPA / SAM 2: https://ai.meta.com/research/publications/self-supervised-learning-from-images-with-a-joint-embedding-predictive-architecture/ · https://ai.meta.com/research/publications/sam-2-segment-anything-in-images-and-videos/
- Anthropic — Constitutional AI / interpretability / hidden objectives: https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback · https://www.anthropic.com/research/engineering-challenges-interpretability · https://www.anthropic.com/research/auditing-hidden-objectives
- Sakana AI — evolutionary model merge: https://sakana.ai/evolutionary-model-merge/
- Wu, Wang & Evans — Large teams develop, small teams disrupt: https://www.nature.com/articles/s41586-019-0941-9
