"""Project and autonomy metadata for cross-agent coordination."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from metadata.base import JsonValue, MetadataBase, MetadataKind


class ProjectStateMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROJECT_STATE] = MetadataKind.PROJECT_STATE
    project_path: str = ""
    goal: str = ""
    written_files: list[str] = Field(default_factory=list)
    run_command: str = ""
    readme_path: str = ""
    file_summaries: list[dict[str, JsonValue]] = Field(default_factory=list)
    readme_summary: str = ""
    safe_target_files: list[str] = Field(default_factory=list)
    memory_records: list[dict[str, JsonValue]] = Field(default_factory=list)
    validation_context: dict[str, JsonValue] = Field(default_factory=dict)
    memory_context: dict[str, JsonValue] = Field(default_factory=dict)
    state_summary: str = ""


class ProductIntentMetadata(MetadataBase):
    kind: Literal[MetadataKind.PRODUCT_INTENT] = MetadataKind.PRODUCT_INTENT
    experience_type: str = "general_project"
    runtime_mode: str = "best_fit_for_goal"
    delivery_surface: str = "project_native"
    target_platforms: list[str] = Field(default_factory=list)
    core_capabilities: list[str] = Field(default_factory=list)
    non_regression_constraints: list[str] = Field(default_factory=list)
    disallowed_substitutions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class ValidationIssueMetadata(MetadataBase):
    kind: Literal[MetadataKind.VALIDATION_ISSUE] = MetadataKind.VALIDATION_ISSUE
    category: str = "runtime_error"
    severity: str = "blocking"
    message: str
    recommended_action: str = ""
    target_files: list[str] = Field(default_factory=list)
    product_intent: ProductIntentMetadata | None = None
    preserves_product_intent: bool = True


class ImprovementAnalysisMetadata(MetadataBase):
    kind: Literal[MetadataKind.IMPROVEMENT_ANALYSIS] = MetadataKind.IMPROVEMENT_ANALYSIS
    project_path: str = ""
    goal: str = ""
    iteration: int = 0
    summary: str = ""
    improvement_opportunities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    next_iteration_goal: str = ""
    must_implement_next: list[str] = Field(default_factory=list)
    blocking_risks: list[str] = Field(default_factory=list)
    designed_tasks: list[dict[str, JsonValue]] = Field(default_factory=list)
    product_judgment: dict[str, JsonValue] = Field(default_factory=dict)


class EnvironmentSyncMetadata(MetadataBase):
    kind: Literal[MetadataKind.ENVIRONMENT_SYNC] = MetadataKind.ENVIRONMENT_SYNC
    project_path: str = ""
    env_name: str = ".venv"
    venv_path: str = ""
    python_executable: str = ""
    pip_executable: str = ""
    python_version: str = ""
    run_command: str = ""
    dependency_source: str = ""
    setup_commands: list[str] = Field(default_factory=list)
    detected_packages: list[str] = Field(default_factory=list)
    installed_packages: list[str] = Field(default_factory=list)
    missing_packages: list[str] = Field(default_factory=list)
    operations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AutonomyDecisionMetadata(MetadataBase):
    kind: Literal[MetadataKind.AUTONOMY_DECISION] = MetadataKind.AUTONOMY_DECISION
    goal: str = ""
    decision: str = ""
    decision_reason: str = ""
    selected_actions: list[str] = Field(default_factory=list)
    next_iteration_goal: str = ""
    confidence: float = 0.0
    constraints: list[str] = Field(default_factory=list)
