# CRU 1 Through 8 Development Release

## Release identity

- Package version: `0.1.0.dev7`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.7`
- Previous release: `46e1ed4` / `v0.1.0-dev.6`
- Remote baseline: `origin/main` at `21c8e66`
- CRU-4B functional freeze: `39b1fab`
- Release date: 2026-08-11

This development release contains the full CRU-1 through CRU-8 ancestry. It
preserves the CRU-7 unified entry and the dev4–dev6 admission, project-scope,
bounded-inventory, and durable writer hardening, then closes the real Snake-game
code-generation completion-limit failure.

## CRU-8 behavior

- Explicit provider context-window and output capabilities bound request
  construction; model names and endpoint strings never imply capability.
- Prompt assembly uses the smallest of the configured ceiling, the soft
  context-window fraction, and context-window minus planned output and safety
  reserve. Input compaction remains separate from output-length recovery.
- The shared enhancement completion pool is 64,000 tokens. Code generation uses
  an 8,000-token floor, 16,000-token initial ceiling, and one recovery ceiling of
  32,000 tokens, always capped by the configured provider maximum output.
- A single typed post-plan file target requests disabled reasoning when supported.
  Ambiguous or multi-target generation retains provider-default reasoning.
- An observed `length` response is reconciled and discarded. With known usage,
  the full source may be regenerated once under a larger source-linked
  reservation. Unknown usage, no larger legal reservation, or a second length
  returns `decompose_required`; truncated source never becomes a CodeArtifact and
  never reaches the synthesized writer.
- Tool planning projects the authoritative single `Task.write_files` target into
  generator input and prompt context so reasoning policy and durable writer
  chaining share the same typed scope.

## Runtime configuration

The local launcher explicitly configures the verified development-provider
capabilities:

```text
OPENPILOT_LLM_REASONING_CAPABILITY_PROFILE=deepseek-chat-known
OPENPILOT_LLM_CONTEXT_WINDOW_TOKENS=1000000
OPENPILOT_LLM_MAX_OUTPUT_TOKENS=384000
OPENPILOT_CONTEXT_MAX_PROMPT_TOKENS=700000
OPENPILOT_CONTEXT_SOFT_LIMIT_RATIO=0.7
OPENPILOT_CONTEXT_SAFETY_RESERVE_TOKENS=20000
```

The existing CRU-7 defaults remain unchanged: unified entry and governed
decomposition are enabled; model-visible protocol repair and core/post-core
integration remain disabled.

## Validation

- focused CRU-8 budget, code-generation, tool-planning, and writer-safety suite:
  **147 passed**;
- complete `Code/tests`: **1597 passed**;
- touched Ruff, compileall, and `git diff --check`: passed;
- isolated wheel `openpilot-0.1.0.dev7-py3-none-any.whl`, SHA-256
  `2221d2387f8204c493675f9cf89c9364d747f7298b15191cfb7566932a074079`;
- editable install reports `0.1.0.dev7` from this worktree.

Real canary evidence:

- an exact Snake request generated and persisted a 163-line `snake_game.py`,
  traversed `code_generator -> file_writer -> mutation verification -> exact
  validation`, and passed independent `python3 -m py_compile`;
- a subsequent single-file request recorded requested and resolved reasoning as
  `disabled` under `deepseek-chat-known`, with exact capability resolution;
- one later Snake request was correctly blocked before generation when the model
  planner proposed unauthorized `README.md`; this is a separate planner-quality
  limitation, not a generation-budget regression;
- one hello task wrote valid code but later failed an independently decomposed
  validation-command contract. The writer receipt remains valid, while overall
  completion correctly stays failed.

## Known limitations

- The one-shot recovery does not recursively increase output budgets. A second
  limit outcome requires decomposition.
- Planner-proposed files outside `Task.write_files` remain fail-closed and may
  require a better plan before generation starts.
- Independently decomposed validation can still fail when a model-proposed
  command does not match the typed exact-validation contract.
- Provider capability values are operator-owned configuration and must be
  updated when the deployed provider contract changes.
