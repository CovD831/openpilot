# Metadata Control Plane Development Index

> Status: Active development index
> Authority: Canonical route for the new-generation architecture program
> Owner: Architecture
> Supersedes: None; current implementation contracts remain authoritative
> Last reviewed: 2026-09-01

## 1. What must exist before implementation starts

A rewrite-scale refactor needs a small, explicit development packet. OpenPilot now maps
that packet as follows:

| Needed document | Canonical owner | Purpose |
| --- | --- | --- |
| Project charter / product positioning | [`PROJECT_CHARTER_CN.md`](PROJECT_CHARTER_CN.md) | Why the project exists, users, goals, non-goals, and competitive claim |
| Current-system baseline | `AGENTS.md`, `API.md`, `Code/src/metadata/`, existing adopted ADRs | What is implemented and enforceable today |
| Target architecture | [`TARGET_ARCHITECTURE_CN.md`](TARGET_ARCHITECTURE_CN.md) | Layers, dependencies, authority flow, module boundaries, and invariants |
| L2 subsystem architecture | [`design/README.md`](design/README.md) | Current-to-target mapping, metadata domain model, runtime, context, search/candidates, durability/recovery |
| Metadata kernel and evolution protocol | [`METADATA_EVOLUTION_CN.md`](METADATA_EVOLUTION_CN.md) | Stable kernel, registry, versioning, migration, deprecation, and removal |
| Migration / refactor roadmap | [`REFACTOR_ROADMAP_CN.md`](REFACTOR_ROADMAP_CN.md) | Small slices, dependency order, entry/exit gates, and rollback boundaries |
| Evaluation and experiment plan | [`EVALUATION_PLAN_CN.md`](EVALUATION_PLAN_CN.md) | Baselines, claims, measurements, and release thresholds |
| Claim/evidence register | [`EVIDENCE_INDEX_CN.md`](EVIDENCE_INDEX_CN.md) | L2 claim status, experiment route, ADR, and adoption gate |
| Architecture reviews | [`reviews/README.md`](reviews/README.md) | Adversarial findings, applied corrections, remaining blockers, and bidirectional steelman |
| Architecture decisions | [`adr/README.md`](adr/README.md) | Why an irreversible or cross-cutting choice was made |
| Documentation governance | [`DOCUMENTATION_GOVERNANCE_CN.md`](DOCUMENTATION_GOVERNANCE_CN.md) | One-owner rule, status lifecycle, update matrix, and archive rules |
| Historical/evidence index | [`HISTORICAL_DOCUMENT_INDEX_CN.md`](HISTORICAL_DOCUMENT_INDEX_CN.md) | Classifies old collections without deleting or rewriting evidence |
| Reviewable baseline and B1 pin | [`../../../experiments/metadata_control_plane/spikes/x0_reviewable_baseline/README_CN.md`](../../../experiments/metadata_control_plane/spikes/x0_reviewable_baseline/README_CN.md) | Enumerates drift, protects historical evidence, and pins a clean commit while excluding the dirty worktree |
| Operations and recovery | [`../../runtime_recovery/README.md`](../../runtime_recovery/README.md) and root loop protocols | Crash, resume, reconciliation, and supervisor boundaries |
| Testing policy | [`../../testing/TEST_DESIGN_GUIDE.md`](../../testing/TEST_DESIGN_GUIDE.md) | Contract, trajectory, safety, recovery, and end-to-end test design |

This is intentionally a finite set. New development updates these owners instead of
creating a new `PHASE_*` document for every slice.

## 2. Authority model

The documents describe different kinds of truth and must not be blended:

1. **Current executable authority**: `Code/src/metadata/`, accepted production code,
   tests, `AGENTS.md`, and `API.md`.
2. **Adopted decisions**: accepted ADRs and explicit runtime decisions.
3. **Target design**: this directory. It guides migration but does not claim a feature is
   implemented.
4. **Roadmap**: planned order and gates; it is mutable and never proves completion.
5. **Evidence**: experiment manifests, receipts, results, and implementation logs.
6. **Historical/superseded material**: useful provenance with no current authority.

If two current authorities conflict, work stops until the conflict is reconciled. A target
document never silently overrides a current contract.

## 3. Project position in one sentence

> OpenPilot is a metadata-first control plane for long-running agents: it uses evolvable
> typed metadata to govern durable state, permissions, evidence, context boundaries,
> validation, and recovery while keeping the underlying harness and optional policies
> replaceable.

Pi is the current execution plane. It is not the owner of OpenPilot task authority,
permission, evidence, or durable recovery semantics.

The adopted scope is a **thin** control plane: Pi keeps ordinary reasoning and tool
selection inside one admitted episode. OpenPilot makes decisions explicit only across
permission, side-effect, validation, context, persistence, recovery, or other durable
boundaries. JIT chains, trees, and world models remain optional experiment-gated policies.
Context governance applies to every OpenPilot-admitted model-request route at its declared
conformance level; selective injection, summary, and on-demand expansion are separately
gated optimizations.

## 4. Reading paths

### 4.1 Minimum path

新参与者和普通实现切片只需按顺序阅读：

1. [`PROJECT_CHARTER_CN.md`](PROJECT_CHARTER_CN.md)：项目定位和不做什么；
2. [`TARGET_ARCHITECTURE_CN.md`](TARGET_ARCHITECTURE_CN.md)：系统边界和稳定不变量；
3. [`REFACTOR_ROADMAP_CN.md`](REFACTOR_ROADMAP_CN.md)：当前阶段和退出门；
4. 当前切片对应的一份 [L2 design](design/README.md)。

### 4.2 Reference path

- 需要理解已采用决定时读 [ADR index](adr/README.md)，其中包含 ADR-0001；
- 修改 metadata 时读 [`METADATA_EVOLUTION_CN.md`](METADATA_EVOLUTION_CN.md) 和
  [`../../metadata/README.md`](../../metadata/README.md)；
- 设计或解释实验时读 [`EVALUATION_PLAN_CN.md`](EVALUATION_PLAN_CN.md) 和
  [`EVIDENCE_INDEX_CN.md`](EVIDENCE_INDEX_CN.md)；
- 维护文档或历史材料时读
  [`DOCUMENTATION_GOVERNANCE_CN.md`](DOCUMENTATION_GOVERNANCE_CN.md) 和
  [`HISTORICAL_DOCUMENT_INDEX_CN.md`](HISTORICAL_DOCUMENT_INDEX_CN.md)；
- 对抗审查是 evidence，按需从 [review index](reviews/README.md) 进入，不属于日常必读路径。

## 5. Current development state

- Working branch: `codex/metadata-control-plane-refactor`.
- Phase 0A (L1 architecture and documentation governance): completed on 2026-08-31.
- Phase 0B (L2 architecture and claim/evidence binding): completed and frozen for
  architecture decisions after four adversarial/steelman rounds. X0 owner adjudication and B1
  pin are complete; this is not production implementation approval or a broad-staging grant.
- Control Plane V1 的必选产品边界、L3 interface minimum、composition freeze、六个纵向切片和
  integration conformance gate 已定义；具体 port 签名和 package map 仍须由各切片在 ME0 后冻结。
- Production implementation: not started by this document set.
- Existing experiments: retained as evidence; they do not authorize global defaults.
- Existing uncommitted work: preserved on the branch; no reset, stash, or bulk deletion was
  performed when the branch was created.
- X0 verdict: `reviewable_baseline_ready`; protected tracked deletions were resolved by the
  owner-approved exact-path restore, with current status routed to the X0 runs. B1 is pinned to the commit in
  [`b1_baseline.json`](../../../experiments/metadata_control_plane/spikes/x0_reviewable_baseline/b1_baseline.json),
  and the current dirty worktree is excluded. X0 itself still grants no restore/delete/stage
  authority.

Production refactoring still has not started. The next allowed work is read-only inventory,
experiment protocols, and shadow validation. Production slices remain gated by
[`REFACTOR_ROADMAP_CN.md`](REFACTOR_ROADMAP_CN.md).
