# op0 批量实证报告：SWE-bench Lite 8 条（2026-09-13/14）

模型：deepseek-v4-flash · harness：`scripts/batch_eval.py`（headless，auto 审批 + 全记账 + Seatbelt 沙箱）· 判据：官方 test_patch 盲注入，agent 不知测试内容

## 一句话结论

**可测 6 条，成功 5 条（83%）**；2 条因 py3.13×老依赖环境不可测（诚实剔除）；总成本 **$0.89**，每条成功任务平均 **$0.085**。

## 结果明细

| instance | verdict | turns | tokens | cost | 时长 |
|---|---|---|---|---|---|
| pallets/flask-4992 | **success** | 26 | 26,075 | $0.0062 | 140s |
| pallets/flask-5063 | failed | 88 | 95,248 | $0.4624 | 789s |
| sympy-15609 | **success** | 27 | 21,575 | $0.0573 | 91s |
| sympy-16988 | environment | - | - | - | - |
| sympy-18057 | environment | - | - | - | - |
| sympy-20212 | **success** | 51 | 39,001 | $0.1271 | 155s |
| sympy-21612 | **success** | 56 | 49,677 | $0.1770 | 263s |
| sympy-21614 | **success** | 33 | 19,417 | $0.0580 | 142s |
| **合计** | 5/6 可测 = **83%** | 281 | 250,993 | **$0.888** | |

判据细节：每条在 base 与 op0-patch 两个状态下同口径对照（官方 test_patch 注入），verdict 要求 FAIL_TO_PASS 全过且 failed/errors 不劣于 base。

## 失败归因三分法

| 归因 | 条数 | 说明 |
|---|---|---|
| environment（不可测） | 2 | sympy 1.5/1.6 的 `distutils` 与 `py.path` 在 py3.13 断裂——F2P 测试在 base 上就 collection-error，benchmark 无法运行。**不是模型失败，是环境死刑** |
| capability（能力边界） | 1 | flask-5063：**功能增强型** issue（给 routes 加 subdomain 信息），88 turns / 95k token 未达——对比 4992（bug 修复型）一次命中。初步模式：**修 bug 易、加功能难** |
| 治理流程导致 | 0 | 没有一条失败与审批/沙箱/记账相关 |

## 治理栈在批量下的表现

- auto 审批模式全程工作：每条 run 的 bash/写操作都有 `consent_bound auto:true` 记账，**零人工卡**，零绕过；
- Seatbelt 沙箱全程在位（模型写操作被限制在各 workspace 内）；
- 全部 run 的账本正常闭合（run_finished），22-56 receipt/条——**8 条 run 全部可对账**。

## 过程中 harness 学到的事（对以后评测有用）

1. **网络**：GitHub 直连断 → gh-proxy.com + codeload 按 sha tarball（镜像不支持按 sha fetch，tarball 是唯一稳路）；PyPI 走清华源；
2. **WorkBuddy 环境两个拦路虎**：python 进程读 .env 被文件 broker 拦（shell 读不拦——key 由调用 shell export）；**后台任务不继承沙箱豁免**（Pi 写 ~/.pi/agent/*.lock 被拦 → 秒崩）——集成类运行必须前台跑；
3. **模型自建测试与官方 test_patch 冲突**（sympy-21614 实测）：harness 在注入官方测试前清掉 agent 对测试文件的改动（源码 patch 保留）；
4. 判定必须逐条独立跑 F2P（`pytest -q` 不列通过项名，grep 输出判定不可行）。

## 诚实边界

- 样本 6 条可测，置信区间宽（83% ± 30%），不构成对 SWE-bench Lite 全集的推断；
- 未跑 SWE-bench 官方 Docker harness（环境复现差异：py3.13 vs 官方 pin 的 python 版本——正是 2 条 environment 剔除的原因）；
- flask-5063 失败的归因（功能增强 vs 长任务预算）只有单样本支撑；agent 自建测试的行为在真实工程里是好习惯，但在盲测协议下需要 harness 显式处理（已处理）。
