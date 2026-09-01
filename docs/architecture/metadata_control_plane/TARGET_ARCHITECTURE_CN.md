# Metadata Control Plane 目标架构

> Status: Proposed target architecture
> Authority: Migration target; not current implementation truth
> Owner: Architecture
> Supersedes: None; current contracts remain authoritative during migration
> Last reviewed: 2026-09-01

## 1. 架构原则

目标不是把现有系统全部图化，而是建立稳定内核、单向依赖和可替换策略：

```text
User / CLI / API
        |
        v
Application Use Cases
        |
        v
Metadata Control Plane
  | authoritative state + admission + evidence + recovery
  | context governance + derived views + optional optimization/search ports
        |
        v
Execution Port
        |
        v
Pi / another harness / provider runtime
        |
        v
Tool Gateway -> side effects -> durable receipts / validation evidence
```

执行引擎可以提出动作和返回观测，但不能直接拥有任务权限、完成事实或持久化真相。
反过来，Control Plane 也不接管一次 admitted episode 内的普通推理和局部工具选择。

## 2. 八个目标组件

### 2.1 Metadata Kernel

拥有最稳定的 envelope、identity、authority、lifecycle 和 evidence-link 规则。
`Code/src/metadata/` 继续只放 typed contracts，不放业务执行逻辑。
领域角色、节点/边/门禁和 derived graph 见
[`design/METADATA_DOMAIN_MODEL_CN.md`](design/METADATA_DOMAIN_MODEL_CN.md)。

### 2.2 Metadata Evolution Protocol

管理 contract registry、版本、兼容读取、迁移、废弃、使用审计和删除门。详细规则见
[`METADATA_EVOLUTION_CN.md`](METADATA_EVOLUTION_CN.md)。

### 2.3 Durable State and Evidence

保存不可伪造的任务状态变化、工具观测、副作用 receipt、验证、checkpoint 和恢复身份。
缓存、摘要和 UI projection 可重建，不得升级为权威事实。
详细 durable boundary 见
[`design/DURABILITY_RECOVERY_CN.md`](design/DURABILITY_RECOVERY_CN.md)。

### 2.4 Derived Graph / State View

从权威 metadata 和 evidence 派生任务、依赖、证据、上下文、消费和恢复关系。第一阶段是
读时 view，不引入第二套通用 graph authority 或 graph database。
节点/边和 query 语义见
[`design/METADATA_DOMAIN_MODEL_CN.md`](design/METADATA_DOMAIN_MODEL_CN.md)。

### 2.5 Pluggable Search Policy

链、top-k 浅树、DAG、best-first、MCTS/LATS 类策略消费同一只读状态 view，并只输出
bounded typed proposals。策略可以替换，但不能直接写 authority。
Template/Proposal/Node、top-1/top-k 和 RAP-style world model 边界见
[`design/SEARCH_POLICY_AND_CANDIDATES_CN.md`](design/SEARCH_POLICY_AND_CANDIDATES_CN.md)。

### 2.6 Context Boundary Governance 与可选优化

每个由 OpenPilot 准入并声明支持的 model-request route，都必须在其可观测边界和声明的
conformance level 内治理 instruction/data separation、source/trust、权限、declared-required
facts、freshness、请求预算、authority isolation 和 fallback。`governed source baseline` 是
合法基线，但不表示完整仓库或完整历史。

purpose-specific selection、omission、summary、on-demand 和 resolution tree 是可选 Context
Optimization；无法验证或实验不通过时回退 governed source baseline，不影响基础治理成立。
详细治理、selector、Hexact、on-demand 和消费审计见
[`design/CONTEXT_PROJECTION_CN.md`](design/CONTEXT_PROJECTION_CN.md)。

### 2.7 Governed Execution

proposal 经过 metadata-first admission 后才成为可执行动作。读取、写入、命令、网络、
预算和验证继续遵守现有 typed permission 与 Action Gateway 边界。
root-only、JIT chain、NodeVisit、admission 和 closure 时序见
[`design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md`](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md)。

### 2.8 Durable Recovery

checkpoint 保存恢复所需的权威身份和游标；恢复消费已有 receipt 和 validation，不重放
已发生副作用，也不让新的 harness 回合改写历史结果。
详细协议见 [`design/DURABILITY_RECOVERY_CN.md`](design/DURABILITY_RECOVERY_CN.md)。

### 2.9 成熟度与必要性分层

八个组件不是同等优先级，也不意味着必须各自形成新模块：

```text
Stable core target
  Metadata Kernel / Evolution
  Durable State and Evidence
  Context Boundary Governance
  Governed Execution
  Durable Recovery

Derived services
  Derived State View
  Selective Context Optimization

Optional policies
  Explicit JIT successor policy
  top-k/tree/DAG/MCTS/LATS/RAP-style search
```

Optional optimization/policy 不在架构成立的关键路径上。若实验不能证明相对 plain
Pi/current OpenPilot 的增量收益，系统应保留 thin control plane + governed source baseline
context，而不启用 selective projection 或复杂搜索。
“组件”表示责任边界，不自动批准一个 package、service、port 或 public metadata contract。

### 2.10 Control Plane V1 产品边界

“完整 V1”表示最小权威闭环可以端到端运行、恢复、验证和迁移，不表示所有可选策略都已
实现。本表是“V1 包含什么”的唯一产品边界 owner；组合方式、接口冻结条件、conformance
证据和集成顺序分别由
[mapping §5.2](design/CURRENT_TO_TARGET_MAPPING_CN.md#52-v1-composition-freeze)、
[runtime protocol §15](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md#15-v1-interface-freeze-gate)、
[evaluation plan §3.5](EVALUATION_PLAN_CN.md#35-control-plane-v1-conformance-suite) 和
[roadmap Phase 4C](REFACTOR_ROADMAP_CN.md#phase-4c-v1-integration-cutover)
投影，不得在别处定义第二份 V1 边界。V1 必须包含：

| V1 responsibility | Minimum completion |
| --- | --- |
| Metadata Kernel / inventory | 当前 public contracts、owner、producer/consumer、lifecycle 和 persistence 可机器检查 |
| Metadata Evolution | 版本读取、typed migration/rejection、deprecation 和 usage-zero 路径可验证 |
| Task Authority / Admission | task、scope、permission、budget 和 acceptance 进入执行前完成绑定 |
| Run / Evidence | observation、receipt、validation 和 canonical transition 可追溯 |
| Read-only State View | 从权威事实构造有界、可失效、可重建的执行视图 |
| Context Governance baseline | supported request routes 满足 source/trust/freshness/required-fact/budget/fallback 门 |
| Governed Execution | Pi 作为默认 adapter，只执行 admitted request/action，不拥有业务终态 |
| Verification / Closure | completion 只能由 validation/evidence owner 形成 ClosureCommit |
| Checkpoint / Recovery | crash window、lease、idempotency、reconciliation 和 resume 闭合 |
| Composition / migration | 单一公开入口、可替换 adapter、兼容切换和旧路径退出条件明确 |

V1 明确不包含 Selective Context Optimization、显式 JIT successor、top-k/tree/DAG、
MCTS/LATS/RAP World Model、通用 graph database 或多 agent 并行调度。它们只能在 V1 核心
闭环之后按独立增量 gate 启用。

V1 可以作为一个完整产品版本统一规划和验收，但实现必须按 roadmap 的纵向切片逐步接入，
不能以“一次发布”为由使用 big-bang rewrite 或一次性替换所有 owner。

### 2.11 显式化边界

只显式化会跨越 owner、episode、持久化或治理边界的事实/决定：

```text
permission / consent / scope
context source / freshness / fallback
provider/tool observation and side-effect receipt
validation / completion
checkpoint / resume / reconciliation
durable dependency / continuation
high-cost admitted strategy choice
```

普通局部推理、一次性下一步、完整思维链、无未来消费者的备选方案不持久化。没有上述
trigger 时，运行路径保持 plain Pi/root-only。

## 3. 权威数据流

```text
Authoritative task / permission / budget / evidence / checkpoint facts
                              |
                              v
                    Derived read-only views
                              |
                              v
              Search or context-policy proposals
                              |
                              v
             Deterministic admission and validation
                              |
                              v
                    Execution-harness action
                              |
                              v
            Observation / receipt / validation evidence
                              |
                              v
                  Authoritative state transition
```

proposal、summary、residual、graph view 和 prompt projection 都不是独立真相。它们必须
保留 source references，并能在 authoritative facts 变化后失效和重建。

## 4. 单向依赖

目标依赖方向如下：

```text
ui/adapters
    -> application/use-cases
        -> control-plane services
            -> metadata contracts

control-plane services
    -> evidence/state ports
    -> context/search policy ports
    -> execution port

Pi/provider/tool adapters
    -> ports defined by OpenPilot
```

禁止：

- `metadata/` 导入 controller、memory、tool 或 provider 实现；
- search policy 直接写 store 或调用未准入工具；
- context projection 复制权限、完成或验证 owner；
- Pi adapter 把 provider-specific payload 泄漏到业务模块；
- 为兼容旧 controller 重新引入第二条公开运行路径。

## 5. Graph、链与树的关系

动态链是每次只实例化一个已选后继的执行轨迹；候选模板和依赖 view 可以形成浅树或
DAG，但未实例化候选应当是 body-free、低成本、可验证的 proposal。只有 admission 后，
候选才成为完整执行节点。

因此：

- 图是状态和关系的表达；
- search policy 是推理资源分配算法；
- active trajectory 是实际执行路径；
- context projection 是每次执行看到的局部视图。

四者不得被实现为一个同时拥有事实、搜索、执行和持久化的巨型 controller。

## 6. 必须长期保持的不变量

1. 一个事实只有一个 authoritative owner。
2. 控制行为只能由 typed values 驱动，说明文本不能授予权限或完成任务。
3. 不可逆副作用必须有 admission、receipt 和验证/对账边界。
4. derived view 可丢弃、可重建、可失效。
5. metadata 的未知版本或非法状态在权限、mutation、完成和恢复边界 fail closed。
6. authoritative owner 已声明的 required facts 不因摘要、树距离或上下文预算而静默丢失；
   该保证不声称不存在未知依赖。
7. 短任务允许 root-only，一次 harness episode 内完成时不强制结构调用。
8. 所有治理、搜索、重试和投影成本都进入端到端经济性评估。
9. 历史 evidence 不因 roadmap 或 revision 更新而被覆盖。
10. 每一迁移切片必须可单独回滚或保留旧读路径，直到兼容门通过。
11. Pi/harness 拥有 episode 内普通推理与合法工具选择；Control Plane 只管理跨边界事实。
12. 一个显式 metadata 若没有跨 episode、跨模块、恢复、审计或门禁 consumer，不持久化。
13. 新 port/contract/service 必须减少旧依赖、旧分支或宽类型传播，不能只增加转发层。
14. 不新增第二 authoritative writer/store、general graph authority 或默认开启的 search
    workflow；可重建 shadow/derived 表示必须 canonical writes=0 或服从单一 writer。
15. root-only 不增加 provider round；JIT/tree/world-model 逐级通过增量 gate 才能启用。
16. Context Governance 对所有 OpenPilot-admitted supported routes 必选；保证只覆盖可观测
    request components 和 declared-required facts。
17. 选择性 projection/summary/on-demand 是 default-off、可否决、可删除的优化，并始终可
    回退 governed source baseline。
18. 基础 Context Governance deterministic/provider-free；provider-assisted context judgment
    归入 optional optimization。

## 7. 与当前目录的关系

- 当前 metadata contract 和字段真相：[`../../metadata/README.md`](../../metadata/README.md)
- 当前 Pi 执行边界：[`../OPENPILOT_PI_RUNTIME_DECISION.md`](../OPENPILOT_PI_RUNTIME_DECISION.md)
- 当前恢复边界：[`../../runtime_recovery/README.md`](../../runtime_recovery/README.md)
- Context Scope Tree 研究设计：
  [`../../context_management/context_scope_governance/ARCHITECTURE_CN.md`](../../context_management/context_scope_governance/ARCHITECTURE_CN.md)
- 当前到目标的实现映射：
  [`design/CURRENT_TO_TARGET_MAPPING_CN.md`](design/CURRENT_TO_TARGET_MAPPING_CN.md)
- Claim 与 evidence 状态：[`EVIDENCE_INDEX_CN.md`](EVIDENCE_INDEX_CN.md)
- 薄控制平面约束：[`adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md`](adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md)
- 上下文治理与可选优化边界：
  [`adr/ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md`](adr/ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md)
- 可观测治理范围：
  [`adr/ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md`](adr/ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md)
- 净收缩与单一权威迁移：
  [`adr/ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md`](adr/ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md)

Context Scope Tree 是 search/context policy 的重要研究输入，不自动成为全局 metadata
存储模型。
