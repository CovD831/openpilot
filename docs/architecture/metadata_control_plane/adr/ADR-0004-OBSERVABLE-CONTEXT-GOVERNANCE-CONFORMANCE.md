# ADR-0004: Context Governance 只承诺可观测请求边界

> Status: Accepted for architecture planning
> Authority: Architecture constraint; it does not authorize production behavior changes
> Owner: Architecture / memory / execution adapters
> Supersedes: None; narrows the scope and guarantees of ADR-0003
> Last reviewed: 2026-08-31

## Context

ADR-0003 已决定 Context Governance 对所有 harness routes 是基础责任，而选择性注入属于
可选优化。第三轮审查进一步确认，“所有 harness”与 `governed full-source` 仍可能被过度
实现：OpenPilot 不一定看见 provider 隐藏 system policy、tool encoding、cache metadata 或
native token accounting，也不能证明任务没有尚未发现的关键事实。

因此必须限定治理对象、保证强度和 fallback，避免把可验证 metadata coverage 写成对完整
provider request 或任务知识的全知承诺。

## Decision

### 1. 支持范围

Context Governance 适用于：

```text
every model-request route admitted by OpenPilot
and explicitly declared supported at a conformance level
```

provider-hidden internals、绕过 OpenPilot admission 的调用和 adapter 无法声明的组件不在保证
范围内。unknown 必须显式，不能被填成 supported。

### 2. Governed source baseline

安全基线称为 `governed source baseline`：

```text
complete declared mandatory/control facts
+ one explicit admitted source pack
+ required tool-roundtrip state
+ known fixed request components
+ conservative output reserve / safety margin
- no optional selector omission
- no summary replacement
- no deferral of declared-required facts
```

它不表示完整仓库、完整历史或所有可读取信息。

### 3. Coverage 保证

Governance 只承诺 **declared-required coverage**：所有 authoritative owner 已声明 required 的
事实被纳入 request 或触发 typed failure。它不承诺：

- 不存在未知依赖；
- 模型已经理解所给事实；
- 当前事实足以完成任务；
- 模型不受恶意数据的语义影响。

latent gap 通过 negative controls、REQUEST_CONTEXT、重新分解或 safe-stop 处理。

### 4. Deterministic governance

基础 Governance 必须 deterministic、provider-free。任何 provider-assisted classification、
selection、summary 或 relevance judgment 都属于 optional Context Optimization，并单独计量。

### 5. Authority isolation

- context/source reference 不授予 read、write、network、tool 或 completion authority；
- Governance 只消费已准入 source；
- Prompt Injection 硬保证是正文不能升级 authority/permission/tool-routing；
- 模型分析质量和语义鲁棒性属于独立质量指标。

### 6. Conformance evidence

adapter 应按能力提供其可观测的 model-visible request components。具体 manifest schema、
capability profile、budget confidence 和 body-free receipt 尚未批准，必须由 G0–G7 experiment/
spike 决定。

在这些实验前，`ContextGovernanceRole` 只是跨 owner conformance 责任，不批准中央 Prompt
service、public port 或新 MetadataKind。

## Consequences

- OpenPilot 可以诚实声明治理边界，而不声称控制 provider-hidden internals；
- full-history/全仓库不再被误作安全 fallback；
- required-fact 指标不再制造 epistemic completeness 假象；
- 新 harness 可以按 conformance level 接入，unsupported route 不冒充 fully governed；
- memory、provider adapter、permission 和 evidence owners 保持各自职责。

## Rejected alternatives

### 统一中央 Request Builder

这会把 memory、provider transport、tool schemas、permission 和 audit 聚合成新的
mega-controller，并削弱 provider/harness 可替换性。

### 对不可见 provider internals 也宣称完整治理

无法提供可验证 evidence，属于不可证伪保证。

## Validation

G0–G7 的问题、比较和 gate 由
[`../EVALUATION_PLAN_CN.md`](../EVALUATION_PLAN_CN.md) 管理；具体实验由
[`../../../../experiments/metadata_control_plane/README_CN.md`](../../../../experiments/metadata_control_plane/README_CN.md)
路由。
