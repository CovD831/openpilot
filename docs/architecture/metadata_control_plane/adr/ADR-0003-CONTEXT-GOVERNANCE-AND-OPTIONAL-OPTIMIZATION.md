# ADR-0003: 区分必选 Context Governance 与可选 Context Optimization

> Status: Accepted for architecture planning
> Authority: Architecture constraint; it does not authorize production behavior changes
> Owner: Architecture / memory
> Supersedes: None; clarifies the context responsibility in ADR-0002
> Last reviewed: 2026-08-31

## Context

每个 LLM harness 都必须决定一次 provider request 使用哪些 instruction、tool schema、任务
事实、项目内容和历史观测，并处理来源、权限、freshness、窗口预算和不可信内容。即使把
完整历史全部注入，这个上下文边界仍然存在。

OpenPilot 进一步研究的选择性注入、summary、on-demand evidence、resolution tree 和消费
审计，是在该边界上的优化，不是上下文治理本身。把两者合并会产生两个错误：

- 选择性缩减实验失败时，基础上下文安全边界也被错误否定；
- 为了建设“治理”而提前引入 selector、projection contract 和额外 provider 调用。

## Decision

### 1. Context Governance 是必选责任

每个 harness adapter/provider request 都必须遵守同一组治理不变量：

```text
instruction/data separation
source / trust / provenance
permission and admitted read scope
required facts and acceptance facts
freshness / invalidation
full-request budget and output reserve
prompt-injection isolation
governed full-source fallback or safe-stop
```

Context Governance 可以由现有 Context Assembly/adapter 实现，不自动批准新 service、port 或
MetadataKind。它不以减少 token 为成立条件。

### 2. Governed full-source 是合法基线

在 selective optimization 未通过、被关闭或发生不确定性时，系统可以使用受治理的完整
source view。若 required facts 加固定 instructions/tool schemas 已超过窗口，必须返回 typed
budget failure、缩小合法 tool surface、重新分解或 safe-stop，不能静默截断控制事实。

### 3. Context Optimization 是可选策略

以下机制属于 default-off、可独立否决和删除的优化：

```text
purpose-specific selection / omission
local projection
summary / compaction replacement
on-demand evidence expansion
resolution tree
unused-injection / consumption optimization
```

它们必须复用 Context Governance 的 source、authority、freshness、budget 和 fallback，不得
创建第二份任务、权限、验证或恢复事实。

### 4. 独立采用门

```text
Context Governance
  -> required for every harness route
  -> safety/correctness/conformance gate

Context Optimization
  -> experiment/shadow/default-off
  -> quality non-inferiority + provider-native total-cost gate
  -> failure falls back to governed full-source
```

JIT、tree 和 World Model 不依赖 selective optimization；它们可以在 governed full-source 上
单独实验，避免把多个未定机制绑定成一个成败包。

## Consequences

正向结果：

- 基础上下文安全边界不再依赖 token-saving 假设；
- selective injection 可以被 killed，而不削弱 Control Plane 的 authority/recovery 定位；
- plain Pi、其他 harness 和未来 provider adapter 使用相同治理不变量；
- 实验能隔离“安全治理是否正确”和“选择性缩减是否有增量收益”。

代价：

- full-source fallback 可能昂贵，甚至因窗口不足而 safe-stop；
- Context Governance 必须覆盖完整 request，而不只是动态正文；
- 优化层需要单独计量 selector、summary、fallback 和治理开销。

## Rejected alternatives

### 把选择性 projection 作为所有 harness 的默认上下文层

这会在 required-fact closure 和真实 provider 总成本尚未证实时，把实验优化变成固定风险。

### 不建设 Context Governance，完全依赖 harness 默认 Prompt 拼接

这会让 permission、freshness、required facts、prompt injection 和窗口失败语义随 adapter
漂移，破坏 metadata-first 的统一控制边界。

## Validation

基础治理与可选优化的独立基线、实验和 kill criteria 由
[`../EVALUATION_PLAN_CN.md`](../EVALUATION_PLAN_CN.md) 管理；L2 语义由
[`../design/CONTEXT_PROJECTION_CN.md`](../design/CONTEXT_PROJECTION_CN.md) 管理。
