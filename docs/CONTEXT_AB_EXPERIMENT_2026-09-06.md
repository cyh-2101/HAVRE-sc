# HAVRE Context A/B 实验结果（2026-09-06）

## 结论与决定

**没有明确胜者。最终有效轮次略偏向 Simple，但不足以支持整体简化；也没有证明
完整架构的复杂度都值得保留。维持已接受的稳定 checkpoint，不增加场景路由。**

32 个真实主样本：**Simple 12 胜 / Full 8 胜 / 平局 1 / 顺序分歧 11**。
Simple 份额 **56.3%**（平局、分歧先各计 0.5），12 个对话家族的 bootstrap
95% 区间为 **42.9%–65.9%**。Full 对应 43.8%，区间 34.1%–57.1%。
把未解决分歧分别全部归给任一方，Simple 份额范围为 **39.1%–73.4%**。
两种展示顺序的一致率为 **65.6%（21/32）**。

份额未达到原定 65%，区间没有排除 50%，一致率没有达到 80%。8 个预定重复案例
的共识标签全部改变：2 个直接在 Full/Simple 之间反向，6 个在分歧与偏好之间
变化。这不是“8 次明确胜负都反转”，但足以反对把单次小样本偏好写成生产策略。

| 场景（每组 4 例） | Full | Simple | tie | unresolved |
|---|---:|---:|---:|---:|
| 人物/任务歧义 | 0 | 4 | 0 | 0 |
| casual talk | 2 | 0 | 0 | 2 |
| 事实纠正 | 1 | 2 | 0 | 1 |
| 跨天续聊 | 1 | 0 | 1 | 2 |
| Goal 相关 | 0 | 1 | 0 | 3 |
| 不应 callback | 1 | 2 | 0 | 1 |
| 过去经历 recall | 1 | 2 | 0 | 1 |
| stale information | 2 | 1 | 0 | 1 |

真实歧义组 4/4 偏 Simple，但该组预定重复案例又偏 Full；构造同名压力组反而偏
Full。它们的任务难度和来源可见性不同，不能从四个案例学出可靠的场景路由。
其他分层也有大量分歧。此次最小决定是保留当前 Context 构造路径，停止架构扩展。
未出现的层不因此获得价值背书；Simple 的其他实现也不由这个具体版本代表。

## 评价维度

每个案例先对两份顺序评分平均，再对 32 个主案例平均；每项有效 n=32。
前五项越高越好，后三项是伤害、越低越好。这是模型的 1–5 等级判断，不是 owner
满意率或事实正确率。整体偏好来自独立语义选择，没有用加权总分或关键词选胜者。

| 维度 | Full | Simple |
|---|---:|---:|
| naturalness | 4.69 | 4.70 |
| relationship_continuity | 4.47 | 4.36 |
| relevant_recall | 4.50 | 4.47 |
| correction_obedience | 4.50 | 4.59 |
| usefulness | 4.34 | 4.56 |
| over_analysis | 1.28 | 1.25 |
| forced_callback | 1.09 | 1.14 |
| fabricated_familiarity | 1.05 | 1.08 |

最终真实主样本只有 2 条 critical 标记，均指向同一个 Full 回答：没有实时工具
证据却确定宣称配送可用。它们是同一回答的两次评审标记，不是两起独立错误。
较低的 fabricated familiarity 分也不能当作其他事实都正确的证明。

## 实验条件与覆盖

稳定基线为 `PERSONAL_CONTEXT_ENGINE_REVIEW_2026-09-06` / production commit
`c5cd20287d9533569439bb44ebfd61db90f678f3`，migration 0071。
[原始协议](CONTEXT_AB_PROTOCOL_2026-09-06.md) 的案例、要求、执行顺序、维度与
判断阈值保持不变。另有下文记录的两次实际信息完整性修复，旧结果全部留档。

- Full：当前 builder v17、ResponsePlan v5、presentation v13、合格 Memory、
  User Model、OA70 运行时示例。
- Simple：独立编译相同 Identity、owner 明确响应约束、连续原始对话、当前问题的
  targeted raw recall 与明确纠正；不注入 ResponsePlan、行为示例、派生 Memory
  摘要、User Model 或主动 Goal。双方仍共用现有本地原始来源检索器和 Core。
- 相同总估算预算 16,384，输出预留 3,072。Simple 释放出的预算可供原始对话使用，
  并非从已经被 Full 裁剪后的输入里删几段。两组均经同一现有 Core，available effects
  为空；最终采用的 104 个回答全部 pass-through。实验不执行产品动作或写回事实。
- Owner 对 70 条候选、138 个 NORMAL/cloud-eligible 原始来源的本机 v2 包回复
  “批准v2”。选定 32 个真实目标、8 个预定重复；每个目标独立使用原始 pre-T 历史，
  不把 A/B 新生成的回答写进下一案例。测试的是固定共有历史下的一轮表现。
- 8 个名义场景各 4 例，属于 12 个对话家族，其中课程/关系两个家族分别有 8、9 例。
  不把相邻对话当作独立用户。真实归档仅约两周；跨天组包含睡后续聊/间隔问候，
  歧义组包含人物分离与任务指代。真正长时间隔和同名多人另用构造压力覆盖。
- Full 实际层覆盖：ResponsePlan 32/32、行为示例 27/32、episodic Memory 6/32、
  User Model 3/32；没有 Goal 或 Current State 注入。Goal 相关对话不是 Goal 投影
  收益的验证。纠正也常通过原始对话可见，不假称每例都测试了 durable overlay。
- 当前 selectors/compiler 按历史时点重建，Goal 来自 hash 可验证的 lifecycle 投影，
  纠正/反馈使用当时已知 revision head；拒绝未来回复或目标历史答案泄漏。
  OA70 的 70 例全部是运行时已暴露材料，不是独立 holdout。

## 固定模型与真正的盲评输入

全部生成及评审使用 **GPT-5.6-sol / medium、Codex CLI 0.153.0**，同一 wrapper、
工具禁用、独立 ephemeral 会话。每次核对返回 model/serving configuration，
CLI executable 和代码/payload hash 封存。模型 alias 不暴露不可变权重版本。
适配器不传 temperature/top-p/seed，采样由 provider 管理；3,072 是请求合同预算，
不是已验证的服务器硬上限。

每对随机标签、随机显示顺序，两次独立评审交换答案顺序。评审看到当前问题、
原始 pre-T 证据、冻结要求、两份答案及双方共有的准确目标时钟，不见架构、生成
prompt、层名、tokens 或 latency。语义理由、不确定性、分歧和 critical flags 原样保留。
锁定全部评分和原始响应 hash 后才读取映射。最终 64 组真实主输入已核对到
`CodexCliProvider._reply_prompt` 实际 canonical payload：Identity、时钟、目标、
source refs 完整一致；复用压力的 24 组实际输入也与评审时钟一致。

这些是模型语义盲评，不是独立人类验收。已有 5 条普通 owner 负面反馈，缺少正例
和成对标签，不能称评审器经过人类校准。模型在展示顺序和重复生成上的不稳定
必须保留。长期关系、主动联系实用性、物理手机体验、维护成本均没有因此得到证明。

## 性能、tokens 与费用

下面只用最终有效的真实轮次：32 个主案例各一对，8 个额外重复，共 80 个回答。
均值、中位数、p90 和 cache hit 仅统计主案例；总 tokens 包含重复。

| 指标 | Full | Simple |
|---|---:|---:|
| 平均 provider 输入 tokens | 14,923.8 | 14,270.6 |
| 平均输出 tokens | 124.5 | 138.2 |
| 生成延迟中位数 | 9.35 s | 10.65 s |
| 生成延迟 p90 | 12.75 s | 19.05 s |
| 主样本累计 cache hit tokens | 218,240 | 233,088 |
| 含重复的生成总 tokens | 605,358 | 579,570 |

Simple 平均输入 tokens 减少 **4.4%**，没有体现出生成延迟优势。Full−Simple
成对延迟差中位数 −0.33 s、均值 −2.21 s。数字包括 provider wrapper，不能直接
换算为 ContextPack 文本长度或整个架构成本。生成串行且顺序预定平衡，但缓存、
采样、服务波动和本机测试活动不可完全控制；不是端到端性能因果结论或 SLA。
准备计时含共享工作和缓存差异，不能拿 Simple 的增量准备时间作完整对照。
真实 80 次均正常 stop；压力 driver 未单独落盘 finish_reason，不能伪称硬输出限制已验证。

最终分析采用的 104 个答案合计 **1,504,048 tokens**，104 份有效评分合计
**1,939,047 tokens**。包括已作废诊断，本次实际完成 **472 次云端模型调用、
8,152,858 tokens**，另有 1 次评分超时没有返回用量。有效分析为 208 次调用，
其余 264 次是保留的准备/评审诊断。没有把失效轮次算进偏好或性能结果。
这些是实验调用，不包括本编码任务或本机 Qwen 的成本。

**USD cost 不可得，不是 $0。** 当前 Codex 认证路由不返回逐次美元账单，不能套用
其他 API 价格，也不能把订阅内调用说成免费。各阶段原始 usage 和未知用量均留档。

## 长期 recall 压力案例

[固定 fixture](../evals/fixtures/context_recall_stress_v1.json)：11 个构造来源、
3 次明确纠正、两段各 140 轮无关对话，查询时间推进 730 天。Memory 是精确 source
绑定的人工 fixture admission，不是自动提炼质量证明，也不是两年真实部署。

这部分未经过有缺陷的真实数据去标识器；24 个生成回答和补齐时钟后的 24 份评审
经实际 payload 核对后原样复用。结果单独为 **Full 6 / Simple 1 / tie 2 /
unresolved 3**，顺序一致率 75%。相对优胜不等于该能力完全通过。

| Cases | 压力能力 | 实际观测 |
|---|---|---|
| S01 / S02 | 很久以前的具体经历、后来身份纠正 | 两组保留修理动作/天气，并服从前同事而非主管的更正 |
| S03 / S04 | 两个人同名、两个项目同名 | 两组最终均未获得对应旧来源；Simple 在人名例猜了性别；项目例两组都未接上原计划 |
| S05 | stale 工作安排 | 两组采用新地点，不恢复旧值班表 |
| S06 | 相互矛盾的信息 | 两组承认未确定，不擅自选一个人 |
| S07 / S08 | 应承认不知道、不能移用他人事实 | 不编旅馆名，不把同事生日移给室友 |
| S09 / S10 | 日常情况应完全不 callback | 两组没有拉回旧脆弱经历；表达偏好仍有分歧 |
| S11 | 长文尾部的旧事实 | 两组正确回答天线接触不良，而非电池问题 |
| S12 | 撤回旧偏好、不要催促 | 两组遵从；Full 更简短，Simple 有额外安慰 |

只读诊断证明：S03/S04 每个查询的 lifetime 候选中都存在两条同名来源，但现有
admission gate 全部拒绝。S03 最高 semantic 分约 .125，S04 约 .424，均未达门槛；
不是索引没存历史或数据被擦除。Full 的显式 recall 入口也没有为这些间接查询
提供原始历史。这只是候选/准入诊断，不是回答质量关键词 scorer。

评审看到 archive ground truth，generator 只看到实际检索结果。因此 S04 的
“没有有效记录”不能直接当成看见事实后编造：先记录 recall 遗漏，再判断措辞是否
不当否定整个 archive。两份原评分保留，归因限制单列。没有为了得分改 query、
补答案或放宽全局门槛；两例不足以验证更宽准入带来的错误 callback 风险。

## 输入缺陷与修正：不混入最终结论

1. 初次生成后，`observed_at` 被错误当成 provider 配置漂移；修复只排除观察时间，
   保留模型、CLI、adapter、serving config 和输入 hash 检查。原 manifest 与代码
   byte/hash 保留。一次 Windows 换行修复尝试引入的空行在首次语义调用前恢复，
   原 JUDGE_PROMPT 不变。压力 generation request AST 没有变化。
2. 第一轮第 14 次评分超时；13 份完成评分保留，剩余评分改为最多 4 路并发。
   没有按内容挑选或删掉评分，超时用量标为未知。
3. 首轮评审包漏了 generator 应有的目标时钟，故全量补时钟重评，见
   [评审时钟 erratum](CONTEXT_AB_JUDGE_REPAIR_2026-09-06.md)。随后最终出站审计
   发现更早的去标识缺陷：四个 ISO 日期被误认为联系方式，一个短地点名被替换
   进普通英文单词。此前只核对 raw ContextPack，漏检了真正发送文本。
4. **前两轮真实结果均作废为准备诊断。** 依照[输入修复协议](CONTEXT_AB_INPUT_REPAIR_2026-09-06.md)
   保留日期、限制 Latin 单词边界，继续使用相同合法别名。逐条证明 32 个当前目标
   字符串、要求、schedule 完全不变，重跑全部 80 个真实回答及 80 份双顺序评分；
   无选择性复用早期回答。最终结论只使用 `validated-input-run`。
5. 压力库准备曾因 fixture 依赖/候选绑定失败而重建；核实隔离库仅含构造来源后
   从空库重新准备，通过 exact source-event 绑定才冻结当前压力输入。错误草稿留档。

本机 Qwen 实体提取与一致替换只用于 privacy preparation，不参与模型训练。
修复后保留 2 个合法去标识实体；四个误报日期不再被替换。原始来源、身份映射和
盲映射保留在 owner-only ACL 目录；NORMAL/cloud-eligible 衍生物只授权本次
生成/评审，training=false，不回灌产品。LOCAL_ONLY 和一次性 HIGHLY_PRIVATE 来源
排除在外。去标识仍可能被识别，不是匿名或公开语料；当前源码未包含原始案例包。

## 必要改动、验证与交付

只增加离线实验工具、12 个压力案例和完整性回归，修复评审时钟和去标识完整性。
生产 Context、Identity、Core、retrieval 门槛、模型配置和数据库 schema 均未改变。
新增 19 项实验测试覆盖 source/target 绑定、历史 Goal/纠正时点、只读数据库、随机
匿名标签、目标时钟、日期/单词边界、评分锁定/顺序绑定、锁后篡改与家族聚类。

**824 主环境 + 62 固定 Torch = 886/886；失败 0、错误 0、跳过 0。**
最终执行源码在测试前后一致：
`sha256:5dd65306b5733031a4009202f8bd65c3b8d5d503ea9699dca1cc9484ff6e91ff`。
测试库 `havre_context_engine_test_20260906`；压力库
`havre_context_ab_stress_20260906` 从空库应用 0001→0071。没有生产迁移或重启；
PostgreSQL 原先运行，结束仍运行。`pip check`、`compileall`、diff 检查通过，
测试 provenance 为 `[]`。

既有 `scripts.benchmark_personal_context` 按原 baseline
`b5664e53ccb527d89a5b07f036b3dabd2f54ef34` 复跑，原始经历保留 13/13，旧来源/
邻近纠正、长文尾部和歧义来源检查一致。随后只修了离线输入/评审工具，召回与
compiler 文件未改变；该 benchmark 是回归证据，不替代回答质量评估。
代码和证据由本任务复核，未额外委派编码代理；不自称独立人类代码审查。

- 最终匿名包：`var/context-ab-20260906/case-review-v2/validated-input-run/blind-review.LOCAL_ONLY.html`。
  52 对答案、客观时钟、可折叠证据和语义理由，无架构标签、外链、上传或写回。
- 完整来源、两轮失效诊断、最终生成/评分、source/clock audits、失败记录与 hash
  位于 `var/context-ab-20260906/case-review-v2/`；全部不进入 Git。
- `scripts/prepare_context_ab_cases.py` 准备只读 owner 包；`evals/context_ab_replay.py`
  与 `context_ab_privacy.py` 生成输入；`context_ab_blind.py` / `context_ab_judge_batch.py`
  执行固定模型与匿名评审；`context_ab_stress*.py` 提供压力实验；
  `context_ab_results.py` 锁定后分析真实与压力结果，不覆盖已有报告。
- 执行记录：`python -m evals.context_ab_blind --directory <run> --executable <pinned-cli> --phase generate`，
  然后 `python -m evals.context_ab_judge_batch --directory <run> --executable <pinned-cli> --concurrency 4`；
  分析为 `python -m evals.context_ab_results --directory <run>`，压力加 `--stress`。
  旧记录需使用其 manifest 绑定的代码，不绕过 drift guard 重解释历史结果。
- 验证命令/日志：`var/context-ab-20260906/run_primary.py`、固定 Torch 的三个
  `test_stage9a_real_*` 模块、`pip check`、`compileall`、`audit-provenance`、上述基准
  与 `git diff --cached --check`，结果在 `verification-summary.json`。

| 关键证据 | SHA-256 |
|---|---|
| owner 审批 v2 | `08cb5e2f799ce57ac1338134eb27138bd2bcc98e78a8f04f05366249c693d520` |
| 最终真实 spec | `191b5b07915826aacda04abc3ce03290e671edb07d79a77e3506a77480951b67` |
| 最终去标识输入 | `623e481959c0c1e141d5970492cd21884db621ee53869a5c4a07111af733b04e` |
| 实际 provider 输入审计 | `74dc70306ac15f9e291795f3569eea721b2e5ce5ac84b9cfe1680739edefc459` |
| 压力输入 | `723ac462e575c480c9fe579e69cd72fed5059b5e3cdee72f353c7bbc2d68a8a2` |
| 最终评分总锁 | `0e05c1ed5eed6cec1c04d034c08ec59bbe34a8699912e6bddcbeb9f3759ea42f` |
| 最终真实结果 | `47f96fc48b312595e5c1dd79a4a76e21d47dee48168bb1d8275255f922c2014b` |
| 有效压力结果 | `db4ca24de5ce8f1db6d42c3e9a22b53c9ce0917b0d796b99ef13f9598e9cd6d2` |

本轮在完成实验、必要修复、测试、证据复核与本地 commit 后停止：**不 push、
不训练、不 promotion、不新增定时任务或下一阶段工作。** Owner 的成对体验评级
仍未取得；这不阻止关闭本次实验，也不能被模型评分冒充。
