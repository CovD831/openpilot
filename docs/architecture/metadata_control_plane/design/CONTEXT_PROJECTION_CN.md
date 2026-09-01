# Context Governance 与可选 Projection Optimization 二级架构

> Status: Proposed L2 architecture
> Authority: Target context-governance and optional optimization semantics; current Context Assembly remains authoritative
> Owner: Memory / context control plane
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 两层职责

### 1.1 Context Governance（必选）

每个由 OpenPilot 准入并声明支持的 model-request route，都必须在其可观测边界和声明的
conformance level 内治理：

```text
instruction/data separation
source / trust / provenance
permission and admitted scope
declared-required facts / acceptance facts
freshness / invalidation
full-request budget / output reserve
prompt-injection isolation
governed source baseline / safe-stop
```

这层不以减少 token 为目标，也不要求 selector、summary 或新的 projection contract。即使
使用 governed source baseline，上述治理仍然必须成立。该 baseline 是完整 mandatory/control
facts 加一个明确 admitted source pack，不是完整仓库、完整历史或所有可读取信息。

### 1.2 Context Optimization（可选）

在 Governance 已成立的前提下，系统可以实验：

> 从权威事实构造一个对当前 purpose 最小充分、可验证、可失效、可回退的 model-facing
> view，使长任务上下文随活动工作集而不是累计历史增长。

选择性注入、omission、summary、on-demand、resolution tree 和 consumption optimization
属于 default-off 策略。它们失败或被关闭时回退 governed source baseline，不影响 Governance
成立。

两层都复用现有 `ContextCandidate`、selection metadata、compaction binding、artifact
reference 和 token budget，不拥有任务、权限、验证、完成或恢复事实。该边界由
[`ADR-0003`](../adr/ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md) 固定。
治理保证的可观测范围、baseline 和 coverage 边界由
[`ADR-0004`](../adr/ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md) 固定。

### 1.3 Provisional conformance taxonomy

以下等级属于 L2 规范 owner，用 `CL-*` 与 G0–G7 实验编号区分。最终 schema、字段和 adapter
声明格式仍由 G5 决定。

| Level | Guarantee | Minimum evidence |
| --- | --- | --- |
| `CL-0 Authority Boundary` | source/reference 不扩大权限；declared-required/control facts 不静默省略 | admission refs、candidate decisions、typed failure path |
| `CL-1 Governed Request` | 可观测 instructions/data、trust、freshness、known fixed components、budget/reserve 已校验 | adapter-visible request components + capability version |
| `CL-2 Auditable Request` | request identity、source decisions、budget confidence、redaction/retention 可追踪 | body-free receipt + evidence refs |
| `CL-3 Optional Optimization` | selection/summary/on-demand 相对 CL-1 baseline 有增量收益 | paired provider-native quality/cost telemetry |

adapter 只能声明实际证明的最高等级。不可观测组件必须标记 unknown/out-of-scope；`CL-3`
失败只关闭 optimization，不降低已经证明的 CL-0/CL-1 保证。

## 2. 输入与输出

输入：

```text
authoritative task / node / acceptance facts
permission and action scope
current residual and blockers
evidence and artifact references
dependency/public-output bindings
checkpoint/recovery facts
recent execution observations
purpose + budget + freshness requirements
```

Governance 的最小输出是当前可观测 request components 是否满足 source、authority、
freshness、declared-required、trust 和预算约束，以及应继续、使用 governed source baseline、
降低 conformance level 还是 safe-stop。它应优先复用当前 Context Assembly decision/evidence。

只有启用 Optimization 时，才需要 `ContextProjectionDecision` 语义：

```text
projection identity
purpose
selected candidate identities
required-fact coverage
source revision/freshness bindings
omitted candidates and typed reasons
token/character accounting
fallback status
rendered request reference
```

具体 contract 在 inventory 后决定；当前不得创建第二份 `ContextSelectionMetadata`。

## 3. Optional NodeContextField

目标组合模型：

```text
NodeContextField(v) =
    InvariantCore
  + SelfFullState
  + ParentIntent
  + AncestorGoalDeltas
  + ChildClosureProjectionsAndResidual
  + SiblingWeakAwareness
  + RequiredDependencyOutputs
  + EvidenceOnDemand
  + RecentToolRoundtrip
```

这是一组可组合 optimization selectors，不是固定 Prompt 模板或新 metadata mega-contract。
Governance 不依赖该组合模型存在。

## 4. Context layers

### 4.1 Invariant Core

默认不可因距离或普通 token 压力被省略：

- 用户根任务和已确认约束；
- read/write/network/command permission；
- 当前节点目标、输入输出和验收；
- 当前 blocker、recovery 和副作用状态；
- 必需依赖输出；
- exact validation/completion facts。

若预算无法容纳完整 Invariant Core，必须返回 typed budget failure，不截断后继续。

### 4.2 Self Full State

当前 node/visit 的完整工作集，包括当前 residual、最近 tool observations、待验证结果和
open issues。它按 purpose 组织，不默认复制完整 session transcript。

### 4.3 Parent / Ancestor

- Parent：完整 intent、责任边界、acceptance 和 residual；
- Higher ancestors：只保留相对当前 node 的目标/约束增量和必要 lineage；
- 根任务 required facts 始终保留，不随深度衰减。

### 4.4 Children / Siblings / Dependencies

- active/failed child：较高分辨率；
- closed child：ClosureCommit refs + ClosureProjection；
- unrelated sibling：identity、status、output description 和 conflict hints；
- required dependency：公开输出、freshness 和必要证据；
- distant closed branch：最低 resolution，需要时展开。

### 4.5 Recent Tool Roundtrip

只保留当前决策所需的有界最近往返。完整 tool/provider history 继续由 Evidence Core 或
artifact 保存，不能全部复制进 Prompt。

## 5. Exact facts、summary 与 Hexact

Projection 中的内容分为：

```text
Exact declared-required facts
  task / acceptance / permission / validated decisions / required outputs

Structured state
  residual / blockers / freshness / status / selected evidence identities

Compressible narrative
  explanations / older observations / closed-branch summaries
```

Exact declared-required facts 必须从 authoritative owner 通过 identity/reference 选择，不允许
由摘要重新生成。该 coverage 不证明不存在未知依赖。summary 只能替换允许压缩的 narrative
source group，并与被替换 source decisions 原子绑定。

## 6. Governance 与 Optimization pipeline

必选 Governance pipeline：

```text
collect admitted sources and fixed request components
  -> bind authority / trust / provenance / freshness
  -> verify instructions, declared-required facts and permissions
  -> verify full-request budget and output reserve
  -> render governed source baseline OR typed budget/conformance failure / safe-stop
```

可选 Optimization pipeline：

```text
collect typed candidates
  -> bind source identity and freshness
  -> classify required / optional / forbidden
  -> apply purpose selectors
  -> verify declared-required coverage
  -> fit optional candidates to budget
  -> optionally apply atomic compaction
  -> render
  -> record ContextSelection / Projection decision
```

推荐优先级：

1. safety/permission/recovery；
2. root task/current acceptance；
3. current node state/residual/blockers；
4. required dependency outputs；
5. recent causal evidence；
6. optional related evidence；
7. distant summaries。

### 6.1 Full-request budget

Context budget 不能脱离完整 provider request 单独计算：

```text
fixed system/developer instructions
+ advertised tool schemas
+ invariant required facts
+ selected optional context
+ expected output reserve
+ provider/safety margin
<= effective context window
```

只有扣除 fixed instructions、tool schemas、required facts 和 output reserve 后的剩余预算，
才能分配给 optional context。固定部分加 required facts 已经超限时，返回 typed budget failure、
减少 tool surface 或重新分解；不得截断权限/验收/恢复事实后继续。

短任务不得为了生成 summary/projection 再调用 provider；deterministic selection 和 root-only
快路径优先。

## 7. Optional purpose profiles

启用 Optimization 时，Selector 输入必须包含 typed purpose，而不是在 Prompt 字符串中猜测：

```text
task_execution
tool_decision
mutation_preparation
validation
closure
recovery
search_policy
human_review
```

同一事实可以被多个 purpose 选择，但仍由一个 source owner 管理。

## 8. Optional REQUEST_CONTEXT / on-demand evidence

模型只提交：

```text
missing fact kind
purpose
affected acceptance/blocker
optional source hint
```

Context control plane 决定：

```text
satisfied
partially_satisfied
rejected
fallback_source_view
safe_stop
```

模型不能通过 REQUEST_CONTEXT 扩大 read scope、提高自己内容的 required 等级、指定无限
token 配额或要求完整远端 transcript。

## 9. Freshness 与失效

每个 required/derived candidate 都应绑定 source identity/revision。以下变化触发重新评估：

- task/acceptance/permission 更新；
- source artifact 或 project state 变化；
- dependency output superseded；
- evidence stale/revoked；
- checkpoint/recovery epoch 变化；
- selector/policy version 变化。

允许状态：

```text
current
revalidation_required
invalidated
unknown
```

`unknown` 不得视为 current。

## 9.1 Trust、Prompt Injection 与敏感信息

所有 project file、web、tool output、memory、artifact 和模型生成文本默认是不可信数据，
即使它来自已允许读取的路径。每个 candidate 至少保留 source/trust/provenance 分类。

约束：

- 外部/项目正文以明确数据边界渲染，不能覆盖 system/developer instructions；
- selector、admission 和 completion 不从正文句子推断权限、required 等级或验证成功；
- 内容中的“调用工具、忽略规则、扩大 scope”等指令只作为被分析数据；
- source hint、文件路径或 artifact reference 不授予新的 read/network/write authority；
- secrets、credential-like values 和不允许持久化的正文在 projection/usage receipt 前脱敏；
- retrieved content 不能直接产生 tool call，必须经过 provider tool schema 和 Action Gateway；
- prompt-injection detector 只能提供风险 evidence，结构化 authority separation 才是主防线。

硬保证仅覆盖正文不能升级 authority、permission、read/network scope 或 tool-routing。模型的
语义判断仍可能受恶意内容影响，必须作为独立 robustness/quality 指标评估。

消费审计默认只记录 candidate/source/fact identity 和 typed decision reference，不复制敏感
正文或 raw model reasoning。

## 10. Atomic fallback

以下任一情况出现时，不得使用不完整 projection 继续：

- required fact coverage 无法证明；
- replacement summary 缺少全部 source bindings；
- selector identity 或 authority mismatch；
- required source freshness 为 unknown/invalidated；
- permission/validation/recovery candidate 被预算淘汰。

处理顺序：

1. 回退到受治理 source view；
2. 若 source view 仍超预算，REQUEST_CONTEXT/重新分解；
3. 若 authority 或 scope 不可满足，safe-stop。

## 11. Optional Summary Resolution

历史内容按需展开：

```text
Level 0  one-line outcome/index
Level 1  ClosureProjection
Level 2  child commits/projections
Level 3  relevant NodeVisits/tool observations
Level 4  original artifact/evidence/transcript
```

Resolution tree 是信息索引，不是 task tree 或 authority graph。

## 12. Optional 消费侧使用审计

“传入 Prompt”不等于“被用于决定”。消费审计至少区分：

```text
selected
rendered
referenced_by_model
used_in_tool_or_decision
required_for_validation
unused_or_unobservable
```

模型引用只能作为 usage observation；真正影响工具、admission、validation 的消费由 typed
decision/evidence 关联确认。审计用于发现长期无用注入和 selector 缺口，不反向改变任务
事实。

## 13. 成本账户

同时记录：

- provider input/output tokens；
- selected/rendered chars/token proxy；
- projection/compaction provider calls；
- on-demand requests；
- repeated evidence reads；
- fallback/safe-stop；
- projection build latency；
- quality、rework 和遗漏成本。

只减少 rendered chars 不能证明总成本下降。

## 14. 当前实现映射

| Target responsibility | Current seed |
| --- | --- |
| Candidate/source governance | `ContextCandidate`, decisions, freshness/trust fields |
| Budgeted selection | `ContextAssembler.assemble_candidates` |
| Source assembly | `MemoryContextBuilder` |
| Derived projection | `memory/context_projection.py` |
| Atomic compaction | compaction records/bindings and reusable compaction gates |
| Checkpoint replay | current context/checkpoint handlers |

目标重构先拆职责和 ports，不重写这些经过验证的规则。

## 15. Claim routing

本设计拥有 `CP-C01`、`CP-C02`、`CP-C03`、`CP-C04`、`CP-C05`、`CP-C06`、`CP-C07` 的语义；status、evidence 和 adoption gate 只在
[`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。

## 16. 未决问题

- declared-required coverage 的最小可执行证明格式是什么？
- provider 模型输出如何以低侵入方式记录 fact references？
- `referenced_by_model` 与真实决策消费如何区分？
- selector policy 是否属于版本化 metadata，还是普通配置 artifact？
- root-only 短任务是否应完全跳过 derived graph 构建？
- G0–G7：最终 request manifest、adapter capability level、budget confidence、body-free receipt
  和 Pi 可见性应采用什么最小 schema？
- latent/undeclared dependency 的发现率和 REQUEST_CONTEXT/safe-stop 行为如何评估？
