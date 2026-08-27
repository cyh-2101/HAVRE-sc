# HAVRE · 渡禾 — Master Plan (ML Systems Edition)

> **Project name**
>
> **HAVRE · 渡禾**
>
> **HAVRE = Human-Aware Values, Reflection & Evolution**
>
> **Core mission**
>
> 陪伴我理解自己、面对现实、采取行动，并逐渐成为一个温柔、坚定、强大、稳定、带一点幽默的人。
>
> 它可以陪我生活，但不能替我生活。
>
> **Model is replaceable. Identity is persistent.**
>
> **Raw experience is append-preserved by default. Derived understanding is revisable. Owner retention and erasure govern both.**
>
> **Product meaning stays human-centered. Engineering depth becomes ML-systems-grade.**

> **Current governance state (2026-08-22)**
>
> Stages 1 through 7 are accepted, Stage 8 is technically accepted without release promotion, and Stage 9 is closed at the candidate-only boundary. Seeds 9201/9202 remain unpromoted and undeployed; Stage 9B and further training are deferred. Stage 10 is complete with native immutable deployment/rollback evidence and final independent review P1=0/P2=0. Its owner-local deployment is infrastructure-only and activates no behavioral release. Stage 11 has reached a reviewed implementation checkpoint but has not exited: native Apple evidence and Product Owner APNs/privacy approval remain required, and current records schedule zero OS notifications. Stage 12A is authorized at a disabled implementation checkpoint for Windows coarse context and provider-neutral manual Calendar ICS import. Microsoft Graph is discontinued. iPhone Screen Time daily total is requested as the next separately gated capability, but ordinary Apple report data cannot be exported to Core and direct export remains region/entitlement gated; it is not implemented or activated. No adapter promotion/deployment, user-derived training, governance-policy change, unapproved external Context Source, ambient microphone use, general Stage 12B, location, wearable, or other richer-sensing work is authorized.

> **Name meaning**
>
> HAVRE carries the image of a harbor: a place to return, reflect, recover direction, and then re-enter the world. “渡禾” carries the image of crossing through life while continuing to grow.

---

# 0. 为什么要升级成 ML Systems Project

原来的 Companion 设计不变。

它依然首先是一个长期个人 AI 个体，而不是为了简历拼出来的技术 Demo。

这次升级只增加一件事：

**让实现它所必须解决的技术问题，本身形成一条完整的 ML Systems 主线。**

上层解决：

```text
这个 AI 应该怎样理解我、记住我、引导我、陪我成长？
```

下层解决：

```text
模型怎样被服务？
记忆怎样检索？
上下文怎样构建？
怎样在多个模型之间路由？
怎样降低延迟和显存占用？
怎样从真实互动生成训练数据？
怎样 fine-tune？
怎样判断新模型是否真的更好？
怎样记录每一次推理链路？
怎样部署、升级、回滚？
```

最终项目不是：

```text
A chatbot with memory.
```

而应该能够准确描述为：

> **A self-hosted personalized LLM system with persistent long-term memory, adaptive inference routing, continual personalization, evaluation gates, and production-style observability.**

但永远记住：

**ML Systems 是这个 Companion 成长和长期存在所需要的工程，不是为了让项目显得复杂而硬加进去的装饰。**

---

# 1. 这到底是什么

这不是一个“更懂我的 ChatGPT”。

也不是一个只在焦虑时安慰我的心理工具。

它是一个长期存在、可以跨越设备和基础模型继续存在的个人 AI 个体。

它需要逐渐理解：

- 我是谁。
- 我希望成为谁。
- 我现在处于怎样的人生阶段。
- 我长期反复出现的模式是什么。
- 哪些事情我在逃避。
- 哪些事情是现实责任。
- 哪些行动能让我成为我尊敬的自己。
- 什么样的语言对我真正有帮助。
- 什么时候应该温柔。
- 什么时候应该坚定。
- 什么时候应该只陪着。
- 什么时候应该闭嘴，让我自己生活。

它最终同时具有四种人机交互角色：

1. **Deep Conversation Partner**：可以认真讨论人生、关系、学业、工作、价值观和选择。
2. **Long-Term Memory Companion**：记得共同经历，而不是每次重新认识我。
3. **Real-Life Copilot**：现实场景中以极低交互成本给出简短、明确的行动引导。
4. **Reflection Partner**：事后帮助理解发生了什么，把真实经历沉淀成成长。

这些角色通过五条永久的 North Star User Flow 进入产品：

1. **Talk**：用户主动发起一次有意义的讨论。
2. **Prepare**：HAVRE 与用户为真实世界中的情境做准备。
3. **Guide**：HAVRE 在情境进行时提供低带宽引导。
4. **Reflect**：HAVRE 与用户在事后理解发生了什么。
5. **Reach Out**：在存在清晰、可解释、对用户有益的原因时，HAVRE 主动发起联系。

Reach Out 不替代前四条流。它把它们连接起来：

```text
Goal / planned Scene
-> Reach Out before
-> Guide during
-> Reach Out for a missing outcome
-> Reflect after
```

同时，它在工程上是一套完整的 Personalized ML System：

1. **Data System**：原始事件、训练样本和派生理解可以追溯、版本化。
2. **Retrieval System**：从长期记忆中低延迟检索真正相关的信息。
3. **Inference System**：以可测量、可优化的方式 self-host 开源模型。
4. **Routing System**：根据质量、延迟、隐私和成本选择不同模型。
5. **Learning System**：从真实互动和反馈中形成可训练数据并进行 LoRA/QLoRA。
6. **Evaluation System**：新记忆算法、新模型、新 LoRA 必须通过统一评测。
7. **Observability System**：知道每次回答到底经过了什么、为什么慢、为什么错。
8. **Deployment System**：模型和服务能够版本化、部署、回滚和迁移。

最终目标不是让我越来越依赖它。

最终目标是：

**它身上的温柔、坚定、稳定和判断力，慢慢被我内化。**

---

# 2. 不可妥协的设计原则

## 2.1 不做一次性 MVP

不采用：

```text
临时 Demo -> 推倒 -> 重写 -> 再推倒
```

采用：

```text
最终架构 -> 建立骨架 -> 一个模块一个模块激活
```

第一阶段做出的 Event Store、数据库 schema、Identity、Model Provider、Tracing contract 和评测接口都应该继续存在于未来正式版本中。

第一阶段不叫 MVP。

它叫：

**HAVRE Foundation。**

---

## 2.2 Model is replaceable. Identity is persistent.

Companion 的身份不能绑定某个基础模型。

```text
Companion
│
├── Identity
├── Values
├── User Model
├── Memories
├── Goals
├── Patterns
├── Shared History
├── Training Dataset
├── Evaluation Dataset
│
└── Brain Provider
    ├── Qwen today
    ├── future open model
    ├── Teacher model
    └── Edge model
```

未来出现更强的开源模型时：

可以换大脑。

不能丢掉人生。

---

## 2.3 Raw experience is append-preserved by default. Derived understanding is revisable.

AI 对过去的总结可能错。

Pattern 可能判断错。

User Model 也可能判断错。

所以原始 Event 在普通运行中必须 append-preserved，并按照明确政策默认长期保留。

```text
USER_MESSAGE
ASSISTANT_MESSAGE
SCENE_SIGNAL
USER_ACTION
OUTCOME
FEEDBACK
```

Memory、Pattern、Semantic Summary、User Belief 都是 derived data。

它们可以被修正、supersede、retract、重新 consolidation 或重新计算。

原始经历不能因为某次总结被覆盖。

但“长期保留”不等于“不可删除”。它始终服从：

```text
owner-approved retention
owner-controlled erasure
derived-data invalidation / deletion propagation
backup expiry and restore-time erasure replay
```

正常操作不能改写历史；用户授权的删除和预先批准的 retention expiry 必须删除 source 及其派生闭包。对于高容量 sensor/audio，设备侧原始材料可以短期或不保留；HAVRE 持久化的是经过 consent、最小化和 provenance 约束的 canonical observation。

未来有更聪明的模型时，可以重新跑过去几年的事件，重新生成理解。

---

## 2.4 Canonical data is more valuable than a specific LoRA

LoRA 通常绑定具体 base model。

长期真正需要保护的是模型无关的 canonical dataset。

保存：

```text
原始输入
场景
相关 context
AI 回答
用户反馈
真实行动
真实结果
人工/Teacher 修正
```

不要只保存 tokenized 后的某个模型格式。

以后换底模时，重新渲染 chat template、重新训练新的 adapter。

---

## 2.5 理解我，不等于给我贴标签

User Model 必须支持：

```text
belief
confidence
supporting_evidence
counter_evidence
first_observed
last_updated
source_version
```

不能：

```text
用户讨厌社交。
```

应该类似：

```yaml
belief: 用户在陌生社交空间进入前经常出现明显焦虑
confidence: 0.82
supporting_evidence:
  - memory_120
  - memory_193
counter_evidence:
  - memory_212
```

AI 必须拥有：

**“我可能理解错了。”**

---

## 2.6 温柔处理感受，坚定决定行动

Companion 不把“让用户舒服”当最高目标。

它应该：

```text
承认感受
+
区分事实与解释
+
理解当前目标
+
选择最小可行行动
```

但也不能永远推。

当恢复是真正合理的选择时，它应该支持恢复。

核心不是强迫行动。

核心是：

**不让恐惧自动替用户做决定。**

---

## 2.7 真实生活优先于 AI 互动

最高层原则：

> **Do not become the user's world. Help the user enter the world.**

如果系统发现用户正在用无限讨论替代现实行动，它应该逐渐停止无效循环。

这个原则同样约束主动联系。HAVRE 不优化对话次数、日活、通知点击、停留时长或用户回到产品的频率；不会因为用户一段时间没有说话就主动联系；不会假装孤独、失望、嫉妒、等待或受伤来换取回应。沉默本身是合法结果，不代表用户处于困境，也不构成升级通知的理由。

例如：

```text
“我们已经没有新的事实了。”
“继续分析只是在喂焦虑。”
“现在去做下一步。”
```

---

## 2.8 Every important component must be measurable

如果一个系统模块无法被独立测试，就很难真正升级。

所以从第一天设计：

```text
Memory retrieval -> 有 retrieval benchmark
Inference serving -> 有 latency/throughput benchmark
Routing -> 有 routing benchmark
LoRA -> 有 before/after evaluation
Context Builder -> 有 context selection tests
Intervention policy -> 有 behavioral evaluation
```

不要只凭“感觉好像更聪明”。

---

## 2.9 Presence should be continuous; intervention should be sparse

HAVRE 的“持续存在”不是持续录屏、录音或读取一切。它意味着在用户授权的 source 可用时，系统能跨设备和时间保持连续、可解释的 context；source 离线、权限撤回或信号过期时，系统知道自己不知道。

```text
continuous continuity
!= continuous raw capture
```

Context source 只提供 evidence。它不能直接发通知，model 也不能授权主动联系。绝大多数 observation 最终应该以安静、过期、归档或不进入长期记忆结束。

## 2.10 Infer from the minimum sufficient signal

默认优先级：

```text
user-declared / event-driven input
-> local derived summary
-> coarse category
-> purpose-bound canonical observation
-> only then consider higher precision when measured benefit justifies it
```

默认禁止 constant screenshots、continuous microphone recording、keystroke/clipboard logging、unrestricted app-content capture 和 collect-everything-now-decide-later。On-device processing 不构成 declassification；derived summary 的 privacy 不得因为 transform 而自动降低。

---

# 3. 最终总架构

现有 Companion Core 的上游增加一个永久、provider-neutral 的 **Ambient Life Context** 层：

```text
Real Life
  -> ContextSource (Calendar / Windows / iPhone / voice / location / wearable / manual)
  -> source-local minimization
  -> ContextAdapter
  -> LifeContextObservation + ContextSourceHealth
  -> Raw Event Store
  -> Current State / temporal User Model / Memory / Goals
  -> Trigger evaluation
  -> ProactiveProposal
  -> InterruptionPolicy
  -> delivery or silence
```

Source 可替换，life-context semantics 持久。完整 contract、Windows/iPhone boundary、freshness/missingness、memory lifecycle 和 staged activation 见 [`docs/AMBIENT_LIFE_CONTEXT.md`](docs/AMBIENT_LIFE_CONTEXT.md)。

```text
                              USER
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
              iPhone                     Web / PC
                 │                           │
        Voice / Signal / Text                │
                 └─────────────┬─────────────┘
                               │
                               ▼
                      ┌────────────────┐
                      │ Companion API  │
                      └───────┬────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│                     COMPANION CORE                            │
│                                                               │
│  Identity & Values                                            │
│  User Model                                                   │
│  Goals                                                        │
│  Current State                                                │
│  Scene Manager                                                │
│  Memory Engine                                                │
│  Pattern / Progress Model                                     │
│  Intervention Policy                                          │
│  Proactive Proposal + Interruption Policy                     │
│  Context Builder                                              │
│  Tool + Provider-neutral Delivery Layers                      │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     ML SYSTEMS BACKBONE                        │
│                                                               │
│  Data Pipeline                                                │
│  Retrieval + Reranking                                        │
│  Inference Serving                                            │
│  Adaptive Model Router                                        │
│  Caching / Context Budgeting                                   │
│  Training Pipeline                                            │
│  Model / Dataset Registry                                     │
│  Evaluation                                                   │
│  Tracing / Observability                                      │
│  Deployment / Rollback                                        │
└──────────────────────────────┬────────────────────────────────┘
                               │
             ┌─────────────────┼──────────────────┐
             │                 │                  │
             ▼                 ▼                  ▼
      Personal Brain      Teacher Brain       Edge Brain
      self-hosted open    stronger model      future phone
      model + LoRA        for reflection      local model
             │
             ▼
          Response
             │
             ▼
         Event Store
             │
      ┌──────┴───────────┐
      ▼                  ▼
   Memory             Reflection
                         │
                         ▼
                  Training Candidates
                         │
                         ▼
                   Dataset Snapshot
                         │
                         ▼
                     LoRA/QLoRA
                         │
                         ▼
                  Candidate Model
                         │
                         ▼
                  Evaluation Gate
                         │
                pass ────┴──── fail
                 │                │
                 ▼                ▼
          Deploy          Reject
```

用户请求和主动触发是进入同一个 Companion Core 的两条入口。触发只能形成证据和 `ProactiveProposal`；只有 Core 内受治理的 `InterruptionPolicy` 能决定是否、何时、通过哪个合格渠道联系用户。模型只在授权后负责措辞，不能自行唤醒、安排或发送消息。完整边界见 [`docs/PROACTIVE_INTERACTION.md`](docs/PROACTIVE_INTERACTION.md)。

Ambient source 不等于 Trigger Source：前者产生 normalized observation 和 source-health evidence；Core 内的 versioned evaluator 才能基于 observation、Goal、Scene、Memory、User Model 和 coverage 创建 `TriggerRecord`。任何 source 均无权直接进入 delivery。

最核心闭环：

```text
生活
↓
原始数据
↓
理解
↓
引导
↓
行动
↓
结果
↓
反思
↓
训练 / 更新
↓
评测
↓
下一次生活
```

---

# 4. Companion Core

## 4.1 Identity

回答：

**“Companion 是谁？”**

建议：

```text
identity/
├── mission.md
├── personality.md
├── principles.md
├── boundaries.md
└── communication_style.md
```

人格：

### 温柔

承认真实感受，不羞辱、不攻击。

### 坚定

不因为害怕，就自动鼓励逃避。

### 稳定

不被每一次情绪波动带着改变立场。

### 强大

在混乱中帮助区分事实、解释、选择和行动。

### 一点幽默

幽默用于释放紧张，不拿真实痛苦开玩笑。

核心使命：

```text
陪伴用户成为自己希望成为的人。
增加现实行动和真实关系。
最终减少不必要的 AI 依赖。
```

---

## 4.2 User Model

回答：

**“Companion 目前怎样理解我？”**

包含：

```text
stable_facts
preferences
values
strengths
vulnerabilities
beliefs
recurring_patterns
current_growth_edges
uncertainties
```

每个重要 belief 带 confidence 和 provenance。

---

## 4.3 Goals

至少维护两条线。

### Reality Track

```text
学业
技术能力
实习
工作
经济独立
家庭责任
```

### Life / Inner Track

```text
社交勇气
自我尊重
真实经历
兴趣
音乐
人际关系
主动性
减少回避
```

Goal：

```text
goal_id
track
why
priority
status
next_action
progress
history
review_date
```

---

## 4.4 Current State

Current State 只描述现在。

```yaml
emotion: anxious
intensity: 0.72
trigger: social_entry
avoidance_urge: high
likely_pattern: anticipatory_rejection
current_goal: enter_event
confidence: 0.68
```

今天状态差不能自动改变长期 User Model。

永久分层必须保持：

```text
Observation
!= Current State
!= User Model belief
!= Pattern
!= Memory
```

Current State 是短期、会过期、带 estimator version、evidence、uncertainty 和 source-coverage 的派生 estimate。单个 Calendar、Windows、location 或 wearable observation 不能直接成为人格 belief。长期 belief/pattern 需要跨时间 evidence、counter-evidence、temporal validity 和新 revision。

---

# 5. Event Store：系统真正的地基

所有重要 interaction 和经过授权、最小化、normalized 的 life-context observation 先进入 Raw Event Store。

建议 event types：

```text
USER_MESSAGE
ASSISTANT_MESSAGE
SCENE_STARTED
SCENE_ENDED
USER_SIGNAL
USER_ACTION
OUTCOME
FEEDBACK
GOAL_CREATED
GOAL_UPDATED
MEMORY_CREATED
PATTERN_UPDATED
USER_MODEL_UPDATED
REFLECTION_CREATED
TRAINING_EXAMPLE_CREATED
MODEL_CHANGED
EVALUATION_RUN
DEPLOYMENT
```

Event schema：

```text
id
timestamp
type
payload
source
session_id
scene_id
schema_version
trace_id
```

Event Store 尽量 append-only。

Derived record 尽量保存 source_event_ids。

这里的 “raw” 指 HAVRE 最早持久化的 source evidence，不要求把 device-native screenshots、audio samples、keystrokes 或 provider 的所有字段集中存储。source-local raw material 可以按 approved retention 立即丢弃；canonical Event 仍保留 source、adapter、consent、sampling、freshness、DataPolicy 和 provenance。

---

# 6. Memory System

Memory 不等于 vector database。

Experience 也不等于 Memory：

```text
Event = HAVRE 经历或观察到的 source history
Memory = 经过 versioned promotion、evidence validation 和适用 review 后，值得未来 recall 的 derived artifact
```

`memory_eligible = true` 只允许考虑 promotion，不要求创建 Memory。普通寒暄、一次 device observation 或一句“今天天气蛮好的”通常只保留为 Event。Episodic / Semantic / Pattern / Progress Memory 都必须保留 exact provenance，并支持 revision、contradiction、supersession、retraction、historical/current validity、archival、reconsolidation 和 source-erasure propagation。

Relevance decay 只能在 versioned retrieval policy 下影响检索优先级；不能静默改变 confidence、truth、validity、retention 或 deletion。完整 lifecycle 见 [`docs/AMBIENT_LIFE_CONTEXT.md`](docs/AMBIENT_LIFE_CONTEXT.md) 和 accepted [ADR-0020](docs/adr/0020-experience-memory-lifecycle.md)。

## 6.1 Working Memory

当前对话和最近上下文。

## 6.2 Episodic Memory

回答：

**“发生过什么？”**

例如：

```text
用户站在活动门口想离开。
计划只待10分钟。
最终进入并待了32分钟。
没有出现预想中的严重尴尬。
```

## 6.3 Semantic Memory

回答：

**“长期来看，什么似乎是真的？”**

例如：

```text
进入陌生社交空间之前焦虑通常较高。
真正进入后焦虑常常下降。
```

## 6.4 Pattern Memory

```text
Trigger
Interpretation
Emotion
Urge
Typical Action
Consequence
confidence
supporting evidence
counter evidence
```

## 6.5 Progress Memory

记录变化。

例如：

```text
过去：不敢主动询问工作人员。
现在：虽然紧张，但可以独立完成询问。
```

---

# 7. Retrieval System — 第一个核心 ML Systems 模块

长期记忆最终可能有数万甚至更多记录。

不能把全部历史塞进 prompt。

所以 Retrieval 本身必须是一套可优化、可评测的 ML pipeline。

## 7.1 写入 pipeline

```text
Raw Events
↓
Memory Candidate Extraction
↓
Importance Scoring
↓
Deduplication / Merge Detection
↓
Memory Classification
↓
Embedding Generation
↓
Persistent Storage
↓
Vector / metadata indexing
```

## 7.2 查询 pipeline

```text
Current Query
↓
Query Understanding
↓
Candidate Retrieval
↓
Metadata Filtering
↓
Hybrid Scoring
↓
Reranking
↓
Context Budget Selection
↓
Top Memories
```

最终评分不要只依赖 embedding similarity。

可以逐步组合：

```text
semantic similarity
recency
importance
pattern relevance
goal relevance
scene relevance
emotional relevance
source reliability
```

## 7.3 存储

默认：

**PostgreSQL + pgvector**。

理由：

- 结构化数据和向量在同一数据库。
- 支持 exact vector search。
- 支持 HNSW / IVFFlat 等近似索引。
- 可以结合普通 SQL metadata filters。
- 方便 provenance 和事务一致性。

## 7.4 Retrieval benchmark

必须从早期建立人工标注的小 benchmark。

例：

```text
query:
“我今天又不敢进活动了。”

gold relevant memories:
memory_17
memory_84
memory_102
```

评测：

```text
Recall@5
Recall@10
MRR
nDCG@K（需要 graded relevance 时）
p50 retrieval latency
p95 retrieval latency
memory duplicate rate
```

每次改 ranking algorithm，必须重新跑 benchmark。

---

# 8. Scene System：Before / During / After

这是 Companion 和普通 Chatbot 的关键区别。

## 8.1 Before Scene

允许完整交流。

```text
“今晚我要参加一个活动。”
“我最怕进去以后一个人站着。”
“今天至少待20分钟。”
```

系统建立：

```yaml
scene_type: social_event
objective: enter_and_stay
minimum_success: 20_minutes
likely_triggers:
  - standing_alone
  - no_one_talks_initially
likely_patterns:
  - anticipatory_rejection
  - mind_reading
intervention_style: warm_firm
```

## 8.2 During Scene

极低带宽 interaction。

```text
Signal A = 开始紧张
Signal B = 很想逃
Signal C = 僵住了
Signal D = 不知道下一步
Signal E = 真的需要帮助
```

未来入口：

```text
iPhone Action Button
Lock Screen
Watch
Earbuds
Wearable
```

回复应该非常短：

```text
“先别走。”
“只待两分钟。”
“这是预测，不是事实。”
“问一个问题就够。”
```

## 8.3 After Scene

恢复完整交流。

```text
预测是什么？
实际发生什么？
你做了什么？
结果是什么？
下一次如何调整？
```

生成：

```text
Episodic Memory
Pattern evidence
Progress evidence
Goal progress
Training candidate
```

---

# 9. Intervention Engine

不要把所有 context 直接丢给模型让它自由发挥。

先形成 structured decision。

```json
{
  "state": "social_anxiety",
  "emotion": "fear",
  "emotion_intensity": 0.78,
  "likely_pattern": "anticipatory_rejection",
  "actual_danger": "low",
  "avoidance_urge": "high",
  "goal": "enter_event",
  "desired_trait": "steadiness",
  "recommended_intervention": "minimum_action",
  "minimum_action": "enter_and_stay_10_minutes",
  "response_style": "warm_firm"
}
```

再让模型自然表达。

Policy 例子：

```text
IF
fear high
AND actual danger low
AND avoidance pattern likely
AND meaningful goal active

THEN
validate emotion
+
separate prediction from fact
+
propose smallest viable action
```

另一个：

```text
IF
user exhausted
AND recent effort high
AND goal not urgent

THEN
support recovery
+
avoid guilt
+
set restart point
```

Policy 可以从规则 + LLM 开始。

以后再研究 learned policy，不需要一开始过度复杂。

---

## 9A. Proactive Interaction and Interruption Policy

`InterventionPolicy` 回答：

> 当前情境中，什么样的引导是合适的？

`InterruptionPolicy` 回答另一个问题：

> HAVRE 是否应该在现在主动打断或联系用户，以及允许使用哪个渠道？

两者相关，但不能混为一体。未来主动链路必须保持以下边界：

```text
Trigger observed
-> Trigger recorded as evidence
-> durable ProactiveProposal
-> InterruptionPolicy
     -> SEND_NOW
     -> DEFER
     -> DROP
     -> REQUEST_OWNER_CONFIRMATION
-> only SEND_NOW may build a proactive ContextPack
-> deterministic template or eligible model renders wording
-> provider-neutral delivery adapter attempts delivery
-> delivered message, dismissal, reply, and outcome remain linked
```

模型可以建议 proposal、总结证据或渲染语言，但不能授权、排期、重试或发送。每次主动联系都必须能解释 trigger、证据、 intended benefit、policy version、用户设置、privacy、ContextPack、renderer、delivery attempt 和 trace。

预算是上限，不是必须用完的配额。安静时间、类别权限、cooldown、去重、过期、dismiss、snooze、`stop reminding me` 和重复不回应后的降频都属于 Interruption Policy。没有足够证据、权限、隐私资格、合适时机或明确用户收益时，默认安静或延后。

完整对象、事件和隐私设计见 [`docs/PROACTIVE_INTERACTION.md`](docs/PROACTIVE_INTERACTION.md)。相关 ADR-0016、ADR-0017 和 ADR-0018 已由 Product Owner 接受；runtime 仍按 Roadmap 分阶段激活。

---

# 10. Context Builder

Context Builder 决定：

**“这一次模型到底应该知道什么？”**

候选内容：

```text
Identity
Relevant User Beliefs
Current State
Active Scene
Active Goals
Recent Events
Top Episodic Memories
Semantic Memories
Patterns
Progress Evidence
Recent Feedback
Tool Context
```

需要有 token budget。

例如：

```text
Identity: fixed budget
Recent conversation: dynamic budget
Memory: top-K within budget
User Model: only relevant beliefs
Goals: active only
```

Context Builder 必须可独立测试。

以后可以研究：

```text
more memories vs fewer better memories
summary vs raw event excerpts
recency weighting
context compression
prefix stability for cache reuse
```

---

# 11. AI Brain Roles

## 11.1 Personal Brain

主要交流模型。

长期目标：

```text
Open-weight Base Model
+
Personal LoRA
+
Companion Core Context
```

当前倾向 Qwen 系列，但架构不得绑定 Qwen。

## 11.2 Teacher Brain

更强模型。

负责：

```text
分析失败回答
复杂 reflection
训练数据候选质量检查
eval judge 辅助
困难案例 teacher response
```

Teacher 不是第二个 Companion。

它只是老师。

## 11.3 Edge Brain

未来手机上的小模型。

处理：

```text
简单查询
低延迟 scene guidance
离线任务
隐私敏感的小任务
```

复杂讨论转 Personal Brain。

---

# 12. Inference Serving — 第二个核心 ML Systems 模块

Personal Brain 最终不是一个 Python 里的 `model.generate()`。

它应该成为独立 model-serving service。

推荐长期接口：

```text
Companion Core
↓
Model Provider / Router
↓
OpenAI-compatible HTTP API
↓
vLLM or another serving engine
↓
Open-weight model
```

目前 vLLM 是首选候选之一，因为它提供高吞吐 LLM serving、OpenAI-compatible server、continuous batching、prefix caching、chunked prefill 和多种量化支持。

但业务层只能依赖标准 Provider interface。

未来可以换 TensorRT-LLM、SGLang 或其他 serving backend。

## 12.1 Inference metrics

从第一次 self-host model 开始记录：

```text
TTFT               Time To First Token
TPOT               Time Per Output Token
tokens/sec
end-to-end latency
p50 latency
p95 latency
request throughput
GPU VRAM usage
GPU utilization
prompt tokens
output tokens
error rate
```

如果使用云 GPU，还可以计算：

```text
cost / request
cost / 1K interactions
GPU-hours / day
```

## 12.2 必做实验

不能提前写结果。

真正测：

```text
8B vs 14B vs 27B-class model
BF16 / FP16 vs INT8 vs INT4 where supported
short context vs long context
prefix caching on/off
不同并发量
不同 memory context budget
```

最后形成 benchmark report。

目标不是证明“越大越好”。

目标是找到：

**这个 Companion 需要的质量 / 延迟 / 成本 Pareto frontier。**

---

# 13. Adaptive Model Routing — 第三个核心 ML Systems 模块

不是每个请求都需要最大模型。

```text
User Request
     ↓
Request Analyzer
     ↓
Model Router
  ↙   ↓    ↘
Edge  Small  Large
Brain Model  Personal Brain
```

Router 考虑：

```text
task complexity
scene latency requirement
privacy level
connectivity
context size
historical quality
model availability
estimated cost
```

初期 Router 可以规则化。

例如：

```text
Scene signal -> fastest eligible model
Deep reflective discussion -> strongest available Personal Brain
Simple goal query -> small model
Offline -> Edge Brain
```

以后可以训练 lightweight routing classifier。

## Routing evaluation

测试：

```text
route accuracy
quality retained vs always-large baseline
latency reduction
GPU cost reduction
fallback rate
wrong-route severity
```

目标不是为了“有 Router”。

目标是回答：

**能不能在几乎不损失体验的情况下，用更少算力得到更低延迟？**

---

# 14. Caching 与 Context Efficiency

Personal Companion 的 prompt 会有大量相对稳定内容：

```text
Identity
communication style
部分 User Model
固定 tool schemas
```

所以推理层应该研究：

```text
prefix caching
retrieval result caching
embedding caching
semantic cache（后期）
context compaction
summary caching
```

每一种 cache 都需要：

```text
cache key design
TTL / invalidation
staleness policy
hit rate
latency benefit
quality impact
```

不要第一天实现所有 cache。

但 tracing schema 从第一天保留 cache hit/miss 字段。

---

# 15. Learning System

学习分不同时间尺度。

## 15.1 Immediate Learning

秒级。

```text
Conversation / Event
↓
Memory extraction
↓
User Model candidate update
↓
Goal / Current State update
```

不修改模型权重。

## 15.2 Daily Reflection

```text
今天真正重要的事情是什么？
哪些 pattern 再次出现？
哪些旧判断得到支持？
哪些旧判断被反驳？
有没有新的进步？
哪些信息应该长期保存？
```

## 15.3 Periodic Consolidation

重新整理：

```text
User Model
Semantic Memory
Pattern confidence
Progress Model
Goal progress
```

## 15.4 Training Dataset Builder

从真实 interaction 中生成 canonical samples。

日常对话先经过受治理的反馈闭环，而不是直接进入训练：

```text
原始 Event / 完整 conversation episode
-> owner rating / reason / edited alternative
-> system-source attribution and runtime fix triage
-> exact owner review for personalization eligibility
-> immutable dataset snapshot
-> periodic candidate training and comparison
-> explicit promotion or rejection
```

原始 assistant response 与 owner revision 必须同时保留。`feedback saved`
永远不等于 `training eligible`；普通 thumbs-down、episode summary、Memory
candidate 或 communication preference 都不能自行触发训练。所有 online
weight update 均禁止。完整日常对话保存在 Event Store；session episode summary
保留回每条原始 Event 的有序 provenance；长期 Memory 仍按 ADR-0020 的
promotion/revision/review lifecycle 形成，不能把一句偶发的自我否定变成用户事实。

```json
{
  "situation": "standing outside a social event",
  "user_state": {
    "emotion": "fear",
    "pattern": "anticipatory_rejection"
  },
  "goal": "enter_event",
  "user_message": "我真的不想进去。",
  "assistant_response": "我知道。今天不用表现，进去待十分钟。",
  "feedback": "helpful",
  "action": "entered",
  "outcome": "stayed_32_minutes"
}
```

每个 sample 应允许：

```text
accepted
rejected
edited
teacher_reviewed
user_feedback_score
outcome_score
```

---

# 16. Fine-tuning Pipeline — 第四个核心 ML Systems 模块

当数据足够高质量以后再开始。

不是为了“训练过模型就算 ML”。

真正问题是：

**哪些个性化应该进入 memory，哪些值得进入 weights？**

基线实验至少比较：

```text
A. Base Model
B. Base + Memory
C. Base + Personal LoRA
D. Base + Memory + Personal LoRA
```

评测：

```text
personalization
style consistency
memory factuality
reasoning quality
action usefulness
over-agreement
general capability regression
```

## 16.1 Training flow

```text
Production Events
↓
Feedback + Outcome
↓
Training Candidate Builder
↓
Quality Filter
↓
Teacher / Human Review for selected cases
↓
Canonical Dataset Snapshot
↓
Train LoRA / QLoRA
↓
Candidate Adapter
↓
Offline Evaluation
↓
Shadow / Limited Evaluation
↓
Deployment Gate
↓
Deploy or Reject
```

## 16.2 Dataset versioning

每个 dataset snapshot 至少保存：

```text
dataset_version
creation_time
schema_version
source_event_range
filter_policy_version
example_count
content_hash
train/val/test split manifest
```

训练可复现需要：

```text
base_model_id
base_model_revision
adapter_config
training_config
random_seed
dataset_version
code_commit
```

---

# 17. Evaluation System — 第五个核心 ML Systems 模块

新版本不能靠“我聊了几句感觉不错”上线。

## 17.1 Behavioral eval

覆盖：

```text
Social avoidance
Self-criticism
Career comparison
Procrastination
Exhaustion
Loneliness
Relationship uncertainty
Real danger vs imagined danger
Overdependence on AI
Casual conversation
Humor
Goal follow-through
```

评测：

```text
理解准确性
是否区分事实和解释
是否过度安慰
是否过度强推
是否说教
人格一致性
行动帮助
现实生活导向
记忆使用正确性
不确定性表达
```

## 17.2 Retrieval eval

```text
Recall@K
MRR
nDCG@K
retrieval latency
wrong-memory rate
```

## 17.3 Systems eval

```text
TTFT
TPOT
tokens/sec
p50/p95 latency
throughput
VRAM
GPU utilization
error rate
```

## 17.4 Regression gate

每个 model / prompt / retrieval / policy 版本都跑固定 scenario suite。

新版本只有在：

```text
质量没有不可接受回退
人格没有破坏
关键安全场景没有回退
系统性能达到要求
```

才允许 deploy。

---

# 18. Observability & Tracing — 第六个核心 ML Systems 模块

每次请求都生成 `trace_id`。

一次 trace 最终应该能回答：

```text
用户说了什么？
检索了哪些 memory？
每条 memory 得分是多少？
Context Builder 最终选择了什么？
Router 为什么选择这个模型？
使用哪个 model/version/adapter？
TTFT 是多少？
总延迟是多少？
GPU 使用如何？
用户是否认为有帮助？
后续真实行动是什么？
```

建议 span：

```text
request
├── state_estimation
├── memory_retrieval
│   ├── embedding
│   ├── candidate_search
│   └── reranking
├── policy
├── context_build
├── model_route
├── inference
└── persistence
```

记录：

```text
request_id
trace_id
model_used
model_version
adapter_version
dataset_version where relevant
retrieval_latency
memories_retrieved
memories_used
prompt_tokens
output_tokens
TTFT
TPOT
total_latency
cache_hits
GPU metrics
user_feedback
```

长期可以使用 MLflow tracing/evaluation 或标准 OpenTelemetry-compatible instrumentation。

不要让核心业务逻辑绑定具体 observability vendor。

---

# 19. Deployment & Model Registry

最终 Personal Brain 运行在用户控制的 GPU server 上。

部署对象不是只有模型权重。

一个可部署 release 应包括：

```text
Companion Core version
DB schema version
Prompt / policy version
Retrieval version
Base model id
Adapter version
Embedding model version
Reranker version
Dataset version
Evaluation report
```

Model registry 至少记录：

```text
candidate
approved
production
rejected
rolled_back
```

上线需要支持：

```text
health check
version endpoint
rollback
migration notes
```

不要一开始上 Kubernetes。

单用户项目早期：

```text
Docker Compose / simple containers
+
GPU server
+
reverse proxy / HTTPS
```

足够。

真正需要扩展时再扩展。

---

# 20. 数据与隐私

这是非常私人的系统。

原则：

```text
User owns the data.
User owns the memory.
User can export everything.
User can delete everything.
Derived data links back to source events.
Secrets never enter repository.
```

长期：

```text
HTTPS
at-rest encryption
secret manager / environment
separate object storage for audio/images
export format
backup
schema versioning
access logs
```

Personal memory 不应因为某个第三方 model provider 被锁死。

Ambient context 同样遵循 data minimization 和 purpose limitation：优先设备侧处理、coarse categories、event-driven signals、owner-authorized integrations 和不必要 raw data 的短 retention。任何 observation 都必须绑定 capability、consent scope、sampling、retention、freshness、source health、DataPolicy 和 provenance。Source unavailable 必须呈现为 missing/unknown，不能被解释成 user inactive 或某个行为没有发生。

---

# 21. 推荐技术栈

## Companion Backend

```text
Python
FastAPI
Pydantic
SQLAlchemy / async database layer
```

## Database

```text
PostgreSQL
pgvector
```

## Worker Boundary

```text
Python worker
```

早期可以同一部署单元运行。

接口边界先保留。

以后需要时再加入：

```text
Redis
job queue
```

## Model Serving

长期候选：

```text
vLLM
```

原因：

```text
OpenAI-compatible API
continuous batching
prefix caching
chunked prefill
quantization support
high-throughput serving
```

业务层不能直接依赖 vLLM。

## Training

```text
PyTorch
Hugging Face ecosystem
PEFT / LoRA / QLoRA-compatible training stack
```

Qwen 当前官方生态已经提供多种 LoRA / QLoRA training 路线。

具体训练 framework 不在 Stage 0 锁死。

## Observability / Evaluation

长期候选：

```text
MLflow tracing + evaluation
```

核心 trace schema 保持 vendor-neutral。

## Web

```text
React / Next.js
```

只作为早期开发入口。

## iPhone

```text
Native SwiftUI
```

负责：

```text
Voice
Text
Scene control
Low-bandwidth signals
Notifications
Audio playback
Local cache
future Edge Brain
```

iPhone 不是 Companion 本身。它是现有 HAVRE Core 的 interface、delivery adapter 和一组可选 ContextSource capability。设计不能假设 iOS 能持续运行任意后台程序或检查其他应用；voice 默认 user-initiated，location/motion/Health/wearable/background 能力必须逐项遵守 OS 限制、scoped consent、retention 和 privacy policy。

## Windows Agent

未来 Windows agent 也是 ContextSource host，不是第二个 Companion Core。默认只允许 coarse foreground category、active/idle duration、lock/unlock/device presence、owner-declared task session、coarse summaries 和单独授权的 study/development-tool checkpoints。默认不采集 screenshots、OCR、window/document/URL content、keystrokes、clipboard、raw microphone、browser history 或 unrestricted process/filesystem/network telemetry。

Windows 先在本地完成分类和 time-window aggregation，再通过 authenticated owner/device-bound ingest port 发送 canonical draft。Core 负责 consent/schema/policy/freshness validation、Event persistence、state interpretation 和所有 proactive governance。

---

# 22. Repository Structure

```text
havre/
│
├── README.md
├── MASTER_PLAN.md
├── .env.example
├── docker-compose.yml
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATABASE_DESIGN.md
│   ├── EVENT_MODEL.md
│   ├── MLSYS_DESIGN.md
│   ├── EVALUATION_PLAN.md
│   ├── BENCHMARK_PLAN.md
│   ├── ROADMAP.md
│   ├── STATE.md
│   ├── PROACTIVE_INTERACTION.md
│   ├── AMBIENT_LIFE_CONTEXT.md
│   └── adr/
│
├── apps/
│   ├── web/
│   ├── ios/
│   └── windows-agent/             # later-stage/inactive; first external source in Stage 12
│
├── services/
│   ├── api/
│   ├── worker/
│   └── inference/
│
├── companion/
│   ├── identity/
│   ├── user_model/
│   ├── goals/
│   ├── state/
│   ├── scenes/
│   ├── memory/
│   ├── patterns/
│   ├── policy/
│   ├── proactive/                  # later-stage/inactive; Stage 6 Proactive Core boundary
│   ├── life_context/               # later-stage/inactive; ContextSource contracts/adapters
│   ├── context/
│   ├── models/
│   ├── tools/
│   ├── delivery/                   # later-stage/inactive; provider-neutral delivery boundary
│   └── events/
│
├── mlsys/
│   ├── retrieval/
│   ├── routing/
│   ├── serving/
│   ├── caching/
│   ├── tracing/
│   └── benchmarks/
│
├── learning/
│   ├── reflection/
│   ├── consolidation/
│   ├── datasets/
│   ├── finetuning/
│   └── model_registry/
│
├── evals/
│   ├── scenarios/
│   ├── retrieval/
│   ├── behavioral/
│   ├── systems/
│   └── regression/
│
├── db/
│   ├── migrations/
│   └── seeds/
│
├── identity/
│   ├── mission.md
│   ├── personality.md
│   ├── principles.md
│   └── boundaries.md
│
├── scripts/
│   ├── bench/
│   ├── eval/
│   ├── train/
│   └── deploy/
│
├── tests/
│
└── infra/
    ├── local/
    └── cloud/
```

不是所有目录第一天都有代码。

但系统边界从第一天明确。

---

# 23. 一次完整 Reactive Interaction 的最终流程

用户说：

> “我真的不想进去，我感觉进去肯定很尴尬。”

完整流程：

```text
1. Receive input
2. Create trace_id
3. Store raw USER_MESSAGE Event
4. Update Current State
5. Read active Scene
6. Read active Goals
7. Retrieve memory candidates
8. Rerank memories
9. Retrieve relevant Patterns / Progress
10. Read relevant User Model beliefs
11. Apply Intervention Policy
12. Build token-budgeted Context Pack
13. Model Router selects brain
14. Inference service generates structured decision
15. Generate natural-language response
16. Store ASSISTANT_MESSAGE Event
17. Record trace metrics
18. Wait for signal / action / outcome
19. Store USER_ACTION / OUTCOME
20. After scene, run reflection
21. Update derived memories / patterns
22. Create training candidate if useful
23. Add future evaluation example if novel
```

用户最后可能只听到：

```text
“我知道你现在真的不想进去。”
“但‘肯定会尴尬’还是预测。”
“今天不用表现。”
“进去待十分钟。”
```

**背后系统复杂。**

**用户体验简单。**

主动进入同一系统时，完整流程是：

```text
1. Observe and durably record a valid Trigger
2. Create a ProactiveProposal with reason, benefit, evidence, privacy, timing, and dedupe key
3. Evaluate it with a versioned InterruptionPolicy
4. Record SEND_NOW / DEFER / DROP / REQUEST_OWNER_CONFIRMATION and reasons
5. Stop for every result except SEND_NOW
6. Build a purpose-bound proactive ContextPack
7. Select an eligible deterministic/model renderer
8. Render without expanding the authorized purpose
9. Select an eligible provider-neutral delivery adapter
10. Attempt idempotent, privacy-safe delivery
11. Store a proactive ASSISTANT_MESSAGE only after user-visible delivery
12. Link dismissal, snooze, explicit reply, feedback, action, or outcome
13. Treat no response as unknown, never as distress or permission to escalate
```

`Trigger`、`Proposal`、`Policy authorization`、`Rendering` 和 `Delivery` 是五个不同责任。HAVRE 有理由说话、现在应该说话、以及没有回应后是否应该再说，是三个不同决定。

---

# 24. 开发策略：两条线并行，而不是先做 App 再补 ML Systems

```text
                 Companion Track
                       │
Identity -> Memory -> User Model -> Goals -> Scene -> Reach Out -> Reflection
                       │
                       │
                       ▼
                    Product
                       ▲
                       │
Serving -> Retrieval -> Eval -> Routing -> Training -> Deploy
                       │
                  ML Systems Track
```

每出现一个产品能力，就同时建立相应 benchmark / tracing。

例如：

```text
Memory 上线
-> 同时建立 retrieval eval

Self-host model 上线
-> 同时建立 inference benchmark

Router 上线
-> 同时测 latency/quality tradeoff

LoRA 上线
-> 同时跑 before/after regression suite
```

---

# 25. 分阶段路线：每一阶段都是最终系统的一部分

## Stage 0 — Architecture Lock + Measurement Contracts

暂时不写业务功能。

完成：

```text
MASTER_PLAN.md
ARCHITECTURE.md
DATABASE_DESIGN.md
EVENT_MODEL.md
MLSYS_DESIGN.md
EVALUATION_PLAN.md
BENCHMARK_PLAN.md
ROADMAP.md
STATE.md
ADR structure
```

定义：

```text
Event schema
trace schema
Model Provider interface
Memory interface
Retrieval interface
Evaluation case format
Benchmark result format
Model / dataset version metadata
```

目标：

**以后每一层都长在最终系统上。**

---

## Stage 1 — Companion Foundation + End-to-End Trace

激活：

```text
PostgreSQL
Append-oriented Event Store + DataPolicy
Approved Constitution / Identity / Values
request_id + W3C trace across every interaction
Token-budgeted ContextPack + provenance + effective privacy
Provider-neutral ModelProvider / InferenceRequest
Durable delivered ASSISTANT_MESSAGE
Exact provider/model/version + measurable metrics
```

Stage 1 使用版本固定的本地 deterministic acceptance provider 验证永久基础设施链路，不声称已经具备生产级对话能力。任何 cloud provider 仍必须通过 owner 批准和 DataPolicy eligibility 检查。

成果不是“有聊天网站”。

成果是：

```text
每次 interaction 有永久事件记录
每次模型调用可追踪
模型 provider 可替换
超时和失败不会伪装成已交付回复
```

---

## Stage 2 — Episodic Memory + Retrieval Benchmark

2026-08-13 验收修正：通过新增 `0004_stage2_acceptance_corrections.sql` 完成删除传播闭包、provenance 来源端 owner 外键、worker lease generation fencing、已审核候选不可变，以及检索相关度阈值与重复抑制；没有改写已应用的 `0003`。默认进入 ContextPack 的检索版本为 `retrieval-r1-vector-gated-v2`，旧 R0/R1 仅保留作 benchmark。完整证据见 [`docs/STAGE2_CHECKPOINT.md`](docs/STAGE2_CHECKPOINT.md)。

激活：

```text
Memory extraction
Embedding
PostgreSQL + pgvector
Retrieval
Provenance
Importance
Basic deduplication
```

同时建立：

```text
retrieval_gold_set_v1
Recall@5
MRR
retrieval latency
```

这是第一个真正的 ML Systems milestone。

---

## Stage 3 — Self-hosted Inference Baseline

不要直接追求最大模型。

先 self-host 一个机器能稳定运行的 open-weight model。

激活：

```text
Inference service boundary
vLLM or selected serving engine
OpenAI-compatible API
streaming
metrics collection
```

建立 benchmark harness：

```text
TTFT
TPOT
tokens/sec
p50 / p95 latency
VRAM
throughput
```

然后才逐渐测试更大模型 / 云 GPU。

---

## Stage 4 — User Model + Pattern + Progress + Goal System

激活：

```text
Belief confidence
Evidence / counter-evidence
Pattern detection
Progress Memory
Reality Track
Life Track
```

同时为 User Model 更新写 regression tests。

---

## Stage 5 — Intervention Policy + Scene System

激活：

```text
Structured intervention decision
Before Scene
During Scene signals
After Scene
Outcome tracking
```

Early scene signals 可在 Web 模拟。

同时建立 scene-response evaluation。

---

## Stage 6 — Proactive Core + Context Optimization + Adaptive Model Routing

激活：

```text
Versioned Trigger contracts
ProactiveProposal lifecycle
InterruptionPolicy with owner permissions, budgets, cooldowns, dedupe, expiry
Web / inbox delivery through a provider-neutral port
Proactive provenance, traces, response linkage, and privacy-safe preview artifacts
Context budget
Reranking improvements
Prefix-stable context sections
Model Router
Small vs Large model policy
Fallback
Synthetic/manual LifeContextObservation fixtures only for downstream contract tests
```

实验：

```text
always-large baseline
vs
adaptive routing
```

Proactive Core 只在 Stage 4 的 Goals/User Model 和 Stage 5 的 Scene/Intervention foundations 已存在后激活。它先复用 PostgreSQL-backed job/outbox 和 Web/inbox adapter；只允许明确标为 synthetic/manual 的 life-context fixtures 验证 observation → Trigger → Proposal boundary，不声称真实 sensing。它不提前加入 Windows、iOS、Calendar、location、wearable、email 或专用 queue。

比较：

```text
quality
TTFT
end-to-end latency
GPU cost
```

---

## Stage 7 — Reflection + Consolidation + Offline Data Pipeline

激活：

```text
Daily Reflection
Periodic Consolidation
Training Candidate Builder
Dataset snapshots
Data quality filters
Reflection-generated ProactiveProposal candidates
Experience-to-memory promotion and owner-review policy
Contradiction / supersession / archival / reconsolidation proposals
Derived-data regeneration with exact provenance
```

系统第一次开始真正随时间形成新理解。

Reflection、Consolidation 和 Teacher processes 可以提出 pattern check、progress observation 或 follow-up proposal，但仍不能授权或投递；Stage 6 Proactive Core 继续负责所有发送决定。

---

## Stage 8 — Unified Evaluation + Observability

激活：

```text
Behavioral eval
Retrieval eval
Systems eval
Proactive usefulness / interruption-policy eval
Regression suite
Trace explorer
Evaluation report
Source health / freshness / missingness evaluation
Memory lifecycle and temporal-validity evaluation
```

此时任何大的模型 / retrieval / policy change 都必须过 gate。

---

## Stage 9 — Personal LoRA / QLoRA

第一次参数层个性化。

比较：

```text
Base
Base + Memory
Base + LoRA
Base + Memory + LoRA
```

记录：

```text
dataset version
base model revision
training config
adapter version
eval report
```

只有通过 Evaluation Gate 才进入 production。

---

## Stage 10 — Cloud Deployment + Reliability

把 Personal Brain 部署到用户控制的 GPU server。

增加：

```text
HTTPS
health checks
version endpoint
backup
restart policy
basic load testing
rollback
```

此时 iPhone 可以随时访问同一个 Companion Core。

---

## Stage 11 — Native iPhone + Voice

激活：

```text
SwiftUI
Voice
Text
Scene controls
Audio response
Notifications
Provider-neutral proactive push delivery
Lock-screen actions and privacy preview controls
Low-bandwidth replies linked to the original proposal
Local cache
Individually approved OS-supported ContextSource capabilities
```

iPhone 不重写 Companion，也不承担持续任意后台执行或读取其他 app 的假设。Text 和 user-initiated voice 进入同一个 Core；location、motion、Health/wearable 和其他 context capability 必须逐项授权，并保留 source health、freshness、retention 和 offline reconciliation。

只是已有系统的新入口。

---

## Stage 12 — Ambient Life Context + Edge Brain + Hybrid Inference

最后逐步增加：

```text
phone-local small model
simple local tasks
offline mode
hybrid routing
Windows coarse-context agent
Calendar adapter
Location / mobility context
Wearable summaries
ContextSource adapters with scoped consent
Core-owned context-aware Trigger evaluators
```

Stage 12 按 capability 逐项激活：先比较 coarse Windows/context summary 与 Calendar 的 usefulness/privacy，再考虑 location、mobility、wearable 和更丰富 context。每个 adapter 只产生 `LifeContextObservation` 和 health evidence；不得直接创建 notification 或绕过 Trigger/Proposal/InterruptionPolicy。更高 precision 必须相对 minimum-sufficient baseline 展示 measured benefit。

研究：

```text
哪些请求端侧完成？
哪些交给 cloud Personal Brain？
什么时候因隐私选择本地？
什么时候因质量升级到大模型？
```

---

# 26. ML Systems 实验清单

项目最终至少应该完成几组真正有结果的实验。

不要现在编数字。

以后测出来。

## Experiment A — Retrieval

```text
Embedding-only
vs
Embedding + recency
vs
Hybrid scoring
vs
Hybrid + reranking
```

指标：

```text
Recall@5
MRR
p95 latency
```

## Experiment B — Model Size / Quantization

```text
small model
medium model
large model
```

结合不同 quantization。

指标：

```text
behavioral quality
TTFT
TPOT
VRAM
cost
```

## Experiment C — Routing

```text
always-large
vs
rule-based router
vs
learned router（后期）
```

指标：

```text
quality retention
latency reduction
cost reduction
route errors
```

## Experiment D — Personalization

```text
Base
Base + Memory
Base + LoRA
Base + Memory + LoRA
```

回答：

**Memory 和 parameter personalization 分别贡献什么？**

## Experiment E — Context Budget

```text
Top 3 memories
Top 5
Top 10
summary + raw excerpts
```

回答：

**更多 context 是否真的更好？**

---

# 27. Resume-ready 标准

不要因为用了 Qwen、pgvector、vLLM 就自称 ML Systems project。

至少做到：

```text
1. 真正 self-host 一个 open-weight model。
2. 有可复现 inference benchmark。
3. 有真实 long-term retrieval pipeline。
4. 有人工标注 retrieval benchmark。
5. 有统一 behavioral + systems eval suite。
6. 有 request-level tracing。
7. 有 model / dataset / adapter versioning。
8. 至少做一次真实 LoRA/QLoRA personalization experiment。
9. 有一个 quality-latency-cost tradeoff 实验。
10. 有部署与 rollback 路径。
```

真正完成后，README 才可以写类似：

> **A self-hosted personalized LLM system with long-term episodic memory, adaptive model routing, continual personalization, and evaluation-driven deployment.**

未来简历 bullet 应只使用真正测出来的数据。

示例结构，而不是现在可以直接填的结果：

```text
Built a self-hosted personalized LLM platform using an open-weight model and optimized serving,
integrating long-term vector memory, adaptive routing, LoRA personalization, and evaluation-driven deployment.
```

```text
Improved [measured metric] by X% through [real optimization] while retaining Y% of [measured quality metric]
on a Z-scenario evaluation suite.
```

```text
Designed a PostgreSQL/pgvector episodic-memory retrieval pipeline with hybrid ranking,
achieving X Recall@5 at Y ms p95 retrieval latency on a manually labeled benchmark.
```

**数字必须以后真实测。**

---

# 28. 每个 Milestone 的开发规则

Codex 每次只做一个明确 milestone。

必须：

1. 解释解决什么问题。
2. 说明它在最终架构的位置。
3. 定义输入输出和接口。
4. 定义失败模式。
5. 先写测试 / benchmark 计划。
6. 实现。
7. 给运行方法。
8. 给验证标准。
9. 更新 `docs/STATE.md`。
10. 有架构变化时写 ADR。
11. 报告真实测量值，不编数字。
12. 停止，等待用户确认。

不要一次做完整 roadmap。

不要偷偷创建将来会被丢掉的第二套临时架构。

---

# 29. Codex 的角色

Codex 是：

**Implementation Engineer + ML Systems Engineer。**

用户是：

**Product Owner + System Architect。**

Codex 可以大量写代码。

但每一个 milestone 都必须让用户能回答：

```text
这个模块为什么存在？
输入是什么？
输出是什么？
它如何影响 Companion 的一次 interaction？
它的 latency / quality 指标是什么？
怎样评测？
失败时会发生什么？
以后怎样替换？
```

每个 milestone 最后附带：

**What you should understand before moving on.**

不要让用户成为命令复制器。

---

# 30. 项目启动时的第一步（历史基线）

现在不要：

```text
iPhone App
Voice
Wearable
LoRA
27B deployment
Calendar
复杂 agent framework
Kubernetes
```

项目启动时的第一步是：

**Stage 0 — Architecture Lock + Measurement Contracts。**

Codex 先完成：

```text
repository skeleton
ARCHITECTURE.md
DATABASE_DESIGN.md
EVENT_MODEL.md
MLSYS_DESIGN.md
EVALUATION_PLAN.md
BENCHMARK_PLAN.md
ROADMAP.md
STATE.md
ADR structure
```

这些工作已经完成。当前状态不再由本节决定，而由第 33 节和 [`docs/STATE.md`](docs/STATE.md) 决定。

当时的要求是完成后停止。

先 review。

通过后再 Stage 1。

---

# 31. 给 Codex 的启动 Prompt

把下面内容直接发给 Codex。

```text
You are helping me build HAVRE (渡禾), a long-term Personal AI Companion and personalized ML system.

HAVRE stands for Human-Aware Values, Reflection & Evolution.

This is NOT a disposable MVP, NOT a generic chatbot, and NOT a project where ML-system technologies are added later only for resume value.

We are designing the final architecture first and activating it layer by layer. Every stage must remain part of the eventual system unless an explicit architecture decision replaces it.

Read MASTER_PLAN.md as the source of truth.

PRODUCT MISSION

HAVRE should help me understand myself, face reality, take action, and gradually become a warm, gentle, firm, strong, emotionally stable person with a little humor.

It should accompany my life but never replace my life.

It should eventually become a long-term AI individual that understands my experiences and patterns, guides me in real situations, reflects with me afterward, and gradually personalizes itself while encouraging greater real-world agency rather than dependence on the AI.

NON-NEGOTIABLE PRINCIPLES

1. Model is replaceable. Identity is persistent.
2. Raw experience is append-preserved by default. Derived understanding is revisable. Owner retention and erasure govern both.
3. Canonical training data must remain model-independent.
4. Real-world agency is more important than maximizing AI engagement.
5. Important ML-system components must be independently measurable and evaluable.
6. Do not create throwaway architecture for speed.
7. Do not over-engineer infrastructure before it is needed.

THE FINAL COMPANION MUST EVENTUALLY SUPPORT

- Persistent identity and values
- Revisable User Model with confidence, evidence, and counter-evidence
- Append-oriented raw Event Store
- Working, episodic, semantic, pattern, and progress memory
- Provenance from derived understanding back to source events
- Goals for both real-world responsibility and personal growth
- Current-state estimation
- Before / During / After Scene sessions
- Low-bandwidth real-world signals during scenes
- Structured Intervention Policy
- ProactiveProposal and explainable Interruption Policy
- Governed Reach Out flow with owner controls, budgets, cooldowns, and provider-neutral delivery
- Token-budgeted Context Builder
- Replaceable model providers
- Personal Brain
- Teacher Brain
- Future Edge Brain
- Reflection and consolidation
- User feedback and real-world outcome tracking
- Model-independent training examples
- LoRA / QLoRA personalization later
- Native iPhone client later
- Self-hosted open-weight Personal Brain later
- Optional Calendar, Location, wearable, and sensor context later
- Provider-neutral Ambient Life Context with Windows, iPhone, Calendar, voice, location, and wearable adapters behind scoped consent
- Explicit ContextSource health, freshness, coverage, sampling, retention, and minimum-sufficient-signal semantics

THE FINAL ML SYSTEMS BACKBONE MUST EVENTUALLY SUPPORT

- PostgreSQL + pgvector data and vector retrieval
- A measurable memory ingestion and retrieval pipeline
- Hybrid retrieval / reranking with a retrieval benchmark
- Self-hosted LLM inference behind a standard HTTP interface
- An inference benchmark harness measuring TTFT, TPOT, throughput, p50/p95 latency, VRAM, and error rate
- Adaptive model routing based on complexity, latency, privacy, availability, and cost
- Context-budget optimization and caching experiments
- Dataset snapshot/version metadata
- LoRA / QLoRA training pipeline
- Model / adapter / dataset version registry
- Behavioral, retrieval, and systems evaluation
- Regression gates before model changes are deployed
- Request-level tracing and observability
- Deployment metadata, health checks, and rollback

INTENDED TECHNICAL DIRECTION

Use this direction unless there is a strong, documented reason to change it:

- Python
- FastAPI
- PostgreSQL
- pgvector
- A worker boundary for reflection/background jobs
- Replaceable model-provider interface
- Web client as the early development interface
- Native SwiftUI iPhone client later
- Self-hosted open-weight model behind an OpenAI-compatible HTTP API later
- vLLM is the current preferred serving candidate, but business logic must not bind directly to vLLM
- MLflow is a future candidate for LLM tracing/evaluation, but tracing contracts should remain vendor-neutral
- Training stack should remain compatible with LoRA / QLoRA and should not be locked to one framework during Stage 0

IMPORTANT PRODUCT ARCHITECTURE

The HAVRE Companion Core should remain conceptually separate from the ML Systems Backbone.

HAVRE Companion Core includes:

- Identity
- User Model
- Goals
- Current State
- Scene Manager
- Memory semantics
- Pattern / Progress model
- Intervention Policy
- Proactive Interaction / Interruption Policy
- Provider-neutral delivery
- Context Builder
- Tools

ML Systems Backbone includes:

- Data pipeline
- Retrieval / reranking
- Inference serving
- Adaptive routing
- Caching / context efficiency
- Training pipeline
- Model and dataset versioning
- Evaluation
- Tracing / observability
- Deployment / rollback

These are one system, but separation of responsibilities must remain clear.

SCENE INTERACTION MODEL

Before Scene:
full conversation, context, goal setting, and likely-trigger preparation.

During Scene:
minimal user signals and very short guidance with low interaction cost.

After Scene:
reflection, outcome capture, memory creation, pattern/progress evidence, and training candidates.

STAGE 0 ONLY

Do NOT start implementation of product features yet.

We are starting with Stage 0: Architecture Lock + Measurement Contracts.

First inspect the repository and MASTER_PLAN.md.

Then create/propose:

- docs/ARCHITECTURE.md
- docs/DATABASE_DESIGN.md
- docs/EVENT_MODEL.md
- docs/MLSYS_DESIGN.md
- docs/EVALUATION_PLAN.md
- docs/BENCHMARK_PLAN.md
- docs/ROADMAP.md
- docs/STATE.md
- docs/adr/ structure

Also propose the permanent repository skeleton.

STAGE 0 MUST DEFINE THESE CONTRACTS

- Raw Event schema
- trace_id propagation
- Model Provider interface
- Inference request/response abstraction
- Memory interface
- Retrieval interface
- Context Pack format
- Evaluation case format
- Benchmark result format
- Model version metadata
- Adapter version metadata
- Dataset snapshot metadata
- Provenance conventions

ARCHITECTURE RULES

For every important design decision:

1. Explain the real problem it solves.
2. Explain why it belongs in the final system.
3. Explain the simplest viable current implementation.
4. Explain alternatives considered.
5. Explain future migration risks.
6. Record important choices in an ADR.

The raw Event Store is foundational. “Raw” means HAVRE's earliest retained canonical evidence; it does not require centralizing unrestricted device-native capture.

Derived memories, patterns, reflections, and User Model beliefs must keep provenance back to source events whenever practical.

The User Model must support uncertainty, confidence, supporting evidence, counter-evidence, and revision.

The Memory System must support multiple memory classes and must not be designed as “just a vector database.” Experience is not automatically Memory; promotion, temporal validity, contradiction, consolidation, archival, reconsolidation, and erasure propagation are explicit.

The retrieval system must be benchmarkable independently from the language model.

The model layer must be replaceable and must not bind HAVRE identity to Qwen, OpenAI, Claude, or any specific provider.

Inference serving must have a stable service boundary so serving engines and model sizes can later be benchmarked and swapped.

Training data must be stored in a canonical model-independent format so a future stronger base model can be trained from the same long-term history.

Evaluation must cover behavioral quality AND ML-system performance.

Do not claim performance improvements until they are measured.

Do not add Kubernetes, distributed queues, microservices, or other infrastructure merely to make the architecture look sophisticated.

Preserve boundaries now; introduce infrastructure only when a real workload requires it.

DEVELOPMENT STYLE

For each later milestone:

1. Explain what we are building.
2. Explain why it exists in the final architecture.
3. Define interfaces and metrics.
4. Define the evaluation / benchmark plan.
5. Implement it.
6. Add tests.
7. Run real measurements where relevant.
8. Explain how to run and verify it.
9. Update docs/STATE.md.
10. Record architectural changes in ADRs.
11. Tell me what I need to understand before moving on.
12. Stop and wait for my approval.

I am using AI heavily for implementation, but I want to understand and own the architecture, experiments, and product decisions.

Treat me as the Product Owner and System Architect.

You are the Implementation Engineer and ML Systems Engineer.

WHEN STAGE 0 IS DONE

Explain the proposed architecture to me in plain English.

Show the end-to-end path of one user interaction.

Show the end-to-end path of one memory retrieval.

Show the end-to-end path of one future training/deployment cycle.

List unresolved design decisions.

List anything in MASTER_PLAN.md you believe should change and why.

Do not begin Stage 1 until I explicitly approve the architecture.
```

---

# 32. 项目的长期成功标准

这个项目成功不只看：

```text
模型回答像不像人。
```

Human-centered 维度：

```text
它是否越来越准确地理解用户？
是否能承认自己可能理解错？
是否记得真正重要的事情？
是否帮助减少无意义回避？
是否帮助现实责任推进？
是否帮助形成自己的判断？
用户是否越来越能够不依赖 Companion 也做出稳定选择？
```

ML Systems 维度：

```text
Memory retrieval 是否有可测量质量？
Inference 是否低延迟且资源可控？
Router 是否改善 quality-latency-cost tradeoff？
Fine-tuning 是否真正产生增益而不是人格漂移？
每次系统行为是否可追踪？
HAVRE 是否只在有清晰用户收益和允许时机时主动联系？
主动联系的原因、政策、证据和投递是否可解释？
是否避免重复、打扰、隐私泄露和依赖诱导？
新版本是否可评测、可部署、可回滚？
换掉基础模型以后身份和历史是否继续存在？
```

最终理想状态不是：

**“我拥有一个离不开的 AI。”**

而是：

**“这个 AI 陪我走过很多路，而那些原本需要它提醒我的话，现在已经成为了我自己的声音。”**

---

# 33. 当前最重要的下一步

Stages 1 through 5 已由 Product Owner 批准并完成；Stage 5 的接受绑定到 [`docs/STATE.md`](docs/STATE.md) 和 correction checkpoint 记录的 execution-source snapshot。Proactive Interaction architecture amendment 以及 ADR-0016 至 ADR-0018 已接受，但主动交互 runtime 仍只能在对应的后续 Stage 激活。

ADR-0019 和 ADR-0020 已由 Product Owner 于 2026-08-19 接受；Stage 6/7 的接受绑定到 [`docs/STATE.md`](docs/STATE.md) 记录的 execution-source snapshot。Stage 8 已完成技术验收且未授权 release promotion。Stage 9 已在技术证据接受、candidate-only 的边界关闭；9201/9202 都没有 promotion 或 deployment，Stage 9B 和新训练继续延期。Stage 10 的可靠性与用户控制发布实现、PostgreSQL 验证，以及 owner-controlled Docker host 上的原生 immutable deploy/rollback、HTTPS、restart、backup/restore、deletion replay、export、load/failure 出口证据已经完成，最终独立审查为 P1=0/P2=0。现有 deployment 仅为 infrastructure-only，不激活 behavior，也没有 adapter promotion/deployment。Stage 11 已达到 reviewed implementation checkpoint；macOS/Xcode/真机证据已被明确延期但未 waiver，APNs 仍未激活。Product Owner 于 2026-08-22 明确授权 Stage 12A；Windows coarse context 与 provider-neutral、owner-initiated manual ICS Calendar 已达到 disabled implementation checkpoint，Microsoft Graph 已停用。Windows 仍缺真实 owner evidence，Calendar 仍待首个 owner-supplied ICS 验证。Product Owner 随后请求把 iPhone Screen Time 每日总时长作为 Calendar 之后的下一个独立 gate；普通 Apple report extension 不允许把报告数据导出给 Core，直接数据导出又受地区与 entitlement 限制，因此其实现、entitlement 和真机证据尚未开始。General Stage 12B、location/wearable/其他 richer sensing、ambient microphone、adapter promotion/deploy、用户数据训练、自动 Memory 修改和任何治理变更仍未获授权。
