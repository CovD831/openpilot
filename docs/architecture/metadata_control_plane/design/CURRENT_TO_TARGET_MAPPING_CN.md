# 当前实现到 Metadata Control Plane 的迁移映射

> Status: Proposed L2 architecture
> Authority: Current-to-target mapping; current code and contracts remain executable truth
> Owner: Architecture / migration
> Supersedes: None
> Last reviewed: 2026-09-01

## 1. 目的

本文回答三个工程问题：

1. 当前哪些能力应该保留，而不是在“新架构”名义下重写；
2. 哪些热点模块需要通过 ports 和单向依赖逐步收缩；
3. 每个目标组件应从当前哪个 owner 迁移出来。

它不批准删除旧路径，也不把目标模块名当作已经实现。

## 2. 当前结构快照

2026-08-31 对当前 dirty worktree 的只读 AST/文件核验结果：

- `Code/src` 有约 230 个 Python 文件、89,645 行；
- `Code/src/metadata` 约 5,559 行；
- 在 `Code/src` 可解析 Python import graph 中未检测到 cycle；这不覆盖 Pi TypeScript
  sidecar、运行时动态导入或仓库外依赖；
- `metadata/` 未反向依赖业务 controller；
- 已存在一个很小的 `autonomous_iteration/ports.py` 和
  `HarnessApplication` facade，可作为 control-plane seam 的种子；
- 权限、动作、证据和恢复已经有可复用的严格边界，而不是从零开始。

主要热点：

| File | Approx. lines | 当前压力 |
| --- | ---: | --- |
| `autonomous_iteration/runtime_controller.py` | 5,339 | 路由、状态、工具、恢复和上下文逻辑集中 |
| `autonomous_iteration/intelligent_autopilot.py` | 4,317 | 旧入口、迭代和恢复责任过宽 |
| `core/provider_tool_roundtrip.py` | 3,963 | provider transport、tool loop 和结果映射耦合 |
| `autonomous_iteration/agents/tool_planning_executor.py` | 2,909 | planning、provider action 和执行编排混合 |
| `metadata/agent_runtime.py` | 2,753 | 大量相邻 runtime value/contract 聚集，演化压力高 |
| `core/tool_event_loop.py` | 2,498 | provider/tool 循环和错误恢复逻辑集中 |
| `memory/context_builder.py` | 1,823 | source loading、compaction、selection、compatibility 输出混合 |

行数本身不是删除理由。它只说明必须通过行为切片和 ports 收缩，不能在一个提交里重写。

## 3. 当前可复用资产

### 3.1 Metadata contracts

`Code/src/metadata/` 保留为 typed contract owner。迁移目标是补 registry、migration 和
usage audit，不是把 metadata 移入 controller 或 graph database。

### 3.2 Evidence Core 和 RunCoordinator

`evidence_core/`、`RunCoordinator` 已区分 raw observation、canonical/derived event、Run
identity、attach 和 terminal decision。目标架构复用其事实历史和 idempotency 边界。

### 3.3 Task admission、Action Gateway 和 completion

`task_admission.py`、`action_gateway/gateway.py`、`verification/completion.py` 已分别拥有：

- task scope 和 validation admission；
- action-time permission/consent/read-before-write/receipt 检查；
- 基于 evidence 的 completion decision。

它们应变成明确 ports 后面的当前实现，不被 search/context policy 绕过。

### 3.4 Context Assembly

`ContextCandidate`、`ContextAssembler`、`MemoryContextBuilder`、compaction binding 和
derived projection 已提供 source governance、token budget、selection evidence 和 atomic
replacement 基础。目标是把 source adapters、selectors、projection 和 rendering 职责拆开，
不重建第二套上下文系统。

### 3.5 Pi execution adapter

`HarnessApplication`、`PiRpcEngine` 和 Pi tool bridge 已把 Pi 限定为模型回合和 execution
engine。它们保留为第一个 `ExecutionEnginePort` adapter。

### 3.6 Checkpoint / recovery

`RuntimeCheckpointStore`、Supervisor、Pi mutation reconciliation 和 session cursor 已覆盖
多种故障窗。目标是把新的 node/revision identity 接入它们，而不是并行建设第二套 resume。

## 4. 目标组件映射

| 当前 owner | 目标职责 | 迁移动作 |
| --- | --- | --- |
| `metadata/` | Metadata Kernel + registry/migration descriptors | 保留并小步扩展 |
| `evidence_core/`, `RunCoordinator` | Durable Evidence / Run history | 保留，补 target event vocabulary |
| `autonomous_iteration/ports.py` | Control-plane ports | 扩展严格 typed signatures，移除 `Any` 扩散 |
| `HarnessApplication` | Application facade | 保留为薄 use-case facade |
| `task_admission.py` | AdmissionPort implementation | 保留，不吸收 search policy |
| `action_gateway/` | Governed ActionPort | 保留权限和副作用 owner |
| `verification/completion.py` | Verification/CompletionPort | 保留最终业务终态 owner |
| `memory/context_assembly/` | Context Governance + optional optimization internals | 先稳定 source/trust/freshness/budget/fallback，再按证据拆 selector/projection/rendering |
| `runtime_controller.py` | Legacy orchestration | 通过 strangler slices 逐步抽出 use cases |
| `intelligent_autopilot.py` | Legacy iteration facade | 新入口覆盖后收缩，不作为目标内核 |
| `tool_planning_executor.py`, `tool_event_loop.py` | Legacy provider/tool orchestration | 将 transport、policy、mapping 分离到 ports/adapters |
| `checkpoint_store.py`, Supervisor | CheckpointPort | 保留并接入 revision/cursor identity |
| `engines/pi_sidecar.py` | Pi `ExecutionEnginePort` adapter | 保留为可替换 adapter |
| `ui/` | UI adapter | 只消费 application view，不拥有 runtime state |

## 5. 目标 ports

目标不是立刻创建十个新模块，而是让下列语义 seam 逐步稳定：

```text
TaskAuthorityPort
  normalize/admit task authority and acceptance

StateViewPort
  read authoritative facts and build bounded derived views

SearchPolicyPort
  propose bounded candidates from a read-only state view

AdmissionPort
  accept/reject/supersede candidate proposals

ExecutionEnginePort
  run one model episode with an admitted request

ActionPort
  execute admitted tools and return durable receipts

VerificationPort
  assess outputs and construct completion/closure decisions

EvidencePort
  append observations, canonical events and derived mappings

CheckpointPort
  persist/attach authoritative recovery identity and cursor
```

第一阶段可以由当前类实现这些 ports。禁止为了端口纯度复制现有事实或一次性重排全部包。
`TaskAuthorityPort` 只是访问当前 task/admission authority 的 seam，不是新的 authority owner。

Context Governance 先作为 cross-cutting conformance role：memory 提供 admitted candidates，
execution adapter 暴露其可观测 request components/conformance level，各 authority owner 提供
控制事实。G0–G7 和 inventory 前不批准中央 `ContextBoundaryPort`；optional selection policy
可以作为独立 experiment/shadow。

### 5.1 Cross-view mapping 与物理放置边界

下表只对齐语义视图，不批准新 package、store 或 public contract。ME0 inventory 和 X1
真实切片完成前，不创建通用 `control_plane/` 包；首批切片留在现有 authority owner 内，只有
通过 port admission gate 的跨边界 seam 才能独立放置。

| Semantic object/view | Authority owner | Target responsibility | Port/seam | Current implementation candidate | Maturity / gate |
| --- | --- | --- | --- | --- | --- |
| `TaskAuthority` | Task / `TaskAdmissionGrant` owners | Metadata Kernel + Governed Execution | `TaskAuthorityPort` | task models + `task_admission.py` | Current; ME0 inventory |
| `Run` | Evidence Core / Run Coordinator | Durable State and Evidence | `EvidencePort` | existing Run/event identity | Current/adopted |
| `PlanEpoch` | current plan/task revision owner | Derived State + Governed Execution | `StateViewPort` | existing revision/plan identity | Candidate; J-T1/R0 |
| `NodeInstance` | admitted task/runtime owner | Governed Execution | `AdmissionPort` + state view | existing task graph/runtime status view | Gated; J0–J4 |
| `NodeVisit` | Run/evidence owner | Governed Execution + Durable Evidence | `ExecutionEnginePort` / `EvidencePort` | request/response/tool event references | Gated; J-T1/R0/R1 |
| `CandidateProposal` | no authority before admission | Pluggable Search Policy | `SearchPolicyPort` / `AdmissionPort` | experiment-only typed value | Dormant outside J-T0/S routes |
| `AdmissionDecision` | current admission owner | Governed Execution | `AdmissionPort` | `task_admission.py` decision/evidence pattern | Current; equivalence gate |
| `GovernedContextView` | source fact owners; view is derived | Context Boundary Governance | `StateViewPort` + execution adapter seam | memory/context assembly | G0–G7 conformance |
| `ExecutionRequest/Observation` | request authority + Evidence Core | Governed Execution | `ExecutionEnginePort` / `EvidencePort` | Pi/provider request and observation records | Current; J-T1 mapping |
| `VerificationDecision` | verification/completion owner | Governed Execution | `VerificationPort` | `verification/completion.py` | Current/adopted |
| `ClosureCommit` | completion + Evidence Core | Durable State and Evidence | `VerificationPort` / `EvidencePort` | result, validation and receipt references | Candidate reuse; RT-C05 |
| `CheckpointCursor` | checkpoint/Supervisor owner | Durable Recovery | `CheckpointPort` | checkpoint store + Supervisor lease/cursor | Current; R0/R1 hardening |
| derived graph/state view | no canonical writer; rebuildable | Derived Graph / State View | `StateViewPort` | current indexes/views | Conditional; ME6 only |

“Current implementation candidate”表示优先复用位置，不是最终 package layout。具体文件移动、
Protocol 名称和 constructor wiring 只在已接受的 L3 slice 中决定。

### 5.2 V1 composition freeze

V1 产品边界的唯一 owner 是
[`TARGET_ARCHITECTURE_CN.md` §2.10](../TARGET_ARCHITECTURE_CN.md#210-control-plane-v1-产品边界)；
本节只定义组合方式。ME0 inventory 完成后、首个 V1 runtime slice 编码前，必须在对应 L3
规格中冻结：

- 唯一 public entry 和 application facade；
- composition root 以及 stores、ports、adapters、policy/config 的创建 owner；
- `TaskAuthority`、Run/Evidence、Context Governance、Pi、Action、Verification 和 Checkpoint
  的实际 binding；
- provider capability、reasoning/config 和 conformance profile 的加载位置；
- startup/shutdown、lease、cancel 和 recovery attachment 生命周期；
- production adapter、recorded/replay adapter 和 test double 的相同 contract 边界；
- 每个新 package/file 对应的现有 owner、被删除依赖和 rollback path。

该冻结产生的是一个受切片约束的 package/composition map，不是预先创建通用
`control_plane/` 目录。若某个责任可由现有 owner 内的窄 helper/typed method 完成，则不得为
目录对称性额外创建 module 或 pass-through port。

### 5.3 Port admission gate

一个语义 seam 只有同时满足以下条件才值得成为显式 Protocol/module：

- 跨越真实 module/adapter 边界；
- 能消除当前反向依赖或宽 `Any` 传播；
- 至少有第二个真实 adapter/owner boundary、shadow comparator 或明确替换需求；test double
  不能单独证明 production port；
- 输入输出能用现有 typed contracts 表达；
- 引入后调用方需要理解的概念数下降，而不是只增加转发层。

否则保留直接调用或窄 helper。Phase 3 的成功指标包含删除依赖和 controller 分支，不是
创建 port 数量。

### 5.4 Complexity / contraction gate

每个 migration/cutover slice 必须提交 net complexity ledger，同时记录新增和删除：

- concepts、owners/authorities；
- dependencies、controller branches、宽 `Any`/dict boundaries；
- adapters、fallbacks、operational paths 和 call depth；
- producer/consumer 和旧恢复入口。

如果新旧路径必须暂时并存，切片必须记录旧路径 owner、runtime usage、fallback、退出条件
和删除复审点。experiment/shadow 必须不拥有 authority、可整体删除并有 TTL/sunset。禁止
以“兼容”为由无限期维护双 controller 或双 authoritative writer/store。

架构收缩的主要指标是调用方需要理解的概念数、旧 consumer 数、跨层依赖、controller
分支和宽类型传播下降；新增模块数、port 数或 MetadataKind 数不是成功指标。

## 6. 单向依赖目标

```text
ui / cli
  -> application use cases
      -> control-plane services
          -> metadata contracts
          -> ports

adapters
  Pi / provider / tool / filesystem / evidence store / checkpoint store
      -> implement ports

policies
  search / optional context selection
      -> consume read-only views
      -> return proposals or projections
```

Context Governance 属于 request/admission boundary，不是可替换 selection policy。
`policies` 不依赖 Action Gateway 具体实现；adapter 不构造业务 authority；metadata 不导入
任何 service。

## 7. Strangler 迁移顺序

1. **Inventory**：登记当前 producer/consumer 和 public entry；
2. **Observe**：在旧路径旁生成 target typed view，不改变决策；
3. **Compare**：旧/新 view 和 decision paired validation；
4. **Route one slice**：只迁移一个 read-only 或 completion slice；
5. **Default one use case**：保留旧 reader/fallback；
6. **Usage-zero**：确认旧 producer/consumer 和恢复入口归零；
7. **Delete separately**：删除作为独立、可恢复的变更。

上述顺序在每个切片内循环执行，而不是等所有目标模块完成后再统一进入 legacy cleanup。
没有 usage-zero 或独立责任证据的旧路径不能删除；没有删除计划和 usage 观测的新路径也
不能无限期保留。

第一批不应选择 mutation 全链路。优先顺序是 read-only Run facade、State View、Context
Governance conformance observation、optional Context Optimization shadow、Completion mapping，
再进入 mutation/recovery。

## 8. Claim routing

本设计拥有 `MAP-C01`、`MAP-C02`、`MAP-C03`、`MAP-C04` 的语义；status、evidence 和 adoption
gate 只在 [`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。

## 9. 明确不做

- 不按文件行数直接删除模块；
- 不建立第二个公开 CLI/runtime 路径；
- 不让新 ports 用宽泛字典重新包装现有 typed contracts；
- 不在 Phase 0B 修改生产依赖方向；
- 不把实验 runner 搬进 `Code/src`。
- 不把 port 数量、模块数量或 metadata object 数量增长当成架构完成度。
- 不建立长期并存的新旧 controller、store 或恢复权威。

本映射遵循
[`ADR-0002`](../adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md)：Control Plane 只显式化
跨 episode、权限、副作用、验证、上下文、持久化和恢复边界；Pi 保留 episode 内普通推理
和工具选择。

迁移与物理表示边界遵循
[`ADR-0005`](../adr/ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md)：允许有界、
可重建、非权威 shadow representation，但同一事实始终只有一个 authoritative writer。
