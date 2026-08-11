# dev11 Interactive Delivery Handoff Release

## Release identity

- Package version: `0.1.0.dev11`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.11`
- Previous release: `d01fcff` / `v0.1.0-dev.10`
- Release date: 2026-08-11

## Observed failure

A real generated pygame Snake run completed one selected improvement, but the
CLI reported only an aggregate `1/1` count. The accepted transaction actually
added a visible score renderer to `snake_game.py` (8 inserted lines), yet the
user saw neither the action nor changed-file evidence. The iteration-count
question did not explain that it controlled code-upgrade rounds rather than app
runs, and no post-iteration delivery step offered to start the new version.

Release canaries exposed three related handoff defects. GUI evaluation imported
pygame modules and could hang on top-level initialization; recovery then deep-
copied an LLM client containing a thread lock. A later run selected score display
even though the generated file already had it because the bounded project preview
contained only the file prefix. Finally, the durable runtime returned the full
iteration result under `session_result`, while the CLI read only wrapper fields,
so it rendered a generic success message and skipped launch eligibility.

## Metadata and authority impact

No new metadata kind or schema field. The launch path reuses the existing ready
`EnvironmentSyncMetadata` as project/run-command authority and the existing
typed `ToolExecutionContext.user_confirmed` as confirmation authority. The
confirmation object travels only through `ToolInputMetadata.runtime_handles`,
which is excluded from serialization and Provider schemas. `Task.validation_command`
and validation receipts remain unchanged and cannot be satisfied by launch.

## Implemented behavior

- The iteration question explains code-upgrade count, non-launching validation,
  final change summary, and the later launch confirmation.
- Completion shows accepted actions, changed file basenames, validation status,
  and the exact command for running the project.
- A successful interactive CLI task backed by a ready
  `interactive_runtime` environment asks whether to launch the newest version.
- Confirmation starts the exact project-owned command as a detached argv process
  using the typed cwd/environment and reports its PID.
- Provider requests cannot set confirmation; absent or untyped confirmation
  fails closed. Once/non-interactive routes show the command without launching.
- Interactive GUI validation uses bounded compile-only execution while retaining
  warning classification and static rejection of unguarded top-level event loops.
- Durable tool-input copies exclude runtime-only handles, so clients containing
  locks remain usable without entering checkpoint serialization.
- Long project files contribute bounded head-and-tail evidence and the analysis
  prompt rejects improvements already visible there.
- Checkpointed runtime wrappers are unwrapped at the delivery boundary so the CLI
  reads the authoritative iteration actions/files and project environment.

## Validation

- focused final regression set: **185 passed**;
- complete `Code/tests`: **1623 passed**;
- touched Ruff, compileall, and `git diff --check`: passed;
- installed editable source and package version: `0.1.0.dev11`;
- isolated wheel `openpilot-0.1.0.dev11-py3-none-any.whl`, SHA-256
  `435d07b0c9e05d581dfa446e00fbf5c4f96cf98a6dab369074507899a347f77b`;
- fresh real project `/tmp/openpilot-dev11-final-snake.j9936j` generated and
  compiled `snake_game.py`, accepted one restart/game-over UX improvement, and
  displayed its exact action, changed file, validation status, and run command;
- confirmed launch returned PID `5322`; after the CLI exited, the process remained
  alive with parent PID `1`, proving independent lifecycle. The canary process was
  then explicitly terminated after evidence capture.

## Remaining boundary

Detached launch reports successful process startup, not ongoing health. The user
closes the application window to terminate it; future process supervision would
need a separate typed lifecycle contract rather than reusing validation.
