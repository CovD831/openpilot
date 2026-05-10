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

### Task Log

- Input: task plan, status changes, user feedback, execution results.
- Output: task log entries and query results.
- Responsibility: record task lifecycle events for progress tracking, daily/weekly reports, and retrospectives.
- Storage: local JSONL files in `Code/data/task_logs/*.jsonl`, separate from audit logs.
- Event types: created, status_changed, blocked, unblocked, note_added, completed, skipped, timeline_updated.
- Required fields: id, timestamp, task_id, event_type; blocked events must include blocked_reason.

### Progress Report

- Input: task log entries, time range, user report preferences.
- Output: structured progress reports (daily/weekly) and Markdown formatted reports.
- Responsibility: generate daily summaries, weekly reviews, and retrospectives from task logs.
- Report types: daily (completed, in-progress, blocked, risks, tomorrow's plan), weekly (goals, completed, delayed/blocked, next week focus, retrospective).
- Default behavior: display in CLI only; writing to file requires explicit parameter or confirmation.

## 2. Tool Plugin Registration

Each tool should be registered with the following fields:

```yaml
name: example_tool
description: What the tool does.
version: 0.1.0
permission_level: auto | notify | confirm | forbidden
input_schema:
  type: object
  required: []
output_schema:
  type: object
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

## 3. Memory Types

### Short-Term Memory

Current task context, active plan, intermediate observations, temporary files, and recent tool outputs.

### Long-Term Memory

Stable user preferences, long-term goals, recurring constraints, preferred output formats, and trusted sources.

### Task Memory

Historical task plans, execution traces, results, user feedback, failure causes, and recovery strategies.

### Skill Memory

Reusable workflows, scripts, prompt templates, tool chains, GUI operation templates, and verified procedures.

## 4. Permission Policy

| Risk Level | Default Handling | Examples |
| --- | --- | --- |
| Low | Execute automatically and log | Search, summarize, read approved files, draft content |
| Medium | Notify before execution or follow user rule | Create files, batch download, consume paid model quota |
| High | Require explicit confirmation | Send email, delete files, modify calendar, access sensitive accounts |
| Forbidden | Block by default or sandbox only | Payments, system setting changes, unknown code execution, production data mutation |

## 5. MVP Interface Contract

The first MVP focuses on personal research and task assistance.

Minimum flow:

1. Receive a research goal from the user.
2. Generate a research plan.
3. Retrieve relevant memory and user preferences.
4. Search or read approved sources.
5. Summarize findings into a structured report.
6. Ask for confirmation before external sending, account login, bulk file writes, or high-risk GUI actions.
7. Generate reflection and propose memory updates.

Minimum deliverables:

- Structured report.
- Execution log.
- Memory update proposal.
- Risk confirmation record when applicable.

## 6. Update Rules

- Update this file when adding a new module, tool type, permission rule, memory category, or external integration.
- Keep this file implementation-facing and concise.
- Do not store secrets, API keys, private credentials, or personal user data in this file.
