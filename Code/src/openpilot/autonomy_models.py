"""
Autonomy decision models for OP-19.

Defines data structures for autonomy level decisions, confidence scoring,
and user preference tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AutonomyLevel(str, Enum):
    """Autonomy level for task execution."""
    MANUAL_REQUIRED = "manual_required"
    CONFIRM_EACH_TIME = "confirm_each_time"
    NOTIFY_THEN_RUN = "notify_then_run"
    AUTO_RUN_LOW_RISK = "auto_run_low_risk"


class AutonomyDecision(BaseModel):
    """Decision about whether and how to execute a step autonomously."""
    step_id: str = Field(description="ID of the step being evaluated")
    should_ask_user: bool = Field(description="Whether user input is needed")
    autonomy_level: AutonomyLevel = Field(description="Recommended autonomy level")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score (0-1)")
    preference_basis: list[str] = Field(
        default_factory=list,
        description="Memory IDs or preference keys that informed this decision"
    )
    decision_reason: str = Field(description="Why this autonomy level was chosen")
    intervention_reason: str | None = Field(
        default=None,
        description="Why user intervention is needed (if should_ask_user=true)"
    )
    requires_user_input: bool = Field(
        default=False,
        description="Whether this step requires user-provided information"
    )


class PreferenceSignal(BaseModel):
    """A signal indicating user preference from past behavior."""
    preference_key: str = Field(description="Unique key for this preference type")
    preference_value: Any = Field(description="The preferred value or choice")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context in which this preference applies"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this preference")
    usage_count: int = Field(default=1, description="Number of times this preference was observed")
    success_count: int = Field(default=0, description="Number of times this preference led to success")
    last_used: str = Field(description="ISO 8601 timestamp of last use")
    created_at: str = Field(description="ISO 8601 timestamp of creation")


class AutonomyProfile(BaseModel):
    """System-wide autonomy configuration based on learned preferences."""
    task_type_autonomy: dict[str, AutonomyLevel] = Field(
        default_factory=dict,
        description="Default autonomy level by task type"
    )
    tool_type_autonomy: dict[str, AutonomyLevel] = Field(
        default_factory=dict,
        description="Default autonomy level by tool type"
    )
    risk_level_autonomy: dict[str, AutonomyLevel] = Field(
        default_factory=dict,
        description="Default autonomy level by risk level"
    )
    preference_signals: list[PreferenceSignal] = Field(
        default_factory=list,
        description="Learned user preferences"
    )
    global_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for autonomous execution"
    )
    last_updated: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of last profile update"
    )


class UserFeedback(BaseModel):
    """User feedback on an autonomy decision or execution result."""
    step_id: str = Field(description="ID of the step that was executed")
    decision_id: str | None = Field(default=None, description="ID of the autonomy decision")
    feedback_type: str = Field(
        description="Type of feedback: accepted, rejected, modified, failed, blocked"
    )
    feedback_reason: str | None = Field(
        default=None,
        description="User's reason for the feedback"
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context about the feedback"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp"
    )


class ConfidenceFactors(BaseModel):
    """Factors contributing to confidence calculation."""
    historical_success_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Success rate of similar tasks"
    )
    preference_match_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How well this matches user preferences"
    )
    risk_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Penalty based on risk level (0=no penalty, 1=max penalty)"
    )
    recency_bonus: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Bonus for recent similar successes"
    )
    usage_frequency_bonus: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Bonus for frequently used patterns"
    )
    final_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Final calculated confidence"
    )
