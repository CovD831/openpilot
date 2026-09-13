# op0 真实任务运行报告：SWE-bench Lite `pallets/flask-4992`

日期：2026-09-13 · 模型：deepseek-v4-flash · 运行方式：老板终端 TUI 交互（人卡审批）

## 一句话结论

**任务成功，零回归**：op0 在不知道测试内容的前提下修复了真实开源 issue，官方评测测试命中，成本 **$0.0062 / 2 分 20 秒**，治理链（审批/账本/receipt）全程真实工作。

## 任务与判据

- 任务：flask issue #4992 —— 给 `flask.Config.from_file()` 加 file mode 参数以支持 `tomllib`（Python 3.11 原生 TOML）
- 判据（SWE-bench 语义，盲测）：
  - FAIL_TO_PASS：`tests/test_config.py::test_config_from_file_toml`（官方 test_patch 注入，op0 事先不知道）→ **PASS** ✓
  - PASS_TO_PASS（简化口径）：`tests/test_config.py` 其余 18 条 → **全 PASS** ✓

## 同口径零破坏对照

全测试面在此环境（py3.13 + 2.3 时代依赖）本底噪音大，因此以 base 与 op0 同口径对照：

| | failed | passed | skipped | errors |
|---|---|---|---|---|
| base + 官方 test_patch | 41 | 106 | 14 | 315 |
| **op0 patch + 官方 test_patch** | **41** | **107** | **14** | **315** |

唯一差异：**passed +1** —— 正是从"不存在"变 PASS 的目标测试。failed/errors 逐类一致，patch 零破坏。

## 成本与规模（账本实测，run_55d138a7…）

| 指标 | 值 |
|---|---|
| 总时长 | **2 分 20 秒**（13:36:54 → 13:39:14 UTC） |
| 回合数 | 26 |
| token | 输入 14,162 · 输出 11,913 · 共 26,075 |
| 成本 | **$0.0062**（v4-flash 牌价） |
| 平均每回合输入 | **~545 token**（治理契约 ~400 + 工具结果回传） |

每回合 545 token 的输入是"能力上下文按需装载"的第一个真实任务数据：治理契约常驻 ~400 token，代码库上下文靠模型按需 read，而非 20k 级 system prompt 常驻。

## 治理事件流（账本 11,275 条事件，30 种注册类型全部合规入账）

| 治理事件 | 次数 | 说明 |
|---|---|---|
| command_proposed + consent_bound | 19+22 | 每条 bash 都过审批卡（人按 y/a） |
| patch_proposed + consent_bound | 3+3 | 每次文件写都过卡 |
| bash_receipt_written / patch_receipt_written | 19 / 3 | 全部副作用落 durable receipt |
| run_finished | 1 | 账本正常闭合（可 checkpoint/resume 的良构账本） |

**人与模型的真实协作形态**：模型 26 回合内发起 22 次审批请求，全部被人批准/拒绝后自适应重试，无绕过、无未记账副作用。

## 模型行为的两个亮点

1. **盲测下与维护者决策收敛**：issue 作者建议参数名 `mode="b"`，flask 官方 PR #5019 最终实现改用 `text: bool`。op0 在不知道官方实现的情况下独立选择了 `text`——与人类维护者的最终决策同名同形。
2. **自主文档同步**：除 `src/flask/config.py`（+8/-3）外，主动更新了 `CHANGES.rst` 和 `docs/config.rst`（含 `.. versionchanged:: 2.3` 注记）——真实维护者的收尾习惯，非任务要求。

## 诚实边界

- PASS_TO_PASS 是简化口径（test_config.py 全量），未跑 SWE-bench 完整 harness 的逐条 PASS_TO_PASS 列表与 Docker 化环境复现；
- 全测试面 41 failed / 315 errors 为本底环境噪音（py3.13 × 2.3 时代依赖的 fixture 不兼容），base 与 op0 完全一致，不影响判据有效性，但意味着该环境不能直接用于其他 instance；
- 单任务样本，不构成对任务成功率的统计声明。

## 结论

治理栈（admission → 沙箱内执行 → receipt → 账本 → closure）在真实开源任务上第一次完整跑通：**审批没有拖垮效率（2 分 20 秒）、成本可忽略（$0.0062）、副产物是一份可对账的良构账本**。"可以签字画押的执行语义"从合成环境走向了真实世界。
