# ADR-0002: 将目标收缩为薄 Metadata Control Plane

> Status: Accepted for architecture planning
> Authority: Architecture constraint; it does not authorize production behavior changes
> Owner: Architecture
> Supersedes: None; it narrows ADR-0001 without replacing its incremental-refactor decision
> Last reviewed: 2026-08-31

## Context

双向钢人论证确认了两组同时成立的事实：

- metadata authority、admission、evidence、completion、checkpoint 和 recovery 解决了普通
  harness 不应独自拥有的长期控制问题；
- harness 已经能够隐式生成执行链，若 OpenPilot 显式化每个内部选择，会形成第二套
  workflow engine、额外模型调用和大量重复 contract/ports。

因此，项目必须保留 metadata-first 的长期优势，同时限制显式控制的范围和复杂度。

## Decision

### 1. 最小成立架构

OpenPilot 的必要内核收缩为：

```text
Stable typed metadata and evolution
+ current task/admission/action/completion authorities
+ durable evidence and recovery
+ bounded read-only state views
+ source-governed context projection with fallback
+ Pi as replaceable execution engine
```

显式 JIT、top-k、tree、DAG、MCTS/LATS/RAP World Model 都不是项目成立的前置条件。

### 2. Episode ownership

Pi/harness 继续拥有一次 admitted episode 内的普通推理、工具选择和局部下一步。Control
Plane 只在以下边界显式化：

- 跨 episode 的 durable dependency 或 continuation；
- permission/consent/scope；
- context budget、source、freshness 和 fallback；
- provider/tool observation 和不可逆副作用；
- validation/completion；
- checkpoint/resume/reconciliation；
- 会显著影响未来返工成本的 admitted strategy choice。

没有跨边界消费者的内部选择不持久化。

### 3. Complexity budget

- semantic object 不自动成为 public contract/store/service；
- CandidateTemplate 必须先复用 PlanningSurface/Skill/ToolContract/ToolRegistry；
- 新 port 必须删除反向依赖、宽 `Any`、旧调用路径或证明第二实现需求；
- 新 MetadataKind 必须有独立 lifecycle、真实 producer/consumer、migration 和 duplication
  review；
- 不新增第二 durable store 或 general graph authority；
- root-only 不增加 provider round；
- 未选 candidate 不加载完整 context/environment，只保留最小 redacted receipt；
- 每个生产切片必须减少至少一个真实旧 consumer/branch/dependency，或不得称为重构完成。

### 4. Adoption ladder

```text
offline inventory/fixture
  -> shadow view/decision
  -> paired comparison
  -> default-off limited route
  -> bounded rollout
  -> default-on only after gates
  -> old-path usage-zero and separate deletion
```

实验失败时保留更窄层级，不通过降低门槛维持原方案。

### 5. Optional policy order

```text
root-only/plain Pi
  -> governed context projection
  -> explicit top-1 JIT only if incrementally valuable
  -> top-k/tree only if JIT and low-cost candidates pass
  -> World Model only if bounded tree has real value
```

## Consequences

正向结果：

- 项目即使不实现动态链/树，也保留 metadata evolution、审计、权限和恢复价值；
- 普通任务不会因控制平面被强制序列化；
- 新抽象必须以删除旧复杂度证明自身价值；
- provider 长上下文变便宜时，核心定位仍然成立；
- Search Policy 可以被实验否决而不破坏总体架构。

代价：

- Control Plane 不追求观察或持久化所有模型内部选择；
- 某些 search/audit 研究数据需要专门实验模式，不能成为生产默认；
- 迁移切片需要同步追踪旧 consumer 和删除证据；
- Context/JIT 的上线速度服从安全、总成本和恢复门，而不是功能完成度。

## Rejected alternatives

### 把动态链作为默认核心

这会把尚未证明的增量机制变成所有任务的固定成本，并与 harness 隐式决策重复。

### 先建立完整任务图和通用搜索层

缺少真实跨 owner 查询、总成本和恢复证据，且容易形成第二 workflow engine。

### 只做普通 harness，不保留 Control Plane

会放弃已经存在且有明确价值的 permission、Evidence Core、validation、checkpoint 和
跨进程恢复边界。

## Validation

采用条件和 kill criteria 由
[`../EVALUATION_PLAN_CN.md`](../EVALUATION_PLAN_CN.md) 管理；阶段顺序和持续收缩门由
[`../REFACTOR_ROADMAP_CN.md`](../REFACTOR_ROADMAP_CN.md) 管理。
