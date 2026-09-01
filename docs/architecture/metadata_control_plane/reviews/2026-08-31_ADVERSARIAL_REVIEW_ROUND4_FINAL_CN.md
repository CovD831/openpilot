# Metadata Control Plane 第四轮最终对抗性架构审查

> Status: Completed final architecture review
> Authority: Phase 0B architecture-review evidence; it does not authorize production rollout
> Owner: Architecture review
> Supersedes: None; final review of the Phase 0B document baseline
> Last reviewed: 2026-08-31

## 1. 最终结论

结论：**Phase 0B 架构文档基线通过，可以冻结并进入实验/engineering-spike 阶段；生产重构、
新 public contracts 和默认行为仍未获批准。**

第四轮没有发现新的 critical architecture contradiction。前三轮的主要攻击已经被处理为：

- ADR-0002：薄 Control Plane、episode 内推理归 harness、JIT/tree 可否决；
- ADR-0003：Context Governance 必选，Context Optimization 可选；
- ADR-0004：治理只覆盖 OpenPilot-admitted、可观测、声明支持的 request route；
- ADR-0005：迁移按净复杂度与单一权威裁决，允许有界非权威 shadow；
- 未冻结的 manifest/capability/trigger/receipt/atomicity 等问题进入 G/J/R/X/ME 路线。

“通过”表示架构已经足够清晰和可证伪，不表示这些机制已经实现或产生产品收益。

## 2. 最终审查范围

- 项目章程、L1 Target Architecture；
- 六份 L2 design；
- Metadata Evolution、Roadmap、Evaluation、Evidence Index；
- ADR-0001–ADR-0005；
- G0–G7、J-T0/J-T1、J0–J4、R0–R6、X0–X4、ME0–ME6 路由；
- 当前 ContextAssembler/RequestBuilder、reasoning capability profile、Pi adapter 的只读实现
  种子。

本轮不把 experiment design 当生产 API，不要求实现所有 optional policy，也不以当前 dirty
worktree 的未提交行为证明目标架构已落地。

## 3. 终审退出门

| Gate | Result | Evidence |
| --- | --- | --- |
| Critical architecture contradiction = 0 | **Pass** | authority、context、execution、search、recovery 的 owner/optional boundary 已一致 |
| Unrouted required finding = 0 | **Pass** | A2/A3 未冻结部分已进入 G/J/R/X/ME 或明确 kill/fallback |
| Optional mechanism without kill gate = 0 | **Pass** | selective context、JIT、tree、World Model、derived graph、local rework 均有 fallback/kill |
| New authority duplication approved = 0 | **Pass** | semantic object 不自动成为 contract；single authoritative writer；shadow canonical writes=0 |
| Universal/不可观测保证 = 0 | **Pass** | request route、manifest visibility、declared-required coverage 和 provider-hidden scope 已收窄 |
| Root-only forced workflow = 0 | **Pass by design** | absent structural mode；无 trigger 时不调用/实例化 Search/Scheduler/Candidate |
| Production implementation authorized | **No** | ME/G/J/R/X gates 尚未执行 |

## 4. 前三轮 Findings 的最终处置

### 4.1 已写成架构约束

- thin control plane / Pi episode ownership；
- Context Governance 与 Optimization 分层；
- OpenPilot-admitted observable route scope；
- governed source baseline；
- declared-required coverage；
- deterministic/provider-free Governance；
- authority isolation 不等于模型语义免疫；
- net complexity ledger；
- single authoritative writer 与非权威 shadow 区分；
- test double 不足以批准 production port；
- optional ME6 query-demand gate；
- speculative future consumer 不产生 authoritative metadata。

### 4.2 保留为实验/Spike

| Uncertainty | Route | Why not frozen in architecture |
| --- | --- | --- |
| final model-visible request manifest | G0 | Pi/direct/provider 可见性需要实测 |
| governed source baseline 的实际大小/覆盖 | G1 | 依任务/source pack 分布而变 |
| declared vs latent dependency | G2 | 无法由 schema 静态证明 |
| tokenizer/window budget confidence | G3 | provider/transport specific |
| authority isolation vs semantic robustness | G4 | safety 与模型质量是不同结果 |
| adapter capability/conformance levels | G5 | 具体 profile 字段需要跨 adapter evidence |
| body-free receipt 与审计充分性 | G6 | privacy/audit tradeoff 未验证 |
| governance-only overhead | G7 | 当前没有完整 native telemetry |
| structural trigger contract | J-T0 | vocabulary/owner/cooldown 需要 frozen traces |
| execution-attempt/NodeVisit mapping | J-T1 + R0/R1 | Pi loops、abort/retry/recovery 需 fault evidence |
| revision/cursor/checkpoint atomicity | R0/R1/R5 | durable mixed-state 是实现问题 |
| dirty baseline 与 net contraction | X0/X1 | 必须在真实路径上演练 |
| shadow/single-writer migration | X2 | 需要 fault/reconciliation |
| port admission | X3 | 需要真实依赖 diff，不靠文档判断 |
| experimental metadata expiry | X4 | 需要 usage/removal rehearsal |
| derived graph value | conditional ME6 | 必须先有 query-demand evidence |

## 5. 仍存在但已被路由的风险

这些不是新 blocker，而是后续 evidence 必须报告的风险：

1. 当前文档体系概念较多，若实现切片不产生净收缩，必须回退局部 helper/现有 owner；
2. Context Governance 可能因 final request 不可见而只能达到较低 conformance level；
3. governed source baseline 可能超预算，合法结果可以是 redecompose/safe-stop；
4. Metadata registry/migration 可能没有足够 ROI，ME pilot 失败时保留 models + catalog；
5. 显式 JIT 可能完全没有超过隐式 harness chain 的净收益；
6. 当前 dirty worktree 在 X0 前仍不适合作为 production refactor baseline。

## 6. Freeze rule

Phase 0B 文档从本轮起进入 baseline freeze：

- 不再因为纯观点变化新增第五轮通用审查；
- 新问题必须来自实验结果、真实 implementation spike、生产缺陷或 authority 冲突；
- 新 experiment 更新 Evidence Index/route，不重写历史 review；
- 新 public contract、port、store 或默认 policy 仍需 inventory、evidence 和 ADR；
- 若 G/J/R/X/ME 反驳某层，删除或降级该层，不降低原 gate。

## 7. 最终裁决

允许下一步：

- X0 可审查 baseline；
- read-only ME0/ME3/ME4 inventory；
- G0/G1/G2 的 experiment-only protocol；
- J-T0/J-T1、X1–X4 的局部 engineering spike 设计。

仍不允许：

- production ContextBoundary service；
- 新 durable task graph/search store；
- selective context default-on；
- explicit JIT/tree default-on；
- 未通过 R0/R1 的 durable dynamic structure；
- 把 proxy 或 same-session typed actions 写成总经济性/独立 provider 结论。

最终状态：**Architecture baseline accepted for evidence work; production implementation gated.**
