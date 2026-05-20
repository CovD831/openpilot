# OpenPilot Personal Agent API Notes

本文件用于维护 OpenPilot Personal Agent 的模块接口、工具插件、记忆类型和权限边界。每次修改项目架构、工具调用方式或执行权限时，应同步更新本文档。

## 1. System Modules

### Goal Understanding

- Input: user goal, user constraints, optional files or context.
- Output: structured task card.
- Required fields: `goal`, `task_type`, `priority`, `risk_level`, `required_resources`, `expected_deliverables`.
- Responsibility: identify intent, scope, constraints, permissions, and likely execution path.

### Planner

- Input: structured task card, retrieved memory, available tools.
- Output: ordered execution plan.
- Required fields: `steps`, `dependencies`, `fallbacks`, `confirmation_points`, `success_criteria`.
- Responsibility: decompose goals, choose execution order, define checkpoints, and replan after failures.

### Memory

- Input: task context, user feedback, execution logs, reflections.
- Output: relevant memories and memory update proposals.
- Responsibility: retrieve useful context before execution and store useful lessons after execution.

### Tool Selector

- Input: plan step, available tool registry, permission policy.
- Output: selected tool and invocation schema.
- Responsibility: choose API tools, local tools, browser automation, GUI agent, file system access, or local model execution.

### Executor

- Input: approved plan step and selected tool.
- Output: execution result, artifacts, logs, and errors.
- Responsibility: run low-risk steps automatically, pause for required confirmations, and report failures.

### Reflection

- Input: final result, execution logs, errors, user feedback.
- Output: task review and memory updates.
- Responsibility: summarize what worked, what failed, what should be reused, and what should be avoided next time.

## 2. MVP Python Interfaces

The first implementation lives under `Code/` as a Python package and CLI. It plans tasks only; it does not execute tools yet.

### LLM Configuration

OpenAI-compatible providers are configured with environment variables:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OPENPILOT_LLM_PROVIDER` | No | `openai-compatible` | Provider label used in normalized responses. |
| `OPENPILOT_LLM_BASE_URL` | No | `https://api.openai.com/v1` | OpenAI-compatible endpoint base URL. |
| `OPENPILOT_LLM_API_KEY` | Yes for real calls | None | Secret API key. Do not store it in this file. |
| `OPENPILOT_LLM_MODEL` | No | `gpt-4o-mini` | Chat completion model name. |
| `OPENPILOT_LLM_TIMEOUT_SECONDS` | No | `60` | Provider timeout. |
| `OPENPILOT_LLM_TEMPERATURE` | No | `0.2` | Default sampling temperature. |

CLI readiness checks treat blank `OPENPILOT_LLM_BASE_URL` and blank
`OPENPILOT_LLM_API_KEY` as missing. Diagnostics may show whether a value is set, but
must never print the actual API key.

### Standard LLM Request / Response

`LLMRequest`:

- `messages`: list of `{role, content}` chat messages.
- `response_format`: `text` or `json_object`.
- `temperature`: optional per-request override.
- `max_tokens`: optional token limit.
- `trace_info`: local tracing annotations that are not part of the strict metadata protocol.

`LLMResponse`:

- `content`: raw text content.
- `parsed_json`: parsed object for JSON responses.
- `model`: provider model name.
- `provider`: configured provider label.
- `usage`: normalized usage object when available.
- `finish_reason`: provider finish reason.
- `provider_details`: safe provider details such as response id and timestamp.

### OpenPilot Metadata Protocol

OpenPilot reserves the word metadata for strict, Pydantic v2 model-harness
contracts in `code/src/metadata`. Free-form diagnostic data must use names such
as `annotations`, `attributes`, `trace_info`, or `provider_details`.

Every metadata payload carries:

- `kind`
- `schema_version`
- `source`
- `correlation`

Tool execution uses typed metadata:

- `ToolDefinition.input_metadata_type`
- `ToolDefinition.output_metadata_type`
- `ToolSelection.input_metadata`
- `ExecutionResult.output_metadata`
- `TaskExecutionResult.result_metadata`

Result metadata uses `status`. Successful results put data in `result`; failed
or timed-out results put structured error details in `failure`.

### Autonomous Planning Types

`ClarificationQuestion`:

- `field`
- `prompt`
- `reason`
- `default_assumption`

`ClarificationAnswer`:

- `field`
- `answer`

`TaskBrief`:

- `goal`
- `constraints`
- `answers`
- `assumptions`
- `missing_fields`
- `ready_for_planning`

Interactive `openpilot run` may ask clarification questions before planning when
the goal lacks a deadline, deliverables, or other key project details. `--once`
mode does not block for answers; it records default assumptions and includes
them in planner constraints and audit logs.

`TaskCard`:

- `goal`
- `task_type`
- `priority`
- `risk_level`
- `required_resources`
- `expected_deliverables`
- `constraints`

`PlanStep`:

- `id`
- `title`
- `description`
- `risk_level`
- `required_resources`
- `expected_output`
- `dependencies`
- `confirmation_required`

`TaskStatus`:

- `planned`
- `in_progress`
- `blocked`
- `done`
- `skipped`

`TaskNode`:

- `id`
- `title`
- `description`
- `status`
- `risk_level`
- `required_resources`
- `expected_output`
- `dependencies`
- `confirmation_required`

`TimelineSlot`:

- `id`
- `title`
- `task_ids`
- `start_label`
- `end_label`
- `status`

`TimelinePlan`:

- `goal`
- `time_horizon`
- `status`
- `task_tree`
- `timeline`
- `reminder_plan`
- `milestones`
- `notes`

`ReminderItem`:

- `id`
- `task_id`
- `title`
- `remind_at`
- `reason`
- `channel`
- `status`
- `reminder_type`

`ReminderPlan`:

- `goal`
- `items`
- `notes`

Reminder plans are local planning data only. The MVP does not create Windows
notifications, calendar events, emails, background jobs, or external reminders.

`ExecutionPlan`:

- `task_card`
- `steps`
- `fallbacks`
- `confirmation_points`
- `success_criteria`
- `timeline`

The MVP derives `timeline` deterministically from validated `steps`. It creates
planning-only task nodes, timeline slots, and reminder-plan data; it does not
write calendar reminders or execute tools.

### CLI

```powershell
openpilot config check
openpilot plan "用户高层目标"
openpilot plan "用户高层目标" --json
openpilot run
openpilot run --once "用户高层目标"
openpilot run --log-file logs/demo.jsonl
openpilot run --ignore-memory  # OP-04: disable preference retrieval
```

### OpenPilot Validation Log

`openpilot run` provides a modern validation REPL for planning-only workflows. The CLI shows status spinners, the current planning phase, and generated planned steps without executing tools. Users can exit with `exit`, `quit`, or `:q`. The legacy `openpilot openpilot` command remains supported as an alias.

On startup, `openpilot run` prints a Rich header panel and API setup guidance when config is incomplete:

- create or edit `Code/.env`;
- set `OPENPILOT_LLM_BASE_URL`;
- set `OPENPILOT_LLM_API_KEY`;
- set `OPENPILOT_LLM_MODEL`;
- never commit real API keys.

If `OPENPILOT_LLM_BASE_URL` or `OPENPILOT_LLM_API_KEY` is blank or missing, the REPL
prints `WARNING: LLM config incomplete: ...` before each prompt. This warning is
non-blocking; planning failures should still be logged as `planner_failed`.

Default log file:

- `Code/logs/openpilot.jsonl`

Each JSONL event includes:

- `timestamp`
- `session_id`
- `turn_id`
- `event_type`
- `payload`

Event types:

- `goal_received`
- `clarification_started`
- `clarification_answered`
- `clarification_completed`
- `memory_retrieved` (OP-04: records retrieved memories and reuse notes)
- `planner_started`
- `planner_succeeded`
- `reminders_planned`
- `planner_failed`

`planner_succeeded` stores the validated task card, planned executable steps,
derived timeline, task brief or assumptions when present, final risk level,
risk-policy marker, reminder plan, confirmation points, fallbacks, success criteria,
and `memory_reuse_notes` (OP-04: explains which preferences were applied).
`reminders_planned` stores the same local reminder plan as its own event.
`memory_retrieved` (OP-04) stores retrieved memories, their confidence scores, and reuse notes.
Logs must not include API keys, environment variables, or secrets.

## 3. Tool Plugin Registration

Each tool should be registered with the following fields:

```yaml
name: example_tool
description: What the tool does.
version: 0.1.0
permission_level: auto | notify | confirm | forbidden
input_metadata_type: ToolInputMetadata
output_metadata_type: ToolResultMetadata
contract_metadata:
  kind: tool_contract
  required_input_fields: []
  input_defaults: {}
failure_modes:
  - timeout
  - auth_required
  - invalid_input
fallbacks:
  - alternative_tool
audit_log: true
```

Permission levels:

- `auto`: may run automatically and must log the action.
- `notify`: may run after notifying the user or according to user-configured rules.
- `confirm`: must ask for explicit user confirmation before execution.
- `forbidden`: must be blocked by default, except in a sandbox or explicit development override.

## 4. Memory Types

### Short-Term Memory

Current task context, active plan, intermediate observations, temporary files, and recent tool outputs.

### Long-Term Memory

Stable user preferences, long-term goals, recurring constraints, preferred output formats, and trusted sources.

**OP-04 Preference Reuse Implementation:**
- Each memory record includes a `confidence` score (0.0-1.0) and `usage_count`.
- High-confidence preferences (≥0.7) are automatically injected as constraints during planning.
- Low-confidence preferences (<0.7) are retrieved but not auto-applied; they require user confirmation.
- Successfully applied preferences increment their `usage_count` and update `last_used` timestamp.
- Use `--ignore-memory` CLI flag to disable preference retrieval for a specific run.

### Task Memory

Historical task plans, execution traces, results, user feedback, failure causes, and recovery strategies.

### Skill Memory

Reusable workflows, scripts, prompt templates, tool chains, GUI operation templates, and verified procedures.

## 5. Permission Policy

| Risk Level | Default Handling | Examples |
| --- | --- | --- |
| Low | Execute automatically and log | Search, summarize, read approved files, draft content |
| Medium | Notify before execution or follow user rule | Search, batch download, consume paid model quota, create local files |
| High | Require explicit confirmation | Send email, delete files, modify calendar, access sensitive accounts |
| Forbidden | Block by default or sandbox only | Payments, system setting changes, unknown code execution, production data mutation |

The MVP planner applies deterministic keyword safeguards after LLM validation so obvious medium, high, or forbidden operations cannot be silently downgraded.

## 6. MVP Interface Contract

The first MVP focuses on personal task progress assistance.

Minimum flow:

1. Receive a future project or task goal from the user.
2. Clarify missing deadline, deliverable, priority, availability, dependency, or scope details when needed.
3. Generate a task card, executable steps, task tree, and timeline.
4. Identify deadlines, dependencies, resources, risk, and confirmation points.
5. Produce reminder-plan data and task-log-ready structured output.
6. Ask for confirmation before external sending, account login, bulk file writes, or high-risk GUI actions.
7. Preserve research reports as one supported task type, not the only MVP path.
8. Later phases add real reminders, task logs, daily/weekly reports, and authorized auto-actions.

Minimum deliverables:

- Task tree and timeline.
- Reminder-plan data.
- Execution/planning log.
- Memory update proposal.
- Risk confirmation record when applicable.

## 7. Update Rules

- Update this file when adding a new module, tool type, permission rule, memory category, or external integration.
- Keep this file implementation-facing and concise.
- Do not store secrets, API keys, private credentials, or personal user data in this file.

## 8. Autopilot Tool Execution Updates

Autopilot execution supports local document-summary workflows in addition to
planning. A typical completion-report summary chain is:

1. `directory_lister` lists matching files in a local directory.
2. `multi_file_reader` reads the matched files and combines their text.
3. `llm_summarizer` receives the combined text through typed tool input
   metadata and generates the summary.

Built-in local tools:

- `directory_lister`
  - Capability: `file_read`
  - Permission: `low`
  - Inputs: `directory_path`, optional `pattern`, `recursive`, `max_files`
  - Default report pattern: `*完成报告*.md`
  - Output: `files`, `count`, `total_count`, `truncated`
- `multi_file_reader`
  - Capability: `file_read`
  - Permission: `low`
  - Inputs: `file_paths` or `directory_path` plus optional `pattern`
  - Output: combined `content`, `files`, `count`, `truncated`

Execution input chaining:

- Tool selections declare `input_metadata` and optional dependencies.
- The workflow executor routes upstream outputs by metadata kind and the
  declared input/output metadata types.
- File artifacts can feed file-reading tools.
- Text and code artifacts can feed summarization, review, execution, or writing
  tools when those tools declare compatible input metadata.

Workflow execution logs now include `step_results` for each tool call:

- `step_id`
- `tool`
- `status`
- `success`
- `error`
- `input_keys`
- `input_resolution`
- `output_summary`
- `output_preview`
- `duration_seconds`

Workflow execution logs also include:

- `planned_steps`: the validated planner steps, including titles, descriptions,
  expected output, dependencies, risk level, and confirmation flags.
- `tool_selections`: the orchestration output for each step, including selected
  tool, input metadata keys, compact input preview, dependencies, selection
  reason, confidence, and confirmation flag.

Autopilot writes diagnostic events before the final workflow summary:

- `workflow_plan_generated`
- `tool_orchestration_planned`
- `tool_execution_result`
- `workflow_execution`

Before invoking a built-in tool, the workflow executor validates required
inputs. Missing required inputs produce a failed `ExecutionResult` with
`error.type = "MissingRequiredInput"` instead of allowing a raw `KeyError`.
For `llm_summarizer`, missing `text` records whether a compatible upstream
metadata output was available and whether the input chain was unresolved.

Workflow success must reflect actual execution. Non-dry-run workflows are
successful only when at least one tool ran, every execution result succeeded,
and all available validation results passed.

### Autopilot log routing and final-report behavior

- Autopilot workflow diagnostics use the same log file as the interactive CLI:
  `Code/logs/openpilot.jsonl`.
- `Code/logs/workflow.jsonl` is no longer the primary Autopilot diagnostic log.
- `openpilot run` clears the selected log file once at startup. The default
  selected log is `Code/logs/openpilot.jsonl`; `--log-file` selects and clears a
  different log file.
- `/autopilot` and `/execute` receive the active CLI logger, so their
  `workflow_plan_generated`, `tool_orchestration_planned`,
  `tool_execution_result`, and `workflow_execution` events are written to
  `openpilot.jsonl`.
- Successful `llm_summarizer` output is not printed verbatim in the CLI. The CLI
  shows step status and concise errors; bounded `output_preview` and
  `output_summary` fields are written to the JSONL log for diagnostics.
- Final report generation is an LLM summarization step unless the user explicitly
  requests persistence with a concrete output file path or filename. In that
  explicit-save case, `file_writer` receives content from the latest compatible
  text/code result metadata.

### LLM semantic analysis

- Goal understanding and plan-step tool orchestration use LLM semantic analysis
  instead of keyword-based positive classification.
- `SemanticAnalyzer.analyze_goal(goal, constraints)` returns task type, risk,
  resources, deliverables, intent, confidence, and reason as strict JSON.
- `SemanticAnalyzer.analyze_plan_step(goal, step, available_tools)` returns the
  operation type, capability, preferred tool, write/mutation flags, source kind,
  confidence, and reason as strict JSON.
- Deterministic code is still allowed for path extraction, glob matching, schema
  validation, required-input checks, and safety blocking. It must not be used to
  positively classify the user intent or step semantics.
- Autopilot logs `semantic_goal_analysis`, `semantic_step_analysis`, and
  `semantic_analysis_failed` events to `Code/logs/openpilot.jsonl`.
- If an LLM summary tool returns empty text, the executor logs
  `empty_output_retry`, retries once with a shorter payload, and then fails the
  current step with `EmptyLLMOutput` if the retry is also empty.
- Input-resolution diagnostics include `source_text_empty` so a present-but-empty
  upstream metadata output is distinguishable from a missing compatible source.
