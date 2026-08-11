# dev8 Typed Validation Handoff Release

## Release identity

- Package version: `0.1.0.dev8`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.8`
- Previous release: `081a335` / `v0.1.0-dev.7`
- Release date: 2026-08-11

## Observed failure

Real task `637cec4f-b1da-4fe8-9769-82d94f260074` owned the exact validation
command `python -m py_compile snake_game.py`. The tool-planning prompt did not
project that typed field, so the model independently proposed
`python -m compileall /Users/abab/Developer/openpilot-experiment/snake_game.py`.
The substitute was safe and would also check syntax, but exact-command admission
correctly rejected it. The preceding generator, writer, mutation verification,
and independent `py_compile` evidence all succeeded.

## Metadata and authority impact

No metadata schema or `MetadataKind` changes. `Task.validation_command` remains
the sole command authority. The deterministic handoff creates only a routed
`DecisionNeedMetadata` projection and does not grant command, path, environment,
or completion authority. Router, Guard, project-interpreter binding, execution
receipt, and exact completion evidence remain mandatory.

## Implemented behavior

- Non-mutating inspect/inspection/validate/validation/verify/verification/test
  tasks with a non-empty typed command route exactly one deterministic
  `command_check` before any model call.
- The command uses automatic mode, a bounded timeout, and the original command as
  both requested command and test-command evidence.
- The existing strict model-plan filter remains active for any non-deterministic
  path: substitute commands, extra commands, and validation-task mutation needs
  are still rejected.
- Validation tasks without a typed command remain fail-closed.
- The existing exact-command fallback now reuses the same canonical typed plan
  instead of maintaining a second command projection.

## Validation

- focused tool-planning suite: **114 passed**;
- complete `Code/tests`: **1600 passed**;
- touched Ruff, compileall, and `git diff --check`: passed;
- final installed real canary executed `test -f snake_game.py` and
  `python -m py_compile snake_game.py` as two exact typed command receipts, made
  no planning-model call inside either subtask, and completed the overall goal
  successfully;
- isolated wheel `openpilot-0.1.0.dev8-py3-none-any.whl`, SHA-256
  `80cef7696fab3cb86438abd3e41fc29e9e057214c2c51292b66502ec4603cabf`;
- editable package and source versions both report `0.1.0.dev8`.

## Remaining boundary

This release does not reinterpret or improve a bad typed validation command. If
decomposition selects the wrong command, the exact wrong command will still run
subject to existing command policy. Improving validation-command selection is a
separate decomposition-quality concern.

The first dev8 canary also showed that decomposition can attach an exact
existence check such as `test -f snake_game.py` to an `inspect` subtask. The
deterministic lane therefore covers inspection as well as validation kinds; it
does not cover implementation tasks or any task with write scope.
