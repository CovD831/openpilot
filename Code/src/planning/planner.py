"""Autonomous task planning service."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from core.exceptions import InvalidLLMResponseError
from core.llm import LLMMessage, LLMRequest, LLMResponse
from models.planner_models import ExecutionPlan, TaskCard
from core.risk import enforce_risk_policy
from planning.timeline import attach_timeline


class CompletionClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a normalized LLM response."""


def apply_task_type_fallback(task_card: TaskCard, goal: str) -> TaskCard:
    """Deprecated no-op kept for compatibility.

    Task type inference is handled by the LLM semantic analyzer. This function
    intentionally performs no keyword classification.
    """
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

CRITICAL: You MUST return ONLY valid JSON. Do NOT include:
- Markdown code blocks (```json or ```)
- Explanatory text before or after the JSON
- Comments inside the JSON
- Any text that is not part of the JSON structure

Your response must start with { and end with }. Nothing else.

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

            plan = enforce_risk_policy(plan)
            return attach_timeline(plan)
        except json.JSONDecodeError as exc:
            raise InvalidLLMResponseError("Planner returned invalid JSON.") from exc
        except ValidationError as exc:
            raise InvalidLLMResponseError(f"Planner JSON failed schema validation: {exc}") from exc

