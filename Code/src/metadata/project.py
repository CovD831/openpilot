"""Project and autonomy metadata for cross-agent coordination."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    stack_preset: "ProjectStackPresetMetadata | None" = None


class ProblemSignalMetadata(MetadataBase):
    """Raw evidence that something might require repair or replanning."""

    kind: Literal[MetadataKind.PROBLEM_SIGNAL] = MetadataKind.PROBLEM_SIGNAL
    signal_source: str = "tool_execution"
    category: str = "ambiguous_task"
    message: str = ""
    evidence: list[str] = Field(default_factory=list)
    task_id: str = ""
    tool_name: str = ""
    target_files: list[str] = Field(default_factory=list)
    raw_payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_source(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("source"), str):
            value = dict(value)
            value.setdefault("signal_source", value.pop("source"))
        return value


class ProblemJudgmentMetadata(MetadataBase):
    """Deterministic/LLM judgment for a problem signal."""

    kind: Literal[MetadataKind.PROBLEM_JUDGMENT] = MetadataKind.PROBLEM_JUDGMENT
    is_problem: bool = True
    severity: str = "blocking"
    requires_fix: bool = True
    user_visible: bool = True
    recommended_repair_kind: str = ""
    confidence: float = 0.5
    reason: str = ""


class DifficultyAssessmentMetadata(MetadataBase):
    """Complexity assessment used to choose direct repair versus decomposition."""

    kind: Literal[MetadataKind.DIFFICULTY_ASSESSMENT] = MetadataKind.DIFFICULTY_ASSESSMENT
    level: str = "simple"
    needs_decomposition: bool = False
    blocking_factors: list[str] = Field(default_factory=list)
    recommended_task_count: int = 1


class ResolutionPlanMetadata(MetadataBase):
    """Chosen repair strategy for a judged problem."""

    kind: Literal[MetadataKind.RESOLUTION_PLAN] = MetadataKind.RESOLUTION_PLAN
    strategy: str = "direct_retry"
    target_tasks: list[str] = Field(default_factory=list)
    max_attempts: int = 2
    acceptance_check: str = ""


class ValidationGrant(BaseModel):
    """One admitted exact validation capability owned by a task admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str = Field(min_length=1)
    cwd: str = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=900)

    @model_validator(mode="after")
    def _grant_is_non_blank(self) -> "ValidationGrant":
        if not self.command.strip() or not self.cwd.strip():
            raise ValueError("validation grant command and cwd must be non-empty")
        return self


class FileMutationPrecondition(BaseModel):
    """Immutable identity snapshot of one admitted regular-file mutation target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    device: int = Field(ge=0)
    inode: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)

    @model_validator(mode="after")
    def _precondition_is_canonical(self) -> "FileMutationPrecondition":
        from pathlib import Path

        if not self.path.strip() or not Path(self.path).is_absolute():
            raise ValueError("file mutation precondition path must be absolute and non-empty")
        return self


class TaskApprovalGrant(BaseModel):
    """One explicit user approval for a pending mutation proposal.

    This record is deliberately narrower than a task admission: it names an
    already-admitted proposal but carries no file or command authority of its
    own. The execution entry binds it to the newly created Run before any
    mutation reaches Action Gateway.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    admission_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    protocol_version: Literal["cli-v2"] = "cli-v2"

    @model_validator(mode="after")
    def _approval_is_complete(self) -> "TaskApprovalGrant":
        if any(
            not str(value).strip()
            for value in (
                self.approval_id,
                self.proposal_id,
                self.admission_id,
                self.task_id,
                self.project_root,
                self.conversation_id,
            )
        ):
            raise ValueError("task approval fields must be non-empty")
        return self

    def bind_run(self, run_id: str) -> "TaskConsentReference":
        return TaskConsentReference(
            consent_id=f"consent_{self.approval_id}",
            approval_id=self.approval_id,
            proposal_id=self.proposal_id,
            admission_id=self.admission_id,
            task_id=self.task_id,
            project_root=self.project_root,
            conversation_id=self.conversation_id,
            run_id=run_id,
            protocol_version=self.protocol_version,
        )


class TaskConsentReference(BaseModel):
    """Run-bound projection of one approved mutation proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consent_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    admission_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    protocol_version: Literal["cli-v2"] = "cli-v2"

    @model_validator(mode="after")
    def _consent_is_complete(self) -> "TaskConsentReference":
        if any(
            not str(value).strip()
            for value in (
                self.consent_id,
                self.approval_id,
                self.proposal_id,
                self.admission_id,
                self.task_id,
                self.project_root,
                self.conversation_id,
                self.run_id,
            )
        ):
            raise ValueError("task consent fields must be non-empty")
        return self


class TaskAdmissionGrant(BaseModel):
    """Immutable, project-bound authority snapshot for one admitted task plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    admission_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    protocol_version: Literal["cli-v2"] = "cli-v2"
    policy_revision: int = Field(default=1, ge=1)
    read_files: list[str] = Field(default_factory=list)
    write_files: list[str] = Field(default_factory=list)
    validation: ValidationGrant | None = None
    write_preconditions: list[FileMutationPrecondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _grant_has_a_complete_mutation_chain(self) -> "TaskAdmissionGrant":
        if any(not str(path).strip() for path in (*self.read_files, *self.write_files)):
            raise ValueError("task admission scopes must not contain blank paths")
        if len(self.read_files) != len(set(self.read_files)):
            raise ValueError("task admission read scope must be unique")
        if len(self.write_files) != len(set(self.write_files)):
            raise ValueError("task admission write scope must be unique")
        if self.write_files:
            if self.validation is None:
                raise ValueError("mutation task admission requires a validation grant")
            if not set(self.write_files).issubset(set(self.read_files)):
                raise ValueError("mutation task admission requires read-before-write scope")
            if [precondition.path for precondition in self.write_preconditions] != self.write_files:
                raise ValueError(
                    "mutation task admission requires one matching file precondition per write target"
                )
        elif self.validation is not None or self.write_preconditions:
            raise ValueError("read-only task admission cannot carry mutation authority")
        return self

    @property
    def is_mutation(self) -> bool:
        return bool(self.write_files)


class TaskGraphNodeMetadata(MetadataBase):
    """Typed graph metadata for a decomposed task."""

    kind: Literal[MetadataKind.TASK_GRAPH_NODE] = MetadataKind.TASK_GRAPH_NODE
    task_id: str
    description: str = ""
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    estimated_effort: float | None = None
    task_kind: str = "general"
    difficulty: str = "simple"
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    read_files: list[str] = Field(default_factory=list)
    support_context_files: list[str] = Field(default_factory=list)
    write_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    can_run_parallel: bool = True
    validation_command: str = ""
    tags: list[str] = Field(default_factory=list)
    problem_resolution_depth: int = Field(default=0, ge=0)
    problem_resolution_parent_task_id: str | None = None
    admission: TaskAdmissionGrant | None = None

    @model_validator(mode="after")
    def _admission_matches_task_plan(self) -> "TaskGraphNodeMetadata":
        if self.admission is None:
            return self
        if self.admission.task_id != self.task_id:
            raise ValueError("task admission task_id must match task graph node")
        if self.admission.read_files != self.read_files:
            raise ValueError("task admission read scope must match task graph node")
        if self.admission.write_files != self.write_files:
            raise ValueError("task admission write scope must match task graph node")
        expected_validation = self.admission.validation.command if self.admission.validation else ""
        if self.validation_command != expected_validation:
            raise ValueError("task admission validation command must match task graph node")
        return self


class TaskGraphEdgeMetadata(MetadataBase):
    """Typed edge metadata for dependency and validation relationships."""

    kind: Literal[MetadataKind.TASK_GRAPH_EDGE] = MetadataKind.TASK_GRAPH_EDGE
    from_task: str
    to_task: str
    edge_type: str = "blocks"


class ExecutionStateMetadata(MetadataBase):
    """Summary of one task-graph execution pass."""

    kind: Literal[MetadataKind.EXECUTION_STATE] = MetadataKind.EXECUTION_STATE
    completed_tasks: list[str] = Field(default_factory=list)
    failed_tasks: list[str] = Field(default_factory=list)
    blocked_tasks: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    validation_result: dict[str, JsonValue] = Field(default_factory=dict)
    execution_batches: list[list[str]] = Field(default_factory=list)


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


class ProjectStackPresetMetadata(MetadataBase):
    """Mutable project-level delivery surface, language, framework, and UI decision."""

    kind: Literal[MetadataKind.PROJECT_STACK_PRESET] = MetadataKind.PROJECT_STACK_PRESET
    project_path: str = ""
    preset_file: str = ""
    revision: int = 1
    preset_source: str = "initial_inference"
    delivery_surface: str = "project_native"
    architecture: str = "single_runtime"
    frontend_language: str = "best_fit_for_surface"
    frontend_frameworks: list[str] = Field(default_factory=list)
    backend_language: str = "python"
    backend_frameworks: list[str] = Field(default_factory=list)
    ui_strategy: str = "evaluate_user_facing_ui"
    ui_review_required: bool = False
    rationale: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    mutable: bool = True


class FileContentSectionMetadata(MetadataBase):
    """Deterministic structural span inside a project file."""

    kind: Literal[MetadataKind.FILE_CONTENT_SECTION] = MetadataKind.FILE_CONTENT_SECTION
    section_id: str
    title: str = ""
    section_type: str = "text"
    summary: str = ""
    embedding: list[float] = Field(default_factory=list)
    line_start: int = 1
    line_end: int = 1
    char_start: int = 0
    char_end: int = 0
    symbol_name: str = ""
    parent_symbol: str = ""


class FileContentIndexMetadata(MetadataBase):
    """Sidecar index for one file's functional sections and exact locations."""

    kind: Literal[MetadataKind.FILE_CONTENT_INDEX] = MetadataKind.FILE_CONTENT_INDEX
    file_path: str = ""
    relative_path: str = ""
    index_file: str = ""
    project_root: str = ""
    content_sha256: str = ""
    language: str = ""
    byte_size: int = 0
    line_count: int = 0
    sections: list[FileContentSectionMetadata] = Field(default_factory=list)
    deleted: bool = False


class DirectorySketchMetadata(MetadataBase):
    """Aggregated directory sketch containing file index summaries."""

    kind: Literal[MetadataKind.DIRECTORY_SKETCH] = MetadataKind.DIRECTORY_SKETCH
    version: int = 2
    directory: str = ""
    project_root: str = ""
    files: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)


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
    stack_preset: ProjectStackPresetMetadata | None = None
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
    evidence_ids: list[str] = Field(default_factory=list)
    designed_tasks: list[dict[str, JsonValue]] = Field(default_factory=list)
    product_judgment: dict[str, JsonValue] = Field(default_factory=dict)
    stack_preset: dict[str, JsonValue] = Field(default_factory=dict)
    stack_preset_update: dict[str, JsonValue] = Field(default_factory=dict)
    ui_iteration_contract: dict[str, JsonValue] = Field(default_factory=dict)
    diagnosis: ProjectDiagnosisMetadata | None = None
    improvement_candidates: list[ImprovementCandidateMetadata] = Field(default_factory=list)
    selected_candidate: ImprovementCandidateMetadata | None = None


class EnvironmentOperation(str, Enum):
    LEGACY_SYNC = "legacy_sync"
    PREFLIGHT = "preflight"
    SETUP = "setup"
    SYNC = "sync"


class EnvironmentReadiness(str, Enum):
    UNKNOWN = "unknown"
    SETUP_REQUIRED = "setup_required"
    READY = "ready"
    STALE = "stale"
    BLOCKED = "blocked"


class EnvironmentSyncMetadata(MetadataBase):
    kind: Literal[MetadataKind.ENVIRONMENT_SYNC] = MetadataKind.ENVIRONMENT_SYNC
    operation: EnvironmentOperation = EnvironmentOperation.LEGACY_SYNC
    readiness: EnvironmentReadiness = EnvironmentReadiness.UNKNOWN
    environment_id: str = ""
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
    stack_preset: ProjectStackPresetMetadata | None = None
    git_repository: GitRepositoryMetadata | None = None
    git_snapshot: GitSnapshotMetadata | None = None
    operations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ready_environment_has_execution_identity(self) -> "EnvironmentSyncMetadata":
        if self.readiness == EnvironmentReadiness.READY:
            missing = [
                name
                for name, value in (
                    ("environment_id", self.environment_id),
                    ("python_executable", self.python_executable),
                    ("command_cwd", self.command_cwd),
                )
                if not str(value or "").strip()
            ]
            if missing:
                raise ValueError(f"ready environment requires: {', '.join(missing)}")
        return self


class AutonomyDecisionMetadata(MetadataBase):
    kind: Literal[MetadataKind.AUTONOMY_DECISION] = MetadataKind.AUTONOMY_DECISION
    goal: str = ""
    decision: str = ""
    decision_reason: str = ""
    selected_actions: list[str] = Field(default_factory=list)
    next_iteration_goal: str = ""
    confidence: float = 0.0
    constraints: list[str] = Field(default_factory=list)
