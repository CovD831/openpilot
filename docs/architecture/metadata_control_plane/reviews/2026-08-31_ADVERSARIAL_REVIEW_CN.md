# Metadata Control Plane 对抗性架构审查

> Status: Completed review
> Authority: Review evidence only; corrected architecture documents remain authoritative
> Owner: Architecture review
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 审查结论

结论：**对架构讨论条件通过，对生产实现不通过。**

修订后的文档已经能明确区分当前 authority、目标语义、可选 policy、实验 claim 和 kill
criteria；但仍存在必须由 inventory、fault injection 和真实 provider telemetry 解决的实施前门。

本审查未发现由文档改动直接造成的数据丢失或权限开放，因为本轮没有生产行为变化。
最大风险是概念膨胀和 authority duplication，而不是当前代码漏洞。

## 2. 范围与方法

审查对象：

- L1 charter/target architecture；
- 六份 L2 design；
- metadata evolution protocol；
- roadmap、evaluation plan、Evidence Index；
- 新 experiment route；
- 当前 ports、HarnessApplication、Context Assembly、Evidence Core、Action Gateway 和
  checkpoint/recovery 的只读结构。

审查轴：

```text
correctness / state consistency
readability / concept count
architecture / ownership / dependency direction
security / untrusted inputs / authority escalation
performance / fan-out / retention / token economics
migration / compatibility / rollback
falsifiability / baseline / kill criteria
```

## 3. 已确认并修复的问题

| ID | Severity | Finding | Why it mattered | Resolution |
| --- | --- | --- | --- | --- |
| AR-01 | Required | `SearchPolicyPort.select -> PolicyDecision` 与 Scheduler/Admission 抢最终选择权 | policy recommendation 可能被误实现成 authority | 改为 `PolicyRecommendation`；最终选择只属于 deterministic admission/Scheduler |
| AR-02 | Required | `CandidateTemplate` 可能复制 PlanningSurface、SkillSpec、ToolContract 和 ToolRegistry | 会形成第二 capability schema/registry | 增加 existing-registry reuse gate；template 首先是 role/view |
| AR-03 | Required | 十个目标 ports 和多个 runtime 名词可能只把复杂度改名 | pass-through ports 会扩大概念数 | 增加 port admission gate；semantic object 明确不等于 public contract |
| AR-04 | Required | Search/MCTS/RAP 被列为组件但未说明不是核心依赖 | 容易提前进入复杂树/World Model 工程 | L1 增加 stable core / derived services / optional policies 分层和 kill path |
| AR-05 | Required | Context 只讨论 selected context budget，没有完整 request budget | tool schemas、fixed instructions、output reserve 可能吃掉全部节省 | 增加 full-request budget 和 root-only no-summary-call 规则 |
| AR-06 | Required | Context 缺少不可信正文和 Prompt Injection 边界 | 项目/web/tool 文本可能被误当控制指令 | 增加 trust/provenance、instruction/data separation、redaction 和 Action Gateway 约束 |
| AR-07 | Required | Node lifecycle 缺 cancellation、failure、非法 transition、lease loss 和 starvation | 会出现无法恢复或无限等待状态 | 增加完整 transition 表、terminal/reopen 规则和 interruption/fairness 行为 |
| AR-08 | Required | Derived graph query 没有 cardinality/depth/materialization 上限 | 长任务可能产生无界 fan-out 和第二 graph authority | 增加 relation allowlist、root/purpose、node/edge/depth/artifact bounds 和 source-version invalidation |
| AR-09 | Required | Durability 缺 single-writer、monotonic ordering 和 retention | 并发 writer、索引膨胀和清理可能破坏恢复 | 增加 lease/single-writer、sequence/generation conflict 和 evidence/artifact/index retention |
| AR-10 | Required | Evolution 文档讨论多版本，但当前 base 只接受 `Literal["1.0"]` | 容易把目标协议误写成已有能力 | 明确当前限制；ME1/ME2 前禁止扩宽 base 假装已有 dispatcher |
| AR-11 | Required | Claim status 出现 `Candidate default/invariant` 等枚举外值 | Evidence Index 无法稳定审计 | L2 与 index 全部归一到固定七状态；35/35 Claim 对齐 |
| AR-12 | Required | Baseline 和阈值不足以否决架构 | 删除安全门或结果后调阈值都可能制造“收益” | 增加相同权限/工具/模型/预算 baseline contract、统计冻结和 architecture kill criteria |
| AR-13 | Required | 当前结构快照没有限定 dirty worktree/Python-only 范围 | “无 cycle”等结论可能被过度解释 | 限定为当前 dirty worktree 的可解析 `Code/src` Python graph |

## 4. 尚未解决的实施前门

| ID | Severity | Blocker | Required evidence |
| --- | --- | --- | --- |
| AB-01 | Critical before durable dynamic rollout | revision + active cursor + checkpoint 的物理提交协议未定 | R0/R1 fault injection；任何 mixed state 为失败 |
| AB-02 | Required before selective projection default | required-fact closure 仍没有可执行证明格式 | C0/C2/C5/C6；遗漏、unknown 或 authority drift 必须 fallback/safe-stop |
| AB-03 | Required before economic claim | 现有动态/context 证据缺独立 provider samples 和 native telemetry | paired real provider input/output token、calls、latency、task quality |
| AB-04 | Required before new contracts/registries | NodeVisit、ClosureCommit、CandidateTemplate、relation view 的复用 inventory 未完成 | ME0/ME3/ME4；duplicate authority/schema=0 |
| AB-05 | Required before ports refactor | 当前 ports 是否减少复杂度尚未证明 | typed port spike；依赖/分支/`Any`/旧路径必须减少 |
| AB-06 | Required before context rollout | adversarial project/web/tool content 尚未验证 | C5 authority isolation 和 tool-routing negative controls |
| AB-07 | Required before repository merge | 工作区已有大量非本轮 dirty changes，尚未形成可审查基线提交 | 分拆提交/变更集；不得把历史改动混写成本架构实现 |

## 5. State and effects evidence table

| Trigger / input | State or side effect | Blast radius | Failure / recovery | Evidence gate |
| --- | --- | --- | --- | --- |
| Candidate proposal admitted | new node/revision/cursor | scheduler/context/checkpoint | rejection leaves current node; mixed commit fail closed | J/R fault tests |
| Context projection selected | model-facing request only | one provider episode | source fallback or safe-stop | C0/C2/C5/C6 |
| Tool/action admitted | filesystem/command/network side effect | explicit write/action scope | receipt/reconcile/exact validation | existing Action Gateway tests |
| Verification accepts result | ClosureCommit/current completion | consumers and parent residual | no commit on unknown/failure | completion equivalence tests |
| Dependency/source changes | freshness/revalidation/rework | explicit consumers/affected scope | conservative revalidation | C2/R3 |
| Resume/attach | same Run/cursor continues | one authoritative history | lease/id mismatch fail closed | R0/R1/R5 |

## 6. Resource bounds evidence table

| Operation | Work per item | Cardinality bound | Max work / invocation | Backlog/fallback |
| --- | --- | --- | --- | --- |
| Context selection | candidate inspect/count/render | source and token budgets | full-request budget | source fallback/redecompose/safe-stop |
| Derived graph query | entity/edge traversal | max nodes/edges/depth/artifacts | task/run scoped by default | partial typed result or reject |
| Candidate generation | descriptor validate/rank | count/calls/tokens/width/depth | policy budget | root-only/top-1 fallback |
| MCTS/RAP simulation | rollout/value estimate | rollouts/depth/world-model tokens | separate experiment budget | stop without state mutation |
| Scheduler | one ready-node comparison | bounded ready frontier | one active node | age/bypass bound, replan/block |
| Evidence/index retention | append/reference/index | retention/cardinality policy | bounded index/rebuild | artifact offload/rebuild; never delete required recovery data |

## 7. Boundary behavior evidence table

| Input | Zero / empty | Exact boundary | Outside boundary | Recovery / evidence |
| --- | --- | --- | --- | --- |
| CandidateSet | continue current/root-only | validate all descriptors | reject excess before context load | record bounded rejection receipt |
| Required facts | no required facts only when acceptance says so | exact closure | missing/unknown/stale | fallback source view or safe-stop |
| Graph query | exact identity/direct refs | return bounded view | depth/node/edge overflow | typed partial/rejection, no canonical write |
| Full request budget | fixed+required fit | optional fills remainder | fixed+required exceed window | typed failure/reduce tools/redecompose |
| Template/version | registered exact match | resolve trusted adapter | unknown/mismatch/extra executable fields | reject before load/execute |
| Lease/generation | valid current writer | commit monotonic next generation | stale/lost/conflict | stop dispatch and reconcile |

## 8. Complexity review

当前 L2 文档定义了 35 个 Claim、多个语义对象和最多十个候选 seams。它们只有在后续切片
删除旧分支、复用现有类型并减少调用方概念时才算成功。若只是新增同名 wrapper、store、
registry 和状态机，则该重构失败，即使模块文件变小。

文档变更本身已超过普通单次 review 的舒适规模。合并时应至少拆成：

1. L1/governance/bootstrap；
2. L2 subsystem designs；
3. adversarial corrections + evidence/experiment routing。

## 9. 审查后建议

- Phase 0B 可以进入人类架构评审，但不能进入生产实现；
- 下一步只允许 read-only ME0/ME3/ME4/ME6 inventory 和必要 engineering spikes；
- Context/JIT/Search/Recovery experiments 保持 experiment-only；
- 首个生产切片必须删除或替代一个真实旧依赖路径，不能只新增抽象；
- AB-01–AB-07 未关闭前，不将 Phase 0B 标为 architecture accepted。
