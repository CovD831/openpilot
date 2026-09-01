# Metadata Control Plane L2 Design Index

> Status: Active routing index
> Authority: Routing only; each linked document owns its subsystem design
> Owner: Architecture
> Supersedes: None
> Last reviewed: 2026-08-31

These documents expand the L1 target architecture into implementable subsystem semantics.
They define invariants, interfaces, state machines, open claims, experiments, and fallback
boundaries without claiming that production migration has happened.

| Document | Responsibility |
| --- | --- |
| [`CURRENT_TO_TARGET_MAPPING_CN.md`](CURRENT_TO_TARGET_MAPPING_CN.md) | Current assets/hotspots, keep/extract/replace/delete mapping, ports, and strangler order |
| [`METADATA_DOMAIN_MODEL_CN.md`](METADATA_DOMAIN_MODEL_CN.md) | Kernel, authoritative entities, relationships, gates, evidence, persistence classes, and derived graph |
| [`CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md`](CONTROL_PLANE_RUNTIME_PROTOCOL_CN.md) | Root-only and JIT runtime sequence, NodeInstance/NodeVisit lifecycle, proposal/admission, scheduling, and closure |
| [`CONTEXT_PROJECTION_CN.md`](CONTEXT_PROJECTION_CN.md) | Mandatory source/trust/freshness/budget/fallback governance, plus optional selectors, projection, on-demand evidence, summary, and consumption optimization |
| [`SEARCH_POLICY_AND_CANDIDATES_CN.md`](SEARCH_POLICY_AND_CANDIDATES_CN.md) | Template/proposal/instance separation, top-1/top-k, chain/tree/DAG/MCTS/LATS/RAP policy boundary |
| [`DURABILITY_RECOVERY_CN.md`](DURABILITY_RECOVERY_CN.md) | Run/revision/cursor/checkpoint consistency, crash windows, resume, freshness, and local rework |

## Level rule

- L1 answers why/what/boundaries.
- L2 answers subsystem semantics and interactions.
- L3 is added only for an accepted implementation slice: concrete interfaces, migration,
  failure semantics, and tests.

Experiment protocol and raw results do not live here. Each unresolved L2 claim links through
[`../EVIDENCE_INDEX_CN.md`](../EVIDENCE_INDEX_CN.md) to an immutable experiment route.

The current adversarial and steelman review is routed through
[`../reviews/README.md`](../reviews/README.md).
