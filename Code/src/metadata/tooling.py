"""Tool orchestration metadata contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from metadata.artifacts import (
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    EmbeddingArtifactMetadata,
    FileArtifactMetadata,
    SearchArtifactMetadata,
    TextArtifactMetadata,
)
from metadata.base import JsonValue, MetadataBase, MetadataKind
from metadata.results import ToolResultMetadata


class ToolInputMetadata(MetadataBase):
    """Strict tool input payload used instead of free-form params."""

    kind: MetadataKind = MetadataKind.TOOL_INPUT
    tool_name: str = ""

    # File/text/code fields
    file_path: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    directory_path: str | None = None
    pattern: str | None = None
    content: str | None = None
    text: str | None = None
    code: str | None = None
    language: str | None = None
    encoding: str | None = None
    max_size_mb: int | float | None = None
    read_mode: str | None = None
    max_lines: int | None = None
    offset: int | None = None
    max_total_chars: int | None = None
    recursive: bool | None = None
    max_files: int | None = None
    create_dirs: bool | None = None
    overwrite: bool | None = None

    # LLM/code/search/command fields
    task_description: str | None = None
    task: str | None = None
    task_type: str | None = None
    context: str | None = None
    prompt_context: dict[str, JsonValue] = Field(default_factory=dict)
    instruction: str | None = None
    max_tokens: int | None = None
    query: str | None = None
    provider: str | None = None
    model: str | None = None
    use_cache: bool | None = None
    max_results: int | None = None
    max_pages: int | None = None
    max_page_chars: int | None = None
    max_search_attempts: int | None = None
    search_budget_seconds: int | None = None
    max_redirect_depth: int | None = None
    max_redirect_pages: int | None = None
    max_redirect_candidates: int | None = None
    time_range: str | None = None
    safe_search: str | None = None
    follow_redirects: bool | None = None
    llm_cleanup: bool | None = None
    cleanup_instruction: str | None = None
    command: str | None = None
    mode: str | None = None
    timeout: int | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None

    # Project/autonomous iteration fields
    project_path: str | None = None
    project_summary: str | None = None
    goal: str | None = None
    written_files: list[str] = Field(default_factory=list)
    entry_files: list[str] = Field(default_factory=list)
    run_command: str | None = None
    env_name: str | None = None
    install: bool | None = None
    readme_path: str | None = None
    memory_query: str | None = None
    validation_context: dict[str, JsonValue] = Field(default_factory=dict)
    validation_result: dict[str, JsonValue] = Field(default_factory=dict)
    memory_context: dict[str, JsonValue] = Field(default_factory=dict)
    iteration: int | None = None
    include_environment: bool | None = None
    limit: int | None = None
    system_prompt: str | None = None
    environment: str | dict[str, JsonValue] | None = None
    freshness: str | None = None
    requires_user_input: bool | None = None
    risk_level: str | None = None
    setup_commands: list[str] = Field(default_factory=list)
    step_id: str | None = None
    tbs: str | None = None
    test_command: str | None = None

    # Test/service injection lives outside model-harness protocol.
    runtime_handles: dict[str, Any] = Field(default_factory=dict, exclude=True)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def from_mapping(cls, tool_name: str, values: dict[str, Any]) -> "ToolInputMetadata":
        runtime_handles = {key: value for key, value in values.items() if str(key).startswith("_")}
        public_values = {key: value for key, value in values.items() if not str(key).startswith("_")}
        return cls(tool_name=tool_name, runtime_handles=runtime_handles, **public_values)

    def to_params(self) -> dict[str, Any]:
        """Return public tool fields plus runtime handles for implementation internals."""
        data = self.model_dump(exclude_none=True, exclude={"kind", "schema_version", "source", "correlation", "created_at", "annotations", "runtime_handles"})
        data.pop("tool_name", None)
        data.pop("attributes", None)
        data = {key: value for key, value in data.items() if value not in ({}, [])}
        data.update(self.runtime_handles)
        return data


class ToolSelectionMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TOOL_SELECTION
    step_id: str
    tool_name: str
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    input_metadata: ToolInputMetadata
    requires_confirmation: bool = False
    timeout_override: int | None = None
    fallback_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class ToolContractMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TOOL_CONTRACT
    tool_name: str
    input_metadata_type: str
    output_metadata_type: str
    required_input_fields: list[str] = Field(default_factory=list)
    input_defaults: dict[str, JsonValue] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    permission_level: str = "medium"


class ToolChainMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.TOOL_CHAIN
    tool_results: list[ToolResultMetadata] = Field(default_factory=list)
    final_result: ToolResultMetadata | None = None


def artifact_to_tool_input(tool_name: str, artifact: Any) -> ToolInputMetadata:
    """Route a previous artifact into the next tool's input by metadata kind."""
    if isinstance(artifact, ToolResultMetadata):
        artifact = artifact.result
    if isinstance(artifact, CodeArtifactMetadata):
        code = artifact.code or artifact.content
        if tool_name in {"code_executor", "code_reviewer"}:
            return ToolInputMetadata(tool_name=tool_name, code=code, language=artifact.language)
        return ToolInputMetadata(tool_name=tool_name, content=code)
    if isinstance(artifact, FileArtifactMetadata):
        return ToolInputMetadata(tool_name=tool_name, file_path=artifact.file_path, content=artifact.content, text=artifact.content)
    if isinstance(artifact, TextArtifactMetadata):
        return ToolInputMetadata(tool_name=tool_name, content=artifact.content, text=artifact.content)
    if isinstance(artifact, CommandArtifactMetadata):
        return ToolInputMetadata(tool_name=tool_name, text=artifact.stdout or artifact.stderr)
    if isinstance(artifact, SearchArtifactMetadata):
        return ToolInputMetadata(tool_name=tool_name, text=artifact.research_summary)
    if isinstance(artifact, EmbeddingArtifactMetadata):
        return ToolInputMetadata(tool_name=tool_name, query=artifact.query)
    if isinstance(artifact, dict):
        if isinstance(artifact.get("code"), str):
            if tool_name in {"code_executor", "code_reviewer"}:
                return ToolInputMetadata(tool_name=tool_name, code=artifact.get("code"), language=artifact.get("language"))
            return ToolInputMetadata(
                tool_name=tool_name,
                content=artifact.get("code"),
            )
        if isinstance(artifact.get("content"), str):
            return ToolInputMetadata(tool_name=tool_name, content=artifact.get("content"), text=artifact.get("content"))
        return ToolInputMetadata.from_mapping(tool_name, artifact)
    return ToolInputMetadata(tool_name=tool_name, text=str(artifact) if artifact is not None else None)
