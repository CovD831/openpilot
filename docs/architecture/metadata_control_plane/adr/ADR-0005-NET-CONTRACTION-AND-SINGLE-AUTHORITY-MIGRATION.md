# ADR-0005: 以净收缩和单一权威约束迁移

> Status: Accepted for architecture planning
> Authority: Architecture/migration constraint; it does not authorize production deletion
> Owner: Architecture / migration / metadata
> Supersedes: None; clarifies ADR-0002 complexity and store constraints
> Last reviewed: 2026-08-31

## Context

ADR-0002 要求新抽象减少旧复杂度、禁止第二 durable store。第二轮审查指出，按“每切片删
一个分支”计数会诱发 Goodhart，禁止任何第二物理表示也会阻塞安全 shadow、index rebuild
或 store migration。安全 strangler 需要短期 overlap，但不能允许双 authority 永久存在。

## Decision

### 1. 收缩看净变化，不看单一删除数

每个 migration/cutover slice 维护 net complexity ledger：

```text
added / removed concepts
added / removed owners and authorities
added / removed dependencies
added / removed controller branches
added / removed broad Any/dict boundaries
added / removed adapters and fallbacks
call-depth and operational paths
```

删除一个 branch 不能自动抵消多个新 service/contract/owner。experiment/shadow 只需证明可
整体删除和不拥有 authority；真正 cutover 才要求净收缩或明确的安全/恢复收益。

### 2. 禁止第二权威，不禁止所有第二物理表示

- 同一事实只能有一个 authoritative writer/decision owner；
- shadow index、cache、migration target 或 derived representation 可以暂时存在，但必须
  canonical writes=0 或保持 single authoritative writer；
- shadow 表示必须可重建、可失效、有 owner/TTL/sunset，不能授予权限、完成或恢复事实；
- 双写若无法证明单一事实顺序和 reconciliation，不得进入 production migration。

### 3. Port admission

test double 本身不能证明 production port 的必要性。显式 port/protocol 必须跨越真实
owner/adapter/volatility boundary，或可度量地删除反向依赖、宽类型和旧调用路径。

### 4. Speculative consumer

“未来可能有 consumer”不能让 metadata 进入 authoritative durable state。只有已批准的
experiment/migration、明确 owner、expiry 和 removal gate 同时存在时，才允许进入
experimental namespace。

### 5. Optional derived graph

ME6/derived graph 不是 registry consistency 或 Metadata Evolution 成立的前置。只有 inventory
发现重复跨 owner 查询并达到预注册需求门，才启动 ME6；失败时保留 direct references/local
views。

## Consequences

- shadow/paired migration 可以安全短期并存，不会因机械删除门过早移除 fallback；
- 新抽象必须证明净价值，不能用文件数或 branch 删除数制造进度；
- 物理存储迁移与 authority duplication 被明确区分；
- optional graph 不再反向进入稳定内核关键路径。

## Validation

Roadmap 记录各 stage 的 overlap/deletion gate；Evaluation Plan 维护 net complexity、single
authority、ME6 query-demand 和 usage-zero 指标。
