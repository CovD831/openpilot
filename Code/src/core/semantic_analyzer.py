"""LLM-backed semantic analysis for OpenPilot goals and plan steps."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from core.exceptions import InvalidLLMResponseError
from core.llm import LLMMessage, LLMRequest, LLMResponse
from core.semantic_types import RiskLevel, STANDARD_RESOURCES, TaskType
from core.tool_contracts import ToolCapability


class CompletionClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a normalized LLM response."""


class GoalSemanticAnalysis(BaseModel):
    """Semantic classification for a user goal."""

    task_type: TaskType
    risk_level: RiskLevel
    required_resources: list[str] = Field(default_factory=list)
    expected_deliverables: list[str] = Field(default_factory=list)
    intent: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    def log_payload(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "risk_level": self.risk_level.value,
            "required_resources": self.required_resources,
            "expected_deliverables": self.expected_deliverables,
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class StepSemanticAnalysis(BaseModel):
    """Semantic classification for a planner step."""

    step_id: str
    operation_type: str
    capability: ToolCapability
    preferred_tool: str
    needs_file_write: bool = False
    allows_file_mutation: bool = False
    source_kind: str = "previous_output"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    def log_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation_type": self.operation_type,
            "capability": self.capability.value,
            "preferred_tool": self.preferred_tool,
            "needs_file_write": self.needs_file_write,
            "allows_file_mutation": self.allows_file_mutation,
            "source_kind": self.source_kind,
            "confidence": self.confidence,
            "reason": self.reason,
        }


GOAL_SYSTEM_PROMPT = """You are OpenPilot's semantic goal classifier.
Classify the user's goal by meaning, not keywords.

CRITICAL: You MUST return ONLY valid JSON. Do NOT include:
- Markdown code blocks (```json or ```)
- Explanatory text before or after the JSON
- Comments inside the JSON
Your response must start with { and end with }. Nothing else.

Allowed task_type values:
research, document_summary, planning, file_workflow, calendar_related,
communication, coding, data_analysis, automation, unknown.

Allowed risk_level values: low, medium, high, forbidden.
Allowed required_resources values:
llm, web_search, local_file, document_tool, calendar, email, browser, gui,
python_runtime, memory, timeline, reminder_plan, task_log, code_execution,
tool_orchestration.

Return:
{
  "task_type": "...",
  "risk_level": "...",
  "required_resources": ["..."],
  "expected_deliverables": ["..."],
  "intent": "short natural-language intent",
  "confidence": 0.0,
  "reason": "short reason"
}
"""


STEP_SYSTEM_PROMPT = """You are OpenPilot's semantic plan-step classifier.
Classify the step by meaning, not keywords.

CRITICAL: You MUST return ONLY valid JSON. Do NOT include:
- Markdown code blocks (```json or ```)
- Explanatory text before or after the JSON
- Comments inside the JSON
Your response must start with { and end with }. Nothing else.

Allowed capability values:
file_read, file_write, file_delete, llm_call, web_search, web_request,
code_execution, shell_execution, email, calendar, database, network.

Allowed preferred_tool values:
multi_file_reader, llm_summarizer, file_writer, command_executor,
code_generator, code_reviewer, code_executor, readme_tool, web_searcher,
unsupported_file_mutation.

Use these operation_type values when appropriate:
list_completion_reports, read_reports, summarize, generate_final_report,
write_output_file, move_files, archive_files, rename_files,
generate_code, review_code, execute_code,
generate_readme, analyze_project_improvements,
unsupported_file_mutation, other.

Code Generation Policy:
- If the step describes generating, writing, creating, or implementing code
  (e.g., "generate a Python function", "write a script", "implement a class",
  "create a game", "build an application"), classify as:
  * capability: "code_execution"
  * operation_type: "generate_code"
  * preferred_tool: "code_generator"
  * needs_file_write: true (if the goal mentions saving to a file or directory)
- If the step describes reviewing, analyzing, or checking code quality, classify as:
  * capability: "code_execution"
  * operation_type: "review_code"
  * preferred_tool: "code_reviewer"
- If the step describes running, executing, or testing code, classify as:
  * capability: "code_execution"
  * operation_type: "execute_code"
  * preferred_tool: "code_executor"
- For code generation workflows, the typical chain is:
  generate_code → (optional: review_code) → file_writer → readme_tool
- If the step describes creating usage instructions or README documentation for
  a generated project, classify as:
  * capability: "file_write"
  * operation_type: "generate_readme"
  * preferred_tool: "readme_tool"
- If the step only needs to list, find, or inspect directory entries without
  reading file contents, classify as:
  * capability: "shell_execution"
  * operation_type: "other"
  * preferred_tool: "command_executor"
- If the step needs to read multiple matching files from a directory, classify as:
  * capability: "file_read"
  * operation_type: "read_reports"
  * preferred_tool: "multi_file_reader"
- If the step needs internet research, latest information, source discovery, or
  web search results, classify as:
  * capability: "web_search"
  * operation_type: "other"
  * preferred_tool: "web_searcher"

Important policy:
- If the step wants to move, rename, archive, or reorganize original files and
  the user goal did not explicitly ask to mutate files, classify it as
  unsupported_file_mutation with preferred_tool "llm_summarizer" and
  allows_file_mutation false. It should become a written recommendation.
- If the user explicitly asked to mutate files, classify it as
  unsupported_file_mutation with preferred_tool "unsupported_file_mutation";
  OpenPilot does not have a safe move/rename tool yet.
- Do not choose file_writer unless there is an explicit output file path or
  filename in the step/goal.

Return:
{
  "operation_type": "...",
  "capability": "...",
  "preferred_tool": "...",
  "needs_file_write": false,
  "allows_file_mutation": false,
  "source_kind": "goal_path|previous_output|none",
  "confidence": 0.0,
  "reason": "short reason"
}
"""


class SemanticAnalyzer:
    """Use the configured LLM for goal and plan-step semantic analysis."""

    def __init__(self, llm_client: CompletionClient):
        self.llm_client = llm_client

    def analyze_goal(self, goal: str, constraints: list[str] | None = None) -> GoalSemanticAnalysis:
        payload = {
            "goal": goal,
            "constraints": constraints or [],
        }
        response = self.llm_client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="system", content=GOAL_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
                ],
                response_format="json_object",
                temperature=0.0,
                metadata={"semantic_task": "goal"},
            )
        )
        raw = self._response_payload(response)
        raw["required_resources"] = [
            resource for resource in raw.get("required_resources", [])
            if resource in STANDARD_RESOURCES
        ]
        try:
            return GoalSemanticAnalysis.model_validate(raw)
        except ValidationError as exc:
            raise InvalidLLMResponseError(f"Goal semantic analysis failed validation: {exc}") from exc

    def analyze_plan_step(
        self,
        goal: str,
        step: Any,
        available_tools: list[str],
    ) -> StepSemanticAnalysis:
        payload = {
            "goal": goal,
            "available_tools": available_tools,
            "step": {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "expected_output": step.expected_output,
                "dependencies": step.dependencies,
                "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else str(step.risk_level),
                "confirmation_required": step.confirmation_required,
            },
        }
        response = self.llm_client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="system", content=STEP_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
                ],
                response_format="json_object",
                temperature=0.0,
                metadata={"semantic_task": "plan_step", "step_id": step.id},
            )
        )
        raw = self._response_payload(response)
        raw["step_id"] = step.id
        try:
            return StepSemanticAnalysis.model_validate(raw)
        except ValidationError as exc:
            raise InvalidLLMResponseError(f"Step semantic analysis failed validation: {exc}") from exc

    def _response_payload(self, response: LLMResponse) -> dict[str, Any]:
        payload = response.parsed_json
        if payload is None:
            try:
                payload = json.loads(response.content)
            except json.JSONDecodeError as exc:
                raise InvalidLLMResponseError("Semantic analysis returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise InvalidLLMResponseError("Semantic analysis JSON root must be an object.")
        return payload
