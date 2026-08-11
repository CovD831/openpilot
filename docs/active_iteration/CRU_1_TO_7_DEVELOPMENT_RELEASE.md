# CRU 1 Through 7 Development Release

## Release identity

- Package version: `0.1.0.dev3`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.3`
- Remote baseline: `origin/main` at `21c8e66`
- CRU-4B functional freeze: `39b1fab`
- CRU-7 accepted source: `c6b33db`
- Prior development hardening: `a06853f` / `v0.1.0-dev.2`
- Release date: 2026-08-11

This cumulative development release merges the complete CRU-1 through CRU-7
ancestry into the existing local development edition. It preserves the dev2
real-network/evidence hardening while adding CRU-5 active diagnostic state,
CRU-6 verified core/post-core handoff, and CRU-7 canary/default decisions.

## Included cumulative boundary

- CRU-1 autonomous decomposition error containment and recoverability.
- CRU-2A conversation-owned pre-task state, durable generation storage,
  assistant ledger recovery, and canonical task materialization.
- CRU-2B deterministic runtime-fact completion.
- CRU-2C bounded zero-tool model response.
- CRU-2D source-compatible read-only evidence escalation.
- CRU-3 governed decomposition and evidence execution bridge.
- CRU-4A one bounded model-visible protocol repair, retained default-off.
- CRU-4B replay-free durable Provider observation recovery.
- CRU-5 task-owned typed conflicts, risks, active diagnostic decisions,
  content-sensitive progress, and three-arm development comparison.
- CRU-6 verified core readiness, exact core completion handoff/package, and
  layered core/post-core/overall result composition.
- CRU-7 frozen 12-category/four-path usability matrix, non-compensating safety
  gates, default-on unified entry/governed decomposition, and explicit legacy
  rollback switches.
- dev2 hardening: Chinese claim-boundary compatibility, original-question
  external evidence, evidence-derived response revisions, bounded structured
  `wttr.in` weather lookup, and non-replayable fresh web evidence checkpoints.

## Runtime defaults and rollback

The package defaults are:

```text
OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED=true
OPENPILOT_GOVERNED_DECOMPOSITION=true
OPENPILOT_MODEL_VISIBLE_PROTOCOL_REPAIR=false
OPENPILOT_CORE_POST_CORE_INTEGRATION=false
```

Setting unified entry and governed decomposition to `false` restores the
bounded legacy autonomous lane. Agent Generator routing and its pipeline are
unchanged.

The local development edition retains a dev2 safety admission around explicit
repository/file/path tasks: those inputs keep the top-level
`autonomous_iteration` route but use the legacy project-task autopilot rather
than allowing a zero-tool file-access refusal to become a successful response.
Lightweight conversation, deterministic runtime facts, and current-external
questions use the unified response path. This is a local release hardening on
top of the frozen CRU-7 result, whose environment had no live external Provider
or project-mutation evidence.

Model-visible repair remains default-off because the CRU-7 default-on trial
regressed duplicate/no-progress behavior. Core/post-core integration remains
default-off because no accepted PKG3/PKG4 transaction consumer exists; package
construction alone does not authorize enhancement execution.

## Validation

Source CRU-7 evidence recorded:

- focused twelve-category/four-path selection: **21 passed**;
- canary evaluator and three-arm gates: **15 passed**;
- source branch complete `Code/tests`: **1531 passed**;
- all pre-registered safety counters remained zero.

Merged dev3 evidence recorded before release:

- CRU-5/6/7 plus dev2 overlap tests: **168 passed**;
- merged complete `Code/tests`: **1546 passed**;
- merged canary evaluator/three-arm tests: **15 passed**;
- touched Ruff, `compileall`, JSON validation, and `git diff --check`: passed.

- isolated wheel: `openpilot-0.1.0.dev3-py3-none-any.whl`, SHA-256
  `3810cd91f516449c7ccfb360234026dfcb957960f58a9cff54d91522ce4e1412`;
- editable install reports version `0.1.0.dev3` from this release worktree;
- interactive `openpilot-dev` smoke in one session completed a greeting,
  deterministic model identity, and fresh structured Changshu weather;
- the cumulative merge is sealed by tag `v0.1.0-dev.3`.

## Known limitations

- The accepted CRU-7 result does not claim live Provider token/call/latency
  superiority; its environment had no external Provider credential.
- A transient Provider timeout remains an explicit fail-closed outcome and may
  be retried by the user; it is never converted into fabricated evidence.
- `wttr.in` availability is an external dependency for the structured weather
  path.
- Post-core enhancement transaction execution remains outside this release
  until an authoritative consumer is accepted.
- CRU-4B still forbids replay of an indeterminate Provider transport outcome.
