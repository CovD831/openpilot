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
    diagnostic_evidence: dict[str, JsonValue] = Field(default_factory=dict)
    runtime_evidence: list[str] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    module_summaries: list[str] = Field(default_factory=list)


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


class ProjectObjectiveMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROJECT_OBJECTIVE] = MetadataKind.PROJECT_OBJECTIVE
    goal: str = ""
    project_type: str = "software_project"
    target_users: list[str] = Field(default_factory=list)
    delivery_surface: str = "project_native"
    core_value: list[str] = Field(default_factory=list)
    success_definition: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class SuccessMetricMetadata(MetadataBase):
    kind: Literal[MetadataKind.SUCCESS_METRIC] = MetadataKind.SUCCESS_METRIC
    metric_id: str
    name: str
    dimension: str
    metric_type: str = "qualitative"
    target: str = ""
    current_assessment: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    required: bool = False
    satisfied: bool | None = None


class ProjectDimensionAssessmentMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROJECT_DIMENSION_ASSESSMENT] = MetadataKind.PROJECT_DIMENSION_ASSESSMENT
    dimension: str
    score: float = 0.5
    summary: str = ""
    gaps: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ReferenceInsightMetadata(MetadataBase):
    kind: Literal[MetadataKind.REFERENCE_INSIGHT] = MetadataKind.REFERENCE_INSIGHT
    query: str = ""
    summary: str = ""
    best_practices: list[str] = Field(default_factory=list)
    gap_evidence: list[str] = Field(default_factory=list)
    applicability: str = "unknown"
    source_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ImprovementCandidateMetadata(MetadataBase):
    kind: Literal[MetadataKind.IMPROVEMENT_CANDIDATE] = MetadataKind.IMPROVEMENT_CANDIDATE
    candidate_id: str
    title: str
    dimension: str
    rationale: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    value_score: float = 0.5
    impact_score: float = 0.5
    difficulty_score: float = 0.5
    risk_score: float = 0.5
    evidence_score: float = 0.5
    priority_score: float = 0.5
    candidate_type: str = "enhancement"
    selected: bool = False


class ProjectDiagnosisMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROJECT_DIAGNOSIS] = MetadataKind.PROJECT_DIAGNOSIS
    project_path: str = ""
    iteration: int = 0
    objective: ProjectObjectiveMetadata
    success_metrics: list[SuccessMetricMetadata] = Field(default_factory=list)
    dimension_assessments: list[ProjectDimensionAssessmentMetadata] = Field(default_factory=list)
    improvement_candidates: list[ImprovementCandidateMetadata] = Field(default_factory=list)
    ranked_candidate_ids: list[str] = Field(default_factory=list)
    selected_candidate: ImprovementCandidateMetadata | None = None
    reference_insights: list[ReferenceInsightMetadata] = Field(default_factory=list)
    summary: str = ""
    candidate_shortage_reason: str = ""
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
    diagnosis: ProjectDiagnosisMetadata | None = None
    improvement_candidates: list[ImprovementCandidateMetadata] = Field(default_factory=list)
    selected_candidate: ImprovementCandidateMetadata | None = None


class EnvironmentSyncMetadata(MetadataBase):
    kind: Literal[MetadataKind.ENVIRONMENT_SYNC] = MetadataKind.ENVIRONMENT_SYNC
    project_path: str = ""
    env_name: str = ".venv"
    venv_path: str = ""
    python_executable: str = ""
    pip_executable: str = ""
    python_version: str = ""
    run_command: str = ""
    command_cwd: str = ""
    command_env: dict[str, str] = Field(default_factory=dict)
    python_command: str = ""
    pip_command: str = ""
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
