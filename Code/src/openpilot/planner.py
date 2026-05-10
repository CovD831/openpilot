"""Autonomous task planning service."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from openpilot.exceptions import InvalidLLMResponseError
from openpilot.llm import LLMMessage, LLMRequest, LLMResponse
from openpilot.planner_models import ExecutionPlan, TaskType, TaskCard
from openpilot.risk import enforce_risk_policy
from openpilot.timeline import attach_timeline


class CompletionClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a normalized LLM response."""


def apply_task_type_fallback(task_card: TaskCard, goal: str) -> TaskCard:
    """Apply deterministic fallback for task_type if model returns unknown or invalid.

    OP-01: If the model returns 'unknown' but keywords clearly indicate a specific type,
    perform conservative correction.
    """
    if task_card.task_type != TaskType.UNKNOWN:
        return task_card

    goal_lower = goal.lower()

    # Data analysis keywords (Phase 2)
    if any(kw in goal_lower for kw in ["分析", "数据分析", "analyze", "analysis", "data analysis", "统计", "statistics", "csv", "excel", "数据处理", "data processing", "可视化", "visualization", "图表", "chart"]):
        task_card.task_type = TaskType.DATA_ANALYSIS
        return task_card

    # Automation keywords (Phase 2)
    if any(kw in goal_lower for kw in ["自动化", "批量", "automation", "automate", "batch", "批处理", "脚本", "script", "定时", "scheduled", "重复", "repeat"]):
        task_card.task_type = TaskType.AUTOMATION
        return task_card

    # Research keywords
    if any(kw in goal_lower for kw in ["研究", "调研", "search", "research", "investigate", "find information"]):
        task_card.task_type = TaskType.RESEARCH
        return task_card

    # Document summary keywords
    if any(kw in goal_lower for kw in ["总结", "整理", "summarize", "summary", "organize", "会议记录", "meeting notes"]):
        task_card.task_type = TaskType.DOCUMENT_SUMMARY
        return task_card

    # Communication keywords
    if any(kw in goal_lower for kw in ["发邮件", "发送邮件", "email", "send email", "通知", "notify", "联系", "contact"]):
        task_card.task_type = TaskType.COMMUNICATION
        return task_card

    # Calendar keywords
    if any(kw in goal_lower for kw in ["日历", "日程", "calendar", "schedule", "meeting", "会议", "约会", "appointment", "安排"]):
        task_card.task_type = TaskType.CALENDAR_RELATED
        return task_card

    # Coding keywords
    if any(kw in goal_lower for kw in ["代码", "编程", "code", "coding", "program", "debug", "fix bug", "bug", "python", "java", "javascript", "开发", "develop", "修复"]):
        task_card.task_type = TaskType.CODING
        return task_card

    # Planning keywords
    if any(kw in goal_lower for kw in ["计划", "规划", "plan", "planning", "strategy", "roadmap", "项目", "project"]):
        task_card.task_type = TaskType.PLANNING
        return task_card

    # File workflow keywords
    if any(kw in goal_lower for kw in ["文件", "file", "读取", "read", "写入", "write", "编辑", "edit"]):
        task_card.task_type = TaskType.FILE_WORKFLOW
        return task_card

    # If still unknown, keep it as unknown
    return task_card


SYSTEM_PROMPT = """You are OpenPilot's personal task progress planning module.
Default to helping the user move a future project or task forward. Emphasize deadlines,
scope, priority, dependencies, resources, risks, reminders, task logs, and concrete next steps.

IMPORTANT: Use ONLY these standard task_type values (OP-01 Phase 2):
- "research": Information gathering, web search, document analysis
- "document_summary": Summarizing documents or content
- "planning": Project planning, task breakdown, strategy
- "file_workflow": File operations, code editing, local file tasks
- "calendar_related": Scheduling, calendar management
- "communication": Email, messaging, notifications
- "coding": Software development, debugging, code writing
- "data_analysis": Data processing, statistical analysis, visualization (Phase 2)
- "automation": Automated scripts, batch processing, scheduled tasks (Phase 2)

IMPORTANT: Use ONLY these standard required_resources values (OP-01 Phase 2):
- "llm": LLM API calls for text generation
- "web_search": Web search capability
- "local_file": Local file system access
- "document_tool": Document processing tools
- "calendar": Calendar API access
- "email": Email API access
- "browser": Web browser automation
- "gui": GUI automation
- "python_runtime": Python code execution
- "memory": Memory system access
- "code_execution": Code generation and execution (Phase 2)
- "tool_orchestration": Tool chain orchestration (Phase 2)

Return only strict JSON matching this schema:
{
  "task_card": {
    "goal": "string",
    "task_type": "research|document_summary|planning|file_workflow|calendar_related|communication|coding|data_analysis|automation",
    "priority": "low|normal|high|urgent",
    "risk_level": "low|medium|high|forbidden",
    "required_resources": ["llm", "web_search", "local_file", "document_tool", "calendar", "email", "browser", "gui", "python_runtime", "memory", "code_execution", "tool_orchestration"],
    "expected_deliverables": ["task tree", "timeline", "reminder plan", "string"],
    "constraints": ["string"]
  },
  "steps": [
    {
      "id": "step-1",
      "title": "string",
      "description": "string",
      "risk_level": "low|medium|high|forbidden",
      "required_resources": ["llm", "web_search", "local_file", "code_execution", "tool_orchestration"],
      "expected_output": "string",
      "dependencies": ["step-id"],
      "confirmation_required": false
    }
  ],
  "fallbacks": ["string"],
  "confirmation_points": ["step-id or task"],
  "success_criteria": ["string"]
}

For data_analysis tasks, typically require: ["local_file", "python_runtime", "code_execution", "llm"]
For automation tasks, typically require: ["python_runtime", "code_execution", "tool_orchestration"]

Do not execute tools. Plan only. The application will derive a task tree and timeline
from your steps after validation. Classify risk conservatively."""


class TaskPlanner:
    """Create validated execution plans from high-level goals."""

    def __init__(self, llm_client: CompletionClient) -> None:
        self.llm_client = llm_client

    def plan(self, goal: str, constraints: list[str] | None = None) -> ExecutionPlan:
        """Generate and validate an execution plan."""

        if not goal.strip():
            raise ValueError("goal must not be empty")

        constraints = constraints or []
        request = self._build_request(goal, constraints)
        first_response = self.llm_client.complete(request)

        try:
            return self._parse_plan(first_response, goal)
        except InvalidLLMResponseError as first_error:
            repair_response = self.llm_client.complete(
                self._build_repair_request(goal, constraints, first_response.content)
            )
            try:
                return self._parse_plan(repair_response, goal)
            except InvalidLLMResponseError as second_error:
                raise InvalidLLMResponseError(
                    f"Planner response was invalid after one repair attempt: {second_error}"
                ) from first_error

    def _build_request(self, goal: str, constraints: list[str]) -> LLMRequest:
        user_prompt = {
            "goal": goal,
            "constraints": constraints,
            "instruction": "Produce a safe executable plan. Do not execute anything.",
        }
        return LLMRequest(
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=json.dumps(user_prompt, ensure_ascii=False)),
            ],
            response_format="json_object",
        )

    def _build_repair_request(
        self, goal: str, constraints: list[str], invalid_content: str
    ) -> LLMRequest:
        repair_prompt = {
            "goal": goal,
            "constraints": constraints,
            "invalid_content": invalid_content,
            "instruction": "Repair the previous content into strict JSON matching the schema.",
        }
        return LLMRequest(
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=json.dumps(repair_prompt, ensure_ascii=False)),
            ],
            response_format="json_object",
        )


    def _parse_plan(self, response: LLMResponse, goal: str = "") -> ExecutionPlan:
        try:
            payload = response.parsed_json
            if payload is None:
                payload = json.loads(response.content)
            if not isinstance(payload, dict):
                raise InvalidLLMResponseError("Planner JSON root must be an object.")

            # Pre-validate task_type correction (OP-01)
            if "task_card" in payload and "task_type" in payload["task_card"]:
                task_type = payload["task_card"]["task_type"]
                # Map common invalid values to valid enum values
                type_mapping = {
                    "project_planning": "planning",
                    "task_progress": "planning",
                    "unknown": "unknown",
                }
                if task_type in type_mapping:
                    payload["task_card"]["task_type"] = type_mapping[task_type]

            plan = ExecutionPlan.model_validate(payload)

            # Apply task type fallback to task_card (OP-01)
            corrected_task_card = apply_task_type_fallback(plan.task_card, goal)
            plan = plan.model_copy(update={"task_card": corrected_task_card})

            plan = enforce_risk_policy(plan)
            return attach_timeline(plan)
        except json.JSONDecodeError as exc:
            raise InvalidLLMResponseError("Planner returned invalid JSON.") from exc
        except ValidationError as exc:
            raise InvalidLLMResponseError(f"Planner JSON failed schema validation: {exc}") from exc


