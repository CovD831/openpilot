"""Pydantic contracts for autonomous task planning."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FORBIDDEN = "forbidden"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED = "skipped"


class TaskType(str, Enum):
    """Standard task type enumeration for OP-01."""
    RESEARCH = "research"
    DOCUMENT_SUMMARY = "document_summary"
    PLANNING = "planning"
    FILE_WORKFLOW = "file_workflow"
    CALENDAR_RELATED = "calendar_related"
    COMMUNICATION = "communication"
    CODING = "coding"
    DATA_ANALYSIS = "data_analysis"  # Phase 2: 数据分析任务
    AUTOMATION = "automation"  # Phase 2: 自动化脚本任务
    UNKNOWN = "unknown"


# Standard resource tags for OP-01
STANDARD_RESOURCES = {
    "llm",
    "web_search",
    "local_file",
    "document_tool",
    "calendar",
    "email",
    "browser",
    "gui",
    "python_runtime",
    "memory",
    "timeline",
    "reminder_plan",
    "task_log",
    "code_execution",  # Phase 2: 代码执行能力
    "tool_orchestration",  # Phase 2: 工具编排能力
}


class TaskCard(BaseModel):
    """User's goal + constraints → structured task representation."""

    goal: str = Field(description="What the user wants to accomplish")
    task_type: TaskType = Field(
        default=TaskType.UNKNOWN,
        description="Standardized task type for OP-01 goal understanding",
    )
    priority: str = "normal"
    risk_level: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description="Estimated risk level for this task",
    )
    required_resources: list[str] = Field(
        default_factory=list,
        description="Resource tags needed to execute this task (e.g., web_search, local_file)",
    )
    expected_deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(
        default_factory=list,
        description="User-specified constraints or preferences"
    )
    context: dict[str, str] = Field(
        default_factory=dict,
        description="Optional context (e.g., file paths, URLs, prior state)",
    )


class PlanStep(BaseModel):
    id: str
    title: str
    description: str
    risk_level: RiskLevel
    required_resources: list[str] = Field(default_factory=list)
    expected_output: str
    dependencies: list[str] = Field(default_factory=list)
    confirmation_required: bool = False


class TaskNode(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PLANNED
    risk_level: RiskLevel
    required_resources: list[str] = Field(default_factory=list)
    expected_output: str
    dependencies: list[str] = Field(default_factory=list)
    confirmation_required: bool = False


class TimelineSlot(BaseModel):
    id: str
    title: str
    task_ids: list[str] = Field(default_factory=list)
    start_label: str
    end_label: str
    status: TaskStatus = TaskStatus.PLANNED


class TimelinePlan(BaseModel):
    goal: str
    time_horizon: str = "unspecified"
    status: TaskStatus = TaskStatus.PLANNED
    task_tree: list[TaskNode] = Field(default_factory=list)
    timeline: list[TimelineSlot] = Field(default_factory=list)
    reminder_plan: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    task_card: TaskCard
    steps: list[PlanStep]
    fallbacks: list[str] = Field(default_factory=list)
    confirmation_points: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    timeline: TimelinePlan | None = None


