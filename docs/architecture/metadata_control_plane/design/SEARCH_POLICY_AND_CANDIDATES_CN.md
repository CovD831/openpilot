# Search Policy 与轻量候选对象模型

> Status: Proposed L2 architecture
> Authority: Target candidate/search semantics; no search algorithm is approved as default
> Owner: Search policy / control-plane runtime
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 核心思想

候选与执行节点采用“类—实例”分离：

- **CandidateTemplate 类似类或插件注册**：定义能力、输入输出、成本上界和验证规则；
- **CandidateProposal 类似轻量构造请求**：绑定当前 state/residual，只描述一个可能动作；
- **NodeInstance 类似实例**：只有通过 admission 才获得完整上下文、执行预算和生命周期。

生成候选应当便宜；实例化和执行才是昂贵动作。

## 2. 对象生命周期

```text
CandidateTemplate -> body-free CandidateProposal(s)
  -> policy recommendation -> deterministic AdmissionDecision
  -> admitted NodeInstance OR rejected/expired minimal receipt
```

Proposal 不等于 node，CandidateSet 不等于 task tree，search simulation 不等于真实
execution history。

## 3. CandidateTemplate

Template 是不带任务正文的受信注册信息，只描述 identity/version、capability/schema、typed
trigger、authority/evidence requirements、cost/side-effect class 和 validator/adapter reference。
它不包含当前 Prompt/文件正文、hidden reasoning、未经 admission 的 scope 或自由控制字段。

Template registry 可借鉴插件“注册与运行分开”的设计，但它只登记可验证能力，不自动
授予执行权限。

### 3.1 Existing capability registry reuse gate

`CandidateTemplate` 首先是目标角色，不预先批准新 registry/contract。实现前必须优先比较
`PlanningSurfaceCard/Catalog`、`SkillSpec`、`ToolContractMetadata/ToolRegistry` 和现有 typed
task/decomposition capability/acceptance 描述。

只有这些结构无法表达一个重复出现、跨 policy 的候选能力，而且 adapter/view 会造成错误
ownership 时，才考虑新类型。禁止维护第二份 tool/skill/capability schema。

Template/adapter identity 必须由本地受信 registry 解析。模型 proposal 不能提交可执行
callable、module path、shell command、动态 import 或新的 tool schema；未知 template/version、
未声明字段和 adapter mismatch 在加载上下文前拒绝。

## 4. CandidateProposal

Proposal 是当前 state 上的 body-free/lightweight descriptor，绑定 proposal/template identity、
target/plan epoch、residual/acceptance、declared dependency/input/output、source evidence 和 expiry。
cost/risk/value prediction 只能作为 shadow 排序信号。

模型可以提出 intent 和理由，但 admission 只能消费 typed fields/evidence。自由理由不控制
权限、排序、完成或预算。

## 5. Candidate profiles

所有执行路径都先满足 Context Governance。随后有两条彼此独立的可选方向：

```text
plain Pi / root-only + Context Governance
  ├─ optional selective Context Optimization
  └─ optional explicit top-1 JIT
       -> top-k / bounded tree
       -> optional World Model
```

Context Optimization 不是 JIT 的前置条件；JIT 可以在 governed source baseline 上独立实验。
每个可选层都必须证明相对其直接基线的增量价值。任一层未通过质量、总成本、恢复或
复杂度门，就关闭该层并保留 Context Governance。

### 5.1 Root-only

不生成结构候选。当前 node 可以在一个 episode 内完成时，这是默认且理想路径。

### 5.2 Top-1 / final candidate

模型或 policy 只暴露最终选择的一个 successor。实际结构是一条 JIT dynamic chain。
它最接近普通 harness 的隐式选择，并最小化 proposal 开销；代价是不能审计候选分布或
直接切换未保留的备选。

### 5.3 Top-k body-free candidates

保留少量候选 descriptors，先验证/排序，只实例化被选中的一个。仅当存在真实互斥策略、
错误选择返工昂贵、validator 可靠且增量收益覆盖生成成本时才重新激活。

### 5.4 Bounded recursive/search frontier

只有一个候选被 admission 后，下一层才允许按需产生。禁止一次递归生成完整未来树。

## 6. 未选候选保留什么

默认只持久化 proposal/policy identity、plan epoch、selected/rejected/expired outcome、typed reason、
evidence refs 和 cost counters。不得保留 raw chain-of-thought、未选分支完整 Prompt/context、
预测文件/工具结果或未准入 scope。

当研究模式需要 top-k 内容时，也只保存有界 typed descriptors；原始模型输出按照 provider
evidence/redaction 规则处理，不能成为生产恢复依赖。

最小 receipt 同样受 trust/redaction/retention 规则约束：不保存 credential、敏感正文、
未经授权的路径内容或 raw reasoning；evidence reference 本身不扩大读取权限。

## 7. Candidate validation / admission

实例化前至少检查 schema/template、source/evidence、residual/acceptance、duplicate work、
dependency/readiness、permission/side effect、预算和 no-progress。具体字段与阈值由 S0/S1
protocol 冻结，不在 L2 预写。

模型预测的价值只作排序/shadow evidence。最终 admission 是 deterministic/typed policy。

## 8. SearchPolicyPort

Search policy 的 L2 seam 是“读取 bounded authoritative/derived view，返回 bounded typed
proposal/recommendation，并消费 observation/closure 更新可丢弃 policy state”。精确方法、
payload 和对象数量在 S0/S4 通过后进入 L3。最终选择由 deterministic admission 完成。Policy
不能：

- 写 store/checkpoint；
- 调用 Action Gateway；
- 创建权限；
- 声明验证通过；
- 删除执行历史；
- 把 simulation state 当成 authoritative next state。

## 9. Dormant search extensions

Top-k、best-first、DAG、MCTS/LATS 和 RAP-style World Model 均为 dormant，不能改变 metadata
kernel、permission 或 Evidence Core。若依次通过 JIT 和对应 S gate，仍必须满足：只持久化
admitted transition；simulated state 使用独立 namespace/budget；确定性 safety/admission 优先于
learned score；proposal/frontier/simulation/invalid/no-progress 都有显式上界；销毁未执行候选
不删除真实 evidence。算法接口、evaluator 和具体预算在重新激活后的 L3 中设计。

## 10. 短任务开销约束

- root-only 不产生 candidate-generation provider call；
- top-1 可以复用当前 episode 的 bounded typed exit payload；
- 未选 candidate 不加载完整上下文或执行环境；
- structural/growth tools 只在 typed trigger 出现时暴露；
- governance-only calls 和 tokens 必须单独计量。

## 11. Claim routing

本设计拥有 `SP-C01`、`SP-C02`、`SP-C03`、`SP-C04`、`SP-C05`、`SP-C06` 的语义；status、evidence 和 adoption gate 只在
[`EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md#3-claim-registry) 维护。当前 dormant 状态也
只能由该 index 重新激活。

## 12. 未决问题

- CandidateTemplate 是否能完全复用现有 capability registries？
- top-1 typed exit 是否能稳定复用同一 provider episode而无需额外调用？
- top-k/WorldModel 只有在 dormant claim 重新激活后才补充 interface 级问题。
