"""Result metadata contracts for task and tool execution."""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Annotated, Any, Callable, Literal

from pydantic import Field, SerializeAsAny, model_validator

from metadata.artifacts import (
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    EmbeddingArtifactMetadata,
    FileArtifactMetadata,
    SearchArtifactMetadata,
    TextArtifactMetadata,
)
from metadata.base import JsonValue, MetadataBase, MetadataKind
from metadata.bugfix import BugFixAttemptMetadata, BugFixResultMetadata
from metadata.project import (
    EnvironmentSyncMetadata,
    ImprovementAnalysisMetadata,
    ImprovementCandidateMetadata,
    ProjectDiagnosisMetadata,
    ProjectStateMetadata,
)
from metadata.warnings import WarningCheckResultMetadata, WarningItemMetadata


ArtifactMetadata = Annotated[
    TextArtifactMetadata
    | CodeArtifactMetadata
    | FileArtifactMetadata
    | CommandArtifactMetadata
    | SearchArtifactMetadata
    | EmbeddingArtifactMetadata,
    Field(discriminator="kind"),
]


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAIL = "fail"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FailureMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.FAILURE
    error_type: str
    error_message: str
    error_code: str | None = None
    recoverable: bool = False
    retry_recommended: bool = False
    recovery_strategy: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResultMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TOOL_RESULT
    tool_name: str
    status: ResultStatus
    result: SerializeAsAny[MetadataBase] | None = None
    failure: FailureMetadata | None = None
    logs: list[dict[str, JsonValue]] = Field(default_factory=list)
    resource_usage: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _result_or_failure_matches_status(self) -> "ToolResultMetadata":
        if self.status == ResultStatus.SUCCESS and self.result is None:
            raise ValueError("Successful tool metadata requires result")
        if self.status != ResultStatus.SUCCESS and self.failure is None:
            raise ValueError("Failed tool metadata requires failure")
        return self

    def get(self, key: str, default: Any = None) -> Any:
        """Read a key from the result payload without changing the metadata envelope."""
        if isinstance(self.result, MetadataBase):
            return self.result.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        if isinstance(self.result, MetadataBase):
            return self.result[key]
        raise TypeError(f"{type(self.result).__name__} payload is not key-addressable")

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str) and isinstance(self.result, MetadataBase):
            return key in self.result
        return False

    def setdefault(self, key: str, default: Any) -> Any:
        attributes = getattr(self.result, "attributes", None)
        if isinstance(attributes, dict):
            return attributes.setdefault(key, default)
        raise TypeError("ToolResultMetadata payload is not a mutable mapping")


def payload_to_artifact(tool_name: str, payload: Any, input_metadata: Any = None) -> MetadataBase:
    """Convert common built-in tool payloads into artifact metadata."""
    if isinstance(payload, MetadataBase):
        return payload
    if not isinstance(payload, dict):
        return TextArtifactMetadata(content=str(payload), title=tool_name, attributes={"value": payload})

    def attr_without(*keys: str) -> dict[str, JsonValue]:
        attributes = {key: value for key, value in payload.items() if key not in keys and key != "attributes"}
        nested = payload.get("attributes")
        if isinstance(nested, dict):
            attributes.update(nested)
        return attributes

    input_file_path = getattr(input_metadata, "file_path", "") or ""
    if tool_name == "file_reader":
        return FileArtifactMetadata(
            file_path=input_file_path,
            content=str(payload.get("content") or ""),
            encoding=str(payload.get("encoding") or "utf-8"),
            size_bytes=payload.get("size_bytes"),
            file_type=str(payload.get("file_type") or ""),
            lines_read=payload.get("lines_read"),
            total_lines=payload.get("total_lines"),
            truncated=bool(payload.get("truncated", False)),
            attributes=attr_without("content", "encoding", "size_bytes", "file_type", "lines_read", "total_lines", "truncated"),
        )
    if tool_name == "multi_file_reader":
        return FileArtifactMetadata(
            file_path=input_file_path,
            files=list(payload.get("files") or []),
            content=str(payload.get("content") or ""),
            encoding=str(payload.get("encoding") or "utf-8"),
            truncated=bool(payload.get("truncated", False)),
            attributes=attr_without("content", "encoding", "files", "truncated"),
        )
    if tool_name in {"file_writer", "readme_tool"}:
        return FileArtifactMetadata(
            file_path=str(payload.get("file_path") or input_file_path),
            bytes_written=payload.get("bytes_written"),
            created=payload.get("created"),
            attributes=attr_without("file_path", "bytes_written", "created"),
        )
    if tool_name == "code_generator":
        return CodeArtifactMetadata(
            code=str(payload.get("code") or ""),
            language=str(payload.get("language") or "python"),
            imports=list(payload.get("imports") or []),
            functions=list(payload.get("functions") or []),
            attributes=attr_without("code", "language", "imports", "functions"),
        )
    if tool_name in {"command_executor", "code_executor"}:
        return CommandArtifactMetadata(
            command=str(payload.get("command") or getattr(input_metadata, "command", "") or ""),
            success=bool(payload.get("success", False)),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            exit_code=int(payload.get("exit_code") or 0),
            duration=float(payload.get("duration") or 0.0),
            risk_assessment=payload.get("risk_assessment"),
            attributes=attr_without("command", "success", "stdout", "stderr", "exit_code", "duration", "risk_assessment"),
        )
    if tool_name == "web_searcher":
        return SearchArtifactMetadata(
            query=str(payload.get("query") or getattr(input_metadata, "query", "") or ""),
            provider=str(payload.get("provider") or ""),
            effective_query=str(payload.get("effective_query") or ""),
            results=list(payload.get("results") or []),
            count=int(payload.get("count") or 0),
            pages=list(payload.get("pages") or []),
            research_summary=str(payload.get("research_summary") or ""),
            key_points=list(payload.get("key_points") or []),
            source_notes=list(payload.get("source_notes") or []),
            follow_up_queries=list(payload.get("follow_up_queries") or []),
            warnings=list(payload.get("warnings") or []),
            attributes=attr_without(
                "query",
                "provider",
                "effective_query",
                "results",
                "count",
                "pages",
                "research_summary",
                "key_points",
                "source_notes",
                "follow_up_queries",
                "warnings",
            ),
        )
    if tool_name == "embedder":
        return EmbeddingArtifactMetadata(
            query=str(payload.get("query") or getattr(input_metadata, "query", "") or ""),
            embedding=list(payload.get("embedding") or []),
            dimension=int(payload.get("dimension") or 0),
            model=str(payload.get("model") or ""),
            provider=str(payload.get("provider") or ""),
            cached=bool(payload.get("cached", False)),
            attributes=attr_without("query", "embedding", "dimension", "model", "provider", "cached"),
        )
    if tool_name == "bug_fix_tool":
        attempts = [
            item
            if isinstance(item, BugFixAttemptMetadata)
            else BugFixAttemptMetadata.model_validate(item)
            for item in payload.get("attempts", [])
        ]
        final_command_result = payload.get("final_command_result")
        if isinstance(final_command_result, dict):
            final_command_result = CommandArtifactMetadata.model_validate(final_command_result)
        return BugFixResultMetadata(
            command=str(payload.get("command") or getattr(input_metadata, "command", "") or ""),
            cwd=str(payload.get("cwd") or getattr(input_metadata, "cwd", "") or ""),
            target_files=[str(item) for item in payload.get("target_files") or getattr(input_metadata, "file_paths", [])],
            fixed=bool(payload.get("fixed", False)),
            iterations_used=int(payload.get("iterations_used") or 0),
            max_iterations=int(payload.get("max_iterations") or getattr(input_metadata, "max_iterations", None) or 5),
            continuation_iterations=int(
                payload.get("continuation_iterations") or getattr(input_metadata, "continuation_iterations", None) or 3
            ),
            attempts=attempts,
            final_command_result=final_command_result,
            requires_user_decision=bool(payload.get("requires_user_decision", False)),
            user_terminated=bool(payload.get("user_terminated", False)),
            annotations=attr_without(
                "command",
                "cwd",
                "target_files",
                "fixed",
                "iterations_used",
                "max_iterations",
                "continuation_iterations",
                "attempts",
                "final_command_result",
                "requires_user_decision",
                "user_terminated",
            ),
        )
    if tool_name == "warning_check_tool":
        warnings = [
            item
            if isinstance(item, WarningItemMetadata)
            else WarningItemMetadata.model_validate(item)
            for item in payload.get("warnings", [])
        ]
        ignored_warnings = [
            item
            if isinstance(item, WarningItemMetadata)
            else WarningItemMetadata.model_validate(item)
            for item in payload.get("ignored_warnings", [])
        ]
        return WarningCheckResultMetadata(
            command=str(payload.get("command") or getattr(input_metadata, "command", "") or ""),
            cwd=str(payload.get("cwd") or getattr(input_metadata, "cwd", "") or ""),
            warnings=warnings,
            ignored_warnings=ignored_warnings,
            requires_fix=bool(payload.get("requires_fix", False)),
            reason=str(payload.get("reason") or ""),
            recommended_fix=str(payload.get("recommended_fix") or ""),
            annotations=attr_without("command", "cwd", "warnings", "ignored_warnings", "requires_fix", "reason", "recommended_fix"),
        )
    if tool_name == "project_environment_tool":
        return EnvironmentSyncMetadata(
            project_path=str(payload.get("project_path") or ""),
            env_name=str(payload.get("env_name") or ".venv"),
            venv_path=str(payload.get("venv_path") or ""),
            python_executable=str(payload.get("python_executable") or ""),
            pip_executable=str(payload.get("pip_executable") or ""),
            python_version=str(payload.get("python_version") or ""),
            run_command=str(payload.get("run_command") or ""),
            command_cwd=str(payload.get("command_cwd") or ""),
            command_env={str(key): str(value) for key, value in (payload.get("command_env") or {}).items()}
            if isinstance(payload.get("command_env"), dict)
            else {},
            python_command=str(payload.get("python_command") or ""),
            pip_command=str(payload.get("pip_command") or ""),
            dependency_source=str(payload.get("dependency_source") or ""),
            setup_commands=list(payload.get("setup_commands") or []),
            detected_packages=list(payload.get("detected_packages") or []),
            installed_packages=list(payload.get("installed_packages") or []),
            missing_packages=list(payload.get("missing_packages") or []),
            operations=list(payload.get("operations") or []),
            warnings=list(payload.get("warnings") or []),
            annotations=attr_without(
                "project_path",
                "venv_path",
                "python_executable",
                "pip_executable",
                "run_command",
                "command_cwd",
                "command_env",
                "python_command",
                "pip_command",
                "setup_commands",
                "detected_packages",
                "installed_packages",
                "missing_packages",
                "warnings",
            ),
        )
    if tool_name == "project_state_reader":
        return ProjectStateMetadata(
            project_path=str(payload.get("project_path") or ""),
            goal=str(payload.get("goal") or ""),
            written_files=list(payload.get("written_files") or []),
            run_command=str(payload.get("run_command") or ""),
            readme_path=str(payload.get("readme_path") or ""),
            file_summaries=list(payload.get("file_summaries") or []),
            readme_summary=str(payload.get("readme_summary") or ""),
            safe_target_files=list(payload.get("safe_target_files") or []),
            memory_records=list(payload.get("memory_records") or []),
            validation_context=payload.get("validation_context") if isinstance(payload.get("validation_context"), dict) else {},
            memory_context={"records": payload.get("memory_records") or []},
            state_summary=str(payload.get("readme_summary") or ""),
            diagnostic_evidence=payload.get("diagnostic_evidence") if isinstance(payload.get("diagnostic_evidence"), dict) else {},
            runtime_evidence=[str(item) for item in payload.get("runtime_evidence") or []],
            test_evidence=[str(item) for item in payload.get("test_evidence") or []],
            module_summaries=[str(item) for item in payload.get("module_summaries") or []],
            annotations=attr_without(
                "project_path",
                "goal",
                "written_files",
                "run_command",
                "readme_path",
                "file_summaries",
                "validation_context",
                "memory_records",
                "readme_summary",
                "diagnostic_evidence",
                "runtime_evidence",
                "test_evidence",
                "module_summaries",
            ),
        )
    if tool_name == "project_improvement_tool":
        diagnosis = payload.get("diagnosis")
        if isinstance(diagnosis, dict):
            diagnosis = ProjectDiagnosisMetadata.model_validate(diagnosis)
        candidates = [
            item if isinstance(item, ImprovementCandidateMetadata) else ImprovementCandidateMetadata.model_validate(item)
            for item in payload.get("improvement_candidates") or []
        ]
        selected_candidate = payload.get("selected_candidate")
        if isinstance(selected_candidate, dict):
            selected_candidate = ImprovementCandidateMetadata.model_validate(selected_candidate)
        return ImprovementAnalysisMetadata(
            project_path=str(payload.get("project_path") or ""),
            goal=str(payload.get("goal") or ""),
            iteration=int(payload.get("iteration") or 0),
            summary=str(payload.get("summary") or ""),
            improvement_opportunities=[str(item) for item in payload.get("improvement_opportunities") or []],
            recommended_actions=[str(item) for item in payload.get("recommended_actions") or []],
            next_iteration_goal=str(payload.get("next_iteration_goal") or ""),
            must_implement_next=[str(item) for item in payload.get("must_implement_next") or []],
            blocking_risks=[str(item) for item in payload.get("blocking_risks") or []],
            designed_tasks=list(payload.get("designed_tasks") or []),
            product_judgment=payload.get("product_judgment") if isinstance(payload.get("product_judgment"), dict) else {},
            diagnosis=diagnosis if isinstance(diagnosis, ProjectDiagnosisMetadata) else None,
            improvement_candidates=candidates,
            selected_candidate=selected_candidate if isinstance(selected_candidate, ImprovementCandidateMetadata) else None,
            annotations=attr_without(
                "project_path",
                "goal",
                "iteration",
                "summary",
                "improvement_opportunities",
                "recommended_actions",
                "next_iteration_goal",
                "must_implement_next",
                "blocking_risks",
                "designed_tasks",
                "product_judgment",
                "diagnosis",
                "improvement_candidates",
                "selected_candidate",
            ),
        )
    if tool_name in {
        "llm_summarizer",
        "code_reviewer",
        "memory_context",
        "autonomy_tool",
    }:
        content = (
            payload.get("summary")
            or payload.get("review")
            or payload.get("prompt_text")
            or payload.get("decision_reason")
            or payload.get("next_iteration_goal")
            or ""
        )
        return TextArtifactMetadata(content=str(content), attributes=payload)
    return TextArtifactMetadata(
        content=str(payload.get("content") or payload.get("summary") or ""),
        title=tool_name,
        attributes=payload,
    )


def metadata_tool_result(tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., ToolResultMetadata]]:
    """Wrap a tool implementation so its public output is ToolResultMetadata."""

    def decorator(func: Callable[..., Any]) -> Callable[..., ToolResultMetadata]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> ToolResultMetadata:
            result = func(*args, **kwargs)
            if isinstance(result, ToolResultMetadata):
                return result
            input_metadata = args[0] if args else kwargs.get("input_metadata")
            return ToolResultMetadata(
                tool_name=tool_name,
                status=ResultStatus.SUCCESS,
                result=payload_to_artifact(tool_name, result, input_metadata),
            )

        return wrapper

    return decorator


def tool_result_payload(result: Any) -> Any:
    """Return the payload inside result metadata for UI/final display code."""
    if isinstance(result, ToolResultMetadata):
        return result.result
    return result


class TaskResultMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TASK_RESULT
    task_id: str
    status: ResultStatus
    result: SerializeAsAny[ToolResultMetadata | MetadataBase] | None = None
    failure: FailureMetadata | None = None
    duration: float | None = None

    @model_validator(mode="after")
    def _result_or_failure_matches_status(self) -> "TaskResultMetadata":
        if self.status == ResultStatus.SUCCESS and self.result is None:
            raise ValueError("Successful task metadata requires result")
        if self.status != ResultStatus.SUCCESS and self.failure is None:
            raise ValueError("Failed task metadata requires failure")
        return self
