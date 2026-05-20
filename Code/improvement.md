# OpenPilot Improvement Plan from Hermes-Agent

## 背景与对照

OpenPilot 目前更偏向单机 CLI + Agent/Tool 执行系统：已有 `IntelligentAutopilot` 执行链、`ToolRegistry`、`ui.commands`、JSONL `MemoryStore`、结构化日志、项目评估和自主迭代能力。它的优势是核心路径相对集中，适合围绕“任务分解、工具执行、项目改进”继续增强。

Hermes-Agent 更像一个长期运行的 agent runtime：它强调跨会话记忆、跨平台入口、工具集、技能系统、插件、定时任务、诊断、权限审批、模型/配置 profile、运行环境隔离和会话检索。它的很多能力并不需要被 OpenPilot 全量复制，但很适合作为 OpenPilot 后续工程化、可扩展性和长期自主运行能力的参考。

本计划建议按收益和实现成本分批吸收 Hermes 的设计，而不是直接搬运实现。优先改动应围绕 OpenPilot 已有边界展开：先强化命令、工具、权限、诊断，再扩展 skills、session store、profile、插件和调度能力。

## 优先级路线图

| Priority | 主题 | 主要收益 | 建议阶段 |
| --- | --- | --- | --- |
| P0 | 统一 Slash Command 注册体系 | 减少 CLI help、autocomplete、dispatch 漂移 | 第 1 批 |
| P0 | Toolset / Tool Profile 机制 | 控制工具暴露面，提高安全性和任务适配度 | 第 1 批 |
| P0 | 权限审批与风险闸门增强 | 降低文件写入、shell、网络和代码执行风险 | 第 1 批 |
| P1 | Skills / Procedural Memory 系统 | 把成功经验沉淀为可复用操作知识 | 第 2 批 |
| P1 | 会话持久化与全文检索 | 支持跨会话恢复、回溯和长期上下文 | 第 2 批 |
| P1 | Doctor / Diagnostics | 降低环境配置和依赖问题排查成本 | 第 1 批 |
| P1 | 配置 Profile 与模型切换 | 支持不同任务使用不同 provider/model 配置 | 第 3 批 |
| P1 | 结构化日志与可观测性升级 | 让失败分析、成本分析、工具性能分析可查询 | 第 2 批 |
| P2 | Cron / Scheduled Automation | 支持无人值守的周期性项目维护 | 第 3 批 |
| P2 | Plugin / Extension 机制 | 为工具、provider、memory backend 留扩展口 | 第 3 批 |
| P2 | MCP 集成 | 接入外部工具服务器和生态能力 | 第 3 批 |
| P2 | 多 Agent 委派 / Kanban 工作流 | 支持复杂任务并行和结构化交接 | 第 4 批 |
| P3 | 多入口 Gateway | 为 Telegram、Slack、Webhook 等入口预留架构 | 第 4 批 |
| P3 | ACP / Editor Integration | 支持编辑器侧 diff approval 和上下文同步 | 第 4 批 |
| P3 | Trajectory / Research Data | 为回放、评估和训练数据沉淀任务轨迹 | 第 4 批 |

## 详细改进计划

### P0：统一 Slash Command 注册体系

**Hermes 借鉴点**

Hermes 使用中心化 `CommandDef` registry，将命令名称、alias、分类、参数提示、CLI/Gateway 可见性、help、autocomplete 和 dispatch 统一到同一份元数据中。这样新增命令或 alias 时，不需要同时修改多个分散位置。

**OpenPilot 适配建议**

- 基于当前 `src/ui/commands.py` 扩展 command metadata：`canonical_name`、`aliases`、`category`、`args_hint`、`visibility`、`requires_args`、`handler_key`。
- 让 `/help`、prompt-toolkit autocomplete、命令合法性检查和 dispatch 都从 registry 读取。
- 先只覆盖 CLI；后续如果加入 gateway，保留 `visibility` 字段即可扩展。
- 将当前硬编码处理的 `/help`、`/config`、`/clear`、`/exit` 逐步迁移到统一 dispatch。

**收益**

- 降低命令新增成本。
- 避免 help 文案、alias 和实际 handler 不一致。
- 为后续 `/skills`、`/tools`、`/sessions`、`/doctor`、`/logs` 等命令打基础。

**风险与注意**

- 不要一次性重写整个 CLI loop；先保留现有交互逻辑，只把命令解析入口集中。
- 需要补测试覆盖 alias resolve、help 输出、autocomplete 名称列表和未知命令处理。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P0：Toolset / Tool Profile 机制

**Hermes 借鉴点**

Hermes 将工具按场景组织成 toolset，例如 file、web、browser、memory、skills、cron、delegation。工具暴露给模型前会经过 enabled/disabled toolsets 解析，插件工具也必须进入 toolset 路径，不绕过权限边界。

**OpenPilot 适配建议**

- 在现有 `ToolRegistry` 之上新增 `ToolsetDefinition`，字段包括 `name`、`description`、`tools`、`includes`、`requirements`。
- 提供默认工具集：
  - `file`：file_reader、multi_file_reader、file_writer、readme_tool。
  - `code`：code_generator、code_reviewer、code_executor。
  - `web`：web_searcher。
  - `memory`：memory_context。
  - `project`：project improvement 相关工具。
  - `safe-default`：只包含低风险读操作和 LLM summarizer。
- 支持按 session、task classification、CLI 参数或配置文件启用/禁用工具集。
- 在 LLM tool planning prompt 中只展示当前有效 toolset 内工具。

**收益**

- 降低模型误用高风险工具的概率。
- 不同任务可以使用更小、更清晰的工具面。
- 为 cron、plugins、MCP、gateway 等无人值守或外部入口提供安全边界。

**风险与注意**

- 需要处理工具依赖关系，例如 code generation 后通常需要 file_writer。
- 默认 toolset 不宜过窄，否则会影响当前自动执行能力。
- 需要提供诊断输出，说明某个工具为什么不可用。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P0：权限审批与风险闸门增强

**Hermes 借鉴点**

Hermes 对危险命令、编辑审批、平台来源、cron 自动运行等场景有更细的审批语义。它不是只看工具静态权限，而是结合命令内容、调用来源、运行模式和用户授权来决定是否允许执行。

**OpenPilot 适配建议**

- 保留 `PermissionLevel`，但新增运行时 `ApprovalDecision`：
  - `allow_once`
  - `allow_session`
  - `deny`
  - `require_user_confirmation`
- 对以下操作建立单独 policy：
  - 文件写入、覆盖、删除。
  - shell 执行。
  - 代码执行。
  - 网络请求或 web search。
  - 项目目录外路径访问。
- 将 `auto_approve` 从布尔值升级为 policy 配置，例如 `safe`、`balanced`、`yolo`、`manual`。
- 在日志中记录 approval source、decision、reason、tool_name、path/command summary。

**收益**

- 对自主执行更安全，尤其是项目目录外写入和 shell 命令。
- 为后续 cron/gateway/MCP 接入打安全基础。
- 用户可以清楚知道 agent 为什么被允许或被阻止。

**风险与注意**

- 审批过严会破坏当前“自动完成任务”的体验。
- 需要在 CLI 中设计简洁确认交互，避免频繁打断。
- 不要在日志中保存 API key、完整环境变量或敏感文件内容。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P1：Skills / Procedural Memory 系统

**Hermes 借鉴点**

Hermes 使用 `SKILL.md` 保存过程性知识，并允许 agent 在任务中加载、使用、维护和创建技能。技能不是普通记忆，而是可执行风格的任务指导，例如调试流程、代码审查流程、特定工具使用方法。

**OpenPilot 适配建议**

- 引入目录约定：`skills/<category>/<skill>/SKILL.md`。
- 定义 `Skill` metadata：`name`、`category`、`path`、`description`、`usage_count`、`last_used`。
- 新增命令：
  - `/skills list`
  - `/skills view <name>`
  - `/skills reload`
  - `/skills use <name> <task>`
- 在 task decomposition 或 tool planning 前，根据任务类型检索并注入相关 skill。
- 后续支持从成功项目迭代中生成候选 skill，但先要求人工确认后落盘。

**收益**

- 把重复成功经验沉淀下来，减少每次重新推理。
- 可作为 OpenPilot 自我改进闭环的落地载体。
- 便于项目级或团队级定制 agent 行为。

**风险与注意**

- Skill 内容会影响模型行为，需要 prompt-injection 扫描和来源标记。
- 自动生成 skill 应避免过度泛化或保存错误经验。
- 需要限制一次加载的 skill 数量和长度，防止上下文膨胀。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P1：会话持久化与全文检索

**Hermes 借鉴点**

Hermes 使用 SQLite + FTS5 存储会话消息，支持跨会话搜索、恢复、摘要和上下文回溯。相比纯 JSONL，SQLite 更适合查询、索引、分页和并发读。

**OpenPilot 适配建议**

- 新增 `SessionStore`，优先使用 SQLite。
- 保存内容包括：
  - user/assistant 消息。
  - tool call 和 tool result summary。
  - task graph 状态。
  - project evaluation 和 iteration result。
  - session title、created_at、updated_at、goal。
- 新增命令：
  - `/sessions`
  - `/resume <session_id>`
  - `/search <query>`
  - `/history`
- 中文搜索可先使用普通 FTS5；后续再评估 trigram 或额外 tokenizer。

**收益**

- 用户可以恢复中断任务。
- Agent 可以搜索过去的项目经验。
- Debug 和审计更容易。

**风险与注意**

- 需要定义日志与 session store 的边界：日志偏审计，session store 偏交互状态。
- 工具输出可能很大，应保存摘要和 artifact 引用，不默认保存完整内容。
- 需要考虑 schema migration。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P1：Doctor / Diagnostics

**Hermes 借鉴点**

Hermes 的 `doctor` 会检查 provider、依赖、平台、工具、配置和常见系统问题，并给出修复建议。它降低了 agent 系统最常见的“环境不对但错误难懂”的成本。

**OpenPilot 适配建议**

- 将现有 `openpilot config check` 扩展为 `openpilot doctor`。
- 检查项包括：
  - Python 版本是否符合 `>=3.11`。
  - 关键依赖是否可 import。
  - LLM 配置是否完整，base URL 是否可解析。
  - 当前是否误用项目内 venv 或缺少 socksio。
  - built-in tools 是否注册成功。
  - memory store、logs 目录是否可读写。
  - web search、shell、code execution 等工具的运行前置条件。
- 输出分为 OK、Warning、Fail，并给出建议命令或配置项。

**收益**

- 降低新用户启动失败率。
- 对开发者调试也有帮助。
- 可以作为 CI smoke check 的基础。

**风险与注意**

- 网络连通性检查要有短超时。
- 不要打印完整 API key。
- provider-specific 检查应做成可扩展，不要把核心 doctor 写得过重。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P1：配置 Profile 与模型切换

**Hermes 借鉴点**

Hermes 支持不同 profile、provider、model 和运行配置，用户可以按场景切换。对 agent 系统来说，coding、research、low-cost、high-reasoning 等 profile 很常见。

**OpenPilot 适配建议**

- 引入 profile-aware config：
  - `default`
  - `coding`
  - `research`
  - `local`
- 保留 `.env` 作为 secrets 来源，但将非敏感设置迁移到配置文件，例如 model、base_url、timeout、toolsets、approval policy。
- 新增命令：
  - `/model`
  - `/profile`
  - `/config set`
  - `/config show`
- 在 `LLMSettings` 之上增加 resolver，统一处理 env、profile config、CLI override 的优先级。

**收益**

- 同一项目可快速切换模型和策略。
- 降低频繁改 `.env` 的成本。
- 为多 agent worker 使用不同 profile 打基础。

**风险与注意**

- 配置优先级必须明确，避免“为什么没生效”的困惑。
- secrets 仍应只放 `.env` 或系统环境，不写入普通 YAML。
- 需要兼容当前 `OPENPILOT_LLM_*` 环境变量。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P1：结构化日志与可观测性升级

**Hermes 借鉴点**

Hermes 有多类日志、usage、insights、tool progress 和平台状态输出。OpenPilot 已有 JSONL logger，可以在不重写日志系统的情况下增强索引和统计。

**OpenPilot 适配建议**

- 保留 JSONL，但补充字段：
  - `session_id`
  - `task_id`
  - `tool_name`
  - `duration_ms`
  - `token_usage`
  - `estimated_cost`
  - `failure_category`
  - `approval_decision`
- 新增命令：
  - `/logs`
  - `/usage`
  - `/insights`
- 为 tool executor 和 LLM client 增加统一 telemetry hook。
- 将近期错误 buffer 和完整日志文件关联到 session。

**收益**

- 更容易定位失败任务和慢工具。
- 可以量化模型成本和重试成本。
- 为 project improvement loop 提供真实反馈数据。

**风险与注意**

- 日志字段增加不能暴露 secrets。
- 大型 tool output 只保存摘要。
- 需要控制日志文件增长和索引成本。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P2：Cron / Scheduled Automation

**Hermes 借鉴点**

Hermes 支持自然语言 cron job，并可投递到不同平台。它还对 cron 自动执行做了 toolset 限制、运行锁、profile 上下文、prompt-injection 扫描和结果保存。

**OpenPilot 适配建议**

- 新增本地定时任务能力，先只支持 CLI 管理和本机运行。
- 任务类型示例：
  - 每日项目健康检查。
  - 每周 README/文档更新建议。
  - 定期测试或静态检查摘要。
  - 定期清理日志和 memory 体积报告。
- 每个 cron job 绑定：
  - prompt。
  - schedule。
  - enabled toolsets。
  - approval policy。
  - output target。
- 自动运行默认使用受限 toolset，禁止高风险写入，除非用户明确开启。

**收益**

- OpenPilot 可以从“被动执行任务”走向“持续维护项目”。
- 很适合项目巡检、质量报告、依赖检查。

**风险与注意**

- 无人值守执行风险高，必须先完成 toolset 和 approval policy。
- cron prompt 需要扫描注入风险，尤其是加载 skills 后。
- 需要防止多个 tick 并发执行同一 job。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P2：Plugin / Extension 机制

**Hermes 借鉴点**

Hermes 把 memory backend、model provider、web provider、platform、observability、dashboard 等能力插件化。插件必须走注册路径，不能绕过 toolset 和权限体系。

**OpenPilot 适配建议**

- 定义最小插件接口：
  - 注册工具。
  - 注册命令。
  - 注册 provider。
  - 注册 memory backend。
- 先支持本地插件目录，例如 `plugins/<name>/plugin.py` 或 `plugins/<name>/plugin.json`。
- 插件加载必须有诊断输出：已加载、跳过、失败原因。
- 插件工具必须声明 capabilities、permission_level 和所属 toolset。

**收益**

- 避免核心仓库无限膨胀。
- 方便实验性能力独立迭代。
- 为 MCP、provider、memory 扩展留统一入口。

**风险与注意**

- 插件是代码执行入口，默认不应加载不可信目录。
- 需要版本兼容策略。
- 本阶段不建议做 marketplace，只做本地扩展机制。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P2：MCP 集成

**Hermes 借鉴点**

Hermes 使用 MCP 扩展外部工具能力，但同时关注 lazy discovery、超时、失败隔离和配置诊断，避免慢 MCP server 阻塞主循环。

**OpenPilot 适配建议**

- 新增 MCP server 配置段，支持 stdio/http server。
- MCP 工具发现应独立超时，失败不影响核心启动。
- MCP tools 注册进 `ToolRegistry`，并必须归属 toolset。
- 新增命令：
  - `/reload-mcp`
  - `/mcp status`
- 为 MCP tool call 增加独立日志和错误分类。

**收益**

- 快速接入浏览器、GitHub、文档、数据库等生态工具。
- 减少 OpenPilot 自己维护所有工具的压力。

**风险与注意**

- MCP server 质量不一，需要 schema 校验。
- 外部工具权限必须受 OpenPilot approval policy 约束。
- 需要避免启动时同步等待所有 MCP server。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P2：多 Agent 委派 / Kanban 工作流

**Hermes 借鉴点**

Hermes 支持委派子 agent 和 Kanban worker，通过任务状态、heartbeat、comment、block、complete 等动作协调复杂并行工作。

**OpenPilot 适配建议**

- 在当前 task decomposition 之上增加 worker lane 概念。
- 每个 worker 拥有：
  - 独立上下文。
  - 明确任务边界。
  - 工具集限制。
  - 状态更新。
  - heartbeat。
  - block/comment/complete。
- 先支持本进程内并发 worker，不急于跨进程或跨机器。
- 对文件写入任务要求 disjoint ownership，避免并发冲突。

**收益**

- 对大型项目改造、测试修复、文档梳理等任务更有效。
- 任务进度更透明。
- 可与 session store 和 telemetry 结合做回放分析。

**风险与注意**

- 并发写文件容易冲突，必须引入 ownership 和审批边界。
- 需要控制 worker 数量和总 token budget。
- 当前 `AgentOrchestrator(max_concurrent_tasks=3)` 可作为起点，但需要更明确的 worker contract。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P3：多入口 Gateway

**Hermes 借鉴点**

Hermes 可通过 CLI、Telegram、Discord、Slack、WhatsApp、Signal 等入口与同一个 agent runtime 对话，并保持跨平台会话连续性。

**OpenPilot 适配建议**

- 短期只设计 runtime/gateway 边界：
  - message input。
  - command dispatch。
  - session identity。
  - approval callback。
  - output delivery。
- 先实现 webhook 或 local HTTP gateway，再考虑具体平台。
- 所有 gateway 命令应复用统一 `CommandDef` registry。

**收益**

- 让 OpenPilot 可以远程触发项目维护任务。
- 与 cron、session store、approval policy 组合后价值更高。

**风险与注意**

- 外部入口会放大权限风险。
- 必须先有用户身份、allowlist 和 approval policy。
- 平台适配不应污染核心 agent runtime。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P3：ACP / Editor Integration

**Hermes 借鉴点**

Hermes 有 ACP adapter，可与编辑器/IDE 集成，让编辑审批、权限请求和 session context 在开发环境中流转。

**OpenPilot 适配建议**

- 远期支持编辑器侧能力：
  - diff approval。
  - 当前文件/选区上下文。
  - 任务状态展示。
  - 编辑器内恢复 session。
- 文件写入和 patch 操作可以先暴露 approval hook，未来再接 ACP。

**收益**

- 用户能在 IDE 中审核 agent 修改。
- 降低自动写文件的不确定感。
- 与 OpenPilot 的项目改进定位高度匹配。

**风险与注意**

- ACP 是额外协议依赖，不应成为核心 CLI 的启动前置。
- 需要保证没有编辑器集成时 CLI 仍然完整可用。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### P3：Trajectory / Research Data

**Hermes 借鉴点**

Hermes 保存 trajectory 并支持压缩，用于训练和研究下一代 tool-calling agent。OpenPilot 的自主迭代和项目改进链路天然适合沉淀这类数据。

**OpenPilot 适配建议**

- 保存任务轨迹：
  - goal。
  - decomposition。
  - tool plan。
  - tool calls。
  - failures。
  - repairs。
  - final evaluation。
- 提供 trajectory export，用于回放和分析。
- 对敏感路径、secrets、完整文件内容做脱敏。

**收益**

- 支持 agent 行为评估和回归测试。
- 为未来训练、prompt 改进、工具选择优化提供数据。
- 能更清楚地复盘自主迭代为什么成功或失败。

**风险与注意**

- 轨迹可能包含用户代码和敏感信息。
- 默认应本地保存，不自动上传。
- 需要提供清理和导出控制。

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

## 建议落地顺序

### 第 1 批：先补核心控制面

- 统一 Slash Command 注册体系。
- Toolset / Tool Profile 机制。
- 权限审批与风险闸门增强。
- Doctor / Diagnostics。

这批改动优先级最高，因为它们会成为后续 skills、cron、plugin、MCP、gateway 的基础安全和可维护性边界。

### 第 2 批：补长期记忆和可观测性

- Skills / Procedural Memory 系统。
- 会话持久化与全文检索。
- 结构化日志与可观测性升级。

这批改动让 OpenPilot 不只是一次性执行任务，而是能够积累经验、恢复上下文、分析历史行为。

### 第 3 批：扩展运行时生态

- 配置 Profile 与模型切换。
- Plugin / Extension 机制。
- MCP 集成。
- Cron / Scheduled Automation。

这批改动让 OpenPilot 具备更强扩展性，并开始支持持续运行和外部生态接入。

### 第 4 批：走向多入口和多 agent 协作

- 多 Agent 委派 / Kanban 工作流。
- 多入口 Gateway。
- ACP / Editor Integration。
- Trajectory / Research Data。

这批改动适合在核心控制面、长期记忆和安全策略稳定后推进。

## Interfaces To Mention

### `CommandDef`

建议字段：

- `name`
- `canonical_name`
- `aliases`
- `category`
- `description`
- `args_hint`
- `visibility`
- `requires_args`
- `handler_key`

用途：统一 CLI help、autocomplete、dispatch、gateway command exposure。

### `ToolsetDefinition`

建议字段：

- `name`
- `description`
- `tools`
- `includes`
- `requirements`
- `default_enabled`

用途：控制工具暴露范围，支持 session/task/profile 级别启用和禁用。

### `Skill`

建议字段：

- `name`
- `category`
- `path`
- `description`
- `usage_count`
- `last_used`
- `source`

用途：加载过程性知识，并为未来自动沉淀成功经验做准备。

### `SessionStore`

建议方法：

- `append_message(session_id, role, content, metadata)`
- `append_tool_call(session_id, tool_name, input_summary, output_summary, status)`
- `search(query, limit)`
- `resume(session_id)`
- `list_sessions(limit)`

用途：持久化会话、工具调用、任务图和项目迭代结果。

### `ApprovalDecision`

建议取值：

- `allow_once`
- `allow_session`
- `deny`
- `require_user_confirmation`

用途：将静态 `PermissionLevel` 升级为结合工具、路径、命令、任务来源和运行模式的运行时决策。

## Test Plan

- 文档检查：
  - 确认 `improvement.md` 包含所有优先级分组：P0、P1、P2、P3。
  - 确认每个改进主题都有统一 `Comments` 占位。
  - 确认文档包含背景、路线图、详细计划、落地顺序和接口方向。
- Markdown 预览：
  - 检查标题层级是否清晰。
  - 检查表格是否能正确渲染。
  - 检查 comments 区是否方便后续填写。
- 本次仅写文档，不运行 Python 单元测试。
- 后续进入代码实现时，建议补充以下测试：
  - command registry：alias resolve、help 输出、unknown command。
  - toolset resolution：includes、disabled override、missing dependency。
  - session store：append、resume、FTS search、migration。
  - approval policy：不同工具、路径、命令、运行模式下的决策。
  - doctor：缺失依赖、缺失 API key、不可写目录、工具不可用。

## Comments 汇总区

### 全局决策记录

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### 当前推荐默认选择

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

### 暂缓或不做的能力

**Comments**
- Owner:
- Priority:
- Decision:
- Notes:

## Assumptions

- 使用中文撰写，标题保留少量英文术语便于对应代码概念。
- `hermes-agent` 只作为架构参考，不直接复制代码。
- OpenPilot 的短期重点仍是项目执行与自主改进，不急于变成完整多平台聊天系统。
- 每个改进项都保留 comments 区，方便后续补 owner、优先级调整和决策记录。
