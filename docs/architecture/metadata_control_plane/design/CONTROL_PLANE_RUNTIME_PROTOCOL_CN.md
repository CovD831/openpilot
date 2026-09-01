# Metadata Control Plane 运行协议

> Status: Proposed L2 architecture
> Authority: Target runtime protocol; current Pi/runtime paths remain authoritative until migrated
> Owner: Control-plane runtime
> Supersedes: None
> Last reviewed: 2026-09-01

## 1. 目标

运行协议把 harness 已经具备的隐式执行能力与 OpenPilot 的显式控制分开：

- harness 负责一次模型 episode 内的推理和合法工具选择；
- control plane 负责权威状态、上下文治理、候选 admission、调度、证据、完成和恢复；
- 选择性上下文 projection 是可关闭优化，不是运行协议成立条件；
- 简单任务走 root-only 快路径，不为“显式结构”额外调用模型；
- 长任务在需要时一次只实例化一个后继，形成 JIT dynamic chain；
- top-k/tree 是可替换 policy，不改变运行权威协议。

本文的 `episode` 指一次由 OpenPilot admission 绑定的 execution attempt/visit 语义边界；具体
provider call、Pi tool loop 或 retry 如何映射由 adapter 声明，不能从 provider/model 名称猜测。

## 2. 参与者

```text
Application Use Case
TaskAuthority / Admission
State View Builder
Context Governance / Optional Optimization
Search Policy
Scheduler
Execution Engine (Pi)
Action Gateway
Evidence / Run Coordinator
Verification / Completion
Checkpoint / Supervisor
```

Search、context 和 model 都只能提交 proposal/view；Admission、Action Gateway、
Verification、Evidence 和 Checkpoint 保持各自 authority。

### 2.1 显式化预算

运行时的默认形态是 plain Pi/root-only，而不是先创建计划图。只有 typed boundary trigger
出现时，Control Plane 才允许生成结构 proposal：

- 需要跨 episode 持续存在的 dependency/continuation；
- permission、consent、scope 或 side-effect boundary；
- context source/freshness/fallback 无法在当前 governed view 内闭合；
- validation/completion/recovery 需要独立 authority；
- 当前选择会显著改变后续返工范围或不可逆成本。

普通局部推理、一次性下一步、模型在同一 episode 内已经筛掉的候选，继续由 Pi 拥有，
不持久化为 proposal/node。top-1 proposal 应优先复用当前 episode 的 bounded typed exit
payload；root-only 路径不得增加 candidate-generation provider round。

没有跨 episode、恢复、审计、门禁或当前已批准 consumer 的 metadata，不写入 durable
state。“未来可能有 consumer”本身不构成持久化理由；只有已批准 experiment/migration、
owner、expiry 和 removal gate 同时存在时，才可进入 experimental namespace。研究模式需要
观察 top-k 时，只能保存有界、redacted、可过期的 experiment evidence，不得成为生产恢复
依赖。

无 typed structural trigger 时，Search Policy、Scheduler 和 CandidateProposal 处于 absent
mode：不调用、不实例化、不持久化，而不是构造 no-op workflow。

## 3. 核心运行对象

运行对象、authority owner、port、当前表示和 maturity 的唯一对照见
[`CURRENT_TO_TARGET_MAPPING_CN.md` §5.1](CURRENT_TO_TARGET_MAPPING_CN.md#51-cross-view-mapping-与物理放置边界)。
本文只使用这些语义角色，不批准新的 public `MetadataKind`、store 或 registry。一个切片若
需要同时新增多个上述结构，默认视为边界尚未收窄，应先复用现有 owner 或拆分切片。

## 4. 主时序

```text
Task ingress
  -> normalize and admit task authority
  -> start/attach Run
  -> create or restore root NodeInstance
  -> build authoritative State View
  -> build governed Context View
  -> optionally apply verified Context Optimization
  -> run one harness episode
  -> append observations and tool receipts
  -> evaluate result / blocked / context / governance proposal
  -> verify candidate result
  -> commit closure OR admit one next action/node OR safe-stop
  -> checkpoint authoritative cursor
  -> repeat until root completion
```

顺序中的每一步可以由当前实现暂时承担，但不能合并 owner。例如 Pi `agent_end` 不等于
业务完成；业务完成必须由 completion/verification owner 基于 evidence 决定。

## 5. Root-only 快路径

默认进入 root node，不先调用“任务结构生成器”：

```text
root governed Context View
  -> optional verified Context Optimization
  -> Pi episode
      -> verified result       => root ClosureCommit
      -> context gap           => REQUEST_CONTEXT, same NodeVisit/new episode
      -> local tool progress   => continue within admitted harness budget
      -> structural need       => CandidateProposal
```

如果一次 episode 内完成，系统不得为了记录动态链而产生独立 successor provider call。
结构 metadata 可由运行时从已有 evidence 生成最小 root visit/closure record。

若 Pi 在当前 episode 内可以继续执行合法工具、读取已准入上下文或提交结果，Control Plane
不得把这些普通行为强制切成多个 durable node。只有第 2.1 节的 typed boundary trigger
成立，才允许从 root-only 提升到 JIT。

## 6. JIT 动态链

只有当前节点无法直接闭合且有 typed trigger 时，才暴露结构 proposal：

```text
ACTIVE NodeInstance A
  -> CandidateProposal B
  -> deterministic admission
  -> B becomes admitted NodeInstance
  -> checkpoint A suspended / B ready
  -> execute B
  -> B ClosureCommit
  -> recompute A residual
  -> resume A or propose next successor C
```

top-1 policy 下，实际执行轨迹始终是一条链。候选空间可以是浅树，但未选候选不是完整
节点，也不进入 active trajectory。

## 7. NodeInstance 生命周期

L2 只冻结生命周期边界，不批准新的全局 enum 或完整转换表。实现应优先映射现有
task/runtime/terminal status，并保持：

- `CandidateProposal` 不是 NodeInstance；admission 后才实例化；
- 同一串行 V1 最多一个 active node；
- 模型不能直接写 ready、terminal 或 supersession 状态；
- terminal completion 需要 ClosureCommit；reopen 创建新 revision，不原地改写历史；
- 已执行 evidence 在 supersession 后仍保留；
- suspended/blocked 必须有 typed blocker 和恢复、升级或终止动作；
- 非法或未知转换 fail closed，并记录 typed rejection。

用户取消、consent revoke、预算耗尽、lease 丢失和 provider abort 均只能阻止后续动作，
不能重写已经发生的 receipt。精确状态名称和转换矩阵属于 gated L3 candidate，由 J-T0、
J-T1 和 R0/R1 evidence 通过后再冻结。

## 8. NodeVisit

NodeVisit 是一次短模型 episode 的语义边界，至少能关联 run/node/revision、governed request、
observations/receipts 和 exit disposition。它默认是现有 request/response/tool evidence 上的
adapter-neutral view，不复制 transcript，也不预先批准新的 durable contract。具体字段由
J-T1/R0/R1 mapping 决定。

## 9. 动作面与动态暴露

普通执行继续由 Pi 的 admitted action surface 拥有。只有 dependency、decomposition、rework、
closure 或 governance 的 typed trigger 出现时，才可额外暴露对应的结构 proposal；无 trigger
时相关能力必须 absent，而不是 no-op 调用。精确 action 名称、tool schema、cooldown 和次数
预算属于 J-T0 通过后的 L3 设计。

## 10. Proposal 与 admission

所有 proposal 经过同一逻辑：

```text
schema validation
  -> source/evidence binding
  -> scope and permission check
  -> dependency/readiness check
  -> budget/width/depth check
  -> duplicate/no-progress check
  -> accept | partially_accept | reject | request_evidence
```

AdmissionDecision 必须可审计。拒绝 proposal 后默认继续当前合法执行，除非存在独立安全
或权限冲突。

## 11. Scheduler

V1 保持单 Agent 串行和最多一个 active node。ready 选择必须 deterministic、尊重 admitted
dependency/recovery/closure boundary，并能证明必要工作不会无限等待。精确优先级、age/bypass
阈值和 replan 策略不在 L2 冻结；它们只有在 JIT 实验暴露真实多 ready-node 需求后才进入
L3。依赖不表示并发，多 durable pending branches 或多模型 episode 并行需要独立 ADR 和实验。

## 12. Result、Closure 与继续条件

模型只提交 result/closure candidate。运行时执行：

```text
candidate result
  -> required evidence present?
  -> hard validation / acceptance
  -> side-effect receipts complete?
  -> completion policy
      -> ClosureCommit
      -> typed rework
      -> blocked/safe-stop
```

ClosureCommit 至少绑定 node/revision、输入 freshness、public outputs、acceptance result、
evidence、receipt 和 child closure refs。ClosureProjection 只是下游上下文视图。

## 13. 失败和 fallback

| Failure | Required behavior |
| --- | --- |
| Context Governance 失败/身份不一致 | 不发送 request，修复 governed source baseline 或 safe-stop |
| Optional Context Optimization 不完整/不可验证 | 回退 governed source baseline，不影响基础治理 |
| Invalid candidate proposal | bounded rejection/recovery，不实例化 node |
| Search policy failure | 保持当前 node 或回退 top-1/static policy |
| Pi/provider crash before side effect | 按 transport/recovery policy 重试或阻塞 |
| Durable receipt but no validation | same-Run indeterminate/reconciliation |
| Unknown completion/freshness | 不得 CLOSED/current |
| Checkpoint identity mismatch | fail closed，不创建平行恢复事实 |

## 14. 目标 port payload

第一阶段只冻结 payload 不变量：typed、authority/evidence bound、budgeted、versioned，并让
execution adapter 暴露实际可观测 request components 和 conformance level。port 角色由
current-to-target mapping 拥有；精确方法签名、manifest/capability/receipt 类型由 Phase 1
inventory、G0–G7 和对应 L3 slice 决定。`ContextGovernanceRole` 仍是跨 owner 责任，不自动
批准中央 request service 或重复 metadata contract。

## 15. V1 interface freeze gate

V1 核心实现只允许冻结 `TaskAuthority`、`StateView`、`Admission`、`ExecutionEngine`、
`Action`、`Verification`、`Evidence` 和 `Checkpoint` seam；Context Governance 作为跨 owner
conformance responsibility 绑定到 request assembly 和 execution adapter。`SearchPolicyPort`
不属于 V1 必选接口。

每个核心 seam 在编码前必须满足
[`DOCUMENTATION_GOVERNANCE_CN.md` §2.2](../DOCUMENTATION_GOVERNANCE_CN.md#22-l3-interface-specification-minimum)
的完整 L3 字段，并绑定 current implementation candidate、contract tests、fault cases 和
cutover/rollback。只有语义名称、`Any` payload 或 test double 的接口不算冻结完成。本节只
定义接口冻结条件；V1 产品边界的唯一 owner 是
[`TARGET_ARCHITECTURE_CN.md` §2.10](../TARGET_ARCHITECTURE_CN.md#210-control-plane-v1-产品边界)。

跨 seam 集成必须证明同一 task/run/revision/authority identity 从入口贯穿 request、action、
receipt、verification、closure 和 checkpoint，不能由 composition glue 静默转换成第二套事实。

## 16. Claim routing

本设计拥有 `RT-C01`、`RT-C02`、`RT-C03`、`RT-C04`、`RT-C05` 的语义；status、evidence 和 adoption gate 只在
[`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。

本协议受
[`ADR-0002`](../adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md) 的 episode ownership、
complexity budget 和逐级 adoption ladder 约束。JIT/Search 被实验否决时，root-only +
governed context + durable authority 仍是完整成立路径。

## 17. 未决问题

- PlanEpoch、NodeInstance 和现有 TaskGraphNode identity 如何绑定？
- NodeVisit 是否只需 derived record，还是存在独立持久化生命周期？
- 一次 Pi episode 内多轮 tool call 与一个 NodeVisit 如何精确对齐？
- AdmissionDecision 与 checkpoint 的 durable boundary 如何实现？
- GovernanceSignal 最小 schema 和重复抑制键是什么？
