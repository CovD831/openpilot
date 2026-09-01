# Durable State、Evidence 与 Recovery 二级架构

> Status: Proposed L2 architecture
> Authority: Target durability/recovery integration; current recovery protocols remain normative
> Owner: Evidence / runtime recovery
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 目标

新的 node、candidate、projection 或 search policy 不能破坏已有恢复能力。恢复必须由
authoritative identity、event history、receipt、validation 和 checkpoint 驱动，而不是
依赖完整对话或重新询问模型“之前做到了哪里”。

## 2. 权威持久对象

```text
Run identity and event sequence
Task/admission authority
PlanEpoch / admitted structure revision
active/suspended node cursor
provider/tool observations
side-effect receipts
verification/completion decisions
ClosureCommit references
checkpoint generation and safe boundary
resume attempt / supervisor lease
```

以下默认可重建：

```text
context projection
residual view
candidate ranking
search frontier cache
summary resolution cache
UI/report projection
```

可重建不等于可以无来源重算；它们必须绑定 source revisions 和 policy versions。

## 3. Identity model

至少区分：

```text
task_id
session/conversation identity
run_id
plan_epoch_id
structure_revision_id
node_instance_id
node_visit_id
provider/tool call_id
event_id / idempotency_key
closure_commit_id
checkpoint_id / generation
resume_attempt_id
```

不同 identity domain 不得凭字符串相等自动合并。恢复必须显式 attach 已有 Run，不得通过
task/session alias 静默创建第二个事实历史。

## 4. Event 与 state

- Observation/Event：append-only，记录实际发生或决定；
- Canonical state：由受权 owner 的事件/commit 推进；
- Checkpoint：某个 safe boundary 的恢复快照和 references；
- Summary/report：可从 events/state 重建；
- Projection/search state：derived cache。

State 更新必须能追溯到 source event/decision。不能只覆盖 JSON snapshot 而丢失触发原因。

### 4.1 Single writer and monotonic ordering

- 每个 Run 同一时刻只有一个持有有效 lease 的 authoritative writer；
- 没有 lease 或 lease 丢失的进程不能 dispatch 新 provider/tool/action；
- event sequence、checkpoint generation 和 structure revision 必须单调；
- stale generation、重复 writer 或 conflicting idempotency payload 必须 fail closed；
- wall-clock/`created_at` 只用于展示，不能决定事件顺序；
- lease revoke 不能重写已 dispatch 的 side effect，只阻止后续动作并触发 reconciliation。

## 5. 逻辑 durable boundary

目标要求下列变化对恢复者表现为一个一致提交：

```text
admitted structure revision
+ previous node disposition
+ next active/ready cursor
+ required authority/evidence references
+ checkpoint generation
```

物理实现可以是单一 event-state checkpoint、transactional store 或可恢复 prepare/commit
协议，但必须满足：

1. 恢复后不能看到新 revision 配旧 active cursor；
2. 不能看到 active node 已切换但 admission evidence 缺失；
3. 崩溃后可从 event length/idempotency record 重建；
4. 重复提交使用同一 idempotency identity 不产生第二 transition；
5. checkpoint 失败不把未持久化 proposal 当作 admitted node。

## 6. 建议提交协议

```text
prepare transition
  validate current generation/revision/lease
  validate admission and authority refs

append canonical transition event
  with idempotency key and previous identity

commit event-state/checkpoint
  revision + cursor + generation + source event

ack transition
```

若 append 已发生而 checkpoint 未提交，恢复通过 event history 和长度/sequence 不匹配重建，
不能再次执行 admission 或副作用。

## 7. Node switch checkpoint

切换节点前至少持久化：

```text
exiting NodeVisit disposition
candidate/result/open issues
tool/provider evidence refs
current node lifecycle
admitted next node/revision
next context projection source requirements
budget consumption
pending validation/side-effect state
```

恢复后 Context Projection 重新生成；只有明确 replay-bound request/observation 才原样重放。

## 8. Side-effect crash windows

| Crash window | Durable evidence | Recovery |
| --- | --- | --- |
| action dispatch 前 | 无 receipt | 可按 authority/budget重新决定，不宣称执行 |
| dispatch 后、receipt 前 | 状态未知 | indeterminate/reconcile；不可盲重试不可逆动作 |
| durable receipt 后、validation 前 | mutation 已观察 | 同 Run fresh approval/lease 下只执行原 exact validation |
| validation event 后、closure 前 | 结果可回放 | completion owner重新计算，不重放 action |
| closure 后、checkpoint ack 前 | commit event 可重建 | idempotent attach/rebuild cursor |
| projection/cache 持久化中断 | authority 未变 | 删除/重建 projection 或 source fallback |

## 9. Resume algorithm

```text
resolve exact Run/checkpoint identity
  -> acquire Supervisor lease
  -> verify project/admission/policy compatibility
  -> load latest authoritative event/state boundary
  -> reconcile pending side effects/validation
  -> invalidate stale derived views
  -> rebuild State View and Context Projection
  -> resume exact node/cursor or safe-stop
```

恢复不得：

- 重放已 receipt 的 mutation；
- 使用新的通用验证替代原 exact validation；
- 复用过期 consent；
- 让新的 search policy 覆盖旧 evidence；
- 把 checkpoint 缺字段静默填成 completed/current。

## 10. Freshness / revalidation

ClosureCommit 只在绑定输入、dependency outputs、acceptance、revision 和环境前提下成立。
变化触发：

```text
current
revalidation_required
invalidated
unknown
```

`unknown` 不允许继续作为已验证依赖。revalidation 是新的 evidence/decision，不原地修改
历史 validation。

## 11. 局部返工

```text
AffectedScope =
    ModifiedNode/Subtree
  + ConsumersOfChangedPublicOutputs
  + NodesWhoseAcceptanceOrFreshnessDependsOnChangedFacts
```

限制：

- max reopen depth；
- max affected nodes；
- max closure revisions；
- max cumulative rework budget；
- max plan epochs。

无法证明 public output/consumer 未受影响时，保守重新验证明确 consumer。超过边界进入父级
replan 或新 PlanEpoch。

## 12. Policy/harness 替换与恢复

Checkpoint 保存的是 authoritative facts、accepted decisions 和 cursor，不保存“某算法必须
继续运行”的隐含对象状态。

- 同一 policy/version 可恢复其 derived cache；
- policy 变更后丢弃旧 frontier/ranking，从 authoritative view 重建；
- harness 变更后仍消费同一 admitted execution request；
- 未完成 provider-specific request 是否可 replay 由明确 transport compatibility 决定；
- 已发生 evidence 和 side effect 永不因 policy/harness 更换重写。

## 12.1 Retention and bounded indexes

“append-only evidence”不等于所有正文永久内联：

- event 保留 identity、authority、ordering、receipt/validation references 和受限预览；
- 大正文进入 artifact store，event 只保留引用；
- idempotency、consumer、lineage 和 search indexes 必须有显式 cardinality/retention bound；
- summary/report/index 可重建，损坏时不能影响原始 event truth；
- 未选 candidate/search trace/usage audit 使用独立 retention class，不能成为 resume 前提；
- 在 supported historical-read/recovery window 内，不得清理恢复所需 event/artifact；
- 清理后仍必须能证明哪些数据被删除、依据哪个 policy/version。

## 13. 当前实现映射

| Target responsibility | Current seed |
| --- | --- |
| Run/event identity | Evidence Core + `RunCoordinator` |
| Atomic event-state persistence | Evidence Store event state checkpoint |
| Runtime checkpoint | `RuntimeCheckpointStore` / runtime metadata |
| Lease/resume identity | Supervisor / session resume protocol |
| Mutation reconciliation | `PiMutationRecoveryRunner` |
| Completion from evidence | `verification/completion.py` |
| Context replay/binding | current checkpoint and compaction bindings |

目标工作是接入新 revision/node identities 和 failure tests，不并行建立第二个 recovery store。

## 14. Claim routing

本设计拥有 `DR-C01`、`DR-C02`、`DR-C03`、`DR-C04`、`DR-C05`、`DR-C06`、`DR-C07` 的语义；status、evidence 和 adoption gate 只在
[`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。

## 15. 未决问题

- structure revision 是 Evidence Core canonical event、checkpoint nested value，还是独立 store？
- node transition 与 checkpoint 需要哪种 prepare/commit 物理协议？
- provider episode 内尚未 receipt 的 tool call 如何判定 reconcile capability？
- dependency consumer graph 的 freshness/affected-scope view 如何缓存和失效？
- policy version 变化时，哪些 pending proposals 可以保留最小 receipt？
