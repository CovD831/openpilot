# OpenPilot

OpenPilot is a modern AI agent system centered on the `IntelligentAutopilot` execution path. The codebase now favors an Agent + Tool protocol architecture instead of the removed legacy planning/workflow/reporting stack.

## Quick Start

```bash
conda create -n openpilot python=3.11 -y
conda activate openpilot
cd /Users/yanning/Projects/openpilot/Code
pip install -r requirements.txt
pip install -e .
```

Configure the LLM connection in `.env` or environment variables:

```bash
OPENPILOT_LLM_BASE_URL=https://your-provider.example/v1
OPENPILOT_LLM_API_KEY=your-api-key
OPENPILOT_LLM_MODEL=your-model
```

Check configuration:

```bash
openpilot config check
```

## Usage

Start interactive mode:

```bash
openpilot run
```

Run one goal and exit:

```bash
openpilot run --once "在 /tmp/demo 中创建一个 Python 项目"
```

Interactive commands:

```text
/autopilot <goal>  Run a goal through modern autonomous execution
/config            Show current LLM configuration
/help              Show command help
/clear             Clear the screen
/exit              Exit
```

Plain text entered without a leading slash is also routed to the modern autopilot path.

## Current Architecture

The active runtime path is:

```text
ui.cli -> ui.enhanced_cli -> execution.IntelligentAutopilot
        -> core.SemanticAnalyzer / agents.TaskDecomposer
        -> tools.ToolOrchestrator / tools.ToolExecutor
        -> built-in tools
        -> agents.ProjectEvaluatorAgent / agents.AutonomousIterationAgent
        -> memory + logs + enhanced UI dashboard
```

Important directories:

| Path | Purpose |
| --- | --- |
| `src/ui/` | CLI, interactive mode, Rich dashboard, progress tracking, question UI. |
| `src/execution/` | Modern autopilot and code execution/generation/review support. |
| `src/agents/` | Task decomposition, orchestration, project evaluation, autonomous iteration. |
| `src/tools/` | Standard ToolDefinition protocol, tool registry, built-in tool executors. |
| `src/core/` | LLM client, instrumentation, config, logging, semantic analysis, risk helpers. |
| `src/memory/` | Memory store, short memory, context compression, memory vault. |
| `src/utils/` | Pure utility functions and data structures without LLM/tool protocol behavior. |

The legacy `planning/`, `validation/`, `autonomy/`, `reporting/`, `models/`, and `WorkflowExecutor` code paths have been removed. Pydantic contracts now live beside their owning package: Agent contracts in `agents/`, tool contracts in `tools/`, memory contracts in `memory/`, execution contracts in `execution/`, and semantic classification types in `core/`.

## Refactoring Notes

See `PROJECT_STRUCTURE.md` for a directory-level map and the reserved area for concrete refactoring recommendations.
