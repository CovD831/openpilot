# 历史文档与证据集合索引

> Status: Active collection-level index
> Authority: Classification and routing only; source documents retain their recorded evidence
> Owner: Architecture / documentation owners
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 当前规模快照

截至 2026-08-31，`docs/` 下 Markdown 约 641 份，其中：

| Collection | Markdown files |
| --- | ---: |
| `docs/context_management/` | 597 |
| `docs/active_iteration/` | 15 |
| `docs/task_trajectory/` | 12 |
| `docs/architecture/`（本次新增前） | 6 |
| `docs/runtime_recovery/` | 4 |
| `docs/metadata/` | 4 |
| 其他 docs collections | 3 |

`docs/context_management/` 顶层约有 557 个 `PHASE_*` 文档；
`experiments/context_scope_governance/` 当前约有 84,145 个文件。后者包含 fixtures、环境、
runs 和 receipts，不能按普通设计文档批量移动或改写。

数字用于说明整理规模，不是永久 contract；新增/删除后无需手工维持精确计数。

## 2. Collection-level registry

| Path / collection | Status | Authority | Owner | Superseded by / route | Evidence for | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `AGENTS.md`, `API.md` | Active | Project-wide normative | Project | None | Current policy/API | 保持同步，不归档 |
| `Code/src/metadata/` | Active | Executable contract truth | Metadata | None | Current schemas/validation | 由 tests/catalog 校验 |
| `docs/metadata/README.md` | Active | Routing | Metadata | None | Metadata docs | 保留唯一入口 |
| `docs/metadata/DEVELOPMENT_CONVENTIONS.md` | Active | Normative workflow | Metadata | None | Current change rules | 与本 program 演化协议并行，实施前仍优先 |
| `docs/metadata/CONTRACT_CATALOG.md` | Active | Authoritative inventory | Metadata | Future executable registry, when accepted | Public contract ownership/lifecycle | Phase 1 校验，不批量重写 |
| `docs/metadata/VALUE_NESTING_RESEARCH.md` | Research | Non-normative | Metadata research | None | Current tree/value pressure | 保留研究身份 |
| `docs/architecture/OPENPILOT_PI_RUNTIME_DECISION.md` | Adopted | Current architecture decision | Runtime | None | Pi dependency/permission boundary | 保留 |
| `docs/architecture/ADR-OPENPILOT-HARNESS-EVIDENCE-PHASE0-1.md` | Adopted | Current architecture decision | Harness/Evidence | None | Run/evidence boundary | 保留；后续编号归入 ADR index |
| `docs/architecture/OPENPILOT_HARNESS_EVIDENCE_*` | Mixed current plan/audit | Current-generation architecture/evidence | Harness/Evidence | New program index for target routing | Existing refactor provenance | 单独审计状态头，不覆盖结论 |
| `docs/architecture/metadata_control_plane/` | Active program | Target architecture/roadmap/governance | Architecture | None | New-generation development | 当前唯一新 program 入口 |
| `docs/context_management/README.md` | Active | Subsystem routing/current baseline | Context assembly | None | Unified context assembly | 保留；禁止继续扩张顶层 phase docs |
| `docs/context_management/EXPERIMENT_EVIDENCE_INDEX.md` | Active | Evidence routing | Context evaluation | None | Experiment claim mapping | 保留，不把 result 当 production authority |
| `docs/context_management/PHASE_*` | Mixed evidence/historical | No project-wide normative authority unless explicitly routed | Original phase owners | Subsystem README/evidence index | Historical implementation and experiment slices | 不移动；分批标记 high-value/current references |
| `docs/context_management/context_scope_governance/` | Active research route | Target research/evidence, not production contract | Context research | Metadata control-plane target docs for project-wide architecture | Dynamic chain/tree/context evidence | 保留并通过 evidence index 引用 |
| `experiments/context_scope_governance/` | Evidence collection | Immutable experiment inputs/runs/receipts | Experiment owners | Evidence index | E03/E04 and follow-ups | 不覆盖、不批量移动；清理另立批准 |
| `experiments/full_architecture_context_observation/` | Mixed historical/current experiment evidence; X0 restore completed | Experiment manifests/results/runs retain recorded authority | Context evaluation / original experiment owners | Context evidence index and task-trajectory references | Provider/context/tool-routing evidence | 108 个 tracked paths 已按 owner 裁决从 pinned HEAD 恢复；新文件保留，后续删除仍需 H4 |
| `experiments/mini_swe_active_iteration/` | Historical isolated experiment package; X0 restore completed | Recorded experiment protocol/results only; not production authority | Active-iteration experiment owner | `API.md` experimental boundary and active-iteration docs | SWE-bench/core-benefit screening | 74 个 tracked paths 已恢复，`API.md` 引用重新成立；后续归档/删除单独审批 |
| `experiments/metadata_architecture/` | Historical metadata experiment; X0 restore completed | Recorded experiment evidence only | Metadata experiment owner | Metadata architecture/evolution evidence | Three-layer/authority/isolation probes | 15 个 tracked paths 已恢复；保持 historical evidence，不移动、不替换 |
| `experiments/context_projection_pilot/` | Active/mixed experiment collection; audit pending | Experiment evidence only | Context evaluation | Context evidence index / C routes | Projection mechanism evidence | 保留原 run；纳入 X0 owner/reference inventory |
| `experiments/planner_prompt_pilot/` | Active/mixed experiment collection; audit pending | Experiment evidence only | Planner evaluation | Evidence routing pending | Planner/prompt paired evidence | 不覆盖 run；纳入 X0 inventory |
| `experiments/provider_native_loop_pilot/` | Active/mixed experiment collection; audit pending | Experiment evidence only | Provider/runtime evaluation | Evidence routing pending | Provider-native loop evidence | 不覆盖 run；纳入 X0 inventory |
| `experiments/local_prompt_slimming_pilot/` | Active/mixed experiment collection; audit pending | Experiment evidence only | Context evaluation | Evidence routing pending | Local prompt-slimming evidence | 不覆盖 run；纳入 X0 inventory |
| `experiments/metadata_control_plane/` | Active experiment route | New architecture mechanism/spike/canary evidence | Architecture/evaluation | Metadata-control-plane Evidence Index | ME/C/J/S/R claims | 新 run 不覆盖；不放生产实现 |
| `docs/runtime_recovery/` + root loop protocols | Active | Current recovery design/normative protocols | Recovery | None | Resume/reconciliation | 保持现有单一 roadmap 规则 |
| `docs/task_trajectory/` | Active | Current evidence architecture/log | Trajectory | None | Runtime evidence/implementation history | 行为变化同步 implementation log |
| `docs/active_iteration/` | Mixed; audit pending | Subsystem-specific only | Active iteration | Pending collection review | Historical/current research | 未分类前不得作为 project-wide authority |
| root thought/idea documents | Historical/research candidate | Non-normative unless explicitly adopted | Original authors | Project charter/target architecture for current program | Design provenance | 后续逐份确认状态，不删除 |

## 3. Per-document registry fields

需要逐份清理时使用以下字段，不另造一套正文数据库：

```text
path
title
status
authority
owner
superseded_by
evidence_for
last_reviewed
notes
```

优先登记被当前 README、roadmap、API、tests 或 evidence index 引用的文件。无人引用的
phase 文档不自动等于可删除，因为它可能仍是历史 claim 的唯一 provenance。

## 4. 整理批次

### H0：建立入口和集合索引

本文件完成 collection-level 分类；不移动、不删除、不批量改正文。

### H1：当前权威去重

给所有 active/normative/target 文档补 header，找出相同主题的多个 owner。只保留一个
current owner，其余标记 Superseded/Historical 并给出链接。

### H2：高价值证据路由

从当前 roadmap、API 和 contract catalog 反查证据，确保每个仍使用的 claim 都能到达
具体 manifest/result/receipt；没有被采用的实验不进入 current architecture。

### H3：`PHASE_*` 收束

停止新增顶层 phase 文档。后续状态更新写入一个 roadmap；实验细节放 route 自己的
README/manifest/result。旧文件保持路径，按被引用频率分批加状态头。

### H4：archive candidates

只有满足以下条件才提出移动/删除：

- 没有 active 文档、代码、测试、恢复流程或 evidence index 链接；
- replacement 和 provenance 已明确；
- 移动后链接检查通过；
- 用户对具体目标给出单独授权。

本次启动工作不执行 H4。

## 5. 目前不能做的事

- 不把 557 个 phase 文档一次性改名或移动；
- 不删除当前 worktree 中已标记删除/修改的用户工作；
- 不压缩、重写或合并原始 receipts；
- 不把实验的 `supported_local_*` 状态提升为生产批准；
- 不因新 target architecture 出现而宣告旧 API、Pi、Evidence Core 或 recovery 失效。
