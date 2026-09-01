# Metadata Control Plane Claim 与 Evidence Index

> Status: Active evidence index
> Authority: Claim status and evidence routing; it does not replace source manifests/results
> Owner: Architecture / evaluation
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 作用

本文是 L2 design claim、实验、ADR 和 implementation gate 之间的唯一桥梁：

```text
L2 claim
  -> experiment manifest/run/result
  -> evidence status
  -> ADR when adopted
  -> roadmap implementation slice
```

原始 evidence 留在 `experiments/`。本文只记录 status、claim boundary 和链接。

## 2. 状态

```text
Open
Candidate
Dormant
Locally Supported
Supported Current Implementation
Adopted
Rejected
Superseded
```

- `Locally Supported` 不等于独立 provider 质量或生产批准；
- `Dormant` 表示不在当前 experiment/implementation queue，重新激活前不得创建 production
  schema、package 或默认路径；
- `Adopted` 需要 ADR 或现有规范/实现已明确拥有该边界；
- 无 provider token/call/latency 时，不升级经济性 claim。

## 3. Claim registry

| Claim | Design owner | Status | Evidence / experiment | Adoption gate |
| --- | --- | --- | --- | --- |
| MAP-C01 当前 metadata/evidence/admission/action/recovery 可作为迁移基线 | [Current mapping](design/CURRENT_TO_TARGET_MAPPING_CN.md) | Supported Current Implementation | Code/contracts/current tests | Phase 3 equivalence 保持 |
| MAP-C02 当前 ports/facade 可作为 strangler seam | [Current mapping](design/CURRENT_TO_TARGET_MAPPING_CN.md) | Candidate | `autonomous_iteration/ports.py`, `HarnessApplication` | typed port spike + behavior equivalence |
| MAP-C03 大型 controller 可由独立切片安全净收缩 | [Current mapping](design/CURRENT_TO_TARGET_MAPPING_CN.md) | Open | planned migration slices | net complexity ledger、blast-radius、rollback、usage-zero |
| MAP-C04 Pi 可以长期保持可替换 execution adapter | [Current mapping](design/CURRENT_TO_TARGET_MAPPING_CN.md) | Adopted | [Pi runtime decision](../OPENPILOT_PI_RUNTIME_DECISION.md) | R4 cross-engine rehearsal |
| MD-C01 当前 `MetadataBase` 可作为 provisional structural-envelope candidate | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Candidate | `MetadataBase`, catalog | ME0/ME3/ME5 consistency、usage、deprecation evidence |
| MD-C02 Semantic Kernel 应进入 registry 而非继续扩充 base | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Candidate | [ME0/ME3 plan](EVALUATION_PLAN_CN.md) | registry 不形成第二 schema truth |
| MD-C03 节点/边先作为 derived graph view | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Candidate | ME4 + relationship query fixtures | 跨 owner 查询收益且 authority duplication=0 |
| MD-C04 Gate 必须绑定 authority inputs/evidence | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Adopted | AGENTS/API/admission/completion/recovery contracts | failure-path tests持续通过 |
| MD-C05 usage audit 是安全 deprecation 的必要但非充分证据 | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Candidate | ME3 + ME5 | 静态/运行时使用归零且历史恢复通过 |
| MD-C06 bounded derived graph query 不引入第二 graph authority | [Metadata model](design/METADATA_DOMAIN_MODEL_CN.md) | Candidate | ME6 | query bounds/freshness通过，canonical writes=0 |
| RT-C01 root-only 避免短任务额外结构调用 | [Runtime protocol](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Candidate | J2 | 额外 provider round=0，token/latency回归≤5% |
| RT-C02 top-1 proposal/admission 构成可恢复 JIT chain | [Runtime protocol](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Locally Supported | E03/E04 local mechanisms；J0–J4待补 | 总质量/成本 paired gate |
| RT-C03 typed triggers 动态暴露治理动作可降低 overhead | [Runtime protocol](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Open | J0/J2 | governance-only calls≤10% |
| RT-C04 一个 active node 的串行 V1 足以承载当前目标 | [Runtime protocol](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Candidate | J3/J4 realistic long-task canary | quality/safety不劣且无并发必要性证据 |
| RT-C05 completion/closure 可以复用当前 verification/evidence owners | [Runtime protocol](design/CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Candidate | Phase 1 inventory + equivalence tests | duplicate owner=0，现有 completion结果等价 |
| CP-C01 optional local + on-demand 保持可解决场景质量并减少注入 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Locally Supported | [existing context evidence index](../../context_management/EXPERIMENT_EVIDENCE_INDEX.md) | 独立 provider + native telemetry；失败回退 governed source baseline |
| CP-C02 Context Governance 的 exact declared-required facts/source binding 是任何安全优化前提 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Locally Supported | E03 projection/Hexact probes | 跨任务 historical replay + false completion=0；不声称 latent completeness |
| CP-C03 required permission/validation/recovery facts 不得因距离、selector 或预算被静默省略 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Candidate | contract/failure fixtures | 任何预算下 required omission=0 |
| CP-C04 optional 消费审计可减少 unused injection | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Open | COPT-3 | 可观测消费率 + 质量非劣 |
| CP-C05 optional Resolution tree 可控制长历史展开成本 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Candidate | COPT-4 | provider tokens下降且按需展开 recall/质量不劣 |
| CP-C06 不可信内容不能通过 context route 升级为控制事实 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Candidate | CSG-C5 | adversarial content 下 authority/permission/tool routing 零漂移 |
| CP-C07 full-request budget 防止 context-only 节省被固定/输出开销抵消 | [Context governance/optimization](design/CONTEXT_PROJECTION_CN.md) | Candidate | CSG-C6 | 完整 request/response telemetry 和 required-fact omission=0 |
| SP-C01 Template/Proposal/Node 分离使未选候选低成本 | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Candidate | S0/S1 | 优先复用现有 capability registries；未选候选无独立执行/context load |
| SP-C02 top-1 是默认动态链，top-k 为可选 policy | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Candidate | J0/J2/S0 | short-task fast path + long-task paired gate |
| SP-C03 top-k 只在错误选择代价高时产生净收益 | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Dormant | S0/S3 | JIT gate 后再激活；quality/rework收益超过候选生成和治理成本 |
| SP-C04 bounded tree 可替换且不改 kernel/permission/evidence | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Locally Supported | bounded recursion probes；S2/S4 | policy replacement conformance |
| SP-C05 WorldModelPort 支持 RAP/MCTS 且不污染真实 state | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Dormant | S5 | JIT/top-k gate 后再激活；predicted state namespace/authority sentinel 100% |
| SP-C06 只保存最小未选候选 receipt 足以审计且避免膨胀 | [Search/candidates](design/SEARCH_POLICY_AND_CANDIDATES_CN.md) | Dormant | S6 | top-k gate 后再激活；审计问题可回答，未选正文/context不持久化 |
| DR-C01 Run/event/receipt 是恢复权威基础 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Adopted | [Harness/Evidence ADR](../ADR-OPENPILOT-HARNESS-EVIDENCE-PHASE0-1.md), current recovery tests | 持续回归 |
| DR-C02 revision + active cursor + checkpoint 必须一致提交 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Candidate | R0/R1 | fault injection 无 mixed state |
| DR-C03 projection/search cache 可丢弃重建 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Locally Supported | R2 | corruption fallback/rebuild 100% |
| DR-C04 local affected-scope rework 减少全任务重放 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Open | R3 | 重复工作下降≥20%，质量/安全不劣 |
| DR-C05 更换 policy/harness 可从同一 cursor 恢复 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Open | R4 | 不改写历史、不重复副作用 |
| DR-C06 single-writer/lease conflict 阻止并发事实分叉 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Candidate | R5 | stale writer dispatch=0，conflict fail closed |
| DR-C07 evidence/artifact/index retention 有界且不破坏恢复 | [Durability](design/DURABILITY_RECOVERY_CN.md) | Candidate | R6 | retention 后 supported recovery/lineage 100% |

## 4. Experiment routes

- 新架构实验入口：
  [`../../../experiments/metadata_control_plane/README_CN.md`](../../../experiments/metadata_control_plane/README_CN.md)
- Context Scope Governance 既有证据：
  [`../../context_management/EXPERIMENT_EVIDENCE_INDEX.md`](../../context_management/EXPERIMENT_EVIDENCE_INDEX.md)
- 既有详细研究状态：
  [`../../context_management/context_scope_governance/ARCHITECTURE_STATUS_AND_ROADMAP_CN.md`](../../context_management/context_scope_governance/ARCHITECTURE_STATUS_AND_ROADMAP_CN.md)

旧 evidence 不移动。新 experiment 可以复用 fixture 设计，但必须使用新 manifest/run identity，
并明确哪些结果是 prior evidence。

在 ME0/ME3 inventory 完成前不增加 Claim ID。远期 claim 可以保留为 `Dormant`，但不得仅因
文档中已有编号就创建 schema、package、protocol 或 production path。

## 5. Promotion rule

一个 claim 从 Candidate/Locally Supported 升级为 Adopted，必须同时满足：

- L2 invariant 和 owner 已明确；
- 对应 experiment gate 通过；
- 结果边界没有把 proxy 当 provider telemetry；
- 与现有 authority/permission/recovery contract 无冲突；
- ADR 记录采用和 rejected alternatives；
- roadmap 指定最小 implementation slice 和 rollback；
- production tests 尚未通过时，仍不得写成 implemented。
