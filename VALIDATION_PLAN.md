# Subagent Validation 闭环设计（2026-09-10）

> 调研对象：Claude Code hooks 三层验证模型、验证强度四层分级、OpenAI Agents SDK 三类 guardrails（tripwire 模式）、对抗性审查原则。
> 结论先行：**op0 已有 70% 的件**（decide_closure 三态裁决、record_validation 命令执行、receipt validation_status、fail-closed 纪律）——本设计是组装，不是新建。真正的缺口只有一个：**子 run 的完成判定目前只看"跑没跑完"，不看"目标是否达成"**。

## 一、调研发现（五条可吸收的成熟设计）

1. **cc hooks 的三层验证模型**（已成熟且被广泛实践）：
   - Micro（PostToolUse）：每次写后跑 lint/格式化——秒级反馈；
   - Macro（Stop hook）：agent 声明完成前跑验证脚本，**exit 2 阻止完成并把 stderr 喂回模型**——"模型无法与 shell 进程争辩"；
   - Validator subagent：只读验证代理用全新上下文审查（Anthropic：*"把做事的 agent 和评判的 agent 分开，是强有力的杠杆"*）。
2. **确定性 vs 建议性的光谱**：CLAUDE.md 指令是 advisory（模型在任务压力下会忽略），hooks 是 deterministic（跑在上下文窗口之外）。op0 的 admission/receipt 本来就在 deterministic 一侧——validation 闭环必须同样 deterministic，不做 prompt 层请求。
3. **Stop hook 的实战教训**：连续阻止 8 次后强制结束——**验证-修复循环必须有上限**，否则烧 token 死循环。
4. **OpenAI guardrails 的 tripwire 模式**：验证失败抛 typed exception 而非静默改行为——与 op0 的 fail-closed raise 同构 ✓。
5. **验证信号类型**（Anthropic 官方分级）：测试套件/构建退出码/linter/fixture diff 全是**命令退出码**形态——op0 的 `validation_command: str` 设计正好覆盖。

## 二、现状盘点：缺口只有一个

| 件 | 状态 |
|---|---|
| `decide_closure` 三态裁决（failed > pending > success；dismissed 不算数） | ✅ 已有 |
| `record_validation`（跑命令 + 持久化结果，120s 超时） | ✅ 已有 |
| receipt 的 validation_status / validation_command | ✅ 已有 |
| 主循环的人触发验证（`/validate <cmd>`） | ✅ 已有 |
| **子 run 的验证命令声明** | ❌ 缺 |
| **子 run 结束时的自动验证**（不经人手） | ❌ 缺 |
| **status 按 validation 裁决**（现在只看"跑完没跑完"） | ❌ 缺 |

## 三、设计

### 3.1 验证命令的声明：per-task，写在工单上

`openpilot_task` 的 args 增加 `validate` 参数（shell 命令，可选）：

```json
{"task": "add divide() to utils.py handling zero division",
 "validate": "python -c \"from utils import divide; assert divide(6,3)==2; divide(1,0)\" "}
```

谁声明：**父模型在派发时声明**（任务工单的一部分——它最清楚"完成"意味着什么）；人审批工单时看到验证命令（gate 卡片展示）——验证判据因此也是被人类批准的。

### 3.2 执行时机与环境

子 run 结束（ask 正常返回）后、task_finished 入账前，op0 系统自动执行：

- **沙箱内执行**（同一 profile——验证命令与子任务同一物理边界）；
- 超时 120s（复用 record_validation 的默认）；
- 结果入**子账本**（新事件 `task_validation`，注册进 registry：`{command, exit_code, tail}`）——这次账本归属正确（验证是子 run 生命周期的一部分）。

### 3.3 status 裁决（升级版语义）

| 情形 | status | verified |
|---|---|---|
| 跑完 + validate exit 0 | success | true |
| 跑完 + validate exit 非 0 | **failed**（summary 带 stderr tail，父模型可重派） | false |
| 跑完 + 无 validate 命令 | success | **false**（诚实：没验证就不自称已验证） |
| 子 run 崩溃 / 空报告 | indeterminate | false |

registry 变更：`task_finished` 加 optional `verified: bool`、`validation: str`（命令 + exit code 摘要）；新增 `task_validation` 事件。**父模型拿到失败原因（stderr tail），可以决定重派并带上修正指令——这是 validation 闭环的"闭环"二字所在**。

### 3.4 不做的（第一版边界）

- **验证-修复循环不做**（验证失败直接 failed 返回父）：cc 的 Stop hook 循环有 8 次上限的教训——第一版让父模型决定是否重派，重派次数由父控制（比子内循环更可审计）；
- Micro 验证（每次写后 lint）不做：需要 hook 机制，等有真实 lint 需求再上；
- Validator subagent（第二意见）不做：Phase 3，且 Anthropic 自己警告"审查代理倾向于报告问题"。

## 四、任务分解（预估净增 ~70 行 → 预算 3,950 报备）

- T1 registry：`task_finished` 扩展（verified/validation optional）+ `task_validation` 事件注册（3 行）；
- T2 bridge：`openpilot_task` args 透传 `validate`；TS sidecar 参数声明（~15 行）；
- T3 cli `_spawn_task`：验证执行（沙箱 subprocess）+ status 裁决 + task_validation 入子账本 + TaskHandoff 扩展（~30 行）；
- T4 契约指引（validate 参数说明进不变头部）+ E2E（验证成功/失败/无验证三臂）+ 真实冒烟（一个必须过验证的编码子任务）+ 预算核对（~22 行测试不计）。

## 五、验证路径

1. E2E 三臂：validate exit 0 → success/verified:true；exit 1 → failed + stderr 在 summary；无 validate → success/verified:false；
2. 真实冒烟：派"写一个函数 + validate 跑断言"的子任务——验证模型产出的代码**被命令裁决**而非自报；
3. chaos 不动（fakesuccess 场景已覆盖"claim ≠ closure"主循环侧）。
