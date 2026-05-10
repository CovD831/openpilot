# OpenPilot MVP

OpenPilot is an MVP personal agent planning core. The first version provides:

- OpenAI-compatible LLM configuration.
- A normalized LLM request/response wrapper.
- Autonomous task-progress planning from a high-level goal.
- A derived task tree, timeline, and reminder-plan data.
- A modern Rich-powered CLI entry point.

## Quick Start

```powershell
conda run -n openpilot python -m pip install -e .[dev]
conda run -n openpilot openpilot config check
conda run -n openpilot openpilot plan "Research the AI agent market" --json
conda run -n openpilot openpilot run
```

Copy `.env.example` to `.env` locally and fill in provider settings. Do not commit secrets.
OpenPilot never prints your real API key in CLI diagnostics.

Minimum `.env` fields for real LLM calls:

```dotenv
OPENPILOT_LLM_BASE_URL=https://api.openai.com/v1
OPENPILOT_LLM_API_KEY=your-secret-key
OPENPILOT_LLM_MODEL=gpt-4o-mini
```

## OpenPilot Validation

Use `openpilot run` for the modern interactive validation loop. Type a goal at the
`openpilot>` prompt; OpenPilot shows the current planning phase with a spinner,
then renders the generated planned steps and timeline summary, and writes the
decomposition to JSONL logs. It does not execute tools, create calendar events,
or send real reminders yet.
OpenPilot also renders a local `Reminder plan`; these reminders are planning
data only and do not trigger Windows notifications, calendar events, emails, or
background jobs.

If an interactive goal is too vague, OpenPilot asks a few clarification questions
before planning. In `--once` mode it never blocks for answers; missing details are
recorded as assumptions and shown in the terminal and JSONL audit log.

```powershell
conda run -n openpilot openpilot run --once "整理本周会议记录并生成行动计划"
conda run -n openpilot openpilot run --log-file logs/demo.jsonl
```

The legacy command remains available:

```powershell
conda run -n openpilot openpilot openpilot
```

The default log file is `logs/openpilot.jsonl`. Each line is a JSON event such as
`goal_received`, `planner_started`, `planner_succeeded`, or `planner_failed`.
Successful planning events include the validated task card, steps, derived
`timeline`, local `reminder_plan`, confirmation points, fallbacks, and success
criteria. Reminder plans are also logged as `reminders_planned`.

When `openpilot run` starts, it prints a Rich header panel and API setup guidance
when configuration is incomplete. If `OPENPILOT_LLM_BASE_URL` or
`OPENPILOT_LLM_API_KEY` is blank or missing, it keeps showing a warning before
each `openpilot>` prompt. The warning is non-blocking, so failed provider calls
are still logged for validation.
