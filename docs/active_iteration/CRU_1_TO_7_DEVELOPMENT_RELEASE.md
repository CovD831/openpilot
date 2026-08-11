# CRU 1 Through 7 Development Release

## Release identity

- Package version: `0.1.0.dev6`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.6`
- Remote baseline: `origin/main` at `21c8e66`
- CRU-4B functional freeze: `39b1fab`
- CRU-7 accepted source: `c6b33db`
- Prior development hardening: `a06853f` / `v0.1.0-dev.2`
- Prior cumulative release: `fd49b09` / `v0.1.0-dev.3`
- Prior admission release: `e90169a` / `v0.1.0-dev.4`
- Prior project-scope release: `4c39f2b` / `v0.1.0-dev.5`
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
- dev4 admission hardening: typed positive response admission for lightweight
  and current-external questions; development, artifact creation, mutation,
  execution/validation, and ambiguous requests fail safe to project execution.
  Bounded response, external evidence, and project execution failures have
  distinct credential-redacted CLI stages.
- dev5 project-scope hardening: broad launch roots select an unused generated
  child for artifact creation, while ambiguous existing-project work stops
  recoverably. Project file discovery is breadth-first with hard file,
  directory, entry, and depth ceilings instead of eager recursive sorting.
- dev6 generated-code persistence hardening: when a code-generation need omits
  its writer but the typed task contract authorizes exactly one `write_files`
  target, tool planning deterministically appends `file_writer`. The existing
  artifact handoff supplies the generated content, while Guard, write scope,
  mutation receipt, verification, and completion evidence remain mandatory.

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

The local development edition uses a typed, controller-owned pre-task admission.
Explicit repository/file/path work, natural development/build/mutation intents,
execution/validation requests, and ambiguous inputs keep the top-level
`autonomous_iteration` route but enter project-task execution instead of the
zero-tool response step. Lightweight conversation, deterministic runtime facts,
knowledge-only questions, and current-external questions use the unified
response/evidence path. This is a local release hardening on top of the frozen
CRU-7 result, whose environment had no live external Provider or project-mutation
evidence.

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

Merged dev6 evidence recorded before release:

- tool-planning, runtime-controller, and tool-I/O focused tests: **221 passed**;
- merged complete `Code/tests`: **1582 passed**;
- touched Ruff, `compileall`, and `git diff --check`: passed.

- isolated wheel: `openpilot-0.1.0.dev6-py3-none-any.whl`, SHA-256
  `1526f4881b44cd2abb98377051a6b1ea5ec0bd30be6ad650a157bd71eb0869a2`;
- editable install reports version `0.1.0.dev6` from this release worktree;
- real `openpilot-dev` once-mode smoke completed a greeting and fresh structured
  Changshu weather. An isolated Snake-game request entered project inspection,
  decomposition, environment setup, and `code_generator`; it did not call the
  bounded response/evidence path. The generator then stopped fail-closed at its
  independent completion limit and reported `Task Executor / code_generator`;
- dev5 broad-root smoke started from a temporary container holding two sibling
  repositories, selected and initialized only its `snake-game` child, and bound
  runtime state, environment, path resolutions, checkpoints, and project
  fingerprint to that child. No parent-container recursive scan occurred;
- dev6 live writer smoke generated `hello.py`, synthesized `file_writer` from
  the single typed write scope, wrote the generated artifact, and passed an
  independent `py_compile`. The subsequent decomposed validation task exposed
  a separate command-contract mismatch and is not counted as end-to-end task
  success;
- the cumulative merge is sealed by tag `v0.1.0-dev.6`.

## Known limitations

- The accepted CRU-7 result does not claim live Provider token/call/latency
  superiority; its environment had no external Provider credential.
- A transient Provider timeout remains an explicit fail-closed outcome and may
  be retried by the user; it is never converted into fabricated evidence.
- `wttr.in` availability is an external dependency for the structured weather
  path.
- Large single-call code generation may still reach the generator completion
  limit; that is reported as a project task/tool failure and is not retried as
  a lightweight response.
- A separately decomposed validation task can still fail when its model-proposed
  command does not exactly match its typed validation contract. This does not
  undo an already observed writer receipt, but the overall task remains failed.
- Post-core enhancement transaction execution remains outside this release
  until an authoritative consumer is accepted.
- CRU-4B still forbids replay of an indeterminate Provider transport outcome.
