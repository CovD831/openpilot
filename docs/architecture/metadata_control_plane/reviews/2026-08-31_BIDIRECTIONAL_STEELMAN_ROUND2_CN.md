# Metadata Control Plane 第二轮双向钢人论证

> Status: Completed analysis
> Authority: Deliberation evidence; architecture/evidence/ADR owners decide adoption
> Owner: Architecture review
> Supersedes: None; evaluates the ADR-0002-constrained architecture
> Last reviewed: 2026-08-31

## 1. 共同事实与论证规则

双方接受以下事实：

- Pi/harness 已经能隐式形成执行轨迹；
- OpenPilot 当前已经拥有 metadata、admission、Action Gateway、Evidence Core、completion
  和多种 recovery 边界；
- E03/E04 支持局部 projection/pruning 机制，但不支持独立 provider 总经济性结论；
- ADR-0002 已把 JIT/tree/world-model 降为可选策略；
- 当前架构仍未进入 production refactor，metadata inventory 和 clean review baseline 未完成。

支持方不能用“未来可能有用”证明新 contract；反对方不能把已有 permission/evidence/
recovery 价值归零。双方都必须回答维护成本和可证伪性。

## 2. 支持方的最强论证

### 2.1 薄控制平面解决的是 harness 的责任空白

模型回合可以决定下一步做什么，但不应单独决定什么被允许、什么已发生、什么已验证、
中断后从哪里继续。把这些跨回合事实交给可演化 metadata，是控制平面而不是第二 agent
loop。即使 JIT 和树永不实现，这个责任边界仍然成立。

### 2.2 ADR-0002 让项目不再押注单一研究假设

项目价值不再依赖“显式动态链必然优于隐式链”。最小系统可以停在现有 authority + durable
evidence/recovery + governed context boundary；JIT/search 失败只会删除可选 policy，不会推翻
内核。这显著降低了架构赌注。

### 2.3 Metadata evolution 是当前系统迟早必须支付的成本

metadata-first 系统如果没有 owner、producer/consumer、版本、迁移、deprecation 和 usage
audit，严格模型最终也会积累成无法删除的字段集合。ME0–ME5 即使不服务 JIT/tree，也能
直接改善当前 contract 的可维护性和历史恢复可靠性。

### 2.4 Context boundary 可以独立于 token 优化产生价值

source、trust、freshness、required facts、budget failure 和 fallback 是安全边界；它们在 full
source view 上也有意义。选择性 projection 只是同一治理边界上的可选优化，因此可以被
实验否决而不丢失上下文治理价值。

### 2.5 显式结构只需捕获真正跨边界的决定

支持方不要求保存模型所有隐式候选。只有 durable dependency、恢复点、不可逆副作用前的
strategy commitment 或独立验证边界才值得结构化。若 proposal 复用现有 episode exit、
body-free 且确定性 admission，显式化可以带来审计和局部恢复，而不必复制整套推理树。

### 2.6 持续收缩门能约束重构的组织惯性

许多 strangler refactor 最终停在“双系统永久共存”。usage telemetry、single writer、
usage-zero 和 separate deletion 把删除责任写进路线，而不是留给未来。这是对当前大
controller 和 legacy paths 的直接回应。

### 2.7 可替换 harness 是长期保险

provider、模型和 harness 会变化。只要 task authority、permission、evidence、completion
和 recovery 不依赖 Pi 内部状态，替换执行引擎时就不需要重建长期事实。这种隔离在 provider
上下文更长、更便宜时仍然有价值。

### 2.8 支持方的最小承诺

支持方只需要证明：

- always-on kernel 不增加模型决策回合；
- metadata evolution 能减少 drift 和不可删除字段；
- context governance 能 full-source fallback；
- 每个 production seam 带来净依赖/概念收缩；
- 可选 optimization 失败后能完整删除。

它不需要预先证明 MCTS、树或显式 JIT 一定上线。

## 3. 反对方的最强论证

### 3.1 “薄”仍可能只是命名

目标文档仍列出 Metadata Kernel、Evolution、Evidence、Graph View、Context、Search、
Governed Execution、Recovery，以及十个语义 ports。即使每个都声称可选，团队仍可能围绕
它们创建 package、protocol、registry 和状态机。文档的概念规模已经可能超过当前问题。

### 3.2 Kernel 尚未被 inventory 证明稳定

把当前 envelope 称为 stable kernel 可能过早。真正的 producer、consumer、历史 payload、
外部 API 和恢复使用尚未完成 ME0/ME3/ME5。如果 inventory 后发现字段含义、owner 或版本
边界需要调整，所谓“稳定底座”仍会变化。

### 3.3 Episode 边界并不天然稳定

不同 harness 对一次模型调用、多轮 tool loop、interrupt、retry 和 resume 的切分不同。
如果 Control Plane 用 episode 决定持久化什么，harness 替换反而会改变 metadata 粒度，
破坏其自称的可替换性。

### 3.4 Context governance 很容易重新滑向上下文编排器

required-fact closure、purpose、freshness、trust、dependency、summary、resolution、on-demand
和消费审计本身就是一套复杂系统。full-history 虽贵但直接；如果 selective arm 没有真实
provider 总收益，这些 selector 和 receipt 的维护成本可能超过节省。

### 3.5 显式 trigger 会复制模型已经做过的判断

“是否需要拆分”“是否高成本”“是否会返工”仍需要模型或启发式判断。把判断编码成 typed
trigger 可能只把隐式不确定性包装成确定字段，并增加 serialization/admission/recovery
failure modes。

### 3.6 收缩指标可能制造虚假进步

删除一个 branch 或 `Any` 很容易计数，但新 abstraction、adapter、migration 和 telemetry
引入的认知成本更难量化。团队可能在数字上减少依赖，实际让调用路径更长、更难调试。

### 3.7 Metadata evolution 可能成为自我维护的官僚系统

registry、catalog、impact note、migration corpus、usage audit、deprecation ledger 和 ADR 都要
同步。对小团队而言，治理成本可能让简单字段修改变慢，而 drift 检查本身也会漂移。

### 3.8 证据仍离真实产品收益很远

当前局部实验没有独立 provider samples、native token/call/latency 和真实长任务失败分布。
在这些证据前，重构组织结构仍可能是用理想化 fixture 反向塑造生产代码。

### 3.9 反对方的最小主张

反对方不需要证明 metadata 无用。只要证明以下任一项，就足以停止扩张：

- current owners 已经足够，registry/ports 只增加同步工作；
- root-only 存在不可忽略的 schema/token/latency overhead；
- selective context 无法稳定证明 required-fact closure；
- structural trigger 与 harness 内部决策高度重复；
- complexity ledger 无法显示净收缩；
- recovery 原子性仍依赖完整 workflow engine。

## 4. 双方最关键的交锋

| Question | 支持方最强回应 | 反对方仍成立的反击 | 可裁决证据 |
| --- | --- | --- | --- |
| 为什么不只用 Pi？ | Pi 不拥有长期 permission/evidence/completion/recovery | 当前 owner 已存在，未必需要新 Control Plane ports | T0 + Phase 3 单切片依赖/行为对比 |
| Context 是否属于内核？ | source/freshness/fallback 属于治理 | selective selector/summary 不属于内核 | T2 分离 governed full-source 与 selective arm |
| 显式 JIT 是否重复？ | 只捕获跨边界 commitment | trigger 仍可能复制模型判断 | T1 + J0–J4，必须报告治理全部成本 |
| “薄”如何证明？ | root-only 无结构对象、无新 round、无新 durable write | token/schema/latency 仍可能上涨 | T0 thinness conformance |
| 新 ports 是否值得？ | 能隔离 harness 并删除反向依赖 | wrapper 可能增加调用深度 | T3 net complexity ledger + end-to-end trace |
| Graph/store 是否必要？ | derived view 可重建、能回答跨 owner 查询 | ME6 可能是无真实需求的早期平台化 | query inventory 后再决定 ME6；T4 authority sentinel |
| Metadata evolution 是否过重？ | 长期兼容和删除需要机器证据 | 流程成本可能高于字段风险 | 对 2–3 个真实高压 contract 做 ME0–ME5 pilot |

## 5. 钢人后的架构回应

双方共同支持的最稳妥结构不是“完整 Control Plane”，而是三个可独立否决的 profile：

### Profile A：Authority Kernel（always on）

```text
current typed task/admission/permission facts
+ Evidence Core / receipts
+ verification/completion
+ checkpoint/recovery identity
+ metadata evolution rules
+ replaceable execution adapter boundary
```

约束：不增加 provider round，不要求 Search/Scheduler/Candidate public objects，不建立第二
authority。

### Profile B：Context Boundary Governance

```text
source / trust / freshness
+ required-fact and full-request budget checks
+ governed full-source fallback
```

约束：即使 selective optimization 被关闭，Profile B 仍能工作。

### Profile C：Optional Optimizations

```text
selective projection / summary / on-demand
-> explicit top-1 JIT
-> top-k/tree
-> optional World Model
```

约束：每层相对上一层单独证明 quality、total cost、recovery 和 maintenance value；失败即
删除，不反向改变 A/B authority。

## 6. 必须增加的五个约束

1. **Adapter-neutral boundary**：用 admitted request/observation/receipt identity 定义一次
   execution attempt，不依赖某个 provider 的“episode”概念。
2. **Structural escalation contract**：typed trigger + evidence + budget + cooldown + deterministic
   fallback；自然语言理由不控制。
3. **Thinness telemetry**：治理开销包括 provider calls/tokens、tool schema、typed exit、
   projection build、serialization、durable writes 和 storage，不只看额外调用数。
4. **Net complexity ledger**：同时记录删除和新增的 concepts、dependencies、branches、owners、
   adapters、fallbacks 与调用深度。
5. **Authority/storage distinction**：禁止第二 authoritative writer；shadow/derived 表示必须
   canonical writes=0、可重建、可过期。

## 7. 调整后的实验顺序

```text
T0 root-only thinness conformance
  -> ME0/ME3/ME4 inventory and duplication
  -> ME1/ME2/ME5 real-contract evolution pilot
  -> T2 governed full-source vs selective projection
  -> C5/C6 security and full-request budget
  -> T1/T5 structural boundary and adapter-neutral trace
  -> J0–J4 explicit top-1 incremental value
  -> T3 real cutover/contraction rehearsal
  -> conditional ME6/query view
  -> only then S0–S6
```

这一顺序把“证明薄、证明当前 metadata 可演化、证明 context 安全”放在显式链和树之前。

## 8. 综合裁决

第二轮钢人后的结论是：

> **OpenPilot 最有竞争力的定位仍是 metadata-first authority and recovery substrate，而不是
> planner 或 tree-search framework；但必须把 context slimming 从内核中拆出，并用可执行
> thinness contract 证明 Control Plane 没有复制 harness。**

保留正向优势的方式不是继续增加防御性模块，而是让每个 profile 可独立运行、测量、否决
和删除。若 Profile C 全部失败，Profile A/B 仍应形成一个更小但有价值的产品；若 A/B 本身
不能减少当前复杂度或改善长期一致性，则应停止这次重构，转为局部清理现有 controller。
