# Metadata Control Plane Architecture Review Index

> Status: Active review index
> Authority: Routing only; reviews do not replace architecture, ADR, or evidence owners
> Owner: Architecture review
> Supersedes: None
> Last reviewed: 2026-08-31

| Review | Outcome |
| --- | --- |
| [`2026-08-31_ADVERSARIAL_REVIEW_CN.md`](2026-08-31_ADVERSARIAL_REVIEW_CN.md) | Conditional pass for architecture discussion; production implementation remains gated |
| [`2026-08-31_BIDIRECTIONAL_STEELMAN_CN.md`](2026-08-31_BIDIRECTIONAL_STEELMAN_CN.md) | Stable core is defensible; explicit JIT is conditional; tree/world-model remains optional research |
| [`2026-08-31_ADVERSARIAL_REVIEW_ROUND2_CN.md`](2026-08-31_ADVERSARIAL_REVIEW_ROUND2_CN.md) | Thin direction survives; context/core separation, executable triggers, hidden overhead, and net contraction remain required |
| [`2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND2_CN.md`](2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND2_CN.md) | Reframes the target as authority kernel + context governance + independently rejectable optimizations |
| [`2026-08-31_ADVERSARIAL_REVIEW_ROUND3_CN.md`](2026-08-31_ADVERSARIAL_REVIEW_ROUND3_CN.md) | ADR-0003 survives; narrows governance to OpenPilot-admitted request routes and requires honest request visibility/conformance levels |
| [`2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND3_CN.md`](2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND3_CN.md) | Keeps context governance as a cross-harness authority contract, not a universal Prompt builder or token-optimization claim |
| [`2026-08-31_ADVERSARIAL_REVIEW_ROUND4_FINAL_CN.md`](2026-08-31_ADVERSARIAL_REVIEW_ROUND4_FINAL_CN.md) | Final Phase 0B pass for an evidence-work baseline; production implementation remains gated |
| [`2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND4_FINAL_CN.md`](2026-08-31_BIDIRECTIONAL_STEELMAN_ROUND4_FINAL_CN.md) | Freezes the minimum architecture and moves unresolved questions to evidence-first validation |

Reviews are immutable snapshots of the assessed document state. Confirmed corrections are
applied to the architecture owners; a later review creates a new dated artifact rather than
rewriting the original reasoning.

Round-2 finding A2-01 has been adopted through
[`../adr/ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md`](../adr/ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md):
Context Governance is mandatory for every OpenPilot-admitted supported route, while selective
injection and related token optimizations remain independently gated. Round-3 scope/coverage findings are
adopted through
[`../adr/ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md`](../adr/ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md),
and the net-contraction/single-authority migration findings through
[`../adr/ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md`](../adr/ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md).
Remaining implementation uncertainties are routed to G/J/R/X/ME evidence rather than treated
as adopted production design.
