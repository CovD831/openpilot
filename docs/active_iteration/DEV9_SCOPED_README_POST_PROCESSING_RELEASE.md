# dev9 Scoped README Post-processing Release

## Release identity

- Package version: `0.1.0.dev9`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.9`
- Previous release: `d9ab585` / `v0.1.0-dev.8`
- Release date: 2026-08-11

## Observed failure

Real task `e0a97c3c-9f24-4db0-b841-01d3485f95c0` authorized only
`snake_game.py`. The tool planner correctly proposed project inspection, code
generation, the source write, and syntax validation, but also followed a broad
prompt instruction to create `/Users/abab/Developer/openpilot-experiment/README.md`.
The strict Subtask Write Scope gate rejected that unowned target before any tool
ran, so optional documentation prevented the authorized core artifact.

## Metadata and authority impact

No metadata schema or `MetadataKind` changes. `Task.write_files` remains the
sole write authority. The planner prompt receives a model-facing projection of
that list, but the projection grants nothing. Runtime filtering may discard only
explicit README post-processing outside the scope; every other unscoped
mutation still reaches the existing hard failure. An authorized README target
continues through Router, Guard, writer receipt, and completion evidence.

## Implemented behavior

- The tool-planning prompt displays the exact typed write targets and forbids
  mutation outside them.
- The previous unconditional README suggestion now states that README generation
  is legal only when the exact target appears in `Task.write_files`.
- `readme_generation` and `readme` are treated as optional
  post-processing only when their target is outside the typed scope. They are
  dropped with diagnostics while authorized core needs continue.
- A plan containing only an unauthorized README still fails because no
  actionable authorized need remains.
- Code, patch, delete, arbitrary file-write, and other unauthorized mutations
  retain the existing fail-closed behavior.

## Validation

- focused tool-planning suite: **118 passed**;
- complete `Code/tests`: **1604 passed**;
- touched Ruff, compileall, and `git diff --check`: passed;
- final installed real Snake project canary at
  `/tmp/openpilot-dev9-final-snake.wKEpJ6`
  generated and persisted only `snake_game.py`, performed mutation verification,
  ran the exact typed AST syntax command, completed the overall goal
  successfully, and passed independent `python3 -m py_compile`;
- the canary planner response contained no README need after receiving the typed
  write-scope prompt;
- isolated wheel `openpilot-0.1.0.dev9-py3-none-any.whl`, SHA-256
  `bb095fbfb92fcf3542f32a4481ca8bdfa452a1b872e45e057af49653c43ec469`;
- editable package and source versions both report `0.1.0.dev9`.

## Remaining boundary

This release does not automatically add README to a task's write scope and does
not synthesize documentation after delivery. Documentation must be explicitly
authorized by decomposition or requested in a separate typed task.
