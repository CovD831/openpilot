# Metadata Control Plane 双向钢人论证

> Status: Completed analysis
> Authority: Deliberation evidence; architecture/evidence/ADR owners decide adoption
> Owner: Architecture review
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 规则

双方使用同一事实集：当前代码、L2 design、现有 E03/E04 evidence、缺失 telemetry 和
对抗性审查结果。支持方不能把 candidate 写成 implemented；反对方不能假设现有系统没有
权限、Evidence Core、Context Assembly 或 recovery 能力。

## 2. 支持方的最强论证

### 2.1 普通 harness 解决执行，不解决长期权威

Pi 等 harness 擅长把模型、工具和环境反馈组织成有效轨迹，但它不应成为项目任务事实、
用户权限、验证、Evidence Core 和跨进程恢复的唯一 owner。长程任务真正困难的是：进程
中断后还能知道什么发生过、什么被允许、什么已验证、哪些事实失效。Metadata Control
Plane 正好补这个层，而不是重复 agent loop。

### 2.2 这不是从零搭平台

当前系统已经有 strict metadata、TaskAdmissionGrant、Action Gateway、Evidence Core、
RunCoordinator、Pi adapter、ContextCandidate/Assembler 和 recovery。新架构把已有边界变成
单向依赖并收缩巨大 controller，风险远小于重新选择 LangGraph/Temporal 或完全重写。

### 2.3 Metadata evolution 是长期差异化能力

Agent 系统会不断增加 permission、recovery、context、evidence 和 policy facts。没有
registry、migration、deprecation 和 usage audit，metadata-first 最终只会变成 metadata
堆积。可执行 evolution kernel 能让这个项目跨 harness、模型和版本保持一致，这比某个
planner prompt 更耐久。

### 2.4 Context Projection 已有最强局部证据

现有实验已显示 local + on-demand 可以在受控可解决场景保持质量并显著减少 model-facing
context proxy；hidden/stale evidence 可以恢复，不可用时 safe-stop。即使最后不实现动态树，
source-governed context projection 也可能单独产生产品价值。

### 2.5 显式候选的价值不是“模型不会选择”，而是选择可治理

模型内部本来就会形成隐式分叉。显式化的合理目标不是保存思维链，而是把最终候选变成
body-free、可验证、可预算、可拒绝和可恢复的 proposal。Template/Proposal/Node 分离使
未选候选接近零执行成本，同时让错误选择、返工和审计有结构化依据。

### 2.6 搜索算法被正确降级为可选 policy

架构不绑定 MCTS/LATS/RAP。它只要求 search policy 读取相同 state view、输出 proposal，
不能写 authority。若 top-k/tree 无收益，可以永久停在 root-only/top-1；这说明 pluggability
降低锁定风险，而不是强迫复杂化。

### 2.7 方案已经具备可证伪性

Evaluation Plan 现在允许 registry、graph、ports、JIT、tree、World Model 和 local rework
被 killed。一个能明确写出停止条件的架构比只能不断加机制的方案更可信。

### 2.8 支持方成立的必要条件

- control plane 保持薄，不复制 harness loop；
- 新 seam/contract 必须替代旧依赖，而不是并存；
- root-only 无额外 provider round；
- required facts、permission、receipt、validation 和 recovery 保持现有 owner；
- Context/JIT 的真实总成本有 provider telemetry；
- tree/world-model 永远不是内核前置。

## 3. 反对方的最强论证

### 3.1 动态链早已由 harness 隐式实现

普通 coding harness 每轮根据环境决定下一工具和下一步，本质上已经产生动态执行链。把
选择显式化为 Candidate/Admission/NodeVisit 可能只是把模型一次内部决定变成多次 schema、
持久化和治理动作，没有增加任务质量，却增加 token、延迟和故障点。

### 3.2 Metadata-first 可能演变成第二个 workflow engine

Task、Run、PlanEpoch、NodeInstance、NodeVisit、CandidateProposal、AdmissionDecision、
ClosureCommit、Projection、Checkpoint 等名词足以重建一套 LangGraph/Temporal。即使文档
说“semantic object 不等于 contract”，实现团队仍可能逐个建表、建 store、建 service，
最终比当前 controller 更难理解。

### 3.3 Registry 和 derived graph 可能成为新的漂移源

代码 model、catalog、registry、usage telemetry、derived graph 和文档都描述 metadata。
如果 registry 不能自动从代码验证，它就是第二 schema truth；如果能完全自动生成，又可能
只是一份昂贵索引，没有独立价值。跨 owner graph 查询是否真实高频，目前没有证据。

### 3.4 选择性上下文把显性成本换成隐性风险

完整历史虽然昂贵，但简单。局部 projection 需要正确分类 required facts、freshness、source
trust、dependency 和 fallback。任何遗漏都可能让模型在看似干净的小窗口中稳定地产生错误。
消费审计也很难证明某事实对模型有因果作用。

### 3.5 搜索理论未必能迁移到 coding harness

MCTS/RAP 在可模拟、可评分、短 horizon 环境中更自然。真实 coding task 的下一状态依赖
工具、编译、测试和不可逆副作用；LLM world model 既昂贵又可能错误。把它放进架构会吸引
大量研究工程，却未必超过“模型 + 工具 + 测试”的直接循环。

### 3.6 当前证据不足以支撑重构规模

E03/E04 多数是 offline、typed consumer、same-session 或 proxy telemetry。它们支持局部
mechanism，不证明独立 provider 质量、总 token、延迟、维护成本或真实长任务收益。现在就
围绕这些结果重构 89k 行系统，可能是用实验假设驱动组织结构。

### 3.7 真正问题可能只是几个大文件和旧路径未删除

当前最直接的债务是 2k–5k 行热点模块和多个旧 controller。最有效办法可能是删除旧入口、
抽取纯 helper、统一 Pi 路径和缩小 Context Builder，而不是先设计 35 个 Claim 和十个 ports。

### 3.8 Provider 能力进步可能削弱收益

更长、更便宜的 context、更可靠的 tool use 和 provider-native caching 可能降低自建 context
selection/search 的价值。长期维护 control plane 的成本可能高于节省的 tokens。

### 3.9 反对方成立的条件

- registry/graph 没有真实重复查询或删除收益；
- ports 只做转发，旧 controller 长期共存；
- root-only 仍产生治理调用；
- selective context 无法证明 required-fact closure；
- JIT/tree 没有真实 provider 总收益；
- recovery revision 无法原子提交；
- 团队主要精力转向维护框架而不是完成用户任务。

## 4. 综合裁决

双方最强论证并不要求在“完整架构”与“全部放弃”之间二选一。它们共同指向分层裁决：

| Layer | Current judgment | Why |
| --- | --- | --- |
| Metadata envelope、authority、admission、evidence、recovery | **继续** | 已存在且解决真实安全/恢复问题 |
| Metadata evolution inventory/migration/deprecation | **优先验证** | 是 metadata-first 可持续性的必要条件 |
| Thin derived state/context view | **条件继续** | 有局部价值，但必须有界、只读、可回退 |
| Purpose-specific Context Projection | **最值得继续实验** | 当前局部 evidence 最强，能独立产生价值 |
| Explicit top-1 JIT chain | **保持 candidate** | 必须证明超过 harness 隐式链的净收益 |
| top-k/tree/DAG | **后置** | 只有 JIT 和候选低成本先成立才有意义 |
| MCTS/LATS/RAP World Model | **纯可选研究** | 不属于产品内核，S5 失败即可永久不上线 |
| General graph authority / second workflow engine | **拒绝** | 与单一 authority 和薄控制平面冲突 |

## 5. 最窄可成立架构

如果把所有未经证明的部分拿掉，仍然合理的目标是：

```text
Stable typed metadata and evolution rules
+ current Evidence/Admission/Action/Completion/Recovery owners
+ bounded read-only state views
+ source-governed context projection with fallback
+ Pi as replaceable execution engine
```

这一最窄版本不要求显式动态链、树、DAG、MCTS 或 World Model。只有实验显示增量价值时，
search policy 才作为插件加入。

## 6. 决策规则

1. 先做 ME0/ME3/ME4/ME6，验证 metadata evolution 和 derived view 是否值得；
2. 再做 C5/C6，确认安全/full-request 预算；
3. J2 先证明 root-only 零额外 round；
4. J0–J4 证明显式 top-1 相对隐式链的质量/恢复/总成本价值；
5. 只有 J 组通过才运行 S0–S4；
6. 只有 bounded tree 有真实价值才考虑 S5 World Model；
7. 任一 kill criterion 触发，就保留更窄层级并停止扩张。

## 7. 最终立场

钢人后的结论是：**项目方向值得继续，但应被定义为薄的 metadata control plane，而不是
新的通用 agent framework。** 最值得投入的是 metadata evolution、现有 authority/evidence/
recovery 的统一和可验证 context projection；显式 JIT 尚未定案，树与 World Model 必须继续
后置。
