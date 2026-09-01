# Metadata 领域模型：Kernel、节点、边、门禁与派生视图

> Status: Proposed L2 architecture
> Authority: Target metadata semantics; no new public contract is approved by this document
> Owner: Metadata architecture
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 目的

Metadata 不只是序列化对象。它在 OpenPilot 中承担四种不同职责：

1. 持久化权威事实；
2. 记录事件和证据；
3. 作为 admission、validation、transition 和 recovery 门禁；
4. 为模型、UI、搜索和审计生成可重建视图。

本模型把这些职责分开，使“只读取 metadata 就能理解任务结构”成为 derived-view 能力，
而不是把所有值塞进一个全局图数据库。

## 2. 七类 metadata 角色

### 2.1 Kernel Envelope

所有公共 contract 共享 `kind/schema_version/source/correlation/created_at/annotations`。
它解决身份、producer 和可解析性，不承担领域业务状态。

### 2.2 Authoritative Entity / State

类似图中的节点，表达具有独立 identity、owner 和 lifecycle 的事实，例如：

- Task / Run / execution identity；
- admission grant；
- runtime/checkpoint state；
- artifact/evidence identity；
- committed scope/node/closure identity（若后续批准）。

只有确实跨模块、跨时间或独立持久化的对象才需要成为公共 entity contract。单一 owner
内部的局部值继续使用 owned nested value。

### 2.3 Authoritative Relationship / Binding

类似图中的边，只对“关系本身”有权威，不复制两端事实。候选关系包括：

```text
contains / part_of
depends_on
consumes
supports
derived_from
supersedes
validates
produced_by
reopens
```

一个关系至少需要：

```text
relation kind
source identity
target identity
relation owner
source evidence / admission reference
lifecycle or validity interval
freshness / supersession state when applicable
```

不是每条关系都要成为独立 `MetadataKind`。稳定的一对一 owned relation 可继续嵌套；需要
独立查询、独立生命周期或跨树共享时，才考虑 reference/relationship contract。

### 2.4 Gate / Decision Record

门禁 metadata 记录“在什么输入和 authority 下允许或拒绝什么”，例如 admission、consent、
tool decision、verification、completion、resume decision。

Gate 不是普通布尔值，也不是图算法自动推断出的边。它至少绑定：

- decision identity；
- governed subject/action；
- authoritative inputs；
- policy/version；
- typed outcome/reason；
- evidence references；
- validity/revocation semantics。

Gate 可以产生一条 admitted transition，但不能修改输入事实来让决定看起来成立。

### 2.5 Observation / Evidence

记录实际发生的 provider、tool、filesystem、validation 和 process 观测。Evidence 是 append
history；摘要、report 和 timeline 是 derived projection。

模型自报的成功、预测成本或候选价值是 observation/proposal，不自动升级为 canonical fact。

### 2.6 Snapshot / Checkpoint

Checkpoint 是恢复所需的权威事实快照和 references，不是新的业务 owner。它必须声明：

- source Run/revision/cursor；
- included authoritative facts；
- generation/ordering；
- safe boundary；
- pending/observed side-effect state；
- compatibility version。

### 2.7 Proposal / Projection

Proposal 和 projection 默认无写权限：

- CandidateProposal；
- residual；
- graph/state view；
- context projection；
- ClosureProjection；
- model summary；
- search simulation state。

它们必须带 source references，可失效、可重建，并在 source 不完整时 fallback/safe-stop。

## 3. 节点 metadata 与边 metadata

判断标准不是“数据看起来像对象还是关系”，而是 authority 和 lifecycle：

| 问题 | Node/entity | Edge/relationship | Owned nested value |
| --- | --- | --- | --- |
| 有独立 identity 吗 | 必须 | 关系本身需要时 | 不需要 |
| 有独立 lifecycle 吗 | 通常有 | 关系可失效/替换时有 | 跟随 owner |
| 需要跨 owner 查询吗 | 通常需要 | 是 | 否 |
| 可以单独持久化/引用吗 | 可以 | 可以 | 不可以 |
| 谁是 authority | entity owner | relation owner | parent owner |

示例：

- Task 是 node/entity；
- Task 对文件的 `write_files` admission 是 task-owned scope，不自动成为通用 edge；
- 一个 durable dependency binding 若跨 node revision、可失效且被多个 consumer 查询，则可能
  值得成为 edge-like relation；
- `ContextCandidateDecision` 是 projection selection decision，不是 read permission edge；
- ClosureProjection 是 derived view，不是 Closed node 的 authority。

## 4. Persistence class

每个 contract/field 必须声明一个主要 persistence class：

```text
ephemeral
event_evidence
checkpoint_snapshot
durable_run_state
durable_project_state
artifact_reference
derived_cache
```

- `ephemeral`：一次调用或一次 search simulation；
- `event_evidence`：append-only 观测或决定；
- `checkpoint_snapshot`：恢复所需的绑定快照；
- `durable_run_state`：一个 Run 内持续演化的权威状态；
- `durable_project_state`：跨 Run 的项目事实；
- `artifact_reference`：大内容外置，metadata 只持 identity/lineage；
- `derived_cache`：可以删除和重建。

同一字段不能同时声称是 authoritative durable state 和可随时重建的 projection。

## 5. 权威和写入规则

```text
Authority fact owner
  -> may write its own fact/state

Relationship owner
  -> may admit/supersede relation only

Gate owner
  -> may write decision record only

Evidence producer
  -> may append observation only

Projection builder
  -> may write derived cache/view only

Search/model policy
  -> may submit proposal only
```

一个 consumer 需要不同形状时，应派生 view，不复制 authority。无法确定 owner 时，新字段
默认不进入 metadata kernel。

## 6. Derived Graph / State View

图由 registry、identity references、relationship records、events 和 current state 读时构建：

```text
Contract Registry
        +
Authoritative entities
        +
Relationship / gate records
        +
Evidence lineage
        ↓
Derived Metadata Graph
        ↓
runtime state view / search view / context view / audit view / UI view
```

Derived graph 可以回答：

- 一个事实由谁产生、谁消费；
- 一个 node 依赖哪些输出；
- 哪个 gate 允许了某次 action；
- 一个 projection 来源于哪些 evidence；
- 修改某事实需要失效或重新验证哪些 consumer；
- checkpoint 能否恢复到一致边界。

图 view 不拥有 source facts，不允许直接执行 graph mutation 作为业务写入。

### 6.1 Relation admission and graph bounds

- relation kind 必须来自版本化 allowlist；模型提出的新关系类型仍是 proposal；
- 只有 relation owner 可以把 proposal 变成 canonical binding；
- 当前关系、历史 transition event 和 derived inference 必须分层，不能都叫 edge；
- graph query 必须声明 root identities、允许的 relation kinds、purpose 和 source revision；
- 每次 query 具有 `max_nodes/max_edges/max_depth/max_artifact_expansions`；
- provider hot path 默认禁止无界 transitive closure、全项目 materialization 和正文加载；
- root-only 短任务可以跳过通用 graph 构建，只读取直接 authority references；
- source revision 或 registry version 改变时，缓存 view 必须失效或重新验证。

推荐先提供 task/run scoped view；只有真实跨 Run 查询重复出现并证明收益后，才考虑 project
级索引。

### 6.2 Resource evidence

| Operation | Required bound |
| --- | --- |
| entity lookup | exact identity / bounded batch |
| direct relation lookup | allowed relation kinds + max edges |
| dependent/consumer lookup | max depth/nodes + partial-result status |
| lineage expansion | artifact/body expansion separate budget |
| graph cache | source revision/version binding + bounded entries |
| usage audit | identity/counter only by default，正文另受 retention/redaction policy |

## 7. Registry、query 和 usage

Contract Registry 是 metadata 自描述能力的入口。其上提供只读查询：

```text
describe_contract(kind)
find_producers(kind_or_field)
find_consumers(kind_or_field)
trace_lineage(identity)
find_dependents(identity)
find_gates_for(action_or_transition)
find_stale_views(source_identity)
```

这些是目标语义，不是当前 API 批准。Phase 1 先以 offline inventory 实现，确认不会形成
第二份 schema truth。

## 8. 与现有 contract 的初步映射

| 角色 | 当前代表 |
| --- | --- |
| Kernel envelope | `MetadataBase`, `MetadataKind`, `MetadataSource`, `CorrelationInfo` |
| Entity/state | Task graph、Run、runtime/checkpoint、artifact metadata |
| Gate/decision | task admission nested values、guard/tool decision、verification/resume metadata |
| Evidence | Evidence Core events、tool result、failure、validation receipts |
| Projection | context selection、derived context projection、runtime report、compaction records |
| Relationship candidate | task dependencies、artifact refs、source candidate IDs、supersession refs |

具体复用/扩展必须经过 inventory；本表不批准新的通用 relationship layer。

## 9. Claim routing

本设计拥有 `MD-C01`、`MD-C02`、`MD-C03`、`MD-C04`、`MD-C05`、`MD-C06` 的语义；status、evidence 和 adoption gate 只在
[`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。

## 10. 未决问题

- 哪些现有 relationship 已经有独立 lifecycle，值得从 owned value 升级为 reference？
- contract registry 是代码声明、生成 artifact，还是 catalog sidecar？
- runtime usage audit 的最小字段如何避免记录敏感正文？
- derived graph 的 identity/freshness 缓存如何绑定 source revisions？
- ScopeTreeRevision 是否需要独立 contract，还是现有 task graph 的受限 revision view？
