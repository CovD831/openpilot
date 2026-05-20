"""Tool-call selection models for execution."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator

from metadata import ToolInputMetadata


class SelectionReason(str, Enum):
    """Reason for tool selection."""
    CAPABILITY_MATCH = "capability_match"  # Tool has required capability
    BEST_PERFORMANCE = "best_performance"  # Best performance based on history
    ONLY_OPTION = "only_option"  # Only tool available
    USER_PREFERENCE = "user_preference"  # User prefers this tool
    FALLBACK = "fallback"  # Fallback option
    COST_OPTIMIZED = "cost_optimized"  # Most cost-effective option


class ToolSelection(BaseModel):
    """Selection of a tool for a specific step."""
    step_id: str = Field(..., description="ID of the execution step")
    tool_name: str = Field(..., description="Name of selected tool")

    # Selection metadata
    reason: SelectionReason = Field(..., description="Why this tool was selected")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in selection")

    # Input metadata
    input_metadata: ToolInputMetadata = Field(default_factory=ToolInputMetadata, description="Strict tool input metadata")

    # Execution control
    requires_confirmation: bool = Field(default=False, description="Whether user confirmation needed")
    timeout_override: Optional[int] = Field(default=None, description="Override default timeout")

    # Fallback options
    fallback_tools: list[str] = Field(default_factory=list, description="Alternative tools if this fails")

    # Dependencies
    depends_on: list[str] = Field(default_factory=list, description="Step IDs this depends on")

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_input_metadata(cls, data):
        if isinstance(data, dict) and isinstance(data.get("input_metadata"), dict):
            tool_name = str(data.get("tool_name") or "")
            data = dict(data)
            data["input_metadata"] = ToolInputMetadata.from_mapping(tool_name, data["input_metadata"])
        return data

    @model_validator(mode="after")
    def _attach_tool_name_to_input_metadata(self) -> "ToolSelection":
        if not self.input_metadata.tool_name:
            self.input_metadata.tool_name = self.tool_name
        return self


class ParallelExecutionGroup(BaseModel):
    """Group of tools that can execute in parallel."""
    group_id: str = Field(..., description="Unique group identifier")
    tool_selections: list[ToolSelection] = Field(..., description="Tools in this group")

    # Execution control
    wait_for_all: bool = Field(default=True, description="Wait for all to complete or just one")
    timeout_seconds: int = Field(default=60, description="Max time for group execution")

    # Error handling
    fail_fast: bool = Field(default=False, description="Stop all if one fails")
    min_success_count: int = Field(default=1, description="Minimum successful executions required")
