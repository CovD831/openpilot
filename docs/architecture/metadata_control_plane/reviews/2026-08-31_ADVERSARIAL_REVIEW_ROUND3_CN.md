# Metadata Control Plane 第三轮对抗性架构审查

> Status: Completed review
> Authority: Review evidence only; architecture owners decide and apply corrections
> Owner: Architecture review
> Supersedes: None; reviews the ADR-0003 context split
> Last reviewed: 2026-08-31

## 1. 审查结论

结论：**ADR-0003 的分层方向成立，但“每个 harness 都必须做 Context Governance”需要被
收窄为“每个由 OpenPilot 准入的 model-request route 必须满足治理 conformance”。**

Context Governance 不应被实现为一个中央 Prompt builder，也不能声称完全理解任意外部
harness 的隐藏 request。它应是最终 model-visible request 边界上的可验证合同：adapter
提供其可见组件和能力，Control Plane 校验权威事实、来源、预算和 fallback；无法提供完整
证据的 route 标为 partial/unsupported，而不是假装 100% 治理。

本轮还确认：`governed full-source` 容易被误解为完整仓库/完整历史。安全基线应改称
**governed source baseline**：完整保留声明为 mandatory/control 的事实，对一个明确 admitted
source pack 不做选择性 omission；它不意味着把所有可读取信息注入模型。

因此，本轮对 ADR-0003 方向通过，对 universal request builder、全知 required-fact closure、
不可见 provider request 的“完整治理”主张不通过。

## 2. 当前实现证据

当前代码已经提供可复用种子：

- [`ContextRequestBuilder`](../../../../Code/src/memory/context_assembly/request_builder.py)
  在 assembly 非 `READY` 时不构造 request，并区分 governance 与 budget failure；
- [`ContextAssembler`](../../../../Code/src/memory/context_assembly/assembler.py) 已处理 required、
  trust、freshness、冲突、重复和 compaction binding；
- [`ContextCandidate` metadata](../../../../Code/src/metadata/agent_runtime.py) 已有 retention、
  trust、freshness 和 purpose 等 typed values；
- [`reasoning.py`](../../../../Code/src/core/reasoning.py) 已有显式、版本化 provider capability
  profile，且不从 model name/hostname 猜能力；
- [`PiRpcEngine`](../../../../Code/src/autonomous_iteration/engines/pi_sidecar.py) 禁用 Pi context
  files、prompt templates 和默认 tools，并由 OpenPilot 控制 prompt/tool bridge。

但当前种子也暴露边界：

- `ContextRequestBuilder` 主要组装 message candidates，不天然拥有最终 advertised tool schemas、
  provider wrapper、provider safety margin 或 transport-native token count；
- `ContextAssembler` 在 tokenizer 不可用时回退字符预算，不能证明 provider window 精确适配；
- `PiRpcEngine.run_once` 向 sidecar 传入 prompt，但当前协议没有返回最终 provider request
  manifest；OpenPilot 无法仅凭 prompt 声称看见 Pi/provider 的全部 model-visible bytes；
- reasoning capability profile 可作为模式，但目前只描述 reasoning controls，不等于完整
  context/request capability profile。

## 3. 第三轮 Findings

| ID | Severity | Finding | Failure mode | Required correction / evidence |
| --- | --- | --- | --- | --- |
| A3-01 | Required | “每个 harness”范围过宽 | 被解释为 OpenPilot 可以治理任意外部 harness/provider 内部请求 | 改为每个 **OpenPilot-admitted model-request route**；外部不可见部分必须声明 out-of-scope/unsupported |
| A3-02 | Critical before baseline | `governed full-source` 语义不明确 | 被实现成完整仓库、完整历史或所有 admitted-readable 数据，预算必然失控 | 定义 `governed source baseline`：mandatory/control facts 完整 + 明确 source pack，无 optimization omission；不等于所有潜在信息 |
| A3-03 | Critical before closure claim | required-fact closure 只能证明“已声明 required facts 被选入”，不能证明没有未知关键事实 | 把 schema coverage 误写成 epistemic completeness，模型仍可能缺少未声明依赖 | 指标改为 declared-required coverage；latent gap 用 negative controls、REQUEST_CONTEXT 或 safe-stop，不宣称全知 |
| A3-04 | Critical before cross-harness conformance | 当前 OpenPilot 未必看见最终 provider request 的 tool schemas、wrapper 和 hidden provider components | 预算、prompt-injection 和审计只覆盖局部 request，却报告完整治理 | adapter 提供 versioned model-visible request manifest；无法提供时 conformance 降级，不得通过 full-request gate |
| A3-05 | Required | Context Governance 缺 adapter capability profile | 不同 transport 的 roles、tool schemas、tokenizer、caching、output reserve 和 safety margin 被统一假设 | 复用 reasoning capability profile 模式，建立最小 context/request capability view；不得从 model name 推断 |
| A3-06 | Required | Governance 与 Optimization 仍可能在实现中重新混合 | Governance 为分类/摘要再次调用模型，产生固定 token/延迟和不可重复性 | Governance 必须 deterministic/provider-free；任何 provider-assisted classification/summary 属于 optional optimization |
| A3-07 | Required | Full-request budget 的精度等级未定义 | char proxy、近似 tokenizer 和 provider-native count 被混为同一安全证明 | 记录 exact/native/estimated/char-only budget confidence；不足以证明 fit 时保守 margin 或 typed failure |
| A3-08 | Required | Prompt-injection isolation 容易被理解为模型不受内容影响 | 无法保证模型语义上完全忽略恶意文本 | 硬门只承诺 authority/permission/tool-routing 不升级；模型内容偏差作为质量/robustness 指标单独报告 |
| A3-09 | Required | Context source reference 可能被误当读取授权 | adapter 为满足 baseline 自动加载未 admitted 文件、memory 或远端内容 | Governance 只消费已准入 source；reference、support context 或 model request 不创建 read/network authority |
| A3-10 | Required | Request audit/receipt 的最小持久化边界未定 | 保存完整 request 泄漏源码/凭据；只保存 hash/计数又无法回答审计问题 | 预注册 body-free manifest、source refs、policy/capability version、budget confidence 和 redaction；正文按既有 evidence policy 管理 |
| A3-11 | Required | `ContextBoundaryPort` 可能过早成为中央 request service | memory 层吸收 provider/tool/permission/transport responsibilities，形成新 mega-controller | 先定义 conformance role；最终 request manifest 由 adapter 暴露，authority owner 各自保持不变，inventory 后再决定是否需要 port |
| A3-12 | Required for positioning | “上下文治理”本身不是独特竞争力 | 每个 harness 都拼 Prompt，项目定位退化成通用基础功能 | 差异化必须表述为 metadata-bound、permission-aware、recovery-linked、cross-harness conformance，而不是“我们也管理上下文” |

## 4. 必须收窄的三个概念

### 4.1 Harness scope

正确范围：

```text
all model-request routes admitted and claimed as supported by OpenPilot
```

不包括：

- provider 内部不可见 system/safety prompt；
- 未通过 OpenPilot adapter 的外部 harness 调用；
- adapter 无法声明的 hidden caching/token accounting；
- 用户绕过 admission 直接发出的请求。

### 4.2 Governed source baseline

建议定义：

```text
complete mandatory/control facts
+ one explicit admitted task/source pack
+ required tool-roundtrip state
+ known fixed request components
+ conservative output reserve and safety margin
- no optional selector omission
- no summary replacement
- no on-demand deferral of declared-required facts
```

它是 selective optimization 的对照，不是“所有历史全部注入”。

### 4.3 Declared-required coverage

Governance 能证明：

- 所有被 authoritative owner 声明为 required 的 facts 已选入或触发 failure；
- source identity/freshness/permission 与 request manifest 一致；
- required facts 没被 selector、summary 或预算静默替换。

Governance 不能证明：任务不存在尚未发现的依赖、模型一定理解了事实，或任何事实都足以
完成任务。

## 5. 建议的 Conformance Levels

| Level | Guarantee | Required evidence |
| --- | --- | --- |
| G0 Authority boundary | source refs 不扩大权限；required/control facts 不静默省略 | admission refs、candidate decisions、failure path |
| G1 Governed request | instructions/data、freshness、trust、known fixed components 和 output reserve 已校验 | model-visible request manifest + capability version |
| G2 Auditable request | request identity、source decisions、budget confidence、redaction/retention 可追踪 | body-free durable receipt + evidence refs |
| G3 Optional optimization | selection/summary/on-demand 相对 G1 baseline 有增量收益 | paired provider-native quality/cost telemetry |

adapter 只能声明它实际证明的最高等级。G0/G1 未通过的 route 不得标记为 fully governed；
G3 失败只关闭 optimization。

## 6. 第三轮实验 / Spike 矩阵

| ID | Question | Minimal design | Pass gate |
| --- | --- | --- | --- |
| G0 Request-manifest completeness | OpenPilot 能看到哪些最终 model-visible components | direct LLM route、Pi route、recorded adapter 对同一 request 枚举 messages/tools/fixed/reserve | known components 100% 对齐；unknown 显式降级，不伪造 full conformance |
| G1 Governed-source baseline | baseline 是否有界且不等于完整历史 | 多规模任务比较 mandatory pack、explicit source pack、all-history | mandatory coverage=100%；baseline 大小可解释；all-history 不作为定义 |
| G2 Declared vs latent facts | closure claim 是否过度 | declared-required、hidden dependency、undeclared latent dependency 三类 fixture | declared coverage 精确；latent unknown 不伪装 complete；REQUEST_CONTEXT/safe-stop 正确 |
| G3 Budget confidence | token/window fit 是否可靠 | native tokenizer、known tokenizer、estimate、char-only 四档 | confidence 分层；误差越界 fail closed；不把 char proxy 写成 exact |
| G4 Authority isolation | 恶意内容能否扩大权限或工具面 | project/web/tool/memory injection + source-hint escalation | permission/read/network/tool-routing escalation=0 |
| G5 Adapter capability | 不同 harness 能否声明可支持治理级别 | Pi/direct/recorded adapters 的 versioned capabilities | unsupported fields 不猜测；route admission 与能力一致 |
| G6 Receipt privacy | 审计是否不泄漏正文/凭据 | body-free receipt、redaction、retention/rebuild rehearsal | credential/body leakage=0；必要 source/policy/budget 问题可回答 |
| G7 Governance overhead | 必选层是否足够薄 | current request path vs governance-only path | provider calls delta=0；build/serialization/storage 开销在预注册界内 |

## 7. 与现有实验的关系

- C5/C6 可以为 G3/G4 提供 fixture，但不能证明 Pi/direct adapters 的 request manifest 完整；
- E03 local-injection 支持 optional selection/fallback 机制，不回答 G0/G5；
- 当前 ContextAssembler tests 可以支持 G0 authority/failure seed，但 char/token fallback 必须
  在 G3 中单独分层；
- JIT/tree 实验只应消费达到声明 conformance level 的 context route，不能顺带证明治理。

## 8. 最终裁决

保留 ADR-0003 的核心决定，但建议下一次架构修订采用以下措辞：

> OpenPilot 为每个由其准入并声明支持的 model-request route 定义 Context Governance
> conformance；adapter 暴露 model-visible request manifest 和能力，Control Plane 校验
> metadata authority、source、freshness、预算与 fallback。选择性上下文机制是独立优化。

在 G0–G7 前，不批准新的 universal ContextBoundary service，不把 `full-source`、required-fact
closure 或 prompt-injection isolation 写成超出可观测边界的保证。
