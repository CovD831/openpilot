# Metadata Control Plane 第三轮双向钢人论证

> Status: Completed analysis
> Authority: Deliberation evidence; architecture/evidence/ADR owners decide adoption
> Owner: Architecture review
> Supersedes: None; evaluates Context Governance after ADR-0003
> Last reviewed: 2026-08-31

## 1. 本轮争点

双方不再争论“治理与优化是否分开”，而是争论：

1. Context Governance 是否真的应该成为每个 harness route 的必选合同；
2. OpenPilot 能治理到最终 provider request 的哪一层；
3. required-fact、full-source 和 prompt-injection 能承诺什么；
4. 这项能力是否构成项目竞争力，还是所有 harness 都有的普通功能。

## 2. 支持方的最强论证

### 2.1 所有模型请求客观上都有上下文边界

无论 harness 是否显式建模，它都必须决定 messages、instructions、tools、历史、项目内容和
输出预算。把这个边界交给隐式字符串拼接不会消除治理，只会让治理不可审计。OpenPilot
把它绑定到 metadata authority，是把已有事实显式校验，不是发明新的模型循环。

### 2.2 当前实现不是从零开始

ContextCandidate 已有 retention/trust/freshness，ContextAssembler 已能阻止 stale required、
冲突和预算遗漏，PreparedContextRequest 在 assembly 非 READY 时不产生请求。Pi sidecar
还关闭默认 context files、prompt templates 和 builtin tools。这些都是统一 conformance 的
现实种子。

### 2.3 Governance 与 Optimization 分离后风险显著下降

基础层可以使用 governed source baseline，不需要 summary、selector 或额外 provider call。
因此 selective injection 被否决时，permission、required facts、freshness 和 prompt-injection
边界仍然存在，不会把安全与节省 token 绑定。

### 2.4 Cross-harness conformance 支撑可替换性

如果 Pi、direct provider 和未来 harness adapter 都声明相同的 model-request manifest 与
capability level，task authority 和 recovery 就不依赖某个 Prompt builder。不同 adapter
可以用不同 wire format，但必须证明相同控制事实没有丢失。

### 2.5 Capability profile 已有成功先例

reasoning policy 已通过显式、版本化 profile 避免从 model name 猜能力。Context Governance
可以复用这一模式描述 roles、tool schema visibility、token budget confidence、caching 和
request-manifest 支持，而不是建立 provider 条件分支。

### 2.6 真正差异化是与长期 authority/recovery 的连接

普通 harness 也会拼上下文，但通常不会把每个 required fact、permission、freshness、receipt
和 checkpoint 恢复身份绑定到同一 typed evidence chain。OpenPilot 的价值不是“有 Prompt”，
而是 context route 与长期权威状态一致。

## 3. 反对方的最强论证

### 3.1 Context assembly 是 harness 的本职，不是产品护城河

主流 harness 已经维护 instructions、tools、history、compaction 和 provider window。再增加
OpenPilot conformance 可能只是重复检查，降低 provider-native caching 和优化空间。

### 3.2 OpenPilot 看不见真正完整的请求

Pi/provider 可能添加隐藏 system policy、tool encoding、cache metadata、安全 wrapper 和
token accounting。OpenPilot 若只能看到 prompt，就无法诚实声称治理“完整 request”。

### 3.3 Required facts 永远是不完备集合

任务真正需要什么往往要在执行中发现。把已声明 facts 全部注入只证明 schema 完整，不
证明任务不会漂移。过度依赖 required-fact closure 可能制造虚假安全感。

### 3.4 Governed baseline 仍可能很大

长期任务的 mandatory facts、tool roundtrips 和 source pack 自身就可能超过窗口。fallback
最终仍是重新分解或 safe-stop，Context Governance 不能消除信息论约束。

### 3.5 Provider-specific budget 无法完全抽象

不同 provider 的 tokenizer、tool encoding、reasoning reserve、cache 和 output accounting
不同。统一 capability profile 可能快速膨胀成第二 provider SDK。

### 3.6 Prompt injection 不能被结构化字段完全解决

即使恶意文本不能授予权限，它仍可能诱导模型选择错误工具参数、错误分析或消耗预算。
“authority isolation”不能等同于模型鲁棒性。

### 3.7 Audit 会带来隐私和存储成本

要证明 request 完整，就倾向于保存 messages、tools 和 source content；但这些可能包含源码、
凭据和敏感历史。body-free receipt 又可能不足以复现语义问题。

### 3.8 Universal conformance 会拖慢 harness 接入

如果每个新 adapter 都必须先支持完整 manifest、tokenizer 和 audit，OpenPilot 会失去快速
接入新模型/harness 的能力，违背“执行引擎可替换”的目标。

## 4. 最强回应与仍然成立的反击

| Objection | 支持方回应 | 仍然成立的限制 | 裁决方式 |
| --- | --- | --- | --- |
| 每个 harness 都会拼上下文 | OpenPilot 治理的是 metadata authority 一致性 | 不能把普通 assembly 当差异化 | 定位只强调 cross-harness authority/recovery binding |
| 看不见完整 provider request | adapter 暴露其 model-visible manifest | hidden provider internals 仍不可见 | 明确 observation boundary 和 conformance level |
| required facts 不完备 | 只承诺 declared-required coverage | latent dependency 仍需运行中发现 | G2 negative controls + REQUEST_CONTEXT/safe-stop |
| baseline 太大 | typed budget failure 比静默截断安全 | 不能保证所有任务继续执行 | 报告 safe-stop/redecomposition rate，不伪装成功 |
| capability profile 会膨胀 | 只登记治理所需最小能力 | provider 差异仍可能高频变化 | profile admission gate + unsupported fallback |
| injection 仍影响模型 | authority/tool-routing 不受正文授予 | 语义质量仍可能下降 | safety 与 robustness 两套指标 |
| audit 泄漏内容 | body-free refs + redaction/retention | 语义复现可能不足 | G6 回答审计问题集，而非保存全部正文 |
| 接入变慢 | 支持分级 conformance | partial route 不能宣称 fully governed | G0–G2 levels + explicit unsupported status |

## 5. 钢人后的最窄模型

### 5.1 Control Plane 拥有合同，不拥有所有 rendering

```text
Metadata authorities
  -> required/control source decisions
  -> adapter request manifest
  -> governance conformance decision
  -> adapter-specific wire request
  -> observation / receipt
```

memory 可以生产 candidates，provider/Pi adapter 可以生产最终 wire manifest，但任何一方都
不能独自授予权限、声明完成或伪造 token confidence。

### 5.2 三层 context profile

```text
Authority Context
  typed task/permission/acceptance/recovery facts

Governed Request Envelope
  admitted source pack + instructions/data separation
  + freshness/trust + known tools/fixed components + budget confidence

Optional Optimization
  selection / summary / on-demand / resolution / consumption tuning
```

前两层对 OpenPilot-supported routes 必选，第三层可完全关闭。

### 5.3 保证必须按可观测性分级

- **Known and verified**：OpenPilot/adapter 能提供 manifest 和 source binding；
- **Known but estimated**：token budget 等只能近似，带保守 margin；
- **Provider-hidden**：明确不在治理保证内；
- **Unsupported**：route 不准入或只能进入低等级、无 rollout claim 的模式。

## 6. 对项目定位的影响

合理定位不是：

> OpenPilot 比其他 harness 更会选择 Prompt。

而是：

> OpenPilot 用可演化 metadata 把 context、permission、evidence、validation 和 recovery
> 绑定成跨 harness 一致的 request conformance；选择性 context 只是可插拔优化。

这保留了 metadata-first 的差异化，同时承认 context assembly 本身是行业基础能力。

## 7. 调整后的实验顺序

```text
G0 final request manifest visibility
  -> G5 adapter capability levels
  -> G1 governed-source baseline
  -> G2 declared/latent fact boundary
  -> G3 token-budget confidence
  -> G4 authority isolation vs semantic robustness
  -> G6 receipt privacy/audit sufficiency
  -> G7 governance-only overhead
  -> optional C-Opt experiments
```

JIT/tree 只消费已经标明 conformance level 的 context route，不参与证明 Context Governance。

## 8. 综合裁决

第三轮钢人后的结论是：

> **Context Governance 应作为所有 OpenPilot-supported model-request routes 的必选
> conformance contract，但不应成为中央 Prompt service，也不应承诺治理 provider-hidden
> internals、未知 required facts 或全部信息。**

如果 adapter 无法暴露足够 request manifest，诚实降级或拒绝支持比伪造统一治理更重要。
如果 G0–G7 显示 conformance 成本高于它对权限、恢复和一致性的增量价值，则应把治理保留
在当前 request builders 内，只维护最小跨 harness invariant，而不新建 Control Plane 模块。
