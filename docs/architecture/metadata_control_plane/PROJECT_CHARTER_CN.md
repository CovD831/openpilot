# OpenPilot Metadata Control Plane 项目章程

> Status: Proposed target charter
> Authority: Product and architecture intent; not current runtime behavior
> Owner: Architecture
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 问题定义

主流 harness 已经能让模型通过工具调用和环境反馈隐式生成一条执行轨迹。OpenPilot
不应重复实现一个更重的 agent loop。它要解决的是长程任务中 harness 本身通常不承担的
控制问题：

- 任务事实、权限、证据、预算和完成状态是否有唯一权威；
- 会话变长或进程中断后，任务是否仍能恢复且不漂移；
- 每个由 OpenPilot 准入并声明支持的 model-request route，如何在其可观测边界内统一治理
  来源、权限、freshness、declared-required facts、窗口预算和不可信内容；
- 拆分、候选、搜索和返工如何被审计、替换和限额；
- metadata 如何长期演化，而不是不断堆叠一次性字段和聚合模型。

## 2. 产品定位

OpenPilot 是长程 Agent 的 **薄 Metadata-first 控制平面**。它不接管 harness 的局部
推理和普通工具选择，而是在跨 episode、权限、副作用、验证、上下文、持久化和恢复边界上
组织 typed authority，并把 Pi 等 harness 作为可替换的执行引擎。

目标结构是：

```text
Metadata Kernel
+ Metadata Evolution Protocol
+ Durable State / Evidence
+ Derived Graph and State Views
+ Context Boundary Governance
+ Governed Execution Ports
+ Durable Recovery

Optional after evidence:
+ Selective Context Optimization
+ Explicit JIT / Pluggable Search Policy
```

最低可成立版本不需要显式动态链、树或 World Model。只要 metadata evolution、现有
permission/evidence/completion/recovery 和统一 context governance 成立，项目就有独立价值。
选择性注入和 token 缩减不是最低版本的成立条件。

## 3. 核心用户

- 构建长程 coding/research/operations agent 的开发者；
- 需要审计、恢复、权限边界和成本控制的平台工程团队；
- 希望在不绑定单一搜索算法或 harness 的前提下迭代 agent policy 的研究者。

第一阶段不以普通终端用户 UI 为主要竞争面。

## 4. 核心竞争力

1. **稳定的 metadata kernel**：事实、身份、权威、生命周期和证据关系先于控制器实现。
2. **可执行的 metadata 演化协议**：字段和 contract 可增加、迁移、废弃、审计和删除，
   而不是只靠人工约定。
3. **控制平面与执行平面分离**：模型回合、工具选择和搜索策略可替换；权限、证据和恢复
   不随 harness 更换而重写。
4. **上下文治理与优化分层**：OpenPilot-supported routes 在声明的可观测/能力等级内统一
   约束 source、trust、permission、declared-required facts、freshness、请求预算和 fallback；
   选择性注入只是在其上的可选优化。
5. **搜索策略可选且可否决**：链、浅树、DAG、best-first、MCTS/LATS 类策略只决定如何
   分配推理资源；实验无增量收益时不进入生产。
6. **持久化恢复是一等能力**：checkpoint、receipt、validation 和 resume identity 共同
   约束恢复，避免重复副作用和伪完成。

## 5. 目标

- 让每个 OpenPilot-admitted supported model-request route 在声明的可观测范围内使用统一、
  可验证、可回退的上下文治理边界；
- 在可选优化通过实验后，使长任务的 model-facing 上下文随活动工作集增长，并在同模型、
  同工具、同任务预算下以更少输入保持质量和安全不劣；
- 让关键决策、状态变化和副作用可审计、可恢复、可重放；
- 允许 metadata contract 在兼容窗口内演化，并能证明旧数据仍可读取；
- 让 search policy、context policy 和 harness 可以独立替换和评估；
- 逐步收缩当前臃肿 controller，而不是一次性重写全部生产路径。

## 6. 非目标

- 不重新实现通用 LLM harness 的模型循环、工具协议和终端体验；
- 不把 Control Plane 实现成第二套 workflow engine；
- 不立即建立全局图数据库或把所有 value nesting 改为关系图；
- 不把模型思维链、所有未选候选或完整隐式推理持久化；
- 不默认启用树搜索、MCTS 或多 Agent；
- 不把选择性注入、summary、on-demand 或 token 减少写成 Context Governance 的成立条件；
- 不用新架构名称掩盖没有 provider telemetry 或独立样本的实验缺口；
- 不通过 big-bang rewrite 丢弃当前权限、恢复、Evidence Core 和 Pi 路径。

## 7. 成功定义

项目成功不是“metadata 更多”或“图更复杂”，而是同时满足：

- 核心任务质量与安全门不劣；
- Context Governance 在 governed-source baseline 和 selective routes 上保持同一
  authority/permission/freshness/declared-required 不变量；
- 可选上下文优化启用时，长程上下文和总推理成本有可重复下降；
- 短任务接近零额外治理回合；
- metadata 变更可以通过 registry、兼容语料、迁移和使用审计验证；
- 故障恢复不重复不可逆副作用；
- 替换执行 harness 或 search policy 不要求重写权威状态模型。
- 每个新抽象能够删除或替代一个真实旧依赖/分支，而不是只迁移复杂度。
- 新抽象、fallback 和 shadow representation 的净复杂度可解释，并保持单一 authoritative
  writer/decision owner。

具体基线和阈值由 [`EVALUATION_PLAN_CN.md`](EVALUATION_PLAN_CN.md) 统一管理。
