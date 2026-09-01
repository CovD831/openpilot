# OpenPilot Architecture Documentation

> Status: Active index
> Authority: Routing only; it does not replace the linked contracts or decisions
> Owner: Architecture
> Supersedes: None
> Last reviewed: 2026-08-31

This directory has one job: route readers to the current architecture authority
without turning plans, experiments, and historical notes into competing specifications.

## Current adopted decisions

- [`OPENPILOT_PI_RUNTIME_DECISION.md`](OPENPILOT_PI_RUNTIME_DECISION.md): the adopted Pi
  runtime dependency, process, permission, and rollout boundary.
- [`ADR-OPENPILOT-HARNESS-EVIDENCE-PHASE0-1.md`](ADR-OPENPILOT-HARNESS-EVIDENCE-PHASE0-1.md):
  the adopted Harness / Evidence Core identity and persistence boundary.
- [`OPENPILOT_HARNESS_EVIDENCE_CONTRACTS_CN.md`](OPENPILOT_HARNESS_EVIDENCE_CONTRACTS_CN.md):
  the current Harness / Evidence contract description.
- [`OPENPILOT_HARNESS_EVIDENCE_REFACTOR_PLAN_CN.md`](OPENPILOT_HARNESS_EVIDENCE_REFACTOR_PLAN_CN.md):
  the existing implementation-oriented refactor plan. It remains evidence about the
  current generation and is not the new-generation project charter.

## New-generation metadata control plane

The development entry point is
[`metadata_control_plane/README.md`](metadata_control_plane/README.md).

That program treats OpenPilot as a metadata-first control plane around a replaceable
execution harness. Its documents distinguish:

- current executable authority;
- target architecture;
- adopted decisions;
- migration roadmap;
- evaluation evidence;
- historical material.

No target document changes production behavior by itself. Implementation authority still
comes from accepted code, tests, metadata contracts, `AGENTS.md`, and `API.md`.

## Maintenance rule

Architecture decisions belong in an ADR. Implementation sequencing belongs in one active
roadmap. Experiment outcomes belong in an evidence index. Do not create another
top-level phase document when one of those existing owners can be updated.
