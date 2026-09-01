# 架构与开发文档维护规则

> Status: Active governance proposal
> Authority: Canonical maintenance rule for the metadata-control-plane program
> Owner: Architecture / documentation owners
> Supersedes: Ad-hoc creation of unindexed phase documents for this program
> Last reviewed: 2026-09-01

## 1. 核心规则

1. 一个主题只有一个 current normative owner。
2. README/index 只负责路由和状态，不复制完整设计或实验结论。
3. 架构选择写 ADR；实施顺序写 roadmap；运行结果写 evidence；当前 contract 写 API、
   metadata catalog 或代码模型。
4. target architecture 不得写成已实现；roadmap 的 completed 不替代测试和 evidence。
5. 原始 manifest、receipt 和 run result 不覆盖；结论升级写新 analysis 或 evidence index。
6. 本项目不再新增未进入索引的顶层 `PHASE_*` 文档。
7. 新建文档必须说明为什么不能更新现有 owner。
8. 长期规范只写规则，不写易变的工作区/仓库数量（dirty paths、行数、文件数、修复计数等）；
   此类数字只出现在带日期的 evidence、manifest 或 run 记录中。

### 1.1 主题 owner 矩阵

同一规则可以在其他文档中说明影响，但不得复制第二份 checklist、阈值或 schema。引用方只
保留完成当前文档职责所需的一句话，并链接到下列 owner：

| Topic | Current normative owner | Other documents may contain |
| --- | --- | --- |
| 跨模块、难逆架构决定 | 对应 ADR | 决定摘要和 ADR 链接 |
| 产品边界、目标不变量 | `PROJECT_CHARTER_CN.md` / `TARGET_ARCHITECTURE_CN.md` | 对实现或实验的约束摘要 |
| 子系统语义、authority、fallback | 对应 L2 design | 路由和 adoption gate |
| 迁移顺序、阶段进入/退出 | `REFACTOR_ROADMAP_CN.md` | 当前阶段状态 |
| 对比臂、指标、统计和成本门 | `EVALUATION_PLAN_CN.md` | 对应 experiment ID |
| Claim 状态和 evidence 路由 | `EVIDENCE_INDEX_CN.md` | Claim ID，不复制结果正文 |
| 当前 executable contract | code / `API.md` / metadata catalog | current-to-target mapping |
| 历史材料状态和清理动作 | `HISTORICAL_DOCUMENT_INDEX_CN.md` | superseded/evidence 链接 |

例如，net contraction 的决定归 ADR-0005，ledger 字段归 current-to-target mapping，量化判据
归 evaluation plan，何时执行归 roadmap；四处不得各自维护另一套完整定义。

### 1.2 Canonical glossary

| Term | Meaning |
| --- | --- |
| authority | 对某类事实拥有合法写入和最终解释权的唯一 owner |
| current / target | current 是可执行事实；target 是迁移方向，不能写成已实现 |
| episode | 一次由 OpenPilot admission 绑定的 execution attempt/visit 语义边界 |
| admission | 将 proposal/request/action 与 authority、scope、evidence 和 budget 绑定的门禁 |
| governed source baseline | admitted source pack 中完整 mandatory/control facts；不是完整仓库或完整历史 |
| declared-required coverage | 已声明必需事实的可验证覆盖；不声称发现所有 latent dependency |
| Context Governance | 所有 supported admitted request route 必须满足的 source/trust/freshness/budget/fallback 边界 |
| Context Optimization | 可关闭的 selection、omission、summary、on-demand 等增量优化 |
| root-only | 一个 admitted episode 内完成，不创建结构候选或额外 candidate-generation round |
| proposal / node | proposal 是轻量、无执行权的候选；通过 admission 后才成为可执行 node |
| ClosureCommit | verification/completion owner 接受并绑定 evidence 后形成的权威终态事实 |
| derived view | 从权威事实构造、可丢弃重建且不得反向写 authority 的视图 |
| net complexity ledger | 同时记录新增与删除的 concept、owner、依赖、分支、adapter 和运行路径 |
| usage-zero | 静态、运行时和恢复读取均归零；是删除的必要而非充分证据 |
| dormant | 已登记但不在当前实验/实现队列中；不得据此创建 production schema 或 package |

## 2. 必须使用的文档头

新建或被实质维护的架构文档至少包含：

```text
Status: Draft | Proposed | Active | Adopted | Deprecated | Superseded | Historical
Authority: Normative | Current architecture | Target architecture | Roadmap | Evidence | Routing only
Owner: team or subsystem
Supersedes: path or None
Last reviewed: YYYY-MM-DD
```

`Superseded` 文档必须指向替代文档；`Historical` 文档不得继续包含“下一步必须执行”的
当前命令。

## 2.1 架构层级与实验边界

```text
L1 architecture
  why / what / system boundary / invariants

L2 subsystem architecture
  domain model / state machine / interactions / owners / open claims / fallback

L3 implementation design
  concrete interfaces / migration / failure semantics / tests for one accepted slice
```

- L1/L2 使用稳定文件名，由 architecture 目录拥有；
- L3 只在具体切片即将实现时补充，不为每个函数建立永久设计文档；
- experiment protocol、runner、receipt 和 analysis 放在 `experiments/`；
- architecture 只保留 Claim ID、adoption gate 和 Evidence Index 链接；
- engineering spike 证明可行性，不自动升级质量或经济性 claim。

## 2.2 L3 interface specification minimum

一个 port/adapter/store seam 在进入实现前必须有一份由当前切片 owner 维护的 L3 规格，至少
覆盖下列适用项。`N/A` 必须说明原因，不能以函数名代替语义定义。

| Field | Required content |
| --- | --- |
| owner and boundary | authority owner、caller/callee、允许依赖方向 |
| typed request/response | 复用或新增的 exact model、required/optional 字段、version |
| authority inputs | permission、scope、budget、revision、consent、acceptance/evidence bindings |
| side effects | 允许/禁止的 mutation、dispatch 前门禁、durable receipt |
| errors | typed error/disposition、fail-closed 条件、provider/tool error projection |
| retry and idempotency | retry owner、identity key、重复/冲突处理、不可逆动作规则 |
| timeout and cancellation | timeout、cancel、lease/revoke 对已发生和后续动作的影响 |
| persistence and recovery | 写入 owner、transaction boundary、crash window、resume/reconcile |
| compatibility | supported versions、migration/read policy、旧 adapter/caller 退出条件 |
| observability | body-free events/metrics、redaction、retention、native/proxy confidence |
| conformance tests | contract、negative、fault、historical、adapter-equivalence cases |
| configuration / capability ownership | seam 消费的 config、provider/reasoning capability profile、policy version 的 owner、加载位置与变更门 |
| resource envelope | 单次与累计调用预算（latency、calls、tokens、存储）及超界时的 fail-closed / typed budget failure 行为 |
| rollout | shadow/default-off/cutover、rollback、usage-zero 和 deletion gate |

跨 port 的完整 V1 还必须有 composition root、唯一入口、store/adapter binding 和端到端
conformance suite；多份局部 L3 不能依赖未登记的隐式 wiring 才能协同工作。

L3 规格随切片按需冻结：允许且要求为即将实现的当前切片冻结必要 L3；禁止为尚未进入
Definition of Ready 的未来切片批量预写 L3，也不得以“规范完整性”为由提前生成全套 seam
规格；ME0 完成前不创建任何 V1 runtime seam 的 L3 文档。

## 3. 文档类型与放置

| 类型 | 放置 | 是否可频繁改写 |
| --- | --- | --- |
| Project-wide normative policy | root `AGENTS.md`, `API.md`, loop protocols | 仅随真实 contract/政策变化 |
| Current contract inventory | `docs/metadata/`, subsystem README | 随实现同步 |
| Adopted architecture decision | `docs/architecture/**/adr/` 或已存在 ADR | 采用后不可重写结论；变化写新 ADR |
| Target architecture | 本目录稳定命名文档 | 可随决策演化，必须标记 target |
| Roadmap | 每个 program 一个 active roadmap | 可更新状态和顺序 |
| Experiment protocol/result | `experiments/<route>/` + evidence index | protocol 冻结后只新版本；run 不覆盖 |
| Implementation log | 对应 subsystem 的单一 log | 每个完成切片追加 |
| Historical material | 原路径或 archive，带替代指针 | 只修断链/状态，不重写历史结论 |

## 4. 更新现有文档还是新建

优先更新现有 owner。只有下列情况新建：

- 不可逆或跨模块决定，需要 ADR；
- 新 program 确实没有 charter/roadmap；
- 实验协议冻结后需要新版本；
- 原文档已 adopted/historical，修改会篡改当时结论；
- 新内容拥有不同 authority 或 lifecycle。

不得因“内容很多”“阶段编号变了”或“想单独汇报进度”新建文档。

## 5. 命名规则

- 长期 owner 使用稳定语义名，例如 `TARGET_ARCHITECTURE_CN.md`；
- ADR 使用 `ADR-NNNN-SHORT-TITLE.md`；
- 实验 run 使用不可覆盖的 versioned directory；
- 日期只用于 evidence snapshot、run 或确需冻结的 review；
- 禁止在 program 根继续扩张 `PHASE_*_PLAN/RESULT.md`；阶段状态回写 roadmap，详细证据
  放实验目录。

## 6. 变更同步矩阵

| 变化 | 必查/必更新 |
| --- | --- |
| Metadata field/contract | models、tests、exports、contract catalog、impact note、migration/compatibility；外部可见时 `API.md` |
| 权限、路由、预算、恢复、完成 | `AGENTS.md`、`API.md`、相关协议、failure-path tests、ADR（若跨切面） |
| Target architecture | target architecture、ADR、roadmap；不得直接改 current status |
| Experiment claim | manifest/result、evidence index、evaluation claim status |
| Task trajectory/recovery behavior | 对应 architecture/evidence docs 和 implementation log |
| 文档 owner/authority 改变 | 本索引、历史索引、旧文档 `Superseded` 指针 |

“reviewed but no change required”应写进 PR/change note，不要求给无关文档制造空修改。

## 7. Evidence 维护

- run directory 默认 append-only / no-overwrite；
- 原始模型正文、凭据和敏感环境不进入 receipt；
- aggregate/analysis 必须引用具体 run identity，不复制为新 authority；
- proxy 与 provider telemetry 分栏；不可用字段保持 null/unknown；
- 同会话、replay、deterministic fixture 和独立 provider 样本必须明确区分；
- 失败结果同样保留，不能只索引通过结果。
- architecture package release 或广范围 staging 前必须运行
  `python3 experiments/metadata_control_plane/spikes/x0_reviewable_baseline/runner.py --check`；
- 受保护集合中的 tracked deletion 默认 `needs_owner_decision`，在 restore/replacement/H4
  裁决前阻塞 package release；X0 不授予删除或恢复权限；
- B1 必须由 owner-reviewed full Git commit pin 固定；当前 dirty worktree 默认排除，不能因
  X0 guard 通过而被隐式纳入 comparison baseline；
- 不得用 `git add -A` 把未裁决 historical-evidence deletions 顺带纳入其他提交。
- 即使 X0 通过，dirty worktree 中存在无关修改时仍只允许显式 path staging；B1 pin 和
  package-release readiness 都不授予 broad staging 权限。

## 8. 历史文档整理流程

历史清理按四步进行：

1. **Index**：登记 path、status、authority、owner、superseded_by、evidence_for、
   last_reviewed；
2. **Route**：让当前 README/roadmap/evidence index 指向仍有效的材料；
3. **Mark**：给高优先级旧文档加 Historical/Superseded 头，不批量改写正文；
4. **Move/Delete**：只有确认无链接、无代码/测试消费者、无恢复依赖并获得单独批准后执行。

移动不是整理的第一步。大量相对链接存在时，保留原路径并加状态头通常更安全。

## 9. Review 节奏

触发式 review 优先于固定日历：

- 每次 metadata/API/permission/recovery 变化；
- 每个 roadmap phase 进入或退出；
- 每个主要 experiment claim 升级；
- 每次 harness/provider/search policy 替换；
- 文档扫描发现 orphan、重复 authority、断链或 90 天未复审的 active document。

每个阶段退出时至少运行：

- Markdown link/path check；
- active 文档 header/owner check；
- duplicate normative owner review；
- `git diff --check`；
- 受影响 contract/API/doc sync review。

## 10. PR / change note 的 Documentation Impact

每个实现切片包含：

```text
Documentation impact:
- Current contracts changed:
- Target architecture changed:
- ADR required:
- Roadmap/evidence status changed:
- Historical document superseded:
- Files reviewed but unchanged:
```

全部为 `None` 时也应显式说明，以阻止文档同步成为默认遗漏项。
