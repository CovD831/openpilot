"""Evaluation models for project-level iterative improvement."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    """Hard project validation and improvement target result."""

    validation_passed: bool
    runnable: bool
    has_blocking_bugs: bool
    summary: str
    validation_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    run_command: str = ""
    improvement_opportunities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    next_iteration_goal: str | None = None


class IterationResult(BaseModel):
    """One improvement iteration result."""

    iteration: int
    validation_passed: bool
    completed_successful_iteration: bool
    applied_actions: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    success: bool
    error: str | None = None
    evaluation_notes: list[str] = Field(default_factory=list)
    failure_stage: str | None = None
    failed_tool: str | None = None
    failure_reason: str | None = None
    retry_attempted: bool = False
    retry_history: list[dict] = Field(default_factory=list)
    remaining_goals: list[str] = Field(default_factory=list)


class ProjectStateSnapshot(BaseModel):
    """Structured state snapshot consumed by the autonomous iteration agent."""

    project_path: str
    goal: str = ""
    written_files: list[str] = Field(default_factory=list)
    file_summaries: list[dict[str, str]] = Field(default_factory=list)
    readme_summary: str = ""
    run_command: str = ""
    memory_records: list[dict] = Field(default_factory=list)
    memory_context: dict = Field(default_factory=dict)
    validation_context: dict = Field(default_factory=dict)
    safe_target_files: list[str] = Field(default_factory=list)


class ImprovementGoal(BaseModel):
    """A concrete, evaluable improvement direction."""

    id: str
    title: str
    category: str = "feature"
    rationale: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: str = "medium"


class DesignedImprovementTask(BaseModel):
    """Specific implementation task derived from an improvement goal."""

    id: str
    goal_id: str
    description: str
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class AutonomousIterationResult(BaseModel):
    """Public summary for one autonomous iteration agent run."""

    project_state: ProjectStateSnapshot | None = None
    iteration_goals: list[ImprovementGoal] = Field(default_factory=list)
    designed_tasks: list[DesignedImprovementTask] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    iterations: list[IterationResult] = Field(default_factory=list)
    mind_notes: list[str] = Field(default_factory=list)
