# Metadata Control Plane 第四轮最终双向钢人论证

> Status: Completed final analysis
> Authority: Final Phase 0B deliberation evidence; adopted architecture remains in ADR/L1/L2 owners
> Owner: Architecture review
> Supersedes: None; final steelman before evidence work
> Last reviewed: 2026-08-31

## 1. 最终问题

经过三轮修订，问题不再是“这个架构听起来是否合理”，而是：

> 是否已经找到一个足够小、即使所有 optional experiments 失败仍有价值，并且不会阻止
> 当前系统局部清理的架构基线？

## 2. 支持方的最终最强论证

### 2.1 最小内核不再依赖研究型机制

最终内核只依赖现有 typed authority、permission、Evidence Core、completion、recovery、
metadata evolution 方法和可观测 context conformance。Selective Context、JIT、tree、MCTS、
World Model 和 general graph 全部可以失败并被删除。

### 2.2 架构处理的是已存在的真实责任

当前代码已经有 ContextCandidate、ContextAssembler、TaskAdmissionGrant、Action Gateway、
RunCoordinator、Pi adapter、completion 和 recovery。重构不是创造这些责任，而是防止它们
继续散落在大 controller、provider path 和兼容分支中。

### 2.3 Metadata evolution 即使独立存在也有价值

owner/consumer inventory、历史读取、migration、deprecation 和 usage-zero 能直接回答当前
metadata 如何增删改。它不依赖 token 节省或树搜索，是项目最稳定的长期竞争力候选。

### 2.4 Context 保证已经回到诚实边界

OpenPilot 不再声称控制任意 harness、全部 provider internals、完整历史或未知事实。它只对
admitted/observable/supported route 的 declared facts、permission、freshness、budget 和
fallback 提供分级 conformance。这是可验证合同，不是全知承诺。

### 2.5 迁移门能抵抗“新旧系统永久共存”

net complexity、single authoritative writer、usage-zero 和 separate deletion 允许安全 shadow，
又要求最终切掉无独立责任的旧路径。它比“先建新架构，以后再清理”更可执行。

### 2.6 架构允许自己失败

ME、Context Optimization、JIT、Tree、World Model、derived graph 和 local rework 都有明确的
kill/fallback。失败不会被解释成“还要再加一层”，而是回退更窄架构。

## 3. 反对方的最终最强论证

### 3.1 文档规模本身仍是风险

30 份 program/experiment 文档、35 个 Claim、多组实验和五个 ADR，可能让团队在实现前投入
过多治理成本。当前最直接的问题仍可能只是大文件、旧入口和重复 provider paths。

### 3.2 许多所谓新能力已有实现种子

ContextAssembler 已 fail closed，Pi 已禁用默认 context/tools，reasoning capability 已有
profile，Evidence/permission/recovery 已存在。最有效路线可能是直接修补和删除，而不是再造
Control Plane interfaces。

### 3.3 Conformance 可能没有足够可观测性

如果 Pi/provider 不暴露完整 request manifest，Context Governance 只能覆盖 OpenPilot 提供的
prompt 片段。低等级 conformance 是否值得额外 metadata/receipt，需要真实成本证明。

### 3.4 Metadata evolution 流程可能过重

registry、catalog、impact note、migration corpus、usage telemetry 和 ADR 可能让普通字段
变更变慢。若 2–3 个真实 contract pilot 没有减少缺陷或删除成本，应停止自动化扩张。

### 3.5 动态链/树仍可能吸引过量注意力

即使被写成 optional，详细的 Candidate/Node/Search 文档仍可能让实施资源偏向研究机制，
而不是 metadata inventory、恢复和旧路径收缩。

### 3.6 净复杂度没有天然客观标尺

concept、owner、branch、dependency 和 call depth 权重不同。ledger 仍可能被选择性解释，必须
与真实调试、回滚和运行路径证据结合。

## 4. 对反对方的最终回应

| Objection | Final response | Stop condition |
| --- | --- | --- |
| 文档过多 | 文档已冻结；后续只由 evidence/implementation contradiction 触发修改 | 不再进行第五轮纯观点审查 |
| 已有实现种子 | 优先复用；新 port/contract 必须通过 X3 和 inventory | pass-through/test-double-only 即拒绝 |
| request 不可见 | G0/G5 诚实分级，unsupported 不冒充 fully governed | 无有用 conformance level 就保留当前 builder |
| evolution 过重 | 只 pilot 2–3 个真实高压 contract | 无 drift/delete/recovery 收益就保留 models + catalog |
| JIT/tree 分散资源 | 它们在 ME/G/X 后，且 default-off | J gate 未过不进入 S 组/production |
| ledger 可操纵 | 同时报告 before/after trace、owners、fallback、rollback 和 usage | 无净收益就撤销新 seam |

## 5. 最终最窄可成立产品

```text
Provisional typed metadata envelope
+ executable evolution discipline
+ current task/admission/action/completion authorities
+ durable evidence and recovery
+ observable context-governance conformance
+ Pi/current harness as replaceable execution adapter
```

这个版本不需要新的任务图、显式动态链、选择性上下文、树搜索或 World Model。它的价值
是让长期事实、权限、请求边界、证据和恢复不随 provider/harness 漂移。

## 6. 实验失败时的最终形态

| Failed route | Retained system |
| --- | --- |
| Registry automation | Pydantic models + catalog + manual impact note |
| Context request manifest | 当前已验证 request builder + 明确低等级 conformance |
| Selective Context | governed source baseline |
| Explicit JIT | plain Pi/root-only |
| Tree/World Model | top-1 或无显式 search |
| Derived graph | direct refs/local views |
| New ports | current direct narrow calls/helpers |
| Local rework | conservative parent/full-task validation |

任何一项失败都不要求建立补偿性框架。

## 7. 最终建议顺序

```text
X0 reviewable baseline
  -> ME0/ME3/ME4 inventory
  -> G0/G1/G2 context evidence
  -> ME1/ME2/ME5 real-contract pilot
  -> G3–G7 conformance/cost/privacy
  -> X1–X4 migration spikes
  -> J-T0/J-T1
  -> J0–J4 only if still justified
  -> conditional ME6 and S routes last
```

生产实现只能从已通过 gate 的最小切片开始，并在同一切片提交 net contraction、tests、文档和
rollback evidence。

## 8. 最终裁决

正反双方共同允许冻结当前架构，因为：

- 最小架构不依赖任何尚未证明的 optional mechanism；
- 所有重要不确定性都有实验、spike、fallback 或 kill path；
- 失败不会强迫继续扩大架构；
- 第一批工作是 read-only inventory/evidence，不是重写生产系统。

最终立场：**停止继续抽象讨论，冻结 Phase 0B，进入 evidence-first 验证。** 只有实验或
真实实现证据推翻当前假设时，才重新打开架构决策。
