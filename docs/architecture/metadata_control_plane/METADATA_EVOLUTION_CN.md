# Metadata Kernel 与演化协议

> Status: Proposed protocol
> Authority: Target metadata evolution rules; current mandatory workflow remains `docs/metadata/DEVELOPMENT_CONVENTIONS.md`
> Owner: Metadata architecture
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 为什么需要单独的演化协议

当前项目已经有严格模型、统一 envelope、contract catalog、owner/lifecycle 约定和迁移
案例，但演化能力主要依赖人工审查。缺少的不是更多 metadata，而是可以持续验证的：

- contract registry；
- 版本支持窗口；
- 统一 migration 入口；
- 字段生命周期；
- 历史 payload 兼容语料；
- producer/consumer 使用审计；
- 安全删除门。

## 2. Kernel 的稳定边界

### 2.1 Provisional current envelope

当前 `MetadataBase` 的公共 envelope 是 provisional structural-kernel candidate：

```text
kind
schema_version
source
correlation
created_at
annotations
```

原则：

- `kind` 绑定唯一公共 contract；
- `schema_version` 表示可解析 schema，不表示业务运行阶段；
- `source` 只表达 producer/owner envelope；
- `correlation` 连接 session/task/step/execution 身份，不复制业务对象；
- `created_at` 是观测时间，不替代事件序号或 durable ordering；
- `annotations` 只容纳非控制诊断信息，永不驱动权限、路由、预算、恢复或完成。

这些字段预期极少变化，但在 ME0/ME3/ME5 完成前不能把“稳定”解释为已验证且无需调整。
任何修改都需要独立 ADR、全量历史语料迁移和跨模块验收。

### 2.2 Semantic Kernel

Semantic kernel 不是继续给 `MetadataBase` 加字段，而是一组所有公共 contract 必须声明
的规则：

- authoritative owner；
- authoritative producer；
- consumers；
- lifecycle 和 persistence class；
- legal states / invalid combinations；
- control impact；
- evidence/reference semantics；
- compatibility and migration policy。

这些信息先由 contract catalog 管理，后续再形成机器可读 registry。registry 是现有
模型的索引和验证器，不是第二份字段定义。

### 2.3 当前可执行限制

当前 `MetadataBase.schema_version` 是 `Literal["1.0"]`。它只能验证现行 envelope，尚不是
多版本 dispatcher。项目当前存在的是零散的 model-level legacy migration，而不是统一
registry/migration runtime。

因此在 ME1/ME2 前：

- 不扩宽 base field 类型来假装已经支持多版本；
- 不让 reader 根据字符串或 model name 猜 migration；
- 不原地改写历史 evidence/checkpoint；
- 每个 contract 单独声明 `supported_read_versions` 和 rejection behavior；
- compatibility window 必须按版本/持久化生命周期/恢复需求明确，不能使用一个全局天数。

## 3. Contract Registry 最小记录

每个公共 `MetadataKind` 至少登记：

```text
kind
python_type
source_file
current_schema_version
owner
producer
consumers
lifecycle
persistence_class
control_impact
authoritative_fields
derived_fields
reference_fields
deprecated_fields
supported_read_versions
migration_entrypoint
contract_tests
last_reviewed
```

字段真相仍来自 Pydantic model。registry 不保存一份可漂移的完整 JSON Schema；它通过
测试与 model/export/catalog 交叉校验。

## 4. 允许的变更类型

### 4.1 Compatible extension

新增有默认值或可确定推导的字段，不改变旧字段含义。要求旧 payload 可读、新 writer
只写新格式、JSON round-trip 和 invalid-state 测试通过。

### 4.2 Semantic tightening

收紧合法状态、权限或完成条件。即使字段不变也属于行为变更，必须有迁移/拒绝策略、
历史语料测试和 API/AGENTS 影响审查。

### 4.3 Rename / split / merge

必须使用显式 migration。过渡期遵循 **single-write, compatible-read**：新 producer 只写
新字段；reader 在限定窗口读取旧格式；新旧同时出现且矛盾时 fail closed。

### 4.4 Deprecation and removal

先停止 producer，再观测 consumer，最后删除 reader。不能因为仓库内 `rg` 无命中就认定
持久化数据、外部调用方或恢复路径没有消费者。

## 5. 字段和 contract 生命周期

```text
proposed
  -> experimental
  -> active
  -> deprecated
  -> read_only_legacy
  -> removed
```

- `proposed`: 只有 impact note/ADR，不进入公共 export；
- `experimental`: feature flag 或 experiment namespace，不能成为全局 authority；
- `active`: 有 owner、producer、consumer、tests、catalog 和 migration；
- `deprecated`: 禁止新 producer，保留兼容 reader 和使用观测；
- `read_only_legacy`: 只为历史数据/恢复读取；
- `removed`: 兼容窗口结束、使用为零、迁移语料和恢复测试通过。

状态变化必须记录日期、owner、替代项和删除门，不能只写在 commit message。

## 6. 统一变更流程

每次 metadata 变更按以下顺序：

1. 完成 `DEVELOPMENT_CONVENTIONS.md` 的 inventory/duplication review；
2. 写 metadata impact note，确认 owner、consumer、lifecycle 和 control impact；
3. 选择 reuse、extend、owned nested value、reference/view 或 new contract；
4. 先加入 contract、invalid-state、historical-read 和 migration tests；
5. 实现 model/migration，保持 single authoritative writer；
6. 更新 exports、catalog、registry 和协议可见的 `API.md`；
7. 对 producer/consumer/persistence/recovery 做静态和运行时使用审计；
8. 通过兼容窗口后，按 deprecation gate 删除旧 reader/field；
9. 在 ADR 或 implementation log 记录结论和剩余限制。

## 7. Migration 约束

- migration 必须是 typed、确定性、可测试的纯转换；
- 同一输入重复 migration 结果一致；
- migration 不调用 provider、tool、network 或项目写入；
- 不凭 explanation text 推断控制状态；
- 不可恢复或有歧义的旧值返回 typed rejection，不静默填补；
- checkpoint/evidence 的原始记录不可原地覆盖；新表示通过新 revision 或 derived view
  关联；
- major semantic change 必须声明支持的读取版本窗口和恢复策略。

## 8. 使用审计

安全删改同时依赖两类证据：

1. **静态审计**：exports、构造点、字段读取、序列化、store、API、tests 和文档引用；
2. **运行时审计**：在不记录敏感正文的前提下，统计 contract/version/field 的 producer、
   consumer、migration 和 rejection 事件。

运行时审计是 evidence，不是权限。字段未被某次运行消费不代表可以删除。
审计默认记录 kind/version/field identity、producer/consumer identity 和计数；正文、凭据、
自由 explanation 和 raw payload 不进入 usage telemetry。

## 9. 必须先完成的演化实验

| 实验 | 回答的问题 | 通过门 |
| --- | --- | --- |
| ME0 Registry consistency | registry 能否和 `MetadataKind`、public exports、catalog、models 一致 | 缺失、重复、孤儿 kind 和未登记 public contract 全为 0 |
| ME1 Historical corpus read | 当前 reader 能否读取代表性历史 payload/checkpoint | 所有支持版本成功；未知/非法版本 typed fail closed |
| ME2 Migration properties | rename/add/split 的迁移是否确定、幂等且不制造第二真相 | 重复迁移一致；矛盾 old/new 拒绝；round-trip 语义保持 |
| ME3 Producer/consumer audit | 能否找到真实 producer、consumer 和持久化边界 | 人工 gold set recall 100%，歧义项不自动删除 |
| ME4 Authority duplication sentinel | 新字段/投影是否复制已有权威事实 | 代表性变更中所有重复 owner 被 gate 拒绝 |
| ME5 Deprecation rehearsal | 能否完整演练 stop-write -> compatible-read -> usage-zero -> removal | 历史恢复、API、contract tests 和 rollback 全通过 |
| ME6 Bounded derived graph view | metadata references 能否支持有界查询而不形成第二 authority/store | node/edge/depth 上界有效，source revision 失效正确，canonical writes=0 |

ME0–ME5 在 shadow/fixture 上通过之前，不实现全局自动 migration registry，也不批量改
现有 79 个公共 contract。ME6 只有在 inventory 发现达到预注册门的重复跨 owner 查询后才
启动；它不是 registry/evolution 的成立前置。

## 10. 当前与目标的衔接

当前必须继续遵守：

- [`../../metadata/DEVELOPMENT_CONVENTIONS.md`](../../metadata/DEVELOPMENT_CONVENTIONS.md)
- [`../../metadata/CONTRACT_CATALOG.md`](../../metadata/CONTRACT_CATALOG.md)
- `Code/src/metadata/`

本协议先补足演化方法和实验门。只有在对应 roadmap 切片被接受后，其中的机器可读
registry、migration entrypoint 或 usage telemetry 才能成为生产能力。
