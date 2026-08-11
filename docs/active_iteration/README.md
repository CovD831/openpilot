# Active Iteration 文档入口

## 当前入口

按阅读目的选择文档，不需要顺序阅读整个目录。

| 目的 | 文档 | 定位 |
|---|---|---|
| 对外或管理层汇报 | [ACTIVE_ITERATION_PROGRESS_REPORT_CN.md](./ACTIVE_ITERATION_PROGRESS_REPORT_CN.md) | 中文进度、结论、边界和下一步 |
| 技术评审 | [ACTIVE_ITERATION_EXPERIMENT_REVIEW.md](./ACTIVE_ITERATION_EXPERIMENT_REVIEW.md) | 当前完整证据综述和复现入口 |
| 实验审计 | [ACTIVE_ITERATION_EXPERIMENT_LOG.md](./ACTIVE_ITERATION_EXPERIMENT_LOG.md) | 追加式协议、失败、结果和证据等级账本 |
| 架构设计 | [ACTIVE_ITERATION_EXPERT_ROUTING_ARCHITECTURE.md](./ACTIVE_ITERATION_EXPERT_ROUTING_ARCHITECTURE.md) | 当前主动迭代、信号和专家路由设计 |
| 核心运行时重构 | [CORE_RUNTIME_USABILITY_AND_ACTIVE_ITERATION_PLAN.md](./CORE_RUNTIME_USABILITY_AND_ACTIVE_ITERATION_PLAN.md) | 用户可用性、任务准入、受治理分解、核心问诊推进与 post-core 交接计划 |
| CRU-1 至 CRU-8 累积开发版 | [CRU_1_TO_8_DEVELOPMENT_RELEASE.md](./CRU_1_TO_8_DEVELOPMENT_RELEASE.md) | `0.1.0.dev7` 的 provider-aware 输入/输出预算、post-plan reasoning、一次完整 length recovery、writer fail-closed 与真实 canary 边界 |
| CRU-1 至 CRU-7 累积开发版 | [CRU_1_TO_7_DEVELOPMENT_RELEASE.md](./CRU_1_TO_7_DEVELOPMENT_RELEASE.md) | `0.1.0.dev6` 的完整范围、generated-code durable writer handoff、safe project scope、bounded inventory、typed pre-task admission、验证与回滚边界 |
| CRU-8 provider-aware budget/recovery | [CRU_8_PROVIDER_AWARE_BUDGET_AND_CODE_GENERATION_RECOVERY_PLAN.md](./CRU_8_PROVIDER_AWARE_BUDGET_AND_CODE_GENERATION_RECOVERY_PLAN.md) | Provider context/output capability、post-plan disabled reasoning、一次完整 length recovery、截断 writer fail-closed 与真实贪吃蛇 canary |
| CRU-1 至 CRU-4B 累积开发版 | [CRU_1_TO_4B_DEVELOPMENT_RELEASE.md](./CRU_1_TO_4B_DEVELOPMENT_RELEASE.md) | 从远端基线累积到 `0.1.0.dev2` 的完整范围、开发 canary、验证门禁与已知限制 |
| CRU-2A metadata gate | [CRU_2A_METADATA_IMPACT_AND_WRITER_INVENTORY.md](./CRU_2A_METADATA_IMPACT_AND_WRITER_INVENTORY.md) | pre-task durable owner、复用/新建决策、控制写入者与原子持久化清单 |
| CRU-4B recovery metadata gate | [CRU_4B_METADATA_IMPACT_AND_RECOVERY_INVENTORY.md](./CRU_4B_METADATA_IMPACT_AND_RECOVERY_INVENTORY.md) | bounded Provider request/observation owner、replay-free crash recovery 与 fail-closed 清单 |
| CRU-5 diagnostic metadata gate | [CRU_5_METADATA_IMPACT_AND_DIAGNOSTIC_INVENTORY.md](./CRU_5_METADATA_IMPACT_AND_DIAGNOSTIC_INVENTORY.md) | task-owned conflict/risk、active diagnostic decision、canonical progress 与三臂接口清单 |
| CRU-6 core handoff metadata gate | [CRU_6_METADATA_IMPACT_AND_CORE_HANDOFF_INVENTORY.md](./CRU_6_METADATA_IMPACT_AND_CORE_HANDOFF_INVENTORY.md) | core source readiness、post-core eligibility、分层结果组合与唯一 package builder 边界 |
| CRU-7 canary/rollout gate | [CRU_7_CANARY_AND_ROLLOUT_INVENTORY.md](./CRU_7_CANARY_AND_ROLLOUT_INVENTORY.md) | 12 类用户任务、四路径、非补偿 hard metrics、默认切换与 legacy rollback 决策 |
| Project Improvement 模块研究 | [PROJECT_IMPROVEMENT_ARCHITECTURE_RESEARCH.md](./PROJECT_IMPROVEMENT_ARCHITECTURE_RESEARCH.md) | 模块边界、运行语义、历史问题、根因与重设计约束 |
| 下一阶段实验协议 | [MINI_SWE_ACTIVE_ITERATION_EXPERIMENT_PROTOCOL.md](./MINI_SWE_ACTIVE_ITERATION_EXPERIMENT_PROTOCOL.md) | mini-SWE 原生轨迹上的分阶段净增益、消融与迁移计划 |
| 最短收益决策路线 | [MINI_SWE_CORE_BENEFIT_SCREEN_PROTOCOL.md](./MINI_SWE_CORE_BENEFIT_SCREEN_PROTOCOL.md) | 12 个配对任务的强信号筛查：先判断核心 E2--E3 闭环是否值得继续投入 |
| 核心收益筛查就绪性 | [MINI_SWE_CORE_BENEFIT_SCREEN_READINESS_AUDIT_V1.md](./MINI_SWE_CORE_BENEFIT_SCREEN_READINESS_AUDIT_V1.md) | 当前 receipt、独立审核与 Air 串行资源门的审计状态 |

## 冻结依赖

[ACTIVE_ITERATION_SIGNAL_DECISION_LOG.md](./ACTIVE_ITERATION_SIGNAL_DECISION_LOG.md)
是历史决策账本，并被已冻结实验 artifact 按原路径引用。它必须保留，但不是当前汇报或架构入口。
新结论不再同时写入该文件和实验日志。

当前实施状态：CRU-2A 已完成 metadata contract、durable store、assistant
ledger 幂等提交/崩溃恢复，以及 canonical prepared/active task binding 与 session
authority freshness/revocation recovery gate；唯一 pre-task reducer writer migration 也已完成。
CRU-2B deterministic runtime-fact completion 已接入 once/interactive 默认入口；
CRU-2C bounded zero-tool model response core、CRU-2D evidence escalation core
与 CRU-3 governed decomposition/single-task evidence handoff 已完成；CRU-4A
model-visible bounded tool protocol repair 与 CRU-4B durable Provider-step
recovery、CRU-5 core active diagnostic strengthening、CRU-6 verified core/post-core
handoff 与 CRU-7 canary/default switch 已完成。统一 autonomous entry 与 governed
decomposition 默认开启，显式 false 保留 legacy rollback；model-visible repair 因独立回归门
未过保持 canary-only。post-core transaction 仍等待权威 PKG3/PKG4 consumer，不回落
legacy improvement loop。
evidence-required candidate 复用既有 ToolRouter、
ToolEventLoop、Guard 和 checkpoint，不回落旧 decomposition，也不复制 tool
executor；Agent Generator 未进入新路径。

## 归档

`archive/` 保存已被当前入口吸收的旧矩阵和比较稿。归档文件用于追溯，不代表当前项目状态。

## 更新规则

- 当前进度和对外表述更新中文汇报；
- 新实验事实先写冻结 artifact、实验日志和实验综述；
- 架构文档只保留当前设计，不记录日期式实施流水；
- 历史失败和无效实验不得删除或重新解释；
- 同一结论只保留一个权威入口，其他文档用链接引用。
