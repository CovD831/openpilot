# Metadata Control Plane 第二轮对抗性架构审查

> Status: Completed review
> Authority: Review evidence only; architecture owners decide and apply corrections
> Owner: Architecture review
> Supersedes: None; follows the first adversarial review after ADR-0002
> Last reviewed: 2026-08-31

## 1. 审查结论

结论：**“薄 Metadata Control Plane”方向经受住了第二轮攻击，但“薄”仍是架构原则，尚未
成为可执行的运行与迁移合同。**

ADR-0002 成功消除了第一轮最危险的方向性问题：JIT/tree/world-model 不再是项目成立条件，
Pi 保留 episode 内普通推理，新抽象必须伴随旧复杂度收缩。第二轮没有发现必须放弃
metadata-first control plane 的理由。

但是，当前文档仍有四类实施风险：

1. 把“上下文治理”与“选择性缩减”绑定，导致未充分验证的优化机制仍出现在最小架构中；
2. `episode`、structural trigger 和“高成本选择”等边界尚不能由确定性事实稳定判定；
3. “每切片删除一个旧路径”可能被 Goodhart 化，诱发过早删除或形式化拆分；
4. “无额外 provider round”“无第二 store”只约束了表面形态，没有完整约束 token、schema、
   serialization、shadow storage 和双路径成本。

因此，本轮对 **只读 inventory、shadow 和 experiment-only spike 条件通过**；对 production
port、selective projection default、显式 JIT 和 durable structure 仍不通过。

## 2. 审查范围

本轮针对第一轮修订后的权威设计：

- [`../adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md`](../adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md)；
- [`../PROJECT_CHARTER_CN.md`](../PROJECT_CHARTER_CN.md)；
- [`../TARGET_ARCHITECTURE_CN.md`](../TARGET_ARCHITECTURE_CN.md)；
- [`../REFACTOR_ROADMAP_CN.md`](../REFACTOR_ROADMAP_CN.md)；
- [`../EVALUATION_PLAN_CN.md`](../EVALUATION_PLAN_CN.md)；
- runtime、context、search、mapping 和 metadata evolution 文档。

本轮不改写第一轮 review 快照，不把建议自动升级为 architecture decision，也不审查当前
dirty worktree 中与本架构文档无关的生产改动。

## 3. 第二轮 Findings

| ID | Severity | Finding | Failure mode | Required correction / evidence |
| --- | --- | --- | --- | --- |
| A2-01 | Required | 最小成立架构仍包含 `source-governed context projection`，但 required-fact closure 和真实 provider 总成本尚未通过 | 未验证的 selective slimming 被误认为内核依赖 | 把 **Context Governance/Fallback** 与 **Selective Projection Optimization** 分层；内核允许 governed full source view，选择性缩减继续走 C 组 gate |
| A2-02 | Critical before JIT | `episode` 是 harness/provider 相关概念，尚无 adapter-neutral 起止和重入语义 | 更换 harness、provider abort 或多轮 tool call 后，哪些事实跨界会漂移 | 以 admitted execution request/observation boundary 定义 episode/visit；用现有 Run/request/response identity 映射，inventory 前不新建 contract |
| A2-03 | Critical before structural proposal | structural trigger 仍是自然语言列表；“高成本 strategy choice”“显著影响返工”没有确定性判据 | 模型 explanation 或 controller 经验规则重新获得结构控制权 | 冻结 typed trigger vocabulary、owner、required evidence、cooldown 和 fallback；自由文本只能解释，不能触发持久化或新节点 |
| A2-04 | Required | `root-only 不增加 provider round` 没覆盖 exit schema、tool exposure、serialization、projection 和 persistence 开销 | 没有新调用但 prompt/output/latency/storage 增加，仍被报告为零成本 | T0 同时比较 calls、native input/output tokens、tool-schema bytes、typed exit bytes、build latency、durable writes 和 task quality |
| A2-05 | Required | “每个生产切片至少删除一个旧 consumer/branch/dependency”容易被 Goodhart 化，并与 shadow 并存期冲突 | 为满足计数删除安全 fallback，或把一个旧分支拆成多个新概念后仍声称收缩 | 区分 experiment/shadow、migration cutover 和 deletion slice；使用 net complexity ledger，不以原始删除数量单独过门 |
| A2-06 | Required | “不新增第二 durable store”混淆了 authority 与物理存储 | 合理的 store migration/shadow index 被禁止，或团队绕过约束隐藏临时副本 | 禁止第二 **authoritative writer/store**；允许有 TTL、canonical writes=0、可重建、明确销毁门的 shadow index，迁移期保持 single authoritative writer |
| A2-07 | Required | ME6 derived graph 被放进 Phase 1 registry CI 前门，但 graph 在 ADR-0002 中是非必要能力 | 可选 graph 反向成为 metadata evolution 的前置依赖 | ME0/ME3/ME4 作为 inventory gate；ME6 只在真实重复跨 owner 查询达到预注册门后启动，不阻塞 registry consistency |
| A2-08 | Required | Port admission gate 把 `test double` 作为显式 port 的充分候选理由之一 | 为测试便利创建大量 production abstraction，概念数继续增长 | test double 不能单独证明 port；必须存在真实 adapter/owner/volatility boundary，或可度量地删除反向依赖/宽类型 |
| A2-09 | Required | Runtime participant/main sequence 始终列出 Search Policy、Scheduler、CandidateProposal | 实现者可能在 root-only 路径仍构造空 policy/scheduler 生命周期 | 文档定义 null/absent structural mode：无 typed trigger 时不调用、不实例化、不持久化 search/scheduler/candidate 对象 |
| A2-10 | Required | “已登记未来 consumer”可能成为 speculative metadata 的持久化豁免 | 为尚未实现的 feature 预埋字段，破坏最小 kernel | 未来 consumer 只有在已批准 migration/experiment、owner、expiry 和 removal gate 同时存在时才可进入 experimental namespace；不能进入 authoritative durable state |
| A2-11 | Required | 文档称 `MetadataBase` 为稳定 structural kernel，但 ME0/ME3/ME5 尚未完成 | “稳定”被误读为已验证且无需删改 | 在实验通过前称为 **provisional current envelope**；稳定性是待验证 claim，不是 inventory 前事实 |
| A2-12 | Critical before merge | 架构目录仍处于大型 dirty worktree 中，缺少可审查 baseline | 后续 diff 无法区分历史改动、文档决策和生产实现 | Phase 1 前建立不破坏用户改动的审查基线/变更清单；生产切片必须能独立列出 touched owners、tests 和 rollback |

## 4. 发现的内部张力

### 4.1 Context governance 不等于 selective projection

最窄内核真正需要的是：模型看到的上下文不能绕过 source、permission、freshness、required
facts 和 fallback。它不要求一开始就“选择最小充分集合”。

因此应区分：

```text
Context boundary governance
  source / trust / freshness / required facts / full-source fallback

Optional context optimization
  selectors / omission / summary / on-demand / token reduction
```

前者可以在 full source view 上成立；后者必须证明省 token 且不漂移。若两者不分，C 组实验
失败会错误地威胁整个 control plane。

### 4.2 Continuous contraction 不等于每次都立即删除

安全 strangler 必然有短期双路径。真正需要禁止的是无 owner、无 usage、无 sunset 的长期
并存，而不是任何 shadow overlap。收缩证据应按阶段记录：

| Stage | Required evidence |
| --- | --- |
| experiment/shadow | 不拥有 authority；记录对照和成本；可整体删除 |
| paired/default-off | 明确唯一 writer、fallback、usage 和退出门 |
| cutover | 新路径等价或更优；旧 producer 停写 |
| usage-zero | 旧 consumer/reader/恢复入口归零 |
| deletion | 历史语料、恢复、API 和 rollback 通过 |

### 4.3 No second authority 不等于 no second physical representation

缓存、shadow index、migration target 和 derived view 可能拥有物理数据，但只要 canonical
writes=0、可从 source 重建、不能授予权限或完成任务，它们不是第二 authority。约束对象
应是 writer/decision ownership，而不是文件或数据库数量。

## 5. “薄”必须成为可执行合同

建议增加一个 Thinness Conformance Profile。root-only 基线至少要求：

```text
structural_policy_invoked = false
candidate_generation_calls = 0
candidate_instances = 0
new_structural_durable_writes = 0
provider_round_delta = 0
governance_token/schema/serialization delta is measured
existing permission/receipt/validation/recovery gates remain enabled
```

长任务从 root-only 提升到结构模式时，必须有：

```text
typed trigger
trigger owner
bound evidence
admitted scope
budget
expiry/cooldown
deterministic reject/fallback
```

没有这些字段，所谓“只在必要时显式化”仍无法被测试。

## 6. 第二轮实验 / Spike 矩阵

| ID | Question | Minimal comparison | Pass gate |
| --- | --- | --- | --- |
| T0 Thinness conformance | root-only 是否真的接近零增量 | B0/B1 vs thin control-plane root-only，同任务同 provider | provider round delta=0；结构对象/写入=0；质量不劣；全部隐藏开销被计量 |
| T1 Structural escalation | typed trigger 能否稳定决定何时跨出 Pi | frozen traces：无需结构、context gap、durable dependency、rework、recovery | trigger precision/recall 达预注册门；unknown fail closed；自由文本不控制 |
| T2 Governance vs optimization | context 安全边界能否与 slimming 独立成立 | governed full source vs governed selective projection | 两臂 authority/fallback 相同；只有 selective arm 改变 token/selection |
| T3 Contraction ledger | 新 seam 是否产生净复杂度下降 | 选一个真实 read-only/current path 做 before/shadow/cutover rehearsal | concepts、dependencies、branches、consumers 和 fallback 风险综合下降；不能只报删除数 |
| T4 Authority/store sentinel | shadow representation 是否保持非权威 | source + derived/shadow index 的 mutation/freshness/rebuild fault | canonical writes=0；source revision 失效；删除 shadow 后可恢复 |
| T5 Adapter-neutral episode | 更换 harness/abort/resume 后边界是否一致 | 同一 admitted request 在 Pi adapter、recorded adapter、abort/retry 路径 | Run/request/observation identity 对齐；无重复副作用；completion owner 不变 |

T0–T5 是局部机制验证，不要求先实现完整 Control Plane。通过后再决定是否修改 L1/L2
Claim；失败则收缩相应机制，不扩大工程范围。

## 7. 第一轮 blocker 的继承状态

ADR-0002 没有自动关闭第一轮 AB-01–AB-07：

- revision/cursor/checkpoint 原子提交仍未解决；
- required-fact closure 和 prompt-injection/full-request 仍待 C5/C6；
- provider native telemetry 与独立样本仍缺；
- contract/registry reuse inventory 仍未完成；
- port 是否真正收缩依赖仍待真实切片；
- dirty worktree baseline 仍缺。

第二轮新增的 T0–T5 不能替代这些门，只负责验证 ADR-0002 引入的新约束是否可执行。

## 8. 最终裁决

可保留：

- metadata authority/evolution、permission、evidence、completion、recovery；
- adapter-neutral execution boundary；
- context source/freshness/fallback governance；
- 可否决的选择性 projection、JIT 和 search policy；
- strangler + usage-zero + separate deletion。

必须调整后才能实现：

- 把 context governance 与 slimming 分层；
- 把 episode/trigger/thinness 变成可执行合同；
- 把 contraction 从单一删除计数升级为净复杂度 ledger；
- 把 no-second-store 改为 no-second-authority；
- 把 ME6 从 registry 必要门中解耦。

本轮没有批准任何新 public MetadataKind、store、port、scheduler 或 search runtime。
