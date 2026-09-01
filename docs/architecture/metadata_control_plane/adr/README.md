# Metadata Control Plane ADR Index

> Status: Active index
> Authority: Routing only
> Owner: Architecture
> Supersedes: None
> Last reviewed: 2026-08-31

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| [`ADR-0001-METADATA-CONTROL-PLANE-REFACTOR.md`](ADR-0001-METADATA-CONTROL-PLANE-REFACTOR.md) | Accepted for development planning | Treat the next generation as an incremental metadata-control-plane refactor, preserve current authorities, and avoid a big-bang rewrite |
| [`ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md`](ADR-0002-THIN-CONTROL-PLANE-CONSTRAINTS.md) | Accepted for architecture planning | Keep the control plane thin, explicit only at durable/governed boundaries, and make search policies optional |
| [`ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md`](ADR-0003-CONTEXT-GOVERNANCE-AND-OPTIONAL-OPTIMIZATION.md) | Accepted for architecture planning | Require context governance on every OpenPilot-admitted supported route while keeping selective injection, summary, and on-demand expansion optional |
| [`ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md`](ADR-0004-OBSERVABLE-CONTEXT-GOVERNANCE-CONFORMANCE.md) | Accepted for architecture planning | Limit context guarantees to OpenPilot-admitted observable request routes, a bounded governed-source baseline, and declared-required coverage |
| [`ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md`](ADR-0005-NET-CONTRACTION-AND-SINGLE-AUTHORITY-MIGRATION.md) | Accepted for architecture planning | Measure migration by net complexity, permit bounded non-authoritative shadow representations, and keep one authoritative writer |

## ADR rule

Create an ADR for a cross-module, difficult-to-reverse choice involving authority,
dependency direction, persistence, compatibility, permission, harness boundaries, or
project-wide defaults. Do not use ADRs for ordinary implementation progress.

Accepted ADRs are immutable records. A changed decision gets a new ADR that explicitly
supersedes the old one.

## Terminology narrowing

- ADR-0003 的 `governed full-source` / `every harness route` 是较早表述；当前规范术语为
  `governed source baseline` / `every OpenPilot-admitted supported route`，由 ADR-0004 收窄。
- 这是一条索引级解释指针，不回写不可变 ADR-0003，也不把旧表述重新提升为 current term。
