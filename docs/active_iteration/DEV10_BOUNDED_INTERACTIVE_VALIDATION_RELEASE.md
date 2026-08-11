# dev10 Bounded Interactive Validation Release

## Release identity

- Package version: `0.1.0.dev10`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.10`
- Previous release: `203daa1` / `v0.1.0-dev.9`
- Release date: 2026-08-11

## Observed failure

Real task `597fa8c0-472b-4171-8c95-9917c54553cc` declared
`python snake_game.py` as its authoritative validation command. dev8 correctly
preserved and executed that exact command, but the generated pygame application
entered its normal event loop. The first execution and its bounded retry each
timed out after 30 seconds. A later model-proposed substitute was correctly
rejected by exact-command admission, so the successfully written and independently
compilable game could not complete the overall task.

## Metadata and authority impact

No metadata schema, public contract, or `MetadataKind` changes. The decomposition
producer still owns the initial `Task.validation_command`; the task executor,
Router, Guard, project-environment binding, command receipt, and completion gate
continue to consume exactly that typed value. The new rule is a deterministic
producer-side normalization before `Task` construction, not a second command
authority and not a recovery-time command substitution. No migration is required.

## Implemented behavior

- The decomposition prompt requires validation to terminate without user input
  and forbids direct launch validation for games, GUIs, interactive programs,
  servers, and other long-running applications.
- For those task shapes only, a direct Python script command is rewritten to the
  same interpreter's bounded `-m py_compile` command when the exact script is
  grounded by decomposition `read_files` or `write_files`.
- An ungrounded direct-run target fails closed instead of selecting a similarly
  named file.
- Existing `pytest`, `py_compile`, and non-interactive terminating-script
  commands remain unchanged.

## Validation

- focused decomposer/relocation suite: **32 passed**;
- complete `Code/tests`: **1610 passed**;
- touched Ruff, compileall, and `git diff --check`: passed;
- final installed real task removed the prior tracked `snake_game.py`, regenerated
  a 238-line replacement through `code_generator` and `file_writer`, verified the
  mutation, then executed the exact typed command
  `python -m py_compile snake_game.py` and reached overall CLI `Success` without
  a direct game launch or 30-second validation timeout;
- implementation task `27064bc1-b8d5-433c-b169-02e7008483d8` and validation task
  `d9148521-46a5-45c7-ad93-22669b0ba485` both completed;
- independent `python3 -m py_compile snake_game.py`: passed;
- isolated wheel `openpilot-0.1.0.dev10-py3-none-any.whl`, SHA-256
  `ac8d0e4d08cf5030153847e1d8205f5c8a3e4c1d77838cb1bcc7726ba94ce9c2`;
- editable package and source versions both report `0.1.0.dev10`.

## Remaining boundary

This release does not claim behavioral UI testing for graphical applications.
`py_compile` proves bounded Python syntax/import compilation only. Richer headless
smoke tests require an explicitly authored terminating test entry point and must
remain the exact typed validation command.
