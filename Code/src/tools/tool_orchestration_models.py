"""Tool orchestration models for OpenPilot Phase 2."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class SelectionReason(str, Enum):
    """Reason for tool selection."""
    CAPABILITY_MATCH = "capability_match"  # Tool has required capability
    BEST_PERFORMANCE = "best_performance"  # Best performance based on history
    ONLY_OPTION = "only_option"  # Only tool available
    USER_PREFERENCE = "user_preference"  # User prefers this tool
    FALLBACK = "fallback"  # Fallback option
    COST_OPTIMIZED = "cost_optimized"  # Most cost-effective option


class ExecutionStrategy(str, Enum):
    """Execution strategy for tool."""
    SEQUENTIAL = "sequential"  # Execute one after another
    PARALLEL = "parallel"  # Execute in parallel
    CONDITIONAL = "conditional"  # Execute based on condition
    RETRY = "retry"  # Retry on failure


class ToolSelection(BaseModel):
    """Selection of a tool for a specific step."""
    step_id: str = Field(..., description="ID of the execution step")
    tool_name: str = Field(..., description="Name of selected tool")

    # Selection metadata
    reason: SelectionReason = Field(..., description="Why this tool was selected")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in selection")

    # Input parameters
    input_params: dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")

    # Execution control
    requires_confirmation: bool = Field(default=False, description="Whether user confirmation needed")
    timeout_override: Optional[int] = Field(default=None, description="Override default timeout")

    # Fallback options
    fallback_tools: list[str] = Field(default_factory=list, description="Alternative tools if this fails")

    # Dependencies
    depends_on: list[str] = Field(default_factory=list, description="Step IDs this depends on")

    model_config = ConfigDict(use_enum_values=True)


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


class FallbackStrategy(BaseModel):
    """Fallback strategy when primary tool fails."""
    primary_tool: str = Field(..., description="Primary tool name")
    fallback_sequence: list[str] = Field(..., description="Ordered list of fallback tools")

    # Conditions
    trigger_on_errors: list[str] = Field(
        default_factory=lambda: ["timeout", "permission_denied", "tool_error"],
        description="Error types that trigger fallback"
    )

    # Behavior
    max_attempts: int = Field(default=3, description="Max attempts across all fallbacks")
    backoff_seconds: int = Field(default=2, description="Delay between attempts")


class ToolOrchestrationPlan(BaseModel):
    """Complete plan for tool orchestration."""
    plan_id: str = Field(..., description="Unique plan identifier")
    goal: str = Field(..., description="High-level goal")

    # Tool selections
    tool_selections: list[ToolSelection] = Field(default_factory=list, description="All tool selections")
    parallel_groups: list[ParallelExecutionGroup] = Field(
        default_factory=list,
        description="Groups of tools that can run in parallel"
    )

    # Execution strategy
    execution_strategy: ExecutionStrategy = Field(
        default=ExecutionStrategy.SEQUENTIAL,
        description="Overall execution strategy"
    )

    # Fallback strategies
    fallback_strategies: dict[str, FallbackStrategy] = Field(
        default_factory=dict,
        description="Fallback strategies by tool name"
    )

    # Metadata
    estimated_duration_seconds: Optional[int] = Field(default=None, description="Estimated execution time")
    estimated_cost: Optional[float] = Field(default=None, description="Estimated cost (e.g., API calls)")
    risk_level: str = Field(default="medium", description="Overall risk level")

    # Learning
    based_on_memory: bool = Field(default=False, description="Whether plan uses historical data")
    memory_ids: list[str] = Field(default_factory=list, description="Memory records used")

    model_config = ConfigDict(use_enum_values=True)


class ToolMatchScore(BaseModel):
    """Score for how well a tool matches requirements."""
    tool_name: str
    capability_score: float = Field(ge=0.0, le=1.0, description="How well capabilities match")
    permission_score: float = Field(ge=0.0, le=1.0, description="Permission level appropriateness")
    performance_score: float = Field(ge=0.0, le=1.0, description="Historical performance")
    cost_score: float = Field(ge=0.0, le=1.0, description="Cost effectiveness")

    # Overall score (weighted average)
    total_score: float = Field(ge=0.0, le=1.0, description="Overall match score")

    # Metadata
    reasons: list[str] = Field(default_factory=list, description="Reasons for score")
    warnings: list[str] = Field(default_factory=list, description="Potential issues")


class OrchestrationContext(BaseModel):
    """Context for tool orchestration."""
    task_type: str = Field(..., description="Type of task")
    required_capabilities: list[str] = Field(default_factory=list, description="Required tool capabilities")

    # Constraints
    max_duration_seconds: Optional[int] = Field(default=None, description="Maximum allowed duration")
    max_cost: Optional[float] = Field(default=None, description="Maximum allowed cost")
    max_permission_level: Optional[str] = Field(default=None, description="Maximum permission level")

    # Preferences
    prefer_parallel: bool = Field(default=True, description="Prefer parallel execution when possible")
    prefer_cached: bool = Field(default=True, description="Prefer tools with cached results")

    # Memory
    use_memory: bool = Field(default=True, description="Use historical data for selection")
    memory_query_results: Optional[dict] = Field(default=None, description="Retrieved memory data")

    # Autonomy
    autonomy_level: Optional[str] = Field(default=None, description="Current autonomy level")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Min confidence for auto-execution")


class OrchestrationResult(BaseModel):
    """Result of orchestration planning."""
    success: bool
    plan: Optional[ToolOrchestrationPlan] = None
    error: Optional[str] = None

    # Metadata
    planning_time_ms: int
    tools_considered: int
    alternatives_generated: int

    # Recommendations
    recommendations: list[str] = Field(default_factory=list, description="Suggestions for user")
    warnings: list[str] = Field(default_factory=list, description="Potential issues")
