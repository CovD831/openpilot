# op0 Compaction 模块计划

> 状态：设计定稿，待实施。2026-09-09。
> 依据：老板定调 masking 路线（摘要被实验否决）+ 2026-09 主流策略调研 + 架构讨论共识。

## 0. 目标与定位

长会话能力的第一块拼图：**历史所有权从 Pi 内存收回 Python 侧**，模型上下文 = 账本的投影，compaction = 投影生成时的确定性变换规则集。全程零 LLM、零幻觉、无损可取回、fail-closed。

## 1. 设计基石（讨论定案，实施期不得违背）

| # | 原则 | 内容 |
|---|---|---|
| 1 | 存储与表现分离 | 账本=基表（append-only 永不改写）；模型上下文=物化视图（易失投影）；compaction=视图变换规则。策略换血不动账本一字节 |
| 2 | masking-first | 确定性规则（mask/释放/裁切/去重/清洗），无 LLM。依据：老板实验结论 + JetBrains 研究（masking ≥ summarization 且更便宜）+ Amp/Cognition 对摘要的否定 |
| 3 | 可再生性分级 | 用户消息（不可再生）**特权永不处理** > 结构性内容（配置/接口/schema）mask 可取回 > 可再生输出（命令/日志/列表）释放可重跑 |
| 4 | 单调性 | mask/释放决策写入账本 compaction 事件后永久固定，投影重放照账执行，**绝不滑窗重算**（cache 连环失效教训） |
| 5 | fail-closed | 投影验证不过（空/超长/游标非法）→ 本回合回退账本原文全文，宁超预算不喂坏上下文 |
| 6 | 真实计量 | 触发判断用 provider usage（model_response payload），字符估算只用于内部排序 |

## 2. 架构与数据流

```
                 ┌──────────────────────────────────────────┐
                 │  Session Ledger (.openpilot/trajectory/)  │
                 │  append-only：turn_started / model_response│
                 │  / tool_call / tool_result(obs_ref) /      │
                 │  compaction 决策事件                        │
                 └───────────────┬──────────────────────────┘
                                 │ build_projection(events, policy)
                 ┌───────────────▼──────────────────────────┐
                 │  模型上下文投影（易失视图）                  │
                 │  [不变头部:工具契约] + [任务目标]            │
                 │  + [mask/释放/裁切后的历史] + [新输入]       │
                 └───────────────┬──────────────────────────┘
      触发: usage > 70% 预算      │ 物化 = 重启 Pi 进程，
      （回合边界，滞回至 ≤50%）    │ 首回合注入投影
                 ┌───────────────▼──────────────────────────┐
                 │  Pi Runtime（无状态执行面，--no-session）   │
                 └──────────────────────────────────────────┘
  obs 取回: openpilot_obs(N) → bridge → 读 .openpilot/observations/<call_id>.txt
```

新增组件：
- `Code/src/op0/compaction.py`：触发器 + MaskPolicy 规则集 + build_projection + fail-closed 回退
- `openpilot_obs` 工具：sidecar TS handler + bridge Python handler（只读，免审批，与 read/search 同级）
- `.openpilot/observations/<call_id>.txt`：大输出全文溢出区（账本只存指针 + sha256 + 元信息）

## 3. 实施阶段

### Phase 1（masking 闭环，可独立交付）

| # | 任务 | 内容 | 预估行数 |
|---|---|---|---|
| T1 | obs 存储层 | observations/ 目录；bridge 在工具结果过境时：全文落盘 + 账本事件存指针（call_id/来源工具/字节数/sha256） | ~35 |
| T2 | E1 入口裁切 | bridge 返回给 sidecar 前，单条结果 >8k 字符 → tombstone + obs 引用（大输出从未进入 Pi 内存） | ~15 |
| T3 | 计量与触发 | usage 累计（model_response payload）；>70% 触发；无 usage 时字符估算降级 | ~25 |
| T4 | build_projection | 从账本事件流重建消息序列；不变头部 + 任务目标 + 历史变换区 + 新输入；P1 mask（>4k → 【obs #N】）+ P2 释放（可再生类 → 一行 tombstone 含再生提示） | ~70 |
| T5 | openpilot_obs | TS handler + bridge handler + compose_turn_message 契约加一句 | Py ~15 / TS ~25 |
| T6 | 物化接线 | 折叠 → session.record("compaction", 决策) → 重启 Pi → 下回合投影首消息；UI 打折叠行（只读投影原则） | ~25 |
| T7 | 单测 + 冒烟 | 见验收标准 | tests 不计 |

**Phase 1 验收标准（量化）**
1. mask/取回往返 sha256 一致率 **100%**（≥30 条随机 obs）；
2. 触发后投影 usage ≤ 预算 **50%**；
3. 崩溃重启后投影重建成功——"失忆干活"缺陷修复（recovery 后模型可答会话早期事实）；
4. 长会话冒烟（50+ 回合）：模型**主动调用 openpilot_obs** 取回早期 obs 并完成任务；
5. 全测试通过；Python 总行数 ≤ 3150（G4）。

### Phase 2（长尾清理 + 对照实验）

| # | 任务 | 内容 | 预估行数 |
|---|---|---|---|
| T8 | P3 尾偏置裁切 | 1k–4k 老输出：头 200 + 尾 400 字符（错误/结论在尾部），中间省略 | ~20 |
| T9 | P4 去重 | 同 sha256 重复 obs 只留首份 | ~15 |
| T10 | P5 清洗 | 连续空行折叠、空白压缩 | ~15 |
| T11 | 对照实验 | 同任务集开/关 compaction：closure 成功率 + 真实 usage + 物化后的 cache 计费影响 | 实验脚本 |

**Phase 2 验收标准（量化）**
1. closure 成功率不降（配对对比，0 退步）；
2. 长会话 usage 下降 ≥30%（目标值；实际值如实记录，负向结果照报）；
3. P3–P5 每条规则独立开关且各自有单测。

## 4. 首版参数（全部可配置，落 EngineConfig/环境变量）

| 参数 | 默认 | 说明 |
|---|---|---|
| context_budget_tokens | 按 provider 实测窗口保守取值 | 触发判断的分母 |
| 触发阈值 / 目标水位 | 70% / 50% | 滞回防抖 |
| E1 入口阈值 | 8k 字符 | 超大输出不过模型 |
| P1 mask 阈值 | 4k 字符 | 投影层 |
| P3 保留 | 头 200 / 尾 400 字符 | 尾偏置 |
| 保护区 | 最近 ~20k token 事件 | 短期连贯性 |
| 活跃区 K | 最近 2–3 回合原文 | prompt + 回复 |

## 5. 风险与开放问题

| # | 风险/问题 | 缓解 |
|---|---|---|
| R1 | mask 后模型不调 openpilot_obs 导致任务失败 | 工具契约明示；冒烟验证；失败则扩大保护区或降 mask 阈值 |
| R2 | 部分 provider 响应无 usage（错误响应 usage=0） | 无 usage 时字符估算降级，且不触发折叠（宁等真实值） |
| R3 | 活跃区只重放 prompt+回复，模型"记得结论忘了证据" | obs 通道补偿——这正是 mask/取回设计的动机 |
| R4 | 行数超预算 | 逐任务过账；超则砍 Phase 2 顺序后移 |
| O1 | 物化重启后 prompt cache 全失效一次的计费影响 | 折叠低频可接受；对照实验量化实际占比 |
| O2 | obs 编号 run 内有效，跨 run 不通 | 文档明确；跨 run 记忆属未来 subagent 范畴 |

## 6. 明确不做（scope 控制）

- LLM 摘要（已否决，实验与行业证据充分）；
- 跨 run 长期记忆 / MemGPT 式 archival（subagent 阶段再议）；
- step 级滑窗压缩（cache 连环失效，已否决）；
- 修改 Pi / 打开 --no-session（历史所有权已定：Python 侧）。

## 7. 免费红利（实施中顺带验证）

崩溃恢复上下文重建：engine 重启后首回合注入投影（从账本重放），修复"失忆干活"现存缺陷——T6 物化接线与 recovery 共用 build_projection，一次实现两处收益。
