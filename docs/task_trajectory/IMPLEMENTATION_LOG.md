# TASK_TRAJECTORY_IMPLEMENTATION_LOG.md

## 文档定位

这份文档是 OpenPilot 真实任务 / 任务轨迹证据工作的**实现总日志**。

它只记录两类内容：

1. **已经完成的问题切片**；
2. **阶段结束时明确可见的遗留问题**。

为了方便开发回看和对外汇报，本文档以后采用：

- **单一主文件维护**；
- **按日期分组记录**；
- **顶部总览 + 每日摘要 + 已完成切片 + 遗留问题 + 下一步计划** 的结构。

> 说明：历史内容已按“主要实现落点日期”重新归档。  
> 这是一种阶段性整理，不等价于逐 commit 级别的精确时间线。

---

## 更新规则

当一个问题切片满足以下条件时，必须在**同一个变更集**里更新本文件：

- 根因已经基本明确；
- 已经有实现改动；
- 已经有验证证据（测试 / 真实任务 / 轨迹）；
- 可以明确说出“这次解决了什么、还剩什么”。

如果只是：

- 还在猜测；
- 还没改代码；
- 还没验证；
- 只有方向，没有结论；

那么不应写入本文件，而应放在：

- `Thought.md`
- `REAL_TASK_FAILURE_ANALYSIS_*.md`
- 架构 / 计划类文档

---

## 推荐阅读方式

如果是**你自己回看开发过程**，建议看：

1. 顶部“进度总览”
2. 对应日期下的“已完成切片”
3. “当前遗留问题 / 下一步计划”

如果是**拿去给别人汇报进度**，建议只看：

1. 顶部“进度总览”
2. 每个日期下的“今日摘要（适合汇报）”

---

## 进度总览

| 日期 | 汇报主题 | 状态 | 验证结果 | 主要遗留 |
|---|---|---|---|---|
| 2026-07-04 | 方向切换、仓库清理、路径幻觉第一轮修复、轨迹证据层落地 | 已完成 | 路径相关测试与轨迹落盘验证 | 高层目标路径幻觉仍存在，后续 planning 仍未受证据强约束 |
| 2026-07-05 | timeout 恢复、planning surface、只读护栏、command path 硬化、真实任务复跑诊断 | 已完成 | timeout 回归、真实任务复跑、轨迹证据可复盘 | synthesis 空计划、`project_path` 贯穿不足、evidence 仍未成为唯一目标来源 |
| 2026-07-07 | 只读 synthesis 修复、fallback `project_path` 贯穿、最小路径守卫 | 已完成 | 定向 94 passed，全量 503 passed | route contract 仍粗、`runtime_mode` 仍非一等字段、全面 evidence-backed path policy 未完成 |

---

# 2026-07-04

## 今日摘要（适合汇报）

- 工作主线从“自动修复测试”转向“证据优先的真实任务诊断”；
- 清理了旧 loop 方向残留，重新确立任务轨迹证据为主线；
- 解决了第一类 `/workspace/openpilot` 幻觉路径问题；
- 落地了任务轨迹证据层与 task / subtask / tool-call id 关联；
- 真实任务开始可以被稳定复盘，而不再只能翻终端日志。

## 已完成切片

### [已完成] 工作方向从 repair-first 切换到 evidence-first

- 背景：旧方向更偏向“生成测试 -> 跑测试 -> 修失败 -> 继续循环”。
- 失败现象：这种流程容易让系统过早修表面症状，而不是先稳定收集根因证据。
- 根因判断：问题不在于缺测试，而在于“问题发现、证据采集、假设形成、验证、修复”几个阶段没有被强约束地分开。
- 实现改动：主线工作流切换成“真实任务运行 -> 完整轨迹记录 -> 失败模式总结 -> 根因假设 -> 验证任务 -> 必要时再 repair”。
- 验证结果：新的文档、任务轨迹与 failure analysis 流程都围绕这一方向建立。
- 剩余限制：自动聚类与阶段总结仍然偏弱。

### [已完成] 仓库范围重置与旧 loop 残留清理

- 背景：构建新轨迹证据层前，仓库里还保留着上一轮 `codex_loop` / auto-test-repair 残留。
- 失败现象：旧文档、旧测试假设和新流程叙述不一致，容易混淆边界。
- 根因判断：仓库叙事没有及时跟着架构方向切换同步。
- 实现改动：活跃文档主线改为 `docs/task_trajectory/*`；旧版 real-task diagnostics 文档只保留为兼容指针。
- 验证结果：当前工作说明文档已经以 trajectory evidence 为中心。
- 剩余限制：后续仍需严格执行“完成一个切片就更新日志”的纪律。

### [已完成] `/workspace/openpilot` 幻觉根路径第一轮修复

- 背景：真实任务“请梳理从 CLI 入口到主执行运行时的核心链路，并指出关键模块之间的关系”首次运行时出现了容器式路径幻觉。
- 失败现象：agent 访问了 `/workspace/openpilot`，而本地真实项目根是 `/Users/abab/Documents/openpilot/Code`。
- 根因判断：系统对稳定 project root、cwd 与文件目标 grounding 的约束不够强，不能只靠模型记忆 prompt 内的路径。
- 实现改动：引入基于 project root 的路径 resolver，并把已知幻觉根路径映射回声明的 `project_path`。
- 验证结果：相关验证覆盖集中在：
  - `/Users/abab/Documents/openpilot/Code/tests/test_project_path_resolver.py`
  - `/Users/abab/Documents/openpilot/Code/tests/test_project_path_runtime_integration.py`
  - `/Users/abab/Documents/openpilot/Code/tests/test_path_boundary_validation.py`
- 剩余限制：虽然解决了已知幻觉根路径，但高层 guessed target（如 `setup.py`、`/openpilot/...`）仍未根除。

### [已完成] 路径意图 / 路径解析结果证据化

- 背景：路径字符串此前常被静默归一化，后续很难知道系统到底做了什么修正。
- 失败现象：即使路径被纠正或阻断，runtime state 和 trajectory 里也不一定能看出来。
- 根因判断：缺少显式承载路径意图与解析结果的元数据层。
- 实现改动：引入并记录：
  - `PathIntentMetadata`
  - `PathResolutionMetadata`
  - `RuntimeStateMetadata.path_intents`
  - `RuntimeStateMetadata.path_resolutions`
- 验证结果：路径纠正和阻断现在能在 runtime state 与后续轨迹分析中直接看到。
- 剩余限制：还缺少更强的硬约束，确保后续 planning 只能从 observed evidence 或 resolver-backed candidates 中选文件目标。

### [已完成] 任务轨迹证据层与 id 关联落地

- 背景：系统已经有 logger、tool loop、metadata、artifact 等基础能力，但证据分散在多个位置。
- 失败现象：任务失败后只能翻终端，很难稳定复盘一次真实运行到底发生了什么。
- 根因判断：缺少统一、持久化、可关联的 trajectory evidence layer。
- 实现改动：
  - 打通 `/Users/abab/Documents/openpilot/Code/src/runtime_diagnostics/`
  - 让真实任务写出 durable trajectory
  - 明确 root task / subtask / step / call id 分层
- 验证结果：真实任务运行现在会持久化写到：

```text
/Users/abab/Documents/openpilot/Code/data/runtime_diagnostics/task_trajectory/
```

典型文件包括：

```text
run.json
events.jsonl
artifacts.jsonl
artifacts/
summary.json
```

- 剩余限制：自动聚类、自动阶段总结、用户侧错误展示中的 id 清洗还要继续增强。

## 当前遗留问题

- 高层 guessed target 仍然存在，不只是低层 resolver 问题；
- planning 仍然可能脱离已采集证据；
- 自动聚类与自动阶段总结还不够强。

## 当日关联文档

- `/Users/abab/Documents/openpilot/docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE.md`
- `/Users/abab/Documents/openpilot/docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE_ARCHITECTURE.md`
- `/Users/abab/Documents/openpilot/docs/task_trajectory/TASK_TRAJECTORY_ID_STRATIFICATION.md`
- `/Users/abab/Documents/openpilot/docs/task_trajectory/TASK_TRAJECTORY_EVENT_ALIGNMENT.md`

---

# 2026-07-05

## 今日摘要（适合汇报）

- 为 LLM-backed tools 增加了有界 timeout 恢复与 fallback；
- 引入 planning surface，缩小 planner 首轮看到的能力面；
- 把 `project_improvement_runtime` 纳入统一 trajectory stream；
- 把分析类任务的只读约束下沉到 planner、guard、command 三层；
- 强化了 command path 语义；
- 真实任务复跑后，瓶颈被重新定位到 synthesis / evidence-grounded planning。

## 已完成切片

### [已完成] LLM 工具超时的可恢复处理

- 背景：某些内部依赖 provider 的工具会超过 executor 的可承受超时窗口。
- 失败现象：工具看起来像普通失败，但本质是 provider timeout，且外层 tool loop 可能过早终止任务。
- 根因判断：timeout 需要被视为可恢复证据，而不是简单终止信号。
- 实现改动：
  - timeout 类失败进入 tool loop 的 recoverable path；
  - 对瞬时 timeout 做一次有界 retry；
  - 对重复 `code_generator` timeout 增加确定性本地 fallback；
  - 支持 `timeout_override`；
  - timeout 证据进入用户可见 summary。
- 验证结果：相关回归主要位于 `/Users/abab/Documents/openpilot/Code/tests/test_execution_tool_planning_executor.py`
- 剩余限制：任务完成判断仍然必须基于 runtime state，而不是无限延长外部预算。

### [已完成] planning surface / deferred disclosure

- 背景：planner 最初看到的是过大的完整工具面。
- 失败现象：prompt 噪声过大，增加模型混乱、延迟与 timeout 风险。
- 根因判断：当前项目采用 `decision_needs -> ToolRouter -> tool execution` 链路，planner 并不需要看到完整工具实现。
- 实现改动：
  - 引入 `/Users/abab/Documents/openpilot/Code/src/autonomous_iteration/planning_surface.py`
  - 引入 `/Users/abab/Documents/openpilot/Code/src/autonomous_iteration/skill_specs.py`
  - 工具能力改为“紧凑 need catalog + capability cards + deferred disclosure”
- 验证结果：首轮 planning prompt 更小、更稳定。
- 剩余限制：synthesis 阶段的空计划问题证明瓶颈已经不是单纯 prompt 过大。

### [已完成] `project_improvement_runtime` 证据集成

- 背景：`project_improvement_runtime` 自身有很多有意义的阶段事件，但此前不在统一 trajectory stream 中。
- 失败现象：其结构化日志和主任务轨迹证据是割裂的。
- 根因判断：项目改进流程没有被纳入统一证据层。
- 实现改动：新增轨迹事件：
  - `pipeline_started`
  - `pipeline_environment_failed`
  - `environment_sync_completed`
  - `environment_repair_attempted`
  - `environment_sync_retried`
  - `pipeline_progress`
  - `project_state_read`
  - `pipeline_finished`
- 验证结果：project improvement runtime 已经能进入同一条 durable task trajectory。
- 剩余限制：还不能自动汇总多次 project-improvement failure 的共同根因。

### [已完成] 分析类任务只读护栏

- 背景：分析型任务必须保持只读，除非用户显式开启 repair task。
- 失败现象：像“梳理 / 分析 / 排查 / 取证”这类任务，仍可能漂移到写文件、patch、删除、bug fix 或 mutating commands。
- 根因判断：只靠 prompt 约束不够，必须下沉到 planner、guard 和 command 三层。
- 实现改动：
  - planner prompt 中加入只读任务说明；
  - `RuntimeGuard` / router 阻断 mutation-capable tools；
  - command 层阻断安装依赖、破坏性文件操作、shell 重定向写入、原地修改等明显 mutation 行为。
- 验证结果：只读分析任务的 mutation 风险显著下降。
- 剩余限制：只读任务仍然需要一种“不修改项目文件但能产生最终答案”的输出路径。

### [已完成] command path 角色化加固

- 背景：命令中的路径之前没有按“角色”拆分。
- 失败现象：executable path、data path、cwd、redirection target 混在一起，导致合法解释器路径也可能被误阻断。
- 根因判断：命令路径治理必须区分不同语义角色。
- 实现改动：明确区分：
  - `command_executable_path`
  - `command_cwd`
  - `command_data_path`
  - `command_redirection_path`
- 验证结果：
  - `/usr/bin/env` 及外部 Python 解释器在 executable 位置不再被误判；
  - 项目数据路径仍然走 project-root grounding；
  - redirection target 成为独立风险类别。
- 剩余限制：还不是完整的 Claude Code 风格命令语义提取器，后续仍可继续细化到 `python` / `pytest` / `cat` / `grep` / `git` 等具体命令。

### [已完成] 真实任务复跑与瓶颈重新定位

- 背景：在证据层、只读约束、planning surface、timeout 与 command path 改进后，重新运行了真实分析任务。
- 任务：

> 请梳理从 CLI 入口到主执行运行时的核心链路，并指出关键模块之间的关系。

- 执行命令：

```bash
cd /Users/abab/Documents/openpilot/Code
PYTHONPATH=src python -m ui.cli run --once "请梳理从 CLI 入口到主执行运行时的核心链路，并指出关键模块之间的关系。"
```

- 结果：任务正常启动、生成 durable trajectory、未被外部 timeout 提前打断，但最终仍然失败。
- 观察到的症状：
  - guessed file target：`setup.py`
  - guessed root：`/openpilot`
  - guessed old layout：`/openpilot/selfdrive/cli.py`
  - synthesis 阶段空 `decision_needs` 或不可路由 `decision_needs`
- 最终失败：

```text
Tool planning requires decomposition after empty decision_needs plan
```

- 结论：瓶颈已经从底层 path / timeout 问题，上移到 **evidence-grounded synthesis reliability**。
- 剩余限制：
  1. 已采集证据还不是唯一可接受目标来源；
  2. planner 更擅长 inspection，不擅长 final answer synthesis；
  3. empty-plan recovery 对分析型 synthesis 任务仍然偏弱。

## 当前遗留问题

- `project_path` 还没有稳定贯穿所有 runtime/planning 入口；
- 空 `decision_needs` 还没有被区分成“规划失败”与“已可总结”两类；
- evidence 仍然更多是“记录下来了”，还没有完全变成硬约束。

## 当日关联文档

- `/Users/abab/Documents/openpilot/docs/task_trajectory/failures/REAL_TASK_FAILURE_ANALYSIS_2026-07-04.md`
- `/Users/abab/Documents/openpilot/docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE_PLAN.md`

---

# 2026-07-07

## 今日摘要（适合汇报）

- 修复了只读分析任务“空 `decision_needs` 被一律视为失败”的问题；
- 打通了 fallback `RuntimeStateMetadata` 对 `project_path` / `cwd` 的继承；
- 增加了只读场景下未 grounding 路径的最小 guard；
- 没有新增重复状态层，仍然复用 `RuntimeStateMetadata`；
- 定向测试 94 通过，全量测试 503 通过。

## 已完成切片

### [已完成] 只读 synthesis、项目上下文传递与最小路径守卫加固

- 背景：真实任务复跑后已经明确，当前瓶颈是只读分析的 synthesis 阶段与证据约束不足。
- 失败现象：
  - 只读仓库分析任务可能已经有足够证据，但 LLM 返回空 `decision_needs`；
  - tool-planning executor 把所有空计划统一视为 planning failure；
  - fallback 创建的 `RuntimeStateMetadata` 不能稳定继承 `project_path` / `cwd`；
  - 在没有 project context 或 prior path evidence 的情况下，系统仍可能继续路由 `setup.py` 这种模型提出的相对路径。
- 根因判断：
  1. “空 `decision_needs`”缺少语义分流：既可能是 planning gap，也可能是“已经有证据，可以直接总结”；
  2. `project_path` / `cwd` 没有稳定贯穿所有 runtime / tool planning 入口；
  3. 只读路径证据虽然被记录了，但还没有足够强地变成 guard。
- 实现改动：
  - 在 `ToolPlanningTaskExecutor` 中增加只读空计划 synthesis 完成逻辑；
  - 当 fallback runtime state 被创建时，从 task context 注入 `project_path` / `cwd`；
  - 在 `RuntimeGuard` 中加入一条最小策略：如果没有 `project_path` / `cwd` 或 prior path evidence，则阻断未 grounding 的只读 `file_read`。
- 实现原则：
  - **没有新增 `RuntimeSessionState`**；
  - 继续复用 `RuntimeStateMetadata` 作为 runtime fact source；
  - 对 mutation/actionable task 仍保持严格失败语义，不做过宽放行。
- 验证覆盖：
  - 只读分析 + 已有 runtime evidence + 空 `decision_needs` => 进入 synthesis，而不是失败；
  - 只读分析 + 无证据 + 空 `decision_needs` => 仍失败；
  - fallback `RuntimeStateMetadata` 继承 `project_path` 并记录为 fact / candidate；
  - 只读 `file_read` 在无 `project_path` 或 prior path evidence 时被阻断。
- 定向测试：

```text
PYTHONPATH=Code/src pytest -q \
  Code/tests/test_execution_tool_planning_executor.py \
  Code/tests/test_agent_runtime_controller.py \
  Code/tests/test_project_path_runtime_integration.py \
  Code/tests/test_path_boundary_validation.py
```

- 定向结果：

```text
94 passed
```

- 全量回归：

```text
PYTHONPATH=Code/src pytest -q Code/tests
503 passed
```

- 这次明确解决了什么：
  - 只读空计划不再一律报 `Tool planning requires decomposition after empty decision_needs plan`；
  - fallback runtime state 不再轻易丢失项目上下文；
  - 只读场景下裸相对路径读取至少有了一层最小阻断。
- 剩余限制：
  - `runtime_mode` 仍然通过 `runtime_mode:read_only_analysis` assumption marker 表达，不是一等 metadata field；
  - 当前 guard 仍是最小切片，还没有扩展成“所有 read tool / 所有 workflow mode”的 evidence-backed path policy；
  - `read_only_repository_analysis` 还没有正式进入 `TaskRouteMetadata` 作为独立 route；
  - 当前 trajectory data 仍不适合作 BERT / SVM classifier 的训练标签。

## 当前遗留问题

- route contract 仍然太粗，绝大多数任务仍直接落入 `autonomous_iteration`；
- `runtime_mode` 语义还没有做成更稳的一等字段；
- evidence 记录与 evidence 强约束之间仍有差距；
- BTX / 二级行为路由还没有进入实现阶段。

## 下一步计划

1. 把 `read_only_repository_analysis` 正式纳入 `TaskRouteMetadata`；
2. 扩展 path grounding guard 到 `multi_file_reader` 及更多 read tool；
3. 评估是否把 `runtime_mode` 升级成一等 metadata 字段；
4. 在更稳定的成功轨迹基础上，再考虑 classifier / BTX router 的训练数据问题。

## 当日关联文档

- `/Users/abab/Documents/openpilot/docs/task_trajectory/failures/REAL_TASK_FAILURE_ANALYSIS_2026-07-04.md`
- `/Users/abab/Documents/openpilot/Thought.md`
- `/Users/abab/Documents/openpilot/THOUGHT_ARCHITECTURE.md`

