# Subagent 实施计划（2026-09-10）

> 调研对象：Claude Code subagent 完整机制、OpenAI Agents SDK / LangGraph / CrewAI / AutoGen、多 agent 生产实践。
> 一句话定位：**cc 的 subagent 是"看不见的过程"（父级无法审计中间态），op0 的 subagent 是"看得见的工单"（每一跳入账、副作用有 receipt、失败有三态结论）——多 agent 化不改变 op0 的信任语义，而是把它扩展到执行域边界。**

## 一、调研发现（五条硬结论）

1. **cc 的机制已收敛为事实标准**：subagent = 独立上下文 + frontmatter 定义（name/description/tools/model/permissionMode）+ 只返回最终 summary + 可并行 + 可后台。嵌套深度限制 5 层；`isolation: worktree` 给并行写文件提供文件级隔离。
2. **生产环境最重要的一条洞察**（多框架实践共识）：*"大多数 agent 失败是编排与上下文传递问题，不是模型问题"*——解法是**结构化 handoff schema**（summary/citations/open_questions/confidence），不是自由文本传递。
3. **经典失败模式："lost child task"**（层级委派中子任务完成信号永远没回到父级）——结果返回协议必须是显式契约，不能靠约定。
4. **成本红线**：Anthropic 自家研究系统回顾——multi-agent 约 **15× token** 消耗；小任务（委派描述比直接做还贵）不该用 subagent。cc 的回答是 contract 里写清楚"何时不用"。
5. **HITL 审批已成为各框架一等公民**——这恰好是 op0 的强项：审批卡 + typed admission 我们已经有了，subagent 只需要把审批路由到正确的执行域。

## 二、op0 的差异化设计：工单，不是影子进程

| 维度 | cc subagent | op0 subagent |
|---|---|---|
| 中间过程 | 父级不可见（隔离即黑箱） | 子 run 有自己的完整账本（trajectory + receipts） |
| 失败结论 | 无（异常或空返回） | 子 run 的 closure 三态（success/indeterminate/failed） |
| 副作用 | 混在父会话权限里 | 子 run 自己的 admission gate，审批卡走同一 TUI |
| 父子关系 | 无记录 | 父账本记 `task_spawned`/`task_finished` 事件（含子 run_id） |
| 崩溃 | 孤儿进程 | 父级对账发现子 run 悬案 → 三态呈现（"lost child task" 的结构性防御） |

核心复用：子 run 就是**一个完整的 op0 栈实例**（Session + ReceiptStore + bridge + engine + 沙箱 + skill 索引）——我们在 chaos harness 里已经在反复构造这个组合，subagent 只是把它们组装成可派发的单元。

## 三、六条设计基石（实施期红线）

1. **子 run = 完整治理栈**：独立 ledger/receipt/admission/contract，绝不共享父的账本（单一权威原则：两个 run 两本账，用指针关联）；
2. **delegation 是账本事件**：`task_spawned`（父，含子 run_id + 任务摘要）、`task_finished`（父，含三态结论 + 摘要）——审计链跨执行域连续；
3. **结构化返回**：子 run 返回 {status 三态, summary, receipts 摘要}，不是裸文本（吸收 handoff schema 洞察）；
4. **审批走同一门**：子 run 的 write/bash 审批卡进入同一个 TUI gate（前台模式），人审批的是"子代理的这个副作用"；
5. **depth=1 起步**：不嵌套（15× token + 调试成本），contract 明示"上下文隔离收益 < 委派成本时不用"；
6. **串行起步**：并行 + worktree 隔离是 Phase 2（cc 也是 worktree 才敢并行写）。

## 三点五、Metadata 结合（老板指正，2026-09-10）

结构化 handoff 本质是 metadata 问题：cc 生态在用非类型化约定重新发明旧架构的 typed contract。op0 至今的事件类型是裸字符串、payload 无 schema、消费方全靠防御式提取（compaction 的 _tool_result_text、usage 字段坑、E1 多形态兼容都是同一税源）。修订：**subagent 成为 metadata 维度回归的第一个客户**。

- **T0 CONTRACT_REGISTRY（新增，~80 行）**：每个事件类型的 payload schema（字段/类型/必选/producer）集中注册；record() 按 schema 校验、fail-closed（不合规拒绝入账）；现有 7 类事件 schema 一次性补齐，消费方防御式提取退役为按契约读；生产者/消费者关系入注册表（Semantic Kernel 的最小对应物）。
- **T2/T3 修订**：task_spawned/task_finished 与子→父返回结构按注册表第一个 Domain Contract（TaskHandoff）定义，字段吸收 cc handoff envelope（summary/citations/open_questions/confidence）。
- 后续客户：skill frontmatter、approval 语义均可进注册表。红线：不复活 6,390 行的全家桶——注册表只登记"真实存在生产者和消费者的事实"。

## 四、Phase 1 任务分解（核心闭环）

- T0 **CONTRACT_REGISTRY**：事件类型 payload schema 注册 + record 校验（fail-closed）+ 现有 7 类事件补齐（见三点五节）；
- T1 `openpilot_task` 工具：bridge handler（参数 task/prompt）→ 构造子 run 栈（复用 chaos 的组装路径）→ 同步执行到 closure；
- T2 父账本 delegation 事件（`task_spawned`/`task_finished`）+ 子 run 账本落 `.openpilot/runs/<child_id>.jsonl`（与父账本同目录、指针关联）；
- T3 结构化返回组装（closure 三态 + summary + receipt 计数）→ 以 tool_result 形态回父模型；
- T4 契约扩展：`openpilot_task` 工具契约行 + "何时不用 subagent" 指引（成本红线进契约）；
- T5 崩溃语义：子 run 崩溃 → 父级 `task_finished{status: indeterminate}` + 子账本 reconcile 可查（chaos 新场景：杀子进程验证无孤儿工单）；
- T6 测试 + 真实冒烟（派一个只读研究子任务，验证两本账 + delegation 链）。

预估净增 ~250 行（含 T0 注册表）→ 预算 3,880（报备）。

## 五、Phase 2 / 3（后续）

- Phase 2：并行派发 + worktree 文件隔离（cc 验证过的路径）；
- Phase 3：后台模式（已授权限策略）、嵌套深度限制、skill 的 `context: fork` 字段接通。

## 六、明确不做（边界）

- 不做 agent 间互发消息（cc 明确：那是 agent teams，协调成本另一档）；
- 不做共享内存/共享状态（两个 run 两本账，指针关联）；
- 不做身份/招聘/权限树（MAPLE 血缘边界：单 agent 化移植只取执行域隔离与交接语义）；
- 不做异步派发（同步阻塞到 closure，异步是 Phase 3）。

## 七、验证路径

1. 单测：子 run 账本独立性、delegation 事件完整、结构化返回、子 skill 索引独立计算；
2. chaos 新场景 `subagent`：正常完成（两本账+事件链）/ 子进程 kill（父收 indeterminate、无孤儿）/ 子 run 越权（子 admission 拦截）；
3. 真实冒烟：派只读研究子任务 → 父账本含 task_spawned/task_finished → 父模型收到结构化摘要。


## Phase 2：并行 + worktree（2026-09-10 设计，validation 闭环之后）

调研基础：cc 的 `isolation: worktree`（临时 worktree、无改动自动清理、有改动保留供审查）与 /batch 的 per-agent worktree 模式——git worktree 本身 20 年成熟度，无需新搜索。

**并发安全前提核查**：AdmissionRegistry 无锁（_counter 非原子、dict 并发竞态）→ 方案：**全局审批锁**（module 级 threading.Lock，粗粒度覆盖 propose→gate UI→approve 全程——审批本就串行人处理，排队正确且最小改动）；per-child registry 与 authorizer 参数化留 Phase 3。

**设计**：
- 新工具 `openpilot_tasks`（复数）：`{tasks: [{task, validate?, worktree?}]}` 一次派发 N 个（≤4），ThreadPoolExecutor 并发，聚合 TaskHandoff 数组返回；单发 `openpilot_task` 保留；
- worktree 生命周期：`worktree: true` → `git worktree add -b op0/task-<short>` 于系统临时目录（子 run 的 scoped_roots 即 worktree，沙箱写白名单自动覆盖）；完成后 `git status --porcelain` 判定——干净 → remove+清分支；有改动 → **保留 + 分支路径进 TaskHandoff**（merge 是人的决定，不自动）；
- registry 客户：task_spawned/task_finished 加 optional `worktree` 字段；
- 限制：depth=1 保持、单次 ≤4 并行（15× token 成本红线进契约）、审批串行排队。

任务：T1 registry 2 字段 → T2 bridge openpilot_tasks handler → T3 cli 并发 spawner + worktree + 审批锁 → T4 TS + 契约 → T5 E2E（并行聚合 + worktree 生命周期）→ T6 冒烟 + 预算 + 提交。预估净增 ~150 行。
