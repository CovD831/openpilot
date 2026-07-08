# OpenPilot

OpenPilot is an autonomous AI coding agent. Given a natural-language goal, it classifies
the task, decomposes it into steps, and drives a tool-based execution loop (read/write
files, run code and shell commands, search, evaluate, and iterate) until the goal is met
and verified. It is built around a single modern execution path centered on
`IntelligentAutopilot`, using an **Agent + Tool protocol** architecture with strict
Pydantic v2 contracts between every component.

This document is the handover guide. It covers what the project is, how to run it, how the
code is laid out, and the open issues a new maintainer should know about.

---

## 1. Quick Start

The Python package lives in the [`Code/`](Code/) directory (`openpilot`).

```bash
# 1. Create an environment (Python 3.11+ required)
conda create -n openpilot python=3.11 -y
conda activate openpilot

# 2. Install the package and its dependencies
cd Code
pip install -r requirements.txt
pip install -e .

# 3. Configure credentials (see section 2)
cp .env.example .env      # then edit .env and fill in your API key

# 4. Verify configuration
openpilot config check
```

See [INSTALL.md](INSTALL.md) for venv-based setup and troubleshooting.

## 2. Configuration

OpenPilot talks to any **OpenAI-compatible** chat + embedding endpoint. Configure it via a
`.env` file in `Code/` (or via real environment variables). Copy
[`Code/.env.example`](Code/.env.example) and fill in the blanks:

```bash
OPENPILOT_LLM_BASE_URL=https://your-provider.example/v1
OPENPILOT_LLM_API_KEY=your-api-key
OPENPILOT_LLM_MODEL=your-chat-model

# Embeddings inherit the LLM base URL/key unless these are set explicitly.
OPENPILOT_EMBEDDING_MODEL=text-embedding-3-small
OPENPILOT_EMBEDDING_BASE_URL=
OPENPILOT_EMBEDDING_API_KEY=
```

> **Security note for the new owner:** `.env` files are intentionally **not** tracked in
> git. Never commit real keys. (See section 6 — earlier commits in history did contain
> live keys, which have since been removed from tracking and should be rotated.)

## 3. Usage

```bash
# Interactive session
openpilot run

# Run a single goal and exit
openpilot run --once "Create a Python project in /tmp/demo"

# Run with N improvement iterations (0–5)
openpilot run --once "Build a CLI todo app" --improvement-iterations 2
```

Inside the interactive session, type a task with no leading slash to execute it. Slash
commands:

| Command   | Description                       |
| --------- | --------------------------------- |
| `/config` | Show current LLM configuration    |
| `/help`   | Show command help                 |
| `/clear`  | Clear the screen                  |
| `/exit`   | Exit                              |

Entry point: `openpilot = ui.cli:main` (defined in [`Code/pyproject.toml`](Code/pyproject.toml)).

## 4. Architecture

The active runtime path:

```text
ui.cli -> ui.enhanced_cli -> tools.task_classifier
        -> agent_generator.runner OR autonomous_iteration.IntelligentAutopilot
        -> planning surface (need catalog + capability cards)
        -> autonomous_iteration.AgentRuntimeController
        -> core.SemanticAnalyzer / autonomous_iteration.agents.TaskDecomposer
        -> RuntimeGuard / ToolRouter / FileSelector / EditGuard
        -> StateUpdater / RuntimeVerifier / RuntimeReporter
        -> core.ToolEventLoopRunner / tools.ToolExecutor -> built-in tools
        -> agents.ProjectEvaluatorAgent / ProjectImprovementRuntime
        -> memory + logs + enhanced UI dashboard
```

The runtime is **phase-driven**. `AgentRuntimeController` maintains an explicit
`RuntimeStateMetadata` (current phase, known facts, unknowns, path intents/resolutions,
candidate/selected files, planned edits, modified files, tool history, verification
status, risk, and bounded budgets). `RuntimeGuard` owns budget/risk/confirmation/stop-condition policy; `ToolRouter`
maps decision needs to tools; `FileSelector` promotes evidence-backed candidates to
selected files; `EditGuard` approves scoped edit plans; `StateUpdater` folds tool results
back into state. **Any write or code/shell execution that changes project state must be
followed by verification (`RuntimeVerifier`) before the runtime may report success.**
When a project root is known, the same path-governance layer now grounds not
only file tool inputs but also absolute path fragments inside command strings,
so hallucinated roots such as `/workspace/openpilot/...` can be corrected and
out-of-project absolute paths can be blocked before execution.
The planner now sees a compact **planning surface** instead of a full tool dump. That
surface is built from capability-card providers: tool-backed cards today, with future
skill-backed cards able to join the same prompt layer without changing the core
`decision_needs -> ToolRouter` execution contract.

### Source layout (`Code/src/`)

| Path                     | Purpose                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `ui/`                    | CLI, interactive mode, Rich dashboard, progress tracking, question UI.                    |
| `autonomous_iteration/`  | Modern autopilot runtime, phase controller, task execution, project evaluation, iteration. |
| `agent_generator/`       | Reusable-agent generation pipeline (data collect → process → present → combine).          |
| `tools/`                 | `ToolDefinition` protocol, tool registry, and built-in tool executors.                    |
| `metadata/`              | Strict Pydantic v2 model-harness contracts exchanged between agents, tools, and runtime.  |
| `core/`                  | LLM client, instrumentation, config, logging, semantic analysis, risk helpers.            |
| `memory/`                | Memory store, short-term memory, context compression, memory vault, project index.        |
| `utils/`                 | Pure utilities (diff, formatting, JSON, text, tree viz) with no LLM/tool behavior.         |

**Contract conventions:** Pydantic contracts live beside their owning package, except
strict cross-component exchange objects, which live in `src/metadata/`. Tool invocations
use typed `input_metadata` / `output_metadata`; free-form diagnostic fields should use
names like `annotations`, `attributes`, `trace_info`, or `provider_details`.

The legacy `planning/`, `validation/`, `autonomy/`, `reporting/`, `models/`, and
`WorkflowExecutor` paths have been removed; some prose in [API.md](API.md) still describes
that older module split and is kept as design reference.

## 5. Testing

```bash
cd Code
pytest tests/          # 31 test modules, 433 tests, all offline
```

Scope the run to `tests/` — a bare `pytest` also tries to collect the unrelated
`references/` reference tree and will report collection errors. Tests are contract- and
behavior-focused (runtime controller, tool IO, metadata models, memory context, project
evaluation, etc.) and run without a live LLM.

## 6. Handover Notes / Open Issues

- **Rotate the API keys.** Real keys were committed to git history before this handover
  cleanup. Removing the files from tracking does **not** purge them from history — treat
  the leaked keys as compromised and rotate them.
- **`API.md`** documents an older, more granular module split (Goal Understanding /
  Planner / etc.). The current code consolidates these into the `IntelligentAutopilot`
  path. Treat it as design background, not a current spec.
- **`Code/references/hermes-agent`** was a dangling git submodule reference (no
  `.gitmodules`) used as inspiration material; it has been removed from tracking.
- The repository historically carried two directory cases (`Code/` in git, `code/` on a
  case-insensitive macOS disk). They are the same directory; commands use `Code/`.

## 7. Project Structure (top level)

```text
openpilot/
├── README.md          # this handover guide
├── INSTALL.md         # environment setup details
├── API.md             # legacy module/interface design notes (reference)
├── Code/              # the openpilot Python package
│   ├── src/           # source (see layout above)
│   ├── tests/         # pytest suite
│   ├── pyproject.toml # package + entry point definition
│   └── requirements.txt
└── .env_example       # example credentials template
```
