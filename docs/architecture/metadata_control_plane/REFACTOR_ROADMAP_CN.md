# Metadata Control Plane 重构路线图

> Status: Active proposed roadmap
> Authority: Implementation sequencing and gates; not proof of completion
> Owner: Architecture / implementation leads
> Supersedes: None
> Last reviewed: 2026-09-01

## 1. 路线原则

这次工作按“新一代架构开发”组织，但不采用 big-bang rewrite。现有 Pi 路径、Evidence
Core、权限、恢复和 metadata contracts 是可复用资产，也是迁移期间的安全基线。

每一阶段必须：

- 只解决一个明确边界；
- 先有 metadata impact note 和失败测试；
- 保持单向依赖；
- 有兼容读取或明确 rollback；
- 不把实验 projection、proposal 或 graph view 提升为 authority；
- 让新 seam 同步替代或删除至少一个真实旧 consumer、branch、宽 `Any` 或依赖；
- 不允许新旧入口在没有 usage、owner、退出日期和删除门的情况下长期并存；
- 通过本阶段 gate 后才进入下一阶段。

Legacy contraction 不是最后统一清理的阶段，而是 Phase 1 起每个切片的持续硬门。某个切片
只增加模块、port 或 metadata object，却没有减少旧概念和调用路径，只能算实验或 shadow，
不能算重构完成。该约束由
[`ADR-0002`](adr/ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md) 固定。

### 1.1 V1 delivery model

Control Plane V1 作为一个完整产品版本统一定义、集成和验收，但不作为一次大提交开发。
三套坐标的分工固定如下：

```text
V1-S0 … V1-S5     = 唯一实现和交付顺序
Phase 1 … Phase 4C = 每个切片消费的能力、实验和退出门
Post-V1 Phase 5/6  = V1 发布后的可选研究路线
```

实现顺序使用六个可独立验证、可回滚的纵向切片：

| Slice | End-to-end boundary | Required outcome | 消费的门 |
| --- | --- | --- | --- |
| V1-S0 Inventory / evolution foundation | models/catalog/history -> registry shadow -> typed migration/rejection | 当前 contract 和演化路径可机器检查，不产生第二 schema truth | Phase 1 inventory + Phase 2 evolution/migration |
| V1-S1 Read-only request path | task authority -> admission -> state/context view -> Pi request | 同一 authority/revision 贯穿 request，B1 行为等价 | Phase 3 read-only request port + Phase 4A request conformance |
| V1-S2 Evidence / completion | observation/receipt -> evidence -> verification -> ClosureCommit | 模型自报不能越过 evidence/validation owner | Phase 3 evidence/completion |
| V1-S3 Governed mutation | admitted action -> dispatch -> durable receipt -> exact validation | 权限、幂等、失败和 reconciliation 闭合 | Phase 3 mutation authority + Phase 4A governance |
| V1-S4 Recovery | checkpoint/crash window -> lease/reconcile -> exact resume | 不重复副作用、不创建第二历史或 cursor | Phase 3 recovery attachment + R 系列故障门 |
| V1-S5 Entry cutover / contraction | one public entry -> composed V1 ports -> legacy usage-zero | 单一入口、回滚明确、旧 producer/consumer 可删除 | Phase 4C integration/cutover |

Phase 4B（可选 Selective Context Optimization）不阻塞任何 V1 必选切片。

每个切片在编码前冻结自己的 L3 interface specification；V1 共享的 composition 和 conformance
要求必须在 S1 前冻结。某个切片通过不等于 V1 完成，只有 S0–S5 全部通过 Phase 4C 集成门
才可以发布 V1。

## 2. 分支策略

- 启动分支：`codex/metadata-control-plane-refactor`。
- 分支从原 `codex/collaboration` 当前 HEAD 创建，并保留当时全部未提交工作；没有
  reset、stash 或批量删除。
- 在第一份基线提交之前，所有已有 dirty changes 都必须按现有 owner 审计，不能被
  误写成“新架构已实现”。
- 第一份 package/baseline 提交前必须生成 X0 immutable run，并通过 historical-evidence
  deletion guard；未裁决 tracked deletion 阻塞 release，但 X0 本身不执行恢复或删除。
- X0 owner adjudication 已完成：受保护集合的 tracked historical paths 已从 pinned HEAD
  精确恢复，当前状态以 X0 runs 为准；B1 使用 owner-reviewed commit pin，当前 dirty
  worktree 不属于 B1，baseline 版本化与重 pin 禁止规则见
  [`EVALUATION_PLAN_CN.md` §2.2](EVALUATION_PLAN_CN.md#22-baseline-versioning-rule)。
- 后续大于一个独立切片的工作，使用 `codex/` 前缀的短生命周期分支或 worktree，合并
  前必须满足对应阶段 gate。
- 实验 output 保持不可覆盖；生产实现不得在实验 run 目录内开发。

## 3. Phase 0A：一级架构与文档权威

状态：**已完成（2026-08-31）**。

交付物：

- 唯一架构入口和项目章程；
- 目标架构与当前架构的权威边界；
- metadata 演化协议；
- 统一 roadmap 和 evaluation plan；
- 文档治理规则与历史集合索引；
- 首个 ADR，记录本次重构方式。

退出门：

- 所有新文档有 status/authority/owner/supersedes/last-reviewed；
- 当前规范、目标设计、roadmap、evidence、historical 不再混为同一权威；
- 根文档索引可以到达新入口；
- Markdown 相对链接和 `git diff --check` 通过；
- 本阶段没有生产行为或 metadata schema 变化。

## 4. Phase 0B：二级架构与证据绑定

状态：**架构决策已冻结；X0 owner adjudication 与 B1 commit pin 已通过；生产实施门仍未
打开**。

交付物：

- current-to-target 模块迁移映射；
- metadata node/edge/gate/persistence/derived-view 领域模型；
- root-only/JIT runtime、proposal/admission、NodeVisit/Closure 协议；
- mandatory context governance 与 optional projection/消费优化的分层协议；
- CandidateTemplate/Proposal/Node、top-1/top-k、search/world-model policy 边界；
- revision/checkpoint/receipt/validation 的 durable recovery 协议；
- Claim → Experiment → Evidence → ADR 的统一索引；
- `experiments/metadata_control_plane/` 路线入口。

退出门：

- 六份 L2 文档的 owner、state machine、invariant、open question 和 fallback 明确；
- 每个未定设计有稳定 Claim ID、实验或 engineering spike 和 adoption gate；
- 旧 Context Scope 研究只被选择性提升，不整体改写为生产授权；
- 目标 ports 与当前 owner 映射清楚，不提前创建重复 metadata contract；
- 文档链接/header/authority 检查通过；
- 本阶段仍不修改生产行为。

审查记录：

- [`reviews/2026-08-31_ADVERSARIAL_REVIEW_CN.md`](reviews/2026-08-31_ADVERSARIAL_REVIEW_CN.md)
- [`reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_CN.md`](reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_CN.md)
- [`reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND2_CN.md`](reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND2_CN.md)
- [`reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND2_CN.md`](reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND2_CN.md)
- [`reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND3_CN.md`](reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND3_CN.md)
- [`reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND3_CN.md`](reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND3_CN.md)
- [`reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND4_FINAL_CN.md`](reviews/2026-08-31_ADVERSARIAL_REVIEW_ROUND4_FINAL_CN.md)
- [`reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND4_FINAL_CN.md`](reviews/2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND4_FINAL_CN.md)

## 5. Phase 1：可执行 Metadata Inventory

目标：先让当前 metadata 体系可被机器检查，不改变业务行为。

交付物：

- 由现有 models/exports/catalog 驱动的最小 registry schema；
- 79 个公共 contract 的 owner、producer、consumer、lifecycle、persistence 和 control
  impact 清单；
- orphan kind、漏 export、重复 kind、catalog drift 检查；
- producer/consumer 静态审计和代表性人工 gold set。

实验/门：ME0、ME3、ME4。全部通过后才允许 registry consistency 进入 CI shadow。
registry 不成为第二份 schema truth。ME6 只有在 inventory 发现达到预注册门的重复跨 owner
查询后才启动；derived graph/query 只能是有界、只读、可重建的 view。

## 6. Phase 2：兼容与 Migration Kernel

目标：为 metadata 增删改建立统一且可验证的安全路径。

交付物：

- 版本分派和 migration entrypoint；
- 代表性历史 payload/checkpoint corpus；
- single-write / compatible-read 模式；
- field lifecycle 和 deprecation ledger；
- unknown version / contradictory fields 的 typed rejection。

实验/门：ME1、ME2、ME5。先只选择 2–3 个已有真实迁移压力的 contract，不批量改 79
个类型。

## 7. Phase 3：Control Plane Ports

目标：把权威控制和 Pi/provider/tool 实现之间的接口变窄，保持现有行为不变。

Phase 3 是能力与证据门，不是第二套交付序列；实现顺序由
[`§1.1` V1 delivery model](#11-v1-delivery-model) 唯一决定。本阶段定义四个 port 能力门：

1. 只读 task admission / execution request port（由 V1-S1 消费）；
2. evidence/completion port：observation/receipt ingestion 与 completion decision（由 V1-S2 消费）；
3. governed mutation authority port（由 V1-S3 消费）；
4. recovery attachment port（由 V1-S4 消费）。

退出门：

- 当前 Pi end-to-end 路径结果等价；
- provider-specific payload 不进入业务模块；
- public CLI 不恢复第二条 legacy controller 路径；
- mutation 权限、exact validation 和 reconciliation 测试全部保持绿色。
- 每个 cutover slice 按
  [`CURRENT_TO_TARGET_MAPPING_CN.md` §5.3–5.4](design/CURRENT_TO_TARGET_MAPPING_CN.md#53-port-admission-gate)
  提交 port-admission evidence 和 net complexity ledger；本 roadmap 不维护第二套字段定义。

## 8. Phase 4：Context Governance 与可选 Optimization

### Phase 4A：Context Governance baseline（必选）

目标：让所有 OpenPilot-admitted supported model-request routes 在声明的可观测边界内使用
相同的 source、trust、permission、declared-required coverage、freshness、请求预算、
authority isolation 和 fallback 不变量。

交付物候选：

- 复用现有 Context Assembly 的治理 seam，不预设新 public port/contract；
- governed source baseline；
- required-fact/freshness/budget failure 与 safe-stop；
- cross-adapter conformance tests。

Phase 4A deterministic/provider-free，不以 token 减少为通过门，也不要求 selector、summary
或 on-demand。
退出门是所有声明 supported 的 admitted routes 在其 conformance level 内通过：declared
required/control facts 不静默遗漏，unknown/stale 正确 fallback 或 safe-stop；不可观测
provider components 明确为 unknown/out-of-scope，不伪造完整 request 保证。

### Phase 4B：Selective Context Optimization（可选）

目标：在 4A 不变量完全相同的条件下，评估选择性注入、summary、on-demand、resolution
和消费优化是否产生净收益。

退出门由 evaluation plan 的 C-Opt 组决定。provider token/call/latency 未观测前，不以字符
proxy 宣称总成本收益。失败时停在 4A governed source baseline，不影响后续独立实验。

<a id="phase-4c-v1-integration-cutover"></a>

### Phase 4C：Control Plane V1 integration / cutover（必选）

Phase 4C 不以 4B 为前置；V1 可以只使用 governed source baseline。本阶段只定义何时集成与
发布；V1 产品边界的唯一 owner 是
[`TARGET_ARCHITECTURE_CN.md` §2.10](TARGET_ARCHITECTURE_CN.md#210-control-plane-v1-产品边界)。
进入本阶段前，V1-S0–S4
必须分别通过自己的 contract、negative、fault 和 compatibility tests。

集成交付物：

- owner-reviewed package/composition map 和唯一 public entry；
- core ports/adapters 的完整 L3 specification 与 contract tests；
- B1、shadow V1、Pi adapter 和 recorded/replay adapter 共用的 conformance suite；
- historical payload/checkpoint compatibility 和 crash-window recovery；
- run-bound rollout/rollback、legacy usage telemetry 和 deletion review；
- net complexity ledger，证明没有第二 authoritative writer/store/controller。

退出门：V1 hard safety/authority gates 全部通过；当前 Pi 行为保持等价；mutation、completion、
checkpoint 和 recovery 能端到端闭合；旧入口达到预注册 cutover/usage-zero 条件。通过后才可
称为“完整 Control Plane V1”，而不是因为模块和接口文件已经存在。

## 9. Post-V1 Phase 5：Explicit Top-1 JIT（可选）

目标：只在 Phase 4A governance 已稳定、J gate 证明存在跨 episode 的结构收益后，把一次
episode 无法闭合的 typed structural need 提升为 one-step successor。

交付物候选：

- plain Pi/root-only 默认路径；
- 尽量复用当前 episode exit payload 的轻量 top-1 proposal；
- deterministic admission 后才创建 node instance；
- checkpoint、局部恢复、invalid proposal bounded recovery；
- governance-only provider calls/tokens 的独立计量。

退出门由 J0–J4 决定。root-only 增加 provider round、显式链相对 B0/B1/B3 没有质量、
恢复或总成本增益，或治理成本无法压低时，本阶段终止于 plain Pi + governed source baseline；
是否启用 Phase 4B optimization 由其独立 gate 决定。

## 10. Post-V1 Phase 6：Optional Search Policy

目标：在同一 metadata/state view 上比较链、top-k 浅树、best-first 和 bounded tree。

第一版只允许：

- bounded candidate count/depth/budget；
- body-free 未实例化候选；
- deterministic admission；
- 单 active execution trajectory；
- policy 无直接 store/tool 权限。

只有 JIT 链的必要性、治理开销和经济性门通过后，才实现复杂 search policy。MCTS/LATS/
RAP World Model 是可插拔候选，不是默认架构依赖；任一层失败都回退到上一层，不影响薄
Control Plane 成立。

## 11. 持续 Legacy Contraction Gate

V1-S0–S5 的每个交付切片都必须同时维护旧路径收缩；Post-V1 Phase 5/6 仅在被采用后
遵守同一 contraction gate：

- shadow/paired 阶段可以暂时保留旧 reader，但必须记录真实调用量；
- default-off/rollout 阶段必须有 run-bound fallback，不得新增第二 authoritative writer/store；
- experiment/shadow 可以短期增加表示和调用，但必须不拥有 authority、可整体删除并有
  owner/TTL/sunset；
- 新 producer 稳定后，旧 producer/consumer/恢复入口必须进入 usage-zero 观察；
- supported historical corpus、public CLI、recovery 和 task-trajectory tests 必须通过；
- usage-zero 后单独删除旧路径，并同步 replacement 文档、ADR 和 deprecation ledger；
- 无法删除的旧路径必须说明它仍拥有的独立责任；否则回退或撤销新抽象；
- 不以删除数量单独过门，必须报告新增和删除后的 concepts、owners、dependencies、branches、
  adapters、fallbacks 和 call depth 净变化。

## 12. 每个实现切片的 Definition of Ready

- 有一个可复现问题或已通过的局部实验；
- 明确 current owner 和 target owner；
- 完成 metadata inventory/duplication review；
- 说明 API、permission、persistence、recovery 和文档影响；
- 有最小失败测试和验收指标；
- 有回滚或兼容读取方案；
- 不需要同时重构多个核心模块才能验证。

## 13. Definition of Done

- 代码、contract、migration 和 failure-path tests 通过；
- provider/工具副作用有真实 receipt，不用模型自报代替；
- 对应 roadmap 状态、ADR/evidence index 和 implementation log 已更新；
- `AGENTS.md` / `API.md` / contract catalog 的适用项已同步；
- 已知限制和下一 gate 明确；
- 没有新增无 owner、无索引或重复权威的文档。
- migration/cutover 通过 mapping owner 定义的 net complexity gate；
- 若仍处于 shadow/paired 阶段，明确标记为未完成迁移，不能仅凭新模块或测试存在宣称
  重构完成。
