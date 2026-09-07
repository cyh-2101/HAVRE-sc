# Targeted recall 修复与 owner blind review（2026-09-06）

## 当前结果

已完成有边界的原始来源解析、代码复核、本地回归和 8 对 owner review 包。
保持当前生产 Context 架构，不做 Full/Simple 切换；没有降低全局 retrieval threshold，
没有调整 compiler、Identity、模型配置、数据库 schema 或主动联系策略。
本轮没有重启生产服务、训练、promotion、commit 或 push。

**909/909 测试通过：847 主环境 + 62 固定 Torch；失败、错误、跳过均为 0。**
新云端 GPT 语义复测被自动审批审查阻止，目前仅有明确的来源准入证据，不能宣称
GPT 已验证会稳定自然澄清或长期更懂 owner。18 个完整输入已封存等待本批授权。

## 修复了什么

`conversation-recall-indexed-lifetime-v3` 在原有 Event recall 中增加
`targeted-source-resolution-v1`：

- 精确名称必须来自合格 owner 原话中的明确命名表达，并与当前引用相符。
  不以模型猜测、相似度、名字前缀或 assistant 旧猜测建立人物身份。
- 有界的“又联系我”“下一步是什么来着”可以启动精确名称查找；普通提到名字的
  日常更新不会因此启动通用语义召回。不支持的命名表达仍可能漏检。
- 焦点检索复用同一个 owner/as-of/privacy/route/completion/revocation 过滤索引。
  原始语义门槛 `.45` 或 `.20 + .25 lexical` 保持原样；没有改全局 Memory 准入。
- 保留合理的同名来源、后续更正及对应 request pairs。限定词只在含名称的肯定
  子句里比较；否定比较不被当成人物身份。即使有一个限定词命中，也不丢掉其他
  可能纠正它的原始来源；由当前用户措辞及可见证据支持最终回答。
- 同时出现多个名称或超过 6 条同名来源时，停止该精确补充，保留普通 recent
  context；不从排名最高的一条制造“唯一身份”。这是保守退回，不是完整消歧。
- “摄影那个”一类短澄清只允许借用同 session、十分钟内紧邻的上一条 owner 原话
  作为查找线索；不跨 session/长时间隔绑定。发往模型的当前 user target 不改写。
- 只补充命中的原始 request pairs 和紧接着的明确纠正，不把三十分钟窗口内的
  其他人物/项目顺带导入。检索器版本进入 ContextPack 和最终请求 source refs。

`resolved` 描述当前可见来源层面的命中，不证明全库只有一个同名实体。
没有新增 entity registry、知识图谱、持久化推断、模型、服务或实体置信度算法。

## 与固定 baseline 的来源对照

Baseline 为已提交 `a1d8dc1` 的 recall 函数。双方使用相同当前 builder、planner、
Identity、模型无关呈现、原始来源与目标时点，只有原始 recall 选择器不同。
专用 `havre_context_ab_stress_20260906` 以 read-only 连接读取，共 602 个构造 Events。
保留原 12 个 stress targets/requirements，另加 4 个限定词/未知名字反例。

| 目标 | baseline 最终输入中的相关原始来源 | targeted 最终输入中的相关原始来源 |
|---|---|---|
| S03 同名人物 | 0/2 | 2/2：前同事与社团成员 |
| S04 同名项目 | 0/2 | 2/2：机器人小车与音乐列表 |
| U01 指明前同事 | 两条目标来源未进入 | 两条来源可见，当前限定词可用于区分 |
| U02 指明机器人项目 | 两条来源可见 | 两条来源可见，保留纠正/另一项目的区分证据 |
| U03 指明音乐项目 | 音乐来源可见 | 两条来源可见，当前限定词指向音乐 |
| U04 未知名字 | 无该人物来源 | 无该人物来源，不猜身份 |

S03/S04 不再夹带相邻的不相关项目、工作地点或相机借用话题。第一轮本地诊断
发现旧 neighborhood 会带入这些邻近话题，随后做了上述精确 request-pair 过滤；
原诊断保留，最终来源结果使用 `source-regression-v2.NORMAL.json`。
其余原 stress 案例的准入保持不变，包括 S07 未知旅馆、S08 不挪用生日，及
S09/S10 不应 callback 的原始来源为空。这里测的是来源可见性，不是自动语义评分。
统计只数原始 Event refs；派生 Memory/纠正可能另有 revision refs，不能把表内 0
误读为整个 Context 没有相关派生信息。U01 的既有 Memory 仍带有其他材料，本任务
没有据此扩大修改全局 Memory policy。

## 验证证据与边界

最终源码 hash（测试前后一致）：
`sha256:91b63c1b9a995fa9ad98ef6d639343bfff8bfa164a701e251e63ca0ffbd0029e`。
主环境测试使用核实过的 `havre_context_engine_test_20260906`，当前 migration 0071；
没有新迁移或生产迁移。PostgreSQL 原先运行，任务结束仍运行。

新增 17 项 source-resolution 测试与 6 项 owner-review 测试，覆盖原 S03/S04、
新的中英文名字、名字边界、肯定/否定限定词、假设/未知身份、容量退回、跨日旧来源、
当前目标不变、最终 provider messages、private→cloud 隔离、跨 owner 与撤回、
匿名材料篡改、选择错绑、重复/缺失选择、不可覆盖的回归 receipt。
原有纠正、时点、隐私和 owner isolation PostgreSQL 测试也全部通过。

- 既有 `scripts.benchmark_personal_context` 按 baseline `b5664e53...` 复跑：
  预算下原始经历保留 13/13；>256 Events、两年时间偏移、长文尾部、邻近纠正与
  歧义来源检查通过。这些旧能力是回归结果，不归功于本轮新修复。
- `evals.semantic_memory_benchmark` 保持 9/12 top-1，irrelevant admissions=0；
  deterministic baseline 4/12。不是 owner 回答质量评分。
- `pip check`、`compileall`、diff check 通过；专用测试库 `audit-provenance` 返回 `[]`。
  CLI 第一次仅因缺少其要求的测试 auth token 而未启动；使用临时、未落盘的专用
  测试 token 后审计通过，没有使用或修改生产 token。
- HTML 在 1100px/390px 无横向溢出；8 段、16 项选择、空表单阻止导出、构造选择
  导出及零 JS 错误已验证。真实页面未被代填；UI 导出测试使用不同 packet hash
  的独立构造材料，不能通过真实 owner packet 的回归导入校验。

当前解析依赖有限明确命名语法，不能覆盖任意自然语言指代。候选检索、来源数量和
Context budget 仍有限；不得声称完全召回或全局实体唯一性。需要实际 GPT/owner
对自然澄清、准确选人和无依据时的措辞进行后续验证。代码由本任务复核，未另委派
编码代理，也不冒称独立人类验收。

## Owner blind review 包

本机入口：
`var/targeted-recall-20260906/owner-review/owner-review.LOCAL_ONLY.html`。

从最终有效 A/B 主样本中选择 8 对有可辨差异的原始答案，覆盖 7 个对话家族，
不含生成重复或完全相同答案。选择考虑对话差异与场景多样性，不依照架构胜负；
因此这些选择用于定性产品回归，不再估算 Full/Simple 的无偏胜率。
每对重新随机 A/B，正文保留原始回答和可展开的 pre-target 证据、准确当时时钟。
页面不显示 Full/Simple、模型评分、评审理由、latency、成本或架构 key。

Owner 只评价两项：「哪个更像 HAVRE」「哪个让你更想继续聊」，每项可选 A、B、
差不多或无法判断。无后台、无外部资源或自动上传；点击导出才保存选择文件。
**当前 owner choices 为 pending，尚无真实 owner 回归结论。**

包 hash：`14c6a016cb346b9940d9ae3369b4188d520c811a79e2d422ae41c01bd6cf2d24`。
原始答案、证据、packet 和来源 key 各自绑定 hash，key 留在独立本机文件。
以后收到明确 owner 选择文件，可用：

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_owner_context_review record `
  --directory var/targeted-recall-20260906/owner-review `
  --choices <owner-exported-file> --output <new-local-regression-receipt>
```

只创建不可覆盖的 LOCAL_ONLY 产品回归 receipt；training_eligible=false、
cloud_eligible=false，没有训练、Memory/User Model、OA70 或生产策略自动导入。
本地文件提交本身不是身份认证签名，必须来自实际 owner 提交。

## 云端语义复测的审批边界

自动审批审查拒绝了新批次的云端生成：虽然任务允许本地修复与测试，审查要求明确
授权本批 payload、云端目的地与费用。被拒绝的 shell 未运行，云端调用为 0。
已向 owner 提交一个合并审批项；没有绕过审查或用另一目的地间接执行。

18 个拟调用：原 12 stress targets + 4 个反例的当前输入，及 S03/S04 两个 baseline。
固定 GPT-5.6-sol/medium、现有 Codex route；全部输入可在
`var/targeted-recall-20260906/cloud-review/payload-review.LOCAL_ONLY.html` 查看。
manifest SHA-256：`7f8f46a8cc36d3ed0f2d15dc68aba24120775a386e40c16df9b9197b16f40fdc`。
内容为构造来源及既有已授权 Identity/style，没有新增 owner 日常案例或 review 选择。
NORMAL、仅本次复测、training=false；USD quote 不可得，获准后需记录 usage。

另一次对父目录 ACL 的修改被自动审查拒绝；后续 UI 验证保持已有权限，不再尝试
修改 ACL。Owner review/cloud review 已有独立本机受限目录；页面验证未启动服务。

本轮不增加新架构，不为测试改 target，不训练或 promotion，不进行生产 rollout，
不 commit/push。新的云端授权或真实 owner 选择需另外明确接续，不能伪造完成证据。
