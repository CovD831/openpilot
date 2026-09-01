# ADR-0001: 以 Metadata Control Plane 方式启动新一代重构

> Status: Accepted for development planning
> Authority: Architecture decision; it does not authorize production behavior changes
> Owner: Architecture
> Supersedes: None
> Last reviewed: 2026-08-31

## Context

当前项目已经拥有大量 metadata contracts、controller 行为、Pi 集成、Evidence Core、
恢复协议、上下文实验和历史阶段文档。继续在原有 controller 上叠加功能会扩大热点文件
和重复语义；直接重写又会丢失已经验证的权限、证据和恢复边界。

同时，项目最稳定、最有差异化的方向已经明确：以 typed metadata 作为权威状态和控制
骨架，把 harness、上下文策略和搜索算法变成可替换组件。

## Decision

1. 将下一阶段视为新一代架构开发，但采用增量替换而不是 big-bang rewrite。
2. 以 Metadata Kernel、Evolution Protocol、Derived Views、Search/Context Policies、
   Governed Execution 和 Durable Recovery 作为目标结构。
3. Pi 保持当前 execution plane 身份；OpenPilot 拥有 task authority、permission、
   evidence、completion 和 recovery。
4. 当前 `AGENTS.md`、`API.md`、`Code/src/metadata/`、accepted ADR 和 tests 在迁移期间
   继续是现行权威。
5. target architecture、roadmap 和实验结果不得自动升级为生产 contract。
6. 首先完成文档基线和 metadata evolution 实验，再开始生产模块重构。
7. 历史文档先索引和标记，不批量移动或删除。

## Consequences

正向结果：

- 新开发有稳定入口、边界和停止门；
- metadata 演化不再只依赖人工记忆；
- 可以独立比较 JIT chain、tree/search policy 和 harness；
- 现有权限、证据和恢复能力可被逐步复用。

代价：

- 迁移期需要维护 current 与 target 的明确区分；
- 兼容语料、registry、migration 和 usage audit 会增加前期工作；
- 旧 controller 只有在新路径覆盖和使用归零后才能删除；
- 文档不能再通过大量一次性 phase 文件表达进度。

## Rejected alternatives

### 继续在现有 controller 上直接叠加

无法解决 owner、依赖方向、metadata 演化和文档权威分散问题。

### 一次性重写全部 runtime

风险集中，难以保持 mutation、recovery、Evidence Core 和 provider 路径的已有不变量。

### 先实现通用 graph/MCTS 层

当前主要缺口是 kernel 演化和 control-plane seam，而不是搜索算法本身。search policy 应
在同一 metadata view 上后置比较。

## Validation

本 ADR 的第一阶段验证是文档和边界检查，不是运行时 benchmark。生产迁移必须逐阶段
满足 [`../REFACTOR_ROADMAP_CN.md`](../REFACTOR_ROADMAP_CN.md) 和
[`../EVALUATION_PLAN_CN.md`](../EVALUATION_PLAN_CN.md) 的 gates。
