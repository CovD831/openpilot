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
    dependencies: list["ProjectDependencyMetadata"] = Field(default_factory=list)
    dependency_strategy: "DependencyStrategyMetadata | None" = None


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


class ProjectDependencyMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROJECT_DEPENDENCY] = MetadataKind.PROJECT_DEPENDENCY
    package_name: str
    version: str = ""
    import_names: list[str] = Field(default_factory=list)
    dependency_sources: list[str] = Field(default_factory=list)
    import_usage: list[str] = Field(default_factory=list)
    role: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class DependencyStrategyMetadata(MetadataBase):
    kind: Literal[MetadataKind.DEPENDENCY_STRATEGY] = MetadataKind.DEPENDENCY_STRATEGY
    preserve_packages: list[str] = Field(default_factory=list)
    recommended_packages: list[str] = Field(default_factory=list)
    replaceable_packages: list[str] = Field(default_factory=list)
    rejected_removals: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    reference_queries: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class TaskFileResolutionRequestMetadata(MetadataBase):
    kind: Literal[MetadataKind.TASK_FILE_RESOLUTION_REQUEST] = MetadataKind.TASK_FILE_RESOLUTION_REQUEST
    project_path: str
    task_description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    target_file_hints: list[str] = Field(default_factory=list)
    fallback_files: list[str] = Field(default_factory=list)
    failing_files: list[str] = Field(default_factory=list)
    validation_issues: list[dict[str, JsonValue]] = Field(default_factory=list)
    issue_category: str = ""
    diagnosis: dict[str, JsonValue] = Field(default_factory=dict)
    selected_candidate: dict[str, JsonValue] = Field(default_factory=dict)
    goal: str = ""


class RelatedProjectFileMetadata(MetadataBase):
    kind: Literal[MetadataKind.RELATED_PROJECT_FILE] = MetadataKind.RELATED_PROJECT_FILE
    file_path: str
    name: str = ""
    suffix: str = ""
    description: str = ""
    role: str = ""
    relevance_score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    relation_source: str = "sketch"


class TaskFileResolutionMetadata(MetadataBase):
    kind: Literal[MetadataKind.TASK_FILE_RESOLUTION] = MetadataKind.TASK_FILE_RESOLUTION
    task_description: str = ""
    project_path: str = ""
    related_files: list[RelatedProjectFileMetadata] = Field(default_factory=list)
    primary_file: RelatedProjectFileMetadata | None = None
    recommended_edit_kind: str = "source_code"
    resolution_reason: str = ""


class GitRepositoryMetadata(MetadataBase):
    kind: Literal[MetadataKind.GIT_REPOSITORY] = MetadataKind.GIT_REPOSITORY
    project_path: str = ""
    initialized: bool = False
    branch: str = ""
    head: str = ""
    dirty: bool = False
    status: list[str] = Field(default_factory=list)
    ignored_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GitSnapshotMetadata(MetadataBase):
    kind: Literal[MetadataKind.GIT_SNAPSHOT] = MetadataKind.GIT_SNAPSHOT
    project_path: str = ""
    reason: str = ""
    message: str = ""
    commit_hash: str = ""
    created: bool = False
    skipped: bool = False
    changed_files: list[str] = Field(default_factory=list)
    status_before: list[str] = Field(default_factory=list)
    status_after: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GitDiffContextMetadata(MetadataBase):
    kind: Literal[MetadataKind.GIT_DIFF_CONTEXT] = MetadataKind.GIT_DIFF_CONTEXT
    project_path: str = ""
    base_ref: str = "HEAD"
    head_ref: str = ""
    status: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    diff_stat: str = ""
    diff_preview: str = ""
    target_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    dependencies: list[ProjectDependencyMetadata] = Field(default_factory=list)
    dependency_strategy: DependencyStrategyMetadata | None = None
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
    evidence_spans: list[dict[str, JsonValue]] = Field(default_factory=list)
    syntax_context: str = ""
    issue_fingerprint: str = ""
    recommended_repair_kind: str = ""
    closure_status: str = "open"
    stale_artifact_candidate: bool = False
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
    dependencies: list[ProjectDependencyMetadata] = Field(default_factory=list)
    dependency_strategy: DependencyStrategyMetadata | None = None
    git_repository: GitRepositoryMetadata | None = None
    git_snapshot: GitSnapshotMetadata | None = None
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
