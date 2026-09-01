# Metadata Control Plane 统一评估计划

> Status: Proposed evaluation contract
> Authority: Defines comparison and release gates; recorded results remain in evidence artifacts
> Owner: Architecture / evaluation
> Supersedes: Scattered architecture-level success thresholds; does not replace experiment manifests
> Last reviewed: 2026-09-01

## 1. 评估原则

新架构必须证明的是 **增量价值**，不是重新证明动态规划、树搜索或外部存储在一般意义上
可行。所有主要比较使用同任务、同模型、同工具、同权限、同验证器和同预算；只改变待
评估机制。

字符数和 whitespace token 只能作为 proxy。没有 provider 原生 input/output token、
调用数、延迟和有序 trace 时，不升级为总经济性结论。

L2 claim 状态统一记录在 [`EVIDENCE_INDEX_CN.md`](EVIDENCE_INDEX_CN.md)，新实验的详细
protocol/run 放在
[`../../../experiments/metadata_control_plane/`](../../../experiments/metadata_control_plane/README_CN.md)。

## 2. 必须保留的基线

| ID | 基线 | 回答的问题 |
| --- | --- | --- |
| B0 | Plain Pi / 主流 harness 隐式决策轨迹 | 显式 control plane 相对成熟 harness 本身增加了什么价值和成本 |
| B1 | 当前 OpenPilot Pi-only production commit（[owner-reviewed pin](../../../experiments/metadata_control_plane/spikes/x0_reviewable_baseline/b1_baseline.json)） | 重构是否比当前系统更好，而不只是比简化 toy runner 更好 |
| B2 | Static chain + governed source baseline | 选择性优化和动态激活分别贡献多少 |
| B3 | Static chain + 与实验臂相同的 governed context policy | 在上下文相同后，JIT 动态 successor 是否还有增量价值 |
| B4 | JIT dynamic chain，top-1 successor | 显式链的 governance、恢复和局部返工净收益 |
| B5 | Bounded top-k/tree policy | 多候选搜索是否值得超过链式的复杂度 |

B5 只能在 B4 通过后进入主线；否则树实验保留为研究支线。

B2–B5 可以在 `experiments/` 内使用 experiment-only/shadow implementation 形成对比臂，
但不得进入 `Code/src`、不得成为 production route，也不得绕过 roadmap 的生产实施门。

B1 只包含 pin 指向的 clean Git commit；当前 dirty worktree、未提交生产修改和本架构文档包
均不属于 B1。正式比较必须从该 commit 建立独立 clean checkout/worktree。

### 2.1 Baseline comparability contract

`Plain Pi` 不表示关闭安全边界。B0/B1/B2–B5 必须保持相同：

- task/acceptance fixture；
- provider、model revision、reasoning effort、sampling；
- Pi/harness version；
- admitted read/write/network/command scope；
- Action Gateway、tool implementation 和 validation；
- context-window/output limit 和总预算；
- environment/project snapshot；
- retry、timeout 和 completion policy。

B0 只移除待评估的显式 state/search/context **optimization**，不移除 Context Governance、
权限、receipt、validation 或安全门。否则比较的是安全级别差异，不是架构增量价值。

### 2.2 Baseline versioning rule

- baseline ID 一旦发布即不可变：`B1-openpilot-pi-only-20260831-v1` 永久绑定其 pin commit，
  不得原地重 pin；同一 baseline ID 不得指向不同代码。
- 未来生产变更完成 owner 审计并提交后，新建版本化 baseline（如
  `B1-openpilot-pi-only-<date>-v2`）；旧 baseline 与旧证据永久保留。
- 正式 Tier 2 比较开始前，必须存在一个当时最新、干净、owner-reviewed 的生产 baseline，
  并在 manifest 中预注册使用 v1、v2 还是两者都比较。
- Tier 0/1 离线 inventory、机制验证和接口 spike 不受此约束影响。

## 3. 核心指标

### 3.1 硬门

- 未授权 mutation、跨 scope 行为、凭据泄漏：0；
- false completion：0；
- declared-required fact 丢失后继续执行：0；
- 不可验证 projection 必须 fallback 或 safe-stop：100%；
- 不可逆副作用重复执行：0；
- 最终任务 hard validation 通过率不低于对照的预注册非劣界。

### 3.2 质量

- task success / hard validator；
- acceptance fact recall；
- strategy/branch exactness；
- rework success 和错误返工率；
- interruption 后恢复质量；
- 跨 task family 和 size tier 的稳定性。

### 3.3 成本

- provider input/output/total tokens；
- provider calls 和治理专用 calls；
- tool calls、validation calls、重复读取和 executed nodes；
- wall-clock / p50 / p95；
- retry、invalid proposal、fallback 和 recovery 次数；
- 持久化和 projection 构建成本。
- Context Governance 固定成本与 Context Optimization 增量成本必须分账。
- request coverage 必须标记 native/exact/estimated/char-only/unknown confidence；不可观测
  provider components 不得计为已治理。

### 3.4 架构与维护性

- public contract 数量、重复 authority sentinel、registry drift；
- controller/module 依赖和热点文件变化；
- 旧 producer/consumer/entrypoint 的 runtime usage 和 usage-zero 进度；
- 每个新 port/contract 对应删除的 branch、宽 `Any`、反向依赖和旧调用路径；
- 调用方需要理解的概念数，以及新旧路径同时存活的时间；
- migration 兼容率与 deprecation 使用量；
- 新增策略是否需要修改 metadata kernel；
- 替换 harness 是否需要改写业务 authority。

### 3.5 Control Plane V1 conformance suite

本 suite 只定义如何证明通过；V1 产品边界的唯一 owner 是
[`TARGET_ARCHITECTURE_CN.md` §2.10](TARGET_ARCHITECTURE_CN.md#210-control-plane-v1-产品边界)。
V1 release 使用同一组 adapter-neutral conformance cases 运行在 B1 current path、shadow V1、
Pi adapter 和 recorded/replay adapter；未来有第二个真实 harness 时复用同一套 suite。test
double 可以证明局部 contract，但不能单独证明 production port 或 adapter 替换成立。

| Boundary | Required conformance evidence |
| --- | --- |
| Task authority / admission | 未准入 scope、permission、budget、revision、consent 均不能进入执行 |
| State/context request | declared-required/source/freshness/budget 不完整时 fallback 或 safe-stop |
| Execution adapter | provider-specific payload 不进入业务 owner；abort/timeout/cancel 形成 typed disposition |
| Action | dispatch 前 authority recheck；副作用有 durable receipt；重复/冲突请求 fail closed |
| Evidence | observation append-only、canonical transition 有 source decision、敏感正文不进入 receipt |
| Verification / closure | false completion=0；缺 validation/receipt 不形成 ClosureCommit |
| Checkpoint / recovery | crash-window matrix、lease、generation、idempotency 和 exact resume 全通过 |
| Compatibility / migration | supported history 可读；未知/矛盾版本 typed reject；旧记录不原地覆盖 |
| Composition / entry | 单一 public entry；相同 identity 跨 ports 不被 glue 重写；adapter 可替换 |
| Contraction / rollout | shadow/default/cutover/rollback 可观测；无第二 writer/store；旧路径进入 usage-zero |

V1 completion 是上述 hard gates 与相应任务质量门共同通过，不以模块数、Protocol 数、测试
文件存在或可选 JIT/search policy 完成为判据。

## 4. Pilot 起始目标

以下数值是 pilot 的起始假设，不是已经冻结的 release gate，也不是当前实验结论。pilot
先估计 variance/ceiling/floor；正式运行再在 manifest 中冻结阈值、统计方法和样本量。若
pilot 反驳起始假设，应保留结果并修订后续 protocol，不能把原数字倒写成“已通过”。

| 维度 | 初始门 |
| --- | --- |
| 质量 | 长任务相对 B1/B3 的成功率非劣界不超过 5 个百分点；关键 hard validator 不得下降 |
| 安全 | 所有安全硬门 100% 通过，false completion 和越权均为 0 |
| Context Governance | 所有 OpenPilot-supported admitted routes 在声明 conformance level 内 source/trust/permission/declared-required/freshness/budget/fallback 100% 通过；unknown 不伪装 supported |
| 可选长任务上下文优化 | 启用时 provider input tokens 中位数相对 governed source baseline B1/B2 至少下降 30% |
| 可选长任务总成本优化 | 启用时 provider total tokens 相对 governed source baseline B1/B2 至少下降 15%，或在质量显著提升时给出预注册 cost-quality tradeoff |
| 治理开销 | governance-only provider calls 不超过总 calls 的 10%；未实例化候选不产生独立 provider call |
| 短任务退化 | root-only 任务不增加 provider round；总 token/latency 回归不超过 5% |
| 故障恢复 | 注入故障任务的重复工作/重复读取相对 B1 至少下降 20%，重复副作用为 0 |
| Metadata evolution | ME0–ME5 全部通过；未知版本和矛盾字段 fail closed；ME6 仅在 query-demand gate 后独立裁决 |
| 架构收缩 | cutover 的 net complexity ledger 显示净收缩或明确安全/恢复收益；纯 pass-through 新层不通过 |

若任务方差使百分点门不适用，manifest 必须改用 paired task score，并在运行前冻结最小
可检测效应；不能结果出来后修改门槛。

治理开销门只在全部 quality/safety/required-governance gates 通过后评估；不得通过少记录、
少验证或隐藏治理动作来满足 10% 指标。

### 4.1 Statistical and reproducibility gate

- 先用 pilot 估计 variance/ceiling/floor，再冻结正式样本量和最小可检测效应；
- paired unit、repeat independence、same-session/replay/provider sample 必须分层；
- model/provider/harness 版本漂移后，旧结果保留但不得与新 run 静默合并；
- 报告 task-family/size-tier cluster，而不只报告 receipt 行数；
- multiple comparisons、失败样本、missing telemetry 和 early stop 必须显式；
- proxy 结果只能支持 mechanism，不能用于 monetary/transport rollout gate。

### 4.2 成本分级最小证据路径

每个实验 manifest 必须在运行前冻结 provider calls、input/output tokens、wall-clock、repeats、
提前停止条件和允许解锁的 roadmap gate。全局文档不预设统一金额；具体数值由对应 protocol
按任务、provider 和 tier 冻结。

| Tier | Evidence | Provider cost | Can unlock |
| --- | --- | --- | --- |
| Tier 0 | deterministic offline、inventory、fixture、fault simulation | 0 provider calls | ME/X/G 的 mechanism 或 implementation-readiness gate；不能升级 provider 质量/经济性 claim |
| Tier 1 | bounded canary、单变量、小 task-family/size 覆盖 | manifest 预注册的低 calls/tokens/wall-clock 上限 | experiment/shadow/default-off 下一阶段；不能直接 default-on |
| Tier 2 | formal paired、独立样本、task-family/size-tier、native telemetry | manifest 预注册正式预算和统计停止规则 | rollout/default-on 或 architecture kill decision |

资源不足时只能停止在当前 tier 或缩小尚未运行的 experiment scope，不能在结果出来后降低
quality/safety/authority gate，也不能把 Tier 0/1 结果重解释为 Tier 2 结论。

## 5. 实验组与卡点

### 5.1 Experiment ID namespace

当前文档和新 protocol 只使用 canonical ID。历史 artifact 文件名不重写，但引用时必须加
qualified prefix，避免一个 ID 指向两个问题。

| Namespace | Meaning | Status |
| --- | --- | --- |
| `CL-0…CL-3` | context conformance level；不是实验 ID | Active taxonomy |
| `G0…G7` | Context Governance experiments | Active questions |
| `CSG-C0…CSG-C6` | 既有 `context_scope_governance` C 系列 artifact 的限定引用 | Historical/prior evidence |
| `COPT-0…COPT-4` | 新 Context Optimization experiments | Active questions |
| `J-T0`, `J-T1` | JIT 前置 engineering spikes | Active questions |
| `J0…J4` | 显式 JIT paired experiments | Gated after prerequisites |
| `S0…S6` | Search/tree/world-model experiments | Dormant until JIT gate |
| `R0…R6` | Durability/recovery experiments | Active by roadmap phase |
| `ME0…ME6` | Metadata evolution experiments | Active; ME6 conditional |
| `X0…X4` | Migration/complexity spikes | Active by roadmap phase |
| `B0…B5` | Comparison arms，不是独立实验 | Active vocabulary |

第二轮审查快照里的 `T0…T5` 不再作为 active namespace：`T0` 合并到 G7/J2，`T1` 合并到
J-T0，`T2` 合并到 C-Gov/COPT-0，`T3` 合并到 X1，`T4` 合并到 X2/ME6，`T5` 合并到
J-T1/R0/R1/R4。审查快照保持原文，但新 protocol 不再创建 `T*` 目录或 manifest。

在 ME0/ME3 inventory 完成前冻结 Claim/实验命名空间：可以收缩、合并、拒绝或更新现有
状态，但不得增加新的 Claim ID 或实验组。远期 Search/WorldModel claim 保持 dormant。

### M 组：Metadata evolution

- M0 = ME0 + ME3：回答 registry 能否完整描述当前 contract 和真实使用；
- M1 = ME1 + ME2：回答历史读取与 migration 是否可靠；
- M2 = ME4 + ME5：回答能否阻止重复 authority 并安全删字段。
- M3 = conditional ME6：只有 query-demand inventory 过门后，回答 derived graph/query 是否
  能保持有界且只读。

三组合起来解决“metadata 如何增删改、如何知道能删、如何长期维护”的卡点。

### C-Gov 组：Context Governance（必选）

- 所有 OpenPilot-admitted supported routes 在声明的可观测边界内使用相同 source、trust、
  permission、declared-required、freshness、预算和 fallback 不变量；
- governed source baseline 是基线，不要求 omission 或 token 减少；
- `CSG-C2` 的 stale/hidden/unavailable/undeclared negative controls、`CSG-C5` prompt injection 和 `CSG-C6`
  full-request budget 共同构成治理验证；
- 新增 cross-adapter conformance，验证更换 harness 不改变上下文 authority 和 safe-stop。

C-Gov 回答“每个 OpenPilot-supported route 在声明范围内是否安全、一致、可回退”，属于
基础正确性门。

G0–G7 保留为实验问题：最终 request manifest 可见性、adapter capability level、governed
source baseline、declared/latent fact boundary、budget confidence、authority isolation、
body-free receipt 和 governance-only overhead。具体 schema/contract 在实验前不批准。

### C-Opt 组：Context Optimization（可选）

- `COPT-0`：governed source baseline vs governed local projection；
- `COPT-1`：local-only vs local + on-demand evidence；
- `COPT-2`：fresh / stale / hidden / unavailable / undeclared dependency；
- `COPT-3`：消费侧事实引用与 unused-injection audit；
- `COPT-4`：Summary Resolution Tree 的按需展开、recall 和总 provider token。

`COPT-0…COPT-4` 回答“在 C-Gov 不变量不变时，能否省输入且不因缺事实漂移”。现有 E03
local-injection 对局部机制有支持，但 provider telemetry 和独立样本仍不足。C-Opt 失败时
回退 governed source baseline，不否定 C-Gov。

### J 组：显式 JIT 动态链

- J-T0：structural escalation typed trigger vocabulary、owner、bound evidence、cooldown 和
  deterministic fallback；具体 schema 未通过前不批准 durable proposal；
- J-T1：admitted execution attempt/NodeVisit 与 Pi tool loop、provider call、abort/retry 的
  adapter-neutral mapping；
- J0：B0/B1 vs B4，测显式 top-1 successor 的额外调用和恢复收益；
- J1：B3 vs B4，隔离动态激活本身，不让上下文差异混入；
- J2：短任务 root-only、无需 successor 的快路径；
- J3：长任务中的 invalid proposal、needs-rework、stale scope 和局部恢复；
- J4：同一任务的总 token/call/latency/quality paired analysis。

J0–J4 才回答“把 harness 的隐式选择显式化是否值得”。当前 E04 证明了安全条件裁剪和
部分工作/context proxy 下降，但 typed actions 上升 12.96%，所以还没有总净收益结论。
J-T0/J-T1 是前置 engineering evidence，不升级质量或经济性 claim。

### S 组：链到树/搜索策略

- S0：top-1 与 top-k body-free candidates；
- S1：实例化前候选验证成本；
- S2：bounded depth/breadth 与 node explosion；
- S3：best-first/tree policy 相对 JIT chain 的质量—成本曲线；
- S4：策略替换是否不改 kernel、permission 和 evidence owners。
- S5：RAP/MCTS WorldModel simulated state 与 authoritative state 隔离；
- S6：未选候选最小 receipt 的审计充分性和存储/context 成本。

S 组回答树搜索是否值得；它不是 V1 或 Post-V1 Phase 5/6 的前置条件。

### R 组：恢复与持久化

- R0：checkpoint attach/resume identity；
- R1：receipt 后、validation 前崩溃；
- R2：projection/cache 损坏后的 source fallback；
- R3：局部节点返工 vs 全任务重放；
- R4：更换 search/harness 后的同一 authoritative resume。
- R5：并发 writer、lease loss、stale generation 和 idempotency conflict；
- R6：event/artifact/index retention、清理和 historical recovery。

### X 组：迁移与复杂度 engineering spikes

- X0：dirty-worktree/base-state manifest，能否让后续切片明确区分历史改动与本架构变更；
- X1：在一个真实 read-only seam 上演练 net complexity ledger；
- X2：single authoritative writer + rebuildable shadow representation 的 fault/reconciliation；
- X3：port admission rehearsal，验证 test double/pass-through 不能单独通过；
- X4：experimental metadata expiry/removal，验证“未来 consumer”不会进入 authoritative state。

X 组只支持 implementation readiness，不把 engineering 可行性升级为任务质量或产品收益。

## 6. 当前证据如何使用

- E03/E04、context-scope-governance 和相关论文用于确定机制候选和实验条件；
- 同会话 sequential typed actions 只能支持局部消费/逻辑，不是独立 provider 质量样本；
- offline receipts 可以证明 deterministic gate、安全和计量逻辑，不能证明模型泛化；
- 原始 run/receipt 不覆盖，架构主张只在 evidence index 中升级；
- 新架构实现前先补 M 组和 C-Gov conformance；C-Opt/J 组继续保持 experiment-only，S 组后置。

## 7. 对比结果的呈现

每份最终结果至少同时报告：

- task/fixture/model/provider/repeat 和独立性；
- hard quality/safety；
- provider 原生 telemetry 可用性；
- work、context 和 governance 三类成本，不只报其中一种；
- paired delta、失败样本和 fallback；
- 支持、反驳、仍不确定的具体 claim；
- 是否达到 roadmap 的实现或 rollout gate。

## 8. Architecture kill criteria

以下结果不是“需要更多工程”，而是当前方向的停止或降级条件：

| Candidate | Kill / fallback condition | Fallback |
| --- | --- | --- |
| Executable metadata registry | 必须复制完整 schema/owner，或 drift 无法由生成/校验消除 | 保留 models + catalog +人工 impact note |
| General derived graph | 没有重复跨 owner 查询，或有界 query 无法满足真实用例 | 保留直接 references/local views |
| New control-plane port | 只增加 pass-through 层，或仅由 test double 证明需要，未减少依赖/分支/`Any`/旧路径 | 保留直接窄调用 |
| New metadata object/service | 无独立 lifecycle/consumer，或需要第二 authority/store 才成立 | 复用现有 contract、owned nested value 或 derived view |
| Explicit JIT chain | 相对 B0/B1 无质量、恢复或总成本增益 | root-only/plain Pi + governed context |
| top-k/tree/DAG | 增量收益不覆盖 candidate/search/governance 成本 | top-1 或无显式 candidate |
| MCTS/LATS/RAP WorldModel | simulation token/latency高、value不可校准或真实任务无增益 | 不进入 production roadmap |
| Selective projection | declared-required coverage/freshness 无法可靠验证 | governed source baseline |
| Context Governance route | 可观测 source/trust/permission/declared-required/freshness/budget 无法保持一致 | 不准入或降低该 route conformance level，保留当前已验证 request builder |
| Structure revision | revision/cursor/checkpoint 无法通过 mixed-state fault gate | 不引入 durable dynamic structure |
| Local rework | affected consumer scope 无法可靠确定且重复验证不减少 | conservative parent/full-task revalidation |

任何 killed candidate 的旧 evidence 保留；若未来有新的问题和不同机制，可以新 ADR/Claim
重新提出，不能在原 claim 上悄悄降低门槛。
