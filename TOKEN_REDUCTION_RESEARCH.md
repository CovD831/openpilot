# op0 Token 节省方案：外部调研 × 本地实验数据

> 2026-09-09。调研对象：rtk-ai/rtk、cytostack/openwolf、thedotmack/claude-mem、社区交接文档经验；
> 结合 op0 本地 A/B 实验数据（E1 生效后 usage 增长形态、折叠负收益结论）。

## 0. 本地实验数据（方案的出发点）

- E1 入口裁切（>8k 存档+指针）已拦截 coding 会话最大的膨胀源（工具输出大块）；
- 折叠（投影重启）在短/中会话**全部负收益**（+32.7% ~ +321%），因为 E1 之后折叠区已无可省大块，每次折叠却要付契约重发 + 投影重放 + cache 失效三笔税；
- E1 生效后 usage 的剩余增长源（按预估占比）：**assistant 回复文本、中等 tool_result（1k–8k）、重复读取同一文件、重复犯同样的错**。
- 结论：下一步的收益不在"更激进的折叠"，而在 **不生成浪费 + 不重复劳动 + 中等输出的语义压缩**。以下方案按 ROI 排序。

## 1. 调研发现：各项目核心机制

### rtk（Rust Token Killer，61k★，Apache-2.0）
CLI 代理，命令输出进入上下文前做**按命令类型的语义压缩**，四策略：智能过滤 / 同类分组 / 截断 / 格式规整。
- 实测（2900+ 真实命令）：cargo test 91.8%、git status 80.8%、find 78.3%、grep 49.5%，平均 89%；
- 30 分钟 Claude Code 会话 118k → 23.9k tokens（-80%）；
- 关键原则：**错误信息、测试失败、diff 内容完整保留，只压 AI 不需要的噪音**（通过项一行计数，失败项全保）；
- hook 自动改写 `git status` → `rtk git status`，模型无感知；<10ms 开销。
- **与 op0 的对照**：我们的 E1 是"存全文 + 指针"（保留一切但换空间），rtk 是"语义过滤"（根本不生成）。rtk 的收益区恰是 E1 线下的中等输出（1k–8k）——我们 E1 实验里 usage 仍缓慢增长的主要来源。

### openwolf（Claude Code 中间件，AGPL-3.0）
6 个生命周期 hook，纯 Node 文件 I/O，零 AI 调用。实测单项目 -80%，20 项目平均 -65.8%。
- **anatomy.md 项目地图**：每文件一行描述 + token 估算；模型读文件**前**先看到"这个文件 ~380 token，是入口文件"——摘要够用就跳过读取；
- **重复读取拦截**：同会话重读同文件 → 提醒/拦截，**71% 的重复读取被拦**；
- **cerebrum.md 学习记忆**：用户纠正/偏好沉淀 + Do-Not-Repeat 清单（跨会话防重复犯错）；
- **buglog.json**：bug 修复记忆，修前先查，防重复发现；
- 诚实限制：token 估算 ±15%；依赖模型遵守指令（85–90% 合规）。
- **与 op0 的对照**：op0 的账本天然是重复读取检测的数据源（read 事件 + sha256），比 openwolf 的估算更准。这个能力我们**一行检测逻辑就有**，收益数据（71%）是行业实测。

### claude-mem（Claude Code 记忆插件，72k★，AGPL-3.0）
五 hook 生命周期 + Observer Agent（用另一个 LLM 把工具输出压缩成 ~500 token 结构化观察，10–40x）+ SQLite FTS5 + Chroma 向量。
- **渐进式披露三层**：search 索引（50–100t/条）→ timeline → get_observations 详情（500–1000t/条）；35,000t → 920t（**与 op0 的 obs 索引 + openpilot_obs 完全同构，我们已实现**）；
- 结构化观察字段（type=bugfix/feature/discovery、concepts、files_modified、facts）使每字段可独立检索；
- Smart Explore：tree-sitter AST 三层导航（search → outline → unfold），比 Glob→Grep→Read 省 6–12x；
- **注意边界**：它的 LLM 压缩是**跨 session 知识沉淀**（离线、服务下次会话），不是会话内折叠——后者已被我们实验否决。两者不矛盾。
- 风险记录：Worker 无认证（Issue #1157）、$CMEM 代币化、Anthropic 内置记忆的替代风险。

### 社区经验：交接文档与上下文纪律
- **Session handoff 模式**（多来源共识）：会话末写结构化 handoff 到磁盘——`done / files touched / current state / blockers / next steps`，**200 行封顶**；下会话读它而不是重建。"200 token 的 handoff 明天比 50k 的僵尸 context 便宜得多"。
- **Document & Clear 模式**：上下文重时 dump 到文件 → 清空 → 新会话读文件——"自己选择保留什么"优于 auto-compact（有损且不可控，实测 auto-compact 只保留 20–30% 细节）。
- **60% 容量阈值**：多个独立实践者收敛于同一结论——质量在 20–40% 容量就开始退化，60% 就该主动管理。
- 其他：CLAUDE.md ≤200 行 + progressive disclosure（引用不内联）；Skills 按需加载；Subagent 隔离调研（"便宜 context 是你永不加载的 context"）；Plan Mode 研究/实现分离；精准读（grep 先于 read）。

## 2. op0 落地方案（按 ROI 排序）

### S1 重复读取拦截（来源：openwolf；成本 ~15 行；预期收益：高）
bridge 的 read 处理前查账本：本 run 已读过同路径且当前文件 sha256 未变 → 直接返回
`[already read this run (turn N); content unchanged (sha256 match) — re-check the earlier result or re-read if you need it fresh]`。
账本天然有 read 事件 + 文件可算 hash，比 openwolf 的估算精确。变更写操作后 sha 变化 → 正常返回新内容。
**这是确定性规则、零 AI、零额外进程，行业数据 71% 拦截率。**

### S2 命令感知压缩（来源：rtk；成本 ~40 行；预期收益：中高）
E1 层从"一刀切存档"升级为"按命令前缀语义压缩"：
- test 类（pytest/go test/npm test）→ `PASSED n/n` 一行 + 失败项全保（rtk 数据 91.8%）；
- git status/log → 分组一行式；git diff → stat 行 + 变更块头部；
- find/ls → 目录分组；
- 其余命令维持现有 E1（>8k 存档+指针）。
全文仍落 observations/（可取回），fail-closed 原则不变：解析失败 → 原样返回。

### S3 会话 handoff（来源：社区共识；成本 ~30 行；收益：崩溃恢复质量 + 跨会话连续性）
closure/会话结束时规则式生成 `.openpilot/handoff.md`（decisions / files touched / state / blockers / next steps，≤200 行）——数据全部来自账本与 receipt，无 LLM。
与崩溃恢复投影共用：**恢复投影的折叠区用 handoff 替代逐 turn 重放**——这是解决"折叠区 user/assistant 原文重放导致投影膨胀"（A/B 实验暴露的问题）的规则式路线，不越"LLM 摘要被否"的界。

### S4 输出约束（来源：Caveman；成本 ~1 行；收益：输出端 -20~60%）
compose_turn_message 契约加一句："Reply concisely; never re-quote file contents you just read; one sentence confirmations suffice."。
社区数据：输出 token -65%（Caveman 项目实测 -65%，论文称部分基准准确率反升）。

### S5 项目地图 anatomy（来源：openwolf；成本 ~40 行；收益：探索型任务）
admission 的 project preflight 已扫描项目——顺手生成 anatomy（路径 + 字节 + 一行推断），read 前注入。探索型会话收益大，日常小。放 Phase 3。

### 明确不做
- 会话内 LLM 摘要（实验否决 + 行业把它放兜底）；
- 向量库/嵌入（claude-mem 的 Chroma）——单 run 内 obs 数量小，FTS/精确 id 足够，引入外部依赖违反 op0 纪律；
- 跨 session 记忆库（memsearch/claude-mem 方向）——产品级决策，与 subagent 阶段一起议。

## 3. 预期叠加效果（保守估算，基于来源数据折半）

| 层 | 机制 | 来源数据 | op0 保守预期 |
|---|---|---|---|
| 入口 | E1（已有） | — | 已拦截最大块 |
| 入口 | S1 重复读拦截 | 71% 拦截 | 会话 read 量 -30~50% |
| 入口 | S2 命令压缩 | 89% | 中等输出 -40~60% |
| 投影 | S3 handoff 式折叠区 | — | 修复折叠膨胀问题 |
| 输出 | S4 简洁契约 | -65% | 输出 -20~40% |

## 4. 实施顺序建议

S4（1 行）→ S1（15 行）→ S2（40 行）→ S3（30 行）→ S5（Phase 3）。
全部确定性规则、零 AI、零外部依赖，单测覆盖，行数预算内可消化（S1+S2+S4 ≈ 56 行，需 LINE_BUDGET 微调或压缩补偿）。
