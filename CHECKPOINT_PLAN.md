# Checkpoint Resume 设计（2026-09-11）

> 调研对象：LangGraph checkpointing（每节点边界持久化、crash 后加载快照继续、HITL 原生）、Temporal event-history replay、cc harness 的 "filesystem as checkpoint store"、Microsoft Agent Framework（pending approval 保存在 checkpoint 里，恢复后重发未决请求）、Resume/Replay/Rewind/Fork 语义辨析。
> 结论先行：**op0 的账本就是 event history（Temporal 同构），recovery 投影已经能从账本重建上下文——checkpoint resume 的 90% 机制已存在。缺的是语义锚点、resume 入口、schema 版本化三件小事。**

## 一、调研发现（四条硬结论）

1. **Resume ≠ Replay ≠ Rewind ≠ Fork**（语义混淆是危险之源）：Resume = 从最近有效状态继续（不重执行）；Replay 会重新跑模型调用与工具（可能重复副作用）；Rewind 撤销状态；Fork 开新分支。*"一个不说明语义的恢复按钮可能非常危险。"*——op0 只做 Resume，语义由架构保证（副作用永不重放）。
2. **Checkpoint 不能让现实世界回滚**——bash 改过的未追踪文件、发出去的消息不会随 checkpoint 撤销。op0 的回答恰好是这个问题的正解：**receipt 是"哪些副作用已生效"的权威记录**，resume 后对账 receipt 而不是凭记忆。
3. **cc harness 模式与 op0 同构**：session state（易失）与 task state（持久）分离；把任务分解为带显式完成标记的子任务，恢复时扫描外部状态判断进度——op0 的账本 + receipts 就是这套 event log，且是自动实现的。
4. **Microsoft Agent Framework**：未决审批请求保存在 checkpoint 里，恢复后重新发出——op0 的 pending proposal 在 resume 时也应重新呈现（第一版：提示存在未决提案，详情 /proposals 查看）。
5. **"cleanly aborted run with partial results 是 first-class success state"**——部分完成的合法化是 resume 的价值前提。

## 二、现状盘点：90% 已存在

| 件 | 状态 |
|---|---|
| 从账本重建上下文（build_projection recovery 模式） | ✅ 已有（崩溃恢复路径） |
| 副作用不重放（receipt 对账） | ✅ 已有 |
| 未决审批的持久化（registry proposals 落盘） | ✅ 已有（registry 文件） |
| **checkpoint 语义锚点**（"到这里为止是已完成工作"） | ❌ 缺 |
| **跨进程 resume 入口**（新会话发现未完成 run 并接续） | ❌ 缺 |
| **账本 schema 版本化**（resume 读旧账本的前提，Semantic Kernel 演进缺口） | ❌ 缺 |

## 三、设计（三件小事）

### 3.1 checkpoint 语义锚点
- 新事件 `checkpoint_recorded` `{checkpoint_id, note}`（registry 注册）；`/checkpoint <note>` 命令在回合边界打点（人显式）；run 结束/崩溃时系统自动打点（note=结束原因）。
- 锚点是给"进度语义"用的（resume 时的 summary 素材），不是恢复必需品——**恢复的必需品是账本本身**。

### 3.2 resume 入口（跨进程接续）
`_run_repl` 启动时扫描 `trajectory/*.jsonl`：存在"有 session_started、无 run_finished、且非当前 run"的账本 → 提示：

```
Found an unfinished run run_xxx (N turns, M receipts, last active <time>).
Resume it? (y) start fresh (n)
```

y → 当前 Session 加载该账本路径（或直接以该 run_id 继续追加）+ `inject_recovery_projection()` + 提示"context restored from ledger"。**语义 = 纯 Resume**：账本追加、receipt 不重放、投影重建，与崩溃恢复共用同一条路径。

### 3.3 账本 schema 版本化（Semantic Kernel 演进第一块）
- trajectory 文件**首行**写 meta：`{"record": "schema", "schema_version": 1, "run_id": ...}`（非 EventRecord，load 时跳过）；
- `load_events` 兼容无 meta 的旧账本（视为 v1）；registry 声明 `SCHEMA_VERSION = 1`；
- 未来改 payload 结构时升版本 + registry 记录迁移规则——**演进机制从"会出事的隐式假设"变成"显式版本"**。

## 四、任务分解（预估净增 ~120 行 → 预算 4,180 报备）

- T1 registry：`checkpoint_recorded` 注册 + `SCHEMA_VERSION` 常量；
- T2 session：首行 meta 写入 + load 兼容；
- T3 tui：`/checkpoint` 命令 + 自动打点（run 结束/崩溃）；
- T4 cli：resume 入口（未闭合 run 检测 + 提示 + 账本接续 + 投影注入 + 未决提案提示）；
- T5 E2E：fake-pi 两回合 → 不闭合退出 → 新进程 resume → 上下文恢复（答出前文内容）→ 继续追加同账本；单测（meta 头、load 兼容、未闭合检测）。

## 五、明确不做

Replay/Rewind/Fork（语义危险且无需求）；checkpoint 快照文件（账本即快照，不复制第二份）；自动定时打点（人显式 + run 边界自动，足够）。
