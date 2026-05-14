"""Tool models for OpenPilot Phase 2."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class PermissionLevel(str, Enum):
    """Tool permission levels."""
    AUTO = "auto"  # Can run automatically without confirmation
    LOW = "low"  # Low risk, can run with notification
    MEDIUM = "medium"  # Medium risk, requires confirmation in most cases
    HIGH = "high"  # High risk, always requires confirmation
    FORBIDDEN = "forbidden"  # Never allowed to run


class ToolCapability(str, Enum):
    """Tool capability categories."""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    LLM_CALL = "llm_call"
    WEB_SEARCH = "web_search"
    WEB_REQUEST = "web_request"
    CODE_EXECUTION = "code_execution"
    SHELL_EXECUTION = "shell_execution"
    EMAIL = "email"
    CALENDAR = "calendar"
    DATABASE = "database"
    NETWORK = "network"


class ToolInputSchema(BaseModel):
    """Schema for tool input parameters."""
    name: str
    type: str  # "string", "integer", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Optional[Any] = None


class ToolOutputSchema(BaseModel):
    """Schema for tool output."""
    type: str  # "string", "object", "array", etc.
    description: str
    properties: Optional[dict[str, Any]] = None


class ToolFailureMode(BaseModel):
    """Describes how a tool can fail."""
    error_type: str  # "timeout", "permission_denied", "not_found", "invalid_input", etc.
    description: str
    recovery_strategy: Optional[str] = None


class ToolDependency(BaseModel):
    """Tool dependency specification."""
    name: str
    type: str  # "tool", "library", "service", "environment"
    required: bool = True
    version: Optional[str] = None


class ToolDefinition(BaseModel):
    """Complete tool definition."""
    name: str = Field(..., description="Unique tool identifier")
    display_name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="What this tool does")
    version: str = Field(default="1.0.0", description="Tool version")

    # Capabilities and permissions
    capabilities: list[ToolCapability] = Field(default_factory=list)
    permission_level: PermissionLevel = Field(default=PermissionLevel.MEDIUM)

    # Input/Output
    input_schema: list[ToolInputSchema] = Field(default_factory=list)
    output_schema: ToolOutputSchema

    # Execution constraints
    timeout_seconds: int = Field(default=30, description="Max execution time")
    max_retries: int = Field(default=2, description="Max retry attempts on failure")

    # Dependencies and failure modes
    dependencies: list[ToolDependency] = Field(default_factory=list)
    failure_modes: list[ToolFailureMode] = Field(default_factory=list)

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    author: Optional[str] = None
    audit_required: bool = Field(default=True, description="Whether to log all executions")

    model_config = ConfigDict(use_enum_values=True)


class ToolExecutionContext(BaseModel):
    """Context for tool execution."""
    tool_name: str
    input_params: dict[str, Any]
    user_confirmed: bool = False
    autonomy_level: Optional[str] = None
    confidence: Optional[float] = None
    execution_id: Optional[str] = None


class ToolExecutionResult(BaseModel):
    """Result of tool execution."""
    tool_name: str
    execution_id: str
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: int
    retries: int = 0

    # Resource usage
    memory_mb: Optional[float] = None
    api_calls: int = 0

    # Metadata
    timestamp: str
    logs: list[str] = Field(default_factory=list)
