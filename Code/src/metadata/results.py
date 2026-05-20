"""Result metadata contracts for task and tool execution."""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Annotated, Any, Callable, Literal

from pydantic import Field, model_validator

from metadata.artifacts import (
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    EmbeddingArtifactMetadata,
    FileArtifactMetadata,
    SearchArtifactMetadata,
    TextArtifactMetadata,
)
from metadata.base import JsonValue, MetadataBase, MetadataKind


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
    result: ArtifactMetadata | dict[str, JsonValue] | None = None
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
        if isinstance(self.result, dict):
            return self.result.get(key, default)
        if isinstance(self.result, MetadataBase):
            return self.result.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        if isinstance(self.result, dict):
            return self.result[key]
        if isinstance(self.result, MetadataBase):
            return self.result[key]
        raise TypeError(f"{type(self.result).__name__} payload is not key-addressable")

    def __contains__(self, key: object) -> bool:
        if isinstance(self.result, dict):
            return key in self.result
        if isinstance(key, str) and isinstance(self.result, MetadataBase):
            return key in self.result
        return False

    def setdefault(self, key: str, default: Any) -> Any:
        if not isinstance(self.result, dict):
            attributes = getattr(self.result, "attributes", None)
            if isinstance(attributes, dict):
                return attributes.setdefault(key, default)
            raise TypeError("ToolResultMetadata payload is not a mutable mapping")
        return self.result.setdefault(key, default)


def payload_to_artifact(tool_name: str, payload: Any, input_metadata: Any = None) -> ArtifactMetadata | dict[str, JsonValue] | Any:
    """Convert common built-in tool payloads into artifact metadata."""
    if isinstance(payload, MetadataBase):
        return payload
    if not isinstance(payload, dict):
        return payload

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
    if tool_name in {
        "llm_summarizer",
        "code_reviewer",
        "task_classifier",
        "memory_context",
        "project_environment_tool",
        "autonomy_tool",
        "project_state_reader",
        "project_improvement_tool",
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
    return payload


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
    """Return the payload inside result metadata for internal domain code."""
    if isinstance(result, ToolResultMetadata):
        return result.result
    return result


class TaskResultMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TASK_RESULT
    task_id: str
    status: ResultStatus
    result: ToolResultMetadata | ArtifactMetadata | dict[str, JsonValue] | None = None
    failure: FailureMetadata | None = None
    duration: float | None = None

    @model_validator(mode="after")
    def _result_or_failure_matches_status(self) -> "TaskResultMetadata":
        if self.status == ResultStatus.SUCCESS and self.result is None:
            raise ValueError("Successful task metadata requires result")
        if self.status != ResultStatus.SUCCESS and self.failure is None:
            raise ValueError("Failed task metadata requires failure")
        return self
